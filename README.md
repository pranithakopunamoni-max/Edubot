# EduBot — AI-Based Educational Chatbot

EduBot is a small educational chatbot website built with HTML, CSS, JavaScript, Python, and Flask. It sends questions and recent conversation context from the browser to a Flask endpoint, which calls Google's hosted Gemini API. The backend uses Google's OpenAI-compatible endpoint through the OpenAI Python client; the browser never receives or stores the API key.

## Requirements

- Python 3.10 or newer
- A Gemini API key from Google AI Studio
- Internet access while installing packages and using the chatbot

## Setup (Windows PowerShell)

Open PowerShell in this project folder and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

In Notepad, replace the empty `GEMINI_API_KEY=` value with your own key, then save and close the file. Keep the key private; `.env` is excluded by `.gitignore`.

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey). The default model is `gemini-2.5-flash`; set `GEMINI_MODEL` in `.env` to another model available to your account if needed. Google documents this OpenAI-compatible endpoint at [ai.google.dev/gemini-api/docs/openai](https://ai.google.dev/gemini-api/docs/openai).

Start the website:

```powershell
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser. Stop the development server with `Ctrl+C`.

If PowerShell blocks activation scripts, use this for the current terminal session, then activate the environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Try It

Ask a new question in the chat, for example: **"Explain how a binary search works, and show each step for finding 14 in [2, 5, 8, 14, 19, 23]."** EduBot sends that question to the configured AI model and displays the generated explanation. Ask a follow-up to continue with the recent conversation context. Use **Clear chat** to start over.

When no key is configured, the app responds with a setup message and does not pretend to generate an answer. Other common errors, such as an invalid key, a rate limit, or a connection timeout, are shown in the chat.

## Project Structure

```text
app.py              Flask routes, educational prompt, and Gemini API call
knowledge_base.json Structured concepts for Java, DBMS, operating systems, and AI
requirements.txt    Python dependencies
.env                Local API configuration (ignored by Git)
.env.example        Configuration template
.gitignore          Excludes secrets and Python environment files
README.md           Setup and project documentation
templates/
  index.html         Chat page and accessible page structure
static/
  style.css          Responsive interface styles
  script.js          Chat requests, loading state, and answer formatting
```

## How It Works

1. The browser keeps the conversation in memory and posts it as JSON to `POST /api/chat`.
2. Flask applies simple IF-THEN keyword rules to label the latest question as a Definition, Example, Comparison, Quiz, or general Explanation.
3. Flask searches `knowledge_base.json` for matching subject/topic keywords. If a topic matches, Flask answers directly from its stored definition and example (including local quiz/comparison formatting) without calling Gemini.
4. If no topic matches, Flask reads `GEMINI_API_KEY` and `GEMINI_MODEL` from the environment (loaded from `.env`), adds the educational tutor instructions, and sends the conversation to Google's Gemini-compatible endpoint. If the key is missing, Flask shows a setup error instead of pretending to answer.
5. The browser displays the answer source and detected question type, and formats common Markdown-style headings, lists, emphasis, and fenced code blocks. No database or account is used; refreshing the page clears the in-memory conversation.
