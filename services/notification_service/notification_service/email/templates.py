# LOCATION: services/notification_service/notification_service/email/templates.py

"""
Subject/body builders for every notification-relevant event (Task N's
named list: application.submitted, candidate.advanced/rejected,
interview.scheduled, user.invited, scorecard.generated). Kept as plain
functions (not a templating engine) since every message here is short
and structurally simple -- swap in Jinja2 templates later if richer
HTML emails are needed, without changing any caller.
"""

from __future__ import annotations

from datetime import datetime


def user_invited(*, tenant_name: str, role: str) -> tuple[str, str]:
    subject = f"You've been invited to join {tenant_name} on InSyncHire"
    body = (
        f"You've been invited to join {tenant_name} on InSyncHire as a {role}. "
        "Sign in (or create an account) and accept the invite to get started."
    )
    return subject, body


def application_submitted_recruiter_alert(*, job_title: str) -> tuple[str, str]:
    subject = f"New application for {job_title}"
    body = f"A new candidate just applied to your job posting: {job_title}. Review it in InSyncHire."
    return subject, body


def candidate_advanced(*, job_title: str, new_stage: str) -> tuple[str, str]:
    subject = f"Update on your application for {job_title}"
    body = f"Good news -- your application for {job_title} has advanced to the next stage: {new_stage}."
    return subject, body


def candidate_rejected(*, job_title: str, reason: str | None) -> tuple[str, str]:
    subject = f"Update on your application for {job_title}"
    body = f"Thank you for applying to {job_title}. We won't be moving forward with your application at this time."
    if reason:
        body += f" Feedback: {reason}"
    return subject, body


def interview_scheduled_candidate(*, scheduled_at: datetime) -> tuple[str, str]:
    subject = "Your interview is scheduled"
    body = f"Your interview is scheduled for {scheduled_at.isoformat()}. Good luck!"
    return subject, body


def interview_scheduled_interviewer(*, scheduled_at: datetime) -> tuple[str, str]:
    subject = "You're scheduled to interview a candidate"
    body = f"You've been scheduled to interview a candidate at {scheduled_at.isoformat()}."
    return subject, body


def scorecard_generated_recruiter_alert(*, overall_recommendation: str) -> tuple[str, str]:
    subject = "A scorecard is ready for your review"
    body = (
        f"An interview scorecard is ready for your review in InSyncHire "
        f"(AI-assisted recommendation: {overall_recommendation}). "
        "Please review the full evidence before making a decision."
    )
    return subject, body