import os

import bcrypt
from jose import jwt
from datetime import datetime, timedelta

SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    raw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return raw.decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8"),
            hashed.encode("ascii") if isinstance(hashed, str) else hashed,
        )
    except ValueError:
        return False


def create_token(data):
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=12)
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token
