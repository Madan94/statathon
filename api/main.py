from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session
from database.database import Base, engine, SessionLocal
from auth.routes import router as auth_router
from datasets.routes import router as datasets_router
from analysis.routes import router as analysis_router

app = FastAPI(title="Statathon")
Base.metadata.create_all(bind=engine)
app.include_router(auth_router)
app.include_router(datasets_router)
app.include_router(analysis_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    """Verify SQLAlchemy can reach the database (use after pointing DATABASE_URL at Neon, etc.)."""
    db: Session = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()