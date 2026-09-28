import {getJSON, faNum, ltrCode, withBusy, showFormError, clearFormError} from '../shell/api_client.js';
import {FilterableListController} from '../shell/filterable_list_controller.js';
let screenedRows = [];
let screenedTotal = 0;
let screenedPath = '';
let currentSense = null;
let queueIndex = 0;
let selectedTarget = null;
/* غربال: سنس جاری + صف از خروجی واقعی.
   path اختیاری (T08 تحویل رکورد-محور تاریخچه): فایل screened.jsonl آن
   اجرا را مسلح می‌کند؛ بدون آرگومان رفتار پیشین (پیش‌فرض سرور) حفظ
   می‌شود — همه فراخوان‌های موجود سازگار می‌مانند. */
export async function loadScreened(screenedPath) {
  try {
    const url = screenedPath
      ? '/api/screened?path=' + encodeURIComponent(screenedPath)
      : '/api/screened';
    const j = await getJSON(url);
    screenedRows = j.rows || [];
    screenedTotal = j.total || 0;
    screenedPath = j.path || '';
    clearFormError('linking-err');
    const hp = document.getElementById('handoff-path');
    if (screenedPath) {
      hp.textContent = screenedPath;
      hp.removeAttribute('title');
    } else {
      hp.textContent = '—';
      hp.title = 'هنوز ورودی غربالگری بار نشده است';
    }
    document.getElementById('handoff-total').textContent =
      '(' + faNum(screenedTotal) + ' سنس' + (j.truncated ? ' — نمایش ' + faNum(screenedRows.length) + ' تای اول' : '') + ')';
    if (queueIndex >= screenedRows.length) queueIndex = 0;
    renderQueue();
    selectSense(queueIndex);
    await refreshLabelStats();
  } catch(e) {
    document.getElementById('handoff-path').textContent = 'خواندن ناموفق بود';
    document.getElementById('handoff-total').textContent = '';
    /* T12 OQ-10: every form error lives in the shared 3-part box. */
    showFormError('linking-err', 'خواندن ورودی غربالگری ناموفق بود.',
      (e && e.message) || e, () => loadScreened(screenedPath), undefined);
  }
}
/* پالایش زنده صف: زیررشته‌ای روی شناسه، لم، معنی، یا برچسب وضعیت */
let queueFilter = '';
function queueItemMatches(row, i, q) {
  const needle = (q !== undefined && q !== null ? q : queueFilter || '').trim();
  if (!needle) return true;
  const status = i === queueIndex ? 'داوری جاری' : 'در انتظار';
  return (row.sense_id || '').includes(needle)
    || (row.lemma || '').includes(needle)
    || (row.gloss || '').includes(needle)
    || status.includes(needle);
}
/* نمونه‌سازی صف داوری: ورودی queue-filter + ظرف queue-list */
const queueFilterCtl = new FilterableListController(
  'queue-filter', 'queue-list',
  function(row, i, q) { return queueItemMatches(row, i, q); },
  function(q) { queueFilter = q || ''; renderQueue(); });
function renderQueue() {
  const box = document.getElementById('queue-list');
  box.replaceChildren();
  const visible = screenedRows.map((row, i) => ({row, i}))
    .filter(({row, i}) => queueItemMatches(row, i));
  document.getElementById('queue-remaining').textContent =
    faNum(visible.length) + ' از ' + faNum(screenedRows.length) + ' مورد';
  visible.forEach(({row, i}) => {
    const item = document.createElement('div');
    item.className = 'queue-item' + (i === queueIndex ? ' active' : '');
    /* PUX-22: ردیف صف با صفحه‌کلید کار می‌کند (tabIndex + Enter/Space
       مثل ردیف‌های هر-لم غربالگری). */
    item.tabIndex = 0;
    const wrap = document.createElement('div');
    const b = document.createElement('b');
    b.className = 'code-token';
    if (i === queueIndex) b.style.color = 'var(--c-primary)';
    b.textContent = row.sense_id || '—';
    if (!row.sense_id) b.title = 'سرور این شناسه را ثبت نکرد';
    /* ردیف صف دقیقاً سه چیز حمل می‌کند: شناسه کایکی، برش معنی، وضعیت —
       نامزدها/مثال‌ها/متن کامل هرگز در ردیف نیست (مالک آن‌ها بخش «جزئیات سنس» است) */
    const glossFlat = (row.gloss || '').replace(/\s+/g, ' ').trim();
    const glossSlice = glossFlat
      ? (glossFlat.length > 120 ? glossFlat.slice(0, 120) + '…' : glossFlat)
      : '—';
    const sub = document.createElement('div');
    sub.className = 'queue-gloss ltr-text';
    sub.setAttribute('dir', 'ltr');
    sub.textContent = glossSlice;
    sub.title = glossFlat ? glossSlice : 'سرور معنایی برای این سنس ثبت نکرد';
    wrap.append(b, sub);
    const tag = document.createElement('span');
    tag.className = 'status-tag';
    if (i === queueIndex) tag.style.color = 'var(--c-warning)';
    tag.textContent = i === queueIndex ? 'داوری جاری' : 'در انتظار';
    item.append(wrap, tag);
    item.addEventListener('click', () => selectSense(i));
    item.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        selectSense(i);
      }
    });
    box.append(item);
  });
}
function selectSense(i) {
  if (!screenedRows.length) {
    currentSense = null;
    /* T12 OQ-10: every — carries a title cause from the shared list. */
    const dashTitle = 'هنوز ورودی غربالگری بار نشده است';
    const sid = document.getElementById('sense-id');
    sid.textContent = '—';
    sid.title = dashTitle;
    document.getElementById('sense-meta').textContent = 'صفی خالی است';
    const sdef = document.getElementById('sense-def');
    sdef.textContent = '—';
    sdef.title = dashTitle;
    const sex = document.getElementById('sense-example');
    sex.textContent = '—';
    sex.title = dashTitle;
    renderCandidates([]);
    return;
  }
  queueIndex = ((i % screenedRows.length) + screenedRows.length) % screenedRows.length;
  currentSense = screenedRows[queueIndex];
  document.getElementById('sense-id').textContent = currentSense.sense_id || '—';
  document.getElementById('sense-meta').textContent =
    (currentSense.lemma || '—') + ' · سنس ' + faNum(queueIndex + 1) + ' از ' + faNum(screenedRows.length);
  document.getElementById('sense-def').textContent = currentSense.gloss || '—';
  document.getElementById('sense-example').textContent = currentSense.example || '—';
  renderQueue();
  loadCandidates();
}
let candidatesRequest = 0;
async function loadCandidates() {
  const box = document.getElementById('candidates-stack');
  const statusEl = document.getElementById('candidates-status');
  const myTicket = ++candidatesRequest;
  selectedTarget = null;
  document.getElementById('label-target-name').textContent = 'نامزدی انتخاب نشده است';
  box.replaceChildren();
  if (!currentSense || !currentSense.sense_id) {
    statusEl.textContent = 'سنسی در صف نیست.';
    return;
  }
  statusEl.textContent = 'در حال بارگذاری نامزدها…';
  try {
    /* the queue id is short (run#5): the server resolves it to the
       full kaikki id through the same screened export the queue came
       from, then joins real-run shortlists plus human-review lists */
    let url = '/api/candidates?sense_id=' + encodeURIComponent(currentSense.sense_id);
    if (screenedPath) url += '&screened=' + encodeURIComponent(screenedPath);
    const j = await getJSON(url);
    if (myTicket !== candidatesRequest) return;  // a newer sense won the race
    renderCandidates(j.candidates || [], {cause: j.cause || '', fullId: j.full_id || '',
      witness: j.witness_verdict || ''});
  } catch(e) {
    if (myTicket !== candidatesRequest) return;
    statusEl.textContent = 'بارگذاری نامزدها ناموفق بود: ' + (e.message || e);
  }
}
function renderCandidates(cands, feed) {
  const box = document.getElementById('candidates-stack');
  const statusEl = document.getElementById('candidates-status');
  box.replaceChildren();
  const cause = (feed && feed.cause) || '';
  if (!cands.length) {
    if (cause === 'no-join') {
      /* حالت خالی پیوندنخورده: نثر فارسی (واژه‌نامه §۳)؛ بدون جعبه لاتین. */
      statusEl.textContent =
        'پیوندی برای این سنس نیست: شناسه در نگاشت غربالگری و هیچ اجرایی پیدا نشد.';
    } else {
      /* حالت خالی خنثی: نثر فارسی (واژه‌نامه §۳)؛ بدون جعبه لاتین. */
      statusEl.textContent =
        'نامزدی در جدول پیوند برای این سنس نیست.';
    }
    return;
  }
  const witness = (feed && feed.witness) || '';
  /* خط وضعیت: شمار فارسی + برچسب فارسی «شاهد»؛ مقدار انگلیسی سرور
     (witness_verdict آزاد) خامِ برچسب‌دار در ایزوله LTR می‌ماند. */
  statusEl.replaceChildren();
  statusEl.append(document.createTextNode(
    faNum(cands.length) + ' نامزد از اجرای واقعی'));
  if (witness) {
    statusEl.append(document.createTextNode(' · شاهد: '));
    const w = ltrCode(witness);
    w.title = 'مقدار سرور (witness_verdict)';
    statusEl.append(w);
  }
  cands.forEach((cand) => {
    const card = document.createElement('div');
    card.className = 'candidate-row-card';
    card.dataset.sensekey = cand.sensekey || '';
    /* سطر بالایی: شناسه لاتین ایزوله + دکمه انتخاب */
    const top = document.createElement('div');
    top.className = 'c-top-row';
    const keyTag = document.createElement('bdi');
    keyTag.setAttribute('dir', 'ltr');
    keyTag.className = 'code-token c-sensekey';
    keyTag.textContent = cand.sensekey || '—';
    keyTag.title = cand.sensekey || '';
    const pick = document.createElement('button');
    pick.className = 'btn-select-candidate';
    pick.type = 'button';
    pick.textContent = 'انتخاب برای پیوند';
    pick.addEventListener('click', () => setSelectedTarget(cand.sensekey || '', card));
    top.append(keyTag, pick);
    card.append(top);
    /* معنی برجسته */
    const gloss = document.createElement('div');
    gloss.className = 'c-gloss-text ltr-text';
    gloss.setAttribute('dir', 'ltr');
    gloss.textContent = cand.gloss || '—';
    if (cand.gloss) gloss.title = cand.gloss;
    card.append(gloss);
    /* مترادف‌ها در سطر برچسب‌دار خودشان */
    if ((cand.synonyms || []).length) {
      const synLine = document.createElement('div');
      synLine.className = 'c-synonyms-line ltr-text';
      synLine.setAttribute('dir', 'ltr');
      const synLabel = document.createElement('span');
      synLabel.className = 'c-syn-label';
      synLabel.textContent = 'مترادف‌ها: ';
      synLine.append(synLabel, document.createTextNode(cand.synonyms.join('; ')));
      synLine.title = cand.synonyms.join('; ');
      card.append(synLine);
    }
    /* مثال در بلوک نقل‌قول متمایز */
    if (cand.example) {
      const quote = document.createElement('blockquote');
      quote.className = 'c-example ltr-text';
      quote.setAttribute('dir', 'ltr');
      quote.textContent = cand.example;
      quote.title = cand.example;
      card.append(quote);
    }
    /* متادیتای فنی (شناسه‌های داخلی، روش، شواهد، پرچم‌ها) فقط در
       بلوک تاشو — هرگز در بدنه کارت */
    const metaBits = [];
    if (cand.synset) metaBits.push(['synset', cand.synset]);
    if (cand.synset_locator) metaBits.push(['locator', cand.synset_locator]);
    if (cand.method) metaBits.push(['method', cand.method]);
    if (cand.evidence) metaBits.push(['evidence', cand.evidence]);
    if (cand.in_review) metaBits.push(['review', 'review' + (cand.review_reason ? ': ' + cand.review_reason : '')]);
    if (cand.witness_pick) metaBits.push(['witness pick', 'witness pick' + (witness ? ': ' + witness : '')]);
    if (metaBits.length) {
      const metaBox = document.createElement('details');
      metaBox.className = 'candidate-meta';
      const metaSummary = document.createElement('summary');
      metaSummary.textContent = 'فراداده فنی';
      metaBox.append(metaSummary);
      metaBits.forEach(([label, value]) => {
        const line = document.createElement('div');
        line.className = 'meta-line ltr-text';
        line.setAttribute('dir', 'ltr');
        line.textContent = label + ': ' + value;
        line.title = label + ': ' + value;
        metaBox.append(line);
      });
      card.append(metaBox);
    }
    box.append(card);
  });
}
function setSelectedTarget(sensekey, card) {
  selectedTarget = sensekey || null;
  document.getElementById('label-target-name').textContent = selectedTarget || 'نامزدی انتخاب نشده است';
  document.querySelectorAll('#candidates-stack .candidate-row-card').forEach((el) => {
    el.classList.toggle('selected', !!selectedTarget && el.dataset.sensekey === selectedTarget);
  });
}
async function refreshLabelStats() {
  try {
    const j = await getJSON('/api/labels');
    const labels = j.labels || [];
    const nones = labels.filter(l => l.verdict === 'none').length;
    document.getElementById('m-judged').textContent = faNum(labels.length) + ' / ' + faNum(screenedTotal);
    document.getElementById('m-none').textContent = faNum(nones);
  } catch(e) {
    document.getElementById('m-judged').textContent = 'نامشخص';
    document.getElementById('m-none').textContent = 'نامشخص';
  }
}
/* پیش‌فرض‌گذاری امن ابرداده رأی (پس‌زمینه، خارج از جریان فرم):
   مقادیر بخش تنظیمات اگر اپراتور تعیین کرده باشد، وگرنه پیش‌فرض‌های
   امن نقش‌محور — هرگز نام شخصی ساخته نمی‌شود. */
const LABEL_DEFAULT_STRATUM = 'operator-review';
const LABEL_DEFAULT_ANNOTATOR = 'operator';
function labelDefaults() {
  let s = '', a = '';
  try {
    const sEl = document.getElementById('label-stratum');
    const aEl = document.getElementById('label-annotator');
    s = (sEl && sEl.value || '').trim();
    a = (aEl && aEl.value || '').trim();
  } catch(e){}
  return {
    stratum: s || LABEL_DEFAULT_STRATUM,
    annotator: a || LABEL_DEFAULT_ANNOTATOR,
  };
}
function labelFields(verdict, target) {
  const defs = labelDefaults();
  return {
    sense_id: currentSense ? (currentSense.sense_id || '') : '',
    lemma: currentSense ? (currentSense.lemma || '') : '',
    target_synset: target,
    verdict: verdict,
    stratum: defs.stratum,
    annotator: defs.annotator,
  };
}
async function postLabel(verdict, target) {
  const statusEl = document.getElementById('label-status');
  const receiptEl = document.getElementById('label-receipt');
  receiptEl.hidden = true;
  if (!currentSense) { statusEl.textContent = 'سنسی در صف نیست.'; return; }
  const body = labelFields(verdict, target);
  statusEl.textContent = 'در حال ذخیره…';
  try {
    const j = await getJSON('/api/labels', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    statusEl.textContent = 'ذخیره شد.';
    receiptEl.hidden = false;
    receiptEl.replaceChildren();
    /* رسید فارسی (واژه‌نامه §۳): شناسه بازپخش ماشینی ایزوله + «دفتر
       رأی‌ها» + نشان غیرشاهد؛ مقادیر خام سرور فقط در title فرار دیباگ. */
    receiptEl.append(ltrCode(j.replay || '—'));
    receiptEl.append(document.createTextNode(' — ثبت شد در دفتر رأی‌ها'));
    if (j.store) {
      receiptEl.append(document.createTextNode(' '));
      const path = ltrCode(j.store);
      path.title = String(j.store);
      receiptEl.append(path);
    }
    if (j.watermark) {
      const wm = document.createElement('span');
      wm.textContent = ' — نشان غیرشاهد (غیرقابل امتیاز)';
      wm.title = String(j.watermark);
      receiptEl.append(wm);
    }
    await refreshLabelStats();
  } catch(e) {
    statusEl.textContent = 'ذخیره ناموفق بود: ' + (e.message || e);
    /* T12 OQ-10: failures also land in the shared 3-part box. */
    showFormError('linking-err', 'ذخیره رأی ناموفق بود.',
      (e && e.message) || e, () => postLabel(verdict, target), undefined);
  }
}
/* T12 OQ-10: every server button runs withBusy (busy «در حال…»,
   no double-click). The refresh wrapper also drops the leaked click
   event arg (R5): refresh always reloads the default screened input. */
document.getElementById('btn-refresh-screened').addEventListener('click', (ev) => {
  withBusy(ev && ev.currentTarget, 'در حال…', () => loadScreened());
});
/* پالایش زنده صف از طریق کنترلر (شناسه یا وضعیت) — سیم‌کشی ورودی
   در سازنده FilterableListController انجام می‌شود. */
document.getElementById('btn-skip-next').addEventListener('click', () => selectSense(queueIndex + 1));
document.getElementById('btn-reject-all').addEventListener('click', (ev) => {
  withBusy(ev && ev.currentTarget, 'در حال…', () => postLabel('none', null));
});
document.getElementById('btn-record-link').addEventListener('click', (ev) => {
  if (!selectedTarget) {
    document.getElementById('label-status').textContent = 'اول یک نامزد را از کارت‌ها انتخاب کنید.';
    return;
  }
  withBusy(ev && ev.currentTarget, 'در حال…', () => postLabel('link', selectedTarget));
});
