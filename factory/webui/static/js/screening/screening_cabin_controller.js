import {getJSON, withBusy, faNum, showFormError, clearFormError, ltrCode} from '../shell/api_client.js';
import {openCollisionDialog} from '../shell/data_dialog_controller.js';
import {openView} from '../shell/view_navigator.js';
import {FilterableListController} from '../shell/filterable_list_controller.js';
import {loadScreened} from '../sense_linking/human_review_controller.js';
/* کابین غربالگری کایکی (T07): ستون کنترل چسبان A1 تا A4 + زبانه
   «اجرا و نتایج زنده» (زبانه ۲ پوسته T08 است).
   A1: چندخطی چپ‌چین، تفکیک ویرگول/خط، شمارش سمت‌کاربر == شمار
   ارسالی، میان‌بر واژه‌های دود. A2: نام+مقصد با پیش‌فرض نمایان و
   پیش‌نمایش پاک‌سازی‌شده (نویسه غیرمجاز -> `-`). A3: پیش‌نمایش دفتر
   «X تازه، Y تکراری» + فقط-تازه پیش‌فرض + کلید پردازش دوباره. A4:
   شروع/توقف با withBusy، ۴۰۹ -> پیام صادقانه، تحویل -> loadScreened.
   زنده: نشان elapsed_human، جعبه گزارش ۳-حالته، کارت‌ها از
   drop_reasons (twin_r3/proper_r2/other)، جدول هر-لم با پالایش
   سمت‌کاربر + شمارنده «N نمایان از M سطر» + کلیک -> جزئیات (شمارش‌ها
   + شناسه‌های حذف‌شده + علت، هرگز gloss)، بنر اتصال‌مجدد روی resumed.
   شکل‌های مصرفی (بک‌اند Wave 1):
   POST /api/screening/run {words,out_name?,out_dir?,reprocess_duplicates}؛
   GET /api/screening/status -> {screening:{status,elapsed(raw,kept),
   elapsed_human,started_iso,run_id,resumed,log,manifest, out_dir}}؛
   GET /api/screening/ledger_preview?words=.. -> {fresh,duplicate,
   fresh_count,dup_count}؛ POST /api/screening/abort.
   نشت سراسری صفر: همه حالت‌ها در دامنه ماژول، بدون window.*. */
const SMOKE_WORDS = 'run,light,take,get,make';
const POLL_MS = 1000;
const MAX_POLL_ERRORS = 3;
const LEDGER_DEBOUNCE_MS = 400;
const STATE_FA = {idle: 'بیکار', running: 'در حال اجرا',
  completed: 'تکمیل شد', failed: 'ناموفق بود',
  aborted: 'متوقف شد', unknown: 'نامشخص'};
let pollTimer = 0;
let pollInflight = false;
let pollErrors = 0;
let runActive = false;
let lastOutPath = '';
let perLemma = [];
let lemmaQuery = '';
let selectedLemma = null;
let ledgerTimer = 0;
/* بک‌اند واقعی زیر کلید screening جواب می‌دهد؛ این نرمالایزر شکل
   تودرتو را به شکل مصرفی کنترلر می‌نگارد (elapsed خام نگه داشته
   می‌شود، elapsed_human/started_iso کنارش). */
function normStatus(raw) {
  const s = (raw && raw.screening) || raw || {};
  return {
    state: s.status || s.state || 'idle',
    elapsed: (s.elapsed !== undefined && s.elapsed !== null) ? s.elapsed : null,
    elapsed_human: (typeof s.elapsed_human === 'string' && s.elapsed_human)
      ? s.elapsed_human : null,
    started_iso: (typeof s.started_iso === 'string') ? s.started_iso : null,
    run_id: s.run_id || null,
    resumed: !!s.resumed,
    exit_code: (s.exit_code !== undefined) ? s.exit_code : null,
    log: Array.isArray(s.log) ? s.log : [],
    manifest: s.manifest || null,
    out_path: s.out_path || s.out_dir || '',
    words: Array.isArray(s.words) ? s.words : []
  };
}
function el(id) {
  return document.getElementById(id);
}
/* A1: ویرگول (لاتین/فارسی) یا خط جدید -> لم‌های کوچک‌نشده تهی‌زدوده.
   شمار خروجی دقیقاً شمار ارسالی است (پیوستن با ویرگول برای سرور). */
function parseWords(text) {
  return String(text || '').split(/[,،\n\r]+/)
    .map((w) => w.trim().toLowerCase())
    .filter((w) => w.length > 0);
}
/* A2: پاک‌سازی نام خروجی (T11 OQ-6): فارسی + لاتین + رقم + `-` + `_`
   می‌ماند، هر چه جز این‌هاست -> `-`؛ خط‌تیره‌های پیاپی یکی، سر و ته
   (`-`/`_`) پیراسته؛ پیش‌نمایش زنده همان پاک‌سازی‌شده است. */
function sanitizeName(raw) {
  return String(raw || '').trim().toLowerCase()
    .replace(/[^\u0600-\u06FFa-z0-9\-_]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[-_]+|[-_]+$/g, '')
    .slice(0, 64);
}
/* سقف واژه‌ها (T11 OQ-2): بیش از ۲۵۰۰ هرگز بی‌سر و صدا کوتاه نمی‌شود. */
const WORDS_MAX = 2500;
const WORD_RE = /^[a-z-]{1,64}$/;
function defaultOutName(now) {
  const d = (now instanceof Date) ? now : new Date();
  const p = (n) => String(n).padStart(2, '0');
  return 'screening-' + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate())
    + '-' + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
}
function refreshNamePreview() {
  const node = el('screening-out-name-clean');
  if (!node) return;
  const input = el('screening-out-name');
  const clean = sanitizeName(input && input.value);
  node.replaceChildren();
  if (clean) {
    node.append(document.createTextNode(clean));
    node.removeAttribute('title');
  } else {
    node.append(document.createTextNode('—'));
    node.title = 'نامی وارد نشده است';
  }
}
function refreshWordsCount() {
  const node = el('screening-words-count');
  if (!node) return;
  const input = el('screening-words');
  node.textContent = faNum(parseWords(input && input.value).length);
}
function metricVal(id, value, emptyCause) {
  const node = el(id);
  if (!node) return;
  if (value === null || value === undefined) {
    node.textContent = '—';
    node.title = emptyCause || 'سرور این سنج را ثبت نکرد';
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
/* جعبه گزارش ۳-حالته: بیکار / زنده / پایانی؛ خالیِ هر حالت با title
   علت‌دار (خالی صادقانه، هرگز گزارش ساختگی). */
function renderLog(lines, state) {
  const box = el('screening-log');
  if (!box) return;
  const list = Array.isArray(lines) ? lines : [];
  if (!list.length) {
    if (state === 'running') {
      box.textContent = 'در حال اجرا… نخستین خطوط گزارش به‌زودی می‌رسند.';
      box.title = 'وضعیت: در حال اجرا — سرور هنوز خطی نفرستاده است.';
    } else if (state === 'idle') {
      box.textContent = 'هنوز اجرایی شروع نشده — گزارش اینجا می‌آید.';
      box.title = 'وضعیت: بیکار — هنوز اجرایی شروع نشده است.';
    } else {
      box.textContent = 'گزارشی از سرور نرسید.';
      box.title = 'وضعیت: ' + (STATE_FA[state] || state)
        + ' — سرور گزارشی برنگرداند.';
    }
    return;
  }
  box.removeAttribute('title');
  box.textContent = list.join('\n');
  box.scrollTop = box.scrollHeight;
}
/* کارت‌ها از drop_reasons سرور {twin_r3,proper_r2,other}؛ غایب -> خالی
   عنوان‌دار (هرگز صفر ساختگی). */
function renderMetrics(manifest) {
  const per = (manifest && manifest.per_lemma) || [];
  if (!manifest) {
    ['screening-m-input', 'screening-m-kept', 'screening-m-dropped',
     'screening-m-twins', 'screening-m-proper', 'screening-m-other']
      .forEach((id) => honestVal(id, 'هنوز اجرایی موفق ثبت نشده است'));
    perLemma = [];
    selectedLemma = null;
    renderPerLemma();
    renderDetail();
    return;
  }
  const sum = (key) => per.reduce((n, r) => n + (Number(r[key]) || 0), 0);
  const kept = manifest.kept_total !== undefined ? manifest.kept_total : sum('kept');
  const dropped = manifest.dropped_total !== undefined ? manifest.dropped_total : sum('dropped');
  const input = sum('input_senses') || (Number(kept) || 0) + (Number(dropped) || 0);
  metricVal('screening-m-input', input, 'سرور این سنج را ثبت نکرد');
  metricVal('screening-m-kept', kept, 'سرور این سنج را ثبت نکرد');
  metricVal('screening-m-dropped', dropped, 'سرور این سنج را ثبت نکرد');
  /* T10 route-delete proof: no client-side splitDropReasons reader exists
     (grep: zero hits) — cards read manifest.drop_reasons verbatim (T01);
     absent key -> titled honest empty, never zeros. */
  const reasons = (manifest && manifest.drop_reasons) || null;
  if (reasons && typeof reasons === 'object') {
    metricVal('screening-m-twins',
      (reasons.twin_r3 !== undefined && reasons.twin_r3 !== null) ? reasons.twin_r3 : null,
      'سرور تفکیک علت ثبت نکرد');
    metricVal('screening-m-proper',
      (reasons.proper_r2 !== undefined && reasons.proper_r2 !== null) ? reasons.proper_r2 : null,
      'سرور تفکیک علت ثبت نکرد');
    metricVal('screening-m-other',
      (reasons.other !== undefined && reasons.other !== null) ? reasons.other : null,
      'سرور تفکیک علت ثبت نکرد');
  } else {
    honestVal('screening-m-twins', 'سرور تفکیک علت ثبت نکرد');
    honestVal('screening-m-proper', 'سرور تفکیک علت ثبت نکرد');
    honestVal('screening-m-other', 'سرور تفکیک علت ثبت نکرد');
  }
  perLemma = per;
  if (selectedLemma !== null
      && !perLemma.some((r) => (r && r.lemma) === selectedLemma)) {
    selectedLemma = null;
  }
  renderPerLemma();
  renderDetail();
}
function lemmaMatches(row, q) {
  const needle = String(q || '').trim().toLowerCase();
  if (!needle) return true;
  return String((row && row.lemma) || '').toLowerCase().includes(needle);
}
/* جدول هر-لم: پالایش سمت‌کاربر (بدون فراخوانی سرور) + شمارنده
   «N نمایان از M سطر» + ردیف کلیک‌پذیر. */
function renderPerLemma() {
  const tb = el('screening-per-lemma-tbody');
  const counter = el('screening-visible-count');
  const vis = perLemma
    .map((row, i) => ({row, i}))
    .filter(({row}) => lemmaMatches(row, lemmaQuery));
  if (counter) {
    counter.textContent = (perLemma.length
      ? faNum(vis.length) + ' نمایان از ' + faNum(perLemma.length) + ' سطر'
      : '…');
    counter.removeAttribute('title');
  }
  if (!tb) return;
  tb.replaceChildren();
  if (!perLemma.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 4;
    td.textContent = 'سنجی از سرور نرسید — پس از اجرای موفق پر می‌شود.';
    tr.append(td);
    tb.append(tr);
    return;
  }
  if (!vis.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 4;
    td.textContent = 'ردیفی با این پالایش نیست — پالایش را پاک کنید.';
    tr.append(td);
    tb.append(tr);
    return;
  }
  vis.forEach(({row}) => {
    const tr = document.createElement('tr');
    tr.setAttribute('data-lemma', row.lemma || '');
    tr.tabIndex = 0;
    if (selectedLemma !== null && row.lemma === selectedLemma) {
      tr.classList.add('sel');
    }
    const tdLemma = document.createElement('td');
    if (row.lemma) {
      tdLemma.append(ltrCode(row.lemma));
    } else {
      tdLemma.textContent = '—';
      tdLemma.title = 'سرور این لم را ثبت نکرد';
    }
    const tdIn = document.createElement('td');
    if (row.input_senses !== undefined && row.input_senses !== null) {
      tdIn.textContent = faNum(row.input_senses);
    } else {
      tdIn.textContent = '—';
      tdIn.title = 'سرور این سنج را ثبت نکرد';
    }
    const tdKept = document.createElement('td');
    if (row.kept !== undefined && row.kept !== null) {
      tdKept.textContent = faNum(row.kept);
    } else {
      tdKept.textContent = '—';
      tdKept.title = 'سرور این سنج را ثبت نکرد';
    }
    const tdDrop = document.createElement('td');
    if (row.dropped !== undefined && row.dropped !== null) {
      tdDrop.textContent = faNum(row.dropped);
    } else {
      tdDrop.textContent = '—';
      tdDrop.title = 'سرور این سنج را ثبت نکرد';
    }
    tr.append(tdLemma, tdIn, tdKept, tdDrop);
    tr.addEventListener('click', () => selectLemma(row.lemma));
    tr.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        selectLemma(row.lemma);
      }
    });
    tb.append(tr);
  });
}
function selectLemma(lemma) {
  selectedLemma = lemma;
  renderPerLemma();
  renderDetail();
}
/* جزئیات لم: شمارش‌ها + شناسه‌های حذف‌شده + علت هر حذف از ردیف
   خلاصه (row.drops)؛ غایب -> خالی صادقانه. هرگز متن gloss خوانده
   یا نمایش داده نمی‌شود. */
function renderDetail() {
  const box = el('screening-detail');
  if (!box) return;
  box.replaceChildren();
  const row = perLemma.find((r) => r && r.lemma === selectedLemma);
  if (!row) {
    box.textContent = 'برای دیدن جزئیات یک لم، روی ردیف آن بزنید.';
    box.removeAttribute('title');
    return;
  }
  const head = document.createElement('div');
  head.className = 'screening-detail-head';
  head.append(ltrCode(row.lemma || '—'));
  const counts = document.createElement('span');
  counts.className = 'p-meta';
  counts.textContent = 'ورودی ' + faNum(row.input_senses !== undefined ? row.input_senses : '—')
    + ' • پذیرفته ' + faNum(row.kept !== undefined ? row.kept : '—')
    + ' • حذف‌شده ' + faNum(row.dropped !== undefined ? row.dropped : '—');
  head.append(counts);
  box.append(head);
  const drops = Array.isArray(row.drops) ? row.drops : [];
  if (!drops.length) {
    const empty = document.createElement('div');
    empty.className = 'p-meta';
    empty.textContent = 'شناسه‌های حذف‌شده در خلاصه سرور نیست — فقط شمارش‌ها در دسترس است.';
    empty.title = 'خلاصه manifest شناسه حذف‌شده‌ای برای این لم ندارد.';
    box.append(empty);
    return;
  }
  const list = document.createElement('div');
  list.className = 'screening-drop-list';
  drops.forEach((d) => {
    const line = document.createElement('div');
    line.className = 'screening-drop-line';
    line.append(ltrCode((d && (d.sense_id || d.id)) || '—'));
    const reason = document.createElement('span');
    reason.textContent = String((d && (d.reason || d.kind || d.rule)) || '—');
    line.append(reason);
    list.append(line);
  });
  box.append(list);
}
function renderStatus(st) {
  const state = st.state || 'idle';
  const badge = el('screening-state');
  if (badge) badge.textContent = STATE_FA[state] || state;
  const elapsed = el('screening-elapsed');
  if (elapsed) {
    if (st.elapsed_human && st.elapsed_human !== '—') {
      elapsed.textContent = st.elapsed_human;
      elapsed.removeAttribute('title');
    } else if (st.elapsed !== null && st.elapsed !== undefined) {
      elapsed.textContent = faNum(st.elapsed) + ' ثانیه';
      elapsed.removeAttribute('title');
    } else {
      elapsed.textContent = '—';
      elapsed.title = 'هنوز اجرایی شروع نشده است';
    }
  }
  const resumed = el('screening-resumed');
  if (resumed) {
    if (st.resumed) resumed.removeAttribute('hidden');
    else resumed.setAttribute('hidden', '');
  }
  const out = el('screening-out-path');
  if (out) {
    out.replaceChildren();
    if (st.out_path) {
      out.append(document.createTextNode(st.out_path));
      out.removeAttribute('title');
    } else {
      out.append(document.createTextNode('—'));
      out.title = 'هنوز اجرایی شروع نشده است';
    }
  }
  if (st.out_path) lastOutPath = st.out_path;
  renderLog(st.log, state);
  renderMetrics(st.manifest);
  const handoff = el('screening-handoff');
  const banner = el('screening-handoff-banner');
  const bannerPath = el('screening-handoff-path');
  const done = state === 'completed' && !!st.out_path;
  if (handoff) handoff.disabled = !done;
  if (banner) {
    if (done) {
      banner.removeAttribute('hidden');
      if (bannerPath) {
        bannerPath.replaceChildren();
        bannerPath.append(document.createTextNode(st.out_path));
      }
    } else {
      banner.setAttribute('hidden', '');
    }
  }
  const line = el('screening-status');
  if (line) {
    if (state === 'running') {
      line.textContent = 'در حال اجرا… گزارش زیر زنده به‌روز می‌شود.';
    } else if (state === 'completed') {
      line.textContent = 'اجرا تکمیل شد'
        + ((st.exit_code !== undefined && st.exit_code !== null)
          ? ' (کد خروج ' + faNum(st.exit_code) + ')' : '')
        + (st.out_path ? ' — خروجی آماده تحویل است.' : '.');
    } else if (state === 'failed' || state === 'aborted') {
      line.textContent = 'اجرا ناموفق بود'
        + ((st.exit_code !== undefined && st.exit_code !== null)
          ? ' (کد خروج ' + faNum(st.exit_code) + ')' : '')
        + ' — گزارش بالا را ببینید.';
    } else if (!st.resumed) {
      line.textContent = 'هنوز اجرایی شروع نشده است.';
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
    if (state === 'completed' || state === 'failed' || state === 'aborted') {
      const wasActive = runActive;
      setRunning(false);
      if (state !== 'completed' && wasActive) {
        showFormError('screening-err', 'اجرای غربالگری ناموفق بود.',
          'exit_code=' + ((st.exit_code !== undefined && st.exit_code !== null) ? st.exit_code : '?'),
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
/* A3: پیش‌نمایش دفتر (خوانا-فقط): «X تازه، Y تکراری». */
function scheduleLedger() {
  if (ledgerTimer) clearTimeout(ledgerTimer);
  ledgerTimer = setTimeout(refreshLedger, LEDGER_DEBOUNCE_MS);
}
async function refreshLedger() {
  ledgerTimer = 0;
  const box = el('screening-ledger');
  if (!box) return;
  const wordsEl = el('screening-words');
  const tokens = parseWords(wordsEl && wordsEl.value);
  if (!tokens.length) {
    box.textContent = '…';
    box.removeAttribute('title');
    return;
  }
  try {
    const j = await getJSON('/api/screening/ledger_preview?words='
      + encodeURIComponent(tokens.join(',')));
    const fresh = (j.fresh_count !== undefined && j.fresh_count !== null)
      ? j.fresh_count : (j.fresh || []).length;
    const dup = (j.dup_count !== undefined && j.dup_count !== null)
      ? j.dup_count : (j.duplicate || []).length;
    box.textContent = faNum(fresh) + ' تازه، ' + faNum(dup) + ' تکراری';
    box.removeAttribute('title');
  } catch(e) {
    box.textContent = 'دفتر در دسترس نیست';
    box.title = 'پیش‌نمایش دفتر خوانده نشد: ' + ((e && e.message) || e);
  }
}
/* ارسال یک اجرا به سرور؛ ۴۰۹ برخورد نام یعنی گفت‌وگو لازم است
   (فراخوان پیش‌پرواز را جا انداخته یا مسابقه زمانی رخ داده) —
   پس از انتخاب کاربر حداکثر یک بار دیگر تلاش می‌شود. */
async function postRun(body) {
  try {
    await getJSON('/api/screening/run', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)});
    return true;
  } catch(e) {
    if (e && e.status === 409 && e.body && e.body.collision) {
      return 'collision';
    }
    if (e && e.status === 409) {
      showFormError('screening-err', 'اجرای دیگری هم‌اکنون در حال اجراست.',
        (e && e.message) || e, startRun, undefined);
    } else if (e && e.body && e.body.over_cap) {
      const excess = (e.body.excess !== undefined && e.body.excess !== null)
        ? e.body.excess : '?';
      showFormError('screening-err',
        'فهرست واژه‌ها از سقف ' + faNum(WORDS_MAX) + ' گذشت.',
        'extra=' + faNum(excess) + ' — فهرست را کوتاه کنید.',
        startRun, 'VALIDATION-input');
    } else {
      showFormError('screening-err', 'شروع غربالگری ناموفق بود.',
        (e && e.message) || e, startRun, undefined);
    }
    return false;
  }
}
async function startRun() {
  if (runActive) return;
  const wordsEl = el('screening-words');
  const tokens = parseWords(wordsEl && wordsEl.value);
  if (!tokens.length) {
    showFormError('screening-err', 'واژه‌ای وارد نشده است.',
      'words is empty', startRun, 'VALIDATION-input');
    return;
  }
  /* OQ-2: سقف ۲۵۰۰ fail-fast با شمارش اضافه — هرگز کوتاه‌سازی خاموش. */
  if (tokens.length > WORDS_MAX) {
    const excess = tokens.length - WORDS_MAX;
    showFormError('screening-err',
      'فهرست واژه‌ها از سقف ' + faNum(WORDS_MAX) + ' گذشت.',
      'extra=' + faNum(excess) + ' — فهرست را کوتاه کنید.',
      startRun, 'VALIDATION-input');
    return;
  }
  /* ردیف نامعتبر: نخستین توکن ناسازگار با شماره ردیف گزارش می‌شود. */
  const badIdx = tokens.findIndex((w) => !WORD_RE.test(w));
  if (badIdx >= 0) {
    showFormError('screening-err',
      'ردیف ' + faNum(badIdx + 1) + ' نامعتبر است.',
      'row=' + (badIdx + 1) + ' — فقط حرف لاتین کوچک و خط‌تیره.',
      startRun, 'VALIDATION-input');
    return;
  }
  clearFormError('screening-err');
  const handoff = el('screening-handoff');
  if (handoff) handoff.disabled = true;
  lastOutPath = '';
  const body = {words: tokens.join(','),
    reprocess_duplicates: !!(el('screening-reprocess') && el('screening-reprocess').checked)};
  const nameEl = el('screening-out-name');
  let clean = sanitizeName(nameEl && nameEl.value);
  if (clean) body.out_name = clean;
  const dirEl = el('screening-out-dir');
  const dir = String((dirEl && dirEl.value) || '').trim();
  if (dir) body.out_dir = dir;
  /* برخورد نام (T11): پیش‌پرواز خوانا-فقط پیش از spawn؛ گفت‌وگو
     همیشه پیش از spawn باز می‌شود. جاافتادن پیش‌پرواز را سرور با
     ۴۰۹ جبران می‌کند (تکرار حداکثر یک‌بار پس از انتخاب). */
  if (clean && !dir) {
    let pre = null;
    try {
      pre = await getJSON('/api/screening/exists?out_name='
        + encodeURIComponent(clean));
    } catch(e) {
      pre = null;
    }
    if (pre && pre.exists) {
      const decision = await openCollisionDialog(
        {name: pre.out_name || clean, path: pre.path});
      if (decision.choice === 'cancel') return;
      if (decision.choice === 'auto') body.collision = 'auto';
      else if (decision.choice === 'overwrite') body.collision = 'overwrite';
      else if (decision.choice === 'rename') {
        const fresh = sanitizeName(decision.name);
        if (!fresh) {
          showFormError('screening-err', 'نام تازه خالی است.',
            'rename needs a name', startRun, 'VALIDATION-input');
          return;
        }
        body.out_name = fresh;
        clean = fresh;
      }
    }
  }
  const started = await withBusy(el('screening-start'), 'در حال شروع…', async () => {
    const first = await postRun(body);
    if (first === 'collision') {
      const decision = await openCollisionDialog(
        {name: clean, path: ''});
      if (decision.choice === 'cancel') return false;
      if (decision.choice === 'auto') body.collision = 'auto';
      else if (decision.choice === 'overwrite') body.collision = 'overwrite';
      else if (decision.choice === 'rename') {
        const fresh = sanitizeName(decision.name);
        if (!fresh) {
          showFormError('screening-err', 'نام تازه خالی است.',
            'rename needs a name', startRun, 'VALIDATION-input');
          return false;
        }
        body.out_name = fresh;
        delete body.collision;
      }
      const second = await postRun(body);
      return second === true;
    }
    return first === true;
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
      if (e && e.status === 409) {
        showFormError('screening-err', 'اجرایی در حال اجرا نیست.',
          (e && e.message) || e, abortRun, undefined);
      } else {
        showFormError('screening-err', 'توقف غربالگری ناموفق بود.',
          (e && e.message) || e, abortRun, undefined);
      }
    }
  });
  pollOnce();
}
/* تحویل: تازه‌سازی ورودی غربالگری از مسیر موجود، سپس رفتن به نمای
   پیوندزنی (بنر handoff-path آن نما را loadScreened پر می‌کند). */
async function handoffToLinking() {
  if (!lastOutPath) return;
  await loadScreened();
  openView('view-linking');
}
/* زبانه‌های کابین: زبانه ۱ زنده، زبانه ۲ پوسته T08. */
function selectScreeningTab(id) {
  ['screening-tab-1', 'screening-tab-2'].forEach((pid) => {
    const panel = el(pid);
    if (panel) {
      if (pid === id) panel.removeAttribute('hidden');
      else panel.setAttribute('hidden', '');
    }
  });
  document.querySelectorAll('[data-screening-tab]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-screening-tab') === id);
  });
}
export function initScreeningCabin() {
  const wordsEl = el('screening-words');
  if (wordsEl) {
    wordsEl.addEventListener('input', () => {
      refreshWordsCount();
      scheduleLedger();
    });
  }
  const nameEl = el('screening-out-name');
  if (nameEl && !nameEl.value) nameEl.value = defaultOutName();
  if (nameEl) nameEl.addEventListener('input', refreshNamePreview);
  const smoke = el('screening-smoke');
  if (smoke) smoke.addEventListener('click', () => {
    if (wordsEl) {
      wordsEl.value = SMOKE_WORDS;
      refreshWordsCount();
      scheduleLedger();
    }
  });
  const start = el('screening-start');
  if (start) start.addEventListener('click', startRun);
  const abort = el('screening-abort');
  if (abort) abort.addEventListener('click', abortRun);
  const handoff = el('screening-handoff');
  if (handoff) handoff.addEventListener('click', handoffToLinking);
  document.querySelectorAll('[data-screening-tab]').forEach((btn) => {
    btn.addEventListener('click', () => selectScreeningTab(btn.getAttribute('data-screening-tab')));
  });
  /* پالایش سمت‌کاربر جدول هر-لم: بدون فراخوانی سرور. */
  try {
    new FilterableListController('screening-filter', 'screening-per-lemma-tbody',
      (row, i, q) => lemmaMatches(row, q),
      (q) => { lemmaQuery = q || ''; renderPerLemma(); });
  } catch(e) {}
  refreshWordsCount();
  refreshNamePreview();
  scheduleLedger();
  setRunning(false);
  /* اتصال‌مجدد (T04): وضعیت آغازین را بخوان؛ resumed/running یعنی
     همان run_id با دنباله گزارش از دیسک. */
  getJSON('/api/screening/status').then((raw) => {
    const st = normStatus(raw);
    renderStatus(st);
    if (st.state === 'running') {
      setRunning(true);
      startPolling();
    }
  }).catch(() => {});
}
