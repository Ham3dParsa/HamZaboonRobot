import {getJSON, withBusy, errCodeFor, showFormError, clearFormError, faNum, ltrCode} from '../shell/api_client.js';
import {PagedListController} from '../shell/paginated_list_controller.js';
import {selectLinkingTab} from '../shell/view_navigator.js';
/* کنترلر زبانه ۲ — اجرای داوری با پریست (P4):
   GET /api/judge_presets (فهرست فقط‌خواندنی)، POST /api/arbiter/runs،
   نظرسنجی وضعیت، GET …/verdicts، POST …/abort، پرش به زبانه ۴.
   قرارداد نمایشی: textContent/ltrCode (هرگز innerHTML پویا)، faNum،
   جعبه سه‌بخشی، withBusy، aria-live روی پیشرفت و شمارش. */
let verdicts = [];
let activeRunId = '';
let pollTimer = null;
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
function verdictLabel(v) {
  if (!v || v.verdict === null || v.verdict === undefined) return 'نیازمند بازبینی';
  const norm = String(v.verdict).trim().toLowerCase();
  return norm === 'link' ? 'پیوند' : 'بدون پیوند';
}
function renderVerdicts() {
  const box = el('arbiter-verdict-list');
  const count = el('arbiter-verdict-count');
  if (!box) return;
  box.replaceChildren();
  verdictPager.setTotal(verdicts.length);
  if (count) count.textContent = faNum(verdicts.length) + ' برگه';
  const page = verdictPager.pageItems(verdicts);
  if (!page.length) {
    const empty = document.createElement('div');
    empty.className = 'p-meta';
    empty.textContent = activeRunId
      ? 'هنوز برگه‌ای نرسیده است.'
      : 'اجرایی شروع نشده است — از «شروع داوری» آغاز کنید.';
    box.append(empty);
    return;
  }
  page.forEach((v) => {
    const line = document.createElement('div');
    line.className = 'queue-item';
    const wrap = document.createElement('div');
    const b = document.createElement('b');
    b.className = 'code-token';
    b.textContent = (v && v.sense_id) || '—';
    const gloss = document.createElement('div');
    gloss.className = 'queue-gloss ltr-text';
    gloss.setAttribute('dir', 'ltr');
    const target = (v && v.target_synset) || '';
    gloss.textContent = target || '—';
    gloss.title = gloss.textContent;
    wrap.append(b, gloss);
    const tag = document.createElement('span');
    tag.className = 'status-tag';
    tag.textContent = verdictLabel(v);
    if (v && v.model) {
      const model = document.createElement('span');
      model.className = 'p-meta';
      model.append(ltrCode(String(v.model)));
      wrap.append(model);
    }
    line.append(wrap, tag);
    box.append(line);
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
async function loadPresets() {
  const sel = el('arbiter-preset');
  if (!sel) return;
  try {
    const j = await getJSON('/api/judge_presets');
    const rows = (j && (j.judge_presets || j.presets)) || [];
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
  if (job.status === 'running') {
    pollTimer = setTimeout(() => pollStatus(runId), 1500);
    return;
  }  setRunning(false);
  await loadVerdicts(runId);
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
      if (limitRaw) body.limit = limitRaw;
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
loadPresets();
renderVerdicts();
