#!/bin/bash
# Agent Chat — 启动轮询器
cd "$(dirname "$0")"

# 先杀旧进程
pkill -f "python.*poller.py" 2>/dev/null
sleep 1

# 启动新轮询器（后台）
nohup python poller.py > /dev/null 2>&1 &
PID=$!
echo "Poller started (PID: $PID)"
echo "日志: $(pwd)/poller.log"
echo "通知: $(pwd)/notifications.jsonl"
