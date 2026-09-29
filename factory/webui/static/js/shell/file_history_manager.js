import {getJSON, faNum} from './api_client.js';
/* مدیر یکپارچه فایل/تاریخچه (P04 — تک‌مالک انتخاب فایل/مقصد همه
   کابین‌ها و گام‌ها؛ جایگزین مسیرهای موازی حقایق).
   مالک انحصاری: فهرست مقصدهای پیش‌فرض (ریشه‌ها + سنجاق‌ها + تازه‌ها)،
   اعتبارسنجی مسیر تایپی (پیش‌پرواز سمت‌کاربر + رأی نهایی سرور
   POST /api/files/resolve)، مصرف حقایق هر ریشه (ریشه خودش، نه سراسری)،
   و پرکردن یکدست ورودی فراخوان (مقدار + رویداد input + ثبت تازه‌ها).
   تاریخچه اجراها دست‌نخورده می‌ماند (cabin_history_controller.js):
   تحویل رکورد همان onHandoff موجود است؛ این مدیر فقط پرکردن ورودی
   را یکدست می‌کند تا «گویش دوم» ساخته نشود.
   نشت سراسری صفر: بدون window.* (تازه‌ها در localStorage با کلید
   نام‌دار hz-file-recents؛ فقط مسیر/گونه، بدون راز). */
let rootsPayload = null;
let rootsPromise = null;
let pinsCache = null;

/* علت‌های ماشینی سرور (cause) → عنوان فارسی (تک‌مالک نگاشت؛ P06
   ممکن است رشته‌های خالی مشترک را همین‌جا تجمیع کند). */
export const CAUSE_FA = {
  'file-missing': 'فایلی در این ریشه نیست — سرور چیزی برای نمایش ثبت نکرد',
  'root-unlistable': 'ریشه خوانده نشد — جابه‌جا یا غیرقابل‌دسترس است',
  'unregistered': 'ریشه در سرور ثبت نیست',
  'over-cap': 'بیش از سقف شمارش — شمار دقیق ثبت نشد',
  'server-missing': 'سرور این ستون را ثبت نمی‌کند',
};
export function causeFa(code) {
  return CAUSE_FA[String(code || '')] || CAUSE_FA['server-missing'];
}

export async function fetchRoots(force) {
  if (!force && rootsPayload) return rootsPayload;
  if (!force && rootsPromise) return rootsPromise;
  rootsPromise = getJSON('/api/files/roots').then((j) => {
    rootsPayload = j || {roots: []};
    return rootsPayload;
  }).catch((e) => {
    rootsPromise = null;
    throw e;
  });
  return rootsPromise;
}
export function clearRootsCache() {
  rootsPayload = null;
  rootsPromise = null;
}
/* حقایق همان ریشه (L4): هرگز از ریشه دیگر یا سراسری نمی‌آید.
   برمی‌گرداند {facts|null, cause} — cause همیشه کد ماشینی است. */
export function rootFacts(root) {
  const f = root && root.files;
  if (f && typeof f === 'object' && ('exists' in f)) {
    return {facts: f, cause: f.exists ? '' : (f.cause || 'file-missing')};
  }
  return {facts: null, cause: 'unregistered'};
}

/* ── مقصدهای پیش‌فرض (تک‌مالک فهرست) ── */
const KIND_USEFULNESS = [
  [/data root/i, 'پوشه داده مشترک همه کنسول‌ها — ورودی‌ها و خروجی‌ها اینجا می‌نشینند.'],
  [/bundled samples|pilot/i, 'نمونه‌های آماده بسته — برای شروع بدون فایل خوب است.'],
  [/this console runs/i, 'خروجی اجراهای همین کنسول — تحویل‌ها اینجا هستند.'],
  [/home/i, 'پوشه خانه اپراتور — مسیرهای شخصی اینجا هستند.'],
  [/drive/i, 'ریشه درایو — مرور سراسری دیسک.'],
];
export function usefulnessFor(label) {
  const text = String(label || '');
  for (const [rx, sentence] of KIND_USEFULNESS) {
    if (rx.test(text)) return sentence;
  }
  return 'ریشه مرور سرور — برای برداشتن فایل یا پوشه خوب است.';
}
export async function listPins(force) {
  if (!force && pinsCache) return pinsCache;
  try {
    const j = await getJSON('/api/files/pins');
    pinsCache = (j && j.pins) || [];
    return pinsCache;
  } catch(e) {
    return pinsCache || [];
  }
}
export function clearPinsCache() {
  pinsCache = null;
}
const RECENTS_KEY = 'hz-file-recents';
const RECENTS_CAP = 8;
export function listRecents() {
  try {
    const raw = localStorage.getItem(RECENTS_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((r) => r && r.path) : [];
  } catch(e) {
    return [];
  }
}
export function rememberRecent(path, kind) {
  const clean = String(path || '').trim();
  if (!clean) return;
  const k = (kind === 'file') ? 'file' : 'dir';
  try {
    const rest = listRecents().filter((r) => r.path !== clean);
    rest.unshift({path: clean, kind: k, at: Date.now()});
    localStorage.setItem(RECENTS_KEY, JSON.stringify(rest.slice(0, RECENTS_CAP)));
  } catch(e) {}
}
/* فهرست پیش‌فرض حالت‌مند: input → فایل‌ها (سنجاق فایل + تازه فایل)؛
   dest → پوشه‌ها (ریشه‌ها + سنجاق پوشه + تازه پوشه). هر درایه:
   {value, label, kind, usefulness, effect}. */
export async function presetDestinations(mode, targetLabel) {
  const dest = (mode === 'dest');
  const effect = 'با انتخاب، در ورودی «' + String(targetLabel || 'مقصد') + '» می‌نشیند.';
  let payload = null;
  try {
    payload = await fetchRoots();
  } catch(e) {
    payload = {roots: []};
  }
  const roots = (payload && payload.roots) || [];
  const pins = await listPins();
  const recents = listRecents();
  const out = [];
  if (dest) {
    roots.forEach((r) => {
      if (!r || !r.path) return;
      out.push({value: r.path, label: (r.label || r.path) + ' (ریشه)',
        kind: 'dir', usefulness: usefulnessFor(r.label), effect});
    });
  }
  pins.forEach((p) => {
    if (!p || !p.path) return;
    if (dest && p.kind !== 'dir') return;
    if (!dest && p.kind !== 'file') return;
    out.push({value: p.path, label: p.name + ' (سنجاق)',
      kind: p.kind, usefulness: 'سنجاق ذخیره‌شده شما — میان‌بر مسیر پرتکرار.',
      effect});
  });
  recents.forEach((r) => {
    if (!r || !r.path) return;
    if (dest && r.kind !== 'dir') return;
    if (!dest && r.kind !== 'file') return;
    if (out.some((o) => o.value === r.path)) return;
    out.push({value: r.path, label: r.path + ' (تازه)',
      kind: r.kind, usefulness: 'به‌تازگی استفاده شده — ادامه کار قبلی.',
      effect});
  });
  return out;
}

/* ── اعتبارسنجی مسیر تایپی (پیش‌فرض‌ها + تایپ آزاد) ──
   پیش‌پرواز سمت‌کاربر با ریشه‌های شناخته‌شده؛ رأی نهایی همیشه سرور
   (POST /api/files/resolve — خارج از ریشه‌های مجاز → 400). */
export function clientPrefixOk(path, roots) {
  return matchRoot(path, roots) !== null;
}
/* longest-prefix root match (single owner — popover + validation share it). */
export function matchRoot(path, roots) {
  const norm = (s) => String(s || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
  const want = norm(path);
  if (!want) return null;
  let best = null;
  for (const r of (roots || [])) {
    const base = norm(r && r.path);
    if (!base) continue;
    if (want === base || want.indexOf(base + '/') === 0) {
      if (!best || base.length > String(best.path || '').length) best = r;
    }
  }
  return best;
}
/* سطر دوم ردیف فرمان‌بر: حقایق همان ریشه به فارسی، یا null (خالی عنوان‌دار). */
export function factsLine(facts) {
  if (!facts || !facts.exists) return null;
  const label = String((facts.lines_label !== undefined && facts.lines_label !== null)
    ? facts.lines_label : '—');
  const size = (facts.size !== undefined && facts.size !== null) ? facts.size : '—';
  const mtime = String(facts.mtime_relative || '—');
  if (label === '—' && String(size) === '—' && (mtime === '—' || !mtime)) return null;
  return faNum(label) + ' سطر / ' + faNum(size) + ' بایت • ' + faNum(mtime);
}
export async function validateCustomPath(path, kind) {
  const clean = String(path || '').trim();
  if (!clean) return {ok: false, error: 'مسیر خالی است — یک مسیر بنویسید یا پیش‌فرضی برگزینید.'};
  let roots = [];
  try {
    const payload = await fetchRoots();
    roots = (payload && payload.roots) || [];
  } catch(e) {}
  if (roots.length && !clientPrefixOk(clean, roots)) {
    return {ok: false, error: 'بیرون از ریشه‌های مجاز است — یکی از ریشه‌ها یا سنجاق‌ها را برگزینید.'};
  }
  try {
    const j = await getJSON('/api/files/resolve', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: clean, kind: kind || undefined})});
    return {ok: true, path: (j && j.path) || clean};
  } catch(e) {
    return {ok: false, error: 'سرور مسیر را نپذیرفت (' + String((e && e.message) || e) + ').'};
  }
}

/* ── پرکردن یکدست ورودی فراخوان (تک‌راه) ── */
export function fillInput(target, value, kind) {
  const node = (typeof target === 'string') ? document.getElementById(target) : target;
  if (!node || typeof node.value === 'undefined') return false;
  node.value = String(value === null || value === undefined ? '' : value);
  try {
    node.dispatchEvent(new Event('input', {bubbles: true}));
  } catch(e) {}
  try {
    if (typeof node.focus === 'function') node.focus();
  } catch(e) {}
  rememberRecent(String(value || ''), kind);
  try {
    document.dispatchEvent(new CustomEvent('hz:manager-filled',
      {detail: {target: (node && node.id) || '', value: String(value || '')}}));
  } catch(e) {}
  return true;
}
