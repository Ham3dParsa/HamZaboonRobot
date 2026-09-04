"""Fetch Coxhead Academic Word List (AWL) families (TICKET F3).

Downloads the 10 AWL sublist pages from Victoria University of Wellington
LALS resources, parses ``<p>headword</p><ul><li>members…`` to headwords
(lowercase, affix markers like "*" stripped), and saves JSON
``{metadata, families: {family: [members]}}`` atomically (temp + os.replace).

Public research data (Coxhead 2000, Victoria University of Wellington).
If the source is unreachable the script aborts fail-closed (SystemExit) —
it never invents data.

Usage:
    python factory/fetch_awl.py [--out PATH] [--base-url URL] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import sys
import urllib.request

DEFAULT_OUT = "W:/hamzaban_data_factory/raw/awl_families.json"
DEFAULT_BASE_URL = "https://www.wgtn.ac.nz/lals/resources/academicwordlist/sublist"
SUBLIST_IDS = list(range(1, 11))
SUBLIST_MIN, SUBLIST_MAX = 25, 70  # sanity window; source is authoritative
FAMILY_COUNT_MIN, FAMILY_COUNT_MAX = 565, 575  # ~= 570, fail-closed outside
REQUEST_TIMEOUT = 60
USER_AGENT = "HamZaban-factory/1.0 (research; contact: admin)"


def sublist_url(base: str, num: int) -> str:
    return "%s/sublist%02d" % (base.rstrip("/"), num)


def clean_headword(raw: str) -> str | None:
    """Lowercase + strip affix markers. Returns None when nothing remains."""
    text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip().lower()
    text = text.replace("*", "").strip()
    text = " ".join(text.split())
    # Defensive: strip parenthetical affix notes ("word (-s)") and "word -s".
    text = re.sub(r"\s*\(.*?\)\s*", "", text).strip()
    text = re.sub(r"\s+-\S*$", "", text).strip()
    return text or None


def parse_sublist_html(page: str) -> dict[str, list[str]]:
    """Parse one sublist page to {family_headword: [members]} (pure, hermetic).

    Structure: ``<h2>The Academic Word List</h2>`` then repeating
    ``<p>head</p>`` optionally followed by ``<ul><li>…``. A headword with
    no ``<ul>`` (e.g. ``data``) is a single-member family.
    """
    _, _, body = page.partition("<h2>The Academic Word List</h2>")
    if not body:
        raise ValueError("parse_sublist_html: AWL content block not found")
    body = body.split("</main>")[0]
    families: dict[str, list[str]] = {}
    pattern = re.compile(r"<p>(.*?)</p>\s*(?:<ul>(.*?)</ul>)?", re.DOTALL)
    for match in pattern.finditer(body):
        head = clean_headword(match.group(1))
        if not head:
            continue
        members: list[str] = [head]
        ul = match.group(2) or ""
        for item in re.findall(r"<li>(.*?)</li>", ul, re.DOTALL):
            cleaned = clean_headword(item)
            if cleaned and cleaned not in members:
                members.append(cleaned)
        if head not in families:
            families[head] = members
    if not families:
        raise ValueError("parse_sublist_html: no families parsed")
    return families


def fetch_page(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:
        raise SystemExit(f"error: cannot fetch AWL source {url}: {exc} "
                         "(source unreachable — STOP, no data invented)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Coxhead AWL families.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="destination JSON path")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="AWL sublist base URL")
    parser.add_argument("--dry-run", action="store_true",
                        help="print plan, fetch nothing, write nothing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    urls = [sublist_url(args.base_url, num) for num in SUBLIST_IDS]
    if args.dry_run:
        print("dry-run plan (nothing fetched, nothing written):")
        print(f"  source: {args.base_url} (10 sublists, ~570 families)")
        for url in urls:
            print(f"    {url}")
        print(f"  out:    {args.out}")
        return 0
    families: dict[str, list[str]] = {}
    per_sublist: dict[str, int] = {}
    for num, url in zip(SUBLIST_IDS, urls):
        page = fetch_page(url)
        parsed = parse_sublist_html(page)
        print(f"  sublist {num}: {len(parsed)} families")
        if not (SUBLIST_MIN <= len(parsed) <= SUBLIST_MAX):
            raise SystemExit(f"error: sublist {num} has {len(parsed)} families, "
                             f"outside [{SUBLIST_MIN}, {SUBLIST_MAX}] — STOP, "
                             "source shape changed")
        for head, members in parsed.items():
            if head in families:
                raise SystemExit(f"error: duplicate AWL family {head!r} — STOP")
            families[head] = members
        per_sublist[str(num)] = len(parsed)
    total = len(families)
    print(f"fetched: {total} families")
    if not (FAMILY_COUNT_MIN <= total <= FAMILY_COUNT_MAX):
        raise SystemExit(f"error: family count {total} outside "
                         f"[{FAMILY_COUNT_MIN}, {FAMILY_COUNT_MAX}] — STOP, not writing")
    note = ""
    if total != 570:
        # Honest provenance: the literature says 570; the live VUW pages
        # are authoritative and currently yield `total` (sublist 7 lists 59).
        # Never invent a family to hit the literature number.
        note = (f"VUW sublist pages yield {total} families vs the literature "
                "number 570 (sublist 7 page lists 59); no family invented.")
        print(f"note: {note}")
    payload = {
        "metadata": {
            "source_url": args.base_url,
            "sublist_urls": urls,
            "date": _dt.datetime.now(_dt.timezone.utc).date().isoformat(),
            "family_count": total,
            "per_sublist": per_sublist,
            "provenance": "Coxhead AWL (2000), Victoria University of "
                          "Wellington LALS resources — public research data",
            "note": note,
        },
        "families": families,
    }
    parent = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(parent, exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=1))
    os.replace(tmp, args.out)
    print(f"wrote: {args.out} ({total} families)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
