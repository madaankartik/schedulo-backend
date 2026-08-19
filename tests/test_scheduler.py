from app.solver.scheduler import generate_timetable


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
