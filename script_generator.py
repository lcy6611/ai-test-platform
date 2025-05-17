"""
自动脚本创建模块
使用deepseek-chat API将测试用例转为Playwright自动化脚本
"""

import requests
import json
import os
import re
import ast # 用于语法检查
import logging

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def clean_code_block(text):
    """
    去除AI返回的 markdown 代码块标记，包括```python和```等
    """
    text = text.strip()
    if text.startswith("```") or text.startswith("'''"):
        first_newline = text.find('\n')
        if first_newline != -1:
            text = text[first_newline+1:]
    if text.endswith("```") or text.endswith("'''"):
        text = text.rsplit('\n', 1)[0]
    return text.strip()

def remove_invalid_asserts(code):
    """
    自动去除AI生成脚本中的 assert False 相关无效断言
    """
    # 匹配整行的 assert False 或 assert (False)
    return re.sub(r'^\s*assert\s+\(?False\)?\s*$', '', code, flags=re.MULTILINE)


def fix_empty_blocks(code):
    """
    补全 else/except/finally 后面没有代码的情况
    """
    # 1. else/except/finally后紧跟字符串或空行，补pass
    code = re.sub(r'(else|except[^:]*|finally):\s*(?=\n\s*["\'])', r'\1:\n    pass', code)
    code = re.sub(r'(else|except[^:]*|finally):\s*(?=\n\s*\n)', r'\1:\n    pass', code)
    # 2. else/except/finally后直接结束或只有注释的情况
    code = re.sub(r'(else|except[^:]*|finally):\s*($|\n\s*#.*)', r'\1:\n    pass\2', code, flags=re.MULTILINE)
    return code


def ensure_imports(code):
    """
    确保脚本包含必要的 import 语句
    """
    # 必须的导入
    required_imports = {
        "from playwright.sync_api import sync_playwright, expect",
        "import time",
        "import re"
    }

    # 检查已有的导入
    existing_imports = set()
    for line in code.splitlines():
        line = line.strip()
        if line.startswith("import ") or line.startswith("from "):
            existing_imports.add(line)

    # 添加确实的导入
    imports_to_add = required_imports - existing_imports
    if imports_to_add:
        # 将新增的导入放在文件头部
        imports_block = "\n".join(sorted(list(imports_to_add))) + "\n\n"
        # 避免重复导入，只在没有任何必要导入时添加整个块
        if not any(imp in code for imp in required_imports):
             code = imports_block + code
        else:
             # 如果有部分导入，尝试添加到现有导入块之后
             first_import_line = -1
             lines = code.splitlines()
             for i, line in enumerate(lines):
                 if line.strip().startswith("import ") or line.strip().startswith("from "):
                     first_import_line = i
                 elif first_import_line != -1 and not line.strip(): # 找到导入块后的第一个空行
                      lines[first_import_line+1:first_import_line+1] = list(imports_to_add)
                      code = "\n".join(lines)
                      break
             if first_import_line == -1: # 没有找到任何导入行，直接加到文件头部
                 code = imports_block + code


    # 确保期望的导入格式正确（例如expect在from playwright.sync_api导入中）
    # 这是一个额外的安全检查，防止AI生成奇怪的导入语句
    if "from playwright.sync_api import sync_playwright" in code and "expect" not in code:
         code = code.replace(
             "from playwright.sync_api import sync_playwright",
             "from playwright.sync_api import sync_playwright, expect"
         )

    return code


def is_valid_python(code):
    """
    使用AST检查代码是否是合法的Python语法
    """
    try:
        ast.parse(code)
        return True
    except Exception as e:
        logging.debug(f"语法检查失败: {e}")
        return False

def generate_playwright_script(test_case):
    """
    调用deepseek-chat API，将测试用例转为Playwright+Python自动化测试脚本
    并进行后处理，确保脚本可运行
    """
    if not DEEPSEEK_API_KEY:
        logging.error("DEEPSEEK_API_KEY 环境变量未设置，无法调用API！")
        return ""

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
        "所有if/else/try/except/finally结构必须有代码块，如无实际逻辑请用pass，不要留空，防止IndentationError。"
        "不要用本地文件路径如login_form.html或file:///path/to/login_form.html，"
        "请统一用实际可访问的URL（如 http://10.0.62.222:30050/ ），并确保URL正确。"
        "脚本整体风格规范，注释清晰。"
        f"\n{test_case}"
    )
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=180) # 增加超时时间
        response.raise_for_status()
        resp_json = response.json()

        if "choices" not in resp_json or not resp_json["choices"]:
            logging.error(f"AI返回内容异常或为空: {resp_json}")
            return ""

        code = resp_json["choices"][0]["message"]["content"]
        logging.info("AI原始脚本已获取，开始后处理...")

        # 后处理流程
        code = clean_code_block(code)
        logging.debug(f"清洗markdown后:\n{code[:200]}...")
        code = remove_invalid_asserts(code)
        logging.debug(f"去除无效断言后:\n{code[:200]}...")
        code = fix_empty_blocks(code)
        logging.debug(f"补全空块后:\n{code[:200]}...")
        code = ensure_imports(code)
        logging.debug(f"补全导入后:\n{code[:200]}...")

        # 最终语法检查，如果 still 有问题，尝试一次兜底修复
        if not is_valid_python(code):
            logging.warning("代码依然存在语法问题，尝试兜底补全空块...")
            code = re.sub(r'(else|except[^:]*|finally):\s*($|\n\s*#.*)', r'\1:\n    pass\2', code, flags=re.MULTILINE)
            code = ensure_imports(code) # 再次确保导入
            if not is_valid_python(code):
                 logging.error("代码经过兜底修复后仍存在语法问题，请检查AI输出或修复逻辑。")
                 return "" # 返回空字符串表示生成失败

        logging.info("脚本后处理完成，语法检查通过。")
        return code

    except requests.exceptions.RequestException as e:
        logging.error(f"调用 deepseek-chat API 请求失败: {e}")
        return ""
    except json.JSONDecodeError as e:
         logging.error(f"解析 deepseek-chat API 返回的JSON失败: {e}")
         return ""
    except Exception as e:
        logging.error(f"生成Playwright脚本过程中发生未知错误: {e}")
        return ""


if __name__ == "__main__":
    logging.info("开始生成Playwright自动化脚本...")
    # 清理历史无效脚本，避免pytest收集到旧文件
    for fname in os.listdir("."):
        if fname.startswith("playwright_test_") and fname.endswith((".py", ".error.py", ".healed")):
            try:
                os.remove(fname)
                logging.debug(f"已清理旧脚本文件: {fname}")
            except OSError as e:
                logging.warning(f"清理旧脚本文件失败 {fname}: {e}")


    if not os.path.exists("testcases.json"):
        logging.error("testcases.json 不存在，流程终止。请先运行用例生成步骤。")
        exit(1)

    with open("testcases.json", "r", encoding="utf-8") as f:
        try:
            testcases = json.load(f)
            if not isinstance(testcases, list) or not testcases:
                 logging.error("testcases.json 内容不是非空JSON数组，流程终止。")
                 exit(1)
        except Exception as e:
            logging.error(f"testcases.json 解析失败: {e}")
            exit(1)

    successful_scripts = 0
    for idx, testcase in enumerate(testcases):
        # 检查测试用例结构是否有效，至少包含scene和steps
        if not isinstance(testcase, dict) or "scene" not in testcase or "steps" not in testcase:
             logging.warning(f"跳过无效测试用例 (索引 {idx}): {testcase}")
             continue

        logging.info(f"正在为用例 '{testcase.get('scene', f'用例 {idx+1}')}' 生成脚本...")
        # 将用例转换为JSON字符串传递给AI
        testcase_json_str = json.dumps(testcase, ensure_ascii=False, indent=2)
        code = generate_playwright_script(testcase_json_str)

        filename = f"playwright_test_{idx+1}.py"
        if code:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(code)
            logging.info(f"已生成脚本: {filename}")
            successful_scripts += 1
        else:
            # 如果生成失败，可选保存原始AI返回或错误信息
            error_filename = f"playwright_test_{idx+1}.error.py"
            with open(error_filename, "w", encoding="utf-8") as f:
                f.write(f"# 脚本生成失败，原始用例：\n{testcase_json_str}\n# 详细错误请查看日志。")
            logging.error(f"为用例 '{testcase.get('scene', f'用例 {idx+1}')}' 生成脚本失败，已保存错误文件: {error_filename}")


    logging.info(f"脚本生成过程完成，共尝试 {len(testcases)} 条用例，成功生成 {successful_scripts} 条脚本。")
    if successful_scripts == 0:
        logging.error("未成功生成任何Playwright脚本，流程终止。")
        exit(1) # 如果没有生成任何有效脚本，视为失败
