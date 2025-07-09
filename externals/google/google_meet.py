import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from django.conf import settings

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
]
IMPERSONATE_USER = (
    "contact@hdiplatform.in"
    if any(
        host in settings.ALLOWED_HOSTS for host in ["localhost", "api.hdiplatform.in"]
    )
    else "interview@hdiplatform.in"
)

credentials = service_account.Credentials.from_service_account_file(
    settings.GOOGLE_SERVICE_ACCOUNT_CRED, scopes=SCOPES
)
credentials = credentials.with_subject(IMPERSONATE_USER)

calendar_service = build("calendar", "v3", credentials=credentials)
drive_service = build("drive", "v3", credentials=credentials)


def create_meet_and_calendar_invite(
    interviewer_email, candidate_email, start_time, end_time, **kwargs
):
    candidate_name = kwargs.get("candidate_name")
    designation_name = kwargs.get("designation_name")
    recruiter_email = kwargs.get("recruiter_email")
    event = {
        "summary": f"{candidate_name}_{designation_name}_Technical_Round",
        "description": """
        🔹 INTERVIEW INSTRUCTIONS 🔹

        📍 JOIN REQUIREMENTS:
        • Join at least 3 minutes before scheduled time
        • Ensure your video is ON during the entire interview
        • Test your speaker/microphone beforehand
        • Find a quiet location to avoid background noise

        💻 TECHNICAL REQUIREMENTS:
        • Have appropriate IDE ready for coding sessions
        • Stable internet connection required
        • Backup connection recommended

        🎯 INTERVIEW GUIDELINES:
        • Interviewer's video will be OFF for confidentiality
        • If interviewer doesn't join within 10 minutes, interview will be rescheduled
        • Contact your recruiter directly for any rescheduling needs

        ⚠️  IMPORTANT NOTES:
        • Do NOT reply to this calendar invite
        • For communication, use the original email from our platform
        • Be prepared with relevant documents/portfolio

        Good luck with your interview! 🚀
        """,
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": "Asia/Kolkata",
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": "Asia/Kolkata",
        },
        "attendees": [
            {"email": interviewer_email},
            {"email": candidate_email},
            {"email": recruiter_email, "optional": True},
        ],
        "conferenceData": {
            "createRequest": {
                "requestId": f"meet-{start_time.timestamp()}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 24 * 60},
                {"method": "email", "minutes": 60},
                {"method": "popup", "minutes": 10},
            ],
        },
        "transparency": "opaque",
        "visibility": "default",
        "status": "confirmed",
        "source": {"title": "HDIPlatform", "url": "https://www.hdiplatform.in"},
        "guestsCanModify": False,
        "guestsCanInviteOthers": False,
        "extendedProperties": {
            "private": {
                "platform": "HDIP",
                "event_type": "interview",
                "created_by": "system",
                "version": "2.0",
            }
        },
    }

    event = (
        calendar_service.events()
        .insert(
            calendarId="primary",
            body=event,
            conferenceDataVersion=1,  # to generate meet link
        )
        .execute()
    )

    return event.get("hangoutLink"), event.get("id")


def cancel_meet_and_calendar_invite(event_id):
    try:
        calendar_service.events().delete(
            calendarId="primary", eventId=event_id
        ).execute()
    except Exception:
        pass


def get_meeting_info(event_id):
    event = (
        calendar_service.events().get(calendarId="primary", eventId=event_id).execute()
    )
    return event


def download_file(file_id, mime_type=None, save_path=None):
    if mime_type:
        request = drive_service.files().export_media(fileId=file_id, mimeType=mime_type)
    else:
        request = drive_service.files().get_media(fileId=file_id)

    # instead of reading the cotent directly to ram we save it in temp file by reading chunk of data size 4MB using resumable download which help to resume if download fails in the middle
    with open(save_path, "ab") as file:
        downloader = MediaIoBaseDownload(
            fd=file, request=request, chunksize=4 * 1024 * 1024
        )
        done = False
        while not done:
            try:
                status, done = downloader.next_chunk()  # Resume if interrupted
                print(f"Download {int(status.progress() * 100)}% complete.")
            except Exception as e:
                print(f"Chunk download failed: {e}")
                time.sleep(5)
                continue

    return save_path


def download_from_google_drive(interview_id, event_id):
    event_info = get_meeting_info(event_id)
    attachments = event_info.get("attachments", [])

    if not attachments:
        return {}, f"There is no attachment available for this interview {interview_id}"

    required_files = {
        "video": None,
        "transcript": None,
    }

    for attachment in attachments:
        file_id, mime_type, file_name = (
            attachment["fileId"],
            attachment["mimeType"],
            attachment["title"],
        )
        if "video" in mime_type:
            required_files["video"] = file_id
        elif "Transcript" in file_name:
            required_files["transcript"] = file_id

    if None in required_files.values():
        return (
            {},
            f"Required files are not available. See the files {required_files} and it's available attachments are: {attachments}",
        )

    downloaded_files = {}
    file_configs = {
        "video": {"ext": "mp4", "mime_type": None},
        "transcript": {"ext": "txt", "mime_type": "text/plain"},
    }

    for file_type, file_id in required_files.items():
        save_path = f"/tmp/{event_id}.{file_configs[file_type]['ext']}"
        download_file(
            file_id, mime_type=file_configs[file_type]["mime_type"], save_path=save_path
        )
        downloaded_files[file_type] = {
            "path": save_path,
            "name": f"{event_id}.{file_configs[file_type]['ext']}",
        }

    return {"interview_id": interview_id, "files": downloaded_files}, False


# keep below funcation for testing purpose
def list_all_files():
    results = drive_service.files().list().execute()
    files = results.get("files", [])
    if not files:
        print("❌ No files found.")
        return []
    for file in files:
        print(f"📂 {file['name']} (ID: {file['id']})")
    return files
