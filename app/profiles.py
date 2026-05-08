"""
Clawzd — AI profile generation via interview or chat analysis.
Profiles are saved as Markdown files in profiles/user/.
"""
import os
import uuid
import asyncio
from fastapi import APIRouter, HTTPException, Request
from config import PROFILES_DIR as _ROOT_PROFILES_DIR
from app.llm_provider import get_llm_provider

router = APIRouter()

PROFILES_DIR = os.path.join(_ROOT_PROFILES_DIR, "user")
os.makedirs(PROFILES_DIR, exist_ok=True)

DEFAULT_INTERVIEW_QUESTIONS = [
    "How would you describe yourself in a few sentences?",
    "What are your most important values?",
    "What is your preferred communication style?",
    "What topics are you most passionate about?",
    "What are your core skills and expertise?",
    "What kind of humor do you prefer?",
    "What is your worldview or philosophy?",
    "What are your long-term goals?",
]

# In-memory interview state (keyed by interview session ID)
_active_interviews: dict = {}


@router.post("/interview/start")
async def start_interview():
    """Start a new profile interview with default questions."""
    session_id = str(uuid.uuid4())
    _active_interviews[session_id] = {
        "questions": DEFAULT_INTERVIEW_QUESTIONS,
        "current": 0,
        "answers": [],
    }
    return {
        "session_id": session_id,
        "question": DEFAULT_INTERVIEW_QUESTIONS[0],
        "total": len(DEFAULT_INTERVIEW_QUESTIONS),
        "current": 1,
    }


@router.post("/interview/{session_id}/answer")
async def answer_interview(session_id: str, request: Request):
    """Submit an answer to the current interview question."""
    data = await request.json()
    answer = data.get("answer", "")
    if not answer.strip():
        raise HTTPException(400, "Answer cannot be empty")

    interview = _active_interviews.get(session_id)
    if not interview:
        raise HTTPException(404, "Interview session not found")

    q = interview["questions"][interview["current"]]
    interview["answers"].append({"question": q, "answer": answer})
    interview["current"] += 1

    if interview["current"] >= len(interview["questions"]):
        # Generate the profile using the LLM
        responses = "\n".join(
            [f"Q: {a['question']}\nA: {a['answer']}" for a in interview["answers"]]
        )
        prompt = (
            "Based on the following interview answers, create a detailed AI personality "
            "profile in Markdown format (SOUL.md). Include sections for: Personality, "
            "Values, Communication Style, Expertise, Interests, and Goals.\n\n"
            f"{responses}"
        )
        provider = get_llm_provider()
        full = ""
        async for chunk in provider.chat_stream([{"role": "user", "content": prompt}]):
            full += chunk

        profile_id = str(uuid.uuid4())
        profile_path = os.path.join(PROFILES_DIR, f"{profile_id}.md")
        with open(profile_path, "w") as f:
            f.write(full)

        del _active_interviews[session_id]
        return {"completed": True, "profile_id": profile_id, "markdown": full}

    next_q = interview["questions"][interview["current"]]
    return {
        "completed": False,
        "question": next_q,
        "current": interview["current"] + 1,
        "total": len(interview["questions"]),
    }


@router.get("/profiles")
async def list_profiles():
    """List all saved profiles."""
    profiles = []
    for filename in sorted(os.listdir(PROFILES_DIR), reverse=True):
        if filename.endswith(".md"):
            profile_id = filename[:-3]
            path = os.path.join(PROFILES_DIR, filename)
            with open(path) as f:
                first_line = f.readline().strip().lstrip("# ")
            profiles.append({
                "id": profile_id,
                "title": first_line or "Untitled Profile",
                "filename": filename,
            })
    return {"profiles": profiles}


def _read_profile_content(path: str) -> str:
    with open(path) as f:
        return f.read()


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str):
    """Return a profile's Markdown content."""
    path = os.path.join(PROFILES_DIR, f"{profile_id}.md")
    if not os.path.exists(path):
        raise HTTPException(404, "Profile not found")
    content = await asyncio.to_thread(_read_profile_content, path)
    return {"markdown": content, "profile_id": profile_id}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Delete a saved profile."""
    path = os.path.join(PROFILES_DIR, f"{profile_id}.md")
    if not os.path.exists(path):
        raise HTTPException(404, "Profile not found")
    os.unlink(path)
    return {"status": "deleted", "profile_id": profile_id}


@router.post("/analyze-history")
async def analyze_chat_history(request: Request):
    """Generate a profile by analyzing an existing chat session history.

    Instead of a manual interview, this endpoint reads the messages from
    a session and asks the LLM to extract a personality profile from them.
    """
    data = await request.json()
    session_id = data.get("session_id", "")
    if not session_id:
        raise HTTPException(400, "session_id is required")

    from app.database import get_messages
    messages = get_messages(session_id)
    if not messages:
        raise HTTPException(404, f"No messages found for session '{session_id}'")

    # Build a summary of user messages for analysis
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    if len(user_msgs) < 3:
        raise HTTPException(400, "Need at least 3 user messages to analyze a profile")

    conversation_sample = "\n\n".join(
        f"User: {msg[:500]}" for msg in user_msgs[:20]  # cap at 20 messages
    )

    prompt = (
        "Analyze the following conversation history and create a detailed AI personality "
        "profile in Markdown format (SOUL.md). Extract the user's communication style, "
        "interests, expertise, values, and goals from their messages.\n\n"
        "Include sections for: Personality, Values, Communication Style, Expertise, "
        "Interests, and Goals.\n\n"
        f"--- Conversation History ---\n{conversation_sample}\n--- End ---"
    )

    provider = get_llm_provider()
    full = ""
    async for chunk in provider.chat_stream([{"role": "user", "content": prompt}]):
        full += chunk

    profile_id = str(uuid.uuid4())
    profile_path = os.path.join(PROFILES_DIR, f"{profile_id}.md")
    with open(profile_path, "w") as f:
        f.write(full)

    return {
        "profile_id": profile_id,
        "markdown": full,
        "analyzed_messages": len(user_msgs),
        "source_session": session_id,
    }