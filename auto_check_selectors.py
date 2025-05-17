import os
import re
from playwright.sync_api import sync_playwright

TEST_URL = "http://10.0.62.222:30050/"

def extract_selectors(script_path):
    selectors = []
    with open(script_path, "r", encoding="utf-8") as f:
        code = f.read()
    patterns = [
        r'page\.locator\((r?["\'])(.+?)\1\)',
        r'page\.get_by_label\((r?["\'])(.+?)\1\)',
        r'page\.get_by_text\((r?["\'])(.+?)\1\)',
    ]
    for pat in patterns:
        for m in re.finditer(pat, code):
            selectors.append((pat.split("\\")[1], m.group(2)))
    return selectors

def check_selectors_on_page(selectors):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TEST_URL)
        for sel_type, sel in selectors:
            try:
                if sel_type == "locator":
                    el = page.locator(sel)
                elif sel_type == "get_by_label":
                    el = page.get_by_label(sel)
                elif sel_type == "get_by_text":
                    el = page.get_by_text(sel)
                else:
                    continue
                count = el.count()
                if count == 0:
                    print(f"[NOT FOUND] {sel_type}: {sel}")
                else:
                    print(f"[OK] {sel_type}: {sel} (found {count})")
            except Exception as e:
                print(f"[ERROR] {sel_type}: {sel} -> {e}")
        browser.close()

if __name__ == "__main__":
    for fname in os.listdir('.'):
        if fname.startswith("playwright_test_") and fname.endswith(".py"):
            print(f"\n检测脚本: {fname}")
            selectors = extract_selectors(fname)
            if not selectors:
                print("未检测到选择器")
                continue
            check_selectors_on_page(selectors)