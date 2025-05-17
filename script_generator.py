import requests
import json
import os
import re

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def clean_code_block(text):
    text = text.strip()
    if text.startswith("```") or text.startswith("'''"):
        text = text.split('\n', 1)[-1]
    if text.endswith("```") or text.endswith("'''"):
        text = text.rsplit('\n', 1)[0]
    return text.strip()

def remove_invalid_asserts(code):
    # 去除 assert False 这类无效断言
    return re.sub(r'^\s*assert\s+False.*$', '', code, flags=re.MULTILINE)

def generate_playwright_script(test_case):
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
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    code = response.json()["choices"][0]["message"]["content"]
    code = clean_code_block(code)
    code = remove_invalid_asserts(code)
    return code

if __name__ == "__main__":
    if not os.path.exists("testcases.json"):
        print("testcases.json 不存在，流程终止。")
        exit(1)
    with open("testcases.json", "r", encoding="utf-8") as f:
        try:
            testcases = json.load(f)
        except Exception as e:
            print(f"testcases.json 解析失败: {e}")
            exit(1)
    for idx, testcase in enumerate(testcases):
        code = generate_playwright_script(json.dumps(testcase, ensure_ascii=False, indent=2))
        filename = f"playwright_test_{idx+1}.py"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)