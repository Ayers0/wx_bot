# 设计草案

## 功能边界

本项目目标是开发一个独立运行的微信 AI Bot，复用现有 ILinkAI Weixin Python SDK，不修改 SDK 源码。

目标运行环境为 CentOS 7 / Python 3.6.8。因此实现必须兼容 Python 3.6，不使用 Python 3.7+、3.8+、3.9+ 专有语法。

现有 Python SDK 已做过兼容性检查，已修改 `dict[str, int]` 这类 Python 3.9+ 类型写法，并将 SDK 安装声明调整为 Python 3.6+。

Bot 负责：

- 选择或读取已登录微信账号。
- 启动微信消息监听。
- 将微信消息转换为 AI 输入。
- 从记忆库读取当前会话历史。
- 调用 AI 接口生成回复。
- 保存用户消息和 AI 回复。
- 通过微信 SDK 发送回复。

## 核心模块

### `config.py`

负责加载配置。

计划支持：

- JSON 配置文件。
- 环境变量覆盖敏感配置。
- 默认值补全。
- 配置校验。
- 文件修改时间轮询，实现热重载。

热重载策略：

- 启动时读取 `config.json`。
- 后台每隔 `hot_reload.poll_interval_seconds` 检查配置文件修改时间。
- 修改后重新读取并校验配置。
- 校验成功后替换运行时配置。
- 校验失败时保留旧配置并记录错误日志。

初版允许热重载：

- `ai.model`
- `ai.stream`
- `ai.max_tokens`
- `ai.temperature`
- `ai.system_prompt`
- `reply.*`
- `logging.level`

初版不建议热重载：

- `wechat.*`
- `memory.database_path`
- `hot_reload.enabled`

原因是微信监听服务、账号 token、SDK 路径、数据库连接都属于运行期基础资源，热替换容易引入状态不一致。

### `bot_core/ai/client.py`

负责调用 OpenAI 兼容接口。

计划提供：

- `chat(messages)`：非流式调用，返回完整文本。
- `chat_stream(messages)`：流式调用，逐段产出 delta 文本。

实现决策：

- 直接使用 Python 标准库 `urllib.request` 请求 OpenAI 兼容接口。
- 不依赖官方 `openai` SDK。
- 不依赖 `requests`。
- 不依赖 `httpx`。
- 这样可以兼容 CentOS 7 默认 Python 3.6.8，并减少部署问题。

接口配置通过 `config.json` 提供。设计文档只保留占位示例，避免写入真实服务器地址或密钥：

```text
POST https://api.example.com/v1/chat/completions
```

模型示例：

```text
your-model-name
```

非流式响应结构：

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1779118184,
  "model": "your-model-name",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "...",
        "reasoning_content": "..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 22,
    "completion_tokens": 54,
    "total_tokens": 76
  }
}
```

后续实现默认读取：

```text
choices[0].message.content
```

并忽略：

```text
choices[0].message.reasoning_content
```

流式响应已确认是 SSE 格式：

```text
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant","content":"..."}}]}
data: [DONE]
```

后续实现默认读取：

```text
choices[0].delta.content
```

并忽略：

```text
choices[0].delta.reasoning_content
```

初版固定使用 Python 标准库 `urllib.request` 实现，减少依赖。

不使用第三方 HTTP 客户端和官方 OpenAI SDK，除非后续明确要求改变部署策略。

### `bot_core/memory/store.py`

负责记忆持久化。

推荐初版使用 SQLite。

计划表结构：

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    message_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_messages_session_id_id ON messages(session_id, id);
```

角色：

- `user`
- `assistant`
- `system`

### `bot_core/session/manager.py`

负责构造模型上下文。

计划逻辑：

- 根据微信消息计算 `session_id`。
- 读取最近 N 条历史消息。
- 拼接系统提示词。
- 加入当前用户消息。
- 控制上下文长度。

初版可以按消息条数裁剪，不做 token 精确计算。

### `bot_core/wechat/bot.py`

负责微信侧编排。

计划流程：

1. 读取账号配置。
2. 创建 `WeixinApiClient`。
3. 创建 `MessageSendService`。
4. 创建 `MessageMonitorService`。
5. 收到消息后提取 `ctx.body`。
6. 检查 `context_token` 是否存在。
7. 根据配置决定是否回复。
8. 调用 AI。
9. 保存记忆。
10. 发送微信回复。

### `main.py`

负责启动。

只保留一个直接运行入口：

```bash
python3 main.py
```

默认读取当前目录的 `config.json`。

也支持一个可选配置参数：

```bash
python3 main.py --config config.json
```

不实现复杂 CLI，不提供子命令，不创建 Flask 服务。

代码结构采用根目录入口 + 内部包：

```text
main.py
bot_core/
  ai/client.py
  config/manager.py
  memory/store.py
  media/image_downloader.py
  media/image_data.py
  session/manager.py
  wechat/bot.py
```

`main.py` 只做依赖组装和生命周期管理，业务逻辑留在 `bot_core/` 包中。

ILinkAI Weixin Python SDK vendoring 到：

```text
vendor/ilinkai_weixin
```

`config.json` 默认：

```json
"wechat": {
  "sdk_path": "vendor"
}
```

这样 `wx_bot/` 可以作为独立目录部署。

主流程：

1. 解析可选 `--config` 参数。
2. 加载配置。
3. 初始化热重载监听。
4. 初始化记忆库。
5. 初始化 AI 客户端。
6. 初始化微信监听服务。
7. 阻塞运行长轮询监听。

## AI 调用模式

## AI 图片处理

当前 AI chat 端点可能直接在 `choices[0].message.content` 中返回图片 URL，例如：

```text
https://api.example.com/v1/files/image?id=...
```

`bot_core/media/image_downloader.py` 负责：

- 从 AI 回复文本中匹配图片 URL。
- 带 `Authorization: Bearer <api_key>` 下载图片二进制。
- 根据 `Content-Type` 选择扩展名。
- 保存到 `data/generated_images`。
- 按配置清理过期或超量图片。

`bot_core/wechat/bot.py` 负责：

- 判断 AI 回复是否包含图片 URL。
- 如果包含，通过 `MessageSendService.send_image()` 发送图片。
- 如果不包含，按普通文本发送。

如果 `reply.send_ai_images=false`，则不会下载和发送图片，而是直接把 AI 返回文本发给微信。

## 微信图片识别

收到微信图片后，`MessageMonitorService` 会把媒体保存到 `wechat.media_dir` 并填充 `ctx.media_path` / `ctx.media_type`。

处理流程：

1. `bot_core/wechat/bot.py` 检查 `ctx.media_path` 和 `ctx.media_type`。
2. `bot_core/media/image_data.py` 将本地图片编码为 `data:image/...;base64,...`。
3. `bot_core/session/manager.py` 构造 OpenAI vision 消息：

```json
{
  "role": "user",
  "content": [
    { "type": "text", "text": "请识别这张图片" },
    { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,..." } }
  ]
}
```

4. `bot_core/ai/client.py` 按普通 Chat Completions 请求发送。

接收媒体目录清理：

- `bot_core/media/cleanup.py` 提供通用目录清理器。
- `main.py` 为 `wechat.media_dir` 创建清理器。
- `bot_core/wechat/bot.py` 在处理消息时按间隔触发清理。
- 默认保留 1 天，最多 500 个文件，每小时检查一次。

配置项：

```json
"reply": {
  "recognize_images": true,
  "image_recognition_prompt": "请识别这张图片，并简要说明图片内容。"
}
```

### 非流式模式

流程：

1. 发送完整 messages 到 AI。
2. 等待完整响应。
3. 保存 assistant 消息。
4. 发送一条微信消息。

底层实现：

- `urllib.request.Request`
- `Content-Type: application/json`
- `Authorization: Bearer <api_key>`
- `json.loads(response_body)`
- 读取 `choices[0].message.content`

优点：稳定、简单、不容易刷屏。

### 流式模式

默认建议：

1. 发送 `stream: true`。
2. 控制台实时打印 delta。
3. 收集完整回复。
4. 最终发送一条微信消息。

底层实现：

- `urllib.request.urlopen(request)`
- 逐行读取响应流。
- 只处理 `data:` 开头的 SSE 行。
- 遇到 `data: [DONE]` 结束。
- 对每个 chunk 执行 `json.loads(...)`。
- 读取 `choices[0].delta.content`。
- 忽略 `choices[0].delta.reasoning_content`。

可选增强：

- 按句号、换行或固定字符数分段发送到微信。
- 发送 typing 状态。
- 限制分段频率，避免消息过多。

## 记忆策略

初版建议：

- 每个会话保存完整消息。
- 每次请求只取最近 `max_history_messages` 条。
- 默认 `max_history_messages = 20`。
- 支持用户发送 `/clear` 清空当前会话记忆。

后续增强：

- 对旧消息做摘要。
- 支持长期用户画像。
- 支持向量数据库知识检索。
- 支持按群/私聊配置不同提示词。

## 配置草案

当前 `config.example.json` 已创建，核心配置为：

```json
{
  "wechat": {
    "account_id": "",
    "auto_login": false,
    "media_dir": "data/media"
  },
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
    },
  "memory": {
    "database_path": "data/memory.sqlite3",
    "max_history_messages": 20
  },
  "reply": {
    "ignore_empty_text": true,
    "clear_commands": ["/clear", "清空记忆"],
    "stream_send_to_wechat": false,
    "stream_chunk_chars": 120,
    "stream_chunk_interval_seconds": 1.5
  }
}
```

## 待确认问题

- 是否允许安装第三方依赖。
- AI 流式输出是否需要真的分段发到微信。
- 群聊是否自动回复所有消息。
- 是否需要扫码登录集成在新 Bot 中。
- 是否要支持多账号并发。
- 记忆是否必须加密存储。
