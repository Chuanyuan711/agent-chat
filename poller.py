"""
Agent Chat 轮询器 v3.0 — SSE实时推送版
========================================
职责：通过SSE长连接实时监听新消息，写通知文件。
铁律：绝不自动回复，绝不调用 POST /messages。

变更日志：
- v3.0: SSE长连接为主，HTTP轮询为降级方案
- v2.0: HTTP轮询60秒间隔
- v1.0: 初版

架构：
  SSE (主) → 实时收到新消息 → 写通知文件
    ↓ 断线
  HTTP轮询 (备) → 每5秒检查 → SSE恢复后切回
"""

import urllib.request
import urllib.error
import urllib.parse
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
MY_NAME = "金金"             # 监听谁的未读
MY_NAME_ENCODED = urllib.parse.quote(MY_NAME)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NOTIFY_FILE = os.path.join(BASE_DIR, "notifications.jsonl")
LOG_FILE = os.path.join(BASE_DIR, "poller.log")
STATE_FILE = os.path.join(BASE_DIR, "poller_state.json")

# SSE 配置
SSE_URL = CHAT_URL + "/messages/stream?thread_id=all&last_id={last_id}"
SSE_TIMEOUT = 300            # SSE连接超时（秒），超时后自动重连
SSE_MAX_BACKOFF = 60         # 最大重连退避时间（秒）

# HTTP 轮询降级配置
POLL_INTERVAL = 5            # 降级轮询间隔（秒）
POLL_RECOVERY_ATTEMPTS = 3   # 连续N次HTTP轮询成功后尝试切回SSE


# ── 工具函数 ──────────────────────────────────────────────────────────────

def log(msg):
    """写日志（同时输出到终端和文件）"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state():
    """加载持久化状态（last_processed_id）"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_processed_id": 0}


def save_state(state):
    """保存持久化状态"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        log(f"保存状态失败: {e}")


def write_notification(messages):
    """
    将新消息写入通知文件（append模式）
    返回 True 表示写入成功
    """
    notification = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "unread_count": len(messages),
        "messages": [
            {
                "id": m["id"],
                "sender": m["sender"],
                "content": m["content"],
                "thread_id": m.get("thread_id", ""),
                "timestamp": m.get("timestamp", ""),
            }
            for m in messages
        ],
    }
    try:
        with open(NOTIFY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(notification, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log(f"写入通知文件失败: {e}")
        return False


def process_messages(messages, state):
    """处理新消息：写通知文件 + 更新游标"""
    if not messages:
        return

    # 过滤掉自己发的消息
    new_msgs = [m for m in messages if m.get("sender") != MY_NAME]
    if not new_msgs:
        # 即使全是自己的消息，也要更新游标
        max_id = max(m["id"] for m in messages)
        state["last_processed_id"] = max_id
        save_state(state)
        return

    log(f"收到 {len(new_msgs)} 条新消息 (来自: {', '.join(set(m['sender'] for m in new_msgs))})")

    written = write_notification(new_msgs)
    if written:
        max_id = max(m["id"] for m in messages)
        state["last_processed_id"] = max_id
        save_state(state)
        log(f"已写入通知文件，游标更新到 id={max_id}")
    else:
        log("通知文件写入失败，游标不更新，下次重试")


# ── SSE 长连接 ────────────────────────────────────────────────────────────

def sse_connect(last_id):
    """建立SSE连接，返回 (response, generator) 或 (None, None)"""
    url = SSE_URL.format(last_id=last_id)
    log(f"SSE连接: {url}")
    try:
        req = urllib.request.Request(url)
        req.add_header("Accept", "text/event-stream")
        req.add_header("Cache-Control", "no-cache")
        resp = urllib.request.urlopen(req, timeout=SSE_TIMEOUT)
        return resp
    except Exception as e:
        log(f"SSE连接失败: {e}")
        return None


def sse_read_lines(resp):
    """从SSE响应中逐行读取data行（用readline避免缓冲阻塞）"""
    while True:
        try:
            raw_line = resp.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line.startswith("data: "):
                yield line[6:]
        except Exception:
            break


def sse_loop(state):
    """SSE主循环，返回时表示连接断开"""
    last_id = state["last_processed_id"]
    resp = sse_connect(last_id)
    if resp is None:
        return False

    log("SSE连接已建立，监听中...")
    try:
        for data_str in sse_read_lines(resp):
            try:
                msg = json.loads(data_str)
                process_messages([msg], state)
            except json.JSONDecodeError:
                log(f"SSE数据解析失败: {data_str[:100]}")
    except Exception as e:
        log(f"SSE读取异常: {e}")
    finally:
        try:
            resp.close()
        except Exception:
            pass

    log("SSE连接断开")
    return True


# ── HTTP 轮询降级 ─────────────────────────────────────────────────────────

def poll_once(state):
    """单次HTTP轮询，返回新消息列表或None（失败）"""
    last_id = state["last_processed_id"]
    try:
        url = f"{CHAT_URL}/messages?limit=50&after_id={last_id}"
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json; charset=utf-8")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        messages = data.get("messages", [])
        # 过滤：只取id > last_id的
        return [m for m in messages if m["id"] > last_id]
    except Exception as e:
        log(f"HTTP轮询失败: {e}")
        return None


def poll_loop(state):
    """HTTP轮询降级循环，返回时表示要切回SSE"""
    consecutive_success = 0
    log("进入HTTP轮询降级模式")

    while True:
        time.sleep(POLL_INTERVAL)
        messages = poll_once(state)
        if messages is None:
            consecutive_success = 0
            continue

        process_messages(messages, state)
        consecutive_success += 1

        if consecutive_success >= POLL_RECOVERY_ATTEMPTS:
            log(f"HTTP轮询连续 {consecutive_success} 次成功，尝试切回SSE")
            return True


# ── 主循环 ────────────────────────────────────────────────────────────────

def main():
    state = load_state()
    log("=" * 50)
    log(f"Agent Chat 轮询器 v3.0 (SSE实时推送)")
    log(f"聊天室: {CHAT_URL}")
    log(f"监听身份: {MY_NAME}")
    log(f"通知文件: {NOTIFY_FILE}")
    log(f"状态文件: {STATE_FILE}")
    log(f"游标位置: last_processed_id={state['last_processed_id']}")
    log("铁律: 绝不自动回复，绝不代发消息")
    log("=" * 50)

    # 检查聊天室是否可达
    try:
        req = urllib.request.Request(f"{CHAT_URL}/participants")
        resp = urllib.request.urlopen(req, timeout=5)
        log("聊天室可达")
    except Exception as e:
        log(f"警告: 聊天室不可达 ({e})，将继续重试...")

    backoff = 1
    while True:
        try:
            # 尝试SSE连接
            connected = sse_loop(state)
            if connected:
                backoff = 1  # SSE成功连接过，重置退避
            else:
                log(f"SSE连接失败，{backoff}秒后重试...")
                time.sleep(backoff)
                backoff = min(backoff * 2, SSE_MAX_BACKOFF)
                continue

            # SSE断线后，进入HTTP轮询降级
            should_retry_sse = poll_loop(state)
            if should_retry_sse:
                continue

        except KeyboardInterrupt:
            log("轮询器已退出 (Ctrl+C)")
            break
        except Exception as e:
            log(f"主循环异常: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
