import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.db import Base, engine

app = FastAPI(
    title="Schedulo API",
    version="0.1.0",
    description="Scheduling configuration and timetable generation API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)
app.include_router(router)


@app.api_route("/health", methods=["GET", "HEAD"], tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "schedulo-api"}


@app.get("/api/v1", tags=["system"])
def api_info() -> dict[str, str]:
    return {"name": "Schedulo API", "version": "v1", "status": "scaffolded"}
