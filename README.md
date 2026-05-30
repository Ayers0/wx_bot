# 微信 AI 记忆 Bot

一个基于 vendored ILinkAI Weixin Python SDK 的微信 AI 助手。项目通过微信长轮询监听消息，调用 OpenAI Chat Completions 兼容接口生成回复，并使用 SQLite 为私聊/群聊维护独立上下文记忆。

## 主要特性

- 微信扫码登录、消息监听、文本/图片回复。
- OpenAI 兼容接口，支持非流式与流式响应。
- 多模型配置与微信内命令切换、添加、修改、删除模型。
- 私聊/群聊按会话隔离记忆，支持手动清理上下文。
- SQLite 保存聊天记录、图片记录和长期摘要。
- 支持自动总结旧消息，压缩长期上下文并自动备份数据库。
- 支持微信图片识别：用户发图后转为 vision data URL 发给 AI。
- 支持 AI 图片发送：自动下载 AI 返回的图片 URL 并通过微信发送。
- 配置热重载、日志输出、运行数据自动清理。
- 兼容 Python 3.6.8 / CentOS 7，尽量仅使用标准库。

## 项目结构

```text
wx_bot/
├── main.py                    # Bot 唯一启动入口
├── login.py                   # 微信扫码登录工具
├── config.example.json        # 配置模板
├── config.json                # 本地配置，包含密钥，已忽略提交
├── bot_core/                  # 业务代码
│   ├── ai/client.py           # OpenAI 兼容 HTTP 客户端
│   ├── config/manager.py      # 配置加载、校验、热重载、模型管理
│   ├── media/                 # 图片下载、图片 data URL、目录清理
│   ├── memory/store.py        # SQLite 记忆存储
│   ├── session/manager.py     # 会话 ID、上下文组装、摘要压缩
│   └── wechat/bot.py          # 微信监听、命令处理、回复编排
├── vendor/ilinkai_weixin/     # 内置 ILinkAI Weixin Python SDK
├── data/                      # 运行数据：日志、数据库、图片、备份
├── scripts/                   # 辅助测试脚本
├── DESIGN.md                  # 设计说明
├── ENVIRONMENT.md             # 环境记录
└── PYTHON36_COMPAT.md         # Python 3.6 兼容说明
```

## 快速开始

### 1. 准备环境

推荐 Python 3.6.8；在 Python 3.6 下运行 vendored SDK 需要安装兼容包：

```bash
python3 -m pip install dataclasses
```

项目已内置微信 SDK 到 `vendor/ilinkai_weixin`，无需额外安装原 SDK。

### 2. 首次微信登录

在项目根目录执行：

```bash
python3 login.py
```

按终端提示打开二维码链接并使用微信扫码。登录成功后账号信息会保存到 `~/.ilinkai`。如果 `wechat.account_id` 为空，Bot 默认使用第一个已登录账号。

### 3. 创建配置

```bash
cp config.example.json config.json
```

至少需要修改以下配置：

```json
{
  "ai": {
    "active_model": "default",
    "models": {
      "default": {
        "chat_completions_url": "https://api.example.com/v1/chat/completions",
        "api_key": "",
        "api_key_env": "OPENAI_COMPAT_API_KEY",
        "model": "your-model-name",
        "supports_vision": false
      }
    }
  }
}
```

说明：

- `wechat.sdk_path` 默认保持为 `vendor`。
- `ai.active_model` 必须是 `ai.models` 中已存在的模型名称。
- 推荐优先使用 `api_key_env` 从环境变量读取密钥，避免把 API Key 明文写入配置。
- `config.example.json` 不包含真实服务地址、模型名或密钥；请复制后在本地 `config.json` 中填写。
- `config.json` 可能包含密钥和服务器配置，不要提交到代码仓库。

### 4. 启动 Bot

```bash
python3 main.py
```

或显式指定配置：

```bash
python3 main.py --config config.json
```

后台运行示例：

```bash
nohup python3 main.py --config config.json > bot.out 2>&1 &
```

## 常用微信命令

| 命令 | 说明 |
| --- | --- |
| `/菜单` | 查看命令菜单和使用说明 |
| `/clear`、`/清理`、`清空记忆` | 清空当前会话的消息、图片记录和历史摘要 |
| `/模型`、`/model` | 查看当前模型；带模型名时切换全局模型 |
| `/模型列表`、`/list models` | 查看所有模型配置详情 |
| `/添加模型`、`/add model` | 添加或更新模型，末尾可加 `--activate` 立即切换 |
| `/修改模型`、`/update model` | 修改模型字段，支持 `key=value` 或 JSON |
| `/删除模型`、`/delete model` | 删除非当前使用模型 |
| `/上下文状态`、`/context status` | 查看当前会话消息数和摘要状态 |
| `/总结上下文` | 手动总结并压缩当前会话旧消息 |

示例：

```text
/模型 your-model-profile
/添加模型 demo https://api.example.com/v1/chat/completions your-model sk-xxx --activate
/添加模型 demo https://api.example.com/v1/chat/completions your-model api_key_env=OPENAI_COMPAT_API_KEY --activate
/修改模型 demo model=your-model-v2 max_tokens=2048
/删除模型 demo
/添加模型 {"name":"demo","chat_completions_url":"https://api.example.com/v1/chat/completions","model":"your-model","api_key_env":"OPENAI_COMPAT_API_KEY","activate":true}
```

> 安全建议：微信里添加模型时如果必须输入 `api_key`，该消息本身可能被聊天记录、日志或截图保存。更推荐先在服务器设置环境变量，再通过 `api_key_env=环境变量名` 引用。

## 明文默认项与服务器配置检查

本项目已尽量移除模板中的真实服务地址、模型名和密钥。当前仍需要关注以下内容：

- `config.json`：本地运行配置，可能包含真实 `chat_completions_url`、`api_key`、`account_id` 等敏感信息，已被 `.gitignore` 忽略。
- `~/.ilinkai`：微信扫码登录后的 token 存储目录，不在项目内，但部署和备份时需要保护。
- `data/`：包含 SQLite 记忆库、日志、收发图片和数据库备份，可能含聊天内容或图片，已被 `.gitignore` 忽略。
- `.env.example`：环境变量示例文件，只能放占位符；真实 `.env`、`.env.*` 已被忽略。
- `config.example.json`：只保留 `https://api.example.com/v1/chat/completions`、`your-model-name`、`OPENAI_COMPAT_API_KEY` 等占位符。
- 文档和菜单示例：统一使用 `api.example.com`、`your-model`、`sk-xxx` 等占位符，不应出现真实服务器地址或真实 Key。
- 代码默认值：`bot_core/config/manager.py` 会拒绝明显占位符配置，避免复制模板后误启动。

建议在服务器上用环境变量保存密钥，例如：

```bash
export OPENAI_COMPAT_API_KEY="sk-..."
python3 main.py --config config.json
```

systemd 可使用 `Environment=` 或 `EnvironmentFile=` 注入环境变量。

运行前可检查项目内是否仍有疑似明文：

```powershell
Get-ChildItem -Recurse -File -Include *.py,*.json,*.md,*.env.example |
  Select-String -Pattern 'sk-[A-Za-z0-9_-]{12,}|xqz0|8222|api\.deepseek\.com|真实密钥' -CaseSensitive:$false
```

如果命中 `config.json` 且里面是真实密钥，请确认它没有被提交；如果命中文档或模板中的真实服务器地址，应改成占位符。



## 核心配置说明

### wechat

- `account_id`：微信账号 ID；为空时使用 `~/.ilinkai` 中第一个账号。
- `sdk_path`：SDK 路径，默认 `vendor`。
- `media_dir`：微信接收图片保存目录，默认 `data/media`。
- `media_max_age_seconds` / `media_max_files` / `media_cleanup_interval_seconds`：接收媒体清理策略。

### ai

- `active_model`：当前启用模型名称。
- `stream`：是否使用流式响应；默认最终仍只向微信发送完整回复。
- `timeout_seconds`、`max_tokens`、`temperature`：AI 请求参数。
- `system_prompt`：系统提示词。
- `ignore_reasoning_content`：过滤 `reasoning_content`，只把 `content` 回复到微信。
- `models`：多模型配置；单个模型通常包含 `chat_completions_url`、`api_key`/`api_key_env`、`model`、`supports_vision`。

### memory

- `database_path`：SQLite 数据库路径，默认 `data/memory.sqlite3`。
- `max_history_messages`：每次请求 AI 时携带的最近消息数量。
- `image_context_enabled`：是否把最近图片作为上下文发送给支持 vision 的模型。
- `auto_summary_enabled`：是否自动总结旧消息。
- `summary_trigger_messages`：消息数达到该阈值后触发摘要。
- `summary_keep_recent_messages`：摘要后保留的最近消息数量。
- `summary_backup_*`：摘要压缩前的数据库备份与清理策略。

### reply

- `ignore_empty_text`：忽略空文本消息；如果消息含支持的图片则仍会处理。
- `stream_send_to_wechat`：是否把流式片段分段发送到微信；默认关闭，避免刷屏。
- `send_typing`：处理消息时是否发送“正在输入”状态。
- `recognize_images`：是否识别用户发送的图片。
- `send_ai_images`：是否下载并发送 AI 回复中的图片链接。
- `generated_image_dir`：AI 图片下载保存目录，默认 `data/generated_images`。
- `generated_image_max_age_seconds` / `generated_image_max_files` / `generated_image_cleanup_interval_seconds`：AI 图片清理策略。

### hot_reload 与 logging

- `hot_reload.enabled`：开启后定时检测 `config.json` 变更并重载。
- 热重载适合修改模型、提示词、流式开关、回复策略、日志等级。
- 微信账号、SDK 路径、数据库路径变更后建议重启。
- `logging.file` 默认写入 `data/bot.log`。

## 图片能力

### 用户发图识别

当微信用户发送图片时，SDK 会把图片保存到 `wechat.media_dir`。Bot 会将本地图片转成 base64 data URL，并按 OpenAI vision 消息格式发送给支持视觉的模型。

要求：

- `reply.recognize_images=true`。
- 当前模型 `supports_vision=true`。
- 如果用户发图时带文字，文字会作为识别提示；否则使用 `reply.image_recognition_prompt`。

### AI 生成图发送

如果 AI 文本回复中包含类似以下图片 URL：

```text
https://api.example.com/v1/files/image?id=...
```

Bot 会携带 `Authorization: Bearer <api_key>` 下载图片，保存到 `reply.generated_image_dir`，再调用微信 SDK 发送图片消息。

## 记忆与摘要

- 会话 ID 由微信账号和聊天对象组成，私聊与群聊相互隔离。
- 普通对话会保存 user/assistant 消息。
- 图片上下文会保存用户图片和 AI 生成图片记录。
- 当历史消息过多时，可自动或手动生成长期摘要，并压缩旧消息。
- 执行 `/clear` 或 `/清理` 只清空当前会话记忆，不会删除模型配置、数据库备份或其他会话。

## 部署建议

- 上传整个 `wx_bot/` 目录，确保 `vendor/` 一并上传。
- 首次部署先执行 `python3 login.py` 完成扫码登录。
- 使用 `config.example.json` 创建 `config.json`，并妥善保存 API Key。
- 建议定期备份 `data/memory.sqlite3` 和 `~/.ilinkai`。
- 长期运行建议使用 `systemd`、`supervisor` 或 `nohup`。

## 排查问题

- 启动提示找不到账号：先运行 `python3 login.py`，或检查 `wechat.account_id`。
- AI 无回复或报错：检查 `chat_completions_url`、`api_key`、`model`、网络和 `data/bot.log`。
- 图片无法识别：确认当前模型支持 vision，并开启 `reply.recognize_images` 与 `supports_vision`。
- 微信收到图片异常：先确认 `data/generated_images` 下图片是否正常，再排查微信 SDK 图片发送参数。
- 修改配置不生效：确认 `hot_reload.enabled=true`；账号、SDK、数据库路径变更需重启。

## 兼容约束

项目按 Python 3.6.8 编写，避免使用新语法和重依赖：

- 不使用 `list[str]`、`dict[str, str]`、`match/case`、赋值表达式等新语法。
- AI 请求使用 `urllib.request`，SSE 流式响应按 `data:` 行解析。
- 不依赖 Flask、Webhook、官方 `openai` SDK、`requests` 或 `httpx`。

## 与 ILinkAI SDK 的关系

本项目已将 ILinkAI Weixin Python SDK 复制到：

```text
vendor/ilinkai_weixin
```

运行时 `main.py` 会把 `wechat.sdk_path` 加入 `sys.path`，默认值为 `vendor`。因此部署时只需要上传整个项目目录即可。

## 开源协议

本项目代码采用 [MIT License](LICENSE) 开源。

注意：本仓库包含 vendored 的 `ILinkAI.Weixin` Python SDK，相关代码仍应遵守其原项目协议和版权声明。当前上游 README 标注为 MIT License；如果上游后续变更协议，请以上游仓库为准。

`openclaw-weixin` 当前仓库未看到独立 LICENSE 文件，因此本项目仅作为思路参考列出；如复制其代码或素材，请先确认并遵守其许可条款。



## 参考与致谢

本项目在实现微信接入能力时参考或使用了以下开源项目：

- [openclaw-weixin](https://github.com/hao-ji-xing/openclaw-weixin)：微信 Bot / 消息处理相关思路参考。
- [ILinkAI.Weixin](https://github.com/cyoukon/ILinkAI.Weixin)：本项目 vendored 的 ILinkAI Weixin Python SDK 来源，用于微信扫码登录、消息监听和消息发送。

请在使用、分发或二次开发本项目时，同时遵守上述项目及其依赖的开源协议。