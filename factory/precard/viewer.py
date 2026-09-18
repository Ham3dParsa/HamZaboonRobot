"""Precard run viewer: reads one precard run directory (precard.jsonl +
sample order + dropped.log + run.log) and writes one standalone viewer HTML.
Read-only, stdlib only.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from collections import OrderedDict
from pathlib import Path

from factory.precard import __version__ as _LINE_VERSION
from factory.precard.accounting import item_key
from factory.precard.cefr import CEFR_ORDER
from factory.precard.pipeline import DEFAULT_OUT, DEFAULT_SAMPLE
from factory.precard.progress import normalize_stage
from factory.precard.topics import LABELS as _TOPIC_LABELS

_PROPER_RE = re.compile(r"w:([A-Za-z]+):pick-proper-noun/([^\s,)]+)")

_STAGE_IDS = ("s0", "s0b", "s1", "s2", "s3", "s4", "s5")

_LANGS = ("en", "fa")

STRINGS = {
    "en": {
        "brand": "Precard Studio",
        "loading": "Loading...",
        "navigate": "↑↓ or J K navigate",
        "theme": "Theme",
        "search.ph": "Search lemma or key... (press /)",
        "title": "precard viewer — {run}",
        "placeholder": "Select a word from the left list",
        "all.topics": "All Topics",
        "topics.title": ("All Topics counts all lemmas (kept + dropped); "
                         "each topic counts kept-only lemmas"),
        "all.statuses": "All Statuses",
        "kept.only": "Kept Only",
        "dropped.only": "Dropped Only",
        "synthetic": "Needs Synthetic Ex",
        "status.title": ("Dropped lemmas carry no senses: Dropped Only "
                         "combined with a CEFR, topic, style, method, or "
                         "source filter matches nothing"),
        "all.styles": "All Styles",
        "styles.title": ("All Styles counts all lemmas (kept + dropped); "
                         "each style counts kept-only lemmas with any sense "
                         "carrying it"),
        "all.methods": "All Methods",
        "methods.title": ("All Methods counts all lemmas (kept + dropped); "
                          "each method counts kept-only lemmas with any sense "
                          "using it"),
        "all.sources": "All Sources",
        "sources.title": ("All Sources counts all lemmas (kept + dropped); "
                          "each source counts kept-only lemmas with any sense "
                          "from it"),
        "sort.default": "Original Order",
        "sort.alpha": "A → Z",
        "sort.senses": "Senses (High to Low)",
        "sort.cefr": "CEFR Level",
        "sort.title": ("CEFR Level sorts by each kept lemma's lowest sense "
                       "CEFR (filter matches any sense)"),
        "filters.advanced": "Advanced filters",
        "filters.active": "{N} active filters",
        "opt.kept": "{v} ({N} kept lemmas)",
        "pill.all": "ALL: all {N} lemmas (kept + dropped)",
        "pill.level": ("{L}: {N} kept-only lemmas with any sense at {L} "
                       "(pool or sense CEFR; one lemma may count in "
                       "2 levels)"),
        "strip": ("{N} lemmas (all: {K} kept, {D} dropped) · {P} precards "
                  "(kept-only rows) · kept rate {R}% (kept lemmas / "
                  "all lemmas)"),
        "drops.tip": ("drops by reason (dropped.log): {H}: {N} "
                      "dropped lemmas"),
        "drops.none": "no drops recorded",
        "summary": ("Distributions — nine metric groups · lemma-level "
                    "(exists, overlaps noted) vs precard-level (row-level) · "
                    "every number names its unit"),
        "tab.review": "Review",
        "tab.metrics": "Metrics",
        "tab.charts": "Charts",
        "charts.badge_levels": "lemma-level, row-level",
        "charts.donut_cap": "kept of all lemmas",
        "charts.rail_share": "share of precards",
        "charts.untagged": "{N} untagged",
        "charts.pillar_unit": "precard(s)",
        "charts.kpi_kept_meta": "{K} kept, {D} dropped",
        "charts.kpi_fanout_meta": "median {M}, P90 {P}",
        "charts.kpi_mismatch_meta": "{E} of {T} evidenced",
        "charts.kpi_synth_meta": "{N} without real example",
        "charts.others": "others ({N} methods)",
        "charts.bench": "production health:",
        "charts.bench_vals": "mean {M}, median {D}, P90 {P}",
        "charts.pareto_head": "drop pareto (validation stages):",
        "charts.cefr_guide_lemma": "lemma-level (exists)",
        "charts.cefr_guide_precard": "precard (row-level)",
        "charts.cefr_pair": "lemma / precard",
        "charts.s4_head": "topic-vector method shares:",
        "charts.prov_head": "example provenance",
        "charts.prov_total": "{N} rows total",
        "kpi.kept": "Lemma kept rate",
        "kpi.fanout": "Mean precards",
        "kpi.mismatch": "Evidenced mismatch",
        "kpi.synthetic": "Synthetic needed",
        "g1.h": "precards per kept lemma",
        "g1.kv": ("mean {a} precards · median {b} · p90 {c} (over {N} "
                  "kept lemmas)"),
        "g1.buckets": ("1 precard / 2 precards / 3 precards / 4+ precards ; "
                       "precards bucket ; kept lemmas"),
        "g2.h": "kept vs dropped",
        "g2.kv": ("{K} kept lemmas · {D} dropped lemmas · kept rate {R}% "
                  "(kept lemmas / all lemmas)"),
        "g2.th": "drop reason (stage signal) ; dropped lemmas",
        "g3.h": "senses by CEFR",
        "g3.th": "CEFR ; kept lemmas, lemma-level (exists) ; precards, row-level",
        "g3.note": ("lemma counts overlap: {N} kept lemmas sit in 2+ CEFR "
                    "buckets (sense_cefr ∪ pool_level); precard counts are "
                    "row-level and never overlap."),
        "g4.h": "senses by topic",
        "g4.th": "topic ; (same two columns as g3)",
        "g4.note": ("lemma counts overlap: {N} kept lemmas sit in 2+ topic "
                    "buckets; {P} precards carry no topic label."),
        "g4.empty": "no topic labels",
        "g5.h": "synthetic examples needed",
        "g5.kv": ("{P} precards ({PP}% of all precards) · {M} kept lemmas "
                  "({MP}% of kept lemmas)"),
        "g6.h": "pool-vs-sense CEFR mismatch",
        "g6.kv": ("{P} precards ({PP}% of all precards) · {M} kept lemmas "
                  "with ≥1 mismatch"),
        "g6.ev": ("evidenced-only: {E} precards ({EP}% of {D} evidenced "
                  "precards)"),
        "g6.note": ("evidenced = sense_cefr_method other than pool-fallback "
                    "or (unknown) (copied levels match by construction)."),
        "g7.h": "CEFR provenance",
        "g7.th": "CEFR method ; precards, row-level",
        "g7.note": ("row-level sense_cefr_method; pool-fallback levels are "
                    "copied from the pool."),
        "g8.h": "topic s4 paths",
        "g8.th": "s4 path ; precards, row-level",
        "g8.note": "row-level stage_calls.s4_path.",
        "g9.h": "example sourcing",
        "g9.th": "example source ; precards, row-level",
        "g9.note": "row-level example_fallback.",
        "empty.rows": "no rows",
        "count": ("{F} of {M} lemmas (filtered view, all) · {P} precards "
                  "(kept-only)"),
        "count.title": ("Filtered view over all {N} lemmas ({K} kept, "
                        "{D} dropped) and {P} precards (kept-only rows)"),
        "drop.badge": "DROP",
        "cefr.title": "lowest CEFR across senses (filter matches any sense)",
        "badge.title": "{N} precards (kept-only senses)",
        "hero.title": "{N} kept-only precard rows for this lemma",
        "dropped.hero": ("dropped: {reason} / This lemma was dropped during "
                         "precard filtering stages."),
        "topic.title": "topic label + weight 0..1",
        "ex.synth": ("No dataset examples — Flagged for synthetic generation "
                     "({fb})"),
        "ex.none": "No examples available",
        "pipe": "Pipeline:",
        "chip.s2": "{name} disambiguation model",
        "chip.s3": "{name} model",
        "chip.s4": "{name} path: {p}",
        "copy.id": "Copy ID / Copy Sense / Copied!",
        "pool.badge": "Pool level: {p} / pool: {p}",
        "foot.fallback": "fallback:",
        "foot.cefr": "cefr-src:",
        "foot.ipa": "ipa-src:",
        "foot.hash": "Precard Hash ID / hash:",
        "empty.h": "No matching lemmas found",
        "empty.p": "Try adjusting your filters or search query.",
        "empty.drop": ("Dropped lemmas carry no senses, so a CEFR/topic/style/"
                       "method/source filter never matches them. Clear them "
                       "to browse all {N} dropped lemmas."),
        "ban.sample": "sample order skipped (missing {p})",
        "ban.rows": "precard rows skipped (missing {p})",
        "ban.dropped": "dropped list skipped (missing {p})",
        "ban.runlog": "run-log scan skipped (missing {p})",
    },
    "fa": {
        "brand": "استودیو پیش‌کارت",
        "loading": "در حال بارگذاری…",
        "navigate": "‎↑ ↓ یا J K برای جابه‌جایی",
        "theme": "پوسته",
        "search.ph": "جست‌وجوی لِما یا کلید… (کلید /)",
        "title": "نمایشگر پیش‌کارت — {run}",
        "placeholder": "یک واژه را از فهرست کناری انتخاب کنید",
        "all.topics": "همه موضوع‌ها",
        "topics.title": ("«همه موضوع‌ها» همه لِماها را می‌شمارد (نگه‌داشته‌شده + "
                         "حذف‌شده)؛ هر موضوع فقط لِماهای نگه‌داشته‌شده را می‌شمارد"),
        "all.statuses": "همه وضعیت‌ها",
        "kept.only": "فقط نگه‌داشته‌شده‌ها",
        "dropped.only": "فقط حذف‌شده‌ها",
        "synthetic": "نیازمند مثال ساختگی",
        "status.title": ("لِماهای حذف‌شده معنی‌ای ندارند: «فقط حذف‌شده‌ها» همراه فیلتر "
                         "سطح، موضوع، سبک، متد یا منبع هیچ نتیجه‌ای ندارد"),
        "all.styles": "همه سبک‌ها",
        "styles.title": ("«همه سبک‌ها» همه لِماها را می‌شمارد (نگه‌داشته‌شده + "
                         "حذف‌شده)؛ هر سبک فقط لِماهای نگه‌داشته‌شده‌ای را می‌شمارد "
                         "که معنی‌ای با آن دارند"),
        "all.methods": "همه متدها",
        "methods.title": ("«همه متدها» همه لِماها را می‌شمارد (نگه‌داشته‌شده + "
                          "حذف‌شده)؛ هر متد فقط لِماهای نگه‌داشته‌شده‌ای را می‌شمارد "
                          "که معنی‌ای با آن دارند"),
        "all.sources": "همه منبع‌ها",
        "sources.title": ("«همه منبع‌ها» همه لِماها را می‌شمارد (نگه‌داشته‌شده + "
                          "حذف‌شده)؛ هر منبع فقط لِماهای نگه‌داشته‌شده‌ای را می‌شمارد "
                          "که معنی‌ای از آن دارند"),
        "sort.default": "ترتیب اصلی",
        "sort.alpha": "الفبا (A تا Z)",
        "sort.senses": "معنی‌ها (زیاد به کم)",
        "sort.cefr": "سطح CEFR",
        "sort.title": ("«سطح CEFR» بر اساس پایین‌ترین سطح معنی هر لمای نگه‌داشته‌شده "
                       "مرتب می‌کند (فیلتر با هر معنی‌ای منطبق می‌شود)"),
        "filters.advanced": "فیلترهای پیشرفته",
        "filters.active": "{N} فیلتر فعال",
        "opt.kept": "{v} ({N} لمای نگه‌داشته‌شده)",
        "pill.all": "همه: همه {N} لِما (نگه‌داشته‌شده + حذف‌شده)",
        "pill.level": ("{L}: {N} لمای نگه‌داشته‌شده با معنی در {L} (CEFR پول یا "
                       "معنی؛ یک لِما ممکن است در ۲ سطح شمرده شود)"),
        "strip": ("{N} لِما (همه: {K} نگه‌داشته‌شده، {D} حذف‌شده) · {P} پیش‌کارت "
                  "(فقط ردیف‌های نگه‌داشته‌شده) · نرخ ماندگاری {R}٪ (لِماهای "
                  "نگه‌داشته‌شده / همه لِماها)"),
        "drops.tip": ("حذف‌ها بر اساس دلیل (dropped.log): ‏{H}: {N} لمای حذف‌شده"),
        "drops.none": "حذفی ثبت نشده",
        "summary": ("توزیع‌ها — ۹ گروه سنجه · سطح لِما (وجودی، با ذکر هم‌پوشانی‌ها) "
                    "در برابر سطح پیش‌کارت (ردیفی) · هر عدد واحد خود را مشخص می‌کند"),
        "tab.review": "بررسی",
        "tab.metrics": "سنجه‌ها",
        "tab.charts": "نمودارها",
        "charts.badge_levels": "سطح لِما، سطح ردیفی",
        "charts.donut_cap": "از همه لِماها",
        "charts.rail_share": "سهم از پیش‌کارت‌ها",
        "charts.untagged": "{N} بدون برچسب",
        "charts.pillar_unit": "پیش‌کارت",
        "charts.kpi_kept_meta": "{K} نگه\u200cداشته، {D} حذف",
        "charts.kpi_fanout_meta": "میانه {M}، صدک \u06f9\u06f0: {P}",
        "charts.kpi_mismatch_meta": "{E} از {T} مدرک\u200cدار",
        "charts.kpi_synth_meta": "{N} بدون مثال واقعی",
        "charts.others": "سایر ({N} متد)",
        "charts.bench": "سلامت تولید:",
        "charts.bench_vals": "میانگین {M}، میانه {D}، صدک \u06f9\u06f0: {P}",
        "charts.pareto_head": "تحلیل پارتو عوامل حذف:",
        "charts.cefr_guide_lemma": "سطح لِما (وجودی)",
        "charts.cefr_guide_precard": "پیش\u200cکارت (ردیفی)",
        "charts.cefr_pair": "لِما / کارت",
        "charts.s4_head": "سهم متدهای تخصیص موضوعی:",
        "charts.prov_head": "منشأ تولید مثال\u200cها",
        "charts.prov_total": "مجموع {N} ردیف",
        "kpi.kept": "نرخ ماندگاری لماها",
        "kpi.fanout": "میانگین پیش‌کارت",
        "kpi.mismatch": "مغایرت مدرک‌دار",
        "kpi.synthetic": "نیاز به مثال ساختگی",
        "g1.h": "پیش‌کارت به‌ازای هر لمای نگه‌داشته‌شده",
        "g1.kv": ("میانگین {a} پیش‌کارت · میانه {b} · صدک نود {c} (روی {N} لمای "
                  "نگه‌داشته‌شده)"),
        "g1.buckets": ("1 پیش‌کارت / 2 پیش‌کارت / 3 پیش‌کارت / 4+ پیش‌کارت ؛ "
                       "بازه پیش‌کارت ؛ لِماهای نگه‌داشته‌شده"),
        "g2.h": "نگه‌داشته‌شده در برابر حذف‌شده",
        "g2.kv": ("{K} لمای نگه‌داشته‌شده · {D} لمای حذف‌شده · نرخ ماندگاری {R}٪ "
                  "(لِماهای نگه‌داشته‌شده / همه لِماها)"),
        "g2.th": "دلیل حذف (سیگنال مرحله) ؛ لِماهای حذف‌شده",
        "g3.h": "معنی‌ها بر اساس CEFR",
        "g3.th": "CEFR ؛ لِماهای نگه‌داشته‌شده، سطح لِما (وجودی) ؛ پیش‌کارتها، سطح ردیفی",
        "g3.note": ("شمارش لِماها هم‌پوشانی دارد: {N} لمای نگه‌داشته‌شده در ۲+ بازه "
                    "CEFR هستند (sense_cefr ∪ pool_level)؛ شمارش پیش‌کارتها ردیفی "
                    "است و هرگز هم‌پوشانی ندارد."),
        "g4.h": "معنی‌ها بر اساس موضوع",
        "g4.th": "موضوع ؛ (همان دو ستون گروه ۳)",
        "g4.note": ("شمارش لِماها هم‌پوشانی دارد: {N} لمای نگه‌داشته‌شده در ۲+ بازه "
                    "موضوعی هستند؛ {P} پیش‌کارت فاقد برچسب موضوعی‌اند."),
        "g4.empty": "بدون برچسب موضوعی",
        "g5.h": "مثال‌های ساختگی موردنیاز",
        "g5.kv": ("{P} پیش‌کارت ({PP}٪ از همه پیش‌کارتها) · {M} لمای نگه‌داشته‌شده "
                  "({MP}٪ از لِماهای نگه‌داشته‌شده)"),
        "g6.h": "مغایرت CEFR پول و معنی",
        "g6.kv": ("{P} پیش‌کارت ({PP}٪ از همه پیش‌کارتها) · {M} لمای نگه‌داشته‌شده "
                  "با ۱+ مغایرت"),
        "g6.ev": "فقط مدرک‌دارها: {E} پیش‌کارت ({EP}٪ از {D} پیش‌کارت مدرک‌دار)",
        "g6.note": ("مدرک‌دار یعنی wn-single / wn-evp-gloss فقط؛ "
                    "ردیف‌های unmapped و pool-fallback کنار گذاشته می‌شوند."),
        "g7.h": "منشأ سطح CEFR",
        "g7.th": "متد CEFR ؛ پیش‌کارتها، سطح ردیفی",
        "g7.note": ("در سطح ردیف: sense_cefr_method؛ ردیف‌های unmapped "
                    "سطح ندارند (pool_level جداگانه نمایش داده می‌شود)."),
        "g8.h": "مسیرهای s4 موضوع",
        "g8.th": "مسیر s4 ؛ پیش‌کارتها، سطح ردیفی",
        "g8.note": "در سطح ردیف: stage_calls.s4_path.",
        "g9.h": "منشأ مثال‌ها",
        "g9.th": "منبع مثال ؛ پیش‌کارتها، سطح ردیفی",
        "g9.note": "در سطح ردیف: example_fallback.",
        "empty.rows": "ردیفی موجود نیست",
        "count": ("{F} از {M} لِما (نمای فیلترشده، همه) · {P} پیش‌کارت "
                  "(فقط نگه‌داشته‌شده)"),
        "count.title": ("نمای فیلترشده روی همه {N} لِما ({K} نگه‌داشته‌شده، "
                        "{D} حذف‌شده) و {P} پیش‌کارت (فقط ردیف‌های نگه‌داشته‌شده)"),
        "drop.badge": "حذف",
        "cefr.title": "پایین‌ترین CEFR در میان معنی‌ها (فیلتر با هر معنی‌ای منطبق می‌شود)",
        "badge.title": "{N} پیش‌کارت (فقط معنی‌های نگه‌داشته‌شده)",
        "hero.title": "{N} ردیف پیش‌کارت نگه‌داشته‌شده برای این لِما",
        "dropped.hero": "حذف‌شده: {reason} / این لِما در مراحل پالایش پیش‌کارت حذف شد.",
        "topic.title": "برچسب موضوع + وزن 0..1",
        "ex.synth": "فاقد مثال در دیتاست — نشانه‌گذاری‌شده برای تولید ساختگی ({fb})",
        "ex.none": "مثالی موجود نیست",
        "pipe": "خط تولید:",
        "chip.s2": "مدل ابهام‌زدایی {name}",
        "chip.s3": "مدل {name}",
        "chip.s4": "مسیر {name}: ‏{p}",
        "copy.id": "کپی شناسه / کپی معنی / کپی شد!",
        "pool.badge": "سطح پول: {p} / پول: {p}",
        "foot.fallback": "منبع مثال:",
        "foot.cefr": "منبع سطح:",
        "foot.ipa": "منبع آوا:",
        "foot.hash": "شناسه هش پیش‌کارت / هش:",
        "empty.h": "هیچ لمای منطبقی پیدا نشد",
        "empty.p": "فیلترها یا عبارت جست‌وجو را تغییر دهید.",
        "empty.drop": ("لِماهای حذف‌شده معنی‌ای ندارند؛ بنابراین فیلترهای سطح، موضوع، "
                       "سبک، متد یا منبع با آن‌ها منطبق نمی‌شوند. فیلترها را پاک کنید "
                       "تا همه {N} لمای حذف‌شده را ببینید."),
        "ban.sample": "ترتیب نمونه نادیده گرفته شد (فاقد {p})",
        "ban.rows": "ردیف‌های پیش‌کارت نادیده گرفته شد (فاقد {p})",
        "ban.dropped": "فهرست حذف‌شده‌ها نادیده گرفته شد (فاقد {p})",
        "ban.runlog": "پویش لاگ اجرا نادیده گرفته شد (فاقد {p})",
    },
}


def _tr(lang, key, **kwargs):
    text = STRINGS[lang][key]
    if kwargs:
        text = text.format(**kwargs)
    return text


_RTL_CSS = """
[dir="rtl"] .sidebar { border-right: none; border-left: 1px solid var(--border-subtle); }
[dir="rtl"] .lemma-list-item.selected { border-left: none; border-right: 3px solid var(--accent); }
[dir="rtl"] .dist-group th, [dir="rtl"] .dist-group td { text-align: right; }
[dir="rtl"] .dist-group td.num { text-align: left; }
[dir="rtl"] .example-item { border-left: none; border-right: 3px solid var(--border-strong); border-radius: 6px 0 0 6px; }
[dir="rtl"] .search-input { text-align: right; }
[dir="rtl"] .detail-pane { text-align: right; }
[dir="rtl"] .hero-title-group { flex-direction: row; }
[dir="rtl"] .telemetry-box { flex-direction: row; }
[dir="rtl"] .filter-bar { flex-direction: row; }
[dir="rtl"] {
  --font-sans: "Segoe UI", system-ui, sans-serif;
}
[dir="rtl"] .header-strip,
[dir="rtl"] .dist-drawer > summary,
[dir="rtl"] .dist-hint,
[dir="rtl"] .dist-group h3,
[dir="rtl"] .dist-group table,
[dir="rtl"] .dist-note,
[dir="rtl"] .dist-kv,
[dir="rtl"] .stats-badge,
[dir="rtl"] .pill-btn,
[dir="rtl"] .select-filter,
[dir="rtl"] .search-input,
[dir="rtl"] .shortcut-hint,
[dir="rtl"] .telemetry-box,
[dir="rtl"] .no-examples-notice,
[dir="rtl"] .dropped-reason-pill,
[dir="rtl"] .copy-btn,
[dir="rtl"] .viewer-banner {
  font-family: var(--font-sans);
}
"""

_FA_TOGGLE = ('\n      <a class="theme-toggle-btn" '
              'href="precard-viewer.html" style="text-decoration:none;">EN</a>')


def _en_toggle(href):
    return ('\n      <a class="theme-toggle-btn" '
            'href="%s" style="text-decoration:none;">FA</a>' % href)


def _inject_en_toggle(page, href):
    return _sub_once(page, "      </button>\n    </div>\n  </header>",
                     "      </button>%s\n    </div>\n  </header>"
                     % _en_toggle(href))


def _sub_once(page, old, new):
    found = page.find(old)
    if found < 0:
        raise AssertionError(
            "viewer-fa: expected chrome not found: %r" % old[:60])
    return page[:found] + new + page[found + len(old):]


def _header_strip_fa(stats):
    if stats["drops_by_reason"]:
        drops_tip = ("حذف‌ها بر اساس دلیل (dropped.log): ‏"
                     + ", ".join("%s: %d لمای حذف‌شده" % (head, count)
                                 for head, count in stats["drops_by_reason"]))
    else:
        drops_tip = _tr("fa", "drops.none")
    return (
        '<div class="header-strip" id="headerStrip" title="%s">'
        '<span><b>%d</b> لِما '
        '<span class="hs-dim">(همه: <b>%d</b> نگه‌داشته‌شده، '
        '<b>%d</b> حذف‌شده)</span></span>'
        '<span class="hs-sep">\u00b7</span>'
        '<span><b>%d</b> پیش‌کارت '
        '<span class="hs-dim">(فقط ردیف‌های نگه‌داشته‌شده)</span></span>'
        '<span class="hs-sep">\u00b7</span>'
        '<span>نرخ ماندگاری <b>%d٪</b> '
        '<span class="hs-dim">(لِماهای نگه‌داشته‌شده / همه لِماها)</span></span>'
        "</div>" % (
            html.escape(drops_tip, quote=True),
            stats["lemmas_total"], stats["lemmas_kept"],
            stats["lemmas_dropped"], stats["precards_total"],
            stats["kept_rate_pct"]))


def _fa_th(key):
    return [part.strip() for part in STRINGS["fa"][key].split("؛")]


def _dist_drawer_fa(stats):
    ppc = stats["ppc"]
    buckets = [part.strip() for part in
               STRINGS["fa"]["g1.buckets"].split("؛")]
    bucket_labels = [part.strip() for part in buckets[0].split("/")]
    g1 = (
        "<h3>1 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g1.h"])
        + '<p class="dist-kv">%s</p>' % _esc(_tr(
            "fa", "g1.kv", a=ppc["mean"], b=ppc["median"],
            c=ppc["p90"], N=stats["lemmas_kept"]))
        + _dist_table(
            (buckets[1], buckets[2]),
            [(bucket_labels[0], ppc["hist"]["1"]),
             (bucket_labels[1], ppc["hist"]["2"]),
             (bucket_labels[2], ppc["hist"]["3"]),
             (bucket_labels[3], ppc["hist"]["4+"])]))

    g2 = (
        "<h3>2 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g2.h"])
        + '<p class="dist-kv">%s</p>' % _esc(_tr(
            "fa", "g2.kv", K=stats["lemmas_kept"],
            D=stats["lemmas_dropped"], R=stats["kept_rate_pct"]))
        + (_dist_table(
            _fa_th("g2.th"),
            [(head, count) for head, count in stats["drops_by_reason"]])
            if stats["drops_by_reason"]
            else '<p class="dist-note">%s</p>' % _esc(_tr("fa", "drops.none"))))

    levels = _ordered_levels(stats["cefr_lemma"], stats["cefr_precard"])
    g3 = (
        "<h3>3 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g3.h"])
        + _dist_table(
            _fa_th("g3.th"),
            [(lvl, stats["cefr_lemma"].get(lvl, 0),
              stats["cefr_precard"].get(lvl, 0)) for lvl in levels])
        + '<p class="dist-note">%s</p>' % _esc(_tr(
            "fa", "g3.note", N=stats["cefr_lemma_overlap"])))

    labels = sorted(set(stats["topic_lemma"]) | set(stats["topic_precard"]),
                    key=lambda l: (-stats["topic_precard"].get(l, 0), l))
    g4 = (
        "<h3>4 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g4.h"])
        + (_dist_table(
            _fa_th("g4.th"),
            [(label, stats["topic_lemma"].get(label, 0),
              stats["topic_precard"].get(label, 0)) for label in labels])
            if labels
            else '<p class="dist-note">%s</p>' % _esc(_tr("fa", "g4.empty")))
        + '<p class="dist-note">%s</p>' % _esc(_tr(
            "fa", "g4.note", N=stats["topic_lemma_overlap"],
            P=stats["untagged_precards"])))

    synth = stats["synthetic"]
    g5 = (
        "<h3>5 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g5.h"])
        + '<p class="dist-kv">%s</p>' % _esc(_tr(
            "fa", "g5.kv", P=synth["precards"], PP=synth["precards_pct"],
            M=synth["lemmas"], MP=synth["lemmas_pct"])))

    mismatch = stats["mismatch"]
    g6 = (
        "<h3>6 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g6.h"])
        + '<p class="dist-kv">%s</p>' % _esc(_tr(
            "fa", "g6.kv", P=mismatch["precards"],
            PP=mismatch["precards_pct"], M=mismatch["lemmas"]))
        + '<p class="dist-kv">%s</p>' % _esc(_tr(
            "fa", "g6.ev", E=mismatch["evidenced_precards"],
            EP=mismatch["evidenced_pct"],
            D=mismatch["evidenced_denominator"]))
        + '<p class="dist-note">%s</p>' % _esc(_tr("fa", "g6.note")))

    g7 = (
        "<h3>7 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g7.h"])
        + (_dist_table(
            _fa_th("g7.th"),
            [(method, "%d پیش‌کارت (%s٪)" % (
                count, _pct(count, stats["precards_total"])))
             for method, count in stats["cefr_method"].items()])
            if stats["cefr_method"]
            else '<p class="dist-note">%s</p>' % _esc(_tr("fa", "empty.rows")))
        + '<p class="dist-note">%s</p>' % _esc(_tr("fa", "g7.note")))

    g8 = (
        "<h3>8 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g8.h"])
        + (_dist_table(
            _fa_th("g8.th"),
            [(path, "%d پیش‌کارت (%s٪)" % (
                count, _pct(count, stats["precards_total"])))
             for path, count in stats["topic_path"].items()])
            if stats["topic_path"]
            else '<p class="dist-note">%s</p>' % _esc(_tr("fa", "empty.rows")))
        + '<p class="dist-note">%s</p>' % _esc(_tr("fa", "g8.note")))

    g9 = (
        "<h3>9 \u00b7 %s</h3>" % _esc(STRINGS["fa"]["g9.h"])
        + (_dist_table(
            _fa_th("g9.th"),
            [(source, "%d پیش‌کارت (%s٪)" % (
                count, _pct(count, stats["precards_total"])))
             for source, count in stats["example_source"].items()])
            if stats["example_source"]
            else '<p class="dist-note">%s</p>' % _esc(_tr("fa", "empty.rows")))
        + '<p class="dist-note">%s</p>' % _esc(_tr("fa", "g9.note")))

    return (
        '<details class="dist-drawer" id="distDrawer" open>'
        "<summary>%s</summary>" % _esc(_tr("fa", "summary"))
        + '<div class="dist-grid">'
        + "".join('<section class="dist-group">%s</section>' % g
                   for g in (g1, g2, g3, g4, g5, g6, g7, g8, g9))
        + "</div></details>")


def _apply_fa_chrome(page):
    page = _sub_once(page, '<html lang="en" data-theme="dark">',
                     '<html lang="fa" dir="rtl" data-theme="dark">')
    page = _sub_once(
        page, '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700;800&display=swap" rel="stylesheet">')
    page = _sub_once(page, "  padding: 6px 24px;\n}\n</style>",
                     "  padding: 6px 24px;\n}" + _RTL_CSS + "</style>")
    page = _sub_once(page, "<h1>Precard Studio",
                     "<h1>%s" % _tr("fa", "brand"))
    page = _sub_once(
        page, '<span class="stats-badge" id="statsCount">Loading...</span>',
        '<span class="stats-badge" id="statsCount">%s</span>'
        % _tr("fa", "loading"))
    page = _sub_once(
        page,
        "      <div class=\"shortcut-hint\">\n"
        "        <span class=\"kbd-key\">↑</span><span class=\"kbd-key\">↓</span>"
        " or <span class=\"kbd-key\">J</span><span class=\"kbd-key\">K</span>"
        " navigate\n"
        "      </div>",
        "      <div class=\"shortcut-hint\">%s</div>" % _tr("fa", "navigate"))
    page = _sub_once(
        page, "<span id=\"themeIcon\">☀️</span> Theme",
        "<span id=\"themeIcon\">☀️</span> %s" % _tr("fa", "theme"))
    page = _sub_once(page, "      </button>\n    </div>\n  </header>",
                     "      </button>%s\n    </div>\n  </header>" % _FA_TOGGLE)
    page = _sub_once(page, 'placeholder="Search lemma or key... (press /)"',
                     'placeholder="%s"' % html.escape(
                         _tr("fa", "search.ph"), quote=True))
    page = _sub_once(
        page,
        "      title=\"All Topics counts all lemmas (kept + dropped); "
        "each topic counts kept-only lemmas\">\n"
        "      <option value=\"ALL\">All Topics</option>",
        "      title=\"%s\">\n"
        "      <option value=\"ALL\">%s</option>" % (
            html.escape(_tr("fa", "topics.title"), quote=True),
            _tr("fa", "all.topics")))
    page = _sub_once(
        page,
        "      title=\"Dropped lemmas carry no senses: Dropped Only combined "
        "with a CEFR, topic, style, method, or source filter matches "
        "nothing\">\n"
        "      <option value=\"ALL\">All Statuses</option>\n"
        "      <option value=\"KEPT\">Kept Only</option>\n"
        "      <option value=\"DROPPED\">Dropped Only</option>\n"
        "      <option value=\"SYNTHETIC\">Needs Synthetic Ex</option>",
        "      title=\"%s\">\n"
        "      <option value=\"ALL\">%s</option>\n"
        "      <option value=\"KEPT\">%s</option>\n"
        "      <option value=\"DROPPED\">%s</option>\n"
        "      <option value=\"SYNTHETIC\">%s</option>" % (
            html.escape(_tr("fa", "status.title"), quote=True),
            _tr("fa", "all.statuses"), _tr("fa", "kept.only"),
            _tr("fa", "dropped.only"), _tr("fa", "synthetic")))
    page = _sub_once(
        page,
        "      title=\"All Styles counts all lemmas (kept + dropped); each "
        "style counts kept-only lemmas with any sense carrying it\">\n"
        "      <option value=\"ALL\">All Styles</option>",
        "      title=\"%s\">\n"
        "      <option value=\"ALL\">%s</option>" % (
            html.escape(_tr("fa", "styles.title"), quote=True),
            _tr("fa", "all.styles")))
    page = _sub_once(
        page,
        "      title=\"All Methods counts all lemmas (kept + dropped); each "
        "method counts kept-only lemmas with any sense using it\">\n"
        "      <option value=\"ALL\">All Methods</option>",
        "      title=\"%s\">\n"
        "      <option value=\"ALL\">%s</option>" % (
            html.escape(_tr("fa", "methods.title"), quote=True),
            _tr("fa", "all.methods")))
    page = _sub_once(
        page,
        "      title=\"All Sources counts all lemmas (kept + dropped); each "
        "source counts kept-only lemmas with any sense from it\">\n"
        "      <option value=\"ALL\">All Sources</option>",
        "      title=\"%s\">\n"
        "      <option value=\"ALL\">%s</option>" % (
            html.escape(_tr("fa", "sources.title"), quote=True),
            _tr("fa", "all.sources")))
    page = _sub_once(
        page,
        "      title=\"CEFR Level sorts by each kept lemma's lowest sense "
        "CEFR (filter matches any sense)\">\n"
        "      <option value=\"DEFAULT\">Original Order</option>\n"
        "      <option value=\"ALPHA\">A → Z</option>\n"
        "      <option value=\"SENSES_DESC\">Senses (High to Low)</option>\n"
        "      <option value=\"CEFR_ASC\">CEFR Level</option>",
        "      title=\"%s\">\n"
        "      <option value=\"DEFAULT\">%s</option>\n"
        "      <option value=\"ALPHA\">%s</option>\n"
        "      <option value=\"SENSES_DESC\">%s</option>\n"
        "      <option value=\"CEFR_ASC\">%s</option>" % (
            html.escape(_tr("fa", "sort.title"), quote=True),
            _tr("fa", "sort.default"), _tr("fa", "sort.alpha"),
            _tr("fa", "sort.senses"), _tr("fa", "sort.cefr")))
    page = _sub_once(
        page, ">Select a word from the left list</div>",
        ">%s</div>" % _tr("fa", "placeholder"))
    page = _sub_once(page, "<summary><span>Advanced filters</span>",
                     "<summary><span>%s</span>" % _tr("fa", "filters.advanced"))
    return page


_FA_JS_HELPERS = """
const UI_STRINGS = __UI_STRINGS__;
function trFmt(t, params) {
  let s = t || "";
  if (params) {
    Object.keys(params).sort((a, b) => b.length - a.length).forEach(k => {
      s = s.split("{" + k + "}").join(params[k]);
    });
  }
  return s;
}
function tr(key, params) { return trFmt(UI_STRINGS[key], params); }
function trPart(key, i, params) {
  return trFmt((UI_STRINGS[key] || "").split(" / ")[i] || "", params);
}
"""


def _apply_fa_js(page):
    page = _sub_once(page, "const KNOWN_TOPICS =",
                     _FA_JS_HELPERS.replace(
                         "__UI_STRINGS__",
                         _neutralise(json.dumps(STRINGS["fa"],
                                                ensure_ascii=False)))
                     + "const KNOWN_TOPICS =")
    subs = [
        ("if (allPill) allPill.title = `ALL: all "
         "${escapeHtml(STATS.lemmas_total)} lemmas (kept + dropped)`;",
         "if (allPill) allPill.title = tr(\"pill.all\", "
         "{N: escapeHtml(STATS.lemmas_total)});"),
        ("if (btn) btn.title = `${escapeHtml(lvl)}: ${escapeHtml(count)} "
         "kept-only lemmas with any sense at ${escapeHtml(lvl)} (pool or "
         "sense CEFR; one lemma may count in 2 levels)`;",
         "if (btn) btn.title = tr(\"pill.level\", {L: escapeHtml(lvl), "
         "N: escapeHtml(count)});"),
        ("sel.innerHTML = `<option value=\"ALL\">All Topics "
         "(${RAW_LEMMAS.length})</option>`;",
         "sel.innerHTML = `<option value=\"ALL\">${tr(\"opt.kept\", "
         "{v: UI_STRINGS[\"all.topics\"], N: RAW_LEMMAS.length})}</option>`;"),
        ("styleSel.innerHTML = `<option value=\"ALL\">All Styles "
         "(${RAW_LEMMAS.length})</option>`;",
         "styleSel.innerHTML = `<option value=\"ALL\">${tr(\"opt.kept\", "
         "{v: UI_STRINGS[\"all.styles\"], N: RAW_LEMMAS.length})}</option>`;"),
        ("methodSel.innerHTML = `<option value=\"ALL\">All Methods "
         "(${RAW_LEMMAS.length})</option>`;",
         "methodSel.innerHTML = `<option value=\"ALL\">${tr(\"opt.kept\", "
         "{v: UI_STRINGS[\"all.methods\"], N: RAW_LEMMAS.length})}</option>`;"),
        ("sourceSel.innerHTML = `<option value=\"ALL\">All Sources "
         "(${RAW_LEMMAS.length})</option>`;",
         "sourceSel.innerHTML = `<option value=\"ALL\">${tr(\"opt.kept\", "
         "{v: UI_STRINGS[\"all.sources\"], N: RAW_LEMMAS.length})}</option>`;"),
        ("opt.textContent = `${t} (${topicCounts[t]})`;",
         "opt.textContent = tr(\"opt.kept\", {v: t, N: topicCounts[t]});"),
        ("opt.textContent = `${v} (${styleCounts[v]} kept lemmas)`;",
         "opt.textContent = tr(\"opt.kept\", {v: v, N: styleCounts[v]});"),
        ("opt.textContent = `${v} (${methodCounts[v]} kept lemmas)`;",
         "opt.textContent = tr(\"opt.kept\", {v: v, N: methodCounts[v]});"),
        ("opt.textContent = `${v} (${sourceCounts[v]} kept lemmas)`;",
         "opt.textContent = tr(\"opt.kept\", {v: v, N: sourceCounts[v]});"),
        ("opt.title = `${v}: ${styleCounts[v]} kept-only lemmas "
         "with any sense carrying it`;",
         "opt.title = `${v}: ${styleCounts[v]} "
         "لمای نگه‌داشته‌شده با معنی منطبق`;"),
        ("opt.title = `${v}: ${methodCounts[v]} kept-only lemmas "
         "with any sense using it`;",
         "opt.title = `${v}: ${methodCounts[v]} "
         "لمای نگه‌داشته‌شده با معنی منطبق`;"),
        ("opt.title = `${v}: ${sourceCounts[v]} kept-only lemmas "
         "with any sense from it`;",
         "opt.title = `${v}: ${sourceCounts[v]} "
         "لمای نگه‌داشته‌شده با معنی منطبق`;"),
        ("let hint = \"Try adjusting your filters or search query.\";",
         "let hint = UI_STRINGS[\"empty.p\"];"),
        ("hint = `Dropped lemmas carry no senses, so a "
         "CEFR/topic/style/method/source filter never matches them. `",
         "hint = tr(\"empty.drop\", {N: STATS.lemmas_dropped});"),
        ("        + `Clear them to browse all ${STATS.lemmas_dropped} "
         "dropped lemmas.`;", ""),
        ("<h3>No matching lemmas found</h3>",
         "<h3>${UI_STRINGS[\"empty.h\"]}</h3>"),
        ("statsEl.textContent = `${escapeHtml(filteredList.length)} of "
         "${escapeHtml(RAW_LEMMAS.length)} lemmas (filtered view, all) · "
         "${escapeHtml(filteredPrecards)} precards (kept-only)`;",
         "statsEl.textContent = tr(\"count\", "
         "{F: escapeHtml(filteredList.length), "
         "M: escapeHtml(RAW_LEMMAS.length), "
         "P: escapeHtml(filteredPrecards)});"),
        ("statsEl.title = `Filtered view over all "
         "${escapeHtml(STATS.lemmas_total)} lemmas "
         "(${escapeHtml(STATS.lemmas_kept)} kept, "
         "${escapeHtml(STATS.lemmas_dropped)} dropped) and "
         "${escapeHtml(STATS.precards_total)} precards (kept-only rows)`;",
         "statsEl.title = tr(\"count.title\", "
         "{N: escapeHtml(STATS.lemmas_total), "
         "K: escapeHtml(STATS.lemmas_kept), "
         "D: escapeHtml(STATS.lemmas_dropped), "
         "P: escapeHtml(STATS.precards_total)});"),
        ("if (activeCount) activeCount.textContent = "
         "`${nActive} active filters`;",
         "if (activeCount) activeCount.textContent = "
         "tr(\"filters.active\", {N: nActive});"),
        ("border-color:var(--drop-b);\">DROP</span>",
         "border-color:var(--drop-b);\">${UI_STRINGS[\"drop.badge\"]}</span>"),
        ("title=\"lowest CEFR across senses (filter matches any sense)\"",
         "title=\"${UI_STRINGS[\"cefr.title\"]}\""),
        ("title=\"${escapeHtml(nPrecards)} precards (kept-only senses)\""
         ">${escapeHtml(nPrecards)} precards</span>",
         "title=\"${tr(\"badge.title\", {N: escapeHtml(nPrecards)})}\">"
         "${escapeHtml(nPrecards)} پیش‌کارت</span>"),
        ("btn.textContent = \"Copied!\";",
         "btn.textContent = trPart(\"copy.id\", 2);"),
        ("<div class=\"dropped-reason-pill\">dropped: "
         "${escapeHtml(item.drop_reason)}</div>",
         "<div class=\"dropped-reason-pill\">"
         "${trPart(\"dropped.hero\", 0, "
         "{reason: escapeHtml(item.drop_reason)})}</div>"),
        ("<p style=\"margin-top:16px; font-size:13px; "
         "color:var(--text-secondary)\">This lemma was dropped during precard "
         "filtering stages.</p>",
         "<p style=\"margin-top:16px; font-size:13px; "
         "color:var(--text-secondary)\">"
         "${trPart(\"dropped.hero\", 1, "
         "{reason: escapeHtml(item.drop_reason)})}</p>"),
        ("title=\"topic label + weight 0..1\"",
         "title=\"${UI_STRINGS[\"topic.title\"]}\""),
        ("<div class=\"no-examples-notice\">⚠️ No dataset examples — "
         "Flagged for synthetic generation "
         "(${escapeHtml(s.example_fallback)})</div>",
         "<div class=\"no-examples-notice\">⚠️ "
         "${tr(\"ex.synth\", {fb: escapeHtml(s.example_fallback)})}</div>"),
        ("font-style:italic\">No examples available</div>",
         "font-style:italic\">${UI_STRINGS[\"ex.none\"]}</div>"),
        ("title=\"${STAGE_NAMES.s2 || 's2'} disambiguation model\"",
         "title=\"${tr(\"chip.s2\", {name: STAGE_NAMES.s2 || 's2'})}\""),
        ("title=\"${STAGE_NAMES.s3 || 's3'} model\"",
         "title=\"${tr(\"chip.s3\", {name: STAGE_NAMES.s3 || 's3'})}\""),
        ("title=\"${STAGE_NAMES.s4 || 's4'} path: "
         "${escapeHtml(sc.s4_path || '')}\"",
         "title=\"${tr(\"chip.s4\", {name: STAGE_NAMES.s4 || 's4', "
         "p: escapeHtml(sc.s4_path || '')})}\""),
        ("font-weight:bold;\">Pipeline:</span>",
         "font-weight:bold;\">${UI_STRINGS[\"pipe\"]}</span>"),
        ("data-copy-text=\"${escapeHtml(s.pre_card_id)}\">Copy ID</button>",
         "data-copy-text=\"${escapeHtml(s.pre_card_id)}\">"
         "${trPart(\"copy.id\", 0)}</button>"),
        ("data-copy-text=\"${escapeHtml(s.sense_id)}\">Copy Sense</button>",
         "data-copy-text=\"${escapeHtml(s.sense_id)}\">"
         "${trPart(\"copy.id\", 1)}</button>"),
        ("title=\"Pool level: ${escapeHtml(s.pool_level)}\">pool: "
         "${escapeHtml(s.pool_level)}",
         "title=\"${trPart(\"pool.badge\", 0, "
         "{p: escapeHtml(s.pool_level)})}\">"
         "${trPart(\"pool.badge\", 1, {p: escapeHtml(s.pool_level)})}"),
        ("<span>fallback: <code>${escapeHtml(s.example_fallback)}</code></span>",
         "<span>${UI_STRINGS[\"foot.fallback\"]} "
         "<code>${escapeHtml(s.example_fallback)}</code></span>"),
        ("<span>cefr-src: <code>${escapeHtml(s.sense_cefr_method)}</code></span>",
         "<span>${UI_STRINGS[\"foot.cefr\"]} "
         "<code>${escapeHtml(s.sense_cefr_method)}</code></span>"),
        ("<span>ipa-src: <code>${escapeHtml(s.ipa_src || 'dataset')}</code></span>",
         "<span>${UI_STRINGS[\"foot.ipa\"]} "
         "<code>${escapeHtml(s.ipa_src || 'dataset')}</code></span>"),
        ("<span title=\"Precard Hash ID\">hash: "
         "<code>${escapeHtml(s.pre_card_id)}</code></span>",
         "<span title=\"${trPart(\"foot.hash\", 0)}\">"
         "${trPart(\"foot.hash\", 1)} "
         "<code>${escapeHtml(s.pre_card_id)}</code></span>"),
        ("title=\"${escapeHtml(item.senses.length)} kept-only precard rows "
         "for this lemma\">${escapeHtml(item.senses.length)} precards</span>",
         "title=\"${tr(\"hero.title\", "
         "{N: escapeHtml(item.senses.length)})}\">"
         "${escapeHtml(item.senses.length)} پیش‌کارت</span>"),
        ("${item.dropped ? 'style=\"text-decoration:line-through; "
         "opacity:0.6\"' : ''}>${escapeHtml(item.text)}</span>",
         "${item.dropped ? 'style=\"text-decoration:line-through; "
         "opacity:0.6\"' : ''}><bdi>${escapeHtml(item.text)}</bdi></span>"),
        ("<span class=\"item-sub\">${escapeHtml(item.key)}</span>",
         "<span class=\"item-sub\"><bdi>${escapeHtml(item.key)}</bdi></span>"),
    ]
    for old, new in subs:
        page = _sub_once(page, old, new)
    return page

_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", Consolas, monospace;

  /* LIGHT THEME */
  --bg-page: #f1f2f5;
  --bg-surface: #ffffff;
  --bg-surface-hover: #eef0f3;
  --bg-surface-active: #e0e3e8;
  --border-subtle: #d4d7dd;
  --border-strong: #b4b9c1;

  --text-primary: #111317;
  --text-secondary: #4b515d;
  --text-muted: #838a97;

  --accent: #2563eb;
  --accent-soft: #eff6ff;

  --cefr-a: #059669; --cefr-a-bg: #ecfdf5; --cefr-a-b: #a7f3d0;
  --cefr-b: #0284c7; --cefr-b-bg: #f0f9ff; --cefr-b-b: #bae6fd;
  --cefr-c: #7c3aed; --cefr-c-bg: #f5f3ff; --cefr-c-b: #ddd6fe;

  --drop-text: #dc2626; --drop-bg: #fef2f2; --drop-b: #fecaca;
  --warn-text: #d97706; --warn-bg: #fffbeb; --warn-b: #fde68a;
  --info-text: #0284c7; --info-bg: #f0f9ff; --info-b: #bae6fd;

  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 4px 10px rgba(0,0,0,0.08);
}

[data-theme="dark"] {
  /* DARK THEME (Clean Neutral Zinc / Charcoal) */
  color-scheme: dark;
  --bg-page: #121316;
  --bg-surface: #191a1f;
  --bg-surface-hover: #22232a;
  --bg-surface-active: #2b2d35;
  --border-subtle: #292b34;
  --border-strong: #3a3d4a;

  --text-primary: #f3f4f6;
  --text-secondary: #9da3af;
  --text-muted: #6b7280;

  --accent: #38bdf8;
  --accent-soft: #0369a133;

  --cefr-a: #34d399; --cefr-a-bg: #064e3b33; --cefr-a-b: #065f46;
  --cefr-b: #38bdf8; --cefr-b-bg: #0369a133; --cefr-b-b: #075985;
  --cefr-c: #c084fc; --cefr-c-bg: #581c8733; --cefr-c-b: #6b21a8;

  --drop-text: #f87171; --drop-bg: #450a0a33; --drop-b: #7f1d1d;
  --warn-text: #fbbf24; --warn-bg: #451a0333; --warn-b: #78350f;
  --info-text: #38bdf8; --info-bg: #0369a126; --info-b: #075985;

  --shadow-sm: 0 1px 3px rgba(0,0,0,0.5);
  --shadow-md: 0 4px 14px rgba(0,0,0,0.6);
}

/* Themed scrollbars: native <select> popups follow color-scheme for free.
   Sidebar + detail panes keep a 10px hit area with a thin visible thumb.
   Thumb uses --text-muted (not --border-strong) to hold >= 3:1 contrast
   against the pane surface in both themes. No new palette. */
.sidebar, .detail-pane {
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: var(--text-muted) transparent;
}
.sidebar::-webkit-scrollbar, .detail-pane::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
.sidebar::-webkit-scrollbar-track, .detail-pane::-webkit-scrollbar-track {
  background: transparent;
}
.sidebar::-webkit-scrollbar-thumb, .detail-pane::-webkit-scrollbar-thumb {
  background-color: var(--text-muted);
  border: 3px solid transparent;
  background-clip: content-box;
  border-radius: 8px;
}
.sidebar::-webkit-scrollbar-thumb:hover, .detail-pane::-webkit-scrollbar-thumb:hover {
  background-color: var(--text-secondary);
  border: 3px solid transparent;
  background-clip: content-box;
}

/* Header strip: always-visible lemma + precard totals (T4). */
.header-strip {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 6px 24px;
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}
.header-strip b {
  color: var(--text-primary);
}
.hs-dim {
  color: var(--text-muted);
  font-size: 11px;
}
.hs-sep {
  color: var(--border-strong);
}

/* Distributions drawer under the filter bar: nine metric groups. */
.dist-drawer {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 6px 24px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.dist-drawer > summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 12.5px;
  color: var(--text-primary);
  outline: none;
}
.dist-drawer > summary .dist-hint {
  font-weight: 400;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
}
.dist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px;
  padding: 10px 0 6px 0;
  max-height: 38vh;
  overflow-y: auto;
  min-height: 0;
}
.dist-group {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
}
.dist-group h3 {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.dist-group table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: 11px;
}
.dist-group th, .dist-group td {
  text-align: left;
  padding: 2px 6px 2px 0;
  color: var(--text-secondary);
  vertical-align: top;
}
.dist-group th {
  color: var(--text-muted);
  font-weight: 600;
  border-bottom: 1px solid var(--border-subtle);
}
.dist-group td.num {
  text-align: right;
  color: var(--text-primary);
  white-space: nowrap;
}
.dist-note {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
  font-family: var(--font-sans);
}
.dist-kv {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
  margin: 2px 0;
}
.dist-kv b {
  color: var(--text-primary);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background-color: var(--bg-page);
  color: var(--text-primary);
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  line-height: 1.5;
}

/* Guard against ultrawide display drift */
.app-shell {
  max-width: 1680px;
  width: 100%;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-left: 1px solid var(--border-subtle);
  border-right: 1px solid var(--border-subtle);
  box-shadow: 0 0 40px rgba(0,0,0,0.3);
}

.app-header {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
  gap: 16px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}
.brand h1 {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.3px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.brand-pill {
  font-family: var(--font-mono);
  font-size: 10px;
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid var(--accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.stats-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-subtle);
  padding: 3px 8px;
  border-radius: 6px;
  color: var(--text-secondary);
}
.controls {
  display: flex;
  align-items: center;
  gap: 12px;
}
.shortcut-hint {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
.kbd-key {
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 10px;
}
.theme-toggle-btn {
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  padding: 6px 12px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s ease;
}
.theme-toggle-btn:hover {
  background: var(--bg-surface-active);
  border-color: var(--border-strong);
}

.filter-bar {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 10px 24px;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.search-input {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-family: var(--font-sans);
  width: 230px;
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus {
  border-color: var(--accent);
}
.select-filter {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-family: var(--font-sans);
  outline: none;
  cursor: pointer;
}
.filter-pills {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  max-width: 100%;
  min-width: 0;
}
.pill-btn {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  font-family: var(--font-mono);
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.pill-count {
  opacity: 0.65;
  font-size: 10px;
}
.pill-btn.active {
  background: var(--text-primary);
  color: var(--bg-surface);
  border-color: var(--text-primary);
}
.pill-btn.active .pill-count {
  opacity: 0.9;
  font-weight: bold;
}

/* Collapsible advanced filters: desktop stays flat (details dissolves
   into the filter bar, summary hidden — geometry unchanged); phones get
   a full-width disclosure with a 40px summary button. */
.advanced-filters {
  display: contents;
}
.advanced-filters > summary {
  display: none;
}
.active-filter-count {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
}

.split-workspace {
  display: grid;
  grid-template-columns: 320px 1fr;
  flex: 1;
  overflow: hidden;
  min-height: 200px;
}
/* Review tab touch scroll: the pane itself must shrink inside the
   app-shell column (min-height:0) and stack its workspace (flex
   column); the [hidden] guard keeps tab switching working now that
   the pane carries an author display rule. */
#reviewPane {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
#reviewPane[hidden], #metricsPane[hidden], #chartsPane[hidden] {
  display: none;
}

.sidebar {
  background: var(--bg-surface);
  border-right: 1px solid var(--border-subtle);
  overflow-y: auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.lemma-list-item {
  padding: 12px 18px;
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background 0.1s;
}
.lemma-list-item:hover {
  background: var(--bg-surface-hover);
}
.lemma-list-item.selected {
  background: var(--bg-surface-active);
  border-left: 3px solid var(--accent);
}
.item-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.item-word {
  font-weight: 600;
  font-size: 14.5px;
  color: var(--text-primary);
}
.item-sub {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.item-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.detail-pane {
  background: var(--bg-page);
  overflow-y: auto;
  min-height: 0;
  padding: 24px 32px 60px 32px;
}
.detail-content {
  max-width: 960px;
  margin: 0 auto;
}

/* Phone-only stacking + compaction (viewer-responsive T2): single column
   (sidebar over detail), kbd hints hidden, search full-width. Shell stays
   locked (body overflow hidden); panes keep their own internal scroll. */
@media (max-width:640px) {
  .split-workspace {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(180px,38vh) minmax(220px,1fr);
    overflow-y: auto;
  }
  .sidebar {
    max-height: 38vh;
  }
  .detail-pane {
    min-height: 220px;
    padding: 16px 16px 40px;
  }
  .shortcut-hint, .kbd-key {
    display: none;
  }
  .search-input {
    flex: 1 1 100%;
    width: 100%;
  }
  .filter-bar {
    padding: 8px 12px;
    gap: 8px;
  }
  .app-header {
    padding: 10px 12px;
  }
  #chartsPane .kpi-strip {
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  #chartsPane .kpi-value {
    font-size: 18px;
  }
  #chartsPane .kpi-card {
    padding: 8px 10px;
  }
  #chartsPane .charts-panel {
    padding: 16px 14px;
  }
  #chartsPane .charts-donut-wrap {
    flex-direction: column;
    text-align: center;
  }
  #chartsPane .charts-rail-grid {
    grid-template-columns: 1fr;
  }
  .advanced-filters {
    display: block;
    flex: 1 1 100%;
    min-width: 0;
  }
  .advanced-filters > summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex: 1 1 100%;
    min-height: 40px;
    padding: 6px 12px;
    background: var(--bg-page);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    cursor: pointer;
    list-style: none;
  }
  .advanced-filters > summary::-webkit-details-marker {
    display: none;
  }
}

.word-hero {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-sm);
  flex-wrap: wrap;
  gap: 14px;
}
.hero-title-group {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.hero-word {
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.5px;
}
.hero-ipa {
  font-family: var(--font-mono);
  font-size: 16px;
  color: var(--text-muted);
}
.hero-key {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-page);
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
}

.sense-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 20px 22px;
  margin-bottom: 18px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sense-topline {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 12px;
}
.topline-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sense-id-badge {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  border: 1px solid var(--border-strong);
  padding: 2px 8px;
  border-radius: 6px;
}
.cefr-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}
.cefr-A1, .cefr-A2 { background: var(--cefr-a-bg); color: var(--cefr-a); border: 1px solid var(--cefr-a-b); }
.cefr-B1, .cefr-B2 { background: var(--cefr-b-bg); color: var(--cefr-b); border: 1px solid var(--cefr-b-b); }
.cefr-C1, .cefr-C2 { background: var(--cefr-c-bg); color: var(--cefr-c); border: 1px solid var(--cefr-c-b); }
.cefr-none { background: var(--bg-page); color: var(--text-muted); border: 1px solid var(--border-subtle); }

.pos-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  padding: 2px 7px;
  border-radius: 5px;
}
.register-tag {
  font-size: 11px;
  font-style: italic;
  color: var(--warn-text);
  background: var(--warn-bg);
  border: 1px solid var(--warn-b);
  padding: 1px 6px;
  border-radius: 4px;
}

.topics-group {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.topic-pill {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  padding: 2px 8px;
  border-radius: 5px;
  display: inline-flex;
  gap: 5px;
}
.topic-pill b {
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.sense-def {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.55;
}

.examples-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.example-item {
  background: var(--bg-page);
  border-left: 3px solid var(--border-strong);
  padding: 8px 14px;
  border-radius: 0 6px 6px 0;
  font-size: 13.5px;
  color: var(--text-secondary);
  font-style: italic;
}
.no-examples-notice {
  font-size: 12px;
  font-style: italic;
  color: var(--warn-text);
  background: var(--warn-bg);
  border: 1px dashed var(--warn-b);
  padding: 8px 12px;
  border-radius: 6px;
}

.telemetry-box {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
}
.telemetry-stages {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.stage-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
}
.stage-chip.model {
  background: var(--info-bg);
  border-color: var(--info-b);
  color: var(--info-text);
  font-weight: 600;
}
.stage-name {
  color: var(--text-muted);
}
.copy-btn {
  font-family: var(--font-mono);
  font-size: 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.copy-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}

.sense-inspector-footer {
  padding-top: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  flex-wrap: wrap;
  gap: 8px;
}
.inspector-tags {
  display: flex;
  gap: 12px;
}

.dropped-hero {
  background: var(--drop-bg);
  border: 1px solid var(--drop-b);
  border-radius: 12px;
  padding: 40px 24px;
  text-align: center;
  margin-top: 20px;
}
.dropped-hero h2 {
  font-size: 26px;
  color: var(--drop-text);
  margin-bottom: 8px;
}
.dropped-reason-pill {
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--bg-surface);
  border: 1px solid var(--drop-b);
  color: var(--drop-text);
  padding: 6px 14px;
  border-radius: 8px;
  display: inline-block;
  margin-top: 12px;
}
/* Charts tab: KPI strip + server-rendered bars (theme vars + charts tokens). */
/* Charts tokens: oklch accent family, charts scope only (never globals).
   Dark = bright prototype values; light = deep variants. */
#chartsPane {
  --charts-gold: oklch(.55 .137 106.2);
  --charts-mint: oklch(.55 .137 166.2);
  --charts-purple: oklch(.55 .137 286.2);
  --charts-rose: oklch(.55 .12 346.2);
  --charts-bg: oklch(.96 .008 286);
  --charts-border: oklch(.85 .02 286);
  font-family: 'Vazirmatn', "Segoe UI", system-ui, -apple-system, sans-serif;
  overflow-y: auto;
  min-height: 0;
}
[data-theme="dark"] #chartsPane {
  --charts-gold: oklch(.699 .137 106.2);
  --charts-mint: oklch(.699 .137 166.2);
  --charts-purple: oklch(.699 .137 286.2);
  --charts-rose: oklch(.699 .137 346.2);
  --charts-bg: oklch(.130 .020 286.2);
  --charts-border: oklch(.290 .035 286.2);
}
.view-tabs {
  display: flex;
  gap: 6px;
  padding: 8px 24px 0 24px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.view-tab {
  background: transparent;
  border: 1px solid transparent;
  border-bottom: none;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-sans);
  padding: 6px 14px;
  border-radius: 6px 6px 0 0;
  cursor: pointer;
}
.view-tab.active {
  background: var(--bg-page);
  color: var(--text-primary);
  border-color: var(--border-subtle);
}
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}
.kpi-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 14px 16px;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kpi-card::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  inset-inline-end: 0;
  width: 4px;
}
.kpi-card.rail-gold::after { background: var(--charts-gold); }
.kpi-card.rail-mint::after { background: var(--charts-mint); }
.kpi-card.rail-purple::after { background: var(--charts-purple); }
.kpi-card.rail-rose::after { background: var(--charts-rose); }
.kpi-card.rail-gold .kpi-value { color: var(--charts-gold); }
.kpi-card.rail-mint .kpi-value { color: var(--charts-mint); }
.kpi-card.rail-purple .kpi-value { color: var(--charts-purple); }
.kpi-card.rail-rose .kpi-value { color: var(--charts-rose); }
.kpi-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}
.kpi-value {
  font-size: 24px;
  font-weight: 900;
  line-height: 1.1;
  margin: 2px 0;
}
.kpi-sub {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}
.charts-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 4px 16px color-mix(in srgb, black 35%, transparent);
}
.charts-panel-full {
  grid-column: 1 / -1;
}
.charts-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 12px;
}
.charts-panel-head h3 {
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary);
}
.charts-badge {
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  background: var(--bg-page);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  padding: 2px 8px;
  border-radius: 8px;
}
.charts-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
  font-size: 11px;
}
.charts-name {
  min-width: 110px;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
.charts-track {
  flex: 1;
  height: 10px;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  overflow: hidden;
}
.charts-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
}
.charts-fill.drop {
  background: var(--charts-rose);
  border-radius: 99px;
}
.charts-fill.alt {
  background: var(--cefr-b);
}
.charts-num {
  min-width: 28px;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-primary);
}
.charts-legend-line {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}
.charts-section-head {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
}
.charts-guide {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}
.charts-guide .charts-pair {
  margin-inline-start: auto;
  color: var(--text-primary);
  font-weight: 700;
  white-space: nowrap;
}
.charts-donut-wrap {
  display: flex;
  align-items: center;
  gap: 20px;
}
.charts-donut-box {
  position: relative;
  width: 120px;
  height: 120px;
  flex-shrink: 0;
  margin: 0 auto;
}
.charts-donut {
  width: 120px;
  height: 120px;
  transform: rotate(-90deg);
}
.charts-donut-bg {
  fill: none;
  stroke: var(--border-subtle);
  stroke-width: 6;
}
.charts-donut-fg {
  fill: none;
  stroke: var(--charts-gold);
  stroke-width: 6;
}
.charts-donut-fg.drop {
  stroke: var(--charts-rose);
}
.charts-donut-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.charts-donut-label {
  font-size: 22px;
  font-weight: 900;
  line-height: 1;
  color: var(--charts-gold);
}
.charts-donut-cap {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-top: 4px;
}
.charts-keep-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}
.charts-keep-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
.charts-keep-row b {
  color: var(--text-primary);
}
.charts-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-inline-end: 6px;
}
.charts-dot.keep { background: var(--charts-gold); }
.charts-dot.drop { background: var(--charts-rose); }
.charts-dot.lemma { background: var(--charts-mint); }
.charts-dot.precard { background: var(--charts-purple); }
.charts-pareto {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.charts-pareto .charts-row {
  display: grid;
  grid-template-columns: 140px 1fr auto;
  gap: 10px;
  align-items: center;
}
.charts-pareto .charts-name {
  min-width: 0;
  max-width: none;
  direction: ltr;
  text-align: start;
}
.charts-pareto .charts-track {
  border-radius: 99px;
}
.charts-pareto .charts-num {
  min-width: 34px;
  font-weight: 700;
}
.charts-row-others {
  opacity: 0.75;
}
.charts-row-others .charts-fill {
  opacity: 0.65;
}
.charts-scroll {
  max-height: 280px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.charts-cefr-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.charts-cefr-item {
  display: grid;
  grid-template-columns: 40px 1fr auto;
  gap: 10px;
  align-items: center;
}
.charts-cefr-badge {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 800;
  text-align: center;
  padding: 4px 0;
  border-radius: 6px;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
}
.charts-cefr-badge.a { color: var(--cefr-a); border-color: var(--cefr-a-b); }
.charts-cefr-badge.b { color: var(--cefr-b); border-color: var(--cefr-b-b); }
.charts-cefr-badge.c { color: var(--cefr-c); border-color: var(--cefr-c-b); }
.charts-cefr-badge.none { color: var(--text-muted); }
.charts-cefr-bars {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.charts-cefr-bars .charts-track {
  flex: none;
}
.charts-fill.lemma { background: var(--charts-mint); }
.charts-fill.precard { background: var(--charts-purple); }
.charts-rail {
  display: flex;
  height: 24px;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  overflow: hidden;
}
.charts-rail-thin {
  height: 14px;
}
.charts-rail > div { height: 100%; }
.charts-seg0 { background: var(--charts-gold); }
.charts-seg1 { background: var(--charts-mint); }
.charts-seg2 { background: var(--charts-purple); }
.charts-seg3 { background: var(--charts-rose); }
.charts-rail-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.charts-rail-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
.charts-rail-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: ltr;
}
.charts-rail-cap {
  font-size: 11px;
  color: var(--text-muted);
}
.charts-topics {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.charts-topics .charts-row {
  padding: 7px 12px;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}
.charts-topics .charts-name {
  min-width: 0;
  max-width: none;
  direction: ltr;
  text-align: start;
  font-weight: 600;
}
.charts-topics .charts-track {
  border-radius: 99px;
}
.charts-fill.topic {
  background: linear-gradient(90deg, var(--charts-purple), var(--charts-mint));
  border-radius: 99px;
}
.charts-pillars {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.charts-pillar {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 16px 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.charts-pillar-stage {
  height: 80px;
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.charts-pillar-col {
  width: 32px;
  height: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.charts-pillar-fill {
  background: var(--charts-mint);
  border-radius: 6px 6px 0 0;
}
.charts-pillar-fill.max { background: var(--charts-purple); }
.charts-pillar-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}
.charts-pillar-stat {
  font-size: 16px;
  font-weight: 900;
  color: var(--text-primary);
  font-family: var(--font-mono);
}
.charts-pillar-share {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.charts-bench {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  background: color-mix(in srgb, var(--charts-mint) 8%, var(--bg-page));
  border: 1px dashed color-mix(in srgb, var(--charts-mint) 35%, transparent);
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--charts-mint);
}
@media (max-width: 390px) {
  .charts-pillars { grid-template-columns: 1fr; }
  .charts-rail-grid { grid-template-columns: 1fr; }
}
.charts-panel table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: 11px;
}
.charts-panel th, .charts-panel td {
  text-align: left;
  padding: 2px 6px 2px 0;
  color: var(--text-secondary);
  vertical-align: top;
}
.charts-panel th {
  color: var(--text-muted);
  font-weight: 600;
  border-bottom: 1px solid var(--border-subtle);
}
.charts-panel td.num {
  text-align: right;
  color: var(--text-primary);
  white-space: nowrap;
}
#chartsPane {
  padding: 12px 24px 20px 24px;
  background: var(--bg-page);
}
[dir="rtl"] .charts-panel { text-align: right; }
[dir="rtl"] .charts-num { text-align: left; }
[dir="rtl"] .charts-panel th, [dir="rtl"] .charts-panel td { text-align: right; }
[dir="rtl"] .charts-panel td.num { text-align: left; }
.viewer-banner {
  background: var(--warn-bg);
  border: 1px solid var(--warn-b);
  color: var(--warn-text);
  font-size: 12px;
  padding: 6px 24px;
}
</style>
</head>
<body>

<div class="app-shell">
__BANNERS__

  <header class="app-header">
    <div class="brand">
      <h1>Precard Studio <span class="brand-pill">v__LINE_VERSION__</span></h1>
      <span class="stats-badge" id="statsCount">Loading...</span>
    </div>

    <div class="controls">
      <div class="shortcut-hint">
        <span class="kbd-key">↑</span><span class="kbd-key">↓</span> or <span class="kbd-key">J</span><span class="kbd-key">K</span> navigate
      </div>
      <button class="theme-toggle-btn" onclick="toggleTheme()">
        <span id="themeIcon">☀️</span> Theme
      </button>
    </div>
  </header>

__HEADER_STRIP__

__VIEW_TABS__

  <div id="reviewPane">
  <div class="filter-bar">
    <input type="text" id="searchInput" class="search-input" placeholder="Search lemma or key... (press /)" oninput="applyFilters()">

    <details class="advanced-filters" id="advancedFilters" open>
    <summary><span>Advanced filters</span> <span class="active-filter-count" id="activeFilterCount"></span></summary>
    <div class="filter-pills" id="cefrPills">
__CEFR_PILLS__
    </div>

    <select id="topicFilter" class="select-filter" onchange="applyFilters()"
      title="All Topics counts all lemmas (kept + dropped); each topic counts kept-only lemmas">
      <option value="ALL">All Topics</option>
    </select>

    <select id="statusFilter" class="select-filter" onchange="applyFilters()"
      title="Dropped lemmas carry no senses: Dropped Only combined with a CEFR, topic, style, method, or source filter matches nothing">
      <option value="ALL">All Statuses</option>
      <option value="KEPT">Kept Only</option>
      <option value="DROPPED">Dropped Only</option>
      <option value="SYNTHETIC">Needs Synthetic Ex</option>
    </select>

    <select id="registerFilter" class="select-filter" onchange="applyFilters()"
      title="All Styles counts all lemmas (kept + dropped); each style counts kept-only lemmas with any sense carrying it">
      <option value="ALL">All Styles</option>
    </select>

    <select id="methodFilter" class="select-filter" onchange="applyFilters()"
      title="All Methods counts all lemmas (kept + dropped); each method counts kept-only lemmas with any sense using it">
      <option value="ALL">All Methods</option>
    </select>

    <select id="sourceFilter" class="select-filter" onchange="applyFilters()"
      title="All Sources counts all lemmas (kept + dropped); each source counts kept-only lemmas with any sense from it">
      <option value="ALL">All Sources</option>
    </select>

    <select id="sortOrder" class="select-filter" onchange="applyFilters()" style="margin-left:auto;"
      title="CEFR Level sorts by each kept lemma's lowest sense CEFR (filter matches any sense)">
      <option value="DEFAULT">Original Order</option>
      <option value="ALPHA">A → Z</option>
      <option value="SENSES_DESC">Senses (High to Low)</option>
      <option value="CEFR_ASC">CEFR Level</option>
    </select>
    </details>
  </div>

  <div class="split-workspace">
    <aside class="sidebar" id="sidebarList"></aside>
    <main class="detail-pane" id="detailPane">
      <div class="detail-content" id="detailContent">
        <div style="text-align:center; padding: 100px; color:var(--text-muted)">Select a word from the left list</div>
      </div>
    </main>
  </div>
  </div>

  <section id="metricsPane" hidden>
__DIST_DRAWER__
  </section>

  <section id="chartsPane" hidden>
__CHARTS__
  </section>

</div>

<script>
/*PRECARD_VIEWER_DATA_START*/
const RAW_LEMMAS = __VIEWER_DATA__;
/*PRECARD_VIEWER_DATA_END*/
const STATS = __VIEWER_STATS__;
const KNOWN_TOPICS = __KNOWN_TOPICS__;
const STAGE_NAMES = __STAGE_NAMES__;

let filteredList = [];
let selectedIndex = -1;
let currentCefrFilter = "ALL";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function initTopicsAndPillCounts() {
  const topicCounts = {};
  const styleCounts = {};
  const methodCounts = {};
  const sourceCounts = {};
  const cefrCounts = { "ALL": 0, "A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0, "C2": 0 };

  RAW_LEMMAS.forEach(l => {
    cefrCounts["ALL"]++;
    if (!l.dropped) {
      // Find all unique CEFR levels present in this lemma
      const lemmaCefrs = new Set();
      const lemmaTopics = new Set();
      const lemmaStyles = new Set();
      const lemmaMethods = new Set();
      const lemmaSources = new Set();
      l.senses.forEach(s => {
        if (s.sense_cefr) lemmaCefrs.add(s.sense_cefr);
        if (s.pool_level) lemmaCefrs.add(s.pool_level);
        (s.topic_vector || []).forEach(t => lemmaTopics.add(t.label));
        if (s.register) lemmaStyles.add(`register:${s.register}`);
        if (s.lexical_type && s.lexical_type !== "word") lemmaStyles.add(`type:${s.lexical_type}`);
        lemmaMethods.add(s.sense_cefr_method || "(unknown)");
        lemmaSources.add(s.example_fallback || "(unknown)");
      });
      lemmaCefrs.forEach(c => {
        if (cefrCounts[c] !== undefined) cefrCounts[c]++;
      });
      lemmaTopics.forEach(t => {
        topicCounts[t] = (topicCounts[t] || 0) + 1;
      });
      lemmaStyles.forEach(v => {
        styleCounts[v] = (styleCounts[v] || 0) + 1;
      });
      lemmaMethods.forEach(v => {
        methodCounts[v] = (methodCounts[v] || 0) + 1;
      });
      lemmaSources.forEach(v => {
        sourceCounts[v] = (sourceCounts[v] || 0) + 1;
      });
    }
  });

  // Set CEFR pill counts + unit tooltips (label rule: ALL counts all
  // lemmas incl. dropped; each level counts kept-only lemmas, exists
  // semantics, so one lemma may count in 2 levels).
  const allPill = document.querySelector('#cefrPills .pill-btn[data-cefr="ALL"]');
  if (allPill) allPill.title = `ALL: all ${escapeHtml(STATS.lemmas_total)} lemmas (kept + dropped)`;
  for (const [lvl, count] of Object.entries(cefrCounts)) {
    const el = document.getElementById(`count-${lvl}`);
    if (el) el.textContent = `(${count})`;
    if (lvl !== "ALL") {
      const btn = document.querySelector(`#cefrPills .pill-btn[data-cefr="${lvl}"]`);
      if (btn) btn.title = `${escapeHtml(lvl)}: ${escapeHtml(count)} kept-only lemmas with any sense at ${escapeHtml(lvl)} (pool or sense CEFR; one lemma may count in 2 levels)`;
    }
  }

  // Populate Topics dropdown with counts
  const sel = document.getElementById("topicFilter");
  // ALL is a lemma count (total incl. dropped), matching CEFR ALL;
  // per-topic rows count kept lemmas (dropped never match a topic).
  sel.innerHTML = `<option value="ALL">All Topics (${RAW_LEMMAS.length})</option>`;
  KNOWN_TOPICS.filter(t => topicCounts[t] !== undefined).concat(Object.keys(topicCounts).filter(t => !KNOWN_TOPICS.includes(t)).sort()).forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = `${t} (${topicCounts[t]})`;
    sel.appendChild(opt);
  });

  // Populate Styles dropdown with kept-only lemma counts (exists semantics).
  // Keys carry their field origin (register:informal vs type:colloquial)
  // so one combined select stays unambiguous.
  const styleSel = document.getElementById("registerFilter");
  styleSel.innerHTML = `<option value="ALL">All Styles (${RAW_LEMMAS.length})</option>`;
  Object.keys(styleCounts).sort().forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = `${v} (${styleCounts[v]} kept lemmas)`;
    opt.title = `${v}: ${styleCounts[v]} kept-only lemmas with any sense carrying it`;
    styleSel.appendChild(opt);
  });

  // Populate Method + Source dropdowns (kept-only, exists semantics)
  const methodSel = document.getElementById("methodFilter");
  methodSel.innerHTML = `<option value="ALL">All Methods (${RAW_LEMMAS.length})</option>`;
  Object.keys(methodCounts).sort().forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = `${v} (${methodCounts[v]} kept lemmas)`;
    opt.title = `${v}: ${methodCounts[v]} kept-only lemmas with any sense using it`;
    methodSel.appendChild(opt);
  });
  const sourceSel = document.getElementById("sourceFilter");
  sourceSel.innerHTML = `<option value="ALL">All Sources (${RAW_LEMMAS.length})</option>`;
  Object.keys(sourceCounts).sort().forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = `${v} (${sourceCounts[v]} kept lemmas)`;
    opt.title = `${v}: ${sourceCounts[v]} kept-only lemmas with any sense from it`;
    sourceSel.appendChild(opt);
  });
}

function filterCefr(level) {
  currentCefrFilter = level;
  document.querySelectorAll("#cefrPills .pill-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-cefr") === level);
  });
  applyFilters();
}

const CEFR_RANK = { "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6 };

// Lowest CEFR across all senses (pool fallback), consistent with the
// any-sense CEFR filter. senses[0]-only display/sort drifted from it.
function lowestCefrOf(item) {
  let best = null;
  let bestRank = 99;
  (item.senses || []).forEach(s => {
    [s.sense_cefr, s.pool_level, item.pool_level].forEach(lvl => {
      const r = CEFR_RANK[lvl] || 99;
      if (r < bestRank) { bestRank = r; best = lvl; }
    });
  });
  return best || item.pool_level || "—";
}

function applyFilters() {
  const q = document.getElementById("searchInput").value.trim().toLowerCase();
  const topic = document.getElementById("topicFilter").value;
  const status = document.getElementById("statusFilter").value;
  const style = document.getElementById("registerFilter").value;
  const method = document.getElementById("methodFilter").value;
  const source = document.getElementById("sourceFilter").value;
  const sort = document.getElementById("sortOrder").value;

  const nActive = (currentCefrFilter !== "ALL" ? 1 : 0) + [topic, status, style, method, source].filter(v => v !== "ALL").length;
  const activeCount = document.getElementById("activeFilterCount");
  if (activeCount) activeCount.textContent = `${nActive} active filters`;

  filteredList = RAW_LEMMAS.filter(item => {
    if (q && !item.text.toLowerCase().includes(q) && !item.key.toLowerCase().includes(q)) {
      return false;
    }
    if (status === "KEPT" && item.dropped) return false;
    if (status === "DROPPED" && !item.dropped) return false;
    if (status === "SYNTHETIC") {
      const needsSynth = item.senses.some(s => s.example_synthetic_needed);
      if (!needsSynth) return false;
    }
    if (currentCefrFilter !== "ALL") {
      if (item.dropped) return false;
      const hasCefr = item.senses.some(s => s.sense_cefr === currentCefrFilter || s.pool_level === currentCefrFilter);
      if (!hasCefr) return false;
    }
    if (topic !== "ALL") {
      if (item.dropped) return false;
      const hasTopic = item.senses.some(s => (s.topic_vector || []).some(t => t.label === topic));
      if (!hasTopic) return false;
    }
    if (style !== "ALL") {
      if (item.dropped) return false;
      const cut = style.indexOf(":");
      const field = style.slice(0, cut);
      const want = style.slice(cut + 1);
      const hasStyle = item.senses.some(s => field === "register" ? s.register === want : s.lexical_type === want);
      if (!hasStyle) return false;
    }
    if (method !== "ALL") {
      if (item.dropped) return false;
      const hasMethod = item.senses.some(s => (s.sense_cefr_method || "(unknown)") === method);
      if (!hasMethod) return false;
    }
    if (source !== "ALL") {
      if (item.dropped) return false;
      const hasSource = item.senses.some(s => (s.example_fallback || "(unknown)") === source);
      if (!hasSource) return false;
    }
    return true;
  });

  if (sort === "ALPHA") {
    filteredList.sort((a, b) => a.text.localeCompare(b.text));
  } else if (sort === "SENSES_DESC") {
    filteredList.sort((a, b) => b.senses.length - a.senses.length);
  } else if (sort === "CEFR_ASC") {
    filteredList.sort((a, b) => {
      return (CEFR_RANK[lowestCefrOf(a)] || 99) - (CEFR_RANK[lowestCefrOf(b)] || 99);
    });
  }

  renderSidebar();
  if (filteredList.length > 0) {
    selectLemma(0);
  } else {
    let hint = "Try adjusting your filters or search query.";
    if (status === "DROPPED" && (currentCefrFilter !== "ALL" || topic !== "ALL" || style !== "ALL" || method !== "ALL" || source !== "ALL")) {
      hint = `Dropped lemmas carry no senses, so a CEFR/topic/style/method/source filter never matches them. `
        + `Clear them to browse all ${STATS.lemmas_dropped} dropped lemmas.`;
    }
    document.getElementById("detailContent").innerHTML = `
      <div style="text-align:center; padding: 80px; color:var(--text-muted)">
        <h3>No matching lemmas found</h3>
        <p style="margin-top:6px; font-size:13px;">${escapeHtml(hint)}</p>
      </div>`;
  }
}

function renderSidebar() {
  const sidebar = document.getElementById("sidebarList");
  sidebar.innerHTML = "";
  const filteredPrecards = filteredList.reduce((n, item) => n + (item.dropped ? 0 : item.senses.length), 0);
  const statsEl = document.getElementById("statsCount");
  statsEl.textContent = `${escapeHtml(filteredList.length)} of ${escapeHtml(RAW_LEMMAS.length)} lemmas (filtered view, all) · ${escapeHtml(filteredPrecards)} precards (kept-only)`;
  statsEl.title = `Filtered view over all ${escapeHtml(STATS.lemmas_total)} lemmas (${escapeHtml(STATS.lemmas_kept)} kept, ${escapeHtml(STATS.lemmas_dropped)} dropped) and ${escapeHtml(STATS.precards_total)} precards (kept-only rows)`;

  filteredList.forEach((item, idx) => {
    const el = document.createElement("div");
    el.className = `lemma-list-item ${idx === selectedIndex ? "selected" : ""}`;
    el.id = `lemma-item-${idx}`;
    el.onclick = () => selectLemma(idx);

    let rightBadge = "";
    if (item.dropped) {
      rightBadge = `<span class="stats-badge" style="color:var(--drop-text); border-color:var(--drop-b);">DROP</span>`;
    } else {
      const lemmaCefr = lowestCefrOf(item);
      const nPrecards = item.senses.length;
      rightBadge = `
        <span class="cefr-tag cefr-${escapeHtml(lemmaCefr)}" title="lowest CEFR across senses (filter matches any sense)">${escapeHtml(lemmaCefr)}</span>
        <span class="stats-badge" title="${escapeHtml(nPrecards)} precards (kept-only senses)">${escapeHtml(nPrecards)} precards</span>
      `;
    }

    el.innerHTML = `
      <div class="item-left">
        <span class="item-word" ${item.dropped ? 'style="text-decoration:line-through; opacity:0.6"' : ''}>${escapeHtml(item.text)}</span>
        <span class="item-sub">${escapeHtml(item.key)}</span>
      </div>
      <div class="item-right">${rightBadge}</div>
    `;
    sidebar.appendChild(el);
  });
}

function copyText(txt, btn) {
  navigator.clipboard.writeText(txt).then(() => {
    const old = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = old; }, 1500);
  });
}

document.getElementById("detailContent").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-copy-text]");
  if (btn) copyText(btn.getAttribute("data-copy-text"), btn);
});

function selectLemma(index) {
  if (index < 0 || index >= filteredList.length) return;
  selectedIndex = index;
  document.querySelectorAll(".lemma-list-item").forEach((el, i) => {
    el.classList.toggle("selected", i === index);
  });

  const activeEl = document.getElementById(`lemma-item-${index}`);
  if (activeEl) {
    activeEl.scrollIntoView({ block: "nearest" });
  }

  const item = filteredList[index];
  const container = document.getElementById("detailContent");
  if (!item) return;

  document.getElementById("detailPane").scrollTop = 0;

  if (item.dropped) {
    container.innerHTML = `
      <div class="dropped-hero">
        <h2>${escapeHtml(item.text)}</h2>
        <div style="color:var(--text-muted); font-family:var(--font-mono); margin-top:4px;">${escapeHtml(item.key)}</div>
        <div class="dropped-reason-pill">dropped: ${escapeHtml(item.drop_reason)}</div>
        <p style="margin-top:16px; font-size:13px; color:var(--text-secondary)">This lemma was dropped during precard filtering stages.</p>
      </div>
    `;
    return;
  }

  const firstSense = item.senses[0] || {};
  const heroIpa = firstSense.ipa ? `<span class="hero-ipa">${escapeHtml(firstSense.ipa)}</span>` : "";

  let sensesHtml = item.senses.map(s => {
    const posList = (s.pos || []).map(p => `<span class="pos-tag">${escapeHtml(p)}</span>`).join("");

    let regHtml = "";
    if (s.register && s.register !== "neutral") {
      regHtml += `<span class="register-tag">${escapeHtml(s.register)}</span>`;
    }
    if (s.lexical_type && s.lexical_type !== "word") {
      regHtml += `<span class="register-tag">${escapeHtml(s.lexical_type)}</span>`;
    }

    const topicsHtml = (s.topic_vector || []).map(t => `
      <span class="topic-pill" title="topic label + weight 0..1">${escapeHtml(t.label)} <b>${t.weight.toFixed(2)}</b></span>
    `).join("");

    const exs = s.dataset_examples || [];
    let exsHtml = "";
    if (exs.length > 0) {
      exsHtml = `<div class="examples-block">` + exs.map(e => `<div class="example-item">“${escapeHtml(e)}”</div>`).join("") + `</div>`;
    } else if (s.example_synthetic_needed) {
      exsHtml = `<div class="no-examples-notice">⚠️ No dataset examples — Flagged for synthetic generation (${escapeHtml(s.example_fallback)})</div>`;
    } else {
      exsHtml = `<div style="font-size:12px; color:var(--text-muted); font-style:italic">No examples available</div>`;
    }

    // Telemetry & Stage Calls Pipeline
    const sc = s.stage_calls || {};
    const s2Chip = sc.s2 ? `<span class="stage-chip model" title="${STAGE_NAMES.s2 || 's2'} disambiguation model"><span class="stage-name">s2:</span> ${escapeHtml(sc.s2)}</span>` : "";
    const s3Chip = sc.s3 ? `<span class="stage-chip model" title="${STAGE_NAMES.s3 || 's3'} model"><span class="stage-name">s3:</span> ${escapeHtml(sc.s3)}</span>` : "";
    const s4Chip = sc.s4 ? `<span class="stage-chip" title="${STAGE_NAMES.s4 || 's4'} path: ${escapeHtml(sc.s4_path || '')}"><span class="stage-name">s4:</span> ${escapeHtml(sc.s4)}</span>` : "";
    const s5Chip = sc.s5 ? `<span class="stage-chip"><span class="stage-name">s5:</span> ${escapeHtml(sc.s5)}</span>` : "";

    return `
      <article class="sense-card">
        <!-- ROW 1: SenseID | CEFR | POS | Topic -->
        <div class="sense-topline">
          <div class="topline-left">
            <span class="sense-id-badge">${escapeHtml(s.sense_id)}</span>
            ${(s.sense_cefr ? `<span class="cefr-tag cefr-${escapeHtml(s.sense_cefr)}">${escapeHtml(s.sense_cefr)}</span>` : `<span class="cefr-tag cefr-none" title="unmapped sense CEFR">—</span>`)}
            ${s.pool_level !== s.sense_cefr ? `<span class="stats-badge" title="Pool level: ${escapeHtml(s.pool_level)}">pool: ${escapeHtml(s.pool_level)}</span>` : ""}
            ${posList}
            ${regHtml}
          </div>
          <div class="topics-group">
            ${topicsHtml}
          </div>
        </div>

        <!-- ROW 2: Definition -->
        <div class="sense-def">${escapeHtml(s.en_def)}</div>

        <!-- ROW 3: Examples -->
        ${exsHtml}

        <!-- ROW 4: Telemetry Pipeline Breakdown -->
        <div class="telemetry-box">
          <div class="telemetry-stages">
            <span style="color:var(--text-muted); font-family:var(--font-mono); font-weight:bold;">Pipeline:</span>
            ${s2Chip}
            ${s3Chip}
            ${s4Chip}
            ${s5Chip}
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            <button class="copy-btn" data-copy-text="${escapeHtml(s.pre_card_id)}">Copy ID</button>
            <button class="copy-btn" data-copy-text="${escapeHtml(s.sense_id)}">Copy Sense</button>
          </div>
        </div>

        <!-- Technical Details Footer -->
        <footer class="sense-inspector-footer">
          <div class="inspector-tags">
            <span>fallback: <code>${escapeHtml(s.example_fallback)}</code></span>
            <span>cefr-src: <code>${escapeHtml(s.sense_cefr_method)}</code></span>
            <span>ipa-src: <code>${escapeHtml(s.ipa_src || 'dataset')}</code></span>
          </div>
          <span title="Precard Hash ID">hash: <code>${escapeHtml(s.pre_card_id)}</code></span>
        </footer>
      </article>
    `;
  }).join("");

  container.innerHTML = `
    <div class="word-hero">
      <div class="hero-title-group">
        <span class="hero-word">${escapeHtml(item.text)}</span>
        ${heroIpa}
        <span class="hero-key">${escapeHtml(item.key)}</span>
      </div>
      <span class="stats-badge" style="font-size:12px;" title="${escapeHtml(item.senses.length)} kept-only precard rows for this lemma">${escapeHtml(item.senses.length)} precards</span>
    </div>
    <div class="senses-list">
      ${sensesHtml}
    </div>
  `;
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  document.getElementById("themeIcon").textContent = next === "dark" ? "🌙" : "☀️";
}

function switchView(view) {
  const showReview = view === "review";
  const showMetrics = view === "metrics";
  const showCharts = view === "charts";
  document.getElementById("reviewPane").hidden = !showReview;
  document.getElementById("metricsPane").hidden = !showMetrics;
  document.getElementById("chartsPane").hidden = !showCharts;
  document.getElementById("tabReview").classList.toggle("active", showReview);
  document.getElementById("tabMetrics").classList.toggle("active", showMetrics);
  document.getElementById("tabCharts").classList.toggle("active", showCharts);
  document.getElementById("tabReview").setAttribute("aria-selected", String(showReview));
  document.getElementById("tabMetrics").setAttribute("aria-selected", String(showMetrics));
  document.getElementById("tabCharts").setAttribute("aria-selected", String(showCharts));
}

// Global Keyboard Navigation
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.key === "ArrowDown" || e.key === "j" || e.key === "J") {
    e.preventDefault();
    if (selectedIndex < filteredList.length - 1) selectLemma(selectedIndex + 1);
  } else if (e.key === "ArrowUp" || e.key === "k" || e.key === "K") {
    e.preventDefault();
    if (selectedIndex > 0) selectLemma(selectedIndex - 1);
  } else if (e.key === "/") {
    e.preventDefault();
    document.getElementById("searchInput").focus();
  }
});

// Narrow viewports start with advanced filters collapsed (markup
// carries `open` so desktop renders flat); wide restores it.
const advFilters = document.getElementById("advancedFilters");
const advMq = window.matchMedia("(max-width: 640px)");
function syncAdvFilters() { if (advMq.matches) advFilters.removeAttribute("open"); else advFilters.setAttribute("open", ""); }
advMq.addEventListener("change", syncAdvFilters);
syncAdvFilters();

// Initial Run
initTopicsAndPillCounts();
applyFilters();

</script>
</body>
</html>
"""


def _esc(value):
    return html.escape(str(value), quote=False)


def _default_run_dir():
    return Path(DEFAULT_OUT).parent


def _load_order(sample_path, limit):
    order = []
    if not sample_path:
        return order
    try:
        raw = Path(sample_path).read_text(encoding="utf-8")
    except OSError:
        return order
    try:
        sample = json.loads(raw)
    except ValueError:
        return order
    try:
        items = sample if isinstance(sample, list) else sample.get("items", [])
    except AttributeError:
        return order
    if isinstance(items, dict):
        items = items.get("items", [])
    try:
        seq = list(items) if not limit else list(items)[:limit]
    except TypeError:
        return order
    for item in seq:
        try:
            key = item_key(item)
        except Exception:
            key = item.get("key") if isinstance(item, dict) else None
        if key and key not in order:
            order.append(key)
    return order


def _load_rows(precard_path):
    rows = OrderedDict()
    if not precard_path:
        return rows
    try:
        handle = open(precard_path, encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            key = rec.get("key") if isinstance(rec, dict) else None
            if not key:
                continue
            rows.setdefault(key, []).append(rec)
    return rows


_ENTRY_SUFFIX_RE = re.compile(r"\s\[entry=([^\]]+)\]\s*$")


def _split_entry_suffix(reason):
    """Strip a trailing " [entry=BAND]" (pipeline #730); (reason, band|None)."""
    text = str(reason or "")
    match = _ENTRY_SUFFIX_RE.search(text)
    if not match:
        return text.strip(), None
    band = match.group(1).strip() or None
    return text[:match.start()].rstrip(), band


def _drop_reason(value):
    """Reason string from a dropped-map value (dict {reason, entry_band}
    or legacy plain string; legacy strings are suffix-stripped too)."""
    if isinstance(value, dict):
        return value.get("reason") or ""
    reason, _band = _split_entry_suffix(value)
    return reason


def _drop_band(value):
    """Entry band from a dropped-map value (None for legacy lines)."""
    if isinstance(value, dict):
        return value.get("entry_band")
    _reason, band = _split_entry_suffix(value)
    return band


def _load_dropped(dropped_path, run_log_path=None):
    """Dropped map: key -> {"reason", "entry_band"}.

    The " [entry=BAND]" suffix is stripped at the reader so reason
    grouping (_reason_head) never sees it; the band rides along as a
    separate field for the later viewer pass (lemmas_data entry_band).
    Legacy suffix-less lines yield entry_band None.
    """
    dropped = OrderedDict()
    if dropped_path:
        try:
            text = Path(dropped_path).read_text(encoding="utf-8")
        except OSError:
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("===") or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) >= 3:
                reason, band = _split_entry_suffix(
                    ":".join(parts[2:]).strip())
                dropped.setdefault(parts[0] + ":" + parts[1],
                                   {"reason": reason, "entry_band": band})
    if run_log_path:
        try:
            log_text = Path(run_log_path).read_text(encoding="utf-8")
        except OSError:
            log_text = ""
        for match in _PROPER_RE.finditer(log_text):
            dropped.setdefault("w:" + match.group(1),
                               {"reason": "pick-proper-noun/" + match.group(2),
                                "entry_band": None})
    return dropped


def _cefr_pills():
    lines = ["      <button class=\"pill-btn active\" data-cefr=\"ALL\" "
             "onclick=\"filterCefr('ALL')\">ALL "
             "<span class=\"pill-count\" id=\"count-ALL\"></span></button>"]
    for level in CEFR_ORDER:
        lines.append("      <button class=\"pill-btn\" data-cefr=\"%s\" "
                     "onclick=\"filterCefr('%s')\">%s "
                     "<span class=\"pill-count\" id=\"count-%s\"></span></button>"
                     % (level, level, level, level))
    return "\n".join(lines)


def _banners(warnings):
    return "\n".join("    <div class=\"viewer-banner\">%s</div>" % _esc(w)
                      for w in warnings)


def _neutralise(text):
    return text.replace("</", "<\\/")


_CEFR_LEVELS = tuple(CEFR_ORDER) + ("\u2014",)
_MISSING = "\u2014"
_UNKNOWN_METHOD = "(unknown)"


def _reason_head(reason):
    head = (reason or "").split(":")[0].split("/")[0].strip()
    return head or "(unknown)"


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def _median(values):
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _p90(values):
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def _sort_dist(dist):
    return dict(sorted(dist.items(), key=lambda kv: (-kv[1], kv[0])))


def _compute_stats(rows, dropped_map):
    """Distribution metrics from kept precard rows + drop reasons.

    Lemma-level counts use exists semantics (one lemma in two buckets
    counts in both, overlaps tallied separately); precard-level counts
    are row-level. Stdlib only; single dict embedded as STATS.
    """
    kept_keys = [k for k in rows]
    dropped_keys = [k for k in dropped_map if k not in rows]
    n_kept = len(kept_keys)
    n_dropped = len(dropped_keys)
    n_rows = sum(len(v) for v in rows.values())

    drops = {}
    for key in dropped_keys:
        head = _reason_head(_drop_reason(dropped_map[key]))
        drops[head] = drops.get(head, 0) + 1
    drops_by_reason = sorted(drops.items(), key=lambda kv: (-kv[1], kv[0]))

    per_lemma = [len(rows[k]) for k in kept_keys]
    hist = {"1": 0, "2": 0, "3": 0, "4+": 0}
    for n in per_lemma:
        hist["4+" if n >= 4 else str(n)] += 1

    cefr_lemma = {lvl: 0 for lvl in _CEFR_LEVELS}
    cefr_precard = {lvl: 0 for lvl in _CEFR_LEVELS}
    cefr_overlap = 0
    topic_lemma = {}
    topic_precard = {}
    topic_overlap = 0
    untagged_precards = 0
    synth_precards = 0
    synth_lemmas = 0
    mismatch_precards = 0
    mismatch_lemmas = 0
    method_precard = {}
    path_precard = {}
    source_precard = {}
    evidenced_rows = 0
    evidenced_mismatch = 0

    for key in kept_keys:
        lemma_cefrs = set()
        lemma_topics = set()
        lemma_synth = False
        lemma_mismatch = False
        for rec in rows[key]:
            if not isinstance(rec, dict):
                continue
            sense_cefr = rec.get("sense_cefr") or _MISSING
            pool = rec.get("pool_level") or _MISSING
            cefr_precard[sense_cefr] = cefr_precard.get(sense_cefr, 0) + 1
            lemma_cefrs.add(sense_cefr)
            lemma_cefrs.add(pool)
            labels = [t.get("label") for t in (rec.get("topic_vector") or [])
                      if isinstance(t, dict) and t.get("label")]
            if labels:
                for label in labels:
                    topic_precard[label] = topic_precard.get(label, 0) + 1
            else:
                untagged_precards += 1
            lemma_topics.update(labels)
            if rec.get("example_synthetic_needed"):
                synth_precards += 1
                lemma_synth = True
            method = rec.get("sense_cefr_method") or _UNKNOWN_METHOD
            method_precard[method] = method_precard.get(method, 0) + 1
            calls = rec.get("stage_calls")
            path = calls.get("s4_path") if isinstance(calls, dict) else None
            path = path or _UNKNOWN_METHOD
            path_precard[path] = path_precard.get(path, 0) + 1
            source = rec.get("example_fallback") or _UNKNOWN_METHOD
            source_precard[source] = source_precard.get(source, 0) + 1
            evidenced = method in ("wn-single", "wn-evp-gloss")
            if evidenced:
                evidenced_rows += 1
            if (sense_cefr != _MISSING and pool != _MISSING
                    and sense_cefr != pool):
                mismatch_precards += 1
                lemma_mismatch = True
                if evidenced:
                    evidenced_mismatch += 1
        for level in lemma_cefrs:
            cefr_lemma[level] = cefr_lemma.get(level, 0) + 1
        if len(lemma_cefrs) > 1:
            cefr_overlap += 1
        for label in lemma_topics:
            topic_lemma[label] = topic_lemma.get(label, 0) + 1
        if len(lemma_topics) > 1:
            topic_overlap += 1
        if lemma_synth:
            synth_lemmas += 1
        if lemma_mismatch:
            mismatch_lemmas += 1

    n_total = n_kept + n_dropped
    return {
        "lemmas_total": n_total,
        "lemmas_kept": n_kept,
        "lemmas_dropped": n_dropped,
        "precards_total": n_rows,
        "kept_rate_pct": round(100.0 * n_kept / n_total) if n_total else 0,
        "drops_by_reason": [[head, count] for head, count in drops_by_reason],
        "ppc": {
            "mean": round(sum(per_lemma) / len(per_lemma), 2) if per_lemma else 0,
            "median": _median(per_lemma),
            "p90": _p90(per_lemma),
            "hist": hist,
        },
        "cefr_lemma": cefr_lemma,
        "cefr_lemma_overlap": cefr_overlap,
        "cefr_precard": cefr_precard,
        "topic_lemma": dict(sorted(topic_lemma.items())),
        "topic_lemma_overlap": topic_overlap,
        "topic_precard": dict(sorted(topic_precard.items())),
        "untagged_precards": untagged_precards,
        "synthetic": {
            "precards": synth_precards,
            "precards_pct": _pct(synth_precards, n_rows),
            "lemmas": synth_lemmas,
            "lemmas_pct": _pct(synth_lemmas, n_kept),
        },
        "mismatch": {
            "precards": mismatch_precards,
            "precards_pct": _pct(mismatch_precards, n_rows),
            "lemmas": mismatch_lemmas,
            "evidenced_precards": evidenced_mismatch,
            "evidenced_denominator": evidenced_rows,
            "evidenced_pct": _pct(evidenced_mismatch, evidenced_rows),
        },
        "cefr_method": _sort_dist(method_precard),
        "topic_path": _sort_dist(path_precard),
        "example_source": _sort_dist(source_precard),
    }


def _header_strip(stats):
    if stats["drops_by_reason"]:
        drops_tip = "drops by reason (dropped.log): " + ", ".join(
            "%s: %d dropped lemmas" % (head, count)
            for head, count in stats["drops_by_reason"])
    else:
        drops_tip = "no drops recorded"
    return (
        '<div class="header-strip" id="headerStrip" title="%s">'
        '<span><b>%d</b> lemmas '
        '<span class="hs-dim">(all: <b>%d</b> kept, <b>%d</b> dropped)</span></span>'
        '<span class="hs-sep">\u00b7</span>'
        '<span><b>%d</b> precards '
        '<span class="hs-dim">(kept-only rows)</span></span>'
        '<span class="hs-sep">\u00b7</span>'
        '<span>kept rate <b>%d%%</b> '
        '<span class="hs-dim">(kept lemmas / all lemmas)</span></span>'
        "</div>" % (
            html.escape(drops_tip, quote=True),
            stats["lemmas_total"], stats["lemmas_kept"],
            stats["lemmas_dropped"], stats["precards_total"],
            stats["kept_rate_pct"]))


def _dist_table(headers, rows):
    head = "".join("<th>%s</th>" % _esc(h) for h in headers)
    body = "".join(
        "<tr>" + "".join(
            '<td class="num">%s</td>' % _esc(c) if i
            else "<td>%s</td>" % _esc(c)
            for i, c in enumerate(row)
        ) + "</tr>"
        for row in rows)
    return ("<table><thead><tr>%s</tr></thead>"
            "<tbody>%s</tbody></table>" % (head, body))


def _ordered_levels(*maps):
    levels = [lvl for lvl in _CEFR_LEVELS
              if any(m.get(lvl) for m in maps)]
    extras = sorted({k for m in maps for k in m} - set(_CEFR_LEVELS))
    return levels + extras


def _dist_drawer(stats):
    ppc = stats["ppc"]
    g1 = (
        "<h3>1 \u00b7 precards per kept lemma</h3>"
        '<p class="dist-kv">mean <b>%(mean)s</b> precards \u00b7 '
        "median <b>%(median)s</b> \u00b7 p90 <b>%(p90)s</b> "
        "(over %(n)d kept lemmas)</p>" % {
            "mean": ppc["mean"], "median": ppc["median"],
            "p90": ppc["p90"], "n": stats["lemmas_kept"]}
        + _dist_table(
            ("precards bucket", "kept lemmas"),
            [("1 precard", ppc["hist"]["1"]),
             ("2 precards", ppc["hist"]["2"]),
             ("3 precards", ppc["hist"]["3"]),
             ("4+ precards", ppc["hist"]["4+"])]))

    g2 = (
        "<h3>2 \u00b7 kept vs dropped</h3>"
        '<p class="dist-kv"><b>%(kept)d</b> kept lemmas \u00b7 '
        "<b>%(dropped)d</b> dropped lemmas \u00b7 kept rate "
        "<b>%(rate)d%%</b> (kept lemmas / all lemmas)</p>" % {
            "kept": stats["lemmas_kept"],
            "dropped": stats["lemmas_dropped"],
            "rate": stats["kept_rate_pct"]}
        + (_dist_table(
            ("drop reason (stage signal)", "dropped lemmas"),
            [(head, count) for head, count in stats["drops_by_reason"]])
            if stats["drops_by_reason"]
            else '<p class="dist-note">no drops recorded</p>'))

    levels = _ordered_levels(stats["cefr_lemma"], stats["cefr_precard"])
    g3 = (
        "<h3>3 \u00b7 senses by CEFR</h3>"
        + _dist_table(
            ("CEFR", "kept lemmas, lemma-level (exists)",
             "precards, row-level"),
            [(lvl, stats["cefr_lemma"].get(lvl, 0),
              stats["cefr_precard"].get(lvl, 0)) for lvl in levels])
        + '<p class="dist-note">lemma counts overlap: '
        "<b>%d</b> kept lemmas sit in 2+ CEFR buckets "
        "(sense_cefr \u222a pool_level); precard counts are row-level "
        "and never overlap.</p>" % stats["cefr_lemma_overlap"])

    labels = sorted(set(stats["topic_lemma"]) | set(stats["topic_precard"]),
                    key=lambda l: (-stats["topic_precard"].get(l, 0), l))
    g4 = (
        "<h3>4 \u00b7 senses by topic</h3>"
        + (_dist_table(
            ("topic", "kept lemmas, lemma-level (exists)",
             "precards, row-level"),
            [(label, stats["topic_lemma"].get(label, 0),
              stats["topic_precard"].get(label, 0)) for label in labels])
            if labels else '<p class="dist-note">no topic labels</p>')
        + '<p class="dist-note">lemma counts overlap: '
        "<b>%d</b> kept lemmas sit in 2+ topic buckets; "
        "<b>%d</b> precards carry no topic label.</p>" % (
            stats["topic_lemma_overlap"], stats["untagged_precards"]))

    synth = stats["synthetic"]
    g5 = (
        "<h3>5 \u00b7 synthetic examples needed</h3>"
        '<p class="dist-kv"><b>%(p)d</b> precards '
        "(%(pp)s%% of all precards) \u00b7 <b>%(m)d</b> kept lemmas "
        "(%(mp)s%% of kept lemmas)</p>" % {
            "p": synth["precards"], "pp": synth["precards_pct"],
            "m": synth["lemmas"], "mp": synth["lemmas_pct"]})

    mismatch = stats["mismatch"]
    g6 = (
        "<h3>6 \u00b7 pool-vs-sense CEFR mismatch</h3>"
        '<p class="dist-kv"><b>%(p)d</b> precards '
        "(%(pp)s%% of all precards) \u00b7 <b>%(m)d</b> kept lemmas "
        "with \u22651 mismatch</p>"
        '<p class="dist-kv">evidenced-only: <b>%(ep)d</b> precards '
        "(%(epp)s%% of %(ed)d evidenced precards)</p>"
        '<p class="dist-note">evidenced = sense_cefr_method wn-single / '
        'wn-evp-gloss only; unmapped and pool-fallback rows are '
        'excluded.</p>' % {
            "p": mismatch["precards"], "pp": mismatch["precards_pct"],
            "m": mismatch["lemmas"], "ep": mismatch["evidenced_precards"],
            "epp": mismatch["evidenced_pct"],
            "ed": mismatch["evidenced_denominator"]})

    g7 = (
        "<h3>7 \u00b7 CEFR provenance</h3>"
        + (_dist_table(
            ("CEFR method", "precards, row-level"),
            [(method, "%d precards (%s%%)" % (
                count, _pct(count, stats["precards_total"])))
             for method, count in stats["cefr_method"].items()])
            if stats["cefr_method"]
            else '<p class="dist-note">no rows</p>')
        + '<p class="dist-note">row-level sense_cefr_method; '
        "unmapped rows carry no level (pool_level shown separately).</p>")

    g8 = (
        "<h3>8 \u00b7 topic s4 paths</h3>"
        + (_dist_table(
            ("s4 path", "precards, row-level"),
            [(path, "%d precards (%s%%)" % (
                count, _pct(count, stats["precards_total"])))
             for path, count in stats["topic_path"].items()])
            if stats["topic_path"]
            else '<p class="dist-note">no rows</p>')
        + '<p class="dist-note">row-level stage_calls.s4_path.</p>')

    g9 = (
        "<h3>9 \u00b7 example sourcing</h3>"
        + (_dist_table(
            ("example source", "precards, row-level"),
            [(source, "%d precards (%s%%)" % (
                count, _pct(count, stats["precards_total"])))
             for source, count in stats["example_source"].items()])
            if stats["example_source"]
            else '<p class="dist-note">no rows</p>')
        + '<p class="dist-note">row-level example_fallback.</p>')

    return (
        '<details class="dist-drawer" id="distDrawer" open>'
        "<summary>Distributions "
        '<span class="dist-hint">nine metric groups \u00b7 lemma-level '
        "(exists, overlaps noted) vs precard-level (row-level) \u00b7 "
        "every number names its unit</span></summary>"
        '<div class="dist-grid">'
        + "".join('<section class="dist-group">%s</section>' % g
                   for g in (g1, g2, g3, g4, g5, g6, g7, g8, g9))
        + "</div></details>")


def _charts_badge(lang, num):
    return _tr(lang, "charts.badge_levels")


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _num(value, lang):
    """Charts display number: Persian digits on the FA charts path,
    Latin elsewhere (drawer/header keep Latin)."""
    text = str(value)
    return text.translate(_FA_DIGITS) if lang == "fa" else text


def _bar_row(name, value, width, variant=""):
    cls = "charts-fill" + (" " + variant if variant else "")
    return (
        '<div class="charts-row"><span class="charts-name">%s</span>'
        '<div class="charts-track"><div class="%s" style="width:%s%%">'
        "</div></div>"
        '<span class="charts-num">%s</span></div>'
        % (_esc(name), cls, width, _esc(value)))


def _view_tabs(lang):
    return (
        '<div class="view-tabs" role="tablist">'
        '<button class="view-tab active" id="tabReview" role="tab" '
        'aria-selected="true" onclick="switchView(\'review\')">%s</button>'
        '<button class="view-tab" id="tabMetrics" role="tab" '
        'aria-selected="false" onclick="switchView(\'metrics\')">%s</button>'
        '<button class="view-tab" id="tabCharts" role="tab" '
        'aria-selected="false" onclick="switchView(\'charts\')">%s</button>'
        "</div>" % (_esc(_tr(lang, "tab.review")),
                    _esc(_tr(lang, "tab.metrics")),
                    _esc(_tr(lang, "tab.charts"))))


def _charts_legend(lang, key):
    """Short unit legends for the charts tab.

    Every legend is a verbatim substring of the STRINGS catalog (no new
    prose); guarded by test_charts_legends_reuse_catalog_only.
    """
    legends = {
        "en": {
            "kept_share": "kept lemmas / all lemmas",
            "fanout_dist": "precards bucket, kept lemmas",
            "row_level": "precards, row-level",
        },
        "fa": {
            "kept_share": "لِماهای نگه‌داشته‌شده / همه لِماها",
            "fanout_dist": "بازه پیش‌کارت، لِماهای نگه‌داشته‌شده",
            "row_level": "پیش‌کارتها، سطح ردیفی",
        },
    }
    return legends[lang][key]


_RAIL_SEGS = ("charts-seg0", "charts-seg1", "charts-seg2", "charts-seg3")


def _rail(dist, total, lang):
    """Segmented share rail + legend grid, server-computed shares."""
    items = list(dist.items())
    if not items:
        return '<p class="dist-note">%s</p>' % _esc(_tr(lang, "empty.rows"))
    segs = "".join(
        '<div class="%s" style="width:%s%%"></div>'
        % (_RAIL_SEGS[i % len(_RAIL_SEGS)], _pct(count, total))
        for i, (_name, count) in enumerate(items))
    pct_sign = "٪" if lang == "fa" else "%"
    item_sep = "،" if lang == "fa" else ","
    grid = "".join(
        '<div class="charts-rail-item"><span class="charts-rail-name">%s</span>'
        '<span class="charts-num">%s%s %s%s</span></div>'
        % (_esc(name), _esc(_num(count, lang)), item_sep,
           _esc(_num(_pct(count, total), lang)), pct_sign)
        for name, count in items)
    return ('<div class="charts-rail">%s</div>'
            '<div class="charts-rail-grid">%s</div>'
            '<p class="charts-rail-cap">%s</p>'
            % (segs, grid, _esc(_tr(lang, "charts.rail_share"))))


def _render_charts(stats, lang="en"):
    """KPI strip + five panels bound to the STATS dict (server-side).

    Headings and unit notes reuse the STRINGS group catalog; badge
    counts are mechanical. Widths are server-side percents (1 decimal).
    """
    sep = "؛" if lang == "fa" else ";"
    pct_sign = "٪" if lang == "fa" else "%"
    kept = stats["lemmas_kept"]
    total = stats["lemmas_total"]
    rate = stats["kept_rate_pct"]
    ppc = stats["ppc"]
    mismatch = stats["mismatch"]
    synth = stats["synthetic"]

    def head(num, key, extra=""):
        badge = ('<span class="charts-badge">%s</span>'
                 % _esc(_charts_badge(lang, num)))
        if extra:
            badge += ' <span class="charts-badge">%s</span>' % _esc(extra)
        return ('<div class="charts-panel-head"><h3>%s</h3>'
                '<div>%s</div></div>'
                % (_esc(_tr(lang, key)), badge))

    kpis = [
        ("kpiKept", _tr(lang, "kpi.kept"), _num("%d%s" % (rate, pct_sign), lang),
         _tr(lang, "charts.kpi_kept_meta",
              K=_num(kept, lang),
              D=_num(stats["lemmas_dropped"], lang)), "rail-gold"),
        ("kpiFanout", _tr(lang, "kpi.fanout"), _num(ppc["mean"], lang),
         _tr(lang, "charts.kpi_fanout_meta",
              M=_num(ppc["median"], lang),
              P=_num(ppc["p90"], lang)), "rail-mint"),
        ("kpiMismatch", _tr(lang, "kpi.mismatch"),
         _num("%s%s" % (mismatch["evidenced_pct"], pct_sign), lang),
         _tr(lang, "charts.kpi_mismatch_meta",
              E=_num(mismatch["evidenced_precards"], lang),
              T=_num(mismatch["evidenced_denominator"], lang)),
         "rail-purple"),
        ("kpiSynthetic", _tr(lang, "kpi.synthetic"),
         _num("%s%s" % (synth["precards_pct"], pct_sign), lang),
         _tr(lang, "charts.kpi_synth_meta",
              N=_num(synth["precards"], lang)), "rail-rose"),
    ]
    kpi_html = (
        '<div class="kpi-strip">'
        + "".join(
            '<div class="kpi-card %s" id="%s">'
            '<div class="kpi-label">%s</div>'
            '<div class="kpi-value">%s</div>'
            '<div class="kpi-sub">%s</div></div>'
            % (rail, cid, _esc(label), _esc(value), _esc(sub))
            for cid, label, value, sub, rail in kpis)
        + "</div>")

    kept_share = _pct(kept, total)
    drop_share = 0.0 if not total else round(100.0 - kept_share, 1)
    drops = stats["drops_by_reason"]
    drop_max = max([count for _head, count in drops] + [0])
    if drops:
        top, rest = drops[:4], drops[4:]
        rows = "".join(
            _bar_row(head, _num(count, lang), _pct(count, drop_max), "drop")
            for head, count in top)
        if rest:
            rest_n = sum(count for _head, count in rest)
            rows += (
                '<div class="charts-row charts-row-others">'
                '<span class="charts-name">%s</span>'
                '<div class="charts-track"><div class="charts-fill drop" '
                'style="width:%s%%"></div></div>'
                '<span class="charts-num">%s</span></div>'
                % (_esc(_tr(lang, "charts.others", N=_num(len(rest), lang))),
                   min(_pct(rest_n, drop_max), 100.0),
                   _esc(_num(rest_n, lang))))
        pareto = '<div class="charts-pareto">' + rows + "</div>"
    else:
        pareto = '<p class="dist-note">%s</p>' % _esc(_tr(lang, "drops.none"))
    if lang == "fa":
        kept_row_label = "لِماهای نگه‌داشته‌شده"
        dropped_row_label = "لِماهای حذف‌شده"
    else:
        kept_row_label = "kept lemmas"
        dropped_row_label = "dropped lemmas"
    keep_rows = (
        '<div class="charts-keep-rows">'
        '<div class="charts-keep-row"><span>'
        '<span class="charts-dot keep"></span>%s</span><b>%s</b></div>'
        '<div class="charts-keep-row"><span>'
        '<span class="charts-dot drop"></span>%s</span><b>%s</b></div>'
        "</div>"
        % (_esc(kept_row_label), _esc(_num(kept, lang)),
           _esc(dropped_row_label),
           _esc(_num(stats["lemmas_dropped"], lang))))
    p1 = (
        '<section class="charts-panel">%s'
        '<div class="charts-donut-wrap">'
        '<div class="charts-donut-box">'
        '<svg class="charts-donut" viewBox="0 0 42 42" role="img">'
        '<circle cx="21" cy="21" r="16" class="charts-donut-bg"></circle>'
        '<circle cx="21" cy="21" r="16" class="charts-donut-fg drop" '
        'pathLength="100" stroke-dasharray="%s 100" '
        'stroke-dashoffset="-%s"></circle>'
        '<circle cx="21" cy="21" r="16" class="charts-donut-fg" '
        'pathLength="100" stroke-dasharray="%s 100"></circle>'
        "</svg>"
        '<div class="charts-donut-center">'
        '<div class="charts-donut-label">%s</div>'
        '<div class="charts-donut-cap">%s</div>'
        "</div></div>%s</div>"
        '<p class="charts-legend-line">%s</p>'
        '<p class="charts-section-head">%s</p>%s</section>'
        % (head(2, "g2.h"), drop_share, kept_share, kept_share,
           _num("%d%s" % (rate, pct_sign), lang),
           _esc(_tr(lang, "charts.donut_cap")), keep_rows,
           _esc(_charts_legend(lang, "kept_share")),
           _esc(_tr(lang, "charts.pareto_head")), pareto))

    levels = _ordered_levels(stats["cefr_lemma"], stats["cefr_precard"])
    lemma_max = max([stats["cefr_lemma"].get(lvl, 0)
                     for lvl in levels] + [0])
    precard_max = max([stats["cefr_precard"].get(lvl, 0)
                       for lvl in levels] + [0])
    dual_items = []
    for lvl in levels:
        initial = lvl[0] if lvl else ""
        band = initial.lower() if initial in "ABC" else "none"
        lemma_n = stats["cefr_lemma"].get(lvl, 0)
        precard_n = stats["cefr_precard"].get(lvl, 0)
        pair = "%s / %s" % (_num(lemma_n, lang), _num(precard_n, lang))
        dual_items.append(
            '<div class="charts-cefr-item">'
            '<span class="charts-cefr-badge %s">%s</span>'
            '<div class="charts-cefr-bars">'
            '<div class="charts-track"><div class="charts-fill lemma" '
            'style="width:%s%%"></div></div>'
            '<div class="charts-track"><div class="charts-fill precard" '
            'style="width:%s%%"></div></div>'
            '</div><span class="charts-num">%s</span></div>'
            % (band, _esc(lvl),
               _pct(lemma_n, lemma_max), _pct(precard_n, precard_max),
               _esc(pair)))
    dual = '<div class="charts-cefr-list">' + "".join(dual_items) + "</div>"
    guide = (
        '<div class="charts-guide">'
        '<span><span class="charts-dot lemma"></span>%s</span>'
        '<span><span class="charts-dot precard"></span>%s</span>'
        '<span class="charts-pair">%s</span></div>'
        % (_esc(_tr(lang, "charts.cefr_guide_lemma")),
           _esc(_tr(lang, "charts.cefr_guide_precard")),
           _esc(_tr(lang, "charts.cefr_pair"))))
    p2 = (
        '<section class="charts-panel">%s%s%s</section>'
        % (head(3, "g3.h"), guide, dual))

    n_rows = stats["precards_total"]
    s4_rail = _rail(stats["topic_path"], n_rows, lang)
    if lang == "fa":
        method_rows = [
            (method, "%d پیش‌کارت (%s٪)" % (
                count, _pct(count, n_rows)))
            for method, count in stats["cefr_method"].items()]
    else:
        method_rows = [
            (method, "%d precards (%s%%)" % (
                count, _pct(count, n_rows)))
            for method, count in stats["cefr_method"].items()]
    example_rail = _rail(stats["example_source"], n_rows, lang)
    g7_heads = [_esc(part.strip()) for part in
                _tr(lang, "g7.th").split(sep)]
    method_grid = (_dist_table(g7_heads, method_rows)
                   if method_rows
                   else '<p class="dist-note">%s</p>'
                   % _esc(_tr(lang, "empty.rows")))
    p3 = (
        '<section class="charts-panel">%s'
        '<p class="charts-section-head">%s</p>%s%s'
        '<div><p class="charts-section-head">%s</p>'
        '<p class="charts-legend-line">%s%s %s</p></div>%s</section>'
        % (head(8, "g8.h"), _esc(_tr(lang, "charts.s4_head")), s4_rail,
           method_grid,
           _esc(_tr(lang, "charts.prov_head")),
           _esc(_tr(lang, "charts.prov_total",
                     N=_num(n_rows, lang))),
           "،" if lang == "fa" else ",",
           _esc(_tr(lang, "charts.rail_share")), example_rail))

    ranked = sorted(set(stats["topic_lemma"]) | set(stats["topic_precard"]),
                    key=lambda l: (-stats["topic_precard"].get(l, 0), l))
    top = ranked[:10]
    topic_max = max([stats["topic_precard"].get(l, 0) for l in top] + [0])
    if top:
        topics = ('<div class="charts-topics">' + "".join(
            _bar_row(label, _num(stats["topic_precard"].get(label, 0), lang),
                     _pct(stats["topic_precard"].get(label, 0), topic_max),
                     "topic")
            for label in top) + "</div>")
    else:
        topics = '<p class="dist-note">%s</p>' % _esc(_tr(lang, "g4.empty"))
    untagged_badge = _tr(lang, "charts.untagged",
                          N=_num(stats["untagged_precards"], lang))
    p4 = (
        '<section class="charts-panel">%s'
        '<p class="charts-legend-line">%s</p>'
        '<div class="charts-scroll">%s</div></section>'
        % (head(4, "g4.h", untagged_badge),
           _esc(_charts_legend(lang, "row_level")), topics))

    if lang == "fa":
        buckets = [part.strip() for part in
                   STRINGS["fa"]["g1.buckets"].split("؛")]
        bucket_labels = [part.strip() for part in buckets[0].split("/")]
    else:
        bucket_labels = ["1 precard", "2 precards", "3 precards",
                         "4+ precards"]
    hist = ppc["hist"]
    fanout_max = max([hist["1"], hist["2"], hist["3"], hist["4+"]] + [0])
    pillar_cells = []
    for label, key in zip(bucket_labels, ("1", "2", "3", "4+")):
        count = hist[key]
        share = _pct(count, fanout_max)
        pillar_cells.append(
            '<div class="charts-pillar">'
            '<div class="charts-pillar-title">%s</div>'
            '<div class="charts-pillar-stage"><div class="charts-pillar-col">'
            '<div class="charts-pillar-fill%s" '
            'style="width:%s%%;height:%s%%"></div>'
            '</div></div>'
            '<div class="charts-pillar-stat">%s %s</div>'
            '<div class="charts-pillar-share">%s%s</div></div>'
            % (_esc(label),
               " max" if count and count == fanout_max else "",
               share, share,
               _esc(_num(count, lang)),
               _esc(_tr(lang, "charts.pillar_unit")),
               _esc(_num(_pct(count, stats["lemmas_kept"]), lang)),
               pct_sign))
    pillars = '<div class="charts-pillars">' + "".join(pillar_cells) + "</div>"
    bench = (
        '<div class="charts-bench"><span>%s</span><span>%s</span></div>'
        % (_esc(_tr(lang, "charts.bench")),
           _esc(_tr(lang, "charts.bench_vals",
                     M=_num(ppc["mean"], lang),
                     D=_num(ppc["median"], lang),
                     P=_num(ppc["p90"], lang)))))
    p5 = (
        '<section class="charts-panel charts-panel-full">%s%s'
        '<p class="charts-legend-line">%s</p>%s</section>'
        % (head(1, "g1.h"), pillars,
           _esc(_charts_legend(lang, "fanout_dist")), bench))

    return (kpi_html + '<div class="charts-grid">'
            + p1 + p2 + p3 + p4 + p5 + "</div>")


def _fa_sibling(path):
    name = path.name
    if name.endswith(".fa.html"):
        return path
    if name.endswith(".html"):
        return path.with_name(name[:-len(".html")] + ".fa.html")
    return path.with_name(name + ".fa.html")


def _en_sibling(path):
    name = path.name
    if name.endswith(".fa.html"):
        return path.with_name(name[:-len(".fa.html")] + ".html")
    return path.with_name(path.stem + "-en.html")


def _build(run_dir=None, precard=None, sample=None, dropped=None,
           run_log=None, limit=0, title=None, lang="en"):
    if lang not in _LANGS:
        raise ValueError("lang must be one of %s" % (list(_LANGS),))
    run_path = Path(run_dir) if run_dir else None
    if run_path is None:
        for cand in (precard, dropped, run_log):
            if cand:
                run_path = Path(cand).parent
                break
        if run_path is None:
            run_path = _default_run_dir()
    precard_path = Path(precard) if precard else run_path / "precard.jsonl"
    sample_path = Path(sample) if sample else (
        Path(DEFAULT_SAMPLE) if DEFAULT_SAMPLE else None)
    dropped_path = Path(dropped) if dropped else run_path / "dropped.log"
    run_log_path = Path(run_log) if run_log else run_path / "run.log"

    warnings = []
    order = _load_order(sample_path, limit)
    if sample_path is None or not sample_path.exists():
        if lang == "fa":
            warnings.append(_tr("fa", "ban.sample", p=sample_path))
        else:
            warnings.append("sample order skipped (missing %s)" % sample_path)
    rows = _load_rows(precard_path)
    if not precard_path.exists():
        if lang == "fa":
            warnings.append(_tr("fa", "ban.rows", p=precard_path))
        else:
            warnings.append("precard rows skipped (missing %s)" % precard_path)
    dropped_map = _load_dropped(dropped_path, run_log_path)
    if not dropped_path.exists():
        if lang == "fa":
            warnings.append(_tr("fa", "ban.dropped", p=dropped_path))
        else:
            warnings.append("dropped list skipped (missing %s)" % dropped_path)
    if run_log_path is None or not run_log_path.exists():
        if lang == "fa":
            warnings.append(_tr("fa", "ban.runlog", p=run_log_path))
        else:
            warnings.append(
                "run-log scan skipped (missing %s)" % run_log_path)

    keys = [k for k in order if k in rows or k in dropped_map]
    seen = set(keys)
    for k in list(rows) + list(dropped_map):
        if k not in seen:
            seen.add(k)
            keys.append(k)
    n_rows = sum(len(v) for v in rows.values())

    lemmas_data = []
    for key in keys:
        if key in rows:
            recs = rows[key]
            first = recs[0] if isinstance(recs[0], dict) else {}
            text = first.get("text") or key.split(":", 1)[-1]
            pool_level = first.get("pool_level") or "\u2014"
            lemmas_data.append({
                "text": text,
                "key": key,
                "pool_level": pool_level,
                "dropped": False,
                "drop_reason": None,
                "senses": recs,
            })
        elif key in dropped_map:
            text = key.split(":", 1)[-1]
            lemmas_data.append({
                "text": text,
                "key": key,
                "pool_level": "\u2014",
                "dropped": True,
                "drop_reason": _drop_reason(dropped_map[key]),
                "entry_band": _drop_band(dropped_map[key]),
                "senses": [],
            })

    if title:
        shown_title = title
    elif lang == "fa":
        shown_title = _tr("fa", "title", run=run_path.name)
    else:
        shown_title = "precard viewer \u2014 %s" % run_path.name
    page = _HTML_TEMPLATE.replace("__TITLE__", _esc(shown_title))
    page = page.replace("__LINE_VERSION__", _esc(_LINE_VERSION))
    page = page.replace("__CEFR_PILLS__", _cefr_pills())
    page = page.replace("__BANNERS__", _banners(warnings))
    stats = _compute_stats(rows, dropped_map)
    page = page.replace("__VIEW_TABS__", _view_tabs(lang))
    page = page.replace("__CHARTS__", _render_charts(stats, lang))
    if lang == "fa":
        page = page.replace("__HEADER_STRIP__", _header_strip_fa(stats))
        page = page.replace("__DIST_DRAWER__", _dist_drawer_fa(stats))
    else:
        page = page.replace("__HEADER_STRIP__", _header_strip(stats))
        page = page.replace("__DIST_DRAWER__", _dist_drawer(stats))
    page = page.replace("__VIEWER_DATA__",
                        _neutralise(json.dumps(lemmas_data, ensure_ascii=False)))
    page = page.replace("__VIEWER_STATS__",
                        _neutralise(json.dumps(stats, ensure_ascii=False)))
    page = page.replace("__KNOWN_TOPICS__",
                        _neutralise(json.dumps(list(_TOPIC_LABELS),
                                               ensure_ascii=False)))
    page = page.replace("__STAGE_NAMES__",
                        _neutralise(json.dumps(
                            {sid: normalize_stage(sid) for sid in _STAGE_IDS},
                            ensure_ascii=False)))
    if lang == "fa":
        page = _apply_fa_chrome(page)
        page = _apply_fa_js(page)
    else:
        page = _inject_en_toggle(
            page, _fa_sibling(Path("precard-viewer.html")).name)
    return page, {"rows": n_rows, "lemmas": len(keys)}


def build_html(run_dir=None, *, precard=None, sample=None, dropped=None,
               run_log=None, limit=0, title=None, lang="en"):
    """Return the standalone viewer HTML text for one precard run."""
    page, _stats = _build(run_dir, precard, sample, dropped, run_log,
                          limit, title, lang)
    return page


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default=str(_default_run_dir()),
                    help="run dir with precard.jsonl + dropped.log")
    ap.add_argument("--precard", default=None,
                    help="precard.jsonl path (default <run-dir>/precard.jsonl)")
    ap.add_argument("--sample", default=None,
                    help="sample json file (default pipeline DEFAULT_SAMPLE)")
    ap.add_argument("--dropped", default=None,
                    help="dropped.log path (default <run-dir>/dropped.log)")
    ap.add_argument("--run-log", default=None,
                    help="run log path (default <run-dir>/run.log)")
    ap.add_argument("--out", default=None,
                    help="viewer path for the selected language "
                    "(both twins are always written; default "
                    "<run-dir>/precard-viewer.html)")
    ap.add_argument("--limit", type=int, default=0,
                    help="max sample lemmas (0 = all)")
    ap.add_argument("--title", default=None,
                    help="page title (default 'precard viewer \u2014 <run-dir name>')")
    ap.add_argument("--lang", default="en", choices=list(_LANGS),
                    help="viewer language: en or fa (default en)")
    args = ap.parse_args(argv)
    try:
        page_en, stats = _build(args.run_dir, args.precard, args.sample,
                                args.dropped, args.run_log, args.limit,
                                args.title, "en")
        page_fa, _fa_stats = _build(args.run_dir, args.precard, args.sample,
                                    args.dropped, args.run_log, args.limit,
                                    args.title, "fa")
    except AssertionError as exc:
        print("viewer build failed: %s" % exc, file=sys.stderr)
        return 1
    if args.out:
        given = Path(args.out)
        if args.lang == "fa":
            dest_fa = given
            dest_en = _en_sibling(given)
        else:
            dest_en = given
            dest_fa = _fa_sibling(given)
    else:
        dest_en = Path(args.run_dir) / "precard-viewer.html"
        dest_fa = Path(args.run_dir) / "precard-viewer.fa.html"
    if dest_en == dest_fa:
        print("viewer --out collision: en and fa twins resolve to %s"
              % dest_en, file=sys.stderr)
        return 2
    if dest_fa.name != _fa_sibling(Path("precard-viewer.html")).name:
        page_en = page_en.replace(
            'href="precard-viewer.fa.html"',
            'href="%s"' % html.escape(dest_fa.name, quote=True), 1)
    if dest_en.name != "precard-viewer.html":
        page_fa = page_fa.replace(
            'href="precard-viewer.html"',
            'href="%s"' % html.escape(dest_en.name, quote=True), 1)
    dest_en.parent.mkdir(parents=True, exist_ok=True)
    dest_en.write_text(page_en, encoding="utf-8")
    dest_fa.parent.mkdir(parents=True, exist_ok=True)
    dest_fa.write_text(page_fa, encoding="utf-8")
    shown = dest_fa if args.lang == "fa" else dest_en
    print("wrote %(out)s rows=%(rows)d lemmas=%(lemmas)d" % {
        "out": shown, "rows": stats["rows"], "lemmas": stats["lemmas"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
