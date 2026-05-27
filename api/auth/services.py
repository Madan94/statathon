from datetime import datetime

from sqlalchemy.orm import Session

from database.models import User
from .utils import hash_password, verify_password


def create_user(
    db: Session,
    email: str,
    password: str,
    *,
    full_name: str | None = None,
    officer_role: str | None = None,
    is_active: bool = False,
) -> User:
    hashed = hash_password(password)
    user = User(
        email=email.strip().lower(),
        password=hashed,
        full_name=full_name,
        officer_role=officer_role,
        is_active=is_active,
        email_verified_at=datetime.utcnow() if is_active else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.password:
        return None
    if not verify_password(password, user.password):
        return None
    return user


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()
