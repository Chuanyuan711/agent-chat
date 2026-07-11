#!/bin/bash
# Agent Chat — 停止轮询器
if pkill -f "python.*poller.py" 2>/dev/null; then
    echo "Poller stopped"
else
    echo "Poller not running"
fi
