"""Dashboard models (interfaces §10.1). T1.9 owns ``LabelsDocument``; T8.1 adds the other models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pruefstand.core.models.gate import CauseCode


class LabelsDocument(BaseModel):
    """``labels.json``: the en labels the PR comment, the HTML report and the dashboard share.

    Built by ``pruefstand.report.labels.labels_document()`` and copied to ``data/labels.json`` by
    ``export-dashboard``, so the dashboard never re-types a label (ui-spec §10.4.3).

    Attributes:
        metrics: Metric code to label (every ``KNOWN_METRICS`` name and ``evidence_recall``).
        causes: Cause code to message (``CAUSE_MESSAGES``).
        hard_fail_rules: Hard-fail rule code to label (R12 UI12-15, D273).
        informational_reasons: Every ``informational_reason`` code of interfaces §9 to its label.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    metrics: dict[str, str]
    causes: dict[CauseCode, str]
    hard_fail_rules: dict[str, str]
    informational_reasons: dict[str, str]
