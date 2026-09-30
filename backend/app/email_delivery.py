"""Provider-neutral email skeleton. No network client or sending worker exists.

A future approved provider can implement EmailTransport. Business notifications
continue to be committed through notification_service independently of email.
"""
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class EmailMessage:
    recipient: str
    subject: str
    text: str
    notification_id: str


class EmailTransport(Protocol):
    def send(self, message: EmailMessage) -> bool:
        """Return True only when a configured provider accepts delivery."""
        ...


class DisabledEmailTransport:
    def send(self, message: EmailMessage) -> bool:
        # Deliberately discard without logging recipients, body or credentials.
        return False


def build_notification_email(notification, recipient, application_url):
    url = urlparse(application_url)
    if url.scheme not in {'https', 'http'} or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Use the application base URL without credentials, query or fragment.')
    return EmailMessage(recipient=recipient, subject='Postbank document review: attention required',
        text=f'{notification.message}\n\nSign in to the application to view the request and respond:\n{application_url.rstrip("/")}\n\nComparison ID: {notification.comparison_id}\nNotification ID: {notification.id}',
        notification_id=notification.id)
