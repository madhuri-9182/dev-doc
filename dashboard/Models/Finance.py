import uuid
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from hiringdogbackend.ModelUtils import SoftDelete, CreateUpdateDateTimeAndArchivedField
from .Internal import InternalClient, InternalInterviewer
from .Client import Organization
from .Internal import InternalInterviewer
from .Interviews import Interview


class BillingLog(CreateUpdateDateTimeAndArchivedField):
    BILLING_REASON_CHOICES = [
        ("feedback_submitted", "Feedback Submitted"),
        ("late_rescheduled", "Late Rescheduled"),
        ("free_feedback", "Initial Free Interviewer Feedback Submission for Client"),
    ]
    STATUS_CHOICES = (
        ("PED", "Pending"),
        ("PAI", "Paid"),
    )

    interview = models.ForeignKey(Interview, on_delete=models.CASCADE)
    client = models.ForeignKey(Organization, on_delete=models.CASCADE)
    interviewer = models.ForeignKey(InternalInterviewer, on_delete=models.CASCADE)

    amount_for_client = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_for_interviewer = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )

    reason = models.CharField(max_length=50, choices=BILLING_REASON_CHOICES)
    billing_month = models.DateField()
    is_billing_calculated = models.BooleanField(default=False)
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default="PED",
        db_index=True,
        help_text="This field signifies client payment status",
    )
    interviewer_payment_status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default="PED",
        db_index=True,
        help_text="This field signifies interveiwer payment status",
    )
    late_feedback_submission_deduction = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    is_interviewer_feedback_submitted_late = models.BooleanField(
        default=False, help_text="signifies the late feedback submission by interviewer"
    )

    class Meta:
        unique_together = (("interview", "reason"),)
        indexes = [
            models.Index(
                fields=["client", "billing_month", "status"],
                name="client_billing_status_idx",
            ),
            models.Index(
                fields=["interviewer", "billing_month", "status"],
                name="interviewer_billing_status_idx",
            ),
        ]


class BillingRecord(CreateUpdateDateTimeAndArchivedField):
    RECORD_TYPE_CHOICES = (
        ("CLB", "Client Billing"),
        ("INP", "Interviewer Payment"),
    )

    STATUS_CHOICES = (
        ("PED", "Pending"),
        ("PAI", "Paid"),
        ("OVD", "Overdue"),
        ("CAN", "Cancelled"),
        ("FLD", "Failed"),
        ("INP", "Inprogress"),
        ("MMP", "Mid-Month Payment"),
        ("PIP", "Post Invoice, Pre Due"),
        ("LTD", "Late Payment"),
    )

    objects = SoftDelete()
    object_all = models.Manager()

    # public_id is exposed to the frontend
    public_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, db_index=True
    )
    billing_month = models.DateField(
        db_index=True, editable=False
    )  # stores first day of month

    record_type = models.CharField(
        max_length=15, choices=RECORD_TYPE_CHOICES, null=True, blank=True
    )
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="PED")

    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount_received_without_tax = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total amount received for this month without tax. This field is automatically updated by the system.",
        editable=False,
        default=0,
    )
    total_amount_received_with_tax = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total amount received for this month with tax. This field is automatically updated by the system.",
        editable=False,
        default=0,
    )

    due_date = models.DateField()

    invoice_number = models.CharField(max_length=20, unique=True, null=True, blank=True)

    client = models.ForeignKey(
        InternalClient,
        on_delete=models.CASCADE,
        related_name="finance_records",
        null=True,
        blank=True,
    )
    interviewer = models.ForeignKey(
        InternalInterviewer,
        on_delete=models.CASCADE,
        related_name="finance_records",
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["record_type", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "billing_month"],
                name="unique_client_billing_per_month",
            ),
            models.UniqueConstraint(
                fields=["interviewer", "billing_month"],
                name="unique_interviewer_billing_per_month",
            ),
        ]

    def __str__(self):
        if self.record_type == "CLB":
            return f"Client Billing for Client ID{self.client_id} - ₹{self.amount_due} - {self.billing_month.strftime('%B %Y')}"
        return f"Interviewer Payment for Interview ID {self.interviewer_id} - ₹{self.amount_due} - {self.billing_month.strftime('%B %Y')}"

    def save(self, *args, **kwargs):
        if self.record_type == "CLB" and not self.client:
            raise ValidationError("Client is required for client billing records")
        if self.record_type == "INP" and not self.interviewer:
            raise ValidationError(
                "Interviewer is required for interviewer payment records"
            )
        if not self.billing_month:
            self.billing_month = timezone.now().replace(day=1).date()
        super().save(*args, **kwargs)


class BillPayments(CreateUpdateDateTimeAndArchivedField):
    objects = SoftDelete()
    object_all = models.Manager()

    PAYMENT_STATUS_CHOICES = [
        ("SUC", "Success"),
        ("FLD", "Failed"),
        ("UDP", "User Dropped"),
        ("CNL", "Cancelled"),
        ("VOD", "Void"),
        ("PED", "Pending"),
        ("INA", "Inactive"),
    ]

    LINK_STATUS_CHOICES = [
        ("PAID", "Paid"),
        ("PRT", "Partially Paid"),
        ("EXP", "Expired"),
        ("CNL", "Cancelled"),
    ]

    billing_record = models.ForeignKey(
        BillingRecord, on_delete=models.DO_NOTHING, related_name="billing_payments"
    )
    billing_logs = models.ManyToManyField(BillingLog)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="The original amount of the bill without any taxes or adjustments",
    )
    amount_received = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="The total amount received including any applicable taxes",
    )
    payment_link_id = models.CharField(max_length=100, unique=True, db_index=True)
    payment_link_url = models.URLField(null=True, blank=True)
    payment_status = models.CharField(
        max_length=15, choices=PAYMENT_STATUS_CHOICES, default="PED"
    )
    link_status = models.CharField(
        max_length=15, choices=LINK_STATUS_CHOICES, null=True, blank=True
    )
    payment_date = models.DateField(auto_now_add=True)
    transaction_id = models.CharField(
        max_length=100, unique=True, null=True, blank=True
    )
    link_expired_time = models.DateTimeField()
    cf_link_id = models.CharField(max_length=100, unique=True)
    order_id = models.CharField(max_length=100, unique=True, null=True, blank=True)

    # Customer Details
    customer_name = models.CharField(max_length=255)
    customer_phone = models.CharField(max_length=15)
    customer_email = models.EmailField()

    # both link generation and webhook response
    meta_data = models.JSONField(default=dict)
