import {faNum} from './api_client.js';
/* ── P06: ماژول مشترک فهرست صفحه‌دار (p50) + خالی‌های عنوان‌دار ──
   همراه صفحه‌بندی FilterableListController (نه انشعاب از آن): پالایش
   در مالک فهرست می‌ماند، این ماژول فقط برش صفحه + پیجر + شمار را
   می‌دهد. اندازه صفحه پیش‌فرض ۵۰ (تک‌مالک PAGED_LIST_SIZE)؛ هرگز
   بیش از یک صفحه در DOM سوار نمی‌شود. پذیرندگان (بدون کپی):
   صف داوری، جدول هر-لم، تاریخچه اجراها، فهرست فایل‌ها. پالایش روی
   همه صفحه‌ها نگه داشته می‌شود (تغییر پالایش → reset به صفحه اول).
   خالی‌های عنوان‌دار شش‌گانه در EMPTY_FA (تک‌مالک رشته‌ها): هر حالت
   خالی جمله فارسی کوتاه + title علت دارد؛ هیچ «…» لخت و هیچ «—»
   لخت در مسیرهای فهرست پذیرفته نیست.
   نشت سراسری صفر: بدون window.*. */
export const PAGED_LIST_SIZE = 50;

/* واژه‌نامه خالی‌های عنوان‌دار (هر درایه {text, title}) —
   no-roots: ریشه‌ای برای مرور نیست؛ no-rows: منبع داده خالی؛
   no-filter-match: پالایش بی‌هم‌خوان؛ no-history: تاریخچه خالی؛
   popover-group-empty: گروه فرمان‌بر بی‌هم‌خوان؛ missing-fact:
   مقداری که سرور ثبت نکرد (خط‌تیره عنوان‌دار). */
export const EMPTY_FA = {
  noRoots: {text: 'ریشه‌ای نیست — پوشه داده جابه‌جا شده است؟',
    title: 'سرور ریشه‌ای برنگرداند؛ خالی صادقانه است، نه خطا.'},
  noRows: {text: 'ردیفی نیست — پس از رسیدن داده اینجا پر می‌شود.',
    title: 'منبع داده خالی است؛ خالی صادقانه است، نه خطا.'},
  noFilterMatch: {text: 'ردیفی با این پالایش نیست — پالایش را پاک کنید.',
    title: 'پالایش جاری هم‌خوانی ندارد؛ داده‌ای حذف نشده است.'},
  noHistory: {text: 'هنوز اجرایی برای این کابین ثبت نشده است — پس از نخستین اجرای موفق اینجا پر می‌شود.',
    title: 'سرور runs خالی برگرداند؛ خالی صادقانه است، نه خطا.'},
  popoverGroupEmpty: {text: 'در این گروه هم‌خوانی نیست.',
    title: 'پالایش جاری هم‌خوانی در این گروه ندارد.'},
  missingFact: {text: '—',
    title: 'سرور این مقدار را ثبت نکرد'},
};

/* سطر خالی عنوان‌دار جدول (colSpan همان جدول پذیرنده). */
export function emptyRow(colSpan, key) {
  const entry = EMPTY_FA[key] || EMPTY_FA.noRows;
  const tr = document.createElement('tr');
  const td = document.createElement('td');
  td.colSpan = colSpan;
  td.textContent = entry.text;
  td.title = entry.title;
  tr.append(td);
  return tr;
}

/* خالی عنوان‌دار ظرف بلوکی (صف داوری: div، نه جدول). */
export function emptyDiv(key) {
  const entry = EMPTY_FA[key] || EMPTY_FA.noRows;
  const div = document.createElement('div');
  div.className = 'p-meta';
  div.textContent = entry.text;
  div.title = entry.title;
  return div;
}

export class PagedListController {
  constructor(opts) {
    const o = opts || {};
    this.pagerId = String(o.pagerId || '');
    this.onPage = (typeof o.onPage === 'function') ? o.onPage : null;
    this.page = 0;
    this.total = 0;
    this._built = false;
  }
  get pageSize() {
    return PAGED_LIST_SIZE;
  }
  pages() {
    return Math.max(1, Math.ceil(this.total / PAGED_LIST_SIZE));
  }
  hasNext() {
    return this.page < this.pages() - 1;
  }
  hasPrev() {
    return this.page > 0;
  }
  setTotal(total) {
    this.total = Math.max(0, Number(total) || 0);
    if (this.page > this.pages() - 1) this.page = this.pages() - 1;
    if (this.page < 0) this.page = 0;
    this.paint();
  }
  /* تغییر پالایش → بازگشت به صفحه اول (پالایش روی همه صفحه‌ها). */
  reset() {
    this.page = 0;
  }
  /* نمایان‌کردن موقعیت سراسری pos (انتخاب/جهش): پیجر صفحه را می‌گیرد. */
  reveal(pos) {
    const p = Math.floor(Math.max(0, Number(pos) || 0) / PAGED_LIST_SIZE);
    this.page = Math.min(Math.max(0, p), this.pages() - 1);
  }
  /* برش صفحه جاری (حداکثر یک صفحه در DOM) + نگاشت شمار دقیق. */
  pageItems(all) {
    const arr = Array.isArray(all) ? all : [];
    this.setTotal(arr.length);
    const start = this.page * PAGED_LIST_SIZE;
    return arr.slice(start, start + PAGED_LIST_SIZE);
  }
  next() {
    if (!this.hasNext()) return this.page;
    this.page += 1;
    this.paint();
    if (this.onPage) this.onPage();
    return this.page;
  }
  prev() {
    if (!this.hasPrev()) return this.page;
    this.page -= 1;
    this.paint();
    if (this.onPage) this.onPage();
    return this.page;
  }
  pagerEl() {
    if (!this.pagerId) return null;
    try {
      return document.getElementById(this.pagerId);
    } catch(e) {
      return null;
    }
  }
  ensure() {
    const box = this.pagerEl();
    if (!box || this._built) return;
    box.replaceChildren();
    const prev = document.createElement('button');
    prev.type = 'button';
    prev.className = 'btn-skip-next';
    prev.setAttribute('data-pager', 'prev');
    prev.textContent = '‹ قبلی';
    prev.title = 'صفحه قبلی فهرست';
    prev.addEventListener('click', () => this.prev());
    const label = document.createElement('span');
    label.className = 'p-meta';
    label.setAttribute('data-pager', 'label');
    label.setAttribute('aria-live', 'polite');
    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'btn-skip-next';
    next.setAttribute('data-pager', 'next');
    next.textContent = 'بعدی ›';
    next.title = 'صفحه بعدی فهرست';
    next.addEventListener('click', () => this.next());
    box.append(prev, document.createTextNode(' '), label,
      document.createTextNode(' '), next);
    this._built = true;
  }
  paint() {
    const box = this.pagerEl();
    if (!box) return;
    /* تک‌صفحه‌ای: پیجر پنهان (بدون تغییر چیدمان فهرست‌های کوتاه). */
    if (this.total <= PAGED_LIST_SIZE) {
      box.setAttribute('hidden', '');
      return;
    }
    box.removeAttribute('hidden');
    this.ensure();
    const prev = box.querySelector('[data-pager="prev"]');
    const next = box.querySelector('[data-pager="next"]');
    const label = box.querySelector('[data-pager="label"]');
    if (prev) prev.disabled = !this.hasPrev();
    if (next) next.disabled = !this.hasNext();
    if (label) {
      label.textContent = 'صفحه ' + faNum(this.page + 1)
        + ' از ' + faNum(this.pages());
    }
  }
}

/* پیمایش جهت‌دار ردیف‌ها با گذر از مرز صفحه از طریق پیجر —
   قرارداد صفحه‌کلید §1.7 درون صفحه‌بندی حفظ می‌شود: Enter/Space
   در مالک فهرست می‌ماند، بالا/پایین در انتهای صفحه ورق می‌زند و
   فوکوس را به نخستین/واپسین ردیف صفحه تازه می‌برد. برمی‌گرداند
   true وقتی کلیدی مصرف شد. */
export function moveAcrossPages(box, cur, delta, pager, selector) {
  if (!box || !cur || !pager) return false;
  const rows = Array.from(box.querySelectorAll(selector));
  const i = rows.indexOf(cur);
  const j = i + delta;
  if (j >= 0 && j < rows.length) {
    rows[j].focus();
    return true;
  }
  if (delta > 0 && pager.hasNext()) {
    pager.next();
    const fresh = box.querySelectorAll(selector);
    if (fresh.length) fresh[0].focus();
    return true;
  }
  if (delta < 0 && pager.hasPrev()) {
    pager.prev();
    const fresh = box.querySelectorAll(selector);
    if (fresh.length) fresh[fresh.length - 1].focus();
    return true;
  }
  return false;
}
