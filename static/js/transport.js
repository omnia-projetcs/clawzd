/**
 * Clawzd — Chat transport abstraction.
 *
 * Provides a unified API for chat streaming via WebSocket (preferred)
 * with automatic fallback to SSE + POST (legacy).
 *
 * Usage:
 *   const transport = new ChatTransport(sessionId);
 *   transport.onToken  = (token) => { ... };
 *   transport.onDone   = (data)  => { ... };
 *   transport.onError  = (err)   => { ... };
 *   transport.connect();
 *   transport.send({ message: "Hello", provider: "ollama", model: "..." });
 *   transport.stop();
 */

class ChatTransport {
  constructor(sessionId) {
    this.sessionId = sessionId;
    this.ws = null;
    this.mode = 'disconnected'; // 'ws' | 'sse' | 'disconnected'
    this._reconnectDelay = 1000;
    this._maxReconnectDelay = 30000;
    this._pingInterval = null;
    this._closed = false;
    this._streaming = false;

    // Callbacks (set by consumer)
    this.onToken = null;
    this.onDone = null;
    this.onError = null;
    this.onConnected = null;
    this.onDisconnected = null;
  }

  /**
   * Connect to the server. Tries WebSocket first, falls back to SSE.
   */
  connect() {
    this._closed = false;
    this._connectWS();
  }

  /**
   * Disconnect and clean up.
   */
  disconnect() {
    this._closed = true;
    this._clearPing();
    if (this.ws) {
      try { this.ws.close(1000, 'client disconnect'); } catch (_) {}
      this.ws = null;
    }
    this.mode = 'disconnected';
  }

  /**
   * Send a chat message. Accepts the same payload as POST /send/.
   * @param {Object} payload - { message, provider, model, preprompt, ... }
   */
  send(payload) {
    if (this.mode === 'ws' && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'message', ...payload }));
      this._streaming = true;
    } else {
      // Fallback: POST + SSE
      this._sendViaSSE(payload);
    }
  }

  /**
   * Stop the current generation.
   */
  stop() {
    if (this.mode === 'ws' && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'stop' }));
    } else {
      // Fallback: POST /stop/
      fetch(`/stop/${this.sessionId}`, { method: 'POST' }).catch(() => {});
    }
  }

  /** @returns {boolean} True if connected via WebSocket or SSE. */
  get connected() {
    return this.mode !== 'disconnected';
  }

  /** @returns {boolean} True if using WebSocket transport. */
  get isWebSocket() {
    return this.mode === 'ws';
  }

  // --- Private: WebSocket ---

  _connectWS() {
    if (this._closed) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/${this.sessionId}`;

    try {
      this.ws = new WebSocket(url);
    } catch (_) {
      console.warn('[Transport] WebSocket constructor failed, falling back to SSE');
      this.mode = 'sse';
      this.onConnected?.();
      return;
    }

    this.ws.onopen = () => {
      this._reconnectDelay = 1000;
      // Don't set mode yet — wait for "connected" message
    };

    this.ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch (_) { return; }

      switch (msg.type) {
        case 'connected':
          this.mode = 'ws';
          this._startPing();
          this.onConnected?.();
          break;
        case 'token':
          this.onToken?.(msg.data);
          break;
        case 'done':
          this._streaming = false;
          this.onDone?.(msg);
          break;
        case 'processing':
          // Generation started, metadata available
          break;
        case 'stopped':
          this._streaming = false;
          this.onDone?.({ stopped: true });
          break;
        case 'error':
          this._streaming = false;
          this.onError?.(msg.detail || 'Unknown error');
          break;
        case 'pong':
          // Keepalive acknowledged
          break;
      }
    };

    this.ws.onclose = (evt) => {
      this._clearPing();
      const wasConnected = this.mode === 'ws';
      this.mode = 'disconnected';

      if (this._closed) return;

      if (wasConnected) {
        this.onDisconnected?.();
        // Reconnect with exponential backoff
        setTimeout(() => this._connectWS(), this._reconnectDelay);
        this._reconnectDelay = Math.min(
          this._reconnectDelay * 2,
          this._maxReconnectDelay
        );
      } else {
        // Never connected — WS not supported, fall back to SSE
        console.info('[Transport] WebSocket unavailable, using SSE fallback');
        this.mode = 'sse';
        this.onConnected?.();
      }
    };

    this.ws.onerror = () => {
      // onclose will fire after this — handled there
    };
  }

  _startPing() {
    this._clearPing();
    this._pingInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN && !this._streaming) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 25000);
  }

  _clearPing() {
    if (this._pingInterval) {
      clearInterval(this._pingInterval);
      this._pingInterval = null;
    }
  }

  // --- Private: SSE fallback ---

  _sendViaSSE(payload) {
    this._streaming = true;

    // POST the message
    fetch(`/send/${this.sessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        // Start listening on SSE
        this._connectSSE();
      })
      .catch((err) => {
        this._streaming = false;
        this.onError?.(err.message);
      });
  }

  _connectSSE() {
    const es = new EventSource(`/stream/${this.sessionId}`);

    es.onmessage = (evt) => {
      if (evt.data === '[DONE]') {
        es.close();
        this._streaming = false;
        this.onDone?.({});
        return;
      }
      this.onToken?.(evt.data);
    };

    es.onerror = () => {
      es.close();
      if (this._streaming) {
        this._streaming = false;
        this.onError?.('SSE connection lost');
      }
    };
  }
}

// Expose globally
window.ChatTransport = ChatTransport;
