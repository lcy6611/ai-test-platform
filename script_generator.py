import requests
import json
import os
import re

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-xxx")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def read_snapshots():
    if not os.path.exists("snapshots"):
        return ""
    snapshots = []
    for fname in os.listdir("snapshots"):
        if fname.endswith(".html"):
            with open(os.path.join("snapshots", fname), "r", encoding="utf-8") as f:
                snapshots.append(f"页面 {fname} 快照:\n{f.read()}")
    return "\n".join(snapshots)

def generate_playwright_script(test_case, snapshots):
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
        "所有控件操作前必须先click再fill。"
        "请严格根据以下页面快照/HTML结构生成Playwright选择器，优先使用id、name、data-testid等唯一属性，不要凭空猜测class或结构。"
        "不要用本地文件路径如login_form.html或file:///path/to/login_form.html，"
        "请统一用实际可访问的URL（如 http://10.0.62.222:30050/ ），"
        "脚本整体风格规范。\n"
        f"页面快照如下：\n{snapshots}\n"
        f"测试用例如下：\n{test_case}"
    )
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"]

def clean_code_block(text):
    text = text.strip()
    if text.startswith("```python"):
        text = text[9:]
    elif text.startswith("```"):
        text = text[3:]
    if text.strip().endswith("```"):
        text = text.strip()[:-3]
    return text.strip()

def remove_invalid_asserts(script: str) -> str:
    script = re.sub(r'^\s*assert\s+False.*$', '', script, flags=re.MULTILINE)
    return script

def ensure_imports(script: str) -> str:
    imports = "from playwright.sync_api import sync_playwright, expect\nimport time\n"
    if "from playwright.sync_api import sync_playwright" not in script:
        script = imports + script
    return script

if __name__ == "__main__":
    for fname in os.listdir('.'):
        if fname.startswith("playwright_test_") and fname.endswith(".py"):
            os.remove(fname)
    with open("testcases.json", "r", encoding="utf-8") as f:
        test_cases = json.load(f)
    snapshots = read_snapshots()
    for idx, case in enumerate(test_cases):
        script_filename = f"playwright_test_{idx+1}.py"
        script = generate_playwright_script(json.dumps(case, ensure_ascii=False), snapshots)
        script = clean_code_block(script)
        script = remove_invalid_asserts(script)
        script = ensure_imports(script)
        with open(script_filename, "w", encoding="utf-8") as f:
            f.write(script)
        print(f"已生成脚本: {script_filename}")