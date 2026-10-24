import os
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.env import is_production
from app.errors import NotConfiguredError


class Mailer(Protocol):
    def send(self, recipient: str, subject: str, body: str) -> None: ...


class ConsoleMailer:
    def send(self, recipient: str, subject: str, body: str) -> None:
        print(f"[mail not configured] To: {recipient}\nSubject: {subject}\n\n{body}\n")


class SmtpMailer:
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        user: str | None = None,
        password: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._user = user
        self._password = password

    def send(self, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self._host, self._port, timeout=15) as server:
            server.starttls()

            if self._user:
                server.login(self._user, self._password)

            server.send_message(message)


def get_mailer() -> Mailer:
    host = os.environ.get("SMTP_HOST")

    if not host:
        # The console copy carries the reset link, and in production the console ends up in
        # the logs, where anyone who reads them could take over the account.
        if is_production():
            raise NotConfiguredError("Password recovery is not available on this server")

        return ConsoleMailer()

    return SmtpMailer(
        host=host,
        port=int(os.environ.get("SMTP_PORT", "587")),
        sender=os.environ.get("SMTP_FROM", "no-reply@arquila.local"),
        user=os.environ.get("SMTP_USER") or None,
        password=os.environ.get("SMTP_PASSWORD", ""),
    )
