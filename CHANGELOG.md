# Changelog

All notable changes to HamZaboon. Generated automatically from
[Conventional Commits](https://www.conventionalcommits.org/) by
[scripts/generate_changelog.py](scripts/generate_changelog.py). Do not edit by hand.

### 2026-08-19
#### Features
- show session summary report after study session (#410) (`study`)
  — @Ham3dParsa [9c99914](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9c99914)
- add delete-card flow + first-exposure pronounce fix (#406) (`srs`)
  — @Ham3dParsa [7f16597](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7f16597)

#### Bug Fixes
- route session summary through send_pretty to avoid double-escape (#411) (`study`)
  — @Ham3dParsa [2954bde](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2954bde)
- address Kilo review on delete-card PR #406 (#409) (`srs`)
  — @Ham3dParsa [7a65da4](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7a65da4)
- redirect test subprocesses to throwaway DB and fail CI on production-DB touch (#391) (#402) (`tests`)
  — @Ham3dParsa [736806e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/736806e)
- make grading session-aware and idempotent after restart (issue #401) (#403) (`study`)
  — @Ham3dParsa [3ece608](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3ece608)

#### Refactoring
- always-on audio pronunciation, remove tts_access and IPA toggles (#390) (#405) (`tts`)
  — @Ham3dParsa [d60c628](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d60c628)

#### Documentation
- mark srs-delete-card plan merged via PR #406 (#407) (`plans`)
  — @Ham3dParsa [2142e36](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2142e36)

#### Chores
- add date-grouped timeline with authors and commit links (`changelog`)
  — @Ham3dParsa [8e9fcdc](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8e9fcdc)
- persist send_pretty research sandbox under tools/ (research copy) (#404) (`tools`)
  — @Ham3dParsa [e4ce6e3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e4ce6e3)

#### Other
- bronze wasn't a premium plan, fixed it.
  — @Ham3dParsa [6305c18](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6305c18)

### 2026-08-18
#### Refactoring
- migrate admin AI screens to send_pretty spans (T8-PRE, T8a) (#388) (`admin_ai`)
  — @Ham3dParsa [d76ca7b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d76ca7b)
- consolidate plan identity into a canonical leaf (J-B6) (#387) (`config`)
  — @Ham3dParsa [889ed32](https://github.com/Ham3dParsa/HamZaboonRobot/commit/889ed32)

#### Documentation
- re-validate CARD-MODES + #338 Phase 3 tickets against d76ca7b (#399) (`plans`)
  — @Ham3dParsa [9e8f9df](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9e8f9df)
- mark governance-reform plan complete (PR #400) (`plans`)
  — @Ham3dParsa [dd7c409](https://github.com/Ham3dParsa/HamZaboonRobot/commit/dd7c409)

#### Chores
- reform tooling and slim operating rules (R1-R7) (#400) (`governance`)
  — @Ham3dParsa [5eb9ea7](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5eb9ea7)

### 2026-08-17
#### Bug Fixes
- settings_key copy safety + pattern suffix validation (J0.2 follow-up) (`settings`)
  — @Ham3dParsa [e4cf351](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e4cf351)

#### Refactoring
- deep outbound-message module with recursive span tree (R3, T1-T5) (#385) (`send_pretty`)
  — @Ham3dParsa [f6cd2b3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f6cd2b3)
- consolidate TTS voice map into the language catalog (J-B3) (#384) (`tts`)
  — @Ham3dParsa [c6bd1de](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c6bd1de)
- canonical AI preset-field schema module (J-B2) (#383) (`ai`)
  — @Ham3dParsa [7be8f3f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7be8f3f)
- centralize awaiting text-input routing in handlers/flows.py (R2) (#382) (`flows`)
  — @Ham3dParsa [1583a0a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1583a0a)
- consolidate display-toggle ownership into display_toggles.py (R3) (#377) (`db`)
  — @Ham3dParsa [436ffd2](https://github.com/Ham3dParsa/HamZaboonRobot/commit/436ffd2)
- canonical settings-key registry (J0.2) (`settings`)
  — @Ham3dParsa [3022899](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3022899)

#### Documentation
- add DB continuation serial pipeline (13 tickets A2-1..A2-13) (#386) (`plans`)
  — @Ham3dParsa [537b6fd](https://github.com/Ham3dParsa/HamZaboonRobot/commit/537b6fd)
- mark DB track complete in architecture-deepening theme; consolidate duplicate (#381) (`plans`)
  — @Ham3dParsa [9c822ce](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9c822ce)
- record DB-track consolidation completion (J-A1/A2/A3 merged) (#379) (`plans`)
  — @Ham3dParsa [c8be6f0](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c8be6f0)

#### Testing
- lock bare-admin unknown-fallback after Kilo WARNING fix (#380) (`routing`)
  — @Ham3dParsa [7dd87a5](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7dd87a5)

### 2026-08-16
#### Features
- redesign dashboard UI with hero KPIs and plan tier cards (#369) (`financial-model`)
  — @Ham3dParsa [6f375d7](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6f375d7)

#### Bug Fixes
- provider hardening — fail-closed client seam, real-token TPM, lazy limiter store (J-B1) (#373) (`ai`)
  — @Ham3dParsa [a964770](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a964770)

#### Refactoring
- central callback registry (R1) + B1 double-notify fix (#375) (`routing`)
  — @Ham3dParsa [38d2131](https://github.com/Ham3dParsa/HamZaboonRobot/commit/38d2131)
- centralize plan semantics in plans.py (R5) (#372) (`db`)
  — @Ham3dParsa [b7a3862](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b7a3862)
- add canonical identifier-namespace registry (#370) (`catalog`)
  — @Ham3dParsa [542ffa8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/542ffa8)
- unify atomic writes behind transaction() seam (#371) (`db`)
  — @Ham3dParsa [0b086b5](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0b086b5)

#### Documentation
- lock the Kilo Code Review PR loop into the workflow (§5) (#374) (`agents`)
  — @Ham3dParsa [2024d77](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2024d77)

#### Chores
- update ruff requirement from <1,>=0.16.0 to >=0.16.2,<1 (#368) (`deps`)
  — @dependabot[bot] [2da8917](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2da8917)
- update tzdata requirement from >=2024.1 to >=2026.3 (#367) (`deps`)
  — @dependabot[bot] [50b220b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/50b220b)
- bump openai from 2.53.0 to 3.0.0 (#366) (`deps`)
  — @dependabot[bot] [47944bb](https://github.com/Ham3dParsa/HamZaboonRobot/commit/47944bb)

### 2026-08-15
#### Features
- staged/immediate render for FE and review cards (T2+T3) (#362) (`card-modes`)
  — @Ham3dParsa [4d5ecff](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4d5ecff)
- card-mode schema, registry, and resolver (CARD-MODES T1) (#361) (`db`)
  — @Ham3dParsa [d5a6652](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d5a6652)
- staged-reveal session flow for review cards (Phase 2 of #338) (#355) (`srs`)
  — @Ham3dParsa [7cba7a6](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7cba7a6)
- staged-reveal prompt engine and display-toggle system (Phase 1 of #338) (#353) (`srs`)
  — @Ham3dParsa [c920edb](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c920edb)

#### Bug Fixes
- persist active study session across restart (Bug #363) (#364) (`study`)
  — @Ham3dParsa [0fdec76](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0fdec76)
- reword word-query prompt to clarify it builds a learning card (#358) (`ux`)
  — @Ham3dParsa [87e0ba9](https://github.com/Ham3dParsa/HamZaboonRobot/commit/87e0ba9)
- bump cryptography to 50.0.0 (resolves dependabot alerts) (#360) (`deps`)
  — @Ham3dParsa [c5ebe83](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c5ebe83)
- blank answer word in hints and drop back-stage review badge (#356) (`srs`)
  — @Ham3dParsa [233534d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/233534d)
- canonical preset labels and fix field-edit back button (#352) (`admin-ai`)
  — @Ham3dParsa [2b1315f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2b1315f)

#### Documentation
- mark Bug 1 session-restart plan complete after PR #364 merge (#365) (`session`)
  — @Ham3dParsa [fc508bb](https://github.com/Ham3dParsa/HamZaboonRobot/commit/fc508bb)
- mark T2+T3 merged (#362) and post-merge state (`card-modes`)
  — @Ham3dParsa [07440f3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/07440f3)
- mark T1 merged (#361) and post-merge state (`card-modes`)
  — @Ham3dParsa [191d6a8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/191d6a8)
- mark T1 shipped (PR #361) and record reviewer notes (`card-modes`)
  — @Ham3dParsa [3e85bc2](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3e85bc2)
- record plan tickets and PR #356 seam release (`card-modes`)
  — @Ham3dParsa [6f70299](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6f70299)
- mark phase 2 of staged-reveal (#338) merged via PR #355 (`srs`)
  — @Ham3dParsa [cd35c5a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cd35c5a)
- plan AI_MASTER_KEY rotation (deferred, blocked on Seam 1) (#354) (`security`)
  — @Ham3dParsa [d6e7a19](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d6e7a19)
- lock phase-3 owner decisions (premium toggles, presentation removal, delete scope) (#338) (`srs`)
  — @Ham3dParsa [8e237ad](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8e237ad)
- draft phase 2/3 tickets for staged-reveal (#338) (`srs`)
  — @Ham3dParsa [f3ea53f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f3ea53f)
- mark phase 1 of staged-reveal (#338) merged via PR #353 (`srs`)
  — @Ham3dParsa [dce5bc8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/dce5bc8)
- archive labels-and-back plan and mark complete (#352) (`presets`)
  — @Ham3dParsa [9fc5151](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9fc5151)
- mark Phase 5 secure-keys complete and archive plan (#351) (`ai-preset`)
  — @Ham3dParsa [b735c5d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b735c5d)

#### feat/financial model ui (#359)
- feat/financial model ui (#359)
  — @Ham3dParsa [a4855ce](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a4855ce)

#### IBTN_SRS_EASY_FE = 'کاملاً بلدم 🟪'
- IBTN_SRS_EASY_FE = 'کاملاً بلدم 🟪'
  — @Ham3dParsa [1993e97](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1993e97)

### 2026-08-14
#### Features
- offer duplicate retrieve-vs-new and retain queries 30 days (#345) (`word-query`)
  — @Ham3dParsa [1102541](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1102541)
- encrypt AI preset API keys at rest (Phase 5, #330) (#339) (`db`)
  — @Ham3dParsa [0d9a491](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0d9a491)
- show translations on by default; remove prepare toggle (#341) (`word-query`)
  — @Ham3dParsa [ae5aa49](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ae5aa49)

#### Refactoring
- remove builtin presets and is_custom column (phase 4) (#337) (`ai`)
  — @Ham3dParsa [f185822](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f185822)

#### Documentation
- consolidate AGENTS.md to a lean contract, defer detail to skills (#349) (`agents`)
  — @Ham3dParsa [a2d6c63](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a2d6c63)
- harden parallel-work-guard with worktree isolation and Kilo review loop (#348) (`workflow`)
  — @Ham3dParsa [b59e82e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b59e82e)
- mark duplicate word-query retrieve-vs-new done (closes #344) (`status`)
  — @Ham3dParsa [31600af](https://github.com/Ham3dParsa/HamZaboonRobot/commit/31600af)
- lock word-query card-consistency spec, track via #340 (`ux`)
  — @Ham3dParsa [e43c07b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e43c07b)
- mark archived FSRS plans complete with final verdicts (`fsrs`)
  — @Ham3dParsa [45929ce](https://github.com/Ham3dParsa/HamZaboonRobot/commit/45929ce)
- reconcile T09 release docs, archive FSRS plans, close #309 (`fsrs`)
  — @Ham3dParsa [0391eea](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0391eea)

### 2026-08-13
#### Features
- T06 Phase 03 FSRS atomic grade transitions with GradeResult (#336) (`db`)
  — @Ham3dParsa [f77214c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f77214c)
- phase 3 preset handlers UX - delete confirm, duplicate, wizard back, usage pagination (#334) (`ai`)
  — @Ham3dParsa [1d297db](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1d297db)

#### Bug Fixes
- scope session queue and due count to active language (`srs`)
  — @Ham3dParsa [a3c541d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a3c541d)
- skip rendering empty wizard draft line (#335) (`ai`)
  — @Ham3dParsa [2f128df](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2f128df)
- Admin AI Preset Phase 2 DB correctness + R14 create flow (#333) (`ai`)
  — @Ham3dParsa [a38841a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a38841a)

#### Documentation
- lock staged-reveal + display-toggle spec, track via #338 (`srs`)
  — @Ham3dParsa [25054b1](https://github.com/Ham3dParsa/HamZaboonRobot/commit/25054b1)
- reconcile language-leak audit with implemented fix (`audit`)
  — @Ham3dParsa [d257a1a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d257a1a)
- mark phases 3-5 merged and reconcile release status (`fsrs`)
  — @Ham3dParsa [3e71170](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3e71170)
- mark phase 3 complete and record clone_preset tests (`preset`)
  — @Ham3dParsa [946c268](https://github.com/Ham3dParsa/HamZaboonRobot/commit/946c268)

### 2026-08-12
#### Bug Fixes
- scope dashboard date to project_status.json commit to stop cross-day drift (#321) (#329) (`ci`)
  — @Ham3dParsa [c3e205e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c3e205e)
- support array-index paths and guard non-JSON/empty stdin (#328) (`ghjson`)
  — @Ham3dParsa [40fc822](https://github.com/Ham3dParsa/HamZaboonRobot/commit/40fc822)

#### Refactoring
- extract custom-word-query into pure orchestration core (#320) (`word_query`)
  — @Ham3dParsa [a7ac763](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a7ac763)

#### Documentation
- add Product Layers framing section (#332) (`roadmap`)
  — @Ham3dParsa [7626aca](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7626aca)

#### Chores
- widen reviewer perms, document skill-registry reload, add ghjson helper (#326) (`agent`)
  — @Ham3dParsa [d23480d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d23480d)

### 2026-08-11
#### Features
- add FSRS UTC review timestamp schema columns (#318) (`db`)
  — @Ham3dParsa [aea834e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/aea834e)
- add about section to help panel (#317) (`help`)
  — @Ham3dParsa [2dd58f6](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2dd58f6)
- hide review section from help panel for now (#315) (`help`)
  — @Ham3dParsa [6b74020](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6b74020)
- add /help and راهنما user help panel (#314) (`help`)
  — @Ham3dParsa [ccb6e6c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ccb6e6c)
- grade feedback uses success toast (#308) (#312) (`srs`)
  — @Ham3dParsa [121904b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/121904b)

#### Refactoring
- centralize callback notification policy (#311) (`callbacks`)
  — @Ham3dParsa [b2162c1](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b2162c1)

#### Documentation
- mark FSRS phase 02 complete after merge (#319) (`plans`)
  — @Ham3dParsa [4e3c371](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4e3c371)
- optimize agent workflow with conditional skill injection and tiered reviewer (#313) (`workflow`)
  — @Ham3dParsa [6290b26](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6290b26)
- align plan and parallel-workflow guidance (`agents`)
  — @Ham3dParsa [d4fa6fa](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d4fa6fa)

#### Custom-word query flow: quota release on failure, input validation, save/remove toggle, visible quota (#316)
- Custom-word query flow: quota release on failure, input validation, save/remove toggle, visible quota (#316)
  — @Ham3dParsa [e45a2a9](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e45a2a9)

### 2026-08-10
#### Features
- retire legacy daily card storage (#300) (`fsrs`)
  — @Ham3dParsa [a62bb12](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a62bb12)
- backfill saved word origins (#304) (`fsrs`)
  — @Ham3dParsa [bd58566](https://github.com/Ham3dParsa/HamZaboonRobot/commit/bd58566)

#### Documentation
- tighten parallel-work-guard description and run note (#305) (`skills`)
  — @Ham3dParsa [ea9c09f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ea9c09f)
- add parallel-work-guard skill and claim registry (#302) (`skills`)
  — @Ham3dParsa [188eba5](https://github.com/Ham3dParsa/HamZaboonRobot/commit/188eba5)

### 2026-08-09
#### Features
- route preset key resolution through group-aware resolver (#284) (`db`)
  — @Ham3dParsa [29f559c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/29f559c)

#### Bug Fixes
- harden AI preset panel against callback/escaping/state bugs (#287) (`admin`)
  — @Ham3dParsa [6ab4d40](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6ab4d40)

#### Documentation
- archive completed pr287 follow-ups (`plans`)
  — @Ham3dParsa [8166c9c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8166c9c)

#### Chores
- update pytest requirement from <9,>=8.0 to >=9.1.1,<10 (#219) (`deps`)
  — @dependabot[bot] [d216b74](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d216b74)
- bump httpx from 0.27.2 to 0.28.1 (#220) (`deps`)
  — @dependabot[bot] [7df877b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7df877b)
- bump python-dotenv from 1.0.1 to 1.2.2 (#221) (`deps`)
  — @dependabot[bot] [ef6970f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ef6970f)
- bump openai from 1.51.0 to 2.53.0 (#285) (`deps`)
  — @dependabot[bot] [12ef764](https://github.com/Ham3dParsa/HamZaboonRobot/commit/12ef764)
- update flask requirement from <4,>=3 to >=3.1.3,<4 (#286) (`deps`)
  — @dependabot[bot] [ce12c92](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ce12c92)

#### Add a REVIEW.md file for Review Bots
- Add a REVIEW.md file for Review Bots
  — @Ham3dParsa [e6c842d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e6c842d)

#### fix/review followups (#283)
- fix/review followups (#283)
  — @Ham3dParsa [be76657](https://github.com/Ham3dParsa/HamZaboonRobot/commit/be76657)

### 2026-08-08
#### Features
- add FSRS simulator and fsrs-replay tooling
  — @Ham3dParsa [7a86970](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7a86970)

#### Refactoring
- update plan-persistence and add author metadata across custom skills (`skills`)
  — @Ham3dParsa [7d786e9](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7d786e9)

#### Documentation
- sync callback-wiring routing map with admin thin-dispatcher split (`skills`)
  — @Ham3dParsa [831ae50](https://github.com/Ham3dParsa/HamZaboonRobot/commit/831ae50)
- add planning, audit, and archived plan documents
  — @Ham3dParsa [91a5cc7](https://github.com/Ham3dParsa/HamZaboonRobot/commit/91a5cc7)
- add non-canonical gamification and engagement roadmap
  — @Ham3dParsa [ee3862e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ee3862e)
- reconcile pooling plan and 2026-08-06 audits with current code (`plans`)
  — @Ham3dParsa [86fc718](https://github.com/Ham3dParsa/HamZaboonRobot/commit/86fc718)
- archive completed test-pytest-config plan (`plans`)
  — @Ham3dParsa [972e724](https://github.com/Ham3dParsa/HamZaboonRobot/commit/972e724)
- lock local pytest worker count to -n 14 (`validation`)
  — @Ham3dParsa [ef70c2c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ef70c2c)
- group plans by dependency theme and consolidate audits (`plans`)
  — @Ham3dParsa [85c1076](https://github.com/Ham3dParsa/HamZaboonRobot/commit/85c1076)

#### Chores
- ignore generated and throwaway dev artifacts
  — @Ham3dParsa [973b183](https://github.com/Ham3dParsa/HamZaboonRobot/commit/973b183)

#### refactor/architecture deepening (#271)
- refactor/architecture deepening (#271)
  — @Ham3dParsa [930a63a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/930a63a)

#### chore/test pytest config (#270)
- chore/test pytest config (#270)
  — @Ham3dParsa [3379ec2](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3379ec2)

### 2026-08-07
#### Documentation
- update README.md with current project_status and FSRS migration status
  — @Ham3dParsa [a8f9529](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a8f9529)

#### Chores
- run suite in parallel with pytest-xdist (#268) (`test`)
  — @Ham3dParsa [2e32d6e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2e32d6e)

### 2026-08-06
#### Features
- add entry_source origin tag to saved_words (#266) (`db`)
  — @Ham3dParsa [302ad0d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/302ad0d)
- study-resume fresh card + plan-wizard UX (back/skip/groups) (#260) (`study`)
  — @Ham3dParsa [d62350f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d62350f)
- implement DB-driven admin-editable plan specs (#258) (`plans`)
  — @Ham3dParsa [5bcea03](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5bcea03)

#### Bug Fixes
- answer callback in catch-all, error_handler, and settings handlers (#265) (`bot`)
  — @Ham3dParsa [22c6d97](https://github.com/Ham3dParsa/HamZaboonRobot/commit/22c6d97)

#### Documentation
- archive entry-source plan and commit architecture alignment audit
  — @Ham3dParsa [f34a4ed](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f34a4ed)
- archive completed study+plan-wizard UX plan to docs/archive
  — @Ham3dParsa [130941a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/130941a)

#### Testing
- cover session-resume path regression (#256) (`study`)
  — @Ham3dParsa [87bfe2a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/87bfe2a)

#### Delete docs/plan_pooling.md
- Delete docs/plan_pooling.md
  — @Ham3dParsa [59f5a93](https://github.com/Ham3dParsa/HamZaboonRobot/commit/59f5a93)

#### Add Pool / Semantic-Cache Pre-Decision Audit report
- Add Pool / Semantic-Cache Pre-Decision Audit report
  — @Ham3dParsa [f4ec656](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f4ec656)

### 2026-08-05
#### Features
- add front-end UI, RTL, web-vitals, and interface-review skills (#254) (`skills`)
  — @Ham3dParsa [17fa34b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/17fa34b)
- migrate daily cards to first-exposure session engine (#252) (`db`)
  — @Ham3dParsa [628b9e4](https://github.com/Ham3dParsa/HamZaboonRobot/commit/628b9e4)
- add lean subagents, skills, and graphify indexing (#247) (`opencode`)
  — @Ham3dParsa [aea9908](https://github.com/Ham3dParsa/HamZaboonRobot/commit/aea9908)

#### Bug Fixes
- replace offline error messages with user-friendly apology (`bot`)
  — @Ham3dParsa [5d5685a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5d5685a)
- show manual CAC and ad-budget estimate side by side (#253) (`financial-dashboard`)
  — @Ham3dParsa [b04a2e7](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b04a2e7)
- dynamic plans trial CAC, rebalance, and trial plan picker (#251) (`financial-dashboard`)
  — @Ham3dParsa [8a99ab5](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8a99ab5)
- harden git-protocol PowerShell backtick safety (#249) (`skills`)
  — @Ham3dParsa [9799753](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9799753)
- drop pinned model from subagents for opencode compat (#250) (`agents`)
  — @Ham3dParsa [2493b8a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2493b8a)
- add tzdata dependency and safe timezone fallback for CI (#246) (`config`)
  — @Ham3dParsa [9c75052](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9c75052)

#### Refactoring
- remove stale daily/review/SRS card flows and fix session resume (#255) (`phase2a`)
  — @Ham3dParsa [7b5a99c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7b5a99c)

#### Documentation
- condense AGENTS.md and add lazy git/audit/doc skills (#248) (`agents`)
  — @Ham3dParsa [f0af1fa](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f0af1fa)
- archive completed opencode tooling plan (`agents`)
  — @Ham3dParsa [0143dda](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0143dda)
- sync roadmap, status, AGENTS map, and archive Phase 1 merge plan (#244) (`fsrs`)
  — @Ham3dParsa [8593407](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8593407)
- add PowerShell escaping and Unicode sanitization rules (`agents`)
  — @Ham3dParsa [3c7f251](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3c7f251)

### 2026-08-03
#### Bug Fixes
- accept remaining_slots to fix session completion crash (#243) (`session`)
  — @Ham3dParsa [018894e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/018894e)

### 2026-08-02
#### Features
- merge session engine from feat/fsrs-migration (#240) (`fsrs`)
  — @Ham3dParsa [949c2cc](https://github.com/Ham3dParsa/HamZaboonRobot/commit/949c2cc)
- add real AI model pricing, custom prices and picker to financial dashboard (`tools`)
  — @Ham3dParsa [27968fc](https://github.com/Ham3dParsa/HamZaboonRobot/commit/27968fc)

#### Testing
- add dead-reference, reverse-wiring, and migration guards (#239) (`wp2`)
  — @Ham3dParsa [a8e0509](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a8e0509)

### 2026-08-01
#### Features
- add KPI tooltips and live guide examples to financial dashboard (`tools`)
  — @Ham3dParsa [464addc](https://github.com/Ham3dParsa/HamZaboonRobot/commit/464addc)
- add research-backed P&L, marketing CAC, and AI-cost model to financial dashboard (`tools`)
  — @Ham3dParsa [bc053f6](https://github.com/Ham3dParsa/HamZaboonRobot/commit/bc053f6)
- enforce test-mode DB safety guard (WP1) (#237) (`db`)
  — @Ham3dParsa [58cafbf](https://github.com/Ham3dParsa/HamZaboonRobot/commit/58cafbf)
- add collapsible charts and monthly user-growth chart in financial model (`tools`)
  — @Ham3dParsa [09bbe1a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/09bbe1a)
- upgrade financial model dashboard (`tools`)
  — @Ham3dParsa [6c33e58](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6c33e58)
- add HamZaboon financial model dashboard (`tools`)
  — @Ham3dParsa [00b62ca](https://github.com/Ham3dParsa/HamZaboonRobot/commit/00b62ca)

#### Bug Fixes
- expose KPI_HELP to template to fix dashboard blank page (`tools`)
  — @Ham3dParsa [6c3bcb8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6c3bcb8)
- correct signup_boost growth math and modal flash in financial model (`tools`)
  — @Ham3dParsa [f75c270](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f75c270)

#### Documentation
- mark WP4 merged (`plans`)
  — @Ham3dParsa [ddee3f6](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ddee3f6)
- harden change process with review and done criteria (#238) (`agents`)
  — @Ham3dParsa [14b6052](https://github.com/Ham3dParsa/HamZaboonRobot/commit/14b6052)
- mark financial dashboard phases P1-P6 complete (`tools`)
  — @Ham3dParsa [cca6925](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cca6925)

### 2026-07-31
#### Bug Fixes
- refund quota on AI timeout for custom word and grammar tip (#236) (`bot`)
  — @Ham3dParsa [1626c1c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1626c1c)
- AI preset manager clone crash + permanent test-DB isolation (#235)
  — @Ham3dParsa [06c7fbb](https://github.com/Ham3dParsa/HamZaboonRobot/commit/06c7fbb)

#### feat/fsrs migration (#230)
- feat/fsrs migration (#230)
  — @Ham3dParsa [2ad475a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2ad475a)

### 2026-07-30
#### Bug Fixes
- stop auto-seeding presets on startup — only seed fresh DBs (#229) (`db`)
  — @Ham3dParsa [ba0f681](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ba0f681)
- stop _init_ai_presets_table from overwriting custom presets and pricing on every restart (`db`)
  — @Ham3dParsa [a2a310c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a2a310c)

#### Documentation
- update docs to reflect removal of Persian phonetic transcription (#228)
  — @Ham3dParsa [9aa9e9b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9aa9e9b)

#### Chores
- remove Persian phonetic transcription (keep IPA only) (#227) (`phonetic`)
  — @Ham3dParsa [1c33630](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1c33630)

### 2026-07-29
#### Features
- add FSRS-6 migration plan and Phase 1a core engine (`fsrs`)
  — @Ham3dParsa [0a89b50](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0a89b50)

#### Chores
- add standalone FSRS-6 simulator HTML and reference it in strategic docs (`tools`)
  — @Ham3dParsa [bcb6104](https://github.com/Ham3dParsa/HamZaboonRobot/commit/bcb6104)

### 2026-07-28
#### Features
- add v5.2 FSRS-6 full comparison + rename versions (`Fsrs_simulation_v5`)
  — @Ham3dParsa [85e7263](https://github.com/Ham3dParsa/HamZaboonRobot/commit/85e7263)
- add SRS simulation modules v2-v5 + benchmarks (`tools`)
  — @Ham3dParsa [48741f2](https://github.com/Ham3dParsa/HamZaboonRobot/commit/48741f2)

#### Docs/ Added FSRSv6 documentations
- Docs/ Added FSRSv6 documentations
  — @Ham3dParsa [6de1750](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6de1750)

### 2026-07-26
#### Features
- SRS Session Engine v3 pull-based simulation (v2 simulator) (#224) (`tools`)
  — @Ham3dParsa [158e793](https://github.com/Ham3dParsa/HamZaboonRobot/commit/158e793)
- SRS v2.8 simulation tool with interactive mode and usage guide (#222) (`tools`)
  — @Ham3dParsa [505eb85](https://github.com/Ham3dParsa/HamZaboonRobot/commit/505eb85)
- bulk edit modal, accordion groups, visual chain, UI cleanup (`ai-preset-manager`)
  — @Ham3dParsa [1d2fab3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1d2fab3)

#### Bug Fixes
- strip quotes from CSV path input in interactive mode (#223) (`srs-sim`)
  — @Ham3dParsa [b090710](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b090710)
- remove unused cost_per_req field from edit panel (`ai-preset-manager`)
  — @Ham3dParsa [66422ac](https://github.com/Ham3dParsa/HamZaboonRobot/commit/66422ac)
- replace cost_per_1k_tokens with input/output_cost_per_million in edit panel (`ai-preset-manager`)
  — @Ham3dParsa [d61490f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d61490f)

#### Refactoring
- consolidate main menu, redesign SRS flow, add settings inline keyboard (#217) (`keyboards`)
  — @Ham3dParsa [73beff3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/73beff3)

#### feature/engine v3 migration (#225)
- feature/engine v3 migration (#225)
  — @Ham3dParsa [0eb2626](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0eb2626)

### 2026-07-25
#### Features
- enrich user stats with sub-menus and remove dead button from main keyboard (#216) (`admin`)
  — @Ham3dParsa [9254621](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9254621)

#### Bug Fixes
- correct MODEL_COST_MAP prices and USD_TO_IRR (`benchmark`)
  — @Ham3dParsa [5950c0a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5950c0a)
- one-line USER activity without cost, full_name at end (`logging`)
  — @Ham3dParsa [7a88bc8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7a88bc8)

#### Documentation
- update README, AGENTS, ROADMAP, .env.example and clean up archived plan (`project`)
  — @Ham3dParsa [dbe9bd1](https://github.com/Ham3dParsa/HamZaboonRobot/commit/dbe9bd1)

#### Chores
- update ruff requirement from <1,>=0.9 to >=0.16.0,<1 (#212) (`deps`)
  — @dependabot[bot] [1172735](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1172735)
- update colorlog requirement from <7,>=6.8 to >=6.12.0,<7 (#213) (`deps`)
  — @dependabot[bot] [770d6f8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/770d6f8)
- update edge-tts requirement from <8,>=7.0 to >=7.2.8,<8 (#214) (`deps`)
  — @dependabot[bot] [052bf58](https://github.com/Ham3dParsa/HamZaboonRobot/commit/052bf58)
- bump python-telegram-bot from 21.6 to 22.8 (#215) (`deps`)
  — @dependabot[bot] [f3ba4fd](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f3ba4fd)
- remove CodeQL workflow (requires public repo or paid plan) (`ci`)
  — @Ham3dParsa [ec12d19](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ec12d19)

### 2026-07-24
#### Features
- help pages and last-successful-preset tracking (#208) (`admin,keyboards`)
  — @Ham3dParsa [031cc6b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/031cc6b)
- compact fallback chain UX with rank jump and consumption view (#208) (`db,llm,admin,keyboards`)
  — @Ham3dParsa [86f89ec](https://github.com/Ham3dParsa/HamZaboonRobot/commit/86f89ec)
- preset group/pagination, full edit wizard, confirm dialog (#208) (`admin,keyboards,db`)
  — @Ham3dParsa [6b48778](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6b48778)
- per-preset cost fields with global fallback (#208) (`db,ai,admin`)
  — @Ham3dParsa [a596a49](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a596a49)
- add preset cost, group_label, in_fallback_chain, preset_name columns (#207) (`db`)
  — @Ham3dParsa [5f74d76](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5f74d76)

#### Bug Fixes
- detect blocked users to prevent wasted AI and Telegram API calls (#210) (`bot`)
  — @Ham3dParsa [143c2c5](https://github.com/Ham3dParsa/HamZaboonRobot/commit/143c2c5)
- use thin_white instead of grey (colorlog has no grey) (`logging`)
  — @Ham3dParsa [cf20a42](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cf20a42)

#### Documentation
- overhaul documentation ecosystem and add CI/CD tooling (#211) (`project`)
  — @Ham3dParsa [ba23b7a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ba23b7a)

#### Testing
- add integration tests for fallback chain behavior (`fallback`)
  — @Ham3dParsa [b336e90](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b336e90)

#### Chores
- use grey for INFO level instead of green (`logging`)
  — @Ham3dParsa [50bc113](https://github.com/Ham3dParsa/HamZaboonRobot/commit/50bc113)

#### feat/preset edit extended (#209)
- feat/preset edit extended (#209)
  — @Ham3dParsa [31c2a00](https://github.com/Ham3dParsa/HamZaboonRobot/commit/31c2a00)

### 2026-07-23
#### Features
- colored severity, COST pipe format, preset switch logs, USER_ACTIVITY level (#205) (`logging`)
  — @Ham3dParsa [ba44ca2](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ba44ca2)
- add AI model benchmark tool with cost/retry/report pipeline (#206) (`benchmark`)
  — @Ham3dParsa [40810c4](https://github.com/Ham3dParsa/HamZaboonRobot/commit/40810c4)
- colored console output, COST level, runtime log level control (#204) (`logging`)
  — @Ham3dParsa [caa2fc3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/caa2fc3)

#### Bug Fixes
- align levelname column despite double-width emoji (`logging`)
  — @Ham3dParsa [fd8cb41](https://github.com/Ham3dParsa/HamZaboonRobot/commit/fd8cb41)
- match USER levelname to log_colors key after emoji prepend (`logging`)
  — @Ham3dParsa [3f5ffd6](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3f5ffd6)
- remove double emoji on USER level (`logging`)
  — @Ham3dParsa [e12ae24](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e12ae24)
- add admin panel back navigation, TTS toggle, and preset delete (`admin`)
  — @Ham3dParsa [1994fb4](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1994fb4)

### 2026-07-22
#### Features
- replace old presets with fallback chain & Google multi-key presets (`db`)
  — @Ham3dParsa [4dbad29](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4dbad29)

#### Bug Fixes
- add BEGIN IMMEDIATE to all write functions (`db`)
  — @Ham3dParsa [e5e1d69](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e5e1d69)
- wrap sync AI calls in asyncio.to_thread and fix _daily_locks thread-safety (#176) (`admin,bot`)
  — @Ham3dParsa [96dfb8c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/96dfb8c)

### 2026-07-21
#### Documentation
- add Integration Test Protocol to AGENTS.md (#147) (`agents`)
  — @Ham3dParsa [8f559b3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8f559b3)
- update AGENTS.md with CI workflow references (#146) (`agents`)
  — @Ham3dParsa [59b2e6f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/59b2e6f)

#### Testing
- add AST-based callback routing integrity scanner with sub-router coverage (#144) (`wiring`)
  — @Ham3dParsa [4798e0b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4798e0b)

#### chore/test cleanup (#143)
- chore/test cleanup (#143)
  — @Ham3dParsa [117a8fc](https://github.com/Ham3dParsa/HamZaboonRobot/commit/117a8fc)

### 2026-07-20
#### Features
- circuit breaker reset, SRS retry queue, raw call migration (#142) (`network`)
  — @Ham3dParsa [fdd5a81](https://github.com/Ham3dParsa/HamZaboonRobot/commit/fdd5a81)
- add circuit breaker and retry wrappers (#137) (`network`)
  — @Ham3dParsa [b95c438](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b95c438)

#### Refactoring
- restructure flat modules into packages and clean up stale docs (#140) (`project`)
  — @Ham3dParsa [d0d8035](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d0d8035)
- centralize all inline button labels as IBTN_ constants (#139) (`keyboards`)
  — @Ham3dParsa [39cedfa](https://github.com/Ham3dParsa/HamZaboonRobot/commit/39cedfa)

#### Documentation
- update file paths to reflect package restructuring (#141) (`agents`)
  — @Ham3dParsa [b8bdb47](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b8bdb47)

### 2026-07-19
#### Features
- add Ruff linting, wiring tests, formatting boundary tests, and AGENTS.md updates (#133) (`testing`)
  — @Ham3dParsa [4fa2f92](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4fa2f92)
- Edge TTS pronunciation with caching, premium gating, on-demand button (#131) (`tts`)
  — @Ham3dParsa [6086e61](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6086e61)
- AI presets with batch/RPM control, test/fallback, backup/restore (`admin`)
  — @Ham3dParsa [70a8921](https://github.com/Ham3dParsa/HamZaboonRobot/commit/70a8921)
- extract admin panel, LLM cost dashboard, and admin handlers to admin.py (Stage 5) (`admin`)
  — @Ham3dParsa [8af2a5b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8af2a5b)
- extract SRS handler module from bot.py and user.py (#129) (`srs`)
  — @Ham3dParsa [7466b9d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7466b9d)
- extract user-facing handlers and llm_services module (#128) (`user`)
  — @Ham3dParsa [0f5fd3e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0f5fd3e)

#### Bug Fixes
- correct TTS handler parsing and restructure admin panel UX (#134) (`bot`)
  — @Ham3dParsa [ec2bc07](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ec2bc07)
- audit fixes — imports, backup/restore, fallback retry, custom test candidate (#132) (`admin`)
  — @Ham3dParsa [7515504](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7515504)

### 2026-07-18
#### Features
- extract shared Telegram plumbing from bot.py (#127) (`helpers`)
  — @Ham3dParsa [c59a5f8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c59a5f8)
- extract formatting and card rendering module from bot.py (#126) (`formatting`)
  — @Ham3dParsa [86248b8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/86248b8)
- add staged self-test SRS reminder with recall tracking (#115) (`bot`)
  — @Ham3dParsa [f66ebac](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f66ebac)
- overhaul UX with 1440p grid, interactive stats, progress fix, decision links, and watch/serve CLI (#112) (`dashboard`)
  — @Ham3dParsa [6e05f08](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6e05f08)
- remove Latin pronunciation from all new phonetic generations (`ai`)
  — @Ham3dParsa [96ebe0f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/96ebe0f)

#### Bug Fixes
- restore main menu keyboard after ask-word flow (#114) (`bot`)
  — @Ham3dParsa [37379da](https://github.com/Ham3dParsa/HamZaboonRobot/commit/37379da)
- release Windows SQLite file locks by using db.get_conn() with explicit commit (#113) (`tests`)
  — @Ham3dParsa [976e8f7](https://github.com/Ham3dParsa/HamZaboonRobot/commit/976e8f7)
- add delivery atomicity, grace timeout, stale recovery, and cap migration (`srs`)
  — @Ham3dParsa [5bb7022](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5bb7022)
- add language-scoped word avoidance to fix scheduled delivery TypeError (#75) (`bot`)
  — @Ham3dParsa [9fbf084](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9fbf084)

#### Documentation
- add staged extraction plan for bot.py modules (#124) (`bot`)
  — @Ham3dParsa [3faf464](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3faf464)
- add vision and product goals document (#117) (`vision`)
  — @Ham3dParsa [fad449e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/fad449e)
- add dashboard UX overhaul to implementation status (`roadmap`)
  — @Ham3dParsa [e85329a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e85329a)
- add docstrings to public functions and dataclass (#76) (`scheduling`)
  — @Ham3dParsa [0be2b0e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0be2b0e)

#### Chores
- remove redundant hamzaban-issues.md markdown export (`issues`)
  — @Ham3dParsa [cf906be](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cf906be)
- add logging, error handling, and dry-run to migrate_phonetics.py (`tools`)
  — @Ham3dParsa [71fba9e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/71fba9e)
- mark issue #71 as resolved (Latin pronunciation removed) (`issues`)
  — @Ham3dParsa [c904117](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c904117)

#### feat/gh issues migration (#111)
- feat/gh issues migration (#111)
  — @Ham3dParsa [b2dcd9b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b2dcd9b)

### 2026-07-17
#### Documentation
- correct Section 2.5.1 reference (`agents`)
  — @Ham3dParsa [5075852](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5075852)
- renumber section 2 and make roadmap_refs optional (`agents`)
  — @Ham3dParsa [6a8e10c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6a8e10c)
- number section headers and restore full rework warning (`agents`)
  — @Ham3dParsa [43d7886](https://github.com/Ham3dParsa/HamZaboonRobot/commit/43d7886)
- define outdated test handling and owner inquiry protocols (`agents`)
  — @Ham3dParsa [bc99300](https://github.com/Ham3dParsa/HamZaboonRobot/commit/bc99300)
- enhance error recovery, localization, and gate tags (`agents`)
  — @Ham3dParsa [e82aa42](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e82aa42)

### 2026-07-16
#### Features
- unify and strengthen phonetic validation
  — @Ham3dParsa [c08cdfa](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c08cdfa)

#### Documentation
- strengthen git workflow enforcement in AGENTS.md (`agents`)
  — @Ham3dParsa [caafd29](https://github.com/Ham3dParsa/HamZaboonRobot/commit/caafd29)

### 2026-07-15
#### Features
- add card generation tool
  — @Ham3dParsa [e6cba57](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e6cba57)
- normalize phonetic data structure in database
  — @Ham3dParsa [7696816](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7696816)

#### Bug Fixes
- robustly parse and format phonetic data in bot output
  — @Ham3dParsa [f403317](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f403317)
- restore phonetic fallback for legacy/unlabeled cards if Latin is enabled
  — @Ham3dParsa [6746732](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6746732)
- enforce strict phonetic labels and relax synonym/antonym validation
  — @Ham3dParsa [8da938b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8da938b)

#### Documentation
- clarify filtering limitations in README
  — @Ham3dParsa [11626f9](https://github.com/Ham3dParsa/HamZaboonRobot/commit/11626f9)
- add README for tools directory
  — @Ham3dParsa [cccbb0a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cccbb0a)
- move planning documents to docs directory
  — @Ham3dParsa [1bb1c3c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1bb1c3c)
- move audit reports to Audits directory
  — @Ham3dParsa [cb74cae](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cb74cae)
- restructure and document .env.example
  — @Ham3dParsa [ca724f8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ca724f8)

#### Chores
- move utility scripts to tools directory
  — @Ham3dParsa [ba38952](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ba38952)
- update environment defaults for Toman rate and Telegram concurrency
  — @Ham3dParsa [64bba17](https://github.com/Ham3dParsa/HamZaboonRobot/commit/64bba17)
- update .env.example with phonetic display defaults
  — @Ham3dParsa [e99d258](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e99d258)

#### Implemented a more robust escaping approach in the on_level_selected function within bot.py.
- Implemented a more robust escaping approach in the on_level_selected function within bot.py.
  — @Ham3dParsa [ca8e95d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ca8e95d)

### 2026-07-14
#### Features
- quiet polling logs and report connection health
  — @HamedParsa [dda1c54](https://github.com/Ham3dParsa/HamZaboonRobot/commit/dda1c54)
- add premium presentation preferences
  — @HamedParsa [097d1cf](https://github.com/Ham3dParsa/HamZaboonRobot/commit/097d1cf)
- add cached translation preparation flow
  — @HamedParsa [b3af5e5](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b3af5e5)
- restore card richness and presentation modes
  — @HamedParsa [1390a30](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1390a30)
- add local project status editor
  — @HamedParsa [762b8dd](https://github.com/Ham3dParsa/HamZaboonRobot/commit/762b8dd)
- add validated project status editor
  — @HamedParsa [4dd204e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4dd204e)

#### Documentation
- record SRS and scheduled delivery risks
  — @HamedParsa [17a9f91](https://github.com/Ham3dParsa/HamZaboonRobot/commit/17a9f91)
- define per-rule contract locking workflow
  — @HamedParsa [575461e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/575461e)
- lock agent decisions and track modularization
  — @HamedParsa [1a57521](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1a57521)
- structure roadmap project status
  — @HamedParsa [397ab0b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/397ab0b)
- audit card richness and translation UX
  — @HamedParsa [6b29b37](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6b29b37)

#### Testing
- add rendering cache regression contracts
  — @HamedParsa [7057ef4](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7057ef4)

#### Enhance UI/UX: category-based card borders, quick filter chips, search highlighting, 3-column phase layout, priority badges
- Enhance UI/UX: category-based card borders, quick filter chips, search highlighting, 3-column phase layout, priority badges
  — @Ham3dParsa [ca53d02](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ca53d02)

#### updates on project_status.html
- updates on project_status.html
  — @Ham3dParsa [1e36bce](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1e36bce)

#### Audit card failure reporting pipeline
- Audit card failure reporting pipeline
  — @Devin AI [03e4296](https://github.com/Ham3dParsa/HamZaboonRobot/commit/03e4296)

#### Update roadmap and issues for review UX
- Update roadmap and issues for review UX
  — @Devin AI [358d7bf](https://github.com/Ham3dParsa/HamZaboonRobot/commit/358d7bf)

#### Enhance project_status.html for 1440p with unified sidebar and phase-issue integration
- Enhance project_status.html for 1440p with unified sidebar and phase-issue integration
  — @Ham3dParsa [4b46726](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4b46726)

#### Add configurable phonetic rendering
- Add configurable phonetic rendering
  — @HamedParsa [5eefefd](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5eefefd)

#### Updated Card Formatting
- Updated Card Formatting
  — @Ham3dParsa [35bb86e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/35bb86e)
- Updated Card Formatting
  — @Ham3dParsa [6d7ff1a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6d7ff1a)

#### fix stale callback query crash in prepare handlers
- fix stale callback query crash in prepare handlers
  — @HamedParsa [7b3afd7](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7b3afd7)

#### fix prepared translation label escaping
- fix prepared translation label escaping
  — @Devin AI [f95fe3d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f95fe3d)

#### backed up the legacy issues.html
- backed up the legacy issues.html
  — @Ham3dParsa [c6410a2](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c6410a2)

#### fix card translation quote formatting
- fix card translation quote formatting
  — @Devin AI [96119bf](https://github.com/Ham3dParsa/HamZaboonRobot/commit/96119bf)

### 2026-07-13
#### Features
- use compact JSON for AI cards and batches
  — @HamedParsa [c394115](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c394115)
- improve LLM cost dashboard UX
  — @HamedParsa [491f19b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/491f19b)

#### Bug Fixes
- retry daily batches without avoid-list anchoring
  — @HamedParsa [b023a2a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b023a2a)
- diagnose empty validated daily batches
  — @HamedParsa [e985456](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e985456)

#### Documentation
- map card presentation direction in roadmap
  — @HamedParsa [d6de9fe](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d6de9fe)
- track card presentation preferences
  — @HamedParsa [cb2285b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cb2285b)
- add quota and network issues
  — @Devin AI [236e1b1](https://github.com/Ham3dParsa/HamZaboonRobot/commit/236e1b1)
- add future issue ideas
  — @Devin AI [0be29a1](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0be29a1)
- phase the roadmap backlog
  — @Devin AI [3a115af](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3a115af)
- lock adaptive SRS roadmap
  — @HamedParsa [37885ba](https://github.com/Ham3dParsa/HamZaboonRobot/commit/37885ba)
- add locked content pooling plan
  — @HamedParsa [5ff622a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5ff622a)
- lock segment content pooling decisions
  — @HamedParsa [9951aab](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9951aab)

#### Chores
- split batch duplicate diagnostics
  — @HamedParsa [58c4893](https://github.com/Ham3dParsa/HamZaboonRobot/commit/58c4893)

#### Other
- tested differet formats in terms of token usuage
  — @Ham3dParsa [ecf807c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ecf807c)
- better navigation, More control over status
  — @Ham3dParsa [aff7ece](https://github.com/Ham3dParsa/HamZaboonRobot/commit/aff7ece)
- better navigation, More control over status
  — @Ham3dParsa [d4ee22d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d4ee22d)
- sticky controls and two-column issue cards; fix resolved quick filter
  — @Ham3dParsa [eb306c3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/eb306c3)
- prune fixed issues and refresh roadmap
  — @Devin AI [7d7326c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7d7326c)

#### Updated Issues.html
- Updated Issues.html
  — @Ham3dParsa [e29d66d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e29d66d)
- Updated Issues.html
  — @Ham3dParsa [6aaf8b3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6aaf8b3)

#### tiny edit on a QUIZZ related feature
- tiny edit on a QUIZZ related feature
  — @Ham3dParsa [08f6adf](https://github.com/Ham3dParsa/HamZaboonRobot/commit/08f6adf)

#### added a note on issue #40
- added a note on issue #40
  — @Ham3dParsa [052afd1](https://github.com/Ham3dParsa/HamZaboonRobot/commit/052afd1)

#### changed defaluts in the exanple conf
- changed defaluts in the exanple conf
  — @Ham3dParsa [1afbf12](https://github.com/Ham3dParsa/HamZaboonRobot/commit/1afbf12)

#### Seed LLM pricing defaults
- Seed LLM pricing defaults
  — @HamedParsa [0403c92](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0403c92)

#### Add LLM cost metrics dashboard
- Add LLM cost metrics dashboard
  — @HamedParsa [519372b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/519372b)

#### Improve AI efficiency and SRS reliability
- Improve AI efficiency and SRS reliability
  — @HamedParsa [d3e2118](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d3e2118)

### 2026-07-12
#### Features
- paginate review history by week
  — @HamedParsa [8f5d887](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8f5d887)
- lock daily card session snapshots
  — @HamedParsa [3393ee9](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3393ee9)
- prime manual daily card batches
  — @HamedParsa [e258a47](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e258a47)
- harden custom-word input
  — @HamedParsa [e1f0226](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e1f0226)
- add llm wait-state feedback
  — @HamedParsa [cfab1ce](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cfab1ce)
- add llm wait-state feedback
  — @HamedParsa [f839e8d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f839e8d)
- count daily learning toward streaks
  — @HamedParsa [a71dd2f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a71dd2f)
- cap grammar tips and note review ux
  — @HamedParsa [7f7387e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7f7387e)
- improve issues explorer filters
  — @HamedParsa [4ee04d1](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4ee04d1)
- add daily card review history
  — @HamedParsa [6dbd2fb](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6dbd2fb)
- add custom-word review callbacks
  — @HamedParsa [0b44f01](https://github.com/Ham3dParsa/HamZaboonRobot/commit/0b44f01)
- clarify runtime configuration and plan quotas
  — @HamedParsa [152a9fd](https://github.com/Ham3dParsa/HamZaboonRobot/commit/152a9fd)
- add durable load-aware scheduled delivery
  — @HamedParsa [cbcea68](https://github.com/Ham3dParsa/HamZaboonRobot/commit/cbcea68)
- add on-demand interactive flashcards
  — @HamedParsa [5dafa7a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5dafa7a)

#### Bug Fixes
- ignore automatic deliveries for streaks
  — @HamedParsa [5b81d96](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5b81d96)
- keep issue exports optional
  — @HamedParsa [227aeaf](https://github.com/Ham3dParsa/HamZaboonRobot/commit/227aeaf)
- harden delivery and quota correctness
  — @HamedParsa [2137838](https://github.com/Ham3dParsa/HamZaboonRobot/commit/2137838)

#### Refactoring
- centralize issue review tooling
  — @HamedParsa [fe84895](https://github.com/Ham3dParsa/HamZaboonRobot/commit/fe84895)
- centralize learner option catalog
  — @HamedParsa [6500b50](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6500b50)

#### Documentation
- record incomplete SRS card review
  — @HamedParsa [c81194d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c81194d)
- clarify vocab knowledge roadmap item
  — @HamedParsa [433cfdf](https://github.com/Ham3dParsa/HamZaboonRobot/commit/433cfdf)
- add vocab size estimation roadmap item
  — @HamedParsa [77a2897](https://github.com/Ham3dParsa/HamZaboonRobot/commit/77a2897)
- audit scheduled job reliability
  — @HamedParsa [ed3d4ba](https://github.com/Ham3dParsa/HamZaboonRobot/commit/ed3d4ba)
- add wait-state ux audit
  — @HamedParsa [b806c89](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b806c89)
- audit daily-card batching
  — @HamedParsa [92e286a](https://github.com/Ham3dParsa/HamZaboonRobot/commit/92e286a)
- audit streak and automation gaps
  — @HamedParsa [49fa81f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/49fa81f)
- lock session language and issue phases
  — @HamedParsa [9dceea8](https://github.com/Ham3dParsa/HamZaboonRobot/commit/9dceea8)
- record custom-word audit findings
  — @HamedParsa [eb56c74](https://github.com/Ham3dParsa/HamZaboonRobot/commit/eb56c74)
- lock AI mini quizzes roadmap
  — @Devin AI [8ef354d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/8ef354d)
- add agent workflow guidance
  — @HamedParsa [908cbe0](https://github.com/Ham3dParsa/HamZaboonRobot/commit/908cbe0)
- consolidate code review findings and roadmap
  — @HamedParsa [4f3ad7f](https://github.com/Ham3dParsa/HamZaboonRobot/commit/4f3ad7f)
- lock catalog as option registry owner
  — @HamedParsa [48780fb](https://github.com/Ham3dParsa/HamZaboonRobot/commit/48780fb)
- define canonical language registry architecture
  — @HamedParsa [20109f7](https://github.com/Ham3dParsa/HamZaboonRobot/commit/20109f7)
- derive session sizes from daily allowance
  — @HamedParsa [3b18d9d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3b18d9d)
- define load-aware learning delivery
  — @HamedParsa [c70eb30](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c70eb30)
- sync roadmap with interactive card direction
  — @HamedParsa [18da715](https://github.com/Ham3dParsa/HamZaboonRobot/commit/18da715)

#### Audit For Word SRS
- Audit For Word SRS
  — @Ham3dParsa [3ac5b8d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/3ac5b8d)

#### adding some notes and destails to the issue #26
- adding some notes and destails to the issue #26
  — @Ham3dParsa [6a918c3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/6a918c3)

#### adding a plan to update  Issues.html sub app
- adding a plan to update  Issues.html sub app
  — @Ham3dParsa [b10e9ed](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b10e9ed)
- adding a plan to update  Issues.html sub app
  — @Ham3dParsa [62cca2c](https://github.com/Ham3dParsa/HamZaboonRobot/commit/62cca2c)
- adding a plan to update  Issues.html sub app
  — @Ham3dParsa [d0f7265](https://github.com/Ham3dParsa/HamZaboonRobot/commit/d0f7265)

#### Updates on Issues.html sub app
- Updates on Issues.html sub app
  — @Ham3dParsa [5ad9e54](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5ad9e54)

#### Adding Issue Manager Module
- Adding Issue Manager Module
  — @Ham3dParsa [929916b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/929916b)

#### Changed some defaults in the Example_Config
- Changed some defaults in the Example_Config
  — @Ham3dParsa [12738e4](https://github.com/Ham3dParsa/HamZaboonRobot/commit/12738e4)

#### Changed the roadmap batching logic
- Changed the roadmap batching logic
  — @Ham3dParsa [05dda56](https://github.com/Ham3dParsa/HamZaboonRobot/commit/05dda56)

#### Changing the default LLM in the Example_Config
- Changing the default LLM in the Example_Config
  — @Ham3dParsa [a6785c9](https://github.com/Ham3dParsa/HamZaboonRobot/commit/a6785c9)

### 2026-07-11
#### Features
- add plan access controls
  — @HamedParsa [03424a2](https://github.com/Ham3dParsa/HamZaboonRobot/commit/03424a2)
- generate daily cards in batches
  — @HamedParsa [5cc887d](https://github.com/Ham3dParsa/HamZaboonRobot/commit/5cc887d)
- اضافه کردن دکمه‌های جدید/تغییر منو (`keyboards`)
  — @Ham3dParsa [e6c2feb](https://github.com/Ham3dParsa/HamZaboonRobot/commit/e6c2feb)
- add proficiency levels and card validation
  — @HamedParsa [7b375f3](https://github.com/Ham3dParsa/HamZaboonRobot/commit/7b375f3)

#### Documentation
- align product page with roadmap
  — @HamedParsa [869738e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/869738e)
- add product roadmap
  — @HamedParsa [72d72c5](https://github.com/Ham3dParsa/HamZaboonRobot/commit/72d72c5)

#### Chores
- به‌روزرسانی .gitignore برای فایل‌های مستندات
  — @Ham3dParsa [c04e567](https://github.com/Ham3dParsa/HamZaboonRobot/commit/c04e567)
- حذف فایل قدیمی hamzaban-product-doc.html
  — @Ham3dParsa [b4e5a0e](https://github.com/Ham3dParsa/HamZaboonRobot/commit/b4e5a0e)

#### Other
- cache daily cards per plan limit and add SRS reminder job
  — @HamedParsa [988f83b](https://github.com/Ham3dParsa/HamZaboonRobot/commit/988f83b)

#### Rename hamzaban-product-doc.html to hamzaban-product-doc-v2.html
- Rename hamzaban-product-doc.html to hamzaban-product-doc-v2.html
  — @Ham3dParsa [356c0a7](https://github.com/Ham3dParsa/HamZaboonRobot/commit/356c0a7)

#### افزودن نقشه راه اولیه محصول
- افزودن نقشه راه اولیه محصول
  — @Ham3dParsa [f6fe089](https://github.com/Ham3dParsa/HamZaboonRobot/commit/f6fe089)

#### Fix daily-card MarkdownV2 crash, duplicate words, and add error handler
- Fix daily-card MarkdownV2 crash, duplicate words, and add error handler
  — @HamedParsa [509d3f6](https://github.com/Ham3dParsa/HamZaboonRobot/commit/509d3f6)

#### Initial commit: هم‌زبان Telegram bot MVP
- Initial commit: هم‌زبان Telegram bot MVP
  — @HamedParsa [80d11fa](https://github.com/Ham3dParsa/HamZaboonRobot/commit/80d11fa)

---

This changelog is generated automatically. Manual edits will be overwritten.
