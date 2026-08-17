from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.models import Absence, Organization, School
from app.schemas import AbsenceCreate, OrganizationCreate, SchoolCreate, SchoolUpdate
from app.solver.scheduler import generate_timetable

router = APIRouter(prefix="/api/v1")


@router.post("/organizations")
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db), user_id: str = Depends(current_user)):
    school = School(name=payload.name, academic_year="2026–27", setup={}, timetable=[])
    db.add(school)
    db.flush()
    organization = Organization(name=payload.name, type=payload.type, owner_id=user_id, school_id=school.id)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return {"id": organization.id, "name": organization.name, "type": organization.type, "school_id": organization.school_id, "academic_year": school.academic_year}


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
