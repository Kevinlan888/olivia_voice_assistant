# 联网搜索响应慢的原因分析

> 本文档分析服务端在调用 `web_search` 工具时响应缓慢的根本原因。

---

## 完整请求链路（联网搜索路径）

```
客户端发送音频
  │
  ▼
[1] ASR：asyncio.to_thread(asr.transcribe, raw_pcm)         ≈ 1–5 s
  │       (faster-whisper, 默认 CPU)
  ▼
[2] LLM 第一轮：agent.run() → generate_with_tools()          ≈ 2–30 s
  │       判断是否需要调用 web_search
  ▼
[3] Status TTS（若 TTS_STATUS_AUDIO=True）                   ≈ 0.5–2 s
  │       synthesize_stream("正在联网搜索...") → Edge TTS 网络请求
  │       ⚠️ 此步骤完成前，web_search 不会启动
  ▼
[4] SerpAPI HTTP 请求                                         ≈ 1–4 s
  │       GET https://serpapi.com/search.json
  ▼
[5] LLM 第二轮：generate_with_tools()（含搜索结果）           ≈ 2–30 s
  │       生成最终回复
  ▼
[6] TTS 最终回复：synthesize_stream(reply)                    ≈ 1–3 s
  │       Edge TTS 网络请求（回复文本通常更长）
  ▼
客户端收到音频
```

**总耗时（联网搜索）：约 7–74 秒**

对比不需要搜索的普通问答（仅步骤 1 + 2 + 6）：约 4–38 秒。
搜索路径**额外增加约 3–36 秒**。

---

## 各瓶颈详细说明

### 瓶颈 1：两次 LLM 推理（架构层面必然开销）

**位置**：`server/agent.py`，`ToolAgent.run()` 的循环体（第 149 行）

搜索路径必须经历两次完整 LLM 调用：

| 轮次 | 作用 | 输入 tokens |
|------|------|------------|
| 第 1 轮 | 决定调用哪个工具 | 系统提示 + 对话历史 + **3 条 tool definition** |
| 第 2 轮 | 根据搜索结果生成回复 | 第 1 轮内容 + **搜索结果 JSON** |

- **OpenAI API**：每轮约 2–5 秒（含网络延迟 + 云端推理）
- **Ollama 本地（默认 `qwen2.5:7b`，CPU）**：每轮约 5–30 秒

两轮叠加，仅 LLM 部分就需要 **4–60 秒**。

---

### 瓶颈 2：Status TTS 阻塞搜索启动（最易被忽视）

**位置**：`server/agent.py` 第 86–92 行 + `server/main.py` 第 150–167 行 + `server/config.py` 第 32 行

```python
# agent.py _execute_tool_calls()
for tc in tool_calls:
    name = tc["function"]["name"]
    if name not in seen:
        await status_cb(msg)   # ← 在此 await，工具执行尚未开始

# 直到 status_cb 完全返回后，才进入：
return list(await asyncio.gather(*[_run_one(tc) for tc in tool_calls]))
```

`config.py` 中 `TTS_STATUS_AUDIO` 默认值为 `True`：

```python
TTS_STATUS_AUDIO: bool = True
```

当该选项启用时，`send_status("正在联网搜索...")` 会：
1. 发送 `STATUS:正在联网搜索...` 文本帧
2. 调用 `tts.synthesize_stream("正在联网搜索...")` → **向 Microsoft Edge TTS 发起网络请求**
3. 等待音频流式返回并逐块发送给客户端
4. 发送 `STATUS_AUDIO_DONE`

**只有上述步骤全部完成，SerpAPI 请求才会发出。**
换言之，status 音频合成（约 0.5–2 秒）与搜索请求是**串行**的，而非并发。

---

### 瓶颈 3：SerpAPI 外部网络延迟

**位置**：`server/tools/web_search.py` 第 42 行

```python
resp = await _HTTP.get(_SERPAPI_URL, params=params)
```

- SerpAPI 是一个商业搜索代理服务，本身有 1–4 秒的处理时间
- 默认搜索引擎为 Google（`SERPAPI_ENGINE: str = "google"`），Google 结果获取相对较慢
- 服务器到 SerpAPI 服务器的网络延迟因部署地点而异
- 超时设置为 15 秒（`timeout=15.0`），最差情况下等待时间很长

---

### 瓶颈 4：LLM 响应不使用流式输出

**位置**：`server/llm/ollama_llm.py` 第 45 行，`server/llm/openai_llm.py` 第 35 行

```python
# ollama_llm.py
"stream": False,   # 等待完整响应后再返回
```

两个 LLM 客户端均未启用 streaming，必须等待模型生成完整回复后才继续后续步骤。
对于较长的搜索摘要回复，这会带来额外的等待时间。

---

### 瓶颈 5：最终回复的 TTS 合成（Edge TTS 网络请求）

**位置**：`server/main.py` 第 224 行，`server/tts/edge_tts_engine.py` 第 26 行

```python
# edge_tts_engine.py
communicate = edge_tts.Communicate(text, self._voice)
async for chunk in communicate.stream():   # 每次合成都向微软服务器发请求
    yield chunk["data"]
```

- Edge TTS 是微软云服务，每次调用均需网络往返
- 搜索场景下 LLM 回复通常比普通问答更长（包含搜索摘要），音频合成时间相应增加
- 同一连接中 status 语音（步骤 3）和最终回复语音（步骤 6）各占一次 Edge TTS 请求

---

## 瓶颈汇总

| # | 瓶颈 | 估算耗时 | 涉及文件 |
|---|------|---------|---------|
| 1 | **两次 LLM 推理**（架构必然） | 4–60 s | `agent.py:149` |
| 2 | **Status TTS 阻塞搜索启动**（`TTS_STATUS_AUDIO=True`） | 0.5–2 s 额外延迟 | `agent.py:86`，`main.py:156`，`config.py:32` |
| 3 | **SerpAPI 外部网络延迟** | 1–4 s | `web_search.py:42` |
| 4 | **LLM 非流式响应** | 增加等待感 | `ollama_llm.py:45`，`openai_llm.py:35` |
| 5 | **最终 TTS 合成（网络调用）** | 1–3 s | `edge_tts_engine.py:26` |

最关键的两个问题是 **瓶颈 1（两轮 LLM）** 和 **瓶颈 2（Status TTS 串行阻塞）**，两者合计占总延迟的绝大部分。

---

## 说明

本文档仅作分析，未对代码进行任何修改。
