import {getJSON, faNum, showFormError, clearFormError} from './api_client.js';
/* گفت‌وگوی داده سراسری (T09 — تک‌مالک انتخاب فایل/مقصد همه کابین‌ها؛
   هیچ رونوشت per-cabin وجود ندارد — کابین بعدی همین openDataDialog را
   با caller خودش صدا می‌زند).
   قرارداد: openDataDialog(mode, callerId)؛ mode «input» (فایل → پرکردن
   A1 + رویداد input برای شمارش/دفتر) یا «dest» (پوشه → پرکردن A2).
   ریشه‌ها از GET /api/files/roots (ریشه نخست = ریشه داده؛ ریشه مرده
   هرگز از سرور نمی‌آید)؛ سطرها از GET /api/files/list (اندازه + سطرهای
   سقف‌دار «۵۰۰۰۰+» + mtime نسبی T02 با title شمسی/میلادی؛ پوشه‌ها هیچ
   ادعای اندازه ندارند)؛ سنجاق‌ها از GET/POST/DELETE /api/files/pins.
   عملیات مجاز: ساخت پوشه + تغییرنام هم‌والد (OQ-1) + بارگذاری یک فایل
   در پوشه جاری (T11: POST /api/files/upload، فقط ریشه‌های مجاز،
   هم‌نام → ۴۰۹ بدون بازنویسی)؛ دکمه حذف وجود ندارد (مسدود سخت).
   گفت‌وگوی برخورد نام (T11: openCollisionDialog) با ۴ گزینه صریح
   (نام خودکار _v2 / بازنویسی با تأیید / نام تازه / انصراف کامل) —
   هرگز بازنویسی بی‌سر و صدا نیست.
   هرگز ستون کنترل را نمی‌پوشاند (CSS: چسبیده به سمت مخالف؛ تبلت: ورق
   با ستون کنترل بالاتر از ورق)؛ بستن فوکوس را به caller برمی‌گرداند.
   نشت سراسری صفر: همه حالت‌ها در دامنه ماژول، بدون window.*. */
let curDir = '';
let mode = 'input';
let callerId = '';
let lastFocus = null;

function el(id) {
  return document.getElementById(id);
}
function dialog() {
  return el('data-dialog');
}
function ltr(text) {
  const s = document.createElement('bdi');
  s.className = 'code-token';
  s.setAttribute('dir', 'ltr');
  s.textContent = String(text === null || text === undefined ? '—' : text);
  return s;
}
function faCell(value, title) {
  const s = document.createElement('span');
  s.textContent = faNum(value);
  if (title) s.title = title;
  return s;
}
function fail(message, detail, retryFn) {
  showFormError('data-dialog-err', message, detail, retryFn, undefined);
}
export function isDataDialogOpen() {
  const d = dialog();
  return !!d && !d.hasAttribute('hidden');
}
/* بازکردن: mode در {'input','dest'}؛ callerId شناسه فیلد فراخوان صداکننده
   (متن A1 یا مقصد A2). ریشه نخست (ریشه داده) نقطه شروع است. */
export function openDataDialog(wantMode, wantCallerId) {
  mode = (wantMode === 'dest') ? 'dest' : 'input';
  callerId = String(wantCallerId || '');
  try {
    lastFocus = document.activeElement || null;
  } catch(e) { lastFocus = null; }
  const d = dialog();
  if (!d) return;
  clearFormError('data-dialog-err');
  const label = el('data-dialog-mode');
  if (label) {
    label.textContent = (mode === 'dest')
      ? 'حالت: انتخاب مقصد (پوشه)'
      : 'حالت: انتخاب ورودی (فایل)';
  }
  d.removeAttribute('hidden');
  try {
    document.body.classList.add('has-data-dialog');
  } catch(e) {}
  boot();
  const close = el('data-dialog-close');
  if (close) close.focus();
}
export function closeDataDialog() {
  const d = dialog();
  if (d) d.setAttribute('hidden', '');
  try {
    document.body.classList.remove('has-data-dialog');
  } catch(e) {}
  const back = (callerId && el(callerId)) || lastFocus;
  try {
    if (back && typeof back.focus === 'function') back.focus();
  } catch(e) {}
  callerId = '';
  lastFocus = null;
}
async function boot() {
  try {
    const j = await getJSON('/api/files/roots');
    const roots = (j && j.roots) || [];
    renderRoots(roots);
    if (roots.length && roots[0].path) {
      listDir(roots[0].path);
    } else {
      renderEntries({dir: '', parent: null, entries: []});
      fail('ریشه‌ای برای مرور نیست.', undefined, boot, undefined);
    }
    refreshPins();
  } catch(e) {
    fail('خواندن ریشه‌های داده ناموفق بود.', (e && e.message) || e, boot);
  }
}
function renderRoots(roots) {
  const box = el('data-dialog-roots');
  if (!box) return;
  box.replaceChildren();
  if (!roots.length) {
    const empty = document.createElement('span');
    empty.className = 'p-meta';
    empty.textContent = 'ریشه‌ای نیست — پوشه داده جابه‌جا شده است؟';
    box.append(empty);
    return;
  }
  roots.forEach((r) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn-skip-next';
    b.append(ltr((r && r.label) || (r && r.path) || 'ریشه'));
    b.title = (r && r.path) || '';
    b.addEventListener('click', () => listDir(r.path));
    box.append(b);
  });
}
async function listDir(dir) {
  try {
    const j = await getJSON('/api/files/list?dir=' + encodeURIComponent(dir));
    curDir = (j && j.dir) || dir;
    renderEntries(j);
  } catch(e) {
    fail('فهرست پوشه خوانده نشد.', (e && e.message) || e,
      () => listDir(dir));
  }
}
function renderEntries(payload) {
  const crumb = el('data-dialog-crumb');
  if (crumb) {
    crumb.replaceChildren();
    crumb.append(document.createTextNode(String((payload && payload.dir) || curDir || '—')));
    if (payload && payload.parent) {
      const up = document.createElement('button');
      up.type = 'button';
      up.className = 'btn-skip-next';
      up.textContent = 'بالا ⬆';
      up.addEventListener('click', () => listDir(payload.parent));
      crumb.append(document.createTextNode(' '), up);
    }
  }
  const tb = el('data-dialog-tbody');
  if (!tb) return;
  tb.replaceChildren();
  const rows = ((payload && payload.entries) || []);
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.textContent = 'این پوشه خالی است.';
    tr.append(td);
    tb.append(tr);
    return;
  }
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    const tdName = document.createElement('td');
    tdName.append(ltr((row && row.name) || '—'));
    if (row && row.is_dir) {
      const tag = document.createElement('span');
      tag.className = 'badge';
      tag.textContent = 'پوشه';
      tdName.append(document.createTextNode(' '), tag);
    }
    const tdSize = document.createElement('td');
    if (row && row.is_dir) {
      tdSize.append(faCell('—', 'پوشه‌ها اندازه تجمیعی ندارند'));
    } else {
      tdSize.append(faCell((row && row.size !== undefined) ? row.size : '—', null));
    }
    const tdLines = document.createElement('td');
    if (row && row.is_dir) {
      tdLines.append(faCell('—', 'شمارش سطر برای پوشه نیست'));
    } else {
      tdLines.append(faCell((row && row.lines_label) || '—',
        (row && row.lines_note) || null));
    }
    const tdMtime = document.createElement('td');
    if (row && row.is_dir) {
      tdMtime.append(faCell('—', null));
    } else {
      tdMtime.append(faCell((row && row.mtime_relative) || '—',
        (row && row.mtime_detail) || null));
    }
    const tdAct = document.createElement('td');
    tdAct.className = 'data-dialog-actions';
    const full = ((payload && payload.dir) || curDir || '') + '/' + ((row && row.name) || '');
    if (mode === 'input' && row && !row.is_dir) {
      const pick = document.createElement('button');
      pick.type = 'button';
      pick.className = 'btn-select-candidate';
      pick.textContent = 'انتخاب به‌عنوان ورودی';
      pick.addEventListener('click', () => pickAsInput(full));
      tdAct.append(pick);
    }
    if (mode === 'dest' && row && row.is_dir) {
      const pick = document.createElement('button');
      pick.type = 'button';
      pick.className = 'btn-select-candidate';
      pick.textContent = 'انتخاب به‌عنوان مقصد';
      pick.addEventListener('click', () => pickAsDest(full));
      tdAct.append(pick);
    }
    if (row && row.is_dir) {
      const go = document.createElement('button');
      go.type = 'button';
      go.className = 'btn-skip-next';
      go.textContent = 'بازکردن';
      go.addEventListener('click', () => listDir(full));
      tdAct.append(go);
    }
    const pin = document.createElement('button');
    pin.type = 'button';
    pin.className = 'btn-skip-next';
    pin.textContent = 'سنجاق';
    pin.title = 'سنجاق این مسیر با نام همین سطر';
    pin.addEventListener('click', () => pinRow(
      full, ((row && row.name) || ''), row && row.is_dir ? 'dir' : 'file'));
    tdAct.append(pin);
    const ren = document.createElement('button');
    ren.type = 'button';
    ren.className = 'btn-skip-next';
    ren.textContent = 'تغییر نام';
    ren.addEventListener('click', () => renameInline(tr, full, (row && row.name) || ''));
    tdAct.append(ren);
    /* عمداً بدون دکمه حذف (OQ-1 مسدود سخت). بارگذاری (T11) در
       سطر عملیات بالای جدول است، نه در هر سطر. */
    tr.append(tdName, tdSize, tdLines, tdMtime, tdAct);
    tb.append(tr);
  });
}
/* پرکردن A1: واژه‌های سقف‌دار سرور در textarea + رویداد input (شمارش
   و دفتر T07 همان شنونده موجود را اجرا می‌کنند) + بستن. */
async function pickAsInput(full) {
  const target = callerId && el(callerId);
  if (!target) {
    fail('فیلد فراخوان پیدا نشد.', callerId || undefined, null);
    return;
  }
  try {
    const j = await getJSON('/api/files/words?path=' + encodeURIComponent(full));
    const words = (j && j.words) || [];
    if (!words.length) {
      fail('فایل واژه‌ای نداشت.', full, () => pickAsInput(full));
      return;
    }
    target.value = words.join('\n');
    try {
      target.dispatchEvent(new Event('input', {bubbles: true}));
    } catch(e) {}
    closeDataDialog();
  } catch(e) {
    fail('خواندن واژه‌های فایل ناموفق بود.', (e && e.message) || e,
      () => pickAsInput(full));
  }
}
function pickAsDest(full) {
  const target = callerId && el(callerId);
  if (!target) {
    fail('فیلد فراخوان پیدا نشد.', callerId || undefined, null);
    return;
  }
  target.value = full;
  try {
    target.dispatchEvent(new Event('input', {bubbles: true}));
  } catch(e) {}
  closeDataDialog();
}
async function mkdirCurrent() {
  const input = el('data-dialog-mkdir-name');
  const name = String((input && input.value) || '').trim();
  if (!name || !curDir) {
    fail('نام پوشه و مسیر جاری لازم است.', undefined, null);
    return;
  }
  try {
    await getJSON('/api/files/mkdir', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({dir: curDir, name})});
    if (input) input.value = '';
    listDir(curDir);
  } catch(e) {
    fail('ساخت پوشه ناموفق بود.', (e && e.message) || e, mkdirCurrent);
  }
}
/* بارگذاری یک فایل در پوشه جاری (T11): فقط ریشه‌های مجاز سرور،
   هم‌نام → ۴۰۹ بدون بازنویسی؛ پس از موفقیت فهرست تازه می‌شود و فایل
   از همان گفت‌وگو دوباره قابل انتخاب است (UX-3/6). */
async function uploadCurrent() {
  const picker = el('data-dialog-upload-file');
  const btn = el('data-dialog-upload');
  const file = picker && picker.files && picker.files[0];
  if (!file || !curDir) {
    fail('فایل و پوشه جاری لازم است.', undefined, null);
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const form = new FormData();
    form.append('dir', curDir);
    form.append('file', file, file.name);
    const r = await fetch('/api/files/upload',
      {method: 'POST', body: form});
    let j = null;
    try { j = await r.json(); } catch(e) {}
    if (!r.ok) {
      fail('بارگذاری ناموفق بود.',
        ((j && j.error) || ('خطای ' + r.status)),
        uploadCurrent);
      return;
    }
    if (picker) picker.value = '';
    clearFormError('data-dialog-err');
    listDir(curDir);
  } catch(e) {
    fail('بارگذاری ناموفق بود.', (e && e.message) || e, uploadCurrent);
  } finally {
    if (btn) btn.disabled = false;
  }
}
/* ── گفت‌وگوی برخورد نام خروجی (T11) ──
   openCollisionDialog({name, path}) قولی برمی‌گرداند با یکی از:
   {choice:'auto'} (نام خودکار _v2 سمت سرور)، {choice:'overwrite'}
   (بازنویسی خروجی پیشین — فقط با تیک تأیید صریح فعال می‌شود)،
   {choice:'rename', name} (نام تازه درون‌خطی)، {choice:'cancel'}
   (انصراف کامل، هیچ درخواستی فرستاده نمی‌شود). بستن با ✕ یا Escape
   یعنی انصراف کامل. فوکوس پس از بستن به فراخوان برمی‌گردد. */
let collisionSettle = null;
function collisionDlg() {
  return el('collision-dialog');
}
function endCollision(result) {
  const d = collisionDlg();
  if (d) d.setAttribute('hidden', '');
  try {
    document.body.classList.remove('has-collision-dialog');
  } catch(e) {}
  const fn = collisionSettle;
  collisionSettle = null;
  if (typeof fn === 'function') fn(result || {choice: 'cancel'});
}
export function openCollisionDialog(info) {
  const d = collisionDlg();
  const name = String((info && info.name) || '');
  const path = String((info && info.path) || '');
  if (!d) return Promise.resolve({choice: 'cancel'});
  const nameSlot = el('collision-name');
  if (nameSlot) {
    nameSlot.replaceChildren();
    nameSlot.append(document.createTextNode(name || '—'));
  }
  const pathSlot = el('collision-path');
  if (pathSlot) {
    pathSlot.replaceChildren();
    pathSlot.append(document.createTextNode(path || '—'));
  }
  const rename = el('collision-rename');
  if (rename) rename.value = '';
  const confirm = el('collision-overwrite-confirm');
  if (confirm) confirm.checked = false;
  const overBtn = el('collision-overwrite');
  if (overBtn) overBtn.disabled = true;
  clearFormError('collision-err');
  d.removeAttribute('hidden');
  try {
    document.body.classList.add('has-collision-dialog');
  } catch(e) {}
  const autoBtn = el('collision-auto');
  if (autoBtn) autoBtn.focus();
  return new Promise((resolve) => {
    collisionSettle = resolve;
  });
}
function initCollisionDialog() {
  const d = collisionDlg();
  if (!d || d.dataset.wired) return;
  d.dataset.wired = '1';
  const autoBtn = el('collision-auto');
  if (autoBtn) {
    autoBtn.addEventListener('click', () => endCollision({choice: 'auto'}));
  }
  const confirm = el('collision-overwrite-confirm');
  const overBtn = el('collision-overwrite');
  if (confirm && overBtn) {
    confirm.addEventListener('change', () => {
      overBtn.disabled = !confirm.checked;
    });
  }
  if (overBtn) {
    overBtn.addEventListener('click', () => {
      if (confirm && !confirm.checked) return;
      endCollision({choice: 'overwrite'});
    });
  }
  const renameGo = el('collision-rename-go');
  if (renameGo) {
    renameGo.addEventListener('click', () => {
      const input = el('collision-rename');
      const fresh = String((input && input.value) || '').trim();
      if (!fresh) {
        showFormError('collision-err', 'نام تازه خالی است.',
          undefined, null, 'VALIDATION-input');
        return;
      }
      endCollision({choice: 'rename', name: fresh});
    });
  }
  const cancel = el('collision-cancel');
  if (cancel) {
    cancel.addEventListener('click', () => endCollision({choice: 'cancel'}));
  }
  const x = el('collision-cancel-x');
  if (x) {
    x.addEventListener('click', () => endCollision({choice: 'cancel'}));
  }
  document.addEventListener('keydown', (ev) => {
    const open = d && !d.hasAttribute('hidden');
    if (ev.key === 'Escape' && open && collisionSettle) {
      endCollision({choice: 'cancel'});
    }
  });
}
/* تغییرنام هم‌والد: سطر به ورودی inline + تأیید/لغو (بدون prompt). */
function renameInline(tr, full, oldName) {
  const first = tr && tr.cells && tr.cells[0];
  if (!first) return;
  first.replaceChildren();
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'code-token';
  input.setAttribute('dir', 'ltr');
  input.value = oldName;
  input.setAttribute('aria-label', 'نام تازه');
  const ok = document.createElement('button');
  ok.type = 'button';
  ok.className = 'btn-select-candidate';
  ok.textContent = 'تأیید';
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'btn-skip-next';
  cancel.textContent = 'لغو';
  ok.addEventListener('click', async () => {
    const name = String(input.value || '').trim();
    if (!name) return;
    try {
      await getJSON('/api/files/rename', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: full, name})});
      listDir(curDir);
    } catch(e) {
      fail('تغییر نام ناموفق بود.', (e && e.message) || e, null);
      listDir(curDir);
    }
  });
  cancel.addEventListener('click', () => listDir(curDir));
  first.append(input, document.createTextNode(' '), ok,
    document.createTextNode(' '), cancel);
  try { input.focus(); input.select(); } catch(e) {}
}
async function pinRow(full, name, kind) {
  if (!name) return;
  try {
    await getJSON('/api/files/pins', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, path: full, kind})});
    refreshPins();
  } catch(e) {
    fail('سنجاق ناموفق بود.', (e && e.message) || e,
      () => pinRow(full, name, kind));
  }
}
async function refreshPins() {
  const box = el('data-dialog-pins');
  if (!box) return;
  box.replaceChildren();
  try {
    const j = await getJSON('/api/files/pins');
    const pins = (j && j.pins) || [];
    if (!pins.length) {
      const empty = document.createElement('span');
      empty.className = 'p-meta';
      empty.textContent = 'هنوز سنجاقی نیست — از سطر فهرست «سنجاق» بزنید.';
      box.append(empty);
      return;
    }
    pins.forEach((p) => {
      const chip = document.createElement('span');
      chip.className = 'data-pin-chip';
      chip.append(ltr((p && p.name) || '—'));
      const jump = document.createElement('button');
      jump.type = 'button';
      jump.className = 'btn-skip-next';
      jump.textContent = 'رفتن';
      jump.title = (p && p.path) || '';
      jump.addEventListener('click', () => {
        if (p && p.kind === 'dir') listDir(p.path);
        else if (p && p.path) {
          const slash = String(p.path).lastIndexOf('/');
          listDir(slash > 0 ? String(p.path).slice(0, slash) : p.path);
        }
      });
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'btn-skip-next';
      del.textContent = 'برداشتن سنجاق';
      del.addEventListener('click', async () => {
        try {
          await getJSON('/api/files/pins/' + encodeURIComponent(p.name),
            {method: 'DELETE'});
          refreshPins();
        } catch(e) {
          fail('برداشتن سنجاق ناموفق بود.', (e && e.message) || e,
            refreshPins);
        }
      });
      chip.append(document.createTextNode(' '), jump,
        document.createTextNode(' '), del);
      box.append(chip);
    });
  } catch(e) {
    const err = document.createElement('span');
    err.className = 'p-meta';
    err.textContent = 'سنجاق‌ها خوانده نشد.';
    err.title = String((e && e.message) || e);
    box.append(err);
  }
}
async function pinCurrent() {
  const input = el('data-dialog-pin-name');
  const name = String((input && input.value) || '').trim();
  if (!name || !curDir) {
    fail('نام سنجاق و مسیر جاری لازم است.', undefined, null);
    return;
  }
  try {
    await getJSON('/api/files/pins', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, path: curDir, kind: 'dir'})});
    if (input) input.value = '';
    refreshPins();
  } catch(e) {
    fail('سنجاق مسیر جاری ناموفق بود.', (e && e.message) || e, pinCurrent);
  }
}
/* آکاردئون A1 تا A4 (T09): دسکتاپ همه باز (summary پنهان در CSS)؛
   تبلت یکی‌باز (بازکردن یکی بقیه را می‌بندد؛ ترتیب A1→A4 در DOM). */
function initCabinAccordion() {
  const sections = Array.from(
    document.querySelectorAll('#screening-card details.acc'));
  if (!sections.length) return;
  const tablet = () => {
    try {
      return window.matchMedia('(max-width: 1024px)').matches;
    } catch(e) { return false; }
  };
  /* تبلت با یکی‌باز شروع می‌کند (نخستین بخش)؛ دسکتاپ همه‌باز می‌ماند. */
  if (tablet()) {
    let kept = false;
    sections.forEach((sec) => {
      if (sec.open && !kept) kept = true;
      else if (sec.open) sec.open = false;
    });
    if (!kept && sections.length) sections[0].open = true;
  }
  sections.forEach((sec) => {
    sec.addEventListener('toggle', () => {
      if (sec.open && tablet()) {
        sections.forEach((other) => {
          if (other !== sec && other.open) other.open = false;
        });
      }
    });
  });
}
/* سیم‌کشی دکمه‌های فراخوان کابین غربالگری (A1/A2) + بستن + عملیات.
   همین ماژول برای کابین‌های بعدی هم کافی است (callerId تازه). */
function initDialog() {
  const close = el('data-dialog-close');
  if (close) close.addEventListener('click', closeDataDialog);
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && isDataDialogOpen()) closeDataDialog();
  });
  const pickInput = el('screening-pick-input');
  if (pickInput) {
    pickInput.addEventListener('click', () => openDataDialog('input', 'screening-words'));
  }
  const pickDest = el('screening-pick-dest');
  if (pickDest) {
    pickDest.addEventListener('click', () => openDataDialog('dest', 'screening-out-dir'));
  }
  const mkdir = el('data-dialog-mkdir');
  if (mkdir) mkdir.addEventListener('click', mkdirCurrent);
  const upload = el('data-dialog-upload');
  if (upload) upload.addEventListener('click', uploadCurrent);
  const pinAdd = el('data-dialog-pin-add');
  if (pinAdd) pinAdd.addEventListener('click', pinCurrent);
  initCollisionDialog();
  initCabinAccordion();
}
initDialog();
