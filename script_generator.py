"""
脚本生成器模块
根据生成的测试用例和页面快照数据，调用 AI 模型生成 Playwright 自动化测试脚本。
包含对 AI 响应的代码块提取和初步语法检查。
"""
import os
import json
import requests
import ast  # 用于初步的语法检查
import re   # 用于清理markdown代码块
from loguru import logger

# 配置日志
logger.add("file_{time}.log", rotation="1 day", level="INFO")

# 从环境变量获取 DeepSeek API Key
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    logger.error("未设置 DEEPSEEK_API_KEY 环境变量。请设置 API Key。")
    # Consider exiting or raising an error if the API key is critical
    # exit(1)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions" # DeepSeek API 地址

def call_deepseek_api(prompt_messages):
    """
    调用 DeepSeek API 获取 AI 生成的响应。

    Args:
        prompt_messages (list): 包含对话消息的列表，遵循 OpenAI API 格式。

    Returns:
        str or None: AI 生成的文本内容，如果调用失败则返回 None。
    """
    if not DEEPSEEK_API_KEY:
        logger.error("API Key 未设置，无法调用 DeepSeek API。")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    payload = {
        "model": "deepseek-chat", # 或 "deepseek-coder" 取决于您的需求，chat 通常更适合生成测试脚本
        "messages": prompt_messages,
        "stream": False # 非流式输出
    }

    try:
        logger.info("正在调用 DeepSeek API 生成脚本...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60) # 增加超时时间
        response.raise_for_status() # 检查 HTTP 错误

        response_data = response.json()
        logger.debug(f"DeepSeek API 原始响应: {response_data}") # 打印原始响应用于调试

        # 检查并返回 AI 生成的内容
        if response_data and response_data.get('choices'):
            # 查找 role 是 'assistant' 的第一个消息，并获取其 content
            for choice in response_data['choices']:
                if choice.get('message') and choice['message'].get('role') == 'assistant':
                    return choice['message']['content']
            logger.warning("DeepSeek API 响应成功，但未找到 role 为 'assistant' 的消息内容。")
            return None
        else:
            logger.error(f"DeepSeek API 响应格式错误或为空: {response_data}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"调用 DeepSeek API 发生网络或HTTP错误: {e}")
        return None
    except KeyError as e:
        logger.error(f"DeepSeek API 响应缺少预期的键: {e}. 响应数据: {response_data}")
        # 打印完整的响应数据以帮助调试
        logger.error(f"完整响应数据: {json.dumps(response_data, indent=4)}")
        return None
    except Exception as e:
        logger.error(f"调用 DeepSeek API 发生未知错误: {e}")
        return None

def clean_code_block(text):
    """
    从包含 Markdown 代码块的文本中提取 Python 代码。
    如果存在 '```python' 和 '```' 标记，则只提取标记内的内容。
    如果没有标记，则返回原始文本（去除首尾空白）。
    """
    # 使用正则表达式查找 Python 代码块
    match = re.search(r'```python\n(.*?)\n```', text, re.DOTALL)
    if match:
        # 返回代码块内的内容
        cleaned_text = match.group(1).strip()
        logger.info("从 Markdown 代码块中成功提取 Python 代码。")
        return cleaned_text
    else:
        # 如果没有找到代码块标记，打印警告并返回原始文本
        logger.warning("未在 AI 响应中找到 '```python'/'```' Markdown 代码块标记，返回原始文本。")
        return text.strip() # 返回去除首尾空白的原始文本

def validate_python_syntax(code):
    """
    初步检查 Python 代码的语法是否有效。

    Args:
        code (str): 要检查的 Python 代码字符串。

    Returns:
        bool: 如果语法有效返回 True，否则返回 False。
    """
    try:
        ast.parse(code)
        logger.info("Python 代码语法检查通过。")
        return True
    except SyntaxError as e:
        logger.error(f"Python 代码语法错误: {e}")
        return False
    except Exception as e:
        logger.error(f"检查 Python 代码语法时发生未知错误: {e}")
        return False

def generate_scripts_from_testcases(testcases_file="generated_testcases.json", snapshot_file="snapshots/page_snapshot.json", scripts_dir="generated_scripts"):
    """
    读取测试用例和页面快照数据，调用 AI 生成 Playwright 脚本。

    Args:
        testcases_file (str): 包含测试用例的 JSON 文件路径。
        snapshot_file (str): 包含页面快照的 JSON 文件路径。
        scripts_dir (str): 生成脚本保存的目录。
    """
    if not os.path.exists(testcases_file):
        logger.error(f"未找到测试用例文件: {testcases_file}")
        return

    if not os.path.exists(snapshot_file):
         logger.error(f"未找到页面快照文件: {snapshot_file}。请先运行 page_snapshot_collector.py。")
         return

    if not os.path.exists(scripts_dir):
        os.makedirs(scripts_dir)
        logger.info(f"创建脚本输出目录: {scripts_dir}")

    try:
        with open(testcases_file, 'r', encoding='utf-8') as f:
            testcases = json.load(f)
        logger.info(f"成功加载测试用例文件: {testcases_file}")
    except Exception as e:
        logger.error(f"加载测试用例文件失败: {e}")
        return

    try:
        with open(snapshot_file, 'r', encoding='utf-8') as f:
            snapshot_data = json.load(f)
        logger.info(f"成功加载页面快照文件: {snapshot_file}")
    except Exception as e:
        logger.error(f"加载页面快照文件失败: {e}")
        # 即使加载快照失败，也可以尝试用测试用例生成脚本，但效果可能不好
        snapshot_data = {}
        logger.warning("页面快照数据加载失败，脚本生成可能会受到影响。")


    # 遍历每个测试用例，生成对应的脚本
    for i, testcase in enumerate(testcases):
        testcase_name = testcase.get("name", f"test_case_{i+1}")
        steps = testcase.get("steps", [])
        target_url = testcase.get("target_url") # 获取测试用例中的目标URL

        if not steps:
            logger.warning(f"测试用例 '{testcase_name}' 没有步骤，跳过脚本生成。")
            continue

        # 根据目标URL获取对应的快照数据
        current_url_snapshot = snapshot_data.get(target_url, [])
        # 将结构化的快照数据转换为 AI 易于理解的字符串描述
        snapshot_description = "页面 UI 元素快照:\n"
        if current_url_snapshot:
            for element in current_url_snapshot:
                 snapshot_description += f"- 标签: {element.get('tag')}, 选择器示例: {element.get('selector')}, 文本/值: '{element.get('text')}', ID: '{element.get('id')}', 名称: '{element.get('name')}', 类型: '{element.get('type')}', 角色: '{element.get('role')}'\n"
        else:
            snapshot_description += "无可用快照数据。\n"


        # 构建给 AI 的 Prompt
        # 强调使用 Playwright Python API
        # 强调只输出完整的、可直接运行的 Python 代码
        # 添加在填写输入框前先点击的要求
        prompt_messages = [
            {"role": "system", "content": "你是一个经验丰富的自动化测试工程师，擅长使用 Playwright Python 库编写端到端测试脚本。请根据用户提供的测试用例步骤和页面UI元素快照，生成一个完整的、可直接运行的 Playwright Python 测试脚本。脚本应该使用同步 API (sync_playwright)。在生成脚本时，遵循以下规则：1. 对于所有的输入字段（input fields），在执行文本填写（fill/type）操作之前，必须先执行一次点击（click）操作。2. 仅输出完整的 Python 代码，不要包含任何解释性文本或 Markdown 代码块标记（如 ```python）。3. 尽可能使用稳健的选择器，如 text=, role=, 或者 комбинированные CSS/XPath 选择器。4. 包含必要的导入语句和 Playwright 的上下文管理。5. 脚本应该包含一个测试函数，例如 `def test_example(page):`。6. 在需要等待元素出现、页面加载或导航时，使用合适的 Playwright 等待方法，并设置合理的超时时间。"},
            {"role": "user", "content": f"请为以下测试用例生成 Playwright Python 脚本：\n\n测试用例名称: {testcase_name}\n目标 URL: {target_url}\n测试步骤:\n{'- ' + '\\n- '.join(steps)}\n\n{snapshot_description}\n\n请注意：对于所有的输入字段（input fields），在执行文本填写（fill/type）操作之前，必须先执行一次点击（click）操作。"}
        ]

        logger.info(f"正在为测试用例 '{testcase_name}' 生成脚本...")
        ai_response = call_deepseek_api(prompt_messages)

        if ai_response:
            logger.info(f"成功获取 AI 响应，正在清理和验证代码...")
            # 清理 AI 响应，提取代码块
            cleaned_code = clean_code_block(ai_response)

            if cleaned_code:
                # 进行初步的 Python 语法检查
                if validate_python_syntax(cleaned_code):
                    # 生成脚本文件名，例如 test_login.py
                    # 将测试用例名称转换为有效的文件名
                    script_filename = re.sub(r'\W+', '_', testcase_name).lower() + ".py"
                    script_file_path = os.path.join(scripts_dir, script_filename)

                    try:
                        with open(script_file_path, 'w', encoding='utf-8') as f:
                            f.write(cleaned_code)
                        logger.success(f"脚本生成成功并保存到: {script_file_path}")
                    except Exception as e:
                        logger.error(f"保存脚本文件 {script_file_path} 失败: {e}")
                else:
                    logger.error(f"为测试用例 '{testcase_name}' 生成的脚本存在语法错误，未保存为 .py 文件。")
                    # 可以选择将错误代码保存到临时文件以便调试
                    error_file_path = os.path.join(scripts_dir, f"{testcase_name}.error.py")
                    try:
                         with open(error_file_path, 'w', encoding='utf-8') as f:
                             f.write(cleaned_code)
                         logger.warning(f"有语法错误的代码已保存到: {error_file_path}")
                    except Exception as e:
                         logger.error(f"保存错误代码到文件失败: {e}")

            else:
                logger.error(f"AI 返回内容清理后为空，未生成脚本 for '{testcase_name}'。原始响应：{ai_response}")

        else:
            logger.error(f"AI 返回内容为空，未生成脚本 for '{testcase_name}'。请检查 API 调用或 AI 响应。")


if __name__ == "__main__":
    logger.info("开始执行脚本生成器...")
    generate_scripts_from_testcases()
    logger.info("脚本生成器执行完成。")