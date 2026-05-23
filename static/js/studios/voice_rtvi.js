/* static/js/studios/voice_rtvi.js */

class RTVIAudioQueue {
  constructor() {
    this.queue = [];
    this.isPlaying = false;
    this.currentAudio = null;
  }

  enqueue(url, text, onPlay, onEnd) {
    this.queue.push({ url, text, onPlay, onEnd });
    if (!this.isPlaying) {
      this.playNext();
    }
  }

  playNext() {
    if (this.queue.length === 0) {
      this.isPlaying = false;
      this.currentAudio = null;
      return;
    }
    this.isPlaying = true;
    const chunk = this.queue.shift();
    const audio = new Audio(chunk.url);
    this.currentAudio = audio;

    audio.onplay = () => {
      if (chunk.onPlay) chunk.onPlay(chunk.text);
    };

    audio.onended = () => {
      if (chunk.onEnd) chunk.onEnd();
      this.playNext();
    };

    audio.play().catch(err => {
      console.warn("Audio playback failed:", err);
      this.playNext();
    });
  }

  clear() {
    if (this.currentAudio) {
      try {
        this.currentAudio.pause();
      } catch(e) {}
      this.currentAudio = null;
    }
    this.queue = [];
    this.isPlaying = false;
  }
}

class SiriWaveformVisualizer {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    this.active = false;
    this.phase = 0;
    this.waves = [
      { amplitude: 12, speed: 0.1, frequency: 0.015, color: 'rgba(167, 139, 250, 0.45)' }, // Purple
      { amplitude: 22, speed: 0.05, frequency: 0.008, color: 'rgba(96, 165, 250, 0.35)' },  // Blue
      { amplitude: 8, speed: 0.15, frequency: 0.025, color: 'rgba(52, 211, 153, 0.4)' }    // Green
    ];
  }

  start() {
    this.active = true;
    this.draw();
  }

  stop() {
    this.active = false;
    if (this.ctx && this.canvas) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
  }

  draw(audioLevel = 0.15) {
    if (!this.active || !this.canvas) return;

    const w = this.canvas.width;
    const h = this.canvas.height;
    this.ctx.clearRect(0, 0, w, h);

    // Apply scaling based on audio level
    const levelScale = audioLevel * 2.0 + 0.05;

    this.waves.forEach((wave, idx) => {
      wave.speed += 0.001; // subtle speed modulation
      const phaseOffset = wave.speed * (idx + 1) * 0.1;
      
      this.ctx.beginPath();
      this.ctx.strokeStyle = wave.color;
      this.ctx.lineWidth = idx === 0 ? 3 : 1.5;

      for (let x = 0; x < w; x++) {
        // Curve dampener at edges
        const normalize = Math.sin((x / w) * Math.PI);
        const y = h / 2 + Math.sin(x * wave.frequency + this.phase + phaseOffset) * wave.amplitude * normalize * levelScale;
        
        if (x === 0) {
          this.ctx.moveTo(x, y);
        } else {
          this.ctx.lineTo(x, y);
        }
      }
      this.ctx.stroke();
    });

    this.phase += 0.08;
    requestAnimationFrame(() => this.draw(audioLevel));
  }
}

class VoiceStudioRTVIPilot {
  constructor() {
    this.ws = null;
    this.status = 'idle';
    this.audioQueue = new RTVIAudioQueue();
    this.visualizer = null;
    this.recognition = null;
    this.latencyStart = 0;
    this.pings = 0;
    this.rtts = [];
    this.statsInterval = null;
  }

  init() {
    console.log("Initializing Voice Studio RTVI Client...");
    this.visualizer = new SiriWaveformVisualizer('voice-rtvi-canvas');
    
    // Check SpeechRecognition support for continuous STT
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      this.recognition = new SpeechRecognition();
      this.recognition.continuous = true;
      this.recognition.interimResults = false;
      this.recognition.lang = 'fr-FR';

      this.recognition.onresult = (event) => {
        const result = event.results[event.results.length - 1];
        if (result.isFinal) {
          const text = result[0].transcript.trim();
          if (text) {
            this.sendTranscript(text);
          }
        }
      };

      this.recognition.onerror = (err) => {
        console.warn("Speech recognition error:", err);
      };
      
      this.recognition.onend = () => {
        if (this.status === 'listening' || this.status === 'speaking') {
          this.recognition.start(); // auto-restart continuous listening
        }
      };
    }
  }

  async connect() {
    if (this.ws) return;

    this.status = 'connecting';
    this.updateUIState();

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${window.location.host}/voice/rtvi/session`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log("Voice RTVI WebSocket connected!");
      this.audioQueue.clear();
      this.status = 'idle';
      this.updateUIState();
      this.startStats();
      
      // Send initial config
      const voiceStyle = document.getElementById('voice_style')?.value || 'female_soft';
      const language = document.getElementById('voice_lang')?.value || 'auto';
      this.ws.send(JSON.stringify({
        type: 'config',
        voice_style: voiceStyle,
        language: language
      }));
      
      // Start visualizer in idle mode
      this.visualizer.start();
      
      if (this.recognition) {
        try {
          this.recognition.start();
        } catch(e) {}
      }
    };

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      if (msg.type === 'pong') {
        const rtt = Date.now() - this.latencyStart;
        this.rtts.push(rtt);
        if (this.rtts.length > 5) this.rtts.shift();
        const avgRtt = Math.round(this.rtts.reduce((a, b) => a + b, 0) / this.rtts.length);
        
        const rttElement = document.getElementById('rtvi-rtt');
        if (rttElement) {
          rttElement.textContent = `${avgRtt} ms`;
        }
        return;
      }

      if (msg.type === 'state') {
        this.status = msg.state;
        this.updateUIState();
      }

      if (msg.type === 'audio_chunk') {
        // Enqueue the chunk to play seamlessly
        this.audioQueue.enqueue(
          msg.url,
          msg.text,
          (txt) => {
            // Triggered on chunk play: update active speech subtitles
            this.addLiveSubtitles(txt);
          },
          () => {
            // Triggered on chunk end
            this.clearLiveSubtitles();
          }
        );
      }

      if (msg.type === 'cancelled') {
        this.audioQueue.clear();
        this.clearLiveSubtitles();
      }
    };

    this.ws.onclose = () => {
      console.log("Voice RTVI WebSocket closed.");
      this.cleanup();
    };

    this.ws.onerror = (err) => {
      console.error("Voice RTVI WebSocket error:", err);
      this.cleanup();
    };
  }

  sendTranscript(text) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    
    // User spoke! Instantly send interruption signal to stop ongoing bot speech
    this.ws.send(JSON.stringify({ type: 'interrupt' }));
    this.audioQueue.clear();
    
    // Show transcript in feed locally
    this.appendTranscriptFeed('user', text);
    
    // Send transcript to trigger response
    this.ws.send(JSON.stringify({
      type: 'transcript',
      text: text
    }));
  }

  appendTranscriptFeed(sender, text) {
    const feed = document.querySelector('.voice-transcript-feed');
    if (!feed) return;

    const logItem = document.createElement('div');
    logItem.className = `voice-log-item ${sender}`;

    const author = document.createElement('span');
    author.className = 'log-author';
    author.textContent = sender === 'user' ? 'Vous' : 'Clawzd';
    logItem.appendChild(author);

    const paragraph = document.createElement('p');
    paragraph.textContent = text;
    logItem.appendChild(paragraph);

    feed.appendChild(logItem);
    feed.scrollTop = feed.scrollHeight;
  }

  addLiveSubtitles(text) {
    // Add subtitle text to live transcriber panel with active word highlight
    const messagePanel = document.querySelector('.voice-hint-message');
    if (messagePanel) {
      messagePanel.innerHTML = `<span class="voice-active-word">Clawzd:</span> ${text}`;
    }
    
    // Also append the assistant transcript chunk to feed if it's the start
    this.appendTranscriptFeed('assistant', text);
  }

  clearLiveSubtitles() {
    const messagePanel = document.querySelector('.voice-hint-message');
    if (messagePanel && messagePanel.textContent.startsWith("Clawzd:")) {
      messagePanel.textContent = "Clawzd est à l'écoute...";
    }
  }

  startStats() {
    this.statsInterval = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      this.latencyStart = Date.now();
      this.ws.send(JSON.stringify({ type: 'ping' }));
    }, 2000);
  }

  updateUIState() {
    // Modify standard sphere state class and telemetry panel
    const statusDot = document.querySelector('.voice-status-dot');
    const statusText = document.querySelector('.voice-status-badge span');
    const sphereGlow = document.getElementById('voice-sphere-glow');
    
    if (statusText) {
      statusText.textContent = this.status.toUpperCase();
    }

    if (statusDot) {
      statusDot.className = 'voice-status-dot';
      if (this.status === 'thinking') statusDot.classList.add('pulse-orange');
      else if (this.status === 'speaking') statusDot.classList.add('pulse-green');
      else if (this.status === 'listening') statusDot.classList.add('pulse-blue');
    }

    if (sphereGlow) {
      sphereGlow.className = 'voice-sphere-glow-layer';
      sphereGlow.classList.add(`state-${this.status}`);
    }
  }

  cleanup() {
    this.ws = null;
    this.status = 'idle';
    this.updateUIState();
    this.audioQueue.clear();
    this.visualizer.stop();
    
    if (this.statsInterval) {
      clearInterval(this.statsInterval);
      this.statsInterval = null;
    }
    
    if (this.recognition) {
      try {
        this.recognition.stop();
      } catch(e) {}
    }

    const rttElement = document.getElementById('rtvi-rtt');
    if (rttElement) rttElement.textContent = '-- ms';
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
    }
    this.cleanup();
  }
}

// Global hook to toggle between standard and pro RTVI modes
window.clawzdVoicePilot = new VoiceStudioRTVIPilot();
window.addEventListener('DOMContentLoaded', () => {
  window.clawzdVoicePilot.init();
  
  // Register toggle collapsible event for Telemetry header
  const telHeader = document.querySelector('.telemetry-header');
  if (telHeader) {
    telHeader.addEventListener('click', () => {
      const panel = telHeader.parentElement;
      panel.classList.toggle('collapsed');
    });
  }
});
