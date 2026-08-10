"""Focused regression checks for the standalone financial-model dashboard."""

from pathlib import Path


DASHBOARD = Path("tools/financial_model/financial_model_dashboard.html")


def _html() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_query_credit_pack_defaults_are_present():
    html = _html()

    assert "id: 'query40'" in html
    assert "price: 9000" in html
    assert "credits: 40" in html
    assert "id: 'query100'" in html
    assert "price: 19000" in html
    assert "credits: 100" in html
    assert "nonExpiring: true" in html


def test_free_plan_has_no_default_query_ai_quota():
    html = _html()

    assert "name: 'رایگان', nameEn: 'Free', price: 0, callsPerDay: 0" in html
    assert "d.plans = d.plans.map(p => p.id === 'free' ? { ...p, callsPerDay: 0 } : p);" in html


def test_credit_pack_simulation_has_independent_assumptions_and_seeded_noise():
    html = _html()

    for key in (
        "creditPackPurchaseRatePct",
        "creditPackRepeatRatePct",
        "creditPackPurchaseNoisePct",
        "creditPackConsumptionRatePct",
        "creditPackConsumptionNoisePct",
        "creditPackRandomSeed",
    ):
        assert key in html

    assert "const seededNoise =" in html
    assert "const packGrossRevenue =" in html
    assert "const queryAiCostToman =" in html
    assert "outstandingCredits:" in html


def test_credit_pack_export_import_is_a_separate_section():
    html = _html()

    assert "id: 'creditPacks'" in html
    assert "out.creditPacks = inp.value.creditPacks;" in html
    assert "merged.creditPacks = parsed.creditPacks.map(p => ({ ...p }));" in html


def test_credit_pack_prices_follow_existing_annual_price_index():
    html = _html()

    assert "const priceIdx = Math.pow(1 + renewal, Math.floor(t / 12));" in html
    assert "p.units * (p.price || 0) * priceIdx" in html


def test_plan_and_credit_pack_editors_have_separate_authority():
    html = _html()

    assert "مدیریت بسته‌های اعتبار Query" in html
    assert "قیمت و سهم — نمای تحلیلی" in html
    assert "const addCreditPack =" in html
    assert "const removeCreditPack =" in html
    assert "normalizeCreditPackShares" in html
    assert "creditPackSalesShareSum" in html
