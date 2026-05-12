"""
Clawzd — Application configuration.
All values are loaded from .env (with sensible defaults).
"""
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Base directory ---
BASE_DIR = Path(__file__).parent.resolve()

def _get_git_hash() -> str:
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], 
            cwd=BASE_DIR, 
            stderr=subprocess.DEVNULL
        ).decode('ascii').strip()
    except Exception:
        return ""

# --- Version (single source of truth) ---
_BASE_VERSION = "0.0.1b"
_git_hash = _get_git_hash()
APP_VERSION = f"{_BASE_VERSION}-{_git_hash}" if _git_hash else _BASE_VERSION

# --- LLM Providers ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Master toggle for cloud AI providers (OpenAI, Anthropic, Google, Grok, Groq, Mistral, etc.)
# Set to "false" in .env to run fully offline/local (Ollama only).
# Can also be toggled at runtime via the Settings panel → "Cloud AI Models".
ENABLE_CLOUD_MODELS: bool = os.getenv("ENABLE_CLOUD_MODELS", "true").lower() not in ("0", "false", "no", "off")

# --- Ollama (local LLM backend) ---
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
# Fast non-reasoning model used for prompt enrichment (image/video/chat enhance).
# Must be a non-reasoning instruction model to avoid <think> token budget waste.
ENHANCE_MODEL = os.getenv("ENHANCE_MODEL", "hf.co/unsloth/GLM-4.7-Flash-REAP-23B-A3B-GGUF:Q4_K_S")
OLLAMA_NUM_GPU = int(os.getenv("OLLAMA_NUM_GPU", "999"))  # 999 = all layers on GPU (100% VRAM)
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "-1"))    # -1 = max context window

# --- Research Models (open_deep_research-inspired role-specialization) ---
# Assign different models to different research pipeline stages for
# optimal speed/quality/cost tradeoffs. Each defaults to the main model
# so existing deployments are unaffected without explicit .env configuration.
#
#  RESEARCH_SUMMARIZATION_MODEL — lightweight & fast: summarises raw web pages
#    before injecting them into context. Runs once per scraped URL.
#    Recommended: fast model (glm-4.7-flash, gemma3:4b, phi4-mini)
#
#  RESEARCH_MAIN_MODEL — high-capability: drives planning, perspective
#    decomposition, reflection (think_tool), sub-question generation.
#    Recommended: best available model (qwen3.5:9b, claude-3-5-sonnet)
#
#  RESEARCH_COMPRESSION_MODEL — intermediate: compresses accumulated findings
#    and rewrites the evolving report draft (IterResearch condensation).
#    Recommended: medium model with good instruction following.
#
#  RESEARCH_REPORT_MODEL — best available: generates the final comprehensive
#    report from all condensed findings. Quality matters most here.
#    Recommended: largest/best model you can afford.
RESEARCH_SUMMARIZATION_MODEL = os.getenv("RESEARCH_SUMMARIZATION_MODEL", ENHANCE_MODEL)
RESEARCH_MAIN_MODEL = os.getenv("RESEARCH_MAIN_MODEL", OLLAMA_MODEL)
RESEARCH_COMPRESSION_MODEL = os.getenv("RESEARCH_COMPRESSION_MODEL", OLLAMA_MODEL)
RESEARCH_REPORT_MODEL = os.getenv("RESEARCH_REPORT_MODEL", OLLAMA_MODEL)


# Expose Ollama settings so the ollama client library picks them up natively
os.environ.setdefault("OLLAMA_HOST", OLLAMA_HOST)

# --- Application Paths ---
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", str(BASE_DIR / "chroma_db"))
DATA_DIR = os.getenv("DATA_DIR", str(BASE_DIR / "data"))
RAG_DIR = os.getenv("RAG_DIR", str(Path(DATA_DIR) / "rag"))
RESEARCH_DIR = os.getenv("RESEARCH_DIR", str(Path(DATA_DIR) / "research"))
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", str(BASE_DIR / "workspace"))
STATIC_DIR = os.getenv("STATIC_DIR", str(BASE_DIR / "static"))
TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", str(BASE_DIR / "templates"))
AGENTS_DIR = os.getenv("AGENTS_DIR", str(BASE_DIR / "profiles" / "agents"))
PROFILES_DIR = os.getenv("PROFILES_DIR", str(BASE_DIR / "profiles"))
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "clawzd.db"))
SETTINGS_PATH = os.getenv("SETTINGS_PATH", str(BASE_DIR / "data" / "settings.json"))
MODELS_DIR = os.getenv("MODELS_DIR", str(BASE_DIR / "models"))

# Force Hugging Face to store models in our MODELS_DIR
os.environ["HF_HOME"] = MODELS_DIR

# Expose HUGGINGFACE_API_KEY as HF_TOKEN so huggingface_hub authenticates natively
if HUGGINGFACE_API_KEY and not os.environ.get("HF_TOKEN"):
    os.environ["HF_TOKEN"] = HUGGINGFACE_API_KEY

# --- Security ---
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN", "")  # empty = no auth
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
RATE_LIMIT = os.getenv("RATE_LIMIT", "30/minute")

# --- Notifications ---
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# --- Social integrations ---
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET", "")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_AUTHOR_ID = os.getenv("LINKEDIN_AUTHOR_ID", "") # URN e.g., urn:li:person:123456
MEDIUM_INTEGRATION_TOKEN = os.getenv("MEDIUM_INTEGRATION_TOKEN", "")
MEDIUM_AUTHOR_ID = os.getenv("MEDIUM_AUTHOR_ID", "")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")

# --- Signal CLI ---
SIGNAL_CLI_PATH = os.getenv("SIGNAL_CLI_PATH", "signal-cli")
SIGNAL_PHONE = os.getenv("SIGNAL_PHONE", "")

# --- Server ---
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8888"))
DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes", "on")