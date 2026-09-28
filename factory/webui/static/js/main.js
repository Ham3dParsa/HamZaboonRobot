import {restoreViewMemory, openView} from './shell/view_navigator.js';
import {withBusy, showFormError, faNum} from './shell/api_client.js';
import {refreshBadges, refreshProviderCards, refreshSupervisorToken, refreshSupervisorLifecycle} from './providers/provider_registry_controller.js';
import {refreshJudgeCatalog} from './arbitration_presets/preset_catalog_controller.js';
import {loadScreened} from './sense_linking/human_review_controller.js';
import {initScreeningCabin} from './screening/screening_cabin_controller.js';
/* T09: تک‌مالک گفت‌وگوی داده — import اثرگذار (سیم‌کشی دکمه‌های
   A1/A2 + آکاردئون را خودش فعال می‌کند؛ نامی لازم نیست). */
import './shell/data_dialog_controller.js';
import {CabinHistoryController} from './shell/cabin_history_controller.js';
/* T2 wiring: the telemetry controller was never imported, so its
   listeners + init fetches never ran and the tables froze on "…" —
   side-effect import loads it (no names needed). */
import './telemetry/telemetry_dashboard_controller.js';
// سیستم سوئیچ تم شب و روز
const themeBtn = document.getElementById('theme-btn');
try {
  const savedTheme = localStorage.getItem('hz-theme');
  if (savedTheme === 'light' || savedTheme === 'dark') {
    document.documentElement.setAttribute('data-theme', savedTheme);
  }
} catch(e){}
themeBtn.addEventListener('click', () => {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const nextTheme = isDark ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', nextTheme);
  try { localStorage.setItem('hz-theme', nextTheme); } catch(e){}
});
restoreViewMemory();
refreshBadges();
refreshSupervisorToken();
refreshSupervisorLifecycle();
refreshProviderCards();
refreshJudgeCatalog();
loadScreened();
initScreeningCabin();
/* T08: تاریخچه غربالگری — همان کلاس GENERIC؛ کابین‌های بعدی با cabin
   خودشان نمونه می‌سازند. تحویل رکورد-محور: مسلح‌سازی بنر پیوندزنی با
   فایل screened.jsonl آن اجرا (قرارداد loadScreened) + رفتن به نمای
   پیوندزنی، دقیقاً مثل تحویل T07. */
const screeningHistory = new CabinHistoryController({
  cabin: 'screening',
  filterInputId: 'screening-history-search',
  tbodyId: 'screening-history-tbody',
  counterId: 'screening-history-count',
  errorSlotId: 'screening-history-err',
  onHandoff: async (row) => {
    const dir = String((row && row.out_dir) || '').trim();
    const screenedFile = dir ? dir.replace(/\/+$/, '') + '/screened.jsonl' : '';
    await loadScreened(screenedFile || undefined);
    openView('view-linking');
  },
});
screeningHistory.refresh();
document.getElementById('screening-tabbtn-2')
  .addEventListener('click', () => screeningHistory.refresh());
/* T12 OQ-10 cross-cabin conformance (wired here — no new module per the
   module change guard; shell boot owns cross-cabin wiring). precard/pilot
   shells share screening's names/shapes; شروع is busy-wrapped then
   reports the unwired backend honestly in the 3-part box (zero endpoints
   called, zero cabin-logic change). linking keeps its queue-driven
   intake (R2 deviation → follow-up) + gains the next-cabin handoff. */
function parseConformanceWords(text) {
  return String(text || '').split(/[,،\n\r]+/)
    .map((w) => w.trim().toLowerCase()).filter((w) => w.length > 0);
}
function startConformance(prefix) {
  const start = document.getElementById(prefix + '-start');
  if (!start || start.disabled) return;
  withBusy(start, 'در حال شروع…', async () => {
    await new Promise((r) => setTimeout(r, 600));
    showFormError(prefix + '-err', 'اجرای این کابین هنوز به سرور وصل نیست.',
      'followup: backend wiring pending — no endpoint called',
      () => startConformance(prefix), undefined);
  });
}
function initConformanceCabin(prefix, nextView) {
  const words = document.getElementById(prefix + '-words');
  const count = document.getElementById(prefix + '-words-count');
  const paint = () => {
    if (count) count.textContent = faNum(parseConformanceWords(words && words.value).length);
  };
  if (words) words.addEventListener('input', paint);
  paint();
  const start = document.getElementById(prefix + '-start');
  if (start) start.addEventListener('click', () => startConformance(prefix));
  const next = document.getElementById(prefix + '-handoff-next');
  if (next) next.addEventListener('click', () => openView(nextView));
}
initConformanceCabin('precard', 'view-pilot');
initConformanceCabin('pilot', 'view-transfer');
const linkingNext = document.getElementById('linking-handoff-next');
if (linkingNext) linkingNext.addEventListener('click', () => openView('view-precard'));
