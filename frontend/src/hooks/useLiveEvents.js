import { useEffect, useRef, useState } from 'react'
import { socketUrl } from '../api'

/** Subscribes to the run event stream, retrying with backoff if the socket drops. */
export function useLiveEvents(path, onEvent) {
  const [connected, setConnected] = useState(false)
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  useEffect(() => {
    if (!path) return undefined

    let socket
    let retryTimer
    let attempt = 0
    let closed = false

    const connect = () => {
      if (closed) return
      socket = new WebSocket(socketUrl(path))

      socket.onopen = () => {
        attempt = 0
        setConnected(true)
      }
      socket.onmessage = (message) => {
        try {
          const payload = JSON.parse(message.data)
          if (payload.type !== 'heartbeat') handlerRef.current?.(payload)
        } catch {
          /* ignore malformed frames */
        }
      }
      socket.onclose = () => {
        setConnected(false)
        if (closed) return
        attempt += 1
        retryTimer = setTimeout(connect, Math.min(1000 * 2 ** attempt, 15000))
      }
      socket.onerror = () => socket.close()
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      socket?.close()
    }
  }, [path])

  return connected
}
