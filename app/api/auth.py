import os

from fastapi import APIRouter, Cookie, Depends, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, client_ip, get_current_user
from app.database import get_session
from app.env import setting
from app.mailer import Mailer, get_mailer
from app.models import User
from app.schemas import (
    LoginRequest,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    ProfileUpdate,
    RegisterRequest,
    UserRead,
)
from app.services.auth_service import SESSION_LIFETIME, AuthService
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/auth", tags=["auth"])

SAMESITE_VALUES = ("lax", "strict", "none")


def get_service(session: Session = Depends(get_session)) -> AuthService:
    return AuthService(session)


def cookie_options() -> dict:
    samesite = os.environ.get("COOKIE_SAMESITE", "lax").lower()

    if samesite not in SAMESITE_VALUES:
        samesite = "lax"

    return {
        "httponly": True,
        "samesite": samesite,
        "secure": samesite == "none" or setting("COOKIE_SECURE") == "1",
        "path": "/",
    }


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        **cookie_options(),
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_service),
):
    user, token = service.register(data, client_ip(request))
    set_session_cookie(response, token)
    return user


@router.post("/login", response_model=UserRead)
def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_service),
):
    user, token = service.login(data, client_ip(request))
    set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=204)
def logout(
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    service: AuthService = Depends(get_service),
):
    service.logout(token)

    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, **cookie_options())
    return response


@router.post("/password-reset", status_code=204)
def request_password_reset(
    data: PasswordResetRequest,
    service: AuthService = Depends(get_service),
    mailer: Mailer = Depends(get_mailer),
):
    service.request_password_reset(data.email, mailer)
    return Response(status_code=204)


@router.post("/password-reset/confirm", status_code=204)
def confirm_password_reset(
    data: PasswordResetConfirm,
    service: AuthService = Depends(get_service),
):
    service.reset_password(data.token, data.password)

    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, **cookie_options())
    return response


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserRead)
def update_me(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return ProfileService(session, user).update(data)


@router.post("/me/avatar", response_model=UserRead)
def upload_avatar(
    file: UploadFile,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return ProfileService(session, user).upload_avatar(file.filename, file.file)


@router.post("/change-password", status_code=204)
def change_password(
    data: PasswordChange,
    user: User = Depends(get_current_user),
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    service: AuthService = Depends(get_service),
):
    service.change_password(user, token or "", data)
    return Response(status_code=204)
