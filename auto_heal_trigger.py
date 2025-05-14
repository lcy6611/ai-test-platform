import requests
from playwright.sync_api import sync_playwright

DEEPSEEK_API_KEY = "sk-2c7a9791906b429fb5732f2a2e88fbd5"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def clean_code_block(code_str):
    lines = code_str.splitlines()
    in_code_block = False
    code_lines = []
    found_code_block = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            found_code_block = True
            continue
        if in_code_block:
            code_lines.append(line)
    if found_code_block:
        return "\n".join(code_lines)
    else:
        return code_str

def trigger_auto_heal(script_path, error_message, test_url, selector="body"):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(test_url, wait_until="load", timeout=60000)
        ui_fragment = page.locator(selector).evaluate("el => el.outerHTML")
        browser.close()
    with open(script_path, "r", encoding="utf-8") as f:
        old_script = f.read()
    prompt = (
        "以下是原始Playwright自动化测试脚本、最新页面UI片段和故障诊断信息，请根据新UI结构和故障原因修复脚本中的元素定位和操作，"
        "所有注释请用三引号\"\"\"注释内容\"\"\"风格，保持脚本可直接运行：\n"
        f"原始脚本：\n{old_script}\n"
        f"新UI片段：\n{ui_fragment}\n"
        f"故障诊断信息：{error_message}\n"
        "请只输出修复后的完整Python代码，不要输出任何解释说明。"
    )
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}]
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    resp_json = response.json()
    if "choices" in resp_json and resp_json["choices"]:
        healed_script = resp_json["choices"][0]["message"]["content"]
        healed_script = clean_code_block(healed_script)
        healed_path = script_path + ".healed"
        with open(healed_path, "w", encoding="utf-8") as f:
            f.write(healed_script)
        print(f"已生成自愈脚本: {healed_path}")
        return healed_path
    else:
        print("AI自愈失败：", resp_json)
        return None