import {getJSON, withBusy, faNum, showFormError, clearFormError, ltrCode} from '../shell/api_client.js';
import {openView} from '../shell/view_navigator.js';
import {loadScreened} from '../sense_linking/human_review_controller.js';
/* کابین غربالگری کایکی (W3): میدان واژه‌ها + میان‌بر واژه‌های دود،
   شروع/توقف روی قرارداد قفل‌شده /api/screening/*، نظرسنجی وضعیت هر
   ۱ ثانیه حین اجرا، جعبه گزارش <pre>، کارت‌های سنج از manifest،
   تحویل خروجی به کابین پیوندزنی از مسیر loadScreened موجود.
   شکل‌های مصرفی (بک‌اند جداگانه می‌نشیند — server.py مال همکار موازی):
   POST /api/screening/run {words?, out_dir?} -> {state, pid}؛
   GET /api/screening/status -> {state, elapsed_s, exit_code, log[],
     manifest?, out_path?}؛ POST /api/screening/abort -> {state}.
   نشت سراسری صفر: همه حالت‌ها در دامنه ماژول، بدون window.*. */
const SMOKE_WORDS = 'run,light,take,get,make';
const POLL_MS = 1000;
const MAX_POLL_ERRORS = 3;
const STATE_FA = {idle: 'بیکار', running: 'در حال اجرا',
  completed: 'تکمیل شد', failed: 'ناموفق بود'};
let pollTimer = 0;
let pollInflight = false;
let pollErrors = 0;
let runActive = false;
let lastOutPath = '';
/* بک‌اند واقعی زیر کلید screening با status/elapsed/out_dir جواب
   می‌دهد؛ این نرمالایزر هر دو شکل را به شکل مصرفی کنترلر می‌نگارد. */
function normStatus(raw) {
  const s = (raw && raw.screening) || raw || {};
  return {
    state: s.status || s.state || 'idle',
    elapsed_s: (s.elapsed_s !== undefined && s.elapsed_s !== null)
      ? s.elapsed_s : s.elapsed,
    exit_code: (s.exit_code !== undefined) ? s.exit_code : null,
    log: s.log || [],
    manifest: s.manifest || null,
    out_path: s.out_path || s.out_dir || ''
  };
}
function el(id) {
  return document.getElementById(id);
}
function metricVal(id, value) {
  const node = el(id);
  if (!node) return;
  if (value === null || value === undefined) {
    node.textContent = '—';
    node.removeAttribute('title');
  } else {
    node.textContent = faNum(value);
    node.removeAttribute('title');
  }
}
function honestVal(id, note) {
  const node = el(id);
  if (!node) return;
  node.textContent = '—';
  node.title = note;
}
function setRunning(on) {
  runActive = on;
  const start = el('screening-start');
  const abort = el('screening-abort');
  if (start) start.disabled = on;
  if (abort) abort.disabled = !on;
  if (!on) stopPolling();
}
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = 0;
  }
  pollInflight = false;
}
function renderLog(lines) {
  const box = el('screening-log');
  if (!box) return;
  box.replaceChildren();
  if (!lines || !lines.length) {
    box.textContent = 'گزارشی از سرور نرسید.';
    return;
  }
  box.textContent = lines.join('\n');
  box.scrollTop = box.scrollHeight;
}
/* تفکیک حذف دوقلو در برابر اسم خاص از سایدکار علت‌ها، در صورت وجود:
   manifest.drop_reasons نگاشت {علت: تعداد} یا manifest.drops آرایه
   [{reason}]؛ R3 دوقلو/تکراری، R2 اسم خاص؛ بقیه «سایر». بدون
   سایدکار، خالی صادقانه (null) — هرگز عدد ساختگی. */
function splitDropReasons(manifest) {
  const src = (manifest && (manifest.drop_reasons || manifest.drops)) || null;
  if (!src) return null;
  let twins = 0, proper = 0;
  const put = (reason, n) => {
    const r = String(reason || '');
    if (/twin|duplicat|dedup|r3/i.test(r)) twins += n;
    else if (/proper|propn|\bname\b|r2/i.test(r)) proper += n;
  };
  if (Array.isArray(src)) {
    src.forEach((d) => put(d && (d.reason || d.kind || d.rule), 1));
  } else if (typeof src === 'object') {
    Object.entries(src).forEach(([k, v]) => put(k, Number(v) || 0));
  } else {
    return null;
  }
  return {twins, proper};
}
function renderMetrics(manifest) {
  const per = (manifest && manifest.per_lemma) || [];
  if (!manifest) {
    ['screening-m-input', 'screening-m-kept', 'screening-m-dropped']
      .forEach((id) => metricVal(id, null));
    honestVal('screening-m-twins', 'سرور تفکیک علت ثبت نکرد');
    honestVal('screening-m-proper', 'سرور تفکیک علت ثبت نکرد');
    renderPerLemma([]);
    return;
  }
  const sum = (key) => per.reduce((n, r) => n + (Number(r[key]) || 0), 0);
  const kept = manifest.kept_total !== undefined ? manifest.kept_total : sum('kept');
  const dropped = manifest.dropped_total !== undefined ? manifest.dropped_total : sum('dropped');
  const input = sum('input_senses') || (Number(kept) || 0) + (Number(dropped) || 0);
  metricVal('screening-m-input', input);
  metricVal('screening-m-kept', kept);
  metricVal('screening-m-dropped', dropped);
  const split = splitDropReasons(manifest);
  if (split) {
    metricVal('screening-m-twins', split.twins);
    metricVal('screening-m-proper', split.proper);
  } else {
    honestVal('screening-m-twins', 'سرور تفکیک علت ثبت نکرد');
    honestVal('screening-m-proper', 'سرور تفکیک علت ثبت نکرد');
  }
  renderPerLemma(per);
}
function renderPerLemma(rows) {
  const tb = el('screening-per-lemma-tbody');
  if (!tb) return;
  tb.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 4;
    td.textContent = 'سنجی از سرور نرسید — پس از اجرای موفق پر می‌شود.';
    tr.append(td);
    tb.append(tr);
    return;
  }
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    const tdLemma = document.createElement('td');
    tdLemma.append(ltrCode(r.lemma || '—'));
    const tdIn = document.createElement('td');
    tdIn.textContent = faNum(r.input_senses !== undefined ? r.input_senses : '—');
    const tdKept = document.createElement('td');
    tdKept.textContent = faNum(r.kept !== undefined ? r.kept : '—');
    const tdDrop = document.createElement('td');
    tdDrop.textContent = faNum(r.dropped !== undefined ? r.dropped : '—');
    tr.append(tdLemma, tdIn, tdKept, tdDrop);
    tb.append(tr);
  });
}
function renderStatus(raw) {
  const st = normStatus(raw);
  const state = st.state || 'idle';
  const badge = el('screening-state');
  if (badge) badge.textContent = STATE_FA[state] || state;
  const elapsed = el('screening-elapsed');
  if (elapsed) {
    elapsed.textContent = (st && st.elapsed_s !== null && st.elapsed_s !== undefined)
      ? faNum(st.elapsed_s) + ' ثانیه' : '—';
  }
  const out = el('screening-out-path');
  if (out) {
    out.replaceChildren();
    out.append(document.createTextNode((st && st.out_path) || '—'));
  }
  if (st && st.out_path) lastOutPath = st.out_path;
  renderLog(st && st.log);
  if (st && st.manifest) renderMetrics(st.manifest);
  const line = el('screening-status');
  if (line) {
    if (state === 'running') {
      line.textContent = 'در حال اجرا… گزارش زیر زنده به‌روز می‌شود.';
    } else if (state === 'completed') {
      line.textContent = 'اجرا تکمیل شد'
        + ((st && st.exit_code !== undefined && st.exit_code !== null)
          ? ' (کد خروج ' + faNum(st.exit_code) + ')' : '')
        + ((st && st.out_path) ? ' — خروجی آماده تحویل است.' : '.');
    } else if (state === 'failed') {
      line.textContent = 'اجرا ناموفق بود'
        + ((st && st.exit_code !== undefined && st.exit_code !== null)
          ? ' (کد خروج ' + faNum(st.exit_code) + ')' : '')
        + ' — گزارش بالا را ببینید.';
    }
  }
}
async function pollOnce() {
  if (pollInflight) return;
  pollInflight = true;
  try {
    const st = normStatus(await getJSON('/api/screening/status'));
    pollErrors = 0;
    renderStatus(st);
    const state = st.state || 'idle';
    if (state === 'completed' || state === 'failed') {
      const done = state === 'completed';
      const ok = done && !!(st && st.out_path);
      setRunning(false);
      const handoff = el('screening-handoff');
      if (handoff) handoff.disabled = !ok;
      if (!done) {
        showFormError('screening-err', 'اجرای غربالگری ناموفق بود.',
          'exit_code=' + ((st && st.exit_code !== undefined && st.exit_code !== null) ? st.exit_code : '?'),
          pollOnce, undefined);
      }
    }
  } catch(e) {
    pollErrors += 1;
    if (pollErrors >= MAX_POLL_ERRORS) {
      setRunning(false);
      showFormError('screening-err', 'خواندن وضعیت غربالگری ناموفق بود.',
        (e && e.message) || e, pollOnce, undefined);
    }
  } finally {
    pollInflight = false;
  }
}
function startPolling() {
  stopPolling();
  pollErrors = 0;
  pollTimer = setInterval(pollOnce, POLL_MS);
}
async function startRun() {
  if (runActive) return;
  const wordsEl = el('screening-words');
  const words = ((wordsEl && wordsEl.value) || '').trim();
  if (!words) {
    showFormError('screening-err', 'واژه‌ای وارد نشده است.',
      'words is empty', startRun, 'VALIDATION-input');
    return;
  }
  clearFormError('screening-err');
  const handoff = el('screening-handoff');
  if (handoff) handoff.disabled = true;
  lastOutPath = '';
  const started = await withBusy(el('screening-start'), 'در حال شروع…', async () => {
    try {
      await getJSON('/api/screening/run', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({words})});
      return true;
    } catch(e) {
      showFormError('screening-err', 'شروع غربالگری ناموفق بود.',
        (e && e.message) || e, startRun, undefined);
      return false;
    }
  });
  if (!started) return;
  setRunning(true);
  startPolling();
  pollOnce();
}
async function abortRun() {
  if (!runActive) return;
  await withBusy(el('screening-abort'), 'در حال توقف…', async () => {
    try {
      await getJSON('/api/screening/abort', {method: 'POST'});
    } catch(e) {
      showFormError('screening-err', 'توقف غربالگری ناموفق بود.',
        (e && e.message) || e, abortRun, undefined);
    }
  });
  pollOnce();
}
/* تحویل: تازه‌سازی ورودی غربالگری از مسیر موجود، سپس نشاندن بنر
   کابین پیوندزنی روی screened.jsonl خروجی و فعال‌سازی نمای پیوندزنی. */
async function handoffToLinking() {
  if (!lastOutPath) return;
  await loadScreened();
  const banner = el('handoff-path');
  if (banner) banner.textContent = lastOutPath;
  openView('view-linking');
}
export function initScreeningCabin() {
  const smoke = el('screening-smoke');
  if (smoke) smoke.addEventListener('click', () => {
    const wordsEl = el('screening-words');
    if (wordsEl) wordsEl.value = SMOKE_WORDS;
  });
  const start = el('screening-start');
  if (start) start.addEventListener('click', startRun);
  const abort = el('screening-abort');
  if (abort) abort.addEventListener('click', abortRun);
  const handoff = el('screening-handoff');
  if (handoff) handoff.addEventListener('click', handoffToLinking);
  setRunning(false);
}
