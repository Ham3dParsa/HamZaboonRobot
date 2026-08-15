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





def test_plan_analysis_rows_support_precise_paid_plan_inputs():

    html = _html()



    assert html.count('data-plan-analysis="price"') == 1

    assert html.count('data-plan-analysis="quota"') == 1

    assert html.count('data-plan-analysis="share"') == 1

    assert '@change="autoBalanceShare(p.id, $event.target.value)"' in html

    assert "این بخش فقط‌خواندنی است" not in html





def test_plan_numeric_inputs_clamp_values_and_keep_touch_targets():

    html = _html()



    assert "const clampPlanField = (plan, field, min, max)" in html

    assert "@change=\"clampPlanField(p, 'price', 0, 3000000)\"" in html

    assert "@change=\"clampPlanField(p, 'callsPerDay', 0, 100)\"" in html

    assert html.count("min-h-[44px]") >= 4

    assert "paidPlanShare" not in html

    assert "سهم پلن‌ها (تنظیم در «قیمت و سهم پلن‌ها»)" not in html





def test_dashboard_surfaces_credit_pack_revenue_separately():

    html = _html()



    assert "m1.packNetRevenue" in html

    assert "planNetRevenue" in html

    assert "درآمد بسته Query" in html

    assert "[m1.value.planNetRevenue, m1.value.packNetRevenue" in html





def test_desktop_dock_was_replaced_by_collapsible_sidebar():

    html = _html()



    assert "Desktop Floating Glass Dock" not in html

    assert "fixed bottom-6 left-1/2" not in html

    assert 'class="hidden lg:flex fixed top-[84px] bottom-0 right-0 z-30 flex-col' in html

    assert ':class="sidebarCollapsed ? \'w-20\' : \'w-64\'"' in html

    assert "toggleSidebar" in html

    assert "navItems" in html

    assert "hamzaboon_financial_model_sidebar_collapsed" in html

    assert "desktopContentPad" in html





def test_table_numbers_use_tabular_nums_and_forecast_is_sticky():

    html = _html()



    assert html.count("tabular-nums") >= 4

    assert '<span v-else class="text-left" dir="ltr">{{ format(p.callsPerDay) }} / روز</span>' in html

    assert "overflow-x-auto overflow-y-auto max-h-[560px]" in html

    assert "sticky top-0 right-0 z-30 bg-paper" in html

    assert "sticky right-0 z-20 bg-card" in html

    assert "sticky top-0 z-10 bg-paper" in html





def test_chart_panels_use_grid_accordion_instead_of_v_show():

    html = _html()



    assert "class=\"accordion-grid\"" in html

    assert "accordion-inner" in html

    assert html.count('class="accordion-grid"') == 4

    assert html.count(":class=\"{ open: chartOpen.") == 4

    assert "v-show=\"chartOpen.bar\"" not in html

    assert "v-show=\"chartOpen.pie\"" not in html

    assert "v-show=\"chartOpen.line\"" not in html

    assert "v-show=\"chartOpen.growth\"" not in html





def test_slider_thumb_is_24px_with_32px_mobile_variant():

    html = _html()



    assert "width: 24px; height: 24px;" in html

    assert "width: 32px; height: 32px;" in html

    assert "@media (max-width: 1023px)" in html

    assert ".hz-slider::-moz-range-thumb" in html





def test_kpi_tooltips_use_floating_ui_not_static_absolute():

    html = _html()



    assert "@floating-ui/core@1.6.0" in html

    assert "cdn.jsdelivr.net/npm/@floating-ui/dom" in html

    assert "FloatingUIDOM.autoUpdate" in html

    assert "FloatingUIDOM.flip" in html

    assert "FloatingUIDOM.shift" in html

    assert "absolute left-1/2 -translate-x-1/2 top-[calc(100%+6px)]" not in html





def test_ai_model_section_uses_wider_group_spacing():

    html = _html()



    assert 'v-if="inp.modelChoice === \'custom\'" class="mb-6"' in html

    assert html.count("mb-6") >= 2





def test_mobile_navigation_keeps_larger_touch_padding():

    html = _html()



    assert "lg:hidden fixed bottom-4" in html

    assert "rounded-full px-3 py-2" in html

    assert "class=\"px-4 py-2.5 rounded-full" in html





def test_settings_and_dashboard_are_exclusive_on_desktop():

    html = _html()



    # reciprocal desktop v-show clauses removed -> exclusive pages

    assert "v-show=\"activeTab === 'inputs' || (isDesktop && activeTab === 'dashboard')\"" not in html

    assert "v-show=\"activeTab === 'dashboard' || (isDesktop && activeTab === 'inputs')\"" not in html

    assert "v-show=\"activeTab === 'inputs'\"" in html

    assert "v-show=\"activeTab === 'dashboard'\"" in html





def test_pricing_guidance_is_an_operational_strip_with_query_pack_action():

    html = _html()



    # the old dense paragraph is gone

    assert "قیمت، سهمیهٔ AI و ترکیب ارتقای پلن‌های پولی را می‌توانید در همین جدول" not in html

    # operational strip + action that jumps to Query-pack management

    assert "gotoMarketing" in html

    assert "@click=\"gotoMarketing\"" in html

    assert "بسته‌های Query" in html

    assert "مدیریت مستقل" in html





def test_plan_management_uses_one_plan_editor_with_transient_selection():

    html = _html()



    # one-plan-at-a-time selector + selected editor, not a repeated card per plan

    assert "selectedPlanId = p.id" in html

    assert "selectedPlanView.plan" in html

    # the old open-card-per-plan loop used :key="p.id"; the selector uses :key="'sel-'+p.id"

    assert 'v-for="(p, idx) in inp.plans" :key="p.id"' not in html





def test_selected_plan_editor_keeps_commercial_fields_editable():

    html = _html()



    # commercial fields remain editable in the selected plan editor

    assert "clampPlanField(selectedPlanView.plan, 'price', 0, 3000000)" in html

    assert "clampPlanField(selectedPlanView.plan, 'callsPerDay', 0, 100)" in html

    assert "v-model.number=\"selectedPlanView.plan.callsPerDay\"" in html

    assert "autoBalanceShare(selectedPlanView.plan.id, $event.target.value)" in html

    # analysis table still edits the same plans (both editors share the source)

    assert 'data-plan-analysis="price"' in html


def test_credit_pack_share_sum_counts_only_active_packs():

    html = _html()

    # the displayed sales-share mix must match the normalize/simulation base (active packs only),
    # so deactivating a pack cannot inflate the shown total or block "normalize" from reaching 100%
    assert "creditPacks.value.filter(p => p.active !== false).reduce((s, p) => s + (Math.max(0, Number(p.salesSharePct) || 0)), 0)" in html


def test_callsperday_preserves_intentional_zero_over_falsy_default():

    html = _html()

    # a paid plan's intentional 0 daily quota must NOT be reset to 3 by the falsy `||` default
    # (Kilo review: the prior `(base && base.callsPerDay) || 3` treated 0 as falsy)
    assert "typeof base.callsPerDay === 'number' ? base.callsPerDay : 3" in html
