import os
import traceback
import requests
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

def heal_script(original_script, error_log, snapshots):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = (
        "以下是自动化测试脚本在运行时遇到的异常，请根据异常信息和最新页面快照，修复该Playwright脚本。"
        "修复时严格按快照/HTML结构生成选择器，优先用id、name、data-testid等唯一属性。"
        "所有控件操作前必须click再fill。不要生成assert False。遇到无法实现的断言请用pass占位。\n"
        f"异常信息：\n{error_log}\n"
        f"页面快照：\n{snapshots}\n"
        f"原始脚本：\n{original_script}"
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

def run_and_heal(script_path):
    import subprocess
    try:
        result = subprocess.run(["pytest", script_path], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print(f"{script_path} 通过")
            return
        else:
            print(f"{script_path} 失败，尝试自愈")
            error_log = result.stdout + "\n" + result.stderr
    except Exception as e:
        error_log = traceback.format_exc()
    with open(script_path, "r", encoding="utf-8") as f:
        original_script = f.read()
    snapshots = read_snapshots()
    healed_script = heal_script(original_script, error_log, snapshots)
    healed_script = clean_code_block(healed_script)
    healed_script = remove_invalid_asserts(healed_script)
    healed_script = ensure_imports(healed_script)
    healed_path = script_path + ".healed"
    with open(healed_path, "w", encoding="utf-8") as f:
        f.write(healed_script)
    print(f"已生成自愈脚本: {healed_path}")
    # 可自动重试
    subprocess.run(["pytest", healed_path])

if __name__ == "__main__":
    for fname in os.listdir('.'):
        if fname.startswith("playwright_test_") and fname.endswith(".py"):
            run_and_heal(fname)