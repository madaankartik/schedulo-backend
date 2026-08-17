from datetime import datetime

from pydantic import BaseModel, Field


def default_academic_year() -> str:
    year = datetime.now().year
    return f"{year}–{str(year + 1)[-2:]}"


class SchoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    academic_year: str = Field(default_factory=default_academic_year, max_length=30)


class SchoolUpdate(BaseModel):
    name: str | None = None
    academic_year: str | None = None
    setup: dict = Field(default_factory=dict)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    type: str = Field(default="school", pattern="^(school|college)$")
    academic_year: str = Field(default_factory=default_academic_year, max_length=30)


class AbsenceCreate(BaseModel):
    date: str
    teacher: str
    reason: str = ""


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=6, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)
