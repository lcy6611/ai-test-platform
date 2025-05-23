"""
自动化故障检测与自愈模块
根据测试报告或错误日志，触发AI对失败脚本的自愈，并尝试重新运行
"""

import os
import json
import logging
import glob
import subprocess
import re
import requests
import ast

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
        if any(imp in existing and (imp.split(" import ")[-1] in existing or imp.split(" import ")[0].replace("import ", "") in existing) for existing in existing_imports):
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
    """
    lines = code.splitlines()
    processed_lines = []
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        # Regex to match Playwright interaction operations on locators or page objects
        # Need to be more robust to different ways locators are created (e.g., page.locator, page.get_by_text, etc.)
        # And different ways methods are called (e.g., .fill(), .click(), .type())
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
    # Update selectors based on your application's HTML
    readonly_selectors = [
        "#form_item_username",
        "#form_item_password",
        "input[name='username']", # Added based on logs
        "input[name='password']", # Added based on logs
        # Add other selectors if needed, e.g., placeholder text based selectors
        # 'input[placeholder*="用户名"]', # Example with placeholder text
        # 'input[placeholder*="密码"]',    # Example with placeholder text
    ]

    lines = code.splitlines()
    processed_lines = []

    for i, line in enumerate(lines):
        stripped_line = line.strip()
        original_indent = line[:len(line) - len(stripped_line)]
        modified = False

        # Regex to find .fill() or .type() calls on potential locator or page objects
        match_fill_type = re.match(r'^(\s*)(.*?)\.(fill|type)\s*\(\s*["\'](.*?)["\']\s*,(.*?)\)$', line)
        match_locator_fill_type = re.match(r'^(\s*)(.*?)\.locator\s*\(\s*["\'](.*?)["\']\s*\)\s*\.(fill|type)\s*\(\s*["\'](.*?)["\']\s*\).*$', line)


        selector = None
        value = None
        prefix = None # The part before .fill or .type (e.g., 'page' or 'username_input')

        if match_locator_fill_type:
             indent, prefix_before_locator, selector_in_locator, method, value_in_method = match_locator_fill_type.groups()
             full_prefix_match = re.match(r'^(\s*)(.*\.locator\(.*?\))', line)
             if full_prefix_match:
                 prefix = full_prefix_match.group(2) # Capture the full locator part
             else:
                 prefix = prefix_before_locator + ".locator('" + selector_in_locator + "')" # Reconstruct prefix
             selector = selector_in_locator
             value = value_in_method
             method_name = method # fill or type

        elif match_fill_type:
            indent, prefix_part, method, selector_or_value, remaining_args_str = match_fill_type.groups()
            method_name = method # fill or type

            # Need to differentiate between page.fill(selector, value) and locator.fill(value)
            # A simple heuristic: if the part before .fill/.type looks like a locator variable,
            # then selector_or_value is the value, and we need to get the selector from somewhere else (hard).
            # If it looks like 'page', then selector_or_value is the selector.

            # Let's focus on the page.fill(selector, value) pattern first as it's easier to reliably parse
            match_page_fill_type_explicit = re.match(r'^(\s*)(page)\.(fill|type)\s*\(\s*["\'](.*?)["\']\s*,\s*["\'](.*?)["\']\s*\).*$', line)
            if match_page_fill_type_explicit:
                 indent, prefix, method, selector, value = match_page_fill_type_explicit.groups()
                 method_name = method

        if selector and value and prefix and method_name in ['fill', 'type']:
             # Check if the selector matches one of the known readonly selectors
             # Simple contains check for now, can be made more robust
             if any(rs in selector for rs in readonly_selectors):
                # Construct page.evaluate() call
                # Using arguments[1] and arguments[2] to pass selector and value safely
                # The JS code finds the element by selector and sets its value
                evaluate_js = "selector => { const element = document.querySelector(selector); if (element) { element.value = arguments[1]; element.dispatchEvent(new Event('input', { bubbles: true })); element.dispatchEvent(new Event('change', { bubbles: true })); } }" # Add input/change events
                evaluate_line = f'{original_indent}page.evaluate("{evaluate_js}", "{selector}", "{value}")'

                processed_lines.append(evaluate_line)
                logging.info(f"Replaced .{method_name}() with .evaluate() for potential readonly selector: {selector}")
                modified = True


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
                 # 如果是最后一行且是 try, except, finally 结尾，也认为是空块，插入 pass
                 current_line_indent = line[:len(line) - len(line.lstrip())]
                 processed_lines.append(f"{current_line_indent}    pass") # 假设使用4个空格缩进

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
    # add_wait_before_actions should be called after replace_readonly_fill_with_evaluate
    # because evaluate doesn't need wait_for editable state
    code = replace_readonly_fill_with_evaluate(code) # 新增：处理 readonly 输入框
    code = add_wait_before_actions(code) # 添加等待可见 (只对非 readonly fill/type 添加)
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
            # Modified to handle UnboundLocalError traceback as well
            failure_pattern = re.compile(
                r"^(?:FAILED|ERROR collecting)\s+([\w\\/\.-]+\.py)(.*?)(?=^=+ short test summary info =+|^=+ .+ =+|$)",
                re.DOTALL | re.MULTILINE
            )

            matches = failure_pattern.finditer(content)

            for match in matches:
                script_path = match.group(1)
                error_details = match.group(2).strip()

                # Filter out .healed scripts
                if script_path.endswith(".healed"):
                    continue

                # Clean up some traceback lines to reduce noise for the AI
                # error_details = re.sub(r'File ".*?playwright[\\/]_impl[\\/].*?\.py", line \d+.*?\n', '', error_details, flags=re.DOTALL)
                # error_details = re.sub(r'C:\\Program Files\\Python.*?\\site-packages\\.*?\n', '', error_details, flags=re.DOTALL)

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
        # 从文件名中提取索引，例如 playwright_test_1.py -> 1
        # 移除目录部分和 .healed 后缀，只匹配文件名中的数字
        base_script_name = os.path.basename(script_name)
        match = re.search(r"test_playwright_(\d+)\.py(?:\.healed)?$", base_script_name)
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
            {"role": "system", "content": "You are a helpful AI assistant that refactors Python code. Focus on fixing syntax and runtime errors, especially Playwright-related issues like timeouts or incorrect element interactions. If an input element is readonly or not editable and the error log indicates a failure with .fill() or .type(), suggest using page.evaluate() to set its value via JavaScript. If a locator matches multiple elements causing strict mode violation, suggest using a more specific locator or methods like .first(), .last(), .nth(index). Pay close attention to the provided error messages and test case steps."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        logging.info("Calling DeepSeek API...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=120) # Increased timeout
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        result = response.json()
        # logging.debug(f"DeepSeek API raw response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        if result and result['choices'] and result['choices'][0]['message']['content']:
            return result['choices'][0]['message']['content']
        else:
            logging.warning("DeepSeek API 返回空内容或格式错误。")
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

    # 读取原始失败脚本内容
    try:
        with open(original_script_path, "r", encoding="utf-8") as f:
            original_code = f.read()
    except Exception as e:
        logging.error(f"读取原始失败脚本失败 {original_script_path}: {e}")
        return ""

    # 构建给AI的Prompt
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
请根据提供的测试用例和完整的错误信息，修复这个Python脚本。修复后的代码应该是一个完整的、可运行的pytest Playwright测试脚本。特别注意修复：
1. Python语法错误和缩进错误。
2. Playwright相关的运行时错误，例如定位器找不到元素、操作超时、元素不可编辑/不可见等。
3. 如果错误信息显示元素是只读的（readonly）导致无法填写（.fill()或.type()失败），请使用 page.evaluate() 执行 JavaScript 来设置元素的值，而不是 .fill() 或 .type()。
4. 如果定位器匹配到多个元素导致严格模式（strict mode）冲突，请修改定位器使其只匹配一个元素，或者使用 .first(), .last(), .nth(index) 方法。
5. 确保所有必要的 Playwright 导入（如 sync_playwright, expect）都存在。
6. 修复因变量作用域导致的错误（如 UnboundLocalError）。

只返回修复后的Python代码，不要包含任何解释或其他文本，将代码放在Markdown代码块中。
"""

    logging.info("正在调用AI进行自愈...")
    healed_code_raw = call_deepseek_api(prompt)

    if not healed_code_raw:
        logging.error("AI自愈返回空内容。")
        return ""

    # 清理AI返回的代码块
    healed_code = clean_code_block(healed_code_raw)

    # 对自愈后的代码进行后处理
    healed_code = post_process_script(healed_code)

    # 最终检查修复后的代码是否是有效的Python
    if not is_valid_python(healed_code):
        logging.error("AI自愈后的代码不是有效的Python代码，放弃保存。")
        # 可以选择将无效代码保存到一个临时文件以便调试
        # with open(f"{original_script_path}.invalid", "w", encoding="utf-8") as f:
        #     f.write(healed_code)
        return ""

    # 生成修复后的文件名
    healed_script_path = f"{original_script_path}.healed"

    # 保存修复后的脚本
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
    # 针对每个修复的文件单独运行，这样即使部分修复失败也不影响其他修复成功的
    for healed_file in healed_files:
        if not os.path.exists(healed_file):
            logging.warning(f"自愈后的脚本文件不存在，跳过运行: {healed_file}")
            success = False # 认为整体修复运行失败
            continue

        logging.info(f"正在运行自愈脚本: {healed_file}")
        # 构建pytest命令，只运行当前修复的文件
        # --clean-alluredir 不清空，以便合并报告
        # --verbose 打印更详细的测试结果
        command = ["pytest", "--verbose", healed_file, f"--alluredir={allure_dir}"]

        # 添加重试逻辑
        for attempt in range(max_retries + 1):
            logging.info(f"执行命令 (尝试 {attempt + 1}/{max_retries + 1}): {' '.join(command)}")
            try:
                # 运行命令并捕获输出
                # text=True, encoding='utf-8'确保输出正确解码
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=False) # check=False 即使pytest失败也不抛异常

                logging.info(f"Pytest 执行完成 for {healed_file}.")
                logging.info("--- Pytest 标准输出 ---")
                logging.info(result.stdout)
                logging.info("--- Pytest 标准错误 ---")
                logging.error(result.stderr) # 运行失败的错误输出应该用error级别
                logging.info(f"--- Pytest 执行结束 for {healed_file} ---")

                # 将 pytest 的输出（包括标准输出和标准错误）写入 pytest_errors.log，覆盖旧内容
                # 这样下次自愈脚本可以读取最新的失败信息
                with open("pytest_errors.log", "w", encoding="utf-8") as f:
                     f.write(result.stdout)
                     f.write(result.stderr)

                if result.returncode == 0:
                    logging.info(f"自愈脚本 {healed_file} 执行成功。")
                    # 如果成功，可以删除对应的 .healed 文件，或者保留作为成功的标记
                    # os.remove(healed_file) # Optional: clean up successful healed scripts
                    break # 成功则跳出重试循环
                else:
                    logging.warning(f"自愈脚本 {healed_file} 执行失败，退出码: {result.returncode}.")
                    if attempt < max_retries:
                        logging.info(f"正在重试运行 {healed_file}...")
                        # 可选：在重试前等待一段时间
                        # import time
                        # time.sleep(5)
                    else:
                        logging.error(f"自愈脚本 {healed_file} 在 {max_retries + 1} 次尝试后仍然失败。")
                        success = False # 标记整体失败
            except FileNotFoundError:
                logging.error("未找到 pytest 命令。请确保 pytest 已安装。")
                # 将错误信息写入日志文件
                with open("pytest_errors.log", "w", encoding="utf-8") as f:
                    f.write("未找到 pytest 命令。")
                success = False # 标记整体失败
                break # 命令都找不到，重试也没用
            except Exception as e:
                logging.error(f"运行自愈脚本 {healed_file} 时发生异常: {e}")
                # 将异常信息写入日志文件
                with open("pytest_errors.log", "w", encoding="utf-8") as f:
                    f.write(f"运行自愈脚本时发生异常: {e}")
                success = False # 标记整体失败
                break # 发生异常，停止重试

    return success


if __name__ == "__main__":
    # 假设 pytest_errors.log 包含上一步运行测试的失败信息
    error_log_file = "pytest_errors.log"
    testcases_file = "testcases.json" # 测试用例文件
    script_dir = "playwright_scripts" # 生成脚本的目录
    max_heal_attempts_per_script = 2 # 每个失败脚本最多尝试自愈的次数

    # 确保 Playwright 脚本目录存在
    if not os.path.exists(script_dir):
        os.makedirs(script_dir)

    # 在开始自愈前，先检查是否有 pytest_errors.log 文件存在。
    # 如果不存在，说明运行测试阶段可能压根没启动或者没有产生日志，自愈就没有意义。
    if not os.path.exists(error_log_file):
         logging.info(f"未找到错误日志文件 {error_log_file}，跳过自愈阶段。")
         # 如果流水线配置为即使测试失败也继续，这里应该以成功退出
         # 如果流水线配置为测试失败则中断，这里应该以失败退出
         # 根据你的 Jenkinsfile，运行测试失败会直接导致阶段失败，
         # 所以这里即使没有日志，也可能意味着上一步失败了。
         # 稳妥起见，如果没有日志，可以认为没有需要处理的特定脚本错误，正常退出。
         exit(0)


    # 循环尝试自愈和重新运行
    for heal_attempt in range(max_heal_attempts_per_script):
        logging.info(f"--- 自动自愈尝试 {heal_attempt + 1}/{max_heal_attempts_per_script} ---")

        # 读取当前的失败脚本列表和错误信息
        failed_tests_info = get_failed_tests_from_log(error_log_file)
        failed_scripts = list(failed_tests_info.keys())

        if not failed_scripts:
            logging.info("没有需要自愈的失败脚本。")
            # 如果在任何一次自愈尝试中，没有失败脚本需要处理，说明问题已经解决
            logging.info("自动自愈成功！所有测试通过或已修复。")
            exit(0) # 没有失败脚本，以成功退出

        logging.info(f"检测到 {len(failed_scripts)} 个失败脚本，开始自愈...")

        healed_scripts = []
        current_attempt_healing_success = True # 标记当前轮次的自愈是否全部成功

        for script_path in failed_scripts:
            logging.info(f"尝试自愈脚本: {script_path}")
            error_info = failed_tests_info.get(script_path, "未知错误信息") # 获取该脚本的错误信息

            # 确保脚本路径是相对于当前工作目录的正确路径
            full_script_path = os.path.join(script_dir, os.path.basename(script_path))
            if not os.path.exists(full_script_path):
                 logging.error(f"原始失败脚本文件不存在，跳过自愈: {full_script_path}")
                 current_attempt_healing_success = False
                 continue

            testcase = load_testcase_by_script_name(full_script_path, testcases_file)

            if testcase:
                healed_script_path = heal_script(full_script_path, testcase, error_info)
                if healed_script_path and os.path.exists(healed_script_path):
                    healed_scripts.append(healed_script_path)
                    # 成功自愈后，可以将原始失败的脚本重命名或备份，
                    # 并在 run_healed_tests 中只运行 .healed 文件
                    try:
                         original_backup_path = f"{full_script_path}.failed_backup_{heal_attempt}"
                         os.rename(full_script_path, original_backup_path)
                         logging.info(f"备份原始失败脚本到: {original_backup_path}")
                    except Exception as e:
                         logging.warning(f"备份原始失败脚本失败 {full_script_path}: {e}")

                else:
                    logging.error(f"自愈脚本 {full_script_path} 失败。")
                    current_attempt_healing_success = False
            else:
                logging.error(f"找不到脚本 {full_script_path} 对应的测试用例，跳过自愈。")
                current_attempt_healing_success = False # 找不到用例也算自愈失败

        if not healed_scripts:
            logging.error(f"自愈尝试 {heal_attempt + 1}：没有脚本成功自愈。")
            # 如果当前轮次没有脚本成功自愈，并且还有失败脚本，则继续下一轮尝试（如果允许）
            continue

        logging.info(f"自愈尝试 {heal_attempt + 1}：成功自愈以下脚本: {healed_scripts}")

        # 运行修复后的测试脚本
        logging.info(f"自愈尝试 {heal_attempt + 1}：运行自愈后的测试...")
        run_success = run_healed_tests(healed_scripts)

        if run_success:
            logging.info(f"自愈尝试 {heal_attempt + 1}：所有自愈后的测试运行成功。")
            logging.info("自动自愈成功！所有测试通过或已修复。")
            exit(0) # 修复后的测试运行成功，以成功退出
        else:
            logging.warning(f"自愈尝试 {heal_attempt + 1}：运行自愈后的测试失败。")
            # 如果运行修复后的测试仍然失败，继续下一轮尝试（如果允许）
            pass # 继续循环

    # 如果循环结束，仍然有失败脚本
    logging.error(f"在 {max_heal_attempts_per_script} 次自愈尝试后，仍然存在失败脚本。自动自愈最终失败。")
    exit(1) # 超过最大尝试次数，以失败退出