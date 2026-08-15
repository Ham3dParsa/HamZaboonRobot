"""Optional local Playwright verification for the standalone financial dashboard.

Run with ``python tools/financial_model/verify_dashboard_ui.py`` when Playwright
and Chromium are available locally. The repository's regular pytest suite keeps
the source-level checks because browser dependencies are not project-managed.
"""

from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright


URL = Path(__file__).with_name("financial_model_dashboard.html").resolve().as_uri()


def visible(locator):
    for index in range(locator.count()):
        item = locator.nth(index)
        if item.is_visible():
            return item
    raise AssertionError("No visible control found")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(URL, wait_until="networkidle", timeout=120000)

    # default tab is Dashboard; the model table toggle lives in the Settings (inputs) column
    visible(page.get_by_role("button", name=re.compile(r"^تنظیمات"))).click()
    table_toggle = page.get_by_role("button", name=re.compile("قیمت واقعی مدل"))
    table = table_toggle.locator("xpath=..").locator("table")
    expect(table).not_to_be_visible()
    table_toggle.click()
    expect(table).to_be_visible()
    table_toggle.click()
    expect(table).not_to_be_visible()
    # back to Dashboard for the chart/forecast checks that live there
    visible(page.get_by_role("button", name=re.compile(r"^داشبورد"))).click()

    # -- Fix #1: desktop sidebar replaces the floating dock; preference persists --
    sidebar = page.locator("aside.fixed")
    expect(sidebar).to_be_visible()
    expect(sidebar).to_have_class(re.compile(r"w-64"))
    mobile_pill = page.locator("nav.fixed.bottom-4")
    expect(mobile_pill).not_to_be_visible()
    sidebar.locator("button").first.click()
    expect(sidebar).to_have_class(re.compile(r"w-20"))
    page.reload(wait_until="networkidle", timeout=120000)
    sidebar = page.locator("aside.fixed")
    expect(sidebar).to_have_class(re.compile(r"w-20"))
    sidebar.locator("button").first.click()
    expect(sidebar).to_have_class(re.compile(r"w-64"))

    # -- Fix #3: all chart panels use CSS-grid accordions and persist state --
    chart_grids = page.locator(".accordion-grid")
    chart_toggles = page.get_by_role("button", name="باز/بسته")
    assert chart_grids.count() == 4
    assert chart_toggles.count() == 4
    for index in range(4):
        grid = chart_grids.nth(index)
        expect(grid).to_have_class(re.compile(r"open"))
        chart_toggles.nth(index).click()
        expect(grid).not_to_have_class(re.compile(r"open"))
    page.reload(wait_until="networkidle", timeout=120000)
    chart_grids = page.locator(".accordion-grid")
    for index in range(4):
        expect(chart_grids.nth(index)).not_to_have_class(re.compile(r"open"))
        page.get_by_role("button", name="باز/بسته").nth(index).click()
        expect(chart_grids.nth(index)).to_have_class(re.compile(r"open"))

    # -- Fix #2: forecast table header + Month column are sticky, numbers tabular --
    th_month = page.locator("thead th.sticky").first
    expect(th_month).to_have_text("زمان")
    forecast = page.locator("table.forecast-table")
    header_count = forecast.locator("thead th").count()
    body_count = forecast.locator("tbody tr").first.locator("td").count()
    assert header_count == body_count
    pos = forecast.locator("tbody td.sticky").first.evaluate("(el) => getComputedStyle(el).position")
    assert pos == "sticky", pos
    fvn = page.locator("tbody td").nth(1).evaluate("(el) => getComputedStyle(el).fontVariantNumeric")
    assert "tabular-nums" in fvn, fvn

    # -- Fix #2 / T9: on desktop, Settings and Dashboard are exclusive pages --
    # default tab is Dashboard; switch to Settings to reach the pricing table
    visible(page.get_by_role("button", name=re.compile(r"^تنظیمات"))).click()
    pricing_toggle = page.get_by_role("button", name=re.compile(r"^قیمت و سهم — نمای تحلیلی"))
    pricing_card = pricing_toggle.locator("xpath=..")
    pricing_toggle.click()
    assert pricing_card.locator('input[data-plan-analysis="price"]').count() == 4
    assert pricing_card.locator('input[data-plan-analysis="quota"]').count() == 4
    assert pricing_card.locator('input[data-plan-analysis="share"]').count() == 4

    price = pricing_card.locator('input[data-plan-analysis="price"]').first
    price.fill("-100")
    price.press("Tab")
    expect(price).to_have_value("0")

    quota = pricing_card.locator('input[data-plan-analysis="quota"]').first
    quota.fill("999")
    quota.press("Tab")
    expect(quota).to_have_value("100")

    share = pricing_card.locator('input[data-plan-analysis="share"]').first
    peer_share = pricing_card.locator('input[data-plan-analysis="share"]').nth(1)
    peer_before = float(peer_share.input_value())
    share.fill("50")
    share.press("Tab")
    shares = [float(pricing_card.locator('input[data-plan-analysis="share"]').nth(i).input_value()) for i in range(4)]
    assert abs(sum(shares) - 100) < 0.001
    assert float(peer_share.input_value()) != peer_before

    # -- T9: switching to Dashboard hides the Settings (pricing) column --
    visible(page.get_by_role("button", name=re.compile(r"^داشبورد"))).click()
    expect(pricing_card).not_to_be_visible()

    # -- T11/T12: plan editor shows one plan at a time; selects paid plan, edits, adds --
    visible(page.get_by_role("button", name=re.compile(r"^بازاریابی"))).click()
    editor_heading = page.get_by_role("heading", name=re.compile("مدیریت پلن‌ها"))
    editor_card = editor_heading.locator("xpath=../..")
    selector_buttons = editor_card.locator("button[type='button']")
    assert selector_buttons.count() == 5  # one selector button per plan
    # default selection is the free plan; select the first paid plan (bronze)
    selector_buttons.nth(1).click()
    editor_price = editor_card.locator('input[type="number"]').first
    editor_price.fill("-100")
    editor_price.press("Tab")
    expect(editor_price).to_have_value("0")
    editor_quota = editor_card.locator('input[type="number"]').nth(1)
    editor_quota.fill("999")
    editor_quota.press("Tab")
    expect(editor_quota).to_have_value("100")
    # adding a plan selects the newly added plan
    editor_card.get_by_role("button", name=re.compile("افزودن پلن")).click()
    assert selector_buttons.count() == 6
    # only the selected plan editor is visible -> exactly one price + one quota input
    assert editor_card.locator('input[type="number"]').count() == 2

    page.set_viewport_size({"width": 390, "height": 844})
    visible(page.get_by_role("button", name=re.compile(r"^تنظیمات"))).click()
    mobile_pill = page.locator("nav.fixed.bottom-4")
    padding = mobile_pill.evaluate("(el) => [getComputedStyle(el).paddingLeft, getComputedStyle(el).paddingTop]")
    assert padding == ["12px", "8px"], padding
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    assert not errors, errors

    # -- Fix #5: KPI tooltip positions via Floating UI and stays inside the viewport --
    page.set_viewport_size({"width": 1440, "height": 900})
    visible(page.get_by_role("button", name=re.compile(r"^داشبورد"))).click()
    help_label = page.get_by_text("توضیح").first
    help_label.hover()
    tip = page.locator(".bg-ink.text-white.rounded-2xl").first
    expect(tip).to_be_visible()
    tip_pos = tip.evaluate("(el) => getComputedStyle(el.parentElement).position")
    assert tip_pos == "fixed", tip_pos
    box = tip.bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= 1441, box
    assert box["y"] >= -1, box

    context.close()
    browser.close()
    print("Dashboard browser verification passed: T1, T2, T3, sidebar, sticky table, "
          "chart accordion, clamping, mobile, Floating UI tooltip, console clean.")
