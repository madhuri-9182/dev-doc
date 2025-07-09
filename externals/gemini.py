import json
import logging
import google.generativeai as genai
from django.conf import settings
from hiringdogbackend.utils import log_action

genai.configure(api_key=settings.GOOGLE_API_KEY)


def generate_job_description(job_details):
    """Generate a high-quality job description using Gemini API."""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""
        You are a hiring expert helping startups and enterprises draft clear, structured, and professional job descriptions.

        Generate a Job Description for the following role:

        - Title: {job_details['designation']}
        - Specialization: {job_details['specialization']}
        - Experience Required: {job_details['min_exp']} to {job_details['max_exp']} years
        - Tech Stack: {', '.join(job_details['tech_stack'])}
        - Location: {job_details['location']}

        ## Output Format Requirements:
        - Start with: "We are looking for a [designation]..."
        - Use markdown headers for sections: "Responsibilities", "Required Skills", "Preferred Qualifications", "Location", "Experience"
        - Add bullet points for each skill or responsibility
        - Keep tone professional, concise, and relevant to the role
        - Avoid soft skills, company details, or generic fluff
        - Return only the job description (no explanations)

        Now generate the JD.
        """

        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        log_action(f"Error generating JD: {str(e)}", level=logging.ERROR)
        return None


def generate_questionnaire(job_details):
    """Generates technical questions for all difficulty levels with a single API call."""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""
        You are an AI that generates technical interview questions.

        Create a categorized list of interview questions for the following role:
        - Job Title: {job_details['designation']}
        - Specialization: {job_details['specialization']}
        - Skill Focus: {job_details['skill']}
        - Experience Range: {job_details['min_exp']} to {job_details['max_exp']} years

        Generate 10 questions each for the following difficulty levels:
        - easy
        - medium
        - hard

        Format your response strictly as valid JSON like this:
        {{
            "easy": ["question1", "question2", ..., "question10"],
            "medium": ["question1", "question2", ..., "question10"],
            "hard": ["question1", "question2", ..., "question10"]
        }}

        Requirements:
        - Do not add explanations. Return only JSON.
        - Focus on technical concepts
        - Include practical/scenario-based questions
        - Number questions in each section should be 10
        - Do not repeat questions across levels
        """

        response = model.generate_content(prompt)
        text = response.text.strip()

        try:
            if text.startswith("```json"):
                text = text[7:-3].strip()
            questions_json = json.loads(text)
            return questions_json
        except json.JSONDecodeError:
            log_action(
                "LLM response not valid JSON, fallback to empty structure.",
                level=logging.WARNING,
                response_text=text,
            )
            return {"easy": [], "medium": [], "hard": []}

    except Exception as e:
        log_action(f"Error generating questions: {str(e)}", level=logging.ERROR)
        return {"easy": [], "medium": [], "hard": []}
