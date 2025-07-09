import json
from django.conf import settings
import google.generativeai as genai

# import assemblyai as aai

# Configure APIs
# aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")
genai.configure(api_key=settings.GOOGLE_API_KEY)


# def transcribe_video(video_path):
#     """
#     Transcribe video directly using AssemblyAI's video-to-text API.
#     """
#     try:
#         transcriber = aai.Transcriber()
#         transcript = transcriber.transcribe(video_path)
#         return transcript
#     except Exception as e:
#         st.error(f"Error during transcription: {e}")
#         return None


def analyze_transcription_and_generate_feedback(transcription):
    """
    Analyze the transcription and generate feedback for all questions in a single API request.
    Group questions by skills.
    """
    prompt = f"""
        Below is a transcription of an interview. Perform the following tasks:

        1. Extract the interviewer's questions and the candidate's answers:
            - Ignore filler words like "okay," "hmm," "uh," etc., unless part of a meaningful question/answer.
            - Only include complete sentences or meaningful phrases.
            - Skip any exchange where:
                - The question is filler (e.g., "Okay", "Hmm", "Got it").
                - The answer is too short, incomplete, or irrelevant (e.g., "Yes", "No", "Maybe", "I think so").

        2. Categorize each question under a generalized skill category (e.g., Python, AI, JavaScript, Machine Learning, etc.).

        3. For each skill category:
            - Summarize the candidate's performance concisely (word limit: 900 characters).

        4. For each extracted question-answer pair:
            - Include start and end timestamps in seconds (relative to interview start).
            - Group questions by skill area into a single block.

        5. Provide an overall evaluation:
            - Candidate strengths (word limit: 400 characters).
            - Points of improvement (word limit: 400 characters).

        6. Additionally, rate the candidate on:
            - Communication: Choose one — poor, average, good, excellent.
            - Attitude: Choose one — poor, average, good, excellent.

        Output STRICTLY in the following JSON structure:
        {{
            "skill_based_performance": {{
                "skill_name (e.g., Python, JavaScript)": {{
                    "summary": "Concise skill-specific feedback (up to 900 characters).",
                    "questions": [
                        {{
                            "que": "Meaningful interviewer's question (up to 900 characters).",
                            "ans": "Meaningful candidate's answer (up to 4000 characters).",
                            "start_time": "Start time in seconds.",
                            "end_time": "End time in seconds."
                        }}
                        ...
                    ]
                }},
                ...
            }},
            "skill_evaluation": {{
                "Communication": "poor/average/good/excellent",
                "Attitude": "poor/average/good/excellent"
            }},
            "strength": "Overall strengths (if available, up to 400 characters).",
            "improvement_points": "Improvement areas (if available, up to 400 characters)."
        }}

        Important rules:
        - Return ONLY valid JSON. No extra text, titles, explanations, or notes outside JSON.
        - JSON should contain only mentioned keys and their values.
        - Ensure JSON is properly formatted, parsable, and complete.
        - Summarize feedback clearly but concisely.
        - Remove filler words and incomplete exchanges.
        - All timestamps must be relative to the start of the interview.
        - Ensure that nothing outside keys present in the JSON aprart from the mentioned keys.

        Transcription:
        {transcription}
    """

    try:
        model = genai.GenerativeModel("gemini-2.0-flash-thinking-exp-01-21")
        response = model.generate_content(prompt)

        # Clean the response text
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()

        # Parse the JSON response
        data = json.loads(response_text)
        return data
    except json.JSONDecodeError:
        print(
            "The API response is not valid JSON. Please check the prompt or API output."
        )
        print("Raw API Response:", response_text)
        return None
    except Exception as e:
        print(f"An error occurred while analyzing the transcription: {e}")
        return None
