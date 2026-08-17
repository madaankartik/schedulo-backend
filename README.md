# Schedulo Backend

FastAPI service for Schedulo. This service will own authentication integration, school configuration, timetable persistence, validation, and the OR-Tools CP-SAT scheduling engine.

## Local setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check: `http://localhost:8000/health`

## Planned modules

- `app/api/` — HTTP routes
- `app/models/` — database models
- `app/schemas/` — request/response schemas
- `app/services/` — application services
- `app/solver/` — CP-SAT model and diagnostics
- `tests/` — API and solver tests
