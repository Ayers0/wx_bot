# Python 3.6.8 兼容说明

目标服务器环境：

```text
CentOS Linux 7 (Core)
Python 3.6.8
```

## 结论

可以兼容当前 Python 3.6.8，但需要遵守兼容约束。

现有 ILinkAI Weixin Python SDK 使用了 `dataclasses`。`dataclasses` 是 Python 3.7 才内置的模块，因此 Python 3.6 需要安装兼容包：

```bash
python3 -m pip install dataclasses
```

SDK 的 `setup.py` 已调整：

```python
python_requires=">=3.6"
install_requires=["dataclasses; python_version < '3.7'"]
```

## 已检查和已修改的不兼容点

已扫描现有 Python SDK，发现并处理：

- `ilinkai_weixin/auth/session_guard.py` 曾使用 `dict[str, int]`，这是 Python 3.9+ 类型写法，已改为普通 `{}`。
- `setup.py` 曾声明 `python_requires=">=3.8"`，已改为 `>=3.6`。
- `setup.py` 已为 Python 3.6 增加 `dataclasses` 条件依赖。

已确认无需替换：

- f-string：Python 3.6 已支持。
- 变量注解：Python 3.6 已支持，但后续不使用 `dict[str]` / `list[str]` 这类写法。
- 数字下划线，例如 `35_000`：Python 3.6 已支持。
- `bytes.fromhex`：Python 3.5+ 已支持。
- `int.from_bytes`：Python 3.2+ 已支持。
- `os.makedirs(..., exist_ok=True)`：Python 3.2+ 已支持。
- `urllib.request.Request(..., method="POST")`：Python 3.3+ 已支持。
- `datetime.timezone`：Python 3.2+ 已支持。

## 后续代码约束

Bot 代码将避免使用以下语法或特性：

- f-string 可以使用，Python 3.6 已支持。
- 不使用 `list[str]` / `dict[str, str]`。
- 不使用 `typing.Protocol`。
- 不使用 `dataclasses`，除非明确依赖兼容包。
- 不使用 `asyncio.run`。
- 不使用 `contextvars`。
- 不使用 `zoneinfo`。
- 不使用 `match/case`。
- 不使用仅 Python 3.8+ 支持的赋值表达式 `:=`。
- 不使用仅 Python 3.8+ 支持的仅位置参数语法 `/`。

## 推荐依赖策略

初版只依赖：

- Python 标准库
- `dataclasses` 兼容包，仅 Python 3.6 需要
- 当前项目内的 ILinkAI Weixin SDK

明确不依赖：

- 官方 `openai` SDK
- `requests`
- `httpx`

AI 接口请求使用：

```python
urllib.request
```

非流式响应直接解析 JSON：

```text
choices[0].message.content
```

流式响应直接解析 SSE：

```text
data: {...}
data: [DONE]
```

记忆存储使用：

```python
sqlite3
```

配置热重载使用：

```python
os.path.getmtime
threading
time
```

## CentOS 7 注意事项

不要替换系统自带 Python。CentOS 7 的系统工具可能依赖 `/usr/bin/python` 或系统 Python 3.6。

如果后续需要更高版本 Python，建议额外安装并指定运行命令，不要覆盖系统 Python。
