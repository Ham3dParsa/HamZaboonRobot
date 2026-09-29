import {getJSON, ltrCode, faCell, showFormError, clearFormError} from './api_client.js';
import {PagedListController, EMPTY_FA} from './paginated_list_controller.js';
import {fetchRoots, listPins, clearPinsCache, listRecents, presetDestinations, validateCustomPath, fillInput,
  rootFacts, matchRoot, factsLine, causeFa, usefulnessFor} from './file_history_manager.js';
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
/* P06: پیجر مشترک p50 فهرست فایل‌ها (بدون کپی)؛ رندر صفحه از
   آخرین محموله کش‌شده می‌آید تا ورق‌زدن فراخوانی سرور نخواهد. */
let lastEntries = null;
const entriesPager = new PagedListController({
  pagerId: 'data-dialog-pager', onPage: () => renderEntries(lastEntries)});

function el(id) {
  return document.getElementById(id);
}
function dialog() {
  return el('data-dialog');
}
/* PUX-B9: ltr/faCell از تک‌مالک api_client می‌آیند (رونوشت محلی حذف شد). */
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
  renderPresetBlock();
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
    const j = await fetchRoots();
    const roots = (j && j.roots) || [];
    renderRoots(roots);
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
    empty.textContent = EMPTY_FA.noRoots.text;
    empty.title = EMPTY_FA.noRoots.title;
    box.append(empty);
    return;
  }
  roots.forEach((r) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn-skip-next';
    b.append(ltrCode((r && r.label) || (r && r.path) || 'ریشه'));
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
  lastEntries = payload || null;
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
  entriesPager.setTotal(rows.length);
  const page = entriesPager.pageItems(rows);
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.textContent = 'این پوشه خالی است.';
    td.title = EMPTY_FA.noRows.title;
    tr.append(td);
    tb.append(tr);
    return;
  }
  page.forEach((row) => {
    const tr = document.createElement('tr');
    const tdName = document.createElement('td');
    tdName.append(ltrCode((row && row.name) || '—'));
    if (!row || !row.name) {
      tdName.title = EMPTY_FA.missingFact.title;
    }
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
      const sz = (row && row.size !== undefined && row.size !== null) ? row.size : null;
      tdSize.append(faCell(sz === null ? '—' : sz,
        sz === null ? EMPTY_FA.missingFact.title : null));
    }
    const tdLines = document.createElement('td');
    if (row && row.is_dir) {
      tdLines.append(faCell('—', 'شمارش سطر برای پوشه نیست'));
    } else {
      const lab = (row && row.lines_label) || null;
      tdLines.append(faCell(lab === null ? '—' : lab,
        lab === null ? EMPTY_FA.missingFact.title
          : ((row && row.lines_note) || null)));
    }
    const tdMtime = document.createElement('td');
    if (row && row.is_dir) {
      tdMtime.append(faCell('—', EMPTY_FA.missingFact.title));
    } else {
      const mt = (row && row.mtime_relative) || null;
      tdMtime.append(faCell(mt === null ? '—' : mt,
        mt === null ? EMPTY_FA.missingFact.title
          : ((row && row.mtime_detail) || null)));
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
   و دفتر T07 همان شنونده موجود را اجرا می‌کنند) + بستن. پرکردن از
   تک‌راه مدیر (P04) می‌گذرد تا تازه‌ها ثبت شوند. */
async function pickAsInput(full) {
  if (!callerId || !el(callerId)) {
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
    fillInput(callerId, words.join('\n'), 'file');
    closeDataDialog();
    /* بسته‌بودن فرمان‌بر → بی‌اثر (رفتار فوکوس گفت‌وگو حفظ می‌شود)؛
       بازبودن → بستن با بازگشت فوکوس به دکمه فراخوان. */
    closeCmdPopover(true);
  } catch(e) {
    fail('خواندن واژه‌های فایل ناموفق بود.', (e && e.message) || e,
      () => pickAsInput(full));
  }
}
function pickAsDest(full) {
  if (!callerId || !el(callerId)) {
    fail('فیلد فراخوان پیدا نشد.', callerId || undefined, null);
    return;
  }
  fillInput(callerId, full, 'dir');
  closeDataDialog();
  closeCmdPopover(true);
}
/* ── P04: نوار پیش‌فرض + مسیر تایپی (مدیر یکپارچه) ──
   پیش‌فرض حالت‌مند مدیر (ریشه/سنجاق/تازه) + ورودی آزاد با اعتبارسنجی
   سرور (POST /api/files/resolve — خارج از مجاز → خطای فارسی، بی‌گزینش). */
function targetLabel() {
  if (callerId === 'screening-words') return 'واژه‌ها';
  if (callerId === 'screening-out-dir') return 'مقصد';
  return callerId || 'مقصد';
}
async function renderPresetBlock() {
  const sel = el('data-dialog-preset');
  if (!sel) return;
  sel.replaceChildren();
  const hint = document.createElement('option');
  hint.value = '';
  hint.textContent = 'پیش‌فرضی برگزینید…';
  sel.append(hint);
  try {
    const items = await presetDestinations(mode, targetLabel());
    items.forEach((it) => {
      const opt = document.createElement('option');
      opt.value = it.value;
      opt.textContent = it.label;
      opt.title = it.usefulness + ' ' + it.effect;
      sel.append(opt);
    });
    if (!items.length) {
      hint.textContent = 'پیش‌فرضی نیست — مسیر تایپ کنید.';
      hint.title = 'سرور ریشه/سنجاق/تازه‌ای برنگرداند.';
    }
  } catch(e) {
    hint.textContent = 'پیش‌فرض‌ها خوانده نشد — مسیر تایپ کنید.';
    hint.title = String((e && e.message) || e);
  }
}
async function applyPreset() {
  const sel = el('data-dialog-preset');
  const value = String((sel && sel.value) || '').trim();
  if (!value) {
    fail('پیش‌فرضی برگزیده نشده است.', undefined, null);
    return;
  }
  const verdict = await validateCustomPath(value, mode === 'dest' ? 'dir' : 'file');
  if (!verdict.ok) {
    fail(verdict.error, value, applyPreset);
    return;
  }
  fillInput(callerId, verdict.path, mode === 'dest' ? 'dir' : 'file');
  closeDataDialog();
}
async function applyCustom() {
  const input = el('data-dialog-custom');
  const raw = String((input && input.value) || '').trim();
  if (!raw) {
    fail('مسیر خالی است — یک مسیر بنویسید یا پیش‌فرضی برگزینید.', undefined, null);
    return;
  }
  const verdict = await validateCustomPath(raw, mode === 'dest' ? 'dir' : 'file');
  if (!verdict.ok) {
    fail(verdict.error, raw, applyCustom);
    return;
  }
  fillInput(callerId, verdict.path, mode === 'dest' ? 'dir' : 'file');
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
    clearPinsCache();
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
    const pins = await listPins();
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
      chip.append(ltrCode((p && p.name) || '—'));
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
          clearPinsCache();
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
    clearPinsCache();
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
/* ── P05: فرمان‌بر لنگردار PICKING-ONLY ──
   لایه موقت کنار نقطه فراخوان (نخست A1/A2 غربالگری): سه گروه
   سنجاق/تازه/مسیر از مدیر یکپارچه، پالایش سمت‌کاربر (بدون فراخوانی
   سرور)، ردیف‌های دوسطری (نام + جمله سودمندی / حقایق همان ریشه +
   خط اثر)، تک‌ایست تب، چرخش بالا/پایین، Enter گزینش، Escape انصراف
   با بازگشت فوکوس به دکمه فراخوان. هرگز اقدام نمی‌کند (بدون دکمه
   ساخت/بارگذاری/تغییرنام/حذف/سنجاق) — فقط ورودی فراخوان را پر می‌کند.
   مرور کامل (ناوبری، نه اقدام) گفت‌وگوی داده را باز می‌کند. */
let cmdMode = 'input';
let cmdCallerId = '';
let cmdInvoker = null;
let cmdItems = [];
let cmdActive = -1;

function cmdPopover() {
  return el('cmd-popover');
}
export function isCmdPopoverOpen() {
  const p = cmdPopover();
  return !!p && !p.hasAttribute('hidden');
}
function cmdErr(message, detail) {
  showFormError('cmd-popover-err', message, detail, null, undefined);
}
/* نام نمایشی ردیف: مسیرها در گره ایزوله لاتین، نام‌های فارسی بی‌واسطه. */
function cmdNameNode(text) {
  const s = String(text === null || text === undefined ? '—' : text);
  if (/[/\\]/.test(s)) return ltrCode(s);
  return document.createTextNode(s);
}
function cmdMatches(item, needle) {
  if (!needle) return true;
  const hay = [item.name, item.value, item.usefulness]
    .map((v) => String(v || '').toLowerCase()).join(' ');
  return hay.indexOf(needle) >= 0;
}
/* سطرهای هر گروه از مدیر: input → فایل‌ها (نماینده همان ریشه برای
   مسیرها)؛ dest → پوشه‌ها. حقایق همیشه همان ریشه (L4). */
async function cmdBuildItems() {
  const dest = (cmdMode === 'dest');
  const effect = 'با انتخاب، در ورودی «' + targetLabel() + '» می‌نشیند.';
  let payload = null;
  try {
    payload = await fetchRoots();
  } catch(e) {
    payload = {roots: []};
  }
  const roots = (payload && payload.roots) || [];
  const pins = await listPins();
  const recents = listRecents();
  const items = [];
  pins.forEach((p) => {
    if (!p || !p.path) return;
    if (dest && p.kind !== 'dir') return;
    if (!dest && p.kind !== 'file') return;
    const root = matchRoot(p.path, roots);
    const rf = root ? rootFacts(root) : {facts: null, cause: 'unregistered'};
    items.push({group: 'pins', name: p.name, value: p.path,
      kind: p.kind, usefulness: 'سنجاق ذخیره‌شده شما — میان‌بر مسیر پرتکرار.',
      facts: rf.facts, cause: rf.cause, rootPath: root ? root.path : ''});
  });
  recents.forEach((r) => {
    if (!r || !r.path) return;
    if (dest && r.kind !== 'dir') return;
    if (!dest && r.kind !== 'file') return;
    if (items.some((it) => it.value === r.path)) return;
    const root = matchRoot(r.path, roots);
    const rf = root ? rootFacts(root) : {facts: null, cause: 'unregistered'};
    items.push({group: 'recents', name: r.path, value: r.path,
      kind: r.kind, usefulness: 'به‌تازگی استفاده شده — ادامه کار قبلی.',
      facts: rf.facts, cause: rf.cause, rootPath: root ? root.path : ''});
  });
  roots.forEach((r) => {
    if (!r || !r.path) return;
    const rf = rootFacts(r);
    if (dest) {
      items.push({group: 'paths', name: (r.label || r.path), value: r.path,
        kind: 'dir', usefulness: usefulnessFor(r.label),
        facts: rf.facts, cause: rf.cause, rootPath: r.path});
    } else if (rf.facts && rf.facts.exists && rf.facts.path) {
      items.push({group: 'paths', name: (r.label || r.path), value: rf.facts.path,
        kind: 'file', usefulness: usefulnessFor(r.label),
        facts: rf.facts, cause: rf.cause, rootPath: r.path});
    } else {
      items.push({group: 'paths', name: (r.label || r.path), value: '',
        kind: 'file', usefulness: usefulnessFor(r.label),
        facts: null, cause: rf.cause || 'file-missing', rootPath: r.path,
        disabled: true});
    }
  });
  return {items, roots};
}
function cmdFactsText(item) {
  const line = factsLine(item.facts);
  if (line) return {text: line, title: String((item.facts && item.facts.path) || item.rootPath || '')};
  return {text: '—', title: causeFa(item.cause || 'file-missing')};
}
function cmdRenderRow(item) {
  const li = document.createElement('li');
  li.className = 'cmd-row';
  li.setAttribute('role', 'option');
  li.setAttribute('tabindex', '-1');
  if (item.disabled) {
    li.classList.add('cmd-disabled');
    li.setAttribute('aria-disabled', 'true');
  } else {
    li.setAttribute('aria-selected', 'false');
  }
  const line1 = document.createElement('div');
  line1.className = 'cmd-line1';
  line1.append(cmdNameNode(item.name || '—'));
  const use = document.createElement('span');
  use.className = 'cmd-use';
  use.textContent = ' — ' + String(item.usefulness || '');
  line1.append(use);
  const line2 = document.createElement('div');
  line2.className = 'cmd-line2';
  const facts = cmdFactsText(item);
  const factsSpan = document.createElement('span');
  factsSpan.className = 'cmd-facts';
  factsSpan.textContent = facts.text;
  factsSpan.title = facts.title;
  const effect = document.createElement('span');
  effect.className = 'cmd-effect';
  effect.textContent = ' • ' + ('با انتخاب، در ورودی «' + targetLabel() + '» می‌نشیند.');
  line2.append(factsSpan, effect);
  li.append(line1, line2);
  li.title = String(item.value || item.rootPath || '');
  if (!item.disabled) {
    li.addEventListener('click', () => cmdPick(item));
  }
  return li;
}
function cmdRenderEmpty() {
  const li = document.createElement('li');
  li.className = 'cmd-empty';
  li.textContent = 'در این گروه هم‌خوانی نیست.';
  li.title = 'پالایش جاری هم‌خوانی در این گروه ندارد.';
  return li;
}
async function cmdRender() {
  const filter = el('cmd-popover-filter');
  const needle = String((filter && filter.value) || '').trim().toLowerCase();
  clearFormError('cmd-popover-err');
  const built = await cmdBuildItems();
  cmdItems = built.items.filter((it) => cmdMatches(it, needle));
  const groups = {pins: [], recents: [], paths: []};
  cmdItems.forEach((it) => {
    if (groups[it.group]) groups[it.group].push(it);
  });
  const host = el('cmd-popover-groups');
  if (host) {
    ['pins', 'recents', 'paths'].forEach((key) => {
      const sec = host.querySelector('section[data-group="' + key + '"] ul');
      if (!sec) return;
      sec.replaceChildren();
      if (!groups[key].length) {
        sec.append(cmdRenderEmpty());
      } else {
        groups[key].forEach((it) => sec.append(cmdRenderRow(it)));
      }
    });
  }
  cmdActive = -1;
  cmdPaintActive();
}
function cmdVisibleRows() {
  const p = cmdPopover();
  if (!p) return [];
  return Array.from(p.querySelectorAll('li.cmd-row:not(.cmd-disabled)'));
}
function cmdPaintActive() {
  const rows = cmdVisibleRows();
  rows.forEach((row, idx) => {
    const on = (idx === cmdActive);
    row.classList.toggle('active', on);
    row.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  const browse = el('cmd-popover-browse');
  if (browse) browse.classList.toggle('active', cmdActive === rows.length);
}
function cmdMove(delta) {
  const rows = cmdVisibleRows();
  const total = rows.length + 1; /* + مرور کامل */
  if (!total) return;
  cmdActive = ((cmdActive < 0 ? (delta > 0 ? -1 : 0) : cmdActive) + delta + total) % total;
  cmdPaintActive();
  const all = rows.concat([el('cmd-popover-browse')].filter(Boolean));
  const node = all[cmdActive];
  try {
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({block: 'nearest'});
    }
  } catch(e) {}
}
function cmdActivate() {
  const rows = cmdVisibleRows();
  if (cmdActive === rows.length) {
    const browse = el('cmd-popover-browse');
    if (browse) browse.click();
    return;
  }
  const row = rows[cmdActive];
  if (!row) return;
  const item = cmdRowItem(row, rows);
  if (item) cmdPick(item);
}
function cmdRowItem(row, rows) {
  const pos = Array.prototype.indexOf.call(rows, row);
  const enabled = cmdItems.filter((it) => !it.disabled);
  return enabled[pos] || null;
}
function cmdPick(item) {
  if (!item || item.disabled || !item.value) return;
  if (cmdMode === 'dest') {
    fillInput(cmdCallerId, item.value, 'dir');
    closeCmdPopover(true);
    return;
  }
  /* input: واژه‌های سقف‌دار سرور → A1 (همان قرارداد pickAsInput). */
  callerId = cmdCallerId;
  mode = 'input';
  pickAsInput(item.value);
}
/* لنگر به نقطه فراخوان: زیر دکمه، جا نشد بالا؛ هرگز بیرون نما و
   هرگز روی ستون کنترل (راست‌چین: به چپ می‌لغزد). */
function cmdAnchor(invoker) {
  const p = cmdPopover();
  if (!p || !invoker) return;
  let top = 0, left = 0;
  try {
    const r = invoker.getBoundingClientRect();
    const w = p.offsetWidth || 420;
    const h = p.offsetHeight || 300;
    left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - w - 8));
    top = r.bottom + 8;
    if (top + h > window.innerHeight - 8) {
      top = Math.max(8, r.top - h - 8);
    }
    try {
      const ctl = document.getElementById('screening-controls');
      if (ctl) {
        const c = ctl.getBoundingClientRect();
        const overlap = !(left + w <= c.left || left >= c.right
          || top + h <= c.top || top >= c.bottom);
        if (overlap) {
          left = Math.max(8, c.left - w - 8);
        }
      }
    } catch(e) {}
    p.style.top = Math.max(8, top) + 'px';
    p.style.left = Math.max(8, left) + 'px';
  } catch(e) {}
}
export function openCmdPopover(wantMode, wantCallerId, invoker) {
  cmdMode = (wantMode === 'dest') ? 'dest' : 'input';
  cmdCallerId = String(wantCallerId || '');
  cmdInvoker = invoker || null;
  const p = cmdPopover();
  if (!p) return;
  closeDataDialog();
  p.removeAttribute('hidden');
  const filter = el('cmd-popover-filter');
  if (filter) {
    filter.value = '';
    clearFormError('cmd-popover-err');
  }
  cmdRender();
  cmdAnchor(cmdInvoker);
  try {
    if (filter && typeof filter.focus === 'function') filter.focus();
  } catch(e) {}
}
export function closeCmdPopover(returnFocus) {
  const p = cmdPopover();
  if (!p || p.hasAttribute('hidden')) return; /* بی‌اثر وقتی بسته است */
  p.setAttribute('hidden', '');
  cmdItems = [];
  cmdActive = -1;
  if (returnFocus !== false) {
    /* بازگشت فوکوس به دکمه فراخوان (نه ورودی) — قرارداد P05. */
    const back = cmdInvoker && document.contains(cmdInvoker) ? cmdInvoker : null;
    try {
      if (back && typeof back.focus === 'function') back.focus();
    } catch(e) {}
  }
  cmdInvoker = null;
}
function initCmdPopover() {
  const filter = el('cmd-popover-filter');
  if (filter) {
    filter.addEventListener('input', () => cmdRender());
    filter.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowDown') {
        ev.preventDefault();
        cmdMove(1);
      } else if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        cmdMove(-1);
      } else if (ev.key === 'Enter') {
        ev.preventDefault();
        cmdActivate();
      } else if (ev.key === 'Escape') {
        ev.preventDefault();
        closeCmdPopover(true);
      } else if (ev.key === 'Tab') {
        /* تک‌ایست تب: تب درون لایه می‌ماند. */
        ev.preventDefault();
        try { filter.focus(); } catch(e) {}
      }
    });
  }
  const browse = el('cmd-popover-browse');
  if (browse) {
    browse.addEventListener('click', () => {
      const m = cmdMode, c = cmdCallerId;
      closeCmdPopover(false);
      openDataDialog(m, c);
    });
  }
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && isCmdPopoverOpen()) closeCmdPopover(true);
  });
  document.addEventListener('click', (ev) => {
    if (!isCmdPopoverOpen()) return;
    const p = cmdPopover();
    try {
      if (p && !p.contains(ev.target)
          && !(cmdInvoker && cmdInvoker.contains(ev.target))) {
        /* کلیک بیرون = انصراف با بازگشت فوکوس (قرارداد P05). */
        closeCmdPopover(true);
      }
    } catch(e) {}
  }, true);
  document.addEventListener('hz:close-popover', () => closeCmdPopover(false));
}
/* سیم‌کشی دکمه‌های فراخوان کابین غربالگری (A1/A2) + بستن + عملیات.
   نخستین عرضه فرمان‌بر (P05/Q4): دکمه‌ها فرمان‌بر لنگردار را باز
   می‌کنند؛ گفت‌وگوی کامل از ردیف «مرور کامل…» می‌آید. */
function initDialog() {
  const close = el('data-dialog-close');
  if (close) close.addEventListener('click', closeDataDialog);
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && isDataDialogOpen()) closeDataDialog();
  });
  const pickInput = el('screening-pick-input');
  if (pickInput) {
    pickInput.addEventListener('click', () => openCmdPopover('input', 'screening-words', pickInput));
  }
  const pickDest = el('screening-pick-dest');
  if (pickDest) {
    pickDest.addEventListener('click', () => openCmdPopover('dest', 'screening-out-dir', pickDest));
  }
  const mkdir = el('data-dialog-mkdir');
  if (mkdir) mkdir.addEventListener('click', mkdirCurrent);
  const presetGo = el('data-dialog-preset-pick');
  if (presetGo) presetGo.addEventListener('click', applyPreset);
  const customGo = el('data-dialog-custom-pick');
  if (customGo) customGo.addEventListener('click', applyCustom);
  const upload = el('data-dialog-upload');
  if (upload) upload.addEventListener('click', uploadCurrent);
  const pinAdd = el('data-dialog-pin-add');
  if (pinAdd) pinAdd.addEventListener('click', pinCurrent);
  initCmdPopover();
  initCollisionDialog();
  initCabinAccordion();
}
initDialog();
