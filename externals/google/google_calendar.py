import os
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from typing import List, Optional, Tuple, Dict, Any
from core.models import OAuthToken

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


class GoogleCalendar:
    SCOPES: list[str] = ["https://www.googleapis.com/auth/calendar"]

    def auth_init(self) -> Tuple[str, str]:
        """
        Starts the OAuth flow to get the user's consent for accessing their Google Calendar.
        """
        flow = Flow.from_client_secrets_file(
            settings.GOOGLE_CLIENT_SECRET_FILE, scopes=self.SCOPES
        )
        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

        # Generate the authorization URL
        authorization_url, state = flow.authorization_url(
            access_type="offline", include_granted_scopes="true"
        )
        # print("In Auth Init", state, authorization_url) keep it for debugging
        return state, authorization_url

    def auth_callback(self, state: str, authorization_response: str) -> Tuple[str, str]:
        """
        Handles the callback from Google OAuth after the user grants permissions.
        """

        # Create flow instance from the saved state
        flow = Flow.from_client_secrets_file(
            settings.GOOGLE_CLIENT_SECRET_FILE, scopes=self.SCOPES, state=state
        )
        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

        # Fetch the token using the authorization response
        flow.fetch_token(authorization_response=authorization_response)
        credentials = flow.credentials
        access_token = credentials.token
        refresh_token = credentials.refresh_token
        expired_time = credentials.expiry

        # Return the credentials (or store them for later use)
        return access_token, refresh_token, expired_time

    def _get_service(
        self,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        user,
    ) -> Any:
        """return the respective google calender service with updateed access refresh token"""
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            expiry = credentials.expiry
            if timezone.is_naive(expiry):
                expiry = timezone.make_aware(expiry)
            OAuthToken.objects.update_or_create(
                user=user,
                defaults={
                    "access_token": credentials.token,
                    "expires_at": expiry,
                    "refresh_token": credentials.refresh_token,
                },
            )

        service = build("calendar", "v3", credentials=credentials)
        return service

    """ -> keep this for future implementation
        def _check_availability(
            self,
            access_token: str,
            refres_token: str,
            date,
            start_time,
            end_time,
            time_zone="Asia/Kolkata",
        ) -> Any:
            pass
    """

    def generate_rrule_string(self, recurrence_data):
        freq = recurrence_data["frequency"]
        interval = recurrence_data["intervals"]
        until = recurrence_data.get("until")

        rrule_string = f"RRULE:FREQ={freq};INTERVAL={interval}"

        if until:
            rrule_string += f";UNTIL={until.strftime('%Y%m%dT%H%M%SZ')}"
        elif "count" in recurrence_data and recurrence_data["count"] is not None:
            rrule_string += f";COUNT={recurrence_data['count']}"

        if freq != "DAILY":
            days = recurrence_data.get("days", [])

            if freq == "WEEKLY" and days:
                rrule_string += ";BYDAY=" + ",".join(days)
            elif freq == "MONTHLY" and days:
                rrule_string += ";BYMONTHDAY=" + ",".join(str(day) for day in days)
            elif freq == "YEARLY" and days:
                rrule_string += ";BYMONTHDAY=" + ",".join(str(day) for day in days)

        return rrule_string

    def create_event(
        self, access_token: str, refresh_token: str, user, event_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Creates an event on the user's Google Calendar.
        """
        # Set up the credentials and the Google Calendar API client
        service = self._get_service(
            access_token,
            refresh_token,
            settings.GOOGLE_CLIENT_ID,
            settings.GOOGLE_CLIENT_SECRET,
            user,
        )

        created_event = (
            service.events().insert(calendarId="primary", body=event_details).execute()
        )
        # with open("CREATE_EVENT_DETAILS_FROM_GOOGLE.txt", "w") as e:
        #     e.write(str(created_event))
        return {
            "message": "Event created successfully",
            "event_link": created_event.get("htmlLink"),
            "id": created_event.get("id"),
        }

    def get_events(
        self,
        access_token: str,
        refresh_token: str,
        user,
        page_token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetches events from the user's Google Calendar and returns them in a paginated list.
        """
        service = self._get_service(
            access_token,
            refresh_token,
            settings.GOOGLE_CLIENT_ID,
            settings.GOOGLE_CLIENT_SECRET,
            user,
        )
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=datetime.utcnow().isoformat() + "Z",
                timeMax=(datetime.utcnow() + timedelta(days=365)).isoformat() + "Z",
                maxResults=10,
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )

        events = []
        for idx, event in enumerate(events_result.get("items", [])):
            # if idx == 0:
            #     print(event)
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))
            events.append(
                {
                    "id": event.get("id"),
                    "start": start,
                    "end": end,
                    "summary": event.get("summary", "No Title"),
                    "status": event.get("status", "confirmed"),
                }
            )

        response = {
            "previous_page": events_result.get("previousPageToken"),
            "next_page": events_result.get("nextPageToken"),
            "events": events,
        }

        return response
