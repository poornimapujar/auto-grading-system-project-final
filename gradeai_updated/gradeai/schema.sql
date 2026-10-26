-- GradeAI database schema (SQLite). Based on the team's MySQL schema, with these additions:
--   teachers table (teacher login), questions.reference_answer + expected_concepts (needed by the LLM),
--   evaluations: one row per (submission, method) so a submission can have BOTH an AI and a Teacher evaluation,
--   evaluations.summary / details_json for feedback text.
CREATE TABLE IF NOT EXISTS students (
    usn           TEXT PRIMARY KEY,
    student_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teachers (
    username      TEXT PRIMARY KEY,
    teacher_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    question_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text     TEXT NOT NULL,
    maximum_marks     REAL NOT NULL DEFAULT 10,
    reference_answer  TEXT NOT NULL DEFAULT '',
    expected_concepts TEXT NOT NULL DEFAULT '[]',
    marking_scheme    TEXT NOT NULL DEFAULT ''
);
-- Teacher-graded sample answers per question. They are put in the LLM prompt (few-shot prompting)
-- so the model can calibrate how strict to be. marks = total marks the teacher gave (out of the question's maximum).
CREATE TABLE IF NOT EXISTS graded_examples (
    example_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id   INTEGER NOT NULL REFERENCES questions(question_id),
    answer_text   TEXT NOT NULL,
    marks         REAL NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ex_q ON graded_examples(question_id);
CREATE TABLE IF NOT EXISTS submissions (
    submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    usn           TEXT NOT NULL REFERENCES students(usn),
    question_id   INTEGER NOT NULL REFERENCES questions(question_id),
    answer_text   TEXT NOT NULL,
    submitted_at  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'Pending'
);
CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id     INTEGER NOT NULL REFERENCES submissions(submission_id),
    evaluation_method TEXT NOT NULL CHECK (evaluation_method IN ('AI', 'Teacher')),
    correctness       REAL NOT NULL DEFAULT 0,
    relevance         REAL NOT NULL DEFAULT 0,
    completeness      REAL NOT NULL DEFAULT 0,
    concept_coverage  REAL NOT NULL DEFAULT 0,
    total_marks       REAL NOT NULL DEFAULT 0,
    summary           TEXT,
    details_json      TEXT,
    evaluated_at      TEXT NOT NULL,
    UNIQUE (submission_id, evaluation_method)
);
CREATE INDEX IF NOT EXISTS idx_sub_usn ON submissions(usn);
