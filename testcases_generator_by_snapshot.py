"""
测试用例生成模块
根据页面快照生成结构化测试用例 (testcases.json)
"""
import json
import os
import requests
import re
from loguru import logger
import sys
import traceback # Import traceback module

# Remove sys.stdout.reconfigure and sys.stderr.reconfigure for broader Python version compatibility.
# To ensure UTF-8 output, it's generally recommended to set the PYTHONIOENCODING environment variable
# before running the script, or rely on the logging library's encoding settings.
# sys.stdout.reconfigure(encoding='utf-8')
# sys.stderr.reconfigure(encoding='utf-8')

# 使用loguru进行日志记录，并确保日志文件使用UTF-8编码
logger.add("testcase_generation.log", rotation="1 MB", encoding="utf-8")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def clean_code_block(text):
    """
    从AI返回的文本中提取JSON代码块，处理可能的Markdown标记。
    如果提取失败，则尝试直接解析原始文本（在清理Markdown标记后）。
    """
    # Decode bytes if necessary, assuming UTF-8
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='ignore')

    # Remove potential Byte Order Mark (BOM)
    text = text.lstrip('\ufeff')

    # Enhanced regex to find potential JSON blocks, including those with or without language specifiers
    json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        logger.debug("Found JSON block using ```json``` or `````` markdown.")
        extracted_text = json_match.group(1)
        # Attempt to parse the extracted text as JSON
        try:
            json.loads(extracted_text)
            logger.debug("Successfully parsed extracted JSON block.")
            return extracted_text.strip()
        except json.JSONDecodeError:
            logger.warning("Extracted text from markdown block is not valid JSON. Trying fallback methods.")
            # Fallback to cleaning markdown and trying to parse the whole text
            pass # Continue to general markdown cleaning below

    # If markdown block not found or not valid JSON, try cleaning general markdown
    logger.debug("JSON markdown block not found or invalid. Trying general markdown cleaning.")
    text = text.strip()
    # Remove leading/trailing ```, ```json, ```python etc.
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) > 1:
             first_line = lines[0].strip()
             # If the first line is only ``` or starts with ``` and some word (like json, python)
             if re.match(r"```\w*$", first_line) or first_line == "```":
                 text = "\n".join(lines[1:])
        text = text.rstrip("```").strip()

    # Remove potential triple quotes ``` or ''' if AI uses them without markdown backticks
    if text.startswith("'''"):
         text = text[3:].strip()
    if text.endswith("'''"):
         text = text[:-3].strip()
    if text.startswith('"""'):
         text = text[3:].strip()
    if text.endswith('"""'):
         text = text[:-3].strip()

    # Remove common non-printable characters (less aggressive than in script_generator if possible, to preserve text)
    # Keep printable ASCII, basic whitespace, and common CJK range
    text = re.sub(r'[^\x09\x0A\x0D\x20-\x7E\u4E00-\u9FFF]+', '', text)

    return text.strip()


def generate_testcases(page_snapshot_content):
    """
    调用AI根据页面快照生成测试用例。
    """
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set.")
        return None, "DEEPSEEK_API_KEY not set."

    api_prompt_content = f"""
请分析以下HTML页面快照内容，识别页面上的关键元素（如输入框、按钮、链接、复选框等），并根据这些元素和常见的用户交互流程，生成一份详细的、结构化的测试用例列表。

请以JSON格式返回测试用例列表，格式如下：
[
    {{
        "scene": "测试场景描述",
        "steps": [
            "步骤1",
            "步骤2",
            ...
        ],
        "expected": "预期结果描述"
    }},
    ...
]

请确保JSON格式严格正确，不要包含任何额外的文本或Markdown代码块标记（如```json或```）。
在生成测试用例时，请考虑以下方面：
- 输入字段的交互（输入文本，检查placeholder，检查输入类型）
- 按钮的初始状态（可用/禁用）和点击功能
- 链接的可见性和点击后的导航
- 复选框和单选框的选中/取消选中状态
- 表单的整体提交功能（输入有效/无效数据后的行为）
- 页面上其他重要UI元素的可见性或状态

页面快照内容:
{page_snapshot_content}
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": api_prompt_content}
        ]
    }

    logger.info("开始调用AI生成测试用例...")
    logger.debug(f"Prompt snippet sent to API: '{api_prompt_content[:200]}...'") # Log snippet of prompt


    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status() # Raise an exception for bad status codes
        response_data = response.json()

        logger.info("AI原始响应接收成功。")
        # Log snippet of AI response
        if response_data and 'choices' in response_data and response_data['choices']:
             ai_response_content = response_data['choices'][0]['message']['content']
             logger.info(f"AI response content snippet: '{ai_response_content[:200]}...'")
        else:
            logger.warning("AI response format unexpected or empty.")
            return None, "AI response format unexpected or empty."


        # 清理AI返回的文本，提取JSON内容
        cleaned_content = clean_code_block(ai_response_content)
        logger.debug(f"Cleaned AI response content snippet: '{cleaned_content[:200]}...'")


        # 尝试解析JSON
        try:
            testcases = json.loads(cleaned_content)
            # Optional: Add schema validation here using jsonschema if you have a schema
            # from jsonschema import validate
            # schema = {...} # Define your schema
            # validate(instance=testcases, schema=schema)
            logger.info("成功解析AI生成的JSON。")
            return testcases, None
        except json.JSONDecodeError as e:
            logger.error(f"解析AI生成的JSON失败: {e}")
            logger.error(f"Attempted to parse: {cleaned_content}") # Log the content that failed parsing
            logger.error(traceback.format_exc()) # Log the full traceback for JSONDecodeError
            return None, f"解析AI生成的JSON失败: {e}"
        except Exception as e:
            logger.error(f"解析AI生成内容时发生意外错误: {e}")
            logger.error(traceback.format_exc()) # Log the full traceback
            return None, f"解析AI生成内容时发生意外错误: {e}"


    except requests.exceptions.RequestException as e:
        logger.error(f"调用DeepSeek API失败: {e}")
        logger.error(traceback.format_exc()) # Log the full traceback
        return None, f"调用DeepSeek API失败: {e}"
    except Exception as e:
        logger.error(f"生成测试用例时发生意外错误: {e}")
        logger.error(traceback.format_exc()) # Log the full traceback
        return None, f"生成测试用例时发生意外错误: {e}"


# --- Main Execution ---
if __name__ == "__main__":
    snapshot_file = "page_snapshot.json" # Assuming snapshot is saved here
    output_file = "testcases.json"

    if not os.path.exists(snapshot_file):
        logger.error(f"错误：找不到页面快照文件 {snapshot_file}。请先运行快照采集脚本。")
        sys.exit(1) # Exit with a non-zero status code to indicate failure


    page_snapshot_content = ""
    try:
        with open(snapshot_file, 'r', encoding='utf-8') as f:
            page_snapshot_content = f.read()
        logger.info(f"成功加载页面快照文件 {snapshot_file}。")
    except Exception as e:
        logger.error(f"读取页面快照文件 {snapshot_file} 失败: {e}")
        logger.error(traceback.format_exc()) # Log the full traceback
        sys.exit(1) # Exit with a non-zero status code if reading snapshot fails


    test_cases, error_message = generate_testcases(page_snapshot_content)

    if test_cases:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(test_cases, f, indent=2, ensure_ascii=False)
            logger.info(f"测试用例已成功保存到 {output_file}，共生成 {len(test_cases)} 个测试用例。")
        except Exception as e:
             logger.error(f"无法将测试用例写入文件 {output_file}: {e}")
             logger.error(traceback.format_exc()) # Log the full traceback
             sys.exit(1) # Exit if writing testcases fails
    else:
        logger.error(f"生成测试用例失败: {error_message}")
        sys.exit(1) # Exit with a non-zero status code if generation fails
