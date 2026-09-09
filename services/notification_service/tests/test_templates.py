# LOCATION: services/notification_service/tests/test_templates.py

from datetime import datetime, timezone

from notification_service.email import templates


def test_user_invited_mentions_tenant_and_role():
    subject, body = templates.user_invited(tenant_name="Acme Corp", role="recruiter")
    assert "Acme Corp" in subject
    assert "recruiter" in body


def test_application_submitted_mentions_job_title():
    subject, body = templates.application_submitted_recruiter_alert(job_title="Backend Engineer")
    assert "Backend Engineer" in subject
    assert "Backend Engineer" in body


def test_candidate_advanced_mentions_stage():
    subject, body = templates.candidate_advanced(job_title="Backend Engineer", new_stage="ADVANCED")
    assert "Backend Engineer" in subject
    assert "ADVANCED" in body


def test_candidate_rejected_includes_reason_when_present():
    subject, body = templates.candidate_rejected(job_title="Backend Engineer", reason="Not enough experience")
    assert "Not enough experience" in body


def test_candidate_rejected_omits_reason_when_absent():
    subject, body = templates.candidate_rejected(job_title="Backend Engineer", reason=None)
    assert "Feedback:" not in body


def test_interview_scheduled_candidate_and_interviewer_differ():
    when = datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc)
    candidate_subject, candidate_body = templates.interview_scheduled_candidate(scheduled_at=when)
    interviewer_subject, interviewer_body = templates.interview_scheduled_interviewer(scheduled_at=when)
    assert candidate_subject != interviewer_subject
    assert when.isoformat() in candidate_body
    assert when.isoformat() in interviewer_body


def test_scorecard_generated_mentions_recommendation():
    subject, body = templates.scorecard_generated_recruiter_alert(overall_recommendation="STRONG_YES")
    assert "STRONG_YES" in body