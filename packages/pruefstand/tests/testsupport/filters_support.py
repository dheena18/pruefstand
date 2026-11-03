"""Shared inputs of the support-check live test and its cassette replay (T4.3)."""

import os

from testsupport.qa_support import SECOND

QUESTION = "Wie lange vorher muss mein Arbeitgeber mir kündigen, wenn ich zwei Jahre dort arbeite?"
ANSWER = "Einen Monat zum Ende eines Kalendermonats (§ 622 Abs. 2 Nr. 1 BGB)."
SUPPORT_MODEL = os.environ.get("PRUEFSTAND_SUPPORT_TEST_MODEL", SECOND)
PARAPHRASES = (
    "Wie lange ist die Kündigungsfrist nach zwei Jahren?",
    "Welche Kündigungsfrist gilt nach zwei Jahren Beschäftigung?",
    "Was regelt § 3 ArbZG?",
)
