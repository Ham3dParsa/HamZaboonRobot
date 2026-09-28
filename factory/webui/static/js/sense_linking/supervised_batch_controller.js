import {getJSON, withBusy, errCodeFor, buildFormError, showFormError, clearFormError, copyReport, faNum, ltrCode} from '../shell/api_client.js';
import {FilterableListController} from '../shell/filterable_list_controller.js';
/* کنترلر بسته‌های داوری تحت نظارت اپراتور (P05، قراردادهای قفل‌شده W2):
   POST /api/batches {size}، GET /api/batches، GET /api/batches/<id>،
   POST /api/batches/<id>/import {answer_sheet}،
   POST /api/batches/<id>/approve {ids}، POST /api/batches/<id>/cancel،
   GET /api/gallery?run=… (HTML) + تاریخچه از GET /api/runs.
   قرارداد نمایشی: همه متن پویا فقط با textContent/ltrCode در DOM می‌نشیند
   (اصل persian-formatting برای وب — هرگز innerHTML با داده پویا)؛ عددها با
   faNum؛ خطاها جعبه سه‌بخشی؛ دکمه‌های سروری withBusy. نشت سراسری صفر:
   همه حالت‌ها در دامنه ماژول، بدون window.*. */
const STATUS_FA = {exported: 'صادرشده', awaiting: 'در انتظار پاسخ',
  partial: 'ناقص', complete: 'کامل', in_review: 'در بازبینی',
  imported: 'واردشده', cancelled: 'لغوشده'};
let batches = [];
let batchFilter = '';
let reviewBatchId = '';
let reviewItems = [];
let repairCache = {};
let initialized = false;
function el(id) {
  return document.getElementById(id);
}
/* کد خطای استاندارد: توکن پیشوندی سرور (VALIDATION-* و…) از متن خطا بیرون
   کشیده می‌شود تا نشان جعبه سه‌بخشی دقیق بماند. */
function codeFrom(err) {
  const d = String((err && err.message) || err || '');
  const m = d.match(/^([A-Z]+-[\w*]+)/);
  if (m) return m[1];
  return errCodeFor(err);
}
function batchMatches(batch, i, q) {
  const needle = (q !== undefined && q !== null ? q : batchFilter || '').trim();
  if (!needle) return true;
  const status = STATUS_FA[batch.status] || String(batch.status || '');
  return String(batch.id || '').includes(needle) || status.includes(needle);
}
/* پالایش زنده فهرست بسته‌ها (شناسه یا وضعیت) — ورودی هرگز بازسازی
   نمی‌شود پس فوکوس حین تایپ می‌ماند؛ بازسازی سطرها هم فوکوس را برمی‌گرداند. */
const batchFilterCtl = new FilterableListController(
  'batch-filter', 'batch-list',
  function(batch, i, q) { return batchMatches(batch, i, q); },
  function(q) { batchFilter = q || ''; renderBatchList(); });
function countsLine(batch) {
  return 'اندازه ' + faNum(batch.size) + ' · ' + faNum(batch.answered || 0)
    + ' پاسخ · ' + faNum(batch.approved || 0) + ' تأیید';
}
function renderBatchList() {
  const box = el('batch-list');
  const note = el('batch-list-note');
  if (!box) return;
  const focusedFilter = document.activeElement && document.activeElement.id === 'batch-filter';
  const selStart = focusedFilter ? document.activeElement.selectionStart : null;
  const selEnd = focusedFilter ? document.activeElement.selectionEnd : null;
  box.replaceChildren();
  const visible = batches.filter((b, i) => batchMatches(b, i));
  const countBadge = el('batch-count');
  if (countBadge) countBadge.textContent = faNum(batches.length) + ' بسته';
  if (note) {
    note.textContent = batches.length
      ? (faNum(visible.length) + ' از ' + faNum(batches.length) + ' بسته')
      : 'بسته‌ای صادر نشده است — از «صدور بسته» شروع کنید.';
  }
  visible.forEach((batch) => {
    box.append(renderBatchRow(batch));
  });
  if (focusedFilter) {
    const input = el('batch-filter');
    if (input) {
      input.focus();
      try {
        if (selStart !== null && selEnd !== null) input.setSelectionRange(selStart, selEnd);
      } catch(e){}
    }
  }
}
function rowNoteBox(row) {
  let slot = row.querySelector('.batch-row-note');
  if (!slot) {
    slot = document.createElement('div');
    slot.className = 'p-meta batch-row-note';
    slot.setAttribute('aria-live', 'polite');
    row.append(slot);
  }
  return slot;
}
function rowError(row, faMessage, detail, retryFn, code) {
  const slot = rowNoteBox(row);
  slot.replaceChildren();
  slot.append(buildFormError(faMessage, detail, retryFn, undefined, code));
}
function rowNote(row, text) {
  const slot = rowNoteBox(row);
  slot.replaceChildren();
  slot.textContent = text;
}
function renderBatchRow(batch) {
  const id = String(batch.id || '');
  const row = document.createElement('div');
  row.className = 'provider-cfg-card';
  row.dataset.batch = id;
  const head = document.createElement('div');
  head.className = 'p-header';
  const title = document.createElement('span');
  title.className = 'p-title code-token';
  title.setAttribute('dir', 'ltr');
  title.textContent = id || '—';
  const chip = document.createElement('span');
  chip.className = 'status-tag';
  chip.textContent = STATUS_FA[batch.status] || String(batch.status || '—');
  head.append(title, chip);
  row.append(head);
  const counts = document.createElement('div');
  counts.className = 'p-meta';
  counts.setAttribute('aria-live', 'polite');
  counts.textContent = countsLine(batch);
  row.append(counts);
  const actions = document.createElement('div');
  actions.style.cssText = 'display: flex; gap: 8px; flex-wrap: wrap;';
  const mkBtn = (label, fn) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn-skip-next';
    b.textContent = label;
    b.addEventListener('click', (ev) => fn(ev.currentTarget));
    actions.append(b);
    return b;
  };
  mkBtn('کپی MD', (btn) => copyBatchMd(id, btn, row));
  mkBtn('دانلود JSON', (btn) => downloadBatchJson(id, btn, row));
  const importBox = buildImportBox(id, row);
  const importToggle = mkBtn('درج پاسخ‌نامه', () => {
    importBox.hidden = !importBox.hidden;
    if (!importBox.hidden) {
      const ta = importBox.querySelector('textarea');
      if (ta) ta.focus();
    } else {
      importToggle.focus();
    }
  });
  mkBtn('بازبینی', (btn) => openReview(id, btn));
  mkBtn('کپی ترمیم', (btn) => copyRepair(id, btn, row));
  mkBtn('لغو', (btn) => cancelBatch(id, btn, row));
  row.append(actions, importBox);
  return row;
}
function buildImportBox(id, row) {
  const box = document.createElement('div');
  box.hidden = true;
  box.style.cssText = 'display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;';
  const ta = document.createElement('textarea');
  ta.className = 'inline-input code-token';
  ta.setAttribute('dir', 'ltr');
  ta.rows = 6;
  ta.style.width = '100%';
  ta.placeholder = '{"model": ..., "prompt_hash": ..., "verdicts": [...]}';
  ta.setAttribute('aria-label', 'پاسخ‌نامه JSON برای بسته ' + id);
  const send = document.createElement('button');
  send.type = 'button';
  send.className = 'btn-select-candidate';
  send.textContent = 'ارسال پاسخ‌نامه';
  send.addEventListener('click', (ev) => submitImport(id, ta, ev.currentTarget, row, box));
  const repair = document.createElement('button');
  repair.type = 'button';
  repair.className = 'btn-skip-next';
  repair.textContent = 'کپی درخواست ترمیم';
  repair.hidden = true;
  repair.addEventListener('click', (ev) => copyRepair(id, ev.currentTarget, row));
  box.append(ta, send, repair);
  return box;
}
async function refreshBatches() {
  clearFormError('batch-err');
  try {
    const j = await getJSON('/api/batches');
    batches = j.batches || [];
    renderBatchList();
  } catch(e) {
    showFormError('batch-err', 'خواندن فهرست بسته‌ها ناموفق بود.',
      (e && e.message) || e, refreshBatches, codeFrom(e));
  }
}
async function issueBatch(btn) {
  clearFormError('batch-err');
  const note = el('batch-issue-note');
  if (note) note.textContent = '';
  const raw = ((el('batch-size') || {}).value || '').trim() || '25';
  const size = Number(raw);
  if (!Number.isInteger(size) || size < 10 || size > 50) {
    showFormError('batch-err', 'اندازه بسته باید عدد صحیح ۱۰ تا ۵۰ باشد (چیزی صادر نشد).',
      'size=' + raw, issueBatch, 'VALIDATION-size');
    return;
  }
  await withBusy(btn || el('btn-issue-batch'), 'در حال صدور…', async () => {
    try {
      const j = await getJSON('/api/batches', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({size})});
      const created = (j && j.batch) || {};
      if (note) {
        note.replaceChildren();
        note.append(document.createTextNode('بسته ' + (created.id || '') + ' صادر شد (اندازه ' + faNum(created.size || size) + ').'));
      }
      await refreshBatches();
    } catch(e) {
      showFormError('batch-err', 'صدور بسته ناموفق بود.',
        (e && e.message) || e, issueBatch, codeFrom(e));
    }
  });
}
async function fetchBatchDetail(id) {
  return getJSON('/api/batches/' + encodeURIComponent(id));
}
async function copyBatchMd(id, btn, row) {
  await withBusy(btn, 'در حال خواندن…', async () => {
    try {
      const j = await fetchBatchDetail(id);
      const md = (j && j.md) || '';
      if (!md) { rowNote(row, 'متن MD این بسته خالی است.'); return; }
      await copyReport(md, btn, 'MD کپی شد');
    } catch(e) {
      rowError(row, 'خواندن بسته ناموفق بود.', (e && e.message) || e,
        () => copyBatchMd(id, null, row), codeFrom(e));
    }
  });
}
async function downloadBatchJson(id, btn, row) {
  await withBusy(btn, 'در حال خواندن…', async () => {
    try {
      const j = await fetchBatchDetail(id);
      const items = (j && j.items) || [];
      const blob = new Blob([JSON.stringify({batch: (j && j.batch) || {id}, items}, null, 2)],
        {type: 'application/json'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'batch-' + id + '.json';
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      rowNote(row, 'JSON دانلود شد (' + faNum(items.length) + ' مورد).');
    } catch(e) {
      rowError(row, 'خواندن بسته ناموفق بود.', (e && e.message) || e,
        () => downloadBatchJson(id, null, row), codeFrom(e));
    }
  });
}
async function submitImport(id, ta, btn, row, box) {
  const text = (ta.value || '').trim();
  if (!text) {
    rowError(row, 'پاسخ‌نامه خالی است (چیزی فرستاده نشد).',
      'answer_sheet is empty', () => submitImport(id, ta, null, row, box), 'VALIDATION-input');
    return;
  }
  let parsed = null;
  try {
    parsed = JSON.parse(text);
  } catch(e) {
    rowError(row, 'پاسخ‌نامه JSON معتبر نیست (چیزی فرستاده نشد).',
      (e && e.message) || e, () => submitImport(id, ta, null, row, box), 'VALIDATION-input');
    return;
  }
  if (!parsed || typeof parsed !== 'object') {
    rowError(row, 'پاسخ‌نامه باید یک شیء JSON باشد (چیزی فرستاده نشد).',
      'answer sheet must be a JSON object',
      () => submitImport(id, ta, null, row, box), 'VALIDATION-input');
    return;
  }
  await withBusy(btn, 'در حال واردسازی…', async () => {
    try {
      // Contract: the route requires the RAW sheet string (it extracts
      // the JSON block itself for strict validation) — never the parsed
      // object. Client-side parse above is a pre-check only.
      const j = await getJSON('/api/batches/' + encodeURIComponent(id) + '/import',
        {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify({answer_sheet: text})});
      delete repairCache[id];
      const repairBtn = box.querySelectorAll('button')[1];
      if (repairBtn) repairBtn.hidden = true;
      rowNote(row, faNum((j && j.staged) || 0) + ' مورد در بازبینی نشست.');
      await refreshBatches();
      await openReview(id, null);
    } catch(e) {
      const body = (e && e.body) || {};
      if ((e && e.status) === 422 || body.repair_request) {
        if (body.repair_request) repairCache[id] = body.repair_request;
        const repairBtn = box.querySelectorAll('button')[1];
        if (repairBtn && body.repair_request) repairBtn.hidden = false;
        rowError(row, 'واردسازی کل بسته رد شد (بدون ثبت ناقص) — «کپی درخواست ترمیم» را به چت هوش مصنوعی برگردانید.',
          body.error || (e && e.message) || e,
          () => submitImport(id, ta, null, row, box), 'VALIDATION-answer-sheet');
      } else {
        rowError(row, 'واردسازی پاسخ‌نامه ناموفق بود.', (e && e.message) || e,
          () => submitImport(id, ta, null, row, box), codeFrom(e));
      }
    }
  });
}
async function copyRepair(id, btn, row) {
  const text = repairCache[id] || '';
  if (!text) {
    if (row) rowNote(row, 'هنوز درخواست ترمیمی برای این بسته نیست — اول پاسخ‌نامه را بفرستید.');
    else showFormError('batch-review-err', 'هنوز درخواست ترمیمی نیست.',
      'no repair_request cached', null, 'VALIDATION-input');
    return;
  }
  await copyReport(text, btn, 'درخواست ترمیم کپی شد');
}
function itemSummary(item) {
  const cands = (item && item.candidates) || [];
  return faNum(cands.length) + ' نامزد';
}
function renderReview() {
  const box = el('batch-review-list');
  const badge = el('batch-review-batch');
  const note = el('batch-review-note');
  const selectAll = el('batch-select-all');
  if (!box) return;
  box.replaceChildren();
  if (selectAll) selectAll.checked = false;
  if (!reviewBatchId) {
    if (badge) badge.textContent = 'بسته‌ای انتخاب نشده است';
    if (note) note.textContent = '';
    return;
  }
  if (badge) {
    badge.replaceChildren();
    badge.append(document.createTextNode('بسته '));
    badge.append(ltrCode(reviewBatchId));
  }
  if (!reviewItems.length) {
    if (note) note.textContent = 'موردی برای بازبینی نیست.';
    return;
  }
  reviewItems.forEach((item) => {
    const senseId = String((item && item.sense_id) || '');
    const line = document.createElement('label');
    line.className = 'queue-item';
    line.style.cursor = 'pointer';
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.value = senseId;
    check.setAttribute('aria-label', 'تأیید ' + senseId);
    check.addEventListener('change', updateReviewNote);
    const wrap = document.createElement('div');
    const b = document.createElement('b');
    b.className = 'code-token';
    b.textContent = senseId || '—';
    const gloss = document.createElement('div');
    gloss.className = 'queue-gloss ltr-text';
    gloss.setAttribute('dir', 'ltr');
    const defFlat = String((item && (item.definition || item.gloss)) || '').replace(/\s+/g, ' ').trim();
    gloss.textContent = (item && item.lemma ? item.lemma + ' — ' : '')
      + (defFlat ? (defFlat.length > 120 ? defFlat.slice(0, 120) + '…' : defFlat) : '—');
    gloss.title = gloss.textContent;
    wrap.append(b, gloss);
    const tag = document.createElement('span');
    tag.className = 'status-tag';
    tag.textContent = itemSummary(item);
    const cands = (item && item.candidates) || [];
    if (cands.length) {
      tag.title = cands.slice(0, 8).map((c) => c.synset_id || '').filter(Boolean).join(', ');
    }
    line.append(check, wrap, tag);
    box.append(line);
  });
  updateReviewNote();
}
function selectedReviewIds() {
  const box = el('batch-review-list');
  if (!box) return [];
  return Array.from(box.querySelectorAll('input[type="checkbox"]:checked'))
    .map((c) => c.value).filter(Boolean);
}
function updateReviewNote() {
  const note = el('batch-review-note');
  if (!note || !reviewBatchId) return;
  note.textContent = faNum(reviewItems.length) + ' مورد · ' + faNum(selectedReviewIds().length) + ' انتخاب‌شده';
}
async function openReview(id, btn) {
  clearFormError('batch-review-err');
  const run = async () => {
    try {
      const j = await fetchBatchDetail(id);
      reviewBatchId = id;
      reviewItems = (j && j.items) || [];
      renderReview();
      const title = el('batch-review-title');
      if (title && btn) title.focus();
    } catch(e) {
      showFormError('batch-review-err', 'خواندن بسته برای بازبینی ناموفق بود.',
        (e && e.message) || e, run, codeFrom(e));
    }
  };
  if (btn) await withBusy(btn, 'در حال خواندن…', run);
  else await run();
}
async function approveSelected(btn) {
  clearFormError('batch-review-err');
  if (!reviewBatchId) {
    showFormError('batch-review-err', 'بسته‌ای برای بازبینی انتخاب نشده است (اول «بازبینی» یک بسته را بزنید).',
      'no batch in review', approveSelected, 'VALIDATION-input');
    return;
  }
  const ids = selectedReviewIds();
  if (!ids.length) {
    showFormError('batch-review-err', 'موردی انتخاب نشده است (چیزی تأیید نشد).',
      'ids is empty', approveSelected, 'VALIDATION-input');
    return;
  }
  await withBusy(btn || el('btn-batch-approve'), 'در حال تأیید…', async () => {
    try {
      const j = await getJSON('/api/batches/' + encodeURIComponent(reviewBatchId) + '/approve',
        {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify({ids})});
      const box = el('batch-review-list');
      if (box) box.querySelectorAll('input[type="checkbox"]:checked').forEach((c) => { c.checked = false; });
      updateReviewNote();
      const note = el('batch-review-note');
      if (note) {
        note.textContent = faNum((j && j.finalized) || 0) + ' نهایی شد · '
          + faNum((j && j.returned) || 0) + ' به صف برگشت.';
      }
      await refreshBatches();
    } catch(e) {
      showFormError('batch-review-err', 'تأیید موارد ناموفق بود.',
        (e && e.message) || e, approveSelected, codeFrom(e));
    }
  });
}
async function cancelBatch(id, btn, row) {
  if (!confirm('بسته ' + id + ' لغو می‌شود و شناسه‌ها به صف برمی‌گردند؛ ادامه می‌دهید؟')) return;
  await withBusy(btn, 'در حال لغو…', async () => {
    try {
      await getJSON('/api/batches/' + encodeURIComponent(id) + '/cancel', {method: 'POST'});
      delete repairCache[id];
      rowNote(row, 'بسته لغو شد؛ شناسه‌ها به صف برگشتند.');
      if (reviewBatchId === id) {
        reviewBatchId = '';
        reviewItems = [];
        renderReview();
      }
      await refreshBatches();
    } catch(e) {
      rowError(row, 'لغو بسته ناموفق بود.', (e && e.message) || e,
        () => cancelBatch(id, null, row), codeFrom(e));
    }
  });
}
/* گالری: پاسخ سرور HTML است (نه JSON) پس fetch خام؛ موفقیت یعنی بازکردن
   در زبانه تازه، 404 صادقانه یعنی جعبه سه‌بخشی بدون زبانه تازه. */
async function buildGallery(btn) {
  clearFormError('gallery-err');
  const note = el('gallery-note');
  if (note) note.textContent = '';
  const run = ((el('gallery-run') || {}).value || '').trim();
  if (!run) {
    showFormError('gallery-err', 'شناسه یا مسیر اجرا خالی است (گالری ساخته نشد).',
      '?run is required', buildGallery, 'VALIDATION-run');
    return;
  }
  const url = '/api/gallery?run=' + encodeURIComponent(run);
  await withBusy(btn || el('btn-build-gallery'), 'در حال ساخت…', async () => {
    try {
      const r = await fetch(url);
      if (!r.ok) {
        let detail = 'خطای ' + r.status;
        try {
          const j = await r.json();
          if (j && j.error) detail = j.error;
        } catch(e){}
        const err = new Error(detail);
        err.status = r.status;
        throw err;
      }
      window.open(url, '_blank', 'noopener');
      if (note) note.textContent = 'گالری در زبانه تازه باز شد.';
      const state = el('gallery-state');
      if (state) state.textContent = 'آخرین گالری: ' + run;
    } catch(e) {
      showFormError('gallery-err', 'ساخت گالری ناموفق بود.',
        (e && e.message) || e, buildGallery, codeFrom(e));
    }
  });
}
/* تاریخچه اجراها (GET /api/runs): هر سطر دکمه گالری خودش را دارد —
   شناسه در ورودی می‌نشیند و همان مسیر ساخت فراخوانی می‌شود. */
async function refreshHistory() {
  const tb = el('gallery-history-tbody');
  const count = el('gallery-history-count');
  const note = el('gallery-history-note');
  if (!tb) return;
  try {
    const j = await getJSON('/api/runs');
    const rows = (j && j.runs) || [];
    tb.replaceChildren();
    if (count) count.textContent = faNum(rows.length) + ' اجرا';
    if (!rows.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 4;
      td.textContent = 'اجرایی ثبت نشده است.';
      tr.append(td);
      tb.append(tr);
      if (note) note.textContent = '';
      return;
    }
    rows.forEach((r) => {
      const tr = document.createElement('tr');
      const tdRun = document.createElement('td');
      tdRun.append(ltrCode(r.run_name || r.id || '—'));
      const tdStatus = document.createElement('td');
      tdStatus.textContent = r.status || '—';
      const tdCreated = document.createElement('td');
      tdCreated.append(ltrCode(r.created || '—'));
      const tdAct = document.createElement('td');
      const g = document.createElement('button');
      g.type = 'button';
      g.className = 'btn-skip-next';
      g.textContent = 'گالری';
      g.setAttribute('aria-label', 'بازکردن گالری اجرای ' + (r.run_name || r.id || ''));
      g.addEventListener('click', (ev) => {
        const inp = el('gallery-run');
        if (inp) inp.value = r.run_name || r.id || '';
        buildGallery(ev.currentTarget);
      });
      tdAct.append(g);
      tr.append(tdRun, tdStatus, tdCreated, tdAct);
      tb.append(tr);
    });
    if (note) note.textContent = faNum(rows.length) + ' اجرا از تاریخچه خوانده شد.';
  } catch(e) {
    tb.replaceChildren();
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 4;
    td.append(buildFormError('خواندن تاریخچه اجراها ناموفق بود.',
      (e && e.message) || e, refreshHistory, undefined, codeFrom(e)));
    tr.append(td);
    tb.append(tr);
    if (count) count.textContent = 'نامشخص';
  }
}
function initSupervisedBatches() {
  if (initialized) return;
  initialized = true;
  const issue = el('btn-issue-batch');
  if (issue) issue.addEventListener('click', (ev) => issueBatch(ev.currentTarget));
  const refresh = el('btn-refresh-batches');
  if (refresh) refresh.addEventListener('click', (ev) => withBusy(ev.currentTarget, 'در حال خواندن…', refreshBatches));
  const selectAll = el('batch-select-all');
  if (selectAll) selectAll.addEventListener('change', () => {
    const box = el('batch-review-list');
    if (box) box.querySelectorAll('input[type="checkbox"]').forEach((c) => { c.checked = selectAll.checked; });
    updateReviewNote();
  });
  const approve = el('btn-batch-approve');
  if (approve) approve.addEventListener('click', (ev) => approveSelected(ev.currentTarget));
  const gallery = el('btn-build-gallery');
  if (gallery) gallery.addEventListener('click', (ev) => buildGallery(ev.currentTarget));
  refreshBatches();
  refreshHistory();
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initSupervisedBatches);
} else {
  initSupervisedBatches();
}
