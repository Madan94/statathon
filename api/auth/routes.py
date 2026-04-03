from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.database import SessionLocal
from .schemas import UserCreate, UserLogin
from .services import create_user, authenticate_user
from .utils import create_token

router = APIRouter(prefix="/auth")

def get_db():

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):

    new_user = create_user(db, user.email, user.password)

    return {"message": "User created"}


@router.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):

    auth_user = authenticate_user(db, user.email, user.password)

    if not auth_user:

        return {"error": "Invalid credentials"}

    token = create_token({"user_id": auth_user.id})

    return {"access_token": token, "token_type": "bearer"}