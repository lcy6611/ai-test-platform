"""
自动脚本创建模块
结合用例和页面快照，使用deepseek-chat API生成Playwright自动化脚本
"""

import requests
import json
import os
import ast

DEEPSEEK_API_KEY = "sk-2c7a9791906b429fb5732f2a2e88fbd5"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def read_snapshots():
    snapshots = []
    for fname in os.listdir("snapshots"):
        if fname.endswith(".html"):
            with open(os.path.join("snapshots", fname), "r", encoding="utf-8") as f:
                snapshots.append(f"片段 {fname}:\n{f.read()}")
    return "\n".join(snapshots)

def is_valid_python_code(code_str):
    try:
        ast.parse(code_str)
        return True
    except SyntaxError as e:
        print("生成的代码有语法错误：", e)
        return False

def clean_code_block(code_str):
    """
    只保留AI返回的markdown代码块内的内容，如果没有代码块标记则原样返回
    """
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

def generate_playwright_script(test_case, snapshots):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = (
        "请根据以下结构化测试用例和页面关键UI片段，生成Playwright+Python自动化测试脚本。\n"
        "要求：\n"
        "1. 只输出完整、可直接运行的Python代码，不要输出任何解释或伪代码。\n"
        "2. 必须包含所有必要的import、函数定义、主入口。\n"
        "3. 所有注释都用三引号\"\"\"注释内容\"\"\"风格，不要用#。\n"
        "4. 测试函数不要带任何参数，统一用with sync_playwright() as p:方式启动Playwright。\n"
        "5. 登录步骤：登录地址为 http://10.0.62.222:30050/，用户名为006，密码为1q2w3e4r5t!!。\n"
        "6. 登录时请自动分析页面，优先通过placeholder、label、input type、按钮文本等方式智能定位用户名、密码输入框和登录按钮，避免写死选择器。\n"
        "7. 所有输入框在输入内容前都要先点击输入框（即先 .click() 再 .fill()），不要省略。\n"
        "8. 登录成功后再执行后续测试步骤。\n"
        "9. 结合页面关键UI片段内容，智能定位和操作页面元素。\n"
        "10. 断言、等待、异常处理要健壮，代码风格规范。\n"
        "11. 只输出代码，不要输出任何解释说明。\n"
        f"用例内容：\n{test_case}\n"
        f"页面关键UI片段：\n{snapshots}\n"
    )
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    resp_json = response.json()
    if "choices" in resp_json and resp_json["choices"]:
        return resp_json["choices"][0]["message"]["content"]
    else:
        raise Exception(f"API返回异常：{resp_json}")

if __name__ == "__main__":
    with open("testcases.json", "r", encoding="utf-8") as f:
        test_cases = json.load(f)
    snapshots = read_snapshots()
    for idx, case in enumerate(test_cases):
        script_filename = f"playwright_test_{idx+1}.py"
        if os.path.exists(script_filename):
            print(f"{script_filename} 已存在，跳过生成。")
            continue
        try:
            script = generate_playwright_script(json.dumps(case, ensure_ascii=False), snapshots)
            print(f"AI原始返回内容（{script_filename}）：\n{script}\n{'='*60}")
            script = clean_code_block(script)
            if not script.strip():
                print(f"AI返回内容为空，未生成脚本: {script_filename}")
                continue
            if is_valid_python_code(script):
                with open(script_filename, "w", encoding="utf-8") as f:
                    f.write(script)
                print(f"已生成脚本: {script_filename}")
                # 可选：自动格式化
                try:
                    os.system(f"black {script_filename}")
                except Exception:
                    pass
            else:
                error_filename = script_filename.replace(".py", ".error.py")
                with open(error_filename, "w", encoding="utf-8") as f:
                    f.write(script)
                print(f"生成的脚本有语法错误，请人工修正: {error_filename}")
        except Exception as e:
            print(f"生成 {script_filename} 失败，原因：{e}")