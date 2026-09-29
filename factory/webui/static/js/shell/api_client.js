/* ── سیم‌کشی زنده: همه عددها از سرور، بدون عدد نمایشی ── */
const FA_DIGITS = {'0':'۰','1':'۱','2':'۲','3':'۳','4':'۴','5':'۵','6':'۶','7':'۷','8':'۸','9':'۹'};
export function faNum(v) {
  return String(v === null || v === undefined ? '—' : v).replace(/[0-9]/g, d => FA_DIGITS[d]);
}
/* شناسه ماشینی همیشه در عنصر لاتین ایزوله (§2.2): bdi + dir + کلاس */
export function ltrCode(text) {
  const s = document.createElement('bdi');
  s.className = 'code-token';
  s.setAttribute('dir', 'ltr');
  s.textContent = String(text === null || text === undefined ? '—' : text);
  return s;
}
/* خانه عدد فارسی (تک‌مالک PUX-B9 در کنار faNum/ltrCode): رقم فارسی
   با قلم بدنه، علت در title. */
export function faCell(value, title) {
  const s = document.createElement('span');
  s.textContent = faNum(value);
  if (title) s.title = title;
  return s;
}

/* ── سامانه طراحی منجمد: جعبه خطای سه‌بخشی + حالت مشغولی ──
   هر شکاف خطای فرم سه بخش دارد: (۱) نشان کد استاندارد + پیام ساده
   فارسی، (۲) جزئیات سرور در عنصر لاتین ایزوله، (۳) دکمه تلاش دوباره
   + دکمه کپی گزارش (نام‌ها فقط؛ هیچ مقداری هرگز کپی نمی‌شود).
   پیشوندهای استاندارد (§5.1): NET-xxx / AUTH-* / QUOTA-429 / VALIDATION-* */
const formErrorRetry = {};
export function errCodeFor(err) {
  const status = err && err.status;
  if (status === 429) return 'QUOTA-429';
  if (status) return 'NET-' + status;
  const d = String((err && err.message) || err || '');
  if (/429|سهمیه|quota|rate/i.test(d)) return 'QUOTA-429';
  if (/401|403|missing key|کلید|توکن|token|auth/i.test(d)) return 'AUTH-missing-key';
  if (/400|empty|خالی|invalid|نامعتبر|bad/i.test(d)) return 'VALIDATION-input';
  return 'NET-unknown';
}
export function buildFormError(faMessage, detail, retryFn, slotId, code) {
  const box = document.createElement('div');
  box.className = 'form-error';
  box.setAttribute('role', 'alert');
  const errCode = code || errCodeFor(detail);
  box.setAttribute('data-code', errCode);
  const badge = document.createElement('span');
  badge.className = 'badge error-code';
  badge.textContent = String(errCode).replace('-', ' · ');
  box.append(badge);
  const msg = document.createElement('div');
  msg.className = 'form-error-msg';
  msg.textContent = faMessage;
  box.append(msg);
  if (detail) {
    const det = document.createElement('div');
    det.className = 'form-error-detail';
    det.textContent = String(detail);
    box.append(det);
  }
  const actions = document.createElement('div');
  actions.className = 'form-error-actions';
  if (typeof retryFn === 'function') {
    if (slotId) formErrorRetry[slotId] = retryFn;
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = 'تلاش دوباره';
    retry.addEventListener('click', () => {
      const fn = slotId ? formErrorRetry[slotId] : retryFn;
      if (typeof fn === 'function') fn();
    });
    actions.append(retry);
  }
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.textContent = 'کپی گزارش';
  copy.addEventListener('click', async () => {
    const errCode = box.getAttribute('data-code') || '';
    const report = (errCode ? errCode + ' — ' : '') + faMessage + (detail ? ' — ' + detail : '');
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(report);
      } else {
        const ta = document.createElement('textarea');
        ta.value = report;
        document.body.append(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
      }
      copy.textContent = 'گزارش کپی شد';
    } catch(e) {
      copy.textContent = 'کپی ناموفق بود';
    }
  });
  actions.append(copy);
  box.append(actions);
  return box;
}
export function clearFormError(slotId) {
  const slot = document.getElementById(slotId);
  if (slot) slot.replaceChildren();
  delete formErrorRetry[slotId];
}
export function showFormError(slotId, faMessage, detail, retryFn, code) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  slot.replaceChildren();
  slot.append(buildFormError(faMessage, detail, retryFn, slotId, code));
}
/* حالت مشغولی دکمه‌های متصل به سرور: غیرفعال + متن «در حال…»
   با بازیابی در finally. (دو تابع supervisorWake و
   fetchPresetModels حالت مشغولی درونی قفل‌شده خود را نگه
   می‌دارند و از این کمک‌گیر استفاده نمی‌کنند.) */
export async function withBusy(btn, busyText, fn) {
  const idle = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = busyText; }
  try { return await fn(); }
  finally { if (btn) { btn.disabled = false; btn.textContent = idle; } }
}
/* کپی گزارش عیب‌یابی: نام‌ها فقط، هیچ مقدار رازی هرگز کپی نمی‌شود */
export async function copyReport(text, btn, doneText) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.append(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    if (btn) btn.textContent = doneText || 'کپی شد';
  } catch(e) {
    if (btn) btn.textContent = 'کپی ناموفق بود';
  }
}
export async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  let j = null;
  try { j = await r.json(); } catch(e){}
  if (!r.ok) {
    const err = new Error((j && j.error) || ('خطای ' + r.status));
    err.status = r.status;
    err.body = j;
    throw err;
  }
  return j;
}
