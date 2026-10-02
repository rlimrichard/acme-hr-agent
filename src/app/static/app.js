// Talks to the REAL /chat and /health endpoints in src/app/main.py.
//
// Confirmation flow: the API uses a simple `confirmed: bool` flag, not
// conversation history. When a response comes back with
// requires_confirmation: true, we show a "confirm" button on that same
// message. Clicking it resends the EXACT SAME query + employee_id with
// confirmed: true, per how HRAgent.answer() actually works (see
// src/agent/orchestrator.py — confirmed is a parameter on the same call,
// not something inferred from a follow-up message).

// ---- Theme ----
const htmlEl = document.documentElement;
const themeToggle = document.getElementById('theme-toggle');

function applyTheme(theme) {
  htmlEl.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
}

(function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'dark' || saved === 'light') {
    applyTheme(saved);
  } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    applyTheme('dark');
  }
})();

themeToggle.addEventListener('click', () => {
  applyTheme(htmlEl.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
});

// ---- Chat ----
const thread = document.getElementById('thread');
const intro = document.getElementById('intro');
const composerEl = document.getElementById('composer');
const queryInput = document.getElementById('query-input');
const sendBtn = document.getElementById('send-btn');
let signedInEmployeeId = '';
const healthDot = document.getElementById('health-dot');
const healthLabel = document.getElementById('health-label');

const tplUser = document.getElementById('tpl-user-message');
const tplAgent = document.getElementById('tpl-agent-message');
const tplThinking = document.getElementById('tpl-thinking');

const EMPLOYEE_ID_PATTERN = /^EMP-\d{3}$/;

async function loadEmployeeOptions() {
  try {
    const res = await fetch('/portal/me');
    if (res.status === 401) { window.location.href = '/login'; return; }
    if (!res.ok) throw new Error('account unavailable');
    const data = await res.json();
    signedInEmployeeId = data.employee_id;
    document.getElementById('employee-label').textContent = `${data.name} (${data.employee_id})`;
  } catch {
    document.getElementById('employee-label').textContent = 'Account unavailable';
  }
}

function scrollToBottom() {
  thread.scrollTop = thread.scrollHeight;
}

function hideIntroOnce() {
  if (intro && !intro.hidden) intro.hidden = true;
}

function addUserMessage(text) {
  hideIntroOnce();
  const node = tplUser.content.cloneNode(true);
  node.querySelector('.message__bubble').textContent = text;
  thread.appendChild(node);
  scrollToBottom();
}

function escapeHtml(value) {
  const s = typeof value === 'string' ? value : String(value);
  return s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function renderCitations(container, citations, snippets) {
  container.innerHTML = '';
  citations.forEach((c) => {
    const snippet = snippets.find((s) => s.doc_id === c.doc_id && s.section === c.section);
    const item = document.createElement('div');
    item.className = 'citation-item';
    item.innerHTML = `
      <div class="citation-item__title">${escapeHtml(c.doc_title || c.doc_id)} <span class="citation-item__section">— ${escapeHtml(c.section)}</span></div>
      ${snippet && snippet.text ? `<div class="citation-item__snippet">"${escapeHtml(snippet.text)}"</div>` : ''}
    `;
    container.appendChild(item);
  });
}

function renderTrace(container, trace) {
  container.innerHTML = '';
  trace.forEach((t) => {
    const item = document.createElement('div');
    item.className = 'trace-item';
    item.innerHTML = `
      <span class="trace-item__tool">${escapeHtml(t.tool)}</span>
      <div class="trace-item__args">args: ${escapeHtml(JSON.stringify(t.args))}</div>
      <div class="trace-item__result">result: ${escapeHtml(JSON.stringify(t.result))}</div>
    `;
    container.appendChild(item);
  });
}

function showThinking() {
  const node = tplThinking.content.cloneNode(true);
  thread.appendChild(node);
  scrollToBottom();
  return thread.querySelector('.message--thinking:last-of-type');
}

function addAgentMessage(data, originalQuery, employeeId) {
  const node = tplAgent.content.cloneNode(true);
  const bubble = node.querySelector('.message__bubble');

  node.querySelector('.message__answer').textContent = data.answer;

  if (data.escalated) {
    const escalation = node.querySelector('.message__escalated');
    escalation.textContent = data.escalation_message || 'HR review recommended.';
    escalation.hidden = false;
  }

  // The backend's `confirmed` flag is a parameter on the SAME call, not
  // conversation history (see HRAgent.answer() in orchestrator.py) -- so
  // confirming just resends the identical query + employee_id with
  // confirmed: true, rather than tracking any multi-turn state here.
  if (data.requires_confirmation) {
    const confirmBtn = node.querySelector('.confirm-btn');
    confirmBtn.hidden = false;
    confirmBtn.addEventListener('click', () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Submitting…';
      sendQuery(originalQuery, employeeId, /* confirmed */ true);
    });
  }

  const citationsSection = node.querySelector('.message__citations');
  if (data.citations && data.citations.length) {
    citationsSection.hidden = false;
    citationsSection.querySelector('.count').textContent = `(${data.citations.length})`;
    renderCitations(citationsSection.querySelector('.citations-body'), data.citations, data.snippets || []);
  }

  const traceSection = node.querySelector('.message__trace');
  if (data.tool_trace && data.tool_trace.length) {
    traceSection.hidden = false;
    traceSection.querySelector('.count').textContent = `(${data.tool_trace.length} steps)`;
    renderTrace(traceSection.querySelector('.trace-body'), data.tool_trace);
  }

  thread.appendChild(node);

  bubble.querySelectorAll('.section-toggle').forEach((btn) => {
    btn.addEventListener('click', () => btn.nextElementSibling.classList.toggle('open'));
  });

  scrollToBottom();
}

function addErrorMessage(message) {
  const node = tplAgent.content.cloneNode(true);
  node.querySelector('.message__answer').textContent = message;
  thread.appendChild(node);
  scrollToBottom();
}

async function sendQuery(query, employeeIdOverride, confirmed = false) {
  const employeeId = (employeeIdOverride || signedInEmployeeId).toUpperCase();

  if (!EMPLOYEE_ID_PATTERN.test(employeeId)) {
    addErrorMessage('Employee ID must look like EMP-001 (EMP- followed by 3 digits).');
    return;
  }
  if (query.trim().length < 3) {
    addErrorMessage('Please enter a question with at least 3 characters.');
    return;
  }

  // Only show the user's own bubble on the first send -- a confirm-resend
  // is the same question again, and the confirm button already showed
  // what's being confirmed, so a second identical user bubble would just
  // be visual noise.
  if (!confirmed) {
    addUserMessage(query);
  }

  sendBtn.disabled = true;
  const thinkingEl = showThinking();

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, employee_id: employeeId, confirmed }),
    });

    thinkingEl?.remove();

    if (res.status === 422) {
      const detail = await res.json().catch(() => null);
      addErrorMessage(`That request wasn't valid: ${detail?.detail ? JSON.stringify(detail.detail) : 'please check the employee ID and question.'}`);
      return;
    }
    if (res.status === 503) {
      const detail = await res.json().catch(() => null);
      addErrorMessage(detail?.detail || 'The HR tool server is unavailable right now. Please try again shortly.');
      return;
    }
    if (!res.ok) {
      if (res.status === 401) { window.location.href = '/login'; return; }
      addErrorMessage(`Request failed (${res.status}). Check the server logs.`);
      return;
    }

    const data = await res.json();
    addAgentMessage(data, query, employeeId);
  } catch (err) {
    thinkingEl?.remove();
    addErrorMessage('Could not reach the server. Is it running?');
  } finally {
    sendBtn.disabled = false;
  }
}

composerEl.addEventListener('submit', (e) => {
  e.preventDefault();
  const query = queryInput.value.trim();
  if (!query) return;
  queryInput.value = '';
  sendQuery(query);
});

queryInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    composerEl.requestSubmit();
  }
});

document.querySelectorAll('.opener').forEach((btn) => {
  btn.addEventListener('click', () => sendQuery(btn.dataset.query));
});

async function pollHealth() {
  try {
    const res = await fetch('/health');
    const data = await res.json();
    healthDot.className = 'status-dot ' + (data.status === 'ok' ? 'ok' : 'degraded');
    const bits = [];
    if (!data.mcp_connected) bits.push('mcp offline');
    if (!data.chroma_loaded) bits.push('index offline');
    healthLabel.textContent = bits.length ? `${data.status} · ${bits.join(', ')}` : `${data.status} · ${data.doc_count ?? 0} docs`;
  } catch (err) {
    healthDot.className = 'status-dot degraded';
    healthLabel.textContent = 'unreachable';
  }
}

loadEmployeeOptions();
pollHealth();
setInterval(pollHealth, 15000);
