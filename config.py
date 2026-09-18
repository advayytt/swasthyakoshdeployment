"""Configuration for Swasthya Kosh.

Everything is driven by environment variables loaded from .env so that the
same codebase runs in three modes:

  1. Supabase Postgres + Gemini          -> full demo
  2. Supabase Postgres, no AI key        -> deterministic fallback engine
  3. SQLite, no AI key, no internet      -> offline live-demo insurance

Mode 3 is the one you run on stage when the venue wifi dies.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "swasthya-kosh-dev-secret-change-me")

    # ---- Database -------------------------------------------------------
    # DATABASE_URL should be the Supabase "Session pooler" connection string.
    # If it is missing we silently fall back to a local SQLite file so the
    # prototype always boots.
    _raw_db = os.getenv("DATABASE_URL", "").strip()
    if _raw_db.startswith("postgres://"):
        _raw_db = _raw_db.replace("postgres://", "postgresql+psycopg2://", 1)
    elif _raw_db.startswith("postgresql://"):
        _raw_db = _raw_db.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif _raw_db.startswith("postgresql+psycopg://"):
        _raw_db = _raw_db.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)

    # On Vercel (and most serverless platforms) everything except /tmp is
    # read-only, so the local-SQLite fallback needs a writable path there
    # too — this only keeps a misconfigured first deploy from 500ing on
    # every request; it does NOT make SQLite usable in production. Data in
    # /tmp does not persist between invocations. Set DATABASE_URL (Supabase)
    # as a real environment variable in the Vercel project settings for
    # anything to actually work.
    if os.getenv("VERCEL") and not _raw_db:
        import tempfile
        _sqlite_path = os.path.join(tempfile.gettempdir(), "swasthya_kosh.sqlite3")
    else:
        _sqlite_path = BASE_DIR / "instance" / "swasthya_kosh.sqlite3"

    SQLALCHEMY_DATABASE_URI = _raw_db or f"sqlite:///{_sqlite_path}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True} if _raw_db else {}

    USING_POSTGRES = bool(_raw_db)

    # ---- Supabase (optional, for Storage of uploaded documents) ---------
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()

    # ---- AI provider ----------------------------------------------------
    # gemini | groq | openrouter | none
    AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
    # Groq deprecates and shuts down models on a rolling schedule (see
    # https://console.groq.com/docs/deprecations) — meta-llama/llama-4-
    # scout-17b-16e-instruct, this project's original default for BOTH
    # text and vision, was retired 07/17/2026 and now 404s. Text and
    # vision need separate current models on Groq: openai/gpt-oss-120b is
    # a stable Production model for text, but is NOT vision-capable.
    # qwen/qwen3.8-27b is, as of this writing, the only vision-capable
    # model in Groq's live catalog (https://console.groq.com/docs/models)
    # — its predecessor qwen/qwen3.6-27b was itself withdrawn shortly
    # after release. qwen3.8-27b is listed under Groq's "Preview Models"
    # tier, which Groq's own docs say "may be discontinued at short
    # notice" — if this 404s again, https://console.groq.com/docs/vision
    # and /docs/models will have whatever replaced it.
    GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
    GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free").strip()
    AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "45"))

    # ---- ABDM -----------------------------------------------------------
    # Real sandbox creds slot in here. Until then MOCK_ABDM keeps the same
    # interface with a local implementation.
    MOCK_ABDM = _bool("MOCK_ABDM", True)
    ABDM_CLIENT_ID = os.getenv("ABDM_CLIENT_ID", "").strip()
    ABDM_CLIENT_SECRET = os.getenv("ABDM_CLIENT_SECRET", "").strip()

    # ---- Bhashini (MeitY National Language Translation Mission) ---------
    # Optional, off by default. The kiosk's speech features work today on
    # the browser's own Web Speech API with no key at all (see static/js/
    # kiosk.js and speak.js) — that is the load-bearing path, always
    # available, and it is what every rehearsal and the actual demo should
    # be built around. Bhashini is additive: production-grade Indian-
    # language ASR/TTS/NMT that AI4Bharat trained specifically for Indian
    # speech, including code-mixed and accented speech that the browser's
    # generic recogniser handles poorly (this is exactly the ASR gap the
    # IIT-KGP/NIMHANS audit documented). It matters most for languages the
    # patient's own device has no voice for at all, which in practice on
    # this team's laptops has meant Marathi.
    #
    # Flip BHASHINI_ENABLED=true once a key is approved. Nothing else
    # changes: services/bhashini.py checks this flag before doing anything,
    # and every caller (routes/speech.py) falls back to instructing the
    # browser to use its own engine when the flag is off or a call fails.
    # A judge asking "what if Bhashini rejects your key request" should get
    # the honest answer that the demo does not depend on it either way.
    BHASHINI_ENABLED = _bool("BHASHINI_ENABLED", False)
    BHASHINI_USER_ID = os.getenv("BHASHINI_USER_ID", "").strip()
    BHASHINI_API_KEY = os.getenv("BHASHINI_API_KEY", "").strip()
    # ULCA-issued API key, used only for the Pipeline Config call. This is
    # NOT the per-request inference key — Bhashini returns that dynamically
    # (see services/bhashini.py _get_pipeline_config docstring).
    # Leave blank to use Bhashini's IIT Madras pipeline, which covers both
    # ASR and TTS (the two task types this app actually calls). The older
    # "Initial Pipeline Models" ID some docs list can return "Pipeline model
    # with the request PipelineId does not exist" for accounts it isn't
    # provisioned on — if that happens, an account-specific ID from your own
    # Bhashini dashboard belongs here instead.
    BHASHINI_PIPELINE_ID = os.getenv(
        "BHASHINI_PIPELINE_ID", "660fa5bec7fb5b0328229016").strip()
    # The default published pipeline ID for ASR+Translation+TTS, per
    # Bhashini's own example integrations. Overridable in case the account
    # is issued a different one.
    BHASHINI_TIMEOUT = int(os.getenv("BHASHINI_TIMEOUT", "20"))
    # Config-call responses (service IDs per language) are cached in memory
    # for this many seconds, since they rarely change and a config round
    # trip before every single utterance would be wasteful.
    BHASHINI_CONFIG_CACHE_SECONDS = int(
        os.getenv("BHASHINI_CONFIG_CACHE_SECONDS", "3600"))

    # ---- Uploads --------------------------------------------------------
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024  # 12 MB
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}

    # ---- Clinical safety knobs -----------------------------------------
    CONSENT_DEFAULT_HOURS = int(os.getenv("CONSENT_DEFAULT_HOURS", "24"))
    LOW_CONFIDENCE_THRESHOLD = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.75"))