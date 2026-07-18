"""
Pydantic schemas: these define the exact JSON shape the mobile app sends
and receives for each endpoint. FastAPI uses these to validate requests
automatically and to generate the interactive docs at /docs.
"""
from datetime import date
from typing import Optional

from pydantic import BaseModel, EmailStr


# ---------- Auth ----------

class SendOtpRequest(BaseModel):
    email: EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    otp: str
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class ForgotPasswordSendOtpRequest(BaseModel):
    username: str
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    username: str
    email: EmailStr
    otp: str
    new_password: str


# ---------- Reports ----------

class MonthlyReportQuery(BaseModel):
    month: int
    year: int
    property: Optional[str] = None