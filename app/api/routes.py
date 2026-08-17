import os
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import create_access_token, current_user, hash_password, verify_password
from app.db import get_db
from app.models import Absence, Organization, School, User
from app.schemas import AbsenceCreate, LoginRequest, OrganizationCreate, SchoolCreate, SignupRequest, SchoolUpdate
from app.solver.scheduler import generate_timetable

router = APIRouter(prefix="/api/v1")


def _user_response(user: User, token: str) -> dict:
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "email": user.email, "full_name": user.full_name}}


@router.post("/auth/signup")
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, full_name=payload.full_name.strip(), password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_response(user, create_access_token(user.id))


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _user_response(user, create_access_token(user.id))


@router.get("/auth/me")
def me(user_id: str = Depends(current_user), db: Session = Depends(get_db)):
    user = db.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {"id": user.id, "email": user.email, "full_name": user.full_name}


@router.get("/auth/google/start")
def google_start():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    callback = f"{os.getenv('API_PUBLIC_URL', 'http://localhost:8000')}/api/v1/auth/google/callback"
    query = urlencode({"client_id": client_id, "redirect_uri": callback, "response_type": "code", "scope": "openid email profile", "access_type": "offline", "prompt": "select_account"})
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@router.get("/auth/google/callback")
async def google_callback(code: str, db: Session = Depends(get_db)):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    callback = f"{os.getenv('API_PUBLIC_URL', 'http://localhost:8000')}/api/v1/auth/google/callback"
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post("https://oauth2.googleapis.com/token", data={"code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": callback, "grant_type": "authorization_code"})
        if token_response.is_error:
            raise HTTPException(status_code=400, detail="Google authorization failed")
        access_token = token_response.json().get("access_token")
        profile_response = await client.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {access_token}"})
        if profile_response.is_error:
            raise HTTPException(status_code=400, detail="Could not read Google profile")
    profile = profile_response.json()
    email = profile.get("email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email address")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, full_name=profile.get("name", ""), password_hash=None)
        db.add(user)
        db.commit()
        db.refresh(user)
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    return RedirectResponse(f"{frontend_origin}/oauth/callback?token={create_access_token(user.id)}")


@router.post("/organizations")
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db), user_id: str = Depends(current_user)):
    existing = db.query(Organization).filter(Organization.owner_id == user_id).first()
    if existing:
        school = db.get(School, existing.school_id)
        return {"id": existing.id, "name": existing.name, "type": existing.type, "school_id": existing.school_id, "academic_year": school.academic_year if school else ""}
    school = School(name=payload.name, academic_year=payload.academic_year, setup={}, timetable=[])
    db.add(school)
    db.flush()
    organization = Organization(name=payload.name, type=payload.type, owner_id=user_id, school_id=school.id)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return {"id": organization.id, "name": organization.name, "type": organization.type, "school_id": organization.school_id, "academic_year": school.academic_year}


@router.get("/organizations/me")
def get_my_organization(db: Session = Depends(get_db), user_id: str = Depends(current_user)):
    organization = db.query(Organization).filter(Organization.owner_id == user_id).first()
    if not organization:
        return None
    school = db.get(School, organization.school_id)
    return {"id": organization.id, "name": organization.name, "type": organization.type, "school_id": organization.school_id, "academic_year": school.academic_year if school else ""}


@router.post("/schools")
def create_school(payload: SchoolCreate, db: Session = Depends(get_db)):
    school = School(name=payload.name, academic_year=payload.academic_year, setup={}, timetable=[])
    db.add(school)
    db.commit()
    db.refresh(school)
    return {"id": school.id, "name": school.name, "academic_year": school.academic_year, "setup": school.setup, "timetable": school.timetable}


@router.get("/schools/{school_id}")
def get_school(school_id: int, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    return {"id": school.id, "name": school.name, "academic_year": school.academic_year, "setup": school.setup, "timetable": school.timetable}


@router.put("/schools/{school_id}/setup")
def update_setup(school_id: int, payload: SchoolUpdate, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    if payload.name is not None:
        school.name = payload.name
    if payload.academic_year is not None:
        school.academic_year = payload.academic_year
    school.setup = payload.setup
    db.commit()
    db.refresh(school)
    return {"id": school.id, "name": school.name, "academic_year": school.academic_year, "setup": school.setup}


@router.post("/schools/{school_id}/generate")
def generate_school_timetable(school_id: int, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    result = generate_timetable(school.setup or {})
    if result["status"] != "INFEASIBLE":
        school.timetable = result["entries"]
        db.commit()
    return result


@router.get("/schools/{school_id}/timetable")
def get_timetable(school_id: int, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    return {"entries": school.timetable or []}


@router.post("/schools/{school_id}/absences")
def create_absence(school_id: int, payload: AbsenceCreate, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    affected = [entry for entry in (school.timetable or []) if entry.get("teacher") == payload.teacher]
    absence = Absence(school_id=school_id, date=payload.date, teacher=payload.teacher, reason=payload.reason, substitutions=[])
    db.add(absence)
    db.commit()
    return {"id": absence.id, "date": payload.date, "teacher": payload.teacher, "affected": affected, "candidates": _substitute_candidates(school, payload.teacher, affected)}


def _substitute_candidates(school: School, absent_teacher: str, affected: list[dict]) -> list[str]:
    teachers = {item.get("teacher") for item in (school.setup or {}).get("assignments", []) if item.get("teacher") and item.get("teacher") != absent_teacher}
    busy = {item.get("teacher") for item in (school.timetable or []) if item.get("period") in {entry.get("period") for entry in affected}}
    return sorted(teacher for teacher in teachers if teacher not in busy)
