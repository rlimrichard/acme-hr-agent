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

// ---- Modal ----
const modal         = document.getElementById('doc-modal');
const modalBackdrop = document.getElementById('modal-backdrop');
const modalTitle    = document.getElementById('modal-title');
const modalBody     = document.getElementById('modal-body');
const modalClose    = document.getElementById('modal-close');
const modalDownload = document.getElementById('modal-download');

async function openPreview(doc) {
  modalTitle.textContent = doc.title;
  modalDownload.href     = doc.url;
  modalDownload.download = doc.filename;
  modalBody.replaceChildren();

  // Show the modal before loading content so the element has dimensions
  modal.hidden = false;
  document.body.style.overflow = 'hidden';
  modalClose.focus();

  if (doc.format === 'pdf') {
    // <embed> is more reliable than <iframe> for PDF rendering across browsers
    const embed = document.createElement('embed');
    embed.className = 'modal-frame';
    embed.src       = doc.url;
    embed.type      = 'application/pdf';
    modalBody.appendChild(embed);

  } else if (doc.format === 'html') {
    // Fetch the HTML and use srcdoc — avoids navigation restrictions on src
    const loading = document.createElement('div');
    loading.className   = 'modal-loading';
    loading.textContent = 'Loading…';
    modalBody.appendChild(loading);
    try {
      const html = await fetch(doc.url).then(r => r.text());
      const iframe = document.createElement('iframe');
      iframe.className = 'modal-frame';
      iframe.title     = doc.title;
      iframe.srcdoc    = html;
      modalBody.replaceChildren(iframe);
    } catch {
      loading.textContent = 'Could not load document.';
    }

  } else {
    // md / txt — plain text in a <pre>
    const loading = document.createElement('div');
    loading.className   = 'modal-loading';
    loading.textContent = 'Loading…';
    modalBody.appendChild(loading);
    try {
      const text = await fetch(doc.url).then(r => r.text());
      const pre = document.createElement('pre');
      pre.className   = 'modal-text';
      pre.textContent = text;
      modalBody.replaceChildren(pre);
    } catch {
      loading.textContent = 'Could not load document.';
    }
  }
}

function closePreview() {
  modal.hidden = true;
  document.body.style.overflow = '';
  modalBody.replaceChildren();
}

modalClose.addEventListener('click', closePreview);
modalBackdrop.addEventListener('click', closePreview);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !modal.hidden) closePreview();
});

// ---- Documents ----
const docsList   = document.getElementById('docs-list');
const docsCount  = document.getElementById('docs-count');
const docsSearch = document.getElementById('docs-search');

let allDocs = [];

const FORMAT_LABEL = { pdf: 'PDF', html: 'HTML', md: 'MD', txt: 'TXT' };

function buildDocCard(d) {
  const card = document.createElement('div');
  card.className = 'doc-card';

  const badge = document.createElement('span');
  badge.className = `doc-format-badge doc-format-badge--${d.format}`;
  badge.textContent = FORMAT_LABEL[d.format] || d.format.toUpperCase();

  const info = document.createElement('div');
  info.className = 'doc-info';

  const title = document.createElement('div');
  title.className = 'doc-title';
  title.textContent = d.title;

  const meta = document.createElement('div');
  meta.className = 'doc-meta';

  const docId = document.createElement('span');
  docId.className = 'doc-id';
  docId.textContent = d.doc_id;

  const size = document.createElement('span');
  size.textContent = `${d.size_kb} KB`;

  meta.append(docId, size);
  info.append(title, meta);

  const actions = document.createElement('div');
  actions.className = 'doc-actions';

  const viewBtn = document.createElement('button');
  viewBtn.className = 'doc-btn doc-btn--primary';
  viewBtn.type      = 'button';
  viewBtn.textContent = 'View';
  viewBtn.addEventListener('click', () => openPreview(d));

  const dlBtn = document.createElement('a');
  dlBtn.className = 'doc-btn';
  dlBtn.href      = d.url;
  dlBtn.download  = d.filename;
  dlBtn.textContent = 'Download';

  actions.append(viewBtn, dlBtn);
  card.append(badge, info, actions);
  return card;
}

function renderDocs(docs) {
  docsCount.textContent = `${docs.length} document${docs.length !== 1 ? 's' : ''}`;
  docsList.replaceChildren();
  if (!docs.length) {
    const msg = document.createElement('div');
    msg.className   = 'docs-loading';
    msg.textContent = 'No documents match your search.';
    docsList.appendChild(msg);
    return;
  }
  const fragment = document.createDocumentFragment();
  docs.forEach(d => fragment.appendChild(buildDocCard(d)));
  docsList.appendChild(fragment);
}

async function loadDocuments() {
  try {
    const res  = await fetch('/documents');
    const data = await res.json();
    allDocs = data.documents || [];
    renderDocs(allDocs);
  } catch {
    const msg = document.createElement('div');
    msg.className   = 'docs-loading';
    msg.textContent = 'Could not load documents. Is the server running?';
    docsList.replaceChildren(msg);
  }
}

docsSearch.addEventListener('input', () => {
  const q = docsSearch.value.trim().toLowerCase();
  renderDocs(q ? allDocs.filter(d =>
    d.title.toLowerCase().includes(q) ||
    d.doc_id.toLowerCase().includes(q) ||
    d.format.toLowerCase().includes(q)
  ) : allDocs);
});

loadDocuments();
