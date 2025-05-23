"""
自动脚本创建模块
使用deepseek-chat API将测试用例转为Playwright自动化脚本
"""

import json
import os
import re
import subprocess  # Import subprocess for running autopep8
import requests
import logging # Import logging module

# 使用loguru进行日志记录，并确保日志文件使用UTF-8编码
# 如果你已经使用了 logging.basicConfig，这里可以选择保留或替换
# logger.add("script_generation.log", rotation="1 MB", encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
TESTCASES_FILE = "testcases.json"  # 修改为实际生成的测试用例文件名


def generate_playwright_script(test_case):
    """
    调用deepseek-chat API，将测试用例转为Playwright+Python自动化脚本。
    要求所有注释都用三引号风格，且测试函数不带任何参数，统一用with sync_playwright() as p:方式启动Playwright。
    """
    if not DEEPSEEK_API_KEY:
        logging.error("DEEPSEEK_API_KEY not set.")
        return ""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    prompt = (
        "请将以下测试用例转化为Playwright+Python自动化测试脚本，"
        "要求可直接运行，包含必要的import和断言，"
        "所有中文注释都用三引号风格，不要用#，"
        "测试函数不要带任何参数，统一用with sync_playwright() as p:方式启动Playwright。"
        "不要生成 assert False 这种占位断言，遇到无法实现的断言请用 pass 占位。"
        # 移除对代码块的额外要求，依赖 autopep8 处理
        # "所有if/else/try/except/finally结构必须有代码块，如无实际逻辑请用pass。"
        "不要用本地文件路径如login_form.html或file:///path/to/login_form.html，"
        "请统一用实际可访问的URL（如 http://10.0.62.222:30050/ ），"
        "脚本整体风格规范，易于阅读和维护。" # 优化prompt，强调规范性和易读性
        f"\n测试用例内容:\n{test_case}" # 明确标记测试用例内容
    )
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=120) # 增加超时
        response.raise_for_status() # Raise an exception for bad status codes
        resp_json = response.json()

        if "choices" not in resp_json or not resp_json["choices"]:
            logging.error(f"AI返回内容异常或为空: {resp_json}")
            return ""

        content = resp_json["choices"][0]["message"]["content"]
        code = clean_code_block(content)
        code = remove_invalid_asserts(code)
        # code = fix_empty_blocks(code) # 移除对 fix_empty_blocks 的调用
        return code
    except requests.exceptions.RequestException as e:
        logging.error(f"调用 deepseek-chat API 失败: {e}")
        return ""
    except Exception as e:
        logging.error(f"生成 Playwright 脚本时发生意外错误: {e}")
        return ""


def clean_code_block(text):
    """
    去除AI返回的 markdown 代码块标记，包括```python和```等
    """
    text = text.strip()
    # 尝试查找是否有 markdown 代码块
    match = re.search(r"```(?:python)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # 如果没有找到 markdown 代码块，尝试清理常见的前后缀
    if text.startswith("'''python"):
        text = text[len("'''python"):].strip()
    elif text.startswith("```python"):
         text = text[len("```python"):].strip()
    elif text.startswith("```") or text.startswith("'''"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]

    if text.endswith("```") or text.endswith("'''"):
        text = text.rsplit("\n", 1)[0]

    # 移除可能的BOM字符
    text = text.lstrip('\ufeff')

    return text.strip()


def remove_invalid_asserts(code):
    """
    自动去除AI生成脚本中的 assert False 相关无效断言
    """
    return re.sub(r"^\s*assert\s+False.*$", "", code, flags=re.MULTILINE)


# 移除 fix_empty_blocks 函数的定义
# def fix_empty_blocks(code):
#     """
#     补全 else/except/finally 后面没有代码的情况
#     """
#     # 1. else/except/finally后紧跟字符串或空行，补pass
#     code = re.sub(
#         r'(else|except[^:]*|finally):\s*(?=\n\s*["\"])', r"\1:\n    pass", code
#     )
#     code = re.sub(r"(else|except[^:]*|finally):\s*(?=\n\s*\n)", r"\1:\n    pass", code)
#     # 2. else/except/finally后直接结束的情况
#     code = re.sub(
#         r"(else|except[^:]*|finally):\s*$", r"\1:\n    pass", code, flags=re.MULTILINE
#     )
#     return code


def ensure_imports(script: str) -> str:
    """
    确保脚本包含必要的 import 语句
    """
    imports_needed = ["from playwright.sync_api import sync_playwright", "import time", "import pytest"]
    # 确保 pytest 被导入，因为我们生成的是 pytest 风格的测试文件

    # 将现有 imports 提取出来
    existing_imports = []
    code_lines = script.splitlines()
    clean_lines = []
    in_imports_block = True

    for line in code_lines:
        stripped_line = line.strip()
        if stripped_line.startswith("import ") or stripped_line.startswith("from "):
            existing_imports.append(stripped_line)
        elif not stripped_line and in_imports_block:
            # 允许import块中有空行
            existing_imports.append(stripped_line)
        else:
            in_imports_block = False
            clean_lines.append(line)

    # 确保所有需要的 import 都存在，并添加到现有 imports 列表的顶部
    for imp in reversed(imports_needed):
        if not any(imp.split(" ")[1] in existing_imp for existing_imp in existing_imports if existing_imp.strip()):
             # 简单检查是否已导入 (可能有from... import...的情况)
             # 一个更完善的检查会更复杂，这里假设简单的字符串匹配够用
             if imp not in existing_imports:
                 existing_imports.insert(0, imp)


    # 重构代码，将 imports 放在顶部
    return "\n".join(existing_imports) + "\n\n" + "\n".join(clean_lines)


if __name__ == "__main__":
    # 清理历史无效脚本，避免pytest收集到旧文件
    # 清理 playwright_scripts 目录下的文件
    script_dir = "playwright_scripts"
    if os.path.exists(script_dir):
        for fname in os.listdir(script_dir):
            if fname.startswith("test_playwright_") and fname.endswith(".py"):
                try:
                    os.remove(os.path.join(script_dir, fname))
                    logging.info(f"已清理历史脚本: {fname}")
                except Exception as e:
                    logging.warning(f"清理历史脚本 {fname} 失败: {e}")


    if not os.path.exists(TESTCASES_FILE):
        logging.error(f"错误：未找到测试用例文件: {TESTCASES_FILE}")
        exit(1)

    testcases = []
    try:
        with open(TESTCASES_FILE, "r", encoding="utf-8") as f:
            testcases = json.load(f)
        logging.info(f"成功加载测试用例文件: {TESTCASES_FILE}")
        if not isinstance(testcases, list) or not testcases:
             logging.error("测试用例文件内容格式不正确或为空。")
             exit(1)

    except json.JSONDecodeError as e:
        logging.error(f"解析测试用例文件 {TESTCASES_FILE} 失败，内容不是合法的 JSON: {e}")
        exit(1)
    except Exception as e:
        logging.error(f"读取或解析测试用例文件 {TESTCASES_FILE} 失败: {e}")
        exit(1)


    logging.info(f"开始生成 {len(testcases)} 个测试脚本...")

    os.makedirs(script_dir, exist_ok=True) # 确保 playwright_scripts 目录存在

    for idx, testcase in enumerate(testcases):
        logging.info(f"正在生成第 {idx+1} 个脚本...")
        code = generate_playwright_script(
            json.dumps(testcase, ensure_ascii=False, indent=2)
        )

        if not code or not code.strip():
             logging.warning(f"第 {idx+1} 个测试用例生成脚本失败或生成了空脚本，跳过。")
             continue # 跳过空脚本

        # 确保引入必要的库并规范格式
        code = ensure_imports(code)

        filename = os.path.join(script_dir, f"test_playwright_{idx+1}.py") # 将生成的脚本保存到 playwright_scripts 目录

        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(code)
            logging.info(f"已生成脚本: {filename}")

            # 使用 autopep8 格式化生成的脚本
            # 确保 autopep8 在执行环境的 PATH 中或者通过完整路径调用
            autopep8_command = ["autopep8", "--in-place", filename] # 修正变量名
            logging.info(f"正在格式化脚本: {filename} 使用命令: {' '.join(autopep8_command)}")

            process = subprocess.run(autopep8_command, capture_output=True, text=True)

            if process.returncode == 0:
                logging.info(f"已格式化脚本: {filename}")
                if process.stdout:
                    logging.debug(f"autopep8 stdout: {process.stdout}")
                if process.stderr:
                    logging.debug(f"autopep8 stderr: {process.stderr}")
            else:
                logging.warning(f"autopep8 格式化脚本 {filename} 失败，退出码: {process.returncode}")
                logging.warning(f"autopep8 stdout: {process.stdout}")
                logging.warning(f"autopep8 stderr: {process.stderr}")
                # 失败但不中断流程，依赖 pytest 报告语法错误

        except FileNotFoundError:
            logging.error("错误: 未找到 autopep8 命令，请确保已安装 (pip install autopep8) 且在 PATH 中。")
            # 致命错误，中断脚本生成流程
            exit(1)
        except Exception as e:
            logging.warning(f"格式化脚本 {filename} 时发生意外错误: {e}")
            # 发生意外，记录警告，但不中断流程

    logging.info("所有测试脚本生成和格式化尝试完成。")