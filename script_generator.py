"""
自动脚本创建模块
使用deepseek-chat API将测试用例转为Playwright自动化脚本
"""

import json
import os
import re
import requests
import ast # Import ast module for robust syntax checking
import traceback # Import traceback for detailed error logging
import sys


from loguru import logger # Using loguru for better logging

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Configure loguru
logger.add("script_generation.log", rotation="1 MB")
# Ensure loguru outputs to stderr for Jenkins console
if sys.stderr and not logger._core.handlers.get(sys.stderr.fileno()):
     logger.add(sys.stderr)


def clean_code_block(text):
    """
    去除AI返回的 markdown 代码块标记，包括```python和```等
    更鲁棒地移除开头和结尾的标记。
    """
    text = text.strip()
    # Use regex to remove markdown code block markers at the beginning and end
    # Match ``` followed by optional language specifier (like python) and newline at the start
    text = re.sub(r'^```[a-zA-Z]*\\s*\\n', '', text, flags=re.DOTALL)
    # Match ``` at the end, preceded by optional newline
    text = re.sub(r'\\n```$', '', text, flags=re.DOTALL)

    # Also handle potential triple quotes if AI uses them outside markdown blocks
    text = re.sub(r"^'''\\s*\\n", '', text, flags=re.DOTALL)
    text = re.sub(r"'''$", '', text, flags=re.DOTALL)
    text = re.sub(r'^"""\\s*\\n', '', text, flags=re.DOTALL)
    text = re.sub(r'"""$', '', text, flags=re.DOTALL)

    return text.strip()


def remove_invalid_asserts(code):
    """
    自动去除AI生成脚本中的 assert False 相关无效断言
    """
    # Use word boundaries to avoid removing valid asserts that contain "False"
    return re.sub(r"^\\s*assert\\s+False\\b.*$", "", code, flags=re.MULTILINE)


def fix_empty_blocks(code):
    """
    尝试补全 if/else/except/finally/def/class/for/while/with 等后面没有代码的情况
    使用更精确的正则匹配，并在必要时插入 pass
    """
    lines = code.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped_line = line.strip()
        # Match lines ending with a colon, potentially followed by comments or whitespace
        # Added more keywords to check: def, class, for, while, with
        if re.match(r'\\s*(if|else|elif|except|finally|def|class|for|while|with)[^:]*:', stripped_line) and not stripped_line.startswith('#'):
            # Check if the next non-empty line is less indented or doesn't exist
            next_non_empty_line_idx = -1
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    next_non_empty_line_idx = j
                    break

            current_indent = len(line) - len(line.lstrip())

            if next_non_empty_line_idx == -1:
                # No more lines, insert pass
                indent = " " * (current_indent + 4) # Add 4 spaces indent
                lines.insert(i + 1, indent + "pass")
                i += 1 # Account for the inserted line
            else:
                next_line = lines[next_non_empty_line_idx]
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent <= current_indent and not next_line.strip().startswith('#'):
                    # Next non-comment line is not more indented, insert pass
                    indent = " " * (current_indent + 4) # Add 4 spaces indent
                    lines.insert(i + 1, indent + "pass")
                    i += 1 # Account for the inserted line
        i += 1
    return "\\n".join(lines)


def ensure_playwright_imports(script: str) -> str:
    """
    确保脚本包含基本的 Playwright 测试所需 import 语句，并放在文件开头。
    智能处理现有导入和初始内容。
    """
    required_imports = [
        "from playwright.sync_api import sync_playwright",
        "import time",
        "import pytest" # Assuming pytest is used for test discovery
    ]

    script_lines = script.splitlines()
    initial_content = []
    existing_imports = []
    code_body_start_index = 0

    # Separate initial comments/docstrings and imports from the main code body
    for i, line in enumerate(script_lines):
        stripped_line = line.strip()
        if not stripped_line:
            # Keep blank lines in initial content/import block context
            if code_body_start_index == i: # Only add to initial content if we haven't reached code body yet
                 initial_content.append(line)
            continue
        if stripped_line.startswith("#") or stripped_line.startswith('"""') or stripped_line.startswith("'''"):
            if code_body_start_index == i: # Only add to initial content if we haven't reached code body yet
                 initial_content.append(line)
            continue
        if stripped_line.startswith("import ") or stripped_line.startswith("from "):
            existing_imports.append(stripped_line)
            continue # Continue to look for more imports
        # Found the first line that is not blank, comment, docstring, or import
        code_body_start_index = i
        break
    else:
        # Entire file is initial content or imports
        code_body_start_index = len(script_lines)


    # Extract the main code body
    code_body_lines = script_lines[code_body_start_index:]
    code_body = "\\n".join(code_body_lines)

    # --- Critical Fix: Clean markdown markers from the extracted code body ---
    cleaned_code_body = clean_code_block(code_body)
    # --- End of Critical Fix ---


    # Combine required imports, existing imports, and cleaned code body
    # Use a set to handle uniqueness and maintain order preference for required imports
    all_imports_unique = []
    seen_imports = set()

    def add_import(imp):
        if imp not in seen_imports:
            all_imports_unique.append(imp)
            seen_imports.add(imp)

    # Add required imports first
    for req_import in required_imports:
         add_import(req_import)

    # Add existing imports that are not already in required_imports
    for ex_import in existing_imports:
         # Simple check for equivalence, might need more sophisticated logic for complex imports
         is_redundant = False
         for req_import in required_imports:
             # Check if existing import is a variation of a required import (e.g., import time vs from time import sleep)
             # This is a simplified check; a full AST analysis would be more accurate.
             if req_import.split(' import ')[0] in ex_import.split(' import ')[0]:
                  is_redundant = True
                  break
         if not is_redundant:
             add_import(ex_import)


    # Reconstruct the script
    initial_section = "\\n".join(initial_content).strip()
    import_section = "\\n".join(all_imports_unique).strip()
    cleaned_code_body = cleaned_code_body.strip()

    # Combine sections, ensuring correct spacing and no excessive blank lines
    parts = []
    if initial_section:
        parts.append(initial_section)
    if import_section:
        parts.append(import_section)
    if cleaned_code_body:
        parts.append(cleaned_code_body)

    # Join parts with at most two newlines between sections
    combined_code = "\\n\\n".join(parts)

    # Clean up any remaining excessive blank lines
    filtered_lines = []
    previous_line_was_blank = False
    for line in combined_code.splitlines():
        is_blank = not line.strip()
        if is_blank and previous_line_was_blank:
             continue # Skip this blank line if the previous added line is also blank
        filtered_lines.append(line)
        previous_line_was_blank = is_blank


    return "\\n".join(filtered_lines)


def validate_python_code(code):
    """
    尝试使用AST解析来验证Python代码语法。
    移除格式化逻辑，仅做校验。
    """
    try:
        ast.parse(code)
        logger.info("AST parse successful. Code is syntactically correct.")
        return True, None # Return success status and no error message
    except SyntaxError as err:
        logger.error(f"Syntax Error in generated script: {err}")
        logger.error(f"Problematic code snippet around line {err.lineno}:\\n{err.text.strip()}")
        return False, f"Syntax Error on line {err.lineno}: {err}"
    except Exception as ex:
        logger.error(f"An unexpected error occurred during code validation: {ex}")
        logger.error(traceback.format_exc())
        return False, f"Unexpected Validation Error: {ex}"


def generate_playwright_script(test_case):
    """
    调用deepseek-chat API，将测试用例转为Playwright+Python自动化脚本。
    要求可直接运行，包含必要的import和断言，
    所有中文注释都用三引号风格，不要用#，
    测试函数不要带任何参数，统一用with sync_playwright() as p:方式启动Playwright。
    不要生成 assert False 这种占位断言，遇到无法实现的断言请用 pass 占位。
    所有if/else/try/except/finally/for/while/with结构必须有代码块，如无实际逻辑请用pass。
    不要用本地文件路径如login_form.html或file:///path/to/login_form.html，
    请统一用实际可访问的URL（如 http://10.0.62.222:30050/ ），
    脚本整体风格规范， 특히 들여쓰기를 정확하게 해주세요 (特别是请确保缩进正确)。
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    # Ensure test_case is a JSON string for the prompt
    test_case_json_str = json.dumps(test_case, ensure_ascii=False, indent=2)

    api_prompt_content = (
        "请将以下测试用例转化为Playwright+Python自动化测试脚本，"
        "要求可直接运行，包含必要的import和断言，"
        "所有中文注释都用三引号风格，不要用#，"
        "测试函数不要带任何参数，统一用with sync_playwright() as p:方式启动Playwright。"
        "不要生成 assert False 这种占位断言，遇到无法实现的断言请用 pass 占位。"
        "所有if/else/try/except/finally/for/while/with结构必须有代码块，如无实际逻辑请用pass。"
        "不要用本地文件路径如login_form.html或file:///path/to/login_form.html，"
        "请统一用实际可访问的URL（如 http://10.0.62.222:30050/ ），"
        "脚本整体风格规范，尤其是代码缩进必须正确。" # Simplified Korean phrase and added explicit Chinese instruction
        f"\\n\\n{test_case_json_str}"
    )
    # Use single quotes for the outer string for data dict for better readability
    data = {'model': 'deepseek-chat', 'messages': [{'role': 'user', 'content': api_prompt_content}]}


    raw_ai_response = None
    intermediate_code = None # Variable to hold code after cleaning/fixing, before validation
    try:
        logger.info("Calling DeepSeek API to generate script...")
        logger.debug(f"Prompt snippet sent to API: {repr(api_prompt_content[:500])}...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=120)
        response.raise_for_status()
        result = response.json()
        raw_ai_response = result

        logger.info(f"AI original response received.")
        if "choices" in result and result["choices"]:
             ai_content = result["choices"][0]["message"]["content"]
             logger.info(f"AI response content snippet: {repr(ai_content[:200])}...")
        else:
             logger.warning(f"AI response has no choices: {repr(result)}")
             return None, "API returned no choices or invalid format", raw_ai_response, None


        code = result["choices"][0]["message"]["content"]
        logger.info("AI original script content extracted.")

        # Apply cleaning and fixing steps in a sequence that makes sense
        # Ensure cleaning markdown happens early, and again after import manipulation if needed
        cleaned_code_initial = clean_code_block(code)
        logger.info("Initial cleaning of markdown code block.")

        # ensure_playwright_imports now handles cleaning its extracted code body part
        code_with_imports = ensure_playwright_imports(cleaned_code_initial)
        logger.info("Ensured necessary imports and handled existing ones.")

        code_fixed_blocks = fix_empty_blocks(code_with_imports)
        logger.info("Fixed empty blocks (pass insertion).")

        # Store the code state after cleaning/fixing, before final validation
        intermediate_code = code_fixed_blocks

        # Validate the final code using AST
        is_valid, validation_error_msg = validate_python_code(intermediate_code) # Validate intermediate_code

        if not is_valid:
            logger.error("Generated script is syntactically invalid after attempted fixes.")
            return None, validation_error_msg, raw_ai_response, intermediate_code

        logger.success("Script generated and validated successfully.")
        return intermediate_code, None, raw_ai_response, None # Return the validated code


    except requests.exceptions.Timeout:
        logger.error("DeepSeek API request timed out.")
        return None, "API Request Timeout", raw_ai_response, intermediate_code
    except requests.exceptions.RequestException as err:
        logger.error(f"Error calling DeepSeek API: {err}")
        return None, f"API Request Error: {err}", raw_ai_response, intermediate_code
    except Exception as ex:
        logger.error(f"An unexpected error occurred during script generation: {ex}")
        logger.error(traceback.format_exc())
        return None, f"Unexpected Error: {ex}", raw_ai_response, intermediate_code


if __name__ == "__main__":
    # 清理历史脚本和错误文件
    logger.info("Cleaning up old script and error files...")
    for fname in os.listdir("."):
        if fname.startswith("playwright_test_") and (fname.endswith(".py") or fname.endswith(".error.py") or fname.endswith(".raw_response.json") or fname.endswith(".raw_response.json.txt")):
            try:
                os.remove(fname)
                logger.info(f"Removed old file: {fname}")
            except OSError as err:
                logger.warning(f"Could not remove file {fname}: {err}")


    if not os.path.exists("testcases.json"):
        logger.error("testcases.json 不存在，流程终止。")
        exit(1)

    with open("testcases.json", "r", encoding="utf-8") as f:
        try:
            testcases = json.load(f)
            logger.info(f"成功加载 testcases.json，共 {len(testcases)} 个测试用例。")
        except json.JSONDecodeError as err:
            logger.error(f"testcases.json 解析失败，请检查文件格式: {err}")
            exit(1)
        except Exception as ex:
            logger.error(f"加载 testcases.json 时发生未知错误: {ex}")
            exit(1)

    successful_scripts = 0
    for idx, testcase in enumerate(testcases):
        scene_name = testcase.get('scene', f'用例 {idx+1}')
        logger.info(f"处理测试用例 '{scene_name}' 生成脚本...")

        generated_code, error_message, raw_ai_response_content, intermediate_code_on_error = generate_playwright_script(testcase)

        # Save raw AI response regardless of success for debugging
        raw_response_filename = f"playwright_test_{idx+1}.raw_response.json"
        if raw_ai_response_content:
            try:
                with open(raw_response_filename, "w", encoding="utf-8") as f:
                     json.dump(raw_ai_response_content, f, ensure_ascii=False, indent=2)
                logger.info(f"原始AI响应已保存到文件: {raw_response_filename}")
            except (IOError, TypeError) as err:
                 logger.error(f"无法写入原始AI响应文件 {raw_response_filename} 或内容非JSON格式: {err}")
                 try:
                      with open(raw_response_filename + ".txt", "w", encoding="utf-8") as f_txt:
                           f_txt.write(str(raw_ai_response_content))
                      logger.info(f"原始AI响应（非JSON）已保存到文件: {raw_response_filename}.txt")
                 except IOError as txt_err:
                      logger.error(f"也无法写入原始AI响应文本文件 {raw_response_filename}.txt: {txt_err}")


        if generated_code is not None:
            # Successfully generated valid code
            filename = f"playwright_test_{idx+1}.py"
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(generated_code)
                logger.success(f"已成功生成并保存脚本: {filename}")
                successful_scripts += 1
            except IOError as err:
                 logger.error(f"无法写入文件 {filename}: {err}")
                 error_filename = f"playwright_test_{idx+1}.write_error.py"
                 with open(error_filename, "w", encoding="utf-8") as f:
                      f.write(generated_code)
                 logger.info(f"Generated code saved to {error_filename} due to write error.")

        else:
            # Script generation or validation failed (generated_code is None)
            error_filename = f"playwright_test_{idx+1}.error.py"
            logger.error(f"为场景 '{scene_name}' 生成脚本失败: {error_message}。")
            logger.info(f"处理失败的代码或原始AI内容已保存到文件: {error_filename}")

            try:
                with open(error_filename, "w", encoding="utf-8") as f:
                     f.write(f"# Script generation failed for scene: {repr(scene_name)}\\n")
                     f.write(f"# Error: {repr(error_message)}\\n\\n")

                     if intermediate_code_on_error:
                          f.write("# Code state before final validation:\\n")
                          f.write(intermediate_code_on_error)
                     elif raw_ai_response_content and 'choices' in raw_ai_response_content and raw_ai_response_content['choices']:
                          f.write("# Raw AI response content:\\n")
                          f.write(raw_ai_response_content['choices'][0]['message']['content'])
                     else:
                          f.write("# No intermediate code or raw AI content available.\\n")


            except IOError as err:
                 logger.error(f"无法写入错误文件 {error_filename}: {err}")


    logger.info(f"脚本生成完成。共处理 {len(testcases)} 个用例，成功生成 {successful_scripts} 个脚本。")

    if successful_scripts == 0:
        logger.error("未成功生成任何Playwright脚本，停止后续流程。")
        exit(1)
    else:
        exit(0)