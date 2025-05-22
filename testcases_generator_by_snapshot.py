import json
import logging
import os
import re

import requests

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def read_snapshots(snapshot_json_path="snapshots/page_snapshot.json"):
    """
    读取 page_snapshot.json 文件内容。
    """
    if not os.path.exists(snapshot_json_path):
        logging.error(f"错误：找不到页面快照文件 {snapshot_json_path}。")
        return None
    try:
        with open(snapshot_json_path, 'r', encoding='utf-8') as f:
            # 读取整个JSON文件的内容作为快照数据
            snapshot_content = f.read()
            logging.info(f"成功读取页面快照文件 {snapshot_json_path}。")
            return snapshot_content
    except Exception as e:
        logging.error(f"读取页面快照文件 {snapshot_json_path} 失败: {e}")
        return None


def clean_code_block(text):
    """
    自动提取第一个 markdown 代码块（```json ... ``` 或 '''json ... '''），只保留 JSON 内容
    """
    text = text.strip()
    # 匹配 ```json ... ``` 或 '''json ... '''
    match = re.search(
        r"(?:```json|'''json|```|''')\s*([\s\S]*?)\s*(?:```|''')", text, re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    # 如果没有代码块，尝试直接找第一个 [ 开头的 JSON
    idx = text.find("[")
    if idx != -1:
        return text[idx:].strip()
    return text


def generate_testcases_by_snapshot(snapshots):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    prompt = (
        "请根据以下页面快照，自动分析页面结构和功能，生成结构化的功能测试用例，"
        "每个用例包含scene, steps, expected三个字段，输出为JSON数组：\n"
        f"{snapshots}"
    )
    data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
    try:
        response = requests.post(
            DEEPSEEK_API_URL, headers=headers, json=data, timeout=120
        )
        response.raise_for_status()
        resp_json = response.json()
        logging.info(f"AI原始返回: {resp_json}")
        if "choices" not in resp_json or not resp_json["choices"]:
            logging.error(f"AI返回内容异常: {resp_json}")
            return ""
        content = resp_json["choices"][0]["message"]["content"]
        return clean_code_block(content)
    except Exception as e:
        logging.error(f"调用 deepseek-chat 失败: {e}")
        return ""


if __name__ == "__main__":
    snapshot_file = os.path.join("snapshots", "page_snapshot.json")  # 修改为正确路径
    output_file = "testcases.json"
    snapshots = read_snapshots(snapshot_file) # 将修改后的 read_snapshots 函数参数传递进去
    if not snapshots:
        logging.error("未获取到任何页面快照，流程终止。")
        exit(1)
    testcases = generate_testcases_by_snapshot(snapshots)
    if not testcases:
        logging.error("未生成任何用例，流程终止。")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("")
        exit(1)
    # 写入前先校验JSON
    try:
        json.loads(testcases)
    except Exception as e:
        logging.error(f"AI返回内容不是合法JSON: {e}\n内容如下：\n{testcases}")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("")
        exit(1)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(testcases)