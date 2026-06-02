import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from auth.cookies import clear_session_cookies, set_session_cookies
from auth.rate_limit import check_rate_limit
from auth.otp_service import (
    resend_otp,
    start_login,
    start_signup,
    verify_login_otp,
    verify_signup_otp,
)
from auth.schemas import (
    ChallengeResponse,
    DevQuickLoginResponse,
    LoginStartRequest,
    OtpVerifyRequest,
    ResendOtpRequest,
    SignupStartRequest,
    UserMeResponse,
)
from auth.services import get_user_by_id
from auth.token_service import (
    access_max_age_seconds,
    create_access_token,
    decode_access_token,
    issue_refresh_token,
    refresh_max_age_seconds,
    revoke_refresh_token,
    rotate_refresh_token,
)
from auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from database.database import SessionLocal
from deps import get_current_user_id

router = APIRouter(prefix="/auth")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _client_key(request: Request, email: str | None = None) -> str:
    ip = request.client.host if request.client else "unknown"
    if email:
        return f"{ip}:{email}"
    return ip


def _issue_session(response: Response, db, user, request: Request) -> None:
    access = create_access_token(user.id)
    refresh = issue_refresh_token(db, user.id, user_agent=request.headers.get("user-agent"))
    csrf = secrets.token_urlsafe(32)
    set_session_cookies(
        response,
        access,
        refresh,
        access_max_age_seconds(),
        refresh_max_age_seconds(),
        csrf_token=csrf,
    )


@router.post("/signup/start", response_model=ChallengeResponse)
def signup_start(body: SignupStartRequest, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    if not check_rate_limit(_client_key(request, email)):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    try:
        challenge_id, expires_in, mail_meta = start_signup(
            db,
            body.full_name,
            body.officer_role,
            email,
            body.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        import logging

        logging.getLogger(__name__).exception("signup/start failed")
        raise HTTPException(
            status_code=500,
            detail="Signup failed. Ensure the database auth migration completed (restart API).",
        ) from e
    return ChallengeResponse(
        challenge_id=challenge_id,
        expires_in=expires_in,
        dev_otp_logged=mail_meta.get("dev_otp_logged"),
    )


@router.post("/signup/verify-otp")
def signup_verify_otp(
    body: OtpVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = verify_signup_otp(db, body.challenge_id, body.otp)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _issue_session(response, db, user, request)
    return {"message": "Account verified", "user_id": user.id}


@router.post("/signup/resend-otp", response_model=ChallengeResponse)
def signup_resend(body: ResendOtpRequest, request: Request, db: Session = Depends(get_db)):
    if not check_rate_limit(_client_key(request)):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    try:
        expires_in, mail_meta = resend_otp(db, body.challenge_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    ch_id = body.challenge_id
    return ChallengeResponse(
        challenge_id=ch_id,
        expires_in=expires_in,
        dev_otp_logged=mail_meta.get("dev_otp_logged"),
    )


@router.post("/login/start", response_model=ChallengeResponse)
def login_start(body: LoginStartRequest, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    if not check_rate_limit(_client_key(request, email)):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    challenge_id, expires_in, mail_meta = start_login(db, email, body.password)
    if not challenge_id:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    dev_otp = None
    try:
        from auth.dev_user import dev_auth_enabled, get_dev_fixed_otp, is_dev_test_email

        if dev_auth_enabled() and is_dev_test_email(email):
            dev_otp = get_dev_fixed_otp()
    except Exception:
        pass

    return ChallengeResponse(
        challenge_id=challenge_id,
        expires_in=expires_in or 600,
        dev_otp_logged=mail_meta.get("dev_otp_logged") if mail_meta else None,
        dev_otp=dev_otp,
    )


@router.post("/login/verify-otp")
def login_verify_otp(
    body: OtpVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = verify_login_otp(db, body.challenge_id, body.otp)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _issue_session(response, db, user, request)
    return {"message": "Signed in", "user_id": user.id}


@router.post("/login/resend-otp", response_model=ChallengeResponse)
def login_resend(body: ResendOtpRequest, request: Request, db: Session = Depends(get_db)):
    if not check_rate_limit(_client_key(request)):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    try:
        expires_in, mail_meta = resend_otp(db, body.challenge_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ChallengeResponse(
        challenge_id=body.challenge_id,
        expires_in=expires_in,
        dev_otp_logged=mail_meta.get("dev_otp_logged"),
    )


@router.get("/me", response_model=UserMeResponse)
def me(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserMeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        officer_role=user.officer_role,
        email_verified_at=user.email_verified_at.isoformat() if user.email_verified_at else None,
    )


@router.post("/refresh")
def refresh_session(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="No refresh token")
    rotated = rotate_refresh_token(db, raw, user_agent=request.headers.get("user-agent"))
    if not rotated:
        clear_session_cookies(response)
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    access, new_refresh = rotated
    csrf = secrets.token_urlsafe(32)
    set_session_cookies(
        response,
        access,
        new_refresh,
        access_max_age_seconds(),
        refresh_max_age_seconds(),
        csrf_token=csrf,
    )
    return {"message": "refreshed"}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        revoke_refresh_token(db, raw)
    clear_session_cookies(response)
    return {"message": "logged out"}


@router.post("/dev/quick-login", response_model=DevQuickLoginResponse)
def dev_quick_login(
    body: LoginStartRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Development only — sign in as the test officer without OTP."""
    from auth.dev_user import (
        DEV_TEST_EMAIL,
        dev_auth_enabled,
        is_dev_test_email,
        log_test_user_otp,
        resolve_dev_user,
    )
    from auth.services import authenticate_user

    if not dev_auth_enabled():
        raise HTTPException(status_code=404, detail="Not available")

    email = body.email.lower().strip()
    if not is_dev_test_email(email):
        raise HTTPException(
            status_code=403,
            detail=f"Dev quick-login only for {DEV_TEST_EMAIL}",
        )

    user = resolve_dev_user(db, email, body.password)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    log_test_user_otp(purpose="quick_login_skipped")
    _issue_session(response, db, user, request)
    return DevQuickLoginResponse(
        message="Dev session issued (OTP skipped)",
        user_id=user.id,
        email=user.email,
    )


# Legacy endpoints — redirect clients to OTP flows
@router.post("/register")
def register_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Use POST /auth/signup/start then /auth/signup/verify-otp",
    )


@router.post("/login")
def login_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Use POST /auth/login/start then /auth/login/verify-otp",
    )
