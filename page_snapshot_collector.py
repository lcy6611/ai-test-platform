"""
页面快照采集模块
使用Playwright采集指定页面的HTML快照
"""

import os
import time
from playwright.sync_api import sync_playwright
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 需要采集快照的页面URL列表
TARGET_URLS = [
    "http://10.0.62.222:30050/login", # 示例URL，请根据实际情况修改
    # "http://your_app_url/dashboard", # 更多页面
]

SNAPSHOTS_DIR = "snapshots"

def collect_snapshot(url, output_dir):
    """
    采集单个页面的HTML快照
    """
    try:
        with sync_playwright() as p:
            # 根据需要选择不同的浏览器，例如 p.firefox, p.webkit
            browser = p.chromium.launch()
            page = browser.new_page()

            logging.info(f"正在访问页面: {url}")
            # 等待页面完全加载，根据需要调整等待条件，例如 'networkidle'
            page.goto(url, wait_until="domcontentloaded")
            logging.info(f"页面 {url} 加载完成")

            # 等待额外的异步内容加载，根据实际页面加载情况调整等待时间
            page.wait_for_timeout(2000) # 等待2秒，可根据需要调整

            # 获取页面的完整HTML，包括动态加载的内容
            html_content = page.content()

            # 提取文件名，例如从 http://domain/path/page.html -> page.html
            fname = url.split("/")[-1]
            if not fname:
                fname = "index.html" # 如果URL以/结尾，使用index.html作为文件名
            # 确保文件名合法
            fname = "".join(c for c in fname if c.isalnum() or c in (' ', '.', '_')).rstrip()
            # 防止过长的文件名
            fname = fname[:50] + ".html"

            output_path = os.path.join(output_dir, fname)

            # 保存快照
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            logging.info(f"页面快照已保存到: {output_path}")

            browser.close()

    except Exception as e:
        logging.error(f"采集页面快照失败 {url}: {e}")

if __name__ == "__main__":
    # 创建快照目录
    if not os.path.exists(SNAPSHOTS_DIR):
        os.makedirs(SNAPSHOTS_DIR)

    logging.info(f"开始采集页面快照到目录: {SNAPSHOTS_DIR}")

    # 遍历URL列表，采集快照
    for url in TARGET_URLS:
        collect_snapshot(url, SNAPSHOTS_DIR)

    logging.info("所有页面快照采集完成。")