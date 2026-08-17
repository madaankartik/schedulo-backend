from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Schedulo API",
    version="0.1.0",
    description="Scheduling configuration and timetable generation API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "schedulo-api"}


@app.get("/api/v1", tags=["system"])
def api_info() -> dict[str, str]:
    return {"name": "Schedulo API", "version": "v1", "status": "scaffolded"}
