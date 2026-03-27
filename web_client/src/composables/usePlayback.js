import { log, IS_IOS } from './logger'

export function usePlayback() {
  let sharedAudioCtx  = null
  let currentPlayback = null
  let isPlayingAudio  = false
  let streamPlayer    = null
  let audioChunks     = []
  let statusAudioBuf  = []
  let inStatusAudio   = false

  /* ── iOS audio unlock ────────────────────────────────────────────── */
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

  /* ── MediaSource stream player ───────────────────────────────────── */
  function _createStreamPlayer() {
    if (IS_IOS) return null
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

  /* ── Chunk playback (Web Audio API) ──────────────────────────────── */
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

  /* ── Stop any active playback ────────────────────────────────────── */
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

  /* ── Audio buffer routing (called by WS handlers) ────────────────── */

  /** Route incoming binary audio data to the appropriate buffer. */
  function pushAudioData(data) {
    if (inStatusAudio) statusAudioBuf.push(data)
    else if (streamPlayer && !streamPlayer.failed) streamPlayer.push(data)
    else audioChunks.push(data)
  }

  /** DONE received: finalize stream or play buffered chunks. */
  function finishResponse() {
    inStatusAudio = false; statusAudioBuf = []
    if (streamPlayer && !streamPlayer.failed) {
      streamPlayer.finish()
    } else {
      const mp3 = audioChunks.splice(0)
      if (mp3.length) playChunks(mp3)  // non-blocking
    }
  }

  /** EMPTY/ERROR: discard audio buffers and stream player. */
  function discardBuffers() {
    audioChunks = []
    if (streamPlayer) { streamPlayer.stop(); streamPlayer = null }
  }

  /** STATUS: begin buffering status audio. */
  function beginStatusAudio() {
    inStatusAudio = true; statusAudioBuf = []
  }

  /** STATUS_AUDIO_DONE: play buffered status audio. */
  function endStatusAudio() {
    inStatusAudio = false
    const clips = statusAudioBuf.splice(0)
    if (clips.length) playChunks(clips)  // non-blocking
  }

  /** ASSISTANT_TEXT or ERROR: reset status audio state. */
  function resetStatusAudio() {
    inStatusAudio = false; statusAudioBuf = []
  }

  /** Prepare for a new server response (after recording stops). */
  function prepareForResponse() {
    audioChunks = []
    if (streamPlayer) streamPlayer.stop()
    streamPlayer = _createStreamPlayer()
  }

  function isPlaying() { return isPlayingAudio }

  function destroy() {
    if (sharedAudioCtx) { try { sharedAudioCtx.close() } catch {} }
  }

  return {
    unlockAudio, stopPlayback, isPlaying, destroy,
    pushAudioData, finishResponse, discardBuffers,
    beginStatusAudio, endStatusAudio, resetStatusAudio,
    prepareForResponse,
  }
}
