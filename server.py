"""Agent Chat — 三人群聊系统 FastAPI 服务"""

import sqlite3
import os
import urllib.request
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import asyncio
import json

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(_BASE_DIR, "chat.db"))
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", os.path.join(_BASE_DIR, "archive"))
PORT = int(os.getenv("PORT", "9090"))

app = FastAPI(title="Agent Chat")

# ── 数据库初始化 ──────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            thread_id TEXT DEFAULT 'general',
            reply_to INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'sent',
            priority TEXT DEFAULT 'normal',
            metadata TEXT
        );
        CREATE TABLE IF NOT EXISTS participants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'guest',
            avatar TEXT,
            registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        );
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            metadata TEXT
        );
        CREATE TABLE IF NOT EXISTS thread_members (
            thread_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            invited_by TEXT,
            status TEXT DEFAULT 'joined',
            PRIMARY KEY (thread_id, agent_id)
        );
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            callback_url TEXT,
            status TEXT DEFAULT 'online',
            registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        );
    """)
    # Add priority column to existing messages table if missing
    try:
        cur.execute("ALTER TABLE messages ADD COLUMN priority TEXT DEFAULT 'normal'")
    except sqlite3.OperationalError:
        pass  # column already exists
    # 注册默认参与者
    defaults = [
        ("金金", "金金", "commander"),
        ("Pumpkin", "Pumpkin", "worker"),
        ("胖胖金", "胖胖金", "owner"),
    ]
    for pid, name, role in defaults:
        cur.execute(
            "INSERT OR IGNORE INTO participants (id, name, role) VALUES (?, ?, ?)",
            (pid, name, role),
        )
    # 创建默认话题
    cur.execute(
        "INSERT OR IGNORE INTO threads (id, name, created_by) VALUES (?, ?, ?)",
        ("general", "综合讨论", "system"),
    )
    conn.commit()
    conn.close()

# ── 请求模型 ─────────────────────────────────────────────────────────────

class MessageCreate(BaseModel):
    sender: str
    content: str
    thread_id: str = "general"
    reply_to: Optional[int] = None
    priority: str = "normal"

class ThreadCreate(BaseModel):
    id: str
    name: str
    created_by: str = "system"
    auto_notify: bool = True  # 是否自动通知已注册Agent

class ParticipantCreate(BaseModel):
    id: str
    name: str
    role: str = "guest"

class AgentRegister(BaseModel):
    id: str
    name: str
    callback_url: Optional[str] = None

class ThreadInvite(BaseModel):
    participant_id: str

class WakeRequest(BaseModel):
    thread_id: Optional[str] = None  # 目标话题，None=当前所有活跃话题
    sender: str = "胖胖金"  # 谁在催

# ── 消息端点

@app.post("/messages")
def create_message(msg: MessageCreate):
    conn = get_db()
    cur = conn.cursor()
    # 检查话题是否已归档
    thread = cur.execute("SELECT status FROM threads WHERE id = ?", (msg.thread_id,)).fetchone()
    if thread and thread["status"] == "archived":
        conn.close()
        raise HTTPException(403, "该话题已归档，无法发送消息。请先恢复话题。")
    # Auto-determine priority: 胖胖金's messages are urgent by default
    priority = msg.priority
    if msg.sender == "胖胖金" and priority == "normal":
        priority = "urgent"
    cur.execute(
        "INSERT INTO messages (sender, content, thread_id, reply_to, timestamp, priority) VALUES (?, ?, ?, ?, ?, ?)",
        (msg.sender, msg.content, msg.thread_id, msg.reply_to, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), priority)
    )
    conn.commit()
    row = cur.execute(
        "SELECT id, sender, content, thread_id, reply_to, timestamp, status, priority FROM messages WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    conn.close()
    
    # 写入通知文件 + 调用 OpenClaw hooks
    if msg.sender != "Pumpkin":
        try:
            notify_file = os.path.join(_BASE_DIR, "pumpkin_notifications.jsonl")
            with open(notify_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "id": row["id"],
                    "sender": row["sender"],
                    "content": row["content"],
                    "thread_id": row["thread_id"],
                    "timestamp": row["timestamp"],
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # 调用 OpenClaw hooks 唤醒
        try:
            hook_data = json.dumps({
                "text": f"[Agent Chat] {msg.sender}: {msg.content[:100]}",
            }, ensure_ascii=False).encode("utf-8")
            hook_req = urllib.request.Request(
                "http://localhost:18789/hooks/wake",
                data=hook_data,
                headers={
                    "Authorization": "Bearer agent-chat-hook-2026",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            urllib.request.urlopen(hook_req, timeout=3)
        except Exception:
            pass
    
    return dict(row)

@app.get("/messages")
def get_messages(
    thread_id: Optional[str] = None,
    sender: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    after_id: int = Query(0, ge=0),
):
    conn = get_db()
    cur = conn.cursor()
    where, params = [], []
    if after_id > 0:
        where.append("id > ?")
        params.append(after_id)
    if thread_id:
        where.append("thread_id = ?")
        params.append(thread_id)
    if sender:
        where.append("sender = ?")
        params.append(sender)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = cur.execute(f"SELECT COUNT(*) FROM messages{clause}", params).fetchone()[0]
    rows = cur.execute(
        f"SELECT id, sender, content, thread_id, reply_to, timestamp, status, priority FROM messages{clause} ORDER BY id ASC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return {"messages": [dict(r) for r in rows], "total": total}

@app.get("/messages/unread/{participant_id}")
def get_unread(participant_id: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, sender, content, thread_id, reply_to, timestamp, status, priority FROM messages WHERE status != 'read' AND sender != ? ORDER BY id ASC",
        (participant_id,),
    ).fetchall()
    conn.close()
    return {"messages": [dict(r) for r in rows]}

@app.put("/messages/{msg_id}/read")
def mark_read(msg_id: int):
    conn = get_db()
    conn.execute("UPDATE messages SET status = 'read' WHERE id = ?", (msg_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/messages/{msg_id}")
def delete_message(msg_id: int, sender: str = Query(...)):
    """撤回消息 — 只有发送者本人可以撤回"""
    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT id, sender, thread_id FROM messages WHERE id = ?", (msg_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "消息不存在")
    if row["sender"] != sender:
        conn.close()
        raise HTTPException(403, "只能撤回自己发送的消息")
    thread_id = row["thread_id"]
    cur.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    # 同时清除引用该消息的reply_to
    cur.execute("UPDATE messages SET reply_to = NULL WHERE reply_to = ?", (msg_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "msg_id": msg_id}

# ── Wake端点（催一下）─────────────────────────────────────────────────────
@app.post("/hooks/wake")
def wake_agents(wake: WakeRequest):
    """催一下Agent — 发送系统消息到目标话题 + 推送到已注册Agent的callback_url"""
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 确定目标话题
    if wake.thread_id:
        target_threads = [wake.thread_id]
    else:
        rows = cur.execute("SELECT id FROM threads WHERE status = 'active'").fetchall()
        target_threads = [r["id"] for r in rows]
    
    if not target_threads:
        conn.close()
        return {"ok": False, "message": "没有活跃话题"}
    
    # 向每个目标话题发送催促系统消息
    wake_msg = f"⚡ {wake.sender}催了一下，请尽快查看消息！"
    threads_notified = []
    for tid in target_threads:
        cur.execute(
            "INSERT INTO messages (sender, content, thread_id, timestamp, priority) VALUES (?, ?, ?, ?, 'urgent')",
            ("system", wake_msg, tid, now),
        )
        threads_notified.append(tid)
    
    conn.commit()
    
    # 尝试推送到已注册Agent的callback_url
    agents = cur.execute("SELECT id, name, callback_url FROM agents WHERE status = 'online'").fetchall()
    pushed_agents = []
    for agent in agents:
        if agent["callback_url"]:
            try:
                req = urllib.request.Request(
                    agent["callback_url"],
                    data=json.dumps({
                        "event": "wake",
                        "sender": wake.sender,
                        "threads": threads_notified,
                        "message": wake_msg,
                        "timestamp": now,
                    }, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=3)
                pushed_agents.append(agent["name"])
            except Exception:
                pass  # 推送失败不影响主流程
    
    conn.close()
    return {
        "ok": True,
        "timestamp": now,
        "threads_notified": threads_notified,
        "pushed_agents": pushed_agents,
        "message": f"已催促 {len(threads_notified)} 个话题" + (f"，已推送给 {', '.join(pushed_agents)}" if pushed_agents else ""),
    }

# ── 话题端点

@app.get("/threads")
def get_threads(status: Optional[str] = None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT id, name, created_by, created_at, status FROM threads WHERE status = ? ORDER BY created_at ASC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT id, name, created_by, created_at, status FROM threads ORDER BY created_at ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/threads")
def create_thread(t: ThreadCreate):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO threads (id, name, created_by) VALUES (?, ?, ?)",
            (t.id, t.name, t.created_by),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "话题已存在")

    # 自动通知已注册Agent + 邀请加入话题
    notified_agents = []
    if t.auto_notify:
        agents = conn.execute("SELECT id, name, callback_url FROM agents WHERE status = 'online'").fetchall()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for agent in agents:
            agent_id = agent["id"]
            # 自动邀请加入话题
            try:
                conn.execute(
                    "INSERT INTO thread_members (thread_id, agent_id, invited_by, status) VALUES (?, ?, ?, 'invited')",
                    (t.id, agent_id, t.created_by),
                )
            except sqlite3.IntegrityError:
                pass
            # 发系统消息通知
            notify_content = f"📢 新话题「{t.name}」已创建（by {t.created_by}），请关注。"
            conn.execute(
                "INSERT INTO messages (sender, content, thread_id, timestamp, priority) VALUES (?, ?, ?, ?, 'normal')",
                ("system", notify_content, t.id, now),
            )
            notified_agents.append(agent["name"])
            # 如果有callback_url，尝试推送通知
            if agent["callback_url"]:
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        agent["callback_url"],
                        data=json.dumps({
                            "event": "thread_created",
                            "thread_id": t.id,
                            "thread_name": t.name,
                            "created_by": t.created_by,
                        }, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=5)
                except Exception:
                    pass  # callback推送失败不影响主流程
        conn.commit()
    conn.close()
    return {
        "id": t.id,
        "name": t.name,
        "created_by": t.created_by,
        "notified_agents": notified_agents,
    }

# ── 话题成员端点 ─────────────────────────────────────────────────────────

@app.post("/threads/{thread_id}/invite")
def invite_to_thread(thread_id: str, invite: ThreadInvite):
    """邀请Agent加入话题"""
    conn = get_db()
    # Verify thread exists
    thread = conn.execute("SELECT id FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        conn.close()
        raise HTTPException(404, "话题不存在")
    # Verify participant exists
    p = conn.execute("SELECT id FROM participants WHERE id = ?", (invite.participant_id,)).fetchone()
    if not p:
        conn.close()
        raise HTTPException(404, f"参与者 {invite.participant_id} 不存在")
    try:
        conn.execute(
            "INSERT INTO thread_members (thread_id, agent_id, invited_by, status) VALUES (?, ?, ?, 'invited')",
            (thread_id, invite.participant_id, "system"),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Already a member/invited - update status
        conn.execute(
            "UPDATE thread_members SET status = 'invited' WHERE thread_id = ? AND agent_id = ?",
            (thread_id, invite.participant_id),
        )
        conn.commit()
    conn.close()
    return {"thread_id": thread_id, "agent_id": invite.participant_id, "status": "invited"}

@app.post("/threads/{thread_id}/join")
def join_thread(thread_id: str, invite: ThreadInvite):
    """Agent主动加入话题"""
    conn = get_db()
    thread = conn.execute("SELECT id FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        conn.close()
        raise HTTPException(404, "话题不存在")
    try:
        conn.execute(
            "INSERT INTO thread_members (thread_id, agent_id, status) VALUES (?, ?, 'joined')",
            (thread_id, invite.participant_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Already exists - update to joined
        conn.execute(
            "UPDATE thread_members SET status = 'joined' WHERE thread_id = ? AND agent_id = ?",
            (thread_id, invite.participant_id),
        )
        conn.commit()
    conn.close()
    return {"thread_id": thread_id, "agent_id": invite.participant_id, "status": "joined"}

@app.post("/threads/{thread_id}/leave")
def leave_thread(thread_id: str, invite: ThreadInvite):
    """Agent退出话题"""
    conn = get_db()
    result = conn.execute(
        "DELETE FROM thread_members WHERE thread_id = ? AND agent_id = ?",
        (thread_id, invite.participant_id),
    )
    conn.commit()
    if result.rowcount == 0:
        conn.close()
        raise HTTPException(404, f"{invite.participant_id} 不在话题 {thread_id} 中")
    conn.close()
    return {"thread_id": thread_id, "agent_id": invite.participant_id, "status": "left"}

@app.get("/threads/{thread_id}/participants")
def get_thread_participants(thread_id: str):
    """获取话题参与者列表"""
    conn = get_db()
    thread = conn.execute("SELECT id, name FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        conn.close()
        raise HTTPException(404, "话题不存在")
    rows = conn.execute(
        """SELECT tm.agent_id, tm.status, tm.invited_by, tm.joined_at,
                  p.name, p.role
           FROM thread_members tm
           LEFT JOIN participants p ON p.id = tm.agent_id
           WHERE tm.thread_id = ?
           ORDER BY tm.joined_at ASC""",
        (thread_id,),
    ).fetchall()
    conn.close()
    return {
        "thread_id": thread_id,
        "thread_name": thread["name"],
        "members": [dict(r) for r in rows],
        "count": len(rows),
    }

# ── Agent注册端点 ────────────────────────────────────────────────────────

@app.post("/agents/register")
def register_agent(agent: AgentRegister):
    """注册Agent（UPSERT语义：已存在则更新callback_url和last_seen）
    上线时自动拉取未读消息"""
    conn = get_db()
    existing = conn.execute("SELECT id FROM agents WHERE id = ?", (agent.id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        conn.execute(
            "UPDATE agents SET name = ?, callback_url = ?, last_seen = ?, status = 'online' WHERE id = ?",
            (agent.name, agent.callback_url, now, agent.id),
        )
        conn.commit()
        action = "updated"
    else:
        conn.execute(
            "INSERT INTO agents (id, name, callback_url, registered_at, last_seen) VALUES (?, ?, ?, ?, ?)",
            (agent.id, agent.name, agent.callback_url, now, now),
        )
        conn.commit()
        action = "registered"

    # Agent上线时拉取未读消息
    unread_rows = conn.execute(
        "SELECT id, sender, content, thread_id, reply_to, timestamp, priority FROM messages WHERE status != 'read' AND sender != ? ORDER BY id ASC",
        (agent.id,),
    ).fetchall()
    unread_messages = [dict(r) for r in unread_rows]

    # 同时拉取该Agent被邀请但未加入的话题
    pending_invites = conn.execute(
        "SELECT tm.thread_id, t.name as thread_name, tm.invited_by, tm.joined_at FROM thread_members tm JOIN threads t ON t.id = tm.thread_id WHERE tm.agent_id = ? AND tm.status = 'invited'",
        (agent.id,),
    ).fetchall()
    invites = [dict(r) for r in pending_invites]

    conn.close()
    return {
        "id": agent.id,
        "name": agent.name,
        "callback_url": agent.callback_url,
        "action": action,
        "unread_count": len(unread_messages),
        "unread_messages": unread_messages,
        "pending_invites": invites,
    }

@app.get("/agents")
def get_agents():
    """获取所有已注册Agent"""
    conn = get_db()
    rows = conn.execute("SELECT id, name, callback_url, status, registered_at, last_seen FROM agents ORDER BY registered_at ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── 参与者端点 ───────────────────────────────────────────────────────────

@app.get("/participants")
def get_participants():
    conn = get_db()
    rows = conn.execute("SELECT id, name, role, avatar, registered_at FROM participants").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/participants")
def create_participant(p: ParticipantCreate):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO participants (id, name, role) VALUES (?, ?, ?)",
            (p.id, p.name, p.role),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "参与者已存在")
    conn.close()
    return {"id": p.id, "name": p.name, "role": p.role}

# ── 归档端点 ─────────────────────────────────────────────────────────────

@app.post("/threads/{thread_id}/archive")
def archive_thread(thread_id: str):
    conn = get_db()
    thread = conn.execute("SELECT id, name FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        conn.close()
        raise HTTPException(404, "话题不存在")
    thread_name = thread["name"]
    rows = conn.execute(
        "SELECT m.id, m.sender, m.content, m.reply_to, m.timestamp FROM messages m WHERE m.thread_id = ? ORDER BY m.id ASC",
        (thread_id,),
    ).fetchall()
    conn.close()

    # Build reply_to lookup map
    reply_map = {}
    if rows:
        reply_ids = [r["reply_to"] for r in rows if r["reply_to"]]
        if reply_ids:
            conn2 = get_db()
            placeholders = ",".join("?" * len(reply_ids))
            for r2 in conn2.execute(f"SELECT id, sender FROM messages WHERE id IN ({placeholders})", reply_ids).fetchall():
                reply_map[r2["id"]] = r2["sender"]
            conn2.close()

    lines = [
        f"# 对话记录：{thread_name}",
        f"日期：{datetime.now().strftime('%Y-%m-%d')}",
    ]
    participants = set()
    for r in rows:
        participants.add(r["sender"])
    lines.append(f"参与者：{', '.join(sorted(participants))}")
    lines.append("\n---\n")
    for r in rows:
        time_str = r["timestamp"][:16] if r["timestamp"] else ""
        reply_info = ""
        if r["reply_to"] and r["reply_to"] in reply_map:
            reply_info = f" → {reply_map[r['reply_to']]}"
        lines.append(f"**[{time_str}] {r['sender']}{reply_info}**\n{r['content']}\n")
    lines.append(f"\n---\n归档时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    fname = f"{thread_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    fpath = os.path.join(ARCHIVE_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # 标记话题为已归档（不删数据）
    conn2 = get_db()
    conn2.execute("UPDATE threads SET status = 'archived' WHERE id = ?", (thread_id,))
    conn2.commit()
    conn2.close()

    return {"file": fname, "path": fpath, "message_count": len(rows)}

@app.post("/threads/{thread_id}/restore")
def restore_thread(thread_id: str):
    """恢复已归档的话题"""
    conn = get_db()
    thread = conn.execute("SELECT id, status FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        conn.close()
        raise HTTPException(404, "话题不存在")
    if thread["status"] != "archived":
        conn.close()
        raise HTTPException(400, "话题未归档，无需恢复")
    conn.execute("UPDATE threads SET status = 'active' WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return {"thread_id": thread_id, "status": "active", "ok": True}

# ── SSE实时推送端点

@app.get("/messages/stream")
async def message_stream(thread_id: str = "all", last_id: int = 0):
    async def event_generator():
        current_last_id = last_id
        while True:
            conn = get_db()
            cursor = conn.cursor()
            if thread_id == "all":
                cursor.execute(
                    "SELECT id, sender, content, thread_id, timestamp, reply_to, priority FROM messages WHERE id > ? ORDER BY id",
                    (current_last_id,)
                )
            else:
                cursor.execute(
                    "SELECT id, sender, content, thread_id, timestamp, reply_to, priority FROM messages WHERE id > ? AND thread_id = ? ORDER BY id",
                    (current_last_id, thread_id)
                )
            messages = cursor.fetchall()
            conn.close()

            if messages:
                for msg in messages:
                    current_last_id = msg[0]
                    data = json.dumps({
                        "id": msg[0],
                        "sender": msg[1],
                        "content": msg[2],
                        "thread_id": msg[3],
                        "timestamp": msg[4],
                        "reply_to": msg[5],
                        "priority": msg[6]
                    }, ensure_ascii=False)
                    yield f"data: {data}\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# ── 静态文件 & 根路由 ────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "viewer.html"))

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")), name="static")

# ── 启动 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
