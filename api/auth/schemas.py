from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupStartRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=256)
    officer_role: str = Field(..., min_length=2, max_length=256)
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=128)


class LoginStartRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        email = v.strip().lower()
        # Allow dev test addresses (.local etc.) — do not use EmailStr here.
        if email.endswith("@test.local") or email.endswith("@example.com"):
            return email
        if "@" not in email or len(email.split("@", 1)[0]) < 1:
            raise ValueError("Invalid email address")
        return email


class OtpVerifyRequest(BaseModel):
    challenge_id: str
    otp: str = Field(..., min_length=4, max_length=8)


class ResendOtpRequest(BaseModel):
    challenge_id: str


class ChallengeResponse(BaseModel):
    challenge_id: str
    expires_in: int
    dev_otp_logged: bool | None = None
    dev_otp: str | None = None  # only for dev test user


class DevQuickLoginResponse(BaseModel):
    message: str
    user_id: int
    email: str


class UserMeResponse(BaseModel):
    id: int
    email: str
    full_name: str | None
    officer_role: str | None
    email_verified_at: str | None
