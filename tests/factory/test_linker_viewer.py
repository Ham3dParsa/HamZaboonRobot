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
    # flow tracer: five nodes + four wires per card (Gemini build).
    for pos in ("1", "2", "3", "4", "5"):
        assert 'data-ftnode="%s"' % pos in page
    assert 'class="flowtrace-wirelist"' in page
    assert "ردیاب جریان پیوند" in page


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
    assert stats["unknown_methods"] == [""]
    counters = linker.telemetry_counters(rows)
    assert counters["total"] == 1
    assert counters["stage"]["other"] == 1


def test_link_stats_mixed_none_and_str_method_no_crash():
    # None mixed with str: sorted() over the raw keys raised TypeError.
    rows = [
        {"kaikki_sense_id": "a", "method": None,
         "evidence": "", "flags": ""},
        {"kaikki_sense_id": "b", "method": "LINK:2-sig",
         "evidence": "Sa:j=0.40", "flags": ""},
    ]
    stats = linker.link_stats(rows)
    assert stats["total"] == 2
    assert None not in stats["method_counts"]
    assert stats["method_counts"][""] == 1
    assert stats["unknown_methods"] == [""]


def test_trace_cand_why_no_verdict_row_winner():
    # LINK:2-sig row, {} verdict, empty evidence: winner is the row's own
    # sensekey, so the why-line must NOT claim a judge source.
    row = {"kaikki_sense_id": "k", "method": "LINK:2-sig",
           "evidence": "", "flags": "", "lemma": "run",
           "kaikki_gloss": "To move.",
           "wordnet_sensekey": "run%2:38:00::"}
    bare = viewer._render_trace(row, {})
    assert "نامزد برتر از داور آمد" not in bare
    assert "نامزد برتر ردیف است" in bare
    # verdict-present keeps the judge wording.
    judged = viewer._render_trace(row, {
        "verdict": "LINK", "winner_sensekey": "run%2:38:00::",
        "votes": [{"ok": True, "verdict": "LINK", "winner_index": 0}],
    })
    assert "نامزد برتر از داور آمد" in judged


def test_stage_mapping_single_source():
    from factory.linker.linker import _stats_stage, LINK_METHOD_VOCAB
    assert viewer._stage_of is _stats_stage
    for method in list(LINK_METHOD_VOCAB) + [None, "", "WAT"]:
        assert viewer._stage_of(method) == _stats_stage(method)


def test_js_norm_nfkc_parity():
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert 'normalize("NFKC")' in src
    # fullwidth query matches after NFKC (parity with normalize_search).
    assert viewer.normalize_search("ＲＵＮ") == "run"


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


def test_decision_rule_hostile_method_escaped_all_branches():
    hostile = 'LINK:2-sig"><script>alert(1)</script>'
    methods = [
        "LINK:exact-sensekey+2-sig" + hostile[11:],
        "LINK:judge-v2" + hostile[4:],
        "LINK:manual-override" + hostile[4:],
        hostile,
        "JUDGE-PENDING",
        "JUDGE-NONE",
        "WAT" + hostile,
    ]
    for method in methods:
        _rule, cmp_txt = viewer._decision_rule(method, 2)
        assert "<script>" not in cmp_txt, method
    # full gallery path: hostile TSV method cell must not break HTML
    rows = [dict(_rows()[0], method=hostile)]
    import pathlib as _pl
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        out = str(_pl.Path(tmp) / "gallery.html")
        viewer.build_linker_gallery(rows, [], out)
        page = _pl.Path(out).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# --- Flow tracer (owner-locked Gemini build) ---

def test_flow_trace_data_pure_model():
    row = {"kaikki_sense_id": "k", "lemma": "run",
           "kaikki_gloss": "To move fast.",
           "method": "LINK:2-sig",
           "wordnet_sensekey": "run%2:38:00::",
           "evidence": "Sa:j=0.40+Sd:hyp=move", "flags": ""}
    cands = {"top3": [
        {"sensekey": "run%2:38:11::", "gloss": "move about freely",
         "jaccard": 0.0, "lemmas": ["run"], "fires": ["Sd:hyp=move"]},
        {"sensekey": "run%2:38:00::",
         "gloss": "move fast by using one's feet",
         "jaccard": 0.1176, "lemmas": ["run"], "fires": []},
    ]}
    data = linker.flow_trace_data(row, {}, cands)
    assert data["kid"] == "k"
    assert data["winner"] == "run%2:38:00::"
    assert data["winner_locator"] == "38:00"
    # FULL defs, scores, winner flags per candidate.
    assert data["candidates"][1]["def"] == "move fast by using one's feet"
    assert data["candidates"][1]["j"] == 0.1176
    assert data["candidates"][1]["is_winner"] is True
    assert data["candidates"][0]["is_winner"] is False
    # signals carry exact words/scores.
    assert data["signals"][0]["alias"] == "Sa:j=0.40"
    assert data["signals"][1]["alias"] == "Sd:hyp=move"
    assert data["n_fires"] == 2
    # four wires, rule LINK bypasses the judge node.
    assert [(w["from"], w["to"]) for w in data["wires"]] == [
        (1, 2), (2, 3), (3, 4), (4, 5)]
    assert [w["status"] for w in data["wires"]] == [
        "success", "success", "bypassed", "success"]
    twin = linker.flow_trace_data(
        dict(row, method="twin-pending"), {}, None)
    assert twin["wires"][2]["status"] == "twin"
    assert twin["wires"][3]["status"] == "twin"
    assert twin["gate"] == "twin"
    assert twin["candidates"] == []


def test_gallery_flowtrace_nodes_winner_and_wires(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        _rows(), _verdicts_with_latency(), str(out),
        candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # five nodes per card, one flow block per card (HTML sections only;
    # the stylesheet also carries [data-ftnode] selectors).
    assert page.count('class="flowtrace"') == 5
    assert page.count(
        '<section class="flowtrace-node" data-ftnode="1"') == 5
    assert page.count(
        '<section class="flowtrace-node" data-ftnode="5"') == 5
    assert page.count("<svg") == page.count("</svg>")
    # winner candidate highlighted in node 2.
    assert "is-winner" in page
    # wires carry node-id refs + status + exact colors.
    assert 'data-from="1"' in page and 'data-to="2"' in page
    assert 'data-from="4"' in page and 'data-to="5"' in page
    for color in ("#10b981", "#f59e0b", "#f43f5e", "#c084fc", "#475569"):
        assert color in page
    # magnet ports on every node.
    assert page.count("magnet-port") >= 5 * 4


def test_gallery_flowtrace_gemini_strings_verbatim(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out),
                                candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # node titles verbatim (5/5).
    for title in ("معنی ورودی مبدأ", "غربالگری کاندیداها",
                  "ارزیابی سیگنال‌ها", "حل تعارض و داوری",
                  "فرجام پیوند و تکمیل"):
        assert title in page
    # per-node guide sentences verbatim.
    for guide in ("تعریف تحت بررسی:", "کلمات استخراج‌شده:",
                  "شناسه سنس:", "متادیتای ردیف مبدأ",
                  "تزریق فیلدهای وردنت:", "رکورد خروجی JSON",
                  "لیتنسی و بذرها", "هدایت نگاه:"):
        assert guide in page
    # concept tooltips verbatim (title + body).
    for tip in ("ضریب جاکارد (Jaccard)", "سینست (Locator)",
                "همزاد (Twin)", "بازبینی (Flip-Review)",
                "شاخص اشتراک واژگان", "کد مکان در وردنت",
                "تعارض همزاد", "پرچم هشدار کیفی"):
        assert tip in page
    # wire-color legend verbatim.
    assert "راهنمای نوری سیم‌ها:" in page
    for label in ("موفق / تأیید", "داوری / هشدار", "رد / مسدودسازی",
                  "تعارض دوقلو", "عبور داده شده"):
        assert label in page
    # technical proof beside the Gemini sentence (both appear).
    assert "Sa:j=0.40" in page
    assert "shortlist-jaccard" in page


def test_gallery_flowtrace_zero_http_no_arrows_no_coords(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # self-contained: no fetches. The only http URI allowed is the
    # literal SVG XML-namespace constant (never fetched).
    assert "https://" not in page
    assert "cdn" not in page
    # TASK4 fonts: the only url() allowed is the embedded data-URI @font-face.
    assert page.count("url(") == page.count("url(data:font/ttf;base64,")
    assert "fonts.googleapis" not in page
    assert (page.count("http://")
            == page.count("http://www.w3.org/2000/svg"))
    for char in ("▼", "▲", "◄", "►"):
        assert char not in page
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    # dynamic layout proof: rects + resize observer redraw.
    assert "getBoundingClientRect" in src
    assert "ResizeObserver" in src
    assert 'addEventListener("resize"' in src
    # forbidden: fixed presets, stored layouts, drag. Top-panel session
    # persistence (TASK1, gallery:top: keys) is the only localStorage use —
    # the flowtrace itself keeps no presets or stored layouts.
    assert "gallery:top:" in src
    assert "preset-select" not in src
    assert "flowtrace-preset" not in src
    assert "flowtrace" in src and "data-ftnode" in src


# --- Flow tracer locked spec: 3-col S-flow, per-row wiring, exact colors ---

def test_flowtrace_three_col_rtl_sflow(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # Ticket-locked 3-col RTL S-flow asserted ON THE RENDERED STRING
    # (not viewer source): right col nodes 1+2, middle col 3+4,
    # left col node 5; narrow screens stack to one column.
    assert "1fr 1.15fr 1fr" in page
    assert "direction: rtl" in page
    assert "grid-template-areas" not in page
    assert page.count('class="flowtrace-grid"') == 5
    # exactly 3 column wrapper divs per card (right 1+2, middle 3+4,
    # left 5); counted on div tags so the stylesheet can't inflate them.
    assert page.count('<div class="flowtrace-col ') == 5 * 3
    for cls in ("flowtrace-col-right", "flowtrace-col-mid",
                "flowtrace-col-left"):
        assert page.count(
            '<div class="flowtrace-col %s">' % cls) == 5, cls
    # node order in the string: 1,2 in right col / 3,4 in middle / 5 left.
    for pos in ("1", "2", "3", "4", "5"):
        assert page.count(
            '<section class="flowtrace-node" data-ftnode="%s"' % pos) == 5
    card1 = page.split('class="flowtrace-grid"')[1].split(
        'class="flowtrace-wirelist"')[0]
    order = [card1.find(tok) for tok in (
        "flowtrace-col-right", 'data-ftnode="1"', 'data-ftnode="2"',
        "flowtrace-col-mid", 'data-ftnode="3"', 'data-ftnode="4"',
        "flowtrace-col-left", 'data-ftnode="5"')]
    assert all(i >= 0 for i in order), order
    assert order == sorted(order), order
    # single-column fallback for narrow screens.
    assert "@media (max-width:" in page
    assert "grid-template-columns: minmax(0, 1fr)" in page


def test_flowtrace_per_row_wiring_not_scenarios(tmp_path):
    out = tmp_path / "gallery.html"
    rows = _rows()
    viewer.build_linker_gallery(rows, _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # no scenario bar: tracer count equals row count, keyed per-row kid.
    for token in ("scenario-bar", "flowtrace-scenario", "5-scenario"):
        assert token not in page
    assert page.count('class="flowtrace"') == len(rows)
    for row in rows:
        assert 'data-flowtrace="%s"' % row["kaikki_sense_id"] in page
    # every tracer carries its own status badge from its own row.
    assert page.count('class="flowtrace-status"') == len(rows)


def test_flowtrace_status_colors_exact():
    assert viewer._flowtrace_status(
        {"method": "JUDGE-REVIEW"}, {}) == ("REVIEW", "#f59e0b")
    assert viewer._flowtrace_status(
        {"method": "twin-pending"}, {}) == ("twin", "#c084fc")
    assert viewer._flowtrace_status(
        {"method": "LINK:2-sig"}, {}) == ("LINK", "#10b981")
    assert viewer._flowtrace_status(
        {"method": "JUDGE-NONE"}, {"verdict": "NONE"}) == (
        "NONE", "#ef4444")
    assert viewer._flowtrace_status(
        {"method": "JUDGE-PENDING"},
        {"vote_status": "FAILED", "votes": [{"ok": False}]}) == (
        "FAILED", "#ef4444")
    # Verdict-first (owner-locked): table-pending never masks the verdict.
    assert viewer._flowtrace_status(
        {"method": "JUDGE-PENDING"}, {"verdict": "LINK"}) == (
        "LINK", "#10b981")
    assert viewer._flowtrace_status(
        {"method": "JUDGE-PENDING"}, {"verdict": "NONE"}) == (
        "NONE", "#ef4444")
    assert viewer._flowtrace_status(
        {"method": "JUDGE-PENDING"}, {}) == ("REVIEW", "#f59e0b")


def test_flowtrace_status_badge_exact_hex(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts_with_latency(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    for color in ("#f59e0b", "#c084fc", "#10b981", "#ef4444", "#475569"):
        assert color in page


def test_flowtrace_gaps_fallback_and_filled_only(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out),
                                candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # empty row (no wordnet evidence) renders the honest fallback line.
    assert "هیچ فیلدی منتقل نشد" in page
    # filled row shows only filled gaps with check marks.
    assert "✓" in page
    assert "تکمیل فیلدها" in page
    # decision cuts live ONCE page-wide (global constants), never per card.
    assert page.count('id="global-thresholds"') == 1
    assert "flowtrace-math" not in page
    assert "flowtrace-thr" not in page
    # judge votes render as compact mini-cards.
    assert "vote-minis" in page
    assert "vote-mini" in page


def test_flowtrace_corridor_ports_and_safe_labels(tmp_path):
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    # corridor routing: vertical 1->2 / 3->4, S-curves 2->3 / 4->5.
    assert "fromId" in src and "toId" in src
    assert "Corridor routing" in src
    assert 'pa.bottom' in src and 'pb.top' in src
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "z-50" in page
    for char in ("▼", "▲", "◄", "►"):
        assert char not in page
        assert char not in src


def test_flowtrace_system_font_stack(tmp_path):
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert "system-ui" in src and "Segoe UI" in src
    assert "Tahoma" in src and "sans-serif" in src
    assert "fonts.googleapis" not in src
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "fonts.googleapis" not in page
    assert "https://" not in page


# --- External patch: candidate fallback + canonical wires + tooltip colors ---

def test_flowtrace_fallback_renders_winner_when_flow_candidates_empty():
    # Winner row with NO cand_entry: fallback must show candwinner,
    # never the empty "never reached this stage" message.
    row = {"kaikki_sense_id": "k", "method": "LINK:2-sig",
           "evidence": "Sa:j=0.40", "flags": "", "lemma": "run",
           "kaikki_gloss": "To move.",
           "wordnet_sensekey": "run%2:38:00::"}
    html_out = viewer._render_trace(row, {}, None)
    assert "candwinner" in html_out
    assert "run%2:38:00::" in html_out
    assert "هیچ کاندیدایی به این مرحله نرسید" not in html_out
    # Raw top3 fallback: flow model empty but caller entry present.
    cands = {"top3": [
        {"sensekey": "run%2:38:00::", "gloss": "move fast",
         "jaccard": 0.4, "lemmas": ["run"], "fires": []},
    ]}
    html_fb = viewer._render_trace(row, {}, cands)
    assert "رتبه 1" in html_fb
    assert "38:00" in html_fb


def test_flowtrace_canonical_wires_always_four():
    import re as _re
    rows = [
        {"kaikki_sense_id": "k1", "method": "LINK:2-sig",
         "evidence": "Sa:j=0.40+Sd:hyp=move", "flags": "",
         "lemma": "run", "kaikki_gloss": "To move.",
         "wordnet_sensekey": "run%2:38:00::"},
        {"kaikki_sense_id": "k2", "method": "UNMAPPED",
         "evidence": "0sig", "flags": "",
         "lemma": "run", "kaikki_gloss": "To own.",
         "wordnet_sensekey": "-"},
        {"kaikki_sense_id": "k3", "method": "twin-pending",
         "evidence": "Sa:j=0.3", "flags": "",
         "lemma": "run", "kaikki_gloss": "To move.",
         "wordnet_sensekey": "run%2:38:00::"},
    ]
    for row in rows:
        html_out = viewer._render_trace(row, {}, None)
        pairs = _re.findall(r'data-from="(\d)" data-to="(\d)"', html_out)
        assert pairs == [("1", "2"), ("2", "3"), ("3", "4"), ("4", "5")], row
    # UNMAPPED voteless tail wire holds (never judged → never a
    # rejection claim); twin row carries twin statuses.
    assert 'data-status="warn"' in viewer._render_trace(rows[1], {}, None)
    assert 'data-status="twin"' in viewer._render_trace(rows[2], {}, None)


def test_flowtrace_tooltip_colors_present(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    for color in ("#f59e0b", "#c084fc", "#38bdf8", "#f43f5e"):
        assert color in page
    assert "box-shadow:0 0 6px" in page


def test_flowtrace_wirelist_hidden():
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert ".flowtrace-wirelist { display: none !important;" in src
    assert "top: calc(100% + 6px)" in src


def test_flowtrace_label_strip_and_clear():
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert "halfW" in src and "65" in src and "halfH" in src
    assert "tSamples" in src
    assert "fromCharCode(9660" in src and ".trim()" in src
    assert "pair.a.x" in src


# --- Gallery top redress (S1/S2/S3) + export capsule + fonts + row-gap ---

def test_top_redress_collapsed_default_and_summary(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts_with_latency(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # S1: one-line summary strip on top with totals + coverage + expand.
    assert 'id="summary-strip"' in page
    assert "sumexpand" in page
    assert 'href="#sec-table"' in page
    assert "پوشش داور" in page
    # S1: all four diagnostic panels collapsed by default (no open attr).
    import re as _re
    for pid in ("panel-gauges", "panel-verdict", "panel-checks",
                "panel-latency-full"):
        m = _re.search(r'<details[^>]*id="%s"[^>]*>' % pid, page)
        assert m, pid
        assert "open" not in m.group(0), pid


def test_latency_strip_inside_judge_panel(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts_with_latency(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # S2: slim strip inside the judge section; full histogram one click away.
    assert 'id="latstrip"' in page
    assert page.count("class='latstrip-bar'") == 8
    assert "avg" in page and "p90" in page
    judge_sec = page.split('id="sec-judge"')[1].split('id="sec-table"')[0]
    assert 'id="latstrip"' in judge_sec
    assert 'id="lathist"' in judge_sec
    # full-width histogram row deleted: no latency block left in sec-gauges.
    gauges_sec = page.split('id="sec-gauges"')[1].split('id="sec-judge"')[0]
    assert 'id="lathist"' not in gauges_sec
    # strip budget: <=40px strip, <=28px mini-bars.
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert "max-height: 40px" in src
    assert "max-height: 28px" in src


def test_navpanel_filters_search_hash_state(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts_with_latency(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # ONE dropdown panel under the nav holding search + every filter key.
    assert 'id="navpanel"' in page
    assert 'id="navfilter"' in page and 'id="navsearch"' in page
    panel = page.split('id="navpanel"')[1].split('id="sec-gauges"')[0]
    assert 'id="search"' in panel and 'id="searchclear"' in panel
    for key in ("stage:link", "stage:quarantine", "sig:lexical-overlap",
                "sig:judge-vote", "judge:unanimous", "judge:concordant",
                "judge:split-vote",
                "outcome:LINK", "outcome:NONE"):
        assert 'data-fkey="%s"' % key in panel, key
    # advanced/rare keys hide in the second inner collapsible group.
    assert 'id="navpanel-advanced"' in page
    advanced = page.split('id="navpanel-advanced"')[1].split("</details>")[0]
    for key in ("outcome:FAILED", "src:mechanical", "check:link-evidence"):
        assert 'data-fkey="%s"' % key in advanced, key
    # old sprawling drawer rows are gone.
    assert 'id="filter-drawer"' not in page
    assert "drawer-group" not in page
    assert 'id="filter-clear"' in panel
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    # state in URL hash + clear-all; search/debounce/mark untouched.
    assert "location.hash" in src and "replaceState" in src
    assert "readHash" in src and "writeHash" in src
    assert "hashchange" in src
    assert "setTimeout" in src and "175" in src and "<mark>" in src


def test_export_capsule_grouping(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # TASK2: checkboxes live in a labeled group attached to the Export button.
    assert 'id="export-capsule"' in page
    cap = page.split('id="export-capsule"')[1].split("</div>")[0]
    assert 'id="exp-cand"' in cap and "checked" in cap
    assert 'id="exp-judge"' in cap
    assert 'id="export"' in cap
    assert "export includes" in cap
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    # file content only: filter/search matching never consults the toggles.
    matches_fn = src.split("function matches(")[1].split(
        "function paintHighlight")[0]
    assert "exp-cand" not in matches_fn and "exp-judge" not in matches_fn


def test_font_embedded_vazirmatn(tmp_path, monkeypatch):
    import re as _re
    # Hermetic: real C:\Windows\Fonts files don't exist on Linux CI —
    # point the embedding list at tiny tmp fixtures instead.
    f400 = tmp_path / "Vazirmatn-Regular.ttf"
    f700 = tmp_path / "Vazirmatn-Bold.ttf"
    f400.write_bytes(b"fake-regular-font-bytes")
    f700.write_bytes(b"fake-bold-font-bytes")
    monkeypatch.setattr(viewer, "_FONT_FILES", (
        ("Vazirmatn", 400, str(f400)),
        ("Vazirmatn", 700, str(f700)),
    ))
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # TASK4: Base64 @font-face for Regular(400)+Bold(700), offline.
    assert "@font-face" in page and "Vazirmatn" in page
    assert "font-weight:400" in page and "font-weight:700" in page
    uris = _re.findall(r"url\(data:font/ttf;base64,([A-Za-z0-9+/=]+)\)", page)
    assert len(uris) == 2
    for b64 in uris:
        assert len(b64) > 0  # payload present; real ~120KB files covered by manual QA
    # fallback stack stays; no downloads.
    assert '"Vazirmatn", system-ui' in page
    assert "Segoe UI" in page and "Tahoma" in page
    assert "fonts.googleapis" not in page and "https://" not in page


def test_flowtrace_row_gap_40():
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert "row-gap: 40px" in src


def test_concordant_link_never_claims_certainty(tmp_path):
    # Real run20 row: en-run-en-verb-~Hj7wpfX — 3× LINK#2 (same verdict +
    # same winner) but DIVERGENT quoted evidences: seed 42 quotes glosses,
    # seeds 43/44 quote examples. Same conclusion, different justification
    # → CONCORDANT, not unanimous.
    row = {"kaikki_sense_id": "en-run-en-verb-~Hj7wpfX",
           "wordnet_sensekey": "run%2:38:01::",
           "method": "JUDGE-PENDING", "evidence": "Sd:hyp=move",
           "flags": "", "lemma": "run", "kaikki_pos": "verb",
           "kaikki_gloss": "To flow rapidly."}
    verdict = {"kid": "en-run-en-verb-~Hj7wpfX", "lemma": "run",
               "verdict": "LINK", "winner_index": 2,
               "winner_sensekey": "run%2:38:11::",
               "votes": [
                   {"ok": True, "verdict": "LINK", "winner_index": 2,
                    "seed": 42, "latency_s": 7.9,
                    "kaikki_evidence": "To move or spread quickly.",
                    "wordnet_evidence": "move about freely and without "
                    "restraint, or act as if running around in an "
                    "uncontrolled way || words: run || eg: who are these "
                    "people running around in the building? || She runs "
                    "around telling everyone of her troubles"},
                   {"ok": True, "verdict": "LINK", "winner_index": 2,
                    "seed": 43, "latency_s": 7.64,
                    "kaikki_evidence": "There's a strange story running "
                    "around the neighborhood that you had a miscarriage "
                    "last year. || The flu is running through my "
                    "daughter's kindergarten.",
                    "wordnet_evidence": "who are these people running "
                    "around in the building? || She runs around telling "
                    "everyone of her troubles"},
                   {"ok": True, "verdict": "LINK", "winner_index": 2,
                    "seed": 44, "latency_s": 7.61,
                    "kaikki_evidence": "There's a strange story running "
                    "around the neighborhood that you had a miscarriage "
                    "last year. || The flu is running through my "
                    "daughter's kindergarten.",
                    "wordnet_evidence": "who are these people running "
                    "around in the building? || She runs around telling "
                    "everyone of her troubles"},
               ]}
    # tier is CONCORDANT, never UNANIMOUS.
    assert viewer.agreement_key(verdict) == "concordant"
    summary = viewer.verdict_summary([verdict])
    assert summary["concordant"] == 1
    assert summary["unanimous"] == 0
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([row], [verdict], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "هم‌نظر در رأی، متفاوت در دلیل (concordant)" in page
    assert "پس قطعی است" not in page
    assert "اجماع قاطع" not in page
    # judge-decided rows stay advisory (model vote, not certainty).
    assert "رأی مدل است" in page
    # concordant counts as needs-review (like split), not certain.
    assert "is-provisional" in page
    # distinct reasons: each quote once, with seed tags.
    # NOTE: split on the rendered div marker (the bare class name also
    # occurs in the <style> block, so a bare split lands in CSS).
    assert "class='flowtrace-reasons'" in page
    reasons = page.split("class='flowtrace-reasons'")[1].split("</ul>")[0]
    assert reasons.count("To move or spread quickly.") == 1
    assert reasons.count("strange story running around the neighborhood") == 1
    assert "seed 42" in reasons
    assert "seed 43" in reasons and "seed 44" in reasons


def test_full_unanimous_control(tmp_path):
    # Control: identical verdict + winner + identical evidences → UNANIMOUS.
    votes = [{"ok": True, "verdict": "LINK", "winner_index": 3,
              "seed": seed, "latency_s": 6.5,
              "kaikki_evidence": "To move forward quickly.",
              "wordnet_evidence": "move fast on foot"}
             for seed in (42, 43, 44)]
    verdict = {"kid": "en-run-en-verb-4acunXz3", "lemma": "run",
               "verdict": "LINK", "winner_index": 3,
               "winner_sensekey": "run%2:38:00::", "votes": votes}
    assert viewer.agreement_key(verdict) == "unanimous"
    summary = viewer.verdict_summary([verdict])
    assert summary["unanimous"] == 1
    assert summary["concordant"] == 0
    row = {"kaikki_sense_id": "en-run-en-verb-4acunXz3",
           "wordnet_sensekey": "run%2:38:00::",
           "method": "JUDGE-PENDING", "evidence": "Sd:hyp=move",
           "flags": "", "lemma": "run", "kaikki_pos": "verb",
           "kaikki_gloss": "To move fast."}
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([row], [verdict], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "هر ۳ داور هم‌نظر (unanimous)" in page


def test_split_vote_unchanged():
    # Votes differ (winner) → SPLIT, exactly as before.
    verdict = {"kid": "en-take-en-verb-D", "lemma": "take",
               "verdict": "LINK", "winner_index": 2,
               "votes": [
                   {"ok": True, "verdict": "LINK", "winner_index": 2,
                    "seed": 42,
                    "kaikki_evidence": "To cover a course.",
                    "wordnet_evidence": "move fast"},
                   {"ok": True, "verdict": "LINK", "winner_index": 1,
                    "seed": 43,
                    "kaikki_evidence": "To cover a course.",
                    "wordnet_evidence": "move fast"},
                   {"ok": True, "verdict": "LINK", "winner_index": 2,
                    "seed": 44,
                    "kaikki_evidence": "To cover a course.",
                    "wordnet_evidence": "move fast"},
               ]}
    assert viewer.agreement_key(verdict) == "split-vote"
    summary = viewer.verdict_summary([verdict])
    assert summary["split"] == 1
    assert summary["unanimous"] == 0 and summary["concordant"] == 0


def test_evidence_whitespace_only_difference_stays_unanimous():
    # strip + collapse-whitespace: padding/newlines alone are not divergence.
    verdict = {"kid": "k-ws", "votes": [
        {"ok": True, "verdict": "NONE", "winner_index": None,
         "seed": 42, "kaikki_evidence": "  To stall. ",
         "wordnet_evidence": "wait\naround"},
        {"ok": True, "verdict": "NONE", "winner_index": None,
         "seed": 43, "kaikki_evidence": "To stall.",
         "wordnet_evidence": "wait around"},
        {"ok": True, "verdict": "NONE", "winner_index": None,
         "seed": 44, "kaikki_evidence": "To  stall.",
         "wordnet_evidence": "wait  around"},
    ]}
    assert viewer.agreement_key(verdict) == "unanimous"


def test_verdict_summary_distinguishes_three_tiers():
    def _v(kid, tier):
        base = {"ok": True, "verdict": "LINK", "winner_index": 2,
                "kaikki_evidence": "gloss", "wordnet_evidence": "wn"}
        if tier == "unanimous":
            votes = [dict(base, seed=s) for s in (42, 43, 44)]
        elif tier == "concordant":
            votes = [dict(base, seed=42),
                     dict(base, seed=43, kaikki_evidence="example quote"),
                     dict(base, seed=44, kaikki_evidence="example quote")]
        else:
            votes = [dict(base, seed=42),
                     dict(base, seed=43, winner_index=1),
                     dict(base, seed=44)]
        return {"kid": kid, "votes": votes}
    summary = viewer.verdict_summary(
        [_v("k-u", "unanimous"), _v("k-c", "concordant"), _v("k-s", "split")])
    assert (summary["unanimous"], summary["concordant"], summary["split"],
            summary["judged"]) == (1, 1, 1, 3)


def test_candidates_top3_node2_with_winner(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        _rows(), _verdicts_with_latency(), str(out),
        candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    # TASK3 shape: node-2 shows the shortlist with winner highlight + FULL def.
    assert "رتبه 1" in page and "رتبه 2" in page
    assert "is-winner" in page
    # FULL def, never truncated (apostrophe is HTML-escaped by _esc).
    assert "move fast by using one" in page


# --- Owner gallery round 5 (defects A-G): DIFF-VIEW + key audit ---

def _mech_rows():
    # Mirrors real run20 mechanical methods (LINK:2-sig ×33,
    # LINK:exact-sensekey+2-sig ×12, LINK:3-sig ×1 — 46 total on disk),
    # plus judge-driven and pending rows that must NOT match.
    base = {"flags": "", "lemma": "run", "kaikki_pos": "verb",
            "kaikki_gloss": "To move."}
    return [
        dict(base, kaikki_sense_id="k-mech-2",
             wordnet_sensekey="run%2:38:01::", method="LINK:2-sig",
             evidence="Sa:j=0.20+Sb:flow"),
        dict(base, kaikki_sense_id="k-mech-exact",
             wordnet_sensekey="run%2:38:02::",
             method="LINK:exact-sensekey+2-sig",
             evidence="Sa:j=0.20+Sd:hyp=flow"),
        dict(base, kaikki_sense_id="k-mech-3",
             wordnet_sensekey="run%2:38:03::", method="LINK:3-sig",
             evidence="Sa:j=0.30+Sb:flow+Sd:hyp=go"),
        dict(base, kaikki_sense_id="k-judge",
             wordnet_sensekey="run%2:38:11::", method="LINK:judge-v2",
             evidence="Sb:course | judge:kaikki=\"x\" wordnet=\"y\""),
        dict(base, kaikki_sense_id="k-pend",
             wordnet_sensekey="-", method="JUDGE-PENDING",
             evidence="edge:obsolete+Sd:hyp=move"),
    ]


def _judged():
    return {"kid": "k-judge", "lemma": "run", "verdict": "LINK",
            "winner_index": 2, "winner_sensekey": "run%2:38:11::",
            "wordnet_evidence": "move about || words: run",
            "votes": [{"ok": True, "verdict": "LINK", "winner_index": 2,
                       "seed": 42, "kaikki_evidence": "To move.",
                       "wordnet_evidence": "move about"}]}


def test_mechanical_filter_returns_exactly_rule_links():
    # Defect A: the judge-less/mechanical filter isolates exactly the
    # no-verdict rule LINKs (run20 disk count: 46 = 33 + 12 + 1).
    rows = _mech_rows()
    verdicts = [_judged()]
    by_kid = {v["kid"]: v for v in verdicts}
    keyed = [(r["kaikki_sense_id"],
              viewer.row_filter_keys(r, by_kid.get(r["kaikki_sense_id"], {})))
             for r in rows]
    hit = {kid for kid, keys in keyed
           if viewer.row_matches_filters(keys, {"src:mechanical"})}
    assert hit == {"k-mech-2", "k-mech-exact", "k-mech-3"}
    # Audit: raw evidence tokens never become sig: keys.
    for _kid, keys in keyed:
        for key in keys:
            assert not key.startswith("sig:edge"), keys
            assert not key.startswith("sig:inventory"), keys
            assert not key.startswith("sig:judge-first"), keys
            assert not key.startswith("sig:no-candidates"), keys
            assert not key.startswith("sig:best-cand"), keys
    pend_keys = dict(keyed)["k-pend"]
    assert "sig:hypernym-topic" in pend_keys
    assert "src:mechanical" not in pend_keys


def test_mechanical_node2_winner_def_paths():
    # Defect B: mechanical LINKs have no candidate pack (0/46 in run20) —
    # node-2 states the missing pack explicitly, shows the WINNER key,
    # and either its definition (row wordnet data present) or an honest
    # gap. Never a silent empty node.
    base = {"kaikki_sense_id": "k", "method": "LINK:2-sig",
            "evidence": "Sa:j=0.20+Sb:flow", "flags": "", "lemma": "run",
            "kaikki_gloss": "To flow.",
            "wordnet_sensekey": "run%2:38:01::"}
    with_def = viewer._render_trace(
        dict(base, wordnet_gloss="Of a liquid, to flow."), {}, None)
    assert "کاندیداها در بسته نیست" in with_def
    assert "shortlist recompute" in with_def
    assert "run%2:38:01::" in with_def
    assert "Of a liquid, to flow." in with_def
    bare = viewer._render_trace(dict(base), {}, None)
    assert "کاندیداها در بسته نیست" in bare
    assert "run%2:38:01::" in bare
    assert "winner-def-missing" in bare


def test_rule_winner_naming_and_badge(tmp_path):
    # Defect C: a rule win shows its REAL Persian rule name + the
    # mechanical-link badge (m-rule), distinct from the judge LINK badge.
    assert viewer._rule_fa("LINK:2-sig") == "پیوند قاعده‌ای: ۲ سیگنال مستقل"
    assert viewer._rule_fa(
        "LINK:exact-sensekey+2-sig") == "پیوند قاعده‌ای: کلیددقیق + ۲ سیگنال"
    assert "قاعده" not in viewer._rule_fa("LINK:3-sig").replace(
        "قاعده‌ای", "")
    for method, name in (
            ("LINK:2-sig", "پیوند قاعده‌ای: ۲ سیگنال مستقل"),
            ("LINK:3-sig", "پیوند قاعده‌ای: ۳ سیگنال مستقل"),
            ("LINK:exact-sensekey+2-sig",
             "پیوند قاعده‌ای: کلیددقیق + ۲ سیگنال")):
        badge = viewer._method_badge(method)
        assert 'class="badge m-rule"' in badge, method
        assert name in badge, method
        assert method in badge, method
    judge_badge = viewer._method_badge("LINK:judge-v2")
    assert 'class="badge m-link"' in judge_badge
    assert "m-rule" not in judge_badge
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_mech_rows(), [_judged()], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "پیوند قاعده‌ای: ۲ سیگنال مستقل" in page
    assert "badge m-rule" in page


def test_flowtrace_node_card_grammar(tmp_path):
    # Defect D (PIC-2): every node 1-5 is header (title + badge) / body /
    # footer (meta chips). Colors/wires/tooltips/RTL untouched.
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out),
                                candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    for pos in ("1", "2", "3", "4", "5"):
        sec = page.split(
            '<section class="flowtrace-node" data-ftnode="%s"' % pos
        )[1].split("</section>")[0]
        assert 'class="ft-head"' in sec, pos
        assert "flowtrace-nodetitle" in sec, pos
        assert ("ft-badge" in sec or "badge m-" in sec), pos
        assert 'class="ft-body"' in sec, pos
        assert 'class="ft-foot"' in sec, pos
        assert "ft-chip" in sec, pos
    import pathlib as _pl
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert ".ft-head" in src and ".ft-body" in src and ".ft-foot" in src
    assert ".ft-foot" in src and "11px" in src


def _unanimous_verdict():
    votes = [{"ok": True, "verdict": "LINK", "winner_index": 3,
              "seed": seed, "latency_s": 6.5,
              "kaikki_evidence": "To move forward quickly upon two feet.",
              "wordnet_evidence": "move fast by using one's feet"}
             for seed in (42, 43, 44)]
    return {"kid": "en-run-en-verb-4acunXz3", "lemma": "run",
            "verdict": "LINK", "winner_index": 3,
            "winner_sensekey": "run%2:38:00::", "votes": votes}


def test_identical_votes_render_once_with_multiplier(tmp_path):
    # Defect E: 4acunXz3-style unanimous (3 identical quotes) renders ONE
    # reason + ×3; per-vote blocks appear only for differing content.
    verdict = _unanimous_verdict()
    row = {"kaikki_sense_id": "en-run-en-verb-4acunXz3",
           "wordnet_sensekey": "run%2:38:00::",
           "method": "JUDGE-PENDING", "evidence": "Sd:hyp=move",
           "flags": "", "lemma": "run", "kaikki_pos": "verb",
           "kaikki_gloss": "To move fast."}
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([row], [verdict], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node4 = page.split(
        '<section class="flowtrace-node" data-ftnode="4"')[1].split(
        "</section>")[0]
    assert node4.count("move fast by using one") == 1
    assert node4.count("نقل دلیل") == 1
    assert "×3" in node4
    assert node4.count("class='agree-line'") == 1


def test_node5_single_source_winner_def_and_flag_chips(tmp_path):
    # Defect F: flags are COLOR chips; winner_def appears exactly once in
    # node-5 (gap-def cross-references it); gaps are field←source rows.
    # B1: the def comes from the candidate pack (definition field); the
    # judge quote renders on its own labeled line, never as the def.
    wdef = "move fast by using one's feet, with one foot off the ground"
    row = {"kaikki_sense_id": "k5", "wordnet_sensekey": "run%2:38:00::",
           "method": "LINK:2-sig", "evidence": "Sa:j=0.40+Sd:hyp=move",
           "flags": "provisional_consensus", "lemma": "run",
           "kaikki_pos": "verb", "kaikki_gloss": "To move fast."}
    verdict = {"kid": "k5", "verdict": "LINK", "winner_sensekey":
               "run%2:38:00::",
               "wordnet_evidence": wdef + " || words: run",
               "votes": []}
    cands = {"top3": [{"sensekey": "run%2:38:00::", "gloss": wdef,
                       "jaccard": 0.4, "lemmas": ["run"], "fires": []}]}
    flow_def = wdef  # pack gloss feeds node-5, never the quote
    assert viewer._node5_winner_def(
        row, verdict, "run%2:38:00::", cands) == ("def", flow_def)
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        [row], [verdict], str(out), candidates={"k5": cands})
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node5 = page.split(
        '<section class="flowtrace-node" data-ftnode="5"')[1].split(
        "</section>")[0]
    # winner line carries the FULL pack definition...
    assert "تعریف برنده: “<bdi>%s</bdi>”" % viewer._esc(wdef) in node5
    # ...the quote lives on its own labeled line, never as the def...
    assert "نقل‌قول پشتیبان داور" in node5
    assert "support-quote" in node5
    assert "example-shown-as-def" not in node5
    # ...and the gap-def row cross-references it instead of repeating.
    assert "همان تعریف برنده (بالا)" in node5
    assert "←" in node5
    assert "flagchip flag-prov" in node5
    assert "badge m-rule" in node5
    # method code lives once (node-5 header badge); decision cross-refs it.
    assert node5.count("LINK:2-sig") == 1
    assert "method-in-header" in node5


def test_concordant_collapses_agreement_to_one_line(tmp_path):
    # Defect G (~Hj7wpfX): agreements collapse to ONE line
    # (verdict+winner ×3); ONLY divergences expand (seed-42 quote vs the
    # seeds-43+44 quote pair, the latter merged with ×2).
    row = {"kaikki_sense_id": "en-run-en-verb-~Hj7wpfX",
           "wordnet_sensekey": "run%2:38:01::",
           "method": "JUDGE-PENDING", "evidence": "Sd:hyp=move",
           "flags": "", "lemma": "run", "kaikki_pos": "verb",
           "kaikki_gloss": "To flow rapidly."}
    verdict = {"kid": "en-run-en-verb-~Hj7wpfX", "lemma": "run",
               "verdict": "LINK", "winner_index": 2,
               "winner_sensekey": "run%2:38:11::",
               "votes": [
                   {"ok": True, "verdict": "LINK", "winner_index": 2,
                    "seed": 42, "latency_s": 7.9,
                    "kaikki_evidence": "To move or spread quickly.",
                    "wordnet_evidence": "move about freely"},
                   {"ok": True, "verdict": "LINK", "winner_index": 2,
                    "seed": 43, "latency_s": 7.64,
                    "kaikki_evidence": "A strange story running around.",
                    "wordnet_evidence": "running around in the building"},
                   {"ok": True, "verdict": "LINK", "winner_index": 2,
                    "seed": 44, "latency_s": 7.61,
                    "kaikki_evidence": "A strange story running around.",
                    "wordnet_evidence": "running around in the building"},
               ]}
    assert viewer.agreement_key(verdict) == "concordant"
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([row], [verdict], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node4 = page.split(
        '<section class="flowtrace-node" data-ftnode="4"')[1].split(
        "</section>")[0]
    assert node4.count("class='agree-line'") == 1
    assert "×3" in node4
    assert node4.count("To move or spread quickly.") == 1
    assert node4.count("A strange story running around.") == 1
    assert "×2" in node4


# --- Owner round 5: per-case scores / signal sentences / winner-def
# fallback / version+changelog / navbar panel ---

def test_thresholds_once_pagewide_percard_scores(tmp_path):
    # Item 1: cuts render ONCE page-wide; per-card blocks carry only
    # this case's numbers (candidate shortlist-jaccards, fired-signal
    # words/scores, vote winners, tier/seed) with no cut duplication.
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts_with_latency(), str(out),
                                candidates=_cand_entry())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert page.count('id="global-thresholds"') == 1
    assert "global decision constants" in page
    # per-card threshold repeats are gone (glossary row, thr paragraph,
    # foot chip); the cut code-chips appear exactly once (global block).
    assert "flowtrace-thr" not in page
    assert page.count("<bdi>jaccard</bdi>") == 1
    assert page.count("<bdi>link_min</bdi>") == 1
    # per-card numbers survive: candidate shortlist scores, fired exact
    # words/scores, vote seeds, tier/seed line.
    assert "shortlist-jaccard" in page
    assert "0.1176" in page
    assert "نمره جاکارد" in page and "0.40" in page
    assert "seed" in page
    assert "verdict-tier" in page
    # uniformity assert helper: frozen constants => one signature.
    assert len(viewer._threshold_signatures(_rows())) == 1


def test_signal_sentences_and_muted_codes(tmp_path):
    # Item 2: every fired signal is a full FA sentence (WHAT matched
    # WHAT + WHY it counts); codes survive only muted beside; the
    # shoot glossary explains «شلیک» once page-wide.
    assert "ابرنام/موضوع مشترک" in viewer._signal_exact(
        "hypernym-topic", "Sd:hyp=move")
    assert "move" in viewer._signal_exact("hypernym-topic", "Sd:hyp=move")
    assert "۱ امتیاز" in viewer._signal_exact("hypernym-topic", "Sd:hyp=move")
    assert "0.40" in viewer._signal_exact("lexical-overlap", "Sa:j=0.40")
    assert "course" in viewer._signal_exact(
        "synonym-crossfire", "Sb:course")
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node3 = page.split(
        '<section class="flowtrace-node" data-ftnode="3"')[1].split(
        "</section>")[0]
    assert "پس ۱ امتیاز" in node3
    assert "<span class='why'>" in node3
    assert "<span class='code'>" in node3
    assert "شلیک = سیگنال شمرده‌شده" in node3
    assert "vote/point" in page


def test_winner_def_example_fallback_t2XxCWy5(tmp_path):
    # Item 3 regression (repurposed: single-source _node5_winner_def):
    # t2XxCWy5-style verdict quotes a BARE example sentence as
    # wordnet_evidence (no "||" structure) — the gallery must label it
    # as a support quote, never show it as a definition.
    row = {"kaikki_sense_id": "en-run-en-verb-t2XxCWy5",
           "wordnet_sensekey": "run%2:38:11::",
           "method": "JUDGE-PENDING", "evidence": "Sd:hyp=move",
           "flags": "", "lemma": "run", "kaikki_pos": "verb",
           "kaikki_gloss": "To move briskly."}
    verdict = {"kid": "en-run-en-verb-t2XxCWy5", "lemma": "run",
               "verdict": "LINK", "winner_index": 1,
               "winner_sensekey": "run%2:38:11::", "tier": "VOTE",
               "wordnet_evidence":
               "who are these people running around in the building?",
               "votes": []}
    assert viewer._node5_winner_def(
        row, verdict, "run%2:38:11::", None) == ("missing", "")
    assert viewer._support_quote(verdict) == (
        "example-quote",
        "who are these people running around in the building?")
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([row], [verdict], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "support-quote-example" in page
    assert "who are these people running around in the building?" in page
    # never rendered as a winner definition...
    assert "تعریف برنده: “<bdi>who are these people" not in page
    # ...nor transferred into the def gap with a check mark.
    node5 = page.split(
        '<section class="flowtrace-node" data-ftnode="5"')[1].split(
        "</section>")[0]
    assert "همان تعریف برنده (بالا)" not in node5
    rec = viewer.export_record(row, verdict, None, "t.tsv#L2", n=1)
    assert rec["winner_def"].startswith(
        "[support-quote-example (upstream)]")


def test_gallery_version_and_changelog(tmp_path):
    # Item 4: footer carries the gallery version + dated changelog.
    import re as _re
    assert _re.fullmatch(r"\d+\.\d+\.\d+", viewer.GALLERY_VERSION)
    assert len(viewer.GALLERY_CHANGELOG) >= 5
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert ("linker gallery v%s" % viewer.GALLERY_VERSION) in page
    assert "gallery changelog" in page
    for date, line in viewer.GALLERY_CHANGELOG:
        assert date in page and line in page


# --- Owner round 6: sticky toolbar (item 1) + compact judge node (item 3) ---

def test_sticky_toolbar_filter_search_entry_points(tmp_path):
    # Item 1: the top droplet nav is position:sticky (always visible)
    # and carries the filter + search ENTRY points (buttons opening the
    # SAME panel/input, not duplicates). No scroll-to-top ever.
    import pathlib as _pl
    import re as _re
    src = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    nav_css = _re.search(r"nav\.pillnav \{(.*?)\}", src, _re.S).group(1)
    assert "position: sticky" in nav_css
    panel_css = _re.search(r"\.navpanel \{(.*?)\}", src, _re.S).group(1)
    assert "position: sticky" in panel_css  # open filters stay usable
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    nav = page.split('<nav class="pillnav"')[1].split("</nav>")[0]
    # both entry points live IN the sticky nav, wired to the same panel
    assert 'id="navfilter"' in nav and 'aria-controls="navpanel"' in nav
    assert 'id="navsearch"' in nav and 'aria-controls="navpanel"' in nav
    # ONE shared search input + ONE shared panel (no duplicates)
    assert page.count('id="search"') == 1
    assert page.count('id="navpanel"') == 1
    # both buttons drive the SAME setPanel handler (shared toggle ids)
    js = src.split("var navpanel =")[1].split("readHash();")[0]
    assert 'getElementById("navfilter")' in js
    assert 'getElementById("navsearch")' in js
    assert js.count("setPanel(") >= 3  # def + filter toggle + search open
    # owner rule: no scroll-to-top ever (CSS smooth scroll is not a button)
    for tok in ("scroll-to-top", "scrolltop", "back-to-top", "backtotop",
                "window.scrollTo", "scrollIntoView"):
        assert tok.lower() not in src.lower(), tok
        assert tok.lower() not in page.lower(), tok


def _t2XxCWy5_compact():
    row = {"kaikki_sense_id": "en-run-en-verb-t2XxCWy5",
           "wordnet_sensekey": "run%2:38:11::",
           "method": "JUDGE-PENDING", "evidence": "Sd:hyp=move",
           "flags": "", "lemma": "run", "kaikki_pos": "verb",
           "kaikki_gloss": "To move briskly."}
    gloss = "To move briskly or smoothly."
    wn = "who are these people running around in the building?"
    votes = [{"ok": True, "verdict": "LINK", "winner_index": 1,
              "seed": seed, "latency_s": lat,
              "kaikki_evidence": gloss, "wordnet_evidence": wn}
             for seed, lat in ((42, 15.22), (43, 6.96), (44, 7.13))]
    verdict = {"kid": "en-run-en-verb-t2XxCWy5", "lemma": "run",
               "verdict": "LINK", "winner_index": 1,
               "winner_sensekey": "run%2:38:11::", "tier": "VOTE",
               "wordnet_evidence": wn, "votes": votes}
    return row, verdict, gloss, wn


def test_compact_judge_node_t2XxCWy5(tmp_path):
    # Item 3 (owner mock, verbatim structure): header (title + LLM badge
    # + latency-seeds collapsible); verdict line ONCE; winner line ONCE;
    # latencies inline; single نقل دلیل quote (dedup identical);
    # seeds line once; flags line once; چرا once. No repeated blocks.
    row, verdict, gloss, wn = _t2XxCWy5_compact()
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([row], [verdict], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node4 = page.split(
        '<section class="flowtrace-node" data-ftnode="4"')[1].split(
        "</section>")[0]
    # header: title + LLM badge + latency-seeds collapsible, each once
    assert "هر ۳ داور هم‌نظر (unanimous)" in node4
    assert node4.count("هیئت داوری LLM") == 1
    assert node4.count("jlatseeds") == 1
    # verdict line ONCE with ×3; winner line ONCE (sensekey in both = 2)
    assert node4.count("class='agree-line'") == 1
    assert node4.count("رأی:") == 1
    assert "×3" in node4
    assert node4.count("class='jwinner'") == 1
    assert node4.count("run%2:38:11::") == 2
    # details: latencies inline, each once
    for lat in ("15.2s", "7.0s", "7.1s"):
        assert node4.count(lat) == 1, lat
    # single نقل دلیل quote (identical ×3 deduped); both sides quoted once
    assert node4.count("نقل دلیل") == 1
    assert node4.count(gloss) == 1
    assert node4.count(wn) == 1
    # seeds line once; flags line once; چرا once
    assert node4.count("seed 42") == 1
    assert node4.count("seed 43") == 1
    assert node4.count("seed 44") == 1
    assert node4.count("پرچم‌ها:") == 1
    assert node4.count("چرا:") == 1
    # retired repetitions are gone: per-vote badges, gatebody winner
    # repeat, techhead label inside the judged node
    assert 'class="vote ' not in node4
    assert "flowtrace-techhead" not in node4
    assert "رأی‌ها:" not in node4


def _pending_wire_row(kid="en-run-en-verb-4acunXz3", flags=""):
    return {"kaikki_sense_id": kid,
            "wordnet_sensekey": "run%2:38:11::",
            "method": "JUDGE-PENDING", "evidence": "Sd:hyp=move",
            "flags": flags, "lemma": "run", "kaikki_pos": "verb",
            "kaikki_gloss": "To move forward quickly."}


def _pending_wire_verdict(kid="en-run-en-verb-4acunXz3", verdict="LINK"):
    votes = [{"ok": True, "verdict": verdict, "winner_index": 3,
              "seed": seed, "latency_s": 6.5,
              "kaikki_evidence": "To move forward quickly.",
              "wordnet_evidence": "move fast on foot"}
             for seed in (42, 43, 44)]
    return {"kid": kid, "lemma": "run",
            "verdict": verdict, "winner_index": 3,
            "winner_sensekey": "run%2:38:00::", "votes": votes}


def _wire45(page):
    """(status, label) of the judge→outcome wire in a one-card gallery."""
    import re as _re
    m = _re.search(r'data-from="4" data-to="5"[^>]*data-status="([^"]+)"'
                   r'[^>]*data-color="[^"]*">([^<]*)', page)
    assert m, "4→5 wire missing"
    return m.group(1), m.group(2)


def test_pending_unanimous_link_wire_approves(tmp_path):
    # Target: en-run-en-verb-4acunXz3 — JUDGE-PENDING row, unanimous
    # 3×LINK verdict. Verdict-first (owner-locked): the judge→outcome
    # wire approves (success), table-pending is a node-5 fact instead.
    row = _pending_wire_row()
    verdict = _pending_wire_verdict()
    assert viewer.agreement_key(verdict) == "unanimous"
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([row], [verdict], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    status, label = _wire45(page)
    assert (status, label) == ("success", "تأیید پیوند")
    assert "رد قطعی داور" not in page
    # referral wire still warns (was referred to judge); both truths stay.
    assert 'data-from="3" data-to="4"' in page
    assert "آرای یکدست" in page and "JUDGE-PENDING" in page
    # vote-count lock: one agree line ×3 for three ok votes.
    assert page.count("class='agree-line'") == 1
    assert "×3" in page
    # table-consumption pending shown at node-5, never on the wire.
    assert "pending-table" in page


def test_pending_unanimous_none_wire_rejects(tmp_path):
    # Same class, NONE verdict: unanimous no-link votes on a still-pending
    # row reject (fail) — verdict-first; the node-5 pending-table note
    # still records that the table hasn't consumed it.
    row = _pending_wire_row(kid="en-run-en-verb-6lDuK7AI")
    verdict = _pending_wire_verdict(kid="en-run-en-verb-6lDuK7AI",
                                    verdict="NONE")
    assert viewer.agreement_key(verdict) == "unanimous"
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([row], [verdict], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    status, label = _wire45(page)
    assert (status, label) == ("fail", "رد قطعی داور")
    assert "pending-table" in page


def test_pending_voteless_wire_holds_and_stays_provisional(tmp_path):
    # No-verdict pending row: honest "not yet reached judge" text with a
    # holding wire (never a rejection claim); a provisional flag on a
    # unanimous card likewise holds without contradicting the badge.
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery([_pending_wire_row()], [], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "هنوز به داور نرسیده" in page
    status, _label = _wire45(page)
    assert status == "warn"
    assert "رد قطعی داور" not in page
    out2 = tmp_path / "gallery2.html"
    viewer.build_linker_gallery(
        [_pending_wire_row(flags="provisional_hold")],
        [_pending_wire_verdict()], str(out2))
    page2 = pathlib.Path(str(out2)).read_text(encoding="utf-8")
    # provisional flag + unanimous LINK verdict: amber card styling holds
    # the row back while the verdict-driven wire still approves — both
    # truths visible, no contradiction.
    assert "is-provisional" in page2 and "آرای یکدست" in page2
    status2, label2 = _wire45(page2)
    assert (status2, label2) == ("success", "تأیید پیوند")


# --- Verdict-first sweep (owner round 5): one regression test per class ---

def test_verdict_wire45_helper_mapping():
    # linker.verdict_wire45 owns the 4→5 mapping (viewer calls it).
    assert linker.verdict_wire45(
        {"verdict": "LINK"}, "JUDGE-PENDING", "run%2:38:00::") == {
        "from": 4, "to": 5, "label": "تأیید پیوند", "status": "success"}
    assert linker.verdict_wire45(
        {"verdict": "NONE"}, "JUDGE-PENDING", "-") == {
        "from": 4, "to": 5, "label": "رد قطعی داور", "status": "fail"}
    assert linker.verdict_wire45({}, "JUDGE-PENDING", "run%2:38:11::") == {
        "from": 4, "to": 5, "label": "توقف جهت بازبینی", "status": "warn"}
    # verdict-less mechanical rule LINK still approves; twin stays twin.
    assert linker.verdict_wire45(
        {}, "LINK:2-sig", "run%2:38:00::")["status"] == "success"
    assert linker.verdict_wire45(
        {}, "twin-pending", "-") == {
        "from": 4, "to": 5, "label": "تعلیق پیوند در صف دوقلوها",
        "status": "twin"}


def test_card_winner_prefers_verdict_key(tmp_path):
    # 4acunXz3 shape: table cell 38:11, judge winner 38:00. The card
    # declares the judge key everywhere: data-winner attr, node-5
    # locator, and the candidate highlight (rank 3 gets is-winner + ✓).
    row = _pending_wire_row()
    verdict = _pending_wire_verdict()
    assert viewer._card_winner(row, verdict) == "run%2:38:00::"
    assert viewer._card_winner(row, {}) == "run%2:38:11::"
    cands = {"top3": [
        {"sensekey": "run%2:38:11::", "gloss": "g1",
         "jaccard": 0.3, "lemmas": ["run"], "fires": []},
        {"sensekey": "run%2:38:01::", "gloss": "g2",
         "jaccard": 0.2, "lemmas": ["run"], "fires": []},
        {"sensekey": "run%2:38:00::", "gloss": "g3",
         "jaccard": 0.1, "lemmas": ["run"], "fires": []},
    ]}
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        [row], [verdict], str(out),
        candidates={row["kaikki_sense_id"]: cands})
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert 'data-winner="run%2:38:00::"' in page
    import re as _re
    winners = _re.findall(
        r'<li class="is-winner">رتبه (\d) ✓ · کلید <bdi class=\'wkey\'>'
        r'([^<]+)</bdi>', page)
    assert winners == [("3", "run%2:38:00::")], winners
    # node-5 locator follows the judge key, not the stale table cell.
    node5 = page.split(
        '<section class="flowtrace-node" data-ftnode="5"')[1].split(
        "</section>")[0]
    assert "38:00" in node5 and "38:11" not in node5


def test_node5_pending_note_only_for_pending_tables(tmp_path):
    # JUDGE-PENDING rows carry the consumption note at node-5;
    # consumed (rule-LINK) rows never do.
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        [_pending_wire_row()], [_pending_wire_verdict()], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "flowtrace-pending" in page
    assert "table-not-consumed" in page
    out2 = tmp_path / "gallery2.html"
    viewer.build_linker_gallery([_rows()[0]], [], str(out2))
    page2 = pathlib.Path(str(out2)).read_text(encoding="utf-8")
    assert "flowtrace-pending" not in page2
    assert "table-not-consumed" not in page2


def test_agreement_counts_sum_to_ok_votes():
    # vote-blocks vs verdict line: grouped ×N counts always sum to the
    # ok-vote count, for unanimous / split / concordant shapes.
    import re as _re
    for votes in (
        [{"ok": True, "verdict": "LINK", "winner_index": 1}] * 3,
        [{"ok": True, "verdict": "LINK", "winner_index": 1},
         {"ok": True, "verdict": "LINK", "winner_index": 1},
         {"ok": True, "verdict": "NONE", "winner_index": 2}],
    ):
        html_out = viewer._render_agreement_lines({"votes": votes})
        counts = [int(n) for n in _re.findall(r"×(\d+)", html_out)]
        bare = html_out.count("agree-line") - len(counts)
        assert sum(counts) + bare == 3, html_out
        assert html_out.count("agree-line") <= 2, html_out


def test_counts_reconcile_run20_mix():
    # gauges vs rows: stage buckets (minus orthogonal provisional) sum to
    # total; pie LINK+NONE+FAILED sums to verdict total — run20 mix shape
    # (pending+LINK, pending+NONE, pending voteless, rule LINK, UNMAPPED).
    rows = [_pending_wire_row(kid="k%d" % i) for i in range(3)]
    rows += [_rows()[0], _rows()[2]]
    verdicts = [_pending_wire_verdict(kid="k0", verdict="LINK"),
                _pending_wire_verdict(kid="k1", verdict="NONE")]
    checks = viewer.quality_checks(rows, verdicts)
    row = {c["id"]: c for c in checks}["counts-reconcile"]
    assert row["status"] == "PASS", row
    tele = linker.telemetry_counters(rows)
    assert (tele["stage"]["pending"] == 3 and tele["stage"]["link"] == 1
            and tele["stage"]["unmapped"] == 1)
    judge = viewer.verdict_summary(verdicts)
    assert judge["link"] + judge["none"] + judge["failed"] == 2


# --- Phase 2: search panel + categorized filters ---

def test_navpanel_collapsed_default_with_close(tmp_path):
    # Search/filter panel collapsed on load (hidden) with a visible
    # CLOSE (×) button that collapses it.
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert '<div class="navpanel" id="navpanel" hidden>' in page
    assert 'id="navclose"' in page
    assert "× بستن" in page
    import pathlib as _pl
    js = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    assert 'getElementById("navclose")' in js
    assert "setPanel(false" in js


def test_navpanel_compact_css_constraints():
    # Compact by construction: max-height + width caps on the panel so
    # it can never fill a tablet viewport; compact search input.
    import pathlib as _pl
    css = _pl.Path(viewer.__file__).read_text(encoding="utf-8")
    panel = css.split(".navpanel {")[1].split("}")[0]
    assert "max-height:" in panel and "max-width:" in panel
    assert "overflow-y:" in panel
    assert ".navsearch #search" in css


def test_advanced_group_membership_per_key():
    # Advanced/rare keys live inside the collapsed «پیشرفته» group;
    # common keys stay visible outside it; nothing sprawls ungrouped.
    import re as _re
    html_out = viewer._render_navpanel()
    assert "پیشرفته" in html_out
    main, advanced = html_out.split('<details class="panel-advanced"')
    for key in ("outcome:FAILED", "src:mechanical"):
        assert ('data-fkey="%s"' % key) in advanced, key
        assert ('data-fkey="%s"' % key) not in main, key
    for check_id, _fa, _en in viewer._CHECKS:
        assert ('data-fkey="check:%s"' % check_id) in advanced, check_id
    for key in ("stage:link", "stage:pending", "sig:lexical-overlap",
                "judge:unanimous", "outcome:LINK", "outcome:NONE"):
        assert ('data-fkey="%s"' % key) in main, key
    # every filter button sits inside a labeled panel-group (no sprawl).
    groups = _re.findall(
        r'<div class="panel-group"><h3>(.*?)</h3>(.*?)</div>', html_out)
    grouped_keys = _re.findall(r'data-fkey="([^"]+)"',
                               "".join(g[1] for g in groups))
    all_keys = _re.findall(r'data-fkey="([^"]+)"', html_out)
    assert sorted(grouped_keys) == sorted(all_keys)
    assert all(g[0].strip() for g in groups)  # every group labeled


# --- Run-version display (owner-ordered): gallery version + source-run version ---

_RUN20_PROV = ("rules:v0.6-equiv:se=None:STOP=base:seed=20260918:build=run20:"
              "factory-linker=origin/feat/precard-linker@dd84cc2")
_RUN21_PROV = ("rules:v0.7-se:se=all-MiniLM:STOP=base:seed=20260919:build=run21:"
              "factory-linker=origin/feat/precard-linker@ee11aa2")


def _prov_row(kid, provenance):
    return {"kaikki_sense_id": kid, "wordnet_sensekey": "run%2:38:00::",
            "method": "LINK:2-sig", "evidence": "Sa:j=0.40",
            "flags": "", "lemma": "run", "kaikki_pos": "verb",
            "kaikki_gloss": "To move.", "provenance": provenance}


def test_parse_run_provenance_triple_tail_and_absent():
    assert linker.parse_run_provenance(_RUN20_PROV) == {
        "rules": "v0.6-equiv", "build": "run20", "seed": "20260918"}
    # judge tail after "|" never perturbs the run triple.
    assert linker.parse_run_provenance(
        _RUN20_PROV + "|judge-v2:pass1:3-0:LINK/1") == {
        "rules": "v0.6-equiv", "build": "run20", "seed": "20260918"}
    # legacy / inventory / empty provenances are absent — never guessed.
    assert linker.parse_run_provenance(
        "linker-v0.6:link_table_v0_7.tsv") is None
    assert linker.parse_run_provenance("inventory:tsv-twin") is None
    assert linker.parse_run_provenance("rules:v0.6-equiv:se=None") is None
    assert linker.parse_run_provenance("") is None
    assert linker.parse_run_provenance(None) is None


def test_run_version_single_source(tmp_path):
    rows = [_prov_row("k1", _RUN20_PROV),
            _prov_row("k2", _RUN20_PROV + "|judge-v2:pass1:3-0:LINK/1")]
    info = linker.run_version(rows)
    assert info["status"] == "single"
    assert info["label"] == "run20 (v0.6-equiv)"
    assert (info["build"], info["rules"], info["seed"]) == (
        "run20", "v0.6-equiv", "20260918")
    out = tmp_path / "gallery.html"
    summary = viewer.build_linker_gallery(rows, [], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "data: run20 (v0.6-equiv)" in page
    assert "viewer: 4.1.1" in page
    assert summary["run_version"]["status"] == "single"


def test_run_version_mixed_majority_never_wins(tmp_path):
    # 3x run20 + 1x run21: majority must NOT win — mixed label.
    rows = [_prov_row("k%d" % i, _RUN20_PROV) for i in range(3)]
    rows.append(_prov_row("k9", _RUN21_PROV))
    info = linker.run_version(rows)
    assert info["status"] == "mixed"
    assert info["label"] == "mixed"
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(rows, [], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "data: mixed" in page
    assert "viewer: 4.1.1" in page
    # run20 shape on disk: rules triple rows + inventory rows disagree too.
    mixed2 = linker.run_version(
        [_prov_row("k1", _RUN20_PROV),
         _prov_row("k2", "inventory:tsv-twin")])
    assert mixed2["status"] == "mixed"
    assert mixed2["label"] == "mixed"


def test_run_version_absent_unknown(tmp_path):
    assert linker.run_version([])["label"] == "unknown (absent)"
    assert linker.run_version(
        [_prov_row("k1", ""), _prov_row("k2", "")])["status"] == "unknown"
    # legacy provenances carry no run triple — unknown, never guessed.
    legacy = linker.run_version(
        [_prov_row("k1", "linker-v0.6:link_table_v0_7.tsv")])
    assert legacy["status"] == "unknown"
    assert legacy["label"] == "unknown (absent)"
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(_rows(), _verdicts(), str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    assert "data: unknown (absent)" in page
    assert "viewer: 4.1.1" in page


def test_run_version_help_documents_both(tmp_path):
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        [_prov_row("k1", _RUN20_PROV)], [], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    help_sec = page.split('id="sec-help"')[1].split("</section>")[0]
    # run version = which linker build made the DATA ...
    assert "run version" in help_sec
    assert "which linker build made the data" in help_sec.lower()
    # ... gallery version = which viewer renders it.
    assert "gallery version" in help_sec
    assert "which viewer renders it" in help_sec.lower()


# --- PR #774 blockers (A1/A2/A3) + neighbor session (B1/B2) ---

def test_n_fires_counts_only_canonical_signals():
    # A1: edge:obsolete is a non-canonical evidence token — it must not
    # inflate the rule quorum (node-3 needs 2 REAL signals).
    row = {"kaikki_sense_id": "k", "lemma": "run",
           "kaikki_gloss": "To move.", "method": "JUDGE-PENDING",
           "wordnet_sensekey": "-", "evidence": "edge:obsolete+Sd:hyp=move",
           "flags": ""}
    data = linker.flow_trace_data(row, {}, None)
    assert data["n_fires"] == 1
    assert linker.CANON_SIGNAL_NAMES >= {
        "lexical-overlap", "synonym-crossfire", "example-crossfire",
        "hypernym-topic", "meaning-similarity", "short-definition",
        "no-signal", "judge-vote"}
    assert viewer._CANON_SIG_NAMES == linker.CANON_SIGNAL_NAMES
    # judge-tail tokens never count either.
    row2 = dict(row, evidence="Sa:j=0.40+judge-first")
    assert linker.flow_trace_data(row2, {}, None)["n_fires"] == 1


def test_verdict_wire45_failed_vote_holds_not_approves():
    # A2: a LINK verdict with a FAILED judge run must hold (warn),
    # never approve green — mirroring _flowtrace_status (failed ≠ LINK).
    held = linker.verdict_wire45(
        {"verdict": "LINK", "vote_status": "FAILED"},
        "JUDGE-PENDING", "k")
    assert (held["status"], held["label"]) == ("warn", "توقف جهت بازبینی")
    nonok = linker.verdict_wire45(
        {"verdict": "LINK",
         "votes": [{"ok": True, "verdict": "LINK", "winner_index": 1},
                   {"ok": False, "verdict": "LINK", "winner_index": 1}]},
        "JUDGE-PENDING", "k")
    assert (nonok["status"], nonok["label"]) == ("warn", "توقف جهت بازبینی")
    # healthy LINK verdicts still approve.
    ok = linker.verdict_wire45(
        {"verdict": "LINK",
         "votes": [{"ok": True, "verdict": "LINK", "winner_index": 1}]},
        "JUDGE-PENDING", "k")
    assert (ok["status"], ok["label"]) == ("success", "تأیید پیوند")


def test_gallery_seq_resets_between_builds(tmp_path):
    # A3: id anchors must not depend on process history — two builds
    # in the same process yield identical ids starting at ft-1-1.
    import re as _re
    rows = _rows()[:2]
    out1 = tmp_path / "g1.html"
    viewer.build_linker_gallery(rows, _verdicts(), str(out1))
    out2 = tmp_path / "g2.html"
    viewer.build_linker_gallery(rows, _verdicts(), str(out2))
    ids1 = _re.findall(r'id="ft-(\d+)-(\d)"',
                       pathlib.Path(str(out1)).read_text(encoding="utf-8"))
    ids2 = _re.findall(r'id="ft-(\d+)-(\d)"',
                       pathlib.Path(str(out2)).read_text(encoding="utf-8"))
    assert ids1 == ids2
    assert ids1[0] == ("1", "1")


def test_node5_example_quote_never_becomes_winner_def(tmp_path):
    # B1 (t2XxCWy5 shape, v4.1b row en-get-en-verb-~ybLNLQA): the judge
    # quotes a BARE example as wordnet_evidence while the candidate pack
    # carries the FULL winner definition. Node-5 must show the pack
    # definition as the winner def AND label the quote separately —
    # never the example as the definition.
    row = {"kaikki_sense_id": "en-get-en-verb-~ybLNLQA",
           "wordnet_sensekey": "get%2:40:00::",
           "method": "JUDGE-REVIEW",
           "evidence": "short-gloss:0sig | judge:kaikki=\"To getter.\" "
                       "wordnet=\"She got a lot of paintings from her uncle\"",
           "flags": "judge-v2:3-0", "lemma": "get",
           "kaikki_pos": "verb", "kaikki_gloss": "To getter."}
    verdict = {"kid": "en-get-en-verb-~ybLNLQA", "lemma": "get",
               "verdict": "LINK",
               "winner_sensekey": "get%2:40:00::",
               "wordnet_evidence":
               "She got a lot of paintings from her uncle",
               "votes": []}
    pack_def = "come into the possession of something concrete or abstract"
    cands = {"top3": [
        {"sensekey": "get%2:40:00::", "gloss": pack_def,
         "jaccard": -1.0, "lemmas": ["acquire", "get"], "fires": []},
    ]}
    assert viewer._node5_winner_def(
        row, verdict, "get%2:40:00::", cands) == ("def", pack_def)
    assert viewer._support_quote(verdict) == (
        "example-quote", "She got a lot of paintings from her uncle")
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        [row], [verdict], str(out),
        candidates={"en-get-en-verb-~ybLNLQA": cands})
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node5 = page.split(
        '<section class="flowtrace-node" data-ftnode="5"')[1].split(
        "</section>")[0]
    # winner line shows the FULL pack definition...
    assert "تعریف برنده: “<bdi>%s</bdi>”" % pack_def in node5
    # ...the example is labeled as a support quote, never as the def.
    assert "تعریف برنده: “<bdi>She got a lot" not in node5
    assert "نقل‌قول پشتیبان داور" in node5
    assert "(مثال، نه تعریف)" in node5
    assert "support-quote-example" in node5
    rec = viewer.export_record(
        row, verdict, cands, "t.tsv#L2", n=1)
    assert rec["winner_def"] == pack_def


def _b2_row(kid, method, evidence, flags):
    return {"kaikki_sense_id": kid, "wordnet_sensekey": "-",
            "method": method, "evidence": evidence, "flags": flags,
            "lemma": "get", "kaikki_pos": "verb",
            "kaikki_gloss": "To getter."}


def test_v41b_methods_flags_badges_meanings_wires(tmp_path):
    # B2: v4.1b methods/flags render with their OWN badge + one-line FA
    # meaning — never reduced to plain LINK/NONE. Wire behavior is the
    # already-defined mapping (asserted, not changed).
    import re as _re
    shapes = [
        # (kid, method, evidence, flags, verdict, badge, fa, wire45)
        ("b2-review", "JUDGE-REVIEW", "Sd:hyp=x+gatesR-REVIEW-B",
         "judge-v2:3-0+gatesR-REVIEW-B", {"verdict": "LINK"},
         "بازبینی داور", "gatesR-REVIEW-B", "success"),
        ("b2-none", "JUDGE-NONE", "0sig", "judge-none+judge-v2:3-0",
         {"verdict": "NONE"}, "بدون‌پیوند داور", "judge-none", "fail"),
        ("b2-prov", "LINK:judge-v2", "Sd:hyp=x",
         "judge-v2:2-1+provisional_consensus+provisional-hold",
         {"verdict": "LINK"}, "پیوند با داور", "توقف موقت", "success"),
        ("b2-quar", "quarantined-known-false", "Sa:j=0.33",
         "quarantined-known-false", {}, "قرنطینه خطای شناخته‌شده",
         "quarantined-known-false", "warn"),
        ("b2-twin", "twin-pending", "Sa:j=0.3", "twin-pending", {},
         "دوقلوی معلق", "twin-pending", "twin"),
    ]
    for kid, method, evidence, flags, verdict, badge, fa, wire in shapes:
        row = _b2_row(kid, method, evidence, flags)
        verdict = dict({"kid": kid}, **verdict)
        out = tmp_path / ("%s.html" % kid)
        viewer.build_linker_gallery([row], [verdict], str(out))
        page = pathlib.Path(str(out)).read_text(encoding="utf-8")
        # distinct badge + method code, never a plain LINK/NONE badge.
        assert badge in page, kid
        assert method in page, kid
        # one-line FA meaning for the method/flag surface.
        assert fa in page, kid
        status, _label = _wire45(page)
        assert status == wire, (kid, status)
    # gate-reason extractor: codes verbatim, order kept, no invention.
    assert viewer._review_gate_reason(
        {"evidence": "Sd:hyp=x+gatesR-REVIEW-B+prov-review",
         "flags": "judge-v2:3-0+gatesR-REVIEW-B"}) == ["gatesR-REVIEW-B"]
    assert viewer._review_gate_reason(
        {"evidence": "0sig", "flags": "flip-review"}) == ["flip-review"]
    assert viewer._review_gate_reason(
        {"evidence": "0sig", "flags": ""}) == []
    # review card shows the recorded reason + human-review frame.
    out = tmp_path / "b2-review2.html"
    row = _b2_row("b2-r2", "JUDGE-REVIEW", "Sd:hyp=x+gatesR-REVIEW-A",
                  "judge-v2:3-0+gatesR-REVIEW-A")
    viewer.build_linker_gallery([row], [{"kid": "b2-r2"}], str(out))
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node4 = page.split(
        '<section class="flowtrace-node" data-ftnode="4"')[1].split(
        "</section>")[0]
    assert "gatesR-REVIEW-A" in node4
    assert "بازبینی انسانی" in node4
    # voteless review row: no verdict to follow → the wire holds.
    status, _label = _wire45(page)
    assert status == "warn"
    # provisional pair: consensus + hold each get their amber chip + FA.
    assert viewer._flag_fa("provisional_consensus") == "اجماع موقت"
    assert viewer._flag_fa("provisional-hold") == "توقف موقت"


def test_flowtrace_status_failed_beats_link_verdict():
    # FINDING 1: LINK verdict + FAILED judge run must NOT show LINK-green.
    # Status and wire must agree (FAILED-red + warn hold).
    row = {"kaikki_sense_id": "k-failed-link", "method": "JUDGE-PENDING",
           "evidence": "Sd:hyp=move", "flags": ""}
    verdict = {"verdict": "LINK", "vote_status": "FAILED",
               "winner_sensekey": "run%2:38:00::",
               "votes": [{"ok": False, "verdict": "LINK",
                          "winner_index": 1}]}
    assert viewer._flowtrace_status(row, verdict) == ("FAILED", "#ef4444")
    wire = linker.verdict_wire45(verdict, "JUDGE-PENDING",
                                 "run%2:38:00::")
    assert (wire["status"], wire["label"]) == ("warn", "توقف جهت بازبینی")


def test_packless_example_only_renders_labeled_quote_never_def():
    # FINDING 2: pack-less row with example-only evidence routes through
    # _node5_winner_def (missing) + labeled support-quote, never bare def.
    row = {"kaikki_sense_id": "k-packless", "method": "LINK:2-sig",
           "evidence": "Sa:j=0.20", "flags": "", "lemma": "run",
           "kaikki_gloss": "To move.",
           "wordnet_sensekey": "run%2:38:00::"}
    verdict = {"wordnet_evidence":
               "She got a lot of paintings from her uncle"}
    assert viewer._node5_winner_def(
        row, verdict, "run%2:38:00::", None) == ("missing", "")
    html_out = viewer._render_trace(row, verdict, None)
    assert "support-quote-example" in html_out
    assert "She got a lot of paintings from her uncle" in html_out
    assert "تعریف برنده: “<bdi>She got a lot" not in html_out
    rec = viewer.export_record(row, verdict, None, "t.tsv#L2", n=1)
    assert rec["winner_def"].startswith(
        "[support-quote-example (upstream)]")
    assert rec["winner_def"] != "She got a lot of paintings from her uncle"


# --- Mechanical LINK winner-def via build-time WordNet (n9BROLz0) ---

def _n9_shape_row():
    # Owner-reported shape: mechanical LINK:exact-sensekey+2-sig, no
    # verdict, no candidate pack, no definition fields.
    return {"kaikki_sense_id": "en-run-en-verb-n9BROLz0",
            "wordnet_sensekey": "run%2:38:01::",
            "method": "LINK:exact-sensekey+2-sig",
            "evidence": "Sa:j=0.20+Sb:flow+Se:0.515",
            "flags": "", "lemma": "run", "kaikki_pos": "verb",
            "kaikki_gloss": "To flow rapidly."}


def _fake_wordnet_resolver():
    # Hermetic fake: the 38:01 gloss a real WordNet boot would return.
    return {"run%2:38:01::": "move along, of liquids || words: run; flow"}


def test_mech_wordnet_resolver_src_priority():
    row = _n9_shape_row()
    # No resolver: honest missing (today's behavior, unchanged).
    assert viewer._node5_winner_def(
        row, {}, "run%2:38:01::", None) == ("missing", "")
    assert viewer._winner_def_src(
        row, {}, "run%2:38:01::", None) == "missing"
    # Fake resolver: def + wordnet provenance.
    assert viewer._node5_winner_def(
        row, {}, "run%2:38:01::", None,
        _fake_wordnet_resolver()) == (
            "def", "move along, of liquids || words: run; flow")
    assert viewer._winner_def_src(
        row, {}, "run%2:38:01::", None,
        _fake_wordnet_resolver()) == "wordnet"
    # Callable resolvers work too; hostile resolver output never crashes.
    assert viewer._resolve_wordnet_def(
        "run%2:38:01::", lambda k: "callable gloss") == "callable gloss"
    assert viewer._resolve_wordnet_def(
        "run%2:38:01::", lambda k: 1 / 0) == ""
    # Existing sources beat wordnet (priority unchanged).
    pack = {"top3": [{"sensekey": "run%2:38:01::", "gloss": "pack gloss"}]}
    assert viewer._winner_def_src(
        row, {}, "run%2:38:01::", pack,
        _fake_wordnet_resolver()) == "pack"
    assert viewer._winner_def_src(
        row, {"winner_gloss": "verdict gloss"}, "run%2:38:01::", pack,
        _fake_wordnet_resolver()) == "verdict"
    assert viewer._winner_def_src(
        dict(row, wordnet_gloss="row gloss"), {}, "run%2:38:01::", pack,
        _fake_wordnet_resolver()) == "row"


def test_mech_wordnet_node5_and_node2_gallery(tmp_path):
    row = _n9_shape_row()
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        [row], [], str(out),
        winner_def_resolver=_fake_wordnet_resolver())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node5 = page.split(
        '<section class="flowtrace-node" data-ftnode="5"')[1].split(
        "</section>")[0]
    # Node-5 shows the 38:01 definition with its wordnet provenance...
    assert "move along, of liquids" in node5
    assert "lblsrc:wordnet" in node5
    assert "winner-def-missing" not in node5
    # ...and the gap-def row carries the same source.
    assert "همان تعریف برنده (بالا)" in node5
    node2 = page.split(
        '<section class="flowtrace-node" data-ftnode="2"')[1].split(
        "</section>")[0]
    # Node-2 shows winner key + resolved def + method badge, no dead end.
    assert "candwinner" in node2
    assert "run%2:38:01::" in node2
    assert "move along, of liquids" in node2
    assert "LINK:exact-sensekey+2-sig" in node2
    assert "lblsrc:wordnet" in node2
    assert "winner-def-missing" not in node2
    rec = viewer.export_record(row, {}, None, "t.tsv#L18", n=18,
                               winner_def_resolver=_fake_wordnet_resolver())
    assert rec["winner_def"] == "move along, of liquids || words: run; flow"
    assert rec["winner_def_src"] == "wordnet"


def test_mech_wordnet_missing_everywhere_stays_honest(tmp_path):
    # Resolver covers nothing: the honest missing label stays (existing).
    row = dict(_n9_shape_row(), wordnet_sensekey="run%2:99:99::")
    assert viewer._node5_winner_def(
        row, {}, "run%2:99:99::", None,
        _fake_wordnet_resolver()) == ("missing", "")
    out = tmp_path / "gallery.html"
    viewer.build_linker_gallery(
        [row], [], str(out),
        winner_def_resolver=_fake_wordnet_resolver())
    page = pathlib.Path(str(out)).read_text(encoding="utf-8")
    node5 = page.split(
        '<section class="flowtrace-node" data-ftnode="5"')[1].split(
        "</section>")[0]
    assert "winner-def-missing" in node5
    assert "lblsrc:wordnet" not in node5
    rec = viewer.export_record(row, {}, None, "t.tsv#L18", n=18,
                               winner_def_resolver=_fake_wordnet_resolver())
    assert rec["winner_def"] == ""
    assert rec["winner_def_src"] == "missing"
