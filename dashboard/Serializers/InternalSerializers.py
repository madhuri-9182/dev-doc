import datetime
from rest_framework import serializers
from organizations.utils import create_organization
from organizations.models import Organization
from celery import group
from django.conf import settings
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from phonenumber_field.serializerfields import PhoneNumberField
from core.models import User, Role
from ..models import (
    InternalClient,
    ClientPointOfContact,
    InternalInterviewer,
    ClientUser,
    Agreement,
    HDIPUsers,
    DesignationDomain,
)
from hiringdogbackend.utils import (
    validate_incoming_data,
    get_random_password,
    is_valid_gstin,
    is_valid_pan,
    get_boolean,
    check_for_email_and_phone_uniqueness,
)
from ..tasks import send_mail, send_email_to_multiple_recipients

ONBOARD_EMAIL_TEMPLATE = "onboard.html"
WELCOME_MAIL_SUBJECT = "Welcome to Hiring Dog"
CONTACT_EMAIL = settings.EMAIL_HOST_USER if settings.DEBUG else settings.CONTACT_EMAIL
INTERVIEW_EMAIL = (
    settings.EMAIL_HOST_USER if settings.DEBUG else settings.INTERVIEW_EMAIL
)
CHANGE_EMAIL_NOTIFICATION_TEMPLATE = "user_email_changed_confirmation_notification.html"


class InternalClientDomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternalClient
        fields = ("id", "name", "domain")


class ClientPointOfContactSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format="%d/%m/%Y", read_only=True)
    poc_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = ClientPointOfContact
        fields = ["id", "poc_id", "name", "email", "phone", "created_at"]
        read_only_fields = ["created_at"]

    def run_validation(self, data=...):
        email = data.get("email")
        phone = data.get("phone")

        errors = check_for_email_and_phone_uniqueness(email, phone, User)
        if errors:
            raise serializers.ValidationError({"errors": errors})

        return super().run_validation(data)

    def validate(self, data):
        errors = validate_incoming_data(
            data,
            ["name", "email", "phone"],
            ["poc_id"],
            partial=self.partial,
        )
        if errors:
            raise serializers.ValidationError({"errors": errors})
        return data


class HDIPUserForInterClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = HDIPUsers
        fields = ("id", "name")


class InternalClientStatSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(max_length=155)
    active_jobs = serializers.IntegerField()
    passive_jobs = serializers.IntegerField()
    total_candidates = serializers.IntegerField()


class InternalClientSerializer(serializers.ModelSerializer):
    onboarded_at = serializers.DateTimeField(
        source="created_at", format="%d/%m/%Y", read_only=True
    )
    points_of_contact = ClientPointOfContactSerializer(many=True)
    assigned_to = HDIPUserForInterClientSerializer(read_only=True)

    class Meta:
        model = InternalClient
        fields = (
            "id",
            "name",
            "brand_name",
            "website",
            "domain",
            "gstin",
            "pan",
            "code",
            "is_signed",
            "assigned_to",
            "address",
            "client_level",
            "initial_free_interviews_allocation",
            "points_of_contact",
            "onboarded_at",
        )

    def to_internal_value(self, data):

        points_of_contact = data.get("points_of_contact")
        errors = {}
        if not points_of_contact:
            errors.setdefault("points_of_contact", []).append(
                "This field is required and must contain list of objects."
            )

        if not isinstance(points_of_contact, list):
            errors.setdefault("points_of_contact", []).append(
                "This field must be a list of objects."
            )

        if points_of_contact and len(points_of_contact) > 3:
            errors.setdefault("points_of_contact", []).append(
                "A maximum of 3 points of contact are allowed."
            )

        assigned_to = data.get("assigned_to")
        if assigned_to is None:
            errors.setdefault("assigned_to", []).append(
                "assigned_to is a required field."
            )
        elif (
            not isinstance(assigned_to, int)
            or not HDIPUsers.objects.filter(pk=assigned_to).exists()
        ):
            errors.setdefault("assigned_to", []).append("Invalid assigned to value.")

        if errors:
            raise serializers.ValidationError(errors)

        contact_ids = []
        for i, contact in enumerate(points_of_contact):
            if contact.get("poc_id"):
                contact["email"] = ""
                contact["phone"] = ""
                contact_ids.append(contact.get("poc_id"))
            serializer = ClientPointOfContactSerializer(data=contact)
            if not serializer.is_valid():
                errors[f"{i + 1}"] = (
                    serializer.errors["errors"]
                    if "errors" in serializer.errors
                    else serializer.errors
                )

        if errors:
            raise serializers.ValidationError(errors)

        self.context["contact_ids"] = contact_ids
        self.context["assigned_to"] = assigned_to

        return super().to_internal_value(data)

    def run_validation(self, data=...):
        if data.get("is_signed"):
            data["is_signed"] = get_boolean(data, "is_signed")
        return super().run_validation(data)

    def validate(self, data):
        errors = validate_incoming_data(
            self.initial_data,
            [
                "name",
                "brand_name",
                "website",
                "domain",
                "gstin",
                "pan",
                "code",
                "is_signed",
                "assigned_to",
                "address",
                "client_level",
                "points_of_contact",
            ],
            [
                "initial_free_interviews_allocation",
            ],
            partial=self.partial,
        )
        if errors:
            raise serializers.ValidationError({"errors": errors})

        if data.get("gstin") and not is_valid_gstin(data.get("gstin")):
            errors.setdefault("gstin", []).append("Invalid gstin.")

        if data.get("pan") and not is_valid_pan(data.get("pan")):
            errors.setdefault("pan", []).append("Invalid PAN.")

        client_level = data.get("client_level")
        if client_level is not None and not 0 < client_level < 4:
            errors.setdefault("client_level", []).append("Invalid client_level value")

        code = data.get("code")
        if not settings.CURRENCIES.get(code):
            errors.setdefault("code", []).append("Invalid code")

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def create(self, validated_data):
        request = self.context.get("request")
        points_of_contact_data = validated_data.pop("points_of_contact")
        organization_name = validated_data.get("name")
        assigned_to = self.context["assigned_to"]

        with transaction.atomic():
            organization = None
            client_user_objs = []
            points_of_contact_objs = []

            for index, point_of_contact in enumerate(points_of_contact_data):
                email = point_of_contact.get("email")
                name_ = point_of_contact.get("name")
                password = get_random_password()

                role = Role.CLIENT_OWNER if index == 0 else Role.CLIENT_ADMIN
                user = User.objects.create_user(
                    email,
                    point_of_contact.get("phone"),
                    password,
                    role=role,
                )

                if index == 0:
                    organization = create_organization(
                        user, organization_name, is_active=False
                    )

                    agreement_rates = [
                        {"years_of_experience": "0-4", "rate": 2300},
                        {"years_of_experience": "4-6", "rate": 2800},
                        {"years_of_experience": "6-8", "rate": 3300},
                        {"years_of_experience": "8-10", "rate": 3500},
                        {"years_of_experience": "10+", "rate": 4000},
                    ]

                    agreements = [
                        Agreement(organization=organization, **agreement_rate)
                        for agreement_rate in agreement_rates
                    ]
                    Agreement.objects.bulk_create(agreements)
                """ 
                else:
                    # Not using OrganizationUser for now, instead UserProfile works as a organization user
                    # because it has a foreign key with organization
                    OrganizationUser.objects.create(
                        organization=organization, user=user
                    )
                """

                points_of_contact_objs.append(
                    ClientPointOfContact(client=None, **point_of_contact)
                )
                client_user_objs.append(
                    ClientUser(organization=organization, user=user, name=name_)
                )
                user.profile.name = name_
                user.profile.organization = organization
                user.profile.save()

                point_of_contact["temporary_password"] = password

            client = InternalClient.objects.create(
                organization=organization, assigned_to_id=assigned_to, **validated_data
            )

            for poc in points_of_contact_objs:
                poc.client = client

            ClientPointOfContact.objects.bulk_create(points_of_contact_objs)
            ClientUser.objects.bulk_create(client_user_objs)

            send_mail_to_poc_and_internal = group(
                *(
                    [
                        send_mail.si(
                            to=point_of_contact["email"],
                            subject=WELCOME_MAIL_SUBJECT,
                            template=ONBOARD_EMAIL_TEMPLATE,
                            user_name=point_of_contact["name"],
                            password=point_of_contact["temporary_password"],
                            login_url=settings.LOGIN_URL,
                            org_name=organization_name,
                        )
                        for point_of_contact in points_of_contact_data
                    ]
                    + [
                        send_mail.si(
                            to=request.user.email,
                            subject=f"{organization.name} Client Onboarded Successfully.",
                            template="internal_client_onboarding_confirmation.html",
                            internal_user_name=getattr(
                                getattr(request.user, "hdipuser", None),
                                "name",
                                request.user.email,
                            ),
                            client_name=organization.name,
                            onboarding_date=datetime.date.today().strftime("%d/%m/%Y"),
                        )
                    ]
                )
            )

            # Queue the email sending after the transaction is committed
            transaction.on_commit(lambda: send_mail_to_poc_and_internal.apply_async())

        return client

    def update(self, instance, validated_data):
        point_of_contact_data = validated_data.pop("points_of_contact")

        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()

        existing_contacts = ClientPointOfContact.objects.filter(client=instance)
        existing_contacts_dict = {contact.id: contact for contact in existing_contacts}
        contact_ids = self.context.get("contact_ids")

        to_archive = existing_contacts.exclude(id__in=contact_ids)
        for contact in to_archive:
            suffix = f".deleted.{contact.id}-{contact.client.organization.id}"
            user = User.objects.filter(email=contact.email).first()
            if user:
                user.is_active = False
                user.email += suffix
                user.phone = str(user.phone) + suffix
                if hasattr(user, "clientuser"):
                    user.clientuser.archived = True
                    user.clientuser.save()
                user.save()
            contact.archived = True
            contact.email += suffix
            contact.phone = str(contact.phone) + suffix
            contact.save()

        for index, point_of_contact in enumerate(point_of_contact_data):
            # contact_id = contact_ids[index] if index < len(contact_ids) else None
            # log_action(
            #     f"Index {index}, contact_id {contact_id}, contact_ids {contact_ids}, point_of_contact {point_of_contact}, existing_contacts_dict {existing_contacts_dict}",
            #     level=logging.DEBUG,
            # )

            """--> keep it for future reference.
            if not contact_id and len(existing_contacts_dict) >= 3:
                raise serializers.ValidationError(
                    {
                        "errors": {
                            "points_of_contact": [
                                "Maximum 3 points of contact are allowed"
                            ]
                        }
                    }
                )
            """

            if point_of_contact.get("poc_id"):
                contact = existing_contacts_dict.get(point_of_contact["poc_id"])
                if not contact:
                    continue
                point_of_contact.pop("email", None)
                point_of_contact.pop("phone", None)
                for key, value in point_of_contact.items():
                    setattr(contact, key, value)
                    setattr(contact.client.organization.internal_client, key, value)
                contact.save()
            else:
                email = point_of_contact.get("email")
                name = point_of_contact.get("name")
                password = get_random_password()
                user = User.objects.create_user(
                    email,
                    point_of_contact.get("phone"),
                    password,
                    role=Role.CLIENT_ADMIN,
                )
                send_mail.delay(
                    to=email,
                    subject=WELCOME_MAIL_SUBJECT,
                    template=ONBOARD_EMAIL_TEMPLATE,
                    user_name=name,
                    password=password,
                    login_url=settings.LOGIN_URL,
                    org_name=instance.name,
                )
                user.profile.name = name
                user.profile.save()
                ClientPointOfContact.objects.create(client=instance, **point_of_contact)
                ClientUser.objects.create(
                    organization=instance.organization, user=user, name=name
                )

        return instance


class DesignationDomainSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = DesignationDomain
        fields = ("id", "name", "full_name")

    def get_full_name(self, obj):
        role_choice = dict(InternalInterviewer.ROLE_CHOICES)
        return role_choice.get(obj.name)


def validate_social_links(value):
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(val, str) and val.startswith("http")
        for key, val in value.items()
    ):
        raise serializers.ValidationError(
            "Invalid social links format. It should be a dictionary with string keys and HTTP URLs values."
        )


class InterviewerSerializer(serializers.ModelSerializer):
    strength = serializers.ChoiceField(
        choices=InternalInterviewer.STRENGTH_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in InternalInterviewer.STRENGTH_CHOICES])}"
        },
        required=False,
    )
    assigned_domains = DesignationDomainSerializer(many=True, read_only=True)
    assigned_domain_ids = serializers.CharField(
        max_length=100,
        required=False,
        write_only=True,
    )
    social_links = serializers.JSONField(
        validators=[validate_social_links], required=False
    )

    class Meta:
        model = InternalInterviewer
        fields = (
            "id",
            "name",
            "email",
            "phone_number",
            "current_company",
            "previous_company",
            "current_designation",
            "total_experience_years",
            "total_experience_months",
            "interview_experience_years",
            "interview_experience_months",
            "assigned_domains",
            "assigned_domain_ids",
            "skills",
            "strength",
            "interviewer_level",
            "cv",
            "account_number",
            "ifsc_code",
            "social_links",
        )

    def run_validation(self, data=...):
        email = data.get("email")
        phone = data.get("phone_number")
        errors = check_for_email_and_phone_uniqueness(email, phone, User)
        if errors:
            raise serializers.ValidationError({"errors": errors})
        return super().run_validation(data)

    def validate(self, data):
        # Ensure total experience is logical
        errors = validate_incoming_data(
            self.initial_data,
            required_keys=[
                "name",
                "email",
                "phone_number",
                "current_company",
                "previous_company",
                "current_designation",
                "total_experience_years",
                "total_experience_months",
                "interview_experience_years",
                "interview_experience_months",
                "assigned_domain_ids",
                "skills",
                "strength",
                "interviewer_level",
            ],
            allowed_keys=["account_number", "ifsc_code", "social_links", "cv"],
            partial=self.partial,
            original_data=data,
            form=True,
        )
        if errors:
            raise serializers.ValidationError({"errors": errors})
        for key in ["total_experience_years", "interview_experience_years"]:
            if key in data and not 1 <= data[key] <= 50:
                errors.setdefault(key, []).append("Invalid Experience")
        for key in ["total_experience_months", "interview_experience_months"]:
            if key in data and not 0 <= data[key] <= 12:
                errors.setdefault(key, []).append("Invalid Experience")
        if (
            "total_experience_years" in data
            and "interview_experience_years" in data
            and data["total_experience_years"] < data["interview_experience_years"]
        ):
            errors.setdefault("years", []).append(
                "Total experience must be greater than interview experience."
            )

        if "assigned_domain_ids" in data and isinstance(
            data["assigned_domain_ids"], str
        ):
            try:
                data["assigned_domain_ids"] = list(
                    map(int, data["assigned_domain_ids"].split(","))
                )
            except ValueError:
                raise serializers.ValidationError(
                    {
                        "assigned_domain_ids": [
                            "Assigned domain IDs must be comma-separated and consist of valid IDs."
                        ]
                    }
                )

        assigned_domain_ids = set(data.get("assigned_domain_ids", []))
        existing_domain_ids = set(
            DesignationDomain.objects.values_list("id", flat=True)
        )
        invalid_domain_ids = assigned_domain_ids - existing_domain_ids
        if invalid_domain_ids:
            errors.setdefault("assigned_domain_ids", []).append(
                f"Invalid domain IDs: {', '.join(map(str, invalid_domain_ids))}"
            )

        interviewer_level = data.get("interviewer_level")
        if interviewer_level is not None and not 0 < interviewer_level < 4:
            errors.setdefault("interviewer_level", []).append(
                "Invalid interviewer_level value."
            )

        if errors:
            raise serializers.ValidationError({"errors": errors})
        return data

    def create(self, validated_data):
        email = validated_data.get("email")
        phone = validated_data.get("phone_number")
        name = validated_data.get("name")
        domain_ids = validated_data.pop("assigned_domain_ids", [])
        password = get_random_password()
        with transaction.atomic():
            user = User.objects.create_user(
                email,
                phone,
                password,
                role=Role.INTERVIEWER,
            )
            interviewer_obj = InternalInterviewer.objects.create(
                user=user, **validated_data
            )
            interviewer_obj.assigned_domains.add(*domain_ids)
            verification_data = (
                f"{user.id}:{int(datetime.datetime.now().timestamp() + 86400)}"
            )
            verification_data_uid = urlsafe_base64_encode(
                force_bytes(verification_data)
            )
            contexts = [
                {
                    "subject": WELCOME_MAIL_SUBJECT,
                    "from_email": INTERVIEW_EMAIL,
                    "email": email,
                    "template": ONBOARD_EMAIL_TEMPLATE,
                    "user_name": name,
                    "password": password,
                    "login_url": settings.LOGIN_URL,
                    "site_domain": settings.SITE_DOMAIN,
                    "verification_link": f"/verification/{verification_data_uid}/",
                },
                {
                    "subject": f"Confirmation: {interviewer_obj.name} Successfully Onboarded as Interviewer",
                    "from_email": INTERVIEW_EMAIL,
                    "email": CONTACT_EMAIL,
                    "template": "internal_interviewer_onboarded_confirmation_notification.html",
                    "internal_user_name": "Admin",
                    "interviewer_name": interviewer_obj.name,
                    "onboarding_date": datetime.date.today().strftime("%d/%m/%Y"),
                },
            ]
            send_email_to_multiple_recipients.delay(contexts, "", "")
            user.profile.name = name
            user.profile.save()
        return interviewer_obj

    def update(self, instance, validated_data):
        email = validated_data.get("email", instance.email)
        phone = validated_data.get("phone_number", instance.phone_number)
        assigned_domain_ids = set(validated_data.get("assigned_domain_ids", []))
        current_email = instance.email

        with transaction.atomic():
            changes = {}

            if instance.email != email:
                instance.user.email = email
                changes["email"] = email

            if instance.phone_number != phone:
                instance.user.phone = phone
                changes["phone"] = phone

            if changes:
                instance.user.save(update_fields=["email", "phone"])

            instance.assigned_domains.set(assigned_domain_ids)
            instance = super().update(instance, validated_data)

            if "email" in changes:
                send_mail.delay(
                    to=current_email,
                    template=CHANGE_EMAIL_NOTIFICATION_TEMPLATE,
                    subject=f"{instance.name} - Your Email is updated",
                    name=instance.name,
                    new_email=instance.email,
                )

        return instance


class AgreementSerializer(serializers.ModelSerializer):
    agreement_id = serializers.IntegerField(
        write_only=True, min_value=1, required=False
    )
    years_of_experience = serializers.ChoiceField(
        choices=Agreement.YEARS_OF_EXPERIENCE_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Agreement.YEARS_OF_EXPERIENCE_CHOICES])}"
        },
        required=False,
    )

    class Meta:
        model = Agreement
        fields = [
            "id",
            "years_of_experience",
            "rate",
            "agreement_id",
        ]

    def validate(self, data):
        errors = validate_incoming_data(
            data.keys(),
            required_keys=[
                "years_of_experience",
                "rate",
            ],
            allowed_keys=["agreement_id"],
            partial=self.partial,
        )

        if "rate" in data and data["rate"] <= 0:
            errors.setdefault("rate", []).append("Rate must be a positive value.")

        if errors:
            raise serializers.ValidationError({"errors": errors})

        return data


class OrganizationAgreementSerializer(serializers.ModelSerializer):
    agreements = AgreementSerializer(required=False, many=True)
    organization_id = serializers.IntegerField(
        write_only=True, required=False, min_value=1
    )

    class Meta:
        model = Organization
        fields = ("id", "name", "agreements", "organization_id")
        read_only_fields = ("name",)

    def to_internal_value(self, data):
        agreements = data.get("agreements")
        errors = {}
        if not agreements:
            errors.setdefault("agreements", []).append(
                "This field is required and must contain list of objects."
            )

        if not isinstance(agreements, list):
            errors.setdefault("agreements", []).append(
                "This field must be a list of objects."
            )

        if errors:
            raise serializers.ValidationError(errors)

        agreement_ids = []
        for i, agreeemnt in enumerate(agreements):
            if agreeemnt.get("id"):
                agreement_ids.append(agreeemnt.get("id"))
            serializer = AgreementSerializer(data=agreeemnt)
            if not serializer.is_valid():
                errors[f"{i + 1}"] = serializer.errors or serializer.errors["errors"]

        if errors:
            raise serializers.ValidationError(errors)

        self.context["agreement_ids"] = agreement_ids
        return super().to_internal_value(data)

    def validate(self, data):
        if self.partial:
            required_keys = ["agreements"]
        else:
            required_keys = ["organization_id", "agreements"]

        errors = validate_incoming_data(
            self.initial_data,
            required_keys=required_keys,
            partial=self.partial,
        )

        if organization_id := data.pop("organization_id", None):
            organization = Organization.objects.filter(id=organization_id).first()
            if not organization:
                errors.setdefault("organization_id", []).append(
                    "Invalid organization_id"
                )
            elif (
                not self.partial
                and Agreement.objects.filter(organization_id=organization_id).exists()
            ):
                errors.setdefault("organization_id", []).append(
                    "Organization agreement already existed"
                )
            if not self.instance:
                data["organization"] = organization

        if self.partial and "agreements" in data:
            existing_agreement_years = set(
                Agreement.objects.values_list("years_of_experience", flat=True)
            )
            incoming_agreement_years = {
                agreement.get("years_of_experience")
                for agreement in data.get("agreements")
                if "agreement_id" not in agreement
            }
            common_years = existing_agreement_years & incoming_agreement_years
            if common_years:
                error_message = f"Agreement with years_of_experience {', '.join(map(str, common_years))} already existed. Please update it by providing it's id"
                for i, agreement in enumerate(data.get("agreements")):
                    if agreement.get("years_of_experience") in common_years:
                        errors.setdefault(f"{i}", []).append(error_message)

        if errors:
            raise serializers.ValidationError({"errors": errors})

        return data

    def create(self, validated_data):
        agreements_info = validated_data.pop("agreements")
        organization = validated_data.get("organization")
        agreements = [
            Agreement(**agreement, organization=organization)
            for agreement in agreements_info
        ]
        Agreement.objects.bulk_create(agreements)
        return organization

    def update(self, instance, validated_data):
        agreements_info = validated_data.pop("agreements", None)
        if agreements_info:
            agreements_dict = {
                agreement["agreement_id"]: agreement
                for agreement in agreements_info
                if "agreement_id" in agreement
            }
            existing_agreements = {
                agreement.id: agreement
                for agreement in Agreement.objects.filter(
                    organization=instance, id__in=agreements_dict.keys()
                )
            }

            # Update existing agreements
            for agreement_id, agreement in existing_agreements.items():
                agreement_info = agreements_dict.pop(agreement_id, None)
                if agreement_info:
                    for attr, value in agreement_info.items():
                        setattr(agreement, attr, value)
                    agreement.save()

            # Create new agreements
            new_agreements = [
                Agreement(**agreement, organization=instance)
                for agreement in agreements_info
                if "agreement_id" not in agreement
            ]
            Agreement.objects.bulk_create(new_agreements)

        return instance


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = (
            "id",
            "name",
        )


class UserInternalSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "phone", "role")


class ClientUserInternalSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternalClient
        fields = ("id", "name", "domain")


class InternalClientUserSerializer(serializers.ModelSerializer):

    email = serializers.EmailField(write_only=True, required=False)
    phone = PhoneNumberField(write_only=True, required=False)
    client = ClientUserInternalSerializer(
        source="organization.internal_client", read_only=True
    )
    user = UserInternalSerializer(read_only=True)
    internal_client_id = serializers.IntegerField(write_only=True, required=False)
    role = serializers.ChoiceField(
        choices=[
            ("client_user", "Client User"),
            ("client_admin", "Client Admin"),
        ],
        error_messages={
            "invalid_choice": (
                "This is an invalid choice. Valid choices are "
                "client_user(Client User), client_admin(Client Admin), "
            )
        },
        required=False,
    )
    accessibility = serializers.ChoiceField(
        choices=ClientUser.ACCESSIBILITY_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in ClientUser.ACCESSIBILITY_CHOICES])}"
        },
        required=False,
    )

    class Meta:
        model = ClientUser
        fields = [
            "id",
            "internal_client_id",
            "client",
            "user",
            "email",
            "phone",
            "name",
            "role",
            "accessibility",
        ]

    def run_validation(self, data):
        email = data.get("email")
        phone = data.get("phone")

        errors = check_for_email_and_phone_uniqueness(email, phone, User)
        if errors:
            raise serializers.ValidationError({"errors": errors})

        return super().run_validation(data)

    def validate(self, data):
        required_keys = [
            "email",
            "phone",
            "role",
            "accessibility",
            "internal_client_id",
            "name",
        ]
        allowed_keys = []
        if self.partial:
            required_keys = []
            allowed_keys = ["role", "accessibility", "name", "email", "phone"]
        errors = validate_incoming_data(
            self.initial_data,
            required_keys=required_keys,
            allowed_keys=allowed_keys,
            partial=self.partial,
        )

        internal_client_id = data.pop("internal_client_id", None)
        if internal_client_id:
            internal_client = InternalClient.objects.filter(
                pk=internal_client_id
            ).first()
            if not internal_client:
                errors.setdefault("internal_client_id", []).append(
                    "Invalid internal_client_id"
                )
            self.context["internal_client"] = internal_client

        if errors:
            raise serializers.ValidationError({"errors": errors})

        return data

    def create(self, validated_data):
        email = validated_data.pop("email")
        phone = validated_data.pop("phone")
        role = validated_data.pop("role")
        internal_client = self.context["internal_client"]
        request = self.context["request"]
        password = get_random_password()

        with transaction.atomic():
            user = User.objects.create_user(email, phone, password, role=role)
            user.profile.name = validated_data.get("name")
            user.profile.save()
            validated_data["user"] = user
            validated_data["organization"] = internal_client.organization
            validated_data["invited_by"] = request.user
            client_user = super().create(validated_data)

            send_mail.delay(
                to=email,
                subject=WELCOME_MAIL_SUBJECT,
                template=ONBOARD_EMAIL_TEMPLATE,
                user_name=validated_data.get("name"),
                password=password,
                login_url=settings.LOGIN_URL,
                org_name=internal_client.organization.name,
            )
        return client_user

    def update(self, instance, validated_data):
        new_email = validated_data.pop("email", None)
        new_phone = validated_data.pop("phone", None)
        new_role = validated_data.pop("role", None)
        current_email = instance.user.email

        with transaction.atomic():

            internal_client = instance.organization.internal_client
            poc = ClientPointOfContact.objects.filter(
                client=internal_client, email=current_email
            ).first()

            if new_role:
                instance.user.role = new_role

            if "name" in validated_data:
                instance.user.profile.name = validated_data["name"]
                instance.user.profile.save()
                if poc:
                    poc.name = validated_data["name"]

            if new_email:
                instance.user.email = new_email
                if poc:
                    poc.email = new_email

            if new_phone:
                instance.user.phone = new_phone
                if poc:
                    poc.phone = new_phone

            instance.user.save()
            if poc:
                poc.save()

            instance = super().update(instance, validated_data)
            if new_email and current_email != new_email:
                send_mail.delay(
                    to=current_email,
                    subject=f"{instance.name}, Your Email Is Updated",
                    template=CHANGE_EMAIL_NOTIFICATION_TEMPLATE,
                    name=instance.name,
                    new_email=instance.user.email,
                )

        return instance


class HDIPUsersSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(
        choices=[("moderator", "Moderator"), ("admin", "Admin")],
        error_messages={
            "invalid_choice": (
                "This is an invalid choice. Valid choices are "
                "moderator(Moderator), admin(Admin)"
            )
        },
        required=False,
    )
    email = serializers.EmailField(write_only=True, required=False)
    phone = PhoneNumberField(write_only=True, required=False)
    client_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        write_only=True,
        required=False,
    )
    user = UserInternalSerializer(read_only=True)
    client = ClientUserInternalSerializer(
        source="internalclients", many=True, read_only=True
    )

    class Meta:
        model = HDIPUsers
        fields = [
            "id",
            "name",
            "user",
            "client",
            "role",
            "email",
            "phone",
            "client_ids",
        ]

    def run_validation(self, data):
        email = data.get("email")
        phone = data.get("phone")

        errors = check_for_email_and_phone_uniqueness(email, phone, User)
        if errors:
            raise serializers.ValidationError({"errors": errors})

        return super().run_validation(data)

    """ keeping this for future update 
    def validate_client_ids(self, value):
        request_method = self.context["request"].method
        if request_method == "POST" and len(value) < 1:
            raise serializers.ValidationError(
                "This field must have at least 1 item for POST requests."
            )
        return value
    """

    def validate(self, data):
        required_keys = ["name", "email", "phone", "role"]
        allowed_keys = ["client_ids"]
        if self.partial:
            required_keys = []
            allowed_keys.extend(["role", "name", "email", "phone"])

        errors = validate_incoming_data(
            self.initial_data,
            required_keys=required_keys,
            allowed_keys=allowed_keys,
            partial=self.partial,
        )

        client_ids = data.get("client_ids")
        if client_ids:
            existing_client_ids = set(
                InternalClient.objects.filter(pk__in=client_ids).values_list(
                    "id", flat=True
                )
            )
            already_assign_client_ids = set(
                HDIPUsers.objects.filter(internalclients__in=client_ids).values_list(
                    "internalclients", flat=True
                )
            )
            if self.partial:
                already_assign_client_ids -= set(
                    self.instance.internalclients.values_list("id", flat=True)
                )
            if not existing_client_ids:
                errors.setdefault("client_ids", []).append("Invalid client ids")
            elif already_assign_client_ids & existing_client_ids:
                errors.setdefault("client_ids", []).append(
                    f"These client ids are {', '.join(map(str, already_assign_client_ids & existing_client_ids))} already assigned to others."
                )
            else:
                invalid_ids = set(client_ids) - existing_client_ids
                if invalid_ids:
                    errors.setdefault("client_ids", []).append(
                        f"Invalid client ids: {', '.join(map(str, invalid_ids))}"
                    )

        if errors:
            raise serializers.ValidationError({"errors": errors})

        return data

    def create(self, validated_data):
        email = validated_data.pop("email")
        phone_number = validated_data.pop("phone")
        role = validated_data.pop("role")
        client_ids = validated_data.pop("client_ids", None)
        password = get_random_password()

        with transaction.atomic():
            user = User.objects.create_user(email, phone_number, password, role=role)
            user.profile.name = validated_data.get("name")
            user.profile.save()
            validated_data["user"] = user
            hdip_user = super().create(validated_data)
            if client_ids:
                InternalClient.objects.filter(pk__in=client_ids).update(
                    assigned_to=hdip_user
                )
            send_mail.delay(
                to=email,
                subject=WELCOME_MAIL_SUBJECT,
                template=ONBOARD_EMAIL_TEMPLATE,
                user_name=validated_data.get("name"),
                password=password,
                login_url=settings.LOGIN_URL,
            )
        return hdip_user

    def update(self, instance, validated_data):
        email = validated_data.pop("email", None)
        phone = validated_data.pop("phone", None)
        role = validated_data.pop("role", None)
        client_ids = validated_data.pop("client_ids", None)
        current_email = instance.user.email

        with transaction.atomic():

            if role is not None:
                instance.user.role = role
            if email is not None:
                instance.user.email = email
            if phone is not None:
                instance.user.phone = phone
            instance.user.save()

            if validated_data.get("name"):
                instance.user.profile.name = validated_data["name"]
                instance.user.profile.save()

            if client_ids is not None:
                current_client_ids = set(
                    InternalClient.objects.filter(assigned_to=instance).values_list(
                        "id", flat=True
                    )
                )
                new_client_ids = set(client_ids)
                clients_to_assign = new_client_ids - current_client_ids
                clients_to_unassign = current_client_ids - new_client_ids

                if clients_to_assign:
                    InternalClient.objects.filter(pk__in=clients_to_assign).update(
                        assigned_to=instance
                    )
                if clients_to_unassign:
                    InternalClient.objects.filter(pk__in=clients_to_unassign).update(
                        assigned_to=None
                    )

            super().update(instance, validated_data)
            if email and current_email != email:
                send_mail.delay(
                    to=current_email,
                    subject=f"{instance.name}, Your Email Is Updated",
                    template=CHANGE_EMAIL_NOTIFICATION_TEMPLATE,
                    name=instance.name,
                    new_email=instance.user.email,
                )

        return instance
