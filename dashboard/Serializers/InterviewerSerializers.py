import pytz
import json
import calendar
import datetime
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from rest_framework import serializers
from ..models import (
    InterviewerAvailability,
    Candidate,
    Interview,
    InterviewFeedback,
    InternalInterviewer,
    Job,
    BillingLog,
    BillingRecord,
    InterviewerPricing,
    Agreement,
    JobInterviewRounds,
)
from hiringdogbackend.utils import validate_incoming_data, validate_attachment


class RecurrenceSerializer(serializers.Serializer):
    frequency = serializers.ChoiceField(
        choices=[
            ("WEEKLY", "Weekly"),
            ("DAILY", "Daily"),
            ("MONTHLY", "Monthly"),
            ("YEARLY", "Yearly"),
            ("HOURLY", "Hourly"),
            ("MINUTELY", "Minutely"),
            ("SECONDLY", "Secondly"),
        ],
        error_messages={
            "invalid_choice": "This is an invalid choice. Valid choices are WEEKLY, DAILY, MONTHLY, YEARLY, HOURLY, MINUTELY, SECONDLY."
        },
    )
    intervals = serializers.IntegerField(min_value=1, max_value=90, required=False)
    count = serializers.IntegerField(min_value=1, max_value=250, required=False)
    until = serializers.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M:%S"], format="%d/%m/%Y %H:%M", required=False
    )
    days = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[
                ("MO", "Monday"),
                ("TU", "Tuesday"),
                ("WE", "Wednesday"),
                ("TH", "Thursday"),
                ("FR", "Friday"),
                ("SA", "Saturday"),
                ("SU", "Sunday"),
            ],
            error_messages={
                "invalid_choice": "This is an invalid choice. Valid choices are MO, TU, WE, TH, FR, SA, SU."
            },
        ),
        required=False,
        min_length=1,
    )
    month_day = serializers.ListField(
        child=serializers.IntegerField(min_value=-31, max_value=31), required=False
    )
    year_day = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=365), required=False
    )

    def validate(self, data):
        frequency = data.get("frequency")
        if data.get("count") and data.get("until"):
            raise serializers.ValidationError(
                {"error": "Count and until date cannot be used simultaneously"}
            )

        invalid_keys = {
            "DAILY": ["byDay", "byMonthDay", "byYearDay"],
            "WEEKLY": ["byMonthDay", "byYearDay"],
            "MONTHLY": ["byYearDay"],
            "YEARLY": ["byMonthDay"],
        }[frequency]

        for key in invalid_keys:
            if data.get(key):
                raise serializers.ValidationError(
                    {"error": f"'{key}' is not applicable for {frequency} frequency."}
                )
        return data


class InterviewerAvailabilitySerializer(serializers.ModelSerializer):
    date = serializers.DateField(
        input_formats=["%d/%m/%Y"], format="%d/%m/%Y", required=False
    )
    start_time = serializers.TimeField(input_formats=["%H:%M"], required=False)
    end_time = serializers.TimeField(input_formats=["%H:%M"], required=False)
    recurrence = RecurrenceSerializer(write_only=True, required=False)

    class Meta:
        model = InterviewerAvailability
        fields = (
            "id",
            "interviewer",
            "date",
            "start_time",
            "end_time",
            "recurrence",
            "is_booked",
            "booked_by",
            "notes",
        )
        read_only_fields = ["interviewer"]

    def validate(self, data):
        interviewer_user = self.context["interviewer_user"]
        required_keys = [
            "date",
            "start_time",
            "end_time",
        ]
        allowed_keys = ["notes", "recurrence"]

        errors = validate_incoming_data(
            self.initial_data,
            required_keys,
            allowed_keys,
            partial=self.partial,
        )

        """ --> commented this for temporary
        if not self.partial and not data.get("recurrence"):
            errors.append(
                {
                    "recurrence": "This field is required.",
                    "schema": {
                        "frequency": "string",
                        "interval": "integer",
                        "count": "integer",
                        "until": "date",
                        "days": "integer",
                        "month_day": "integer",
                        "year_day": "integer",
                    },
                }
            )
        """

        if errors:
            raise serializers.ValidationError({"errors": errors})

        overlapping_slots = InterviewerAvailability.objects.filter(
            interviewer=interviewer_user,
            date=data.get("date"),
            start_time__lt=data.get("end_time"),
            end_time__gt=data.get("start_time"),
        )
        if overlapping_slots.exists():
            errors.setdefault("availability", []).append(
                "Interviewer already available at this date and time."
            )

        if data["date"] < datetime.datetime.now().date():
            errors.setdefault("date", []).append("Invalid date. Date can't in past")

        current_time = datetime.datetime.now().time()
        if data["end_time"] <= data["start_time"]:
            errors.setdefault("end_time", []).append(
                "end_time must be after start_time"
            )
        if data["date"] == datetime.datetime.now().date() and (
            data["start_time"] <= current_time or data["end_time"] <= current_time
        ):
            errors.setdefault("start_time & date_time", []).append(
                "start_time and end_time must be in the future for today"
            )

        if errors:
            raise serializers.ValidationError({"errors": errors})

        data["date"] = datetime.datetime.strptime(str(data["date"]), "%Y-%m-%d").date()

        return data

    def create(self, validated_data):
        validated_data.pop("recurrence", None)
        return super().create(validated_data)


class InterviewerRequestSerializer(serializers.Serializer):
    candidate_id = serializers.IntegerField(min_value=0)
    interviewer_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1
    )
    date = serializers.DateField(input_formats=["%d/%m/%Y"])
    time = serializers.TimeField(input_formats=["%H:%M"])

    def validate(self, data):
        request = self.context.get("request")
        errors = {}

        candidate = (
            Candidate.objects.select_for_update()
            .filter(
                organization=request.user.clientuser.organization,
                pk=data.get("candidate_id"),
            )
            .first()
        )
        if not candidate:
            errors.setdefault("candidate_id", []).append("Invalid candidate_id")

        if (
            candidate.status not in ["NSCH", "SCH", "CSCH", "NJ"]
            and not candidate.next_round
        ):
            errors.setdefault("candidate_id", []).append(
                "Candidate is already scheduled and processed. Rescheduling can't be done."
            )

        # after rescheduling implementation commented out the below thing
        # if (
        #     candidate.last_scheduled_initiate_time
        #     and timezone.now()
        #     < candidate.last_scheduled_initiate_time + datetime.timedelta(hours=1)
        # ):
        #     errors.setdefault("candidate_id", []).append(
        #         "Can't reinitiate the scheduling for 1 hour. Previous scheduling is in progress"
        #     )

        valid_interviewer_ids = set(
            InterviewerAvailability.objects.filter(
                pk__in=data.get("interviewer_ids")
            ).values_list("id", flat=True)
        )
        invalid_interviewer_ids = (
            set(data.get("interviewer_ids", [])) - valid_interviewer_ids
        )
        if invalid_interviewer_ids:
            errors.setdefault("interviewer_ids", []).append(
                f"Invalid interviewers ids: {', '.join(map(str, invalid_interviewer_ids))}"
            )

        if errors:
            raise serializers.ValidationError({"errors": errors})

        data["candidate_obj"] = candidate

        return data


class InterviewerJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ("id", "name", "job_description_file")


class InterviewerJobInterviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobInterviewRounds
        fields = ("other_details",)


class InterviewerCandidateSerializer(serializers.ModelSerializer):
    designation = InterviewerJobSerializer(read_only=True)
    question_bank = InterviewerJobInterviewSerializer(
        read_only=True, source="next_round"
    )

    class Meta:
        model = Candidate
        fields = (
            "id",
            "name",
            "designation",
            "specialization",
            "year",
            "month",
            "company",
            "question_bank",
        )


class QuestionSerializer(serializers.Serializer):
    que = serializers.CharField(max_length=1000, allow_blank=True)
    ans = serializers.CharField(max_length=5000, allow_blank=True)


class TopicSerializer(serializers.Serializer):
    summary = serializers.CharField(max_length=1000, allow_blank=True)
    score = serializers.IntegerField(min_value=0, max_value=100)
    start_time = serializers.IntegerField(required=False)
    end_time = serializers.IntegerField(required=False)
    questions = serializers.ListSerializer(child=QuestionSerializer(), min_length=1)


class SkillBasedPerformanceSerializer(serializers.Serializer):
    def validate(self, data):
        if not data:
            raise serializers.ValidationError("At least one skill must be provided.")

        # Check for duplicate skills (case-insensitive)
        skill_keys_lower = [key.lower() for key in data.keys()]
        if len(skill_keys_lower) != len(set(skill_keys_lower)):
            raise serializers.ValidationError("Duplicate skills are not allowed.")

        return data

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a dictionary of skills.")

        validated_data = {}
        errors = {}

        for skill_name, skill_data in data.items():
            if not isinstance(skill_data, dict):
                errors[skill_name] = (
                    "Each skill should have summary, score, start_time, end_time and questions."
                )
                continue

            topic_serializer = TopicSerializer(data=skill_data)
            if not topic_serializer.is_valid():
                errors[skill_name] = topic_serializer.errors
            else:
                validated_data[skill_name] = topic_serializer.validated_data

        if errors:
            raise serializers.ValidationError(errors)

        return validated_data

    def to_representation(self, instance):
        return instance  # Ensure full validated data is returned


class SkillEvaluationSerializer(serializers.Serializer):
    """Validate skill evaluation dictionary"""

    ALLOWED_CHOICES = ["poor", "average", "good", "excellent"]
    REQUIRED_EVALUATIONS = ["Communication", "Attitude"]

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                "Expected a dictionary for skill evaluations."
            )

        validated_data = {}
        errors = {}

        # Validate choices first
        for skill, rating in data.items():
            if rating not in self.ALLOWED_CHOICES:
                errors.setdefault(skill, []).append(
                    f"Invalid value '{rating}'. Allowed values: {self.ALLOWED_CHOICES}."
                )

        # Only check for missing required fields if there are no validation errors yet
        if not errors:
            missing_required = [
                skill for skill in self.REQUIRED_EVALUATIONS if skill not in data
            ]
            if missing_required:
                for skill in missing_required:
                    errors.setdefault(skill, []).append(
                        f"{skill} evaluation is required."
                    )

        if errors:
            raise serializers.ValidationError(errors)

        return validated_data

    def to_representation(self, instance):
        return instance  # Ensure full validated data is returned


class InterviewerFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternalInterviewer
        fields = (
            "name",
            "total_experience_years",
            "total_experience_months",
            "current_company",
        )


class CandidateFeedbackSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    recommended_score = serializers.IntegerField(
        source="designation.recommended_score", read_only=True
    )

    def get_role(self, obj):
        return obj.designation.get_name_display()

    class Meta:
        model = Candidate
        fields = (
            "name",
            "email",
            "phone",
            "year",
            "month",
            "company",
            "role",
            "current_designation",
            "specialization",
            "recommended_score",
        )


class InterviewFeedbackSerializer(serializers.ModelSerializer):
    skill_based_performance = serializers.DictField()
    skill_evaluation = serializers.DictField()
    interview_date = serializers.DateTimeField(
        source="interview.scheduled_time", format="%d/%m/%Y %H:%M:%S", read_only=True
    )
    recording_link = serializers.FileField(source="interview.recording", read_only=True)
    candidate = CandidateFeedbackSerializer(
        source="interview.candidate", read_only=True
    )
    interview_id = serializers.IntegerField()
    interviewer = InterviewerFeedbackSerializer(
        source="interview.interviewer", read_only=True
    )

    class Meta:
        model = InterviewFeedback
        fields = (
            "interview_id",
            "interview_date",
            "candidate",
            "interviewer",
            "is_submitted",
            "skill_based_performance",
            "skill_evaluation",
            "strength",
            "improvement_points",
            "overall_remark",
            "overall_score",
            "recording_link",
            "pdf_file",
            "attachment",
            "link",
        )
        read_only_fields = ("pdf_file",)

    def to_internal_value(self, data):
        data = data.copy()

        for field in ["skill_based_performance", "skill_evaluation"]:
            value = data.get(field)
            if isinstance(value, str):
                try:
                    data[field] = json.loads(value)
                except json.JSONDecodeError:
                    raise serializers.ValidationError({field: ["Invalid JSON format."]})

        skill_based_performance = data.get("skill_based_performance")
        if skill_based_performance:
            serializer = SkillBasedPerformanceSerializer(data=skill_based_performance)
            if not serializer.is_valid():
                raise serializers.ValidationError(
                    {"skill_based_performance": serializer.errors}
                )

        skill_evaluation = data.get("skill_evaluation")
        if skill_evaluation:
            serializer = SkillEvaluationSerializer(data=skill_evaluation)
            if not serializer.is_valid():
                raise serializers.ValidationError(
                    {"skill_evaluation": serializer.errors}
                )
        data = super().to_internal_value(data)
        if skill_based_performance:
            data["skill_based_performance"] = skill_based_performance
        if skill_evaluation:
            data["skill_evaluation"] = skill_evaluation
        return data

    def validate(self, data):
        errors = validate_incoming_data(
            self.initial_data,
            [
                "interview_id",
                "skill_based_performance",
                "skill_evaluation",
                "overall_remark",
                "overall_score",
            ],
            [
                "attachment",
                "link",
                "strength",
                "improvement_points",
            ],
            partial=self.partial,
            original_data=data,
            form=True,
        )
        if errors:
            raise serializers.ValidationError({"errors": errors})

        if data.get("interview_id"):
            if not str(data.get("interview_id")).isdigit():
                errors.setdefault("interview_id", []).append("Invalid interview_id")
            else:
                interview = Interview.objects.filter(
                    pk=data.get("interview_id")
                ).first()
                if not interview:
                    errors.setdefault("interview_id", []).append(
                        "No interview found for this interview_id"
                    )

        attachment = data.get("attachment")
        if attachment:
            errors.update(
                validate_attachment(
                    "attachment",
                    attachment,
                    ["docx", "doc", "pdf", "txt", "zip"],
                    5,
                )
            )

        if errors:
            raise serializers.ValidationError({"errors": errors})

        return data

    def late_feedback_submission(self, ai_feedback_generate_time, interview_end_time):
        """
        Calculates the late submission fine for feedback submission.

        :param ai_feedback_generate_time: The time when AI feedback was generated
        :param interview_end_time: The time when the interview ended
        :return: The fine amount
        """
        current_time = timezone.now()
        kolkata = pytz.timezone("Asia/Kolkata")

        current_time_kolkata = current_time.astimezone(kolkata)
        ai_feedback_time_kolkata = ai_feedback_generate_time.astimezone(kolkata)
        interview_end_kolkata = interview_end_time.astimezone(kolkata)

        # excluding the evening grace time for the same day only
        if interview_end_kolkata.time() > datetime.time(20, 30):
            ai_feedback_time_kolkata += datetime.timedelta(days=1)
            ai_feedback_time_kolkata = ai_feedback_time_kolkata.replace(
                hour=9, minute=0, second=0, microsecond=0
            )

        # Calculate the delay
        delay_start = ai_feedback_time_kolkata + datetime.timedelta(hours=1)
        elapsed = current_time_kolkata - delay_start

        # Calculate the fine
        delay_in_hours = elapsed.total_seconds() / 3600
        if delay_in_hours <= 1:
            fine = 0
        elif 1 < delay_in_hours <= 2:
            fine = 100
        elif 2 < delay_in_hours <= 3:
            fine = 300
        elif 3 < delay_in_hours <= 5:
            fine = 500
        elif 5 < delay_in_hours <= 8:
            fine = 700
        else:
            fine = 1000

        return fine

    def update(self, instance, validated_data):
        with transaction.atomic():
            feedback = super().update(instance, validated_data)

            interview = instance.interview
            candidate = interview.candidate
            interviewer = interview.interviewer
            client = candidate.organization
            client_profile = client.internal_client
            billing_month = timezone.now().replace(day=1).date()

            # update candidate next round
            if instance.overall_remark != "NJ":
                candidate.last_completed_round = candidate.next_round
                next_job_interview_round = JobInterviewRounds.objects.filter(
                    job=candidate.designation,
                    sequence_number__gt=candidate.next_round.sequence_number,
                ).first()

                if next_job_interview_round is not None:
                    candidate.next_round = next_job_interview_round
                else:
                    candidate.next_round = None

                candidate.save()

            # Fetch experience levels
            interviewer_exp = InterviewerPricing.get_year_of_experience(
                candidate.year, candidate.month
            )
            client_exp = Agreement.get_years_of_experience(
                candidate.year, candidate.month
            )

            try:
                interviewer_pricing = InterviewerPricing.objects.get(
                    experience_level=interviewer_exp
                )
                client_pricing = Agreement.objects.get(
                    organization=client, years_of_experience=client_exp
                )
            except (InterviewerPricing.DoesNotExist, Agreement.DoesNotExist):
                raise serializers.ValidationError(
                    "Pricing information not configured for given experience."
                )

            # Calculate amounts
            interviewer_amount = interviewer_pricing.price
            client_amount = client_pricing.rate

            if instance.overall_remark == "NJ":
                interviewer_amount = (
                    settings.INTERVIEWER_LATE_RESCHEDULE_CANCEL_AND_NOT_JOINED_AMOUNT
                )
                client_amount = (
                    settings.CLIENT_LATE_RESCHEDULE_CANCEL_AND_NOT_JOINED_AMOUNT
                )

            if client_profile.initial_free_interviews_allocation > 0:
                client_amount = 0
                client_profile.initial_free_interviews_allocation -= 1
                client_profile.save()

            billinglog, _ = BillingLog.objects.get_or_create(
                interview=interview,
                reason="feedback_submitted",
                defaults={
                    "billing_month": billing_month,
                    "client": client,
                    "interviewer": interviewer,
                    "amount_for_client": client_amount,
                    "amount_for_interviewer": interviewer_amount,
                },
            )

            # fine calculation in case of appered interview
            if instance.overall_remark != "NJ":
                fine_amount = self.late_feedback_submission(
                    billinglog.interview.interview_feedback.created_at,
                    billinglog.interview.scheduled_time + datetime.timedelta(hours=1),
                )

            if not billinglog.is_billing_calculated:
                # fine deduction
                if fine_amount:
                    interviewer_amount -= fine_amount
                    billinglog.amount_for_interviewer = interviewer_amount
                    billinglog.late_feedback_submission_deduction = fine_amount
                    billinglog.is_interviewer_feedback_submitted_late = True

                today = timezone.now()
                end_of_month = calendar.monthrange(today.year, today.month)[1]
                due_date = (
                    today.replace(day=end_of_month) + datetime.timedelta(days=10)
                ).date()

                # Update Client BillingRecord
                client_record, _ = BillingRecord.objects.get_or_create(
                    client=client.internal_client,
                    billing_month=billing_month,
                    defaults={
                        "record_type": "CLB",
                        "amount_due": client_amount,
                        "due_date": due_date,
                        "status": "PED",
                    },
                )
                if not _:
                    client_record.amount_due += client_amount
                    client_record.save()

                # Update Interviewer BillingRecord
                interviewer_record, _ = BillingRecord.objects.get_or_create(
                    interviewer=interviewer,
                    billing_month=billing_month,
                    defaults={
                        "record_type": "INP",
                        "amount_due": interviewer_amount,
                        "due_date": due_date,
                        "status": "PED",
                    },
                )
                if not _:
                    interviewer_record.amount_due += interviewer_amount
                    interviewer_record.save()

                if not billinglog.amount_for_client:
                    billinglog.status = "PAI"
                    billinglog.reason = "free_feedback"

                billinglog.is_billing_calculated = True
                billinglog.save()

            return feedback


class InterviewerDashboardSerializer(serializers.ModelSerializer):
    candidate = InterviewerCandidateSerializer(read_only=True)
    scheduled_time = serializers.DateTimeField(format="%d/%m/%Y %H:%M:%S")

    class Meta:
        model = Interview
        fields = ("id", "candidate", "scheduled_time", "meeting_link")


class InterviewerBankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternalInterviewer
        fields = ("account_number", "ifsc_code")

    def validate(self, data):
        errors = validate_incoming_data(
            self.initial_data, [], ["account_number", "ifsc_code"], self.partial
        )

        if errors:
            raise serializers.ValidationError(errors)

        return data
