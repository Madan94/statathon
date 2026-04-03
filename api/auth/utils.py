from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta

pwd_context = CryptContext(schemes=["bcrypt"])

SECRET_KEY = "supersecret"
ALGORITHM = "HS256"

def hash_password(password):

    return pwd_context.hash(password)


def verify_password(plain, hashed):

    return pwd_context.verify(plain, hashed)


def create_token(data):

    payload = data.copy()

    payload["exp"] = datetime.utcnow() + timedelta(hours=12)

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    return token