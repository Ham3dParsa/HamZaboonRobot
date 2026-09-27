import {getJSON, faNum, ltrCode} from '../shell/api_client.js';
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
    tdModel.append(ltrCode(defaults[p.name] || '—'));
    tr.append(tdName, tdModel);
    for (let i = 0; i < 5; i++) {
      tr.append(honestEmptyCell());
    }
    tb.append(tr);
  }
}

/* مسیرها: فقط ریشه‌های زنده سرور */
export function renderPaths(roots) {
  document.getElementById('paths-badge').textContent = faNum(roots.length) + ' ریشه زنده';
  const tb = document.getElementById('paths-tbody');
  tb.replaceChildren();
  if (!roots.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 4;
    td.textContent = 'بدون ریشه زنده — سرور محلی مسیری گزارش نکرد.';
    tr.append(td);
    tb.append(tr);
    return;
  }
  for (const r of roots) {
    const tr = document.createElement('tr');
    const tdLabel = document.createElement('td');
    tdLabel.textContent = r.label || '—';
    const tdPath = document.createElement('td');
    tdPath.append(ltrCode(r.path || '—'));
    const tdLast = honestEmptyCell();
    const tdRows = honestEmptyCell();
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
  renderPaths(detail.roots || []);
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
    renderPaths((f && f.roots) || []);
  } catch(e) {}
}
fetchAndRenderTelemetry();
fetchAndRenderPaths();
