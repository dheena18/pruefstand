"""Test helpers of the orchestrator tests (like ``infra/gpu/gpu_testkit.py``)."""

from dataclasses import dataclass, field

from pruefstand.core.enums import GateStatus


@dataclass
class SpyPoster:
    """Records ``post_status`` and ``set_check`` calls in order (no GitHub call)."""

    calls: list[tuple[str, ...]] = field(default_factory=list)

    def post_status(
        self, sha: str, state: str, description: str, context: str = "pruefstand/gate"
    ) -> None:
        """Record a low-level status."""
        self.calls.append(("post_status", sha, state, description, context))

    def set_check(
        self,
        sha: str,
        status: GateStatus,
        summary: str,
        *,
        no_baseline: bool = False,
        infra_error: bool = False,
    ) -> None:
        """Record a gate-result status."""
        self.calls.append(
            ("set_check", sha, str(status), summary, str(no_baseline), str(infra_error))
        )
