# LOCATION: services/notification_service/notification_service/__init__.py

"""Notification Service (M7) -- headless Kafka consumer only, no HTTP
routes (Section 3: "Notification Service (Kafka consumer only)").

Consumes every notification-relevant topic named in Task N
(application.submitted, candidate.advanced, candidate.rejected,
interview.scheduled, user.invited, scorecard.generated,
agent.integrity_flagged) and sends email. It owns and writes to no
database -- see `config.py`'s module docstring and README.md's "DB
ownership" section for why the in-app `users_db.user_notifications`
row-writes were placed in `user_profile_service` instead, following the
same no-cross-service-DB-writes precedent FIX-M2 established.
"""