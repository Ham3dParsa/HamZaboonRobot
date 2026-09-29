// کنترل باز و بسته شدن سایدبار در تبلت و موبایل
const menuBtn = document.getElementById('menu-toggle-btn');
const mainNav = document.getElementById('main-nav');
const backdrop = document.getElementById('nav-backdrop');

export function toggleMobileNav() {
  mainNav.classList.toggle('open');
  backdrop.classList.toggle('open');
}

menuBtn.addEventListener('click', toggleMobileNav);
backdrop.addEventListener('click', toggleMobileNav);

// ناوبری: کلیک هر دکمه، نمای data-view-target خودش را باز می‌کند
document.querySelectorAll('.nav-btn[data-view-target]').forEach((b) => {
  b.addEventListener('click', () => openView(b.dataset.viewTarget));
});

// تغییر نماهای فضای کاری
export function openView(viewId) {
  document.querySelectorAll('.workspace-view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  const target = document.getElementById(viewId);
  if (target) target.classList.add('active');

  // همگام‌سازی برجستگی دکمه ناوبری با نمای فعال
  document.querySelectorAll('.nav-btn').forEach(b => {
    if (b.dataset.viewTarget === viewId) b.classList.add('active');
  });

  // حافظه نما: آخرین کابین (فقط شناسه نما، بدون راز)
  saveViewMemory(viewId);

  /* P05 scope-check: فرمان‌بر لنگردار به نمای فراخوان چسبیده است —
     با تعویض نما/زبانه بسته می‌شود (بدون نشت به نمای دیگر). */
  try {
    document.dispatchEvent(new CustomEvent('hz:close-popover'));
  } catch(e) {}

  // بستن منو در موبایل پس از انتخاب
  mainNav.classList.remove('open');
  backdrop.classList.remove('open');
}

/* ── حافظه نما: آخرین کابین + زبانه پیوندزنی در localStorage ──
   فقط شناسه‌ها (view-* و شماره زبانه)؛ هیچ راز/کلید/مقدار اپراتوری.
   اجرای اول (مقدار ذخیره‌نشده یا خراب) بدون تغییر، پیش‌فرض موجود می‌ماند. */
function readViewMemory() {
  try {
    const raw = localStorage.getItem('hz-view-memory');
    if (!raw) return null;
    const mem = JSON.parse(raw);
    if (!mem || typeof mem !== 'object') return null;
    return mem;
  } catch(e){ return null; }
}
export function saveViewMemory(viewId, tabIndex) {
  try {
    const mem = readViewMemory() || {};
    if (typeof viewId === 'string' && viewId.indexOf('view-') === 0) mem.view = viewId;
    if (Number.isInteger(tabIndex)) mem.tab = tabIndex;
    localStorage.setItem('hz-view-memory', JSON.stringify(mem));
  } catch(e){}
}
/* زبانه‌های کابین پیوندزنی — همواره محدود به نمای پیوندزنی:
   کابین غربالگری جفت زبانه خودش را دارد (index.html)؛ پرس‌وجوی
   سراسری روی کلاس زبانه‌ها، کلیک زبانه غربالگری را به اشتباه به
   selectLinkingTab می‌رساند و active و حافظه را خراب می‌کرد. */
export function selectLinkingTab(index, persist) {
  const tabs = document.querySelectorAll('#view-linking .cockpit-tabs .tab-link');
  if (!tabs.length) return;
  const idx = Number(index);
  if (!Number.isInteger(idx) || idx < 0 || idx >= tabs.length) return;
  tabs.forEach((t, i) => t.classList.toggle('active', i === idx));
  if (persist !== false) saveViewMemory(null, idx);
  /* P05 scope-check: مانند تعویض نما — فرمان‌بر باز روی زبانه قبلی
     با رفتن به زبانه دیگر بسته می‌شود. */
  try {
    document.dispatchEvent(new CustomEvent('hz:close-popover'));
  } catch(e) {}
  /* P5/R2: زبانه‌ها پنل واقعی‌اند — فقط پنل فعال نمایان است (حافظه
     زبانه در save/restoreViewMemory می‌ماند: رفرش روی همین زبانه
     برمی‌گردد). انتخاب با شناسه است نه ترتیب DOM (ترتیب DOM با شماره
     زبانه یکی نیست). */
  try {
    document.querySelectorAll('#view-linking .linking-tabpanel').forEach((p) => {
      if (p.id === 'linking-tabpanel-' + idx) p.removeAttribute('hidden');
      else p.setAttribute('hidden', '');
    });
  } catch(e){}
}
export function restoreViewMemory() {
  try {
    const mem = readViewMemory();
    if (!mem) return;
    if (typeof mem.view === 'string' && document.getElementById(mem.view)) {
      openView(mem.view);
    }
    if (mem.tab !== undefined && document.getElementById('view-linking')) {
      selectLinkingTab(mem.tab, false);
    }
  } catch(e){}
}
document.querySelectorAll('#view-linking .cockpit-tabs .tab-link').forEach((t) => {
  t.addEventListener('click', () => selectLinkingTab(t.dataset.tabIndex));
});
