"""
自动化故障检测与自愈模块
根据测试报告或错误日志，触发AI对失败脚本的自愈，并尝试重新运行
"""

import os
import json
import logging
# import glob # Removed unused import
import subprocess
import re
import requests
import ast # Needed for is_valid_python

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 假设失败信息会写入 pytest_errors.log (由 run_tests.py 生成)
# 假设AI生成的修复脚本以 .healed 结尾

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def clean_code_block(text):
    """
    从AI返回的文本中提取JSON或Python代码块，处理可能的Markdown标记。
    """
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='ignore')
    text = text.lstrip('\ufeff')
    match = re.search(r"```(?:[a-zA-Z]+)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

def ensure_imports(code):
    """
    确保脚本包含必要的导入，如 Playwright 的 sync_playwright, expect 和 re。
    """
    required_imports = [
        "import pytest",
        "from playwright.sync_api import sync_playwright",
        "from playwright.sync_api import expect",
        "import re" # Added re import
    ]
    lines = code.splitlines()
    existing_imports = [line.strip() for line in lines if line.strip().startswith("import") or line.strip().startswith("from")]

    for imp in required_imports:
        # Check if the exact import statement exists or if the module/object is already imported
        if any(imp.split(" import ")[-1] in existing and (imp.split(" import ")[0].replace("import ", "") in existing or imp in existing) for existing in existing_imports):
            continue

        # Find the position to insert the import statement
        insert_index = 0
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith("import") or lines[i].strip().startswith("from"):
                insert_index = i + 1
                break
            if lines[i].strip().endswith('"""') or lines[i].strip().endswith("'''"):
                insert_index = i + 1
                break

        lines.insert(insert_index, imp)
        logging.info(f"Added missing import: {imp}")

    return "\n".join(lines)

def add_wait_before_actions(code):
    """
    在 Playwright 的 fill(), click(), type() 前添加等待元素可见状态。
    注意：这里只添加可见等待，不处理 readonly 导致 fill 失败的问题，
    readonly 问题由 replace_readonly_fill_with_evaluate 处理。
    """
    lines = code.splitlines()
    processed_lines = []
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        # Regex to match Playwright interaction operations on locators or page objects
        # Need to be more robust to different ways locators are created (e.g., page.locator, page.get_by_text, etc.)
        # And different ways methods are called (e.g., .fill(), .click(), .type())
        # Fixed redundant escape in regex
        match_action = re.match(r'^(\s*)(.*?)\.(fill|click|type)\((.*)\)$', line)

        if match_action:
            indent, locator_part, action_method, args = match_action.groups()
            # Check if the line is already a wait_for call to avoid duplicates
            if "wait_for" in action_method:
                 processed_lines.append(line)
                 continue

            # Heuristic: if the line above is a wait_for call for the same locator, skip adding another one
            if processed_lines and processed_lines[-1].strip().startswith(locator_part.strip()) and ".wait_for(" in processed_lines[-1]:
                 processed_lines.append(line)
                 continue

            # Insert wait_for(state='visible') before the action
            wait_line = f"{indent}{locator_part}.wait_for(state='visible', timeout=15000)" # 15秒等待可见
            processed_lines.append(wait_line)
            processed_lines.append(line) # Add the original action line
        else:
            processed_lines.append(line) # Add non-action lines

    return "\n".join(processed_lines)


def replace_readonly_fill_with_evaluate(code):
    """
    检测针对已知 readonly 输入框的 .fill()/.type() 调用，并替换为 page.evaluate()。
    """
    # Define patterns that might match the username/password input fields
    # Using broad regex to catch variations in locators
    readonly_selector_patterns = [
        re.compile(r'#form_item_username'),
        re.compile(r'#form_item_password'),
        re.compile(r'input\[name=[\'\"]?username[\'\"]?\]', re.IGNORECASE),
        re.compile(r'input\[name=[\'\"]?password[\'\"]?\]', re.IGNORECASE),
        re.compile(r'get_by_placeholder\([\'\"]?.*?用户名.*?[\'\"]?\)', re.IGNORECASE),
        re.compile(r'get_by_placeholder\([\'\"]?.*?密码.*?[\'\"]?\)', re.IGNORECASE),
        re.compile(r'get_by_label\([\'\"]?.*?用户名.*?[\'\"]?\)', re.IGNORECASE),
        re.compile(r'get_by_label\([\'\"]?.*?密码.*?[\'\"]?\)', re.IGNORECASE),
        # Add more patterns if other locators are used for these fields
    ]

    lines = code.splitlines()
    processed_lines = []

    for i, line in enumerate(lines):
        stripped_line = line.strip()
        original_indent = line[:len(line) - len(stripped_line)]
        modified = False

        # Regex to find .fill() or .type() calls on any object (assuming it's a locator or page)
        match_fill_type = re.match(r'^(\s*)(.*?)\.(fill|type)\s*\((.*)\)$', line)

        if match_fill_type:
            indent, object_part, method_name, args_part = match_fill_type.groups()

            # Extract the selector string and value from the args or the object_part
            selector = None
            value = None

            # Try to parse as page.fill(selector, value) or page.type(selector, value)
            match_page_method = re.match(r'^\s*(page)\.(fill|type)\s*\(\s*["\'](.*?)["\']\s*,\s*["\'](.*?)["\']\s*\).*$', stripped_line)
            if match_page_method:
                 method_name_page, page_obj, selector_page, value_page = match_page_method.groups()
                 selector = selector_page
                 value = value_page
                 # Check if this selector matches any of the readonly patterns
                 if any(pattern.search(selector) for pattern in readonly_selector_patterns):
                    # Construct page.evaluate() call with doubled curly braces for f-string
                    evaluate_js = "selector => {{ const element = document.querySelector(selector); if (element) {{ element.value = arguments[1]; element.dispatchEvent(new Event('input', {{ bubbles: true }})); element.dispatchEvent(new Event('change', {{ bubbles: true }})); }} }}"
                    evaluate_line = f'{original_indent}{page_obj}.evaluate("{evaluate_js}", "{selector}", "{value}")'
                    processed_lines.append(evaluate_line)
                    logging.info(f"Replaced {page_obj}.{method_name_page}() with {page_obj}.evaluate() for potential readonly selector: {selector}")
                    modified = True


            # Try to parse as locator.fill(value) or locator.type(value)
            if not modified:
                # This regex tries to capture a locator creation/variable and the subsequent fill/type call
                match_locator_method = re.match(r'^(\s*)(.*?) = (.*?locator\(.*?\).*)\n\s*\2\.(fill|type)\s*\(\s*["\'](.*?)["\']\s*\).*$', line, re.DOTALL)

                if match_locator_method:
                    indent, var_name, locator_creation_part, method_name_locator, value_locator = match_locator_method.groups()
                    # Attempt to extract selector from the locator_creation_part
                    selector_match = re.search(r'locator\s*\(\s*["\'](.*?)["\']\s*\)', locator_creation_part)
                    if selector_match:
                        selector = selector_match.group(1)
                        value = value_locator
                         # Check if this selector matches any of the readonly patterns
                        if any(pattern.search(selector) for pattern in readonly_selector_patterns):
                            # Construct page.evaluate() call (assuming 'page' object is available)
                            evaluate_js = "selector => {{ const element = document.querySelector(selector); if (element) {{ element.value = arguments[1]; element.dispatchEvent(new Event('input', {{ bubbles: true }})); element.dispatchEvent(new Event('change', {{ bubbles: true }})); }} }}"
                            # We need the page object. Assuming the locator was created from a page object,
                            # we can't reliably get the page object variable name here.
                            # Relying on the AI to correctly generate page.evaluate is better.
                            # For post-processing, if we detect this pattern, we could try to infer the page object
                            # or just log a warning and rely on the AI. Let's rely on AI for now.
                            logging.warning(f"Detected locator.{method_name_locator}() for potential readonly selector: {selector}. Relying on AI to replace with page.evaluate.")
                            # We won't modify the line here, let the AI handle it based on the prompt.
                            modified = False # Do not mark as modified by post-processing
                        else:
                             # If it's not a readonly selector, keep the original line
                             modified = False # Do not mark as modified by post-processing


        if not modified:
            processed_lines.append(line)

    return "\n".join(processed_lines)


def fix_empty_blocks_with_pass(code):
    """
    检查并修复空的 try, except, finally 块，插入 pass 语句。
    """
    lines = code.splitlines()
    processed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        processed_lines.append(line)
        stripped_line = line.strip()

        # 检查是否是 try, except, or finally 语句的结尾
        if stripped_line.endswith(':') and (stripped_line.startswith('try:') or stripped_line.startswith('except') or stripped_line.startswith('finally:')):
            # 查看下一行是否是缩进的，如果不是，则表示是空块，插入 pass
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                current_indent = len(line) - len(stripped_line)
                next_indent = len(next_line) - len(next_line.lstrip())

                # 如果下一行缩进小于或等于当前行的缩进，或者下一行是注释或空行，则认为是空块
                if next_indent <= current_indent or next_line.strip().startswith('#') or not next_line.strip():
                     # 检查是否已经有 pass 语句
                     if not next_line.strip() == 'pass':
                         # 查找当前行的实际缩进
                         current_line_indent = line[:len(line) - len(line.lstrip())]
                         # 插入 pass，使用当前行的缩进加上4个空格
                         processed_lines.append(f"{current_line_indent}    pass") # 假设使用4个空格缩进

            else:
                 # If it's the last line ending with try, except, or finally, insert pass
                 current_line_indent = line[:len(line) - len(line.lstrip())]
                 processed_lines.append(f"{current_line_indent}    pass") # Assume 4 spaces indentation

        i += 1
    return "\n".join(processed_lines)


def is_valid_python(code):
    """
    检查给定的字符串是否是有效的Python代码。
    """
    try:
        ast.parse(code) # Use ast.parse for more robust syntax checking
        return True
    except IndentationError as e:
        logging.error(f"代码存在缩进错误: {e}")
        return False
    except SyntaxError as e:
        logging.error(f"代码存在语法错误: {e}")
        return False
    except Exception as e:
        logging.error(f"检查代码有效性时发生未知错误: {e}")
        return False


def post_process_script(code):
    """
    对生成的脚本进行后处理，例如移除无效断言、确保必要导入、修复空块、处理readonly输入框等。
    """
    code = ensure_imports(code) # 确保导入
    # Call replace_readonly_fill_with_evaluate first
    # Relying more on AI to handle readonly, keep this for specific patterns
    # code = replace_readonly_fill_with_evaluate(code) # Let AI handle this first
    # Then add wait_for for other actions (that are not replaced)
    code = add_wait_before_actions(code) # Add wait_for visible
    code = fix_empty_blocks_with_pass(code) # 修复空块
    # Add other post-processing steps here if needed
    # code = fix_unboundlocalerror(code) # Could implement specific fixes for UnboundLocalError
    # code = fix_strict_mode_violation(code) # Could implement specific fixes for strict mode

    return code

def get_failed_tests_from_log(log_file="pytest_errors.log"):
    """
    从pytest错误日志中解析失败的测试文件列表和错误信息。
    返回一个字典 {script_path: error_details}
    """
    failed_tests = {}
    if not os.path.exists(log_file):
        logging.info("未找到 pytest 错误日志文件，跳过自愈。")
        return failed_tests

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

            # Pattern to capture the test file path and the subsequent error traceback
            # This pattern looks for lines starting with "FAILED" or "ERROR collecting"
            # followed by a file path, and then captures everything until the next
            # "==" separator or end of file.
            # Modified to handle various error types and capture more context
            # Fixed redundant escape in regex
            failure_pattern = re.compile(
                r"^(?:FAILED|ERROR collecting)\s+([\w\\/\.-]+\.py)(.*?)(?=^==+ .+ ==+|^$)",
                re.DOTALL | re.MULTILINE
            )

            matches = failure_pattern.finditer(content)

            for match in matches:
                script_path = match.group(1)
                error_details = match.group(2).strip()

                # Filter out .healed scripts
                if script_path.endswith(".healed"):
                    continue

                # Store the first occurrence of failure for a script
                if script_path not in failed_tests:
                    failed_tests[script_path] = error_details
                    logging.info(f"Detected failed script: {script_path}")
                    # logging.debug(f"Error details for {script_path}: {error_details[:500]}...")


    except Exception as e:
        logging.error(f"解析pytest错误日志失败: {e}")
        return {}

    logging.info(f"从日志中解析到以下失败/收集错误脚本: {list(failed_tests.keys())}")
    return failed_tests


def load_testcase_by_script_name(script_name, testcases_file="testcases.json"):
    """
    根据失败的脚本文件名，查找对应的原始测试用例
    脚本文件名格式如 playwright_scripts/test_playwright_1.py 或 playwright_scripts/test_playwright_1.py.healed
    """
    try:
        # From the error log, the script paths are like playwright_scripts/test_playwright_1.py
        # The testcase index is based on the number in the filename.
        base_script_name = os.path.basename(script_name)
        match = re.search(r"test_playwright_(\d+)\.py(?:\.healed)?$", base_script_name)
        if not match:
            logging.warning(f"脚本文件名格式不匹配，无法找到对应用例: {script_name}")
            return None

        testcase_index = int(match.group(1)) - 1 # Index is 0-based

        if not os.path.exists(testcases_file):
            logging.error(f"未找到测试用例文件: {testcases_file}")
            return None

        with open(testcases_file, "r", encoding="utf-8") as f:
            testcases = json.load(f)

        if isinstance(testcases, list) and 0 <= testcase_index < len(testcases):
            return testcases[testcase_index]
        else:
            logging.warning(f"测试用例文件格式错误或索引超出范围: {testcase_index} (总用例数: {len(testcases) if isinstance(testcases, list) else 0})")
            return None

    except Exception as e:
        logging.error(f"根据脚本名查找测试用例失败 {script_name}: {e}")
        return None


def call_deepseek_api(prompt):
    """
    调用 DeepSeek API 获取自愈后的脚本代码。
    """
    if not DEEPSEEK_API_KEY:
        logging.error("DEEPSEEK_API_KEY 环境变量未设置，无法调用API！")
        return None

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a helpful AI assistant that refactors Python code. Focus on fixing syntax and runtime errors, especially Playwright-related issues like timeouts or incorrect element interactions. If an input element is readonly or not editable and the error log indicates a failure with .fill() or .type(), suggest using page.evaluate() to set its value via JavaScript. If a locator matches multiple elements causing strict mode violation, suggest using a more specific locator or methods like .first(), .last(), .nth(index). Pay close attention to the provided error messages and test case steps. Ensure the generated code is a complete and syntactically correct Python script for pytest with Playwright."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        logging.info("Calling DeepSeek API...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=180) # Increased timeout further
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        result = response.json()
        # logging.debug(f"DeepSeek API raw response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        if result and result['choices'] and result['choices'][0]['message']['content']:
            return result['choices'][0]['message']['content']
        else:
            logging.warning("DeepSeek API 返回空内容或格式错误。")
            # Log the full response if it's not as expected for debugging
            # logging.warning(f"DeepSeek API full response: {json.dumps(result, indent=2, ensure_ascii=False)}")
            return None
    except requests.exceptions.Timeout:
        logging.error("调用 DeepSeek API 超时。")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"调用 DeepSeek API 失败: {e}")
        return None
    except Exception as e:
        logging.error(f"处理 API 响应失败: {e}")
        return None


def heal_script(original_script_path, testcase, error_info):
    """
    调用AI自愈失败的脚本
    """
    logging.info(f"正在自愈脚本: {original_script_path}")
    logging.info(f"失败信息 (部分): {error_info[:500]}...")

    # Read original failed script content
    try:
        with open(original_script_path, "r", encoding="utf-8") as f:
            original_code = f.read()
    except Exception as e:
        logging.error(f"读取原始失败脚本失败 {original_script_path}: {e}")
        return ""

    # Build Prompt for AI
    prompt = f"""
我有一个Playwright自动化测试脚本在运行时或收集时失败了。
原始脚本文件路径：{original_script_path}
对应的原始测试用例（JSON格式）：
```json
{json.dumps(testcase, indent=2, ensure_ascii=False)}
```
脚本代码如下：
```python
{original_code}
```
完整的错误信息如下：
请根据提供的测试用例和完整的错误信息，修复这个Python脚本。修复后的代码应该是一个完整的、可运行的pytest Playwright测试脚本。请特别注意修复以下问题：
1. **Python语法错误和缩进错误**：确保代码是有效的Python语法，并且缩进正确。
2. **Playwright运行时错误**：
    - **元素定位问题**：如果错误提示元素找不到（e.g., `element not found`, `Locator expected to be visible/editable`）或者定位器匹配多个元素导致严格模式冲突（`strict mode violation`），请修改定位器，使用更准确的选择器，或者结合 Playwright 提供的链式定位方法（如 `.locator(...).locator(...)`）或序列方法（`.first()`, `.last()`, `.nth(index)`）。
    - **元素交互问题**：如果错误提示元素不可见、不可编辑或被遮挡导致 `.click()`, `.fill()`, `.type()` 等操作超时，请在操作前添加适当的等待，例如 `locator.wait_for(state='visible')` 或 `locator.wait_for(state='editable')`。
    - **只读输入框问题**：**重要！** 根据错误信息，用户名和密码输入框是只读的（`readonly`），直接使用 `.fill()` 或 `.type()` 会失败。请使用 `page.evaluate()` 方法执行 JavaScript 来设置这些只读输入框的值，例如：`page.evaluate("selector => {{ document.querySelector(selector).value = arguments[1]; }}", "#form_item_username", "your_username")`。请确保正确识别并替换针对 `#form_item_username`、`#form_item_password` 以及日志中出现的其他用户名字段定位器（如 `get_by_label("用户名")` 对应的元素）的 `.fill()` 或 `.type()` 调用。
    - **页面跳转问题**：如果测试在点击某个链接或按钮后失败，检查是否正确使用了 `page.wait_for_url()` 或 `page.wait_for_navigation()` 来等待页面加载完成，并且目标 URL 或页面内容断言是正确的。

3.  **导入问题**：确保脚本开头包含了所有必要的 Playwright 和其他模块导入（如 `pytest`, `sync_playwright`, `expect`, `re`）。
4.  **变量作用域问题**：修复因变量未定义或作用域不正确导致的错误（如 `UnboundLocalError`）。

只返回修复后的Python代码，不要包含任何解释或其他文本，将代码放在Markdown代码块中。
"""

    logging.info("正在调用AI进行自愈...")
    healed_code_raw = call_deepseek_api(prompt)

    if not healed_code_raw:
        logging.error("AI自愈返回空内容。")
        return ""

    # 清理AI返回的代码块
    healed_code = clean_code_block(healed_code_raw)

    # Post-process the healed code
    # Note: Post-processing should ideally not alter the AI's key fixes (like evaluate calls)
    # but handle formatting and general issues.
    healed_code = ensure_imports(healed_code) # Ensure imports
    # We might skip add_wait_before_actions and replace_readonly_fill_with_evaluate here
    # and rely on the AI to incorporate waits and evaluate calls based on the detailed prompt.
    # If AI struggles, we can re-enable specific post-processing steps.
    # healed_code = replace_readonly_fill_with_evaluate(healed_code) # Let AI handle this first
    healed_code = add_wait_before_actions(healed_code) # Add wait_for visible (only to non-replaced actions)
    healed_code = fix_empty_blocks_with_pass(healed_code) # Fix empty blocks

    # Final check if the healed code is valid Python
    if not is_valid_python(healed_code):
        logging.error("AI自愈后的代码不是有效的Python代码，放弃保存。")
        # Optionally save invalid code for debugging
        # with open(f"{original_script_path}.invalid", "w", encoding="utf-8") as f:
        #     f.write(healed_code)
        return ""

    # Generate healed filename
    healed_script_path = f"{original_script_path}.healed"

    # Save healed script
    try:
        with open(healed_script_path, "w", encoding="utf-8") as f:
            f.write(healed_code)
        logging.info(f"自愈后的脚本已保存到: {healed_script_path}")
        return healed_script_path
    except Exception as e:
        logging.error(f"保存自愈后脚本失败 {healed_script_path}: {e}")
        return ""

def run_healed_tests(healed_files, allure_dir="allure-results", max_retries=1):
    """
    运行修复后的测试脚本。
    """
    logging.info(f"正在运行自愈后的测试脚本: {healed_files}")

    success = True
    # Run each healed file separately so that failure in one doesn't affect others
    for healed_file in healed_files:
        if not os.path.exists(healed_file):
            logging.warning(f"自愈后的脚本文件不存在，跳过运行: {healed_file}")
            success = False # Consider overall healing run failed
            continue

        logging.info(f"正在运行自愈脚本: {healed_file}")
        # Build pytest command to run only the current healed file
        # --clean-alluredir False to merge reports
        # --verbose to print detailed test results
        command = ["pytest", "--verbose", healed_file, f"--alluredir={allure_dir}"]

        # Add retry logic
        for attempt in range(max_retries + 1):
            logging.info(f"执行命令 (尝试 {attempt + 1}/{max_retries + 1}): {' '.join(command)}")
            try:
                # Run command and capture output
                # text=True, encoding='utf-8' ensures correct decoding
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=False) # check=False doesn't raise exception on non-zero exit code

                logging.info(f"Pytest 执行完成 for {healed_file}.")
                logging.info("--- Pytest 标准输出 ---")
                logging.info(result.stdout)
                logging.info("--- Pytest 标准错误 ---")
                logging.error(result.stderr) # Error output should be logged as error
                logging.info(f"--- Pytest 执行结束 for {healed_file} ---")

                # Write pytest output (stdout and stderr) to pytest_errors.log, overwriting old content
                # This way, the auto-healing script can read the latest failure information next time
                with open("pytest_errors.log", "w", encoding="utf-8") as f:
                     f.write(result.stdout)
                     f.write(result.stderr)

                if result.returncode == 0:
                    logging.info(f"自愈脚本 {healed_file} 执行成功。")
                    # Optionally, remove the .healed file after successful run
                    # os.remove(healed_file) # Optional: clean up successful healed scripts
                    break # Exit retry loop on success
                else:
                    logging.warning(f"自愈脚本 {healed_file} 执行失败，退出码: {result.returncode}.")
                    if attempt < max_retries:
                        logging.info(f"正在重试运行 {healed_file}...")
                        # Optional: wait for some time before retrying
                        # import time
                        # time.sleep(5)
                    else:
                        logging.error(f"自愈脚本 {healed_file} 在 {max_retries + 1} 次尝试后仍然失败。")
                        success = False # Mark overall failure
            except FileNotFoundError:
                logging.error("未找到 pytest 命令。请确保 pytest 已安装。")
                # Write error message to log file
                with open("pytest_errors.log", "w", encoding="utf-8") as f:
                    f.write("未找到 pytest 命令。")
                success = False # Mark overall failure
                break # No point in retrying if command is not found
            except Exception as e:
                logging.error(f"运行自愈脚本 {healed_file} 时发生异常: {e}")
                # Write exception info to log file
                with open("pytest_errors.log", "w", encoding="utf-8") as f:
                    f.write(f"运行自愈脚本时发生异常: {e}")
                success = False # Mark overall failure
                break # Stop retrying on exception

    return success


if __name__ == "__main__":
    # Assume pytest_errors.log contains failure information from the previous test run
    error_log_file = "pytest_errors.log"
    testcases_file = "testcases.json" # Test case file
    script_dir = "playwright_scripts" # Directory where scripts are generated
    max_heal_attempts_per_script = 2 # Max number of healing attempts per failed script

    # Ensure Playwright scripts directory exists
    if not os.path.exists(script_dir):
        os.makedirs(script_dir)

    # Before starting healing, check if pytest_errors.log file exists.
    # If not, it means the test run stage might not have started or produced logs,
    # so healing is not relevant.
    if not os.path.exists(error_log_file):
         logging.info(f"未找到错误日志文件 {error_log_file}，跳过自愈阶段。")
         # If the pipeline is configured to continue even if tests fail, exit successfully here.
         # If the pipeline is configured to abort on test failure, exiting with failure might be appropriate.
         # Based on your Jenkinsfile, test failure leads to stage failure.
         # So, even without logs, it could mean the previous step failed.
         # To be safe, if no logs are found, assume no specific script errors need healing and exit successfully.
         exit(0)


    # Loop for auto-healing attempts
    for heal_attempt in range(max_heal_attempts_per_script):
        logging.info(f"--- 自动自愈尝试 {heal_attempt + 1}/{max_heal_attempts_per_script} ---")

        # Read current list of failed scripts and error information
        failed_tests_info = get_failed_tests_from_log(error_log_file)
        failed_scripts = list(failed_tests_info.keys())

        if not failed_scripts:
            logging.info("没有需要自愈的失败脚本。")
            # If in any healing attempt, no failed scripts are found, it means the issue is resolved
            logging.info("自动自愈成功！所有测试通过或已修复。")
            exit(0) # No failed scripts, exit successfully

        logging.info(f"检测到 {len(failed_scripts)} 个失败脚本，开始自愈...")

        healed_scripts = []
        current_attempt_healing_success = True # Flag for current round's healing success

        for script_path in failed_scripts:
            logging.info(f"尝试自愈脚本: {script_path}")
            error_info = failed_tests_info.get(script_path, "未知错误信息") # Get error info for the script

            # Ensure script path is correct relative to current working directory
            full_script_path = os.path.join(script_dir, os.path.basename(script_path))
            # Before healing, ensure the original file exists, or try to restore from backup (optional)
            if not os.path.exists(full_script_path):
                 # Add logic to try restoring from .failed_backup_X files if needed
                 logging.error(f"原始失败脚本文件不存在，跳过自愈: {full_script_path}")
                 current_attempt_healing_success = False
                 continue


            testcase = load_testcase_by_script_name(full_script_path, testcases_file)

            if testcase:
                healed_script_path = heal_script(full_script_path, testcase, error_info)
                if healed_script_path and os.path.exists(healed_script_path):
                    healed_scripts.append(healed_script_path)
                    # After successful healing, rename the original failed script so get_failed_tests_from_log doesn't detect it next time
                    try:
                         original_backup_path = f"{full_script_path}.failed_backup_{heal_attempt}"
                         os.rename(full_script_path, original_backup_path)
                         logging.info(f"Backed up original failed script to: {original_backup_path}")
                    except Exception as e:
                         logging.warning(f"Failed to backup original failed script {full_script_path}: {e}")

                else:
                    logging.error(f"自愈脚本 {full_script_path} 失败。")
                    current_attempt_healing_success = False
            else:
                logging.error(f"找不到脚本 {full_script_path} 对应的测试用例，跳过自愈。")
                current_attempt_healing_success = False # Failure if test case not found

        if not healed_scripts:
            logging.error(f"自愈尝试 {heal_attempt + 1}：没有脚本成功自愈。")
            # If no scripts were successfully healed in this round, and there are still failed scripts,
            # continue to the next attempt (if allowed)
            if heal_attempt < max_heal_attempts_per_script -1 and failed_scripts:
                 logging.info("Proceeding to the next auto-healing attempt...")
                 continue # Continue outer loop to next attempt
            else:
                 # No successfully healed scripts, and reached max attempts, or no more failed scripts (checked above)
                 logging.error(f"Reached maximum auto-healing attempts ({max_heal_attempts_per_script}). Auto-healing ultimately failed.")
                 exit(1) # Exit with failure

        logging.info(f"自愈尝试 {heal_attempt + 1}：成功自愈以下脚本: {healed_scripts}")

        # Run healed test scripts
        logging.info(f"自愈尝试 {heal_attempt + 1}：运行自愈后的测试...")
        run_success = run_healed_tests(healed_scripts)

        if run_success:
            logging.info(f"自愈尝试 {heal_attempt + 1}：所有自愈后的测试运行成功。")
            logging.info("自动自愈成功！所有测试通过或已修复。")
            exit(0) # Healed tests ran successfully, exit with success
        else:
            logging.warning(f"自愈尝试 {heal_attempt + 1}：运行自愈后的测试失败。")
            # If running healed tests still fails, continue to the next attempt (if allowed)
            if heal_attempt < max_heal_attempts_per_script - 1:
                 logging.info("Proceeding to the next auto-healing attempt...")
                 continue # Continue outer loop to next attempt
            else:
                 logging.error(f"Reached maximum auto-healing attempts ({max_heal_attempts_per_script}), and healed tests still failing. Auto-healing ultimately failed.")
                 exit(1) # Exit with failure

    # If all auto-healing attempts are exhausted and there are still failed scripts, exit with code 1
    # (The loop logic above should handle this, but this is a final safeguard)
    logging.error("Auto-healing process ended unexpectedly. There might be unhandled failed scripts.")
    exit(1)