import uuid
from organizations.models import Organization
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from phonenumber_field.modelfields import PhoneNumberField
from core.models import User
from hiringdogbackend.ModelUtils import SoftDelete, CreateUpdateDateTimeAndArchivedField
from .Internal import InternalInterviewer


class ClientUser(CreateUpdateDateTimeAndArchivedField):
    STATUS_CHOICES = (
        ("ACT", "Active"),
        ("INACT", "Inactive"),
        ("PEND", "Pending"),
    )
    ACCESSIBILITY_CHOICES = (("AJ", "All jobs"), ("AGJ", "Assigned jobs"))

    objects = SoftDelete()
    object_all = models.Manager()

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="clientuser", blank=True
    )
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="clientuser", blank=True
    )
    name = models.CharField(max_length=100, blank=True)
    designation = models.CharField(
        max_length=100,
        blank=True,
        null=True,  # Allows null values to prevent empty strings from being stored as null
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="invited_by_clientuser",
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        blank=True,
        help_text="verification status",
        default="PEND",
    )
    last_invitation_notification_time = models.DateTimeField(null=True, blank=True)
    accessibility = models.CharField(
        max_length=5, choices=ACCESSIBILITY_CHOICES, blank=True, default="AJ"
    )

    class Meta:
        indexes = [
            models.Index(fields=["name", "status"]),
        ]


class Department(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="departments", blank=True
    )
    name = models.CharField(max_length=255, blank=True, null=True, db_index=True)


class Job(CreateUpdateDateTimeAndArchivedField):
    REASON_FOR_ARCHIVED_CHOICES = (
        ("PF", "Position Filled"),
        ("POH", "Position On Hold"),
        ("OTH", "Other"),
    )
    objects = SoftDelete()
    object_all = models.Manager()
    clients = models.ManyToManyField(ClientUser, related_name="jobs", blank=True)
    name = models.CharField(
        max_length=15,
        choices=InternalInterviewer.ROLE_CHOICES,
        blank=True,
        db_index=True,
    )
    job_id = models.CharField(max_length=100, blank=True, null=True)
    hiring_manager = models.ForeignKey(
        ClientUser,
        on_delete=models.CASCADE,
        related_name="hiringmanager",
        blank=True,
    )
    min_exp = models.PositiveIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(50)], null=True, blank=True
    )
    max_exp = models.PositiveIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(50)], null=True, blank=True
    )
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="jobs", blank=True, null=True
    )
    total_positions = models.PositiveSmallIntegerField(default=0)
    specialization = models.CharField(max_length=100, blank=True, null=True)
    recommended_score = models.PositiveSmallIntegerField(
        default=80, validators=[MinValueValidator(60), MaxValueValidator(80)]
    )
    job_description_file = models.FileField(upload_to="job_descriptions", blank=True)
    mandatory_skills = models.JSONField(default=list, blank=True)
    reason_for_archived = models.CharField(
        max_length=15, choices=REASON_FOR_ARCHIVED_CHOICES, blank=True, null=True
    )
    is_diversity_hiring = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class JobInterviewRounds(CreateUpdateDateTimeAndArchivedField):
    DURATION_MINUTES_CHOICES = (
        (60, "1 hour"),
        (90, "1.5 hours"),
        (120, "2 hours"),
    )

    objects = SoftDelete()
    object_all = models.Manager()
    job = models.ForeignKey(
        Job, on_delete=models.CASCADE, related_name="interview_rounds"
    )
    name = models.CharField(
        max_length=50,
        help_text="Name of the round",
        null=True,
        blank=True,
    )
    duration_minutes = models.IntegerField(
        choices=DURATION_MINUTES_CHOICES,
        default=60,
        help_text="Interview duration",
    )
    sequence_number = models.PositiveSmallIntegerField(
        default=1, help_text="The order of this interview round within the job"
    )
    other_details = models.JSONField(default=dict, blank=True, null=True)

    def __str__(self):
        return f"{self.name}-{self.sequence_number}-{self.job_id}"


class Candidate(CreateUpdateDateTimeAndArchivedField):
    STATUS_CHOICES = (
        # Scheduling Statuses
        # Scheduled is only use for the client candidate when client initiate the scheduling
        ("SCH", "Scheduled"),
        # Complete Scheduled is basically represent that interviewer accepted it.
        ("CSCH", "Compete Scheduled"),
        ("NSCH", "Not Scheduled"),
        ("RESCH", "Rescheduled"),
        ("NJ", "Not Joined"),
        # Evaluation Statuses
        ("PENDING_EVAL", "Pending Evaluation"),
        ("COMPLETED", "Completed"),
        ("HREC", "Highly Recommended"),
        ("REC", "Recommended"),
        ("NREC", "Not Recommended"),
        ("SNREC", "Strongly Not Recommended"),
    )
    REASON_FOR_DROPPING_CHOICES = (
        ("CNI", "Candidate Not Interested"),
        ("CNA", "Candidate Not Available"),
        ("CNR", "Candidate Not Responded"),
        ("OTH", "Others"),
        ("RJD", "Rejected By HDIP"),
        ("NJ", "Not Joined Candidate"),
        ("MSD", "Multi Select Delete"),
    )
    FINAL_SELECTION_STATUS_CHOICES = (
        ("R1R", "Round 1 Reject"),
        ("R2R", "Round 2 Reject"),
        ("R3R", "Round 3 Reject"),
        ("R4R", "Round 4 Reject"),
        ("OFD", "Offer Decline"),
        ("HMR", "HM Reject"),
        ("SLD", "Selected"),
        ("HD", "Hold"),
    )
    SOURCE_CHOICES = (("INT", "Internal"), ("AGN", "Agency"))
    GENDER_CHOICES = (("M", "Male"), ("F", "Female"), ("TG", "Transgender"))
    SPECIALIZATION_CHOICES = (
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
    INTERVIEW_TYPE_CHOICES = (
        ("AI", "AI Interview"),
        ("P2P", "Peer to Peer Interview"),
    )
    objects = SoftDelete()
    object_all = models.Manager()
    name = models.CharField(max_length=100, blank=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="candidate"
    )
    year = models.PositiveSmallIntegerField(
        default=0, help_text="candidate experience total year"
    )
    month = models.PositiveBigIntegerField(
        default=0, help_text="candidate experience total month"
    )
    phone = PhoneNumberField(region="IN", blank=True)
    email = models.EmailField(max_length=255, blank=True)
    company = models.CharField(max_length=100, blank=True)
    designation = models.ForeignKey(
        Job, on_delete=models.SET_NULL, related_name="candidate", null=True
    )
    current_designation = models.CharField(max_length=100, blank=True, null=True)
    source = models.CharField(
        max_length=3,
        blank=True,
        choices=SOURCE_CHOICES,
        help_text="From Which side this candidate is ?",
    )
    gender = models.CharField(
        max_length=2, choices=GENDER_CHOICES, blank=True, null=True
    )
    cv = models.FileField(upload_to="candidate_cvs", blank=True)
    remark = models.TextField(max_length=255, blank=True, null=True)
    specialization = models.CharField(
        max_length=100, blank=True, choices=SPECIALIZATION_CHOICES
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        blank=True,
        default="NSCH",
        help_text="candidate interview status",
    )
    reason_for_dropping = models.CharField(
        max_length=100, choices=REASON_FOR_DROPPING_CHOICES, blank=True, null=True
    )
    last_scheduled_initiate_time = models.DateTimeField(
        null=True,
        db_index=True,
        blank=True,
        help_text="Gives the clarity the weather reinitiate the schedule again or not.",
    )
    scheduled_time = models.DateTimeField(blank=True, null=True)
    score = models.PositiveSmallIntegerField(default=0)
    total_score = models.PositiveSmallIntegerField(default=0)
    final_selection_status = models.CharField(
        max_length=20, choices=FINAL_SELECTION_STATUS_CHOICES, null=True, blank=True
    )
    added_by = models.ForeignKey(
        ClientUser,
        on_delete=models.SET_NULL,
        related_name="candidates",
        blank=True,
        null=True,
    )
    last_completed_round = models.ForeignKey(
        JobInterviewRounds,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_candidates",
        help_text="The last round that the candidate has cleared",
    )
    next_round = models.ForeignKey(
        JobInterviewRounds,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="upcoming_candidates",
        db_index=True,
        help_text="The next interview round this candidate is supposed to attend",
    )
    is_engagement_pushed = models.BooleanField(default=False)
    interview_type = models.CharField(
        max_length=15, choices=INTERVIEW_TYPE_CHOICES, default="P2P"
    )

    def __str__(self):
        return f"Candidate: {self.name} (Organization ID: {self.organization_id})"


class Engagement(CreateUpdateDateTimeAndArchivedField):
    STATUS_CHOICE = (
        ("YTJ", "Yet to Join"),
        ("DBT", "Doubtful"),
        ("JND", "Joined"),
        ("DCL", "Declined"),
        ("OHD", "On Hold"),
    )

    NOTICE_PERIOD_CHOICE = (
        ("0-7", "0-7 days"),
        ("8-15", "8-15 days"),
        ("16-30", "16-30 days"),
        ("31-45", "31-45 days"),
        ("46-60", "46-60 days"),
        ("61-75", "61-75 days"),
        ("76-90", "76-90 days"),
    )

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="engagements",
        null=True,
        blank=True,
    )
    candidate_name = models.CharField(max_length=50, blank=True, null=True)
    candidate_email = models.EmailField(max_length=255, blank=True, null=True)
    candidate_phone = PhoneNumberField(region="IN", blank=True, null=True)
    candidate_cv = models.FileField(
        upload_to="engagement-candidate-cv", blank=True, null=True
    )
    job = models.CharField(max_length=255, blank=True, null=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="engagements"
    )
    gtp_email = models.EmailField(max_length=255, blank=True, null=True)
    gtp_name = models.CharField(max_length=50, blank=True, null=True)

    status = models.CharField(max_length=11, choices=STATUS_CHOICE, default="YTJ")
    notice_period = models.CharField(
        max_length=10, choices=NOTICE_PERIOD_CHOICE, default="16-30"
    )
    offered = models.BooleanField(default=False)
    offer_date = models.DateField(null=True, blank=True)
    offer_accepted = models.BooleanField(default=False)
    other_offer = models.BooleanField(default=False)

    def __str__(self):
        candidate_identifier = (
            self.candidate_name if self.candidate_name else f"ID: {self.candidate_id}"
        )
        return f"Candidate {candidate_identifier}, Status: {self.get_status_display()}"


class EngagementTemplates(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="engagementtemplates",
        blank=True,
    )
    template_name = models.CharField(max_length=255, blank=True)
    template_html_content = models.TextField(blank=True)
    subject = models.CharField(max_length=255, blank=True)
    attachment = models.FileField(
        upload_to="engagement_attachments/", blank=True, null=True
    )


class EngagementOperation(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()
    DELIVERY_STATUS_CHOICES = (
        ("PED", "Pending"),
        ("SUC", "Success"),
        ("FLD", "Failed"),
    )
    engagement = models.ForeignKey(
        Engagement, on_delete=models.CASCADE, related_name="engagementoperations"
    )
    template = models.ForeignKey(
        EngagementTemplates,
        on_delete=models.CASCADE,
        related_name="engagementoperations",
    )
    week = models.PositiveSmallIntegerField(blank=True)
    date = models.DateTimeField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivery_status = models.CharField(
        max_length=15,
        choices=DELIVERY_STATUS_CHOICES,
        default="PED",
        help_text="Email Delivery Status",
    )
    operation_complete_status = models.CharField(
        max_length=15,
        choices=DELIVERY_STATUS_CHOICES,
        default="PED",
        help_text="Operation Completation Status",
    )
    task_id = models.UUIDField(null=True, editable=False, blank=True)

    def __str__(self):
        return f"Template {self.template_id}: {self.get_delivery_status_display()} on {self.date.strftime('%d %b %Y')}"


class InterviewScheduleAttempt(CreateUpdateDateTimeAndArchivedField):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        Candidate, on_delete=models.CASCADE, related_name="scheduling_attempts"
    )
