<template>
  <div class="app-shell">
    <header>
      <h1>OLIVIA</h1>
      <p>AI 语音助手</p>
    </header>

    <div class="status-pill">
      <div class="dot" :class="dotState"></div>
      <span>{{ statusText }}</span>
    </div>

    <div class="chat" ref="chatRef">
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="bubble"
        :class="msg.type"
      >{{ msg.text }}</div>
    </div>

    <div class="bottom-bar">
      <div class="process-status" :class="{ show: processStatusText }">{{ processStatusText }}</div>

      <div class="mic-area">
        <canvas
          ref="waveCanvasRef"
          class="wave-canvas"
          :class="{ show: isRecording }"
          width="140"
          height="140"
        ></canvas>
        <div class="ring" :class="{ show: isRecording }"></div>
        <button
          class="mic-btn"
          :class="micState"
          :disabled="!wsReady"
          @pointerdown.prevent="onPointerDown"
          @pointerup.prevent="onPointerUp"
          @pointercancel="onPointerCancel"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="2" width="6" height="13" rx="3"/>
            <path d="M5 10a7 7 0 0 0 14 0"/>
            <line x1="12" y1="19" x2="12" y2="22"/>
            <line x1="9"  y1="22" x2="15" y2="22"/>
          </svg>
        </button>
      </div>

      <p class="hint">{{ hintText }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { log, IS_IOS } from './composables/logger'
import { useChat } from './composables/useChat'
import { usePlayback } from './composables/usePlayback'
import { useRecorder } from './composables/useRecorder'
import { useConnection } from './composables/useConnection'

/* ── Config ────────────────────────────────────────────────────────────────── */
const WS_SCHEME = location.protocol === 'https:' ? 'wss' : 'ws'
const WS_URL    = `${WS_SCHEME}://${location.host}/ws/audio`

log('Page loaded. isIOS=%s UA=%s', IS_IOS, navigator.userAgent)
log('WS_URL=%s', WS_URL)
log('visibility=%s', document.visibilityState)

/* ── Reactive UI state ─────────────────────────────────────────────────────── */
const dotState          = ref('')       // '' | 'ok' | 'rec' | 'think'
const statusText        = ref('连接中...')
const micState          = ref('')       // '' | 'rec' | 'think'
const hintText          = ref('按住麦克风说话，松开发送')
const processStatusText = ref('')

/* ── Template refs ─────────────────────────────────────────────────────────── */
const waveCanvasRef = ref(null)
const chatRef       = ref(null)

/* ── Composables ───────────────────────────────────────────────────────────── */
const chat     = useChat(chatRef)
const playback = usePlayback()
const recorder = useRecorder(waveCanvasRef, {
  onMicDenied() {
    conn.wsReady.value = false
    hintText.value = '请在浏览器中允许麦克风权限'
  },
})
const conn = useConnection(WS_URL, {
  onOpen()  {
    setStatus('ok', '已连接')
    hintText.value = '按住麦克风说话，松开发送'
    processStatusText.value = ''
  },
  onClose() {
    setStatus('', '已断开，正在重连...')
    processStatusText.value = '连接已断开，正在重连...'
    recorder.cancelRecording()
    playback.stopPlayback()
  },
  onBinary(data) { playback.pushAudioData(data) },
  onText(msg)    { handleMessage(msg) },
  onEvent(ev)    { handleEvent(ev) },
})

const { messages }   = chat
const { wsReady }    = conn
const { isRecording } = recorder

/* ── Non-reactive orchestration state ──────────────────────────────────────── */
let holdSource  = null
let pendingMsgId = null
let streamingAssistantId = null   // tracks the bubble being built by llm_token events

/* ── UI helpers ────────────────────────────────────────────────────────────── */
function setStatus(state, text) {
  dotState.value   = state
  statusText.value = text
}

function _idle(hint = '按住麦克风说话，松开发送') {
  micState.value = ''
  setStatus('ok', '已连接')
  hintText.value = hint
}

/* ── WS message routing ───────────────────────────────────────────────────── */
function handleMessage(msg) {
  try {
    if (msg === 'DONE') {
      _idle(); processStatusText.value = ''
      playback.finishResponse()

    } else if (msg === 'EMPTY') {
      _idle('未检测到语音，请重试')
      processStatusText.value = ''
      playback.discardBuffers()
      if (pendingMsgId !== null) { chat.removeMessage(pendingMsgId); pendingMsgId = null }

    } else if (msg.startsWith('USER_TEXT:')) {
      const txt = msg.slice(9).trim()
      if (pendingMsgId !== null) {
        chat.updateMessage(pendingMsgId, txt || '未识别到语音')
        pendingMsgId = null
      } else if (txt) {
        chat.addMessage('user', txt)
      }

    } else if (msg.startsWith('ASSISTANT_TEXT:')) {
      playback.resetStatusAudio()
      const txt = msg.slice(15).trim()
      if (txt) chat.addMessage('assistant', txt)

    } else if (msg.startsWith('STATUS:')) {
      processStatusText.value = msg.slice(7)
      playback.beginStatusAudio()

    } else if (msg === 'STATUS_AUDIO_DONE') {
      playback.endStatusAudio()

    } else if (msg.startsWith('ERROR:')) {
      playback.resetStatusAudio()
      _idle('出错了，请重试')
      processStatusText.value = '处理失败'
      chat.addMessage('info', '⚠️ ' + msg.slice(6))
      playback.discardBuffers()
      if (pendingMsgId !== null) { chat.removeMessage(pendingMsgId); pendingMsgId = null }
    }
    // 'PONG': ignore
  } catch (err) {
    log('[WS] message handler error: %s', err)
    _idle('出错了，请重试')
    processStatusText.value = ''
    playback.discardBuffers()
    if (pendingMsgId !== null) { chat.removeMessage(pendingMsgId); pendingMsgId = null }
  }
}

/* ── v2 event routing ─────────────────────────────────────────────────────── */
function handleEvent(ev) {
  try {
    switch (ev.event) {
      case 'user_text': {
        const txt = (ev.text || '').trim()
        if (pendingMsgId !== null) {
          chat.updateMessage(pendingMsgId, txt || '未识别到语音')
          pendingMsgId = null
        } else if (txt) {
          chat.addMessage('user', txt)
        }
        break
      }

      case 'llm_token': {
        // Progressive assistant text — build the bubble incrementally
        const token = ev.token || ''
        if (streamingAssistantId === null) {
          playback.resetStatusAudio()
          streamingAssistantId = chat.addMessage('assistant', token)
        } else {
          chat.appendMessage(streamingAssistantId, token)
        }
        break
      }

      case 'assistant_text': {
        // Full assistant text (fallback if streaming was off)
        playback.resetStatusAudio()
        const txt = (ev.text || '').trim()
        if (streamingAssistantId !== null) {
          // Replace streamed content with final text
          chat.updateMessage(streamingAssistantId, txt)
          streamingAssistantId = null
        } else if (txt) {
          chat.addMessage('assistant', txt)
        }
        break
      }

      case 'status':
        processStatusText.value = ev.text || ''
        // v2 does not send status audio binary frames, so do NOT enter
        // status-audio buffering mode — that would swallow reply audio.
        break

      case 'status_audio_done':
        playback.endStatusAudio()
        break

      case 'tool_start':
        processStatusText.value = ev.tool || '正在调用工具...'
        break

      case 'tool_end':
        // processStatusText will be overwritten by next event
        break

      case 'agent_start':
        log('[v2] agent_start: %s', ev.agent)
        break

      case 'agent_end':
        log('[v2] agent_end: %s', ev.agent)
        break

      case 'handoff':
        log('[v2] handoff → %s', ev.to_agent)
        break

      case 'empty':
        _idle('未检测到语音，请重试')
        processStatusText.value = ''
        playback.discardBuffers()
        if (pendingMsgId !== null) { chat.removeMessage(pendingMsgId); pendingMsgId = null }
        streamingAssistantId = null
        break

      case 'done':
      case 'audio_done':
        _idle()
        processStatusText.value = ''
        playback.finishResponse()
        streamingAssistantId = null
        break

      case 'error':
        playback.resetStatusAudio()
        _idle('出错了，请重试')
        processStatusText.value = '处理失败'
        chat.addMessage('info', '⚠️ ' + (ev.message || ev.text || '未知错误'))
        playback.discardBuffers()
        if (pendingMsgId !== null) { chat.removeMessage(pendingMsgId); pendingMsgId = null }
        streamingAssistantId = null
        break

      default:
        log('[v2] unknown event: %s', ev.event)
    }
  } catch (err) {
    log('[v2] event handler error: %s', err)
    _idle('出错了，请重试')
    processStatusText.value = ''
    playback.discardBuffers()
    if (pendingMsgId !== null) { chat.removeMessage(pendingMsgId); pendingMsgId = null }
    streamingAssistantId = null
  }
}

/* ── Press-to-talk ─────────────────────────────────────────────────────────── */
async function beginPressToTalk(source) {
  if (holdSource || recorder.isActive) return
  holdSource = source

  await playback.unlockAudio()

  if (playback.isPlaying()) playback.stopPlayback()

  if (!conn.isOpen()) {
    holdSource = null
    hintText.value = '连接未就绪，请稍后'
    return
  }

  const perm = await recorder.ensureMicPermission()
  if (!perm.granted) {
    holdSource = null
    if (perm.hint) hintText.value = perm.hint
    return
  }

  playback.stopPlayback()

  const result = await recorder.startRecording()
  if (result && result.error) {
    holdSource = null
    hintText.value = result.error
    return
  }
  if (!recorder.isActive) { holdSource = null; return }

  // UI: recording started
  processStatusText.value = ''
  micState.value    = 'rec'
  setStatus('rec', '录音中...')
  hintText.value    = '松开发送'
  pendingMsgId      = chat.addMessage('user', '正在听你说...')

  if (holdSource !== source) finishRecording()
}

function endPressToTalk(source) {
  if (holdSource !== source) return
  holdSource = null
  if (recorder.isActive) finishRecording()
}

function finishRecording() {
  const data = recorder.stopRecording()

  if (!data || !conn.isOpen()) return

  // UI: transition to thinking
  playback.prepareForResponse()
  micState.value = 'think'
  setStatus('think', 'AI 思考中...')
  hintText.value          = '正在处理...'
  processStatusText.value = '正在处理...'

  // Resample and send (fire-and-forget)
  recorder.resampleAndSend(data.chunks, data.sampleRate, (buf) => {
    conn.send(buf)
  }).catch(() => {
    _idle('处理录音失败，请重试')
    processStatusText.value = ''
    if (pendingMsgId !== null) { chat.removeMessage(pendingMsgId); pendingMsgId = null }
    playback.discardBuffers()
  })
}

/* ── Button event handlers ─────────────────────────────────────────────────── */
function onPointerDown(evt) {
  try { evt.currentTarget.setPointerCapture(evt.pointerId) } catch {}
  beginPressToTalk('pointer')
}

function onPointerUp(evt) {
  try { evt.currentTarget.releasePointerCapture(evt.pointerId) } catch {}
  endPressToTalk('pointer')
}

function onPointerCancel() {
  endPressToTalk('pointer')
}

/* ── Keyboard ──────────────────────────────────────────────────────────────── */
function onKeyDown(evt) {
  if (evt.code !== 'Space') return
  if (evt.repeat) { evt.preventDefault(); return }
  const tag = evt.target?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || evt.target?.isContentEditable) return
  evt.preventDefault()
  beginPressToTalk('space')
}

function onKeyUp(evt) {
  if (evt.code !== 'Space') return
  evt.preventDefault()
  endPressToTalk('space')
}

function onWindowBlur() {
  if (holdSource) endPressToTalk(holdSource)
}

/* ── Lifecycle ─────────────────────────────────────────────────────────────── */
onMounted(() => {
  conn.connect()
  recorder.syncMicPermission()
  window.addEventListener('keydown',            onKeyDown)
  window.addEventListener('keyup',              onKeyUp)
  window.addEventListener('blur',               onWindowBlur)
  document.addEventListener('visibilitychange', conn.onVisibilityChange)
  window.addEventListener('pageshow',           conn.onPageShow)
  window.addEventListener('pagehide',           conn.onPageHide)
  window.addEventListener('online',             conn.onOnline)
  window.addEventListener('offline',            conn.onOffline)
})

onUnmounted(() => {
  conn.destroy()
  playback.destroy()
  window.removeEventListener('keydown',            onKeyDown)
  window.removeEventListener('keyup',              onKeyUp)
  window.removeEventListener('blur',               onWindowBlur)
  document.removeEventListener('visibilitychange', conn.onVisibilityChange)
  window.removeEventListener('pageshow',           conn.onPageShow)
  window.removeEventListener('pagehide',           conn.onPageHide)
  window.removeEventListener('online',             conn.onOnline)
  window.removeEventListener('offline',            conn.onOffline)
})
</script>

<style>
:root {
  --bg:           #0d0d1a;
  --surface:      #16162a;
  --surface2:     #1e1e35;
  --accent:       #7c6ff7;
  --accent-dim:   rgba(124,111,247,0.18);
  --accent-glow:  rgba(124,111,247,0.35);
  --text:         #e4e4f0;
  --text-muted:   #7070a0;
  --green:        #4eeaaa;
  --red:          #ff6b6b;
  --radius:       14px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, #app {
  height: 100%;
  min-height: 0;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", sans-serif;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  align-items: center;
  /* horizontal + top padding only; bottom handled by fixed bar */
  padding: env(safe-area-inset-top, 1.5rem) 1rem 0;
  overflow: hidden;
  -webkit-tap-highlight-color: transparent;
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;
}

.app-shell {
  width: 100%;
  max-width: 480px;
  flex: 1;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  overflow: hidden;
  /* leave room for the fixed bottom bar (~190px) */
  padding-bottom: 190px;
}

/* ── Header ──────────────────────────────────────────────────────────────── */
header {
  text-align: center;
  padding: 1.2rem 0 0.8rem;
}
header h1 {
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  background: linear-gradient(135deg, #a89af7, #6ee7f7);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
header p { color: var(--text-muted); font-size: 0.82rem; margin-top: 4px; }

/* ── Status pill ─────────────────────────────────────────────────────────── */
.status-pill {
  display: flex;
  align-items: center;
  gap: 7px;
  background: var(--surface);
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 0.82rem;
  color: var(--text-muted);
  margin-bottom: 0.75rem;
}
.dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  flex-shrink: 0;
  transition: background 0.3s;
}
.dot.ok    { background: var(--green); }
.dot.rec   { background: var(--red);    animation: blink 0.9s infinite; }
.dot.think { background: var(--accent); animation: blink 0.5s infinite; }

@keyframes blink {
  0%,100% { opacity: 1; } 50% { opacity: 0.25; }
}

/* ── Mic button ──────────────────────────────────────────────────────────── */
.mic-area {
  position: relative;
  margin: 0.8rem 0 0.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ring {
  position: absolute;
  inset: -14px;
  border-radius: 50%;
  border: 2.5px solid var(--accent);
  opacity: 0;
  pointer-events: none;
}
.ring.show { animation: ripple 1.1s ease-out infinite; }
@keyframes ripple {
  0%   { opacity: 0.8; transform: scale(1);   }
  100% { opacity: 0;   transform: scale(1.35); }
}

.wave-canvas {
  position: absolute;
  inset: -24px;
  border-radius: 50%;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.3s;
}
.wave-canvas.show { opacity: 1; }

.mic-btn {
  position: relative;
  width: 92px; height: 92px;
  border-radius: 50%;
  border: none;
  background: var(--surface2);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 32px rgba(0,0,0,0.45);
  transition: background 0.25s, box-shadow 0.25s, transform 0.1s;
  outline: none;
}
.mic-btn:active          { transform: scale(0.93); }
.mic-btn.rec             { background: #2a1020; box-shadow: 0 0 0 0 #0000, 0 6px 28px rgba(255,80,80,0.25); }
.mic-btn.think           { background: #12123a; box-shadow: 0 0 20px var(--accent-glow); }
.mic-btn:disabled        { opacity: 0.4; cursor: not-allowed; }
.mic-btn svg             { width: 38px; height: 38px; color: var(--text); }
.mic-btn.rec svg         { color: var(--red); }
.mic-btn.think svg       { color: var(--accent); }
.mic-btn, .mic-area      { touch-action: manipulation; }

/* ── Bottom bar ──────────────────────────────────────────────────────────── */
.bottom-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--bg);
  /* subtle top border to separate from chat */
  border-top: 1px solid rgba(124,111,247,0.12);
  padding-top: 0.2rem;
  padding-bottom: env(safe-area-inset-bottom, 1rem);
  z-index: 10;
}

.hint {
  color: var(--text-muted);
  font-size: 0.83rem;
  text-align: center;
  min-height: 1.2em;
}

.process-status {
  min-height: 1.4em;
  margin-top: 0.4rem;
  padding: 0 0.75rem;
  color: #a89af7;
  font-size: 0.8rem;
  text-align: center;
  opacity: 0;
  transform: translateY(-2px);
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.process-status.show {
  opacity: 1;
  transform: translateY(0);
}

/* ── Chat log ────────────────────────────────────────────────────────────── */
.chat {
  width: 100%;
  flex: 1;
  flex-basis: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0.5rem 2px 0.5rem;
  overflow-y: auto;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior: contain;
  touch-action: pan-y;
  scrollbar-width: thin;
  scrollbar-color: rgba(124,111,247,0.45) transparent;
}
.chat::-webkit-scrollbar       { width: 6px; }
.chat::-webkit-scrollbar-thumb { background: rgba(124,111,247,0.45); border-radius: 999px; }
.chat::-webkit-scrollbar-track { background: transparent; }

.bubble {
  padding: 9px 14px;
  border-radius: var(--radius);
  font-size: 0.88rem;
  line-height: 1.55;
  max-width: 82%;
  animation: pop 0.25s cubic-bezier(.34,1.6,.64,1);
}
@keyframes pop {
  from { opacity: 0; transform: scale(0.88) translateY(6px); }
  to   { opacity: 1; transform: scale(1)    translateY(0); }
}
.bubble.user {
  background: var(--accent);
  color: #fff;
  align-self: flex-end;
  border-bottom-right-radius: 4px;
}
.bubble.assistant {
  background: var(--surface2);
  color: var(--text);
  align-self: flex-start;
  border-bottom-left-radius: 4px;
}
.bubble.info {
  background: transparent;
  color: var(--text-muted);
  font-size: 0.78rem;
  align-self: center;
  font-style: italic;
}
</style>
