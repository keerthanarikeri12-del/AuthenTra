"""Secure administrative tool for provisioning AuthenTra SYSTEM_ADMIN accounts.

Administrative privileges in AuthenTra must be assigned through a secure trusted administrative
process (such as this script run on the server), never by public registration or user-editable metadata.

Usage:
    python scripts/create_admin.py --email admin@example.com --name "Platform Administrator" --password "StrongPassword123!"
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.storage import connect, initialize, password_hash, ROLE_SYSTEM_ADMIN, audit


def create_or_promote_admin(email: str, name: str, password: str = None) -> bool:
    email = email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        print(f"Error: Invalid email format '{email}'.", file=sys.stderr)
        return False

    initialize()

    with connect() as conn:
        existing = conn.execute("SELECT * FROM users WHERE lower(email)=?", (email,)).fetchone()
        if existing:
            # Promote existing user
            conn.execute(
                "UPDATE users SET role=?, approval_status='APPROVED', email_verified=1 WHERE id=?",
                (ROLE_SYSTEM_ADMIN, existing["id"])
            )
            audit(conn, existing["id"], "admin_promoted_via_cli", reference=email, details="Role set to SYSTEM_ADMIN via CLI")
            print(f"Successfully promoted existing account '{email}' (ID: {existing['id']}) to SYSTEM_ADMIN.")
            return True
        else:
            if not password or len(password) < 12:
                print("Error: Password of at least 12 characters is required for new administrator accounts.", file=sys.stderr)
                return False
            cursor = conn.execute(
                """
                INSERT INTO users(email, name, password, role, approval_status, email_verified)
                VALUES(?, ?, ?, ?, 'APPROVED', 1)
                """,
                (email, name.strip(), password_hash(password), ROLE_SYSTEM_ADMIN)
            )
            admin_id = cursor.lastrowid
            audit(conn, admin_id, "admin_created_via_cli", reference=email, details="New SYSTEM_ADMIN provisioned via CLI")
            print(f"Successfully created new SYSTEM_ADMIN account '{email}' (ID: {admin_id}).")
            return True


def main():
    parser = argparse.ArgumentParser(description="AuthenTra System Administrator Provisioning")
    parser.add_argument("--email", required=True, help="Administrator email address")
    parser.add_argument("--name", default="Platform Administrator", help="Administrator display name")
    parser.add_argument("--password", help="Password for new administrator account (min 12 chars)")

    args = parser.parse_args()
    success = create_or_promote_admin(args.email, args.name, args.password)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
