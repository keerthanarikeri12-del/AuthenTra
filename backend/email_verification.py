"""Email Ownership Verification Service for AuthenTra Institutions.

Provides secure token and code generation, storage, and verification for institutional emails.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from .storage import connect


def create_email_verification(email: str) -> Dict[str, str]:
    """Generate and store an email verification token and 6-digit code."""
    token = secrets.token_hex(24)
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    clean_email = email.strip().lower()

    with connect() as conn:
        # Invalidate any existing tokens for this email
        conn.execute("DELETE FROM email_verifications WHERE lower(email)=lower(?)", (clean_email,))
        conn.execute(
            "INSERT INTO email_verifications(email, token, code, expires_at) VALUES(?, ?, ?, ?)",
            (clean_email, token, code, expires_at)
        )

    return {
        "email": clean_email,
        "token": token,
        "code": code,
        "expires_at": expires_at
    }


def verify_email_token(email: str, token_or_code: str) -> bool:
    """Verify an email token or 6-digit code and mark the user's email as verified."""
    if not email or not token_or_code:
        return False

    clean_email = email.strip().lower()
    value = token_or_code.strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM email_verifications
            WHERE lower(email)=lower(?) AND (token=? OR code=?) AND expires_at > ?
            """,
            (clean_email, value, value, now_iso)
        ).fetchone()

        if not row:
            return False

        # Mark user as verified
        conn.execute(
            "UPDATE users SET email_verified=1 WHERE lower(email)=lower(?)",
            (clean_email,)
        )
        # Remove consumed token
        conn.execute("DELETE FROM email_verifications WHERE id=?", (row["id"],))

    return True


def is_email_verified(email: str) -> bool:
    """Check if an email has completed ownership verification."""
    clean_email = email.strip().lower()
    with connect() as conn:
        row = conn.execute(
            "SELECT email_verified FROM users WHERE lower(email)=lower(?)",
            (clean_email,)
        ).fetchone()
        if row and row["email_verified"]:
            return True
    return False
