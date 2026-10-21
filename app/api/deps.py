import os
from collections.abc import Callable

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.orm import Session

from app.database import get_session
from app.errors import AuthenticationError, PermissionDeniedError
from app.models import User
from app.services.access_service import permissions_of
from app.services.auth_service import AuthService

SESSION_COOKIE = "arquila_session"
BEARER = "bearer"
FORWARDED_FOR = "x-forwarded-for"


def client_ip(request: Request) -> str | None:
    """The address of the caller.

    X-Forwarded-For is read only with TRUST_PROXY_HEADERS=1: anyone can send that header, so it
    is trusted only where a proxy in front of the API (such as Vercel) writes it itself.
    """
    if os.environ.get("TRUST_PROXY_HEADERS", "0") == "1":
        forwarded = request.headers.get(FORWARDED_FOR, "").split(",")[0].strip()

        if forwarded:
            return forwarded

    return request.client.host if request.client else None


def get_current_user(
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),
) -> User:
    return AuthService(session).user_for_token(token)


def get_api_user(
    authorization: str | None = Header(default=None),
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_session),
) -> User:
    """Identify the caller of /api/v1 by a bearer access token or by the session cookie."""
    service = AuthService(session)

    try:
        if authorization is None:
            return service.user_for_token(token)

        scheme, _, credentials = authorization.partition(" ")

        if scheme.lower() != BEARER:
            raise AuthenticationError("Not authenticated")

        return service.user_for_access_token(credentials.strip())
    except AuthenticationError:
        raise AuthenticationError("Tu sesión terminó. Vuelve a iniciar sesión.") from None


def require(permission: str) -> Callable[..., User]:
    def allowed_user(user: User = Depends(get_api_user)) -> User:
        if permission not in permissions_of(user):
            raise PermissionDeniedError("No tienes permiso para realizar esta acción.")

        return user

    return allowed_user
