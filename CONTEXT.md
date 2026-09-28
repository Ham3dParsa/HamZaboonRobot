# HamZaban Linking Line

Factory pipeline that turns screened Kaikki senses into linked WordNet synsets through mechanical resolution, LLM arbitration, gates, and operator-supervised review.

## Language

### Linking stages

**Screening**:
Passing Kaikki senses through a garbage filter before anything links them.
_Avoid_: cleaning, filtering (generic)

**Mechanical linking**:
Shortlisting link candidates plus applying deterministic rules; strong at rejecting bad links, weak at confirming good ones.
_Avoid_: arbitration, judging, mechanical arbitration

**Rule resolution**:
DELETED (2026-09-28) — vague invented jargon, replaced below.

**Mechanical review**:
The deterministic verdict step inside mechanical linking: rules review
senses, some are approved on the spot, the rest move on. Code name:
`mechanical_review` (renamed from `arbitrate_link`).
_Avoid_: arbitration, arbiter, resolution

**Arbiter**:
The LLM-based judge that reads a prompt template and returns a verdict. The only judge on the linking line.
_Avoid_: judge, AI judge, mechanical arbiter, arbitration (as a noun for rules)

**Gates**:
Post-arbiter decision points routing rows to auto-linked or to supervised review.
_Avoid_: filters, validators

**Supervised review**:
Operator-supervised final stage for rows the gates did not auto-link (batches, answer sheets, checklists).
_Avoid_: human review (legacy label), manual review

**Judge**:
Legacy word for AI presets. Avoided everywhere in the factory —
it falsely implies the preset knows the task.
_Avoid_: judge preset, پریست داوری

**AI preset**:
Shared model configuration for every factory cabin (provider + model +
rate limits). Says WHO runs and HOW MUCH — never what to do.
_Avoid_: judge preset, داوری (as a preset name)

**Step prompt**:
The task text owned by each cabin step (linking arbiter prompt,
precard prompts, future pilot prompts). Says WHAT to ask — never
stored inside an AI preset.
_Avoid_: preset prompt, shared prompt

**Bot presets**:
The Telegram bot's own AI presets (`services/ai`). Unrelated to
factory AI presets — different consumers, different lifecycle.
Never merged, never mirrored.
_Avoid_: (do not mix the two stores)

### Console directions

**A2**:
The locked design language for the real console (production-line rail, contract headers, real tab panels). A visual/UX standard, not a work package.

**R2**:
The work package that rebuilds the real console in the A2 language. Depends on the arbiter execution capability landing first.
