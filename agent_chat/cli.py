"""Agent Chat CLI - 命令行入口"""

import argparse
import sys
import os
import webbrowser
import threading
import time


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        prog="agent-chat",
        description="🤖 Agent Chat - 让你的AI团队，一个聊天室。",
        epilog="示例: agent-chat --port 9090 --open"
    )
    
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=9090,
        help="服务端口 (默认: 9090)"
    )
    
    parser.add_argument(
        "-H", "--host",
        type=str,
        default="0.0.0.0",
        help="监听地址 (默认: 0.0.0.0)"
    )
    
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="不自动打开浏览器"
    )
    
    parser.add_argument(
        "-V", "--version",
        action="version",
        version="agent-chat 0.2.0"
    )
    
    args = parser.parse_args()
    
    # 设置环境变量
    os.environ["PORT"] = str(args.port)
    
    # 导入服务器模块
    try:
        from agent_chat.server import app
        import uvicorn
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请运行: pip install agent-chat")
        sys.exit(1)
    
    # 自动打开浏览器
    if not args.no_open:
        def open_browser():
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{args.port}")
        
        threading.Thread(target=open_browser, daemon=True).start()
    
    # 启动服务器
    print(f"""
🤖 Agent Chat v0.2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  🌐 访问地址: http://localhost:{args.port}
  📚 API文档:  http://localhost:{args.port}/docs
  🔗 GitHub:   https://github.com/Chuanyuan711/agent-chat

  按 Ctrl+C 停止服务

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
    
    try:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 Agent Chat 已停止")
        sys.exit(0)


if __name__ == "__main__":
    main()
