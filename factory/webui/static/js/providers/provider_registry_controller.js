import {getJSON, withBusy, errCodeFor, buildFormError, showFormError, clearFormError, copyReport, faNum, ltrCode} from '../shell/api_client.js';
/* نوار وضعیت سراسری: master، egress، ریشه‌ها */
export async function refreshBadges() {
  try {
    const m = await getJSON('/api/master/status');
    document.getElementById('master-state').textContent =
      m.configured ? ('فعال (' + (m.var || '') + ')') : 'غیرفعال';
    document.getElementById('master-note').textContent = m.configured
      ? 'ذخیره امن کلید فعال است؛ فقط نام متغیر (' + (m.var || '') + ') نمایش داده می‌شود.'
      : 'ذخیره امن کلید فعال نیست — با تأیید شما یک‌بار ساخته و در فایل محیط کارخانه ذخیره می‌شود؛ مقدار هرگز نمایش داده نمی‌شود.';
    const btn = document.getElementById('btn-master-ensure');
    if (btn) btn.hidden = !!m.configured;
    masterConfigured = !!m.configured;
    syncSecretsBlock();
  } catch(e) {
    masterConfigured = false;
    syncSecretsBlock();
    document.getElementById('master-state').textContent = 'نامشخص';
    document.getElementById('master-note').textContent = 'خواندن وضعیت ناموفق بود.';
  }
  try {
    const r = await getJSON('/api/providers');
    const rows = r.providers || [];
    const ready = rows.filter(p => p.has_key).length;
    const keysEl = document.getElementById('badge-keys');
    keysEl.replaceChildren();
    keysEl.append(document.createTextNode(faNum(ready) + ' از ' + faNum(rows.length) + ' آماده'));
    const vars = rows.map(p => p.key_var).filter(Boolean).join(', ');
    keysEl.title = vars || 'بدون نام متغیر';
  } catch(e) {
    document.getElementById('badge-keys').textContent = 'نامشخص';
  }
  try {
    const r = await fetch('/api/egress/health');
    let j = null;
    try { j = await r.json(); } catch(e){}
    if (!r.ok) throw new Error((j && j.error) || ('خطای ' + r.status));
    document.getElementById('badge-egress').textContent =
      j.healthy ? ('خروج تمیز: فعال (' + faNum(j.servers) + ' سرور)') : 'خروج: ناسالم';
    document.getElementById('badge-egress').title = '';
  } catch(e) {
    /* سرور پایین: متن خطا (شامل دستور دقیق راه‌اندازی، بدون راز) در عنوان نشان */
    const badge = document.getElementById('badge-egress');
    badge.textContent = 'خروج: ناسالم';
    badge.title = e.message || e;
  }
  try {
    const f = await getJSON('/api/files/roots');
    const roots = f.roots || [];
    const files = (f && f.files) || {};
    const rootEl = document.getElementById('badge-root');
    rootEl.replaceChildren();
    if (roots.length) rootEl.append(document.createTextNode(roots[0].path + (roots.length > 1 ? ' (+' + faNum(roots.length - 1) + ')' : '')));
    else rootEl.append(document.createTextNode('—'));
    if (!roots.length) rootEl.title = 'سرور محلی مسیری گزارش نکرد';
    else rootEl.title = '';
    /* T10: files facts ride the same event so the paths table
       renders exists/size/lines/mtime from the live response. */
    document.dispatchEvent(new CustomEvent('hz:paths-refreshed', {detail: {roots, files}}));
  } catch(e) {
    document.getElementById('badge-root').textContent = 'نامشخص';
  }
}

/* ارائه‌دهندگان: کارت‌ها فقط از رجیستری موتور + rate_state */
let rateRows = [];
export async function refreshProviderCards() {
  const box = document.getElementById('provider-cards');
  try {
    const [p, rs, info] = await Promise.all([
      getJSON('/api/providers'), getJSON('/api/rate_state'), getJSON('/api/engine_info')
    ]);
    rateRows = rs.providers || [];
    const rows = p.providers || [];
    document.getElementById('providers-count').textContent =
      faNum(rows.length) + ' ارائه‌دهنده ثبت‌شده (رجیستری موتور)';
    box.replaceChildren();
    for (const row of rows) {
      const rate = rateRows.find(x => x.name === row.name) || {};
      const card = document.createElement('div');
      card.className = 'provider-cfg-card';
      card.dataset.provider = row.name;
      const head = document.createElement('div');
      head.className = 'p-header';
      const title = document.createElement('span');
      title.className = 'p-title code-token';
      title.setAttribute('dir', 'ltr');
      title.textContent = row.name;
      const pill = document.createElement('span');
      pill.className = 'badge ' + (row.has_key ? 'live-disk' : 'rate-cap');
      pill.textContent = row.has_key ? 'کلید آماده است' : 'بدون کلید';
      head.append(title, pill);
      card.append(head);
      const kv = document.createElement('div');
      kv.className = 'p-meta';
      kv.append(document.createTextNode('متغیر کلید: '));
      kv.append(ltrCode(row.key_var || '—'));
      card.append(kv);
      /* ردیف نشان‌های فشرده: مسیر + شمار کلید فعال + آهنگ — بدون نثر بلند */
      const badges = document.createElement('div');
      badges.className = 'provider-badges';
      const routeBadge = document.createElement('span');
      routeBadge.className = 'badge';
      routeBadge.textContent = row.route === 'leased' ? 'تونل استیجاری' : 'مستقیم';
      badges.append(routeBadge);
      const keysBadge = document.createElement('span');
      keysBadge.className = 'badge';
      const activeKeys = (row.active_keys === null || row.active_keys === undefined)
        ? (row.key_count || 0) : row.active_keys;
      keysBadge.textContent = faNum(activeKeys) + ' کلید فعال';
      badges.append(keysBadge);
      const pace = rate.pacing || {};
      const paceBadge = document.createElement('span');
      paceBadge.className = 'badge';
      paceBadge.textContent = 'مکث ' + faNum(
        (pace.sleep_secs_default === null || pace.sleep_secs_default === undefined)
          ? '—' : pace.sleep_secs_default) + ' ثانیه';
      badges.append(paceBadge);
      card.append(badges);
      /* جزئیات اشکال‌زدایی هر کارت: نثر بلند انگلیسی بیرون از بدنه + کپی */
      const debug = document.createElement('details');
      debug.className = 'provider-debug';
      const debugSum = document.createElement('summary');
      debugSum.textContent = 'جزئیات مسیر و نرخ';
      debug.append(debugSum);
      const debugBody = document.createElement('div');
      debugBody.className = 'provider-debug-body';
      const routeLine = document.createElement('div');
      routeLine.className = 'p-meta';
      routeLine.textContent = 'مسیر: ' + (row.route === 'leased' ? 'تونل استیجاری' : 'مستقیم');
      debugBody.append(routeLine);
      if (row.route_reason) {
        const rr = document.createElement('div');
        rr.className = 'p-meta';
        rr.append(document.createTextNode('دلیل مسیر: '));
        rr.append(ltrCode(row.route_reason));
        debugBody.append(rr);
      }
      if (row.clean_exit) {
        const ce = document.createElement('div');
        ce.className = 'p-meta';
        ce.append(document.createTextNode('خروجی تمیز: '));
        ce.append(ltrCode(row.clean_exit));
        debugBody.append(ce);
      }
      const rl = document.createElement('div');
      rl.className = 'p-meta';
      rl.textContent = rateLineFor(row.name);
      debugBody.append(rl);
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'btn-skip-next provider-debug-copy';
      copyBtn.textContent = 'کپی جزئیات';
      copyBtn.addEventListener('click', async () => {
        const lines = [
          'provider: ' + row.name,
          'route: ' + (row.route || ''),
          'route_reason: ' + (row.route_reason || ''),
          'clean_exit: ' + (row.clean_exit || ''),
          'rate: ' + rateLineFor(row.name),
        ];
        await copyReport(lines.join('\n'), copyBtn, 'جزئیات کپی شد');
      });
      debugBody.append(copyBtn);
      debug.append(debugBody);
      card.append(debug);
      const keyRow = document.createElement('div');
      keyRow.style.cssText = 'display: flex; gap: 8px; flex-wrap: wrap;';
      const keyInp = document.createElement('input');
      keyInp.className = 'inline-input code-token';
      keyInp.id = 'pk-' + row.name;
      keyInp.dir = 'ltr';
      /* PUX-23: راز پیش‌فرض پنهان (password) + دکمه نمایش. */
      keyInp.type = 'password';
      keyInp.setAttribute('aria-label', 'مقدار کلید (' + row.name + ')');
      keyInp.placeholder = 'مقدار کلید (رمزشده ذخیره می‌شود)';
      keyInp.autocomplete = 'off';
      const showBtn = document.createElement('button');
      showBtn.type = 'button';
      showBtn.className = 'btn-skip-next';
      showBtn.textContent = 'نمایش';
      showBtn.setAttribute('aria-label',
        'نمایش مقدار کلید ' + row.name);
      showBtn.addEventListener('click', () => {
        const show = keyInp.type === 'password';
        keyInp.type = show ? 'text' : 'password';
        showBtn.textContent = show ? 'پنهان‌کردن' : 'نمایش';
      });
      const saveBtn = document.createElement('button');
      saveBtn.className = 'btn-select-candidate';
      saveBtn.textContent = 'ذخیره کلید';
      saveBtn.addEventListener('click', (ev) => providerKeySave(row.name, ev.currentTarget));
      const delBtn = document.createElement('button');
      delBtn.className = 'btn-skip-next';
      delBtn.textContent = 'حذف کلید';
      delBtn.addEventListener('click', (ev) => providerKeyDelete(row.name, ev.currentTarget));
      const addKeyBtn = document.createElement('button');
      addKeyBtn.className = 'btn-select-candidate';
      addKeyBtn.type = 'button';
      addKeyBtn.textContent = 'افزودن کلید';
      addKeyBtn.setAttribute('aria-label', 'افزودن شکاف کلید برای ' + row.name);
      addKeyBtn.addEventListener('click', (ev) => providerKeyAdd(row.name, ev.currentTarget));
      /* تنها میان‌بر کارت: پرش به کاوشگر مدل پریست (بدون دکمه/جعبه
         فهرست خام در کارت) — ارائه‌دهنده را در فرم پریست می‌نشاند،
         سقف‌ها را پیش‌فرض می‌گذارد، مدل‌ها را می‌گیرد و به جست‌وجو می‌لغزد */
      const jumpBtn = document.createElement('button');
      jumpBtn.className = 'btn-skip-next';
      jumpBtn.type = 'button';
      jumpBtn.textContent = 'مدل‌ها ←';
      jumpBtn.setAttribute('aria-label', 'پرش به کاوشگر مدل برای ' + row.name);
      jumpBtn.addEventListener('click', () => jumpProviderToExplorer(row.name));
      const delProvBtn = document.createElement('button');
      delProvBtn.className = 'btn-skip-next';
      delProvBtn.type = 'button';
      delProvBtn.textContent = 'حذف ارائه‌دهنده';
      delProvBtn.setAttribute('aria-label', 'حذف ارائه‌دهنده ' + row.name);
      delProvBtn.addEventListener('click', (ev) => providerDelete(row.name, ev.currentTarget));
      keyRow.append(keyInp, showBtn, saveBtn, delBtn, addKeyBtn, jumpBtn, delProvBtn);
      card.append(keyRow);
      box.append(card);
    }
    document.dispatchEvent(new CustomEvent('hz:providers-refreshed', {
      detail: {rows, rateRows, info},
    }));
  } catch(e) {
    box.replaceChildren();
    box.append(buildFormError('خواندن ارائه‌دهندگان ناموفق بود.', (e && e.message) || e, refreshProviderCards, undefined, errCodeFor(e)));
  }
}
function rateLineFor(name) {
  const row = rateRows.find(x => x.name === name);
  if (!row) return 'وضعیت نرخ: نامشخص';
  const g = row.groups || {};
  const pace = row.pacing || {};
  return 'گروه‌ها: G1=' + (g.G1 ? '۱' : '۰') + '‏ G2=' + (g.G2 ? '۱' : '۰')
    + ' (' + faNum(row.groups_count || 0) + ' از ۲)'
    + '؛ مسیر: ' + (row.route === 'direct' ? 'مستقیم' : 'تونل')
    + '؛ آهنگ موتور: مکث ' + faNum(pace.sleep_secs_default) + ' ثانیه، مکث چرخش ' + faNum(pace.rotate_pause_secs) + ' ثانیه'
    + (pace.rpm_limiter ? '' : '، بدون سقف دوربردکیقه‌ای') + '.';
}
async function providerKeySave(name, btn) {
  clearFormError('provider-err');
  const inp = document.getElementById('pk-' + name);
  const value = inp ? inp.value : '';
  if (!value) { showFormError('provider-err', 'کلید خالی است (چیزی ذخیره نشد).', '', null); return; }
  await withBusy(btn, 'در حال ذخیره…', async () => {
    try {
      await getJSON('/api/providers/' + encodeURIComponent(name) + '/key',
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key_value: value})});
      if (inp) inp.value = '';
      await refreshProviderCards();
      await refreshBadges();
    } catch(e) { showFormError('provider-err', 'ذخیره کلید ناموفق بود.', (e && e.message) || e, () => providerKeySave(name), errCodeFor(e)); }
  });
}
async function providerKeyDelete(name, btn) {
  clearFormError('provider-err');
  if (!confirm('کلید رمزشده حذف می‌شود و برگشت‌ناپذیر است؛ ادامه می‌دهید؟ (' + name + ')')) return;
  await withBusy(btn, 'در حال حذف…', async () => {
    try {
      await getJSON('/api/providers/' + encodeURIComponent(name) + '/key', {method: 'DELETE'});
      await refreshProviderCards();
      await refreshBadges();
    } catch(e) { showFormError('provider-err', 'حذف کلید ناموفق بود.', (e && e.message) || e, () => providerKeyDelete(name), errCodeFor(e)); }
  });
}
/* مدیریت ارائه‌دهنده: افزودن سطر، افزودن شکاف کلید، حذف سطر —
   هر سه به مسیرهای مدیریتی موجود سرور می‌روند، با حالت مشغولی؛
   حذف پشت گفت‌وگوی تأیید با واژه‌های «رمزشده» و «برگشت‌ناپذیر» است. */
async function providerAdd(btn) {
  const noteEl = document.getElementById('provider-add-note');
  clearFormError('provider-add-err');
  if (noteEl) noteEl.textContent = '';
  const name = ((document.getElementById('provider-add-name') || {}).value || '').trim();
  const keyVar = ((document.getElementById('provider-add-keyvar') || {}).value || '').trim();
  const protocol = ((document.getElementById('provider-add-protocol') || {}).value || 'openai_compat').trim() || 'openai_compat';
  const baseUrl = ((document.getElementById('provider-add-base-url') || {}).value || '').trim();
  const route = (document.getElementById('provider-add-route') || {}).value || 'direct';
  if (!name) { showFormError('provider-add-err', 'نام ارائه‌دهنده خالی است (چیزی ساخته نشد).', '', null); return; }
  await withBusy(btn || document.getElementById('btn-add-provider'), 'در حال افزودن…', async () => {
    try {
      const j = await getJSON('/api/managed_providers',
        {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify({name: name, protocol: protocol, base_url: baseUrl,
                               route: route, key_vars: keyVar ? [keyVar] : []})});
      if (noteEl) {
        noteEl.replaceChildren();
        noteEl.append(document.createTextNode('ارائه‌دهنده ' + (j.provider || name)
          + ' ساخته شد (' + faNum(((j.row || {}).key_count) || 0) + ' شکاف کلید).'));
        if (baseUrl) {
          noteEl.append(document.createTextNode(' نقطه پایانی: '));
          noteEl.append(ltrCode(baseUrl));
        }
        if (!keyVar) noteEl.append(document.createTextNode(' بدون کلید: «دریافت فهرست» سمت سرور رد می‌شود؛ مسیر اجرا به فهرست نیازی ندارد.'));
      }
      await refreshProviderCards();
      await refreshBadges();
    } catch(e) { showFormError('provider-add-err', 'افزودن ارائه‌دهنده ناموفق بود.', (e && e.message) || e, () => providerAdd(), errCodeFor(e)); }
  });
}
async function providerKeyAdd(name, btn) {
  clearFormError('provider-err');
  await withBusy(btn, 'در حال افزودن…', async () => {
    try {
      await getJSON('/api/managed_providers/' + encodeURIComponent(name) + '/keys',
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({})});
      await refreshProviderCards();
      await refreshBadges();
    } catch(e) { showFormError('provider-err', 'افزودن شکاف کلید ناموفق بود.', (e && e.message) || e, () => providerKeyAdd(name), errCodeFor(e)); }
  });
}
async function providerDelete(name, btn) {
  clearFormError('provider-err');
  if (!confirm('ارائه‌دهنده ' + name + ' با شکاف‌های کلید رمزشده‌اش حذف می‌شود و برگشت‌ناپذیر است؛ ادامه می‌دهید؟')) return;
  await withBusy(btn, 'در حال حذف…', async () => {
    try {
      await getJSON('/api/managed_providers/' + encodeURIComponent(name), {method: 'DELETE'});
      await refreshProviderCards();
      await refreshBadges();
    } catch(e) { showFormError('provider-err', 'حذف ارائه‌دهنده ناموفق بود.', (e && e.message) || e, () => providerDelete(name), errCodeFor(e)); }
  });
}
async function masterEnsure(btn) {
  clearFormError('provider-err');
  await withBusy(btn, 'در حال فعال‌سازی…', async () => {
    try {
      await getJSON('/api/master/ensure',
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({confirm: true})});
      await refreshProviderCards();
      await refreshBadges();
    } catch(e) { showFormError('provider-err', 'فعال‌سازی ذخیره امن ناموفق بود.', (e && e.message) || e, () => masterEnsure(), errCodeFor(e)); }
  });
}

/* توکن سرپرست: یک‌بار چسباندن در پنل ارائه‌دهندگان — ورودی بلافاصله
   پس از ارسال پاک می‌شود (نمایش یک‌باره) و مقدار هرگز بازخوانده
   نمی‌شود؛ وضعیت فقط نام + بولی است. */
let masterConfigured = false;
let supervisorConfigured = false;
function syncSecretsBlock() {
  const block = document.getElementById('operator-secrets');
  if (!block) return;
  block.open = !(masterConfigured && supervisorConfigured);
}
export async function refreshSupervisorToken() {
  try {
    const s = await getJSON('/api/supervisor/status');
    supervisorConfigured = !!s.configured;
    syncSecretsBlock();
    document.getElementById('supervisor-state').textContent =
      s.configured ? ('پیکربندی شده (' + (s.var || '') + ')') : 'پیکربندی نشده';
    document.getElementById('supervisor-note').textContent = s.configured
      ? 'توکن سرپرست ذخیره شده است؛ فقط نام متغیر (' + (s.var || '') + ') نمایش داده می‌شود.'
      : 'توکن سرپرست را یک‌بار بچسبانید؛ رمزشده ذخیره می‌شود و مقدار هرگز نمایش داده نمی‌شود.';
  } catch(e) {
    supervisorConfigured = false;
    syncSecretsBlock();
    document.getElementById('supervisor-state').textContent = 'نامشخص';
    document.getElementById('supervisor-note').textContent = 'خواندن وضعیت ناموفق بود.';
  }
}
async function supervisorTokenSave(btn) {
  clearFormError('supervisor-err');
  const inp = document.getElementById('supervisor-token-input');
  const value = inp ? inp.value : '';
  if (inp) inp.value = '';
  if (!value) { showFormError('supervisor-err', 'توکن خالی است (چیزی ذخیره نشد).', '', null); return; }
  await withBusy(btn, 'در حال ذخیره…', async () => {
    try {
      await getJSON('/api/supervisor/token',
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key_value: value})});
      await refreshSupervisorToken();
      await refreshBadges();
    } catch(e) { showFormError('supervisor-err', 'ذخیره توکن ناموفق بود.', (e && e.message) || e, () => supervisorTokenSave(), errCodeFor(e)); }
  });
}
async function supervisorTokenDelete(btn) {
  clearFormError('supervisor-err');
  if (!confirm('توکن رمزشده حذف می‌شود و برگشت‌ناپذیر است؛ ادامه می‌دهید؟ (EGRESS_SUP_TOKEN)')) return;
  const inp = document.getElementById('supervisor-token-input');
  if (inp) inp.value = '';
  await withBusy(btn, 'در حال حذف…', async () => {
    try {
      await getJSON('/api/supervisor/token', {method: 'DELETE'});
      await refreshSupervisorToken();
      await refreshBadges();
    } catch(e) { showFormError('supervisor-err', 'حذف توکن ناموفق بود.', (e && e.message) || e, () => supervisorTokenDelete(), errCodeFor(e)); }
  });
}

/* سطح وضعیت سرپرست: گزارش زنده بیدار/خواب + شمار سرور و لیز، متصل به
   /api/egress/health (پروب واقعی، هرگز برچسب کهنه)؛ نام حامل همیشه
   EGRESS_SUP_TOKEN است و مقدار هرگز نمایش داده نمی‌شود. */
export async function refreshSupervisorLifecycle() {
  const badge = document.getElementById('supervisor-lifecycle-state');
  const note = document.getElementById('supervisor-lifecycle-note');
  if (!badge) return;
  try {
    const r = await fetch('/api/egress/health');
    let j = null;
    try { j = await r.json(); } catch(e){}
    if (!r.ok) throw new Error((j && j.error) || ('خطای ' + r.status));
    const servers = (j.servers === null || j.servers === undefined) ? '—' : faNum(j.servers);
    const leases = (j.leases === null || j.leases === undefined) ? '—' : faNum(j.leases);
    const counts = ' (' + servers + ' سرور، ' + leases + ' لیز)';
    badge.textContent = (j.healthy ? 'سرپرست: بیدار' : 'سرپرست: خواب') + counts;
    if (note) note.textContent = j.healthy
      ? 'سرپرست سالم است' + counts + ' (EGRESS_SUP_TOKEN)؛ بیدارسازی دوباره انجام نمی‌شود.'
      : 'سرپرست پایین است' + counts + ' (EGRESS_SUP_TOKEN)؛ دکمه بیدار، تازه‌سازی اشتراک و بیدارسازی در پس‌زمینه می‌کند.';
  } catch(e) {
    badge.textContent = 'سرپرست: نامشخص';
    if (note) note.textContent = 'خواندن وضعیت ناموفق بود (EGRESS_SUP_TOKEN).';
  }
}
async function supervisorWake() {
  clearFormError('supervisor-err');
  const btn = document.getElementById('btn-supervisor-wake');
  const idleText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'در حال بیدارسازی…'; }
  try {
    const j = await getJSON('/api/supervisor/wake', {method: 'POST'});
    await refreshSupervisorLifecycle();
    await refreshBadges();
    const h = (j && j.health) || {};
    const note = document.getElementById('supervisor-lifecycle-note');
    if (note && (h.servers !== undefined || j.refreshed)) {
      note.textContent += ' (پاسخ بیدار: ' + faNum(h.servers || 0) + ' سرور، ' + faNum(h.leases || 0) + ' لیز — ' + (j.var || 'EGRESS_SUP_TOKEN') + ')';
    }
  } catch(e) { showFormError('supervisor-err', 'بیدارسازی ناموفق بود.', (e && e.message) || e, supervisorWake, errCodeFor(e)); }
  finally { if (btn) { btn.disabled = false; btn.textContent = idleText; } }
}
async function supervisorSleep(btn) {
  clearFormError('supervisor-err');
  await withBusy(btn || document.getElementById('btn-supervisor-sleep'), 'در حال خواب…', async () => {
    try {
      const j = await getJSON('/api/supervisor/sleep', {method: 'POST'});
      await refreshSupervisorLifecycle();
      await refreshBadges();
      if (j && j.reason) showFormError('supervisor-err', 'سرپرست خوابانده نشد.', j.reason, () => supervisorSleep());
    } catch(e) { showFormError('supervisor-err', 'خواباندن سرپرست ناموفق بود.', (e && e.message) || e, () => supervisorSleep(), errCodeFor(e)); }
  });
}
document.getElementById('btn-master-ensure').addEventListener('click', (ev) => masterEnsure(ev.currentTarget));
document.getElementById('btn-supervisor-save').addEventListener('click', (ev) => supervisorTokenSave(ev.currentTarget));
document.getElementById('btn-supervisor-delete').addEventListener('click', (ev) => supervisorTokenDelete(ev.currentTarget));
document.getElementById('btn-supervisor-wake').addEventListener('click', supervisorWake);
document.getElementById('btn-supervisor-sleep').addEventListener('click', (ev) => supervisorSleep(ev.currentTarget));
document.getElementById('btn-add-provider').addEventListener('click', (ev) => providerAdd(ev.currentTarget));
