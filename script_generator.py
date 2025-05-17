"""
自动脚本创建模块
使用deepseek-chat API将测试用例转为Playwright自动化脚本
"""

import json
import os
import re
import requests
import ast # Import ast module for more robust syntax checking
import traceback # Import traceback for detailed error logging

from loguru import logger # Using loguru for better logging

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Configure loguru
logger.add("script_generation.log", rotation="1 MB")

def clean_code_block(text):
    """
    去除AI返回的 markdown 代码块标记，包括```python和```等
    """
    text = text.strip()
    # Remove leading and trailing markdown code block markers
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) > 1:
            # Find the first line that doesn't start with ``` and potential language specifier
            start_index = 0
            for i, line in enumerate(lines):
                if not line.strip().startswith("```"):
                    start_index = i
                    break
            text = "\n".join(lines[start_index:])
    if text.endswith("```"):
         text = text[:-3].strip()

    # Also handle potential triple quotes ``` or ''' if AI uses them
    if text.startswith("'''"):
         text = text[3:].strip()
    if text.endswith("'''"):
         text = text[:-3].strip()
    if text.startswith('"""'):
         text = text[3:].strip()
    if text.endswith('"""'):
         text = text[:-3].strip()


    return text.strip()


def remove_invalid_asserts(code):
    """
    自动去除AI生成脚本中的 assert False 相关无效断言
    """
    # Use word boundaries to avoid removing valid asserts that contain "False"
    return re.sub(r"^\\s*assert\\s+False\\b.*$", "", code, flags=re.MULTILINE)


def fix_empty_blocks(code):
    """
    尝试补全 else/except/finally/if/for/while/with 等后面没有代码的情况
    使用更精确的正则匹配，并在必要时插入 pass
    """
    lines = code.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped_line = line.strip()
        # Match lines ending with a colon, potentially followed by comments or whitespace
        if stripped_line.endswith(':') and not stripped_line.startswith('#'):
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
                next_indent = len(lines[next_non_empty_line_idx]) - len(lines[next_non_empty_line_idx].lstrip())
                if next_indent <= current_indent:
                    # Next line is not more indented, insert pass
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
    import_block_end = 0
    for i, line in enumerate(script_lines):
        stripped_line = line.strip()
        if stripped_line.startswith("import ") or stripped_line.startswith("from "):
            existing_imports.append(stripped_line)
            import_block_end = i + 1
        elif not stripped_line and import_block_end == i:
             # Allow single empty line in import block
             import_block_end = i + 1
        elif stripped_line and not (stripped_line.startswith("#") or stripped_line.startswith('"""') or stripped_line.startswith("'''")):
             # Stop if we hit non-import code or non-import comments/docstrings
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
    initial_comments = []
    code_start_line = 0
    for i, line in enumerate(script_lines):
        stripped_line = line.strip()
        if stripped_line.startswith("#") or stripped_line.startswith('"""') or stripped_line.startswith("'''") or not stripped_line:
             initial_comments.append(line)
             code_start_line = i + 1
        else:
             break

    # Add a blank line after imports if needed
    import_section = "\\n".join(all_imports_unique) + "\\n\\n" if all_imports_unique else ""

    # Get the rest of the code, excluding original imports
    rest_of_code = "\\n".join(script_lines[import_block_end:]) if import_block_end < len(script_lines) else ""


    return "\\n".join(initial_comments) + "\\n" + import_section + rest_of_code.strip()


def validate_and_format_python_code(code):
    """
    尝试使用AST解析来验证Python代码语法，并进行一些格式修正
    """
    try:
        # Attempt to parse the code using AST
        ast.parse(code)
        logger.info("AST parse successful. Code is likely syntactically correct.")
        # Basic formatting: ensure consistent indentation (can be expanded)
        # This is a simple approach; using autopep8/black would be more robust
        formatted_lines = []
        indent_level = 0
        indent_size = 4
        for line in code.splitlines():
            stripped_line = line.strip()
            if not stripped_line:
                formatted_lines.append(line)
                continue

            # Decrease indent for keywords that start a new block or end one
            if stripped_line.startswith(("except ", "finally:", "else:", "elif ", "return ", "break", "continue", "pass")):
                 # Simple heuristic: decrease indent if it seems part of a closing block
                 # This is not perfect and might need refinement
                 current_line_indent = len(line) - len(line.lstrip())
                 if current_line_indent <= indent_level - indent_size:
                      indent_level = max(0, indent_level - indent_size)

            # Add current line with calculated indent
            formatted_lines.append(" " * indent_level + stripped_line)

            # Increase indent for keywords that start a new block
            if stripped_line.endswith(':') and not stripped_line.startswith("#"):
                indent_level += indent_size

        logger.info("Basic formatting applied.")
        return "\\n".join(formatted_lines), True # Return formatted code and success status

    except SyntaxError as e:
        logger.error(f"Syntax Error in generated script: {e}")
        logger.error(f"Problematic code snippet around line {e.lineno}:\\n{e.text.strip()}")
        # Attempt to fix common indentation errors before reporting failure
        # This is a very basic attempt; complex cases require more sophisticated logic
        logger.warning("Attempting to re-indent code based on syntax structure...")
        try:
            re_indented_code = "" # A more advanced re-indentation logic would go here
            # For now, return original code with error flag if AST fails
            logger.warning("Re-indentation logic not fully implemented. Returning original code with error.")
            return code, False # Return original code and failure status
        except Exception as fix_e:
            logger.error(f"Failed to apply automatic re-indentation: {fix_e}")
            return code, False # Return original code and failure status
    except Exception as e:
        logger.error(f"An unexpected error occurred during code validation: {e}")
        logger.error(traceback.format_exc())
        return code, False # Return original code and failure status


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
    脚本整体风格规范。
    """
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
        "所有if/else/try/except/finally/for/while/with结构必须有代码块，如无实际逻辑请用pass。"
        "不要用本地文件路径如login_form.html或file:///path/to/login_form.html，"
        "请统一用实际可访问的URL（如 http://10.0.62.222:30050/ ），"
        "脚本整体风格规范， 특히 들여쓰기를 정확하게 해주세요 (特别是请确保缩进正确)。" # Adding Korean phrase as a magic marker/extra instruction for AI
        f"\\n{test_case}"
    )
    data = {"model": "deepseek-chat", "messages": [{\"role\": \"user\", \"content\": prompt}]}

    try:
        logger.info("Calling DeepSeek API to generate script...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=60) # Add timeout
        response.raise_for_status() # Raise an exception for bad status codes
        result = response.json()
        logger.info(f"AI original response: {result}")

        if "choices" not in result or not result["choices"]:
             logger.error(f"DeepSeek API returned no choices: {result}")
             return None, "API returned no choices"

        code = result["choices"][0]["message"]["content"]
        logger.info("AI original script content received.")

        # Apply cleaning and fixing steps
        cleaned_code = clean_code_block(code)
        logger.info("Cleaned markdown code block.")

        code_with_imports = ensure_playwright_imports(cleaned_code)
        logger.info("Ensured necessary imports.")

        code_fixed_blocks = fix_empty_blocks(code_with_imports)
        logger.info("Fixed empty blocks.")

        # Validate and format the final code
        final_code, is_valid = validate_and_format_python_code(code_fixed_blocks)

        if not is_valid:
            logger.error("Final generated script is syntactically invalid after attempted fixes.")
            return code, "Syntax Error after fixes" # Return original problematic code for saving

        logger.success("Script generated and validated successfully.")
        return final_code, None # Return valid code and no error message

    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling DeepSeek API: {e}")
        return None, f"API Request Error: {e}"
    except Exception as e:
        logger.error(f"An unexpected error occurred during script generation: {e}")
        logger.error(traceback.format_exc())
        return None, f"Unexpected Error: {e}"


if __name__ == "__main__":
    # 清理历史脚本和错误文件
    logger.info("Cleaning up old script and error files...")
    for fname in os.listdir("."):
        if fname.startswith("playwright_test_") and (fname.endswith(".py") or fname.endswith(".error.py")):
            try:
                os.remove(fname)
                logger.info(f"Removed old file: {fname}")
            except OSError as e:
                logger.warning(f"Could not remove file {fname}: {e}")


    if not os.path.exists("testcases.json"):
        logger.error("testcases.json 不存在，流程终止。")
        exit(1)

    with open("testcases.json", "r", encoding="utf-8") as f:
        try:
            testcases = json.load(f)
            logger.info(f"成功加载 testcases.json，共 {len(testcases)} 个测试用例。")
        except json.JSONDecodeError as e:
            logger.error(f"testcases.json 解析失败，请检查文件格式: {e}")
            exit(1)
        except Exception as e:
            logger.error(f"加载 testcases.json 时发生未知错误: {e}")
            exit(1)

    successful_scripts = 0
    for idx, testcase in enumerate(testcases):
        logger.info(f"处理测试用例 '{testcase.get('scene', f'用例 {idx+1}')}' 生成脚本...")
        # Pass the test case dictionary directly, generate_playwright_script will format it
        generated_code, error_message = generate_playwright_script(testcase)

        if generated_code:
            filename = f"playwright_test_{idx+1}.py"
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(generated_code)
                logger.success(f"已成功生成并保存脚本: {filename}")
                successful_scripts += 1
            except IOError as e:
                 logger.error(f"无法写入文件 {filename}: {e}")
                 # Optionally save the code to a different name or log it fully
                 error_filename = f"playwright_test_{idx+1}.write_error.py"
                 with open(error_filename, "w", encoding="utf-8") as f:
                      f.write(generated_code)
                 logger.info(f"Generated code saved to {error_filename} due to write error.")

        else:
            error_filename = f"playwright_test_{idx+1}.error.py"
            logger.error(f"为场景 '{testcase.get('scene', f'用例 {idx+1}')}' 生成脚本失败: {error_message}。")
            logger.info(f"原始AI输出或处理失败的代码已保存到文件: {error_filename}")
            # Save the raw AI response or the state of code when error occurred
            # Depending on where the error occurred, 'generated_code' might be None,
            # so we should save the raw API response if possible or a specific error marker.
            # For now, let's save the potentially problematic code or an error message.
            try:
                with open(error_filename, "w", encoding="utf-8") as f:
                     if generated_code is not None:
                          f.write(generated_code)
                     else:
                          # If generate_playwright_script returned None, save the error message
                          f.write(f"# Script generation failed: {error_message}\\n")
                          # If we had the raw AI response before cleaning, we could save it here too
            except IOError as e:
                 logger.error(f"无法写入错误文件 {error_filename}: {e}")


    logger.info(f"脚本生成完成。共处理 {len(testcases)} 个用例，成功生成 {successful_scripts} 个脚本。")

    if successful_scripts == 0:
        logger.error("未成功生成任何Playwright脚本，停止后续流程。")
        exit(1)
