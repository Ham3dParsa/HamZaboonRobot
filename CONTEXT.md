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
The deterministic verdict inside mechanical linking (twin suppression, signal tallying). Code name pending rename from `arbitrate_link`.
_Avoid_: arbitration, arbiter

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
AI-preset verdicts on the precard line. Never used for linking-line arbitration.
_Avoid_: (do not use this word on the linking line at all)

### Console directions

**A2**:
The locked design language for the real console (production-line rail, contract headers, real tab panels). A visual/UX standard, not a work package.

**R2**:
The work package that rebuilds the real console in the A2 language. Depends on the arbiter execution capability landing first.
