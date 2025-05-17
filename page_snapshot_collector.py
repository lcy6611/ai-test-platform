import os
from playwright.sync_api import sync_playwright

SNAPSHOT_DIR = "snapshots"
URL = "http://10.0.62.222:30050/"  # 替换为你的实际页面

def collect_snapshot():
    if not os.path.exists(SNAPSHOT_DIR):
        os.makedirs(SNAPSHOT_DIR)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL)
        # 只采集关键片段
        html = page.content()
        # 你可以用 page.locator("form").inner_html() 等采集更小片段
        with open(os.path.join(SNAPSHOT_DIR, "login_form.html"), "w", encoding="utf-8") as f:
            f.write(html)
        browser.close()
        print("页面快照已保存")

if __name__ == "__main__":
    collect_snapshot()