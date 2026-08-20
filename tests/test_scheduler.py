from app.solver.scheduler import generate_timetable, move_timetable_entry


def test_class_period_limits_are_respected() -> None:
    result = generate_timetable(
        {
            "days": 5,
            "periods": 7,
            "classPeriods": {"Class 1": 5, "Class 2": 7},
            "classes": ["Class 1", "Class 2"],
            "sections": {"Class 1": ["A"], "Class 2": ["A"]},
            "assignments": [
                {
                    "teacher": "Aarav",
                    "subject": "English",
                    "className": "Class 1 A",
                    "periods": 5,
                },
                {
                    "teacher": "Priya",
                    "subject": "Mathematics",
                    "className": "Class 2 A",
                    "periods": 7,
                },
            ],
        },
    )

    assert result["status"] in {"OPTIMAL", "FEASIBLE"}
    assert max(
        entry["period"]
        for entry in result["entries"]
        if entry["className"] == "Class 1 A"
    ) <= 5
    assert max(
        entry["period"]
        for entry in result["entries"]
        if entry["className"] == "Class 2 A"
    ) <= 7


def test_time_rules_are_hard_constraints() -> None:
    result = generate_timetable(
        {
            "days": 5,
            "periods": 5,
            "classPeriods": {"Class 1": 5},
            "classes": ["Class 1"],
            "sections": {"Class 1": ["A"]},
            "timing": {"messAfter": 2, "lunchAfter": 4},
            "timeRules": [
                {
                    "subject": "Mathematics",
                    "className": "All classes",
                    "relation": "beforeMess",
                    "hard": True,
                }
            ],
            "assignments": [
                {
                    "teacher": "Priya",
                    "subject": "Mathematics",
                    "className": "Class 1 A",
                    "periods": 2,
                },
                {
                    "teacher": "Aarav",
                    "subject": "English",
                    "className": "Class 1 A",
                    "periods": 3,
                },
            ],
        },
    )

    assert result["status"] in {"OPTIMAL", "FEASIBLE"}
    assert all(
        entry["period"] <= 2
        for entry in result["entries"]
        if entry["subject"] == "Mathematics"
    )


def test_move_rejects_teacher_double_booking() -> None:
    entries = [
        {
            "entryId": "english-class-1",
            "day": "Monday",
            "dayIndex": 0,
            "period": 1,
            "className": "Class 1 A",
            "subject": "English",
            "teacher": "Aarav",
        },
        {
            "entryId": "english-class-2",
            "day": "Monday",
            "dayIndex": 0,
            "period": 2,
            "className": "Class 2 A",
            "subject": "English",
            "teacher": "Aarav",
        },
    ]

    result = move_timetable_entry(
        entries,
        {
            "days": 5,
            "periods": 5,
            "classes": ["Class 1", "Class 2"],
            "classPeriods": {"Class 1": 5, "Class 2": 5},
        },
        {
            "entryId": "english-class-2",
            "targetDay": "Monday",
            "targetPeriod": 1,
            "swap": False,
        },
    )

    assert result["ok"] is False
    assert any("double-booked" in error for error in result["errors"])
