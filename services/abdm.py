"""ABDM identity layer.

Every function here has one job: present the same interface whether it is
talking to the real ABDM sandbox or to the local mock. Flipping MOCK_ABDM to
false in .env is the only change needed once sandbox credentials arrive.

We never store an Aadhaar number. Patients are identified by ABHA address,
practitioners by HPR ID, and we keep only the last four digits of a phone
number so a human at the desk can confirm which number the OTP went to.
"""
from __future__ import annotations

import random

from flask import current_app

from models import OtpToken, db, utcnow

OTP_TTL_MINUTES = 10


def issue_otp(subject: str) -> str:
    """Create a one-time code for an ABHA address or consent request."""
    code = f"{random.randint(0, 999999):06d}"
    if current_app.config["MOCK_ABDM"]:
        # Deterministic in mock mode so a live demo never fails on a typo.
        code = "246813"
    db.session.add(OtpToken(subject=subject, code=code))
    db.session.commit()
    return code


def verify_otp(subject: str, code: str) -> bool:
    token = OtpToken.query.filter_by(subject=subject, code=(code or "").strip(),
                                     used=False)\
        .order_by(OtpToken.id.desc()).first()
    if not token:
        return False
    age = (utcnow() - token.created_at).total_seconds() / 60
    if age > OTP_TTL_MINUTES:
        return False
    token.used = True
    db.session.commit()
    return True


def normalise_abha(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "@" not in value and not value.isdigit():
        value = f"{value}@abdm"
    return value


def mock_mode() -> bool:
    return bool(current_app.config["MOCK_ABDM"])


def demo_otp_hint() -> str:
    return "246813" if mock_mode() else ""
