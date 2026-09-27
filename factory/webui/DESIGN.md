# HamZaban WebUI — Design System

**Path:** `factory/webui/DESIGN.md` **Status:** Living standard, v1.0 — see §7 for how to change it **Scope:** every view, cabin, and tool under `factory/webui/` **Read this before:** adding a screen, a card, a table, or an error path.

---

## 0. What this console is

An **industrial operator cockpit**, not a marketing site and not a SaaS dashboard. The operator works long shifts, scans dense data quickly, and occasionally does something irreversible (deleting a key, waking a supervisor, adopting a model). Every rule below serves one of these five outcomes — if a proposed pattern doesn't serve one of them, it doesn't belong here:

1. **Data clarity first** — the eye finds the value next to its label without traveling.
2. **Bounded space** — nothing stretches or grows without a ceiling; nothing forces a scroll it didn't need to.
3. **Shallow navigation** — one place to find a thing, at most two levels (view → cabin).
4. **Honest feedback** — the UI never implies persistence, success, or safety it hasn't earned.
5. **Debuggable failure** — an error tells the operator what broke, and gives them a way to prove it.

---

## 1. Layout

### 1.1 Breakpoints

One shared set, used everywhere — no per-component breakpoint invention.

| Token | Range | Typical device |
| --- | --- | --- |
| `--bp-mobile` | ≤ 640px | phone |
| `--bp-tablet` | 641–1023px | tablet, split-screen desktop |
| `--bp-desktop` | 1024–1439px | laptop |
| `--bp-wide` | ≥ 1440px | operator monitor |

### 1.2 Containment

- Every form/table region: `max-width: 1200px; margin-inline: auto;`
- No element is allowed to span the full width of a `--bp-wide` monitor edge-to-edge. If content is naturally wide (a table with many columns), it scrolls *inside its own container* (`overflow-x: auto`), never the page.

### 1.3 Card grid

```css
.cards-grid-auto {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
  gap: var(--space-3); /* 12px, see §1.4 */
}
```

Combined with the 1200px container cap, this yields 1 column on mobile, 2 on tablet, 3–4 on desktop/wide — without a single media query. **Do not** hand-write a static `grid-template-columns: repeat(4, 1fr)`; it is the exact anti-pattern this replaces.

### 1.4 Spacing scale

One 4px-based scale. Every margin, padding, and gap in the console must be one of these values — no bespoke pixel numbers in new code.

| Token | Value |
| --- | --- |
| `--space-1` | 4px |
| `--space-2` | 8px |
| `--space-3` | 12px |
| `--space-4` | 16px |
| `--space-5` | 24px |
| `--space-6` | 32px |
| `--space-7` | 48px |

### 1.5 Height ceilings

Any container holding a variable-length list (queue, model explorer, logs) must have a ceiling and its own scrollbar. Pick from this table — don't invent a new number:

| List density | `max-height` |
| --- | --- |
| Compact (rows ≤ 44px, e.g. model list) | 260px |
| Standard (rows with 2 lines of meta) | 320px |
| Log/console output | 380px |

### 1.6 Navigation model

- **Two levels, maximum:** top-level **view** (tab bar) → **cabin** inside a view. No nested menus, no hamburger-behind-hamburger.
- **View memory:** the last-open view is restored on load (already implemented as `restoreViewMemory`) — formalize this as the required pattern for any new top-level view, so operators never re-navigate after a refresh.
- **Master-detail collapse rule:** a 30/70 list-and-detail split (queue, model explorer) applies **only at `--bp-desktop` and above**. Below `--bp-tablet`, stack list-above-detail in the *same* page — do not push to a second screen or add a "back" navigation step. Both stacked sections keep their own height ceiling (§1.5), so stacking never produces one long unbounded page. This is what keeps "master-detail" and "zero navigation complexity" compatible instead of contradictory.

  ```
  Desktop (≥1024px)              Mobile/Tablet (<1024px)
  ┌───────────┬───────────────┐  ┌───────────────────────┐
  │  List 30% │   Detail 70%  │  │  List (capped, scroll)│
  │ (capped)  │   (capped)    │  ├───────────────────────┤
  └───────────┴───────────────┘  │  Detail (capped)      │
                                  └───────────────────────┘
  ```

---

## 2. Typography

- **Body font:** `"Vazirmatn", "Segoe UI", system-ui, sans-serif`
- **Technical font:** `--mono` for every machine identifier (model id, env var name, path)

### 2.1 Type scale

One scale, two densities (desktop / mobile). Don't reach for an arbitrary `font-size` — pick a role from this table.

| Role | Desktop | Mobile | Weight | Line-height |
| --- | --- | --- | --- | --- |
| Section title (`h2`) | 1.1rem | 1rem | 600 | 1.3 |
| Panel title (`.p-title`) | 1rem | 0.95rem | 600 | 1.3 |
| Body / form label | 0.9rem | 0.9rem | 400 | 1.6 |
| Meta / secondary (`.p-meta`) | 0.8rem | 0.8rem | 400 | 1.5 |
| Code token (`.code-token`) | 0.78rem | 0.78rem | 500 | 1.4 |
| Micro / badge | 0.72rem | 0.72rem | 600 | 1.2 |

### 2.2 Bilingual isolation (non-negotiable)

Every machine identifier, model id, env-var name, path, or version string is wrapped:

```html
<bdi dir="ltr" class="code-token">gemini-2.5-flash</bdi>
```

Never `.join(', ')` a list of identifiers into a plain Persian-context string — this breaks bidi rendering (this was a real bug: the raw per-card model list in the provider cards). Every identifier gets its own isolated node, always, even inside a comma-separated summary line.

Numbers in prose and stat cards go through `faNum` (Persian digits). Ports, versions, and anything inside a `.code-token` stay Latin.

---

## 3. Color tokens

### 3.1 Surface hierarchy (dark, four levels — no heavy shadows)

| Token | Hex | Use |
| --- | --- | --- |
| `--bg-base` | `#0d1117` | app background |
| `--bg-surface` | `#161b22` | panels, tables, cabin containers |
| `--bg-elevated` | `#21262d` | cards, inputs, active rows |
| `--bg-overlay` | `#30363d` | dividers, disabled buttons, badge backgrounds |

*This console is dark-only by decision, not by omission — state that explicitly so a future contributor doesn't "fix" it by adding a light theme nobody asked for.*

### 3.2 Semantic accents

| Token | Hex | Meaning | Used for |
| --- | --- | --- | --- |
| `--c-primary` | `#1f6feb` | primary action | confirm, create, adopt-into-form |
| `--c-success` | `#238636` | ready / healthy | key present, model free, supervisor awake |
| `--c-danger` | `#da3633` | destructive / failed | delete actions, network errors |
| `--c-warning` | `#d29922` | caution / retryable | 429 rotation, judge-required, suspended |
| `--c-info` | `#8b949e` | neutral / not-yet-implemented | telemetry columns pending a milestone |

`--c-info` is new versus the previous draft: it exists specifically so an honestly-empty column (§6.4) reads as *intentional* rather than *broken* or *dangerous*.

---

## 4. Components

### 4.1 Buttons

| Variant | Background | Border | When |
| --- | --- | --- | --- |
| Primary | `--c-primary` | none | one per form — the main forward action |
| Secondary / ghost | `--bg-elevated` | 1px `--border-color` | everything else |
| Destructive | `--bg-elevated` | 1px `--c-danger`, text `--c-danger` | delete/remove — always paired with confirm (§7.3) |

States every button must support:

- **Disabled:** `opacity: .5; cursor: not-allowed;` — never just visually implied.
- **Busy:** see §7.2 — this is a state, not a style choice you can skip.
- **Touch target:** minimum 36px height, regardless of variant.

### 4.2 Data row (`.data-row` / `.model-row` / `.provider-cfg-card` row content)

Fixed anatomy, RTL reading order:

```
┌──────────────────────────────────────────────────────────────┐
│ [action button]      [status badges]      [LTR identifier]   │
│  adopt / link          free / match         gemini-2.5-flash │
└──────────────────────────────────────────────────────────────┘
```

- Height: 40–44px, radius 4–6px.
- The identifier is *always* the isolated `<bdi>` node (§2.2), *always* truncated with `text-overflow: ellipsis` and carries a `title` attribute with the full string.
- **Keyboard contract:** if a row is interactive (adoptable, selectable), it must be a real `<button>` or a `<div role="button" tabindex="0">` with `Enter`/`Space` handlers. A bare `<div>` with only a `click` listener fails keyboard users — this is a defect, not a style nit.

### 4.3 Low-frequency / high-risk settings (`<details>` pattern)

One-time infrastructure actions (master key bootstrap) and sensitive credentials (supervisor token) never sit at the same visual weight as daily-use forms.

```html
<details id="operator-secrets">
  <summary>Secure storage & supervisor token</summary>
  <!-- master-card + supervisor-card content -->
</details>
```

- **Default:** closed.
- **Auto-open condition:** only when that section's own config is incomplete (`master.configured === false` or `supervisor.configured === false`). Never auto-open because the page loaded — only because there's something the operator must resolve.

### 4.4 Data tables

- Never allowed to stretch to the container's full width if the content doesn't need it; wrap in `overflow-x: auto` when it does.
- **Honest empty columns:** a column not yet implemented does not render as a wall of `—`. Either the header states the reason (`Latency — arriving in telemetry milestone`, styled `--c-info`) or the column is hidden until it has real data. A silent `—` reads as "broken," a labeled one reads as "not yet," which is the truth.
- Row separators: 1px hairline, `--border-color`. Any Latin content in a cell (paths, identifiers) is isolated per §2.2.

### 4.5 Form inputs

- Any input whose value is **not yet wired to a save endpoint** must be `disabled` and carry a visible note ("suggested default — not saved yet"). An editable-looking input that silently doesn't persist is a trust bug, not a cosmetic one (this was a live issue: the RPM/RPH caps inputs looked editable with no backing `POST`).
- Secret inputs (`type="password"`) get a reveal toggle — a paste-once field with no way to verify what was pasted turns every typo into an opaque failure loop later.

---

## 5. Feedback, errors, and diagnostics

### 5.1 Error anatomy — three parts, always

```html
<div class="error-box" data-code="NET-403">
  <span class="badge error-code">NET · 403</span>
  <p class="error-message">Server did not respond — the tunnel route is blocked.</p>
  <div class="error-actions">
    <button class="btn-retry">Retry</button>
    <button class="btn-copy-log">Copy debug log</button>
  </div>
</div>
```

1. **Code + badge** — a short machine-relatable tag (`NET-403`, `QUOTA-429`, `AUTH-missing-key`), not a bare number.
2. **Plain-language cause** — states what broke, in the interface's voice: no "unfortunately," no apology, no vagueness about what happened.
3. **Action + debug escape hatch** — a retry when retrying makes sense, and *always* a "copy debug log" affordance so an operator can hand the raw error to a developer without screenshotting.

Standard code prefixes:

| Prefix | Meaning |
| --- | --- |
| `NET-xxx` | HTTP/network failure, xxx = status code |
| `AUTH-*` | missing/invalid key or token |
| `QUOTA-429` | rate limit / rotation in progress |
| `VALIDATION-*` | bad input, client-catchable |

### 5.2 Busy state — required above 500ms

Any server-bound action disables its own trigger immediately and restores it in `finally`, regardless of success or failure:

```js
btn.disabled = true;
const prev = btn.textContent;
btn.textContent = 'Waking supervisor…';
try {
  await getJSON(...);
} finally {
  btn.disabled = false;
  btn.textContent = prev;
}
```

No spinner-as-decoration elsewhere; this is the one motion this system asks for, because it answers an operator's own action rather than playing on load.

### 5.3 Destructive-action safeguard

Any delete of a key, token, or otherwise unrecoverable value requires an explicit `confirm()` (or equivalent modal) that states the consequence in one sentence:

> "Delete the {name} key? Its value isn't stored anywhere else — you'll need to paste it again."

### 5.4 Success feedback

A save/delete/create action confirms itself in the same region the operator is looking at (badge or inline note updates immediately) — never rely on the operator noticing a badge change somewhere else on the page.

---

## 6. Accessibility contract

- **Focus-visible:** `outline: 2px solid var(--c-primary); outline-offset: 2px;` on every interactive element — never removed without a replacement.
- **`aria-live="polite"`** on any live count or status line that updates without a page navigation (result counts, supervisor lifecycle badge).
- **Focus retention:** re-rendering a filtered list must not steal focus from the filter input the operator is typing into.
- **Reduced motion:** respect `prefers-reduced-motion`; the busy-state text swap (§5.2) has no animation dependency, so it's unaffected.
- **Minimum touch target:** 36px for buttons, 40px for list rows, everywhere, not just in components marked "tablet-facing."

---

## 7. Governance

This document is **versioned, not frozen**. Token *values* (palette, spacing scale, breakpoints) change rarely and require a one-line changelog entry below. Component *patterns* are expected to evolve — propose a change by referencing the section number in the ticket, not by silently diverging in a new screen.

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | — | Initial standard: layout, tokens, components, feedback, a11y, governance |

### 7.1 Interface review cycle

Every interface ticket proves itself against this document before it merges — no silent divergence, no post-merge alignment. The ticket attaches temporary screenshots of each changed view and cabin, taken at desktop and mobile widths, showing the changed state and its neighboring context. Screenshots are review evidence only: they are never merged into the repository and are removed once sign-off is recorded. Merge requires an explicit UI and UX alignment sign-off that cites the governing section numbers; a change without that sign-off does not land.

### 7.2 Live click-and-interaction testing

Every console button and every cabin is exercised with real clicks against the live interface — no simulated pass, no untested path. Each interaction proves both its success path and its error handling: the error render keeps the three-part anatomy of §5.1, the trigger honors the busy-state rule of §5.2, and destructive actions stay behind their safeguard. Temporary test evidence is cleaned afterwards — no fixture residue, no leftover artifacts, no persisted test values.

---

## 8. Acceptance checklist

Each row is written to be checkable against a specific artifact — a class, a token, or a test — not a subjective impression.

| # | Requirement | How to verify |
| --- | --- | --- |
| 1 | No panel/table exceeds `max-width: 1200px` on a ≥1440px viewport | inspect computed width |
| 2 | Every machine identifier is inside `<bdi dir="ltr" class="code-token">` | grep for raw `.join(` on identifier arrays rendered into Persian-context text |
| 3 | Every interactive element ≥36px height, list rows ≥40px | computed style check |
| 4 | Every variable-length list container has a `max-height` from §1.5 and its own scrollbar | CSS audit |
| 5 | Every error render matches the 3-part anatomy in §5.1, including a code badge | component snapshot test |
| 6 | No table column shows a bare `—` for unimplemented data without a labeled reason | visual/DOM check for `.error-box`/column header text |
| 7 | Every server-bound button implements the busy-state pattern in §5.2 | grep for `disabled = true … finally` around `getJSON`/`fetch` calls |
| 8 | Every destructive action is behind `confirm()` with a consequence sentence | grep for `confirm(` preceding delete calls |
| 9 | Master-detail cabins collapse to stacked layout below `--bp-tablet` per §1.6 | responsive test at 768px and 375px |
| 10 | Filter/search inputs retain focus after their result list re-renders | interaction test |

---

*End of standard. Changes go through §7, not around it.*