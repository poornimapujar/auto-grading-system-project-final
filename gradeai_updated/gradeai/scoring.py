"""Scoring logic shared by the LLM grader and the offline grader.

The LLM rates four criteria from 0 to 10. THIS CODE converts the ratings to marks, so the final
score is deterministic and always adds up. With 10 marks the rubric is 3 / 2 / 3 / 2, the same
as the front end's teacher form."""

WEIGHTS = {
    "correctness": 0.30,
    "relevance": 0.20,
    "completeness": 0.30,
    "concept_coverage": 0.20,
}


def clamp(x, lo=0.0, hi=10.0):
    try:
        x = float(x)
    except (TypeError, ValueError):
        x = 0.0
    return max(lo, min(hi, x))


def criterion_max(max_marks):
    """Maximum marks for each criterion, e.g. 10 marks -> 3 / 2 / 3 / 2."""
    return {k: w * max_marks for k, w in WEIGHTS.items()}


def compute_marks(ratings, max_marks):
    """ratings: criterion -> 0..10.  Returns (marks per criterion rounded to 0.5, total)."""
    marks = {k: round(w * max_marks * clamp(ratings.get(k, 0)) / 10 * 2) / 2 for k, w in WEIGHTS.items()}
    return marks, sum(marks.values())
