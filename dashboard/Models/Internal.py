from organizations.models import Organization
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from phonenumber_field.modelfields import PhoneNumberField
from core.models import User
from hiringdogbackend.ModelUtils import SoftDelete, CreateUpdateDateTimeAndArchivedField


class HDIPUsers(CreateUpdateDateTimeAndArchivedField):
    """I just keep this model for future enhancement otherwise I prefer to use userprofile model as HDIP User"""

    objects = SoftDelete()
    object_all = models.Manager()

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="hdipuser", blank=True
    )
    name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class InternalClient(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()
    organization = models.OneToOneField(
        Organization,
        related_name="internal_client",
        on_delete=models.CASCADE,
        blank=True,
    )
    name = models.CharField(max_length=255, blank=True)
    brand_name = models.CharField(max_length=255, blank=True)
    website = models.URLField(max_length=255, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    pan = models.CharField(max_length=10, blank=True)
    is_signed = models.BooleanField(default=False)
    client_level = models.IntegerField(default=0)
    initial_free_interviews_allocation = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0)]
    )
    assigned_to = models.ForeignKey(
        HDIPUsers,
        on_delete=models.SET_NULL,
        related_name="internalclients",
        null=True,
        blank=True,
    )
    address = models.TextField(max_length=255, blank=True)
    code = models.CharField(max_length=15, default="INR", help_text="Country code")

    def __str__(self):
        return self.name


class ClientPointOfContact(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()

    client = models.ForeignKey(
        InternalClient,
        related_name="points_of_contact",
        on_delete=models.CASCADE,
        blank=True,
    )
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(unique=True, blank=True)
    phone = PhoneNumberField(region="IN", unique=True, blank=True)

    def __str__(self):
        return self.name


class DesignationDomain(CreateUpdateDateTimeAndArchivedField):
    name = models.CharField(max_length=15, blank=True, unique=True)

    def __str__(self) -> str:
        return self.name


class InternalInterviewer(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()

    ROLE_CHOICES = (
        ("SDE_I", "SDE-I"),
        ("SDE_II", "SDE-II"),
        ("SDE_III", "SDE-III"),
        ("PE", "Principal Engineer"),
        ("EM", "Engineering Manager"),
        ("TL", "Technical Lead"),
        ("VPE", "VP Engineering"),
        ("DOE", "Director of Engineering"),
        ("DE", "DevOps Engineer"),
        ("SR_DE", "Senior DevOps Engineer"),
        ("LD_DE", "Lead DevOps Engineer"),
        ("SDET", "SDET"),
        ("SR_SDET", "Sr. SDET"),
        ("MGR_SDET", "Manager-SDET"),
        ("DIR_SDET", "Director-SDET"),
        ("MLS", "ML Scientist"),
        ("SR_MLS", "Sr. ML Scientist"),
        ("LD_MLS", "Lead ML Scientist"),
        ("P_MLS", "Principal ML Scientist"),
        ("DEE", "Data Engineer"),
        ("SR_DEE", "Sr. Data Engineer"),
        ("LD_DEE", "Lead Data Engineer"),
        ("P_DEE", "Principal Data Engineer"),
        ("SEM", "Senior Engineering Manager"),
        ("SPM", "Senior Principal Engineer"),
        ("STL", "Senior Technical Lead"),
        ("AVPE", "AVP Engineer"),
        ("SDE", "Senior Director Of Engineering"),
        ("SM_SDET", "Senior Manager SDET"),
        ("SP_MLS", "Senior Principal ML Scientist"),
        ("SL_DEE", "Senior Lead Data Engineer"),
        ("SP_DEE", "Senior Principal Data Engineer"),
        ("IN", "Intern"),
        ("AR", "Architecht"),
        ("SA", "Senior Architect"),
        ("PA", "Principal Architect"),
        ("QAE", "QA Engineer"),
        ("RS_II", "Research Scientist II"),
    )

    STRENGTH_CHOICES = (
        ("frontend", "Frontend"),
        ("backend", "Backend"),
        ("fullstack", "Fullstack"),
        ("aiml", "AI/ML"),
        ("devops", "DevOps"),
        ("data_engineer", "Data Engineering"),
        ("testing", "Testing/QA"),
        ("android", "Android"),
        ("ios", "iOS"),
        ("mobile", "Mobile (Android + iOS)"),
        ("flutter", "Flutter"),
        ("database", "Database"),
        ("cloud", "Cloud"),
        ("mobile_flutter", "Mobile (Flutter)"),
        ("mobile_react_native", "Mobile (React Native)"),
    )

    organization = models.ManyToManyField(
        Organization, related_name="interviewers", blank=True
    )
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="interviewer", blank=True
    )
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(unique=True, blank=True)
    phone_number = PhoneNumberField(region="IN", unique=True, blank=True)
    current_company = models.CharField(max_length=255, blank=True)
    previous_company = models.CharField(max_length=255, blank=True)
    current_designation = models.CharField(max_length=255, blank=True)
    total_experience_years = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1, message="Expereince should be more than 1 year"),
            MaxValueValidator(50, message="Enter a valid Experience"),
        ],
    )
    total_experience_months = models.PositiveSmallIntegerField(default=0)
    interview_experience_years = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1, message="Expereince should be more than 1 year"),
            MaxValueValidator(50, message="Enter a valid Experience"),
        ],
    )
    interview_experience_months = models.PositiveSmallIntegerField(default=0)
    assigned_domains = models.ManyToManyField(
        DesignationDomain, related_name="interviewers", blank=True
    )
    skills = models.JSONField(default=list, blank=True)  # e.g., ["Java", "Python"]
    strength = models.CharField(
        max_length=50, blank=True, choices=STRENGTH_CHOICES
    )  # e.g., Backend
    cv = models.FileField(upload_to="interviewer_cvs", blank=True, null=True)
    interviewer_level = models.IntegerField(default=0)
    account_number = models.CharField(
        max_length=20, help_text="bank a/c number", null=True, blank=True
    )
    ifsc_code = models.CharField(
        max_length=15, help_text="bank ifsc code", null=True, blank=True
    )
    social_links = models.JSONField(
        default=dict,
        blank=True,
        help_text="A dictionary of social media links related to the interviewer.",
    )
    is_bank_account_updated = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.email}) - {self.current_company}, {self.total_experience_years}y exp"

    def save(self, *args, **kwargs):
        if self.name:
            self.user.profile.name = self.name
            self.user.profile.save()
        return super().save(*args, **kwargs)


class Agreement(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()

    YEARS_OF_EXPERIENCE_CHOICES = (
        ("0-4", "0 - 4 Years"),
        ("4-6", "4 - 6 Years"),
        ("6-8", "6 - 8 Years"),
        ("8-10", "8 - 10 Years"),
        ("10+", "10+ Years"),
    )

    organization = models.ForeignKey(
        Organization,
        related_name="agreements",
        blank=True,
        on_delete=models.SET_NULL,
        null=True,
    )

    years_of_experience = models.CharField(
        max_length=50, choices=YEARS_OF_EXPERIENCE_CHOICES, blank=True
    )
    rate = models.DecimalField(max_digits=10, decimal_places=2, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "years_of_experience"]),
        ]

    def __str__(self):
        return f"Organization ID - {self.organization_id} - ₹{self.rate}"

    @classmethod
    def get_years_of_experience(cls, year, month):
        if year < 4 or (year == 4 and month == 0):
            return "0-4"
        elif year < 6 or (year == 6 and month == 0):
            return "4-6"
        elif year < 8 or (year == 8 and month == 0):
            return "6-8"
        elif year < 10 or (year == 10 and month == 0):
            return "8-10"
        else:
            return "10+"


class InterviewerPricing(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()

    EXPERIENCE_LEVEL_CHOICES = [
        ("0-4", "0 - 4 Years"),
        ("4-7", "4 - 7 Years"),
        ("7-10", "7 - 10 Years"),
        ("10+", "10+ Years"),
    ]

    experience_level = models.CharField(
        max_length=10, choices=EXPERIENCE_LEVEL_CHOICES, unique=True
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True)

    def __str__(self):
        return f"{self.experience_level} - ₹{self.price}"

    @classmethod
    def get_year_of_experience(cls, year, month):
        if year < 4 or (year == 4 and month == 0):
            return "0-4"
        elif year < 7 or (year == 7 and month == 0):
            return "4-7"
        elif year < 10 or (year == 10 and month == 0):
            return "7-10"
        else:
            return "10+"
