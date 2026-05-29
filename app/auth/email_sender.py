"""
Email sender abstraction.

In dev (default), prints the email body to stdout / the uvicorn log
so you can copy the 6-digit code into the verify form without
needing any real mail infrastructure.

When you're ready for real email, set RESEND_API_KEY in the env and
the same send_verification_code() call will route through Resend's
HTTP API instead. No code change needed elsewhere.

To switch providers later (SendGrid / Mailgun / SMTP), add a branch
in send_verification_code() — the rest of the auth flow only knows
about this one function.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Resend defaults. If you set up a real domain, replace `from_email`
# (resend.dev is fine for early testing — Resend allows up to 100/day
# from that domain without verification).
RESEND_API_URL = "https://api.resend.com/emails"
RESEND_DEFAULT_FROM = "ZotAdvisor <onboarding@resend.dev>"
RESEND_DEFAULT_SUBJECT = "Your ZotAdvisor verification code"


def send_verification_code(email: str, code: str) -> bool:
    """
    Dispatch a verification code. Returns True on apparent success.

    Strategy:
      1. If RESEND_API_KEY is set → POST to Resend.
      2. Otherwise → log the code to stdout (dev mode). This is the
         default; you can drop into Phase B with zero configuration.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if api_key:
        return _send_via_resend(email, code, api_key)
    return _send_via_console(email, code)


# ── Dev mode (console) ───────────────────────────────────

def _send_via_console(email: str, code: str) -> bool:
    """
    Print a clearly delimited block to the log. The Box drawing
    characters make it grep-able when the uvicorn log is busy
    streaming agent-loop output.
    """
    banner = (
        "\n"
        "┌──────────────────────────────────────────────┐\n"
        "│  ZotAdvisor — verification code (dev mode)   │\n"
        f"│  to:   {email:<37s} │\n"
        f"│  code: {code:<37s} │\n"
        "│  (set RESEND_API_KEY in env to send for real) │\n"
        "└──────────────────────────────────────────────┘"
    )
    logger.info(banner)
    return True


# ── Production mode (Resend) ─────────────────────────────

def _send_via_resend(email: str, code: str, api_key: str) -> bool:
    """
    Lazy-imported requests call. Returns False on any failure; the
    caller decides whether to surface a 500 or pretend success
    (current policy is to log + return True so the timing channel
    doesn't leak "this email exists" info — but for now we keep it
    honest because there's no enumeration risk in a demo).
    """
    import requests

    from_email = os.environ.get("RESEND_FROM_EMAIL", RESEND_DEFAULT_FROM)
    subject = os.environ.get("RESEND_SUBJECT", RESEND_DEFAULT_SUBJECT)
    body_text = (
        f"Your ZotAdvisor verification code is:\n\n"
        f"    {code}\n\n"
        f"It expires in 10 minutes. If you didn't request this, ignore this email."
    )

    try:
        r = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_email,
                "to":   [email],
                "subject": subject,
                "text":    body_text,
            },
            timeout=10,
        )
        if r.status_code >= 400:
            logger.error("Resend send failed: %d %s", r.status_code, r.text[:200])
            return False
        logger.info("Resend sent verification to %s (id=%s)",
                    email, r.json().get("id", "?"))
        return True
    except requests.RequestException as e:
        logger.error("Resend network error: %s", e)
        return False
