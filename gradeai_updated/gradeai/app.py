"""GradeAI backend (Flask + SQLite) for the team's existing front end.

Run:  python app.py   ->  open http://127.0.0.1:5000  (Flask also serves the front end in /frontend)
Flow: Browser --JSON--> Flask --prompt--> LLM --ratings--> Flask (marks computed + saved in SQLite) --JSON--> Browser
"""
import json
import os
import re
import secrets
import sqlite3
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import database
from llm_grader import grade_with_claude, grade_with_ollama, ollama_running
from offline_grader import grade_offline
from scoring import criterion_max

BASE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(BASE, "frontend")
TOKEN_HOURS = 8
MAX_ANSWER_CHARS = 8000

app = Flask(__name__, static_folder=FRONTEND, static_url_path="")


def _load_secret():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE, ".secret_key")
    if os.path.exists(path):
        return open(path).read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as f:
        f.write(key)
    return key


def _load_teacher_code():
    """Teachers must enter this code to create an account (so students cannot make teacher accounts)."""
    if os.environ.get("TEACHER_CODE"):
        return os.environ["TEACHER_CODE"].strip()
    path = os.path.join(BASE, ".teacher_code")
    if os.path.exists(path):
        return open(path).read().strip()
    code = secrets.token_hex(3).upper()
    with open(path, "w") as f:
        f.write(code)
    return code


TEACHER_CODE = _load_teacher_code()
serializer = URLSafeTimedSerializer(_load_secret(), salt="gradeai-session")
database.init_db()


# ------------------------------------------------------------------ helpers
@app.after_request
def add_cors(resp):  # only needed if the front end is opened from a file:// or another port
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return resp


@app.route("/api/<path:_>", methods=["OPTIONS"])
def preflight(_):
    return ("", 204)


def err(msg, code=400):
    return jsonify({"error": msg}), code


def auth(role):
    """Require a valid login token for the given role ('student' or 'teacher')."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return err("Please sign in.", 401)
            try:
                data = serializer.loads(header[7:], max_age=TOKEN_HOURS * 3600)
            except SignatureExpired:
                return err("Session expired. Please sign in again.", 401)
            except BadSignature:
                return err("Invalid session. Please sign in again.", 401)
            if data.get("role") != role:
                return err("You are not allowed to do this.", 403)
            g.user = data
            return fn(*a, **kw)
        return wrapper
    return deco


def ser_eval(row):
    """Evaluation row -> JSON in the shape the front end expects."""
    d = json.loads(row["details_json"] or "{}")
    return {
        "score": row["total_marks"],
        "correctness": row["correctness"],
        "relevance": row["relevance"],
        "completeness": row["completeness"],
        "coverage": row["concept_coverage"],
        "summary": row["summary"],
        "method": row["evaluation_method"],          # 'AI' or 'Teacher'
        "grader": d.get("method"),                   # 'llm' / 'offline' / 'teacher'
        "needs_review": d.get("needs_review", False),
        "matched_concepts": d.get("matched_concepts", []),
        "missing_concepts": d.get("missing_concepts", []),
        "max_marks": d.get("max_marks", 10),
        "evaluated_at": row["evaluated_at"],
    }


def ser_sub(s, with_answer=False):
    out = {
        "id": s["submission_id"],
        "usn": s["usn"],
        "student_name": s["student_name"],
        "question_id": s["question_id"],
        "question": s["question_text"],
        "max_marks": s["maximum_marks"],
        "submitted_at": s["submitted_at"],
        "status": s["status"],
        "aiEvaluation": ser_eval(s["evaluations"]["AI"]) if "AI" in s["evaluations"] else None,
        "teacherEvaluation": ser_eval(s["evaluations"]["Teacher"]) if "Teacher" in s["evaluations"] else None,
    }
    if with_answer:
        out["answer"] = s["answer_text"]
    return out


def run_grader(question, reference, answer, max_marks, concepts, scheme="", examples=None):
    """Pick a grader. GRADER_MODE: auto (default) | claude | ollama | offline.
    auto = Claude if ANTHROPIC_API_KEY is set, else the free local Ollama model, else the offline grader.
    Any failure falls back to the next option, and finally to the offline grader."""
    mode = os.environ.get("GRADER_MODE", "auto").lower()
    providers = []
    if mode == "claude" or (mode == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        providers.append(grade_with_claude)
    if mode in ("ollama", "auto"):
        providers.append(grade_with_ollama)
    reasons = []
    for fn in providers:
        try:
            return fn(question, reference, answer, max_marks, concepts, scheme=scheme, examples=examples)
        except Exception as exc:
            app.logger.warning("%s failed: %s", fn.__name__, exc)
            reasons.append(str(exc)[:200])
    result = grade_offline(question, reference, answer, max_marks, concepts)
    if reasons:
        result["fallback_reason"] = " | ".join(reasons)
    return result


# ------------------------------------------------------------------ front end pages
@app.get("/")
def home():
    return send_from_directory(FRONTEND, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "claude_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
                    "ollama_running": ollama_running()})


# ------------------------------------------------------------------ sign up + login
@app.post("/api/register")
def register():
    """Create a student or teacher account. The password is stored only as a salted hash."""
    d = request.get_json(silent=True) or {}
    role = d.get("role")
    ident = str(d.get("id", "")).strip()
    name = str(d.get("name", "")).strip()
    password = str(d.get("password", ""))
    if role not in ("student", "teacher"):
        return err("role must be 'student' or 'teacher'")
    if len(name) < 2 or len(name) > 100:
        return err("Please enter your full name.")
    if len(password) < 6 or len(password) > 128:
        return err("Password must be at least 6 characters.")
    pw_hash = generate_password_hash(password)
    try:
        if role == "student":
            usn = ident.upper()
            if not re.fullmatch(r"[A-Z0-9]{6,20}", usn):
                return err("Enter a valid USN (letters and digits only, 6 to 20 characters).")
            database.add_student(usn, name, pw_hash)
        else:
            username = ident.lower()
            if not re.fullmatch(r"[a-z0-9_.]{3,30}", username):
                return err("Username must be 3 to 30 characters: letters, digits, _ or .")
            given = str(d.get("access_code", "")).strip()
            if not secrets.compare_digest(given.upper().encode(), TEACHER_CODE.upper().encode()):
                return err("Invalid teacher access code.", 403)
            database.add_teacher(username, name, pw_hash)
    except sqlite3.IntegrityError:
        return err("This ID is already registered. Please sign in.", 409)
    return jsonify({"message": "Account created. You can sign in now."}), 201


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    role = d.get("role")
    ident = str(d.get("id", "")).strip()
    password = str(d.get("password", ""))
    if role == "student":
        row = database.get_student(ident.upper())
        user_id, name = (row["usn"], row["student_name"]) if row else (None, None)
    elif role == "teacher":
        row = database.get_teacher(ident.lower())
        user_id, name = (row["username"], row["teacher_name"]) if row else (None, None)
    else:
        return err("role must be 'student' or 'teacher'")
    if not row or not check_password_hash(row["password_hash"], password):
        return err("Invalid username/USN or password.", 401)
    token = serializer.dumps({"role": role, "id": user_id})
    return jsonify({"token": token, "role": role, "id": user_id, "name": name})


# ------------------------------------------------------------------ student endpoints
@app.post("/api/submissions")
@auth("student")
def submit_answer():
    d = request.get_json(silent=True) or {}
    answer = str(d.get("answer") or "").strip()
    if len(answer) < 10:
        return err("Please write an answer before submitting.")
    if len(answer) > MAX_ANSWER_CHARS:
        return err(f"Answer too long (max {MAX_ANSWER_CHARS} characters).")
    try:
        qid = int(d["question_id"]) if d.get("question_id") is not None else None
    except (TypeError, ValueError):
        return err("question_id must be a number")
    q = database.get_question(qid)
    if not q:
        return err("Question not found", 404)
    sid = database.create_submission(g.user["id"], q["question_id"], answer)
    return jsonify({"id": sid, "status": "Pending"}), 201


@app.get("/api/submissions/mine")
@auth("student")
def my_submissions():
    return jsonify([ser_sub(s) for s in database.list_submissions(usn=g.user["id"])])


# ------------------------------------------------------------------ teacher endpoints
@app.get("/api/submissions")
@auth("teacher")
def all_submissions():
    return jsonify([ser_sub(s) for s in database.list_submissions()])


@app.get("/api/submissions/<int:sid>")
@auth("teacher")
def one_submission(sid):
    s = database.get_submission(sid)
    return jsonify(ser_sub(s, with_answer=True)) if s else err("Submission not found", 404)


@app.post("/api/submissions/<int:sid>/evaluate-ai")
@auth("teacher")
def evaluate_ai(sid):
    s = database.get_submission(sid)
    if not s:
        return err("Submission not found", 404)
    q = database.get_question(s["question_id"])
    result = run_grader(q["question_text"], q["reference_answer"], s["answer_text"],
                        q["maximum_marks"], q["expected_concepts"],
                        scheme=q.get("marking_scheme", ""), examples=database.list_examples(q["question_id"]))
    database.save_evaluation(sid, "AI", result["marks"], result["score"], "AI evaluation completed.", result)
    saved = database.get_submission(sid)["evaluations"]["AI"]
    out = ser_eval(saved)
    out["fallback_reason"] = result.get("fallback_reason")
    return jsonify(out)


@app.post("/api/submissions/<int:sid>/evaluate-teacher")
@auth("teacher")
def evaluate_teacher(sid):
    s = database.get_submission(sid)
    if not s:
        return err("Submission not found", 404)
    d = request.get_json(silent=True) or {}
    limits = criterion_max(s["maximum_marks"])
    given = {"correctness": d.get("correctness"), "relevance": d.get("relevance"),
             "completeness": d.get("completeness"), "concept_coverage": d.get("coverage")}
    marks = {}
    for key, val in given.items():
        try:
            val = float(val)
        except (TypeError, ValueError):
            return err(f"{key.replace('_', ' ')} must be a number")
        if val < 0 or val > limits[key] + 1e-9:
            return err(f"Please enter marks within the maximum for each criterion "
                       f"({key.replace('_', ' ')}: 0 to {limits[key]:g}).")
        marks[key] = round(val, 1)
    total = round(sum(marks.values()), 1)
    details = {"method": "teacher", "max_marks": s["maximum_marks"], "needs_review": False}
    database.save_evaluation(sid, "Teacher", marks, total, "Teacher evaluation completed.", details)
    return jsonify(ser_eval(database.get_submission(sid)["evaluations"]["Teacher"]))


@app.get("/api/questions")
@auth("teacher")
def questions():
    return jsonify(database.list_questions())


@app.get("/api/questions/public")
@auth("student")
def public_questions():
    """What a student may see: no reference answer, concepts, scheme or examples."""
    return jsonify([{"question_id": q["question_id"], "question_text": q["question_text"],
                     "maximum_marks": q["maximum_marks"]} for q in database.list_questions()])


@app.post("/api/questions")
@auth("teacher")
def create_question():
    d = request.get_json(silent=True) or {}
    text = str(d.get("question_text") or "").strip()
    ref = str(d.get("reference_answer") or "").strip()
    if not text or not ref:
        return err("question_text and reference_answer are required")
    try:
        marks = float(d.get("maximum_marks", 10))
        if marks <= 0 or marks > 100:
            raise ValueError
    except (TypeError, ValueError):
        return err("maximum_marks must be a number between 1 and 100")
    concepts = d.get("expected_concepts") or []
    if isinstance(concepts, str):
        concepts = [c.strip() for c in concepts.split(",") if c.strip()]
    scheme = str(d.get("marking_scheme") or "").strip()
    return jsonify({"id": database.add_question(text, marks, ref, concepts, scheme)}), 201


# ------------------------------------------------------------------ graded examples (few-shot prompting)
@app.get("/api/questions/<int:qid>/examples")
@auth("teacher")
def examples_list(qid):
    if not database.get_question(qid):
        return err("Question not found", 404)
    return jsonify(database.list_examples(qid))


@app.post("/api/questions/<int:qid>/examples")
@auth("teacher")
def examples_add(qid):
    q = database.get_question(qid)
    if not q:
        return err("Question not found", 404)
    d = request.get_json(silent=True) or {}
    answer = str(d.get("answer") or "").strip()
    if len(answer) < 10 or len(answer) > MAX_ANSWER_CHARS:
        return err("Example answer must be between 10 and %d characters." % MAX_ANSWER_CHARS)
    try:
        marks = float(d.get("marks"))
    except (TypeError, ValueError):
        return err("marks must be a number")
    if marks < 0 or marks > q["maximum_marks"]:
        return err("marks must be between 0 and %g for this question." % q["maximum_marks"])
    return jsonify({"id": database.add_example(qid, answer, round(marks, 1))}), 201


@app.delete("/api/examples/<int:eid>")
@auth("teacher")
def examples_delete(eid):
    return jsonify({"deleted": True}) if database.delete_example(eid) else err("Example not found", 404)


if __name__ == "__main__":
    print("GradeAI server starting at http://127.0.0.1:5000  (keep this window open while demonstrating)")
    print(f"Teacher sign-up code (needed to create a teacher account): {TEACHER_CODE}")
    try:
        app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # show the real reason instead of silently closing
        print("\nSERVER STOPPED WITH AN ERROR:", exc)
    input("\nThe server has stopped. Press Enter to close this window...")
