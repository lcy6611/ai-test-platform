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
import sys # Added import sys as it might be needed or referenced


from loguru import logger # Using loguru for better logging

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Configure loguru
# Ensure loguru outputs to stdout/stderr as well for Jenkins console
logger.add("script_generation.log", rotation="1 MB")
# Check if running in an environment like Jenkins where stderr is captured
# If not, loguru might not show logs in the console by default
# A simple check could be if sys.stderr is not None and interactive (though not perfect)
# Or just always add stderr handler to be safe in Jenkins
if not logger._core.handlers.get(os.sys.stderr.fileno()):
     logger.add(os.sys.stderr)


def clean_code_block(text):
    """
    去除AI返回的 markdown 代码块标记，包括```python和```等
    """
    text = text.strip()
    # Remove leading and trailing markdown code block markers
    # Use re.sub for more flexibility in matching start/end markers
    text = re.sub(r'^```.*?\\n', '', text, flags=re.DOTALL) # Remove leading ```...\\n
    text = re.sub(r'\\n```$', '', text, flags=re.DOTALL) # Remove trailing \\n```

    # Also handle potential triple quotes ``` or ''' if AI uses them outside markdown blocks
    text = re.sub(r"^'''\\n", '', text, flags=re.DOTALL)
    text = re.sub(r"'''$", '', text, flags=re.DOTALL)
    text = re.sub(r'^"""\\n', '', text, flags=re.DOTALL)
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
    确保脚本包含基本的 Playwright 测试所需 import 语句，并放在文件开头
    """
    required_imports = [
        "from playwright.sync_api import sync_playwright",
        "import time",
        "import pytest" # Assuming pytest is used for test discovery
    ]

    # Check for existing imports at the beginning of the file
    existing_imports = []
    script_lines = script.splitlines()
    # import_block_end = 0 # This variable is not strictly needed for the logic below
    # code_start_line_after_imports = 0 # This variable is not strictly needed for the logic below
    first_code_line_index = -1
    for i, line in enumerate(script_lines):
        stripped_line = line.strip()
        # Also handle potential docstrings or initial comments before imports
        if not stripped_line or stripped_line.startswith("#") or stripped_line.startswith('"""') or stripped_line.startswith("'''"):
             # This is a comment, docstring or empty line before imports, skip for import check
             # import_block_end = i + 1 # Update might not be necessary
             continue

        if stripped_line.startswith("import ") or stripped_line.startswith("from "):
            existing_imports.append(stripped_line)
            # import_block_end = i + 1 # Update might not be necessary
        else:
             # Stop if we hit non-import code
             first_code_line_index = i
             break

    # Add missing required imports
    new_imports = []
    for req_import in required_imports:
        if req_import not in existing_imports:
            # Check if a similar import already exists (e.g., 'from playwright.sync_api import *')
            found_similar = False
            for ex_import in existing_imports:
                if req_import.split(' import ')[0] in ex_import:
                     found_similar = True
                     break
            if not found_similar:
                 new_imports.append(req_import)

    # Combine new and existing imports, keep unique ones and order required ones first
    all_imports = required_imports + [imp for imp in existing_imports if imp not in required_imports]
    all_imports_unique = []
    seen = set()
    for imp in all_imports:
        if imp not in seen:
            all_imports_unique.append(imp)
            seen.add(imp)

    # Reconstruct the script with consolidated imports
    # Keep initial comments/docstrings if they exist before imports
    initial_content = []
    first_actual_code_line_index = -1 # Find the index of the first line that is not comment, docstring or import
    for i, line in enumerate(script_lines):
         stripped_line = line.strip()
         if stripped_line.startswith("import ") or stripped_line.startswith("from "):
              continue # Skip existing imports
         if not stripped_line or stripped_line.startswith("#") or stripped_line.startswith('"""') or stripped_line.startswith("'''"):
              initial_content.append(line)
         else:
              first_actual_code_line_index = i
              break

    # Add a blank line after initial content if needed
    initial_section = "\\n".join(initial_content) + ("\\n" if initial_content and all_imports_unique else "") # Add blank line only if initial content exists and there are imports

    # Add imports, ensuring a blank line separates them from the code body
    import_section = "\\n".join(all_imports_unique) + ("\\n\\n" if all_imports_unique else "")

    # Get the rest of the code, excluding original imports and initial content
    rest_of_code_lines = []
    # Start from the first line of actual code identified earlier
    if first_actual_code_line_index != -1:
         rest_of_code_lines = script_lines[first_actual_code_line_index:]
    rest_of_code = "\\n".join(rest_of_code_lines)

    # Combine parts and clean up extra blank lines
    combined_code = (initial_section.strip() + "\\n\\n" + import_section.strip() + "\\n\\n" + rest_of_code.strip()).strip()

    # Remove excessive blank lines (more than one consecutive)
    filtered_lines = []
    previous_line_was_blank = False
    for line in combined_code.splitlines():
        is_blank = not line.strip()
        if is_blank and previous_line_was_blank:
             continue # Skip this blank line
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
    except SyntaxError as err: # Changed variable name
        logger.error(f"Syntax Error in generated script: {err}")
        logger.error(f"Problematic code snippet around line {err.lineno}:\\n{err.text.strip()}")
        # Corrected: Return False and the specific syntax error message
        return False, f"Syntax Error on line {err.lineno}: {err}"
    except Exception as ex: # Changed variable name
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

    # Changed prompt variable name to avoid unused warning if it's the last thing
    api_prompt_content = (
        "请将以下测试用例转化为Playwright+Python自动化测试脚本，"
        "要求可直接运行，包含必要的import和断言，"
        "所有中文注释都用三引号风格，不要用#，"
        "测试函数不要带任何参数，统一用with sync_playwright() as p:方式启动Playwright。"
        "不要生成 assert False 这种占位断言，遇到无法实现的断言请用 pass 占位。"
        "所有if/else/try/except/finally/for/while/with结构必须有代码块，如无实际逻辑请用pass。"
        "不要用本地文件路径如login_form.html或file:///path/to/login_form.html，"
        "请统一用实际可访问的URL（如 http://10.0.62.222:30050/ ），"
        "脚本整体风格规范， 특히 들여쓰기를 정확하게 해주세요 (特别是请确保缩进正确)。"
        f"\\n\\n{test_case_json_str}" # Add test case JSON string to prompt
    )
    # Corrected syntax: Use single quotes for the outer string or escape inner double quotes
    # Using single quotes is cleaner
    data = {'model': 'deepseek-chat', 'messages': [{'role': 'user', 'content': api_prompt_content}]}


    raw_ai_response = None
    intermediate_code = None # Variable to hold code after cleaning/fixing, before validation
    try:
        logger.info("Calling DeepSeek API to generate script...")
        # Log prompt snippet for debugging
        logger.debug(f"Prompt snippet sent to API: {repr(api_prompt_content[:500])}...") # Use repr()
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=120) # Increased timeout
        response.raise_for_status() # Raise an exception for bad status codes
        result = response.json()
        raw_ai_response = result # Store raw response

        logger.info(f"AI original response received.")
        # Log a snippet of the response content to check for unexpected format
        if "choices" in result and result["choices"]:
             ai_content = result["choices"][0]["message"]["content"]
             # Use repr() to safely log the snippet string
             logger.info(f"AI response content snippet: {repr(ai_content[:200])}...")
        else:
             logger.warning(f"AI response has no choices: {repr(result)}") # Use repr() for result
             # Return None for valid code, error message, raw response, and intermediate code
             return None, "API returned no choices or invalid format", raw_ai_response, None


        code = result["choices"][0]["message"]["content"]
        logger.info("AI original script content extracted.")

        # Apply cleaning and fixing steps
        cleaned_code = clean_code_block(code)
        logger.info("Cleaned markdown code block.")

        code_fixed_blocks = fix_empty_blocks(cleaned_code)
        logger.info("Fixed empty blocks (pass insertion).")

        code_with_imports = ensure_playwright_imports(code_fixed_blocks)
        logger.info("Ensured necessary imports.")

        # Store the code state after cleaning/fixing, before final validation
        intermediate_code = code_with_imports

        # Validate the final code using AST
        is_valid, validation_error_msg = validate_python_code(code_with_imports)

        if not is_valid:
            logger.error("Generated script is syntactically invalid after attempted fixes.")
            # Return None for valid code, the error message, raw response, and intermediate code
            return None, validation_error_msg, raw_ai_response, intermediate_code

        logger.success("Script generated and validated successfully.")
        # Return valid code, no error message, raw response, and None for intermediate code
        return code_with_imports, None, raw_ai_response, None

    except requests.exceptions.Timeout:
        logger.error("DeepSeek API request timed out.")
        return None, "API Request Timeout", raw_ai_response, intermediate_code
    except requests.exceptions.RequestException as err: # Changed variable name
        logger.error(f"Error calling DeepSeek API: {err}")
        return None, f"API Request Error: {err}", raw_ai_response, intermediate_code
    except Exception as ex: # Changed variable name
        logger.error(f"An unexpected error occurred during script generation: {ex}")
        logger.error(traceback.format_exc())
        return None, f"Unexpected Error: {ex}", raw_ai_response, intermediate_code


if __name__ == "__main__":
    # 清理历史脚本和错误文件
    logger.info("Cleaning up old script and error files...")
    for fname in os.listdir("."):
        # Added .raw_response.json.txt to cleanup list
        if fname.startswith("playwright_test_") and (fname.endswith(".py") or fname.endswith(".error.py") or fname.endswith(".raw_response.json") or fname.endswith(".raw_response.json.txt")):
            try:
                os.remove(fname)
                logger.info(f"Removed old file: {fname}")
            except OSError as err: # Changed variable name
                logger.warning(f"Could not remove file {fname}: {err}")


    if not os.path.exists("testcases.json"):
        logger.error("testcases.json 不存在，流程终止。")
        exit(1)

    with open("testcases.json", "r", encoding="utf-8") as f:
        try:
            testcases = json.load(f)
            logger.info(f"成功加载 testcases.json，共 {len(testcases)} 个测试用例。")
        except json.JSONDecodeError as err: # Changed variable name
            logger.error(f"testcases.json 解析失败，请检查文件格式: {err}")
            exit(1)
        except Exception as ex: # Changed variable name
            logger.error(f"加载 testcases.json 时发生未知错误: {ex}")
            exit(1)

    successful_scripts = 0
    for idx, testcase in enumerate(testcases):
        scene_name = testcase.get('scene', f'用例 {idx+1}')
        logger.info(f"处理测试用例 '{scene_name}' 生成脚本...")

        # Now receiving intermediate_code_on_error as the fourth return value
        generated_code, error_message, raw_ai_response_content, intermediate_code_on_error = generate_playwright_script(testcase)

        # Save raw AI response regardless of success for debugging
        raw_response_filename = f"playwright_test_{idx+1}.raw_response.json"
        if raw_ai_response_content:
            try:
                # raw_ai_response_content is the dict from response.json()
                with open(raw_response_filename, "w", encoding="utf-8") as f:
                     json.dump(raw_ai_response_content, f, ensure_ascii=False, indent=2)
                logger.info(f"原始AI响应已保存到文件: {raw_response_filename}")
            except (IOError, TypeError) as err: # Changed variable name
                 logger.error(f"无法写入原始AI响应文件 {raw_response_filename} 或内容非JSON格式: {err}")
                 # If saving as JSON fails, try saving as plain text representation
                 try:
                      with open(raw_response_filename + ".txt", "w", encoding="utf-8") as f_txt:
                           # Attempt to represent the content as string
                           f_txt.write(str(raw_ai_response_content))
                      logger.info(f"原始AI响应（非JSON）已保存到文件: {raw_response_filename}.txt")
                 except IOError as txt_err: # Changed variable name
                      logger.error(f"也无法写入原始AI响应文本文件 {raw_response_filename}.txt: {txt_err}")


        # Corrected logic: Check if generated_code is not None (indicating success)
        if generated_code is not None:
            # Successfully generated valid code
            filename = f"playwright_test_{idx+1}.py"
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(generated_code)
                logger.success(f"已成功生成并保存脚本: {filename}")
                successful_scripts += 1
            except IOError as err: # Changed variable name
                 logger.error(f"无法写入文件 {filename}: {err}")
                 # Optionally save the code to a different name or log it fully
                 error_filename = f"playwright_test_{idx+1}.write_error.py"
                 with open(error_filename, "w", encoding="utf-8") as f:
                      f.write(generated_code)
                 logger.info(f"Generated code saved to {error_filename} due to write error.")

        else:
            # Script generation or validation failed (generated_code is None)
            error_filename = f"playwright_test_{idx+1}.error.py"
            logger.error(f"为场景 '{scene_name}' 生成脚本失败: {error_message}。")
            # Corrected: Safely write scene_name and error_message using repr()
            logger.info(f"处理失败的代码或原始AI内容已保存到文件: {error_filename}")

            try:
                with open(error_filename, "w", encoding="utf-8") as f:
                     # Safely write scene_name and error_message
                     f.write(f"# Script generation failed for scene: {repr(scene_name)}\\n") # Use repr()
                     f.write(f"# Error: {repr(error_message)}\\n\\n") # Use repr()

                     # Prioritize saving the intermediate code state if validation failed
                     if intermediate_code_on_error:
                          f.write("# Code state before final validation:\\n")
                          f.write(intermediate_code_on_error)
                     elif raw_ai_response_content and 'choices' in raw_ai_response_content and raw_ai_response_content['choices']:
                          # If no intermediate code, save the raw AI content from the raw response dict
                          f.write("# Raw AI response content:\\n")
                          f.write(raw_ai_response_content['choices'][0]['message']['content'])
                     else:
                          f.write("# No intermediate code or raw AI content available.\\n")


            except IOError as err: # Changed variable name
                 logger.error(f"无法写入错误文件 {error_filename}: {err}")


    logger.info(f"脚本生成完成。共处理 {len(testcases)} 个用例，成功生成 {successful_scripts} 个脚本。")

    if successful_scripts == 0:
        logger.error("未成功生成任何Playwright脚本，停止后续流程。")
        # Exit with a non-zero status to indicate failure in Jenkins
        exit(1)
    else:
        # Exit with status 0 if at least one script was successfully generated
        exit(0)