import requests
from django.conf import settings
from typing import List, Dict, Any


class ResumerParser:

    def __init__(self):
        self.api_key = settings.APILAYER_RESUME_PARSER_API_KEY
        self.url = settings.APILAYER_RESUME_PARSER_URL
        self.headers = {
            "apikey": self.api_key,
            "Content-Type": "application/octet-stream",
        }

    def parse_resume(self, files: List[Any]) -> List[Dict[str, Any]]:
        """
        Takes a list of file paths to resumes and returns a list of dictionaries
        containing the parsed resume data. If a file is not found, its entry in
        the returned list will contain an "error" key instead of resume data.
        """
        response_list: List[Dict[str, Any]] = []
        for file in files:
            try:
                response = requests.post(
                    self.url, headers=self.headers, data=file.read()
                )
                response.raise_for_status()
                response_list.append(response.json())
            except requests.exceptions.RequestException as e:
                response_list.append({"error": str(e)})

        return response_list
