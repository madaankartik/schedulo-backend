from copy import deepcopy

from app.api.routes import _build_absence_plan
from app.models import School
from app.schemas import AbsencePreview, AbsenceTeacher


def test_absence_plan_uses_saved_timetable_without_mutating_it() -> None:
    timetable = [
        {
            "day": "Monday",
            "period": 1,
            "className": "Class 1 A",
            "subject": "English",
            "teacher": "Aarav Sharma",
        },
        {
            "day": "Monday",
            "period": 1,
            "className": "Class 2 A",
            "subject": "Mathematics",
            "teacher": "Priya Mehta",
        },
        {
            "day": "Monday",
            "period": 2,
            "className": "Class 1 A",
            "subject": "English",
            "teacher": "Aarav Sharma",
        },
        {
            "day": "Tuesday",
            "period": 1,
            "className": "Class 1 A",
            "subject": "English",
            "teacher": "Aarav Sharma",
        },
    ]
    original_timetable = deepcopy(timetable)
    school = School(
        name="Green Valley Public School",
        academic_year="2026-27",
        timetable=timetable,
        setup={
            "teachers": [
                {"name": "Aarav Sharma"},
                {"name": "Priya Mehta"},
                {"name": "Kabir Singh"},
            ],
            "assignments": [
                {
                    "teacher": "Aarav Sharma",
                    "subject": "English",
                    "className": "Class 1 A",
                    "periods": 2,
                },
                {
                    "teacher": "Priya Mehta",
                    "subject": "Mathematics",
                    "className": "Class 2 A",
                    "periods": 1,
                },
                {
                    "teacher": "Kabir Singh",
                    "subject": "English",
                    "className": "Class 1 A",
                    "periods": 2,
                },
            ],
        },
    )

    plan = _build_absence_plan(
        school,
        AbsencePreview(
            date="2026-08-17",
            absences=[AbsenceTeacher(teacher="Aarav Sharma", reason="Leave")],
        ),
    )

    assert school.timetable == original_timetable
    assert plan["day"] == "Monday"
    assert plan["summary"]["totalAffected"] == 2
    assert plan["summary"]["covered"] == 2
    assert {item["absentTeacher"] for item in plan["items"]} == {"Aarav Sharma"}
    assert all(item["substitute"] != "Aarav Sharma" for item in plan["items"])

    first_period_candidates = [
        candidate["teacher"]
        for item in plan["items"]
        if item["period"] == 1
        for candidate in item["candidates"]
    ]
    assert "Priya Mehta" not in first_period_candidates
    assert "Kabir Singh" in first_period_candidates
