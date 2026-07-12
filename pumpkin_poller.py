"""
Pumpkin 专属 SSE 监听器
========================
职责：监听 Agent Chat 所有新消息，当收到非 Pumpkin 发送的消息时，
      调用 OpenClaw hooks/wake 唤醒 Pumpkin。

架构：
  SSE 长连接 → 收到新消息 → 调用 OpenClaw hooks/wake
"""

import urllib.request
import urllib.error
import json
import time
import os
import sys
from datetime import datetime

# Windows 控制台 UTF-8 支持
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 配置 ──────────────────────────────────────────────────────────────────

CHAT_URL = "http://localhost:9090"
OPENCLAW_HOOKS_URL = "http://host.docker.internal:18789/hooks/wake"
OPENCLAW_HOOK_TOKEN = "n8n-openclaw-hook-token-2026"
MY_NAME = "Pumpkin"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "pumpkin_poller.log")
STATE_FILE = os.path.join(BASE_DIR, "pumpkin_poller_state.json")

# SSE 配置
SSE_URL = CHAT_URL + "/messages/stream?thread_id=all&last_id={last_id}"
SSE_TIMEOUT = 300
SSE_MAX_BACKOFF = 60

# HTTP 轮询降级配置
POLL_INTERVAL = 5
POLL_RECOVERY_ATTEMPTS = 3


# ── 工具函数 ──────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"last_id": 0}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def wake_openclaw(message, thread_id):
    """调用 OpenClaw hooks/wake 唤醒 Pumpkin"""
    try:
        data = json.dumps({
            "text": f"[Agent Chat] {message}",
            "thread_id": thread_id,
        }, ensure_ascii=False).encode("utf-8")
        
        req = urllib.request.Request(
            OPENCLAW_HOOKS_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENCLAW_HOOK_TOKEN}",
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=5)
        log(f"✅ 已唤醒 OpenClaw: {message[:50]}...")
        return True
    except Exception as e:
        log(f"❌ 唤醒 OpenClaw 失败: {e}")
        return False


def check_unread_http():
    """HTTP 轮询检查未读消息"""
    try:
        url = f"{CHAT_URL}/messages/unread/{MY_NAME}"
        resp = urllib.request.urlopen(url, timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("messages", [])
    except Exception as e:
        log(f"❌ HTTP 轮询失败: {e}")
        return []


def process_message(msg):
    """处理新消息，如果是其他人发的就唤醒 OpenClaw"""
    sender = msg.get("sender", "")
    content = msg.get("content", "")
    thread_id = msg.get("thread_id", "general")
    msg_id = msg.get("id", 0)
    
    # 跳过自己发的消息
    if sender == MY_NAME:
        return False
    
    # 跳过系统消息（但保留重要通知）
    if sender == "system" and "📢" in content:
        # 新话题通知，可以忽略
        return False
    
    # 唤醒 OpenClaw
    wake_text = f"[{thread_id}] {sender}: {content[:100]}"
    return wake_openclaw(wake_text, thread_id)


def sse_connect(last_id):
    """连接 SSE 流"""
    url = SSE_URL.format(last_id=last_id)
    log(f"🔌 连接 SSE: {url}")
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=SSE_TIMEOUT)
        return resp
    except Exception as e:
        log(f"❌ SSE 连接失败: {e}")
        return None


def parse_sse_line(line):
    """解析 SSE 数据行"""
    if line.startswith("data: "):
        try:
            return json.loads(line[6:])
        except json.JSONDecodeError:
            pass
    return None


# ── 主循环 ──────────────────────────────────────────────────────────────

def main():
    log("🚀 Pumpkin SSE 监听器启动")
    
    state = load_state()
    last_id = state.get("last_id", 0)
    log(f"📂 从 last_id={last_id} 开始监听")
    
    sse_mode = True
    sse_resp = None
    http_success_count = 0
    backoff = 1
    
    while True:
        try:
            if sse_mode:
                # SSE 模式
                if sse_resp is None:
                    sse_resp = sse_connect(last_id)
                    if sse_resp is None:
                        log("⚠️ SSE 连接失败，切换到 HTTP 轮询模式")
                        sse_mode = False
                        backoff = 1
                        continue
                
                # 读取 SSE 数据
                line = sse_resp.readline().decode("utf-8").strip()
                if not line:
                    # 连接超时，重连
                    log("⚠️ SSE 连接超时，重连...")
                    sse_resp.close()
                    sse_resp = None
                    time.sleep(backoff)
                    backoff = min(backoff * 2, SSE_MAX_BACKOFF)
                    continue
                
                if line.startswith("data: "):
                    msg = parse_sse_line(line)
                    if msg:
                        msg_id = msg.get("id", 0)
                        if msg_id > last_id:
                            last_id = msg_id
                            save_state({"last_id": last_id})
                            process_message(msg)
                        backoff = 1  # 成功收到消息，重置退避
                
            else:
                # HTTP 轮询模式
                messages = check_unread_http()
                if messages:
                    for msg in messages:
                        msg_id = msg.get("id", 0)
                        if msg_id > last_id:
                            last_id = msg_id
                            save_state({"last_id": last_id})
                            process_message(msg)
                    http_success_count += 1
                    
                    # 连续成功多次后尝试切回 SSE
                    if http_success_count >= POLL_RECOVERY_ATTEMPTS:
                        log("🔄 尝试切回 SSE 模式...")
                        sse_mode = True
                        http_success_count = 0
                else:
                    http_success_count = 0
                
                time.sleep(POLL_INTERVAL)
                
        except KeyboardInterrupt:
            log("👋 收到中断信号，退出...")
            if sse_resp:
                sse_resp.close()
            break
        except Exception as e:
            log(f"❌ 异常: {e}")
            time.sleep(backoff)
            backoff = min(backoff * 2, SSE_MAX_BACKOFF)


if __name__ == "__main__":
    main()
