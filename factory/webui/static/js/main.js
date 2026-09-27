import {restoreViewMemory} from './shell/view_navigator.js';
import {refreshBadges, refreshProviderCards, refreshSupervisorToken, refreshSupervisorLifecycle} from './providers/provider_registry_controller.js';
import {refreshJudgeCatalog} from './arbitration_presets/preset_catalog_controller.js';
import {loadScreened} from './sense_linking/human_review_controller.js';
import {initScreeningCabin} from './screening/screening_cabin_controller.js';
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
