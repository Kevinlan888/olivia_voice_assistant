import { ref } from 'vue'
import { log } from './logger'

const TARGET_SR  = 16000
const SEND_CHUNK = 8192

export function useRecorder(waveCanvasRef, { onMicDenied } = {}) {
  const isRecording = ref(false)

  let recording        = false
  let audioCtx         = null
  let processor        = null
  let audioWorkletNode = null
  let analyser         = null
  let micStream        = null
  let rawChunks        = []
  let nativeSR         = TARGET_SR
  let micPermission    = 'unknown'
  let _rafId           = 0

  /* ── Mic permission ──────────────────────────────────────────────── */
  function _setMicPermission(state) {
    micPermission = state
    if (state === 'denied') onMicDenied?.()
  }

  async function syncMicPermission() {
    if (!navigator.permissions?.query) return micPermission
    try {
      const status = await navigator.permissions.query({ name: 'microphone' })
      _setMicPermission(status.state)
      status.onchange = () => _setMicPermission(status.state)
      return status.state
    } catch {
      return micPermission
    }
  }

  /**
   * Returns { granted: true } or { granted: false, hint: string }.
   */
  async function ensureMicPermission() {
    if (!navigator.mediaDevices?.getUserMedia) {
      _setMicPermission('denied')
      return { granted: false, hint: '当前浏览器不支持麦克风' }
    }
    const state = await syncMicPermission()
    if (state === 'granted') return { granted: true }
    if (state === 'denied') {
      _setMicPermission('denied')
      return { granted: false, hint: '请在浏览器中允许麦克风权限' }
    }
    return { granted: true } // 'prompt' — getUserMedia will show the prompt
  }

  /* ── Recording ───────────────────────────────────────────────────── */

  /**
   * Start capturing audio. Returns true on success, or { error: string }.
   */
  async function startRecording() {
    if (recording) return false

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
      _setMicPermission('granted')
    } catch (e) {
      _setMicPermission('denied')
      return { error: '无法访问麦克风：' + e.message }
    }

    audioCtx = new (window.AudioContext || window.webkitAudioContext)()
    nativeSR = audioCtx.sampleRate
    log('[Rec] AudioContext sampleRate=%d', nativeSR)
    const source = audioCtx.createMediaStreamSource(micStream)

    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 256
    source.connect(analyser)

    rawChunks = []

    // Prefer AudioWorklet; fall back to deprecated ScriptProcessor
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
        await audioCtx.audioWorklet.addModule(url)
        URL.revokeObjectURL(url)
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
    _drawWave()
    return true
  }

  /**
   * Stop recording and return captured audio data.
   * Returns { chunks: Float32Array[], sampleRate: number } or null.
   */
  function stopRecording() {
    if (!recording) return null
    recording = false
    _cleanupAudioNodes()
    const chunks = rawChunks.splice(0)
    const sr = nativeSR
    return { chunks, sampleRate: sr }
  }

  /** Cancel recording without returning data. */
  function cancelRecording() {
    if (!recording) { _cleanupAudioNodes(); return }
    recording = false
    _cleanupAudioNodes()
    rawChunks = []
  }

  function _cleanupAudioNodes() {
    cancelAnimationFrame(_rafId)
    isRecording.value = false
    if (audioWorkletNode) { audioWorkletNode.disconnect(); audioWorkletNode = null }
    if (processor)        { processor.disconnect();        processor         = null }
    if (analyser)         { analyser.disconnect();         analyser          = null }
    if (audioCtx)         { audioCtx.close();              audioCtx          = null }
    if (micStream)        { micStream.getTracks().forEach(t => t.stop()); micStream = null }
  }

  /* ── Waveform visualisation ──────────────────────────────────────── */
  function _drawWave() {
    if (!analyser || !waveCanvasRef.value) return
    _rafId = requestAnimationFrame(_drawWave)

    const canvas = waveCanvasRef.value
    const ctx    = canvas.getContext('2d')
    const W = canvas.width, H = canvas.height
    const data = new Uint8Array(analyser.frequencyBinCount)
    analyser.getByteTimeDomainData(data)

    ctx.clearRect(0, 0, W, H)
    const cx = W / 2, cy = H / 2, r = W / 2 - 14
    const step = (2 * Math.PI) / data.length

    ctx.beginPath()
    for (let i = 0; i < data.length; i++) {
      const amp   = ((data[i] / 128) - 1) * 16
      const angle = i * step - Math.PI / 2
      const x = cx + (r + amp) * Math.cos(angle)
      const y = cy + (r + amp) * Math.sin(angle)
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    }
    ctx.closePath()
    ctx.strokeStyle = 'rgba(124,111,247,0.65)'
    ctx.lineWidth   = 2
    ctx.stroke()
  }

  /* ── DSP: resample & send ────────────────────────────────────────── */
  function _f32ToI16(buf) {
    const out = new Int16Array(buf.length)
    for (let i = 0; i < buf.length; i++)
      out[i] = Math.max(-32768, Math.min(32767, buf[i] * 32767))
    return out
  }

  /**
   * Resample captured audio to 16 kHz and send via `sendFn`.
   * `sendFn` is called with each chunk buffer and then with 'END'.
   * Throws on failure — caller should handle UI recovery.
   */
  async function resampleAndSend(chunks, fromSR, sendFn) {
    if (!chunks.length) { sendFn('END'); return }

    const totalLen = chunks.reduce((s, c) => s + c.length, 0)
    const merged   = new Float32Array(totalLen)
    let off = 0
    for (const c of chunks) { merged.set(c, off); off += c.length }

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

    const i16       = _f32ToI16(resampled)
    const chunkSize = SEND_CHUNK >> 1   // samples per chunk
    for (let i = 0; i < i16.length; i += chunkSize) {
      sendFn(i16.slice(i, i + chunkSize).buffer)
    }
    sendFn('END')
  }

  return {
    isRecording,
    syncMicPermission, ensureMicPermission,
    startRecording, stopRecording, cancelRecording,
    resampleAndSend,
    get isActive() { return recording },
  }
}
