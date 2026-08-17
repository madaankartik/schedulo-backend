from pydantic import BaseModel, Field


class SchoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    academic_year: str = Field(default="2026–27", max_length=30)


class SchoolUpdate(BaseModel):
    name: str | None = None
    academic_year: str | None = None
    setup: dict = Field(default_factory=dict)


class AbsenceCreate(BaseModel):
    date: str
    teacher: str
    reason: str = ""
