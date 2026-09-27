import {getJSON, withBusy, errCodeFor, showFormError, clearFormError, faNum, ltrCode} from '../shell/api_client.js';
import {openView} from '../shell/view_navigator.js';
import {FilterableListController} from '../shell/filterable_list_controller.js';
/* پرش کارت → کاوشگر: ارائه‌دهنده در فرم پریست، سقف‌های پیش‌فرض،
   دریافت مدل‌ها، باز شدن دیالوگ مرکزی کاوشگر */
function openModelPicker() {
  const dlg = document.getElementById('model-picker');
  if (!dlg) return;
  if (typeof dlg.showModal === 'function') {
    if (!dlg.open) {
      try { dlg.showModal(); } catch(e) {
        try { dlg.show(); } catch(_){}
      }
    }
  } else {
    dlg.setAttribute('open', '');
  }
  const target = document.getElementById('preset-model-filter');
  if (target) {
    try { target.focus({preventScroll: true}); } catch(e) {
      try { target.focus(); } catch(_){}
    }
  }
}
function closeModelPicker() {
  const dlg = document.getElementById('model-picker');
  if (!dlg || !dlg.open) return;
  try {
    if (typeof dlg.close === 'function') dlg.close();
    else dlg.removeAttribute('open');
  } catch(e){}
}
async function jumpProviderToExplorer(name) {
  const sel = document.getElementById('preset-provider');
  if (sel) sel.value = name;
  applyPresetCapsDefaults(name);
  openView('view-providers');
  try { await fetchPresetModels(); } catch(e){}
  openModelPicker();
}
/* فرم پریست مدل: گزینه‌ها و قفل‌ها از engine_info + سقف‌های قابل ویرایش */
let presetModels = [];
let presetModelQuery = '';
let presetFreeOnly = false;
function presetModelIsFree(id) {
  return /free/i.test(id || '');
}
function presetModelMatches(id, q) {
  const needle = (q !== undefined && q !== null ? q : presetModelQuery || '').trim().toLowerCase();
  if (presetFreeOnly && !presetModelIsFree(id)) return false;
  if (!needle) return true;
  return (id || '').toLowerCase().includes(needle);
}
function applyPresetCapsDefaults(name) {
  const rpmEl = document.getElementById('preset-rpm');
  const rphEl = document.getElementById('preset-rph');
  const rpdEl = document.getElementById('preset-rpd');
  const noteEl = document.getElementById('preset-caps-note');
  /* هر سه ورودی سقف همیشه جای‌نما (placeholder) صریح دارند:
     خالی یعنی نامحدود — مقدارهای هوشمند زیر فقط پیشنهادند و هرگز
     مقدار تایپ‌شده اپراتور را بازنویسی نمی‌کنند (پرشدن تنها در
     فیلد خالی، تا سقف‌های واردشده پیش از ذخیره گم نشوند) */
  if (rpmEl) rpmEl.placeholder = 'خالی = بدون سقف (نامحدود)';
  if (rphEl) rphEl.placeholder = 'خالی = بدون سقف (نامحدود)';
  if (rpdEl) rpdEl.placeholder = 'خالی = بدون سقف (نامحدود)';
  const rpmPristine = rpmEl && !(rpmEl.value || '').trim();
  const rphPristine = rphEl && !(rphEl.value || '').trim();
  if ((name || '').toLowerCase() === 'kilo') {
    if (rpmPristine) rpmEl.value = '';
    if (rphPristine) rphEl.value = '200';
    if (noteEl) noteEl.textContent = 'در پاسخ‌های سهمیه: چرخه خطا با جابه‌جایی تونل یا نشانی ادامه می‌دهد.';
  } else {
    if (rpmPristine) rpmEl.value = '15';
    if (rphPristine) rphEl.value = '';
    if (noteEl) noteEl.textContent = 'در پاسخ‌های سهمیه: چرخه خطا با چرخش کلید ادامه می‌دهد.';
  }
}
function renderPresetModels() {
  const list = document.getElementById('preset-model-list');
  const count = document.getElementById('preset-models-count');
  list.replaceChildren();
  const visible = (presetModels || []).filter((id) => presetModelMatches(id));
  if (count) count.textContent = faNum(visible.length) + ' از ' + faNum(presetModels.length) + ' مدل فعال';
  visible.forEach((id) => {
    const row = document.createElement('div');
    row.className = 'model-row';
    row.dataset.modelId = id;
    const span = document.createElement('span');
    span.className = 'model-id code-token';
    span.dir = 'ltr';
    span.textContent = id;
    span.title = id;
    row.append(span);
    if (presetModelIsFree(id)) {
      const badge = document.createElement('span');
      badge.className = 'free-badge';
      badge.textContent = 'رایگان';
      row.append(badge);
    }
    const adopt = document.createElement('button');
    adopt.className = 'btn-select-candidate model-adopt';
    adopt.type = 'button';
    adopt.textContent = 'نشاندن در مدل';
    adopt.addEventListener('click', () => {
      document.getElementById('preset-model').value = id;
      closeModelPicker();
    });
    row.append(adopt);
    list.append(row);
  });
}
/* نمونه‌سازی دوم کاوشگر مدل: ورودی preset-model-filter + ظرف preset-model-list
   (ساخته‌شدن پس از تعریف کلاس، کنار نمونه صف داوری) */
let presetModelFilterCtl = null;
function renderPresetForm(info, rates) {
  const sel = document.getElementById('preset-provider');
  sel.replaceChildren();
  for (const name of (info.providers || [])) {
    const o = document.createElement('option');
    o.value = name; o.textContent = name;
    sel.append(o);
  }
  sel.onchange = () => applyPresetCapsDefaults(sel.value);
  applyPresetCapsDefaults(sel.value || ((info.providers || [])[0] || ''));
  const temp = (info.temperature || {});
  document.getElementById('preset-temp').value =
    faNum(temp.fixed) + (temp.supported ? '' : ' (قفل قطعی داوری)');
  document.getElementById('preset-temp-note').textContent =
    temp.supported ? 'دما پشتیبانی می‌شود' : 'دما قفل روی ' + faNum(temp.fixed);
  const chip = document.getElementById('preset-free-chip');
  if (chip && !chip.dataset.wired) {
    chip.dataset.wired = '1';
    chip.addEventListener('click', () => {
      presetFreeOnly = !presetFreeOnly;
      chip.classList.toggle('active', presetFreeOnly);
      chip.setAttribute('aria-pressed', presetFreeOnly ? 'true' : 'false');
      renderPresetModels();
    });
  }
  renderPresetModels();
}
async function fetchPresetModels() {
  const errEl = document.getElementById('preset-models-err');
  const legacyBox = document.getElementById('preset-models');
  const btn = document.getElementById('btn-fetch-models');
  const idleText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'در حال دریافت…'; }
  clearFormError('preset-models-err');
  const name = document.getElementById('preset-provider').value;
  presetModels = [];
  renderPresetModels();
  if (legacyBox) legacyBox.textContent = '…';
  try {
    const j = await getJSON('/api/providers/' + encodeURIComponent(name) + '/models');
    presetModels = j.models || [];
    if (legacyBox) legacyBox.textContent = presetModels.length ? presetModels.join(', ') : 'فهرستی برنگشت';
    if (presetModelFilterCtl) presetModelFilterCtl.apply();
    else renderPresetModels();
  } catch(e) {
    presetModels = [];
    renderPresetModels();
    if (legacyBox) legacyBox.textContent = '';
    showFormError('preset-models-err', 'دریافت فهرست مدل‌ها ناموفق بود.', (e && e.message) || e, fetchPresetModels, errCodeFor(e));
    clearFormError('preset-err');
  }
  finally { if (btn) { btn.disabled = false; btn.textContent = idleText; } }
}
/* ذخیره پریست داوری: مقادیر فرم به مسیر سرور (مسیر موجود، بدون تکثیر) */
/* هویت ویرایش: پس از «نشاندن در فرم»، نام واقعی رکورد در
   judgeEditName می‌ماند تا ذخیره بعدی همان رکورد را به‌روزرسانی کند؛
   تغییر برچسب یعنی تغییرنام (سرور مهاجرت می‌دهد)، نه رکورد دوم. */
let judgeEditName = '';
function presetScopeValue() {
  const checked = document.querySelector('input[name="preset-scope"]:checked');
  return (checked && checked.value) || 'model';
}
function setPresetScopeValue(scope) {
  const want = (scope || 'model').toLowerCase();
  document.querySelectorAll('input[name="preset-scope"]').forEach((el) => {
    el.checked = (el.value === want);
  });
}
async function saveJudgePreset(btn) {
  const noteEl = document.getElementById('preset-save-note');
  clearFormError('preset-err');
  if (noteEl) noteEl.textContent = '';
  const label = ((document.getElementById('preset-label') || {}).value || '').trim();
  const fields = {
    name: label || 'console-judge',
    label: label,
    provider: (document.getElementById('preset-provider') || {}).value || '',
    model: ((document.getElementById('preset-model') || {}).value || '').trim(),
    max_rpm: ((document.getElementById('preset-rpm') || {}).value || '').trim(),
    max_rph: ((document.getElementById('preset-rph') || {}).value || '').trim(),
    max_daily: ((document.getElementById('preset-rpd') || {}).value || '').trim(),
    rate_scope: presetScopeValue(),
    temperature: ((document.getElementById('preset-temp') || {}).value || '').trim(),
  };
  /* هویت ویرایش rides همین ذخیره: فرمِ نشانده‌شده همان رکورد را
     به‌روزرسانی می‌کند (تغییر برچسب = تغییرنامِ بدون تکثیر) */
  if (judgeEditName) fields.previous_name = judgeEditName;
  await withBusy(btn || document.getElementById('btn-save-judge-preset'), 'در حال ذخیره…', async () => {
  try {
    const j = await getJSON('/api/judge_presets',
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(fields)});
    const rec = (j && (j.judge_preset || j.preset)) || {};
    judgeEditName = rec.name || fields.name;
    if (noteEl) noteEl.textContent = 'پریست داوری ذخیره شد (نسخه ' + faNum(rec.version || 1) + ').';
    await refreshJudgeCatalog();
  } catch(e) { showFormError('preset-err', 'ذخیره پریست داوری ناموفق بود.', (e && e.message) || e, () => saveJudgePreset(), errCodeFor(e)); }
  });
}
/* فهرست پریست‌های ذخیره‌شده: خواندن از مسیر موجود judge-presets،
   حذف + نشاندن در فرم — بدون مسیر تازه سمت سرور */
function capCell(value) {
  const td = document.createElement('td');
  const n = parseInt(value || '0', 10);
  td.textContent = (n > 0) ? faNum(n) : 'نامحدود';
  return td;
}
const RATE_SCOPE_FA = {model: 'مدل', address: 'نشانی', account: 'حساب'};
export async function refreshJudgeCatalog() {
  const tb = document.getElementById('preset-catalog-tbody');
  const count = document.getElementById('preset-catalog-count');
  const noteEl = document.getElementById('preset-catalog-note');
  if (!tb) return;
  tb.replaceChildren();
  if (noteEl) noteEl.textContent = '';
  try {
    const j = await getJSON('/api/judge_presets');
    const rows = (j && (j.judge_presets || j.presets)) || [];
    if (count) count.textContent = faNum(rows.length) + ' پریست';
    if (!rows.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 8;
      td.textContent = 'پریستی ذخیره نشده است — فرم بالا را پر کنید و ذخیره کنید.';
      tr.append(td);
      tb.append(tr);
      return;
    }
    for (const r of rows) {
      const tr = document.createElement('tr');
      const tdName = document.createElement('td');
      tdName.append(ltrCode(r.name || '—'));
      if (r.label && r.label !== r.name) {
        const sub = document.createElement('div');
        sub.className = 'p-meta';
        sub.textContent = r.label;
        tdName.append(sub);
      }
      const tdProv = document.createElement('td');
      tdProv.append(ltrCode(r.provider || '—'));
      const tdModel = document.createElement('td');
      tdModel.append(ltrCode(r.model || '—'));
      tr.append(tdName, tdProv, tdModel,
        capCell(r.max_rpm), capCell(r.max_rph), capCell(r.max_daily));
      const tdScope = document.createElement('td');
      tdScope.textContent = RATE_SCOPE_FA[r.rate_scope] || RATE_SCOPE_FA.model;
      tr.append(tdScope);
      const tdAct = document.createElement('td');
      const loadBtn = document.createElement('button');
      loadBtn.className = 'btn-skip-next';
      loadBtn.type = 'button';
      loadBtn.textContent = 'نشاندن در فرم';
      loadBtn.addEventListener('click', () => loadJudgePresetIntoForm(r.name || ''));
      const delBtn = document.createElement('button');
      delBtn.className = 'btn-reject-all';
      delBtn.type = 'button';
      delBtn.textContent = 'حذف';
      delBtn.addEventListener('click', (ev) => deleteJudgePreset(r.name || '', ev.currentTarget));
      tdAct.append(loadBtn, document.createTextNode(' '), delBtn);
      tr.append(tdAct);
      tb.append(tr);
    }
  } catch(e) {
    if (count) count.textContent = 'نامشخص';
    if (noteEl) noteEl.textContent = 'خواندن فهرست پریست‌ها ناموفق بود: ' + ((e && e.message) || e);
  }
}
function loadJudgePresetIntoForm(name) {
  getJSON('/api/judge_presets').then((j) => {
    const rows = (j && (j.judge_presets || j.presets)) || [];
    const rec = rows.find((r) => (r.name || '') === name);
    if (!rec) return;
    /* هویت ویرایش از همین‌جا قفل می‌شود: ذخیره بعدی، حتی با برچسب
       عوض‌شده، همان رکورد را جابه‌جا می‌کند — رکورد دوم ساخته نمی‌شود */
    judgeEditName = rec.name || '';
    const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ''; };
    setVal('preset-label', (rec.label && rec.label !== rec.name) ? rec.label : ((rec.name === 'console-judge') ? '' : (rec.name || '')));
    const sel = document.getElementById('preset-provider');
    if (sel && rec.provider) sel.value = rec.provider;
    setVal('preset-model', rec.model);
    setPresetScopeValue(rec.rate_scope);
    applyPresetCapsDefaults(sel ? sel.value : '');
    /* نشاندن، مقدارهای هوشمند را بازنویسی می‌کند — سقف‌های ذخیره‌شده
       پس از اعمال پیش‌فرض بازگردانده می‌شوند تا فرم همان رکورد شود */
    setVal('preset-rpm', (parseInt(rec.max_rpm || '0', 10) > 0) ? String(rec.max_rpm) : '');
    setVal('preset-rph', (parseInt(rec.max_rph || '0', 10) > 0) ? String(rec.max_rph) : '');
    setVal('preset-rpd', (parseInt(rec.max_daily || '0', 10) > 0) ? String(rec.max_daily) : '');
    const noteEl = document.getElementById('preset-save-note');
    if (noteEl) noteEl.textContent = 'پریست «' + (rec.name || '') + '» در فرم نشانده شد — ذخیره، نسخه تازه می‌سازد.';
  }).catch(() => {});
}
async function deleteJudgePreset(name, btn) {
  if (!name) return;
  if (!confirm('پریست «' + name + '» حذف شود؟ این کار برگشت‌ناپذیر است — برای ساخت دوباره باید فرم را از نو پر کنید.')) return;
  clearFormError('preset-err');
  await withBusy(btn, 'در حال حذف…', async () => {
    try {
      await getJSON('/api/judge_presets/' + encodeURIComponent(name), {method: 'DELETE'});
      if (judgeEditName === name) judgeEditName = '';
      await refreshJudgeCatalog();
    } catch(e) { showFormError('preset-err', 'حذف پریست ناموفق بود.', (e && e.message) || e, () => deleteJudgePreset(name), errCodeFor(e)); }
  });
}
presetModelFilterCtl = new FilterableListController(
  'preset-model-filter', 'preset-model-list',
  function(row, i, q) { return presetModelMatches(typeof row === 'string' ? row : (row && row.id) || '', q); },
  function(q) { presetModelQuery = q || ''; renderPresetModels(); });
document.getElementById('btn-fetch-models').addEventListener('click', fetchPresetModels);
document.getElementById('btn-open-model-picker').addEventListener('click', async () => {
  openModelPicker();
  try { await fetchPresetModels(); } catch(e){}
});
document.getElementById('btn-close-model-picker').addEventListener('click', closeModelPicker);
(function wireModelDialogBackdrop() {
  const dlg = document.getElementById('model-picker');
  if (!dlg) return;
  dlg.addEventListener('click', (ev) => {
    if (ev.target === dlg) closeModelPicker();
  });
})();
document.getElementById('btn-save-judge-preset').addEventListener('click', (ev) => saveJudgePreset(ev.currentTarget));
document.addEventListener('hz:providers-refreshed', (ev) => {
  const detail = (ev && ev.detail) || {};
  renderPresetForm(detail.info || {}, detail.rateRows || []);
});
