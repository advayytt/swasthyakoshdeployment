"""Speech proxy endpoints.

The kiosk's speech features work today with zero server involvement: the
browser's own SpeechRecognition and speechSynthesis run entirely client-side
(see static/js/kiosk.js and static/js/speak.js). That path has no key, no
per-request cost, and no network dependency for synthesis. It is the one the
product is built around and the one every demo should rely on.

These two routes exist so that when BHASHINI_ENABLED=true, the same kiosk
screens can route audio through Bhashini's Indian-language-specific models
instead — without the frontend needing two different code paths baked in.
The frontend always tries these routes first when Bhashini is configured
(kiosk.js checks a small /speech/status flag once per page load) and falls
straight back to the browser engine on any non-200 response, timeout, or when
the status check says Bhashini is off. That fallback is not a special case
the frontend has to remember to handle — it is the frontend's only path
until someone flips the flag on.
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from services import bhashini, groq_speech

bp = Blueprint("speech", __name__, url_prefix="/speech")


@bp.route("/status")
def status():
    """The kiosk calls this once per page load to decide whether to even
    attempt the server-side routes below. Cheap, no external call.

    `enabled` covers either server-side ASR/TTS path being available at
    all — Bhashini, Groq Whisper, or both — so the frontend's existing
    "try /speech/*, fall back to the browser on failure" logic (see
    static/js/kiosk.js and voice-shared.js) needs no changes: it already
    treats a non-200 from /speech/transcribe as "try the next thing", and
    /speech/transcribe now tries Bhashini then Groq before giving up.
    `label` still names whichever one actually answers, per call — see the
    `source` field on responses. """
    bhashini_on = bhashini.available()
    groq_on = groq_speech.available()
    if bhashini_on:
        label = bhashini.status_label()
    elif groq_on:
        label = "Groq Whisper"
    else:
        label = "Browser speech (Web Speech API)"
    return jsonify({
        "enabled": bhashini_on or groq_on,
        "label": label,
    })


@bp.route("/transcribe", methods=["POST"])
def transcribe():
    """Body: multipart audio file + form fields lang, format, sample_rate.
    Returns {"text": "...", "confidence": 0.0-1.0} on success.

    Tries Bhashini first (best for Hindi/Marathi, including code-mixed
    speech), then Groq Whisper (this account's Bhashini pipeline has no
    English ASR service ID, so English always lands here) before giving up.
    A non-200 or malformed response here means the frontend should fall back
    to the browser's own SpeechRecognition for this utterance — it already
    does, unconditionally, on anything but a clean 200 (see kiosk.js).
    """
    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"error": "no_audio_provided"}), 400

    lang = (request.form.get("lang") or "hi").strip()
    audio_format = (request.form.get("format") or "wav").strip()
    try:
        sample_rate = int(request.form.get("sample_rate") or 16000)
    except ValueError:
        sample_rate = 16000

    # Cap read size defensively — this is a single spoken answer, not a
    # document upload. MAX_CONTENT_LENGTH (12 MB) already guards the whole
    # request at the Flask level; this is a tighter, speech-specific bound.
    audio_bytes = audio_file.read(6 * 1024 * 1024)

    tried = []

    if bhashini.available():
        result = bhashini.transcribe(audio_bytes, lang, audio_format, sample_rate)
        if result.ok:
            return jsonify({"text": result.text, "confidence": result.confidence,
                            "source": result.source})
        tried.append(f"bhashini:{result.error}")

    if groq_speech.available():
        result = groq_speech.transcribe(
            audio_bytes, lang, filename=f"utterance.{audio_format}")
        if result.ok:
            return jsonify({"text": result.text, "confidence": result.confidence,
                            "source": result.source})
        tried.append(f"groq:{result.error}")

    if not tried:
        # Neither provider is configured at all — this is the same
        # "server-side speech is off" case as before, same error code so
        # nothing on the frontend needs to change.
        return jsonify({"error": "bhashini_disabled"}), 503

    current_app.logger.info(
        "Server-side ASR unavailable (%s); frontend will fall back to "
        "browser recognition", "; ".join(tried))
    return jsonify({"error": tried[-1].split(":", 1)[-1] or "asr_failed"}), 502


@bp.route("/synthesize", methods=["POST"])
def synthesize():
    """Body (JSON): {"text": "...", "lang": "hi", "gender": "female"}.
    Returns {"audio_base64": "...", "format": "wav"} on success.

    routes/speech.py deliberately returns base64 JSON rather than a raw audio
    response, so the same fetch() call path in kiosk.js works whether the
    browser is going to hand the bytes to an <audio> element or decode them
    through the Web Audio API — the frontend decides, this endpoint just
    hands back the bytes Bhashini generated.
    """
    if not bhashini.available():
        return jsonify({"error": "bhashini_disabled"}), 503

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    lang = (payload.get("lang") or "hi").strip()
    gender = (payload.get("gender") or "female").strip()

    if not text:
        return jsonify({"error": "no_text_provided"}), 400
    if len(text) > 2000:
        # A single kiosk prompt is a sentence or two. Reject anything wildly
        # larger rather than sending it to a paid-quota-adjacent API call —
        # this is the sort of limit that is cheap to add now and annoying to
        # discover the need for later.
        return jsonify({"error": "text_too_long"}), 400

    result = bhashini.synthesize(text, lang, gender)
    if not result.ok:
        current_app.logger.info("Bhashini TTS unavailable (%s); frontend "
                                "will fall back to speechSynthesis",
                                result.error)
        return jsonify({"error": result.error or "tts_failed"}), 502

    return jsonify({"audio_base64": result.audio_b64, "format": "wav"})
