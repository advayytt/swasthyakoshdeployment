"""Single place where every AI call goes out.

Three providers behind one interface, plus a fourth mode that matters more
than the other three: `available() == False`. When no key is configured, or
the network is down, every caller in this codebase falls back to a
deterministic engine and the demo keeps running. Nothing in the clinical
path depends on a model responding.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from typing import Optional

import requests
from flask import current_app


class AIResult:
    """Wraps a model response with where it came from and how sure we are."""

    def __init__(self, text: str = "", source: str = "rules",
                 confidence: float = 0.5, error: Optional[str] = None):
        self.text = text
        self.source = source
        self.confidence = confidence
        self.error = error

    @property
    def ok(self):
        return self.error is None and bool(self.text)


def provider() -> str:
    cfg = current_app.config
    p = cfg.get("AI_PROVIDER", "none")
    if p == "gemini" and cfg.get("GEMINI_API_KEY"):
        return "gemini"
    if p == "groq" and cfg.get("GROQ_API_KEY"):
        return "groq"
    if p == "openrouter" and cfg.get("OPENROUTER_API_KEY"):
        return "openrouter"
    # be forgiving: if the declared provider has no key but another does, use it
    if cfg.get("GEMINI_API_KEY"):
        return "gemini"
    if cfg.get("GROQ_API_KEY"):
        return "groq"
    if cfg.get("OPENROUTER_API_KEY"):
        return "openrouter"
    return "none"


def _provider_chain() -> list[str]:
    """Every provider with a key configured, declared one first, in the
    order a failed call should retry the next one.

    provider() picks a single provider at config time and is right for
    "what should we call". This is for "what should we call, then what
    next" — the case that matters is a key that IS set but is wrong or
    revoked: provider() has no way to notice that (it only checks
    presence, not validity), so without this a bad Gemini key would fail
    every request forever even with a perfectly good Groq key sitting
    right there in the same .env. Called once per top-level generate_*
    call, not cached — .env can change between requests in dev."""
    cfg = current_app.config
    chain = []
    primary = provider()
    if primary != "none":
        chain.append(primary)
    for p, key in (("gemini", "GEMINI_API_KEY"), ("groq", "GROQ_API_KEY"),
                  ("openrouter", "OPENROUTER_API_KEY")):
        if p not in chain and cfg.get(key):
            chain.append(p)
    return chain


def available() -> bool:
    return provider() != "none"


def status_label() -> str:
    p = provider()
    return {
        "gemini": "Gemini",
        "groq": "Groq",
        "openrouter": "OpenRouter",
        "none": "Offline rules engine",
    }[p]


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def generate_text(system_prompt: str, user_prompt: str,
                  max_tokens: int = 1400) -> AIResult:
    chain = _provider_chain()
    if not chain:
        return AIResult(source="rules", error="no_provider")

    last_error = "no_provider"
    for p in chain:
        try:
            if p == "gemini":
                return _gemini_text(system_prompt, user_prompt, max_tokens)
            if p == "groq":
                return _openai_compatible(
                    "https://api.groq.com/openai/v1/chat/completions",
                    current_app.config["GROQ_API_KEY"],
                    current_app.config["GROQ_MODEL"],
                    system_prompt, user_prompt, max_tokens, source="groq")
            result = _openai_compatible(
                "https://openrouter.ai/api/v1/chat/completions",
                current_app.config["OPENROUTER_API_KEY"],
                current_app.config["OPENROUTER_MODEL"],
                system_prompt, user_prompt, max_tokens, source="openrouter")
            return result
        except Exception as exc:  # noqa: BLE001 - never let AI break the request
            current_app.logger.warning(
                "AI text call to %s failed: %s%s", p, exc,
                " — trying next configured provider"
                if p != chain[-1] else "")
            last_error = str(exc)
            continue

    return AIResult(source="rules", error=last_error)


def _gemini_text(system_prompt, user_prompt, max_tokens) -> AIResult:
    cfg = current_app.config
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{cfg['GEMINI_MODEL']}:generateContent")
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }
    r = requests.post(url, params={"key": cfg["GEMINI_API_KEY"]}, json=payload,
                      timeout=cfg["AI_TIMEOUT"])
    r.raise_for_status()
    data = r.json()
    text = _join_gemini_parts(data)
    return AIResult(text=text, source="gemini", confidence=0.82)


def _join_gemini_parts(data) -> str:
    out = []
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if "text" in part:
                out.append(part["text"])
    return "\n".join(out).strip()


def _openai_compatible(url, key, model, system_prompt, user_prompt,
                       max_tokens, source) -> AIResult:
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=current_app.config["AI_TIMEOUT"],
    )
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"].strip()
    return AIResult(text=text, source=source, confidence=0.8)


# ---------------------------------------------------------------------------
# Vision - prescription and report images
# ---------------------------------------------------------------------------

def generate_from_image(system_prompt: str, user_prompt: str,
                        image_path: str, max_tokens: int = 1600) -> AIResult:
    chain = _provider_chain()
    if not chain:
        return AIResult(source="rules", error="no_provider")

    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()

    last_error = "no_provider"
    for p in chain:
        try:
            if p == "gemini":
                cfg = current_app.config
                url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                       f"{cfg['GEMINI_MODEL']}:generateContent")
                payload = {
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{
                        "role": "user",
                        "parts": [
                            {"inline_data": {"mime_type": mime, "data": b64}},
                            {"text": user_prompt},
                        ],
                    }],
                    "generationConfig": {"temperature": 0.1,
                                         "maxOutputTokens": max_tokens},
                }
                r = requests.post(url, params={"key": cfg["GEMINI_API_KEY"]},
                                  json=payload, timeout=cfg["AI_TIMEOUT"])
                r.raise_for_status()
                return AIResult(text=_join_gemini_parts(r.json()),
                                source="gemini-vision", confidence=0.72)

            # Groq and OpenRouter both speak the OpenAI vision message shape
            if p == "groq":
                url = "https://api.groq.com/openai/v1/chat/completions"
                key = current_app.config["GROQ_API_KEY"]
                # Deliberately NOT current_app.config["GROQ_MODEL"] — that
                # one is Groq's text model and is not vision-capable (see
                # the GROQ_MODEL/GROQ_VISION_MODEL comment in config.py).
                # Sending an image to a text-only model is exactly the
                # class of error a 404/400 from Groq won't clearly explain;
                # this keeps the two calls from ever sharing a model that
                # only works for one of them.
                model = current_app.config["GROQ_VISION_MODEL"]
                source = "groq-vision"
            else:
                url = "https://openrouter.ai/api/v1/chat/completions"
                key = current_app.config["OPENROUTER_API_KEY"]
                model = current_app.config["OPENROUTER_MODEL"]
                source = "openrouter-vision"

            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url",
                             "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        ]},
                    ],
                },
                timeout=current_app.config["AI_TIMEOUT"],
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip()
            return AIResult(text=text, source=source, confidence=0.7)

        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning(
                "AI vision call to %s failed: %s%s", p, exc,
                " — trying next configured provider"
                if p != chain[-1] else "")
            last_error = str(exc)
            continue

    return AIResult(source="rules", error=last_error)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_json(text: str):
    """Models wrap JSON in prose and code fences. Dig it out safely."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None
