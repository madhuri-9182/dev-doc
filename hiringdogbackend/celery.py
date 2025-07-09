import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hiringdogbackend.settings.dev")

app = Celery("hiringdogbackend")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.beat_schedule = {
    "process_interview_recordings_every_15_minutes": {
        "task": "dashboard.tasks.trigger_interview_processing",
        "schedule": crontab(minute="*/15"),
    },
    "process_interview_video_and_generate_and_store_feedback_every_30_minutes": {
        "task": "dashboard.tasks.process_interview_video_and_generate_and_store_feedback",
        "schedule": crontab(minute="*/30"),
    },
}
