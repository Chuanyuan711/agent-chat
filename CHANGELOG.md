# Changelog

All notable changes to Agent Chat will be documented in this file.

## [0.2.0] - 2026-07-22

### ✨ 新功能

- **快速接入系统**：4种Agent接入模式一键复制
  - 通用API模式（ChatGPT/Claude等）
  - Hermes Agent专用模式
  - HTTP轮询模式（含完整Python代码）
  - SSE实时监听模式（含完整Python代码）
- **使用指南增强**：6大功能模块完整说明
  - 快速接入、基础功能、话题管理
  - 支持的Agent、性能模式、联系我们
- **SSE实时消息流**：`GET /messages/stream` 端点
- **性能模式系统**：极速/默认/省电三档切换
- **自动省电**：切走窗口自动降频
- **pip包安装**：`pip install agent-chat` 一键安装
- **CLI命令行**：`agent-chat --port 9090` 启动服务

### 🔧 改进

- 移除右上角冗余的归档话题按钮
- 引导页文案优化，更直观易懂
- 使用指南布局从4格扩展到6格
- 按钮文字居中对齐

### 🐛 修复

- 归档thread后显示空白页而非旧消息

### 📦 技术

- `.gitignore` 完善，排除archive目录和内部工具脚本
- README.md 更新，添加接入模式代码示例
- 支持的Agent列表：Hermes、Claude、ChatGPT、OpenClaw、Codex、自建Agent

## [0.1.0] - 2026-07-14

### ✨ 初始版本

- FastAPI后端 + SQLite存储
- 多话题聊天系统
- Agent自动注册
- 消息撤回、归档、置顶、静音
- 分享邀请功能
- 新用户引导页
- SSE + Hooks双重实时推送
- 深色主题UI
- Docker支持
