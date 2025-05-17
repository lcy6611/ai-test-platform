"""
自动脚本创建模块
使用deepseek-chat API将测试用例转为Playwright自动化脚本
"""

import json
import os
import re
import requests
import ast # Import ast module for more robust syntax checking
import traceback # Import Import traceback for detailed error logging
import sys # Import sys module

from loguru import logger # Using loguru for better logging

# Ensure output is UTF-8
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Configure loguru
logger.add("script_generation.log", rotation="1 MB", encoding="utf-8") # Ensure log file is also UTF-8

def clean_code_block(text):
    """
    去除AI返回的 markdown 代码块标记，包括```python和```等，
    并清理潜在的非打印字符和BOM头。
    """
    # Decode bytes if necessary, assuming UTF-8
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='ignore')

    # Remove potential Byte Order Mark (BOM)
    text = text.lstrip('\ufeff')

    # Remove leading and trailing markdown code block markers
    text = text.strip()
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

    # Remove common non-printable characters except for basic whitespace
    # This regex keeps printable ASCII characters, and common whitespace (\t, \n, \r, \f, \v)
    # It also allows some common non-ASCII characters that might be in comments/docstrings (e.g., Chinese characters)
    # A more aggressive removal might be needed if errors persist, potentially restricting to ASCII only
    # Let's refine this to be more aggressive if the issue persists
    # For now, keep a balance to allow comments, but be strict on control characters
    # Allow common printable ASCII, basic whitespace, and a reduced range for common multi-byte chars
    text = re.sub(r'[^\x09\x0A\x0D\x20-\x7E\u4E00-\u9FFF]+', '', text)


    return text.strip()


def remove_invalid_asserts(code):
    """
    自动去除AI生成脚本中的 assert False 相关无效断言
    """
    # Use word boundaries to avoid removing valid asserts that contain "False"
    return re.sub(r"^\s*assert\s+False\b.*$", "", code, flags=re.MULTILINE)


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
                    # Next non-empty line is less indented or same indent, insert pass
                    indent = " " * (current_indent + 4) # Add 4 spaces indent
                    lines.insert(i + 1, indent + "pass")
                    i += 1 # Account for the inserted line
        i += 1
    return "\n".join(lines)

def ensure_imports_and_structure(code):
    """
    确保必要的import语句存在，并且Playwright结构正确 (with sync_playwright() as p:)
    强制将必要的导入语句放在脚本的最顶部。
    """
    # Define required imports as a set for quick lookup
    required_imports = {
        "from playwright.sync_api import sync_playwright",
        "import pytest",
        "import time", # Often useful for waits
        "from playwright.sync_api import expect" # Ensure expect is imported
    }

    existing_imports = set()
    other_lines = []

    # Separate existing imports from other code
    lines = code.splitlines()
    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith("import ") or stripped_line.startswith("from "):
            existing_imports.add(stripped_line)
        else:
            other_lines.append(line)

    # Construct the new code with required imports at the very top
    new_lines = []
    for imp in sorted(list(required_imports)): # Add required imports first (sorted for consistency)
         if imp not in existing_imports:
             new_lines.append(imp)

    # Add any other existing imports that are not in the required set
    # This handles cases where AI might import other useful modules
    for imp in sorted(list(existing_imports - required_imports)):
         new_lines.append(imp)

    # Add a newline after imports for separation, if there are imports and other code
    if (required_imports or existing_imports) and other_lines:
        new_lines.append("") # Add a blank line

    # Add the rest of the code
    new_lines.extend(other_lines)

    code = "\n".join(new_lines)


    # Ensure pytest function naming convention
    # Find function definitions and rename if necessary to start with test_
    def_pattern = re.compile(r"^\s*def\s+(\w+)\s*\(")
    lines = code.splitlines()
    processed_lines = []
    for line in lines:
        match = def_pattern.match(line)
        if match:
            func_name = match.group(1)
            # Don't rename dunder methods or main execution block
            if not func_name.startswith("__") and not func_name == "main" and not func_name.startswith("test_"):
                # Preserve leading whitespace
                # Find the exact start of the function name to replace
                name_start_index = line.find(func_name)
                if name_start_index != -1:
                     new_line = line[:name_start_index] + f"test_{func_name}" + line[name_start_index + len(func_name):]
                     processed_lines.append(new_line)
                     logger.info(f"Renamed function '{func_name}' to 'test_{func_name}' to follow pytest convention.")
                     continue
        processed_lines.append(line)

    code = "\n".join(processed_lines)


    # Basic check for playwright structure (can be enhanced)
    if "with sync_playwright() as p:" not in code:
        # This is a critical structural element for basic Playwright usage.
        # If missing, the generated script is unlikely to work.
        logger.error("Playwright structure 'with sync_playwright() as p:' not found. The script is likely invalid.")
        # We might consider trying to wrap the code, but it's risky. For now,
        # we'll rely on the AST validation and error reporting if this is missing.
        pass # Continue to AST validation


    return code


def validate_python_code(code):
    """
    使用AST解析来校验Python代码语法，并进行基本的格式化（移除多余空行）。
    """
    original_code = code # Keep original code for error reporting
    try:
        # Attempt to parse the code using AST
        ast.parse(code)
        logger.info("Syntax check passed using AST.")

        # Simple formatting: remove consecutive empty lines
        lines = code.splitlines()
        formatted_lines = []
        previous_line_was_empty = False
        for line in lines:
            if line.strip() == "":
                if not previous_line_was_empty:
                    formatted_lines.append(line)
                    previous_line_was_empty = True
            else:
                formatted_lines.append(line)
                previous_line_was_empty = False

        code = "\n".join(formatted_lines)
        return True, code, None # Return True for valid code and the formatted code

    except SyntaxError as e:
        error_message = f"Syntax Error in generated script: {e}"
        logger.error(error_message)

        # Find the line number where the error occurred
        line_number = e.lineno if hasattr(e, 'lineno') else 'unknown'
        offset = e.offset if hasattr(e, 'offset') else 'unknown'
        logger.error(f"Error occurred at line {line_number}, offset {offset}")

        # Extract problematic lines around the error
        problematic_snippet = "Problematic code snippet around line {}:\n".format(line_number)
        lines = original_code.splitlines()
        start_line = max(0, line_number - 5) # Get 5 lines before
        end_line = min(len(lines), line_number + 5) # Get 5 lines after
        for i in range(start_line, end_line):
            problematic_snippet += f"{lines[i]}\n"
        logger.error(problematic_snippet)

        return False, original_code, error_message # Return False for invalid code and the original code, plus error message
    except Exception as e:
        error_message = f"An unexpected error occurred during syntax validation: {e}"
        logger.error(error_message)
        logger.error(traceback.format_exc()) # Log the full traceback
        return False, original_code, error_message


def generate_playwright_script(test_case, page_snapshot_content):
    """
    根据测试用例和页面快照内容，调用AI生成Playwright脚本。
    返回生成的代码、错误信息以及原始prompt和AI响应数据。
    """
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set.")
        return None, "DEEPSEEK_API_KEY not set.", None, None

    api_prompt_content = f"""
请将以下测试用例和页面快照转换为Playwright+Python自动化测试脚本。
脚本应遵循pytest框架，每个测试用例生成一个独立的测试函数，函数名以 `test_` 开头。
确保必要的import语句（包括 sync_playwright, pytest, expect）和Playwright结构 (`with sync_playwright() as p:`) 完整且正确。
不要在代码中包含 markdown 代码块标记（如 ```python 和 ```）。
将测试步骤作为注释添加到脚本中。
不要使用 `assert False` 这样的占位断言，如果某个步骤暂时无法实现，请使用 `pass` 占位。
确保 if/else/try/except/finally/for/while/with 结构有代码块，没有代码时使用 `pass` 填充。
对于URL，请使用实际的可访问URL，例如 `http://10.0.62.222:30050/`，不要使用本地文件路径 `file:///path/to/login_form.html`。
确保生成的脚本语法规范，可以直接运行。

测试用例:
{json.dumps(test_case, indent=2, ensure_ascii=False)}

页面快照内容 (用于理解页面结构，请勿直接将快照内容写入脚本):
{page_snapshot_content}
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    # Construct the data payload with correct JSON structure
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": api_prompt_content}
        ]
    }

    logger.info("Calling DeepSeek API to generate script...")
    logger.debug(f"Prompt snippet sent to API: '{api_prompt_content[:200]}...'") # Log snippet of prompt

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status() # Raise an exception for bad status codes
        response_data = response.json()

        logger.info("AI original response received.")
        # Log snippet of AI response
        ai_response_content = None
        if response_data and 'choices' in response_data and response_data['choices']:
             ai_response_content = response_data['choices'][0]['message']['content']
             logger.info(f"AI response content snippet: '{ai_response_content[:200]}...'")
        else:
            logger.warning("AI response format unexpected or empty.")
            # Return error message, None for code and raw data
            return None, "AI response format unexpected or empty.", api_prompt_content, response_data


        # Extract and clean the code block
        # Pass the raw content to clean_code_block
        raw_script_content = ai_response_content
        logger.info("AI original script content extracted.")

        cleaned_script_content = clean_code_block(raw_script_content)
        logger.info("Initial cleaning of markdown code block and special characters.")


        # Apply syntax fixes and formatting
        script_with_fixed_blocks = fix_empty_blocks(cleaned_script_content)
        logger.info("Fixed empty blocks (pass insertion).")

        # Ensure imports are correctly placed at the top
        script_with_imports = ensure_imports_and_structure(script_with_fixed_blocks)
        logger.info("Ensured necessary imports and handled existing ones.")

        final_script_content = remove_invalid_asserts(script_with_imports)
        logger.info("Removed invalid asserts.")

        # Validate the final code
        is_valid, validated_code, error_message = validate_python_code(final_script_content)

        if is_valid:
            logger.info("Generated script is syntactically valid.")
            # Return valid code, None for error, and raw data
            return validated_code, None, api_prompt_content, response_data
        else:
            logger.error(f"Generated script is syntactically invalid after attempted fixes: {error_message}")
            # Return None for code, the error message, and raw data
            return None, error_message, api_prompt_content, response_data


    except requests.exceptions.RequestException as e:
        error_message = f"Error calling DeepSeek API: {e}"
        logger.error(error_message)
        logger.error(traceback.format_exc()) # Log the full traceback
        # Return None for code, error message, and None for raw data
        return None, error_message, api_prompt_content, None
    except Exception as e:
        error_message = f"An unexpected error occurred during script generation: {e}"
        logger.error(error_message)
        logger.error(traceback.format_exc()) # Log the full traceback
        # Return None for code, error message, and None for raw data
        return None, error_message, api_prompt_content, None

# --- Main Execution ---
if __name__ == "__main__":
    testcases_file = "testcases.json"
    snapshot_file = "page_snapshot.json" # Assuming snapshot is saved here
    output_dir = "playwright_scripts"

    # Clean up old files in the output directory
    if os.path.exists(output_dir):
        logger.info(f"Cleaning up old script and error files in {output_dir}...")
        for filename in os.listdir(output_dir):
            # Clean up .py, .error.py, and .raw_response.json files
            if filename.endswith(".py") or filename.endswith(".error.py") or filename.endswith(".raw_response.json"):
                try:
                    os.remove(os.path.join(output_dir, filename))
                    logger.debug(f"Removed old file: {filename}")
                except OSError as e:
                    logger.warning(f"Error removing old file {filename}: {e}")
    else:
        os.makedirs(output_dir, exist_ok=True)


    if not os.path.exists(testcases_file):
        logger.error(f"Error: {testcases_file} not found. Please run testcase_generator_by_snapshot.py first.")
        sys.exit(1) # Exit with a non-zero status code to indicate failure

    page_snapshot_content = "No snapshot available."
    if not os.path.exists(snapshot_file):
         logger.warning(f"Warning: {snapshot_file} not found. Script generation may be less accurate.")
    else:
        try:
            with open(snapshot_file, 'r', encoding='utf-8') as f:
                page_snapshot_content = f.read()
        except Exception as e:
            logger.error(f"Error reading snapshot file {snapshot_file}: {e}")
            page_snapshot_content = "Error reading snapshot file."


    try:
        with open(testcases_file, 'r', encoding='utf-8') as f:
            test_cases = json.load(f)
        logger.info(f"成功加载 {testcases_file}，共 {len(test_cases)} 个测试用例。")
    except FileNotFoundError:
        logger.error(f"错误：找不到文件 {testcases_file}")
        sys.exit(1) # Exit with a non-zero status code to indicate failure
    except json.JSONDecodeError as e:
        logger.error(f"错误解析 {testcases_file}: {e}")
        sys.exit(1) # Exit with a non-zero status code to indicate failure
    except Exception as e:
        logger.error(f"读取或解析文件 {testcases_file} 时发生意外错误: {e}")
        sys.exit(1) # Exit with a non-zero status code to indicate failure

    successful_scripts = 0
    for i, test_case in enumerate(test_cases):
        script_filename = os.path.join(output_dir, f"test_playwright_{i+1}.py")
        error_filename = os.path.join(output_dir, f"test_playwright_{i+1}.error.py")
        raw_response_filename = os.path.join(output_dir, f"test_playwright_{i+1}.raw_response.json")


        logger.info(f"为用例 '{test_case.get('scene', f'用例 {i+1}')}' 生成脚本...")

        # Call API to generate script and get all relevant data
        generated_code, error_message, api_prompt, raw_api_response_data = generate_playwright_script(test_case, page_snapshot_content)

        # Save raw AI response and prompt for debugging
        try:
             raw_data_to_save = {
                 "prompt": api_prompt,
                 "raw_api_response": raw_api_response_data,
                 "generated_code_before_validation": generated_code if error_message else None, # Save if there was an error during validation
                 "final_validated_code": generated_code if not error_message else None,
                 "error_message": error_message
             }
             with open(raw_response_filename, 'w', encoding='utf-8') as f:
                 json.dump(raw_data_to_save, f, indent=2, ensure_ascii=False)
             logger.info(f"原始AI响应信息、prompt和结果已保存到文件: {raw_response_filename}")
        except Exception as e:
             logger.warning(f"无法保存原始AI响应到文件 {raw_response_filename}: {e}")


        if generated_code and not error_message: # Only save if generation and validation were successful
            try:
                with open(script_filename, 'w', encoding='utf-8') as f:
                    f.write(generated_code)
                logger.info(f"成功为用例 '{test_case.get('scene', f'用例 {i+1}')}' 生成脚本: {script_filename}")
                successful_scripts += 1
                # If script generated successfully, ensure no old error file exists for this test
                if os.path.exists(error_filename):
                     try:
                          os.remove(error_filename)
                          logger.debug(f"Removed old error file for successful script: {error_filename}")
                     except OSError as e:
                          logger.warning(f"Error removing old error file {error_filename}: {e}")

            except Exception as e:
                logger.error(f"无法写入脚本文件 {script_filename}: {e}")
                # Save the generated_code (even if writing failed) to the error file for inspection
                error_message_file = f"无法写入脚本文件: {e}"
                try:
                     with open(error_filename, 'w', encoding='utf-8') as f:
                          f.write(f"写入文件失败: {e}\n\n")
                          f.write("--- 生成的代码 ---\n")
                          if generated_code:
                              f.write(generated_code)
                          else:
                              f.write("None (generated_code was None)")
                     logger.info(f"写入失败的代码已保存到文件: {error_filename}")
                except Exception as write_error:
                     logger.error(f"无法保存写入失败的代码到文件 {error_filename}: {write_error}")


        else: # Script generation or validation failed
            logger.error(f"为用例 '{test_case.get('scene', f'用例 {i+1}')}' 生成脚本失败: {error_message}")
            # Save the error details and the problematic code (if any was returned before validation failed)
            # The raw_response_filename already contains error info, but let's also save a simple .error.py
            try:
                with open(error_filename, 'w', encoding='utf-8') as f:
                    f.write(f"脚本生成或验证失败，错误信息: {error_message}\n\n")
                    # generated_code might be None if validation failed early, or if generation failed
                    if generated_code is not None:
                         f.write("--- 可能有问题的代码 (验证前的) ---\n")
                         f.write(generated_code)
                    else:
                        f.write("--- 未生成有效代码 ---\n")

                logger.info(f"脚本生成失败的错误信息和代码已保存到文件: {error_filename}")
            except Exception as e:
                logger.error(f"无法保存错误信息到文件 {error_filename}: {e}")


    logger.info(f"脚本生成完成。总计 {len(test_cases)} 个测试用例，成功生成 {successful_scripts} 个脚本。")

    if successful_scripts == 0:
        logger.error("未成功生成任何Playwright脚本，停止后续流程。")
        sys.exit(1) # Exit with a non-zero status code if no scripts were generated
