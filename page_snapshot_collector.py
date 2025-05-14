"""
页面快照采集器
自动登录系统，抓取关键页面UI片段
"""

import os
from playwright.sync_api import sync_playwright

TEST_URL = "http://10.0.62.222:30050/"
USERNAME = "006"
PASSWORD = "1q2w3e4r5t!!"

def login_and_snapshot():
    os.makedirs("snapshots", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        # 登录页快照（只抓form）
        page.goto(TEST_URL, wait_until="load", timeout=60000)
        login_form = page.locator('form#formLogin').first
        login_form_html = login_form.evaluate("el => el.outerHTML")
        with open("snapshots/login_form.html", "w", encoding="utf-8") as f:
            f.write(login_form_html)
        # 登录
        username_input = page.locator('input#form_item_username, input[placeholder="请输入登录名"]').first
        password_input = page.locator('input#form_item_password, input[placeholder="请输入密码"]').first
        login_button = page.locator('button.login-button, button[type="submit"]', has_text="登 录").first
        username_input.click()
        username_input.fill(USERNAME)
        password_input.click()
        password_input.fill(PASSWORD)
        login_button.click()
        page.wait_for_load_state("load", timeout=60000)
        # 首页快照（只抓主要功能区，比如表格）
        if page.locator('.ant-table').count() > 0:
            table_html = page.locator('.ant-table').first.evaluate("el => el.outerHTML")
            with open("snapshots/index_table.html", "w", encoding="utf-8") as f:
                f.write(table_html)
        # 你可以继续采集其它关键区块
        browser.close()

if __name__ == "__main__":
    login_and_snapshot()