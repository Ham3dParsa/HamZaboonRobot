# AUDIT: Turkish Phonetic Validation Failures

**Date:** 2026-07-16<br>
**Scope:** Phonetic normalization/validation failures for Turkish (tr) language in scheduled daily card delivery<br>
**Severity:** High — blocks all scheduled delivery for Turkish users, wastes API quota on retries

---

## Observed Symptoms (from logs)

### Affected users
- `5933399854` — fails all 3 attempts every delivery cycle (repeated failures)
- `7240921063` — intermittent failures, sometimes recovers on retry without avoid-list

### Error pattern
```
ai batch validation kind=daily_batch user_id=5933399854 received=1 accepted=0 validation_rejected=1 duplicates=0 ...
reasons={"Card field 'phonetic' is malformed": 1}
```

### Failed normalization samples (DEBUG logs)
```
Failed to normalize string: hız·lı
Failed to normalize string: hız-lı
Failed to normalize string: mut-lu
Failed to normalize string: Mut-lu | مو-تلو
Failed to normalize string: zor
Failed to normalize string: Zor
Failed to normalize string: genç
Failed to normalize string: sı-cak
Failed to normalize string: Sı·cak
Failed to normalize string: mü-te-ma-di-yen
Failed to normalize string: Mut·lu | موت‌لو
Failed to normalize string: Sı·cak | سی‌جاک
```

### Successful normalizations (for comparison)
```
normalized from dict: {'ipa': '/kwɪk/', 'latin': 'kwik', 'persian': 'کوئیک'}
normalized from dict: {'ipa': 'æmˈbɪɡjuəs', 'latin': 'am-BIG-yoo-uhs', 'persian': 'اَم-بیگیو-اِس'}
normalized from dict: {'ipa': 'ˈiːzi', 'latin': 'EE-zee', 'persian': 'ای-زی'}
```

---

## Root Cause Analysis

### 1. Turkish `phonetic_guidance` in `catalog.py:73`
```python
"tr": LanguageOption(
    "tr",
    "ترکی استانبولی",
    "ترکی استانبولی",
    "...",
    "خوانش لاتین را هجا‌بندی‌شده و با علامت میان‌نقطه ارائه کن؛ تلفظ ترکی معمولاً نزدیک به نوشتار است.",
),
```
**Problem:** The guidance tells the AI to output "syllable-separated Latin reading with middle dot (·)" — a **single string format** like `hız·lı` or `mut-lu`.

### 2. `normalize_phonetic()` in `ai.py:138-166` only accepts TWO formats:
- **Strategy 1 (Label-based):** Multi-line with `ipa:`, `latin:`, `persian:` labels
- **Strategy 2 (Legacy pipe):** Exactly 3 parts separated by `|` (e.g., `IPA|Latin|Persian`)

### 3. Mismatch
The AI for Turkish follows the Turkish-specific guidance and outputs single strings like:
- `hız·lı` (middle dot separator)
- `mut-lu` (hyphen separator)
- `zor` (just the word)
- `Mut-lu | مو-تلو` (pipe but only 2 parts, Persian mixed in)

None of these match Strategy 1 (no labels, not multi-line) or Strategy 2 (not exactly 3 parts, or parts don't map to IPA/Latin/Persian).

### 4. Other languages work because:
- Their `phonetic_guidance` says: "آوانگاری را با IPA، یک خوانش لاتینِ هجا‌بندی‌شده، و یک بازنویسی فارسی ارائه کن." (Provide IPA, syllable-separated Latin, and Persian rewrite)
- The generic prompt schema at `prompts.py:50` says: `"phonetic": "سه خط با برچسب‌های IPA، Latin و Persian؛ هر خط فقط همان رسم‌الخط را داشته باشد"` (Three lines with IPA, Latin, Persian labels)
- So non-Turkish AI outputs the expected 3-line labeled format, which Strategy 1 parses correctly.

---

## Code Locations

| File | Line | Issue |
|------|------|-------|
| `catalog.py` | 73 | Turkish `phonetic_guidance` requests wrong output format |
| `ai.py` | 138-166 | `normalize_phonetic()` doesn't accept Turkish syllable format |
| `prompts.py` | 50, 124, 159, 188, 221 | Generic schema requests 3-line labeled format |
| `prompts.py` | 35-36 | `_phonetic_guidance()` injects language-specific guidance |

---

## Proposed Fixes (choose one)

### Option A: Fix Turkish guidance (minimal, recommended)
Update `catalog.py:73` Turkish `phonetic_guidance` to match the generic 3-line labeled format:
```python
"tr": LanguageOption(
    "tr",
    "ترکی استانبولی",
    "ترکی استانبولی",
    "...",
    "آوانگاری را با IPA، یک خوانش لاتینِ هجا‌بندی‌شده (با میان‌نقطه)، و یک بازنویسی فارسی ارائه کن.",
),
```
This makes Turkish consistent with other languages. The AI will output 3 labeled lines, which Strategy 1 already parses.

### Option B: Extend normalizer for Turkish format
Modify `normalize_phonetic()` in `ai.py` to detect and parse Turkish syllable-separated strings:
- Detect patterns like `hız·lı`, `mut-lu`, `sı-cak`
- Treat as `latin` field, leave `ipa` and `persian` empty
- Risk: Ambiguous — can't distinguish IPA from Latin without labels

### Option C: Make normalizer more lenient (fallback)
If both strategies fail but string is non-empty, treat as `latin` only:
```python
# After Strategy 2 fails:
if raw and not any(c in raw for c in '\n|'):
    return {"ipa": "", "latin": raw, "persian": ""}
```
Risk: Accepts malformed data silently; breaks validation contract.

---

## Recommendation

**Option A** — Fix the Turkish `phonetic_guidance` in `catalog.py`. This:
- Aligns Turkish with all other languages
- Requires no code changes to normalizer/validator
- Preserves the strict validation contract
- One-line change, zero regression risk

The Turkish guidance should explicitly request the 3-line labeled format (IPA, Latin, Persian), with a note that Latin should use middle-dot syllable breaks.

---

## Validation Steps After Fix
1. Run `python -m py_compile ai.py catalog.py prompts.py bot.py`
2. Run `python issues/validate.py check`
3. Trigger a test scheduled delivery for a Turkish user
4. Verify no "Failed to normalize string" or "phonetic is malformed" errors
5. Confirm cards are generated and delivered successfully