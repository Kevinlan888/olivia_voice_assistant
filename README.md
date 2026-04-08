# Olivia — AI Voice Assistant

一个本地可部署的中文语音助手，采用"轻客户端 + 中心服务端"架构，支持：

- ASR：Faster-Whisper
- LLM：OpenAI 兼容 API / Ollama（流式输出）
- TTS：Edge-TTS / GPT-SoVITS（流式音频）
- VAD：Silero VAD（神经网络语音活动检测，ONNX 推理）
- 唤醒词：Porcupine（Picovoice 离线唤醒词）
- Multi-Agent：Router + 专项 Agent 架构（参考 OpenAI Agents SDK 设计）
- 工具调用：`@function_tool` 装饰器自动生成 JSON Schema（天气、联网搜索、智能家居）
- Guardrails：输入/输出安全检查框架
- Tracing：Span-based 调用链追踪
- 协议：v1（纯文本）/ v2（JSON 事件）双协议，自动协商
- 前端：Vue 3 网页客户端 / 树莓派 Python 客户端

## 架构概览

```text
麦克风输入（网页或本地客户端）
  -> WebSocket 音频流（PCM）
  -> 服务端 ASR（Whisper）
  -> Multi-Agent Router（LLM 自动路由 + Handoff）
     ├─ Weather Agent  → get_weather 工具
     ├─ Smart Home Agent → control_smart_home 工具
     ├─ Search Agent   → web_search 工具
     └─ 直接回复（闲聊场景）
  -> TTS（流式音频）
  -> 客户端边收边播
```

### Agent 框架

采用自研轻量框架（参考 OpenAI Agents SDK），核心组件：

| 组件 | 说明 |
|------|------|
| **Agent** | 定义 name、instructions（支持动态函数）、tools、handoffs、guardrails |
| **Handoff** | Agent 间委派，LLM 调用 `transfer_to_<name>` 自动切换 |
| **Runner** | 编排器：input guardrails → LLM → tool calls / handoff → output guardrails |
| **EventEmitter** | 实时事件推送（LLMTokenDelta, ToolCallStart/End, Handoff 等） |
| **@function_tool** | 装饰器从 type hints + docstring 自动生成 OpenAI JSON Schema |
| **Tracing** | Span-based 调用链，可按需导出 |

## 项目结构

```text
olivia_voice_assistant/
├─ client/                         # 树莓派 Python 客户端
│  ├─ main.py
│  ├─ ws_client.py                 # WebSocket v1/v2 双协议
│  ├─ audio_recorder.py
│  ├─ silero_vad.py
│  ├─ audio_player.py
│  ├─ wake_word.py
│  ├─ config.py
│  └─ requirements.txt
├─ web_client/                     # Vue 3 网页客户端
│  ├─ src/
│  │  ├─ App.vue                   # v1/v2 事件处理 + 流式 token 显示
│  │  ├─ main.js
│  │  └─ composables/
│  │     ├─ useConnection.js       # WebSocket v2 协议协商
│  │     ├─ useChat.js             # 消息管理 + appendMessage 流式追加
│  │     ├─ usePlayback.js
│  │     ├─ useRecorder.js
│  │     └─ logger.js
│  ├─ index.html
│  ├─ package.json
│  └─ vite.config.js
├─ server/
│  ├─ main.py                     # FastAPI + WebSocket（v1/v2 协议）
│  ├─ config.py                   # Pydantic Settings
│  ├─ protocol.py                 # v2 JSON 事件序列化 + v1 兼容层
│  ├─ requirements.txt
│  ├─ agent_framework/            # 自研 Agent 框架
│  │  ├─ __init__.py              # 公开 API 导出
│  │  ├─ context.py               # RunContext 共享上下文
│  │  ├─ agent.py                 # Agent dataclass
│  │  ├─ tool.py                  # @function_tool 装饰器 + FunctionTool
│  │  ├─ handoff.py               # Handoff 机制
│  │  ├─ guardrail.py             # Input/Output Guardrail
│  │  ├─ events.py                # 事件类型 + EventEmitter
│  │  ├─ runner.py                # Runner 编排器
│  │  ├─ tracing.py               # Span-based 追踪
│  │  └─ sentence_splitter.py     # LLM token → 句子切分
│  ├─ agents/                     # Multi-Agent 定义
│  │  ├─ __init__.py              # create_router_agent()
│  │  ├─ router_agent.py          # 路由 Agent（Handoff 到专项 Agent）
│  │  ├─ chat_agent.py            # 通用闲聊
│  │  ├─ weather_agent.py         # 天气查询
│  │  ├─ smart_home_agent.py      # 智能家居控制
│  │  └─ search_agent.py          # 联网搜索
│  ├─ asr/
│  │  └─ whisper_asr.py
│  ├─ llm/
│  │  ├─ base.py                  # BaseLLM + StreamDelta + 流式接口
│  │  ├─ openai_llm.py
│  │  └─ ollama_llm.py
│  ├─ tts/
│  │  ├─ base.py
│  │  ├─ edge_tts_engine.py
│  │  └─ sovits_tts.py
│  └─ tools/
│     ├─ __init__.py              # ALL_TOOLS / TOOL_DEFINITIONS（自动生成）
│     ├─ weather.py               # @function_tool
│     ├─ smart_home.py            # @function_tool
│     └─ web_search.py            # @function_tool
├─ .env
└─ README.md
```

## 快速开始

### 1. 配置环境变量

```bash
# Linux / macOS
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

编辑 `.env`，至少确认以下字段：

- `LLM_PROVIDER`
- `OPENAI_API_KEY`（如走 openai 兼容接口）
- `TTS_PROVIDER`
- `SERPAPI_KEY`（如要联网搜索）

### 2. 启动服务端

```bash
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r server/requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 使用网页端

服务启动后访问：

```text
http://<服务器IP>:8000/
```

网页交互：

- 按住麦克风说话，松开发送
- 支持空格键按下说话，松开发送
- v2 协议下支持流式 token 逐字显示、工具调用状态、Agent 切换状态
- 聊天区固定高度，内部滚动

注意：

- `localhost` 可用 HTTP 调麦克风
- 手机通过局域网 IP 访问时，通常需要 HTTPS 才能使用麦克风权限

## WebSocket 协议

### 协议协商

客户端连接后发送 `{"protocol": "v2"}` 作为第一个文本帧。服务端回复 `{"protocol": "v2", "status": "ok"}` 确认升级。若客户端不发送，则自动使用 v1 兼容模式。

### Client → Server（v1/v2 共用）

- `binary`：PCM 音频块（int16, 16kHz, mono）
- `text`：`END`（录音结束）
- `text`：`PING`（保活）

### Server → Client（v1 纯文本模式）

- `text`：`USER_TEXT:<msg>`（ASR 用户转写文本）
- `text`：`ASSISTANT_TEXT:<msg>`（助手文本回复）
- `text`：`STATUS:<msg>`（过程状态）
- `text`：`STATUS_AUDIO_DONE`（状态语音结束）
- `binary`：TTS 音频分片（流式 MP3）
- `text`：`DONE`（本轮音频完成）
- `text`：`EMPTY`（无有效语音）
- `text`：`ERROR:<msg>`（异常）
- `text`：`PONG`（保活响应）

### Server → Client（v2 JSON 事件模式）

所有文本帧为 JSON 对象，`event` 字段标识事件类型：

| 事件 | 字段 | 说明 |
|------|------|------|
| `user_text` | `text` | ASR 识别的用户文本 |
| `llm_token` | `token` | LLM 流式输出的单个 token |
| `assistant_text` | `text`, `agent` | 最终助手回复 + 所在 Agent 名称 |
| `agent_start` | `agent` | Agent 开始处理 |
| `agent_end` | `agent` | Agent 处理结束 |
| `tool_start` | `tool`, `args` | 工具调用开始 |
| `tool_end` | `tool`, `result` | 工具调用结束 |
| `handoff` | `from`, `to` | Agent 委派切换 |
| `status` | `text` | 过程状态提示 |
| `guardrail` | `name`, `message` | Guardrail 触发 |
| `audio_done` | — | 本轮 TTS 音频完成 |
| `empty` | — | 无有效语音 |
| `error` | `message` | 异常 |

二进制帧仍为 MP3 音频块（v1/v2 共用）。

## 如何新增一个工具

下面以新增 `get_stock_price` 为例。

### 1. 新建工具实现

新建 `server/tools/stock.py`，使用 `@function_tool` 装饰器：

```python
from typing import Annotated
from pydantic import Field
from server.agent_framework import function_tool, RunContext

@function_tool(description="查询股票最新价格。", status_message="正在查询股价...")
async def get_stock_price(
    symbol: Annotated[str, Field(description="股票代码，例如 AAPL 或 600519")],
    ctx: RunContext | None = None,
) -> dict:
    """获取指定股票的实时价格信息。"""
    import httpx
    url = f"https://example.com/stock?symbol={symbol}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    return {
        "symbol": symbol,
        "price": data.get("price"),
        "currency": data.get("currency", "CNY"),
        "description": f"{symbol} 当前价格约为 {data.get('price')} {data.get('currency', 'CNY')}。",
    }
```

规则：

- 工具函数用 `async def`
- 使用 `Annotated[type, Field(description="...")]` 标注参数描述
- `@function_tool` 自动从函数签名生成 OpenAI JSON Schema，无需手写
- 可选接收 `ctx: RunContext` 参数（框架自动注入，不会出现在 schema 中）
- 返回 `dict`，包含可直接给 LLM 使用的 `description`

### 2. 注册工具

在 `server/tools/__init__.py` 中导入：

```python
from .stock import get_stock_price

ALL_TOOLS = [get_weather, control_smart_home, web_search, get_stock_price]
```

### 3. 分配给 Agent

方式 A — 新建专项 Agent + Handoff：

```python
# server/agents/stock_agent.py
from server.agent_framework import Agent
from server.tools import get_stock_price

stock_agent = Agent(
    name="stock",
    instructions="你是股票查询助手。用户询问股价时调用 get_stock_price 工具。",
    tools=[get_stock_price],
)
```

然后在 `router_agent.py` 中添加 Handoff。

方式 B — 直接加到现有 Agent 的 `tools` 列表中。

### 4. 验证

1. 重启服务端
2. 问一句"帮我查一下 AAPL 现在多少钱"
3. 查看日志是否出现 `[Runner] Tool call: get_stock_price`

## 配置项

### Agent 框架配置（server/config.py）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_MAX_TOOL_ROUNDS` | `5` | 单次对话最大工具调用轮数 |
| `AGENT_ENABLE_TRACING` | `True` | 是否启用调用链追踪 |
| `LLM_STREAMING` | `True` | 是否启用 LLM 流式输出 |

## 常见问题

### 1. `cublas64_12.dll is not found`

Windows + CUDA 常见问题。可安装：

- `nvidia-cublas-cu12`
- `nvidia-cudnn-cu12`

本项目已在 `server/asr/whisper_asr.py` 增加 Windows DLL 路径兜底逻辑。

### 2. 手机网页无法访问麦克风

局域网 IP + HTTP 通常不属于安全上下文，需要 HTTPS。

## 环境变量

请参考 `.env.example` 和当前 `.env` 注释说明。
