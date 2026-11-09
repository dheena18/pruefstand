"""Schedule rule of the workflow guard: off-minute crons only (T0.2)."""

from workflow_model import Doc, triggers


def crons(doc: Doc) -> list[str]:
    """Return findings for cron schedules that start at minute 0 or every minute."""
    schedule = triggers(doc).get("schedule")
    out = []
    for entry in schedule if isinstance(schedule, list) else []:
        cron = str(entry.get("cron", "")) if isinstance(entry, dict) else ""
        field = cron.split()[0] if cron.split() else ""
        if any(busy_minute(part) for part in field.split(",")):
            out.append(f"schedule '{cron}': off-minute crons only (minute 0, * or */N)")
    return out


def busy_minute(part: str) -> bool:
    """True for `*`, `*/N` and any range, list item or step starting at minute 0."""
    start = part.split("/", maxsplit=1)[0].split("-", maxsplit=1)[0]
    return start.startswith("*") or (start.isdigit() and int(start) == 0)
