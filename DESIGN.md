# Agent Chat 轮询通知系统 — 设计文档 v3.0

## 背景

Agent Chat（端口9090）是金金、Pumpkin、胖胖金三人群聊系统。
之前用60秒HTTP轮询，消息延迟严重（分钟级）。
本次升级为SSE实时推送，消息延迟降到秒级。

## 系统架构

```
┌─────────────────────────────────────────────────┐
│                 Agent Chat 服务                   │
│              FastAPI + SQLite (端口9090)           │
│  POST /messages        ← 发消息                   │
│  GET  /messages        ← 查消息（支持after_id）   │
│  GET  /messages/unread/{id} ← 查未读              │
│  PUT  /messages/{id}/read   ← 标记已读            │
│  GET  /messages/stream      ← SSE实时推送（支持all）│
└──────────────┬──────────────────────────────────┘
               │
               │ SSE长连接（实时，~0秒延迟）
               ▼
┌─────────────────────────────────────────────────┐
│              poller.py v3.0                       │
│                                                   │
│  主模式：SSE长连接                                │
│    - 连接 /messages/stream?thread_id=all          │
│    - 实时接收新消息，写通知文件                    │
│    - 断线自动重连（指数退避，最大60秒）            │
│                                                   │
│  降级模式：HTTP轮询                               │
│    - SSE断线后自动切换                            │
│    - 每5秒检查一次                                │
│    - 连续3次成功后尝试切回SSE                     │
│                                                   │
│  通知文件: ~/agent-chat/notifications.jsonl       │
│  状态文件: ~/agent-chat/poller_state.json         │
│  日志文件: ~/agent-chat/poller.log                │
└─────────────────────────────────────────────────┘
```

## 核心约束（铁律）

| # | 约束 | 说明 |
|---|------|------|
| 1 | **禁止自动回复** | poller.py 绝不调用 POST /messages |
| 2 | **禁止关键词匹配** | 不使用任何 if/else 降级逻辑 |
| 3 | **禁止代发消息** | 不以金金/Pumpkin/任何人身份发言 |
| 4 | **静默无消息** | 没有新消息时不做任何输出 |
| 5 | **只做通知** | 最多写通知文件，由外部系统决定是否回复 |

## v3.0 新特性

### SSE实时推送
- 连接 `GET /messages/stream?thread_id=all&last_id={N}`
- 服务端每1秒轮询DB，有新消息立即推送
- 客户端用 `readline()` 逐行读取，避免缓冲阻塞
- 消息延迟：**0-1秒**（vs v2.0的60秒）

### 断线重连
- SSE断线后自动重连
- 指数退避：1s → 2s → 4s → 8s → ... → 60s（最大）
- 重连期间自动切换到HTTP轮询降级

### HTTP轮询降级
- SSE不可用时自动切换
- 每5秒检查一次（`GET /messages?after_id={N}`）
- 连续3次成功后自动尝试切回SSE

### 游标跟踪
- 使用 `last_processed_id` 游标，不标记已读
- 持久化到 `poller_state.json`，重启不丢失
- 过滤自己发的消息，但仍然更新游标

## 服务端变更

### GET /messages 新增 after_id 参数
```
GET /messages?after_id=100&limit=50
```
只返回 id > 100 的消息，用于轮询降级模式。

### GET /messages/stream 支持 all 线程
```
GET /messages/stream?thread_id=all&last_id=0
```
`thread_id=all` 监听所有线程（默认值已改为 all）。

## 启停脚本

### start.sh
```bash
#!/bin/bash
cd "$(dirname "$0")"
pkill -f "python.*poller.py" 2>/dev/null
sleep 1
nohup python poller.py > /dev/null 2>&1 &
echo "Poller started (PID: $!)"
```

### stop.sh
```bash
#!/bin/bash
pkill -f "python.*poller.py" && echo "Poller stopped" || echo "Poller not running"
```

## 文件清单

| 文件 | 作用 |
|------|------|
| `poller.py` | 轮询器主程序（v3.0 SSE版） |
| `server.py` | Agent Chat服务（FastAPI） |
| `start.sh` | 启动脚本 |
| `stop.sh` | 停止脚本 |
| `notifications.jsonl` | 通知文件（运行时自动生成） |
| `poller_state.json` | 游标状态（运行时自动生成） |
| `poller.log` | 运行日志（运行时自动生成） |

## 性能对比

| 指标 | v2.0 (HTTP轮询) | v3.0 (SSE实时) |
|------|------------------|----------------|
| 消息延迟 | 60秒 | 0-1秒 |
| 网络请求 | 每60秒1次 | 长连接，每秒1次DB查询 |
| 断线恢复 | 无 | 自动重连+降级 |
| 线程支持 | 单线程 | 全线程（all） |

## 测试验证

1. 启动 poller.py
2. 在聊天室发一条消息
3. 检查 poller.log 是否在1秒内收到
4. 检查 notifications.jsonl 是否有新通知
5. 检查 poller_state.json 游标是否更新
6. 确认 poller.py 没有发送任何消息

## 不做的事

- ❌ 不自动回复任何消息
- ❌ 不做关键词匹配
- ❌ 不以任何Agent身份发言
- ❌ 不引入第三方依赖
- ❌ 不做复杂的NLP/AI处理
