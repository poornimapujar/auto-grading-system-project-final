"""End-to-end self-test of the backend. Run:  python test_api.py   (uses a temporary database, no API key needed)"""
import os
import tempfile

os.environ["GRADER_MODE"] = "offline"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["TEACHER_CODE"] = "TESTCODE"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from app import app  # noqa: E402

c = app.test_client()


def login(role, ident, pw):
    r = c.post("/api/login", json={"role": role, "id": ident, "password": pw})
    return r, (r.get_json() or {}).get("token")


def H(tok):
    return {"Authorization": "Bearer " + tok}


# --- no hardcoded accounts: login fails until someone signs up
assert login("student", "2SD24CS002", "1234")[0].status_code == 401
assert login("teacher", "teacher", "teach1234")[0].status_code == 401


def register(role, ident, name, pw, code=""):
    return c.post("/api/register", json={"role": role, "id": ident, "name": name, "password": pw, "access_code": code})


# --- sign-up validation
assert register("student", "2SD24CS002", "A", "secret1").status_code == 400            # name too short
assert register("student", "2SD24CS002", "Student One", "123").status_code == 400      # password too short
assert register("student", "bad id!", "Student One", "secret1").status_code == 400     # invalid USN
assert register("teacher", "teacher", "Teacher One", "secret1", "WRONG").status_code == 403   # wrong access code
assert register("student", "2SD24CS002", "Student One", "secret1").status_code == 201
assert register("student", "2sd24cs002", "Again", "secret1").status_code == 409       # duplicate USN (case-insensitive)
assert register("student", "2ST24CS054", "Student Two", "secret2").status_code == 201
assert register("teacher", "teacher", "Teacher One", "teachpw1", "testcode").status_code == 201
assert register("teacher", "teacher", "Teacher One", "teachpw1", "TESTCODE").status_code == 409
print("sign-up OK")

# --- login
assert login("student", "2SD24CS002", "wrong")[0].status_code == 401
assert login("student", "nobody", "secret1")[0].status_code == 401
r, stu = login("student", "2sd24cs002", "secret1")            # USN is case-insensitive
assert r.status_code == 200 and r.get_json()["id"] == "2SD24CS002"
r, stu2 = login("student", "2ST24CS054", "secret2")
r, tea = login("teacher", "teacher", "teachpw1")
assert stu and stu2 and tea
import sqlite3
row = sqlite3.connect(os.environ["DB_PATH"]).execute("SELECT password_hash FROM students WHERE usn='2SD24CS002'").fetchone()[0]
assert "secret1" not in row and len(row) > 40      # stored as a salted hash, never plain text
print("login OK")

# --- protection
assert c.get("/api/submissions").status_code == 401                       # no token
assert c.get("/api/submissions", headers=H(stu)).status_code == 403       # student cannot see all
assert c.post("/api/submissions", json={"answer": "x" * 20}, headers=H(tea)).status_code == 403
assert c.get("/api/submissions", headers={"Authorization": "Bearer junk"}).status_code == 401
print("access control OK")

# --- student submits
assert c.post("/api/submissions", json={"answer": "short"}, headers=H(stu)).status_code == 400
good = ("Software engineering principles such as modularity, testing, documentation and requirements analysis "
        "improve reliability, maintainability and quality, and they reduce complexity through good design and reusability.")
r = c.post("/api/submissions", json={"answer": good}, headers=H(stu))
assert r.status_code == 201
sid = r.get_json()["id"]
c.post("/api/submissions", json={"answer": "Software is code that runs on computers and it is useful."}, headers=H(stu2))
mine = c.get("/api/submissions/mine", headers=H(stu)).get_json()
assert len(mine) == 1 and mine[0]["status"] == "Pending" and "answer" not in mine[0]   # only own submissions
print("submit OK")

# --- teacher dashboard
allsubs = c.get("/api/submissions", headers=H(tea)).get_json()
assert len(allsubs) == 2
detail = c.get(f"/api/submissions/{sid}", headers=H(tea)).get_json()
assert detail["answer"] == good and detail["usn"] == "2SD24CS002"
assert c.get("/api/submissions/9999", headers=H(tea)).status_code == 404

# --- AI evaluation
ai = c.post(f"/api/submissions/{sid}/evaluate-ai", headers=H(tea)).get_json()
print("AI eval:", ai["score"], "/", ai["max_marks"], "| rubric:", ai["correctness"], ai["relevance"], ai["completeness"], ai["coverage"], "| grader:", ai["grader"])
assert abs(ai["score"] - (ai["correctness"] + ai["relevance"] + ai["completeness"] + ai["coverage"])) < 1e-6
assert ai["correctness"] <= 3 and ai["relevance"] <= 2 and ai["completeness"] <= 3 and ai["coverage"] <= 2

# --- teacher evaluation + validation
bad = c.post(f"/api/submissions/{sid}/evaluate-teacher", json={"correctness": 5, "relevance": 1, "completeness": 1, "coverage": 1}, headers=H(tea))
assert bad.status_code == 400, bad.get_json()
t = c.post(f"/api/submissions/{sid}/evaluate-teacher", json={"correctness": 2.5, "relevance": 2, "completeness": 2, "coverage": 1.5}, headers=H(tea)).get_json()
assert t["score"] == 8.0
assert c.post(f"/api/submissions/{sid}/evaluate-teacher", json={"correctness": "a"}, headers=H(tea)).status_code == 400

# --- student sees both
mine = c.get("/api/submissions/mine", headers=H(stu)).get_json()[0]
assert mine["status"] == "Evaluated" and mine["aiEvaluation"] and mine["teacherEvaluation"]["score"] == 8.0
# re-evaluating replaces (no duplicates)
c.post(f"/api/submissions/{sid}/evaluate-ai", headers=H(tea))
assert len(c.get("/api/submissions", headers=H(tea)).get_json()) == 2
print("evaluations OK")

# --- weak answer scores lower than good answer
sid2 = [s for s in allsubs if s["usn"] == "2ST24CS054"][0]["id"]
weak = c.post(f"/api/submissions/{sid2}/evaluate-ai", headers=H(tea)).get_json()
print("weak answer:", weak["score"], "vs good answer:", ai["score"])
assert weak["score"] < ai["score"]

# --- teacher adds a question
q = c.post("/api/questions", json={"question_text": "Define polymorphism.", "reference_answer": "Polymorphism lets objects of different classes respond to the same message."}, headers=H(tea))
assert q.status_code == 201 and len(c.get("/api/questions", headers=H(tea)).get_json()) == 2

# --- Step 2: students pick a question; they never see reference answers
pub = c.get("/api/questions/public", headers=H(stu)).get_json()
assert len(pub) == 2 and set(pub[0]) == {"question_id", "question_text", "maximum_marks"}
assert c.get("/api/questions/public", headers=H(tea)).status_code == 403
assert c.get("/api/questions", headers=H(stu)).status_code == 403
q2 = pub[1]["question_id"]
r = c.post("/api/submissions", json={"answer": "Polymorphism means one interface, many forms.", "question_id": q2}, headers=H(stu))
assert r.status_code == 201
assert c.post("/api/submissions", json={"answer": "x" * 20, "question_id": 999}, headers=H(stu)).status_code == 404
sub2 = c.get(f"/api/submissions/{r.get_json()['id']}", headers=H(tea)).get_json()
assert sub2["question_id"] == q2 and "polymorphism" in sub2["question"]
print("multiple questions OK")

# --- Step 4/5: marking scheme + graded examples (few-shot)
qs = c.post("/api/questions", json={"question_text": "What is encapsulation?", "reference_answer": "Hiding data inside a class.",
            "maximum_marks": 10, "marking_scheme": "5 marks definition, 5 marks example"}, headers=H(tea))
assert qs.status_code == 201
qid = qs.get_json()["id"]
assert [q for q in c.get("/api/questions", headers=H(tea)).get_json() if q["question_id"] == qid][0]["marking_scheme"].startswith("5 marks")
ex_url = f"/api/questions/{qid}/examples"
assert c.get(ex_url, headers=H(stu)).status_code == 403
assert c.post(ex_url, json={"answer": "short", "marks": 5}, headers=H(tea)).status_code == 400
assert c.post(ex_url, json={"answer": "A valid long example answer", "marks": 11}, headers=H(tea)).status_code == 400   # above max
assert c.post(ex_url, json={"answer": "A valid long example answer", "marks": "x"}, headers=H(tea)).status_code == 400
assert c.post("/api/questions/9999/examples", json={"answer": "A valid long example answer", "marks": 5}, headers=H(tea)).status_code == 404
for text, m in [("Weak example answer about data", 2), ("Medium example answer about data hiding", 6), ("Strong example answer about hiding data in a class with methods", 9)]:
    assert c.post(ex_url, json={"answer": text, "marks": m}, headers=H(tea)).status_code == 201
exs = c.get(ex_url, headers=H(tea)).get_json()
assert len(exs) == 3
import llm_grader
prompt = llm_grader.build_user_prompt("Q?", "ref", "STUDENT TEXT", 10, ["a"], "5 marks definition", exs)
assert "GRADED EXAMPLES" in prompt and "teacher gave 9 out of 10" in prompt and "MARKING SCHEME" in prompt
assert prompt.index("GRADED EXAMPLES") < prompt.index("STUDENT ANSWER") and prompt.count("Example ") == 3
assert "GRADED EXAMPLES" not in llm_grader.build_user_prompt("Q?", "ref", "S", 10, [], "", [])
assert "feedback" not in llm_grader.SYSTEM_PROMPT.lower().split("respond with only")[1]       # no feedback requested
many = [{"example_id": i, "answer_text": f"a{i}", "marks": 9} for i in range(1, 6)]
assert len(llm_grader.pick_examples(many, 10)) == 2                                           # at most 2 per band
res = c.post(f"/api/submissions/{sid}/evaluate-ai", headers=H(tea)).get_json()
assert "strengths" not in res and "improvements" not in res                                    # feedback removed
assert c.delete(f"/api/examples/{exs[0]['example_id']}", headers=H(tea)).status_code == 200
assert c.delete(f"/api/examples/{exs[0]['example_id']}", headers=H(tea)).status_code == 404
assert len(c.get(ex_url, headers=H(tea)).get_json()) == 2
print("examples + scheme OK")

# --- front end served
for path in ["/", "/js/app.js", "/css/style.css", "/student/student.html", "/teacher/dashboard.html", "/teacher/evaluate.html", "/teacher/history.html", "/teacher/questions.html"]:
    assert c.get(path).status_code == 200, path
print("front end files served OK")
print("ALL TESTS PASSED")
