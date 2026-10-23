"""Sign-up, email verification, sign-in/out, password reset."""

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import (
    SESSION_COOKIE,
    AuthServiceDep,
    CurrentUser,
    SettingsDep,
    request_token,
)
from app.core.ratelimit import limit_auth, limit_writes
from app.db.models import User
from app.schemas.auth import (
    EmailIn,
    LoginIn,
    MeOut,
    MePatient,
    MessageOut,
    RegisterIn,
    ResetIn,
    TokenIn,
    TokenOut,
)
from app.schemas.common import error_responses

router = APIRouter(prefix="/auth", tags=["auth"])
guarded = [Depends(limit_auth)]

CHECK_EMAIL = "If that email can be used, we have sent a message to it. Check your inbox."


def _me(user: User) -> MeOut:
    patient = user.patient
    return MeOut(
        id=user.id,
        email=user.email,
        role=user.role,
        patient=MePatient(id=patient.id, full_name=patient.full_name, phone=patient.phone)
        if patient
        else None,
    )


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a patient account",
    description=(
        "Always answers 202 with the same message, whether or not the email already has an "
        "account (no account enumeration). A new account gets a verification email; an "
        "existing one gets a 'you already have an account' email."
    ),
    dependencies=guarded,
    responses=error_responses(403, 413, 422, 429),
)
def register(body: RegisterIn, auth: AuthServiceDep) -> MessageOut:
    auth.register(body.full_name, body.phone, str(body.email), body.password)
    return MessageOut(message=CHECK_EMAIL)


@router.post(
    "/verify",
    summary="Confirm an email address with the emailed token",
    dependencies=guarded,
    responses=error_responses(403, 422, 429),
)
def verify(body: TokenIn, auth: AuthServiceDep) -> MessageOut:
    auth.verify_email(body.token)
    return MessageOut(message="Email confirmed. You can sign in now.")


@router.post(
    "/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send the verification email again",
    dependencies=guarded,
    responses=error_responses(403, 422, 429),
)
def resend_verification(body: EmailIn, auth: AuthServiceDep) -> MessageOut:
    auth.resend_verification(str(body.email))
    return MessageOut(message=CHECK_EMAIL)


def _login(request: Request, body: LoginIn, auth: AuthServiceDep) -> tuple[User, str]:
    return auth.login(str(body.email), body.password, request.headers.get("user-agent", ""))


@router.post(
    "/login",
    summary="Sign in (browser): sets an HttpOnly session cookie",
    description=(
        "The session token is only ever in the `__Host-session` cookie (HttpOnly, Secure, "
        "SameSite=Strict), never in the response body, so page scripts cannot read it."
    ),
    dependencies=guarded,
    responses=error_responses(401, 403, 422, 429),
)
def login(
    request: Request, body: LoginIn, response: Response, auth: AuthServiceDep, settings: SettingsDep
) -> MeOut:
    user, token = _login(request, body, auth)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_max_hours * 3600,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return _me(user)


@router.post(
    "/token",
    summary="Sign in (API clients): returns a bearer token",
    description="Use as `Authorization: Bearer <token>`. Same rules and lifetime as a session.",
    dependencies=guarded,
    responses=error_responses(401, 403, 422, 429),
)
def token(request: Request, body: LoginIn, auth: AuthServiceDep, settings: SettingsDep) -> TokenOut:
    _, access_token = _login(request, body, auth)
    return TokenOut(access_token=access_token, expires_in=settings.session_max_hours * 3600)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out this session",
    dependencies=[Depends(limit_writes)],
    responses=error_responses(401, 403, 429),
)
def logout(request: Request, response: Response, _: CurrentUser, auth: AuthServiceDep) -> None:
    session_token, _from_cookie = request_token(request)
    if session_token:
        auth.logout(session_token)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")


@router.get("/me", summary="The signed-in account", responses=error_responses(401))
def me(user: CurrentUser) -> MeOut:
    return _me(user)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a password-reset link",
    description="Always 202 with the same message (no account enumeration).",
    dependencies=guarded,
    responses=error_responses(403, 422, 429),
)
def forgot_password(body: EmailIn, auth: AuthServiceDep) -> MessageOut:
    auth.forgot_password(str(body.email))
    return MessageOut(message=CHECK_EMAIL)


@router.post(
    "/reset-password",
    summary="Set a new password with the emailed token",
    description="Signs out every existing session for the account.",
    dependencies=guarded,
    responses=error_responses(403, 422, 429),
)
def reset_password(body: ResetIn, auth: AuthServiceDep) -> MessageOut:
    auth.reset_password(body.token, body.password)
    return MessageOut(message="Password changed. Sign in with your new password.")
