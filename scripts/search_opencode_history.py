"""Search local OpenCode conversation history without spending tokens.

Reads the on-disk opencode SQLite store read-only (never the live bot DB)
and finds sessions whose message parts mention the given keywords.
Zero network, zero LLM, zero tokens.

Usage (Windows PowerShell):
  python scripts/search_opencode_history.py "کشینگ معنایی"
  python scripts/search_opencode_history.py "کاندیداهای sense" query-cache
  python scripts/search_opencode_history.py --any کش ویس کشینگ
  python scripts/search_opencode_history.py --project TaggerBot 550
  python scripts/search_opencode_history.py --all-projects کش
  python scripts/search_opencode_history.py --since 2026-09-01 "کشینگ معنایی"
  python scripts/search_opencode_history.py --list-projects
  python scripts/search_opencode_history.py "ویس" --out results.txt

Each positional arg is one term; pass a multi-word phrase as a single
quoted arg and it matches as an exact phrase (after Persian normalization).
Default semantics: AND (a part matches only if it contains ALL terms).
Use --any for OR (a part matches if it contains ANY term).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
import time

DB = "file:C:/Users/HamedParsa/.local/share/opencode/opencode.db?mode=ro"

# Arabic/Persian digit variants -> ASCII, for normalization.
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("0123456789")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})

# Arabic diacritics + tatweel + superscript alef: stripped for recall.
_DIACRITICS = re.compile("[\u064b-\u0652\u0670\u0640]")


def normalize_fa(s):
    """Persian-tolerant normalization for recall (applied to terms and content)."""
    if not s:
        return ""
    s = s.lower()
    s = s.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    s = s.replace("\u200c", " ").replace("\u200d", "")  # ZWNJ -> space, ZWJ dropped
    s = s.replace("\ufeff", "")  # BOM
    s = _DIACRITICS.sub("", s)
    s = s.translate(_DIGIT_MAP)
    return " ".join(s.split())


def connect():
    return sqlite3.connect(DB, uri=True)


def list_projects(con):
    rows = con.execute(
        "select id, worktree, time_created from project order by time_created"
    ).fetchall()
    for pid, worktree, created in rows:
        n = con.execute(
            "select count(*) from session where project_id = ?", (pid,)
        ).fetchone()[0]
        print("%s  sessions=%d  %s" % (pid[:8], n, worktree))


def resolve_project(con, override, all_projects):
    """Return (project_id or None, label). Default: auto-detect from cwd."""
    if all_projects:
        return None, "all projects"
    if override:
        row = con.execute(
            "select id, worktree from project where worktree like ?",
            ("%" + override + "%",),
        ).fetchone()
        if row is None:
            return None, "NO-MATCH:%s" % override
        return row[0], row[1]
    cwd = os.path.normpath(os.getcwd()).replace("\\", "/")
    row = con.execute(
        "select id, worktree from project"
        " where lower(replace(worktree, '\\', '/')) = lower(?)",
        (cwd,),
    ).fetchone()
    if row:
        return row[0], row[1] + " (auto from cwd)"
    base = os.path.basename(cwd.rstrip("/")) or cwd
    row = con.execute(
        "select id, worktree from project where worktree like ?",
        ("%" + base + "%",),
    ).fetchone()
    if row:
        return row[0], row[1] + " (auto from cwd basename)"
    return None, "all projects (cwd %s matched nothing)" % cwd


def snippet(text, terms, width=120):
    """First window around any raw term; falls back to first word of a term."""
    low = text.lower()
    for term in terms:
        hit = low.find(term.lower())
        if hit < 0 and " " in term.strip():
            hit = low.find(term.strip().split()[0].lower())
        if hit >= 0:
            start = max(0, hit - width // 2)
            frag = text[start:hit + len(term) + width // 2]
            frag = " ".join(frag.split())
            if len(frag) > width + len(term):
                frag = frag[: width + len(term)] + "..."
            return term, frag
    # Term matched only after normalization (e.g. Arabic ي/ك variants):
    # fall back to the head of the text so the hit still shows context.
    head = " ".join(text.split())[:width] + "..."
    return terms[0] if terms else "", head


def part_text(data):
    try:
        obj = json.loads(data)
    except (TypeError, ValueError):
        return "", str(data or "")
    if isinstance(obj, dict):
        ptype = obj.get("type")
        for key in ("text", "value", "content", "input"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return ptype, val
        return ptype, json.dumps(obj, ensure_ascii=False)[:2000]
    return None, str(obj)[:2000]


def parse_since(value):
    try:
        dt = datetime.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise SystemExit("--since must be YYYY-MM-DD, got %r" % value)
    return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)


def search(con, norm_terms, raw_terms, project_id, project_label,
           limit=15, snippets=2, match_any=False, since_ms=None,
           exclude_prefix=None, text_only=True, out_path=None):
    t0 = time.perf_counter()
    mode = "ANY" if match_any else "ALL"

    def part_matches(norm_text):
        if match_any:
            return any(t in norm_text for t in norm_terms)
        return all(t in norm_text for t in norm_terms)

    # Candidate parts: SQL prefilter keeps it fast on ~468k rows.
    # Text-only (default) skips tool/reasoning/step JSON blobs via LIKE.
    type_filter = (
        "and p.data like '%\"type\":\"text\"%'" if text_only else ""
    )
    proj_filter = "and s.project_id = ?" if project_id else ""
    since_filter = "and s.time_updated >= ?" if since_ms else ""
    args = []
    if project_id:
        args.append(project_id)
    if since_ms:
        args.append(since_ms)
    rows = con.execute(
        "select p.session_id, p.data from part p"
        " join session s on s.id = p.session_id"
        " where 1 = 1 %s %s %s" % (type_filter, proj_filter, since_filter),
        args,
    ).fetchall()

    now_ms = int(time.time() * 1000)
    hits = {}      # sid -> matching part count
    first_text = {}  # sid -> first matching text (for snippets)
    for sid, data in rows:
        if exclude_prefix and sid.startswith(exclude_prefix):
            continue
        ptype, text = part_text(data)
        if text_only and ptype is not None and ptype != "text":
            continue
        if not text or not part_matches(normalize_fa(text)):
            continue
        hits[sid] = hits.get(sid, 0) + 1
        if sid not in first_text:
            first_text[sid] = text

    # Title/slug bonus: sessions whose title matches count even with 0 part hits.
    meta = {}
    for sid in list(hits):
        r = con.execute(
            "select s.title, s.slug, s.time_created, s.time_updated"
            " from session s where s.id = ?", (sid,),
        ).fetchone()
        if r:
            meta[sid] = r
    if norm_terms:
        extra_args = list(args)
        title_rows = con.execute(
            "select s.id, s.title, s.slug, s.time_created, s.time_updated"
            " from session s where 1 = 1 %s %s" % (proj_filter, since_filter),
            extra_args,
        ).fetchall()
        for sid, title, slug, created, updated in title_rows:
            if exclude_prefix and sid.startswith(exclude_prefix):
                continue
            hay = normalize_fa((title or "") + " " + (slug or ""))
            ok = (any(t in hay for t in norm_terms) if match_any
                  else all(t in hay for t in norm_terms))
            if ok:
                meta.setdefault(sid, (title, slug, created, updated))
                hits[sid] = hits.get(sid, 0) + 3  # title bonus, shown in score

    # Ranking: score = hits * 30/(30+age_days) — hit count with recency decay.
    ranked = []
    for sid, n in hits.items():
        title, slug, created, updated = meta.get(sid, ("?", "?", 0, now_ms))
        age_days = max(0.0, (now_ms - (updated or now_ms)) / 86400000.0)
        score = round(n * 30.0 / (30.0 + age_days), 2)
        ranked.append((score, n, age_days, updated, sid, title, slug))
    ranked.sort(key=lambda r: (-r[0], -(r[3] or 0)))
    ranked = ranked[:limit]
    dt = time.perf_counter() - t0

    lines = []
    lines.append("project: %s | mode: %s | text-only: %s | scanned=%d parts in %.2fs"
                 % (project_label, mode, text_only, len(rows), dt))
    lines.append("score = hits * 30/(30+age_days); title match adds +3 hits")
    lines.append("sessions matched: %d" % len(ranked))
    for score, n, age, updated, sid, title, slug in ranked:
        lines.append("=" * 70)
        lines.append("score=%.2f hits=%d age=%.0fd  %s  %s"
                     % (score, n, age, sid[:8], (title or slug or "?")[:60]))
        shown = 0
        seed = first_text.get(sid)
        if seed:
            term, frag = snippet(seed, raw_terms)
            if frag:
                lines.append("  [%s] %s" % (term, frag[:220]))
                shown += 1
        if shown < snippets:
            for (data,) in con.execute(
                "select p.data from part p where p.session_id = ?"
                + (" and p.data like '%\"type\":\"text\"%'" if text_only else "")
                + " order by p.time_created limit 400",
                (sid,),
            ):
                ptype, text = part_text(data)
                if text_only and ptype is not None and ptype != "text":
                    continue
                if not text or not part_matches(normalize_fa(text)) or text == seed:
                    continue
                term, frag = snippet(text, raw_terms)
                if frag:
                    lines.append("  [%s] %s" % (term, frag[:220]))
                    shown += 1
                if shown >= snippets:
                    break
    out = "\n".join(lines)
    print(out)
    if out_path:
        # utf-8-sig: safe for BOM-sensitive Windows readers; stdout untouched.
        with open(out_path, "w", encoding="utf-8-sig") as fh:
            fh.write(out + "\n")
        print("wrote %s" % out_path)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keywords", nargs="*",
                    help="terms; a quoted multi-word arg matches as a phrase")
    ap.add_argument("--project", default=None,
                    help="project worktree substring (default: auto-detect from cwd;"
                    " use --all-projects to skip)")
    ap.add_argument("--all-projects", action="store_true")
    ap.add_argument("--list-projects", action="store_true")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--snippets", type=int, default=2)
    ap.add_argument("--any", action="store_true",
                    help="OR semantics (default: AND — part must contain all terms)")
    ap.add_argument("--since", default=None,
                    help="only sessions updated on/after YYYY-MM-DD")
    ap.add_argument("--exclude-session", default=None,
                    help="skip sessions whose id starts with this prefix")
    ap.add_argument("--include-tools", action="store_true",
                    help="also match tool/reasoning/step blobs (default: text parts only)")
    ap.add_argument("--out", default=None, help="also write output file (utf-8-sig)")
    args = ap.parse_args(argv)
    con = connect()
    if args.list_projects:
        list_projects(con)
        return 0
    if not args.keywords:
        ap.error("give at least one keyword")
    pid, label = resolve_project(con, args.project, args.all_projects)
    if label.startswith("NO-MATCH"):
        print(label)
        return 1
    raw_terms = [k.strip("\"“”'").strip() for k in args.keywords]
    raw_terms = [t for t in raw_terms if t]
    norm_terms = [normalize_fa(t) for t in raw_terms]
    norm_terms = [t for t in norm_terms if t]
    if not norm_terms:
        ap.error("keywords normalize to nothing")
    since_ms = parse_since(args.since) if args.since else None
    return search(con, norm_terms, raw_terms, pid, label, args.limit,
                  args.snippets, args.any, since_ms, args.exclude_session,
                  text_only=not args.include_tools, out_path=args.out)


if __name__ == "__main__":
    raise SystemExit(main())
