"""``refusal_judged``: a judge decides the answers the phrase list cannot (W3.5, AI9-19)."""

from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import JudgePoolLike
from pruefstand.judges.calibration import refusal_judge_passed
from pruefstand.judges.output import make_task
from pruefstand.metrics.deterministic.refusal import is_refusal
from pruefstand.metrics.judged.base import JudgedBase
from pruefstand.metrics.judged.routing import is_ambiguous
from pruefstand.metrics.judged.truncate import over_cap


class RefusalJudged(JudgedBase):
    """Did the answer refuse? 1.0 = refused. The phrase list decides, the judge ambiguous ones.

    The judge is asked only when it is enabled (T5.4 marked it passing in
    ``judges/data/calibration_status.yaml``; without the file it is off) and the answer is
    ambiguous. The prompt never sees whether a refusal was expected. ``details["refused_source"]``
    is ``phrase`` or ``judge``; the target flag is reported (``refusal_flag_mismatch``),
    never used.

    Args:
        judge_enabled: Force the judge on or off; None reads the calibration status.
    """

    name = "refusal_judged"

    def __init__(self, *, judge_enabled: bool | None = None) -> None:
        self._enabled = refusal_judge_passed() if judge_enabled is None else judge_enabled

    def applicable(self, case: TestCase) -> bool:  # noqa: ARG002
        """Only a judge that may run costs a call (a phrase decision is free)."""
        return self._enabled

    async def acompute(
        self, case: TestCase, resp: TargetResponse, judges: JudgePoolLike
    ) -> MetricValue:
        """Decide whether ``resp`` refuses.

        Returns:
            An ``ok`` value (1.0 refused) with ``refused_source``; ``refusal_flag_mismatch`` when
            the target's flag disagrees with the phrase match; ``not_applicable`` when the judge
            input is over the cap.

        Raises:
            LLMError: The judge failed (the runner turns it into an error value).
            BudgetExceeded: The call passed a budget limit.
        """
        phrase = is_refusal(resp.answer)
        flags: dict[str, bool] = {}
        if resp.refused is not None and resp.refused != phrase:
            flags["refusal_flag_mismatch"] = True
        if phrase or not self._enabled or not is_ambiguous(resp):
            return self._value(refused=phrase, source="phrase", flags=flags)
        task = make_task(self.name, frage=case.question, antwort=resp.answer)
        if over_cap(judges.for_metric(self.name), task):
            return self.na("judge_input_too_long")
        verdict = await self.ask(judges, task)
        return self.ok(verdict, refused_source="judge", **flags)

    def _value(self, *, refused: bool, source: str, flags: dict[str, bool]) -> MetricValue:
        return MetricValue(
            metric=self.name,
            metric_version=self.version,
            value=float(refused),
            status=MetricStatus.OK,
            details={"refused_source": source, **flags},
        )
