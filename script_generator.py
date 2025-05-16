"""
自动脚本创建模块
使用deepseek-chat API将测试用例转为Playwright自动化脚本
"""

import requests
import json
import os
import re

DEEPSEEK_API_KEY = "sk-2c7a9791906b429fb5732f2a2e88fbd5"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def generate_playwright_script(test_case):
    """
    调用deepseek-chat API，将测试用例转为Playwright+Python自动化脚本。
    要求所有注释都用三引号风格，且测试函数不带任何参数，统一用with sync_playwright() as p:方式启动Playwright。
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = (
        "请将以下测试用例转化为Playwright+Python自动化测试脚本，"
        "要求可直接运行，包含必要的import和断言，"
        "所有中文注释都用三引号风格，不要用#，"
        "测试函数不要带任何参数，统一用with sync_playwright() as p:方式启动Playwright。"
        "不要生成 assert False 这种占位断言，遇到无法实现的断言请用 pass 占位。"
        "不要用本地文件路径如login_form.html或file:///path/to/login_form.html，"
        "请统一用实际可访问的URL（如 http://10.0.62.222:30050/ ），"
        "脚本整体风格规范。"
        f"\n{test_case}"
    )
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"]

def clean_code_block(text):
    """
    去除AI返回的 markdown 代码块标记，包括```python和```等
    """
    text = text.strip()
    # 去除 ```python 或 ``` 开头
    if text.startswith("```python"):
        text = text[9:]
    elif text.startswith("```"):
        text = text[3:]
    # 去除结尾 ```
    if text.strip().endswith("```"):
        text = text.strip()[:-3]
    return text.strip()

def remove_invalid_asserts(script: str) -> str:
    """
    自动去除AI生成脚本中的 assert False 相关无效断言
    """
    script = re.sub(r'^\s*assert\s+False.*$', '', script, flags=re.MULTILINE)
    return script

def ensure_imports(script: str) -> str:
    """
    确保脚本包含必要的 import 语句
    """
    imports = "from playwright.sync_api import sync_playwright\nimport time\n"
    if "from playwright.sync_api import sync_playwright" not in script:
        script = imports + script
    return script

if __name__ == "__main__":
    # 清理历史无效脚本，避免pytest收集到旧文件
    for fname in os.listdir('.'):
        if fname.startswith("playwright_test_") and fname.endswith(".py"):
            os.remove(fname)
    with open("testcases.json", "r", encoding="utf-8") as f:
        test_cases = json.load(f)
    for idx, case in enumerate(test_cases):
        script_filename = f"playwright_test_{idx+1}.py"
        script = generate_playwright_script(json.dumps(case, ensure_ascii=False))
        script = clean_code_block(script)
        script = remove_invalid_asserts(script)
        script = ensure_imports(script)
        with open(script_filename, "w", encoding="utf-8") as f:
            f.write(script)
        print(f"已生成脚本: {script_filename}")