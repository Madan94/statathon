from fastapi import FastAPI
from database.database import Base, engine
from auth.routes import router as auth_router
from datasets.routes import router as datasets_router
from analysis.routes import router as analysis_router

app = FastAPI(title="Statathon")
Base.metadata.create_all(bind=engine)
app.include_router(auth_router)
app.include_router(datasets_router)
app.include_router(analysis_router)