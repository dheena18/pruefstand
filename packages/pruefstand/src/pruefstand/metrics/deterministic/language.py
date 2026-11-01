"""``language_match``: does the answer's detected language equal the question's (DE or EN)?"""

import unicodedata
from functools import lru_cache

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

from pruefstand.core.enums import Lang
from pruefstand.core.models.metric import MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.deterministic.base import BaseMetric
from pruefstand.metrics.deterministic.refusal import is_refusal

MIN_CHARS = 20
MAX_CHARS = 5000  # the detector sees the first 5 000 characters; enough and bounded
_LINGUA = {Lang.DE: Language.GERMAN, Lang.EN: Language.ENGLISH}
# Wider than DE/EN: a confident French or Turkish answer must score 0, not be mislabelled.
_DETECTED = (
    Language.GERMAN, Language.ENGLISH, Language.FRENCH, Language.SPANISH, Language.ITALIAN,
    Language.DUTCH, Language.POLISH, Language.RUSSIAN, Language.TURKISH,
)  # fmt: skip


@lru_cache(maxsize=1)
def _detector() -> LanguageDetector:
    """The detector over the nine languages, built once on first use."""
    return LanguageDetectorBuilder.from_languages(*_DETECTED).build()


class LanguageMatch(BaseMetric):
    """1 if the detected answer language equals ``case.lang``.

    ``not_applicable`` for answers under 20 characters, refusals (phrase match) and texts the
    detector cannot decide.
    """

    name = "language_match"
    higher_is_better = True

    def _compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        text = unicodedata.normalize("NFC", resp.answer).strip()
        if len(text) < MIN_CHARS:
            return self.na("answer_too_short")
        if is_refusal(text):
            return self.na("refusal")
        detected = _detector().detect_language_of(text[:MAX_CHARS])
        if detected is None:
            return self.na("language_undetermined")
        return self.ok(float(detected == _LINGUA[case.lang]))
