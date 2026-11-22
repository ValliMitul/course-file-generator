// Course-detail dropdowns, course-code autofill, "add new" dialogs and the admin panel.
// Receives the helpers it needs from script.js so there is a single API/error/toast path.

const SEMESTERS = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII'];

/** Academic years from 5 years back to 5 years ahead, e.g. "2021-22" ... "2031-32". */
export function academicYears(now = new Date()) {
  // Indian academic year starts around July.
  const start = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
  const out = [];
  for (let y = start - 5; y <= start + 5; y++) out.push(`${y}-${String((y + 1) % 100).padStart(2, '0')}`);
  return out;
}

export function currentAcademicYear(now = new Date()) {
  const start = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, '0')}`;
}

/** Make sure a <select> can display `value`, even if it is not one of the standard options. */
export function ensureOption(select, value) {
  if (!value) return;
  if (![...select.options].some((o) => o.value === value)) select.append(new Option(value, value));
}

export function initCatalogUi({ $, el, api, toast, confirmDialog, state, setCourseField, role }) {
  const cat = { courses: [], coordinators: [] };
  const semSel = document.querySelector('[data-course="semester"]');
  const yearSel = document.querySelector('[data-course="academic_year"]');
  const coordSel = document.querySelector('[data-course="course_coordinator"]');
  const codeInp = document.querySelector('[data-course="course_code"]');
  const nameInp = document.querySelector('[data-course="course_name"]');

  const fillSelect = (sel, placeholder, values) => {
    const keep = sel.value;
    sel.replaceChildren(new Option(placeholder, ''), ...values.map((v) => new Option(v.label ?? v, v.value ?? v)));
    ensureOption(sel, keep);
    sel.value = keep;
  };

  fillSelect(semSel, 'Select semester', SEMESTERS);
  fillSelect(yearSel, 'Select academic year', academicYears());

  function renderCatalog() {
    fillSelect(coordSel, 'Select coordinator', cat.coordinators.map((p) => ({
      value: p.name, label: p.designation ? `${p.name} — ${p.designation}` : p.name,
    })));
    $('course-codes').replaceChildren(...cat.courses.map((c) => {
      const o = new Option(c.name, c.code);
      return o;
    }));
  }

  async function loadCatalog() {
    try {
      const data = await api('/api/catalog');
      cat.courses = data.courses; cat.coordinators = data.coordinators;
      renderCatalog();
      autofillName();
    } catch (e) { toast(`Could not load courses/coordinators: ${e.message}`, 'error'); }
  }

  // ---- typing a course code fills in the course name
  function autofillName() {
    const code = codeInp.value.trim().toUpperCase().replace(/\s+/g, '');
    const hit = cat.courses.find((c) => c.code === code);
    if (hit && nameInp.value !== hit.name) { setCourseField('course_name', hit.name); }
    $('code-hint').textContent = code && !hit ? 'Code not in the list — enter the name yourself or add it with “+”.' : '';
  }
  codeInp.addEventListener('input', autofillName);
  codeInp.addEventListener('change', autofillName);

  // ---- generic small form dialog
  function openForm(modalId, onSubmit) {
    const modal = $(modalId), form = modal.querySelector('form'), err = modal.querySelector('.form-error');
    form.reset(); err.hidden = true; modal.hidden = false;
    form.querySelector('input,select').focus();
    const close = () => { modal.hidden = true; form.onsubmit = null; };
    modal.querySelector('[data-close]').onclick = close;
    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type=submit]'); btn.disabled = true; err.hidden = true;
      try { await onSubmit(new FormData(form)); close(); }
      catch (ex) { err.textContent = ex.message; err.hidden = false; }
      finally { btn.disabled = false; }
    };
  }
  const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  $('btn-add-course').onclick = () => openForm('course-modal', async (fd) => {
    const c = await api('/api/catalog/courses', json('POST', {
      code: fd.get('code'), name: fd.get('name'), semester: fd.get('semester'),
    }));
    cat.courses.push(c); cat.courses.sort((a, b) => a.code.localeCompare(b.code));
    renderCatalog();
    setCourseField('course_code', c.code); setCourseField('course_name', c.name);
    if (c.semester) setCourseField('semester', c.semester);
    toast(`Added course ${c.code}.`, 'info');
  });
  $('btn-add-coordinator').onclick = () => openForm('coord-modal', async (fd) => {
    const p = await api('/api/catalog/coordinators', json('POST', {
      name: fd.get('name'), designation: fd.get('designation'),
    }));
    cat.coordinators.push(p); cat.coordinators.sort((a, b) => a.name.localeCompare(b.name));
    renderCatalog();
    setCourseField('course_coordinator', p.name);
    toast(`Added ${p.name}.`, 'info');
  });
  $('course-modal').querySelector('select[name=semester]').replaceChildren(
    new Option('Semester (optional)', ''), ...SEMESTERS.map((s) => new Option(s, s)));

  // ---- admin panel (administrators only)
  if (role === 'admin') {
    $('btn-admin').hidden = false;
    $('btn-admin').onclick = openAdmin;
  }
  async function openAdmin() {
    const modal = $('admin-modal'), body = $('admin-body');
    modal.hidden = false;
    modal.querySelector('[data-close]').onclick = () => { modal.hidden = true; };
    const tabs = [...modal.querySelectorAll('[data-tab]')];
    const show = async (tab) => {
      tabs.forEach((t) => t.classList.toggle('active', t.dataset.tab === tab));
      body.replaceChildren(el('p', { class: 'muted', text: 'Loading…' }));
      try {
        if (tab === 'users') await showUsers(body);
        else await showCatalog(body, tab);
      } catch (e) { body.replaceChildren(el('p', { class: 'form-error', text: e.message })); }
    };
    tabs.forEach((t) => { t.onclick = () => show(t.dataset.tab); });
    show('users');
  }

  async function showUsers(body) {
    const { users, current } = await api('/api/admin/users');
    const rows = users.map((u) => {
      const sel = el('select', { 'aria-label': `Role for ${u.email}` },
        el('option', { value: 'faculty', text: 'Faculty' }), el('option', { value: 'admin', text: 'Admin' }));
      sel.value = u.role || 'faculty';
      if (!u.role) sel.prepend(new Option('No role', ''));
      if (!u.role) sel.value = '';
      let prev = sel.value;
      sel.onchange = async () => {
        if (!sel.value) { sel.value = prev; return; }
        if (!await confirmDialog(`Change ${u.name || u.email} to ${sel.value}?`, { title: 'Change role', ok: 'Change' })) {
          sel.value = prev; return;
        }
        try { await api(`/api/admin/users/${encodeURIComponent(u.id)}/role`, json('PUT', { role: sel.value })); prev = sel.value; toast('Role updated.'); }
        catch (e) { sel.value = prev; toast(e.message, 'error'); }
      };
      return el('tr', {}, el('td', { text: u.name || '—' }), el('td', { text: u.email }),
        el('td', {}, sel), el('td', { text: u.created }));
    });
    body.replaceChildren(
      el('p', { class: 'muted', text: 'Everyone who signs up is a Faculty user. Promote trusted people to Admin here.' }),
      el('table', { class: 'admin-table' },
        el('thead', {}, el('tr', {}, ...['Name', 'Email', 'Role', 'Joined'].map((h) => el('th', { text: h })))),
        el('tbody', {}, ...rows)));
    void current;
  }

  async function showCatalog(body, tab) {
    await loadCatalog();
    const isCourse = tab === 'courses';
    const items = isCourse ? cat.courses : cat.coordinators;
    const search = el('input', { type: 'search', placeholder: 'Search…' });
    const list = el('div', { class: 'admin-list' });
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      list.replaceChildren(...items
        .filter((x) => !q || JSON.stringify(x).toLowerCase().includes(q))
        .map((x) => el('div', { class: 'admin-item' },
          el('span', { text: isCourse ? `${x.code} — ${x.name}${x.semester ? ` (Sem ${x.semester})` : ''}`
            : `${x.name}${x.designation ? ` — ${x.designation}` : ''}` }),
          el('button', {
            class: 'btn btn-sm', text: 'Delete', onclick: async () => {
              if (!await confirmDialog(`Delete ${isCourse ? x.code : x.name} from the list?`, { title: 'Delete', ok: 'Delete' })) return;
              try {
                await api(`/api/catalog/${tab}/${encodeURIComponent(isCourse ? x.code : x.name)}`, { method: 'DELETE' });
                items.splice(items.indexOf(x), 1); renderCatalog(); draw();
              } catch (e) { toast(e.message, 'error'); }
            },
          }))));
    };
    search.oninput = draw; draw();
    body.replaceChildren(search, list);
  }

  return loadCatalog();
}
