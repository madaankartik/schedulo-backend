import math
from collections import defaultdict

from ortools.sat.python import cp_model


def _class_names(setup: dict) -> list[str]:
    classes = setup.get("classes", [])
    sections = setup.get("sections", {})
    names = []
    for class_name in classes:
        for section in sections.get(class_name, ["A"]):
            names.append(f"{class_name} {section}")
    return names or ["Demo Class A"]


def generate_timetable(setup: dict) -> dict:
    days = int(setup.get("days", 5))
    periods = int(setup.get("periods", 8))
    assignments = setup.get("assignments", [])
    if not assignments:
        return {"status": "INFEASIBLE", "entries": [], "diagnostics": ["Add at least one teaching assignment before generating."]}

    activities = []
    for assignment in assignments:
        count = max(1, int(assignment.get("periods", 1)))
        for unit in range(count):
            activities.append({**assignment, "unit": unit + 1})

    model = cp_model.CpModel()
    slot_count = days * periods
    variables = []
    by_class_slot = defaultdict(list)
    by_teacher_slot = defaultdict(list)

    for index, activity in enumerate(activities):
        row = [model.NewBoolVar(f"activity_{index}_slot_{slot}") for slot in range(slot_count)]
        model.Add(sum(row) == 1)
        variables.append(row)
        for slot, variable in enumerate(row):
            class_name = activity.get("className", "Demo Class A")
            teacher = activity.get("teacher", "Unassigned")
            by_class_slot[(class_name, slot)].append(variable)
            by_teacher_slot[(teacher, slot)].append(variable)

    for variables_at_slot in by_class_slot.values():
        model.Add(sum(variables_at_slot) <= 1)
    for variables_at_slot in by_teacher_slot.values():
        model.Add(sum(variables_at_slot) <= 1)

    # Prefer spreading repeated subjects over different days when possible.
    day_subject = defaultdict(list)
    subject_totals = defaultdict(int)
    for index, activity in enumerate(activities):
        subject_key = (activity.get("className", "Demo Class A"), activity.get("subject", "Subject"))
        subject_totals[subject_key] += 1
        for slot, variable in enumerate(variables[index]):
            day = slot // periods
            day_subject[(activity.get("className", "Demo Class A"), activity.get("subject", "Subject"), day)].append(variable)
    for (class_name, subject, _day), variables_for_day in day_subject.items():
        model.Add(sum(variables_for_day) <= math.ceil(subject_totals[(class_name, subject)] / days))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "INFEASIBLE",
            "entries": [],
            "diagnostics": ["The current assignments cannot fit into the available teacher, class, and period slots."],
        }

    entries = []
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][:days]
    for index, activity in enumerate(activities):
        for slot, variable in enumerate(variables[index]):
            if solver.Value(variable):
                entries.append({
                    "day": day_names[slot // periods],
                    "dayIndex": slot // periods,
                    "period": (slot % periods) + 1,
                    "className": activity.get("className", "Demo Class A"),
                    "subject": activity.get("subject", "Subject"),
                    "teacher": activity.get("teacher", "Unassigned"),
                    "room": activity.get("room", "—"),
                    "unit": activity["unit"],
                })
                break
    return {"status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE", "entries": entries, "diagnostics": [], "solveSeconds": round(solver.WallTime(), 3)}
