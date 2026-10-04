"""Lexical search for the filesystem backend: a Porter stemmer and a small BM25 index,
with no dependencies. The catalog is tens of procedures, so the index lives in memory and
is rebuilt whenever what a name resolves to changes.

Scoring is BM25 per field (name, description, purpose, triggers), each field weighted and
length-normalised on its own, summed per document. Stemming makes "charged" find
"charge" and "refunds" find "refund"; the Neo4j backend's Lucene index does the same job
with its own analyzer.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

_WORD = re.compile(r"[a-z0-9]+")

# ------------------------------------------------------------------- Porter stemmer
# Porter, M. "An algorithm for suffix stripping", 1980. The original algorithm, not
# Porter2; one function per step, measure m computed over the [C](VC)^m[V] form.

_VOWELS = set("aeiou")


def _cons(w: str, i: int) -> bool:
    c = w[i]
    if c in _VOWELS:
        return False
    if c == "y":
        return i == 0 or not _cons(w, i - 1)
    return True


def _m(stem: str) -> int:
    """The number of VC sequences in `stem`."""
    n, i, m = len(stem), 0, 0
    while i < n and _cons(stem, i):
        i += 1
    while i < n:
        while i < n and not _cons(stem, i):
            i += 1
        if i >= n:
            break
        m += 1
        while i < n and _cons(stem, i):
            i += 1
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _cons(stem, i) for i in range(len(stem)))


def _double_cons(w: str) -> bool:
    return len(w) >= 2 and w[-1] == w[-2] and _cons(w, len(w) - 1)


def _cvc(w: str) -> bool:
    """Ends consonant-vowel-consonant, the last not w, x, or y."""
    return (len(w) >= 3 and _cons(w, len(w) - 1) and not _cons(w, len(w) - 2) and _cons(w, len(w) - 3)
            and w[-1] not in "wxy")


def _replace(w: str, suffix: str, new: str, cond=None) -> Tuple[str, bool]:
    """If `w` ends in `suffix` and `cond(stem)` holds (default: always), swap the suffix.
    The bool says whether the suffix matched at all, so one step tries only its first match."""
    if not w.endswith(suffix):
        return w, False
    stem = w[: len(w) - len(suffix)]
    if cond is None or cond(stem):
        return stem + new, True
    return w, True


def _step1a(w: str) -> str:
    for suffix, new in (("sses", "ss"), ("ies", "i"), ("ss", "ss"), ("s", "")):
        w, hit = _replace(w, suffix, new)
        if hit:
            break
    return w


def _step1b(w: str) -> str:
    w, hit = _replace(w, "eed", "ee", lambda s: _m(s) > 0)
    if hit:
        return w
    for suffix in ("ed", "ing"):
        if w.endswith(suffix) and _has_vowel(w[: -len(suffix)]):
            w = w[: -len(suffix)]
            if w.endswith(("at", "bl", "iz")):
                return w + "e"
            if _double_cons(w) and w[-1] not in "lsz":
                return w[:-1]
            if _m(w) == 1 and _cvc(w):
                return w + "e"
            return w
    return w


def _step1c(w: str) -> str:
    return w[:-1] + "i" if w.endswith("y") and _has_vowel(w[:-1]) else w


_STEP2 = (("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"),
          ("abli", "able"), ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"),
          ("ization", "ize"), ("ation", "ate"), ("ator", "ate"), ("alism", "al"), ("iveness", "ive"),
          ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"))
_STEP3 = (("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", ""))
_STEP4 = ("al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou", "ism",
          "ate", "iti", "ous", "ive", "ize")


def _step_table(w: str, table, cond) -> str:
    for suffix, new in table:
        w, hit = _replace(w, suffix, new, cond)
        if hit:
            break
    return w


def _step4(w: str) -> str:
    for suffix in _STEP4:
        if w.endswith(suffix):
            stem = w[: -len(suffix)]
            if suffix == "ion" and not stem.endswith(("s", "t")):
                return w
            return stem if _m(stem) > 1 else w
    return w


def _step5(w: str) -> str:
    if w.endswith("e"):
        stem = w[:-1]
        m = _m(stem)
        if m > 1 or (m == 1 and not _cvc(stem)):
            w = stem
    if _m(w) > 1 and _double_cons(w) and w.endswith("l"):
        w = w[:-1]
    return w


def stem(word: str) -> str:
    """The Porter stem of a lowercase word; words of one or two letters are left alone."""
    if len(word) <= 2:
        return word
    w = _step1c(_step1b(_step1a(word)))
    w = _step_table(w, _STEP2, lambda s: _m(s) > 0)
    w = _step_table(w, _STEP3, lambda s: _m(s) > 0)
    return _step5(_step4(w))


def tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric runs, stemmed. Digits-only tokens pass through unchanged."""
    return [stem(t) for t in _WORD.findall(text.lower())]


# ------------------------------------------------------------------------------ BM25


@dataclass
class _Doc:
    key: str
    payload: Any
    fields: Dict[str, Counter]           # field -> stemmed term counts
    lengths: Dict[str, int] = field(default_factory=dict)


class BM25Index:
    """Weighted multi-field BM25. Each field is scored as its own BM25 corpus (own average
    length, shared document frequencies per field) and the fields are summed with their
    weights, so a term in a short, heavy field (the name) outweighs one in a long, light
    field (the triggers)."""

    def __init__(self, weights: Dict[str, float], k1: float = 1.2, b: float = 0.75):
        self.weights, self.k1, self.b = dict(weights), k1, b
        self._docs: List[_Doc] = []
        self._df: Dict[str, Counter] = {f: Counter() for f in weights}
        self._avg: Dict[str, float] = {f: 0.0 for f in weights}

    def add(self, key: str, fields: Dict[str, str], payload: Any = None) -> None:
        counts = {f: Counter(tokenize(fields.get(f, "") or "")) for f in self.weights}
        doc = _Doc(key, payload, counts, {f: sum(c.values()) for f, c in counts.items()})
        self._docs.append(doc)
        for f, c in counts.items():
            self._df[f].update(c.keys())
        n = len(self._docs)
        self._avg = {f: sum(d.lengths[f] for d in self._docs) / n for f in self.weights}

    def __len__(self) -> int:
        return len(self._docs)

    def _idf(self, f: str, term: str) -> float:
        n, df = len(self._docs), self._df[f].get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, doc: _Doc, terms: Iterable[str]) -> float:
        total = 0.0
        for f, weight in self.weights.items():
            counts, avg = doc.fields[f], self._avg[f]
            if not counts or avg == 0:
                continue
            norm = self.k1 * (1 - self.b + self.b * doc.lengths[f] / avg)
            for term in terms:
                tf = counts.get(term)
                if tf:
                    total += weight * self._idf(f, term) * tf * (self.k1 + 1) / (tf + norm)
        return total

    def search(self, query: str, limit: int = 10) -> List[Tuple[str, Any, float]]:
        """`(key, payload, score)` for every document matching at least one query term, best first;
        ties break on key. Unique query terms count once each."""
        terms = sorted(set(tokenize(query)))
        if not terms:
            return []
        hits = [(d.key, d.payload, s) for d in self._docs if (s := self.score(d, terms)) > 0]
        hits.sort(key=lambda h: (-h[2], h[0]))
        return hits[:limit]
