import math
from collections import defaultdict
from copy import deepcopy

from ortools.sat.python import cp_model

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
TIME_RULE_LABELS = {
    "beforeMess": "before mess",
    "afterMess": "after mess",
    "beforeLunch": "before lunch",
    "afterLunch": "after lunch",
}


def _class_names(setup: dict) -> list[str]:
    classes = setup.get("classes", [])
    sections = setup.get("sections", {})
    names = []
    for class_name in classes:
        for section in sections.get(class_name, ["A"]):
            names.append(f"{class_name} {section}")
    return names or ["Demo Class A"]


def _base_class_name(class_name: str, classes: list[str]) -> str:
    for name in sorted(classes, key=len, reverse=True):
        if class_name == name or class_name.startswith(f"{name} "):
            return name
    return class_name


def _class_daily_periods(class_name: str, classes: list[str], class_periods: dict, default_periods: int) -> int:
    base_name = _base_class_name(class_name, classes)
    return max(1, int(class_periods.get(base_name) or default_periods))


def _entry_identifier(activity: dict, index: int) -> str:
    parts = [
        activity.get("className", "Class"),
        activity.get("subject", "Subject"),
        activity.get("teacher", "Teacher"),
        str(activity.get("unit", 1)),
        str(index + 1),
    ]
    return "|".join(part.replace("|", "/") for part in parts)


def _rule_applies(rule: dict, activity: dict) -> bool:
    subject = rule.get("subject")
    if subject and subject != activity.get("subject"):
        return False
    target_class = rule.get("className") or ""
    if not target_class or target_class == "All classes":
        return True
    class_name = activity.get("className", "")
    return class_name == target_class or class_name.startswith(f"{target_class} ")


def _rule_limit(rule: dict, setup: dict) -> int | None:
    timing = setup.get("timing") or {}
    relation = rule.get("relation")
    if relation in {"beforeMess", "afterMess"}:
        value = timing.get("messAfter")
    elif relation in {"beforeLunch", "afterLunch"}:
        value = timing.get("lunchAfter")
    else:
        value = None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _period_allowed_by_rule(rule: dict, activity: dict, period: int, setup: dict) -> bool:
    if not _rule_applies(rule, activity):
        return True
    limit = _rule_limit(rule, setup)
    relation = rule.get("relation")
    if not limit:
        return True
    if relation in {"beforeMess", "beforeLunch"}:
        return period <= limit
    if relation in {"afterMess", "afterLunch"}:
        return period > limit
    return True


def _period_allowed_by_rules(activity: dict, period: int, setup: dict) -> bool:
    for rule in setup.get("timeRules") or []:
        if rule.get("hard", True) and not _period_allowed_by_rule(rule, activity, period, setup):
            return False
    return True


def _time_rule_errors(entry: dict, setup: dict) -> list[str]:
    errors = []
    period = int(entry.get("period", 0) or 0)
    for rule in setup.get("timeRules") or []:
        if not rule.get("hard", True):
            continue
        if _period_allowed_by_rule(rule, entry, period, setup):
            continue
        label = TIME_RULE_LABELS.get(rule.get("relation"), "at the configured time")
        scope = rule.get("className") or "all classes"
        errors.append(f"{entry.get('subject', 'Subject')} for {scope} must be {label}.")
    return errors


def _coerce_day_index(day: str | int | None, fallback_index: int | None = None) -> int:
    if fallback_index is not None:
        return max(0, min(len(DAY_NAMES) - 1, int(fallback_index)))
    if isinstance(day, int):
        return max(0, min(len(DAY_NAMES) - 1, day))
    if isinstance(day, str):
        if day in DAY_NAMES:
            return DAY_NAMES.index(day)
        title_day = day.strip().title()
        if title_day in DAY_NAMES:
            return DAY_NAMES.index(title_day)
    return 0


def _entry_day_index(entry: dict) -> int:
    return _coerce_day_index(entry.get("day"), entry.get("dayIndex"))


def _entry_key(entry: dict, index: int) -> str:
    return entry.get("entryId") or entry.get("id") or f"legacy:{index}"


def _find_entry_index(entries: list[dict], entry_id: str | None = None, index: int | None = None) -> int | None:
    if entry_id:
        for row_index, entry in enumerate(entries):
            if _entry_key(entry, row_index) == entry_id:
                return row_index
    if index is not None:
        try:
            row_index = int(index)
        except (TypeError, ValueError):
            return None
        if 0 <= row_index < len(entries):
            return row_index
    return None


def validate_timetable_entries(entries: list[dict], setup: dict | None = None) -> dict:
    setup = setup or {}
    classes = setup.get("classes", [])
    class_periods = setup.get("classPeriods", {}) or {}
    default_periods = max(1, int(setup.get("periods") or 8))
    errors = []
    by_class_slot = defaultdict(list)
    by_teacher_slot = defaultdict(list)

    for index, entry in enumerate(entries):
        day_index = _entry_day_index(entry)
        period = int(entry.get("period", 0) or 0)
        class_name = entry.get("className", "Class")
        teacher = entry.get("teacher", "")
        allowed_periods = _class_daily_periods(class_name, classes, class_periods, default_periods)
        if period < 1:
            errors.append(f"{class_name} has an invalid period number.")
        if period > allowed_periods:
            errors.append(f"{class_name} only has {allowed_periods} periods, but one entry is in P{period}.")
        errors.extend(_time_rule_errors(entry, setup))
        by_class_slot[(class_name, day_index, period)].append(index)
        if teacher and teacher != "Unassigned":
            by_teacher_slot[(teacher, day_index, period)].append(index)

    for (class_name, day_index, period), indexes in by_class_slot.items():
        if len(indexes) > 1:
            errors.append(f"{class_name} has {len(indexes)} classes in {DAY_NAMES[day_index]} P{period}.")
    for (teacher, day_index, period), indexes in by_teacher_slot.items():
        if len(indexes) > 1:
            errors.append(f"{teacher} is double-booked in {DAY_NAMES[day_index]} P{period}.")

    return {"ok": not errors, "errors": errors}


def move_timetable_entry(entries: list[dict], setup: dict, payload: dict) -> dict:
    next_entries = deepcopy(entries or [])
    source_index = _find_entry_index(
        next_entries,
        payload.get("entryId"),
        payload.get("entryIndex"),
    )
    if source_index is None:
        return {"ok": False, "entries": entries, "errors": ["Could not find the period you tried to move."]}

    target_day_index = _coerce_day_index(payload.get("targetDay"), payload.get("targetDayIndex"))
    target_period = int(payload.get("targetPeriod") or 0)
    if target_period < 1:
        return {"ok": False, "entries": entries, "errors": ["Choose a valid target period."]}

    source = next_entries[source_index]
    source_slot = {
        "day": source.get("day"),
        "dayIndex": source.get("dayIndex"),
        "period": source.get("period"),
    }
    target_index = _find_entry_index(next_entries, payload.get("targetEntryId"), payload.get("targetEntryIndex"))
    if target_index is not None and target_index != source_index and payload.get("swap", True):
        target = next_entries[target_index]
        target_slot = {
            "day": target.get("day"),
            "dayIndex": target.get("dayIndex"),
            "period": target.get("period"),
        }
        target.update({
            "day": DAY_NAMES[_coerce_day_index(source_slot["day"], source_slot["dayIndex"])],
            "dayIndex": _coerce_day_index(source_slot["day"], source_slot["dayIndex"]),
            "period": int(source_slot["period"]),
            "manual": True,
            "locked": True,
        })
        source.update({
            "day": DAY_NAMES[_coerce_day_index(target_slot["day"], target_slot["dayIndex"])],
            "dayIndex": _coerce_day_index(target_slot["day"], target_slot["dayIndex"]),
            "period": int(target_slot["period"]),
            "manual": True,
            "locked": True,
        })
    else:
        source.update({
            "day": DAY_NAMES[target_day_index],
            "dayIndex": target_day_index,
            "period": target_period,
            "manual": True,
            "locked": True,
        })

    validation = validate_timetable_entries(next_entries, setup)
    if not validation["ok"]:
        return {"ok": False, "entries": entries, "errors": validation["errors"]}
    return {"ok": True, "entries": next_entries, "errors": []}


def generate_timetable(setup: dict) -> dict:
    days = int(setup.get("days", 5))
    classes = setup.get("classes", [])
    class_periods = setup.get("classPeriods", {}) or {}
    periods = max(1, int(setup.get("periods") or 8))
    max_periods = max([periods, *[max(1, int(value or 1)) for value in class_periods.values()]])
    assignments = setup.get("assignments", [])
    if not assignments:
        return {"status": "INFEASIBLE", "entries": [], "diagnostics": ["Add at least one teaching assignment before generating."]}

    activities = []
    for assignment in assignments:
        count = max(1, int(assignment.get("periods", 1)))
        for unit in range(count):
            activities.append({**assignment, "unit": unit + 1})

    model = cp_model.CpModel()
    slot_count = days * max_periods
    variables = []
    by_class_slot = defaultdict(list)
    by_teacher_slot = defaultdict(list)

    for index, activity in enumerate(activities):
        row = [model.NewBoolVar(f"activity_{index}_slot_{slot}") for slot in range(slot_count)]
        model.Add(sum(row) == 1)
        variables.append(row)
        allowed_periods = _class_daily_periods(activity.get("className", "Demo Class A"), classes, class_periods, periods)
        for slot, variable in enumerate(row):
            class_name = activity.get("className", "Demo Class A")
            teacher = activity.get("teacher", "Unassigned")
            period_number = (slot % max_periods) + 1
            if slot % max_periods >= allowed_periods:
                model.Add(variable == 0)
            if not _period_allowed_by_rules(activity, period_number, setup):
                model.Add(variable == 0)
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
            day = slot // max_periods
            day_subject[(activity.get("className", "Demo Class A"), activity.get("subject", "Subject"), day)].append(variable)
    for (class_name, subject, _day), variables_for_day in day_subject.items():
        model.Add(sum(variables_for_day) <= math.ceil(subject_totals[(class_name, subject)] / days))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "INFEASIBLE",
            "entries": [],
            "diagnostics": ["The current assignments cannot fit into the available teacher, class, and period slots."],
        }

    entries = []
    day_names = DAY_NAMES[:days]
    for index, activity in enumerate(activities):
        for slot, variable in enumerate(variables[index]):
            if solver.Value(variable):
                entry_id = _entry_identifier(activity, index)
                entries.append({
                    "entryId": entry_id,
                    "day": day_names[slot // max_periods],
                    "dayIndex": slot // max_periods,
                    "period": (slot % max_periods) + 1,
                    "className": activity.get("className", "Demo Class A"),
                    "subject": activity.get("subject", "Subject"),
                    "teacher": activity.get("teacher", "Unassigned"),
                    "room": activity.get("room", "—"),
                    "unit": activity["unit"],
                })
                break
    return {"status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE", "entries": entries, "diagnostics": [], "solveSeconds": round(solver.WallTime(), 3)}
