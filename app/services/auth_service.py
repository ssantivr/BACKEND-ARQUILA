import os
import smtplib
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import security, tokens
from app.errors import (
    AuthenticationError,
    ConflictError,
    InvalidDataError,
    InvalidTokenError,
    NotConfiguredError,
    TooManyAttemptsError,
)
from app.logs import logger
from app.mailer import Mailer
from app.models import PasswordResetToken, User, UserSession
from app.repositories.password_reset_repository import PasswordResetRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas import LoginRequest, PasswordChange, RegisterRequest
from app.services.access_service import DEFAULT_ROLE
from app.services.login_limiter import (
    ip_login_limiter,
    login_limiter,
    password_change_limiter,
    register_ip_limiter,
    reset_request_limiter,
)
from app.services.notification_service import notify

SESSION_LIFETIME = timedelta(days=7)
RESET_TOKEN_LIFETIME = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, session: Session) -> None:
        self.users = UserRepository(session)
        self.sessions = SessionRepository(session)
        self.resets = PasswordResetRepository(session)
        self.roles = RoleRepository(session)

    def register(self, data: RegisterRequest, client_ip: str | None = None) -> tuple[User, str]:
        email = normalize_email(data.email)
        ip_key = f"ip:{client_ip}" if client_ip else None

        # Checked before the email, so a blocked address learns nothing about which ones exist.
        # Every attempt counts, and nothing resets the count: changing the email does not help.
        if ip_key is not None:
            if register_ip_limiter.is_blocked(ip_key, self.users.session):
                logger.warning("register_blocked")
                raise TooManyAttemptsError("Too many failed attempts, try again later")

            register_ip_limiter.record_failure(ip_key, self.users.session)

        if self.users.get_by_email(email) is not None:
            raise ConflictError("Email is already registered")

        try:
            user = self.users.add(
                User(
                    name=data.name.strip(),
                    email=email,
                    password_hash=security.hash_password(data.password),
                    roles=self.roles.list_by_names([DEFAULT_ROLE]),
                )
            )
        except IntegrityError:
            self.users.session.rollback()
            raise ConflictError("Email is already registered") from None

        return user, self._start_session(user)

    def login(self, data: LoginRequest, client_ip: str | None = None) -> tuple[User, str]:
        user = self.authenticate(data, client_ip)

        return user, self._start_session(user)

    def issue_access_token(
        self, data: LoginRequest, client_ip: str | None = None
    ) -> tuple[str, int]:
        if tokens.signing_secret() is None:
            raise NotConfiguredError("Este servidor no tiene configurada la emisión de tokens.")

        user = self.authenticate(data, client_ip)
        token = tokens.create_access_token(user.id, user.password_hash)

        return token, int(tokens.ACCESS_TOKEN_LIFETIME.total_seconds())

    def user_for_access_token(self, token: str) -> User:
        claims = tokens.read_access_token(token)

        if claims is None:
            raise AuthenticationError("Not authenticated")

        user_id, fingerprint = claims
        user = self.users.get(user_id)

        # A token stops working as soon as the password it was issued under changes.
        if user is None or fingerprint != tokens.password_fingerprint(user.password_hash):
            raise AuthenticationError("Not authenticated")

        return user

    def authenticate(self, data: LoginRequest, client_ip: str | None = None) -> User:
        email = normalize_email(data.email)
        ip_key = f"ip:{client_ip}" if client_ip else None

        if login_limiter.is_blocked(email, self.users.session) or (
            ip_key is not None and ip_login_limiter.is_blocked(ip_key, self.users.session)
        ):
            logger.warning("login_blocked")
            raise TooManyAttemptsError("Too many failed attempts, try again in a minute")

        user = self.users.get_by_email(email)
        stored = user.password_hash if user else security.DUMMY_PASSWORD_HASH

        if not security.verify_password(data.password, stored) or user is None:
            login_limiter.record_failure(email, self.users.session)

            if ip_key is not None:
                ip_login_limiter.record_failure(ip_key, self.users.session)

            logger.warning("login_failed")
            raise AuthenticationError("Invalid email or password")

        login_limiter.reset(email, self.users.session)

        if security.needs_rehash(user.password_hash):
            user.password_hash = security.hash_password(data.password)
            self.users.save(user)
            logger.info("password_rehashed", extra={"user_id": user.id})

        return user

    def request_password_reset(self, email: str, mailer: Mailer) -> None:
        email = normalize_email(email)

        if reset_request_limiter.is_blocked(email, self.users.session):
            return

        reset_request_limiter.record_failure(email, self.users.session)
        user = self.users.get_by_email(email)

        if user is None:
            return

        now = _now()
        self.resets.delete_expired(now)
        self.resets.delete_for_user(user.id)

        token = security.new_session_token()
        self.resets.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=security.hash_session_token(token),
                expires_at=now + RESET_TOKEN_LIFETIME,
            )
        )

        app_url = os.environ.get("APP_URL", "http://localhost:5173").rstrip("/")

        try:
            mailer.send(
                user.email,
                "Restablecer tu contraseña de ARQUILA",
                "Para elegir una contraseña nueva abre este enlace, válido durante 30 minutos:\n\n"
                f"{app_url}/?reset_token={token}\n\n"
                "Si no lo pediste, ignora este mensaje.",
            )
        except (smtplib.SMTPException, OSError):
            logger.exception("password_reset_mail_failed", extra={"user_id": user.id})

    def reset_password(self, token: str, password: str) -> None:
        reset = self.resets.get_by_token_hash(security.hash_session_token(token))

        if reset is None or reset.expires_at <= _now():
            raise InvalidTokenError("The reset link is invalid or has expired")

        user = self.users.get(reset.user_id)

        if user is None:
            raise InvalidTokenError("The reset link is invalid or has expired")

        user.password_hash = security.hash_password(password)
        self.users.save(user)
        self.resets.delete_for_user(user.id)
        self.sessions.delete_for_user(user.id)
        login_limiter.reset(user.email, self.users.session)

    def change_password(self, user: User, token: str, data: PasswordChange) -> None:
        """Change the password and close every other session of the user."""
        key = str(user.id)

        if password_change_limiter.is_blocked(key, self.users.session):
            raise TooManyAttemptsError("Too many failed attempts, try again later")

        if not security.verify_password(data.current_password, user.password_hash):
            password_change_limiter.record_failure(key, self.users.session)
            logger.warning("password_change_failed", extra={"user_id": user.id})
            raise InvalidDataError("The current password is incorrect")

        if data.new_password == data.current_password:
            raise InvalidDataError("The new password must be different from the current one")

        user.password_hash = security.hash_password(data.new_password)
        self.users.save(user)
        self.sessions.delete_others_of_user(user.id, security.hash_session_token(token))
        password_change_limiter.reset(key, self.users.session)
        login_limiter.reset(user.email, self.users.session)
        logger.info("password_changed", extra={"user_id": user.id})
        notify(
            self.users.session,
            user,
            "Contraseña cambiada",
            "Se cerraron las demás sesiones abiertas. Si no fuiste tú, restablece tu "
            "contraseña desde la pantalla de inicio de sesión.",
        )

    def logout(self, token: str | None) -> None:
        if token:
            self.sessions.delete_by_token_hash(security.hash_session_token(token))

    def user_for_token(self, token: str | None) -> User:
        if not token:
            raise AuthenticationError("Not authenticated")

        user_session = self.sessions.get_by_token_hash(security.hash_session_token(token))

        if user_session is None or user_session.expires_at <= _now():
            raise AuthenticationError("Not authenticated")

        user = self.users.get(user_session.user_id)

        if user is None:
            raise AuthenticationError("Not authenticated")

        return user

    def _start_session(self, user: User) -> str:
        now = _now()
        self.sessions.delete_expired(now)

        token = security.new_session_token()
        self.sessions.add(
            UserSession(
                user_id=user.id,
                token_hash=security.hash_session_token(token),
                expires_at=now + SESSION_LIFETIME,
            )
        )

        return token
