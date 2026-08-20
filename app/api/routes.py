import os
from datetime import date as date_cls
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import create_access_token, current_user, hash_password, verify_password
from app.db import get_db
from app.models import Absence, Organization, School, User
from app.schemas import AbsenceCreate, AbsencePreview, LoginRequest, OrganizationCreate, SchoolCreate, SignupRequest, SchoolUpdate
from app.solver.scheduler import generate_timetable, move_timetable_entry, validate_timetable_entries

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
    return RedirectResponse(f"{frontend_origin}/?token={create_access_token(user.id)}")


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
    setup = school.setup or {}
    return {
        "id": school.id,
        "name": school.name,
        "academic_year": school.academic_year,
        "setup": setup,
        "timetable": school.timetable or [],
        "draft_timetable": setup.get("draftTimetable"),
    }


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
        result = {
            **result,
            "mode": "draft",
            "message": "Draft generated. Save it as current when you are happy with it.",
        }
        setup = dict(school.setup or {})
        setup["draftTimetable"] = result
        school.setup = setup
        db.commit()
    return result


@router.get("/schools/{school_id}/timetable")
def get_timetable(school_id: int, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    setup = school.setup or {}
    return {"entries": school.timetable or [], "draft": setup.get("draftTimetable")}


@router.post("/schools/{school_id}/timetable/save-draft")
def save_draft_timetable(school_id: int, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    setup = dict(school.setup or {})
    draft = setup.get("draftTimetable") or {}
    entries = draft.get("entries") or []
    if not entries:
        raise HTTPException(status_code=400, detail="Generate a draft timetable before saving.")
    validation = validate_timetable_entries(entries, setup)
    if not validation["ok"]:
        raise HTTPException(status_code=409, detail=validation["errors"])
    school.timetable = entries
    setup["savedTimetableMeta"] = {
        "source": "draft",
        "entries": len(entries),
        "status": draft.get("status", "SAVED"),
    }
    school.setup = setup
    db.commit()
    return {"status": "SAVED", "entries": school.timetable, "draft": draft}


@router.post("/schools/{school_id}/timetable/validate")
def validate_timetable(school_id: int, payload: dict, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    source = payload.get("source", "current")
    entries = _entries_for_source(school, source)
    return validate_timetable_entries(entries, school.setup or {})


@router.patch("/schools/{school_id}/timetable/move")
def move_timetable_slot(school_id: int, payload: dict, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    source = payload.get("source", "draft")
    entries = _entries_for_source(school, source)
    if not entries:
        raise HTTPException(status_code=400, detail="No timetable entries are available to edit.")
    result = move_timetable_entry(entries, school.setup or {}, payload)
    if not result["ok"]:
        return {"ok": False, "entries": entries, "errors": result["errors"]}
    if source == "current":
        school.timetable = result["entries"]
    else:
        setup = dict(school.setup or {})
        draft = dict(setup.get("draftTimetable") or {})
        draft["entries"] = result["entries"]
        draft["mode"] = "draft"
        draft["edited"] = True
        setup["draftTimetable"] = draft
        school.setup = setup
    db.commit()
    return {"ok": True, "entries": result["entries"], "source": source}


@router.get("/schools/{school_id}/absences")
def get_absence_plan(school_id: int, date: str, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    day = _day_name(date)
    saved_rows = (
        db.query(Absence)
        .filter(Absence.school_id == school_id, Absence.date == date)
        .order_by(Absence.id.asc())
        .all()
    )
    if not saved_rows:
        return _empty_absence_plan(date, day)

    items = saved_rows[0].substitutions or []
    absences = [
        {"teacher": row.teacher, "reason": row.reason or ""}
        for row in saved_rows
        if row.teacher
    ]
    if not items and absences:
        items = _build_absence_plan(school, AbsencePreview(date=date, absences=absences))[
            "items"
        ]
    return _with_absence_summary(
        {
            "date": date,
            "day": day,
            "absences": absences,
            "items": items,
            "saved": True,
        }
    )


@router.post("/schools/{school_id}/absences/preview")
def preview_absence_plan(school_id: int, payload: AbsencePreview, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    return _build_absence_plan(school, payload)


@router.post("/schools/{school_id}/absences")
def save_absence_plan(school_id: int, payload: AbsenceCreate, db: Session = Depends(get_db)):
    school = db.get(School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    plan = _build_absence_plan(school, payload)
    incoming_substitutions = payload.substitutions or []
    if incoming_substitutions:
        incoming_by_key = {
            _coverage_key(item): item for item in incoming_substitutions if _coverage_key(item)
        }
        for item in plan["items"]:
            incoming = incoming_by_key.get(_coverage_key(item))
            if not incoming:
                continue
            substitute = (incoming.get("substitute") or "").strip()
            item["substitute"] = substitute
            item["status"] = "covered" if substitute else "needs_attention"
            item["reason"] = (
                incoming.get("reason")
                or item.get("reason")
                or ("Manually selected" if substitute else "No substitute selected")
            )
        plan = _with_absence_summary(plan)

    (
        db.query(Absence)
        .filter(Absence.school_id == school_id, Absence.date == payload.date)
        .delete(synchronize_session=False)
    )
    for absence in plan["absences"]:
        db.add(
            Absence(
                school_id=school_id,
                date=payload.date,
                teacher=absence["teacher"],
                reason=absence.get("reason", ""),
                substitutions=plan["items"],
            )
        )
    db.commit()
    plan["saved"] = True
    return plan


def _entries_for_source(school: School, source: str) -> list[dict]:
    if source == "current":
        return school.timetable or []
    setup = school.setup or {}
    draft = setup.get("draftTimetable") or {}
    return draft.get("entries") or []


def _day_name(date_text: str) -> str:
    try:
        return date_cls.fromisoformat(date_text).strftime("%A")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date must use YYYY-MM-DD format") from exc


def _empty_absence_plan(date: str, day: str) -> dict:
    return {
        "date": date,
        "day": day,
        "absences": [],
        "items": [],
        "summary": {
            "absentTeachers": 0,
            "totalAffected": 0,
            "covered": 0,
            "needsAttention": 0,
        },
        "saved": False,
    }


def _normalise_absences(payload: AbsencePreview) -> list[dict]:
    rows = [
        {"teacher": item.teacher.strip(), "reason": item.reason.strip()}
        for item in payload.absences
        if item.teacher.strip()
    ]
    if payload.teacher and payload.teacher.strip():
        rows.append(
            {
                "teacher": payload.teacher.strip(),
                "reason": payload.reason.strip(),
            }
        )
    seen = set()
    normalised = []
    for row in rows:
        key = row["teacher"].casefold()
        if key in seen:
            continue
        seen.add(key)
        normalised.append(row)
    return normalised


def _teacher_names(school: School) -> list[str]:
    setup = school.setup or {}
    names = [
        (teacher.get("name") or "").strip()
        for teacher in setup.get("teachers", [])
        if (teacher.get("name") or "").strip()
    ]
    names.extend(
        (assignment.get("teacher") or "").strip()
        for assignment in setup.get("assignments", [])
        if (assignment.get("teacher") or "").strip()
    )
    return list(dict.fromkeys(names))


def _teacher_assignments(school: School, teacher: str | None = None) -> list[dict]:
    assignments = [
        item
        for item in (school.setup or {}).get("assignments", [])
        if item.get("teacher")
    ]
    if teacher is None:
        return assignments
    return [item for item in assignments if item.get("teacher") == teacher]


def _coverage_key(item: dict) -> tuple | None:
    day = item.get("day")
    period = item.get("period")
    class_name = item.get("className")
    subject = item.get("subject")
    absent_teacher = item.get("absentTeacher")
    if not all([day, period, class_name, subject, absent_teacher]):
        return None
    return day, period, class_name, subject, absent_teacher


def _candidate_reason(teaches_subject: bool, teaches_class: bool, daily_load: int) -> str:
    reasons = []
    if teaches_subject:
        reasons.append("teaches this subject")
    if teaches_class:
        reasons.append("knows this class")
    reasons.append(f"{daily_load} base periods that day")
    return ", ".join(reasons)


def _rank_candidates(
    school: School,
    target_day: str,
    affected_entry: dict,
    absent_names: set[str],
    planned_busy: dict[int, set[str]],
    planned_sub_loads: dict[str, int],
) -> list[dict]:
    period = affected_entry.get("period")
    timetable = school.timetable or []
    busy = {
        item.get("teacher")
        for item in timetable
        if item.get("day") == target_day and item.get("period") == period and item.get("teacher")
    }
    busy |= planned_busy.get(period, set())
    candidates = []
    for teacher in _teacher_names(school):
        if teacher in absent_names or teacher in busy:
            continue
        teacher_rows = _teacher_assignments(school, teacher)
        teaches_subject = any(
            row.get("subject") == affected_entry.get("subject") for row in teacher_rows
        )
        teaches_class = any(
            row.get("className") == affected_entry.get("className") for row in teacher_rows
        )
        daily_load = sum(
            1
            for item in timetable
            if item.get("day") == target_day and item.get("teacher") == teacher
        )
        score = 20
        if teaches_subject:
            score += 70
        if teaches_class:
            score += 25
        score -= daily_load * 2
        score -= planned_sub_loads.get(teacher, 0) * 5
        candidates.append(
            {
                "teacher": teacher,
                "score": score,
                "reason": _candidate_reason(teaches_subject, teaches_class, daily_load),
            }
        )
    return sorted(candidates, key=lambda item: (-item["score"], item["teacher"]))


def _build_absence_plan(school: School, payload: AbsencePreview) -> dict:
    day = _day_name(payload.date)
    absences = _normalise_absences(payload)
    absent_names = {item["teacher"] for item in absences}
    if not absences:
        return _empty_absence_plan(payload.date, day)

    timetable = school.timetable or []
    affected_entries = [
        entry
        for entry in timetable
        if entry.get("day") == day and entry.get("teacher") in absent_names
    ]
    affected_entries.sort(
        key=lambda entry: (
            int(entry.get("period") or 0),
            entry.get("className", ""),
            entry.get("subject", ""),
        )
    )

    planned_busy: dict[int, set[str]] = {}
    planned_sub_loads: dict[str, int] = {}
    items = []
    for entry in affected_entries:
        period = int(entry.get("period") or 0)
        candidates = _rank_candidates(
            school,
            day,
            entry,
            absent_names,
            planned_busy,
            planned_sub_loads,
        )
        chosen = candidates[0] if candidates else None
        substitute = chosen["teacher"] if chosen else ""
        if substitute:
            planned_busy.setdefault(period, set()).add(substitute)
            planned_sub_loads[substitute] = planned_sub_loads.get(substitute, 0) + 1
        items.append(
            {
                "day": entry.get("day"),
                "period": period,
                "className": entry.get("className"),
                "subject": entry.get("subject"),
                "absentTeacher": entry.get("teacher"),
                "substitute": substitute,
                "status": "covered" if substitute else "needs_attention",
                "reason": chosen["reason"] if chosen else "No free teacher found for this period",
                "candidates": candidates[:6],
                "sourceEntry": entry,
            }
        )

    return _with_absence_summary(
        {
            "date": payload.date,
            "day": day,
            "absences": absences,
            "items": items,
            "saved": False,
        }
    )


def _with_absence_summary(plan: dict) -> dict:
    items = plan.get("items", [])
    covered = sum(1 for item in items if item.get("status") == "covered")
    plan["summary"] = {
        "absentTeachers": len(plan.get("absences", [])),
        "totalAffected": len(items),
        "covered": covered,
        "needsAttention": max(0, len(items) - covered),
    }
    return plan
