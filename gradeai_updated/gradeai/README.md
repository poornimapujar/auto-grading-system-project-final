# GradeAI: Backend for the Automatic Grading System (Flask + SQLite)

The team's front end (in `frontend/`) is connected to this backend through `frontend/js/app.js`.
Students pick a question and submit an answer; teachers manage questions, add graded examples and evaluate.

## Run (Windows): FREE, with a local model (no tokens, no limits)
1. Install **Ollama** from https://ollama.com (one time) and let it finish.
2. Double-click `start_server.bat`. It installs the requirements and downloads the model `qwen2.5:3b`
   (about 2 GB, first time only), then starts the server and opens the browser.
3. When it asks for an API key, just press Enter to use the free local model.
Open **http://127.0.0.1:5000** if the browser does not open by itself.

Which grader is used (`GRADER_MODE`, default `auto`): Claude if `ANTHROPIC_API_KEY` is set (paid) -> else the free
Ollama model -> else the offline TF-IDF grader. Other options: `set GRADER_MODE=ollama|claude|offline`,
`set OLLAMA_MODEL=llama3.2:3b` (any model you have pulled). Check what is running: `/api/health`.
Self-test (no key, no Ollama needed): `py test_api.py`

## Accounts (stored in the database, nothing is hardcoded)
- **Students** click **"New here? Create an account"** on the login page and enter their USN, name and a password
  (at least 6 characters). Passwords are saved only as salted hashes.
- **Teachers** do the same on the Teacher tab, and must also enter the **teacher access code**. The code is printed in
  the server window every time it starts ("Teacher sign-up code: ...") and saved in the file `.teacher_code`.
  You can set your own with `set TEACHER_CODE=yourcode` before starting.
- To start from a clean database, stop the server and delete `gradeai.db`.

## Flow
Student signs up / logs in -> submits answer (`POST /api/submissions`) -> teacher opens the submission -> clicks
**Evaluate with AI** (`POST /api/submissions/<id>/evaluate-ai`) -> backend sends question + reference answer + expected
concepts + marking scheme + teacher-graded examples + student answer to the LLM -> LLM returns ratings -> backend converts to marks (3/2/3/2 out of 10), saves in
SQLite, returns JSON -> page shows score + rubric. The teacher can also enter marks manually. The student sees both.

## API
| Method | URL | Who | Purpose |
|---|---|---|---|
| POST | `/api/login` | all | `{role, id, password}` -> `{token, role, id, name}` (token sent as `Authorization: Bearer ...`) |
| POST | `/api/submissions` | student | `{answer, question_id}` submit an answer |
| GET | `/api/questions/public` | student | list questions (no reference answers) |
| GET | `/api/submissions/mine` | student | own submissions + evaluations |
| GET | `/api/submissions` | teacher | all submissions |
| GET | `/api/submissions/<id>` | teacher | one submission with the answer |
| POST | `/api/submissions/<id>/evaluate-ai` | teacher | grade with the LLM (saved) |
| POST | `/api/submissions/<id>/evaluate-teacher` | teacher | `{correctness, relevance, completeness, coverage}` |
| GET/POST | `/api/questions` | teacher | list / add questions (reference answer, concepts, marking scheme) |
| GET/POST | `/api/questions/<id>/examples` | teacher | list / add teacher-graded example answers (few-shot) |
| DELETE | `/api/examples/<id>` | teacher | delete an example |
| GET | `/api/health` | all | server check |

## Database (`gradeai.db`, created automatically)
`students`, `teachers`, `questions` (with `reference_answer`, `expected_concepts`, `marking_scheme`), `graded_examples`,
`submissions`, `evaluations` (one row per submission per method: AI or Teacher). Older databases are upgraded
automatically when the server starts. Schema in `schema.sql`, derived from the team's MySQL schema
(kept in `docs/original_mysql/`). Changes from it: added `teachers`; added reference answer and concepts to
`questions`; evaluations are unique per (submission, method) so AI and Teacher results can both exist.

## Few-shot examples ("training" the model with sample answers)
Ollama models cannot be trained this way, but they can be *shown* marked answers inside the prompt (few-shot prompting,
the "completion-based approach" of the reference paper). On the teacher **Questions** page, add sample answers with the
marks you gave. When grading, the prompt includes up to 2 low, 2 medium and 2 high scoring examples for that question,
so the model calibrates its strictness. Feedback text is not generated (marks, rubric and matched/missing concepts only).

## Files
`app.py` endpoints and login | `database.py` data layer and seed data | `llm_grader.py` prompt + LLM call |
`scoring.py` ratings -> marks | `offline_grader.py` TF-IDF fallback | `frontend/` the team's pages | `test_api.py` (self-test)
