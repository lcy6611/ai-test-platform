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
import requests # Added imports based on function usage

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 假设失败信息会写入 pytest_errors.log (由 run_tests.py 生成)
# 假设AI生成的修复脚本以 .healed 结尾

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def clean_code_block(text):
    """
    从AI返回的文本中提取JSON或Python代码块，处理可能的Markdown标记。
    这里为了通用性，简单处理Markdown块。
    """
    # Decode bytes if necessary, assuming UTF-8
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='ignore')

    # Remove potential Byte Order Mark (BOM)
    text = text.lstrip('\ufeff')

    # Regex to find potential code blocks, including those with or without language specifiers
    # This is a simplified version focused on extracting content within ``` ```
    match = re.search(r"```(?:[a-zA-Z]+)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # If no markdown block found, return the stripped text
    return text.strip()

def ensure_imports(code):
    """
    确保脚本包含必要的导入，如 Playwright 的 sync_playwright 和 pytest。
    """
    required_imports = [
        "import pytest",
        "from playwright.sync_api import sync_playwright"
    ]
    lines = code.splitlines()
    existing_imports = [line.strip() for line in lines if line.strip().startswith("import") or line.strip().startswith("from")]

    for imp in required_imports:
        if not any(imp in existing for existing in existing_imports):
            # 在现有导入后或文件顶部添加缺失的导入
            insert_index = 0
            for i, line in enumerate(lines):
                if line.strip().startswith("import") or line.strip().startswith("from"):
                    insert_index = i + 1
                elif line.strip() and not (line.strip().startswith("#") or line.strip().startswith('"""') or line.strip().startswith("'''")):
                    # 如果遇到非导入、非注释、非 docstring 的行，则在其之前插入
                    insert_index = i
                    break
            lines.insert(insert_index, imp)
            logging.info(f"Added missing import: {imp}")

    return "\n".join(lines)

def add_wait_before_actions(code):
    """
    在 Playwright 的 fill(), click(), type() 前添加等待元素可编辑/可用状态。
    """
    lines = code.splitlines()
    processed_lines = []
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        # 简单的正则匹配 Playwright 交互操作
        match_fill = re.match(r'^(.*\.)fill\((.*)\)$', stripped_line)
        match_click = re.match(r'^(.*\.)click\((.*)\)$', stripped_line)
        match_type = re.match(r'^(.*\.)type\\((.*)\\)$', stripped_line) # Escape parenthesis for regex

        if match_fill or match_click or match_type:
            # 提取 locator 部分，例如 'page.locator("#username")'
            locator_part = (match_fill or match_click or match_type).group(1)
            # 插入等待可编辑的逻辑，保持原有缩进
            indent = line[:len(line) - len(stripped_line)]
            # 使用 state='visible' 作为通用等待状态，更安全
            wait_line = f"{indent}{locator_part}.wait_for(state='visible', timeout=15000)" # 15秒等待
            processed_lines.append(wait_line)
            processed_lines.append(line) # 添加原始操作行
        else:
            processed_lines.append(line) # 添加非操作行

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
        compile(code, "<string>", "exec")
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
    对生成的脚本进行后处理，例如移除无效断言、确保必要导入、修复空块等。
    """
    # code = clean_code_block(code) # clean_code_block 应该在获取AI响应后立即调用
    # code = remove_invalid_asserts(code) # 如果需要移除特定断言，可以在这里实现
    code = ensure_imports(code) # 确保导入
    code = add_wait_before_actions(code) # 添加等待
    code = fix_empty_blocks_with_pass(code) # 修复空块
    return code

def get_failed_tests_from_log(log_file="pytest_errors.log"):
    """
    从pytest错误日志中解析失败的测试文件列表 (简易解析，可根据实际日志格式调整)
    更健壮的方式是解析Allure报告或JUnit XML报告
    这里也尝试解析收集错误（IndentationError等）。
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
            matches = re.findall(r"FAILED\s+([\w\\/\.-]+\.py)::", content)
            # 过滤掉 .healed 脚本，避免重复自愈
            failed_files.update({f for f in matches if not f.endswith(".healed")})

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
        # 移除目录部分，只匹配文件名
        base_script_name = os.path.basename(script_name)
        match = re.search(r"test_playwright_(\d+)\.py(?:\.healed)?$", base_script_name) # 考虑 .healed 结尾
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
            {"role": "system", "content": "You are a helpful AI assistant that refactors Python code. Focus on fixing syntax and runtime errors."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        result = response.json()
        if result and result['choices'] and result['choices'][0]['message']['content']:
            return result['choices'][0]['message']['content']
        else:
            logging.warning("DeepSeek API 返回空内容或格式错误。")
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
    logging.info(f"失败信息: {error_info[:500]}...") # 打印部分错误信息

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
错误信息如下：
请根据提供的测试用例和错误信息，修复这个Python脚本。修复后的代码应该是一个完整的、可运行的pytest Playwright测试脚本。特别注意修复缩进错误、定位器问题或超时问题。只返回修复后的Python代码，不要包含任何解释或其他文本，将代码放在Markdown代码块中。
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
        command = ["pytest", healed_file, f"--alluredir={allure_dir}"]

        # 添加重试逻辑
        for attempt in range(max_retries + 1):
            logging.info(f"执行命令 (尝试 {attempt + 1}/{max_retries + 1}): {' '.join(command)}")
            try:
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=False)

                logging.info(f"Pytest 执行完成 for {healed_file}.")
                logging.info("--- Pytest 标准输出 ---")
                logging.info(result.stdout)
                logging.info("--- Pytest 标准错误 ---")
                logging.error(result.stderr) # 运行失败的错误输出应该用error级别
                logging.info(f"--- Pytest 执行结束 for {healed_file} ---")

                if result.returncode == 0:
                    logging.info(f"自愈脚本 {healed_file} 执行成功。")
                    break # 成功则跳出重试循环
                else:
                    logging.warning(f"自愈脚本 {healed_file} 执行失败，退出码: {result.returncode}. 标准错误:\n{result.stderr}")
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
                success = False # 标记整体失败
                break # 命令都找不到，重试也没用
            except Exception as e:
                logging.error(f"运行自愈脚本 {healed_file} 时发生异常: {e}")
                success = False # 标记整体失败
                break # 发生异常，停止重试

    return success


if __name__ == "__main__":
    # 假设 pytest_errors.log 包含上一步运行测试的失败信息
    error_log_file = "pytest_errors.log"
    testcases_file = "testcases.json" # 测试用例文件

    failed_scripts = get_failed_tests_from_log(error_log_file)

    if not failed_scripts:
        logging.info("没有需要自愈的失败脚本。")
        exit(0) # 没有失败，退出码为0

    healed_scripts = []
    overall_healing_success = True

    # 读取整个错误日志内容，提供给AI
    error_info_full = ""
    if os.path.exists(error_log_file):
        try:
            with open(error_log_file, "r", encoding="utf-8") as f:
                error_info_full = f.read()
        except Exception as e:
            logging.error(f"读取完整错误日志失败: {e}")
            error_info_full = "无法读取完整的错误日志。"

    for script_path in failed_scripts:
        logging.info(f"尝试自愈脚本: {script_path}")
        # 从完整错误信息中提取当前脚本相关的错误部分，如果可能
        # 这是一个简化的实现，实际可能需要更复杂的日志解析
        script_error_info = f"脚本 {script_path} 的错误信息:\n" + error_info_full # 简单地附上完整日志

        testcase = load_testcase_by_script_name(script_path, testcases_file)

        if testcase:
            healed_script_path = heal_script(script_path, testcase, script_error_info)
            if healed_script_path and os.path.exists(healed_script_path):
                healed_scripts.append(healed_script_path)
            else:
                logging.error(f"自愈脚本 {script_path} 失败。")
                overall_healing_success = False
        else:
            logging.error(f"找不到脚本 {script_path} 对应的测试用例，跳过自愈。")
            overall_healing_success = False # 找不到用例也算自愈失败

    if not healed_scripts:
        logging.error("没有脚本成功自愈。自愈阶段失败。")
        exit(1) # 没有成功自愈的脚本，退出码为1

    logging.info(f"成功自愈以下脚本: {healed_scripts}")

    # 运行修复后的测试脚本
    logging.info("运行自愈后的测试...")
    run_success = run_healed_tests(healed_scripts)

    if run_success:
        logging.info("所有自愈后的测试运行成功。")
        exit(0) # 修复后的测试运行成功，退出码为0
    else:
        logging.error("运行自愈后的测试失败。自愈阶段最终失败。")
        exit(1) # 修复后的测试运行失败，退出码为1