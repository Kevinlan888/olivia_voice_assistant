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
let processor         = null
let audioWorkletNode  = null
let analyser          = null
let micStream         = null
let rawChunks      = []    // Float32Array chunks at native sample rate
let nativeSR       = TARGET_SR
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
let _connectAttempt = 0
let _connectAt      = 0   // timestamp of last new WebSocket()

const _isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
               (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)

/* ── Logger ────────────────────────────────────────────────────────────────── */
function log(fmt, ...args) {
  const t = new Date().toISOString().slice(11, 23) // HH:MM:SS.mmm
  // vConsole doesn't expand %s/%d — interpolate manually
  let i = 0
  const msg = fmt.replace(/%[sd]/g, () => {
    const v = args[i++]
    return v === undefined ? '' : v
  })
  const rest = args.slice(i)
  console.log(`[Olivia ${t}] ${msg}`, ...rest)
}

log('Page loaded. isIOS=%s UA=%s', _isIOS, navigator.userAgent)
log('WS_URL=%s', WS_URL)
log('visibility=%s', document.visibilityState)

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
let _connectTimeoutId = null

function _clearConnectTimeout() {
  if (_connectTimeoutId !== null) { clearTimeout(_connectTimeoutId); _connectTimeoutId = null }
}

function connect() {
  // Avoid stacking multiple pending connections
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    log('[WS] connect() skipped — already readyState=%s', ws.readyState)
    return
  }

  _connectAttempt++
  _connectAt = performance.now()
  log('[WS] connect() attempt #%d  visibility=%s  online=%s',
      _connectAttempt, document.visibilityState, navigator.onLine)
  ws = new WebSocket(WS_URL)
  ws.binaryType = 'arraybuffer'

  // Timeout: if still CONNECTING after 8 s, iOS Safari is likely blocking the
  // WSS handshake due to an untrusted certificate. Force-close and retry.
  _clearConnectTimeout()
  _connectTimeoutId = setTimeout(() => {
    if (ws && ws.readyState === WebSocket.CONNECTING) {
      log('[WS] TIMEOUT — still CONNECTING after 8 s. Possible cause: ' +
          'untrusted cert (install mkcert CA on iOS) or network issue. Forcing close.')
      ws.close()
    }
  }, 8000)

  ws.onopen = () => {
    _clearConnectTimeout()
    const elapsed = (performance.now() - _connectAt).toFixed(0)
    log('[WS] onopen  attempt #%d  elapsed=%sms', _connectAttempt, elapsed)
    setStatus('ok', '已连接')
    wsReady.value  = true
    hintText.value = '按住麦克风说话，松开发送'
    processStatusText.value = ''
  }

  ws.onclose = (evt) => {
    _clearConnectTimeout()
    log('[WS] onclose  code=%d  reason=%s  wasClean=%s',
        evt.code, evt.reason || '(none)', evt.wasClean)
    setStatus('', '已断开，正在重连...')
    wsReady.value = false
    processStatusText.value = '连接已断开，正在重连...'
    _cleanupRecording(false)
    stopPlayback()
    setTimeout(connect, 2500)
  }

  ws.onerror = (evt) => {
    log('[WS] onerror  type=%s  readyState=%s', evt.type, ws.readyState)
    ws.close()
  }

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

  // Create AudioContext at the device's native sample rate.
  // iOS Safari ignores a forced sampleRate, so we always capture at native
  // rate and resample offline on stop via OfflineAudioContext (much higher
  // quality than manual linear interpolation).
  audioCtx = new (window.AudioContext || window.webkitAudioContext)()
  nativeSR = audioCtx.sampleRate
  log('[Rec] AudioContext sampleRate=%d', nativeSR)
  const source   = audioCtx.createMediaStreamSource(micStream)

  analyser = audioCtx.createAnalyser()
  analyser.fftSize = 256
  source.connect(analyser)

  rawChunks = []

  // Prefer AudioWorklet (runs on audio thread → no main-thread dropouts).
  // Fall back to the deprecated ScriptProcessor for very old browsers.
  let usedWorklet = false
  if (audioCtx.audioWorklet) {
    try {
      const workletCode = `
class RecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0]?.[0]
    if (ch && ch.length > 0) this.port.postMessage(ch.slice())
    return true
  }
}
registerProcessor('recorder-processor', RecorderProcessor)`
      const blob = new Blob([workletCode], { type: 'application/javascript' })
      const url  = URL.createObjectURL(blob)
      try { await audioCtx.audioWorklet.addModule(url) } finally { URL.revokeObjectURL(url) }
      audioWorkletNode = new AudioWorkletNode(audioCtx, 'recorder-processor')
      audioWorkletNode.port.onmessage = (e) => {
        if (recording) rawChunks.push(new Float32Array(e.data))
      }
      analyser.connect(audioWorkletNode)
      audioWorkletNode.connect(audioCtx.destination)
      usedWorklet = true
      log('[Rec] Using AudioWorklet')
    } catch (err) {
      log('[Rec] AudioWorklet init failed, falling back to ScriptProcessor: %s', err)
      if (audioWorkletNode) { try { audioWorkletNode.disconnect() } catch {} audioWorkletNode = null }
    }
  }

  if (!usedWorklet) {
    processor = audioCtx.createScriptProcessor(4096, 1, 1)
    processor.onaudioprocess = (e) => {
      if (!recording) return
      rawChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
    }
    analyser.connect(processor)
    processor.connect(audioCtx.destination)
    log('[Rec] Using ScriptProcessor (fallback)')
  }

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
  if (audioWorkletNode) { audioWorkletNode.disconnect(); audioWorkletNode = null }
  if (processor)        { processor.disconnect();        processor         = null }
  if (analyser)         { analyser.disconnect();         analyser          = null }
  if (audioCtx)  { audioCtx.close();       audioCtx  = null }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null }

  if (sendEnd && ws?.readyState === WebSocket.OPEN) {
    audioChunks = []
    if (streamPlayer) streamPlayer.stop()
    streamPlayer = createStreamPlayer()
    micState.value = 'think'
    setStatus('think', 'AI 思考中...')
    hintText.value          = '正在处理...'
    processStatusText.value = '正在处理...'
    const chunks = rawChunks.splice(0)
    const sr     = nativeSR
    _resampleAndSend(chunks, sr)  // async, fire-and-forget
  } else {
    rawChunks = []
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

// Resample & send via OfflineAudioContext, then fire END.
// Called after the user releases the mic button.
async function _resampleAndSend(chunks, fromSR) {
  if (!chunks.length) { if (ws?.readyState === WebSocket.OPEN) ws.send('END'); return }

  // Concatenate all captured Float32 chunks
  const totalLen = chunks.reduce((s, c) => s + c.length, 0)
  const merged   = new Float32Array(totalLen)
  let off = 0
  for (const c of chunks) { merged.set(c, off); off += c.length }

  // Resample to 16 kHz using the browser's built-in resampler.
  // OfflineAudioContext handles the anti-aliasing correctly; simple linear
  // interpolation (the old approach) caused audible distortion on iOS.
  let resampled
  if (fromSR === TARGET_SR) {
    resampled = merged
  } else {
    const outLen = Math.ceil(totalLen * TARGET_SR / fromSR)
    const offCtx = new OfflineAudioContext(1, outLen, TARGET_SR)
    const buf    = offCtx.createBuffer(1, totalLen, fromSR)
    buf.getChannelData(0).set(merged)
    const src = offCtx.createBufferSource()
    src.buffer = buf
    src.connect(offCtx.destination)
    src.start(0)
    const rendered = await offCtx.startRendering()
    resampled = rendered.getChannelData(0)
  }
  log('[Rec] resampled %d → %d samples (%dHz → %dHz)', totalLen, resampled.length, fromSR, TARGET_SR)

  // Convert to Int16 and send in chunks
  const i16       = f32ToI16(resampled)
  const chunkSize = SEND_CHUNK >> 1   // samples per chunk
  for (let i = 0; i < i16.length; i += chunkSize) {
    if (ws?.readyState !== WebSocket.OPEN) return
    ws.send(i16.slice(i, i + chunkSize).buffer)
  }
  if (ws?.readyState === WebSocket.OPEN) ws.send('END')
}

/* ── Visibility / background handling ────────────────────────────────────── */
function onVisibilityChange() {
  log('[Page] visibilitychange → %s  wsReadyState=%s',
      document.visibilityState, ws ? ws.readyState : 'no-ws')

  if (document.visibilityState === 'visible') {
    // iOS may silently kill the WS while backgrounded; force reconnect if needed
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      log('[Page] visible — WS dead, reconnecting immediately')
      connect()
    } else if (ws.readyState === WebSocket.OPEN) {
      // Send a PING to verify the connection is actually alive
      log('[Page] visible — WS appears open, sending PING to verify')
      try { ws.send('PING') } catch (e) { log('[Page] PING failed: %s', e); ws.close() }
    }
  } else {
    log('[Page] hidden — WS will likely be frozen/killed by iOS')
  }
}

function onPageShow(evt) {
  log('[Page] pageshow  persisted=%s (bfcache=%s)  wsReadyState=%s',
      evt.persisted, evt.persisted ? 'YES — restored from cache' : 'no',
      ws ? ws.readyState : 'no-ws')
  // bfcache restore on iOS: page looks alive but WS is dead
  if (evt.persisted && ws && ws.readyState !== WebSocket.OPEN) {
    log('[Page] bfcache restore + dead WS, reconnecting')
    connect()
  }
}

function onPageHide(evt) {
  log('[Page] pagehide  persisted=%s', evt.persisted)
}

function onOnline()  { log('[Net] online') }
function onOffline() { log('[Net] offline') }

/* ── Lifecycle ─────────────────────────────────────────────────────────────── */
onMounted(() => {
  connect()
  window.addEventListener('keydown',          onKeyDown)
  window.addEventListener('keyup',            onKeyUp)
  window.addEventListener('blur',             onWindowBlur)
  document.addEventListener('visibilitychange', onVisibilityChange)
  window.addEventListener('pageshow',         onPageShow)
  window.addEventListener('pagehide',         onPageHide)
  window.addEventListener('online',           onOnline)
  window.addEventListener('offline',          onOffline)
})

onUnmounted(() => {
  if (ws) ws.close()
  window.removeEventListener('keydown',          onKeyDown)
  window.removeEventListener('keyup',            onKeyUp)
  window.removeEventListener('blur',             onWindowBlur)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('pageshow',         onPageShow)
  window.removeEventListener('pagehide',         onPageHide)
  window.removeEventListener('online',           onOnline)
  window.removeEventListener('offline',          onOffline)
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
