"""Scoring OCR text against a reference: character and word error rates."""

from __future__ import annotations

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


def cer(hypothesis: str, reference: str, *, ignore_case: bool = False) -> float:
    return score(hypothesis, reference, ignore_case=ignore_case).cer


def wer(hypothesis: str, reference: str, *, ignore_case: bool = False) -> float:
    return score(hypothesis, reference, ignore_case=ignore_case).wer
