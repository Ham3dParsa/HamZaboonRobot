import {getJSON, faNum, ltrCode, showFormError, clearFormError} from './api_client.js';
import {FilterableListController} from './filterable_list_controller.js';
import {PagedListController, EMPTY_FA} from './paginated_list_controller.js';
/* کنترلر GENERIC تاریخچه اجراهای کابین‌ها (T08: نمونه‌سازی برای غربالگری؛
   کابین‌های بعدی همین کلاس را با cabin خودشان نمونه می‌سازند — بدون کپی).
   منبع: GET /api/runs/history?cabin=<id> (سرور newest-last می‌دهد؛ همین
   ترتیب نگه داشته می‌شود). پالایش زنده سمت‌کاربر روی نام/وضعیت/مسیر
   (بدون فراخوانی سرور) با FilterableListController. تحویل هر رکورد از
   طریق onHandoff تزریقی (قرارداد handoff موجود، مثل loadScreened-style
   + openView) — خود کنترلر هیچ وابستگی دامنه‌ای ندارد.
   خالی صادقانه عنوان‌دار وقتی runs خالی است (هرگز خط‌تیره لخت).
   نشت سراسری صفر: همه حالت‌ها در نمونه، بدون window.*. */
const STATUS_FA = {completed: 'تکمیل شد', failed: 'ناموفق بود',
  aborted: 'متوقف شد', running: 'در حال اجرا', unknown: 'نامشخص'};
export class CabinHistoryController {
  constructor(opts) {
    const o = opts || {};
    this.cabin = String(o.cabin || '').trim();
    this.historyUrl = String(o.historyUrl
      || ('/api/runs/history?cabin=' + encodeURIComponent(this.cabin)));
    this.filterInputId = o.filterInputId;
    this.tbodyId = o.tbodyId;
    this.counterId = o.counterId;
    this.errorSlotId = o.errorSlotId;
    this.onHandoff = (typeof o.onHandoff === 'function') ? o.onHandoff : null;
    this.handoffLabel = o.handoffLabel || 'تحویل به کابین بعدی';
    this.rows = [];
    this.query = '';
    /* P06: صفحه‌بندی مشترک p50 (بدون کپی) — pagerId تزریقی؛ بدون آن
       رفتار تک‌صفحه‌ای پیشین حفظ می‌شود. */
    this.pager = new PagedListController({
      pagerId: String(o.pagerId || ''), onPage: () => this.render()});
    try {
      new FilterableListController(this.filterInputId, this.tbodyId,
        (row, i, q) => this.matches(row, q),
        (q) => { this.query = q || ''; this.pager.reset(); this.render(); });
    } catch(e) {}
  }
  /* زیررشته‌ای روی نام اجرا/وضعیت/مسیر (حساس‌نبودن به بزرگی/کوچکی لاتین). */
  matches(row, q) {
    const needle = String(q !== undefined && q !== null ? q : this.query || '')
      .trim().toLowerCase();
    if (!needle) return true;
    const hay = [row && row.run_id, row && row.out_name,
      row && row.status, row && row.out_dir]
      .map((v) => String(v || '').toLowerCase()).join(' ');
    return hay.includes(needle);
  }
  setCounter(visible, total) {
    const node = document.getElementById(this.counterId);
    if (!node) return;
    if (!total) {
      node.textContent = '…';
      node.title = EMPTY_FA.noHistory.title;
      return;
    }
    node.textContent = faNum(visible) + ' نمایان از ' + faNum(total) + ' اجرا';
    node.removeAttribute('title');
  }
  screenedFileFor(row) {
    const dir = String((row && row.out_dir) || '').trim();
    if (!dir) return '';
    return dir.replace(/\/+$/, '') + '/screened.jsonl';
  }
  rowButton(row, cell) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-skip-next';
    btn.textContent = this.handoffLabel;
    const target = this.screenedFileFor(row);
    if (!this.onHandoff || !target) {
      btn.disabled = true;
      btn.title = 'مسیر خروجی این اجرا در تاریخچه نیست — تحویل ممکن نیست.';
    } else {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          await this.onHandoff(row);
        } catch(e) {
          showFormError(this.errorSlotId, 'تحویل این اجرا ناموفق بود.',
            (e && e.message) || e, null, undefined);
        } finally {
          btn.disabled = false;
        }
      });
    }
    cell.append(btn);
  }
  render() {
    const tb = document.getElementById(this.tbodyId);
    if (!tb) return;
    const vis = this.rows.filter((row) => this.matches(row, this.query));
    this.pager.setTotal(vis.length);
    const page = this.pager.pageItems(vis);
    this.setCounter(vis.length, this.rows.length);
    tb.replaceChildren();
    if (!this.rows.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 6;
      td.textContent = EMPTY_FA.noHistory.text;
      td.title = EMPTY_FA.noHistory.title;
      tr.append(td);
      tb.append(tr);
      return;
    }
    if (!vis.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 6;
      td.textContent = EMPTY_FA.noFilterMatch.text;
      td.title = EMPTY_FA.noFilterMatch.title;
      tr.append(td);
      tb.append(tr);
      return;
    }
    page.forEach((row) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-run-id', (row && row.run_id) || '');
      const tdRun = document.createElement('td');
      tdRun.append(ltrCode((row && (row.out_name || row.run_id)) || '—'));
      if (!row || (!row.out_name && !row.run_id)) {
        tdRun.title = EMPTY_FA.missingFact.title;
      }
      if (row && row.out_dir) {
        const sub = document.createElement('div');
        sub.className = 'p-meta';
        sub.append(ltrCode(row.out_dir));
        sub.title = row.out_dir;
        tdRun.append(sub);
      }
      const tdStatus = document.createElement('td');
      const st = String((row && row.status) || 'unknown');
      tdStatus.textContent = STATUS_FA[st] || st;
      const tdStarted = document.createElement('td');
      if (row && row.started_iso) {
        tdStarted.append(ltrCode(row.started_iso));
      } else {
        tdStarted.textContent = '—';
        tdStarted.title = 'سرور زمان آغاز ثبت نکرد';
      }
      const tdKept = document.createElement('td');
      tdKept.textContent = faNum(row ? row.kept_total : null);
      if (row && (row.kept_total === null || row.kept_total === undefined)) {
        tdKept.title = 'سرور جمع پذیرفته‌شده ثبت نکرد';
      }
      const tdDropped = document.createElement('td');
      tdDropped.textContent = faNum(row ? row.dropped_total : null);
      if (row && (row.dropped_total === null || row.dropped_total === undefined)) {
        tdDropped.title = 'سرور جمع حذف‌شده ثبت نکرد';
      }
      const tdAct = document.createElement('td');
      this.rowButton(row, tdAct);
      tr.append(tdRun, tdStatus, tdStarted, tdKept, tdDropped, tdAct);
      tb.append(tr);
    });
  }
  /* یک‌بار خواندن تاریخچه (بدون نظرسنجی): newest-last سرور حفظ می‌شود. */
  async refresh() {
    clearFormError(this.errorSlotId);
    try {
      const body = await getJSON(this.historyUrl);
      const runs = (body && body.runs) || [];
      this.rows = Array.isArray(runs) ? runs : [];
    } catch(e) {
      this.rows = [];
      this.render();
      showFormError(this.errorSlotId, 'خواندن تاریخچه اجراها ناموفق بود.',
        (e && e.message) || e, () => this.refresh(), undefined);
      return;
    }
    this.render();
  }
}
