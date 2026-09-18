"""Groq Whisper speech-to-text — the English ASR fallback.

Bhashini (services/bhashini.py) covers Hindi and Marathi well, but its
published pipeline has no ASR service ID for English on this account, so
every English utterance came back "no_asr_service_for_language:en" and the
frontend fell all the way back to the browser's own SpeechRecognition —
which is exactly the path that was silently failing for English (see the
locale fix in data/i18n_landing.json: en-IN has patchy engine support in
Chrome; en-US does not, but even that only helps browsers whose engine
works at all).

This module adds a real middle tier: Groq hosts OpenAI's Whisper
(whisper-large-v3-turbo) behind an OpenAI-compatible /audio/transcriptions
endpoint, callable with the GROQ_API_KEY this project already has configured
for services/ai.py's text generation. Whisper's English recognition is
strong, including Indian-accented English, and the free tier is generous
enough for a hackathon demo's request volume.

Routing, after this change (see routes/speech.py):
  1. Bhashini, if BHASHINI_ENABLED and it has a service ID for the language
  2. Groq Whisper, if GROQ_API_KEY is set and Bhashini did not handle it
  3. Browser SpeechRecognition (client-side, see static/js/kiosk.js) —
     the fallback of last resort, unconditional, no key needed

Whisper does not need a source_language hint to transcribe English well
(it auto-detects), but a hint is passed anyway when it maps cleanly, since
it makes little difference to cost or latency and slightly improves
accuracy on short, accented utterances.

Never raises. Every function returns a SpeechResult; .ok tells the caller
whether to use it or keep falling back.
"""
from __future__ import annotations

from typing import Optional

import requests
from flask import current_app

TRANSCRIBE_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"

# Whisper's own language codes. Only listing what this app's kiosk actually
# offers (see data/i18n_landing.json's SUPPORTED tuple: en, hi, mr) — no
# point guessing codes for languages nothing here ever asks for.
WHISPER_LANGUAGE_HINTS = {"en": "en", "hi": "hi", "mr": "mr"}

# whisper-large-v3-turbo: materially faster and cheaper than the plain
# large-v3 model on Groq's pricing, with an accuracy difference that does
# not matter for short spoken-answer utterances like this app's.
MODEL = "whisper-large-v3-turbo"


class SpeechResult:
    """Same shape as services.bhashini.SpeechResult — routes/speech.py and
    any future caller can treat the two interchangeably without branching
    on which provider answered."""

    def __init__(self, text: str = "", confidence: float = 0.7,
                 source: str = "groq-whisper", error: Optional[str] = None):
        self.text = text
        self.source = source
        self.confidence = confidence
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text)


def available() -> bool:
    """False means: do not attempt a call, caller should try the next
    fallback in the chain instead."""
    return bool(current_app.config.get("GROQ_API_KEY"))


def transcribe(audio_bytes: bytes, source_language: str = "en",
              filename: str = "utterance.wav") -> SpeechResult:
    """Speech to text via Groq's Whisper endpoint.

    audio_bytes: raw audio file bytes. Whisper accepts wav, mp3, m4a, webm
    and more directly — unlike Bhashini's ASR call, no resampling or
    container conversion is needed before calling this, whatever format
    static/js/voice-shared.js's recordAndTranscribe() produced is fine.
    source_language: an ISO-639 code (en, hi, mr, ...). Unrecognised codes
    are simply omitted from the request rather than treated as an error —
    Whisper auto-detects when no hint is given.
    """
    if not available():
        return SpeechResult(source="rules", error="groq_disabled")
    if not audio_bytes:
        return SpeechResult(source="rules", error="no_audio_provided")

    cfg = current_app.config
    data = {"model": MODEL, "response_format": "json"}
    hint = WHISPER_LANGUAGE_HINTS.get(source_language)
    if hint:
        data["language"] = hint

    try:
        resp = requests.post(
            TRANSCRIBE_ENDPOINT,
            headers={"Authorization": f"Bearer {cfg['GROQ_API_KEY']}"},
            data=data,
            files={"file": (filename, audio_bytes, "application/octet-stream")},
            timeout=cfg.get("AI_TIMEOUT", 45),
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 — never let ASR crash a request
        body_hint = ""
        if "resp" in locals():
            try:
                body_hint = f" — response body: {resp.text[:500]!r}"
            except Exception:  # noqa: BLE001
                pass
        current_app.logger.warning(
            "Groq Whisper ASR call failed: %s%s", exc, body_hint)
        return SpeechResult(source="rules", error=str(exc))

    text = (payload.get("text") or "").strip()
    if not text:
        return SpeechResult(source="rules", error="empty_transcript")

    # Whisper does not return a confidence score the way Bhashini does.
    # 0.75 is a reasonable flat estimate — high enough that kiosk.js's
    # option-matching logic (which only needs a spoken phrase to contain an
    # option's label) behaves the same as a solid Bhashini/browser result,
    # without claiming a precision this API does not actually provide.
    return SpeechResult(text=text, confidence=0.75, source="groq-whisper")
