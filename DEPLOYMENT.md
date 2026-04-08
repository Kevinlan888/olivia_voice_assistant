# Olivia 语音助手 — 部署指南

## 目录

1. [项目概览](#项目概览)
2. [系统要求](#系统要求)
3. [服务端部署](#服务端部署)
4. [客户端部署](#客户端部署)
5. [网页客户端部署](#网页客户端部署)
6. [配置指南](#配置指南)
7. [部署验证](#部署验证)
8. [常见问题](#常见问题)

---

## 项目概览

**Olivia** 是一个本地可部署的中文语音助手，采用"轻客户端 + 中心服务端"架构。

### 核心特性

- **ASR（语音识别）**：Faster-Whisper（离线）
- **LLM（大语言模型）**：OpenAI API / Ollama 本地模型（流式输出）
- **TTS（文字转语音）**：Edge-TTS / GPT-SoVITS（流式音频）
- **VAD（语音活动检测）**：Silero VAD（神经网络，ONNX 推理）
- **唤醒词**：Porcupine（Picovoice 离线唤醒词检测）
- **Multi-Agent 框架**：自研轻量框架（参考 OpenAI Agents SDK），Router + 专项 Agent
- **工具调用**：`@function_tool` 装饰器自动生成 JSON Schema（天气、搜索、智能家居）
- **Guardrails**：输入/输出安全检查框架
- **Tracing**：Span-based 调用链追踪
- **双协议**：v1（纯文本）/ v2（JSON 事件），自动协商
- **前端**：Vue 3 单页应用（支持手机/PC浏览器，v2 流式 token 逐字显示）

### 架构流程

```
┌─────────────┐
│   客户端     │ (树莓派 Python 或 网页浏览器)
│  麦克风      │   v2 协议: JSON 事件 + 流式 token
└──────┬──────┘
       │ PCM 音频流 (WebSocket)
       ↓
┌──────────────────────────────────────┐
│     服务端 (Linux/Docker)             │
│  ┌──────────┐                        │
│  │ ASR      │ Whisper                │
│  └────┬─────┘                        │
│       │ 文本                         │
│  ┌────↓──────────────────────────┐   │
│  │ Multi-Agent Router            │   │
│  │  ├─ Weather Agent (天气)      │   │
│  │  ├─ Smart Home Agent (家居)   │   │
│  │  ├─ Search Agent (搜索)       │   │
│  │  └─ 直接回复 (闲聊)           │   │
│  │  EventEmitter → WS 实时推送   │   │
│  └────┬──────────────────────────┘   │
│       │ 回复文本                     │
│  ┌────↓─────┐                        │
│  │ TTS       │ MP3 流                │
│  └────┬──────┘                        │
└───────┼──────────────────────────────┘
        │ MP3 音频 (WebSocket)
        ↓
┌──────────────┐
│  客户端      │
│  扬声器      │
└──────────────┘
```

---

## 系统要求

### 服务端（推荐配置）

| 组件 | 要求 | 说明 |
|------|------|------|
| **OS** | Ubuntu 20.04+ / Debian 11+ / CentOS 8+ | 支持 Linux、Docker |
| **CPU** | 4+ 核 | Whisper 和 LLM 需要计算资源 |
| **GPU** | 可选（CUDA 11.8+） | 加速 Whisper/LLM（推荐） |
| **内存** | 8GB+ | 推荐 16GB（运行 Ollama 本地大模型） |
| **存储** | 50GB+ | Whisper 模型（~2GB）+ Ollama 模型（5-30GB） |
| **网络** | 100Mbps+ | 支持 WSS（WebSocket Secure） |

### 客户端（树莓派）

| 组件 | 要求 | 说明 |
|------|------|------|
| **硬件** | Raspberry Pi 4B+ | 最低 2GB 内存，推荐 4GB |
| **OS** | Raspberry Pi OS (32/64-bit) | - |
| **音频输入** | 麦克风 USB 或板载 | - |
| **音频输出** | 3.5mm 或 USB 扬声器 | - |
| **网络** | WiFi 或以太网 | 与服务端同网络或可达 |

### 网页客户端

| 组件 | 要求 | 说明 |
|------|------|------|
| **浏览器** | Chrome/Edge/Firefox/Safari | 最新版本，支持 Web Audio API |
| **HTTPS** | 需要 | 如果不是 localhost，必须使用 HTTPS |
| **麦克风权限** | 需要授予 | 浏览器会提示 |

---

## 服务端部署

### 方式 1：主机部署（生产推荐）

#### 1.1 系统依赖

```bash
# Ubuntu/Debian
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  python3.11 \
  python3-pip \
  python3-venv \
  git \
  build-essential \
  libssl-dev

# CentOS/RHEL
sudo yum install -y \
  python3.11 \
  python3-pip \
  git \
  gcc \
  openssl-devel
```

#### 1.2 项目部署

```bash
# 创建部署目录
sudo mkdir -p /opt/olivia-server
sudo chown $USER:$USER /opt/olivia-server
cd /opt/olivia-server

# 克隆项目
git clone <repository> .

# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install --upgrade pip setuptools wheel
pip install -r server/requirements.txt

# 验证安装
python3 -c "import faster_whisper; print('Faster-Whisper OK')"
python3 -c "import fastapi; print('FastAPI OK')"
```

#### 1.3 下载模型

```bash
# Whisper 模型（首次运行会自动下载，也可提前下载）
python3 << 'EOF'
from faster_whisper import WhisperModel
model = WhisperModel("base", device="cpu", compute_type="int8")
print("Model cached at ~/.cache/huggingface")
EOF

# 如果使用 Ollama，先安装并启动 Ollama
# 详见下文 "LLM 配置 → Ollama"
```

#### 1.4 环境配置

创建 `/opt/olivia-server/.env`：

```bash
# ASR
WHISPER_MODEL=base
WHISPER_DEVICE=cpu          # 改为 cuda 如果有 GPU
WHISPER_COMPUTE_TYPE=int8   # 改为 float16 如果有 GPU
WHISPER_LANGUAGE=zh

# LLM
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# TTS
TTS_PROVIDER=edge           # 或 sovits
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural

# 可选：OpenAI API 备选方案
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini
# OPENAI_BASE_URL=https://api.openai.com/v1

# 可选：网络搜索
# SERPAPI_KEY=...
```

#### 1.5 启动服务

```bash
# 开发模式（调试）
cd /opt/olivia-server
source venv/bin/activate
python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

# 生产模式（使用 Gunicorn + Uvicorn）
pip install gunicorn
gunicorn server.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:8000 \
  --timeout 60 \
  --access-logfile /var/log/olivia/access.log \
  --error-logfile /var/log/olivia/error.log
```

#### 1.6 Systemd 服务

创建 `/etc/systemd/system/olivia-server.service`：

```ini
[Unit]
Description=Olivia Voice Assistant Server
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=olivia
Group=olivia
WorkingDirectory=/opt/olivia-server
ExecStart=/opt/olivia-server/venv/bin/python3 -m gunicorn \
  server.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 127.0.0.1:8000 \
  --access-logfile /var/log/olivia/access.log \
  --error-logfile /var/log/olivia/error.log
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable olivia-server
sudo systemctl start olivia-server
sudo journalctl -u olivia-server -f
```

---

### 方式 2：Docker 部署（推荐）

#### 2.1 构建镜像

创建 `Dockerfile` 在项目根目录：

```dockerfile
FROM python:3.11-slim-bullseye

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 项目代码
COPY server ./server
COPY web_client/dist ./web_client/dist

# 确保 agent_framework 和 agents 包被复制
# (已包含在 server/ 目录中)

# 非 root 用户
RUN useradd -m -u 1000 olivia && chown -R olivia:olivia /app
USER olivia

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python3", "-m", "uvicorn", "server.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
```

#### 2.2 构建并运行

```bash
# 构建
docker build -t olivia-server:latest .

# 运行（开发）
docker run \
  -it --rm \
  -p 8000:8000 \
  -v $PWD/server:/app/server \
  -e WHISPER_MODEL=base \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  olivia-server:latest

# 运行（生产）
docker run \
  -d --restart unless-stopped \
  --name olivia-server \
  -p 8000:8000 \
  -v /opt/olivia-models:/home/olivia/.cache \
  -e WHISPER_MODEL=base \
  -e WHISPER_DEVICE=cuda \
  --gpus all \
  olivia-server:latest
```

#### 2.3 Docker Compose

创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  # Ollama LLM
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    environment:
      - OLLAMA_KEEP_ALIVE=24h
    command: serve
    restart: unless-stopped

  # Olivia 服务端
  server:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./server:/app/server
      - whisper_cache:/home/olivia/.cache
    environment:
      - WHISPER_MODEL=base
      - WHISPER_DEVICE=cpu
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - TTS_PROVIDER=edge
    depends_on:
      - ollama
    restart: unless-stopped

volumes:
  ollama_data:
  whisper_cache:
```

```bash
docker-compose up -d
docker-compose logs -f server
```

---

## 客户端部署

### 树莓派部署（本地唤醒词 + 语音输入）

#### 3.1 系统准备

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装依赖
sudo apt install -y \
  python3-pip \
  python3-venv \
  portaudio19-dev \
  libmpg123-dev \
  python3-dev \
  alsa-utils \
  git

# 配置音频输出（树莓派特定）
# 3.5mm 口：
sudo amixer cset numid=3 1
# HDMI：
sudo amixer cset numid=3 2
# USB：
sudo aplay -l  # 列出设备，然后配置 PLAYBACK_DEVICE_INDEX
```

#### 3.2 项目部署

```bash
# 创建部署目录
sudo mkdir -p /opt/olivia-client
sudo chown pi:pi /opt/olivia-client

cd /opt/olivia-client
git clone <repository> .

# 虚拟环境
python3 -m venv venv
source venv/bin/activate

# 依赖安装
pip install --upgrade pip setuptools
pip install -r client/requirements.txt
```

#### 3.3 打包为可执行文件（可选）

将客户端打包为单个可执行文件，部署时无需安装 Python 和 pip 依赖。

```bash
cd /opt/olivia-client
source venv/bin/activate
pip install pyinstaller

pyinstaller --onefile run_client.py \
  --name olivia-client \
  --add-data ".env:." \
  --add-data "client/models:client/models" \
  --collect-all pvporcupine \
  --collect-data miniaudio \
  --hidden-import _cffi_backend
```

生成的可执行文件位于 `dist/olivia-client`，可直接运行：

```bash
./dist/olivia-client
```

> **注意**：目标机器仍需安装系统级依赖 `portaudio19-dev` 和 `libasound2`。
> `.env` 和 Porcupine 模型文件已通过 `--add-data` 打包在内。
> 如需修改配置，需重新打包。

#### 3.4 配置 `.env`

创建 `/opt/olivia-client/client/.env`：

```bash
# 服务器连接
 SERVER_WS_URL=ws://192.168.1.100:8000/ws/audio

# 唤醒词（Porcupine）
PICOVOICE_ACCESS_KEY=​           # https://console.picovoice.ai/ 免费获取
WAKE_WORD_KEYWORD=porcupine
WAKE_WORD_THRESHOLD=0.5

# Silero VAD 语音活动检测
SILERO_SPEECH_THRESHOLD=0.5     # 0.0–1.0，推荐 0.5
SILENCE_SECONDS=1.5
MIN_RECORDING_SECONDS=1.0
MAX_RECORDING_SECONDS=15

# 音频
PLAYBACK_DEVICE_INDEX=-1        # -1 = 系统默认
STREAM_PLAYBACK=false

# 按键说话模式（可选，树莓派 GPIO）
# PTT_GPIO_PIN=17
# PTT_PULL_UP=false
```

#### 3.4 Systemd 自启动

创建 `/etc/systemd/system/olivia-client.service`：

```ini
[Unit]
Description=Olivia Voice Assistant Client
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/olivia-client
ExecStart=/opt/olivia-client/venv/bin/python3 -m client.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable olivia-client
sudo systemctl start olivia-client
journalctl -u olivia-client -f
```

---

## 网页客户端部署

### 4.1 构建静态资源

```bash
cd web_client

# 安装依赖
npm install

# 开发模式
npm run dev

# 生产构建
npm run build
# 输出到 dist/ 目录
```

### 4.2 部署到服务端

网页客户端已集成在服务端，FastAPI 在 `/` 路由服务静态文件：

```bash
# 构建网页客户端
cd web_client && npm run build && cd ..

# 网页资源会被FastAPI在以下位置服务：
# GET / -> index.html
# GET /assets/* -> 哈希的 CSS/JS
# WebSocket ws://host:8000/ws/audio -> 服务端处理
```

### 4.3 访问地址

- **开发**：`http://localhost:5173`（由 Vite 服务）
- **生产**：`http://0.0.0.0:8000`（由 FastAPI 服务）
- **HTTPS 生产**：`https://your-domain.com:8000`（需要证书）

---

## 配置指南

### ASR 配置

| 参数 | 值 | 说明 |
|------|-----|------|
| `WHISPER_MODEL` | `tiny` / `base` / `small` / `medium` / `large-v3` | 大模型精度更高但速度慢 |
| `WHISPER_DEVICE` | `cpu` / `cuda` | GPU 需要 CUDA 11.8+ |
| `WHISPER_COMPUTE_TYPE` | `int8` / `float16` / `float32` | 低精度节省内存 |
| `WHISPER_LANGUAGE` | `zh` / `en` / `auto` | 中文/英文/自动检测 |

### LLM 配置

#### Ollama（本地，推荐）

```bash
# 安装 Ollama
curl https://ollama.ai/install.sh | sh

# 启动服务（macOS）
ollama serve

# 启动服务（Linux/Windows）
sudo systemctl start ollama

# 拉取模型
ollama pull qwen2.5:7b       # 7B 参数，4GB 内存
ollama pull qwen2.5:14b      # 14B 参数，推荐 8GB+
ollama pull llama2:13b       # 英文模型

# 测试
curl http://localhost:11434/api/generate -d '{"model":"qwen2.5:7b","prompt":"你好"}'

# 配置环境
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=qwen2.5:7b
```

#### OpenAI API（云端）

```bash
# 设置 API Key
export OPENAI_API_KEY=sk-...
export LLM_PROVIDER=openai
export OPENAI_MODEL=gpt-4o-mini
```

### TTS 配置

#### Edge-TTS（免费，在线）

```bash
export TTS_PROVIDER=edge
export EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural  # 晓晓
# 或 zh-CN-YunyangNeural（云阳）等
```

#### GPT-SoVITS（本地，自定义声音）

需要单独部署，参考：https://github.com/RVC-Boss/GPT-SoVITS

```bash
export TTS_PROVIDER=sovits
export SOVITS_BASE_URL=http://localhost:9880
```

---

## HTTPS 和 SSL 设置

### 生产环境 HTTPS

#### 使用 Let's Encrypt（推荐）

```bash
# 安装 certbot
sudo apt install -y certbot python3-certbot-nginx

# 申请证书
sudo certbot certonly --standalone \
  -d your-domain.com \
  --non-interactive \
  --agree-tos \
  -m your-email@example.com

# Nginx 反向代理配置
sudo nano /etc/nginx/sites-available/olivia

# 内容示例：
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}

# 启用配置
sudo ln -s /etc/nginx/sites-available/olivia /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# 自动续期
sudo systemctl enable certbot-renew.timer
```

#### 自签名证书（开发/内网）

```bash
openssl req -x509 -newkey rsa:4096 \
  -keyout localhost-key.pem \
  -out localhost.pem \
  -days 365 -nodes

# 在 FastAPI 中启用：
# uvicorn server.main:app \
#   --ssl-keyfile=localhost-key.pem \
#   --ssl-certfile=localhost.pem
```

---

## 部署验证

### 检查清单

```bash
# 1. 服务端健康检查
curl http://localhost:8000/health || echo "Server not responding"

# 2. WebSocket 连接测试
python3 << 'EOF'
import asyncio
import websockets

async def test_ws():
    async with websockets.connect("ws://localhost:8000/ws/audio") as ws:
        print("✓ WebSocket 连接成功")
        await ws.send("PING")
        response = await ws.recv()
        print(f"✓ 收到: {response}")

asyncio.run(test_ws())
EOF

# 3. ASR 测试
python3 << 'EOF'
from faster_whisper import WhisperModel
model = WhisperModel("base", device="cpu")
segments, info = model.transcribe("sample.wav", language="zh")
for segment in segments:
    print(segment.text)
EOF

# 4. 客户端连接测试（树莓派）
cd /opt/olivia-client && source venv/bin/activate
python3 -m client.main

# 5. 网页客户端测试
# 访问 http://localhost:8000，点击麦克风按钮测试
```

### 日志查看

```bash
# 服务端
sudo journalctl -u olivia-server -f --lines=100
tail -f /var/log/olivia/error.log

# 客户端（树莓派）
sudo journalctl -u olivia-client -f --lines=100

# Docker
docker logs -f olivia-server
docker-compose logs -f server
```

---

## 常见问题

### Q1: WebSocket 连接失败

**问题**：客户端无法连接到服务端

**解决**：
```bash
# 检查服务是否运行
nc -zv 192.168.1.100 8000

# 检查防火墙
sudo ufw allow 8000/tcp
sudo ufw enable

# 查看服务日志
sudo journalctl -u olivia-server -f

# 检查 .env 中的 SERVER_WS_URL
cat /opt/olivia-client/client/.env | grep SERVER_WS_URL
```

### Q2: Whisper 模型加载缓慢

**问题**：首次运行时模型下载很慢

**解决**：
```bash
# 提前下载模型
python3 << 'EOF'
from faster_whisper import WhisperModel
model = WhisperModel("base", device="cpu", compute_type="int8")
print("✓ 模型已缓存")
EOF

# 查看缓存位置
ls -lh ~/.cache/huggingface/
```

### Q3: 树莓派没有音频输入/输出

**问题**：麦克风或扬声器无法工作

**解决**：
```bash
# 列出音频设备
arecord -l    # 录音设备
aplay -l      # 播放设备

# 测试麦克风
arecord -d 3 -r 16000 -f S16_LE -c 1 test.wav
aplay test.wav

# 更新 .env 中的 PLAYBACK_DEVICE_INDEX
# 例如设备 ID 为 3，则设置 PLAYBACK_DEVICE_INDEX=3
```

### Q4: Ollama 连接失败

**问题**：服务端无法连接 Ollama

**解决**：
```bash
# 检查 Ollama 是否运行
ps aux | grep ollama
sudo systemctl status ollama

# 测试连接
curl http://localhost:11434/api/tags

# 检查 LLM_PROVIDER 和 OLLAMA_BASE_URL 配置
cat /opt/olivia-server/.env | grep OLLAMA
```

### Q5: 高 CPU 占用

**问题**：树莓派 CPU 占用率高

**解决**：
```bash
# 方案 1：禁用唤醒词检测
# 在 .env 中将 WAKE_WORD_KEYWORD 置空

# 方案 2：降低 Whisper 模型
export WHISPER_MODEL=tiny  # 而非 base

# 方案 3：降频处理
echo "powersave" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

### Q6: HTTPS 证书错误

**问题**：浏览器报"不安全连接"

**解决**：
```bash
# 本地开发：使用 http://localhost:8000
# 生产环境：使用 Let's Encrypt（见上文）

# 自签名证书测试
# 在浏览器中点击"继续前往"或"了解风险"
```

---

## 性能优化

### 服务端优化

```bash
# 1. 使用 GPU 加速 Whisper
export WHISPER_DEVICE=cuda
export WHISPER_COMPUTE_TYPE=float16

# 2. 增加 Gunicorn Workers
gunicorn server.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 8 \
  --worker-connections 1000

# 3. 启用 Gzip 压缩（在 FastAPI 中）
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

### 客户端优化（树莓派）

```bash
# 1. 降低采样率（如果网络带宽有限）
export SAMPLE_RATE=8000

# 2. 缩短沉默检测时间
export SILENCE_SECONDS=0.8

# 3. 调整 Silero VAD 灵敏度（降低 = 更容易触发语音检测）
export SILERO_SPEECH_THRESHOLD=0.4
```

---

## 备份和恢复

### 备份重要数据

```bash
# 备份模型缓存
tar -czf whisper-models-backup.tar.gz ~/.cache/huggingface/

# 备份 Ollama 模型
sudo tar -czf ollama-models-backup.tar.gz /root/.ollama/

# 备份配置
tar -czf olivia-config-backup.tar.gz \
  /opt/olivia-server/.env \
  /opt/olivia-client/client/.env
```

### 恢复步骤

```bash
# 恢复模型
tar -xzf whisper-models-backup.tar.gz -C ~/

# 恢复配置
tar -xzf olivia-config-backup.tar.gz -C /

# 重启服务
sudo systemctl restart olivia-server olivia-client
```

---

## 监控和日志

### 设置Log轮转

创建 `/etc/logrotate.d/olivia`：

```
/var/log/olivia/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 olivia olivia
    sharedscripts
}
```

```bash
sudo logrotate -f /etc/logrotate.d/olivia
```

### 基本监控脚本

```bash
#!/bin/bash
# /usr/local/bin/olivia-monitor.sh

check_service() {
  if systemctl is-active $1 >/dev/null; then
    echo "✓ $1 running"
  else
    echo "✗ $1 stopped — restarting"
    sudo systemctl restart $1
  fi
}

while true; do
  check_service olivia-server
  check_service olivia-client
  sleep 60
done
```

```bash
chmod +x /usr/local/bin/olivia-monitor.sh
# 加入 cron：
# */5 * * * * /usr/local/bin/olivia-monitor.sh
```

---

## 更新升级

### 升级依赖

```bash
# 服务端
cd /opt/olivia-server
source venv/bin/activate
pip list --outdated
pip install --upgrade <package-name>

# 重启服务
sudo systemctl restart olivia-server

# 客户端
cd /opt/olivia-client
source venv/bin/activate
pip install --upgrade -r client/requirements.txt
sudo systemctl restart olivia-client
```

### 升级项目代码

```bash
cd /opt/olivia-server
git pull origin main
source venv/bin/activate
pip install -r server/requirements.txt
sudo systemctl restart olivia-server

# 同时构建新的网页客户端
cd web_client && npm run build && cd ..
```

---

## 支持和调试

### 启用详细日志

```bash
# 临时启用 DEBUG 模式
export LOG_LEVEL=DEBUG
python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000

# 查看 WebSocket 连接详情
python3 << 'EOF'
import logging
logging.basicConfig(level=logging.DEBUG)
# 再启动客户端
EOF
```

### 收集诊断信息

```bash
#!/bin/bash
# 生成诊断报告
echo "=== System Info ===" > diagnosis.txt
uname -a >> diagnosis.txt
echo "\n=== Services ===" >> diagnosis.txt
systemctl status olivia-server >> diagnosis.txt
systemctl status olivia-client >> diagnosis.txt
echo "\n=== Recent Logs ===" >> diagnosis.txt
journalctl -u olivia-server -n 50 >> diagnosis.txt
echo "\n=== Network ===" >> diagnosis.txt
netstat -tulnp | grep 8000 >> diagnosis.txt
echo "\n=== Environment ===" >> diagnosis.txt
env | grep OLIVIA >> diagnosis.txt
cat diagnosis.txt
```

---

## 许可和致谢

项目采用 MIT 许可证。

### 第三方依赖

- **Faster-Whisper**: OpenAI 语音识别模型
- **Ollama**: 本地 LLM 运行时
- **Edge-TTS**: Microsoft 文字转语音
- **Silero VAD**: 神经网络语音活动检测（ONNX Runtime）
- **Porcupine**: Picovoice 离线唤醒词检测

---

**最后更新**：2026-04-08  
**维护者**：Olivia 项目团队
