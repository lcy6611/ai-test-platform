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
    调用deepseek-chat API，将测试用例转为Playwright+Python自动化脚本
    要求所有注释都用三引号""""""风格，且测试函数不带任何参数，统一用with sync_playwright() as p:方式启动Playwright。
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = (
        "请将以下测试用例转化为Playwright+Python自动化测试脚本，"
        "要求可直接运行，包含必要的import和断言，"
        "所有中文注释都用三引号\"\"\"注释内容\"\"\"风格，不要用#，"
        "测试函数不要带任何参数，统一用with sync_playwright() as p:方式启动Playwright。"
        "不要生成 assert False 这种占位断言，遇到无法实现的断言请用 pass 占位。"
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
    去除AI返回的 markdown 代码块标记
    """
    text = text.strip()
    # 去除三重反引号包裹
    if text.startswith("```"):
        text = text.split('\n', 1)[-1]
        if text.endswith("```"):
            text = text.rsplit('\n', 1)[0]
    return text.strip()

def remove_invalid_asserts(script: str) -> str:
    """
    自动去除AI生成脚本中的 assert False 相关无效断言
    """
    script = re.sub(r'^\s*assert\s+False.*$', '', script, flags=re.MULTILINE)
    return script

if __name__ == "__main__":
    with open("testcases.json", "r", encoding="utf-8") as f:
        test_cases = json.load(f)
    for idx, case in enumerate(test_cases):
        script_filename = f"playwright_test_{idx+1}.py"
        # 如果脚本已存在，则跳过生成
        if os.path.exists(script_filename):
            print(f"{script_filename} 已存在，跳过生成。")
            continue
        script = generate_playwright_script(json.dumps(case, ensure_ascii=False))
        script = clean_code_block(script)
        script = remove_invalid_asserts(script)
        with open(script_filename, "w", encoding="utf-8") as f:
            f.write(script)
        print(f"已生成脚本: {script_filename}")