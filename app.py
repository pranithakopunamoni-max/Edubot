import logging
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, OpenAIError, RateLimitError

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
logging.basicConfig(level=logging.INFO)

KNOWLEDGE_BASE_PATH = Path(__file__).with_name("knowledge_base.json")
try:
    with KNOWLEDGE_BASE_PATH.open(encoding="utf-8") as knowledge_file:
        KNOWLEDGE_BASE = json.load(knowledge_file)
except (OSError, json.JSONDecodeError):
    app.logger.exception("Could not load knowledge_base.json")
    KNOWLEDGE_BASE = {"subjects": []}

SYSTEM_PROMPT = """You are EduBot, a patient and encouraging educational tutor. Help students learn across academic subjects, including programming, Java, data structures and algorithms, databases and SQL, operating systems, computer networks, artificial intelligence, machine learning, mathematics, science, English, and other school or university subjects.

Explain ideas clearly in age-appropriate, plain language. Use examples and analogies when useful. For problem-solving requests, show the reasoning in clear steps and check the result. For code questions, explain what the code does and provide corrected or example code when helpful. When asked for practice, create relevant questions and include answers only if requested. Ask a brief clarifying question when the task is genuinely ambiguous. Be accurate: state uncertainty rather than inventing facts, and do not claim to have run code or accessed materials you have not seen. Format longer explanations with short headings, lists, and fenced code blocks where helpful."""


def get_messages(payload):
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return None, "Send a question to get started."

    valid_messages = []
    for message in messages[-20:]:
        if not isinstance(message, dict):
            return None, "The conversation format is invalid. Please try again."
        role = message.get("role")
        content = message.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            return None, "The conversation format is invalid. Please try again."
        content = content.strip()
        if not content:
            return None, "Questions cannot be empty. Please type a question first."
        if len(content) > 8000:
            return None, "Each message must be 8,000 characters or fewer."
        valid_messages.append({"role": role, "content": content})

    if not valid_messages or valid_messages[-1]["role"] != "user":
        return None, "Send a question to get started."
    return valid_messages, None


def classify_question(question):
    """Apply simple IF-THEN rules to identify a student's question type."""
    text = question.lower()
    if any(phrase in text for phrase in ("quiz", "practice questions", "practice question", "test me")):
        return "Quiz"
    if "difference between" in text or "compare" in text or " compared to " in f" {text} ":
        return "Comparison"
    if "give an example" in text or "give me an example" in text or "example of" in text:
        return "Example"
    if re.search(r"\bwhat (?:is|are)\b", text) or re.search(r"\bdefine\b", text) or "definition of" in text:
        return "Definition"
    return "Explanation"


def find_knowledge(question):
    """Return knowledge-base topics whose keywords occur in the question."""
    normalized_question = " ".join(question.lower().split())
    matches = []
    for subject in KNOWLEDGE_BASE.get("subjects", []):
        for topic in subject.get("topics", []):
            matched_keywords = [
                keyword for keyword in topic.get("keywords", [])
                if re.search(r"(?<!\w)" + re.escape(keyword.strip()) + r"(?!\w)", normalized_question)
            ]
            if matched_keywords:
                matches.append({
                    "subject": subject["name"],
                    "topic": topic["name"],
                    "definition": topic["definition"],
                    "example": topic["example"],
                    "match_length": max(map(len, matched_keywords)),
                })
    matches.sort(key=lambda item: item["match_length"], reverse=True)
    return matches[:4]


def build_learning_context(question_type, knowledge):
    """Give Gemini concise reasoning guidance and any matching stored facts."""
    context = f"Detected question type: {question_type}. "
    if question_type == "Comparison":
        context += "Compare the concepts clearly, preferably with a compact table or bullet points. "
    elif question_type == "Quiz":
        context += "Create short relevant practice questions and include answers with brief explanations. "
    elif question_type == "Definition":
        context += "Start with a simple definition, then explain it with an example. "
    elif question_type == "Example":
        context += "Give a concrete, easy-to-follow example. "

    if knowledge:
        context += "Relevant knowledge-base entries (use as supporting context):\n"
        for entry in knowledge:
            context += (
                f"- {entry['subject']} / {entry['topic']}: {entry['definition']} "
                f"Example: {entry['example']}\n"
            )
    else:
        context += "No matching stored topic was found; answer the student's question normally using your subject knowledge."
    return context


def build_knowledge_answer(question_type, knowledge):
    """Answer covered questions using only the matching stored facts."""
    if not knowledge:
        return None

    if question_type == "Quiz":
        answer_lines = ["## Practice quiz from the knowledge base"]
        for number, entry in enumerate(knowledge[:3], start=1):
            answer_lines.extend([
                f"{number}. What is **{entry['topic']}**?",
                f"   **Answer:** {entry['definition']}",
                f"   **Example:** {entry['example']}",
            ])
        return "\n\n".join(answer_lines)

    answer_lines = []
    for entry in knowledge:
        answer_lines.append(f"## {entry['topic']} ({entry['subject']})")
        answer_lines.append(f"**Definition:** {entry['definition']}")
        answer_lines.append(f"**Example:** {entry['example']}")
    return "\n\n".join(answer_lines)


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Please send your question as JSON."), 400

    messages, validation_error = get_messages(payload)
    if validation_error:
        return jsonify(error=validation_error), 400

    question = messages[-1]["content"]
    question_type = classify_question(question)
    knowledge = find_knowledge(question)
    knowledge_answer = build_knowledge_answer(question_type, knowledge)
    if knowledge_answer:
        return jsonify(
            answer=knowledge_answer,
            question_type=question_type,
            source="knowledge_base",
        )

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify(error="AI is not configured yet. Add your Gemini API key to the .env file (GEMINI_API_KEY), then restart EduBot."), 503

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    learning_context = build_learning_context(question_type, knowledge)

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=30.0,
            max_retries=1,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{learning_context}"},
                *messages,
            ],
            temperature=0.5,
        )
        answer = response.choices[0].message.content
        if not answer or not answer.strip():
            return jsonify(error="The AI returned an empty answer. Please try asking again."), 502
        return jsonify(answer=answer.strip(), question_type=question_type, source="gemini")
    except APITimeoutError:
        app.logger.warning("Gemini request timed out")
        return jsonify(error="The AI request timed out. Please try again."), 504
    except APIConnectionError:
        app.logger.warning("Could not connect to Gemini")
        return jsonify(error="Could not connect to the AI service. Check your internet connection and try again."), 502
    except RateLimitError:
        app.logger.warning("Gemini rate limit or quota reached")
        return jsonify(error="The AI service is busy or its usage quota has been reached. Please check your Google AI Studio account and try again later."), 429
    except APIStatusError as error:
        app.logger.error("Gemini returned HTTP %s", error.status_code)
        if error.status_code in (401, 403):
            message = "Gemini rejected the API key. Check that it is valid and enabled in Google AI Studio."
        elif error.status_code == 404:
            message = f"The Gemini model '{model}' is not available for this API. Choose a supported model in GEMINI_MODEL in your .env file."
        elif error.status_code == 503:
            message = "The Gemini model is temporarily unavailable. Please try again in a little while."
        else:
            message = "The AI service could not complete this request. Please try again shortly."
        return jsonify(error=message), 502
    except OpenAIError:
        app.logger.exception("Gemini request failed")
        return jsonify(error="The AI service encountered an error. Please try again."), 502
    except Exception:
        app.logger.exception("Unexpected error while generating a response")
        return jsonify(error="Something went wrong while generating a response. Please try again."), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
