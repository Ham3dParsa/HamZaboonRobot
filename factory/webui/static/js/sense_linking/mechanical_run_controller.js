import {getJSON, withBusy, errCodeFor, showFormError, clearFormError, faNum, ltrCode} from '../shell/api_client.js';
import {selectLinkingTab} from '../shell/view_navigator.js';
/* کنترلر زبانه ۱ — گزینش مکانیکی (R1–R4+R7):
   POST /api/mechanical/runs، نظرسنجی وضعیت، GET …/results،
   GET …/log، ارسال موارد نیازمند داوری به زبانه ۲ (رویداد
   hz:mechanical-handoff با شناسه اجرا؛ ساخت اجرای داور با پریست
   در همان زبانه انجام می‌شود).
   قرارداد نمایشی: textContent/ltrCode (هرگز innerHTML پویا)، faNum،
   withBusy، aria-live روی پیشرفت و شمارش؛ گزارش در <pre> هم‌تم. */
let activeRunId = '';
let pollTimer = null;
let lastCounts = null;
function el(id) {
  return document.getElementById(id);
}
function codeFrom(err) {
  const d = String((err && err.message) || err || '');
  const m = d.match(/^([A-Z]+-[\w*]+)/);
  if (m) return m[1];
  return errCodeFor(err);
}
function setRunning(running, runId) {
  const runBtn = el('btn-mechanical-run');
  const abortBtn = el('btn-mechanical-abort');
  const state = el('mechanical-run-state');
  if (runBtn) runBtn.disabled = !!running;
  if (abortBtn) abortBtn.disabled = !running;
  if (state) state.textContent = running ? 'در حال اجرا' : 'بیکار';
  activeRunId = running ? (runId || activeRunId) : activeRunId;
}
function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}
function elapsedSec(startedAt) {
  try {
    const t0 = Date.parse(startedAt || '');
    if (!t0) return null;
    return Math.max(0, Math.round((Date.now() - t0) / 1000));
  } catch(e) { return null; }
}
function renderCounts(job) {
  const box = el('mechanical-counts');
  if (!box || !job) return;
  box.replaceChildren();
  box.append(document.createTextNode(
    'تأیید ' + faNum(job.approved || 0) + ' · رد ' + faNum(job.rejected || 0)
    + ' · نیازمند داوری ' + faNum(job.deferred || 0)));
  const hand = el('btn-mechanical-handoff');
  const n = (job.deferred_ids || []).length;
  if (hand) hand.disabled = !(job.status === 'done' && n > 0);
}
async function loadLog(runId) {
  const pre = el('mechanical-log');
  if (!pre) return;
  try {
    const j = await getJSON('/api/mechanical/runs/' + encodeURIComponent(runId) + '/log?tail=50');
    const rows = (j && j.log) || [];
    pre.textContent = rows.map((r) =>
      [r.ts || '', r.level || '', r.event || '', r.detail || '']
      .filter(Boolean).join(' ')).join('\n');
    pre.scrollTop = pre.scrollHeight;
  } catch(e) { /* log is advisory; the counts carry the contract */ }
}
async function pollStatus(runId) {
  stopPolling();
  let job = null;
  try {
    const j = await getJSON('/api/mechanical/runs/' + encodeURIComponent(runId));
    job = (j && j.run) || null;
  } catch(e) {
    showFormError('mechanical-err', 'خواندن وضعیت اجرا ناموفق بود.',
      (e && e.message) || e, () => pollStatus(runId), codeFrom(e));
    setRunning(false);
    return;
  }
  if (!job) {
    setRunning(false);
    return;
  }
  lastCounts = job;
  renderCounts(job);
  const prog = el('mechanical-progress');
  if (prog) {
    prog.textContent = 'انجام‌شده ' + faNum(job.done || 0) + ' از '
      + faNum(job.total || 0);
  }
  const cur = el('mechanical-current');
  if (cur) {
    const secs = elapsedSec(job.started_at);
    const curSense = (job.current_sense || '').trim();
    cur.textContent = job.status === 'running'
      ? ('سنس جاری: ' + (curSense || '…') + ' · سپری‌شده: '
        + (secs === null ? '…' : faNum(secs) + ' ثانیه'))
      : '';
  }
  await loadLog(runId);
  if (job.status === 'running') {
    pollTimer = setTimeout(() => pollStatus(runId), 1500);
    return;
  }
  setRunning(false);
  activeRunId = '';
}
/* Cross-panel entry (unified history): show one run's counts without
   starting anything. Exported for the history action only. */
export async function openMechanicalRun(runId) {
  const id = String(runId || '').trim();
  if (!id) return;
  stopPolling();
  setRunning(false);
  activeRunId = id;
  await pollStatus(id);
}
async function startRun(btn) {
  clearFormError('mechanical-err');
  const limitRaw = ((el('mechanical-limit') || {}).value || '').trim();
  await withBusy(btn || el('btn-mechanical-run'), 'در حال شروع…', async () => {
    try {
      const body = {};
      if (limitRaw) body.limit = limitRaw;
      const j = await getJSON('/api/mechanical/runs',
        {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify(body)});
      const run = (j && j.run) || {};
      if (!run.run_id) {
        showFormError('mechanical-err', 'اجرا ساخته نشد (پاسخ سرور ناقص است).', '', null);
        return;
      }
      lastCounts = null;
      const hand = el('btn-mechanical-handoff');
      if (hand) hand.disabled = true;
      setRunning(true, run.run_id);
      await pollStatus(run.run_id);
    } catch(e) {
      showFormError('mechanical-err', 'شروع گزینش ناموفق بود.', (e && e.message) || e,
        () => startRun(), codeFrom(e));
    }
  });
}
async function abortRun(btn) {
  if (!activeRunId) return;
  const runId = activeRunId;
  await withBusy(btn || el('btn-mechanical-abort'), 'در حال توقف…', async () => {
    try {
      await getJSON('/api/mechanical/runs/' + encodeURIComponent(runId) + '/abort', {method: 'POST'});
      stopPolling();
      await pollStatus(runId);
    } catch(e) {
      showFormError('mechanical-err', 'توقف اجرا ناموفق بود.', (e && e.message) || e,
        () => abortRun(), codeFrom(e));
    }
  });
}
function handoff() {
  if (!lastCounts || !lastCounts.run_id) return;
  const ids = lastCounts.deferred_ids || [];
  if (!ids.length) return;
  try {
    document.dispatchEvent(new CustomEvent('hz:mechanical-handoff',
      {detail: {run_id: lastCounts.run_id, deferred: ids}}));
  } catch(e) {}
  selectLinkingTab(2);
}
document.getElementById('btn-mechanical-run').addEventListener('click', (ev) => startRun(ev.currentTarget));
document.getElementById('btn-mechanical-abort').addEventListener('click', (ev) => abortRun(ev.currentTarget));
document.getElementById('btn-mechanical-handoff').addEventListener('click', () => handoff());
document.addEventListener('hz:linking-tab', (ev) => {
  try {
    if (ev && ev.detail && ev.detail.index === 1 && activeRunId) pollStatus(activeRunId);
  } catch(e) {}
});
renderCounts({approved: 0, rejected: 0, deferred: 0, deferred_ids: [], status: 'idle'});
