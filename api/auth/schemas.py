from pydantic import BaseModel, EmailStr, Field


class SignupStartRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=256)
    officer_role: str = Field(..., min_length=2, max_length=256)
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=128)


class LoginStartRequest(BaseModel):
    email: EmailStr
    password: str


class OtpVerifyRequest(BaseModel):
    challenge_id: str
    otp: str = Field(..., min_length=4, max_length=8)


class ResendOtpRequest(BaseModel):
    challenge_id: str


class ChallengeResponse(BaseModel):
    challenge_id: str
    expires_in: int
    dev_otp_logged: bool | None = None


class UserMeResponse(BaseModel):
    id: int
    email: str
    full_name: str | None
    officer_role: str | None
    email_verified_at: str | None
