"""AI Preset Manager — local web UI for viewing & editing AI presets.

Usage:
    cd tools/AI_preset_manager
    python server.py
    Open http://localhost:5555 in browser.
"""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, jsonify, request, send_from_directory
from services import db

app = Flask(__name__, static_folder=None)

DEFAULT_TOMAN_RATE = 190000


# ─── Helpers ──────────────────────────────────────────────

def _mask_key(raw: str | None) -> str:
    if not raw:
        return "\u2014"
    if len(raw) > 12:
        return raw[:6] + "\u2026" + raw[-4:]
    return raw


def _resolve_key(preset: dict) -> str:
    return db.resolve_preset_key(preset) or ""


def _validate_preset_name(name: str) -> str | None:
    """Same validation as the bot (handlers/admin.py). Returns error msg or None."""
    cleaned = name.strip().lower().replace(" ", "_")
    if not cleaned:
        return "نام نمی‌تواند خالی باشد"
    if not cleaned.isalnum() and "_" not in cleaned:
        return "نام نامعتبر. فقط حروف، اعداد و زیرخط مجاز است"
    if not all(c.isalnum() or c == "_" for c in cleaned):
        return "فقط حروف، اعداد و زیرخط مجاز است"
    return None


def _serialize_preset(p, active_name: str | None, chain_names: set | None = None):
    resolved = _resolve_key(p)
    if chain_names is None:
        chain_names = set()
    return {
        "name": p["name"],
        "model": p.get("model", ""),
        "base_url": p.get("base_url", ""),
        "api_key": p.get("api_key", ""),
        "api_key_masked": _mask_key(resolved),
        "api_key_resolved": resolved,
        "enabled": bool(p["enabled"]),
        "priority": p.get("priority", 0),
        "is_custom": bool(p.get("is_custom", 0)),
        "is_emergency": bool(p.get("is_emergency", 0)),
        "in_fallback_chain": bool(p.get("in_fallback_chain", 1)),
        "group_label": p.get("group_label", "") or "",
        "max_concurrency": p.get("max_concurrency", 2),
        "max_rpm": p.get("max_rpm", 30),
        "max_tpm": p.get("max_tpm", 0),
        "daily_batch_size": p.get("daily_batch_size", 6),
        "temperature": p.get("temperature", 0.3),
        "input_cost_per_million": p.get("input_cost_per_million"),
        "output_cost_per_million": p.get("output_cost_per_million"),
        "is_active": p["name"] == active_name,
        "in_fallback_chain_flag": p["name"] in chain_names,
    }


_ALLOWED_FIELDS = {
    "name", "model", "base_url", "api_key", "enabled", "priority",
    "is_custom", "is_emergency", "in_fallback_chain",
    "group_label", "max_concurrency", "max_rpm", "max_tpm",
    "daily_batch_size", "temperature",
    "input_cost_per_million", "output_cost_per_million",
}


def _load_db_data():
    presets = db.get_presets()
    chain_names = {p["name"] for p in db.get_fallback_chain_presets()}
    active = db.get_active_preset()
    active_name = active["name"] if active else None
    return presets, chain_names, active_name


# ─── Index ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(SCRIPT_DIR, "index.html")


# ─── DB Connection ───────────────────────────────────────

_CURRENT_DB_PATH: str = db.DB_PATH


@app.route("/api/db/current")
def db_current():
    return jsonify({"path": _CURRENT_DB_PATH, "exists": os.path.isfile(_CURRENT_DB_PATH)})


@app.route("/api/db/connect", methods=["POST"])
def db_connect():
    global _CURRENT_DB_PATH
    data = request.get_json()
    new_path = data.get("path", "")
    if not new_path or not os.path.isfile(new_path):
        return jsonify({"error": "فایل دیتابیس یافت نشد"}), 400
    db.DB_PATH = new_path
    db.init_db()
    _CURRENT_DB_PATH = new_path
    return jsonify({"ok": True, "path": new_path})


# ─── Settings ──────────────────────────────────────────

@app.route("/api/settings")
def list_settings():
    rate = db.get_setting("usd_to_toman_rate", str(DEFAULT_TOMAN_RATE))
    return jsonify({
        "usd_to_toman_rate": float(rate),
    })


@app.route("/api/settings/toman_rate", methods=["PUT"])
def set_toman_rate():
    data = request.get_json()
    rate = data.get("rate")
    if not rate or float(rate) <= 0:
        return jsonify({"error": "نرخ نامعتبر"}), 400
    db.set_setting("usd_to_toman_rate", str(float(rate)))
    return jsonify({"ok": True, "rate": float(rate)})


# ─── Presets API ──────────────────────────────────────────

@app.route("/api/presets")
def list_presets():
    presets, chain_names, active_name = _load_db_data()
    return jsonify([_serialize_preset(p, active_name, chain_names) for p in presets])


@app.route("/api/presets", methods=["POST"])
def create_preset():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    err = _validate_preset_name(name)
    if err:
        return jsonify({"error": err}), 400
    if db.get_preset(name):
        return jsonify({"error": f"پریست '{name}' از قبل وجود دارد"}), 409
    db.set_preset(
        name=name,
        base_url=data.get("base_url", ""),
        model=data.get("model", ""),
        api_key=data.get("api_key", ""),
        is_custom=1,
    )
    return jsonify({"ok": True})


@app.route("/api/presets/<name>", methods=["GET"])
def get_preset(name):
    p = db.get_preset(name)
    if not p:
        return jsonify({"error": "not found"}), 404
    _, chain_names, active_name = _load_db_data()
    return jsonify(_serialize_preset(p, active_name, chain_names))


@app.route("/api/presets/<name>", methods=["PUT"])
def update_preset(name):
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400

    for key in data:
        if key not in _ALLOWED_FIELDS:
            return jsonify({"error": f"فیلد نامعتبر: {key}"}), 400

    existing = db.get_preset(name)
    if not existing:
        return jsonify({"error": "not found"}), 404

    # Handle rename
    new_name = data.get("name")
    if new_name and new_name != name:
        err = _validate_preset_name(new_name)
        if err:
            return jsonify({"error": err}), 400
        if db.get_preset(new_name):
            return jsonify({"error": f"پریست '{new_name}' از قبل وجود دارد"}), 409

    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        updates = []
        params = []
        for key in sorted(_ALLOWED_FIELDS):
            if key == "name":
                continue  # handle separately
            if key in data:
                val = data[key]
                if isinstance(val, bool):
                    val = 1 if val else 0
                updates.append(f"{key}=?")
                params.append(val)

        if new_name and new_name != name:
            updates.append("name=?")
            params.append(new_name)

        if updates:
            target_name = new_name if new_name and new_name != name else name
            params.append(name)
            conn.execute(
                f"UPDATE ai_presets SET {', '.join(updates)} WHERE name=?",
                params,
            )

        conn.commit()
        result_name = new_name if new_name and new_name != name else name

        if "priority" in data:
            try:
                db.reindex_preset_priority(
                    result_name,
                    data["priority"] + 1,
                    data.get("is_emergency", existing.get("is_emergency", 0)),
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "name": new_name if new_name and new_name != name else name})


@app.route("/api/presets/<name>", methods=["DELETE"])
def delete_preset(name):
    p = db.get_preset(name)
    if not p:
        return jsonify({"error": "not found"}), 404
    active = db.get_active_preset()
    if active and active["name"] == name:
        return jsonify({"error": "نمی‌توان پریست فعال را حذف کرد"}), 400
    db.delete_preset(name)
    return jsonify({"ok": True})


@app.route("/api/presets/<name>/clone", methods=["POST"])
def clone_preset(name):
    p = db.get_preset(name)
    if not p:
        return jsonify({"error": "not found"}), 404
    data = request.get_json() or {}
    new_name = (data.get("name") or name + "_copy").strip()
    err = _validate_preset_name(new_name)
    if err:
        return jsonify({"error": err}), 400
    if db.get_preset(new_name):
        return jsonify({"error": f"پریست '{new_name}' از قبل وجود دارد"}), 409
    db.set_preset(
        name=new_name,
        base_url=p.get("base_url", ""),
        model=p.get("model", ""),
        api_key=p.get("api_key", ""),
        is_custom=1,
        is_emergency=bool(p.get("is_emergency", 0)),
        in_fallback_chain=bool(p.get("in_fallback_chain", 1)),
        group_label=p.get("group_label", "") or "",
        max_concurrency=p.get("max_concurrency", 2),
        max_rpm=p.get("max_rpm", 30),
        max_tpm=p.get("max_tpm", 0),
        daily_batch_size=p.get("daily_batch_size", 6),
        temperature=p.get("temperature", 0.3),
        max_output_tokens=p.get("max_output_tokens", 4096),
        timeout_seconds=p.get("timeout_seconds", 30.0),
        max_daily_req=p.get("max_daily_req", 0),
        input_cost_per_million=p.get("input_cost_per_million"),
        output_cost_per_million=p.get("output_cost_per_million"),
    )
    db.set_preset_priority(new_name, p.get("priority", 0))
    db.set_preset_enabled(new_name, bool(p.get("enabled", 1)))
    return jsonify({"ok": True, "name": new_name})


# ─── Batch Operations ─────────────────────────────────────

@app.route("/api/presets/batch/enable", methods=["PUT"])
def batch_enable():
    data = request.get_json()
    names = data.get("names", [])
    val = 1 if data.get("enabled", True) else 0
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for n in names:
            conn.execute("UPDATE ai_presets SET enabled=? WHERE name=?", (val, n))
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/presets/batch/chain", methods=["PUT"])
def batch_chain():
    data = request.get_json()
    names = data.get("names", [])
    val = 1 if data.get("in_fallback_chain", True) else 0
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for n in names:
            conn.execute("UPDATE ai_presets SET in_fallback_chain=? WHERE name=?", (val, n))
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/presets/batch/group", methods=["PUT"])
def batch_group():
    data = request.get_json()
    names = data.get("names", [])
    label = data.get("group_label", "")
    db.set_preset_group_label_batch(names, label)
    return jsonify({"ok": True})


@app.route("/api/presets/batch/key", methods=["PUT"])
def batch_api_key():
    data = request.get_json()
    names = data.get("names", [])
    key = data.get("api_key", "")
    db.set_preset_api_key_batch(names, key)
    return jsonify({"ok": True})


@app.route("/api/presets/batch/update", methods=["PUT"])
def batch_update_presets():
    """Update specific fields on multiple presets atomically.

    Body: { "names": [...], "updates": { "field1": val1, ... } }
    Only sends updates for the supplied fields; other fields are untouched.
    """
    data = request.get_json()
    names = data.get("names", [])
    updates = data.get("updates", {})

    if not names or not updates:
        return jsonify({"error": "نام پریست یا فیلدهای مورد نظر ارسال نشده"}), 400

    # Validate field names
    for key in updates:
        if key not in _ALLOWED_FIELDS or key == "name":
            return jsonify({"error": f"فیلد نامعتبر: {key}"}), 400

    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values())
    placeholders = ", ".join("?" for _ in names)

    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"UPDATE ai_presets SET {set_clause} WHERE name IN ({placeholders})",
            values + names,
        )
        conn.commit()

    return jsonify({"ok": True, "updated_count": len(names)})


# ─── Activation ──────────────────────────────────────────

@app.route("/api/activate/<name>", methods=["POST"])
def activate_preset(name):
    p = db.get_preset(name)
    if not p:
        return jsonify({"error": "not found"}), 404
    db.activate_preset(name)
    return jsonify({"ok": True})


# ─── Fallback Chain ───────────────────────────────────────

@app.route("/api/fallback")
def fallback_info():
    chain = db.get_fallback_chain_presets()
    status = db.get_fallback_status()
    return jsonify({
        "chain": [
            {
                "name": p["name"],
                "priority": p.get("priority", 0),
                "is_emergency": bool(p.get("is_emergency", 0)),
                "model": p.get("model", ""),
            }
            for p in chain
        ],
        "status": {
            "fallback_active": bool(status.get("fallback_active", False)),
            "primary_preset": status.get("primary_preset"),
            "fallback_preset": status.get("fallback_preset"),
            "fallback_since": status.get("fallback_since"),
            "consecutive_failures": status.get("consecutive_failures", 0),
        },
    })


# ─── Costs & Usage ────────────────────────────────────────

@app.route("/api/stats")
def stats():
    presets, chain_names, active_name = _load_db_data()
    return jsonify({
        "total": len(presets),
        "enabled": sum(1 for p in presets if p["enabled"]),
        "in_chain": len(chain_names),
        "active": active_name,
        "groups": len({p.get("group_label", "") or "_" for p in presets}),
    })


@app.route("/api/usage/<name>")
def usage(name):
    p = db.get_preset(name)
    if not p:
        return jsonify({"error": "not found"}), 404
    reqs, tokens = db.get_hourly_usage(name, hours_back=24)
    return jsonify({"name": name, "requests_24h": reqs, "tokens_24h": tokens})


@app.route("/api/costs")
def cost_summary():
    rate = float(db.get_setting("usd_to_toman_rate", str(DEFAULT_TOMAN_RATE)))
    filters = request.args.get("hours")
    # Get summary per model
    summary = db.summarize_llm_requests(
        {"end_date": None, "start_date": None}  # all time
    ) if not filters else db.summarize_llm_requests()

    by_model = db.breakdown_llm_requests("model", limit=50)
    presets_map = {p["name"]: p for p in db.get_presets()}

    result = []
    for row in by_model:
        model_name = row["bucket"]
        # Find associated preset(s) for this model
        matching_presets = [
            pn for pn, pp in presets_map.items()
            if pp.get("model", "").lower() == (model_name or "").lower()
        ]
        cost_toman = round(row["cost_usd"] * rate, 2)
        billed_fail_cost_toman = round(row.get("billed_failure_cost_usd", 0) * rate, 2)
        result.append({
            "model": model_name,
            "presets": matching_presets,
            "request_count": row["request_count"],
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "total_tokens": row["total_tokens"],
            "cost_usd": row["cost_usd"],
            "cost_toman": cost_toman,
            "billed_failure_count": row["billed_failure_count"],
            "zero_cost_failure_count": row["zero_cost_failure_count"],
        })

    total_cost_usd = summary.get("cost_usd", 0) or 0
    billed_fail_usd = summary.get("billed_failure_cost_usd", 0) or 0
    return jsonify({
        "models": result,
        "total_request_count": summary.get("request_count", 0),
        "total_cost_usd": total_cost_usd,
        "total_cost_toman": round(total_cost_usd * rate, 2),
        "total_prompt_tokens": summary.get("prompt_tokens", 0),
        "total_completion_tokens": summary.get("completion_tokens", 0),
        "total_tokens": summary.get("total_tokens", 0),
        "billed_failure_cost_usd": billed_fail_usd,
        "billed_failure_cost_toman": round(billed_fail_usd * rate, 2),
        "usd_to_toman_rate": rate,
    })


# ─── Server ──────────────────────────────────────────────

if __name__ == "__main__":
    print(f"AI Preset Manager running at http://localhost:5555")
    print(f"  DB: {_CURRENT_DB_PATH}")
    app.run(host="127.0.0.1", port=5555, debug=True, use_reloader=False)
