"""
根据页面快照生成结构化功能测试用例模块
调用deepseek-chat API将HTML快照转为测试用例
"""

import requests
import os
import json
import logging
import re

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def read_snapshots():
    """
    读取snapshots目录下的所有HTML快照文件内容
    """
    snapshots = []
    if not os.path.exists("snapshots"):
        logging.error("snapshots 目录不存在！")
        return ""
    for fname in os.listdir("snapshots"):
        if fname.endswith(".html"):
            try:
                with open(os.path.join("snapshots", fname), "r", encoding="utf-8") as f:
                    # 限制每个快照的大小，防止API请求过长
                    content = f.read(10000) # 读取前10000个字符
                    snapshots.append(f"页面 {fname} 快照:\n{content}")
            except Exception as e:
                logging.error(f"读取 {fname} 失败: {e}")
    return "\n".join(snapshots)

def clean_code_block(text):
    """
    自动提取第一个 markdown 代码块（```json ... ``` 或 '''json ... '''），只保留 JSON 内容
    若无代码块，尝试直接找第一个 [ 开头的 JSON
    """
    text = text.strip()
    # 匹配 ```json ... ``` 或 '''json ... ''' 或 ``` 或 '''
    match = re.search(r"(?:```json|'''json|```|''')\s*([\s\S]*?)\s*(?:```|''')", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # 如果没有代码块，尝试直接找第一个 [ 开头的 JSON
    idx = text.find('[')
    if idx != -1:
        return text[idx:].strip()
    return "" # 如果没有找到JSON结构，返回空字符串


def generate_testcases_by_snapshot(snapshots):
    """
    调用deepseek-chat API，将页面快照转为结构化测试用例
    """
    if not DEEPSEEK_API_KEY:
        logging.error("DEEPSEEK_API_KEY 环境变量未设置，无法调用API！")
        return ""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    prompt = (
        "请根据以下页面快照，自动分析页面结构和功能，生成结构化的功能测试用例，"
        "每个用例包含scene, steps, expected三个字段，输出为JSON数组：\n"
        "确保输出内容是严格的JSON数组格式，不要包含额外的文字或markdown标记。"
        f"\n{snapshots}"
    )
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
    try:
        response = requests.post(
            DEEPSEEK_API_URL, headers=headers, json=data, timeout=120
        )
        response.raise_for_status() # 检查HTTP响应状态
        resp_json = response.json()
        logging.info(f"AI原始返回: {resp_json}")

        if "choices" not in resp_json or not resp_json["choices"]:
            logging.error(f"AI返回内容异常或为空: {resp_json}")
            return ""

        content = resp_json["choices"][0]["message"]["content"]
        # 先尝试清洗，再返回可能为JSON的字符串
        cleaned_content = clean_code_block(content)

        # 额外检查清洗后的内容是否像JSON，防止返回空字符串导致解析失败
        if not cleaned_content.startswith("[") or not cleaned_content.endswith("]"):
             logging.error(f"清洗后的内容不是有效的JSON数组结构: {cleaned_content}")
             # 尝试从原始返回中查找第一个JSON结构作为兜底
             fallback_match = re.search(r'(\\[.*?\\\])', content, re.DOTALL)
             if fallback_match:
                 logging.warning("尝试从原始返回中提取兜底JSON。")
                 try:
                     json.loads(fallback_match.group(1))
                     return fallback_match.group(1)
                 except Exception as e:
                      logging.error(f"兜底JSON提取及校验失败: {e}")
                      return ""
             return ""


        return cleaned_content

    except requests.exceptions.RequestException as e:
        logging.error(f"调用 deepseek-chat API 请求失败: {e}")
        return ""
    except json.JSONDecodeError as e:
         logging.error(f"解析 deepseek-chat API 返回的JSON失败: {e}")
         return ""
    except Exception as e:
        logging.error(f"生成测试用例过程中发生未知错误: {e}")
        return ""


if __name__ == "__main__":
    logging.info("开始生成测试用例...")
    snapshots = read_snapshots()
    if not snapshots:
        logging.error("未获取到任何页面快照，无法生成测试用例。")
        # 即使失败，也要创建一个空的 testcases.json，防止后续脚本报错
        with open("testcases.json", "w", encoding="utf-8") as f:
            f.write("[]") # 写入空JSON数组
        exit(1)

    testcases_content = generate_testcases_by_snapshot(snapshots)

    if not testcases_content:
        logging.error("未生成任何有效测试用例内容。")
        with open("testcases.json", "w", encoding="utf-8") as f:
            f.write("[]") # 写入空JSON数组
        exit(1)

    # 写入前再次校验JSON合法性
    try:
        testcases_list = json.loads(testcases_content)
        # 可选：检查是否是列表且包含用例
        if not isinstance(testcases_list, list) or not testcases_list:
             logging.warning("AI生成内容是合法JSON，但不是非空列表。写入空数组。")
             with open("testcases.json", "w", encoding="utf-8") as f:
                 f.write("[]")
             exit(0) # 非致命错误，允许继续
    except Exception as e:
        logging.error(f"AI生成内容不是合法JSON: {e}\n内容如下：\n{testcases_content}")
        with open("testcases.json", "w", encoding="utf-8") as f:
            f.write("[]") # 写入空JSON数组
        exit(1) # 致命错误，终止流程

    with open("testcases.json", "w", encoding="utf-8") as f:
        json.dump(testcases_list, f, ensure_ascii=False, indent=2)

    logging.info(f"测试用例已成功保存到 testcases.json，共生成 {len(testcases_list)} 条用例。")
