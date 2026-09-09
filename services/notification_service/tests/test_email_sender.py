# LOCATION: services/notification_service/tests/test_email_sender.py

import asyncio

import pytest

from notification_service.email import ConsoleEmailSender, EmailMessage, build_email_sender


def test_console_sender_records_sent_messages():
    async def _run():
        sender = ConsoleEmailSender()
        await sender.send(EmailMessage(to_address="jane@example.com", subject="Hi", body="Hello there"))
        assert len(sender.sent) == 1
        assert sender.sent[0].to_address == "jane@example.com"
        assert sender.sent[0].subject == "Hi"

    asyncio.run(_run())


def test_build_email_sender_console_default():
    sender = build_email_sender(provider="console", sendgrid_api_key=None, from_address="noreply@example.com")
    assert isinstance(sender, ConsoleEmailSender)


def test_build_email_sender_sendgrid_requires_api_key():
    with pytest.raises(ValueError):
        build_email_sender(provider="sendgrid", sendgrid_api_key=None, from_address="noreply@example.com")


def test_build_email_sender_unknown_provider_raises():
    with pytest.raises(ValueError):
        build_email_sender(provider="carrier_pigeon", sendgrid_api_key=None, from_address="noreply@example.com")


def test_build_email_sender_sendgrid_with_key_constructs_without_network_call():
    from notification_service.email import SendGridEmailSender

    sender = build_email_sender(provider="sendgrid", sendgrid_api_key="fake-key", from_address="noreply@example.com")
    assert isinstance(sender, SendGridEmailSender)