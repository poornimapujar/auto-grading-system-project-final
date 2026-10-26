// GradeAI front end, connected to the Flask backend.
const API = location.protocol.startsWith('http') ? '' : 'http://127.0.0.1:5000';
// Share of the total marks for each criterion (same as WEIGHTS in scoring.py): 10 marks -> 3 / 2 / 3 / 2
const WEIGHTS = { correctness: 0.3, relevance: 0.2, completeness: 0.3, coverage: 0.2 };

function token() { return sessionStorage.getItem('gradeai_token'); }
function logout() { sessionStorage.clear(); location.href = '../index.html'; }
function safe(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtDate(iso) { return iso ? new Date(iso).toLocaleString() : ''; }
function fmtNum(n) { return Number(n).toString(); }

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token()) headers.Authorization = 'Bearer ' + token();
  let res;
  try { res = await fetch(API + path, { ...options, headers }); }
  catch (e) { throw new Error('Cannot reach the server. Is the backend running?'); }
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (res.status === 401 && token()) { logout(); }
  if (!res.ok) throw new Error(data.error || 'Server error ' + res.status);
  return data;
}

function requireRole(role) {
  if (sessionStorage.getItem('gradeai_role') !== role || !token()) { location.href = '../index.html'; return false; }
  return true;
}

document.addEventListener('DOMContentLoaded', () => {
  // ---------------- login / sign-up page
  const form = document.getElementById('loginForm');
  if (form) {
    const $ = id => document.getElementById(id);
    let role = 'student';
    let mode = 'login';   // 'login' or 'register'
    const refresh = () => {
      const student = role === 'student';
      $('idLabel').textContent = student ? 'University Seat Number (USN)' : 'Teacher username';
      $('loginId').placeholder = student ? 'Enter your USN' : 'Enter teacher username';
      $('registerFields').hidden = mode !== 'register';
      $('codeField').hidden = mode !== 'register' || student;
      $('submitBtn').textContent = mode === 'login' ? 'Sign in →' : 'Create account →';
      $('toggleMode').textContent = mode === 'login' ? 'New here? Create an account' : 'Already have an account? Sign in';
      $('loginPassword').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
      $('loginError').textContent = '';
    };
    document.querySelectorAll('[data-role]').forEach(b => b.onclick = () => {
      role = b.dataset.role;
      document.querySelectorAll('[data-role]').forEach(x => x.classList.toggle('active', x === b));
      $('loginHint').textContent = role === 'student' ? 'Student portal selected.' : 'Teacher portal selected.';
      refresh();
    });
    $('toggleMode').onclick = e => { e.preventDefault(); mode = mode === 'login' ? 'register' : 'login'; refresh(); };
    form.onsubmit = async e => {
      e.preventDefault();
      const err = $('loginError');
      err.textContent = '';
      const id = $('loginId').value.trim();
      const password = $('loginPassword').value;
      try {
        if (mode === 'register') {
          if (password !== $('regPassword2').value) { err.textContent = 'Passwords do not match.'; return; }
          await api('/api/register', {
            method: 'POST',
            body: JSON.stringify({ role, id, password, name: $('regName').value.trim(), access_code: $('regCode').value.trim() })
          });
          mode = 'login';
          refresh();
          $('loginPassword').value = '';
          $('regPassword2').value = '';
          $('loginHint').textContent = 'Account created. Please sign in with your new password.';
          return;
        }
        const d = await api('/api/login', { method: 'POST', body: JSON.stringify({ role, id, password }) });
        sessionStorage.setItem('gradeai_token', d.token);
        sessionStorage.setItem('gradeai_role', d.role);
        sessionStorage.setItem('gradeai_user', d.id);
        sessionStorage.setItem('gradeai_name', d.name);
        location.href = d.role === 'student' ? 'student/student.html' : 'teacher/dashboard.html';
      } catch (ex) { err.textContent = ex.message; }
    };
    refresh();
  }

  // ---------------- student page
  if (document.getElementById('answerText')) {
    if (!requireRole('student')) return;
    const ta = document.getElementById('answerText');
    const msg = document.getElementById('submitMessage');
    const sel = document.getElementById('questionSelect');
    let questions = [];
    function showQ() {
      const q = questions.find(x => x.question_id === Number(sel.value));
      if (!q) return;
      document.getElementById('qPill').textContent = `QUESTION ${q.question_id} · ${fmtNum(q.maximum_marks)} MARKS`;
      document.getElementById('qText').textContent = q.question_text;
    }
    sel.onchange = showQ;
    api('/api/questions/public').then(list => {
      questions = list;
      sel.innerHTML = list.map(q => `<option value="${q.question_id}">Question ${q.question_id}</option>`).join('');
      showQ();
    }).catch(ex => { msg.textContent = ex.message; });

    ta.oninput = () => document.getElementById('wordCount').textContent = (ta.value.trim() ? ta.value.trim().split(/\s+/).length : 0) + ' words';
    document.getElementById('submitAnswer').onclick = async () => {
      if (ta.value.trim().length < 10) { msg.textContent = 'Please write an answer before submitting.'; return; }
      if (!sel.value) { msg.textContent = 'No question is available yet.'; return; }
      try {
        await api('/api/submissions', { method: 'POST', body: JSON.stringify({ answer: ta.value.trim(), question_id: Number(sel.value) }) });
        ta.value = '';
        document.getElementById('wordCount').textContent = '0 words';
        msg.textContent = 'Answer submitted successfully.';
        renderStudentResults();
      } catch (ex) { msg.textContent = ex.message; }
    };
    renderStudentResults();
  }

  // ---------------- teacher pages
  if (document.getElementById('submissionRows')) renderRows('submissionRows');
  if (document.getElementById('historyRows')) renderRows('historyRows');
  if (document.getElementById('studentAnswer')) loadEvaluation();
  if (document.getElementById('questionList')) loadQuestionsPage();
});

async function renderStudentResults() {
  const el = document.getElementById('studentResults');
  let items;
  try { items = await api('/api/submissions/mine'); } catch (ex) { el.textContent = ex.message; return; }
  if (!items.length) { el.textContent = 'No evaluated submissions yet.'; return; }
  el.innerHTML = items.map(x => {
    const rows = [];
    if (x.aiEvaluation) {
      const a = x.aiEvaluation;
      rows.push(`<div class="rubricrow"><span>AI evaluation · ${safe(fmtDate(x.submitted_at))}</span><strong>${safe(a.score)}/${safe(a.max_marks)}</strong></div>`);
    }
    if (x.teacherEvaluation) rows.push(`<div class="rubricrow"><span>Teacher evaluation · ${safe(fmtDate(x.submitted_at))}</span><strong>${safe(x.teacherEvaluation.score)}/${safe(x.teacherEvaluation.max_marks)}</strong></div>`);
    if (!rows.length) rows.push(`<p>Submission ${safe(fmtDate(x.submitted_at))} — awaiting evaluation.</p>`);
    return `<div class="submission-result"><strong>Question ${safe(x.question_id)}</strong>${rows.join('')}</div>`;
  }).join('');
}

async function renderRows(id) {
  if (!requireRole('teacher')) return;
  const el = document.getElementById(id);
  let items;
  try { items = await api('/api/submissions'); }
  catch (ex) { el.innerHTML = `<tr><td colspan="4">${safe(ex.message)}</td></tr>`; return; }
  if (!items.length) { el.innerHTML = '<tr><td colspan="4">No submissions yet.</td></tr>'; return; }
  el.innerHTML = items.map(x => `<tr><td>${safe(x.usn)}</td><td>${safe(fmtDate(x.submitted_at))}</td><td>${safe(x.status)}</td><td><a class="action-link" href="evaluate.html?id=${x.id}">Open evaluation →</a></td></tr>`).join('');
}

async function loadEvaluation() {
  if (!requireRole('teacher')) return;
  const id = Number(new URLSearchParams(location.search).get('id'));
  const answerEl = document.getElementById('studentAnswer');
  let item;
  try { item = await api('/api/submissions/' + id); }
  catch (ex) { answerEl.textContent = id ? ex.message : 'Return to the dashboard and select a submission.'; return; }

  const maxMarks = Number(item.max_marks);
  document.getElementById('studentDetails').textContent =
    'Student USN: ' + item.usn + ' (' + item.student_name + ') | Question ' + item.question_id + ': ' + item.question;
  answerEl.textContent = item.answer;

  // manual form limits follow the question's maximum marks (30% / 20% / 30% / 20%)
  const fields = [['Correctness', 'mCorrectness', 'correctness'], ['Relevance', 'mRelevance', 'relevance'],
                  ['Completeness', 'mCompleteness', 'completeness'], ['Concept coverage', 'mCoverage', 'coverage']];
  fields.forEach(([name, inputId, key]) => {
    const max = +(WEIGHTS[key] * maxMarks).toFixed(2);
    document.getElementById(inputId).max = max;
    document.getElementById(inputId + 'Label').textContent = `${name} (max ${max})`;
  });
  document.getElementById('manualTotal').textContent = `Enter marks for each criterion (total: ${fmtNum(maxMarks)} marks).`;

  // AI and Teacher results are shown side by side, each with its own label
  const evals = {};
  function block(e) {
    let note = '';
    if (e.method === 'AI' && e.grader === 'offline') note = 'Offline fallback used because the AI model was unavailable. Please review manually.';
    else if (e.method === 'AI' && e.needs_review) note = 'AI confidence is not high. Teacher review recommended.';
    const rubric = fields.map(([name, , key]) =>
      `<div class="rubricrow"><span>${name}</span><strong>${safe(e[key])} / ${+(WEIGHTS[key] * e.max_marks).toFixed(2)}</strong></div>`).join('');
    let concepts = '';
    if (e.method === 'AI') {
      if (e.matched_concepts && e.matched_concepts.length) concepts += `<p><strong>Concepts found:</strong> ${e.matched_concepts.map(safe).join(', ')}</p>`;
      if (e.missing_concepts && e.missing_concepts.length) concepts += `<p><strong>Concepts missing:</strong> ${e.missing_concepts.map(safe).join(', ')}</p>`;
    }
    return `<div class="eval-block"><h3>${e.method === 'AI' ? 'AI evaluation' : 'Teacher evaluation'}</h3>
      <div class="score"><strong>${safe(e.score)}</strong> <span>/ ${safe(e.max_marks)} marks</span></div>
      ${note ? `<p>${safe(note)}</p>` : ''}${rubric}${concepts}</div>`;
  }
  function show(e) {
    evals[e.method] = e;
    document.getElementById('evaluationResult').hidden = false;
    document.getElementById('evalBlocks').innerHTML = ['AI', 'Teacher'].filter(m => evals[m]).map(m => block(evals[m])).join('');
  }
  if (item.aiEvaluation) show(item.aiEvaluation);
  if (item.teacherEvaluation) show(item.teacherEvaluation);

  const aiBtn = document.getElementById('evaluateAI');
  aiBtn.onclick = async () => {
    const label = aiBtn.textContent;
    aiBtn.disabled = true; aiBtn.textContent = 'Evaluating...';
    try {
      const e = await api('/api/submissions/' + id + '/evaluate-ai', { method: 'POST' });
      show(e);
      document.getElementById('savedStatus').textContent = 'AI evaluation saved.';
    } catch (ex) { document.getElementById('savedStatus').textContent = ex.message; }
    finally { aiBtn.disabled = false; aiBtn.textContent = label; }
  };

  document.getElementById('teacherEvaluate').onclick = () => {
    const panel = document.getElementById('manualPanel');
    panel.hidden = !panel.hidden;
  };

  document.getElementById('manualForm').onsubmit = async ev => {
    ev.preventDefault();
    const msg = document.getElementById('manualMessage');
    try {
      const e = await api('/api/submissions/' + id + '/evaluate-teacher', {
        method: 'POST',
        body: JSON.stringify({
          correctness: Number(document.getElementById('mCorrectness').value),
          relevance: Number(document.getElementById('mRelevance').value),
          completeness: Number(document.getElementById('mCompleteness').value),
          coverage: Number(document.getElementById('mCoverage').value)
        })
      });
      show(e);
      msg.textContent = 'Teacher evaluation saved successfully.';
      document.getElementById('savedStatus').textContent = 'Teacher evaluation saved successfully.';
    } catch (ex) { msg.textContent = ex.message; }
  };
}

// ---------------- teacher: manage questions + graded examples
async function loadQuestionsPage() {
  if (!requireRole('teacher')) return;
  const list = document.getElementById('questionList');
  const qMsg = document.getElementById('nqMessage');

  async function refresh() {
    let qs, exs;
    try {
      qs = await api('/api/questions');
      exs = await Promise.all(qs.map(q => api('/api/questions/' + q.question_id + '/examples')));
    } catch (ex) { list.textContent = ex.message; return; }
    if (!qs.length) { list.textContent = 'No questions yet.'; return; }
    list.innerHTML = qs.map((q, i) => `
      <section class="card">
        <span class="pill">QUESTION ${safe(q.question_id)} · ${safe(fmtNum(q.maximum_marks))} MARKS</span>
        <h2>${safe(q.question_text)}</h2>
        <p><strong>Reference answer:</strong> ${safe(q.reference_answer)}</p>
        ${q.expected_concepts.length ? `<p><strong>Expected concepts:</strong> ${q.expected_concepts.map(safe).join(', ')}</p>` : ''}
        ${q.marking_scheme ? `<p><strong>Marking scheme:</strong> ${safe(q.marking_scheme)}</p>` : ''}
        <h3>Graded examples (${exs[i].length})</h3>
        <p>Add answers you have already marked. The AI sees up to 2 low, 2 medium and 2 high scoring examples when it grades.</p>
        ${exs[i].map(e => `<div class="rubricrow"><span>${safe(e.answer_text)}</span>
            <span><strong>${safe(fmtNum(e.marks))}/${safe(fmtNum(q.maximum_marks))}</strong>
            <button class="secondary" data-del="${e.example_id}">Delete</button></span></div>`).join('')}
        <div class="ex-form" data-qid="${q.question_id}" data-max="${q.maximum_marks}">
          <textarea rows="3" class="ex-answer" placeholder="Paste a sample student answer"></textarea>
          <div class="row">
            <input type="number" class="ex-marks" min="0" max="${q.maximum_marks}" step="0.5" placeholder="Marks (0 to ${fmtNum(q.maximum_marks)})" style="max-width:220px">
            <button class="primary" data-add="1">Add example</button>
          </div>
          <p class="error ex-msg"></p>
        </div>
      </section>`).join('');
  }

  list.onclick = async ev => {
    const btn = ev.target.closest('button');
    if (!btn) return;
    if (btn.dataset.del) {
      try { await api('/api/examples/' + btn.dataset.del, { method: 'DELETE' }); refresh(); }
      catch (ex) { alert(ex.message); }
    } else if (btn.dataset.add) {
      const f = btn.closest('.ex-form');
      const msg = f.querySelector('.ex-msg');
      try {
        await api('/api/questions/' + f.dataset.qid + '/examples', {
          method: 'POST',
          body: JSON.stringify({ answer: f.querySelector('.ex-answer').value.trim(), marks: f.querySelector('.ex-marks').value })
        });
        refresh();
      } catch (ex) { msg.textContent = ex.message; }
    }
  };

  document.getElementById('questionForm').onsubmit = async ev => {
    ev.preventDefault();
    try {
      await api('/api/questions', {
        method: 'POST',
        body: JSON.stringify({
          question_text: document.getElementById('nqText').value.trim(),
          maximum_marks: Number(document.getElementById('nqMarks').value),
          reference_answer: document.getElementById('nqRef').value.trim(),
          expected_concepts: document.getElementById('nqConcepts').value,
          marking_scheme: document.getElementById('nqScheme').value.trim()
        })
      });
      ev.target.reset();
      document.getElementById('nqMarks').value = 10;
      qMsg.className = 'success';
      qMsg.textContent = 'Question added.';
      refresh();
    } catch (ex) { qMsg.className = 'error'; qMsg.textContent = ex.message; }
  };
  refresh();
}
