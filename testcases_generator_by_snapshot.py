"""
根据页面快照生成结构化功能测试用例
"""

import requests
import os
import json

DEEPSEEK_API_KEY = "sk-2c7a9791906b429fb5732f2a2e88fbd5"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def read_snapshots():
    snapshots = []
    for fname in os.listdir("snapshots"):
        if fname.endswith(".html"):
            with open(os.path.join("snapshots", fname), "r", encoding="utf-8") as f:
                snapshots.append(f"页面 {fname} 快照:\n{f.read()}")
    return "\n".join(snapshots)

def generate_testcases_by_snapshot(snapshots):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = (
        "请根据以下页面快照，自动分析页面结构和功能，生成结构化的功能测试用例，"
        "每个用例包含scene, steps, expected三个字段，输出为JSON数组：\n"
        f"{snapshots}"
    )
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"]

if __name__ == "__main__":
    snapshots = read_snapshots()
    testcases = generate_testcases_by_snapshot(snapshots)
    print(testcases)
    with open("testcases.json", "w", encoding="utf-8") as f:
        f.write(testcases)