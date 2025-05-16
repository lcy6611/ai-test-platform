"""
需求解析与自然语言处理模块
使用deepseek-chat API从PRD文档中提取测试需求
"""

import requests

DEEPSEEK_API_KEY = "sk-2c7a9791906b429fb5732f2a2e88fbd5"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def extract_requirements(doc_text):
    """
    调用deepseek-chat API，从PRD文档中提取测试需求
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = f"请从以下PRD文档中提取所有测试需求，输出为有序列表：\n{doc_text}"
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"]

if __name__ == "__main__":
    with open("prd.txt", "r", encoding="utf-8") as f:
        doc_text = f.read()
    requirements = extract_requirements(doc_text)
    print(requirements)
    # 写入新文件，避免覆盖pip依赖文件
    with open("requirements_extracted.txt", "w", encoding="utf-8") as f:
        f.write(requirements)