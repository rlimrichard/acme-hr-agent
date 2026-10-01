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

// ---- Auth helper ----
// All /admin/* API calls are session-protected server-side. If the session
// has expired (8h) or was never established, the server returns 401 --
// bounce to the login page rather than rendering an empty/broken panel.
async function fetchJSON(url) {
  const res = await fetch(url);
  if (res.status === 401) {
    window.location.href = '/admin/login';
    throw new Error('unauthenticated');
  }
  return res.json();
}

// ---- Tabs ----
const tabConversations = document.getElementById('tab-conversations');
const tabPrompts       = document.getElementById('tab-prompts');
const tabTickets       = document.getElementById('tab-tickets');
const tabHrDatabase    = document.getElementById('tab-hr-database');
const tabDatabase      = document.getElementById('tab-database');
const panelConversations = document.getElementById('panel-conversations');
const panelPrompts       = document.getElementById('panel-prompts');
const panelTickets       = document.getElementById('panel-tickets');
const panelHrDatabase    = document.getElementById('panel-hr-database');
const panelDatabase      = document.getElementById('panel-database');

function switchTab(tab) {
  const tabs = {
    conversations: [tabConversations, panelConversations],
    prompts: [tabPrompts, panelPrompts],
    tickets: [tabTickets, panelTickets],
    hrDatabase: [tabHrDatabase, panelHrDatabase],
    database: [tabDatabase, panelDatabase],
  };
  Object.entries(tabs).forEach(([name, [button, panel]]) => {
    const selected = name === tab;
    button.classList.toggle('admin-tab--active', selected);
    button.setAttribute('aria-selected', String(selected));
    panel.style.display = selected ? 'flex' : 'none';
  });
}

tabConversations.addEventListener('click', () => switchTab('conversations'));
tabPrompts.addEventListener('click', () => {
  switchTab('prompts');
  if (!promptsLoaded) initPrompts();
});
tabTickets.addEventListener('click', () => {
  switchTab('tickets');
  if (!ticketsLoaded) loadTickets();
});
tabHrDatabase.addEventListener('click', () => {
  switchTab('hrDatabase');
  if (!hrDatabaseLoaded) loadHrDatabase();
});
tabDatabase.addEventListener('click', () => {
  switchTab('database');
  if (!databaseLoaded) initDatabase();
});

// ---- Conversations ----
const dateSelect  = document.getElementById('date-select');
const entriesList = document.getElementById('entries-list');
const entryCount  = document.getElementById('entry-count');

const ANSWER_PREVIEW = 280;

function formatTime(iso) {
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch { return iso; }
}

function formatDateTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

function setStatus(container, msg) {
  container.textContent = '';
  const el = document.createElement('div');
  el.className = 'admin-empty';
  el.textContent = msg;
  container.appendChild(el);
}

function makeBadge(cls, text) {
  const el = document.createElement('span');
  el.className = `log-card__badge ${cls}`;
  el.textContent = text;
  return el;
}

function appendPromptPreview(container, title, prompt) {
  if (!prompt) return;
  const details = document.createElement('details');
  details.className = 'log-card__reasoning';
  const summary = document.createElement('summary');
  summary.textContent = title;
  details.appendChild(summary);
  const pre = document.createElement('pre');
  pre.className = 'audit-preview';
  pre.textContent = prompt;
  details.appendChild(pre);
  container.appendChild(details);
}

function appendToolAudit(container, trace) {
  if (!Array.isArray(trace) || !trace.length) return;
  const details = document.createElement('details');
  details.className = 'log-card__reasoning';
  const summary = document.createElement('summary');
  summary.textContent = `MCP/tool calls (${trace.length})`;
  details.appendChild(summary);
  trace.forEach((step) => {
    const pre = document.createElement('pre');
    pre.className = 'audit-preview';
    pre.textContent = `${step.step || '?'} · ${step.tool || 'tool'}\n` +
      `args: ${JSON.stringify(step.args ?? step.input ?? {}, null, 2)}\n` +
      `result: ${JSON.stringify(step.result ?? step.output ?? {}, null, 2)}`;
    details.appendChild(pre);
  });
  container.appendChild(details);
}

function buildConversationCard(entry) {
  const card = document.createElement('div');
  card.className = 'log-card';

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

  if (entry.escalated) header.appendChild(makeBadge('log-card__badge--escalated', 'escalated'));
  if (entry.tool_steps) {
    const n = Number(entry.tool_steps);
    header.appendChild(makeBadge('log-card__badge--tools', `${n} tool step${n !== 1 ? 's' : ''}`));
  }
  card.appendChild(header);

  const queryEl = document.createElement('div');
  queryEl.className = 'log-card__query';
  queryEl.textContent = entry.query;
  card.appendChild(queryEl);

  const answer = String(entry.answer || '');
  const isLong = answer.length > ANSWER_PREVIEW;
  const preview = isLong ? answer.slice(0, ANSWER_PREVIEW).trimEnd() + '…' : answer;

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

  const reasoning = entry.llm_reasoning || {};
  const routing = reasoning.routing;
  if (routing) {
    const details = document.createElement('details');
    details.className = 'log-card__reasoning';
    const summary = document.createElement('summary');
    summary.textContent = 'LLM reasoning summary (sanitized)';
    details.appendChild(summary);

    const content = document.createElement('div');
    content.className = 'log-card__reasoning-content';
    const answer = reasoning.answer_generation || {};
    content.textContent = `Routing prompt: ${routing.prompt_type || 'not recorded'}\n` +
      `Model: ${routing.model || 'not recorded'}\n` +
      `Route: ${routing.selected_workflow || 'not recorded'} (${routing.route_source || 'not recorded'})\n` +
      `Routing instruction: ${routing.instruction || 'not recorded'}\n` +
      `Answer prompt: ${answer.prompt_type || 'not recorded'}\n` +
      `Answer instruction: ${answer.instruction || 'embedded in prompt preview'}\n` +
      'Prompt previews and MCP calls are available below.';
    details.appendChild(content);
    appendPromptPreview(details, 'Routing prompt preview', routing.prompt_preview);
    appendPromptPreview(details, 'Answer prompt preview', answer.prompt_preview);
    appendToolAudit(details, entry.tool_trace);
    card.appendChild(details);
  }

  return card;
}

function renderConversations(entries) {
  entriesList.textContent = '';
  if (!entries.length) { setStatus(entriesList, 'No entries for this date.'); entryCount.textContent = ''; return; }
  entryCount.textContent = `${entries.length} conversation${entries.length !== 1 ? 's' : ''}`;
  entries.forEach((e) => entriesList.appendChild(buildConversationCard(e)));
}

async function loadConversations(date) {
  setStatus(entriesList, 'Loading…');
  entryCount.textContent = '';
  try {
    const data = await fetchJSON(`/admin/logs/${encodeURIComponent(date)}`);
    renderConversations(data.entries || []);
  } catch { setStatus(entriesList, 'Failed to load entries.'); }
}

async function initConversations() {
  try {
    const data = await fetchJSON('/admin/logs');
    const dates = data.dates || [];
    dateSelect.textContent = '';
    if (!dates.length) {
      const opt = document.createElement('option');
      opt.textContent = 'No logs yet';
      dateSelect.appendChild(opt);
      setStatus(entriesList, 'No conversations have been logged yet.');
      return;
    }
    dates.forEach((d) => {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      dateSelect.appendChild(opt);
    });
    dateSelect.addEventListener('change', () => { if (dateSelect.value) loadConversations(dateSelect.value); });
    loadConversations(dates[0]);
  } catch { setStatus(entriesList, 'Could not reach the server.'); }
}

// ---- Prompt audit (sanitized admin metadata) ----
const promptDateSelect = document.getElementById('prompt-date-select');
const promptList       = document.getElementById('prompt-list');
const promptCount      = document.getElementById('prompt-count');
let promptsLoaded = false;

function buildPromptCard(entry) {
  const card = document.createElement('div');
  card.className = 'log-card';
  const routing = entry.llm_reasoning?.routing;
  if (!routing) {
    card.textContent = `${formatTime(entry.timestamp)} · No prompt audit metadata was recorded for this conversation.`;
    return card;
  }
  const query = document.createElement('div');
  query.className = 'log-card__query';
  query.textContent = entry.query;
  card.appendChild(query);
  const detail = document.createElement('div');
  detail.className = 'log-card__reasoning-content';
  const answer = entry.llm_reasoning.answer_generation || {};
  detail.textContent = `Time: ${formatTime(entry.timestamp)}\n` +
    `Routing instruction: ${routing.instruction || 'not recorded'}\n` +
    `Model: ${routing.model || 'not recorded'}\n` +
    `Selected route: ${routing.selected_workflow || 'not recorded'} (${routing.route_source || 'not recorded'})\n` +
    `Routing response format: ${routing.response_format || 'not recorded'}\n` +
    `Answer prompt: ${answer.prompt_type || 'not recorded'}\n` +
    'Prompt previews and MCP calls are retained only in this authenticated admin view.';
  card.appendChild(detail);
  appendPromptPreview(card, 'Routing prompt preview', routing.prompt_preview);
  appendPromptPreview(card, 'Answer prompt preview', answer.prompt_preview);
  appendToolAudit(card, entry.tool_trace);
  return card;
}

async function loadPrompts(date) {
  setStatus(promptList, 'Loading…');
  try {
    const data = await fetchJSON(`/admin/logs/${encodeURIComponent(date)}`);
    const entries = (data.entries || []).filter((entry) => entry.llm_reasoning);
    promptList.textContent = '';
    promptCount.textContent = `${entries.length} audited conversation${entries.length !== 1 ? 's' : ''}`;
    if (!entries.length) { setStatus(promptList, 'No prompt audit metadata for this date.'); return; }
    entries.forEach((entry) => promptList.appendChild(buildPromptCard(entry)));
  } catch { setStatus(promptList, 'Failed to load prompt audit.'); }
}

async function initPrompts() {
  promptsLoaded = true;
  try {
    const data = await fetchJSON('/admin/logs');
    const dates = data.dates || [];
    promptDateSelect.textContent = '';
    if (!dates.length) { setStatus(promptList, 'No conversations have been logged yet.'); return; }
    dates.forEach((date) => {
      const option = document.createElement('option');
      option.value = date;
      option.textContent = date;
      promptDateSelect.appendChild(option);
    });
    promptDateSelect.addEventListener('change', () => loadPrompts(promptDateSelect.value));
    loadPrompts(dates[0]);
  } catch { setStatus(promptList, 'Could not reach the server.'); }
}

// ---- Read-only HR employee directory ----
const hrDatabaseList  = document.getElementById('hr-database-list');
const hrDatabaseCount = document.getElementById('hr-database-count');
let hrDatabaseLoaded = false;

function renderHrDatabase(data) {
  hrDatabaseList.textContent = '';
  const employees = data.employees || [];
  hrDatabaseCount.textContent = `${employees.length} employee${employees.length !== 1 ? 's' : ''} · read-only`;
  if (!employees.length) { setStatus(hrDatabaseList, 'No employee records are available.'); return; }
  const table = document.createElement('table');
  table.className = 'database-table';
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  data.columns.forEach((column) => { const cell = document.createElement('th'); cell.textContent = column.replace(/_/g, ' '); headRow.appendChild(cell); });
  head.appendChild(headRow); table.appendChild(head);
  const body = document.createElement('tbody');
  employees.forEach((employee) => {
    const row = document.createElement('tr');
    data.columns.forEach((column) => { const cell = document.createElement('td'); cell.textContent = String(employee[column] ?? ''); row.appendChild(cell); });
    body.appendChild(row);
  });
  table.appendChild(body); hrDatabaseList.appendChild(table);
}

async function loadHrDatabase() {
  hrDatabaseLoaded = true;
  setStatus(hrDatabaseList, 'Loading HR database…');
  try { renderHrDatabase(await fetchJSON('/admin/hr-database')); }
  catch { setStatus(hrDatabaseList, 'Failed to load the HR database.'); }
}

// ---- Read-only policy database browser ----
const databaseTableSelect = document.getElementById('database-table-select');
const databaseList        = document.getElementById('database-list');
const databaseCount       = document.getElementById('database-count');
let databaseLoaded = false;

function renderDatabaseRows(data) {
  databaseList.textContent = '';
  databaseCount.textContent = `${data.rows.length} row preview · read-only`;
  if (!data.rows.length) { setStatus(databaseList, 'This table has no rows.'); return; }
  const table = document.createElement('table');
  table.className = 'database-table';
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  data.columns.forEach((column) => { const cell = document.createElement('th'); cell.textContent = column; headRow.appendChild(cell); });
  head.appendChild(headRow); table.appendChild(head);
  const body = document.createElement('tbody');
  data.rows.forEach((row) => {
    const tableRow = document.createElement('tr');
    data.columns.forEach((column) => { const cell = document.createElement('td'); cell.textContent = String(row[column] ?? ''); tableRow.appendChild(cell); });
    body.appendChild(tableRow);
  });
  table.appendChild(body); databaseList.appendChild(table);
}

async function loadDatabaseTable(tableName) {
  setStatus(databaseList, 'Loading table…');
  try { renderDatabaseRows(await fetchJSON(`/admin/database/${encodeURIComponent(tableName)}`)); }
  catch { setStatus(databaseList, 'Failed to load database table.'); }
}

async function initDatabase() {
  databaseLoaded = true;
  try {
    const data = await fetchJSON('/admin/database');
    databaseTableSelect.textContent = '';
    if (!(data.tables || []).length) { setStatus(databaseList, 'No database tables are available.'); return; }
    data.tables.forEach((table) => {
      const option = document.createElement('option');
      option.value = table.name;
      option.textContent = `${table.name} (${table.row_count} rows)`;
      databaseTableSelect.appendChild(option);
    });
    databaseTableSelect.addEventListener('change', () => loadDatabaseTable(databaseTableSelect.value));
    loadDatabaseTable(data.tables[0].name);
  } catch { setStatus(databaseList, 'Could not load the policy database.'); }
}

// ---- Tickets ----
const ticketsList = document.getElementById('tickets-list');
const ticketCount = document.getElementById('ticket-count');
let ticketsLoaded = false;

const TYPE_LABELS = {
  pto_request:           'PTO request',
  benefits_change:       'Benefits change',
  policy_question:       'Policy question',
  accommodation_request: 'Accommodation',
  general_inquiry:       'General inquiry',
};

function buildTicketCard(ticket) {
  const card = document.createElement('div');
  card.className = 'ticket-card';

  // Header: ID · type badge · timestamp (right)
  const header = document.createElement('div');
  header.className = 'ticket-card__header';

  const idEl = document.createElement('span');
  idEl.className = 'ticket-card__id';
  idEl.textContent = ticket.ticket_id;
  header.appendChild(idEl);

  const empEl = document.createElement('span');
  empEl.className = 'log-card__emp';
  empEl.textContent = ticket.employee_id;
  header.appendChild(empEl);

  const typeEl = document.createElement('span');
  typeEl.className = 'ticket-card__type';
  typeEl.textContent = TYPE_LABELS[ticket.ticket_type] || ticket.ticket_type.replace(/_/g, ' ');
  header.appendChild(typeEl);

  const timeEl = document.createElement('span');
  timeEl.className = 'ticket-card__time';
  timeEl.textContent = formatDateTime(ticket.created_at);
  header.appendChild(timeEl);

  card.appendChild(header);

  // Subject
  const subjectEl = document.createElement('div');
  subjectEl.className = 'ticket-card__subject';
  subjectEl.textContent = ticket.subject;
  card.appendChild(subjectEl);

  // Meta: assigned to, dates
  const meta = document.createElement('div');
  meta.className = 'ticket-card__meta';

  function metaItem(label, value) {
    if (!value) return;
    const s = document.createElement('span');
    const strong = document.createElement('strong');
    strong.textContent = label + ' ';
    s.appendChild(strong);
    s.appendChild(document.createTextNode(value));
    meta.appendChild(s);
  }

  metaItem('Assigned to', ticket.assigned_to);
  if (ticket.requested_start_date) metaItem('From', ticket.requested_start_date);
  if (ticket.requested_end_date)   metaItem('To',   ticket.requested_end_date);
  metaItem('Status', ticket.status);

  card.appendChild(meta);

  // Description
  if (ticket.description) {
    const descEl = document.createElement('div');
    descEl.className = 'ticket-card__description';
    descEl.textContent = ticket.description;
    card.appendChild(descEl);
  }

  return card;
}

async function loadTickets() {
  ticketsLoaded = true;
  setStatus(ticketsList, 'Loading…');
  ticketCount.textContent = '';
  try {
    const data = await fetchJSON('/admin/tickets');
    const tickets = data.tickets || [];
    ticketsList.textContent = '';
    if (!tickets.length) { setStatus(ticketsList, 'No tickets have been created yet.'); return; }
    ticketCount.textContent = `${tickets.length} ticket${tickets.length !== 1 ? 's' : ''}`;
    tickets.forEach((t) => ticketsList.appendChild(buildTicketCard(t)));
  } catch { setStatus(ticketsList, 'Failed to load tickets.'); }
}

// ---- Init ----
initConversations();
