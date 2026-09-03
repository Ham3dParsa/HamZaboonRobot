"""Locked factory registry — SQLite-backed lemma/pre-card/batch store (stdlib only).

Locked by plan-v14.md REGISTRY LOCK (2026-09-03, SQLite wins). No re-decisions:
follows factory/DESIGN-registry-A.md for structure, DESIGN-registry-B.md for
proof-test ideas. See factory/REGISTRY_EVIDENCE.md for migrated counts.

Rules (locked):
- Registry file lives on LOCAL disk (factory/registry.db). W: copies are
  backups only — never open the live DB from a network share (SQLite locking
  over SMB/NFS corrupts). See backup_db().
- Stable IDs replace unstable `w#lab` cluster ids (kept as aliases only):
    lemma_key  = normalize(lemma) + "|" + normalize(pos)
    pre_card_id = lemma_key + "::" + sha1(normalize(gloss))[:10]
  Gloss identity EXCLUDES synonyms/examples (examples churn with the Tatoeba
  pool; rank/score/topic are NOT identity either).
- All writes use short IMMEDIATE transactions. Never hold a transaction across
  I/O (no API calls, no file reads inside a write txn).
- Zero reprocessing: migrate_v14() is file reads only (no GPU, no API).

Only dependency: stdlib sqlite3.
"""

import contextlib
import datetime as _dt
import hashlib
import json
import os
import sqlite3

SCHEMA_VERSION = 1
STALE_LEASE_SECONDS = 30 * 60  # 30-min stale re-queue (locked)

# ---------------------------------------------------------------------------
# Normalization (locked; same notion of "same meaning" as R9 exact-dup key)


def normalize_lemma(s):
    """Lowercased lemma with stripped/collapsed whitespace."""
    return " ".join(str(s).strip().split()).lower()


def normalize_pos(s):
    return str(s).strip().lower()


def normalize_gloss(s):
    """Lowercase, collapse whitespace, strip trailing period.

    Synonyms/examples are EXCLUDED from identity by construction: callers
    pass only the gloss string here.
    """
    return " ".join(str(s).lower().split()).rstrip(".")


def lemma_key_for(lemma, pos):
    return normalize_lemma(lemma) + "|" + normalize_pos(pos)


def precard_id_for(lemma_key, gloss):
    return lemma_key + "::" + hashlib.sha1(
        normalize_gloss(gloss).encode("utf-8")).hexdigest()[:10]


def _utcnow_iso():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Connection handling


def _coerce(db):
    """Accept a path (str/os.PathLike) or an existing sqlite3.Connection."""
    if isinstance(db, sqlite3.Connection):
        return db, False
    con = sqlite3.connect(str(db))
    con.execute("PRAGMA journal_mode=WAL;")
    con.row_factory = sqlite3.Row
    return con, True


@contextlib.contextmanager
def _write(db):
    """Short IMMEDIATE-transaction scope. No I/O inside the block."""
    con, owned = _coerce(db)
    try:
        con.execute("BEGIN IMMEDIATE;")
        yield con
        con.execute("COMMIT;")
    except Exception:
        try:
            con.execute("ROLLBACK;")
        except Exception:
            pass
        raise
    finally:
        if owned:
            con.close()


def _query(db, sql, params=()):
    con, owned = _coerce(db)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        if owned:
            con.close()


def _stages_loads(raw):
    try:
        return json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# 1. Schema


def init_db(path):
    """Create factory/registry.db (WAL mode) with the locked 6+1 tables."""
    parent = os.path.dirname(os.path.abspath(str(path)))
    os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS languages(
          code TEXT PRIMARY KEY,
          pack_version TEXT NOT NULL,
          added_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lemmas(
          lang TEXT NOT NULL,
          lemma_key TEXT NOT NULL,
          pos TEXT NOT NULL,
          cefr TEXT,
          stages TEXT NOT NULL DEFAULT '{}',
          raw_hash TEXT,
          PRIMARY KEY(lang, lemma_key)
        );
        CREATE TABLE IF NOT EXISTS precards(
          lang TEXT NOT NULL,
          pre_card_id TEXT NOT NULL,
          lemma_key TEXT NOT NULL,
          gloss TEXT NOT NULL,
          sense_cefr TEXT,
          status TEXT NOT NULL DEFAULT 'active',
          merged_into TEXT,
          converted_final_id TEXT,
          created_run TEXT,
          PRIMARY KEY(lang, pre_card_id)
        );
        CREATE TABLE IF NOT EXISTS lemma_aliases(
          lang TEXT NOT NULL,
          alias TEXT NOT NULL,
          pre_card_id TEXT NOT NULL,
          PRIMARY KEY(lang, alias, pre_card_id)
        );
        CREATE TABLE IF NOT EXISTS runs(
          run_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          started TEXT NOT NULL,
          fingerprint TEXT,
          notes TEXT
        );
        CREATE TABLE IF NOT EXISTS batches(
          ticket TEXT PRIMARY KEY,
          lang TEXT NOT NULL,
          quota INT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          progress TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS batch_items(
          ticket TEXT NOT NULL,
          pre_card_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'claimed',
          PRIMARY KEY(ticket, pre_card_id)
        );
        CREATE INDEX IF NOT EXISTS idx_precards_lemma
          ON precards(lang, lemma_key);
        CREATE INDEX IF NOT EXISTS idx_precards_status
          ON precards(lang, status);
        CREATE INDEX IF NOT EXISTS idx_aliases_alias
          ON lemma_aliases(lang, alias);
        CREATE INDEX IF NOT EXISTS idx_batch_items_card
          ON batch_items(pre_card_id);
        """)
        con.commit()
    finally:
        con.close()
    return str(path)


# ---------------------------------------------------------------------------
# 2. Writes


def register_language(db, code, pack_version):
    """INSERT language; on re-register update pack_version, keep added_at."""
    with _write(db) as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO languages(code, pack_version, added_at)"
            " VALUES(?, ?, ?)", (code, pack_version, _utcnow_iso()))
        if cur.rowcount == 0:
            con.execute("UPDATE languages SET pack_version=? WHERE code=?",
                        (pack_version, code))
    return code


def upsert_lemma(db, lang, lemma, pos, cefr=None, raw_hash=None,
                 stages=None, pack_version=None, code_hash=None):
    """INSERT lemma_key or UPDATE attributes. Stage flags merge (old keys
    kept, new override). Fingerprint stored as stages['fp'] =
    '<pack_version>:<code_hash>' when both are given."""
    key = lemma_key_for(lemma, pos)
    with _write(db) as con:
        row = con.execute(
            "SELECT stages FROM lemmas WHERE lang=? AND lemma_key=?",
            (lang, key)).fetchone()
        merged = _stages_loads(row["stages"]) if row else {}
        for k, v in (stages or {}).items():
            merged[k] = v
        if pack_version is not None and code_hash is not None:
            merged["fp"] = "%s:%s" % (pack_version, code_hash)
        blob = json.dumps(merged, sort_keys=True, ensure_ascii=False)
        con.execute(
            "INSERT INTO lemmas(lang, lemma_key, pos, cefr, stages, raw_hash)"
            " VALUES(?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(lang, lemma_key) DO UPDATE SET"
            " pos=excluded.pos, cefr=excluded.cefr,"
            " stages=excluded.stages, raw_hash=excluded.raw_hash",
            (lang, key, normalize_pos(pos), cefr, blob, raw_hash))
    return key


def add_precard(db, lang, lemma_key, gloss, sense_cefr=None,
                legacy_id=None, created_run=None):
    """INSERT OR IGNORE by content-hash id. Returns True iff row is new.

    Legacy `w#lab` ids are recorded in lemma_aliases either way (idempotent),
    so re-imports still heal missing aliases while reporting no new rows.
    """
    pid = precard_id_for(lemma_key, gloss)
    with _write(db) as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO precards(lang, pre_card_id, lemma_key,"
            " gloss, sense_cefr, created_run)"
            " VALUES(?, ?, ?, ?, ?, ?)",
            (lang, pid, lemma_key, gloss, sense_cefr, created_run))
        new = cur.rowcount == 1
        if legacy_id:
            con.execute(
                "INSERT OR IGNORE INTO lemma_aliases(lang, alias, pre_card_id)"
                " VALUES(?, ?, ?)", (lang, legacy_id, pid))
    return new


def mark_merged(db, lang, survivor_id, dropped_id):
    """Flag a dropped pre-card superseded by survivor. Idempotent."""
    if survivor_id == dropped_id:
        return False
    with _write(db) as con:
        cur = con.execute(
            "SELECT status FROM precards WHERE lang=? AND pre_card_id=?",
            (lang, dropped_id)).fetchone()
        if cur is None:
            return False
        con.execute(
            "UPDATE precards SET status='superseded', merged_into=?"
            " WHERE lang=? AND pre_card_id=?",
            (survivor_id, lang, dropped_id))
    return True


def mark_converted(db, lang, pre_card_id, final_id):
    """Set conversion receipt. Double-conversion to a DIFFERENT final id is
    refused (returns False); same final id is a no-op True."""
    with _write(db) as con:
        row = con.execute(
            "SELECT converted_final_id FROM precards"
            " WHERE lang=? AND pre_card_id=?",
            (lang, pre_card_id)).fetchone()
        if row is None:
            return False
        cur_val = row["converted_final_id"]
        if cur_val is not None and cur_val != final_id:
            return False
        con.execute(
            "UPDATE precards SET converted_final_id=?"
            " WHERE lang=? AND pre_card_id=?",
            (final_id, lang, pre_card_id))
    return True


# ---------------------------------------------------------------------------
# 3. Batches (claim-lease-commit, 30-min stale re-queue)


def _batch_prefix(lang, datestr):
    return "FINAL-%s-%s-" % (lang, datestr)


def claim_batch(db, lang, quota, datestr=None):
    """Claim up to `quota` pending pre-cards into a new ticket
    FINAL-{lang}-YYYYMMDD-NN. Short txn: ticket + items only; the expensive
    final-card work happens OUTSIDE any transaction."""
    datestr = datestr or _dt.datetime.now(
        _dt.timezone.utc).strftime("%Y-%m-%d")
    day = datestr.replace("-", "")
    prefix = _batch_prefix(lang, day)
    pending = get_pending(db, lang)[:max(0, int(quota))]
    with _write(db) as con:
        rows = con.execute(
            "SELECT ticket FROM batches WHERE ticket LIKE ?",
            (prefix + "%",)).fetchall()
        taken = set()
        for r in rows:
            try:
                taken.add(int(r["ticket"].rsplit("-", 1)[-1]))
            except ValueError:
                pass
        seq = (max(taken) + 1) if taken else 1
        ticket = "%s%02d" % (prefix, seq)
        progress = json.dumps({
            "leased_at": _utcnow_iso(),
            "quota": quota,
            "n_items": len(pending),
            "done": 0,
        }, ensure_ascii=False)
        con.execute(
            "INSERT INTO batches(ticket, lang, quota, status, progress)"
            " VALUES(?, ?, ?, 'open', ?)",
            (ticket, lang, quota, progress))
        for pid in pending:
            con.execute(
                "INSERT OR IGNORE INTO batch_items(ticket, pre_card_id, status)"
                " VALUES(?, ?, 'claimed')", (ticket, pid))
    return ticket


def complete_batch_item(db, ticket, pre_card_id, final_id):
    """Commit one item: item -> done, precard gets conversion receipt, batch
    done counter updated — all in ONE short transaction. Returns False when
    the item is already done (no double count) or the pre-card is converted
    to a different final id elsewhere."""
    with _write(db) as con:
        item = con.execute(
            "SELECT status FROM batch_items WHERE ticket=? AND pre_card_id=?",
            (ticket, pre_card_id)).fetchone()
        if item is None or item["status"] == "done":
            return False
        brow = con.execute(
            "SELECT lang FROM batches WHERE ticket=?", (ticket,)).fetchone()
        if brow is None:
            return False
        lang = brow["lang"]
        prow = con.execute(
            "SELECT converted_final_id FROM precards"
            " WHERE lang=? AND pre_card_id=?",
            (lang, pre_card_id)).fetchone()
        if prow is not None and prow["converted_final_id"] not in (None, final_id):
            return False
        con.execute(
            "UPDATE batch_items SET status='done'"
            " WHERE ticket=? AND pre_card_id=?", (ticket, pre_card_id))
        con.execute(
            "UPDATE precards SET converted_final_id=?"
            " WHERE lang=? AND pre_card_id=?",
            (final_id, lang, pre_card_id))
        done = con.execute(
            "SELECT COUNT(*) c FROM batch_items"
            " WHERE ticket=? AND status='done'",
            (ticket,)).fetchone()["c"]
        prog = con.execute(
            "SELECT progress FROM batches WHERE ticket=?",
            (ticket,)).fetchone()["progress"]
        blob = _stages_loads(prog)
        blob["done"] = done
        con.execute("UPDATE batches SET progress=? WHERE ticket=?",
                    (json.dumps(blob, ensure_ascii=False), ticket))
    return True


def requeue_stale(db, ticket, stale_seconds=STALE_LEASE_SECONDS):
    """Crash recovery: 'claimed' items whose batch lease is older than
    `stale_seconds` go back to 'queued'. 'done' rows are NEVER re-queued.
    Returns the number of items re-queued (0 when lease is fresh)."""
    with _write(db) as con:
        row = con.execute(
            "SELECT progress FROM batches WHERE ticket=?",
            (ticket,)).fetchone()
        if row is None:
            return 0
        blob = _stages_loads(row["progress"])
        try:
            leased = _dt.datetime.fromisoformat(blob.get("leased_at", ""))
            if leased.tzinfo is None:
                leased = leased.replace(tzinfo=_dt.timezone.utc)
        except (ValueError, TypeError):
            leased = None
        now = _dt.datetime.now(_dt.timezone.utc)
        if leased is not None and (now - leased).total_seconds() <= stale_seconds:
            return 0
        cur = con.execute(
            "UPDATE batch_items SET status='queued'"
            " WHERE ticket=? AND status='claimed'", (ticket,))
        blob["leased_at"] = now.isoformat(timespec="seconds")
        con.execute("UPDATE batches SET progress=? WHERE ticket=?",
                    (json.dumps(blob, ensure_ascii=False), ticket))
        return cur.rowcount


# ---------------------------------------------------------------------------
# 4. Reads


def count_precards(db, lang, only_unconverted=False):
    """Count pre-card rows for a language (all statuses). With
    only_unconverted=True, exclude rows with a conversion receipt."""
    sql = "SELECT COUNT(*) c FROM precards WHERE lang=?"
    params = [lang]
    if only_unconverted:
        sql += " AND converted_final_id IS NULL"
    rows = _query(db, sql, params)
    return rows[0]["c"] if rows else 0


def stats(db, lang):
    """Breakdown for evidence: lemmas / total / active / superseded /
    converted / unconverted-active."""
    q = lambda sql, p=(): _query(db, sql, (lang,) + tuple(p))[0]["c"]  # noqa: E731
    return {
        "lemmas": q("SELECT COUNT(*) c FROM lemmas WHERE lang=?"),
        "precards_total": q("SELECT COUNT(*) c FROM precards WHERE lang=?"),
        "active": q("SELECT COUNT(*) c FROM precards"
                    " WHERE lang=? AND status='active'"),
        "superseded": q("SELECT COUNT(*) c FROM precards"
                        " WHERE lang=? AND status='superseded'"),
        "converted": q("SELECT COUNT(*) c FROM precards"
                       " WHERE lang=? AND converted_final_id IS NOT NULL"),
        "unconverted_active": q("SELECT COUNT(*) c FROM precards"
                                " WHERE lang=? AND status='active'"
                                " AND converted_final_id IS NULL"),
    }


def get_pending(db, lang, stage=None):
    """Pre-card ids ready for a batch: active, unconverted, and not
    'claimed'/'done' in any same-language ticket ('queued'/'failed' are
    re-claimable). With stage=X, only lemmas whose stages JSON has X=true."""
    rows = _query(db,
        "SELECT p.pre_card_id, p.lemma_key FROM precards p"
        " WHERE p.lang=? AND p.status='active'"
        " AND p.converted_final_id IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM batch_items bi"
        "  JOIN batches b ON b.ticket=bi.ticket"
        "  WHERE bi.pre_card_id=p.pre_card_id AND b.lang=?"
        "  AND bi.status IN ('claimed','done'))"
        " ORDER BY p.lemma_key, p.pre_card_id", (lang, lang))
    if stage is None:
        return [r["pre_card_id"] for r in rows]
    flagged = set()
    for r in _query(db, "SELECT lemma_key, stages FROM lemmas WHERE lang=?",
                    (lang,)):
        if _stages_loads(r["stages"]).get(stage) is True:
            flagged.add(r["lemma_key"])
    return [r["pre_card_id"] for r in rows if r["lemma_key"] in flagged]


# ---------------------------------------------------------------------------
# 5. Invalidation helper


def fingerprint(db, lang, lemma_key, pack_version, code_hash, raw_hash):
    """'reuse' iff the stored row matches pack_version + code_hash (via
    stages['fp']) + raw_hash; otherwise 'reprocess' (fail-closed: unknown
    lemma/language or any mismatch reprocesses that lemma only)."""
    lrows = _query(db, "SELECT pack_version FROM languages WHERE code=?",
                   (lang,))
    if not lrows or lrows[0]["pack_version"] != pack_version:
        return "reprocess"
    lrows = _query(db,
        "SELECT stages, raw_hash FROM lemmas WHERE lang=? AND lemma_key=?",
        (lang, lemma_key))
    if not lrows:
        return "reprocess"
    if (lrows[0]["raw_hash"] or "") != (raw_hash or ""):
        return "reprocess"
    if _stages_loads(lrows[0]["stages"]).get("fp") != "%s:%s" % (
            pack_version, code_hash):
        return "reprocess"
    return "reuse"


# ---------------------------------------------------------------------------
# 6. Backup (W: copy only — never a live DB)


def backup_db(db_path, backup_dir):
    """Consistent snapshot via VACUUM INTO to
    <backup_dir>/registry-backup-YYYYMMDD-HHMMSS.db. Backup ONLY."""
    os.makedirs(str(backup_dir), exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(str(backup_dir),
                        "registry-backup-%s.db" % stamp)
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("VACUUM INTO ?", (dest,))
    finally:
        con.close()
    return dest


# ---------------------------------------------------------------------------
# 7. One-shot migration (reads fixtures, zero reprocessing, idempotent)


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def migrate_v14(db_path, fixtures_dir):
    """Import the 500-lemma v14 fixtures read-only. Safe to run twice
    (INSERT OR IGNORE + idempotent flags). Returns stats('en') + run notes.

    All fixture files are read BEFORE any write transaction opens.
    """
    fx = str(fixtures_dir)
    uniq = _load_json(os.path.join(fx, "uniq_senses-v14a.json"))
    ra = _load_json(os.path.join(fx, "ranked_senses-v14a.json"))
    rb = _load_json(os.path.join(fx, "ranked_senses-v14b.json"))
    rc = _load_json(os.path.join(fx, "ranked_senses-v14c.json"))
    topics = _load_json(os.path.join(fx, "topic_labels-v16b.json"))

    init_db(db_path)
    started = _utcnow_iso()
    register_language(db_path, "en", "v14a")

    # (lemma, cefr) uniquely identifies the uniq row (most/outside/cast dupes
    # differ by pos+cefr; cast|verb B2+C1 share one lemma_key by locked rule).
    uniq_by_lc = {}
    for row in uniq:
        uniq_by_lc.setdefault((row["lemma"], row["cefr"]), []).append(row)
    for k, v in uniq_by_lc.items():
        if len(v) != 1:
            raise ValueError("ambiguous uniq row for %r" % (k,))

    def uniq_row_for(r):
        return uniq_by_lc[(r["lemma"], r["cefr"])][0]

    # 1. lemmas (raw pool) + v14a precards.
    new_precards = 0
    for row in uniq:
        u = uniq_row_for({"lemma": row["lemma"], "cefr": row["cefr"]})
        raw_blob = json.dumps(
            [{"sense_id": s.get("sense_id"), "gloss": s.get("gloss"),
              "synonyms": s.get("synonyms")}
             for s in u["uniq_senses"]],
            sort_keys=True, ensure_ascii=False)
        upsert_lemma(db_path, "en", u["lemma"], u["pos"], cefr=u.get("cefr"),
                     raw_hash=hashlib.sha1(raw_blob.encode("utf-8")
                                           ).hexdigest(),
                     stages={"deduped": True, "n_uniq": len(u["uniq_senses"])},
                     pack_version="v14a", code_hash="legacy-import")
    a_ids = set()
    for r in ra:
        u = uniq_row_for(r)
        lk = lemma_key_for(u["lemma"], u["pos"])
        upsert_lemma(db_path, "en", u["lemma"], u["pos"],
                     stages={"ranked": True},
                     pack_version="v14a", code_hash="legacy-import")
        for s in r["ranked_senses"]:
            if add_precard(db_path, "en", lk, s["gloss"],
                           sense_cefr=s.get("sense_cefr"),
                           legacy_id=s.get("sense_id"),
                           created_run="import-v14a"):
                new_precards += 1
            a_ids.add(precard_id_for(lk, s["gloss"]))

    # 2. v14b survivors (+2 genuinely reworded) + merged_from lineage.
    mf_to_survivor = {}
    b_ids = set()
    for r in rb:
        u = uniq_row_for(r)
        lk = lemma_key_for(u["lemma"], u["pos"])
        upsert_lemma(db_path, "en", u["lemma"], u["pos"],
                     stages={"merged": True},
                     pack_version="v14a", code_hash="legacy-import")
        for s in r["ranked_senses"]:
            pid = precard_id_for(lk, s["gloss"])
            add_precard(db_path, "en", lk, s["gloss"],
                        sense_cefr=s.get("sense_cefr"),
                        legacy_id=s.get("sense_id"),
                        created_run="import-v14b")
            b_ids.add(pid)
            for m in s.get("merged_from", []) or []:
                mf_to_survivor.setdefault(m, pid)
    # Alias -> content map from the v14a pass (for dropped resolution).
    alias_to_cid = {}
    for cid_rows in _query(db_path,
            "SELECT alias, pre_card_id FROM lemma_aliases WHERE lang='en'"):
        alias_to_cid.setdefault(cid_rows["alias"], set()
                                ).add(cid_rows["pre_card_id"])
    merged_n = unresolved_n = 0
    for pid in sorted(a_ids - b_ids):
        aliases = [a for a, cids in alias_to_cid.items() if pid in cids]
        survs = sorted({mf_to_survivor[a] for a in aliases
                        if a in mf_to_survivor} - {pid})
        if mark_merged(db_path, "en", survs[0] if survs else None, pid):
            merged_n += 1
        if not survs:
            unresolved_n += 1
    # 3. v14c picks -> judged flags.
    judged_n = 0
    for r in rc:
        u = uniq_row_for(r)
        upsert_lemma(db_path, "en", u["lemma"], u["pos"],
                     stages={"judged": True,
                             "pick_source": r.get("pick_source", "judge")},
                     pack_version="v14a", code_hash="legacy-import")
        judged_n += 1

    # 4. v16b topic labels -> topics flags (match by legacy alias + lemma).
    alias_rows = _query(
        db_path, "SELECT alias, pre_card_id FROM lemma_aliases"
                 " WHERE lang='en'")
    alias_map = {}
    for ar in alias_rows:
        alias_map.setdefault(ar["alias"], []).append(ar["pre_card_id"])
    lemma_of = {r["pre_card_id"]: r["lemma_key"] for r in _query(
        db_path, "SELECT pre_card_id, lemma_key FROM precards"
                 " WHERE lang='en'")}
    topics_n = 0
    for t in topics:
        cands = alias_map.get(t.get("sense_id"), [])
        if cands:
            topics_n += 1
    # Flag every lemma that owns a matched topic card.
    touched = set()
    for t in topics:
        for pid in alias_map.get(t.get("sense_id"), []):
            touched.add(lemma_of.get(pid))
    touched.discard(None)
    for lk in touched:
        lemma, _, pos = lk.partition("|")
        upsert_lemma(db_path, "en", lemma, pos, stages={"topics": True},
                     pack_version="v14a", code_hash="legacy-import")

    # 5. Provenance runs (one row per import stage).
    notes = {
        "import-v14a": "phase1 uniq+ranked read-only import",
        "import-v14b": "merge read-only import",
        "import-v14c": "judge read-only import",
        "import-v16b": "topics read-only import",
    }
    kinds = {"import-v14a": "phase1", "import-v14b": "merge",
             "import-v14c": "judge", "import-v16b": "topics"}
    with _write(db_path) as con:
        for run_id, note in notes.items():
            con.execute(
                "INSERT OR IGNORE INTO runs(run_id, kind, started,"
                " fingerprint, notes) VALUES(?, ?, ?, ?, ?)",
                (run_id, kinds[run_id], started, "v14a:legacy-import",
                 note))
    out = stats(db_path, "en")
    out.update({"runs": 4, "topics_matched": topics_n,
                "merged": merged_n, "merged_unresolved": unresolved_n,
                "judged_lemmas": judged_n,
                "topics_lemmas": len(touched)})
    return out


_HERE = os.path.dirname(os.path.abspath(__file__))


if __name__ == "__main__":
    import sys
    _db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        _HERE, "registry.db")
    _fx = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        _HERE, "fixtures")
    print(json.dumps(migrate_v14(_db, _fx), indent=1, ensure_ascii=False))
