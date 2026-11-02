"""Result of one perturbation (interfaces §12)."""

from pydantic import BaseModel, ConfigDict


class PerturbResult(BaseModel):
    """Output of ``Perturbation.apply``.

    Attributes:
        text: The (NFC-normalised) perturbed text; equals the NFC form of the input when
            ``changed`` is False.
        changed: True when a rule applied and the text differs from its input.
        notes: Free-text remark for reviewers (e.g. the typo that was inserted); may be empty.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    changed: bool
    notes: str = ""
