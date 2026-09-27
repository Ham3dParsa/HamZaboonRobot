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
export function selectLinkingTab(index, persist) {
  const tabs = document.querySelectorAll('.cockpit-tabs .tab-link');
  if (!tabs.length) return;
  const idx = Number(index);
  if (!Number.isInteger(idx) || idx < 0 || idx >= tabs.length) return;
  tabs.forEach((t, i) => t.classList.toggle('active', i === idx));
  if (persist !== false) saveViewMemory(null, idx);
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
document.querySelectorAll('.cockpit-tabs .tab-link').forEach((t, i) => {
  t.addEventListener('click', () => selectLinkingTab(i));
});
