import {getJSON, withBusy, errCodeFor, showFormError, clearFormError, faNum, ltrCode} from '../shell/api_client.js';
import {PagedListController} from '../shell/paginated_list_controller.js';
import {selectLinkingTab} from '../shell/view_navigator.js';
/* کنترلر زبانه ۲ — اجرای داوری با پریست:
   GET /api/ai_presets (فهرست فقط‌خواندنی)، POST /api/arbiter/runs،
   نظرسنجی وضعیت، GET …/verdicts (پیوست سروری معنی + نامزدها)،
   GET …/log، POST …/abort، پرش به زبانه ۴.
   برگه‌ها در جدول متراکم درون‌لغزنده (سنس | معنی | نامزد | رأی
   رنگی دامنه | زمان)؛ گزارش زنده در <pre> هم‌تم + سنس جاری و
   ثانیه‌های سپری‌شده (پایان کوری کند-دربرابر-گیرکرده).
   قرارداد نمایشی: textContent/ltrCode (هرگز innerHTML پویا)، faNum،
   withBusy، aria-live روی پیشرفت و شمارش. */
let verdicts = [];
let activeRunId = '';
let pollTimer = null;
let pendingFromRun = null;
function el(id) {
  return document.getElementById(id);
}
function codeFrom(err) {
  const d = String((err && err.message) || err || '');
  const m = d.match(/^([A-Z]+-[\w*]+)/);
  if (m) return m[1];
  return errCodeFor(err);
}
const RUN_STATUS_FA = {running: 'در حال اجرا', done: 'تمام‌شده',
  failed: 'ناموفق', aborted: 'متوقف‌شده', interrupted: 'ناتمام مانده'};
const verdictPager = new PagedListController({
  pagerId: 'arbiter-pager', onPage: () => renderVerdicts()});
function verdictKind(v) {
  if (!v || v.verdict === null || v.verdict === undefined) return 'review';
  return String(v.verdict).trim().toLowerCase() === 'link' ? 'link' : 'none';
}
function verdictLabel(v) {
  const kind = verdictKind(v);
  return kind === 'link' ? 'پیوند' : (kind === 'none' ? 'بدون پیوند' : 'نیازمند بازبینی');
}
function fmtDuration(v) {
  const ms = v && v.duration_ms;
  if (ms === null || ms === undefined || ms === '') return '—';
  const secs = Number(ms) / 1000;
  if (!isFinite(secs)) return '—';
  return faNum(secs.toFixed(1)) + ' ث';
}
function renderVerdicts() {
  const body = el('arbiter-verdict-tbody');
  const count = el('arbiter-verdict-count');
  if (!body) return;
  body.replaceChildren();
  verdictPager.setTotal(verdicts.length);
  if (count) count.textContent = faNum(verdicts.length) + ' برگه';
  const page = verdictPager.pageItems(verdicts);
  if (!page.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'p-meta';
    td.textContent = activeRunId
      ? 'هنوز برگه‌ای نرسیده است.'
      : 'اجرایی شروع نشده است — از «شروع داوری» آغاز کنید.';
    tr.append(td);
    body.append(tr);
    return;
  }
  page.forEach((v) => {
    const tr = document.createElement('tr');
    const sid = document.createElement('td');
    sid.append(ltrCode((v && v.sense_id) || '—'));
    const gloss = document.createElement('td');
    gloss.className = 'ltr-text verdict-gloss';
    gloss.setAttribute('dir', 'ltr');
    gloss.textContent = (v && v.gloss) || '—';
    if (v && v.gloss) gloss.title = v.gloss;
    const target = document.createElement('td');
    const tgt = (v && (v.target_synset || v.winner_sensekey)) || '';
    if (tgt) {
      target.append(ltrCode(tgt));
    } else {
      target.textContent = '—';
    }
    const vote = document.createElement('td');
    const tag = document.createElement('span');
    tag.className = 'vote-tag vote-' + verdictKind(v);
    tag.textContent = verdictLabel(v);
    vote.append(tag);
    if (v && v.model) {
      vote.append(document.createTextNode(' '));
      const model = document.createElement('span');
      model.className = 'p-meta';
      model.append(ltrCode(String(v.model)));
      vote.append(model);
    }
    const dur = document.createElement('td');
    dur.className = 'verdict-dur';
    dur.textContent = fmtDuration(v);
    tr.append(sid, gloss, target, vote, dur);
    body.append(tr);
  });
}
function setRunning(running, runId) {
  const runBtn = el('btn-arbiter-run');
  const abortBtn = el('btn-arbiter-abort');
  const state = el('arbiter-run-state');
  if (runBtn) runBtn.disabled = !!running;
  if (abortBtn) abortBtn.disabled = !running;
  if (state) state.textContent = running ? 'در حال اجرا' : 'بیکار';
  activeRunId = running ? (runId || activeRunId) : '';
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
async function loadLog(runId) {
  const pre = el('arbiter-log');
  if (!pre) return;
  try {
    const j = await getJSON('/api/arbiter/runs/' + encodeURIComponent(runId) + '/log?tail=50');
    const rows = (j && j.log) || [];
    pre.textContent = rows.map((r) =>
      [r.ts || '', r.level || '', r.event || '', r.detail || '']
      .filter(Boolean).join(' ')).join('\n');
    pre.scrollTop = pre.scrollHeight;
  } catch(e) { /* log is advisory; verdicts carry the contract */ }
}
async function pollStatus(runId) {
  stopPolling();
  let job = null;
  try {
    const j = await getJSON('/api/arbiter/runs/' + encodeURIComponent(runId));
    job = (j && j.run) || null;
  } catch(e) {
    showFormError('arbiter-err', 'خواندن وضعیت اجرا ناموفق بود.',
      (e && e.message) || e, () => pollStatus(runId), codeFrom(e));
    setRunning(false);
    return;
  }
  if (!job) {
    setRunning(false);
    return;
  }
  const prog = el('arbiter-progress');
  if (prog) {
    const st = RUN_STATUS_FA[job.status] || String(job.status || '');
    prog.textContent = 'انجام‌شده ' + faNum(job.done || 0) + ' از '
      + faNum(job.total || 0) + ' · نیازمند بازبینی '
      + faNum(job.abstained || 0) + ' · وضعیت: ' + st;
  }
  const cur = el('arbiter-current');
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
  }  setRunning(false);
  await loadVerdicts(runId);
}
async function loadPresets() {
  const sel = el('arbiter-preset');
  if (!sel) return;
  try {
    const j = await getJSON('/api/ai_presets');
    const rows = (j && (j.ai_presets || j.presets)) || [];
    sel.replaceChildren();
    if (!rows.length) {
      const o = document.createElement('option');
      o.value = '';
      o.textContent = 'پریستی نیست — اول در نمای ارائه‌دهندگان بسازید';
      sel.append(o);
      return;
    }
    rows.forEach((r) => {
      const o = document.createElement('option');
      o.value = r.name || '';
      o.textContent = (r.name || '') + ' · ' + (r.provider || '') + ' / ' + (r.model || '');
      sel.append(o);
    });
  } catch(e) {
    showFormError('arbiter-err', 'خواندن پریست‌ها ناموفق بود.',
      (e && e.message) || e, loadPresets, codeFrom(e));
  }
}
async function loadVerdicts(runId) {
  try {
    const j = await getJSON('/api/arbiter/runs/' + encodeURIComponent(runId) + '/verdicts');
    verdicts = (j && j.verdicts) || [];
  } catch(e) {
    verdicts = [];
    showFormError('arbiter-err', 'خواندن برگه‌ها ناموفق بود.',
      (e && e.message) || e, () => loadVerdicts(runId), codeFrom(e));
  }
  verdictPager.reset();
  renderVerdicts();
}
/* Cross-panel entry (unified history): show one run's verdicts without
   starting anything. Exported for the history action only. */
export async function openArbiterRun(runId) {
  const id = String(runId || '').trim();
  if (!id) return;
  stopPolling();
  setRunning(false);
  const prog = el('arbiter-progress');
  if (prog) prog.textContent = '';
  activeRunId = id;
  await pollStatus(id);
}
function renderHandoffNote() {
  const note = el('arbiter-handoff-note');
  if (!note) return;
  note.replaceChildren();
  if (pendingFromRun && pendingFromRun.deferred) {
    note.append(document.createTextNode(
      'ورودی از گزینش مکانیکی: ' + faNum(pendingFromRun.deferred.length)
      + ' سنس نیازمند داوری (اجرای '));
    note.append(ltrCode(pendingFromRun.run_id || ''));
    note.append(document.createTextNode(') — با «شروع داوری» همان‌ها داوری می‌شوند.'));
  }
}
async function startRun(btn) {
  clearFormError('arbiter-err');
  await loadPresets();
  const preset = ((el('arbiter-preset') || {}).value || '').trim();
  if (!preset) {
    showFormError('arbiter-err', 'پریستی انتخاب نشده است (اول پریست بسازید).', '', null);
    return;
  }
  const limitRaw = ((el('arbiter-limit') || {}).value || '').trim();
  await withBusy(btn || el('btn-arbiter-run'), 'در حال شروع…', async () => {
    try {
      const body = {preset: preset};
      if (pendingFromRun && pendingFromRun.run_id) body.from_run = pendingFromRun.run_id;
      else if (limitRaw) body.limit = limitRaw;
      const j = await getJSON('/api/arbiter/runs',
        {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify(body)});
      const run = (j && j.run) || {};
      if (!run.run_id) {
        showFormError('arbiter-err', 'اجرا ساخته نشد (پاسخ سرور ناقص است).', '', null);
        return;
      }
      verdicts = [];
      verdictPager.reset();
      renderVerdicts();
      pendingFromRun = null;
      renderHandoffNote();
      setRunning(true, run.run_id);
      await pollStatus(run.run_id);
    } catch(e) {
      showFormError('arbiter-err', 'شروع داوری ناموفق بود.', (e && e.message) || e,
        () => startRun(), codeFrom(e));
    }
  });
}
async function abortRun(btn) {
  if (!activeRunId) return;
  const runId = activeRunId;
  await withBusy(btn || el('btn-arbiter-abort'), 'در حال توقف…', async () => {
    try {
      await getJSON('/api/arbiter/runs/' + encodeURIComponent(runId) + '/abort', {method: 'POST'});
      stopPolling();
      await pollStatus(runId);
    } catch(e) {
      showFormError('arbiter-err', 'توقف اجرا ناموفق بود.', (e && e.message) || e,
        () => abortRun(), codeFrom(e));
    }
  });
}
document.getElementById('btn-arbiter-run').addEventListener('click', (ev) => startRun(ev.currentTarget));
document.getElementById('btn-arbiter-abort').addEventListener('click', (ev) => abortRun(ev.currentTarget));
document.getElementById('btn-arbiter-jump').addEventListener('click', () => {
  selectLinkingTab(3);
  const card = document.getElementById('supervised-batch-card');
  if (card && typeof card.scrollIntoView === 'function') {
    try { card.scrollIntoView({behavior: 'smooth', block: 'start'}); } catch(e){}
  }
  const title = card && card.querySelector('.p-title');
  if (title) {
    if (!title.hasAttribute('tabindex')) title.setAttribute('tabindex', '-1');
    try { title.focus({preventScroll: true}); } catch(e) {
      try { title.focus(); } catch(_){}
    }
  }
});
document.addEventListener('hz:providers-refreshed', () => loadPresets());
document.addEventListener('hz:mechanical-handoff', (ev) => {
  try {
    const d = (ev && ev.detail) || {};
    if (d.run_id && Array.isArray(d.deferred) && d.deferred.length) {
      pendingFromRun = {run_id: String(d.run_id), deferred: d.deferred};
      renderHandoffNote();
    }
  } catch(e) {}
});
document.addEventListener('hz:linking-tab', (ev) => {
  try {
    if (ev && ev.detail && ev.detail.index === 2) loadPresets();
  } catch(e) {}
});
loadPresets();
renderVerdicts();
