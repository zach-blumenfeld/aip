"""Tests for `aip.server.search`: the Porter stemmer, the tokenizer, and the weighted BM25
index the filesystem backend searches with, plus the stemming the backend gains from it."""

import shutil
from pathlib import Path

import pytest

from aip.server.backends.filesystem import FilesystemBackend
from aip.server.records import snapshot
from aip.server.search import BM25Index, stem, tokenize

EXAMPLE = Path(__file__).parent.parent.parent / "examples" / "billing-support"

# Reference outputs of Porter's 1980 algorithm (the paper's own examples and a few from
# the procedure vocabulary); a stemmer that deviates breaks "charged" finding "charge".
PORTER = {
    "caresses": "caress", "ponies": "poni", "ties": "ti", "caress": "caress", "cats": "cat",
    "feed": "feed", "agreed": "agre", "plastered": "plaster", "bled": "bled", "motoring": "motor",
    "sing": "sing", "conflated": "conflat", "troubled": "troubl", "sized": "size", "hopping": "hop",
    "tanned": "tan", "falling": "fall", "hissing": "hiss", "fizzed": "fizz", "failing": "fail",
    "filing": "file", "happy": "happi", "sky": "sky", "relational": "relat", "conditional": "condit",
    "rational": "ration", "valenci": "valenc", "hesitanci": "hesit", "digitizer": "digit",
    "conformabli": "conform", "radicalli": "radic", "differentli": "differ", "vileli": "vile",
    "analogousli": "analog", "vietnamization": "vietnam", "predication": "predic", "operator": "oper",
    "feudalism": "feudal", "decisiveness": "decis", "hopefulness": "hope", "callousness": "callous",
    "formaliti": "formal", "sensitiviti": "sensit", "sensibiliti": "sensibl", "triplicate": "triplic",
    "formative": "form", "formalize": "formal", "electriciti": "electr", "electrical": "electr",
    "hopeful": "hope", "goodness": "good", "revival": "reviv", "allowance": "allow", "inference": "infer",
    "airliner": "airlin", "gyroscopic": "gyroscop", "adjustable": "adjust", "defensible": "defens",
    "irritant": "irrit", "replacement": "replac", "adjustment": "adjust", "dependent": "depend",
    "adoption": "adopt", "homologou": "homolog", "communism": "commun", "activate": "activ",
    "angulariti": "angular", "homologous": "homolog", "effective": "effect", "bowdlerize": "bowdler",
    "probate": "probat", "rate": "rate", "cease": "ceas", "controll": "control", "roll": "roll",
    "generalization": "gener", "happiness": "happi", "running": "run",
    "charged": "charg", "charge": "charg", "charges": "charg", "refunds": "refund", "billing": "bill",
    "messages": "messag", "escalate": "escal", "duplicate": "duplic", "complaints": "complaint",
    "invoice": "invoic", "customers": "custom", "angry": "angri", "subscription": "subscript",
}


def test_porter_reference_pairs():
    wrong = {w: (stem(w), want) for w, want in PORTER.items() if stem(w) != want}
    assert wrong == {}, f"stem(word) -> (got, wanted): {wrong}"


def test_short_words_and_digits_pass_through():
    assert stem("is") == "is" and stem("at") == "at" and stem("a") == "a"
    assert tokenize("Tier-2 queue, 30 days!") == ["tier", "2", "queue", "30", "dai"]
    assert tokenize("") == []


def test_tokenize_folds_inflections_together():
    assert tokenize("charged twice") == tokenize("charge twice")
    assert tokenize("refund requests") == tokenize("refunds request")


def index() -> BM25Index:
    idx = BM25Index({"name": 10.0, "description": 3.0})
    idx.add("billing-support", {"name": "billing-support",
                                "description": "Triage a billing message; refund requests and duplicate charge complaints."}, "b")
    idx.add("invoice-routing", {"name": "invoice-routing",
                                "description": "Route an invoice question to the right team; billing teams included."}, "i")
    idx.add("onboarding", {"name": "onboarding", "description": "Walk a new customer through setup."}, "o")
    return idx


def test_bm25_ranks_by_stemmed_terms_and_idf():
    idx = index()
    keys = lambda q: [k for k, _, _ in idx.search(q)]
    assert keys("charged twice") == ["billing-support"]           # stem match, "twice" nowhere
    assert keys("refunds") == ["billing-support"]
    assert keys("invoices") == ["invoice-routing"]
    assert keys("billing") == ["billing-support", "invoice-routing"]   # name field outweighs description
    assert keys("zzz") == [] and keys("") == []
    hits = idx.search("billing invoice")
    assert [k for k, _, _ in hits] == ["invoice-routing", "billing-support"]
    assert hits[0][1] == "i" and hits[0][2] > hits[1][2] > 0        # payload rides along; scores descend


def test_bm25_rarer_term_scores_higher():
    idx = index()
    rare = idx.search("refund")[0][2]       # one doc
    common = idx.search("billing")[1][2]    # description-only hit for a term in two docs
    assert rare > common


def test_limit_and_tie_break():
    idx = index()
    assert len(idx.search("billing", limit=1)) == 1
    idx2 = BM25Index({"description": 1.0})
    idx2.add("b", {"description": "same words"})
    idx2.add("a", {"description": "same words"})
    assert [k for k, _, _ in idx2.search("same")] == ["a", "b"]


# ------------------------------------------------------- through the filesystem backend


def variant(tmp: Path, name: str, description: str):
    folder = tmp / name
    shutil.copytree(EXAMPLE, folder)
    md = folder / "SKILL.md"
    text = md.read_text().replace("name: billing-support", f"name: {name}", 1)
    start = text.index("description: ")
    end = text.index("\n", start)
    md.write_text(text[:start] + f"description: {description}" + text[end:])
    return snapshot(folder)


def test_filesystem_search_stems(tmp_path):
    catalog = FilesystemBackend(tmp_path / "root").catalog
    catalog.publish(snapshot(EXAMPLE))
    catalog.publish(variant(tmp_path, "aaa-other", "Route an invoice question to the right team."))
    for query in ("charged twice", "refunds", "duplicate charges", "angry customers"):
        hits = catalog.search(query)
        assert hits and hits[0].name == "billing-support", query
    assert [h.name for h in catalog.search("invoices")] == ["aaa-other", "billing-support"]
    assert catalog.search("billing-support")[0].name == "billing-support"
    assert catalog.search("billing-support")[0].score > 100          # the exact-name boost


def test_filesystem_search_follows_retire(tmp_path):
    catalog = FilesystemBackend(tmp_path / "root").catalog
    revision = catalog.publish(snapshot(EXAMPLE))
    assert catalog.search("charged twice")[0].revision == revision
    catalog.retire("billing-support", revision)
    assert catalog.search("charged twice") == []
