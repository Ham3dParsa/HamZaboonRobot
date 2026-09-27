/* ── ماژول پالایش عمیق: کنترلر فهرست پالایش‌پذیر (مستقل و قابل استفاده مجدد) ──
   ورودی: شناسه ورودی پالایش، شناسه ظرف اقلام، تابع تطابق متن
   (row, index, query)؛ خروجی: پالایش زنده بدون دست‌کاری داده.
   نمونه‌سازی فعلی: صف داوری (پالایش زنده با شناسه یا وضعیت)؛
   آماده استفاده مجدد در کابین‌های پیش‌کارت و مخزن داده. */
export class FilterableListController {
  constructor(filterInputId, itemsContainerId, matchFn, onFilter) {
    this.filterEl = document.getElementById(filterInputId);
    this.itemsEl = document.getElementById(itemsContainerId);
    this.matchFn = matchFn;
    this.onFilter = onFilter || function(){};
    this.query = '';
    if (this.filterEl) {
      this.filterEl.addEventListener('input', (ev) => {
        this.query = ev.target.value || '';
        this.onFilter(this.query);
      });
    }
  }
  matches(row, i) {
    try { return this.matchFn(row, i, this.query); }
    catch(e) { return true; }
  }
  apply() { this.onFilter(this.query); }
}
