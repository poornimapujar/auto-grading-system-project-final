"""Offline fallback grader (no internet / API key needed).

Algorithm: TF-IDF cosine similarity between reference and student answer + concept coverage.
It only matches words (not meaning), so its results are always flagged for teacher review."""
import math
import re
from collections import Counter

from scoring import clamp, compute_marks

STOPWORDS = set("""a an the is are was were be been being of to in on at for and or but if then so as by with
from that this these those it its they them their he she his her we our you your i not no do does did done
has have had can could will would should may might shall also such than there which who whom what when where
why how into about over under between more most some any each other very just""".split())


def stem(w):
    for suf in ("ingly", "edly", "ing", "ed", "es", "ly", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def tokens(text):
    return [stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOPWORDS]


def tfidf_cosine(a_tokens, b_tokens):
    docs = [Counter(a_tokens), Counter(b_tokens)]
    vocab = set(docs[0]) | set(docs[1])
    if not vocab:
        return 0.0
    idf = {t: math.log((1 + 2) / (1 + sum(1 for d in docs if t in d))) + 1 for t in vocab}
    va = {t: docs[0][t] * idf[t] for t in vocab}
    vb = {t: docs[1][t] * idf[t] for t in vocab}
    dot = sum(va[t] * vb[t] for t in vocab)
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


def pick_concepts(reference_tokens, n=8):
    counts = Counter(reference_tokens)
    return sorted(counts, key=lambda t: (counts[t], len(t)), reverse=True)[:n]


def grade_offline(question, reference_answer, student_answer, max_marks, concepts=None, scheme=None, examples=None):
    ref_t, stu_t = tokens(reference_answer), tokens(student_answer)
    sim = tfidf_cosine(ref_t, stu_t)
    stu_set = set(stu_t)

    items = [(c, set(tokens(c))) for c in concepts] if concepts else [(t, {t}) for t in pick_concepts(ref_t)]
    matched = [c for c, ts in items if ts and ts <= stu_set]
    missing = [c for c, ts in items if not (ts and ts <= stu_set)]
    coverage = len(matched) / len(items) if items else sim

    length_ratio = min(len(stu_t) / max(len(ref_t), 1), 1.0)
    ratings = {
        "correctness": clamp(sim * 12),
        "relevance": clamp(sim * 14),
        "completeness": clamp((coverage + length_ratio) / 2 * 10),
        "concept_coverage": clamp(coverage * 10),
    }
    marks, total = compute_marks(ratings, max_marks)
    return {
        "score": total,
        "max_marks": max_marks,
        "percentage": round(100 * total / max_marks, 1) if max_marks else 0,
        "ratings": {k: round(v, 1) for k, v in ratings.items()},
        "marks": marks,
        "matched_concepts": matched,
        "missing_concepts": missing,
        "method": "offline",
        "needs_review": True,
    }
