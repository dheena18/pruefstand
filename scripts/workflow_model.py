"""Typed accessors over a parsed workflow document (used by ``check_workflows.py``)."""

from collections.abc import Iterator

Doc = dict[object, object]  # YAML keys may be booleans: PyYAML reads an unquoted `on` as True


def triggers(doc: Doc) -> dict[object, object]:
    """Return the ``on:`` triggers as a dict (a string or list becomes keys with ``None``)."""
    raw = doc.get("on", doc.get(True))  # PyYAML reads an unquoted `on:` as the boolean True
    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return dict.fromkeys(raw)
    return raw if isinstance(raw, dict) else {}


def jobs(doc: Doc) -> dict[str, Doc]:
    """Return the job mappings by id."""
    jobs = doc.get("jobs")
    return {k: v for k, v in jobs.items() if isinstance(v, dict)} if isinstance(jobs, dict) else {}


def steps(job: Doc) -> list[Doc]:
    """Return the step mappings of a job."""
    steps = job.get("steps")
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def strings(node: object) -> Iterator[str]:
    """Yield every string value below ``node``."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)


def all_uses(doc: Doc) -> Iterator[str]:
    """Yield every ``uses:`` value of the jobs and their steps."""
    for job in jobs(doc).values():
        for holder in [job, *steps(job)]:
            value = holder.get("uses")
            if isinstance(value, str):
                yield value


def environment(job: Doc) -> str | None:
    """Return the job's environment name, whether written as a string or as a mapping."""
    env = job.get("environment")
    if isinstance(env, dict):
        env = env.get("name")
    return env if isinstance(env, str) else None
