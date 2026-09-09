# LOCATION: services/notification_service/notification_service/email/__init__.py

"""Email sending abstraction + message templates (Section 3: "Sends
email (SendGrid/SMTP)")."""

from .email_sender import ConsoleEmailSender, EmailMessage, EmailSender, SendGridEmailSender, build_email_sender

__all__ = [
    "EmailSender", "EmailMessage", "ConsoleEmailSender", "SendGridEmailSender", "build_email_sender",
]