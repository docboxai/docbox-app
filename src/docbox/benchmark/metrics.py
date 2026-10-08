"""Scoring OCR text against a reference: character and word error rates."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz.distance import Levenshtein

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str, *, ignore_case: bool = False) -> str:
    """Compare what was read, not how it was laid out: Unicode NFKC (so "ﬁ" equals "fi"
    and full-width digits equal ASCII ones), every run of whitespace (line breaks
    included) as one space, trimmed."""
    text = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip()
    return text.casefold() if ignore_case else text


@dataclass(frozen=True)
class Score:
    """Edit counts against one reference; add them up to score many pages at once."""

    char_edits: int
    ref_chars: int
    word_edits: int
    ref_words: int

    def __add__(self, other: Score) -> Score:
        return Score(
            self.char_edits + other.char_edits, self.ref_chars + other.ref_chars,
            self.word_edits + other.word_edits, self.ref_words + other.ref_words,
        )

    @property
    def cer(self) -> float:
        return _rate(self.char_edits, self.ref_chars)

    @property
    def wer(self) -> float:
        return _rate(self.word_edits, self.ref_words)


ZERO = Score(0, 0, 0, 0)


def _rate(edits: int, length: int) -> float:
    # An empty reference: a perfect read is empty too; anything else is all wrong.
    if length == 0:
        return 0.0 if edits == 0 else 1.0
    return edits / length


def score(hypothesis: str, reference: str, *, ignore_case: bool = False) -> Score:
    hyp = normalize(hypothesis, ignore_case=ignore_case)
    ref = normalize(reference, ignore_case=ignore_case)
    hyp_words, ref_words = hyp.split(), ref.split()
    return Score(
        char_edits=Levenshtein.distance(hyp, ref),
        ref_chars=len(ref),
        word_edits=Levenshtein.distance(hyp_words, ref_words),
        ref_words=len(ref_words),
    )


# Student's t, 97.5th percentile, for 1..30 degrees of freedom (beyond that, 1.96): with
# only a few pages the interval has to be much wider than the normal approximation's.
_T_975 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


def cer_margin(units: list[Score]) -> float | None:
    """Half-width of a 95% interval for the character error rate of `units` scored
    together (all edits over all reference characters). Each unit, a page or document
    with its own reference, is one sample: the ratio estimator's standard error, widened
    with Student's t when there are few units. None below two units, where there is no
    spread to measure."""
    k = len(units)
    chars = sum(u.ref_chars for u in units)
    if k < 2 or chars == 0:
        return None
    rate = sum(u.char_edits for u in units) / chars
    spread = sum((u.char_edits - rate * u.ref_chars) ** 2 for u in units)
    se = math.sqrt(k / (k - 1) * spread) / chars
    t = _T_975[k - 2] if k - 1 <= len(_T_975) else 1.96
    return t * se


def cer(hypothesis: str, reference: str, *, ignore_case: bool = False) -> float:
    return score(hypothesis, reference, ignore_case=ignore_case).cer


def wer(hypothesis: str, reference: str, *, ignore_case: bool = False) -> float:
    return score(hypothesis, reference, ignore_case=ignore_case).wer
