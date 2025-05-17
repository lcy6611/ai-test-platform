import requests
import os
import json
import logging

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def read_snapshots():
    snapshots = []
    if not os.path.exists("snapshots"):
        logging.error("snapshots 目录不存在！")
        return ""
    for fname in os.listdir("snapshots"):
        if fname.endswith(".html"):
            try:
                with open(os.path.join("snapshots", fname), "r", encoding="utf-8") as f:
                    snapshots.append(f"页面 {fname} 快照:\n{f.read()}")
            except Exception as e:
                logging.error(f"读取 {fname} 失败: {e}")
    return "\n".join(snapshots)

def clean_code_block(text):
    text = text.strip()
    if text.startswith("```") or text.startswith("'''"):
        text = text.split('\n', 1)[-1]
    if text.endswith("```") or text.endswith("'''"):
        text = text.rsplit('\n', 1)[0]
    return text.strip()

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
        if "choices" not in resp_json:
            logging.error(f"AI返回内容异常: {resp_json}")
            return ""
        content = resp_json["choices"][0]["message"]["content"]
        return clean_code_block(content)
    except Exception as e:
        logging.error(f"调用 deepseek-chat 失败: {e}")
        return ""

if __name__ == "__main__":
    snapshots = read_snapshots()
    if not snapshots:
        logging.error("未获取到任何页面快照，流程终止。")
        exit(1)
    testcases = generate_testcases_by_snapshot(snapshots)
    if not testcases:
        logging.error("未生成任何用例，流程终止。")
        exit(1)
    with open("testcases.json", "w", encoding="utf-8") as f:
        f.write(testcases)