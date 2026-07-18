
import os
from dotenv import load_dotenv

load_dotenv()  # reads the ".env" file in this same folder

DATABASE_URL = os.environ["DATABASE_URL"]

GMAIL_SENDER = os.environ.get("GMAIL_SENDER", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
OTP_EXPIRY_MINS = int(os.environ.get("OTP_EXPIRY_MINS", 2))

# New settings, only used by the mobile API layer (not by backend.py)
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", 60 * 24 * 7))  # default 7 days