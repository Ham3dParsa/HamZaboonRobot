import {getJSON, faNum, ltrCode} from '../shell/api_client.js';
import {rootFacts, causeFa} from '../shell/file_history_manager.js';
/* تله‌متری: فقط حقایق زنده نرخ/کلید/مسیر؛ ستون توکن صادقانه خالی —
   خانه ثبت‌نشده هرگز دیوار «—» بی‌برچسب نیست: برچسب «سرور ثبت نمی‌کند» */
function honestEmptyCell() {
  const td = document.createElement('td');
  td.className = 'honest-empty';
  td.textContent = '—';
  td.title = 'سرور ثبت نمی‌کند';
  return td;
}
export function renderTelemetry(providers, rates, info) {
  const ready = providers.filter(p => p.has_key).length;
  const groups = rates.reduce((n, r) => n + (r.groups_count || 0), 0);
  const direct = rates.filter(r => r.route === 'direct').length;
  const tunnel = rates.filter(r => r.route === 'tunnel').length;
  document.getElementById('telemetry-badge').textContent =
    faNum(providers.length) + ' ارائه‌دهنده زنده';
  document.getElementById('t-ready').textContent = faNum(ready) + ' / ' + faNum(providers.length);
  document.getElementById('t-groups').textContent = faNum(groups) + ' / ' + faNum(rates.length * 2);
  document.getElementById('t-routes').textContent = faNum(direct) + ' مستقیم / ' + faNum(tunnel) + ' تونل';
  const tb = document.getElementById('telemetry-tbody');
  tb.replaceChildren();
  const defaults = (info.default_models || {});
  if (!providers.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 7;
    td.textContent = 'بدون ارائه‌دهنده زنده — رجیستری موتور خالی است.';
    tr.append(td);
    tb.append(tr);
    return;
  }
  for (const p of providers) {
    const tr = document.createElement('tr');
    const tdName = document.createElement('td');
    tdName.append(ltrCode(p.name));
    const tdModel = document.createElement('td');
    if (defaults[p.name]) {
      tdModel.append(ltrCode(defaults[p.name]));
    } else {
      tdModel.textContent = '—';
      tdModel.title = 'سرور ثبت نمی‌کند';
      tdModel.className = 'honest-empty';
    }
    tr.append(tdName, tdModel);
    for (let i = 0; i < 5; i++) {
      tr.append(honestEmptyCell());
    }
    tb.append(tr);
  }
}

/* مسیرها: فقط ریشه‌های زنده سرور + حقایق همان ریشه (P04/L4).
   هر ردیف هر چهار مقدار بودن/اندازه/سطرها/زمان اصلاح را فقط از
   files همان ریشه می‌خواند (ریشه خودش، هرگز سراسری تکراری):
   ستون ۳ «آخرین فایل معتبر» = mtime نسبی (T02 format_moment، جزئیات
   شمسی+میلادی در title)؛ ستون ۴ «تعداد سطرها / حجم» = lines_label
   (سقف «۵۰۰۰۰+» با اعداد فارسی) + اندازه بایت. ناموجود -> «—»
   عنوان‌دار (علت فایل-ناموجود/ثبت‌نشده/بیش‌از‌سقف از cause همان
   ریشه). ریشه مرده از سرور نمی‌آید؛ نشان شمار با سطرهای نمایان
   برابر است. هرگز عدد ساختگی نیست. پارامتر سراسری files فقط برای
   سازگاری رویداد نگه داشته شده و خوانده نمی‌شود. */
function titledEmpty(cause) {
  const td = document.createElement('td');
  td.className = 'honest-empty';
  td.textContent = '—';
  td.title = cause;
  return td;
}
export function renderPaths(roots, files) {
  const list = Array.isArray(roots) ? roots : [];
  const badge = document.getElementById('paths-badge');
  if (badge) {
    badge.textContent = faNum(list.length) + ' ریشه زنده';
    badge.title = list.length
      ? 'ریشه‌های ناموجود خودبه‌خود کنار رفتند؛ شمار نشان با سطرهای جدول برابر است.'
      : 'سرور محلی مسیری گزارش نکرد.';
  }
  const tb = document.getElementById('paths-tbody');
  if (!tb) return;
  tb.replaceChildren();
  if (!list.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 4;
    td.textContent = 'بدون ریشه زنده — سرور محلی مسیری گزارش نکرد.';
    tr.append(td);
    tb.append(tr);
    return;
  }
  /* P04/L4: پارامتر سراسری files خوانده نمی‌شود (سازگاری رویداد) —
     هر ردیف فقط حقایق ریشه خودش را می‌خواند. */
  for (const r of list) {
    /* حقایق همین ردیف از همان ریشه (نه سراسری). */
    const rowFacts = rootFacts(r);
    const facts = rowFacts.facts;
    const missingCause = causeFa(rowFacts.cause);
    const tr = document.createElement('tr');
    const tdLabel = document.createElement('td');
    if (r && r.label) {
      tdLabel.textContent = r.label;
    } else {
      tdLabel.textContent = '—';
      tdLabel.title = 'سرور این ریشه را ثبت نکرد';
      tdLabel.className = 'honest-empty';
    }
    const tdPath = document.createElement('td');
    if (r && r.path) {
      tdPath.append(ltrCode(r.path));
      tdPath.title = r.path;
    } else {
      tdPath.textContent = '—';
      tdPath.title = 'سرور مسیری برای این ریشه ثبت نکرد';
      tdPath.className = 'honest-empty';
    }
    /* ستون ۳: mtime نسبی + جزئیات تقویم در title (OQ-9-consume). */
    let tdLast;
    if (facts && facts.exists && facts.mtime_relative && facts.mtime_relative !== '—') {
      tdLast = document.createElement('td');
      tdLast.textContent = faNum(facts.mtime_relative);
      tdLast.title = String(facts.mtime_detail || facts.mtime_iso || '');
    } else if (facts && facts.exists) {
      tdLast = titledEmpty('فایل موجود است ولی سرور زمان اصلاح را ثبت نکرد');
    } else if (facts && facts.exists === false) {
      tdLast = titledEmpty(missingCause);
    } else {
      tdLast = titledEmpty(missingCause);
    }
    /* ستون ۴: lines_label (سقف «۵۰۰۰۰+») + اندازه؛ بودن از exists. */
    let tdRows;
    if (facts && facts.exists) {
      tdRows = document.createElement('td');
      const label = String((facts.lines_label !== undefined && facts.lines_label !== null)
        ? facts.lines_label : '—');
      const size = (facts.size !== undefined && facts.size !== null) ? facts.size : '—';
      tdRows.textContent = faNum(label) + ' سطر / ' + faNum(size) + ' بایت';
      tdRows.title = facts.truncated
        ? causeFa('over-cap') + ' (' + faNum(label) + ')'
        : 'حقایق زنده همین ریشه';
    } else if (facts && facts.exists === false) {
      tdRows = titledEmpty(missingCause);
    } else {
      tdRows = titledEmpty(missingCause);
    }
    tr.append(tdLabel, tdPath, tdLast, tdRows);
    tb.append(tr);
  }
}
document.addEventListener('hz:providers-refreshed', (ev) => {
  const detail = (ev && ev.detail) || {};
  renderTelemetry(detail.rows || [], detail.rateRows || [], detail.info || {});
});
document.addEventListener('hz:paths-refreshed', (ev) => {
  const detail = (ev && ev.detail) || {};
  renderPaths(detail.roots || [], detail.files || {});
});
/* مسابقه مقداردهی: جدول‌ها روی بارگذاری صفحه پر می‌شوند —
   رویدادهای hz *ممکن است پیش از شنونده‌ها برسند؛ واکشی مستقیمِ
   آغازین در کنار شنونده‌ها انجماد «...» را می‌بندد */
export async function fetchAndRenderTelemetry() {
  try {
    const [p, rs, info] = await Promise.all([
      getJSON('/api/providers'), getJSON('/api/rate_state'), getJSON('/api/engine_info')
    ]);
    renderTelemetry((p && p.providers) || [], (rs && rs.providers) || [], info || {});
  } catch(e) {}
}
export async function fetchAndRenderPaths() {
  try {
    const f = await getJSON('/api/files/roots');
    renderPaths((f && f.roots) || [], (f && f.files) || {});
  } catch(e) {}
}
fetchAndRenderTelemetry();
fetchAndRenderPaths();
