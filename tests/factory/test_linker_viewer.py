"""Hermetic gallery + telemetry tests (no network, no W:, no model)."""

import pathlib

from factory.linker import linker
from factory.linker import viewer as viewer


def _rows():
    return [
        {"kaikki_sense_id": "en-run-en-verb-A", "wordnet_sensekey": "run%2:38:00::",
         "method": "LINK:2-sig", "evidence": "Sa:j=0.40+Sd:hyp=move",
         "flags": "", "lemma": "run", "kaikki_pos": "verb",
         "kaikki_gloss": "To move fast."},
        {"kaikki_sense_id": "en-run-en-verb-B", "wordnet_sensekey": "run%2:38:11::",
         "method": "JUDGE-PENDING", "evidence": "Sd:hyp=travel",
         "flags": "", "lemma": "run", "kaikki_pos": "verb",
         "kaikki_gloss": "To travel a route."},
        {"kaikki_sense_id": "en-run-en-verb-C", "wordnet_sensekey": "-",
         "method": "UNMAPPED", "evidence": "0sig",
         "flags": "", "lemma": "run", "kaikki_pos": "verb",
         "kaikki_gloss": "To own something."},
        {"kaikki_sense_id": "en-book-en-verb-hoaZwz7Y", "wordnet_sensekey": "book%2:41:00::",
         "method": "quarantined-known-false",
         "evidence": "Sa:j=0.33+Sd:hyp=record+judge-first",
         "flags": "quarantined-known-false", "lemma": "book",
         "kaikki_pos": "verb", "kaikki_gloss": "To record in a book."},
        {"kaikki_sense_id": "en-take-en-verb-D", "wordnet_sensekey": "take%2:35:00::",
         "method": "LINK:judge-v2",
         "evidence": "Sb:course | judge:kaikki=\"x\" wordnet=\"move fast || words: run || eg: run far\"",
         "flags": "judge-v2:2-1+provisional_consensus", "lemma": "take",
         "kaikki_pos": "verb", "kaikki_gloss": "To cover a course."},
    ]


def _verdicts():
    return [
        {"kid": "en-take-en-verb-D", "lemma": "take", "verdict": "LINK",
         "winner_index": 2, "winner_sensekey": "take%2:35:00::",
         "wordnet_evidence": "move fast || words: run || eg: run far",
         "votes": [
             {"ok": True, "verdict": "LINK", "winner_index": 2},
             {"ok": True, "verdict": "LINK", "winner_index": 1},
             {"ok": True, "verdict": "LINK", "winner_index": 2},
         ]},
    ]


def test_link_stats_counters_add_up():
    stats = linker.link_stats(_rows())
    stage = stats["stage"]
    assert stats["total"] == 5
    assert sum(stats["method_counts"].values()) == 5
    assert (stage["link"] + stage["none"] + stage["pending"]
            + stage["unmapped"] + stage["twin"] + stage["quarantine"]
            + stage["other"]) == 5
    assert stage["link"] == 2
    assert stage["quarantine"] == 1
    assert stage["provisional"] == 1
    assert stats["unknown_methods"] == []
    assert stats["signals"]["Sa"] == 2
    assert stats["signals"]["Sd"] == 3
    assert stats["signals"]["judge"] == 1


def test_link_stats_unknown_method_surfaces():
    stats = linker.link_stats([{"kaikki_sense_id": "x", "method": "WAT",
                                "evidence": "", "flags": ""}])
    assert stats["unknown_methods"] == ["WAT"]
    assert stats["stage"]["other"] == 1


def test_gallery_renders_gauges_cards_and_bidi(tmp_path):
    out = tmp_path / "gallery.html"
    summary = viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert summary["words"] == 3
    assert '<html lang="fa" dir="rtl">' in page
    assert "LINK" in page and "quarantine" in page
    assert "signal-fire distribution" in page
    assert "judge agreement" in page
    # per-sense content: kaikki gloss quoted, winner key bidi-isolated
    assert "To move fast." in page
    assert ">run%2:38:00::</bdi>" in page
    # evidence chips per firing signal
    assert "<bdi>Sa:j=0.40</bdi>" in page
    assert "<bdi>Sd:hyp=move</bdi>" in page
    # bidi isolation for keys + English glosses tagged
    assert 'lang="en" dir="ltr"' in page
    assert "<bdi>en-run-en-verb-A</bdi>" in page
    # gap slots present
    assert "example+src" in page


def test_gallery_flags_red_and_amber(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "is-quarantine" in page
    assert "quarantined-known-false" in page
    # provisional row (flags) + split vote both render amber
    assert "is-provisional" in page
    assert "provisional_consensus" in page
    assert "split" in page


def test_signal_vocab_mapping_locked():
    assert linker.signal_vocab("Sa") == {
        "code": "Sa", "name": "lexical-overlap", "fa": "هم‌پوشانی واژگان تعریف"}
    assert linker.signal_vocab("Sb")["name"] == "synonym-crossfire"
    assert linker.signal_vocab("Sc")["name"] == "example-crossfire"
    assert linker.signal_vocab("Sd")["name"] == "hypernym-topic"
    assert linker.signal_vocab("Se")["name"] == "meaning-similarity"
    assert linker.signal_vocab("short-gloss")["name"] == "short-definition"
    assert linker.signal_vocab("zero-sig")["name"] == "no-signal"
    assert linker.signal_vocab("0sig")["name"] == "no-signal"
    assert linker.signal_vocab("judge")["name"] == "judge-vote"
    for code in ("Sa", "Sb", "Sc", "Sd", "Se", "short-gloss", "zero-sig", "judge"):
        assert linker.signal_vocab(code)["fa"]
    # unknown codes pass through fail-soft
    assert linker.signal_vocab("Sx")["name"] == "Sx"


def test_telemetry_counters_vocab_keyed():
    counters = linker.telemetry_counters(_rows())
    assert counters["total"] == 5
    assert counters["signals"]["lexical-overlap"] == 2
    assert counters["signals"]["hypernym-topic"] == 3
    assert counters["signals"]["judge-vote"] == 1
    assert counters["signals"]["no-signal"] == 1
    assert "Sa" not in counters["signals"]
    assert counters["stage"]["link"] == 2
    assert counters["stage"]["quarantine"] == 1


def test_machine_block_scores_thresholds_tier_seeds():
    blk = linker.machine_block(_rows()[0])
    assert blk["signals"]["lexical-overlap"]["detail"] == "Sa:j=0.40"
    assert blk["signals"]["hypernym-topic"]["detail"] == "Sd:hyp=move"
    assert blk["thresholds"]["link_min"] == 2
    assert blk["thresholds"]["se_cut"] == 0.43
    assert blk["thresholds"]["jaccard"] == 0.2
    assert blk["thresholds"]["shortlist_cap"] == 12
    assert blk["tier"] and blk["seed"] and blk["build"]
    assert blk["flags"] == []


def test_gallery_filter_button_wiring(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # every gauge is a filter button with group+key wiring
    for key in ("stage:link", "stage:none", "stage:pending", "stage:unmapped",
                "stage:twin", "stage:quarantine", "stage:provisional"):
        assert 'data-fkey="%s"' % key in page
        assert 'data-fgroup="stage"' in page
    # signal bars filter rows too, keyed by locked vocabulary
    for name in ("lexical-overlap", "synonym-crossfire", "example-crossfire",
                 "hypernym-topic", "meaning-similarity", "short-definition",
                 "no-signal", "judge-vote"):
        assert 'data-fkey="sig:%s"' % name in page
    # judge facts wire certainty + outcome filters
    assert 'data-fkey="judge:unanimous"' in page
    assert 'data-fkey="judge:split-vote"' in page
    assert 'data-fkey="outcome:LINK"' in page
    assert 'data-fkey="outcome:NONE"' in page
    assert 'aria-pressed="false"' in page
    # chips + live count line
    assert 'id="chips"' in page
    assert 'id="countline"' in page
    # rows carry AND-combined filter keys
    assert 'data-keys="' in page
    assert "stage:link" in page


def test_gallery_judge_three_facts_and_trace(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "coverage" in page and "چند معنی به داور رسید" in page
    assert "certainty" in page and "هر ۳ داور هم‌نظر" in page
    assert "outcome" in page and "نتیجه نهایی داور" in page
    for step in ("candidates-in", "signals", "decision", "judge", "gaps"):
        assert 'data-step="%s"' % step in page
    assert "چرا:" in page


def test_gallery_compact_table_export_and_machine(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # compact table: one summary row per sense + expandable detail
    assert "<table" in page and page.count('tr class="summary"') == 5
    assert 'class="detail" hidden' in page
    assert 'class="rowcheck"' in page
    assert 'id="export"' in page
    assert 'id="checkall"' in page
    # export schema: per-record array (round 4), documented in help
    for key in ("records", "row_ref", "in_def", "winner_def",
                "decision", "candidates", "judge", "fires"):
        assert key in page
    assert "EXPORT_SCHEMA" in page
    assert "for LLM evaluation" in page
    # export toolbar: optional candidates + judge-vote checkboxes
    assert 'id="exp-cand"' in page
    assert 'id="exp-judge"' in page
    # per-card machine+raw merged into ONE tech details with two tabs
    assert 'class="tech"' in page
    assert 'role="tablist"' in page
    assert 'role="tabpanel"' in page
    assert "link_min" in page
    # locked vocabulary visible, legacy codes only as aliases
    assert "lexical-overlap" in page
    assert "hypernym-topic" in page


def test_gallery_tag_balance(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    for tag in ("div", "table", "tbody", "tr", "td", "button", "details",
                "ol", "li", "ul", "summary", "section", "header", "footer",
                "nav", "dl", "dt", "dd", "svg"):
        assert page.count("<%s" % tag) == page.count("</%s>" % tag), tag


def _cand_entry():
    return {
        "en-run-en-verb-A": {
            "top3": [
                {"sensekey": "run%2:38:11::", "gloss": "move about freely",
                 "jaccard": 0.0, "lemmas": ["run"],
                 "fires": ["Sd:hyp=move"]},
                {"sensekey": "run%2:38:00::",
                 "gloss": "move fast by using one's feet",
                 "jaccard": 0.1176, "lemmas": ["run"], "fires": []},
            ]
        }
    }


def _verdicts_with_latency():
    votes = [
        {"ok": True, "verdict": "LINK", "winner_index": 1,
         "seed": 42, "latency_s": 6.5,
         "wordnet_evidence": "move fast || words: run || eg: run far",
         "kaikki_evidence": "To move fast."},
        {"ok": True, "verdict": "LINK", "winner_index": 1,
         "seed": 43, "latency_s": 7.5,
         "wordnet_evidence": "move fast || words: run || eg: run far",
         "kaikki_evidence": "To move fast."},
        {"ok": True, "verdict": "LINK", "winner_index": 1,
         "seed": 44, "latency_s": 22.0,
         "wordnet_evidence": "move fast || words: run || eg: run far",
         "kaikki_evidence": "To move fast."},
    ]
    return [
        {"kid": "en-run-en-verb-A", "lemma": "run", "verdict": "LINK",
         "winner_index": 1, "winner_sensekey": "run%2:38:11::",
         "wordnet_evidence": "move fast || words: run || eg: run far",
         "votes": votes},
        {"kid": "en-run-en-verb-B", "lemma": "run", "verdict": "NONE",
         "winner_index": None, "winner_sensekey": None,
         "wordnet_evidence": "",
         "votes": [{"ok": True, "verdict": "NONE", "winner_index": None,
                    "seed": 42, "latency_s": 5.0,
                    "wordnet_evidence": "", "kaikki_evidence": "To travel."}]},
        {"kid": "en-run-en-verb-C", "lemma": "run", "verdict": None,
         "winner_index": None, "winner_sensekey": None,
         "wordnet_evidence": "", "vote_status": "FAILED",
         "votes": [{"ok": False, "verdict": None, "winner_index": None,
                    "seed": 42, "latency_s": 9.0, "note": "parse-fail: x",
                    "raw": "```json {}", "wordnet_evidence": None,
                    "kaikki_evidence": None}]},
    ]


def test_search_normalize_and_match():
    assert viewer.normalize_search("رفتن ۱۲۳") == "رفتن 123"
    assert viewer.normalize_search("۱۲۳") == viewer.normalize_search("١٢٣")
    assert viewer.normalize_search("Run FAST") == "run fast"
    row = {"lemma": "run", "kaikki_gloss": "To move fast.",
           "kaikki_sense_id": "en-run-en-verb-A",
           "wordnet_sensekey": "run%2:38:00::", "evidence": "Sd:hyp=move"}
    assert viewer.match_search(row, {}, "RUN")
    assert viewer.match_search(row, {}, "۱۲۳") is False
    assert viewer.match_search(row, {}, "move fast")
    assert viewer.match_search(row, {}, "take") is False
    assert viewer.match_search(row, {}, "")
    assert viewer.match_search(row, {}, "hyp")


def test_latency_stats_buckets_and_summary():
    stats = viewer.latency_stats([6.0, 7.0, 8.0, 9.0])
    counts = [b["count"] for b in stats["buckets"]]
    assert counts == [0, 0, 3, 1, 0, 0, 0, 0]
    assert stats["avg"] == 7.5
    assert stats["p50"] == 8.0
    assert stats["p90"] == 9.0
    assert stats["max"] == 9.0
    assert stats["n"] == 4
    empty = viewer.latency_stats([])
    assert empty["n"] == 0 and empty["avg"] is None
    assert viewer.verdict_latencies(_verdicts_with_latency()) == [
        6.5, 7.5, 22.0, 5.0, 9.0]


def test_quality_checks_find_violations():
    rows = [
        {"kaikki_sense_id": "k-bare", "method": "LINK:2-sig",
         "evidence": "", "flags": ""},
        {"kaikki_sense_id": "en-book-en-verb-hoaZwz7Y",
         "method": "LINK:2-sig", "evidence": "Sa:j=0.33",
         "flags": "quarantined-known-false"},
        {"kaikki_sense_id": "k-twin", "method": "LINK:2-sig",
         "evidence": "best-cand-twinned;tsv-cefr=A1", "flags": ""},
        {"kaikki_sense_id": "k-ok", "method": "JUDGE-PENDING",
         "evidence": "Sa:j=0.27", "flags": ""},
    ]
    by_id = {c["id"]: c for c in viewer.quality_checks(rows, [])}
    assert by_id["link-evidence"]["status"] == "WARN"
    assert by_id["link-evidence"]["violators"] == ["k-bare"]
    assert by_id["quarantine-clean"]["violators"] == [
        "en-book-en-verb-hoaZwz7Y"]
    assert by_id["twin-clean"]["violators"] == ["k-twin"]
    assert by_id["counts-reconcile"]["status"] == "PASS"
    assert by_id["response-cap"]["value"].endswith("/ 0 رأی")


def test_gallery_borrowed_gauges_search_nav(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        _rows(), _verdicts_with_latency(), str(out),
        candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # verdict pie: clickable slices for LINK/NONE/FAILED
    assert 'id="verdictpie"' in page
    assert 'data-fkey="outcome:LINK"' in page
    assert 'data-fkey="outcome:NONE"' in page
    assert 'data-fkey="outcome:FAILED"' in page
    assert "pieslice" in page
    # latency histogram with avg/p50/p90/max line from verdict latencies
    assert 'id="lathist"' in page
    assert "avg" in page and "p50" in page
    assert "p90" in page and "max" in page
    # quality checklist table check/value/status with all six checks
    assert 'class="checks"' in page
    for check in ("every-LINK-has-evidence", "quarantine-never-LINK",
                  "twin-never-LINK", "unanimous-rate",
                  "response-cap-zero-truncation", "counts-reconcile"):
        assert check in page
    assert "PASS" in page
    # search box + clear button + all-clear banner
    assert 'id="search"' in page
    assert 'id="searchclear"' in page
    assert 'id="allclear"' in page
    assert 'data-search="' in page
    # sticky pill nav over gauges/judge/table/help
    assert 'class="pillnav"' in page
    for tab in ("tab-gauges", "tab-judge", "tab-table", "tab-help"):
        assert 'id="%s"' % tab in page
    for sec in ("sec-gauges", "sec-judge", "sec-table", "sec-help"):
        assert 'id="%s"' % sec in page


def test_gallery_trace_exact_inputs_and_vocab(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        _rows(), _verdicts_with_latency(), str(out),
        candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # candidates-in: rank + sensekey + synset locator + gloss + shortlist score
    assert "candlist" in page
    assert "رتبه 1" in page
    assert "run%2:38:11::" in page
    assert "shortlist" in page
    assert "0.1176" in page
    # signals: exact quoted token, not a bare code
    assert "‘move’" in page or "'move'" in page
    assert "ابرنام/موضوع مشترک" in page
    # decision: rule + threshold comparison
    assert "LINK_MIN_DEFAULT" not in page  # never leaks bare constants
    assert "≥" in page and "→" in page
    # judge: per-vote seed + latency + quoted reason
    assert "seed" in page
    assert "6.5s" in page
    assert "نقل دلیل" in page
    # gaps: field ← source per field
    assert "←" in page
    # naming polish: FA sentence + muted code for methods/flags/top signal
    assert "پیوند" in page
    assert 'class="code"' in page
    assert "در انتظار داور" in page
    assert "نگاشت‌نشده" in page
    # machine JSON keys carry FA glosses
    assert "mkeys" in page
    assert "کمینه سیگنال برای پیوند" in page
    # gloss clamp + density hooks
    assert "gloss-snip" in page


def test_gallery_js_wiring_ids_referenced():
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    for ident in ("search", "searchclear", "export", "checkall", "chips",
                  "countline", "allclear", "clearall", "exp-cand",
                  "exp-judge", "jumptable", "tab-gauges", "tab-judge",
                  "tab-table", "tab-help", "data-fkey", "data-search"):
        assert ident in src, ident


# --- Round 4: filter OR-logic, search prefixes, export schema, naming ---

def test_row_matches_filters_or_within_and_across():
    link = ["stage:link", "sig:lexical-overlap", "judge:unjudged",
            "outcome:-"]
    # same-group keys OR: stage:link OR stage:none matches a link row
    assert viewer.row_matches_filters(
        link, {"stage:link", "stage:none"}) is True
    # across groups AND: stage link + sig judge-vote fails (no judge-vote)
    assert viewer.row_matches_filters(
        link, {"stage:link", "sig:judge-vote"}) is False
    # across groups AND satisfied
    assert viewer.row_matches_filters(
        link, {"stage:link", "sig:lexical-overlap"}) is True
    # empty active matches everything
    assert viewer.row_matches_filters(link, set()) is True
    assert viewer.row_matches_filters([], {"stage:link"}) is False


def test_match_search_field_prefixes():
    row = {"lemma": "run", "kaikki_gloss": "To move fast.",
           "kaikki_sense_id": "en-run-en-verb-A",
           "wordnet_sensekey": "run%2:38:00::", "evidence": "Sd:hyp=move"}
    # kid: prefix hits the kaikki id before substring rules
    assert viewer.match_search(row, {}, "kid:en-run-en-verb-A") is True
    assert viewer.match_search(row, {}, "kid:en-run-en-verb-B") is False
    # key: prefix hits the wordnet sensekey
    assert viewer.match_search(row, {}, "key:run%2:38:00") is True
    assert viewer.match_search(row, {}, "key:take%2:35") is False
    # key: also sees the judge winner sensekey
    verdict = {"winner_sensekey": "take%2:35:00::"}
    assert viewer.match_search(row, verdict, "key:take%2:35") is True
    # plain substring still works
    assert viewer.match_search(row, {}, "move fast") is True


def test_search_js_debounce_and_highlight():
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert "setTimeout" in src and "175" in src  # 150-200ms debounce
    assert "clearTimeout" in src
    assert "<mark>" in src  # gloss match highlight
    # highlight built from escaped slices, never regex on raw HTML
    assert "escHtml" in src


def test_filter_js_group_logic_and_chips():
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    # OR within one key-prefix group, AND across groups
    assert "groupOf" in src
    # chips carry the group prefix, e.g. `stage · … ×`
    assert '" · "' in src or "' · '" in src
    # global zero-results + clear-all (not check:-scoped)
    assert 'id="clearall"' in src
    # stage gauges carry totals for now/tot switching
    assert "data-tot" in src


def test_nav_js_threshold_and_jumptable(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert 'id="jumptable"' in page
    assert 'href="#sec-table"' in page
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    # separate observer threshold; short help section without rootMargin
    assert "threshold" in src
    assert "helpObs" in src


def test_candidates_winner_class_and_signal_badge(tmp_path):
    cands = _cand_entry()
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out),
                                candidates=cands)
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # winner candidate <li> carries is-winner + check
    assert "is-winner" in page
    # +N badge beside the top signal for remaining signals
    assert 'class="more"' in page


def test_evidence_sa_j_and_jaccard_warning():
    assert viewer.evidence_sa_j("Sa:j=0.40+Sd:hyp=move") == 0.40
    assert viewer.evidence_sa_j("Sd:hyp=move") is None
    assert viewer.evidence_sa_j("0sig") is None
    row = {"kaikki_gloss": "To move.", "lemma": "run"}
    cands = {"top3": [
        {"sensekey": "run%2:38:00::", "gloss": "move fast",
         "jaccard": 0.40, "lemmas": ["run"], "fires": []},
        {"sensekey": "run%2:38:11::", "gloss": "travel",
         "jaccard": 0.05, "lemmas": ["run"], "fires": []},
    ]}
    near = viewer.render_candidates_html(
        dict(row, evidence="Sa:j=0.40"), cands, "run%2:38:00::")
    assert "ناهمخوانی" not in near  # |0.40-0.40| <= 0.01
    far = viewer.render_candidates_html(
        dict(row, evidence="Sa:j=0.40"), cands, "run%2:38:11::")
    # winner run%2:38:11:: has j=0.05 vs Sa 0.40 → inline warning
    assert "shortlist-jaccard" in far and "0.05" in far


def test_naming_locked_strings(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out),
                                candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # gaps step renamed; table column renamed; judge section keeps رأی
    assert "تکمیل فیلدها" in page
    assert "وضعیت/روش" in page
    assert "نقل دلیل" in page  # judge per-vote detail keeps رأی-family text
    # crossfire display labels renamed, codes byte-identical in evidence
    assert "هم‌پوشانی مترادف‌ها" in page
    assert "هم‌پوشانی مثال‌ها" in page
    assert "Sb:course" in page  # raw evidence string untouched
    assert "Sa:j=0.40" in page


def test_link_method_vocab_single_source():
    import factory.linker as pkg
    from factory.linker import linker as core
    assert pkg.LINK_METHOD_VOCAB is core.LINK_METHOD_VOCAB
    assert len(core.LINK_METHOD_VOCAB) == 13


def test_words_filter_lemma_less_real_table(tmp_path):
    import csv as _csv
    import pathlib as _pl
    table = _pl.Path(viewer.__file__).parent / "table.tsv"
    header = _csv.DictReader(
        open(table, encoding="utf-8")).fieldnames or []
    assert "lemma" not in header  # real tables lack the column
    out = tmp_path / "gallery.html"
    assert viewer.main(["--table", str(table),
                        "--words", "run,take,get,light",
                        "--out", str(out)]) == 0
    page = out.read_text(encoding="utf-8")
    assert page.count('tr class="summary"') == 37


def test_link_stats_none_method_no_crash():
    rows = [{"kaikki_sense_id": "x", "method": None,
             "evidence": "", "flags": ""}]
    stats = linker.link_stats(rows)
    assert stats["total"] == 1
    assert stats["stage"]["other"] == 1
    assert stats["unknown_methods"] == [None]
    counters = linker.telemetry_counters(rows)
    assert counters["total"] == 1
    assert counters["stage"]["other"] == 1


def test_export_record_schema_shape():
    row = _rows()[0]
    rec = viewer.export_record(row, {}, _cand_entry()["en-run-en-verb-A"],
                               "link_table_run20_v3.tsv#L12", n=1)
    assert rec["kid"] == "en-run-en-verb-A"
    assert rec["row_ref"] == "link_table_run20_v3.tsv#L12"
    assert rec["lemma"] == "run"
    assert rec["in_def"] == "To move fast."
    assert rec["decision"]["method"] == "LINK:2-sig"
    assert rec["decision"]["winner"] == "run%2:38:00::"
    assert rec["decision"]["locator"] == "38:00"
    assert {"sig", "val", "cut", "fired"} <= set(rec["fires"][0])
    assert rec["fires"][0]["sig"] == "lexical-overlap"
    assert rec["fires"][0]["cut"] == 0.2
    # winner_def full (never truncated), candidates full defs
    assert rec["candidates"][0]["rank"] == 1
    assert set(rec["candidates"][0]) == {"rank", "key", "j", "def"}
    assert rec["candidates"][1]["def"] == "move fast by using one's feet"
    assert set(rec["judge"]) == {"votes", "agree"}
    assert isinstance(rec["flags"], list)
    # per-record shape: no parallel-dict top level
    assert "records" not in rec and "glosses" not in rec
