/* static/js/studios/voice.js */

class VoiceStudio {
  constructor() {
    this.active = false;
    this.state = 'idle'; // idle, listening, thinking, speaking
    this.handsFree = true;
    this.autonomy = true;
    this.manuallyStopped = false;
    
    // Audio elements
    this.audioContext = null;
    this.analyser = null;
    this.micStream = null;
    this.activeAudio = null;
    
    // Speech Recognition
    this.recognition = null;
    this.finalTranscript = '';
    
    // VAD settings
    this.vadSilenceThreshold = 1500; // ms of silence before sending
    this.micVolumeThreshold = 0.04;  // Mic amplitude threshold
    this.lastSoundTime = 0;
    this.userIsSpeaking = false;
    
    // Visualizer Canvas
    this.canvas = null;
    this.ctx = null;
    this.animationFrameId = null;
    this.visualizerAngle = 0;
    this.visualizerPulse = 1;
    this.micLevel = 0;
    this.speakingLevel = 0;
    
    // Bind UI elements (mode switching is owned by app.js via toggle())
    this.initUI();
  }

  /**
   * Central mode API — same contract as research/media/presentation studios.
   * Called from app.js mode-toggle so panels never stack.
   */
  toggle(show) {
    if (show) {
      this.activate();
    } else {
      this.deactivate();
    }
  }

  initUI() {
    // Controls only — do not bind mode-btn here (avoids racing app.js).

    const hfToggle = document.getElementById('voice-handsfree');
    if (hfToggle) {
      hfToggle.addEventListener('change', (e) => {
        this.handsFree = e.target.checked;
        if (this.handsFree && this.active && this.state === 'idle') {
          this.startListening();
        } else if (!this.handsFree) {
          this.stopListening();
        }
      });
    }

    const autToggle = document.getElementById('voice-autonomy');
    if (autToggle) {
      autToggle.addEventListener('change', (e) => {
        this.autonomy = e.target.checked;
      });
    }

    const clearBtn = document.getElementById('voice-clear-transcript');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        const feed = document.getElementById('voice-transcript-feed');
        if (feed) feed.innerHTML = '';
      });
    }

    const sphereTrigger = document.getElementById('voice-sphere-trigger');
    if (sphereTrigger) {
      sphereTrigger.addEventListener('click', () => {
        this.toggleManualTrigger();
      });
    }

    // RTVI Mode Switcher
    const rtviToggle = document.getElementById('voice-rtvi-toggle');
    if (rtviToggle) {
      rtviToggle.addEventListener('change', (e) => {
        const isRtvi = e.target.checked;
        const canvasStandard = document.getElementById('voice-sphere-canvas');
        const canvasRtvi = document.getElementById('voice-rtvi-canvas');
        const telemetry = document.getElementById('voice-telemetry-panel');
        const sphereGlow = document.getElementById('voice-sphere-glow');
        const handsfreeRow = document.getElementById('handsfree-row');
        const autonomyRow = document.getElementById('autonomy-row');
        
        if (isRtvi) {
          canvasStandard.style.display = 'none';
          canvasRtvi.style.display = 'block';
          telemetry.style.display = 'block';
          if (sphereGlow) sphereGlow.style.display = 'block';
          if (handsfreeRow) handsfreeRow.style.opacity = '0.5';
          if (autonomyRow) autonomyRow.style.opacity = '0.5';
          
          // Deactivate standard loop
          this.stopListening();
          this.interruptActiveAudio();
          
          // Connect to Pro WebSocket pilot
          if (window.clawzdVoicePilot) {
            window.clawzdVoicePilot.connect();
          }
        } else {
          canvasStandard.style.display = 'block';
          canvasRtvi.style.display = 'none';
          telemetry.style.display = 'none';
          if (sphereGlow) sphereGlow.style.display = 'none';
          if (handsfreeRow) handsfreeRow.style.opacity = '1';
          if (autonomyRow) autonomyRow.style.opacity = '1';
          
          // Disconnect Pro WebSocket pilot
          if (window.clawzdVoicePilot) {
            window.clawzdVoicePilot.disconnect();
          }
          
          // Restore standard state
          this.state = 'idle';
          this.setStatus('IDLE');
          if (this.handsFree && this.active) {
            this.startListening();
          }
        }
      });
    }
  }

  async activate() {
    const panel = document.getElementById('voice-studio');
    if (panel) {
      panel.style.display = 'flex';
      panel.setAttribute('aria-hidden', 'false');
    }
    document.body.dataset.appMode = 'voice-studio';

    // Already active: keep panel visible, skip mic re-init
    if (this.active) return;

    this.active = true;
    this.state = 'idle';
    this.setStatus('IDLE');

    // Init canvas
    this.canvas = document.getElementById('voice-sphere-canvas');
    if (this.canvas) {
      this.ctx = this.canvas.getContext('2d');
      this.startVisualizer();
    }

    // Request Mic permission and start audio contexts
    try {
      await this.initMicrophone();
      if (!this.active) return; // user switched mode during permission prompt
      await this.initSpeechRecognition();
      if (!this.active) return;
      if (this.handsFree) {
        this.startListening();
      }
    } catch (err) {
      if (!this.active) return;
      console.error('[Voice] Mic setup failed:', err);
      this.log('system', 'Error: Microphone access denied or unsupported.');
      this.setStatus('ERROR');
    }
  }

  deactivate() {
    const panel = document.getElementById('voice-studio');
    if (panel) {
      panel.style.display = 'none';
      panel.setAttribute('aria-hidden', 'true');
    }

    if (!this.active) return;

    this.active = false;
    this.stopListening();
    this.interruptActiveAudio();

    // Disconnect RTVI pilot if it was running
    if (window.clawzdVoicePilot) {
      try { window.clawzdVoicePilot.disconnect(); } catch (_) {}
    }

    if (this.micStream) {
      this.micStream.getTracks().forEach(t => t.stop());
      this.micStream = null;
    }
    if (this.audioContext) {
      try { this.audioContext.close(); } catch (_) {}
      this.audioContext = null;
      this.analyser = null;
    }
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
  }

  setStatus(text) {
    const badge = document.getElementById('voice-status-badge');
    const textEl = document.getElementById('voice-status-text');
    const dot = badge ? badge.querySelector('.voice-status-dot') : null;
    const hint = document.getElementById('voice-hint-message');
    const trigger = document.getElementById('voice-sphere-trigger');
    
    if (textEl) textEl.textContent = text;
    
    if (dot) {
      dot.className = 'voice-status-dot';
      if (text === 'LISTENING') dot.className = 'voice-status-dot pulse-blue';
      else if (text === 'THINKING') dot.className = 'voice-status-dot pulse-orange';
      else if (text === 'SPEAKING') dot.className = 'voice-status-dot pulse-green';
      else if (text === 'ERROR') dot.className = 'voice-status-dot';
    }

    if (trigger) {
      if (text === 'IDLE' || text === 'ERROR') {
        trigger.classList.add('inactive');
        trigger.classList.remove('active');
      } else {
        trigger.classList.add('active');
        trigger.classList.remove('inactive');
      }
    }
    
    if (hint) {
      if (text === 'IDLE') hint.textContent = 'Click the sphere or start speaking to pilot Clawzd';
      else if (text === 'LISTENING') hint.textContent = 'I am listening... Stop speaking when finished.';
      else if (text === 'THINKING') hint.textContent = 'Processing your request...';
      else if (text === 'SPEAKING') hint.textContent = 'Speaking... Click the sphere or speak to interrupt.';
    }
  }

  log(author, text) {
    const feed = document.getElementById('voice-transcript-feed');
    if (!feed) return;
    
    const item = document.createElement('div');
    item.className = `voice-log-item ${author}`;
    
    const label = author.charAt(0).toUpperCase() + author.slice(1);
    item.innerHTML = `
      <span class="log-author">${label}</span>
      <p>${escHtml(text)}</p>
    `;
    
    feed.appendChild(item);
    feed.scrollTop = feed.scrollHeight;
  }

  async initMicrophone() {
    if (this.audioContext) return;
    
    this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    
    const source = this.audioContext.createMediaStreamSource(this.micStream);
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    
    source.connect(this.analyser);
    
    // Launch Auto-VAD listening frame analyzer
    this.analyseMicVolume();
  }

  analyseMicVolume() {
    if (!this.active || !this.analyser) return;

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(dataArray);

    // Compute average amplitude/volume level
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      sum += dataArray[i];
    }
    const volume = sum / dataArray.length / 255;
    this.micLevel = volume;

    // Auto-VAD logic (continuous evaluation)
    if (this.handsFree && this.state === 'listening') {
      const now = Date.now();
      if (volume > this.micVolumeThreshold) {
        // User is currently speaking
        if (!this.userIsSpeaking) {
          this.userIsSpeaking = true;
          this.interruptActiveAudio(); // Instantly interrupt any talking
        }
        this.lastSoundTime = now;
      } else {
        // Quiet
        if (this.userIsSpeaking && (now - this.lastSoundTime > this.vadSilenceThreshold)) {
          // Silence duration elapsed -> trigger submit
          this.userIsSpeaking = false;
          this.triggerVadSubmit();
        }
      }
    }

    setTimeout(() => this.analyseMicVolume(), 50);
  }

  initSpeechRecognition() {
    if (this.recognition) return;
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn('[Voice] SpeechRecognition unsupported natively. Whisper fallback will be used.');
      this.isWhisperFallback = true;
      return;
    }
    
    this.recognition = new SpeechRecognition();
    this.recognition.continuous = true;
    this.recognition.interimResults = true;
    
    this.recognition.onstart = () => {
      if (this.recognitionStartTimeout) {
        clearTimeout(this.recognitionStartTimeout);
        this.recognitionStartTimeout = null;
      }
      this.state = 'listening';
      this.setStatus('LISTENING');
    };
    
    this.recognition.onresult = (event) => {
      let interimTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          this.finalTranscript += event.results[i][0].transcript;
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }
      
      // Real-time voice interruption when user speaks over TTS
      if (this.state === 'speaking' && (this.finalTranscript.trim() || interimTranscript.trim())) {
        this.interruptActiveAudio();
        this.state = 'listening';
        this.setStatus('LISTENING');
      }
    };
    
    this.recognition.onerror = (e) => {
      console.error('[Voice] Recognition error:', e.error);
    };
    
    this.recognition.onend = () => {
      if (this.active && this.handsFree && this.state === 'listening') {
        this.recognition.start(); // Restart microphone to ensure continuous stream
      }
    };
  }

  async startListening() {
    this.finalTranscript = '';
    this.userIsSpeaking = false;
    this.lastSoundTime = Date.now();

    // Auto-retry mic stream initialization if it hasn't succeeded yet
    if (!this.micStream) {
      try {
        this.setStatus('INITIALIZING...');
        await this.initMicrophone();
      } catch (err) {
        console.error('[Voice] Retry microphone setup failed:', err);
        this.log('system', 'Error: Microphone access denied or unsupported.');
        this.setStatus('ERROR');
        return;
      }
    }

    if (this.isWhisperFallback) {
      this.state = 'listening';
      this.setStatus('LISTENING');
      this.startWhisperRecording();
      return;
    }

    if (!this.recognition) return;

    // Set a safety timeout: if native speech recognition doesn't start in 1.5 seconds,
    // fallback to local Whisper recorder!
    this.recognitionStartTimeout = setTimeout(() => {
      console.warn('[Voice] SpeechRecognition start timeout. Switching to local Whisper fallback.');
      this.isWhisperFallback = true;
      this.stopListening();
      this.startListening();
    }, 1500);

    try {
      this.recognition.start();
    } catch (_) {}
  }

  stopListening() {
    if (this.isWhisperFallback) {
      if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
        this.mediaRecorder.stop();
      }
      return;
    }

    if (!this.recognition) return;
    try {
      this.recognition.stop();
    } catch (_) {}
  }

  startWhisperRecording() {
    if (!this.micStream) return;
    this.audioChunks = [];
    try {
      this.mediaRecorder = new MediaRecorder(this.micStream);
      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.audioChunks.push(event.data);
        }
      };
      
      this.mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
        if (audioBlob.size > 1000) {
          await this.submitWhisperAudio(audioBlob);
        } else {
          if (this.active && this.handsFree && !this.manuallyStopped) {
            this.startListening();
          }
        }
      };
      this.mediaRecorder.start();
    } catch (e) {
      console.error("[Voice] MediaRecorder start failed:", e);
    }
  }

  async submitWhisperAudio(audioBlob) {
    this.state = 'thinking';
    this.setStatus('THINKING');
    
    const formData = new FormData();
    formData.append('file', audioBlob, 'recording.webm');
    
    try {
      const res = await fetch('/api/transcribe', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      
      if (data.error) {
        throw new Error(data.error);
      }
      
      const text = data.text ? data.text.trim() : '';
      if (text) {
        this.submitVoiceCommand(text);
      } else {
        this.state = 'idle';
        this.setStatus('IDLE');
        if (this.handsFree && !this.manuallyStopped) this.startListening();
      }
    } catch (e) {
      console.error("[Voice] Whisper transcription failed:", e);
      this.log('system', 'Transcription failed: ' + e.message);
      this.state = 'idle';
      this.setStatus('IDLE');
      if (this.handsFree && !this.manuallyStopped) this.startListening();
    }
  }

  toggleManualTrigger() {
    if (document.getElementById('voice-rtvi-toggle')?.checked) {
      if (window.clawzdVoicePilot) {
        if (window.clawzdVoicePilot.ws && window.clawzdVoicePilot.ws.readyState === WebSocket.OPEN) {
          window.clawzdVoicePilot.ws.send(JSON.stringify({ type: 'interrupt' }));
        }
      }
      return;
    }

    if (this.state === 'speaking') {
      this.interruptActiveAudio();
      this.state = 'idle';
      this.setStatus('IDLE');
      this.manuallyStopped = true;
      return;
    }

    if (this.state === 'listening') {
      this.manuallyStopped = true;
      this.stopListening();
      if (this.finalTranscript.trim()) {
        this.submitVoiceCommand(this.finalTranscript.trim());
      } else {
        this.state = 'idle';
        this.setStatus('IDLE');
      }
    } else {
      this.manuallyStopped = false;
      this.interruptActiveAudio();
      this.startListening();
    }
  }

  triggerVadSubmit() {
    this.stopListening();
    const command = this.finalTranscript.trim();
    if (command) {
      this.submitVoiceCommand(command);
    } else {
      if (!this.manuallyStopped) {
        this.startListening();
      }
    }
  }

  async submitVoiceCommand(text) {
    this.log('user', text);
    this.state = 'thinking';
    this.setStatus('THINKING');
    this.interruptActiveAudio();

    try {
      // Ensure session is initialized with voice preprompt
      if (!window.chat.sessionId) {
        const r = await fetch('/chat/new', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider: document.getElementById('provider-select').value,
            model: document.getElementById('model-select').value,
            preprompt: 'voice_pilot'
          })
        });
        const d = await r.json();
        window.chat.sessionId = d.id;
        window.chat.connectSSE();
      }

      // Automatically configure autonomy/auto execution if desired
      const isAuto = this.autonomy ? 'auto' : 'none';

      // Send to Clawzd API
      const sendRes = await fetch(`/send/${window.chat.sessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          provider: document.getElementById('provider-select').value,
          model: document.getElementById('model-select').value,
          preprompt: 'voice_pilot',
          action_mode: isAuto
        })
      });

      if (!sendRes.ok) throw new Error('Send failed');

      // Hook token reader to capture response
      this.captureStreamingTokens();

    } catch (e) {
      console.error(e);
      this.log('system', 'Error: Connection lost or request failed.');
      this.state = 'idle';
      this.setStatus('IDLE');
      if (this.handsFree && !this.manuallyStopped) this.startListening();
    }
  }

  captureStreamingTokens() {
    // Intercept SSE/WebSocket response.
    // Since window.chat parses streams and appends to DOM, we can monitor complete events
    const originalFinish = window.chat.finish.bind(window.chat);
    
    window.chat.finish = async () => {
      // Restore standard finish behavior immediately
      window.chat.finish = originalFinish;
      originalFinish();

      const lastAssistantBubble = document.querySelector('#chat-messages .message.assistant:last-child .message-bubble');
      if (lastAssistantBubble) {
        // Extract raw innerText (voice friendly, strips HTML/details tool thought blocks)
        let bubbleText = lastAssistantBubble.innerText || lastAssistantBubble.textContent;
        // Strip out thought blocks/thinking indicators
        bubbleText = bubbleText.replace(/🧠 Auto-Planning Phase[\s\S]*?\n/g, '')
                               .replace(/⏹️ Generation stopped by user/g, '')
                               .trim();
        
        if (bubbleText) {
          this.log('assistant', bubbleText);
          await this.speakResponse(bubbleText);
        } else {
          this.state = 'idle';
          this.setStatus('IDLE');
          if (this.handsFree && !this.manuallyStopped) this.startListening();
        }
      }
    };
  }

  async speakResponse(text) {
    this.state = 'speaking';
    this.setStatus('SPEAKING');

    const voicePreset = document.getElementById('voice-edge-preset').value;
    const voiceLang = document.getElementById('voice-language').value;

    try {
      const res = await fetch('/audio/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'tts',
          text: text,
          voice_style: voicePreset,
          language: voiceLang,
          format: 'mp3'
        })
      });

      if (!res.ok) throw new Error('TTS generation failed');
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      
      if (!this.active || this.state !== 'speaking') return; // Cancelled/Interrupted already

      this.activeAudio = new Audio(data.url);
      
      this.activeAudio.addEventListener('error', (e) => {
        console.warn('[Voice] Audio playback failed, falling back to browser SpeechSynthesis:', e);
        this.speakFallback(text);
      });
      
      // Visualizer volume feedback from audio output
      this.activeAudio.addEventListener('play', () => {
        this.speakingLevel = 0.5; // Simulate constant wave ripples during talking
      });
      
      this.activeAudio.addEventListener('ended', () => {
        this.activeAudio = null;
        this.state = 'idle';
        this.setStatus('IDLE');
        if (this.handsFree && !this.manuallyStopped) {
          this.startListening();
        }
      });
      
      this.activeAudio.play();

    } catch (err) {
      console.error('[Voice] TTS failed:', err);
      // Fallback: browser SpeechSynthesis
      this.speakFallback(text);
    }
  }

  speakFallback(text) {
    if (!window.speechSynthesis) {
      this.state = 'idle';
      this.setStatus('IDLE');
      if (this.handsFree && !this.manuallyStopped) this.startListening();
      return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    const lang = document.getElementById('voice-language').value;
    utterance.lang = lang === 'fr' ? 'fr-FR' : 'en-US';
    
    utterance.onend = () => {
      this.state = 'idle';
      this.setStatus('IDLE');
      if (this.handsFree && !this.manuallyStopped) this.startListening();
    };
    
    window.speechSynthesis.speak(utterance);
    this.activeAudio = { pause: () => window.speechSynthesis.cancel(), currentTime: 0 };
  }

  interruptActiveAudio() {
    if (this.activeAudio) {
      try {
        this.activeAudio.pause();
      } catch (_) {}
      this.activeAudio = null;
    }
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    this.speakingLevel = 0;
  }

  startVisualizer() {
    const draw = () => {
      if (!this.active || !this.ctx) return;
      this.animationFrameId = requestAnimationFrame(draw);

      const w = this.canvas.width;
      const h = this.canvas.height;
      this.ctx.clearRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      
      // Update variables
      this.visualizerAngle += 0.02;
      
      let baseRadius = 80;
      let strokeColor = 'rgba(139, 92, 246, 0.4)';
      let fillColor = 'rgba(139, 92, 246, 0.05)';
      let waveAmp = 0;

      if (this.state === 'idle') {
        // Pulsing violet circle
        this.visualizerPulse = 1 + Math.sin(this.visualizerAngle) * 0.03;
        baseRadius *= this.visualizerPulse;
        strokeColor = 'rgba(139, 92, 246, 0.4)';
        fillColor = 'rgba(139, 92, 246, 0.03)';
      } 
      else if (this.state === 'listening') {
        // Highly reactive blue sine fluctuations
        waveAmp = this.micLevel * 100;
        this.visualizerPulse = 1 + Math.sin(this.visualizerAngle * 2) * 0.05 + this.micLevel * 0.5;
        baseRadius *= this.visualizerPulse;
        strokeColor = 'rgba(59, 130, 246, 0.8)';
        fillColor = 'rgba(59, 130, 246, 0.08)';
      }
      else if (this.state === 'thinking') {
        // Fast morphing calculation orbit
        baseRadius = 80 + Math.sin(this.visualizerAngle * 8) * 15;
        strokeColor = 'rgba(245, 158, 11, 0.7)';
        fillColor = 'rgba(245, 158, 11, 0.06)';
      }
      else if (this.state === 'speaking') {
        // Concentric expanding ripples
        waveAmp = (Math.sin(this.visualizerAngle * 10) * 10 + 15);
        strokeColor = 'rgba(16, 185, 129, 0.8)';
        fillColor = 'rgba(16, 185, 129, 0.08)';
      }

      // Draw glowing shadow background
      this.ctx.shadowBlur = 30;
      this.ctx.shadowColor = strokeColor;

      // Draw Main Visualizer Sphere path
      this.ctx.beginPath();
      const numPoints = 120;
      for (let i = 0; i < numPoints; i++) {
        const theta = (i / numPoints) * Math.PI * 2;
        // Fluctuating morph offset
        let r = baseRadius;
        if (this.state === 'listening' || this.state === 'speaking') {
          const noise = Math.sin(theta * 6 + this.visualizerAngle * 5) * waveAmp;
          r += noise;
        }
        const x = cx + Math.cos(theta) * r;
        const y = cy + Math.sin(theta) * r;
        if (i === 0) this.ctx.moveTo(x, y);
        else this.ctx.lineTo(x, y);
      }
      this.ctx.closePath();
      
      this.ctx.fillStyle = fillColor;
      this.ctx.fill();
      this.ctx.strokeStyle = strokeColor;
      this.ctx.lineWidth = 3;
      this.ctx.stroke();

      // Reset shadows
      this.ctx.shadowBlur = 0;

      // Draw decorative orbit particles in thinking mode
      if (this.state === 'thinking') {
        this.ctx.fillStyle = 'rgba(245, 158, 11, 0.8)';
        for (let i = 0; i < 3; i++) {
          const particleAngle = this.visualizerAngle * 3 + (i * Math.PI * 2 / 3);
          const px = cx + Math.cos(particleAngle) * 110;
          const py = cy + Math.sin(particleAngle) * 110;
          this.ctx.beginPath();
          this.ctx.arc(px, py, 4, 0, Math.PI * 2);
          this.ctx.fill();
        }
      }
    };
    draw();
  }
}

// Global initialization (works even if script loads after DOMContentLoaded)
function _initVoiceStudio() {
  if (!window.voiceStudio) {
    window.voiceStudio = new VoiceStudio();
  }
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initVoiceStudio);
} else {
  _initVoiceStudio();
}
