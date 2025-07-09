from django.conf import settings
from django.db import models, IntegrityError
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, Group
from django.core.exceptions import ValidationError
from phonenumber_field.modelfields import PhoneNumberField
from organizations.models import Organization
from hiringdogbackend.ModelUtils import CreateUpdateDateTimeAndArchivedField, SoftDelete


class Role(models.TextChoices):
    SUPER_ADMIN = ("super_admin", "Super Admin")
    ADMIN = ("admin", "Admin")
    MODERATOR = ("moderator", "Moderator")
    CLIENT_ADMIN = ("client_admin", "Client Admin")
    CLIENT_OWNER = ("client_owner", "Client Owner")
    CLIENT_USER = ("client_user", "Client User")
    USER = ("user", "User")
    INTERVIEWER = ("interviewer", "Interviewer")
    AGENCY = ("agency", "Agency")


class UserManager(BaseUserManager):
    def create_user(self, email, phone, password=None, **extra_field):
        if not email:
            raise ValueError("User must have an email address")
        if not phone:
            raise ValueError("User must have a phone number")

        user = self.model(
            email=self.normalize_email(email),
            phone=phone,
            **extra_field,
        )
        user.set_password(password)
        try:
            user.save(using=self._db)
        except IntegrityError as e:
            if "phone" in str(e):
                raise ValidationError("phone number already taken.")
            else:
                raise e
        return user

    def create_superuser(self, email, phone, password=None, **extra_field):
        if not email:
            raise ValueError("Admin must have an email address")
        if not phone:
            raise ValueError("Admin must have a phone number")
        user = self.create_user(email, phone, password, **extra_field)
        user.is_admin = True
        user.is_active = True
        user.role = Role.SUPER_ADMIN
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    email = models.EmailField(max_length=255, unique=True)
    phone = PhoneNumberField(region="IN", unique=True)
    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)
    role = models.CharField(max_length=15, choices=Role.choices, default=Role.USER)
    email_verified = models.BooleanField(default=False)
    email_verified_date = models.DateTimeField(null=True, blank=True)
    phone_verified = models.BooleanField(default=True)
    login_count = models.IntegerField(default=0)
    is_password_change = models.BooleanField(default=False)
    is_policy_and_tnc_accepted = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["phone"]

    def __str__(self):
        return self.email

    def has_perm(self, perm, obj=None):
        if self.email in settings.SUPER_ADMIN_ACCESS_EMAILS:
            if "view" == perm.split(".")[1].split("_")[0]:
                return True
            else:
                return False

        if self.is_admin:
            return True
        return Group.objects.filter(
            name=self.role, permissions__codename=perm.split(".")[1]
        ).exists()

    def has_module_perms(self, app_label):
        return self.is_admin

    @property
    def is_staff(self):
        return self.is_admin

    class Meta:
        indexes = [models.Index(fields=["email", "phone"])]


class UserProfile(CreateUpdateDateTimeAndArchivedField):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="profiles", null=True
    )  # comment this when you run you first makemigration command
    name = models.CharField(max_length=100, help_text="User's Full Name")

    def __str__(self) -> str:
        return f"{self.name} --> User({self.user_id})"

    class Meta:
        indexes = [models.Index(fields=["name"])]


class ClientCustomRole(Group):
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="clientcustomrole"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="clientcustomrole"
    )  # comment this when you run you first makemigration command


class OAuthToken(CreateUpdateDateTimeAndArchivedField):
    TOKEN_TYPE_CHOICES = (
        ("CLIENT", "Client"),
        ("INTERVIEWER", "Interviewer"),
        ("INTERNAL", "Internal"),
        ("AGENCY", "Agency"),
    )
    objects = SoftDelete()
    object_all = models.Manager()
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="oauth_token",
        help_text="The user associated with these tokens.",
    )
    token_type = models.CharField(
        max_length=50, choices=TOKEN_TYPE_CHOICES, blank=True, null=True
    )
    access_token = models.TextField(help_text="Access token for API authentication.")
    refresh_token = models.TextField(
        help_text="Refresh token to renew the access token.", blank=True, null=True
    )
    expires_at = models.DateTimeField(help_text="Access Token expiration timestamp.")
    scope = models.TextField(
        help_text="Granted scopes for the token.", blank=True, null=True
    )

    def is_access_token_valid(self):
        from django.utils.timezone import now

        return now() < self.expires_at

    def save(self, **kwargs):
        from django.utils.timezone import now
        from datetime import timedelta

        if self.updated_at is not None:
            expiration_duration = timedelta(hours=1)
            self.expires_at = now() + expiration_duration
        super().save(**kwargs)

    def __str__(self):
        return f"OAuthToken for {self.get_token_type_display()} -> User (id: {self.user_id})"


class FeedbackAndImprovement(CreateUpdateDateTimeAndArchivedField):

    PRIORITY_CHOICES = (
        ("P0", "High"),
        ("P1", "Medium"),
        ("P2", "Low"),
    )
    FEEDBACK_TYPE_CHOICES = (
        ("BUG", "Bug"),
        ("ENHANCEMENT", "Enhancement"),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_and_improvements",
    )
    context = models.TextField(
        blank=True,
        help_text="Context of the feedback or area of improvement.",
    )
    screenshot = models.ImageField(
        upload_to="application_feedback",
        blank=True,
        null=True,
        help_text="Screenshot of the area of improvement.",
    )
    feedback_type = models.CharField(
        max_length=15, choices=FEEDBACK_TYPE_CHOICES, null=True, blank=True
    )
    priority = models.CharField(
        max_length=15,
        choices=PRIORITY_CHOICES,
        null=True,
        blank=True,
        help_text="Priority of the feedback or improvement.",
    )
    is_fixed = models.BooleanField(default=False)
