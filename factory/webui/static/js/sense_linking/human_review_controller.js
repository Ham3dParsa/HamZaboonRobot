import {getJSON, faNum, ltrCode, withBusy, showFormError, clearFormError} from '../shell/api_client.js';
import {FilterableListController} from '../shell/filterable_list_controller.js';
import {PagedListController, emptyDiv, moveAcrossPages} from '../shell/paginated_list_controller.js';
let screenedRows = [];
let screenedTotal = 0;
let screenedPath = '';
let currentSense = null;
let queueIndex = 0;
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
    clearFormError('queue-err');
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
    showFormError('queue-err', 'خواندن ورودی غربالگری ناموفق بود.',
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
/* نمونه‌سازی صف داوری: ورودی queue-filter + ظرف queue-list.
   P06: صفحه‌بندی مشترک p50 از paginated_list_controller (بدون کپی)؛
   تغییر پالایش به صفحه اول برمی‌گردد، پیجر صفحه را می‌گیرد. */
const queuePager = new PagedListController({
  pagerId: 'queue-pager', onPage: () => renderQueue()});
const queueFilterCtl = new FilterableListController(
  'queue-filter', 'queue-list',
  function(row, i, q) { return queueItemMatches(row, i, q); },
  function(q) { queueFilter = q || ''; queuePager.reset(); renderQueue(); });
/* P06: پرچم یک‌بارمصرف آشکارسازی سطر برگزیده — selectSense پیش از
   فراخوان مسلح می‌کند تا امضای بدون‌آرگومان renderQueue (پین
   آزمون‌های صف) حفظ شود؛ رندرهای پیجر/پالایش هرگز آشکار نمی‌کنند. */
let queueRevealArmed = false;
function renderQueue() {
  const box = document.getElementById('queue-list');
  box.replaceChildren();
  const visible = screenedRows.map((row, i) => ({row, i}))
    .filter(({row, i}) => queueItemMatches(row, i));
  queuePager.setTotal(visible.length);
  if (queueRevealArmed) {
    queueRevealArmed = false;
    const pos = visible.findIndex(({i}) => i === queueIndex);
    if (pos >= 0) queuePager.reveal(pos);
  }
  const page = queuePager.pageItems(visible);
  document.getElementById('queue-remaining').textContent =
    faNum(visible.length) + ' از ' + faNum(screenedRows.length) + ' مورد';
  if (!screenedRows.length) {
    box.append(emptyDiv('noRows'));
    return;
  }
  if (!visible.length) {
    box.append(emptyDiv('noFilterMatch'));
    return;
  }
  page.forEach(({row, i}) => {
    const item = document.createElement('div');
    item.className = 'queue-item' + (i === queueIndex ? ' active' : '');
    /* PUX-22: ردیف صف با صفحه‌کلید کار می‌کند (tabIndex + Enter/Space
       مثل ردیف‌های هر-لم غربالگری). */
    item.tabIndex = 0;
    const wrap = document.createElement('div');
    /* PUX-B9: شناسه صف از تک‌مالک api_client (گره ایزوله bdi + dir
       + کلاس)؛ ضخامت پیشین <b> با وزن صریح حفظ می‌شود. */
    const b = ltrCode(row.sense_id || '—');
    b.style.fontWeight = '700';
    if (i === queueIndex) b.style.color = 'var(--c-primary)';
    if (!row.sense_id) b.title = 'سرور این شناسه را ثبت نکرد';
    /* ردیف صف دقیقاً سه چیز حمل می‌کند: شناسه کایکی، برش معنی، وضعیت —
       جزئیات کامل هر سنس در پنل‌های گزینش/داوری است، هرگز در ردیف نیست */
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
      } else if (ev.key === 'ArrowDown') {
        /* P06: پیمایش جهت‌دار با گذر از مرز صفحه از طریق پیجر مشترک. */
        ev.preventDefault();
        moveAcrossPages(box, item, 1, queuePager, '.queue-item');
      } else if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        moveAcrossPages(box, item, -1, queuePager, '.queue-item');
      }
    });
    box.append(item);
  });
}
function selectSense(i) {
  if (!screenedRows.length) {
    currentSense = null;
    queueRevealArmed = true;
    renderQueue();
    return;
  }
  queueIndex = ((i % screenedRows.length) + screenedRows.length) % screenedRows.length;
  currentSense = screenedRows[queueIndex];
  queueRevealArmed = true;
  renderQueue();
}
/* Route-delete (mechanical sprint): the manual-review form lived here —
   per-sense candidate cards + link/none voting now run through the
   mechanical panel (tab 1) and the supervised batches (tab 3). The
   queue above (tab 0) stays the single sense-intake view. */
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
/* T12 OQ-10: every server button runs withBusy (busy «در حال…»,
   no double-click). The refresh wrapper also drops the leaked click
   event arg (R5): refresh always reloads the default screened input. */
document.getElementById('btn-refresh-screened').addEventListener('click', (ev) => {
  withBusy(ev && ev.currentTarget, 'در حال…', () => loadScreened());
});
