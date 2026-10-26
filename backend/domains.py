"""Institutional Domain Parsing and Validation Policy for AuthenTra.

Validates institutional emails according to domain hierarchy rules:
- Strictly rejects public/personal freemail providers (gmail, yahoo, etc.).
- Accepts educational TLDs and multi-part suffixes (.edu, .edu.in, .ac.in, .res.in, .ac.uk, etc.).
- Never accepts a domain merely because '.edu' or '.in' is a substring (e.g. 'fakeedu.com' or 'fake.in.net').
- For generic '.in' domains without educational multi-part suffixes, requires explicit presence
  on the verified institution registry.
"""
import re
from typing import Tuple, Optional
from .storage import connect

# Public freemail and personal email providers that must be rejected for institutions
FREEMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.in", "yahoo.co.in",
    "hotmail.com", "outlook.com", "outlook.in", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com",
    "aol.com", "zoho.com", "zoho.in", "mail.com", "yandex.com", "gmx.com"
}

# Recognized institutional / educational top-level and multi-part domain suffixes
RECOGNIZED_EDU_SUFFIXES = (
    ".edu",          # e.g. mit.edu, stanford.edu, harvard.edu
    ".edu.in",       # e.g. annauniv.edu.in
    ".ac.in",        # e.g. iitb.ac.in, iitd.ac.in, iitm.ac.in
    ".res.in",       # Indian research institutes (e.g. tifr.res.in, isro.res.in)
    ".gov.in",       # Accredited government education bodies
    ".nic.in",       # National informatics
    ".ac.uk",        # e.g. ox.ac.uk, cam.ac.uk
    ".edu.au",       # Australian universities
    ".edu.sg",       # Singapore universities
    ".ac.nz",        # New Zealand universities
    ".ac.za",        # South African universities
    ".ac.jp",        # Japanese universities
)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@([a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]{2,}$")


def normalize_email(email: str) -> str:
    """Normalize and trim an email address."""
    return email.strip().lower()


def extract_domain(email: str) -> Optional[str]:
    """Extract and normalize the domain part of an email address."""
    normalized = normalize_email(email)
    if "@" not in normalized:
        return None
    parts = normalized.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[1]


def is_allowlisted_domain(domain: str) -> Tuple[bool, Optional[str]]:
    """Check if domain is registered in the verified institution allowlist table."""
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT name, verified FROM institution_domains WHERE lower(domain)=lower(?)",
                (domain.lower(),)
            ).fetchone()
            if row and row["verified"]:
                return True, row["name"]
    except Exception:
        pass
    # Fallback in-memory list for demo and well-known institutes
    known = {
        "authentra.demo": "Meridian Institute of Technology (Demo)",
        "mit.edu": "Massachusetts Institute of Technology",
        "stanford.edu": "Stanford University",
        "harvard.edu": "Harvard University",
        "iitb.ac.in": "Indian Institute of Technology Bombay",
        "iitd.ac.in": "Indian Institute of Technology Delhi",
        "iitm.ac.in": "Indian Institute of Technology Madras",
        "iisc.ac.in": "Indian Institute of Science",
        "annauniv.edu": "Anna University",
        "college.test": "Accredited Demonstration College",
    }
    if domain.lower() in known:
        return True, known[domain.lower()]
    return False, None


def validate_institution_domain(email: str) -> Tuple[bool, str, str, Optional[str]]:
    """
    Validate that an email belongs to an authorized educational/institutional domain.

    Returns:
        (is_valid, normalized_email, domain, error_message)
    """
    if not email or not isinstance(email, str):
        return False, "", "", "An institutional email address is required."

    normalized = normalize_email(email)
    if not EMAIL_REGEX.match(normalized):
        return False, normalized, "", "Invalid email format. Provide a valid official email address."

    domain = extract_domain(normalized)
    if not domain:
        return False, normalized, "", "Could not parse domain from email."

    labels = domain.split(".")
    if any(len(label) == 0 or label.startswith("-") or label.endswith("-") for label in labels):
        return False, normalized, domain, "Invalid domain structure."

    # 1. Check and reject public freemail providers
    if domain in FREEMAIL_DOMAINS:
        return False, normalized, domain, (
            f"Personal and public email providers (@{domain}) are not permitted for institution registration. "
            "Please use your official institutional email address."
        )

    # 2. Check institution allowlist / registry first
    is_allowed, inst_name = is_allowlisted_domain(domain)
    if is_allowed:
        return True, normalized, domain, None

    # 3. Check educational suffixes
    # Note: '.edu' or multi-part '.edu.in', '.ac.in', '.res.in'
    matched_suffix = None
    for suffix in RECOGNIZED_EDU_SUFFIXES:
        if domain.endswith(suffix):
            # Ensure the domain is not just the suffix itself (e.g. 'edu' or '.edu')
            # and that there is a proper subdomain label before the suffix
            prefix = domain[:-len(suffix)]
            if prefix and not prefix.endswith("."):
                matched_suffix = suffix
                break

    if matched_suffix:
        # Valid educational multi-part suffix!
        return True, normalized, domain, None

    # 4. Handle generic '.in' domains
    # A generic '.in' without educational multi-part (like '.ac.in' or '.edu.in')
    # cannot be assumed to be an educational institution.
    if domain.endswith(".in"):
        return False, normalized, domain, (
            f"The domain '{domain}' ends with .in, but is not recognized as an accredited educational domain. "
            "Institutional registration requires an official educational suffix (e.g. .ac.in, .edu.in) "
            "or an allowlisted institutional domain."
        )

    # 5. Non-educational domains (.com, .org, .net, etc.)
    return False, normalized, domain, (
        f"The domain '{domain}' is not recognized as an official educational institution. "
        "Institutional registration requires a verified institutional domain (e.g. .edu, .ac.in, .edu.in) "
        "or platform administrator allowlisting."
    )
