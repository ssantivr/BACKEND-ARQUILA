from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_api_user, require
from app.database import get_session
from app.dtos import AccessRead, AccessTokenRead, RoleAssignment
from app.models import User
from app.schemas import LoginRequest
from app.services.access_service import AccessService, permissions_of
from app.services.auth_service import AuthService

router = APIRouter(tags=["access"])


def describe(user: User) -> AccessRead:
    return AccessRead(
        id=user.id,
        name=user.name,
        email=user.email,
        roles=sorted(role.name for role in user.roles),
        permissions=sorted(permissions_of(user)),
    )


@router.post("/auth/token", response_model=AccessTokenRead)
def issue_token(data: LoginRequest, request: Request, session: Session = Depends(get_session)):
    token, lifetime = AuthService(session).issue_access_token(data, client_ip(request))

    return AccessTokenRead(access_token=token, expires_in=lifetime)


@router.get("/auth/me", response_model=AccessRead)
def me(user: User = Depends(get_api_user)):
    return describe(user)


@router.patch("/users/{user_id}/roles", response_model=AccessRead)
def assign_roles(
    user_id: int,
    data: RoleAssignment,
    session: Session = Depends(get_session),
    _: User = Depends(require("roles:manage")),
):
    return describe(AccessService(session).assign_roles(user_id, data.roles))
