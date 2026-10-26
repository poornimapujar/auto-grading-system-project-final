"""SQLite data layer for GradeAI (users, questions, submissions, evaluations)."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "gradeai.db"))

SEED_QUESTION = "Explain the importance of software engineering principles in developing reliable software systems."
SEED_REFERENCE = (
    "Software engineering principles give a disciplined, systematic way to build reliable software. "
    "Requirements analysis makes sure the system does what users actually need. Good design uses modularity, "
    "abstraction and separation of concerns to manage complexity and to allow reusability. Thorough testing and "
    "verification find defects early, which improves reliability and quality. Documentation and clear coding "
    "standards support maintainability, so the software can be understood, fixed and extended over time. "
    "Following these principles, along with version control and quality assurance, reduces cost and failures "
    "and produces dependable systems."
)
SEED_CONCEPTS = ["modularity", "maintainability", "reliability", "testing", "documentation",
                 "reusability", "complexity", "quality", "requirements", "design"]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with open(os.path.join(BASE, "schema.sql"), encoding="utf-8") as f:
        script = f.read()
    with db() as conn:
        conn.executescript(script)
        # migration: databases created before marking_scheme existed
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(questions)")]
        if "marking_scheme" not in cols:
            conn.execute("ALTER TABLE questions ADD COLUMN marking_scheme TEXT NOT NULL DEFAULT ''")
        if not conn.execute("SELECT 1 FROM questions").fetchone():
            conn.execute("INSERT INTO questions (question_text, maximum_marks, reference_answer, expected_concepts) "
                         "VALUES (?, ?, ?, ?)", (SEED_QUESTION, 10, SEED_REFERENCE, json.dumps(SEED_CONCEPTS)))


# ---------------------------------------------------------------- users
def get_student(usn):
    with db() as c:
        r = c.execute("SELECT * FROM students WHERE usn = ?", (usn,)).fetchone()
    return dict(r) if r else None


def add_student(usn, name, password_hash):
    """Raises sqlite3.IntegrityError if the USN already exists."""
    with db() as c:
        c.execute("INSERT INTO students (usn, student_name, password_hash) VALUES (?, ?, ?)", (usn, name, password_hash))


def add_teacher(username, name, password_hash):
    """Raises sqlite3.IntegrityError if the username already exists."""
    with db() as c:
        c.execute("INSERT INTO teachers (username, teacher_name, password_hash) VALUES (?, ?, ?)", (username, name, password_hash))


def get_teacher(username):
    with db() as c:
        r = c.execute("SELECT * FROM teachers WHERE username = ?", (username,)).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- questions
def _q(r):
    d = dict(r)
    d["expected_concepts"] = json.loads(d["expected_concepts"] or "[]")
    return d


def get_question(qid=None):
    """A specific question, or the first one when qid is None."""
    with db() as c:
        if qid is None:
            r = c.execute("SELECT * FROM questions ORDER BY question_id LIMIT 1").fetchone()
        else:
            r = c.execute("SELECT * FROM questions WHERE question_id = ?", (qid,)).fetchone()
    return _q(r) if r else None


def list_questions():
    with db() as c:
        return [_q(r) for r in c.execute("SELECT * FROM questions ORDER BY question_id")]


def add_question(text, marks, reference, concepts, scheme=""):
    with db() as c:
        return c.execute("INSERT INTO questions (question_text, maximum_marks, reference_answer, expected_concepts, "
                         "marking_scheme) VALUES (?, ?, ?, ?, ?)",
                         (text, marks, reference, json.dumps(concepts), scheme)).lastrowid


# ---------------------------------------------------------------- graded examples (few-shot)
def add_example(qid, answer, marks):
    with db() as c:
        return c.execute("INSERT INTO graded_examples (question_id, answer_text, marks, created_at) VALUES (?,?,?,?)",
                         (qid, answer, marks, now())).lastrowid


def list_examples(qid):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM graded_examples WHERE question_id = ? ORDER BY example_id", (qid,))]


def delete_example(eid):
    with db() as c:
        return c.execute("DELETE FROM graded_examples WHERE example_id = ?", (eid,)).rowcount > 0


# ---------------------------------------------------------------- submissions
def create_submission(usn, qid, answer):
    with db() as c:
        return c.execute("INSERT INTO submissions (usn, question_id, answer_text, submitted_at) VALUES (?, ?, ?, ?)",
                         (usn, qid, answer, now())).lastrowid


def _attach_evaluations(c, subs):
    if not subs:
        return subs
    ids = [s["submission_id"] for s in subs]
    marks = ",".join("?" * len(ids))
    evs = c.execute(f"SELECT * FROM evaluations WHERE submission_id IN ({marks})", ids).fetchall()
    by = {}
    for e in evs:
        by.setdefault(e["submission_id"], {})[e["evaluation_method"]] = dict(e)
    for s in subs:
        s["evaluations"] = by.get(s["submission_id"], {})
    return subs


_SUB_SQL = ("SELECT s.*, st.student_name, q.question_text, q.maximum_marks FROM submissions s "
            "JOIN students st ON st.usn = s.usn JOIN questions q ON q.question_id = s.question_id ")


def list_submissions(usn=None):
    with db() as c:
        if usn:
            rows = c.execute(_SUB_SQL + "WHERE s.usn = ? ORDER BY s.submission_id DESC", (usn,)).fetchall()
        else:
            rows = c.execute(_SUB_SQL + "ORDER BY s.submission_id DESC").fetchall()
        return _attach_evaluations(c, [dict(r) for r in rows])


def get_submission(sid):
    with db() as c:
        r = c.execute(_SUB_SQL + "WHERE s.submission_id = ?", (sid,)).fetchone()
        return _attach_evaluations(c, [dict(r)])[0] if r else None


def save_evaluation(sid, method, marks, total, summary, details):
    """Insert or replace the AI / Teacher evaluation of a submission and mark it Evaluated."""
    with db() as c:
        c.execute(
            "INSERT INTO evaluations (submission_id, evaluation_method, correctness, relevance, completeness, "
            "concept_coverage, total_marks, summary, details_json, evaluated_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(submission_id, evaluation_method) DO UPDATE SET correctness=excluded.correctness, "
            "relevance=excluded.relevance, completeness=excluded.completeness, "
            "concept_coverage=excluded.concept_coverage, total_marks=excluded.total_marks, "
            "summary=excluded.summary, details_json=excluded.details_json, evaluated_at=excluded.evaluated_at",
            (sid, method, marks["correctness"], marks["relevance"], marks["completeness"],
             marks["concept_coverage"], total, summary, json.dumps(details), now()))
        c.execute("UPDATE submissions SET status = 'Evaluated' WHERE submission_id = ?", (sid,))
