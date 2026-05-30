# 运行环境信息清单

正式开发代码前，请补充或确认以下信息。确认后可以避免代码写完后因为 Python 版本、依赖、AI 接口或微信 SDK 引用方式不同导致无法运行。

## 基础环境

- 操作系统：CentOS Linux 7 (Core)
- Python 版本：Python 3.6.8
- 是否使用虚拟环境：
- 运行入口：直接运行 `python3 main.py`，不需要 CLI 子命令。
- 是否允许安装第三方 Python 包：

AI HTTP 客户端策略：

- 不安装官方 `openai` SDK。
- 不安装 `requests`。
- 不安装 `httpx`。
- 使用 Python 标准库 `urllib.request` 直接请求 OpenAI 兼容接口。

监听策略：

- 不创建 Flask。
- 不使用 Webhook。
- 使用 ILinkAI Weixin SDK 的 `MessageMonitorService.start()` 长轮询监听。
- `main.py` 是常驻阻塞进程。

当前兼容策略：

- 不升级系统 Python。
- Bot 代码按 Python 3.6.8 编写。
- 现有微信 SDK 的 `setup.py` 已调整为 `Python >= 3.6`。
- Python 3.6 需要 `dataclasses` 兼容包。

## ILinkAI Weixin SDK

- SDK 路径固定为 `vendor`：是
- 是否需要执行 `pip install -e ../ILinkAI.Weixin-master/Python`：不需要
- 是否已经可以成功运行 SDK 示例 `python main.py login`：
- 是否已有已登录账号：
- 是否需要 Bot 自动执行扫码登录：
- 是否需要多微信账号同时运行：

## AI 接口

- AI 服务商：
- API Base URL：
- API Key 获取方式：环境变量、配置文件、手动输入：
- 模型名称：
- 是否 OpenAI Chat Completions 兼容：
- 是否支持 `stream: true`：
- 单次最大输出 token：
- 温度 temperature：
- 系统提示词：

接口调用方式：

- 非流式：HTTP POST JSON。
- 流式：HTTP POST JSON + SSE `data:` 行解析。
- 响应解析不依赖任何第三方 SDK。

## 流式输出策略

请选择一种默认策略：

- 策略 A：流式内容只在控制台实时显示，微信最终发送完整回复。
- 策略 B：流式内容按句子或固定长度分段发送到微信。
- 策略 C：非流式用于微信回复，流式仅作为调试模式。

需要确认：

- 微信侧频繁分段发送是否会被限制：
- 是否希望用户看到“正在输入”状态：
- 流式分段最小间隔秒数：

## 记忆存储

推荐初版使用 SQLite。

- 记忆存储类型：SQLite / JSONL / Redis / 其他：
- 数据保存目录：
- 是否需要长期保存完整聊天记录：
- 每个会话最多保留多少条历史消息：
- 是否需要自动摘要旧消息：
- 是否需要清理命令，例如 `/clear`：
- 是否需要导出聊天记录：

## 会话划分

需要确认记忆按什么维度隔离：

- 私聊：按发送者 `ctx.from_`。
- 群聊：按 `group_id`。
- 多账号：按 `account_id + from/group`。

推荐初版：

```text
session_id = account_id + ':' + group_id_or_from_user
```

## 回复规则

- 是否所有消息都自动回复：
- 群聊是否只在被 @ 或关键词触发时回复：
- 是否忽略空文本、图片、文件、语音等非文本消息：
- 语音消息是否使用微信返回的转文字结果：
- 是否允许回复图片、文件等媒体：
- 是否需要黑名单或白名单：

## 配置安全

- API Key 是否可以写入本地配置文件：
- 是否必须从环境变量读取 API Key：
- 是否需要 `.gitignore` 忽略配置和数据：
