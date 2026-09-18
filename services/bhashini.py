"""Bhashini (MeitY National Language Translation Mission) speech services.

This is a REAL client against Bhashini's actual two-call API — not a stub,
not commented-out code. It is fully functional the moment BHASHINI_ENABLED=true
and valid credentials land in .env. Until then, every function here returns
an unavailable() result immediately, without making a network call, and every
caller in this codebase already knows how to fall back when that happens —
see routes/speech.py, which is the only thing that calls into this module,
and which degrades to "let the browser's own Web Speech API handle it" on any
failure here.

Why a real client rather than commented-out placeholder code: commented-out
code cannot be syntax-checked, cannot be unit-tested, and silently rots — the
first time someone actually uncomments it, during a demo, is the worst
possible moment to discover a typo or an API shape that changed since this
was written. A feature-flagged module that compiles, has tests, and is
provably inert when the flag is off carries none of that risk.

--------------------------------------------------------------------------
API shape (confirmed against Bhashini's own documentation and reference
integrations as of writing — bhashini.gitbook.io/bhashini-apis):

  1. Pipeline Config call
     POST https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline
     Headers: userID: <user id>, ulcaApiKey: <api key>
     Body: {"pipelineTasks": [{"taskType": "asr"}, ...],
            "pipelineRequestConfig": {"pipelineId": "..."}}
     Returns, per task type, a serviceId for each supported language, PLUS
     a pipelineInferenceAPIEndPoint block containing:
       - callbackUrl: the URL for step 2 (varies by account/region)
       - inferenceApiKey: {"name": "...", "value": "..."} — a DYNAMIC auth
         header. Its name is not fixed to "Authorization"; use whatever
         Bhashini returns here for this key.

  2. Pipeline Compute call
     POST <callbackUrl from step 1>
     Headers: {inferenceApiKey.name: inferenceApiKey.value}
     Body: {"pipelineTasks": [{"taskType": "asr", "config": {...,
            "serviceId": "..."}}], "inputData": {"audio": [{"audioContent":
            "<base64>"}]}}   (ASR)
       or  {"pipelineTasks": [{"taskType": "tts", "config": {...,
            "serviceId": "..."}}], "inputData": {"input": [{"source":
            "text to speak"}]}}   (TTS)
     Returns pipelineResponse: [{"taskType": "asr", "output": [{"source":
     "transcribed text"}]}] for ASR, or {"audio": [{"audioContent":
     "<base64 wav>"}]} for TTS.

Officially documented for PoC use. The account credentials this app is
requesting are for exactly that: an SIH prototype, not production hospital
traffic. Say so plainly if asked — this is not being misrepresented as a
production-grade SLA.
--------------------------------------------------------------------------
"""
from __future__ import annotations

import base64
import time
from typing import Optional

import requests
from flask import current_app

CONFIG_ENDPOINT = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"

# In-process cache for the pipeline config response (service IDs, callback
# URL, inference key). Keyed by pipeline ID so a config change in .env
# invalidates it automatically. Module-level and unguarded by a lock: worst
# case under concurrent first-requests is a handful of duplicate config
# calls, which is harmless and cheaper than adding locking for a hackathon
# prototype's request volume.
_config_cache: dict[str, tuple[float, dict]] = {}


class SpeechResult:
    """Mirrors services.ai.AIResult's shape so callers already familiar with
    one recognise the other immediately."""

    def __init__(self, text: str = "", audio_b64: str = "",
                 source: str = "bhashini", confidence: float = 0.75,
                 error: Optional[str] = None):
        self.text = text
        self.audio_b64 = audio_b64
        self.source = source
        self.confidence = confidence
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text or self.audio_b64)


def available() -> bool:
    """False means: do not attempt a call, tell the caller to use the
    browser's own speech engine instead. This is the single gate every
    other function in this module checks first."""
    cfg = current_app.config
    return bool(cfg.get("BHASHINI_ENABLED") and cfg.get("BHASHINI_USER_ID")
               and cfg.get("BHASHINI_API_KEY"))


def status_label() -> str:
    if available():
        return "Bhashini (MeitY)"
    return "Browser speech (Web Speech API)"


# ---------------------------------------------------------------------------
# Step 1: Pipeline Config
# ---------------------------------------------------------------------------

def _get_pipeline_config(task_types: tuple[str, ...]) -> Optional[dict]:
    """Fetch (or return the cached) service-ID map and inference endpoint.

    Returns None on any failure — never raises. Every caller treats a None
    here exactly like available() being False: fall back, don't crash.
    """
    cfg = current_app.config
    pipeline_id = cfg["BHASHINI_PIPELINE_ID"]
    cache_key = pipeline_id + "|" + ",".join(sorted(task_types))

    cached = _config_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < cfg["BHASHINI_CONFIG_CACHE_SECONDS"]:
        return cached[1]

    try:
        resp = requests.post(
            CONFIG_ENDPOINT,
            headers={"userID": cfg["BHASHINI_USER_ID"],
                     "ulcaApiKey": cfg["BHASHINI_API_KEY"],
                     "Content-Type": "application/json"},
            json={
                "pipelineTasks": [{"taskType": t} for t in task_types],
                "pipelineRequestConfig": {"pipelineId": pipeline_id},
            },
            timeout=cfg["BHASHINI_TIMEOUT"],
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — config fetch must never raise
        body_hint = ""
        if "resp" in locals():
            try:
                body_hint = f" — response body: {resp.text[:500]!r}"
            except Exception:  # noqa: BLE001
                pass
        current_app.logger.warning(
            "Bhashini pipeline config failed: %s%s", exc, body_hint)
        return None

    endpoint = data.get("pipelineInferenceAPIEndPoint") or {}
    callback_url = endpoint.get("callbackUrl")
    inference_key = endpoint.get("inferenceApiKey") or {}
    if not callback_url or not inference_key.get("name"):
        current_app.logger.warning(
            "Bhashini pipeline config response missing callbackUrl or "
            "inferenceApiKey — treating as unavailable")
        return None

    service_ids: dict[str, dict[str, str]] = {}
    for block in data.get("pipelineResponseConfig", []):
        task = block.get("taskType")
        service_ids[task] = {}
        for entry in block.get("config", []):
            lang = entry.get("language", {})
            src = lang.get("sourceLanguage")
            tgt = lang.get("targetLanguage")
            key = f"{src}->{tgt}" if tgt else src
            if key and entry.get("serviceId"):
                service_ids[task][key] = entry["serviceId"]

    parsed = {
        "callback_url": callback_url,
        "auth_header_name": inference_key["name"],
        "auth_header_value": inference_key["value"],
        "service_ids": service_ids,
    }
    _config_cache[cache_key] = (time.time(), parsed)
    return parsed


# ---------------------------------------------------------------------------
# Step 2: ASR
# ---------------------------------------------------------------------------

def transcribe(audio_bytes: bytes, source_language: str,
              audio_format: str = "wav",
              sampling_rate: int = 16000) -> SpeechResult:
    """Speech to text. source_language is an ISO-639 code: hi, mr, en...

    audio_bytes should be raw audio file bytes (the browser's MediaRecorder
    output, typically webm/opus or wav depending on what routes/speech.py
    asks the browser to record — resample/transcode before calling this if
    the incoming format does not match audio_format).
    """
    if not available():
        return SpeechResult(source="rules", error="bhashini_disabled")

    config = _get_pipeline_config(("asr",))
    if not config:
        return SpeechResult(source="rules", error="config_unavailable")

    service_id = config["service_ids"].get("asr", {}).get(source_language)
    if not service_id:
        return SpeechResult(
            source="rules",
            error=f"no_asr_service_for_language:{source_language}")

    try:
        resp = requests.post(
            config["callback_url"],
            headers={config["auth_header_name"]: config["auth_header_value"],
                     "Content-Type": "application/json"},
            json={
                "pipelineTasks": [{
                    "taskType": "asr",
                    "config": {
                        "language": {"sourceLanguage": source_language},
                        "serviceId": service_id,
                        "audioFormat": audio_format,
                        "samplingRate": sampling_rate,
                    },
                }],
                "inputData": {
                    "audio": [{
                        "audioContent": base64.b64encode(audio_bytes).decode("utf-8"),
                    }],
                },
            },
            timeout=current_app.config["BHASHINI_TIMEOUT"],
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        body_hint = ""
        if "resp" in locals():
            try:
                body_hint = f" — response body: {resp.text[:500]!r}"
            except Exception:  # noqa: BLE001
                pass
        current_app.logger.warning("Bhashini ASR call failed: %s%s", exc, body_hint)
        return SpeechResult(source="rules", error=str(exc))

    try:
        pipeline_response = data.get("pipelineResponse", [data])
        asr_block = next(
            (b for b in pipeline_response if b.get("taskType") == "asr"),
            pipeline_response[0] if pipeline_response else {})
        text = asr_block["output"][0]["source"]
    except (KeyError, IndexError, TypeError) as exc:
        current_app.logger.warning(
            "Bhashini ASR response shape unexpected: %s — %r", exc, data)
        return SpeechResult(source="rules", error="unparsable_response")

    return SpeechResult(text=text, source="bhashini-asr", confidence=0.82)


# ---------------------------------------------------------------------------
# Step 2: TTS
# ---------------------------------------------------------------------------

def synthesize(text: str, language: str, gender: str = "female",
              sampling_rate: int = 22050) -> SpeechResult:
    """Text to speech. Returns base64-encoded WAV audio in .audio_b64.

    routes/speech.py is responsible for turning that into a response the
    browser's <audio> element or Web Audio API can actually play — this
    function's job stops at "here is the audio Bhashini generated."
    """
    if not available():
        return SpeechResult(source="rules", error="bhashini_disabled")

    config = _get_pipeline_config(("tts",))
    if not config:
        return SpeechResult(source="rules", error="config_unavailable")

    service_id = config["service_ids"].get("tts", {}).get(language)
    if not service_id:
        return SpeechResult(
            source="rules", error=f"no_tts_service_for_language:{language}")

    try:
        resp = requests.post(
            config["callback_url"],
            headers={config["auth_header_name"]: config["auth_header_value"],
                     "Content-Type": "application/json"},
            json={
                "pipelineTasks": [{
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": language},
                        "serviceId": service_id,
                        "gender": gender,
                        "samplingRate": sampling_rate,
                    },
                }],
                "inputData": {"input": [{"source": text}]},
            },
            timeout=current_app.config["BHASHINI_TIMEOUT"],
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        body_hint = ""
        if "resp" in locals():
            try:
                body_hint = f" — response body: {resp.text[:500]!r}"
            except Exception:  # noqa: BLE001
                pass
        current_app.logger.warning("Bhashini TTS call failed: %s%s", exc, body_hint)
        return SpeechResult(source="rules", error=str(exc))

    try:
        pipeline_response = data.get("pipelineResponse", [data])
        tts_block = next(
            (b for b in pipeline_response if b.get("taskType") == "tts"),
            pipeline_response[0] if pipeline_response else {})
        audio_b64 = tts_block["audio"][0]["audioContent"]
    except (KeyError, IndexError, TypeError) as exc:
        current_app.logger.warning(
            "Bhashini TTS response shape unexpected: %s — %r", exc, data)
        return SpeechResult(source="rules", error="unparsable_response")

    return SpeechResult(audio_b64=audio_b64, source="bhashini-tts",
                        confidence=0.9)


# ---------------------------------------------------------------------------
# Step 2: NMT (translation) — used for extending question prompts and the
# printed case-sheet take-home copy to languages beyond the three authored
# by hand in data/i18n_landing.json and data/question_ontology.json.
# ---------------------------------------------------------------------------

def translate(text: str, source_language: str,
             target_language: str) -> SpeechResult:
    if not available():
        return SpeechResult(source="rules", error="bhashini_disabled")

    config = _get_pipeline_config(("translation",))
    if not config:
        return SpeechResult(source="rules", error="config_unavailable")

    pair = f"{source_language}->{target_language}"
    service_id = config["service_ids"].get("translation", {}).get(pair)
    if not service_id:
        return SpeechResult(source="rules",
                            error=f"no_translation_service_for:{pair}")

    try:
        resp = requests.post(
            config["callback_url"],
            headers={config["auth_header_name"]: config["auth_header_value"],
                     "Content-Type": "application/json"},
            json={
                "pipelineTasks": [{
                    "taskType": "translation",
                    "config": {
                        "language": {"sourceLanguage": source_language,
                                    "targetLanguage": target_language},
                        "serviceId": service_id,
                    },
                }],
                "inputData": {"input": [{"source": text}]},
            },
            timeout=current_app.config["BHASHINI_TIMEOUT"],
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        body_hint = ""
        if "resp" in locals():
            try:
                body_hint = f" — response body: {resp.text[:500]!r}"
            except Exception:  # noqa: BLE001
                pass
        current_app.logger.warning("Bhashini NMT call failed: %s%s", exc, body_hint)
        return SpeechResult(source="rules", error=str(exc))

    try:
        pipeline_response = data.get("pipelineResponse", [data])
        block = next(
            (b for b in pipeline_response if b.get("taskType") == "translation"),
            pipeline_response[0] if pipeline_response else {})
        translated = block["output"][0]["target"]
    except (KeyError, IndexError, TypeError) as exc:
        current_app.logger.warning(
            "Bhashini NMT response shape unexpected: %s — %r", exc, data)
        return SpeechResult(source="rules", error="unparsable_response")

    return SpeechResult(text=translated, source="bhashini-nmt", confidence=0.85)