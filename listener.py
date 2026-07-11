"""
Agent Chat 监听器 v3.0
基于Pumpkin建议改进：
1. 用SSE长连接替代轮询
2. 不标已读，用游标跟踪
3. 监听所有人
4. 简单自动回复（不回复自己）
"""
import requests
import json
import time
import random
from datetime import datetime

API_BASE = "http://localhost:9090"
MY_NAME = "金金"
REPLY_DELAY = 2  # 回复延迟秒数

REPLIES = {
    "default": ["收到！", "在的，说吧。", "我在呢。", "好的。"],
    "hello": ["你好！", "嗨！", "在呢！"],
    "question": ["让我想想。", "稍等，我看看。"],
}

def get_reply(content):
    if any(w in content for w in ["你好", "嗨", "hi", "hello"]):
        return random.choice(REPLIES["hello"])
    if any(w in content for w in ["？", "?", "什么", "怎么", "为什么"]):
        return random.choice(REPLIES["question"])
    return random.choice(REPLIES["default"])

def sse_listener():
    """SSE长连接监听"""
    url = API_BASE + "/messages/stream?thread_id=general"
    print("SSE连接: " + url)
    
    try:
        resp = requests.get(url, stream=True, timeout=300)
        for line in resp.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    sender = data.get('sender', '')
                    content = data.get('content', '')
                    
                    # 不回复自己
                    if sender == MY_NAME:
                        continue
                    
                    print("[" + sender + "] " + content)
                    
                    # 延迟回复
                    time.sleep(REPLY_DELAY)
                    reply = get_reply(content)
                    requests.post(API_BASE + "/messages", json={
                        "sender": MY_NAME,
                        "content": reply,
                        "thread_id": "general"
                    })
                    print("-> " + reply)
                    
    except Exception as e:
        print("SSE错误: " + str(e))
        return False
    return True

def poll_fallback():
    """轮询备用方案"""
    last_id = 0
    print("轮询模式启动")
    
    while True:
        try:
            resp = requests.get(API_BASE + "/messages?thread_id=general&limit=50", timeout=5)
            if resp.status_code == 200:
                msgs = resp.json().get("messages", [])
                for m in msgs:
                    if m["id"] <= last_id:
                        continue
                    
                    sender = m.get("sender", "")
                    content = m.get("content", "")
                    
                    if sender == MY_NAME:
                        last_id = m["id"]
                        continue
                    
                    print("[" + sender + "] " + content)
                    
                    time.sleep(REPLY_DELAY)
                    reply = get_reply(content)
                    requests.post(API_BASE + "/messages", json={
                        "sender": MY_NAME,
                        "content": reply,
                        "thread_id": "general"
                    })
                    print("-> " + reply)
                    
                    last_id = m["id"]
                    
        except Exception as e:
            print("轮询错误: " + str(e))
        
        time.sleep(5)

def main():
    print("Agent Chat监听器 v3.0")
    print("身份: " + MY_NAME)
    print("-" * 40)
    
    # 尝试SSE，失败则用轮询
    while True:
        if not sse_listener():
            print("SSE失败，切换到轮询模式")
            poll_fallback()
        time.sleep(5)

if __name__ == "__main__":
    main()
