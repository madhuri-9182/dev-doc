import re
from time import sleep
import datetime
import pandas as pd
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.db import transaction
from phonenumbers import parse, is_valid_number, NumberParseException
from dashboard.models import InternalInterviewer
from core.models import User, Role
from dashboard.tasks import send_email_to_multiple_recipients
from openpyxl import Workbook
from hiringdogbackend.utils import get_random_password

ONBOARD_EMAIL_TEMPLATE = "onboard.html"
WELCOME_MAIL_SUBJECT = "Welcome to Hiring Dog"
CONTACT_EMAIL = settings.EMAIL_HOST_USER if settings.DEBUG else settings.CONTACT_EMAIL
INTERVIEW_EMAIL = (
    settings.EMAIL_HOST_USER if settings.DEBUG else settings.INTERVIEW_EMAIL
)
CHANGE_EMAIL_NOTIFICATION_TEMPLATE = "user_email_changed_confirmation_notification.html"


class Command(BaseCommand):
    help = "Import interviewers from an Excel file"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to the Excel file")

    def handle(self, *args, **kwargs):
        file_path = kwargs["file_path"]
        df = pd.read_excel(file_path)

        df = df.rename(
            columns={
                "Full Name": "name",
                "Mail ID": "email",
                "Phone Number": "phone_number",
                "Alternate Number": "alternate_number",
                "Current Company (Please mention your last company if you are not working currently. Don't mention the registered name like Private Limited/Limited, etc simply mention the brand name)": "current_company",
                "Previous Company": "previous_company",
                "Current Designation": "current_designation",
                "Total Experience (Years & Months)": "total_experience",
                "Interview taking experience (Approx Years)": "interview_experience",
                "Strength": "strength",
                "Skills": "skills",
                "Level": "interviewer_level",
                "Bank Account Number": "account_number",
                "IFSC": "ifsc_code",
                "Linkdn Link": "social_links",
            }
        )

        failed_rows = []
        process_count = 0

        for i, row in df.iterrows():
            if process_count % 10 == 0:
                sleep(60)
            try:
                self.process_row(row)
            except Exception as e:
                failed_rows.append((i, row.get("email"), str(e)))
            process_count += 1

        if failed_rows:
            self.export_failed_rows(failed_rows)
            self.stdout.write(
                self.style.ERROR(f"{len(failed_rows)} rows failed to import.")
            )
        else:
            self.stdout.write(self.style.SUCCESS("All rows imported successfully."))

    def process_row(self, row):
        with transaction.atomic():
            email = row.get("email")
            name = row.get("name")
            phone = str(row.get("phone_number"))

            if not isinstance(email, str) or not email.strip():
                raise ValueError("Email is missing or invalid")
            if not isinstance(phone, str) or not phone.strip():
                raise ValueError("Phone number is missing")

            phone = self.normalize_phone(phone)
            try:
                parsed_number = parse(phone, "IN")
                if not is_valid_number(parsed_number):
                    raise ValueError("Invalid phone number")
            except NumberParseException:
                raise ValueError("Invalid phone number format")

            strength = self.get_strength_value(row.get("strength"))
            skills = self.get_skills(row.get("skills"))

            total_years, total_months = self.split_experience(
                row.get("total_experience")
            )
            interview_years, interview_months = self.split_experience(
                row.get("interview_experience")
            )

            role_mapping = self.get_role_mapping()
            domain_ids = role_mapping.get(str(total_years), [])

            password = get_random_password()

            user, user_created = User.objects.get_or_create(
                email=email, defaults={"phone": phone}
            )
            if user_created:
                user.set_password(password)
                user.role = Role.INTERVIEWER
                user.email_verified = False
                user.save()

                validated_data = {
                    "email": email,
                    "name": name,
                    "phone_number": phone,
                    "current_company": row.get("current_company", ""),
                    "previous_company": row.get("previous_company", ""),
                    "current_designation": row.get("current_designation", ""),
                    "total_experience_years": total_years,
                    "total_experience_months": total_months,
                    "interview_experience_years": interview_years,
                    "interview_experience_months": interview_months,
                    "strength": strength,
                    "skills": skills,
                    "interviewer_level": row.get("interviewer_level"),
                }

                interviewer_obj = InternalInterviewer.objects.create(
                    user=user, **validated_data
                )
                interviewer_obj.assigned_domains.add(*domain_ids)

                # Send emails
                verification_data = (
                    f"{user.id}:{int(datetime.datetime.now().timestamp() + 86400)}"
                )
                verification_data_uid = urlsafe_base64_encode(
                    force_bytes(verification_data)
                )

                contexts = [
                    {
                        "subject": "Welcome to Interview Platform",
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
                        "email": "ashok@mailsac.com",
                        "template": "internal_interviewer_onboarded_confirmation_notification.html",
                        "internal_user_name": "Admin",
                        "interviewer_name": interviewer_obj.name,
                        "onboarding_date": datetime.date.today().strftime("%d/%m/%Y"),
                    },
                ]
                send_email_to_multiple_recipients.delay(contexts, "", "")

                user.profile.name = name
                user.profile.save()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"User with email {email} is successfully created"
                    )
                )

            else:
                self.stdout.write(f"User with email {email} already exists. Skipping.")

    def split_experience(self, exp_value):
        try:
            if isinstance(exp_value, (int, float)):
                exp_str = str(exp_value)
            elif isinstance(exp_value, str):
                exp_str = exp_value.strip()
            else:
                return 0, 0

            parts = exp_str.split(".")
            if len(parts) == 1:
                return int(parts[0]), 0
            return int(parts[0]), int(parts[1])
        except Exception:
            return 0, 0

    def get_strength_value(self, value):
        if not isinstance(value, str):
            return None
        for db_value, human_value in InternalInterviewer.STRENGTH_CHOICES:
            if human_value.lower() == value.lower().strip():
                return db_value
        raise ValueError(f"Invalid strength value: {value}")

    def get_skills(self, value):
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return []

    def get_role_mapping(self):
        return {
            "1": [33],
            "2": [33, 1],
            "3": [33, 1],
            "4": [33, 1, 2],
            "5": [33, 1, 2],
            "6": [33, 1, 2, 3],
            "7": [33, 1, 2, 3],
            "8": [33, 1, 2, 3, 6],
            "9": [33, 1, 2, 3, 6],
            "10": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35],
            "11": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35],
            "12": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35],
            "13": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8],
            "14": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8],
            "15": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28],
            "16": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "17": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "18": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "19": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "20": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "21": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "22": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "23": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "24": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "25": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "26": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "27": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "28": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "29": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
            "30": [33, 1, 2, 3, 6, 24, 4, 25, 34, 35, 8, 28, 27, 7],
        }

    def export_failed_rows(self, failures):
        wb = Workbook()
        ws = wb.active
        ws.append(["Row Number", "Email", "Error"])
        for row_num, email, error in failures:
            ws.append([row_num, email, error])
        wb.save("failed_rows.xlsx")

    def normalize_phone(self, number):
        if not number:
            return ""
        number = re.sub(r"[^\d+]", "", number)
        return number if number.startswith("+") else f"+91{number}"
