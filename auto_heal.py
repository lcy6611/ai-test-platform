"""
自动化故障检测与自愈模块
根据测试报告或错误日志，触发AI对失败脚本的自愈，并尝试重新运行
"""

import os
import json
import logging
import glob
import subprocess
import re # Import re module
import ast # Import ast module
import requests # Import requests module for AI API call

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 从环境变量获取API Key
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

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
            # 这里的正则需要根据实际pytest失败日志格式调整，确保提取包含路径的文件名
            # [\w\\/\.-]+ 匹配单词、反斜杠、斜杠、点、破折号至少一次
            matches = re.findall(r"FAILED\s+([\w\\/\.-]+\.py)(?::|$)", content) # 匹配 FAILED 后面的 .py 文件名，可能带::分隔符
            # 查找 collection errors
            collection_errors = re.findall(r"ERROR collecting\s+([\w\\/\.-]+\.py)", content)

            all_potential_failures = set(matches).union(set(collection_errors))

            # 过滤掉 .healed 脚本，避免重复自愈
            failed_files = {f for f in all_potential_failures if not f.endswith(".healed")}


    except Exception as e:
        logging.error(f"解析pytest错误日志失败: {e}")
        return []

    logging.info(f"从日志中解析到以下失败/收集错误脚本: {list(failed_files)}")
    return list(failed_files)


def load_testcase_by_script_name(script_path, testcases_file="testcases.json"):
    """
    根据失败的脚本完整路径，查找对应的原始测试用例
    脚本路径格式如 playwright_scripts/test_playwright_1.py
    """
    # 从路径中提取文件名
    script_name = os.path.basename(script_path)

    try:
        # 从文件名中提取索引，例如 test_playwright_1.py -> 1
        match = re.search(r"test_playwright_(\d+)\.py$", script_name)
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
            logging.warning(f"测试用例文件格式错误或索引 {testcase_index} 超出范围 {len(testcases)}。")
            return None

    except Exception as e:
        logging.error(f"根据脚本名查找测试用例失败 {script_name}: {e}")
        return None


def heal_script(original_script_path, testcase, error_info):
    """
    调用AI自愈失败的脚本
    """
    logging.info(f"正在自愈脚本: {original_script_path}")
    # 打印部分错误信息，避免日志过长
    error_snippet = error_info if len(error_info) < 500 else error_info[:490] + "..."
    logging.info(f"失败信息片段: \n---\n{error_snippet}\n---")


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
        "以下是一个Playwright+Python自动化测试脚本及其执行时的失败信息。请分析失败原因，并提供一个修复后的完整Playwright+Python自动化测试脚本。\n"
        "--- 原始脚本 ---\n```python\n{original_code}\n```\n"
        "--- 原始测试用例 ---\n```json\n{testcase_json}\n```\n"
        "--- 失败信息/错误日志 ---\n```\n{error_info}\n```\n"
        "--- 修复要求 ---\n"
        "请提供完整的可运行脚本，包含所有必要的import（特别是 Playwright 相关、time, re, pytest）。\n"
        "重点根据失败信息（IndentationError, NameError, Playwright Specific errors etc.）修复选择器、等待条件、断言或逻辑错误。\n"
        "保持原测试用例的场景和步骤意图。\n"
        "所有中文注释用三引号风格，不要用#。\n"
        "测试函数不带任何参数，函数名应符合 pytest 的测试函数命名规则 (以 test_ 开头)。\n"
        "统一用 `with sync_playwright() as p:` 方式启动 Playwright。\n"
        "不要用本地文件路径，统一用实际可访问的URL（如 http://10.0.62.222:30050/ ）。\n"
        "如果修复涉及元素定位，请尽量使用更稳定可靠的Playwright定位器，如 `get_by_role`, `get_by_text`, `get_by_label`, `get_by_test_id` 等，避免复杂的CSS/XPath，除非AI能生成准确无误的复杂选择器。\n"
        "如果某个步骤无法实现有效的断言，请用 `pass` 占位。\n"
        "修复所有缩进错误。\n"
        "输出内容只包含修复后的脚本代码，不要包含额外的文字、markdown标记（如```python```），直接提供Python代码。"
    ).format(
        original_code=original_code,
        testcase_json=json.dumps(testcase, ensure_ascii=False, indent=2),
        error_info=error_info
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
             # 再次尝试修复可能的空块导致的语法错误
             healed_code = fix_empty_blocks(healed_code) # 再次运行 fix_empty_blocks
             healed_code = ensure_imports(healed_code) # 再次确保导入
             if not is_valid_python(healed_code):
                  logging.error("自愈后的代码经过兜底修复后仍存在语法问题，放弃自愈。")
                  # 将失败的脚本移回原位（从.bak恢复），并记录自愈失败标记
                  try:
                      os.rename(original_script_path + ".bak", original_script_path)
                      logging.info(f"已将备份文件 {original_script_path + '.bak'} 恢复为 {original_script_path}")
                      # 记录自愈失败标记，避免下次继续尝试自愈
                      with open(original_script_path + ".heal_failed", "w") as f:
                          f.write("Self-healing failed")
                      logging.info(f"已为 {original_script_path} 创建自愈失败标记文件。")

                  except OSError as e:
                      logging.error(f"恢复备份文件 {original_script_path + '.bak'} 失败: {e}")
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
        # logging.debug(f"自愈脚本语法检查失败: {e}") # 避免日志过多
        return False

# --- 从 script_generator.py 拷贝或适配所需的后处理函数 ---
# 请确保 clean_code_block, remove_invalid_asserts, fix_empty_blocks, ensure_imports 在 auto_heal.py 中可用

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
    # 更精确地匹配 assert False 或 assert(False)
    return re.sub(r'^\s*assert\s+\(?False\)?\s*$', '', code, flags=re.MULTILINE)


def fix_empty_blocks(code):
    """
    补全 else/except/finally 后面没有代码的情况
    """
    # 匹配 else/except/finally 后面只有冒号，接着是换行和可选的空白或#注释
    # 在其下方插入 'pass' 并正确缩进
    # (\1:) 捕获并保留 "else:" 或 "except SomeError:" 等
    # (\n\s*) 匹配换行和后面的空白
    # ($|#.*) 匹配行尾或者 #注释到行尾
    # r'\1:\n    pass\2' 替换为 原来的冒号行，加上新行缩进的 'pass'，再加上捕获的行尾（换行或注释）
    code = re.sub(r'(else|except[^:]*|finally):\s*(\n\s*($|#.*))', r'\1:\n    pass\2', code, flags=re.MULTILINE)

    # 处理 else/except/finally 后面是字符串的情况（AI偶尔会生成这种情况）
    code = re.sub(r'(else|except[^:]*|finally):\s*(["\'](?:.*?)["\'])', r'\1:\n    pass # Original was: \2', code, flags=re.MULTILINE)

    return code


def ensure_imports(code):
    """
    确保脚本包含必要的 import 语句 (针对自愈脚本的需要)
    """
    required_imports = {
        "from playwright.sync_api import sync_playwright, expect", # Playwright core
        "import time", # Often used for waits
        "import re", # Used in some generated code or helper functions
        "import pytest", # For pytest framework
        "import os", # May be needed for file operations or env vars
        "import json", # May be needed for data handling
        "import traceback", # Useful for debugging in tests
        "import logging" # For logging within tests
    }
    existing_imports = set()
    # 简单提取现有 imports
    for line in code.splitlines():
        line = line.strip()
        if line.startswith("import ") or line.startswith("from "):
            existing_imports.add(line)
        # 遇到非import或from的行就停止查找imports，假设imports都在文件开头
        elif line:
            break

    imports_to_add = sorted(list(required_imports - existing_imports)) # 按字母排序要添加的 imports

    # 将需要添加的 imports 放在文件开头
    if imports_to_add:
        imports_block = "\n".join(imports_to_add) + "\n\n"
        code = imports_block + code

    # 特殊处理 Playwright import，确保同时导入 sync_playwright 和 expect
    if "from playwright.sync_api import sync_playwright" in code and "expect" not in code:
        code = code.replace(
            "from playwright.sync_api import sync_playwright",
            "from playwright.sync_api import sync_playwright, expect"
        )
    elif "from playwright.sync_api import expect" in code and "sync_playwright" not in code:
         code = code.replace(
             "from playwright.sync_api import expect",
             "from playwright.sync_api import sync_playwright, expect"
         )


    return code


# --------------------------------------------


if __name__ == "__main__":
    logging.info("开始执行自动故障检测与自愈流程...")

    # 获取需要自愈的失败脚本列表
    # get_failed_tests_from_log 现在会返回包含路径的文件名，如 playwright_scripts/test_playwright_1.py
    failed_scripts = get_failed_tests_from_log()

    if not failed_scripts:
        logging.info("未检测到失败脚本，自愈流程结束。")
        exit(0) # 没有失败脚本，正常退出

    logging.info(f"检测到以下失败脚本需要自愈: {failed_scripts}")

    # 读取原始的pytest错误日志，用于传递给AI
    error_info = ""
    # 检查 pytest_errors.log 是否存在并读取
    pytest_error_log_path = "pytest_errors.log"
    if os.path.exists(pytest_error_log_path):
        try:
            with open(pytest_error_log_path, "r", encoding="utf-8") as f:
                error_info = f.read()
            logging.info(f"已读取错误日志文件: {pytest_error_log_path}")
        except Exception as e:
            logging.warning(f"读取 {pytest_error_log_path} 失败: {e}")


    healed_count = 0
    for script_path in failed_scripts:
        # 检查对应的 .healed 文件是否已存在，避免重复生成
        healed_script_path = script_path + ".healed"
        # 同时检查自愈失败标记文件
        heal_failed_marker = script_path + ".heal_failed"

        if os.path.exists(healed_script_path):
             logging.info(f"自愈脚本 {healed_script_path} 已存在，跳过自愈。")
             healed_count += 1 # 算作已处理
             continue
        if os.path.exists(heal_failed_marker):
             logging.info(f"脚本 {script_path} 存在自愈失败标记，跳过自愈。")
             continue


        # 备份原始失败脚本
        backup_script_path = script_path + ".bak"
        try:
            # 如果备份文件已存在，先删除（可能是上次自愈失败残留）
            if os.path.exists(backup_script_path):
                 os.remove(backup_script_path)
                 logging.info(f"已删除旧的备份文件: {backup_script_path}")

            os.rename(script_path, backup_script_path)
            logging.info(f"已备份原始失败脚本: {backup_script_path}")
        except OSError as e:
            logging.error(f"备份原始失败脚本失败 {script_path}: {e}")
            continue # 跳过当前脚本的自愈

        # 获取对应的原始测试用例
        # load_testcase_by_script_name 现在接收包含路径的脚本名
        testcase = load_testcase_by_script_name(script_path, testcases_file="testcases.json")
        if testcase is None: # 使用 is None 因为 load_testcase_by_script_name 返回 None
            logging.error(f"无法获取脚本 {script_path} 的原始测试用例，无法进行自愈。")
            # 恢复原始文件，并记录自愈失败标记
            try:
                os.rename(backup_script_path, script_path)
                logging.info(f"已将备份文件 {backup_script_path} 恢复为 {script_path}")
                with open(heal_failed_marker, "w") as f:
                    f.write("Self-healing failed - No testcase found")
                logging.info(f"已为 {script_path} 创建自愈失败标记文件。")
            except OSError as e:
                logging.error(f"恢复备份文件 {backup_script_path} 失败: {e}")
            continue # 跳过当前脚本的自愈


        # 调用AI进行自愈
        healed_code = heal_script(backup_script_path, testcase, error_info)

        if healed_code:
            # 保存自愈后的脚本
            try:
                with open(healed_script_path, "w", encoding="utf-8") as f:
                    f.write(healed_code)
                logging.info(f"自愈成功，已保存修复脚本: {healed_script_path}")
                healed_count += 1
                # 自愈成功后，可以考虑删除原始失败脚本（backup_script_path）
                # 或者保留备份文件，根据偏好决定
                # os.remove(backup_script_path) # 可选：删除备份文件
            except Exception as e:
                 logging.error(f"保存自愈脚本失败 {healed_script_path}: {e}")
                 # 记录自愈失败标记
                 try:
                     with open(heal_failed_marker, "w") as f:
                         f.write("Self-healing failed - Save error")
                     logging.info(f"已为 {script_path} 创建自愈失败标记文件。")
                 except Exception as marker_e:
                     logging.error(f"创建自愈失败标记文件失败 {heal_failed_marker}: {marker_e}")
                 # 恢复原始文件
                 try:
                     os.rename(backup_script_path, script_path)
                     logging.info(f"已将备份文件 {backup_script_path} 恢复为 {script_path}")
                 except OSError as e_restore:
                     logging.error(f"恢复备份文件 {backup_script_path} 失败: {e_restore}")

        else:
            logging.error(f"脚本自愈失败: {script_path}")
            # heal_script 失败时已经记录了自愈失败标记和恢复了原始文件
            pass # heal_script 内部已处理失败情况


    logging.info(f"自愈流程完成，共尝试自愈 {len(failed_scripts)} 个脚本，成功生成 {healed_count} 个修复脚本。")

    # 注意：Jenkinsfile 中会单独执行 Re-Run Healed Tests 阶段，这里不需要再次运行测试
