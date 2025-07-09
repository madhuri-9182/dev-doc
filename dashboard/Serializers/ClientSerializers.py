import json
from datetime import datetime
from celery import group
from rest_framework import serializers
from celery import group
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from core.models import User, Role
from datetime import date
from ..models import (
    ClientUser,
    Department,
    Job,
    JobInterviewRounds,
    Candidate,
    InternalInterviewer,
    Engagement,
    EngagementOperation,
    EngagementTemplates,
    Interview,
    BillingLog,
    CandidateToInterviewerFeedback,
)
from phonenumber_field.serializerfields import PhoneNumberField
from hiringdogbackend.utils import (
    validate_incoming_data,
    get_random_password,
    check_for_email_and_phone_uniqueness,
    validate_attachment,
    validate_json,
)
from ..tasks import send_mail, send_schedule_engagement_email


CONTACT_EMAIL = settings.EMAIL_HOST_USER if settings.DEBUG else settings.CONTACT_EMAIL


class ClientUserDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "phone", "role")


class JobSpecificDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ("id", "name")


class ClientUserSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format="%d/%m/%Y", read_only=True)
    user = ClientUserDetailsSerializer(read_only=True)
    email = serializers.EmailField(write_only=True, required=False)
    role = serializers.ChoiceField(
        choices=Role.choices, write_only=True, required=False
    )
    phone = PhoneNumberField(write_only=True, required=False)
    jobs_assigned = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )
    assigned_jobs = JobSpecificDetailsSerializer(
        read_only=True, many=True, source="jobs"
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
        fields = (
            "id",
            "user",
            "name",
            "email",
            "phone",
            "role",
            "designation",
            "jobs_assigned",
            "assigned_jobs",
            "created_at",
            "accessibility",
            "status",
            "last_invitation_notification_time",
        )
        read_only_fields = ["created_at"]

    def run_validation(self, data=...):
        email = data.get("email")
        phone_number = data.get("phone")
        role = data.get("role")
        errors = check_for_email_and_phone_uniqueness(email, phone_number, User)
        if role and role not in ("client_user", "client_admin", "agency"):
            errors.setdefault("role", []).append("Invalid role type.")
        if errors:
            raise serializers.ValidationError({"errors": errors})
        return super().run_validation(data)

    def validate(self, data):
        errors = validate_incoming_data(
            self.initial_data,
            [
                "name",
                "email",
                "role",
                "phone",
                "accessibility",
            ],
            allowed_keys=["jobs_assigned"],
            partial=self.partial,
        )

        if errors:
            raise serializers.ValidationError({"errors": errors})

        return data

    def create(self, validated_data):
        email = validated_data.pop("email", None)
        phone_number = validated_data.pop("phone", None)
        user_role = validated_data.pop("role", None)
        name = validated_data.get("name")
        organization = validated_data.get("organization")
        jobs_assigned = validated_data.pop("jobs_assigned", None)
        temp_password = get_random_password()
        current_user = self.context.get("user")

        with transaction.atomic():
            user = User.objects.create_user(
                email=email, phone=phone_number, password=temp_password, role=user_role
            )
            user.profile.name = name
            user.profile.organization = organization
            user.profile.save()
            client_user = ClientUser.objects.create(
                user=user,
                last_invitation_notification_time=timezone.now(),
                **validated_data,
            )
            if jobs_assigned:
                job_qs = Job.objects.filter(pk__in=jobs_assigned)
                client_user.jobs.add(*job_qs)

            data = f"user:{current_user.email};invitee-email:{email}"
            uid = urlsafe_base64_encode(force_bytes(data))
            send_mail_to_clientuser = send_mail.si(
                to=email,
                subject=f"You're Invited to Join {organization.name} on Hiring Dog",
                template="invitation.html",
                invited_name=name,
                user_name=current_user.clientuser.name,
                user_email=current_user.email,
                org_name=organization.name,
                password=temp_password,
                login_url=settings.LOGIN_URL,
                activation_url=f"/client/client-user-activate/{uid}/",
                site_domain=settings.SITE_DOMAIN,
            )

            send_mail_to_internal = send_mail.si(
                to=(
                    organization.internal_client.assigned_to.user.email
                    if organization.internal_client.assigned_to
                    else CONTACT_EMAIL
                ),
                subject=f"Confirmation: Invitation Sent to {name} for {organization.name}",
                template="internal_client_clientuser_invitation_confirmation.html",
                internal_user_name=(
                    organization.internal_client.assigned_to.name
                    if organization.internal_client.assigned_to
                    else "Unknown"
                ),
                client_user_name=name,
                invitation_date=datetime.today().strftime("%d/%m/%Y"),
                client_name=organization.name,
            )

            transaction.on_commit(
                lambda: (send_mail_to_clientuser | send_mail_to_internal).apply_async()
            )

        return client_user

    def update(self, instance, validated_data):
        email = validated_data.pop("email", None)
        phone_number = validated_data.pop("phone", None)
        role = validated_data.pop("role", None)
        name = validated_data.get("name")
        jobs_assigned = validated_data.pop("jobs_assigned", None)

        updated_client_user = super().update(instance, validated_data)

        if jobs_assigned:
            jobs_qs = Job.objects.filter(pk__in=jobs_assigned)
            updated_client_user.jobs.set(jobs_qs)

        if email:
            updated_client_user.user.email = email
        if phone_number:
            updated_client_user.user.phone = phone_number
        if role:
            updated_client_user.user.role = role
        if name:
            updated_client_user.user.profile.name = name
            updated_client_user.user.profile.save()

        updated_client_user.user.save()
        return updated_client_user


class JobClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientUser
        fields = ("id", "name")


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ("id", "name")


class JobInterviewRoundsSerializer(serializers.ModelSerializer):
    question_bank = serializers.JSONField(source="other_details", required=False)
    duration_minutes = serializers.ChoiceField(
        choices=JobInterviewRounds.DURATION_MINUTES_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in JobInterviewRounds.DURATION_MINUTES_CHOICES])}"
        },
        required=False,
    )
    job_uid = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = JobInterviewRounds
        fields = (
            "id",
            "job_uid",
            "name",
            "duration_minutes",
            "sequence_number",
            "question_bank",
        )

    def to_internal_value(self, data):
        internal_data = super().to_internal_value(data)

        if "other_details" in internal_data and "question_bank" not in internal_data:
            internal_data["question_bank"] = internal_data.pop("other_details")
        return internal_data

    def validate(self, data):
        from_job_serializer = self.context.get("from_job_serializer", False)
        required_keys = [
            "job_uid",
            "name",
            "sequence_number",
            "question_bank",
        ]
        allowed_keys = [
            "duration_minutes",
        ]

        if from_job_serializer or "job_uid" in data and "sequence_number" not in data:
            required_keys = required_keys[1:]

        errors = validate_incoming_data(
            data,
            required_keys,
            allowed_keys,
            partial=self.partial,
        )

        if (
            not from_job_serializer
            and "sequence_number" in data
            and "job_uid" not in data
        ):
            errors.setdefault("job_uid", []).append(
                "Job UID is required to update sequence number"
            )

        if errors:
            raise serializers.ValidationError(errors)

        # validate questions
        if data.get("question_bank") is not None:
            question_bank_schema = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "details": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "time": {
                            "type": "string",
                            "pattern": "^\\d+min$",
                        },
                        "guidelines": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "questionnaire": {
                            "type": ["object", "null"],
                            "properties": {
                                "easy": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                    },
                                },
                                "medium": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                    },
                                },
                                "hard": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                    },
                                },
                            },
                        },
                        "reference_links": {
                            "type": ["array", "null"],
                            "items": {
                                "type": "string",
                            },
                        },
                    },
                    "required": ["details", "time", "guidelines"],
                    "anyOf": [
                        {"required": ["questionnaire"]},
                        {"required": ["reference_links"]},
                        {"required": ["questionnaire", "reference_links"]},
                    ],
                },
            }
            errors.update(
                validate_json(
                    data["question_bank"], "question_bank", question_bank_schema
                )
            )

        # validate job_uid
        job_uid = data.pop("job_uid", None)
        if job_uid:
            org = self.context["org"]
            job = Job.objects.filter(
                hiring_manager__organization=org, pk=job_uid
            ).first()
            if not job:
                errors.setdefault("job_uid", []).append("Invalid job_uid")
            data["job"] = job
            if self.partial:
                last_job_interview_round = (
                    JobInterviewRounds.objects.filter(job=job, pk__lt=self.instance.id)
                    .order_by("-sequence_number")
                    .first()
                )
            else:
                last_job_interview_round = (
                    JobInterviewRounds.objects.filter(job=job)
                    .order_by("-sequence_number")
                    .first()
                )
            self.context["last_round"] = last_job_interview_round
            sequence_number = data.get("sequence_number")
            if sequence_number is not None:
                if JobInterviewRounds.objects.filter(
                    job=job, sequence_number=sequence_number
                ).exists():
                    errors.setdefault("sequence_number", []).append(
                        "Duplicate sequence_number"
                    )
                if (
                    last_job_interview_round
                    and last_job_interview_round.sequence_number >= sequence_number
                ):
                    errors.setdefault("sequence_number", []).append(
                        f"sequence_number must be greater than {last_job_interview_round.sequence_number}"
                    )

        if errors:
            raise serializers.ValidationError(errors)

        if data.get("question_bank"):
            data["other_details"] = data.pop("question_bank")
        return data


class JobSerializer(serializers.ModelSerializer):
    clients = JobClientSerializer(read_only=True, many=True)
    hiring_manager = JobClientSerializer(read_only=True)
    recruiter_ids = serializers.CharField(write_only=True, required=False)
    hiring_manager_id = serializers.IntegerField(write_only=True, required=False)
    name = serializers.ChoiceField(
        choices=InternalInterviewer.ROLE_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in InternalInterviewer.ROLE_CHOICES])}"
        },
        required=False,
    )
    specialization = serializers.ChoiceField(
        choices=Candidate.SPECIALIZATION_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Candidate.SPECIALIZATION_CHOICES])}"
        },
        required=False,
    )
    active_candidates = serializers.SerializerMethodField()
    department = DepartmentSerializer(read_only=True)
    rounds = JobInterviewRoundsSerializer(
        many=True, required=False, source="interview_rounds"
    )
    department_uid = serializers.UUIDField(required=False, write_only=True)

    class Meta:
        model = Job
        fields = (
            "id",
            "clients",
            "name",
            "job_id",
            "department",
            "department_uid",
            "recommended_score",
            "hiring_manager",
            "recruiter_ids",
            "hiring_manager_id",
            "total_positions",
            "job_description_file",
            "mandatory_skills",
            "reason_for_archived",
            "specialization",
            "min_exp",
            "max_exp",
            "active_candidates",
            "is_diversity_hiring",
            "rounds",
            # "interview_rounds",
        )

    def run_validation(self, data=...):
        valid_reasons = ["PF", "POH", "OTH"]
        reason = data.get("reason_for_archived")

        if reason and reason not in valid_reasons:
            raise serializers.ValidationError(
                {
                    "errors": {
                        "reason_for_archived": ["Invalid reason_for_archived value."]
                    }
                }
            )
        return super().run_validation(data)

    def validate(self, data):
        org = self.context["org"]

        if not self.partial:
            rounds_raw = self.initial_data.get("rounds")
            if rounds_raw:
                try:
                    rounds_list = (
                        json.loads(rounds_raw)
                        if isinstance(rounds_raw, str)
                        else rounds_raw
                    )
                except json.JSONDecodeError:
                    raise serializers.ValidationError(
                        {"rounds": ["Invalid JSON format."]}
                    )
                if not rounds_list:
                    raise serializers.ValidationError(
                        {"rounds": ["This field is required"]}
                    )
                errors = {}
                rounds_validated_data = []
                sequence_numbers = [
                    round_data.get("sequence_number")
                    for round_data in rounds_list
                    if round_data.get("sequence_number") is not None
                ]
                if not sequence_numbers or sequence_numbers != sorted(sequence_numbers):
                    raise serializers.ValidationError(
                        {"rounds": ["sequence_number must be strictly sorted."]}
                    )
                for round_data in rounds_list:
                    round_serializer = JobInterviewRoundsSerializer(
                        data=round_data, context={"from_job_serializer": True}
                    )
                    if not round_serializer.is_valid():
                        errors.setdefault("rounds", []).append(
                            {
                                "index": rounds_list.index(round_data),
                                "errors": round_serializer.errors,
                            }
                        )
                    rounds_validated_data.append(round_serializer.validated_data)
                if errors:
                    raise serializers.ValidationError(errors)

                self._validated_rounds = rounds_validated_data
                self.initial_data.pop("rounds")
            else:
                raise serializers.ValidationError(
                    {"rounds": ["This field is required"]}
                )

        required_keys = [
            "name",
            "hiring_manager_id",
            "recruiter_ids",
            "job_description_file",
            "mandatory_skills",
            "specialization",
            "min_exp",
            "max_exp",
        ]
        allowed_keys = [
            "job_id",
            "reason_for_archived",
            "is_diversity_hiring",
            "recommended_score",
            "department_uid",
            "total_positions",
        ]

        errors = validate_incoming_data(
            self.initial_data,
            required_keys,
            allowed_keys,
            original_data=data,
            form=True,
            partial=self.partial,
        )
        if errors:
            raise serializers.ValidationError({"errors": errors})

        hiring_manager_id = data.get("hiring_manager_id")
        recruiter_ids = data.get("recruiter_ids")
        department_uid = data.pop("department_uid", None)

        client_user_ids = set(
            ClientUser.objects.filter(organization=org).values_list("id", flat=True)
        )
        if recruiter_ids:
            try:
                recruiter_ids = set(json.loads(recruiter_ids))
                if not recruiter_ids.issubset(client_user_ids):
                    errors.setdefault("recruiter_ids", []).append(
                        f"Invalid recruiter_ids(clientuser_ids): {recruiter_ids - client_user_ids}"
                    )

            except (json.JSONDecodeError, ValueError, TypeError):
                errors.setdefault("recruiter_ids", []).append(
                    "Invalid data format. It should be a list of integers."
                )

        if hiring_manager_id and hiring_manager_id not in client_user_ids:
            errors.setdefault("hiring_manager_id", []).append(
                "Invalid hiring_manager_id"
            )
        if (
            hiring_manager_id
            and isinstance(recruiter_ids, list)
            and hiring_manager_id in recruiter_ids
        ):
            errors.setdefault("conflict_error", []).append(
                "hiring_manager_id and recruiter_id cannot be the same."
            )

        if data.get("total_positions") and not (0 <= data.get("total_positions") < 100):
            errors.setdefault("total_positions", []).append("Invalid total_positions")

        if data.get("job_description_file"):
            error = validate_attachment(
                "job_description_file",
                data["job_description_file"],
                ["doc", "docx", "pdf"],
                max_size_mb=5,
            )
            if error:
                errors.update(error)

        if data.get("mandatory_skills") is not None:
            schema = {"type": "array", "items": {"type": "string"}, "minItems": 1}
            errors.update(
                validate_json(data["mandatory_skills"], "mandatory_skills", schema)
            )

        if department_uid:
            try:
                data["department"] = Department.objects.get(pk=department_uid)
            except Department.DoesNotExist:
                errors.setdefault("department_uid", []).append("Invalid department_uid")

        if errors:
            raise serializers.ValidationError({"errors": errors})
        data["recruiter_ids"] = recruiter_ids
        return data

    def get_active_candidates(self, obj):
        return obj.candidate.count()

    def create(self, validated_data):
        recruiter_ids = validated_data.pop("recruiter_ids", [])
        rounds_data = getattr(self, "_validated_rounds", [])
        job = super().create(validated_data)
        job.clients.add(*recruiter_ids)
        rounds_data = [
            JobInterviewRounds(job=job, **round_data) for round_data in rounds_data
        ]
        if rounds_data:
            JobInterviewRounds.objects.bulk_create(rounds_data)
        return job

    def update(self, instance, validated_data):
        recruiter_ids = validated_data.pop("recruiter_ids", None)
        job = super().update(instance, validated_data)
        if recruiter_ids is not None:
            job.clients.set(recruiter_ids)
        return job


class CandidateJobInterviewRoundSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobInterviewRounds
        fields = ("id", "name", "sequence_number")


class CandidateSerializer(serializers.ModelSerializer):
    designation = JobSpecificDetailsSerializer(read_only=True)
    gender = serializers.ChoiceField(
        choices=Candidate.GENDER_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Candidate.GENDER_CHOICES])}"
        },
        required=False,
    )
    source = serializers.ChoiceField(
        choices=Candidate.SOURCE_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Candidate.SOURCE_CHOICES])}"
        },
        required=False,
    )
    status = serializers.ChoiceField(
        choices=Candidate.STATUS_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Candidate.STATUS_CHOICES])}"
        },
        required=False,
    )
    final_selection_status = serializers.ChoiceField(
        choices=Candidate.FINAL_SELECTION_STATUS_CHOICES + ((None, "")),
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Candidate.FINAL_SELECTION_STATUS_CHOICES])}"
        },
        required=False,
        allow_blank=True,
    )
    reason_for_dropping = serializers.ChoiceField(
        choices=Candidate.REASON_FOR_DROPPING_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Candidate.REASON_FOR_DROPPING_CHOICES])}"
        },
        required=False,
    )
    job_id = serializers.IntegerField(required=False, write_only=True)
    specialization = serializers.ChoiceField(
        choices=Candidate.SPECIALIZATION_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Candidate.SPECIALIZATION_CHOICES])}"
        },
        required=False,
    )
    interview_type = serializers.ChoiceField(
        choices=Candidate.INTERVIEW_TYPE_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Candidate.INTERVIEW_TYPE_CHOICES])}"
        },
        required=False,
    )
    created_at = serializers.DateTimeField(format="%d/%m/%Y", read_only=True)
    scheduled_time = serializers.DateTimeField(
        format="%d/%m/%Y %I:%S %p", read_only=True
    )
    last_completed_round = CandidateJobInterviewRoundSerializer(read_only=True)
    next_round = CandidateJobInterviewRoundSerializer(read_only=True)

    class Meta:
        model = Candidate
        fields = (
            "id",
            "name",
            "designation",
            "source",
            "year",
            "month",
            "cv",
            "status",
            "gender",
            "score",
            "total_score",
            "final_selection_status",
            "email",
            "phone",
            "company",
            "current_designation",
            "specialization",
            "remark",
            "last_scheduled_initiate_time",
            "reason_for_dropping",
            "job_id",
            "created_at",
            "scheduled_time",
            "is_engagement_pushed",
            "interviews",
            "interview_type",
            "last_completed_round",
            "next_round",
        )
        read_only_fields = ["designation", "created_at", "is_engagement_pushed"]

    def validate(self, data):
        request = self.context.get("request")
        required_keys = [
            "name",
            "year",
            "month",
            "phone",
            "email",
            "company",
            "current_designation",
            "job_id",
            "source",
            "cv",
            "specialization",
        ]
        allowed_keys = [
            "status",
            "reason_for_dropping",
            "interview_type",
            "remark",
            "gender",
        ]

        if self.partial:
            allowed_keys = [
                "specialization",
                "remark",
                "source",
                "final_selection_status",
            ]
            required_keys = allowed_keys

        errors = validate_incoming_data(
            self.initial_data,
            required_keys,
            allowed_keys,
            partial=self.partial,
            original_data=data,
            form=True,
        )

        if errors:
            raise serializers.ValidationError({"errors": errors})

        job = Job.objects.filter(
            pk=data.get("job_id"),
            hiring_manager__organization=request.user.clientuser.organization,
        ).first()
        if data.get("job_id") and not job:
            errors.setdefault("job_id", []).append("Invalid job_id")

        if job and job.is_diversity_hiring and not data.get("gender"):
            errors.setdefault("gender", []).append(
                "This is required field for diversity hiring."
            )

        if data.get("cv"):
            errors.update(validate_attachment("cv", data.get("cv"), ["pdf", "docx"], 5))
        if errors:
            raise serializers.ValidationError({"errors": errors})

        next_round = job.interview_rounds.order_by("sequence_number").first()
        data["next_round"] = next_round

        return data


class EngagementOperationDataSerializer(serializers.Serializer):
    template_id = serializers.IntegerField()
    date = serializers.DateTimeField(
        input_formats=["%d/%m/%Y %H:%M:%S"], format="%d/%m/%Y %H:%M"
    )
    week = serializers.IntegerField(min_value=1, max_value=12)


class EngagementOperationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EngagementTemplates
        fields = ("id", "template_name")


class EngagementOperationSerializer(serializers.ModelSerializer):
    template_data = EngagementOperationDataSerializer(
        many=True, write_only=True, required=False
    )
    template = EngagementOperationTemplateSerializer(read_only=True)
    engagement_id = serializers.IntegerField(write_only=True, required=False)
    date = serializers.DateTimeField(format="%d/%m/%Y %H:%M:%S", read_only=True)

    class Meta:
        model = EngagementOperation
        fields = (
            "id",
            "template",
            "week",
            "date",
            "delivery_status",
            "engagement_id",
            "template_data",
            "operation_complete_status",
        )
        read_only_fields = [
            "week",
            "date",
            "delivery_status",
            "operation_complete_status",
        ]

    def to_internal_value(self, data):
        template_data = data.get("template_data", [])

        if ("template_data" in data.keys() and not template_data) or not isinstance(
            template_data, list
        ):
            raise serializers.ValidationError(
                {
                    "template_data": [
                        "This field must be a non-empty list of dictionaries with keys 'template_id' and 'date'.",
                        "Expected format: [{'template_id': <int>, 'week': <int>, 'date': '<dd/mm/yyyy hh:mm:ss>'}]",
                    ]
                }
            )

        for entry in template_data:
            if (
                not isinstance(entry, dict)
                or "template_id" not in entry
                or "date" not in entry
                or "week" not in entry
            ):
                raise serializers.ValidationError(
                    {
                        "template_data": [
                            "Each item must match the following schema:",
                            "Expected format: {'template_id': <int>, 'week': <int>, 'date': '<dd/mm/yyyy hh:mm:ss>'}",
                        ]
                    }
                )
        return super().to_internal_value(data)

    def validate(self, data):
        request = self.context["request"]
        errors = validate_incoming_data(
            self.initial_data,
            ["engagement_id", "template_data"],
            partial=self.partial,
        )

        engagement_id = data.pop("engagement_id", None)
        engagement = None
        if engagement_id:
            engagement = Engagement.objects.filter(
                organization=request.user.clientuser.organization,
                pk=engagement_id,
            ).first()
            if not engagement:
                errors.setdefault("engagement_id", []).append("Invalid engagement_id")
            data["engagement"] = engagement

        if engagement:
            notice_weeks = int(engagement.notice_period.split("-")[1]) / 7
            max_template_assign = notice_weeks * 2

            templates = data.pop("template_data", [])
            already_associated_operation = EngagementOperation.objects.filter(
                engagement=engagement
            ).count()

            if (
                len(templates) > max_template_assign
                or already_associated_operation > max_template_assign
            ):
                errors.setdefault("template_ids", []).append(
                    "Max {} templates can be assigned ".format(int(max_template_assign))
                )

            week_count = {}
            for template in templates:
                week = template.get("week")
                if week is not None:
                    week_count[week] = week_count.get(week, 0) + 1

            if len(week_count) > notice_weeks:
                errors.setdefault("template_data", []).append(
                    "Number of weeks with templates assigned exceeds the notice period weeks."
                )

            if any(count > 2 for count in week_count.values()):
                errors.setdefault("template_data", []).append(
                    "Max 2 templates can be assigned per week."
                )

            invalid_dates = [
                template["date"].strftime("%d/%m/%Y %H:%M:%S")
                for template in templates
                if datetime.strptime(
                    template["date"].strftime("%d-%m-%Y %H:%M:%S"),
                    "%d-%m-%Y %H:%M:%S",
                )
                < datetime.strptime(
                    datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
                    "%d-%m-%Y %H:%M:%S",
                )
            ]

            if invalid_dates:
                errors.setdefault("template_data", []).append(
                    "Invalid dates present: {}. Dates should not be in past".format(
                        ", ".join(invalid_dates)
                    )
                )

            if not errors:
                valid_template_ids = set(
                    EngagementTemplates.objects.filter(
                        organization=request.user.clientuser.organization,
                        pk__in=[template["template_id"] for template in templates],
                    ).values_list("id", flat=True)
                )

                existing_template_ids = set(
                    EngagementOperation.objects.filter(
                        engagement=engagement, template_id__in=valid_template_ids
                    ).values_list("template_id", flat=True)
                )
                if existing_template_ids:
                    errors.setdefault("template_id", []).extend(
                        [
                            "Template id already exists for the given engagement: {}".format(
                                template_id
                            )
                            for template_id in existing_template_ids
                        ]
                    )

                invalid_template_ids = (
                    set(template["template_id"] for template in templates)
                    - valid_template_ids
                )

                if invalid_template_ids:
                    errors.setdefault("template_id", []).append(
                        "Invalid template_id: {}".format(
                            ", ".join(map(str, invalid_template_ids))
                        )
                    )

                data["templates"] = [
                    template
                    for template in templates
                    if template["template_id"] in valid_template_ids
                    and template["template_id"] not in existing_template_ids
                ]

        if errors:
            raise serializers.ValidationError({"errors": errors})

        return data

    def create(self, validated_data):
        engagement = validated_data["engagement"]
        templates = validated_data.pop("templates", [])

        operations = [
            EngagementOperation(
                engagement=engagement,
                template_id=template["template_id"],
                date=template["date"],
                week=template["week"],
            )
            for template in templates
        ]

        operations = EngagementOperation.objects.bulk_create(operations)

        task_group = group(
            send_schedule_engagement_email.s(operation.id).set(eta=operation.date)
            for operation in operations
        )
        result = task_group.apply_async()

        for operation, task in zip(operations, result.children):
            operation.task_id = task.id
            operation.save()

        return operations


class EngagementTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EngagementTemplates
        fields = (
            "id",
            "template_name",
            "subject",
            "template_html_content",
            "attachment",
        )

    def validate(self, data):
        attachment = self.context.get("attachment")
        required_keys = ["template_name", "subject", "template_html_content"]
        allowed_keys = ["attachment"]
        errors = validate_incoming_data(
            self.initial_data,
            required_keys,
            allowed_keys,
            partial=self.partial,
            original_data=data,
            form=True,
        )
        if attachment:
            errors.update(
                validate_attachment(
                    "attachment",
                    data.get("attachment"),
                    [
                        "pdf",
                        "doc",
                        "docx",
                        "xls",
                        "xlsx",
                        "ppt",
                        "txt",
                        "pptx",
                        "jpeg",
                        "jpg",
                        "mp3",
                        "mp4",
                        "mkv",
                        "zip",
                    ],
                    25,
                )
            )
        if errors:
            raise serializers.ValidationError({"errors": errors})
        return data


class EngagementCandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = ("name", "phone", "email", "company", "cv")


class EngagementJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ("id", "name")


class EngagementClientUserSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = ClientUser
        fields = ("id", "name", "email")
        read_only_fields = ("email",)


class EngagementSerializer(serializers.ModelSerializer):
    candidate = EngagementCandidateSerializer(read_only=True)
    candidate_id = serializers.IntegerField(required=False, write_only=True)
    offer_date = serializers.DateField(
        input_formats=["%d/%m/%Y"], format="%d/%m/%Y", required=False
    )
    engagementoperations = EngagementOperationSerializer(read_only=True, many=True)

    status = serializers.ChoiceField(
        choices=Engagement.STATUS_CHOICE,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Engagement.STATUS_CHOICE])}"
        },
        required=False,
    )
    notice_period = serializers.ChoiceField(
        choices=Engagement.NOTICE_PERIOD_CHOICE,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Engagement.NOTICE_PERIOD_CHOICE])}"
        },
        required=False,
    )

    class Meta:
        model = Engagement
        fields = (
            "id",
            "candidate_name",
            "candidate_email",
            "candidate_phone",
            "candidate_id",
            "job",
            "candidate",
            "status",
            "notice_period",
            "offered",
            "offer_date",
            "offer_accepted",
            "other_offer",
            "gtp_name",
            "gtp_email",
            "candidate_cv",
            "engagementoperations",
        )
        extra_kwargs = {
            "candidate_id": {"write_only": True},
        }

    def validate(self, data):
        request = self.context["request"]
        errors = {}

        required_keys = [
            "job",
            "gtp_name",
            "gtp_email",
            "notice_period",
            "offered",
            "offer_accepted",
            "other_offer",
        ]
        allowed_keys = [
            "status",
            "offer_date",
        ]

        if (
            data.get("candidate_name")
            or data.get("candidate_email")
            or data.get("candidate_phone")
        ):
            required_keys.extend(
                ["candidate_name", "candidate_email", "candidate_phone", "candidate_cv"]
            )
        elif data.get("candidate_id"):
            required_keys.append("candidate_id")
        else:
            errors.setdefault("missing_candidate_details", []).append(
                "Either candidate_id or candidate_email, candidate_name, candidate_phone, candidate_cv is required"
            )

        errors.update(
            validate_incoming_data(
                self.initial_data,
                required_keys=required_keys,
                allowed_keys=allowed_keys,
                partial=self.partial,
                original_data=data,
                form=True,
            )
        )

        candidate_id = data.pop("candidate_id", None)
        if candidate_id:
            candidate = Candidate.objects.filter(
                organization=request.user.clientuser.organization, pk=candidate_id
            ).first()
            if not candidate:
                errors.setdefault("candidate_id", []).append("Invalid candidate_id")
            data["candidate"] = candidate

        candidate_cv = data.get("candidate_cv")
        if candidate_cv:
            errors.update(
                validate_attachment(
                    "candidate_cv", candidate_cv, ["pdf", "doc", "docx"], 5
                )
            )

        if data.get("offered") and not data.get("offer_date"):
            errors.setdefault("offer_date", []).append(
                "Offer date is required if 'offered' is True."
            )

        if data.get("offer_accepted") and not data.get("offered"):
            errors.setdefault("offer_accepted", []).append(
                "Offer cannot be accepted if it was never made."
            )

        if errors:
            raise serializers.ValidationError({"errors": errors})

        return data


class EngagementUpdateStatusSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(
        choices=Engagement.STATUS_CHOICE,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in Engagement.STATUS_CHOICE])}"
        },
        required=False,
    )

    class Meta:
        model = Engagement
        fields = ("status",)


class EngagmentOperationStatusUpdateSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(
        source="operation_complete_status",
        choices=EngagementOperation.DELIVERY_STATUS_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in EngagementOperation.DELIVERY_STATUS_CHOICES])}"
        },
    )

    class Meta:
        model = EngagementOperation
        fields = ("status",)

    def validate(self, data):
        errors = {}
        engagement_operation = self.instance

        if engagement_operation.delivery_status != "SUC":
            errors.setdefault("status", []).append(
                "Invalid status update request. As operation is not successfully delievered yet."
            )

        if errors:
            raise serializers.ValidationError({"errors": errors})
        return data


class FinanceCandidateSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source="designation.name")

    class Meta:
        model = Candidate
        fields = ("name", "year", "month", "role")


class FinanceSerializer(serializers.ModelSerializer):
    candidate = FinanceCandidateSerializer(source="interview.candidate", read_only=True)
    scheduled_time = serializers.DateTimeField(
        source="interview.scheduled_time", format="%d/%m/%Y %H:%M:%S"
    )
    amount = serializers.DecimalField(
        source="amount_for_client", max_digits=10, decimal_places=2
    )

    class Meta:
        model = BillingLog
        fields = ("candidate", "scheduled_time", "amount", "status")


class FinanceSerializerForInterviewer(serializers.ModelSerializer):
    candidate = FinanceCandidateSerializer(source="interview.candidate", read_only=True)
    scheduled_time = serializers.DateTimeField(
        source="interview.scheduled_time", format="%d/%m/%Y %H:%M:%S"
    )
    amount = serializers.DecimalField(
        source="amount_for_interviewer", max_digits=10, decimal_places=2
    )
    status = serializers.CharField(max_length=15, source="interviewer_payment_status")
    is_feedback_submitted_late = serializers.BooleanField(
        source="is_interviewer_feedback_submitted_late"
    )
    late_submission_deduction = serializers.DecimalField(
        source="late_feedback_submission_deduction", max_digits=10, decimal_places=2
    )
    generated_at = serializers.DateTimeField(
        source="interview.interview_feedback.created_at", format="%d/%m/%Y %I %p"
    )
    submitted_at = serializers.DateTimeField(
        source="interview.interview_feedback.submitted_at",
        format="%d/%m/%Y %I %p",
    )

    class Meta:
        model = BillingLog
        fields = (
            "candidate",
            "scheduled_time",
            "amount",
            "status",
            "is_feedback_submitted_late",
            "late_submission_deduction",
            "generated_at",
            "submitted_at",
        )


class AnalyticsQuerySerializer(serializers.Serializer):
    from_date = serializers.DateField(required=False, input_formats=["%d/%m/%Y"])
    to_date = serializers.DateField(required=False, input_formats=["%d/%m/%Y"])
    organization_id = serializers.IntegerField(required=False)

    def validate(self, data):
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        errors = {}

        if not from_date or not to_date:
            errors["date"] = "Both 'from_date' and 'to_date' must be provided together."

        today = date.today()
        if from_date and to_date and (from_date > today or to_date > today):
            errors["date"] = "Dates cannot be in the future."

        if errors:
            raise serializers.ValidationError(errors)

        return data


class FeedbackPDFVideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Interview
        fields = ("id", "recording")


class ResendClientUserInvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(max_length=50)

    def validate(self, data):
        email = data.get("email")
        errors = {}
        try:
            client_user = ClientUser.objects.get(user__email=email)
        except ClientUser.DoesNotExist:
            errors.setdefault("email", []).append("Email address not found.")

        if client_user.status == "ACT":
            errors.setdefault("email", []).append(
                "Invalid request. User is alrady activated"
            )

        request_user = self.context.get("user")
        if request_user.email == email:
            errors.setdefault("email", []).append(
                "Invalid request. You can't resend invitation to yourself"
            )

        if errors:
            raise serializers.ValidationError(errors)

        self.context["client_user"] = client_user

        return data


class InterviewerFeedbackSerializer(serializers.ModelSerializer):
    rating = serializers.ChoiceField(
        choices=CandidateToInterviewerFeedback.RATING_CHOICES,
        error_messages={
            "invalid_choice": f"This is an invalid choice. Valid choices are {', '.join([f'{key}({value})' for key, value in CandidateToInterviewerFeedback.RATING_CHOICES])}"
        },
        required=False,
    )

    class Meta:
        model = CandidateToInterviewerFeedback
        fields = ("rating", "comments")

    def validate(self, data):
        feedback_uid = self.context.get("feedback_uid")
        errors = validate_incoming_data(data, ["rating", "comments"])
        try:
            interview_id = force_str(urlsafe_base64_decode(feedback_uid)).split(":")[1]
        except (ValueError, TypeError, IndexError):
            errors.setdefault("request", []).append("Invalid token.")

        interview = None
        try:
            interview = Interview.objects.get(pk=interview_id)
        except Interview.DoesNotExist:
            errors.setdefault("request", []).append("Invalid request")

        if interview and interview.candidate_interviewer_feeddback.exists():
            errors.setdefault("feedback", []).append("Feedback is already submitted")

        if errors:
            raise serializers.ValidationError(errors)

        data["interviewer"] = interview.interviewer
        data["interview"] = interview
        return data


class JobDescriptionSerializer(serializers.Serializer):
    designation = serializers.CharField(max_length=50)
    specialization = serializers.CharField(max_length=50)
    min_exp = serializers.IntegerField(min_value=0, max_value=50)
    max_exp = serializers.IntegerField(min_value=0, max_value=50)
    tech_stack = serializers.ListField(child=serializers.CharField())
    location = serializers.CharField(max_length=50)


class QuestionRequestSerializer(serializers.Serializer):
    skill = serializers.CharField(max_length=50)
    designation = serializers.CharField(max_length=50)
    specialization = serializers.CharField(max_length=50)
    min_exp = serializers.IntegerField(min_value=0, max_value=50)
    max_exp = serializers.IntegerField(min_value=0, max_value=50)


class InterviewRoundHistorySerializer(serializers.ModelSerializer):
    round_name = serializers.CharField(source="job_round.name", read_only=True)
    scheduled_time = serializers.DateTimeField(format="%d/%m/%Y %H:%M")

    class Meta:
        model = Interview
        fields = ("id", "round_name", "scheduled_time", "score", "status")
