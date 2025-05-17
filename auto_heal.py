"""
自动化故障检测与自愈模块
根据测试报告或错误日志，触发AI对失败脚本的自愈，并尝试重新运行
"""

import os
import json
import logging
import glob
import subprocess

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 假设失败信息会写入 pytest_errors.log (由 run_tests.py 生成)
# 假设AI生成的修复脚本以 .healed 结尾

def get_failed_tests_from_log(log_file="pytest_errors.log"):
    """
    从pytest错误日志中解析失败的测试文件列表 (简易解析，可根据实际日志格式调整)
    更健壮的方式是解析Allure报告或JUnit XML报告
    """
    failed_files = set()
    if not os.path.exists(log_file):
        logging.info("未找到 pytest 错误日志文件，跳过自愈。")
        return []

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
            # 查找类似 "FAILED path/to/test_file.py::test_name" 的行
            # 或者查找测试文件名的模式
            # 这里的正则需要根据实际pytest失败日志格式调整
            matches = re.findall(r"FAILED\s+([\w\\/\.-]+\.py)::", content)
            # 过滤掉 .healed 脚本，避免重复自愈
            failed_files = {f for f in matches if not f.endswith(".healed")}

            # 检查是否有 NameError 或 IndentationError 等收集错误
            collection_errors = re.findall(r"ERROR collecting\s+([\w\\/\.-]+\.py)", content)
            failed_files.update({f for f in collection_errors if not f.endswith(".healed")})


    except Exception as e:
        logging.error(f"解析pytest错误日志失败: {e}")
        return []

    logging.info(f"从日志中解析到以下失败/收集错误脚本: {failed_files}")
    return list(failed_files)


def load_testcase_by_script_name(script_name, testcases_file="testcases.json"):
    """
    根据失败的脚本文件名，查找对应的原始测试用例
    脚本文件名格式如 playwright_test_1.py
    """
    try:
        # 从文件名中提取索引，例如 playwright_test_1.py -> 1
        match = re.search(r"playwright_test_(\d+)\.py$", script_name)
        if not match:
            logging.warning(f"脚本文件名格式不匹配，无法找到对应用例: {script_name}")
            return None

        testcase_index = int(match.group(1)) - 1 # 索引从0开始

        if not os.path.exists(testcases_file):
            logging.error(f"未找到测试用例文件: {testcases_file}")
            return None

        with open(testcases_file, "r", encoding="utf-8") as f:
            testcases = json.load(f)

        if isinstance(testcases, list) and 0 <= testcase_index < len(testcases):
            return testcases[testcase_index]
        else:
            logging.warning(f"测试用例文件格式错误或索引超出范围: {testcase_index}")
            return None

    except Exception as e:
        logging.error(f"根据脚本名查找测试用例失败 {script_name}: {e}")
        return None


def heal_script(original_script_path, testcase, error_info):
    """
    调用AI自愈失败的脚本
    """
    logging.info(f"正在自愈脚本: {original_script_path}")
    logging.info(f"失败信息: {error_info[:200]}...") # 打印部分错误信息

    # 读取原始失败脚本内容
    try:
        with open(original_script_path, "r", encoding="utf-8") as f:
            original_code = f.read()
    except Exception as e:
        logging.error(f"读取原始失败脚本失败 {original_script_path}: {e}")
        return ""

    if not DEEPSEEK_API_KEY:
        logging.error("DEEPSEEK_API_KEY 环境变量未设置，无法调用API进行自愈！")
        return ""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    # 构建自愈prompt
    prompt = (
        "以下是一个Playwright+Python自动化测试脚本及其执行时的失败信息：\n"
        f"原始脚本:\n```python\n{original_code}\n```\n"
        f"测试用例:\n```json\n{json.dumps(testcase, ensure_ascii=False, indent=2)}\n```\n"
        f"失败信息/错误日志:\n```\n{error_info}\n```\n"
        "请分析失败原因，并提供一个修复后的完整Playwright+Python自动化测试脚本。\n"
        "要求：\n"
        "1. 提供完整的可运行脚本，包含所有import。\n"
        "2. 重点根据失败信息修复选择器、等待条件、断言或逻辑错误。\n"
        "3. 保持原测试用例的场景和步骤意图。\n"
        "4. 所有中文注释用三引号风格，不要用#。\n"
        "5. 测试函数不带任何参数，统一用with sync_playwright() as p:方式启动。\n"
        "6. 不要用本地文件路径，统一用实际可访问的URL。\n"
        "7. 如果修复涉及元素定位，请尽量使用更稳定可靠的Playwright定位器，如 get_by_role, get_by_text, get_by_label, get_by_test_id 等，避免复杂的CSS/XPath。\n"
        "8. 输出内容只包含修复后的脚本代码，不要包含额外的文字或markdown标记，直接提供Python代码。"
    )

    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.5} # 可适当降低temperature使AI更稳定

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=180) # 增加超时时间
        response.raise_for_status()
        resp_json = response.json()

        if "choices" not in resp_json or not resp_json["choices"]:
            logging.error(f"AI自愈返回内容异常或为空: {resp_json}")
            return ""

        healed_code = resp_json["choices"][0]["message"]["content"]
        logging.info("AI自愈脚本已获取，开始后处理...")

        # 后处理（与script_generator类似，确保语法、导入等正确）
        healed_code = clean_code_block(healed_code)
        healed_code = remove_invalid_asserts(healed_code) # 自愈后也可能带无效断言
        healed_code = fix_empty_blocks(healed_code) # 自愈后也可能带空块
        healed_code = ensure_imports(healed_code) # 确保导入

        # 最终语法检查
        if not is_valid_python(healed_code):
             logging.warning("自愈后的代码存在语法问题，尝试兜底补全空块...")
             healed_code = re.sub(r'(else|except[^:]*|finally):\s*($|\n\s*#.*)', r'\1:\n    pass\2', healed_code, flags=re.MULTILINE)
             healed_code = ensure_imports(healed_code) # 再次确保导入
             if not is_valid_python(healed_code):
                  logging.error("自愈后的代码经过兜底修复后仍存在语法问题，放弃自愈。")
                  return "" # 返回空字符串表示自愈失败


        logging.info("自愈脚本后处理完成，语法检查通过。")
        return healed_code

    except requests.exceptions.RequestException as e:
        logging.error(f"调用 deepseek-chat API 自愈请求失败: {e}")
        return ""
    except json.JSONDecodeError as e:
         logging.error(f"解析 deepseek-chat API 自愈返回的JSON失败: {e}")
         return ""
    except Exception as e:
        logging.error(f"自愈脚本过程中发生未知错误: {e}")
        return ""

def is_valid_python(code):
    """
    使用AST检查代码是否是合法的Python语法
    """
    try:
        # 尝试解析代码
        ast.parse(code)
        return True
    except Exception as e:
        # 记录详细的语法错误信息
        logging.debug(f"自愈脚本语法检查失败: {e}")
        return False

# 从 script_generator.py 拷贝所需的后处理函数
# 请确保 clean_code_block, remove_invalid_asserts, fix_empty_blocks, ensure_imports, is_valid_python 在 auto_heal.py 中可用
# 可以直接复制过来，或者将这些函数提取到一个单独的 utils.py 文件中导入使用

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
    return re.sub(r'^\s*assert\s+\(?False\)?\s*$', '', code, flags=re.MULTILINE)

def fix_empty_blocks(code):
    """
    补全 else/except/finally 后面没有代码的情况
    """
    code = re.sub(r'(else|except[^:]*|finally):\s*(?=\n\s*["\'])', r'\1:\n    pass', code)
    code = re.sub(r'(else|except[^:]*|finally):\s*(?=\n\s*\n)', r'\1:\n    pass', code)
    code = re.sub(r'(else|except[^:]*|finally):\s*($|\n\s*#.*)', r'\1:\n    pass\2', code, flags=re.MULTILINE)
    return code

def ensure_imports(code):
    """
    确保脚本包含必要的 import 语句
    """
    required_imports = {
        "from playwright.sync_api import sync_playwright, expect",
        "import time",
        "import re"
    }
    existing_imports = set()
    for line in code.splitlines():
        line = line.strip()
        if line.startswith("import ") or line.startswith("from "):
            existing_imports.add(line)

    imports_to_add = required_imports - existing_imports
    if imports_to_add:
        imports_block = "\n".join(sorted(list(imports_to_add))) + "\n\n"
        if not any(imp in code for imp in required_imports):
             code = imports_block + code
        else:
             first_import_line = -1
             lines = code.splitlines()
             for i, line in enumerate(lines):
                 if line.strip().startswith("import ") or line.strip().startswith("from "):
                     first_import_line = i
                 elif first_import_line != -1 and not line.strip():
                      lines[first_import_line+1:first_import_line+1] = list(imports_to_add)
                      code = "\n".join(lines)
                      break
             if first_import_line == -1:
                 code = imports_block + code

    if "from playwright.sync_api import sync_playwright" in code and "expect" not in code:
         code = code.replace(
             "from playwright.sync_api import sync_playwright",
             "from playwright.sync_api import sync_playwright, expect"
         )

    return code


# --------------------------------------------


if __name__ == "__main__":
    logging.info("开始执行自动故障检测与自愈流程...")

    # 获取需要自愈的失败脚本列表
    failed_scripts = get_failed_tests_from_log()

    if not failed_scripts:
        logging.info("未检测到失败脚本，自愈流程结束。")
        exit(0) # 没有失败脚本，正常退出

    logging.info(f"检测到以下失败脚本需要自愈: {failed_scripts}")

    # 读取原始的pytest错误日志，用于传递给AI
    error_info = ""
    if os.path.exists("pytest_errors.log"):
        try:
            with open("pytest_errors.log", "r", encoding="utf-8") as f:
                error_info = f.read()
        except Exception as e:
            logging.warning(f"读取 pytest_errors.log 失败: {e}")

    healed_count = 0
    for script_name in failed_scripts:
        # 检查对应的 .healed 文件是否已存在，避免重复生成
        healed_script_name = script_name + ".healed"
        if os.path.exists(healed_script_name):
             logging.info(f"自愈脚本 {healed_script_name} 已存在，跳过自愈。")
             healed_count += 1 # 算作已处理
             continue

        # 备份原始失败脚本
        backup_script_name = script_name + ".bak"
        try:
            os.rename(script_name, backup_script_name)
            logging.info(f"已备份原始失败脚本: {backup_script_name}")
        except OSError as e:
            logging.error(f"备份原始失败脚本失败 {script_name}: {e}")
            continue # 跳过当前脚本的自愈

        # 获取对应的原始测试用例
        testcase = load_testcase_by_script_name(script_name)
        if not testcase:
            logging.error(f"无法获取脚本 {script_name} 的原始测试用例，无法进行自愈。")
            continue # 跳过当前脚本的自愈

        # 调用AI进行自愈
        healed_code = heal_script(backup_script_name, testcase, error_info)

        if healed_code:
            # 保存自愈后的脚本
            try:
                with open(healed_script_name, "w", encoding="utf-8") as f:
                    f.write(healed_code)
                logging.info(f"自愈成功，已保存修复脚本: {healed_script_name}")
                healed_count += 1
            except Exception as e:
                 logging.error(f"保存自愈脚本失败 {healed_script_name}: {e}")
        else:
            logging.error(f"脚本自愈失败: {script_name}")

    logging.info(f"自愈流程完成，共尝试自愈 {len(failed_scripts)} 个脚本，成功生成 {healed_count} 个修复脚本。")

    # 注意：Jenkinsfile 中会单独执行 Re-Run Healed Tests 阶段，这里不需要再次运行测试
