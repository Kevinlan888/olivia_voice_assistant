# Olivia — AI Voice Assistant

基于 **"瘦客户端 + 服务端"** 架构的本地 AI 语音助手。

```
客户端（树莓派/PC）
  └─ 离线唤醒 (Porcupine)
  └─ 麦克风录音 (PyAudio + VAD)
  └─ WebSocket 音频流
              │
              ▼
服务端（中心服务器）
  ASR  : Faster-Whisper
  LLM  : OpenAI API / Ollama
  TTS  : Edge-TTS / GPT-SoVITS
              │
              ▼
客户端：播放 TTS 音频 (pygame)
```

---

## 项目结构

```
olivia/
├── client/
│   ├── config.py           # 客户端配置（pydantic-settings）
│   ├── wake_word.py        # 离线唤醒词检测（Porcupine）
│   ├── audio_recorder.py   # 麦克风录音 + 能量 VAD
│   ├── audio_player.py     # MP3/WAV 播放（pygame）
│   ├── ws_client.py        # WebSocket 客户端
│   ├── main.py             # 客户端主入口
│   └── requirements.txt
├── web_client/
│   └── index.html          # 手机网页客户端（单文件，无需安装）
├── server/
│   ├── config.py           # 服务端配置（pydantic-settings）
│   ├── main.py             # FastAPI 应用 + WebSocket 端点
│   ├── agent.py            # ToolAgent（Function Calling 循环）
│   ├── asr/
│   │   └── whisper_asr.py  # Faster-Whisper ASR
│   ├── llm/
│   │   ├── base.py
│   │   ├── openai_llm.py   # OpenAI / 兼容 API
│   │   └── ollama_llm.py   # Ollama 本地模型
│   ├── tools/
│   │   ├── definitions.py  # Function Calling schema
│   │   ├── weather.py      # 查天气（wttr.in）
│   │   ├── smart_home.py   # 控制智能家居
│   │   └── web_search.py   # 联网搜索（DuckDuckGo）
│   └── tts/
│       ├── base.py
│       ├── edge_tts_engine.py  # Microsoft Edge TTS（免费）
│       └── sovits_tts.py       # GPT-SoVITS（本地克隆音色）
├── .vscode/
│   └── launch.json         # VS Code 调试配置
├── .env.example
└── README.md
```

---

## 快速开始

### 1. 克隆项目 & 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填写 PORCUPINE_ACCESS_KEY 等
```

### 2. 启动服务端

```bash
cd olivia
python -m venv .venv && source .venv/bin/activate

pip install -r server/requirements.txt

# 若使用 GPU 加速 Whisper：
# pip install faster-whisper[cuda]  （需要 CUDA 环境）

# 启动，reload 模式方便开发
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 启动客户端

```bash
# 树莓派先安装系统依赖：
# sudo apt install portaudio19-dev libmpg123-dev

pip install -r client/requirements.txt
python -m client.main
```

### 4. 手机网页客户端

服务端启动后，手机浏览器直接访问（无需安装任何 App）：

```
http://<服务器IP>:8000/
```

点击麦克风图标 → 说话 → 再次点击停止 → 播放 AI 回复。

- 无需唤醒词，点击即用
- 支持 iOS Safari / Android Chrome
- 单文件纯 HTML，无框架依赖

---

## WebSocket 通信协议

| 方向 | 帧类型 | 内容 |
|------|--------|------|
| Client → Server | binary | PCM 音频块（int16, 16kHz, mono） |
| Client → Server | text | `"END"` — 录音结束，触发处理管道 |
| Client → Server | text | `"PING"` — 保活心跳 |
| Server → Client | binary | MP3 音频块（TTS 结果，流式分批） |
| Server → Client | text | `"DONE"` — 本轮音频发送完毕 |
| Server → Client | text | `"EMPTY"` — 未识别到有效语音 |
| Server → Client | text | `"ERROR:<msg>"` — 处理异常 |
| Server → Client | text | `"PONG"` — 心跳回应 |

---

## 关键技术选型说明

| 模块 | 选型 | 理由 |
|------|------|------|
| 唤醒词 | Porcupine | 全离线、低延迟、支持树莓派 |
| ASR | Faster-Whisper | CTranslate2 量化，比原版快 4× |
| LLM | Ollama / OpenAI | 切换灵活；Ollama 支持完全本地部署 |
| TTS | Edge-TTS | 免费、音质好、无需本地 GPU |
| TTS（高质量） | GPT-SoVITS | 支持音色克隆 |
| 传输协议 | WebSocket | 全双工、低延迟、支持流式二进制传输 |
| 服务端框架 | FastAPI + asyncio | 原生异步、高并发 |

---

## 环境变量参考

见 [`.env.example`](.env.example)。
