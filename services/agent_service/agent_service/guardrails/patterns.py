# LOCATION: services/agent_service/agent_service/guardrails/patterns.py

"""
Compiled regex/term libraries shared across guardrail layers. Kept in
one module so the patterns named explicitly in the project plan's
GUARDRAILS ARCHITECTURE section are each defined exactly once and
referenced (not duplicated) by input_guardrails.py, bias_guardrails.py,
and pii_guardrails.py.
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────
# Layer 1, Rule 1.1 -- prompt injection stripping
# "Patterns blocked: system prompt markers (<system>, [INST], ###, ---),
#  instruction-like phrases ("ignore previous", "you are now",
#  "disregard"), role-override attempts ("act as", "pretend you are",
#  "your new instructions")."
# ─────────────────────────────────────────────────────────────────────
INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"\[\s*INST\s*\]", re.IGNORECASE),
    re.compile(r"#{3,}"),
    re.compile(r"^-{3,}$", re.MULTILINE),
    re.compile(r"ignore\s+(all\s+)?previous(\s+instructions)?", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bdisregard\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\b", re.IGNORECASE),
    re.compile(r"\bpretend\s+you\s+are\b", re.IGNORECASE),
    re.compile(r"your\s+new\s+instructions", re.IGNORECASE),
]

REDACTION_MARKER = "[REDACTED_INJECTION_ATTEMPT]"

# ─────────────────────────────────────────────────────────────────────
# Layer 3, Rule 3.1 -- demographic language detection
# "age indicators ("young", "senior" as age not role, "recent graduate"
#  in scoring context), gender pronouns in assessments, nationality/
#  accent references, physical descriptors, cultural references that
#  could imply demographic inference."
# ─────────────────────────────────────────────────────────────────────
DEMOGRAPHIC_TERM_PATTERNS: list[re.Pattern] = [
    re.compile(r"\byoung(er)?\b", re.IGNORECASE),
    re.compile(r"\belderly\b", re.IGNORECASE),
    re.compile(r"\brecent\s+graduate\b", re.IGNORECASE),
    re.compile(r"\b(he|him|his|she|her|hers)\b", re.IGNORECASE),
    re.compile(r"\baccent\b", re.IGNORECASE),
    re.compile(r"\bnationality\b", re.IGNORECASE),
    re.compile(r"\bforeign(er)?\b", re.IGNORECASE),
    re.compile(r"\battractive\b", re.IGNORECASE),
    re.compile(r"\boverweight\b", re.IGNORECASE),
    re.compile(r"\bdisab(led|ility)\b", re.IGNORECASE),
    re.compile(r"\breligious?\b", re.IGNORECASE),
]

# ─────────────────────────────────────────────────────────────────────
# Layer 4, Rule 4.1 -- PII detection in scorecards
# "candidate's full name (use "the candidate"), email, phone, specific
#  location beyond what's in the job requirements, university name in
#  scoring context."
# ─────────────────────────────────────────────────────────────────────
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
# Simple heuristic university detector -- catches the common "University
# of X" / "X University" / "X College" / "X Institute of Technology"
# shapes without needing a full NER model for this milestone.
UNIVERSITY_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z.&'-]*(?:\s+[A-Z][A-Za-z.&'-]*){0,4}\s+"
    r"(University|College|Institute of Technology))\b"
    r"|\b(University\s+of\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b"
)


def find_first_match(patterns: list[re.Pattern], text: str) -> re.Match | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None