from sqlalchemy.orm import Session
from database.models import User
from .utils import hash_password, verify_password

def create_user(db: Session, email, password):

    hashed = hash_password(password)

    user = User(email=email, password=hashed)

    db.add(user)

    db.commit()

    db.refresh(user)

    return user


def authenticate_user(db: Session, email, password):

    user = db.query(User).filter(User.email == email).first()

    if not user:
        return None

    if not verify_password(password, user.password):
        return None

    return user