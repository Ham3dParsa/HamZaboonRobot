# Plan: Financial Dashboard Research Baseline and Phase Map

> **STATUS:** active — proposal, phases pending owner lock (see "Phase Lock" section).

## 1. Why this document exists

The HamZaboon financial dashboard (`tools/financial_model/financial_model_dashboard.html`)
is a standalone tool. To make it accurate, useful, and benchmark-backed, five
research agents were dispatched on 2026-08-01 against reliable 2024–2026 public
data (international SaaS/edtech benchmarks, LLM API pricing, Iranian payment
and subscription markets, Telegram/GTM benchmarks, and SaaS modeling
methodology). This file is the durable record: it preserves the research
baseline, the recommended defaults, the proposed implementation phases, and the
progress routing so that later sessions (including after context compaction)
can continue without losing data.

**Ground rule:** research is analysis only — no production code was changed by
the research. All figures below are *recommended inputs/decisions* that still
need explicit owner approval before they become dashboard behavior.

## 2. Current model snapshot (the dashboard today)

The dashboard models a Telegram AI language-learning bot with tiers
Free / Bronze / Silver / Gold / Emerald, priced in Toman, with AI cost derived
from daily-call quotas. Current defaults:

| Parameter | Current default |
|---|---|
| MAU (conversion mode) | 2,000 |
| Free→paid conversion (base / pess / opt) | 5.0 / 2.0 / 9.0 % |
| Prices (Toman/mo) | Bronze 49,000 / Silver 199,000 / Gold 359,000 / Emerald 499,000 |
| Paid churn / free churn | 7.8% / 10% per month |
| Acquisition | 10% of total users per month (no CAC cost) |
| Signup growth (base / pess / opt) | 4 / 1.5 / 7 % |
| AI cost per call | $0.00045 |
| Calls/day per tier | Free 3 / Br 4 / Si 7 / Go 12 / Em 20 |
| Exchange rate | 195,000 Toman/USD |
| Projection | 12 months |
| KPIs | net profit, margin, LTV, break-even users, MRR, AI cost, cost/free user |
| Marketing tab | toggleable techniques with effect % on conversion / churn / signups |

## 3. Research findings and recommended changes

### 3.1 Iran market (source: agent 1)

- **Conversion:** Global freemium norm is 2–5%; Duolingo reached ~8.5–9% only
  after years with a massive brand; India ~1.2%; emerging low-purchasing-power
  markets 0.3–2%. Iran sits between global and low-power markets. **No reliable
  Iranian freemium conversion dataset is public.**
  → Recommended base **3%**, pessimistic **1–2%**, optimistic **6%** (9% is not
  credible without Duolingo-scale brand).
- **Prices (Toman/mo, 2026):** Filimo ~90–198k; Namava 90–160k; FilmNet
  ~150–190k; Faradars edtech ~162–246k/mo equivalent; ChatGPT Plus via Iranian
  resellers ~299k–1M/mo. Bronze (49k) is below the mainstream floor; Silver
  (199k) is mainstream; Gold/Emerald (359–499k) compete with "just buy ChatGPT
  Plus".
- **Payment gateways:** Zibal 1% (min 2,000, cap 20,000 Toman/txn); Zarinpal
  0.5% + 500 (cap 16,000); IDPay ~1% (cap 3,000). VAT on digital services in
  Iran is **10%** (9%→10% in 1403; 12% proposed), though educational services
  may be exempt — legal classification is ambiguous.
- **Renewal friction:** Iranian buyers use prepaid (wallet / gateway once);
  seamless auto-renew via card-on-file is not native to Iranian gateways →
  significant **involuntary churn** (10–20%/mo) must be modeled.
- **FX:** Free-market USD ≈ 192,400 (Aug 2026, +~20% over 6 months); annual
  inflation ~66%, YoY ~87.9%. Digital subscriptions are repriced ~+20–30%/yr at
  Nowruz (Filimo +20%, FilmNet +26.6%). Store FX as an input, default ~192,000,
  re-run quarterly.
- **Telegram Ads (Iran):** text CPM ~45–150k Toman/1k views (banner 490–580k);
  min budget ~900k Toman; CTR 4–9%. Channel post 150k–3.2M Toman/24h.

Sources (agent 1): zibal.ir/blog/transaction-fee-update-1405 · zarinpal.com/pricing ·
mehrnews.com/news/6058268 · faradars.org/subscription · gadgetnews.net/969754 ·
alanchand.com/currencies-price/usd · kebnanews.ir/report/514935 ·
namara-academy.com/telegram-advertising-cost · gapgpt.app · whispertick.com

### 3.2 International edtech benchmarks (source: agent 2)

- **Free→paid:** median 1–5%; "good" 3–5%, "great" 6–8%; 30-day downloads→paid
  only 1.7% avg (RevenueCat); Duolingo ~9% is a decade-long top-1% outlier.
  → Niche Telegram bot (no app-store discovery) should default **2% base
  (0.5% pess / 3% opt)** — below the dashboard's current 5% base.
- **Paid churn:** consumer AI-language apps 6–12%/mo band; Recurly education
  ~5%; Babbel monthly-plan 12-month renewal only 9%. Keep **7.8% base**,
  pessimistic **12%**.
- **Free churn:** ~90% of free installs are gone by day 30 industry-wide;
  education D30 ~8.4%, D90 ~4.1%. Keep **10%/mo** (pessimistic 20%).
- **Pricing (USD/mo equivalents):** Duolingo Super $7.99–13.99, Max $14–29.99;
  Babbel $8.95–15.25; Speak ~$20; ELSA $19.99; TalkPal $14.99; Praktika $8.
  AI tiers command ~2x premium (Max = 2.1x Super). Suggested Persian-tier map:
  Bronze ~$3, Silver ~$6, Gold ~$12, Emerald ~$20.
- **LTV:CAC & payback:** healthy consumer subscription 2:1–3:1 (median ~4:1);
  Duolingo ~4–5:1, CAC payback 4.9 months; Bessemer: Best <6, Better 6–12,
  Good 12–18 months. With near-zero organic CAC the binding constraint is
  **payback < 12 months**, not the ratio.
- **ARPPU:** Duolingo ~$81/yr (~$6.8/mo); Speak ~$6.45/mo IAP ARPU.

Sources (agent 2): revenuecat.com/blog (Future of Subscriptions 2024) ·
asohack.com · lennysnewsletter.com (Poyar/OpenView) · stocktitan.net (DUOL 10-K) ·
onepc.org/en/track/ai-language-tutor · recurly.com/research/churn-rate-benchmarks ·
digitalapplied.com (D30/D90) · languageappguide.com/pricing/duolingo-cost ·
jaimebermejo.substack.com (Duolingo LTV/CAC) · sergeycyw.substack.com ·
aitoolsbee.com/news/...-speak-hits-100-million-annualized-revenue

### 3.3 AI cost model (source: agent 3)

Assumes a vocab-card call ≈ 700 in / 120 out tokens; SRS feedback ≈ 300 in /
60 out; Persian tokenizes ~1.2–1.5x English.

| Model (2026) | $/1M in | $/1M out | est. vocab-card call | vs $0.00045 |
|---|---|---|---|---|
| Gemini 2.5 Flash-Lite | 0.10 | 0.40 | ~$0.00012 | 4–9x cheaper |
| GPT-5 nano / 4.1-nano | 0.05 | 0.40 | ~$0.00008 | 6–11x cheaper |
| DeepSeek V3.x/V4 Flash | 0.14 | 0.28 | ~$0.00013 | 3–8x cheaper |
| GPT-4o-mini | 0.15 | 0.60 | ~$0.00018 | 2.5–5x cheaper |
| GPT-4.1-mini | 0.40 | 1.60 | ~$0.00047 | ≈ assumption |
| Gemini 2.5 Flash | 0.30 | 2.50 | ~$0.00051 | ≈ assumption |
| Claude Haiku 4.5 | 1.00 | 5.00 | ~$0.00130 | ~3x higher |
| GPT-5 / 5.1 | 1.25 | 10.00 | ~$0.00208 | ~4.6x higher |
| Claude Sonnet 4.6 | 3.00 | 15.00 | ~$0.00390 | ~8.7x higher |

- **$0.00045/call is a defensible "mid-tier" default** (≈ GPT-4.1-mini / Gemini
  2.5 Flash) but 3–9x too pessimistic for budget models and 3–9x too optimistic
  for Haiku/Sonnet. The single biggest lever is **model choice**, then
  **prompt caching** (50–90% off cached input; ~30–50% total savings for
  repeated system prompts), then **annual cost decline ~40%/yr** (a16z:
  equal-performance cost falls ~10x/year; frontier fell 300x in 3 years).
- Recommended blended 2026 default: **$0.0003/call** (mid model + ~40% cache);
  $0.00045 is an acceptable upper bound.
- **Edge TTS is free** (no API key/quota) — TTS cost stays $0.
- Iranian OpenAI-compatible gateway exists: platform.doona.ai. Open-weight
  Persian-competent models (Qwen3, DeepSeek V3.1, Llama 3.3) via DeepInfra/
  Groq/Together cost ~$0.05–0.13 per call-equivalent.

Sources (agent 3): developers.openai.com/api/docs/pricing · g2.com · platform.claude.com/docs ·
benchlm.ai · a16z.com/llmflation-llm-inference-cost · epoch.ai · tokonomics.ca (caching) ·
claude.com/blog/prompt-caching · xalen.io · costgoat.com/pricing/openrouter ·
celoyn.com/tools/edge-tts · github.com/travisvn/openai-edge-tts

### 3.4 Marketing / GTM (source: agent 4)

- **Funnel reality (Persian Telegram bot):** 100,000 impressions → 5,000–15,000
  subscribers → ~5% start the bot (250–750) → ~30% survive to day 7 (75–225)
  → ~3–8% pay (2–18 payers). **Paid follower→payer ≈ 0.1–0.5%.**
- **Organic:** 2–7% follower lift/week is good; **10% of total users/month
  acquisition is at the top of what organic Telegram sustains** and effectively
  requires a paid budget. The current no-CAC "10%/mo" is the most optimistic
  assumption in the model.
- **Telegram Ads:** official min CPM ~0.1 TON (~$0.34) but effectively
  inaccessible (€2M deposit); use Iranian channel buys (text CPM ~45–150k
  Toman; posts 150k–3.2M Toman). Channel→subscriber $0.05–1.50.
- **CAC benchmarks:** consumer app blended CAC $24–87; referral CAC $5–25;
  edtech median ~$862 (but that's B2B-ish, not Telegram-bot). A Telegram bot
  should sit far below app benchmarks: **CAC/new free user ~$0.5–2**.
- **Marketing technique effect sizes:**
  - Nudges (streak rescue, social proof, discount): 0.5–1.8% conversion boost —
    **credible**, keep defaults.
  - Real 14-day trial: **+1–3 pts** (3-day is under-optimized vs 14-day norm).
  - Capacity/feature wall (hearts model): **+1–4 pts** — strongest lever.
  - Referral: an *acquisition* lever, should move **signups share 5–20%**
    (default 10%), not conversion. Referred users convert ~4x, LTV +16%.
  - Win-back: **5–15%** of churned (churn-reduction ~8% default).
- **Retention:** consumer apps D1 25% / D7 15% / D30 8%; subscription apps
  D7 25–45% / D30 15–25%. Telegram-bot proxy: D7 10–20%, D30 5–10%.

Sources (agent 4): realfame.in · telegramads.agency · propellerads.com ·
telegramgroups.co · marketing98.com · ads.telegram.org · digitalapplied.com (CAC) ·
yourgrowthpartner.io · businessinsider.com (1B MAU) · jaryan.net · saasdash.ai ·
hub.causo.ai (trial) · owler.com/reports/duolingo · referralcandy.com · extole.com ·
shopify.com/enterprise (winback) · userpilot.com · withdaydream.com · makeaihq.com ·
prooflytics.io · saaspricelab.com

### 3.5 Modeling-methodology audit (source: agent 5)

| Issue | Severity | Why | Fix |
|---|---|---|---|
| "Net profit" = AI contribution margin only | High | Only AI + trial CAC subtracted; fixed costs ignored → margin inflated | Relabel "AI contribution margin"; add full P&L with fixed opex |
| Break-even formula wrong | High | `aiCost/avgPrice` only covers the AI bill, ignores fixed costs | BE users = `fixedOpex / (price − variable cost per user)` |
| LTV cost base too narrow | High | LTV should use full gross margin (hosting, payment fees, support), not just AI cost | Use per-tier gross margin in LTV numerator |
| Same-month signup→upgrade (order circularity) | High | New users added then upgraded at full rate in the same month → near-term revenue inflated | Apply upgrades to month-start free base only; conversion with 1-month lag |
| Flat 7.8%/mo churn is not cohort-correct | Med | Real churn is front-loaded (~10% mo-1 → ~4% mo-3); constant rate overstates churn on mature cohorts | Age-graded churn curve or cohort roll-forward |
| Payment gateway fees missing | High | ~3–5% of revenue (Iranian gateways ~1%, but app-store/MoR 30%/5%) | `netRevenue = revenue × (1 − fee% − VAT%)` |
| VAT missing | High | ~10% Iran digital-services VAT | same as above |
| Fixed opex missing (hosting/staff) | High | Hosting ~5–12% of ARR; R&D ~22%, G&A ~15%, S&M ~23% | Monthly fixed budget rows (hosting, dev, ops, G&A) |
| Currency volatility | Med | Revenue Toman, AI cost USD×FX | FX as scenario input ±20%; consider USD-pegged pricing |
| Missing revenue streams | Med | Annual plans (15–20% prepay discount), ads, coin packs, referrals | Add prepaid-annual row + optional ads/coins |
| P&L only, no cash view | High | Accrual profit ≠ cash; trialCAC timing and annual prepays shift cash | Add cumulative cash, runway, CAC payback, MRR/ARR, D30 retention |
| Scenario methodology | Med | 3 scenarios is the accepted minimum but needs internal consistency + one-at-a-time sensitivity (tornado) | Keep 3 consistent cases + tornado on conversion/churn/price/CAC/FX/AI cost |

Sources (agent 5): saasmetricscalculator.com · nonoisemetrics.com · baremetrics.com ·
usermotion.com · mrrcanvas.com · fiscallion.io · investopedia.com · booksandbalancesinc.com ·
stripe.com/pricing · swipesum.com · jeeiee.com · saas-capital.com · ey.com ·
blossomstreetventures.com · charlia.io · glencoyne.com · trezy.io · ibinterviewquestions.com

## 4. Recommended default updates (summary)

| Parameter | Current | Recommended | Rationale |
|---|---|---|---|
| Conversion base / pess / opt | 5 / 2 / 9 % | **3 / 1.5 / 6 %** | Global median + Iran power sensitivity; 9% not credible |
| AI cost per call | $0.00045 | **$0.0003** (model-choice-aware, cache ~40%) | mid model + caching; $0.00045 upper bound |
| FX | 195,000 | **192,000** (input; quarterly refresh) | free-market Aug 2026 |
| Price renewal factor | none | **+20–30%/yr at Nowruz** | Iranian VOD precedent |
| Involuntary churn | none | **+10–20%/mo** (prepaid friction) | Iranian gateways lack auto-renew |
| Payment gateway fee | none | **~1–1.5%** (Iran) / 3–5% (intl) | Zibal/Zarinpal published fees |
| VAT | none | **10%** (sensitivity 0% if educational-exempt) | Iran digital-services VAT |
| Fixed opex | none | monthly rows: hosting, dev, ops, G&A | SaaS cost benchmarks |
| CAC per new free user | none (free growth) | **$0.5–2** + optional monthly ad budget | channel-buy economics |
| Referral | conversion boost | **signups share 5–20% (default 10%)** | referral is an acquisition lever |
| Trial / capacity-wall effects | 0.5–1.8% | nudges keep 0.5–1.8%; trial +1–3 pts; wall +1–4 pts | strength-tiered by lever type |
| Annual AI cost decline | none | **~40%/yr** | a16z/epoch price trends |

## 5. Phase map and progress routing

Phases are independent, ordered, and each has acceptance criteria. Status values
reuse the repo vocabulary: `planned` / `in-progress` / `blocked` / `complete` /
`deferred`. This table is the progress-routing index; the owner locks phases
individually in Section 6.

| Phase | Scope | Key changes | Acceptance criteria | Status |
|---|---|---|---|---|
| P1 | Fix modeling order-of-operations | Same-month signup→upgrade lag; churn-on-starting-base-then-upgrade | Unit-test scenario: month-1 revenue does not include same-month new-signup upgrades; parity check on a small manual table | complete (bc053f6) |
| P2 | Add full P&L cost lines | Payment fee %, VAT, fixed opex rows; relabel current net → "AI contribution margin"; correct break-even = fixedOpex / contribution-margin-per-user; LTV on full gross margin | Dashboard shows both contribution margin and true net P&L; break-even changes when fixed costs change; LTV < old LTV given same inputs | complete (bc053f6) |
| P3 | Marketing inputs & CAC | CAC input, monthly ad budget, Telegram CPM + funnel conversion, referral-as-signups, win-back effect; strength-tier technique effects | Toggling CAC/budget changes signup count and payback; referral moves signups not conversion; effects show in KPI summary | complete (bc053f6) |
| P4 | AI cost realism | Model-choice dropdown (cheap/mid/strong), tokens/call, cache-saving %, annual cost-decline %; default $0.0003 | Cost-per-call table matches Section 3.3 within ±20%; declining-cost scenario lowers AI cost over time | complete (bc053f6) |
| P5 | Defaults reality-check | Apply Section 4 defaults (conversion 3/1.5/6, FX 192k, renewal factor, involuntary churn, gateway fee, VAT) | With defaults, model shows realistic loss/lean-profit trajectory for a 2,000-MAU start; KPI tips visible | complete (bc053f6) |
| P6 | Cash view & KPIs | Cumulative cash, runway, CAC payback, MRR/ARR, D30 retention, tornado sensitivity | All new KPIs present and update with inputs; tornado ranks conversion & churn as top drivers | complete (bc053f6) |

**Progress routing rule:** after each phase ships, update this table's Status,
update the relevant GitHub
Issues, and mark the phase's acceptance criteria as evidence. Do not mark a
phase `complete` on intent alone.

## 6. Phase lock (owner decisions)

> Each phase is locked independently. Owner confirmed **all phases** on 2026-08-01
> via the `question` tool: "Lock all phases (Recommended)".

| Phase | Decision | Locked option | Date | Owner confirmation |
|---|---|---|---|---|
| P1 | Fix order-of-operations (1-month upgrade lag; churn on starting base) | Recommended (P1 as scoped) | 2026-08-01 | "Lock all phases (Recommended)" |
| P2 | Full P&L (payment fee %, VAT, fixed opex); relabel net → AI contribution margin; correct break-even & LTV | Recommended (P2 as scoped) | 2026-08-01 | "Lock all phases (Recommended)" |
| P3 | Marketing inputs & CAC (CAC input, ad budget, CPM funnel, referral-as-signups, win-back) | Recommended (P3 as scoped) | 2026-08-01 | "Lock all phases (Recommended)" |
| P4 | AI cost realism (model dropdown, tokens/call, cache %, annual decline; default $0.0003) | Recommended (P4 as scoped) | 2026-08-01 | "Lock all phases (Recommended)" |
| P5 | Apply Section 4 defaults (conversion 3/1.5/6, FX 192k, renewal factor, involuntary churn, gateway fee, VAT) | Recommended (P5 as scoped) | 2026-08-01 | "Lock all phases (Recommended)" |
| P6 | Cash view & KPIs (cumulative cash, runway, CAC payback, MRR/ARR, D30 retention, tornado sensitivity) | Recommended (P6 as scoped) | 2026-08-01 | "Lock all phases (Recommended)" |
