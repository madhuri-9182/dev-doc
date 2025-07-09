from django.db import models
from django.utils.timezone import now
from core.models import User
from .Internal import InternalInterviewer
from .Interviews import Interview
from hiringdogbackend.ModelUtils import CreateUpdateDateTimeAndArchivedField, SoftDelete


class InterviewerAvailability(CreateUpdateDateTimeAndArchivedField):
    object_all = SoftDelete()
    objects = models.Manager()

    interviewer = models.ForeignKey(
        InternalInterviewer,
        on_delete=models.CASCADE,
        related_name="interviewer_availability",
        help_text="The interviewer associated with it's availability.",
        blank=True,
    )
    date = models.DateField(help_text="The date of the availability", blank=True)
    start_time = models.TimeField(
        help_text="The start time of the availability.", blank=True
    )
    end_time = models.TimeField(
        help_text="The end time of the slot availability.", blank=True
    )
    booked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booked_slots",
        help_text="The user who booked the slot, if any.",
    )
    notes = models.TextField(
        blank=True, null=True, help_text="Additional notes for the slot booking."
    )
    is_scheduled = models.BooleanField(default=False)
    google_calendar_id = models.CharField(max_length=255, blank=True)
    recurrence_rule = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ["date", "start_time", "end_time"]
        unique_together = ("interviewer", "date", "start_time", "end_time")
        verbose_name = "Interviewer Slot Booking"
        verbose_name_plural = "Interviewer Slot Bookings"

    def __str__(self):
        return f"Slot for Interviewer ID {self.interviewer_id} at {self.start_time}"

    @property
    def is_in_past(self):
        """
        Check if the slot time is in the past.
        """
        return self.start_time < now()

    @property
    def is_booked(self):
        return self.booked_by is not None

    @property
    def is_recurrence(self):
        return self.recurrence_rule is not None


# currently model is in not used
class InterviewerRequest(CreateUpdateDateTimeAndArchivedField):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
    )

    interviewer = models.ForeignKey(
        InternalInterviewer,
        on_delete=models.CASCADE,
        related_name="interview_requests",
    )
    interview = models.ForeignKey(
        Interview, on_delete=models.CASCADE, related_name="interviewer_requests"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("interviewer", "interview")

    def __str__(self):
        return f"Interviewer ID {self.interviewer_id} requested to conduct interview ID {self.interview_id} - {self.status}"
