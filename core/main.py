from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine
import sys
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ensure python can find your files
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ingestion import load_raw_data
from api.database.models import Base, Dataset, User # Updated imports!

class Settings(BaseSettings):
    database_url: str
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

settings = Settings()
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Auto-create the new enterprise tables
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI(title="ASI-Gen Engine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- The Foreign Key Bypass ---
@app.on_event("startup")
def create_dummy_user():
    """Ensures there is at least one user in the DB so uploads don't crash."""
    db = SessionLocal()
    admin = db.query(User).filter(User.email == "admin@mospi.gov.in").first()
    if not admin:
        admin = User(email="admin@mospi.gov.in", password="hashed_placeholder")
        db.add(admin)
        db.commit()
    db.close()

@app.get("/")
def greet():
    return {'application' : 'asi_gen', 'status' : 'running'}

# --- The Updated Upload Route ---
@app.post("/api/v1/upload")
async def upload_survey(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.csv', '.xlsx')):
        raise HTTPException(status_code=400, detail="Strict format enforcement: CSV or Excel only.")

    try:
        # 1. Run the heavy ingestion engine
        metadata = await load_raw_data(file, file.filename)
        
        # 2. Get our dummy admin user
        admin = db.query(User).filter(User.email == "admin@mospi.gov.in").first()

        # 3. Save to the NEW Dataset model
        new_dataset = Dataset(
            user_id=admin.id,
            filename=file.filename,
            storage_path=metadata["file_path"],
            row_count=metadata["total_rows"],
            # genesis_hash=metadata["genesis_hash"], # Uncomment if you added it to models.py!
            status="pending" 
        )
        db.add(new_dataset)
        db.commit()
        db.refresh(new_dataset)

        return {
            "status": "success",
            "dataset_id": new_dataset.id,
            "data": metadata
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))