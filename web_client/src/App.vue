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
    <div class="process-status" :class="{ show: processStatusText }">{{ processStatusText }}</div>

    <div class="chat" ref="chatRef">
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="bubble"
        :class="msg.type"
      >{{ msg.text }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted } from 'vue'

/* ── Config ────────────────────────────────────────────────────────────────── */
const WS_SCHEME  = location.protocol === 'https:' ? 'wss' : 'ws'
const WS_URL     = `${WS_SCHEME}://${location.host}/ws/audio`
const TARGET_SR  = 16000
const SEND_CHUNK = 8192

/* ── Reactive UI state ─────────────────────────────────────────────────────── */
const dotState          = ref('')       // '' | 'ok' | 'rec' | 'think'
const statusText        = ref('连接中...')
const micState          = ref('')       // '' | 'rec' | 'think'
const isRecording       = ref(false)
const hintText          = ref('按住麦克风说话，松开发送')
const processStatusText = ref('')
const messages          = ref([])
const wsReady           = ref(false)

/* ── Template refs ─────────────────────────────────────────────────────────── */
const waveCanvasRef = ref(null)
const chatRef       = ref(null)

/* ── Non-reactive mutable state ────────────────────────────────────────────── */
let ws             = null
let recording      = false
let audioCtx       = null
let processor      = null
let analyser       = null
let micStream      = null
let audioChunks    = []
let statusAudioBuf = []
let inStatusAudio  = false
let currentPlayback = null
let isPlayingAudio  = false
let streamPlayer    = null
let holdSource      = null
let pendingMsgId    = null
let micPermission   = 'unknown'
let sharedAudioCtx  = null
let _rafId          = 0
let _msgIdCtr       = 0

const _isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
               (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)

/* ── Message helpers ───────────────────────────────────────────────────────── */
function addMessage(type, text) {
  const id = ++_msgIdCtr
  messages.value.push({ id, type, text })
  nextTick(() => {
    if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight
  })
  return id
}

function updateMessage(id, text) {
  const m = messages.value.find(m => m.id === id)
  if (m) m.text = text
}

function removeMessage(id) {
  const i = messages.value.findIndex(m => m.id === id)
  if (i !== -1) messages.value.splice(i, 1)
}

/* ── UI state helpers ──────────────────────────────────────────────────────── */
function setStatus(state, text) {
  dotState.value  = state
  statusText.value = text
}

function _idle(hintMsg = '按住麦克风说话，松开发送') {
  micState.value    = ''
  isRecording.value = false
  setStatus('ok', '已连接')
  hintText.value    = hintMsg
}

/* ── Mic permission ────────────────────────────────────────────────────────── */
function _setMicPermission(state) {
  micPermission = state
  if (state === 'denied') {
    wsReady.value  = false
    hintText.value = '请在浏览器中允许麦克风权限'
  }
}

async function ensureMicPermission() {
  if (!navigator.mediaDevices?.getUserMedia) {
    _setMicPermission('denied')
    hintText.value = '当前浏览器不支持麦克风'
    return false
  }
  if (micPermission === 'granted') return true
  try {
    const tmp = await navigator.mediaDevices.getUserMedia({ audio: true })
    tmp.getTracks().forEach(t => t.stop())
    micPermission = 'granted'
    return true
  } catch {
    _setMicPermission('denied')
    return false
  }
}

/* ── Audio unlock (iOS) ────────────────────────────────────────────────────── */
async function unlockAudio() {
  if (!sharedAudioCtx || sharedAudioCtx.state === 'closed') {
    sharedAudioCtx = new (window.AudioContext || window.webkitAudioContext)()
  }
  if (sharedAudioCtx.state === 'suspended') {
    try { await sharedAudioCtx.resume() } catch {}
  }
  try {
    const buf = sharedAudioCtx.createBuffer(1, 1, 22050)
    const src = sharedAudioCtx.createBufferSource()
    src.buffer = buf
    src.connect(sharedAudioCtx.destination)
    src.start(0)
  } catch {}
}

/* ── Stream player (MediaSource) ───────────────────────────────────────────── */
function createStreamPlayer() {
  if (_isIOS) return null
  if (!window.MediaSource || !MediaSource.isTypeSupported('audio/mpeg')) return null

  const audio = new Audio()
  audio.autoplay = true
  audio.playsInline = true

  const mediaSource = new MediaSource()
  const objectUrl   = URL.createObjectURL(mediaSource)
  audio.src         = objectUrl

  const state = {
    audio, mediaSource,
    sourceBuffer: null,
    queue: [], open: false, done: false, failed: false, objectUrl,
  }

  const flush = () => {
    if (!state.open || !state.sourceBuffer || state.sourceBuffer.updating) return
    if (state.queue.length > 0) {
      const chunk = state.queue.shift()
      try { state.sourceBuffer.appendBuffer(chunk) } catch { state.queue.unshift(chunk) }
      return
    }
    if (state.done && state.mediaSource.readyState === 'open') {
      try { state.mediaSource.endOfStream() } catch {}
    }
  }

  mediaSource.addEventListener('sourceopen', () => {
    state.open = true
    try {
      state.sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg')
      state.sourceBuffer.mode = 'sequence'
      state.sourceBuffer.addEventListener('updateend', flush)
      flush()
    } catch { state.failed = true }
  })

  state.push = (ab) => {
    if (state.failed) return
    isPlayingAudio = true
    state.queue.push(ab)
    flush()
  }

  state.finish = () => { state.done = true; flush() }

  state.stop = () => {
    state.done = true; state.queue = []
    try { audio.pause() } catch {}
    try { audio.removeAttribute('src'); audio.load() } catch {}
    try { URL.revokeObjectURL(objectUrl) } catch {}
    isPlayingAudio = false
  }

  audio.addEventListener('playing', () => { isPlayingAudio = true })
  audio.addEventListener('ended', () => {
    isPlayingAudio = false
    if (streamPlayer === state) { state.stop(); streamPlayer = null }
  })
  audio.addEventListener('pause', () => { if (state.done) isPlayingAudio = false })

  return state
}

/* ── Playback ──────────────────────────────────────────────────────────────── */
async function playChunks(chunks) {
  if (!chunks.length) return
  const blob = new Blob(chunks, { type: 'audio/mpeg' })
  const buf  = await blob.arrayBuffer()

  if (!sharedAudioCtx || sharedAudioCtx.state === 'closed') {
    sharedAudioCtx = new (window.AudioContext || window.webkitAudioContext)()
  }
  const ctx = sharedAudioCtx
  if (ctx.state === 'suspended') {
    try { await ctx.resume() } catch {}
  }

  try {
    const decoded = await ctx.decodeAudioData(buf)
    const src     = ctx.createBufferSource()
    let resolveEnded = null
    const ended = new Promise(r => { resolveEnded = r })
    src.buffer = decoded
    src.connect(ctx.destination)
    src.onended = () => { if (resolveEnded) resolveEnded() }
    currentPlayback = { ctx, src, resolveEnded }
    isPlayingAudio = true
    src.start(0)
    await ended
  } finally {
    if (currentPlayback?.ctx === ctx) currentPlayback = null
    isPlayingAudio = false
  }
}

function stopPlayback() {
  if (streamPlayer) {
    streamPlayer.stop(); streamPlayer = null; audioChunks = []
    return true
  }
  if (!currentPlayback) return false
  const { src, resolveEnded } = currentPlayback
  currentPlayback = null; isPlayingAudio = false
  try { src.onended = null } catch {}
  try { src.stop(0) } catch {}
  try { if (resolveEnded) resolveEnded() } catch {}
  return true
}

/* ── WebSocket ─────────────────────────────────────────────────────────────── */
function connect() {
  ws = new WebSocket(WS_URL)
  ws.binaryType = 'arraybuffer'

  ws.onopen = () => {
    setStatus('ok', '已连接')
    wsReady.value  = true
    hintText.value = '按住麦克风说话，松开发送'
    processStatusText.value = ''
  }

  ws.onclose = () => {
    setStatus('', '已断开，正在重连...')
    wsReady.value = false
    processStatusText.value = '连接已断开，正在重连...'
    _cleanupRecording(false)
    stopPlayback()
    setTimeout(connect, 2500)
  }

  ws.onerror = () => ws.close()

  ws.onmessage = async (evt) => {
    if (evt.data instanceof ArrayBuffer) {
      if (inStatusAudio)                      statusAudioBuf.push(evt.data)
      else if (streamPlayer && !streamPlayer.failed) streamPlayer.push(evt.data)
      else                                    audioChunks.push(evt.data)
      return
    }

    const msg = evt.data

    if (msg === 'DONE') {
      inStatusAudio = false; statusAudioBuf = []
      _idle(); processStatusText.value = ''
      if (streamPlayer && !streamPlayer.failed) {
        streamPlayer.finish()
      } else {
        const mp3 = audioChunks.splice(0)
        if (mp3.length) await playChunks(mp3)
      }

    } else if (msg === 'EMPTY') {
      _idle('未检测到语音，请重试')
      processStatusText.value = ''
      audioChunks = []
      if (pendingMsgId !== null) { removeMessage(pendingMsgId); pendingMsgId = null }
      if (streamPlayer) { streamPlayer.stop(); streamPlayer = null }

    } else if (msg.startsWith('USER_TEXT:')) {
      const txt = msg.slice(10).trim()
      if (pendingMsgId !== null) {
        updateMessage(pendingMsgId, txt || '未识别到语音')
        pendingMsgId = null
      } else if (txt) {
        addMessage('user', txt)
      }

    } else if (msg.startsWith('ASSISTANT_TEXT:')) {
      inStatusAudio = false; statusAudioBuf = []
      const txt = msg.slice(15).trim()
      if (txt) addMessage('assistant', txt)

    } else if (msg.startsWith('STATUS:')) {
      processStatusText.value = msg.slice(7)
      inStatusAudio = true; statusAudioBuf = []

    } else if (msg === 'STATUS_AUDIO_DONE') {
      inStatusAudio = false
      const clips = statusAudioBuf.splice(0)
      if (clips.length) await playChunks(clips)

    } else if (msg.startsWith('ERROR:')) {
      inStatusAudio = false; statusAudioBuf = []
      _idle('出错了，请重试')
      processStatusText.value = '处理失败'
      addMessage('info', '⚠️ ' + msg.slice(6))
      audioChunks = []
      if (pendingMsgId !== null) { removeMessage(pendingMsgId); pendingMsgId = null }
      if (streamPlayer) { streamPlayer.stop(); streamPlayer = null }
    }
    // 'PONG': ignore
  }

  setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) ws.send('PING')
  }, 20000)
}

/* ── Microphone ────────────────────────────────────────────────────────────── */
async function startRecording() {
  if (recording) return
  const granted = await ensureMicPermission()
  if (!granted) return

  if (streamPlayer) { streamPlayer.stop(); streamPlayer = null }

  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount:     1,
        sampleRate:       TARGET_SR,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl:  true,
      },
    })
  } catch (e) {
    hintText.value = '无法访问麦克风：' + e.message
    return
  }

  audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: TARGET_SR })
  const actualSR = audioCtx.sampleRate
  const source   = audioCtx.createMediaStreamSource(micStream)

  analyser = audioCtx.createAnalyser()
  analyser.fftSize = 256
  source.connect(analyser)

  processor = audioCtx.createScriptProcessor(4096, 1, 1)
  let overflow = new Int16Array(0)

  processor.onaudioprocess = (e) => {
    if (!recording) return
    const f32      = e.inputBuffer.getChannelData(0)
    const resampled = (actualSR === TARGET_SR) ? f32 : resample(f32, actualSR, TARGET_SR)
    const i16      = f32ToI16(resampled)

    const merged = new Int16Array(overflow.length + i16.length)
    merged.set(overflow)
    merged.set(i16, overflow.length)
    overflow = merged

    while (overflow.byteLength >= SEND_CHUNK) {
      const slice = overflow.slice(0, SEND_CHUNK >> 1)
      overflow    = overflow.slice(SEND_CHUNK >> 1)
      if (ws?.readyState === WebSocket.OPEN) ws.send(slice.buffer)
    }
  }

  analyser.connect(processor)
  processor.connect(audioCtx.destination)

  recording         = true
  isRecording.value = true
  audioChunks       = []
  processStatusText.value = ''
  micState.value    = 'rec'
  setStatus('rec', '录音中...')
  hintText.value    = '松开发送'
  pendingMsgId      = addMessage('user', '正在听你说...')
  drawWave()
}

function stopRecording() {
  if (!recording) return
  recording = false
  _cleanupRecording(true)
}

function _cleanupRecording(sendEnd) {
  cancelAnimationFrame(_rafId)
  isRecording.value = false
  if (processor) { processor.disconnect(); processor = null }
  if (analyser)  { analyser.disconnect();  analyser  = null }
  if (audioCtx)  { audioCtx.close();       audioCtx  = null }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null }

  if (sendEnd && ws?.readyState === WebSocket.OPEN) {
    audioChunks = []
    if (streamPlayer) streamPlayer.stop()
    streamPlayer = createStreamPlayer()
    ws.send('END')
    micState.value = 'think'
    setStatus('think', 'AI 思考中...')
    hintText.value          = '正在处理...'
    processStatusText.value = '正在处理...'
  }
}

/* ── Press-to-talk ─────────────────────────────────────────────────────────── */
async function beginPressToTalk(source) {
  if (holdSource || recording) return
  holdSource = source

  unlockAudio()

  if (isPlayingAudio) stopPlayback()

  if (ws?.readyState !== WebSocket.OPEN) {
    holdSource = null
    hintText.value = '连接未就绪，请稍后'
    return
  }

  if (micPermission !== 'granted') {
    const granted = await ensureMicPermission()
    if (!granted) { holdSource = null; return }
  }

  await startRecording()

  if (!recording) { holdSource = null; return }

  if (holdSource !== source) stopRecording()
}

function endPressToTalk(source) {
  if (holdSource !== source) return
  holdSource = null
  if (recording) stopRecording()
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

/* ── Waveform ──────────────────────────────────────────────────────────────── */
function drawWave() {
  if (!analyser || !waveCanvasRef.value) return
  _rafId = requestAnimationFrame(drawWave)

  const canvas = waveCanvasRef.value
  const wCtx   = canvas.getContext('2d')
  const W = canvas.width, H = canvas.height
  const data = new Uint8Array(analyser.frequencyBinCount)
  analyser.getByteTimeDomainData(data)

  wCtx.clearRect(0, 0, W, H)
  const cx = W / 2, cy = H / 2, r = W / 2 - 14
  const step = (2 * Math.PI) / data.length

  wCtx.beginPath()
  for (let i = 0; i < data.length; i++) {
    const amp   = ((data[i] / 128) - 1) * 16
    const angle = i * step - Math.PI / 2
    const x = cx + (r + amp) * Math.cos(angle)
    const y = cy + (r + amp) * Math.sin(angle)
    i === 0 ? wCtx.moveTo(x, y) : wCtx.lineTo(x, y)
  }
  wCtx.closePath()
  wCtx.strokeStyle = 'rgba(124,111,247,0.65)'
  wCtx.lineWidth   = 2
  wCtx.stroke()
}

/* ── DSP helpers ───────────────────────────────────────────────────────────── */
function f32ToI16(buf) {
  const out = new Int16Array(buf.length)
  for (let i = 0; i < buf.length; i++)
    out[i] = Math.max(-32768, Math.min(32767, buf[i] * 32768))
  return out
}

function resample(src, fromSR, toSR) {
  const ratio = fromSR / toSR
  const len   = Math.floor(src.length / ratio)
  const out   = new Float32Array(len)
  for (let i = 0; i < len; i++) {
    const pos = i * ratio
    const lo  = Math.floor(pos)
    const hi  = Math.min(lo + 1, src.length - 1)
    out[i]    = src[lo] + (src[hi] - src[lo]) * (pos - lo)
  }
  return out
}

/* ── Lifecycle ─────────────────────────────────────────────────────────────── */
onMounted(() => {
  connect()
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup',   onKeyUp)
  window.addEventListener('blur',    onWindowBlur)
})

onUnmounted(() => {
  if (ws) ws.close()
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keyup',   onKeyUp)
  window.removeEventListener('blur',    onWindowBlur)
  cancelAnimationFrame(_rafId)
  if (sharedAudioCtx) { try { sharedAudioCtx.close() } catch {} }
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

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", sans-serif;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: env(safe-area-inset-top, 1.5rem) 1rem
           env(safe-area-inset-bottom, 1rem);
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
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* ── Header ──────────────────────────────────────────────────────────────── */
header {
  text-align: center;
  padding: 2.5rem 0 1.5rem;
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
  margin-bottom: 2.5rem;
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
  margin: 0.5rem 0 1.5rem;
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

.hint {
  color: var(--text-muted);
  font-size: 0.83rem;
  text-align: center;
  min-height: 1.2em;
}

.process-status {
  min-height: 1.4em;
  margin-top: 0.65rem;
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
  min-height: 0;
  margin-top: 1.8rem;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0 2px 1rem;
  overflow-y: auto;
  overscroll-behavior: contain;
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
