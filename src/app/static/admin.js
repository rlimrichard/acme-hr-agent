// ---- Theme (shared with app.js) ----
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

// ---- Admin log viewer ----
const dateSelect = document.getElementById('date-select');
const entriesList = document.getElementById('entries-list');
const entryCount = document.getElementById('entry-count');

const ANSWER_PREVIEW_CHARS = 280;

function formatTime(isoString) {
  try {
    return new Date(isoString).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch {
    return isoString;
  }
}

function setStatus(msg) {
  entriesList.textContent = '';
  const el = document.createElement('div');
  el.className = 'admin-empty';
  el.textContent = msg;
  entriesList.appendChild(el);
}

function badge(cls, text) {
  const el = document.createElement('span');
  el.className = `log-card__badge ${cls}`;
  el.textContent = text;
  return el;
}

function buildCard(entry) {
  const card = document.createElement('div');
  card.className = 'log-card';

  // Header row: time · employee · badges
  const header = document.createElement('div');
  header.className = 'log-card__header';

  const timeEl = document.createElement('span');
  timeEl.className = 'log-card__time';
  timeEl.textContent = formatTime(entry.timestamp);
  header.appendChild(timeEl);

  const empEl = document.createElement('span');
  empEl.className = 'log-card__emp';
  empEl.textContent = entry.employee_id;
  header.appendChild(empEl);

  if (entry.escalated) {
    header.appendChild(badge('log-card__badge--escalated', 'escalated'));
  }
  if (entry.tool_steps) {
    const steps = Number(entry.tool_steps);
    header.appendChild(badge('log-card__badge--tools', `${steps} tool step${steps !== 1 ? 's' : ''}`));
  }

  card.appendChild(header);

  // Question
  const queryEl = document.createElement('div');
  queryEl.className = 'log-card__query';
  queryEl.textContent = entry.query;
  card.appendChild(queryEl);

  // Answer (truncated with expand toggle)
  const answer = String(entry.answer || '');
  const isLong = answer.length > ANSWER_PREVIEW_CHARS;
  const preview = isLong ? answer.slice(0, ANSWER_PREVIEW_CHARS).trimEnd() + '…' : answer;

  const answerEl = document.createElement('div');
  answerEl.className = 'log-card__answer';
  answerEl.textContent = preview;
  card.appendChild(answerEl);

  if (isLong) {
    const btn = document.createElement('button');
    btn.className = 'log-card__expand';
    btn.type = 'button';
    btn.textContent = 'Show full answer';
    let expanded = false;
    btn.addEventListener('click', () => {
      expanded = !expanded;
      answerEl.textContent = expanded ? answer : preview;
      btn.textContent = expanded ? 'Collapse' : 'Show full answer';
    });
    card.appendChild(btn);
  }

  return card;
}

function renderEntries(entries) {
  entriesList.textContent = '';

  if (!entries.length) {
    setStatus('No entries for this date.');
    entryCount.textContent = '';
    return;
  }

  entryCount.textContent = `${entries.length} conversation${entries.length !== 1 ? 's' : ''}`;
  entries.forEach((e) => entriesList.appendChild(buildCard(e)));
}

async function loadEntries(date) {
  setStatus('Loading…');
  entryCount.textContent = '';
  try {
    const res = await fetch(`/admin/logs/${encodeURIComponent(date)}`);
    const data = await res.json();
    renderEntries(data.entries || []);
  } catch {
    setStatus('Failed to load entries.');
  }
}

async function init() {
  try {
    const res = await fetch('/admin/logs');
    const data = await res.json();
    const dates = data.dates || [];

    dateSelect.textContent = '';

    if (!dates.length) {
      const opt = document.createElement('option');
      opt.textContent = 'No logs yet';
      dateSelect.appendChild(opt);
      setStatus('No conversations have been logged yet.');
      return;
    }

    dates.forEach((d) => {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      dateSelect.appendChild(opt);
    });

    dateSelect.addEventListener('change', () => {
      if (dateSelect.value) loadEntries(dateSelect.value);
    });

    loadEntries(dates[0]);
  } catch {
    setStatus('Could not reach the server.');
  }
}

init();
