import { FilePreviewPanel } from './pdf-preview.js';
import { ensureOption, initCatalogUi } from './catalog-ui.js';

// ------------------------------------------------------------------ setup
// The page is served by the backend itself, so API calls are same-origin (cookies just work).
const API_BASE = (window.CFG_API_BASE || '').replace(/\/+$/, '');
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
const $ = (id) => document.getElementById(id);

let state = { course: {}, slots: [], files: [], summary: {}, last_output: null };
let pending = [];          // uploads currently being processed: {key, name}
let busy = false;          // blocks drags during a drop request
const preview = new FilePreviewPanel();
const rows = {};           // letter -> {tr, desc, file, view, select, upload, handle}

// ---------------------------------------------------------------- helpers
function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
  }
  kids.flat().forEach((c) => c != null && e.append(c));
  return e;
}

function toast(msg, kind = 'info', ms = 4500) {
  const t = el('div', { class: `toast ${kind}`, text: msg });
  $('toasts').append(t);
  setTimeout(() => t.remove(), kind === 'error' ? ms + 3000 : ms);
}

function setLoading(on, text = 'Working…') {
  $('loading').hidden = !on;
  $('loading-text').textContent = text;
}

function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code; }
}

async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(API_BASE + path, { credentials: 'include', ...opts });
  } catch {
    throw new ApiError('Cannot reach the backend. Is it running on http://127.0.0.1:8000 ?', 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (res.status === 401 && !opts.noAuthRedirect) showLogin();
  if (!res.ok) throw new ApiError(data?.detail || `Request failed (${res.status}).`, res.status, data?.code);
  return data;
}

const postJson = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

function confirmDialog(text, { title = 'Confirm', ok = 'Replace' } = {}) {
  return new Promise((resolve) => {
    $('confirm-title').textContent = title;
    $('confirm-text').textContent = text;
    $('confirm-ok').textContent = ok;
    $('confirm-modal').hidden = false;
    const done = (v) => {
      $('confirm-modal').hidden = true;
      $('confirm-ok').onclick = $('confirm-cancel').onclick = null;
      resolve(v);
    };
    $('confirm-ok').onclick = () => done(true);
    $('confirm-cancel').onclick = () => done(false);
    $('confirm-ok').focus();
  });
}

// ------------------------------------------------------------------ state
function applySnapshot(snap) {
  state = snap;
  render();
}

async function refresh() {
  applySnapshot(await api('/api/slots'));
}

const fileById = (id) => state.files.find((f) => f.id === id);
const slotOf = (letter) => state.slots[LETTERS.indexOf(letter)];

// ----------------------------------------------------------------- render
function buildRows() {
  const body = $('az-body');
  for (const letter of LETTERS) {
    const desc = el('input', { type: 'text', placeholder: 'Description', maxlength: 300, 'aria-label': `Description for ${letter}` });
    const file = el('td', { class: 'file-cell' });
    const view = el('button', { class: 'btn btn-sm', text: 'View File', onclick: () => viewSlot(letter) });
    const select = el('button', { class: 'btn btn-sm', text: 'Select File', onclick: () => selectFlow(letter) });
    const upload = el('button', { class: 'btn btn-sm', text: 'Upload File', onclick: () => slotUploadPick(letter) });
    const handle = el('span', { class: 'handle', title: 'Drag to move/swap this section’s content', text: '⋮⋮' });
    handle.addEventListener('pointerdown', (e) => startDrag(e, letter));
    desc.addEventListener('input', () => onDescInput(letter, desc.value));
    desc.addEventListener('blur', () => flushDesc(letter));
    desc.addEventListener('keydown', (e) => { if (e.key === 'Enter') desc.blur(); });
    const tr = el('tr', { 'data-letter': letter },
      el('td', { class: 'letter', text: letter }),
      el('td', { class: 'desc' }, desc),
      file,
      el('td', { class: 'actions-cell' }, select, view, upload, handle));
    body.append(tr);
    rows[letter] = { tr, desc, file, view, select, upload, handle };
  }
}

function render() {
  // Course fields
  document.querySelectorAll('[data-course]').forEach((inp) => {
    if (document.activeElement !== inp) setFieldValue(inp, state.course[inp.dataset.course] ?? '');
  });
  // Summary
  $('sum-files').textContent = state.summary.total_files ?? 0;
  $('sum-assigned').textContent = state.summary.assigned_files ?? 0;
  $('sum-empty').textContent = state.summary.empty_sections ?? 26;
  // A-Z rows (the 26 rows are fixed; only their content is updated)
  for (const s of state.slots) {
    const r = rows[s.letter];
    if (document.activeElement !== r.desc) r.desc.value = s.description;
    r.file.replaceChildren(s.file
      ? el('span', {}, s.file.original_name, el('span', { class: 'ftype', text: s.file.file_type }))
      : el('span', { class: 'empty', text: 'Empty' }));
    r.view.disabled = !s.file;
  }
  renderLibrary();
  renderResult();
}

function renderLibrary() {
  const body = $('lib-body');
  body.replaceChildren();
  for (const f of state.files) {
    const sel = el('select', { 'aria-label': `Assign ${f.original_name}` },
      el('option', { value: '', text: 'Assign to…' }),
      ...LETTERS.map((l) => el('option', { value: l, text: l + (f.assigned_to === l ? ' (current)' : '') })));
    sel.addEventListener('change', async () => {
      const l = sel.value; sel.value = '';
      if (l) await assignFlow(l, f.id);
    });
    body.append(el('tr', {},
      el('td', { text: f.original_name }),
      el('td', { text: f.file_type }),
      el('td', { text: fmtSize(f.size) }),
      el('td', {}, el('span', { class: f.status === 'ready' ? 'pill' : 'pill warn', text: f.status === 'ready' ? 'Ready' : 'Failed' })),
      el('td', {}, f.assigned_to ? el('span', { class: 'assigned-tag', text: `Assigned to ${f.assigned_to}` }) : 'Unassigned'),
      el('td', {}, el('button', { class: 'btn btn-sm', text: 'View', onclick: () => previewFile(f) }), ' ', sel)));
  }
  for (const p of pending) {
    body.append(el('tr', {}, el('td', { text: p.name }), el('td', { text: '—' }), el('td', { text: '—' }),
      el('td', {}, el('span', { class: 'pill busy', text: 'Converting…' })), el('td', { text: '—' }), el('td')));
  }
  $('lib-empty').hidden = state.files.length > 0 || pending.length > 0;
}

function renderResult() {
  const o = state.last_output;
  $('result-card').hidden = !o;
  if (!o) return;
  $('res-name').textContent = o.filename;
  $('res-docs').textContent = o.total_documents;
  $('res-pages').textContent = o.total_pages;
  $('btn-download-final').href = `${API_BASE}/api/generate/download`;
}

// ------------------------------------------------- course + descriptions
const timers = {};          // key -> timeout id
const inflight = new Set(); // promises of saves in progress

function debounce(key, fn, ms = 600) {
  clearTimeout(timers[key]);
  timers[key] = setTimeout(() => { delete timers[key]; track(fn()); }, ms);
}
function flushKey(key, fn) {
  if (timers[key] === undefined) return;
  clearTimeout(timers[key]); delete timers[key]; track(fn());
}
function track(p) { inflight.add(p); p.finally(() => inflight.delete(p)); return p; }
async function flushAll() {
  for (const key of Object.keys(timers)) {
    if (key === 'course') flushKey(key, saveCourse);
    else flushKey(key, () => saveDesc(key));
  }
  await Promise.allSettled([...inflight]);
}

function onDescInput(letter, value) {
  slotOf(letter).description = value;
  debounce(letter, () => saveDesc(letter));
}
function flushDesc(letter) { flushKey(letter, () => saveDesc(letter)); }
async function saveDesc(letter) {
  try {
    await api(`/api/slots/${letter}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: slotOf(letter).description }),
    });
  } catch (e) { toast(`Could not save description for ${letter}: ${e.message}`, 'error'); }
}

async function saveCourse() {
  try {
    await api('/api/project', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.course),
    });
  } catch (e) { toast(`Could not save course details: ${e.message}`, 'error'); }
}
/** Set a form field; a <select> gets an extra option if the saved value is not in its list. */
function setFieldValue(inp, value) {
  if (inp.tagName === 'SELECT') ensureOption(inp, value);
  inp.value = value;
}

/** Programmatically change one course-detail field and save it like a user edit. */
function setCourseField(name, value) {
  const inp = document.querySelector(`[data-course="${name}"]`);
  state.course[name] = value;
  if (inp) setFieldValue(inp, value);
  debounce('course', saveCourse);
}

function initCourseInputs() {
  document.querySelectorAll('[data-course]').forEach((inp) => {
    inp.addEventListener('input', () => { state.course[inp.dataset.course] = inp.value; debounce('course', saveCourse); });
    inp.addEventListener('blur', () => flushKey('course', saveCourse));
  });
}

// ----------------------------------------------------------------- upload
const ACCEPT = /\.(pdf|docx?|xlsx?|pptx?|txt)$/i;

async function uploadOne(file) {
  const fd = new FormData();
  fd.append('files', file);
  const res = await api('/api/files/upload', { method: 'POST', body: fd });
  return res.results[0];
}

async function uploadMany(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  $('btn-upload').disabled = true;
  let ok = 0;
  for (const f of files) {
    const p = { name: f.name };
    pending.push(p); renderLibrary();
    try {
      if (!ACCEPT.test(f.name)) throw new Error('Unsupported file format.');
      const r = await uploadOne(f);
      if (r.ok) ok++; else toast(`${f.name}: ${r.error}`, 'error');
    } catch (e) {
      toast(`${f.name}: ${e.message}`, 'error');
    } finally {
      pending = pending.filter((x) => x !== p);
      try { await refresh(); } catch { renderLibrary(); }
    }
  }
  $('btn-upload').disabled = false;
  if (ok) toast(`${ok} file${ok > 1 ? 's' : ''} uploaded.`, 'success');
}

let slotUploadTarget = null;
function slotUploadPick(letter) {
  slotUploadTarget = letter;
  $('input-slot').value = '';
  $('input-slot').click();
}
async function slotUploadChosen() {
  const file = $('input-slot').files[0];
  const letter = slotUploadTarget;
  if (!file || !letter) return;
  const cur = slotOf(letter).file;
  if (cur && !(await confirmDialog(`Section ${letter} already contains ${cur.original_name}.\n\nDo you want to replace it?`, { title: 'Replace file?' }))) return;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('replace', cur ? 'true' : 'false');
  setLoading(true, `Uploading ${file.name}…`);
  try {
    applySnapshot(await api(`/api/slots/${letter}/upload`, { method: 'POST', body: fd }));
    toast(`${file.name} assigned to section ${letter}.`, 'success');
  } catch (e) {
    toast(e.message, 'error');
  } finally { setLoading(false); }
}

// ------------------------------------------------------ select / assign
async function assignFlow(letter, fileId) {
  const f = fileById(fileId), slot = slotOf(letter);
  if (!f) return;
  if (slot.file_id === fileId) { toast(`${f.original_name} is already in section ${letter}.`); return; }
  const parts = [];
  if (f.assigned_to) parts.push(`This file is already assigned to section ${f.assigned_to}.\nDo you want to move it to section ${letter}?`);
  if (slot.file) parts.push(`Section ${letter} already contains ${slot.file.original_name}.\nDo you want to replace it?`);
  let force = false;
  if (parts.length) {
    const title = f.assigned_to ? 'Move file?' : 'Replace file?';
    if (!(await confirmDialog(parts.join('\n\n'), { title, ok: f.assigned_to ? 'Move' : 'Replace' }))) return;
    force = true;
  }
  try {
    applySnapshot(await postJson(`/api/slots/${letter}/assign`, { file_id: fileId, force }));
    toast(`${f.original_name} assigned to section ${letter}.`, 'success');
  } catch (e) {
    if (e.status === 409 && !force && await confirmDialog(e.message)) {
      try {
        applySnapshot(await postJson(`/api/slots/${letter}/assign`, { file_id: fileId, force: true }));
        toast(`${f.original_name} assigned to section ${letter}.`, 'success');
      } catch (e2) { toast(e2.message, 'error'); }
    } else if (e.status !== 409) toast(e.message, 'error');
  }
}

function selectFlow(letter) {
  return new Promise((resolve) => {
    let chosen = null;
    const list = $('select-list'), search = $('select-search'), ok = $('select-confirm');
    $('select-title').textContent = `SELECT FILE FOR SECTION ${letter}`;
    search.value = ''; ok.disabled = true;
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const items = state.files.filter((f) => f.original_name.toLowerCase().includes(q));
      list.replaceChildren(...(items.length ? items.map((f) => el('li', {
        class: f.id === chosen ? 'selected' : '', onclick: () => { chosen = f.id; ok.disabled = false; draw(); },
        ondblclick: () => finish(true),
      }, el('span', { text: f.original_name }),
        el('span', { class: 'meta', text: `${f.file_type} · ${fmtSize(f.size)} · ${f.assigned_to ? 'Assigned to ' + f.assigned_to : 'Unassigned'}` })))
        : [el('li', { class: 'none', text: state.files.length ? 'No matching files.' : 'No files uploaded yet.' })]));
    };
    const finish = async (confirmed) => {
      $('select-modal').hidden = true;
      search.oninput = ok.onclick = $('select-cancel').onclick = null;
      if (confirmed && chosen) await assignFlow(letter, chosen);
      resolve();
    };
    search.oninput = draw;
    ok.onclick = () => finish(true);
    $('select-cancel').onclick = () => finish(false);
    draw();
    $('select-modal').hidden = false;
    search.focus();
  });
}

// ---------------------------------------------------------------- preview
function previewFile(f) {
  preview.open({ url: `${API_BASE}/api/files/${f.id}/preview`, name: f.original_name, type: f.file_type });
}
function viewSlot(letter) {
  const f = slotOf(letter).file;
  if (f) previewFile(f);
}

// --------------------------------------------------------------- generate
async function generate() {
  await flushAll();
  setLoading(true, 'Generating final PDF…');
  try {
    const r = await postJson('/api/generate', {});
    await refresh();
    toast('Course File Generated Successfully', 'success');
    $('result-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return r;
  } catch (e) { toast(e.message, 'error'); } finally { setLoading(false); }
}

// ------------------------------------------------------------ drag & drop
// Custom pointer-based drag. Only the ⋮⋮ handle starts a drag. Rows never move:
// dropping calls /api/slots/swap, which exchanges the CONTENT (description + file).
let drag = null;

function dragLabel(letter) {
  const s = slotOf(letter);
  const bits = [letter, s.description.trim() || '(no description)'];
  if (s.file) bits.push(s.file.original_name);
  return bits.join(' · ');
}
const isEmptySlot = (s) => !s.file_id && !s.description.trim();

function startDrag(e, source) {
  if (e.button !== 0 || busy || drag) return;
  e.preventDefault();
  const ghost = el('div', { class: 'drag-ghost', text: dragLabel(source) });
  const badge = el('div', { class: 'drop-badge', hidden: true });
  document.body.append(ghost, badge);
  rows[source].tr.classList.add('drag-source');
  document.body.classList.add('dragging');
  drag = { source, target: null, ghost, badge, scroll: 0, raf: 0 };
  moveDrag(e);
  window.addEventListener('pointermove', moveDrag);
  window.addEventListener('pointerup', endDrag);
  window.addEventListener('pointercancel', cancelDrag);
  window.addEventListener('keydown', dragKey);
  const loop = () => {
    if (!drag) return;
    if (drag.scroll) $('table-scroll').scrollTop += drag.scroll;
    drag.raf = requestAnimationFrame(loop);
  };
  drag.raf = requestAnimationFrame(loop);
}

function moveDrag(e) {
  if (!drag) return;
  drag.ghost.style.left = `${e.clientX + 14}px`;
  drag.ghost.style.top = `${e.clientY + 10}px`;
  const box = $('table-scroll').getBoundingClientRect();
  drag.scroll = e.clientY < box.top + 50 ? -10 : e.clientY > box.bottom - 50 ? 10 : 0;
  const overBox = e.clientX >= box.left && e.clientX <= box.right && e.clientY >= box.top && e.clientY <= box.bottom;
  const tr = overBox ? document.elementFromPoint(e.clientX, e.clientY)?.closest('#az-body tr') : null;
  const letter = tr?.dataset.letter;
  const target = letter && letter !== drag.source ? letter : null;
  if (target !== drag.target) {
    if (drag.target) rows[drag.target].tr.classList.remove('drop-target');
    if (target) rows[target].tr.classList.add('drop-target');
    drag.target = target;
  }
  if (target) {
    const a = slotOf(drag.source), b = slotOf(target);
    drag.badge.hidden = false;
    drag.badge.textContent = isEmptySlot(a) && isEmptySlot(b) ? 'Nothing to move'
      : isEmptySlot(b) ? `Move to ${target}` : `Swap with ${target}`;
    drag.badge.style.left = `${e.clientX + 14}px`;
    drag.badge.style.top = `${e.clientY + 36}px`;
  } else drag.badge.hidden = true;
}

function teardownDrag() {
  if (!drag) return null;
  const d = drag; drag = null;
  cancelAnimationFrame(d.raf);
  d.ghost.remove(); d.badge.remove();
  rows[d.source].tr.classList.remove('drag-source');
  if (d.target) rows[d.target].tr.classList.remove('drop-target');
  document.body.classList.remove('dragging');
  window.removeEventListener('pointermove', moveDrag);
  window.removeEventListener('pointerup', endDrag);
  window.removeEventListener('pointercancel', cancelDrag);
  window.removeEventListener('keydown', dragKey);
  return d;
}
const cancelDrag = () => teardownDrag();
const dragKey = (e) => { if (e.key === 'Escape') teardownDrag(); };

async function endDrag() {
  const d = teardownDrag();
  if (!d || !d.target) return;
  const a = slotOf(d.source), b = slotOf(d.target);
  if (isEmptySlot(a) && isEmptySlot(b)) return;      // both empty: do nothing
  const moving = isEmptySlot(b);
  busy = true;
  try {
    await flushAll();                                  // make sure typed descriptions are saved first
    applySnapshot(await postJson('/api/slots/swap', { from: d.source, to: d.target }));
    toast(moving ? `Moved ${d.source} → ${d.target}` : `Swapped ${d.source} ↔ ${d.target}`, 'success', 2500);
  } catch (e) {
    toast(`Could not move content: ${e.message}`, 'error');
    try { await refresh(); } catch { /* keep the previous UI state */ }
  } finally { busy = false; }
}

// ------------------------------------------------------------------ login
function showLogin() {
  $('login-screen').hidden = false;
  $('login-pass').value = '';
}

function initLogin() {
  // Sign in / Sign up tabs
  document.querySelectorAll('[data-auth-tab]').forEach((tab) => tab.addEventListener('click', () => {
    const up = tab.dataset.authTab === 'signup';
    document.querySelectorAll('[data-auth-tab]').forEach((t) => t.classList.toggle('active', t === tab));
    $('login-form').hidden = up; $('signup-form').hidden = !up;
    $('login-error').hidden = true;
  }));
  $('signup-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('login-error').hidden = true;
    if ($('su-pass').value !== $('su-pass2').value) {
      $('login-error').textContent = 'The two passwords do not match.';
      $('login-error').hidden = false;
      return;
    }
    $('su-btn').disabled = true;
    try {
      await api('/api/auth/signup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, noAuthRedirect: true,
        body: JSON.stringify({ name: $('su-name').value, email: $('su-email').value, password: $('su-pass').value }),
      });
      location.reload();
    } catch (err) {
      $('login-error').textContent = err.message;
      $('login-error').hidden = false;
    } finally { $('su-btn').disabled = false; }
  });
  $('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('login-error').hidden = true;
    $('login-btn').disabled = true;
    try {
      await api('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, noAuthRedirect: true,
        body: JSON.stringify({ login_id: $('login-id').value, password: $('login-pass').value }),
      });
      location.reload();
    } catch (err) {
      $('login-error').textContent = err.message;
      $('login-error').hidden = false;
      $('login-pass').select();
    } finally { $('login-btn').disabled = false; }
  });
  $('btn-logout').onclick = async () => {
    await flushAll();
    try { await api('/api/auth/logout', { method: 'POST', noAuthRedirect: true }); } catch { /* ignore */ }
    location.reload();
  };
}

// ------------------------------------------------------------------- init
async function init() {
  initLogin();
  let me = null;
  try {
    me = await api('/api/auth/me', { noAuthRedirect: true });
    $('user-name').textContent = me.name;
    $('user-role').textContent = me.role;
    $('user-box').hidden = false;
  } catch (e) {
    if (e.status === 401) { showLogin(); $('login-id').focus(); return; }
    // Backend unreachable / not configured: still draw the full A-Z layout so the UI can be seen.
    buildRows();
    try { render(); } catch { /* empty state */ }
    $('lo-warning').textContent = 'Preview only: the backend server is not connected yet, so login, uploads and PDF '
      + 'generation are unavailable. Set the backend address in config.js (CFG_API_BASE).';
    $('lo-warning').hidden = false;
    return;
  }
  buildRows();
  initCourseInputs();
  initCatalogUi({ $, el, api, toast, confirmDialog, state, setCourseField, role: me.role });
  $('btn-upload').onclick = () => { $('input-multi').value = ''; $('input-multi').click(); };
  $('input-multi').onchange = () => uploadMany($('input-multi').files);
  $('input-slot').onchange = slotUploadChosen;
  $('btn-generate').onclick = generate;
  $('btn-preview-final').onclick = () => preview.open({
    url: `${API_BASE}/api/generate/download?inline=true&t=${Date.now()}`,
    name: state.last_output?.filename ?? 'Final course file', type: 'PDF (final course file)',
  });
  try {
    await refresh();
  } catch (e) {
    toast(e.message, 'error', 10000);
  }
  try {
    const h = await api('/api/health');
    if (!h.libreoffice.available) {
      $('lo-warning').textContent = h.libreoffice.message + ' PDF files can still be used; Word/Excel/PowerPoint/TXT cannot be converted until then.';
      $('lo-warning').hidden = false;
    }
  } catch { /* backend unreachable, already reported */ }
}
init();
