"""Agent Chat Server - FastAPI后端"""

import os
import sqlite3
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import json

# 获取当前目录
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_BASE_DIR, "static")

# 创建FastAPI应用
app = FastAPI(
    title="Agent Chat",
    description="让你的AI团队，一个聊天室。",
    version="0.2.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据库配置
DB_PATH = os.getenv("DB_PATH", os.path.join(os.getcwd(), "chat.db"))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_by TEXT,
            is_pinned BOOLEAN DEFAULT 0,
            is_muted BOOLEAN DEFAULT 0,
            is_archived BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            thread_id TEXT DEFAULT 'default',
            reply_to INTEGER,
            is_recalled BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (thread_id) REFERENCES threads(id)
        );
        
        CREATE TABLE IF NOT EXISTS read_status (
            agent_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (agent_id, message_id)
        );
        
        INSERT OR IGNORE INTO threads (id, name, created_by) 
        VALUES ('default', '默认话题', 'system');
    """)
    conn.commit()
    conn.close()

# 启动时初始化数据库
@app.on_event("startup")
async def startup():
    init_db()

# 数据模型
class AgentRegister(BaseModel):
    name: str

class MessageCreate(BaseModel):
    sender: str
    content: str
    thread_id: str = "default"
    reply_to: Optional[int] = None

class ThreadCreate(BaseModel):
    id: str
    name: str
    created_by: str

# API路由
@app.get("/")
async def root():
    """首页"""
    index_path = os.path.join(_STATIC_DIR, "viewer.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Agent Chat API", "docs": "/docs"}

@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "version": "0.2.0"}

@app.post("/agents/register")
async def register_agent(agent: AgentRegister):
    """注册Agent"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO agents (name) VALUES (?)", (agent.name,))
        conn.commit()
        return {"success": True, "agent_id": cursor.lastrowid, "name": agent.name}
    except sqlite3.IntegrityError:
        cursor.execute("SELECT id FROM agents WHERE name = ?", (agent.name,))
        row = cursor.fetchone()
        return {"success": True, "agent_id": row["id"], "name": agent.name, "existing": True}
    finally:
        conn.close()

@app.get("/threads")
async def get_threads():
    """获取话题列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.*, COUNT(m.id) as message_count 
        FROM threads t 
        LEFT JOIN messages m ON t.id = m.thread_id AND m.is_recalled = 0
        WHERE t.is_archived = 0
        GROUP BY t.id 
        ORDER BY t.is_pinned DESC, t.created_at DESC
    """)
    threads = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return threads

@app.post("/threads")
async def create_thread(thread: ThreadCreate):
    """创建话题"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO threads (id, name, created_by) VALUES (?, ?, ?)",
            (thread.id, thread.name, thread.created_by)
        )
        conn.commit()
        return {"success": True}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="话题ID已存在")
    finally:
        conn.close()

@app.post("/messages")
async def send_message(message: MessageCreate):
    """发送消息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (sender, content, thread_id, reply_to) VALUES (?, ?, ?, ?)",
        (message.sender, message.content, message.thread_id, message.reply_to)
    )
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"success": True, "id": message_id}

@app.get("/messages/{thread_id}")
async def get_messages(thread_id: str, limit: int = Query(50, ge=1, le=200)):
    """获取消息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM messages 
        WHERE thread_id = ? AND is_recalled = 0
        ORDER BY created_at DESC LIMIT ?
    """, (thread_id, limit))
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return list(reversed(messages))

@app.get("/messages/unread/{agent_id}")
async def get_unread(agent_id: str):
    """获取未读消息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.* FROM messages m
        WHERE m.is_recalled = 0
        AND m.id NOT IN (
            SELECT message_id FROM read_status WHERE agent_id = ?
        )
        ORDER BY m.created_at ASC
    """, (agent_id,))
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return messages

@app.put("/messages/{message_id}/read")
async def mark_read(message_id: int, agent_id: str = Query(...)):
    """标记已读"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO read_status (agent_id, message_id) VALUES (?, ?)",
        (agent_id, message_id)
    )
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/messages/{message_id}")
async def recall_message(message_id: int):
    """撤回消息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE messages SET is_recalled = 1 WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/threads/{thread_id}/archive")
async def archive_thread(thread_id: str):
    """归档话题"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE threads SET is_archived = 1 WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/threads/{thread_id}/restore")
async def restore_thread(thread_id: str):
    """恢复话题"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE threads SET is_archived = 0 WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/threads/{thread_id}/pin")
async def pin_thread(thread_id: str):
    """置顶话题"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE threads SET is_pinned = NOT is_pinned WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/threads/{thread_id}/mute")
async def mute_thread(thread_id: str):
    """静音话题"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE threads SET is_muted = NOT is_muted WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/hooks/wake")
async def wake_hook():
    """唤醒钩子"""
    return {"success": True, "message": "已通知Agent检查"}

@app.get("/messages/stream")
async def message_stream(thread_id: str = "all", last_id: int = 0):
    """SSE消息流"""
    async def event_generator():
        while True:
            conn = get_db()
            cursor = conn.cursor()
            
            if thread_id == "all":
                cursor.execute("""
                    SELECT * FROM messages 
                    WHERE id > ? AND is_recalled = 0
                    ORDER BY id ASC
                """, (last_id,))
            else:
                cursor.execute("""
                    SELECT * FROM messages 
                    WHERE thread_id = ? AND id > ? AND is_recalled = 0
                    ORDER BY id ASC
                """, (thread_id, last_id))
            
            messages = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            for msg in messages:
                last_id = msg["id"]
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            
            await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

# 挂载静态文件
if os.path.exists(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
