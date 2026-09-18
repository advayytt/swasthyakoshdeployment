"""Landing page translations.

Deliberately not a translation API. Clinical copy that a judge or a patient
reads should be text a human on the team has checked, not text a model
produced at request time. It is also faster, works offline, and costs nothing.

Strings live in data/i18n_landing.json. Any key missing from a locale falls
back to English rather than rendering blank, so a half-finished translation
degrades into a mixed page instead of an empty one.
"""
from __future__ import annotations

import json
from functools import lru_cache

from flask import request, session

from config import BASE_DIR

SUPPORTED = ("en", "hi", "mr")
DEFAULT = "en"


@lru_cache(maxsize=1)
def _bundle() -> dict:
    path = BASE_DIR / "data" / "i18n_landing.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def available_languages():
    """[{code, label, speech}] for the switcher, in a fixed order."""
    data = _bundle()
    out = []
    for code in SUPPORTED:
        block = data.get(code, {})
        out.append({
            "code": code,
            "label": block.get("_label", code),
            "speech": block.get("_speech", "en-IN"),
        })
    return out


def resolve_locale() -> str:
    """?lang= wins, then the session, then the browser, then English."""
    requested = (request.args.get("lang") or "").strip().lower()
    if requested in SUPPORTED:
        return requested

    stored = session.get("ui_lang")
    if stored in SUPPORTED:
        return stored

    # Accept-Language, best effort. Never raises.
    try:
        best = request.accept_languages.best_match(SUPPORTED)
        if best:
            return best
    except Exception:  # noqa: BLE001
        pass

    return DEFAULT


def speech_locale(code: str) -> str:
    return _bundle().get(code, {}).get("_speech", "en-IN")


def translator(code: str):
    """Return t(key) bound to this locale, falling back to English."""
    data = _bundle()
    primary = data.get(code, {})
    fallback = data.get(DEFAULT, {})

    def t(key: str, default: str = "", **params) -> str:
        value = primary.get(key)
        if not value:
            value = fallback.get(key, default or key)
        if params:
            try:
                return value.format(**params)
            except (KeyError, IndexError):
                # A template passed a placeholder the string doesn't use, or
                # vice versa. Never 500 a patient screen over a missing
                # interpolation — show the unformatted string instead.
                return value
        return value

    return t


def translator_html(code: str):
    """Like translator(), but params may be marked to render inside a tag.

    Some UI strings need one interpolated value visually emphasised — the
    phone digits on the OTP screen, the mock code shown to a tester — where
    plain text_before + bold + text_after would otherwise require the
    template to re-parse an already-formatted string (fragile: any string
    matching the placeholder text elsewhere in the sentence corrupts the
    split, and it breaks silently in whichever language has the value appear
    twice).

    Call as th(key, name=("Kamla Devi", None), last4=("4417", "b")): a plain
    string value interpolates normally; a (value, tag) tuple wraps value in
    <tag>...</tag> first. Only safe because the tag name and value are always
    ours, never user-submitted HTML — do not use this for any patient-entered
    field.
    """
    data = _bundle()
    primary = data.get(code, {})
    fallback = data.get(DEFAULT, {})

    def th(key: str, **params):
        from markupsafe import Markup, escape

        value = primary.get(key) or fallback.get(key, key)
        plain = {}
        for k, v in params.items():
            if isinstance(v, tuple):
                text, tag = v
                plain[k] = (f"<{tag}>{escape(text)}</{tag}>" if tag
                            else str(escape(text)))
            else:
                plain[k] = str(escape(v))
        try:
            return Markup(escape(value).format(**{
                k: Markup(v) for k, v in plain.items()
            }))
        except (KeyError, IndexError):
            return Markup(escape(value))

    return th


def flash_key(key: str, **params) -> str:
    """Encode a translation key plus interpolation values for flash().

    Flask's flash() stores a plain (message, category) tuple, so there is
    nowhere to carry structured data like a doctor's name or an OTP code
    alongside the key. This packs both into one string using a delimiter that
    cannot appear in a key name, and resolve_flash() (registered as a Jinja
    global, see app.py) unpacks it back into a call to t() at render time, in
    whatever language the viewer currently has selected — which may differ
    from the language active when the route ran, since a flashed message can
    outlive a language switch within the same request-response cycle.

    Usage in a route:
        flash(flash_key("flash_access_granted", doctor=doc.name,
                        until="17:40"), "ok")
    """
    if not params:
        return key
    return key + "||" + json.dumps(params, ensure_ascii=False)


def resolve_flash(t, raw: str) -> str:
    """The Jinja-global counterpart to flash_key(). See its docstring.

    A message may be several flash_key() outputs joined with \\x1f (a control
    character that cannot appear in either a key name or normal flash text),
    for routes that compose more than one translated fragment into a single
    flashed line rather than baking a conditional into the translation file.
    """
    def resolve_one(part: str) -> str:
        if "||" not in part:
            return t(part)
        key, _, payload = part.partition("||")
        try:
            params = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            params = {}
        return t(key, **params)

    return "".join(resolve_one(part) for part in raw.split("\x1f"))
