# Olivia — AI Voice Assistant

一个本地可部署的中文语音助手，采用“轻客户端 + 中心服务端”架构，支持：

- ASR：Faster-Whisper
- LLM：OpenAI 兼容 API / Ollama
- TTS：Edge-TTS / GPT-SoVITS
- VAD：Silero VAD（神经网络语音活动检测，ONNX 推理）
- 唤醒词：Porcupine（Picovoice 离线唤醒词）
- 工具调用：Function Calling（天气、联网搜索、智能家居）
- 前端：Vue 3 网页客户端 / 树莓派 Python 客户端

## 架构概览

```text
麦克风输入（网页或本地客户端）
  -> WebSocket 音频流（PCM）
  -> 服务端 ASR（Whisper）
  -> LLM + ToolAgent（可并发调用工具）
  -> TTS（流式音频）
  -> 网页端边收边播
```

## 项目结构

```text
olivia_voice_assistant/
├─ client/
│  ├─ main.py
│  ├─ ws_client.py
│  ├─ audio_recorder.py      # 录音 + Silero VAD 语音端点检测
│  ├─ silero_vad.py           # Silero VAD ONNX 封装（自动下载模型）
│  ├─ audio_player.py
│  ├─ wake_word.py
│  ├─ config.py
│  └─ requirements.txt
├─ web_client/
│  └─ index.html
├─ server/
│  ├─ main.py
│  ├─ config.py
│  ├─ agent.py
│  ├─ requirements.txt
│  ├─ asr/
│  │  └─ whisper_asr.py
│  ├─ llm/
│  │  ├─ base.py
│  │  ├─ openai_llm.py
│  │  └─ ollama_llm.py
│  ├─ tts/
│  │  ├─ base.py
│  │  ├─ edge_tts_engine.py
│  │  └─ sovits_tts.py
│  └─ tools/
│     ├─ __init__.py
│     ├─ definitions.py
│     ├─ weather.py
│     ├─ smart_home.py
│     └─ web_search.py
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
- 聊天区固定高度，内部滚动
- 支持显示用户转写文本与助手文本回复

注意：

- `localhost` 可用 HTTP 调麦克风
- 手机通过局域网 IP 访问时，通常需要 HTTPS 才能使用麦克风权限

## WebSocket 协议

### Client -> Server

- `binary`：PCM 音频块（int16, 16kHz, mono）
- `text`：`END`（录音结束）
- `text`：`PING`（保活）

### Server -> Client

- `text`：`USER_TEXT:<msg>`（ASR 用户转写文本）
- `text`：`ASSISTANT_TEXT:<msg>`（助手文本回复）
- `text`：`STATUS:<msg>`（过程状态）
- `text`：`STATUS_AUDIO_DONE`（状态语音结束）
- `binary`：TTS 音频分片（流式）
- `text`：`DONE`（本轮音频完成）
- `text`：`EMPTY`（无有效语音）
- `text`：`ERROR:<msg>`（异常）
- `text`：`PONG`（保活响应）

## 如何新增一个 Function Calling 工具

下面以新增 `get_stock_price` 为例。

### 1. 新建工具实现

新建 `server/tools/stock.py`：

```python
import httpx


async def get_stock_price(symbol: str) -> dict:
  # 示例：请替换为你的真实数据源
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
- 参数尽量简单（字符串、数字、布尔）
- 返回 `dict`，并包含可直接给 LLM 使用的 `description`

### 2. 导出工具

在 `server/tools/__init__.py` 中导入并加入 `__all__`。

### 3. 注册到 Agent 调度表

编辑 `server/agent.py`：

- 在 import 区域引入 `get_stock_price`
- 在 `_TOOL_REGISTRY` 增加映射：

```python
"get_stock_price": get_stock_price,
```

### 4. 增加 Tool Schema

编辑 `server/tools/definitions.py`，在 `TOOL_DEFINITIONS` 追加：

```python
{
  "type": "function",
  "function": {
    "name": "get_stock_price",
    "description": "查询股票最新价格。",
    "parameters": {
      "type": "object",
      "properties": {
        "symbol": {
          "type": "string",
          "description": "股票代码，例如 AAPL 或 600519"
        }
      },
      "required": ["symbol"],
    },
  },
}
```

并在 `TOOL_STATUS_MESSAGES` 增加：

```python
"get_stock_price": "正在查询股价...",
```

### 5. 提示词建议（可选但推荐）

在 `SYSTEM_PROMPT` 中明确：

- 涉及实时信息（价格、新闻、天气）优先调用工具
- 工具失败时给出降级说明，不要编造

### 6. 验证

1. 重启服务端
2. 问一句“帮我查一下 AAPL 现在多少钱”
3. 查看日志是否出现 `[Agent] calling tool get_stock_price(...)`

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
