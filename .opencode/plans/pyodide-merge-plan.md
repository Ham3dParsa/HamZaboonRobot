# Pyodide Merge Plan: FSRS-6 Simulator v1.4

**Goal:** Replace JS simulation engine with embedded Python `v5.4_FSRS_full.py` running via Pyodide (WebAssembly), keeping the HTML/Chart.js UI intact.

**Target file:** `tools/Fsrs_simulation_v5/fsrs_simulator_v1.4.htm`

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  HTML / CSS (RT L Persian)            │
├──────────────────────────────────────────────────────┤
│  UI Layer (JS)                                       │
│  • Controls (plan, persona, seed buttons/sliders)    │
│  • Chart.js rendering (4 charts)                     │
│  • Step-by-step replay of pre-computed events        │
│  • Time-lapse controls (▶ ⏭ ⏮ ⏹)                    │
├──────────────────────────────────────────────────────┤
│  Pyodide WASM Bridge                                 │
│  • loadPyodide() on page init                        │
│  • runPython() executes v5.4 code                    │
│  • JSON serialization for JS↔Python data exchange    │
├──────────────────────────────────────────────────────┤
│  Python v5.4 (embedded in <script type="text/python">)│
│  • simulate(cfg) → (rows, summary, events)           │
│  • Full FSRS-6 DSR formulas + Persona + Attendance   │
│  • Rejection, Catch-up, Proficiency, Debt caps       │
└──────────────────────────────────────────────────────┘
```

**Key decision — step-by-step handling:**

Instead of calling Python per-card (too slow due to Pyodide bridge overhead), the Python `simulate()` will be extended to return a **detailed event log**:

```python
# Each event in the log:
{
  "day": int,
  "card_idx": int,       # index into cardsPool
  "type": "first_exposure" | "review",
  "grade": 1-4,
  "stability_before": float,
  "stability_after": float,
  "difficulty_before": float,
  "difficulty_after": float,
  "retrievability": float,
  "outcome": "forget"|"hold"|"advance"|"master",
  "interval_days": int,
}
```

JS replays these events step-by-step (showing the card, animating the grade button, updating stats). This is like "playing back a recording" of the Python simulation.

---

## Implementation Steps

### Step 1: Add Pyodide loader to `<head>`

```html
<script src="https://cdn.jsdelivr.net/pyodide/v0.25.0/full/pyodide.js"></script>
```

Same pattern as existing Chart.js CDN include. No version pinning needed — `v0.25.0` is stable.

### Step 2: Embed Python code

Use `<script type="text/python">` tag — Pyodide natively discovers these:

```html
<script type="text/python">
# v5.4_FSRS_full.py — full content inline, EXCEPT:
# - Remove __main__ block
# - Remove format_table() and write_csv() (unused in browser)
# - Add exported function: simulate_and_return_json(cfg_dict)
</script>
```

Alternatively, embed as a JS string and pass to `pyodide.runPython()` at init time. More explicit control.

### Step 3: Modify `simulate()` to return events

Add to `v5.4_FSRS_full.py`:

```python
def simulate_detailed(cfg: SimConfig) -> dict:
    """Like simulate() but returns per-card event log for step-by-step replay."""
    rows, summary, extra = simulate(cfg, debug=True)
    # Build event log from extra["active"] + lateness_samples
    # Card word mapping from cardsPool (passed as JS global)
    ...
    return {"rows": rows, "summary": summary, "events": event_log}
```

A `cardsPool` mapping (index → word) is passed from JS to Python at init time so events can reference the word/translation for display.

### Step 4: JS bridge layer

```javascript
// In HTML <script> block:
let pyodide;

async function initPyodide() {
    pyodide = await loadPyodide();
    // Execute embedded Python
    await pyodide.runPython(pythonCodeString);
    // Pass cards pool to Python
    pyodide.globals.set("cards_pool_json", JSON.stringify(cardsPool));
}

async function runSimulationPython(config) {
    const pyCode = `
cfg = SimConfig(
    plan="${config.plan}",
    persona="${config.persona}",
    proficiency="${config.proficiency}",
    days=${config.days},
    seed=${config.seed}
)
result = simulate_detailed(cfg)
import json
json.dumps(result)
    `;
    return JSON.parse(await pyodide.runPythonAsync(pyCode));
}
```

### Step 5: Replace JS `Simulation` class

- `new Simulation(config, cardsPool)` → calls `runSimulationPython(config)` (async)
- Returns events array + rows + summary
- Current JS Simulation class/startDay/advanceCard/submitGrade are **removed** (no longer used)
- JS state machine becomes a simple "replay index" that walks through the events array

### Step 6: Replay engine in JS

```javascript
let events = [];          // pre-computed from Python
let eventIndex = 0;
let currentDayEvents = []; // events for the current day

function stepForward() {
    if (eventIndex >= events.length) return;
    const evt = events[eventIndex++];
    // Update UI: show card, highlight grade, update stats
    renderCardFromEvent(evt);
    highlightGradeButton(evt.grade, () => {
        updateStatsFromEvent(evt);
    });
}
```

### Step 7: Chart rendering

- Charts already use Chart.js with `dailyLog` array
- `dailyLog` = Python's `rows` (same structure: `{day, attended, active, due_processed, ai_gen, ...}`)
- After each day completes in replay, push that day's row to chart data and call `chart.update('none')`

### Step 8: Remove stale JS code

Remove (from v1.3):
- `class RNG` + prototype methods (replaced by Python random)
- `function s0`, `d0`, `clamp`, `retrievability`, `intervalDays`, `updateDifficulty`, `updateStability`, `sampleGrade` (replaced by Python functions)
- `Simulation` constructor + all prototype methods
- `function resetSimulation`, `startAutoPlay`, `autoPlayStep`, `stopAutoPlay` (replaced by replay engine)
- `function render`, `renderGradeButtons`, `renderCharts` (partial — keep charts, remove card rendering)
- `PERSONA`, `PERSONA_GRADE_PROBS`, `PLAN`, `W`, `DSR_FACTOR` constants (all defined in Python now)

### Step 9: Keep JS-only code

Keep:
- `highlightGradeButton` — pure UI, no math
- `updateMonitor` — anti-gaming display, UI only
- Chart.js setup and update functions
- Keyboard shortcuts (1-4 for grades, space for play)
- Slider state persistence (localStorage)
- Seed lock toggle
- CSS styles (unchanged)
- Card display rendering (word, translation, examples — from cardsPool)

---

## Key Design Decisions

### D1: Python code embedding method

| Option | Pro | Con |
|--------|-----|-----|
| A: `<script type="text/python">` | Clean, semantic, Pyodide natively discovers | Harder to debug, mixing Python/JS in same file |
| B: JS template literal string | Full control, explicit loading | Ugly code, escaping issues |
| C: Base64 in `<script>` + decode | No escaping issues, compact | One more step in load |
| **D: External JS wrapper** (NEW) | **Cleanest separation** | Requires extra HTTP request |

**Recommendation:** Option B (JS string) — explicit, debuggable, well-understood pattern.

### D2: Module division — one file or two?

| Option | Pro | Con |
|--------|-----|-----|
| Single `v1.4.htm` | One file offline, simple deployment | Huge file (~3000+ lines) |
| **Two files** (`v1.4.htm` + `v5.4_FSRS_full.py`) | Smaller HTML, Python is editable separately | `fetch()` breaks on `file://` — must embed |

**Recommendation:** Single file. Embed Python as JS string. The HTML is already ~2200 lines; +700 lines of Python = ~2900 lines. Manageable.

### D3: Step-by-step vs batch-only

| Mode | Flow |
|------|------|
| **Step-by-step (▶ ⏭ ⏮)** | Pre-compute all events in one Python call → JS replay engine walks through events array → renders card + grade animation per event |
| **Batch / MAX** | Same pre-compute → run all events instantly → show final charts |
| **Day-by-day** | Could be added: group events by day, advance one day at a time |

**Recommendation:** Pre-compute always, replay always. Step and batch are just different speeds of the same replay.

---

## Verification

After implementation, verify:

1. **Load**: Pyodide loads, Python code executes without error
2. **Run**: Default config (Free, Average, 180 days) produces events array
3. **Step replay**: Each click shows a card, grade highlights, stats update
4. **Auto play**: Events advance at configured speed
5. **Charts**: Final charts match Python standalone output
6. **Seed repeat**: Same seed produces identical event sequence
7. **Offline**: All CDN resources cached (Chart.js, Pyodide) — or document internet requirement

---

## Files to Create

| File | Action |
|------|--------|
| `tools/Fsrs_simulation_v5/fsrs_simulator_v1.4.htm` | **NEW** — target file, embedded Python + Pyodide bridge + replay engine |

---

## Rollback

Delete `v1.4.htm`. The existing `v1.3.htm` (JS-only, with Plan + Attendance fixes) is unaffected.

---

## Acceptance Criteria

1. All Python FSRS-6 features run in browser (attendance, rejection, catch-up, proficiency, debt caps)
2. Results are **bitwise identical** to running `v5.4_FSRS_full.py` standalone with same seed
3. UI interaction (step, play, pause, stop, grade highlighting) works as before
4. Charts render correctly from pre-computed daily data
5. Page loads and runs on `file://` protocol (no server needed; internet required for CDN on first load)
