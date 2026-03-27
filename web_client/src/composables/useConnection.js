import { ref } from 'vue'
import { log } from './logger'

const CONNECT_TIMEOUT = 8000   // ms before giving up on WS handshake
const RECONNECT_DELAY = 2500   // ms before reconnecting after close
const PING_INTERVAL   = 20000  // ms between keep-alive pings

/**
 * @param {string} url - WebSocket URL
 * @param {Object} handlers
 * @param {Function} handlers.onOpen
 * @param {Function} handlers.onClose
 * @param {Function} handlers.onBinary - called with ArrayBuffer
 * @param {Function} handlers.onText   - called with string
 */
export function useConnection(url, handlers) {
  const wsReady = ref(false)

  let ws                  = null
  let _connectAttempt     = 0
  let _connectAt          = 0
  let _connectTimeoutId   = null
  let _reconnectTimeoutId = null
  let _pingIntervalId     = null

  function _clearConnectTimeout() {
    if (_connectTimeoutId !== null) { clearTimeout(_connectTimeoutId); _connectTimeoutId = null }
  }

  function send(data) {
    if (ws?.readyState === WebSocket.OPEN) ws.send(data)
  }

  function isOpen() {
    return ws?.readyState === WebSocket.OPEN
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      log('[WS] connect() skipped — already readyState=%s', ws.readyState)
      return
    }

    _connectAttempt++
    _connectAt = performance.now()
    log('[WS] connect() attempt #%d  visibility=%s  online=%s',
        _connectAttempt, document.visibilityState, navigator.onLine)
    ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'

    _clearConnectTimeout()
    _connectTimeoutId = setTimeout(() => {
      if (ws && ws.readyState === WebSocket.CONNECTING) {
        log('[WS] TIMEOUT — still CONNECTING after %d ms. Possible cause: ' +
            'untrusted cert (install mkcert CA on iOS) or network issue. Forcing close.',
            CONNECT_TIMEOUT)
        ws.close()
      }
    }, CONNECT_TIMEOUT)

    ws.onopen = () => {
      _clearConnectTimeout()
      const elapsed = (performance.now() - _connectAt).toFixed(0)
      log('[WS] onopen  attempt #%d  elapsed=%sms', _connectAttempt, elapsed)
      wsReady.value = true
      handlers.onOpen?.()
    }

    ws.onclose = (evt) => {
      _clearConnectTimeout()
      log('[WS] onclose  code=%d  reason=%s  wasClean=%s',
          evt.code, evt.reason || '(none)', evt.wasClean)
      wsReady.value = false
      handlers.onClose?.()
      _reconnectTimeoutId = setTimeout(connect, RECONNECT_DELAY)
    }

    ws.onerror = (evt) => {
      log('[WS] onerror  type=%s  readyState=%s', evt.type, ws.readyState)
      ws.close()
    }

    ws.onmessage = (evt) => {
      if (evt.data instanceof ArrayBuffer) {
        handlers.onBinary?.(evt.data)
      } else {
        handlers.onText?.(evt.data)
      }
    }

    if (_pingIntervalId === null) {
      _pingIntervalId = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) ws.send('PING')
      }, PING_INTERVAL)
    }
  }

  /* ── Visibility / background handling ────────────────────────────── */
  function onVisibilityChange() {
    log('[Page] visibilitychange → %s  wsReadyState=%s',
        document.visibilityState, ws ? ws.readyState : 'no-ws')

    if (document.visibilityState === 'visible') {
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        log('[Page] visible — WS dead, reconnecting immediately')
        connect()
      } else if (ws.readyState === WebSocket.OPEN) {
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
    if (evt.persisted && ws && ws.readyState !== WebSocket.OPEN) {
      log('[Page] bfcache restore + dead WS, reconnecting')
      connect()
    }
  }

  function onPageHide(evt) { log('[Page] pagehide  persisted=%s', evt.persisted) }
  function onOnline()      { log('[Net] online') }
  function onOffline()     { log('[Net] offline') }

  function destroy() {
    if (_reconnectTimeoutId !== null) { clearTimeout(_reconnectTimeoutId); _reconnectTimeoutId = null }
    _clearConnectTimeout()
    if (ws) ws.close()
    if (_pingIntervalId !== null) { clearInterval(_pingIntervalId); _pingIntervalId = null }
  }

  return {
    wsReady, connect, send, isOpen, destroy,
    onVisibilityChange, onPageShow, onPageHide, onOnline, onOffline,
  }
}
