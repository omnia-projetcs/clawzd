/**
 * Clawzd — VoiceInput
 * Extracted from app.js for modular architecture.
 * Uses window globals for shared utilities (el, $, $$, toast, escHtml, icon, ICONS).
 */
/* global $, $$, el, toast, escHtml, icon, ICONS, OC */

// ---- Voice Input (Web Speech API / Backend Fallback) ----
class VoiceInput {
  constructor(inputEl, sendFn) {
    this.inputEl = inputEl;
    this.sendFn = sendFn;
    this.btn = $('#btn-voice');
    if (!this.btn) return;
    this.isRecording = false;

    this.supported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

    if (this.supported) {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      this.recognition = new SR();
      this.recognition.continuous = true;
      this.recognition.interimResults = true;
      this.recognition.lang = 'fr-FR';
      this.recognition.onresult = (e) => this.onResult(e);
      this.recognition.onerror = (e) => this.onError(e);
      this.recognition.onend = () => this.onEnd();
    } else {
      this.mediaRecorder = null;
      this.audioChunks = [];
    }

    this.btn.addEventListener('click', () => this.toggle());
  }
  async toggle() {
    if (this.isRecording) this.stop(); else await this.start();
  }
  async start() {
    if (this.isRecording) return;

    // Check for secure context (HTTPS required for microphone in most browsers)
    if (!window.isSecureContext && location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
      toast(ICONS.x(14) + ' Microphone requires HTTPS. Use localhost or enable HTTPS in your server.');
      return;
    }

    // Pre-check microphone permission state
    try {
      const perm = await navigator.permissions.query({ name: 'microphone' });
      if (perm.state === 'denied') {
        toast(ICONS.x(14) + ' Microphone blocked by browser. Click the 🔒 icon in the address bar to allow access.');
        return;
      }
    } catch (e) { /* permissions API not supported — proceed anyway */ }

    if (this.supported && this.recognition) {
      try {
        this.recognition.start();
        this.isRecording = true;
        this.btn.classList.add('recording');
        this.btn.title = 'Click to stop recording';
        toast(ICONS.circle(14) + ' Listening...');
      } catch (e) { console.error('Voice error:', e); toast(ICONS.x(14) + ' Voice recognition failed: ' + e.message); }
    } else {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.mediaRecorder = new MediaRecorder(stream);
        this.audioChunks = [];
        this.mediaRecorder.ondataavailable = e => { if (e.data.size > 0) this.audioChunks.push(e.data); };
        this.mediaRecorder.onstop = async () => {
          const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
          this.audioChunks = [];
          toast(ICONS.loader ? ICONS.loader(14) + ' Transcribing...' : 'Transcribing...');
          const fd = new FormData();
          fd.append('file', blob, 'audio.webm');
          try {
            const r = await fetch('/api/transcribe', { method: 'POST', body: fd });
            const d = await r.json();
            if (d.text) {
              const val = this.inputEl.value;
              this.inputEl.value = val ? val + ' ' + d.text : d.text;
              this.inputEl.dispatchEvent(new Event('input'));
            } else if (d.error) {
              toast(ICONS.x(14) + ' Transcription error: ' + d.error);
            }
          } catch (e) { toast(ICONS.x(14) + ' Transcription failed'); }
        };
        this.mediaRecorder.start();
        this.isRecording = true;
        this.btn.classList.add('recording');
        this.btn.title = 'Click to stop recording';
        toast(ICONS.circle(14) + ' Recording audio...');
      } catch (e) {
        const msg = e.name === 'NotAllowedError'
          ? ' Microphone blocked. Click 🔒 in address bar to allow.'
          : (e.name === 'NotFoundError' ? ' No microphone found.' : ' Microphone error: ' + e.message);
        toast(ICONS.x(14) + msg);
      }
    }
  }
  stop() {
    if (!this.isRecording) return;
    if (this.supported && this.recognition) {
      this.recognition.stop();
    } else if (this.mediaRecorder) {
      this.mediaRecorder.stop();
      this.mediaRecorder.stream.getTracks().forEach(t => t.stop());
    }
    this.isRecording = false;
    this.btn.classList.remove('recording');
    this.btn.title = 'Voice input';
  }
  onResult(e) {
    let interim = '', final = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) final += t; else interim += t;
    }
    if (final) {
      this.inputEl.value += (this.inputEl.value ? ' ' : '') + final;
      this.inputEl.dispatchEvent(new Event('input'));
    }
  }
  onError(e) {
    console.error('Speech error:', e.error);
    if (e.error !== 'no-speech') toast('Error: ' + e.error);
    this.stop();
  }
  onEnd() {
    if (this.isRecording && this.supported) {
      try { this.recognition.start(); } catch (e) { this.stop(); }
    }
  }
}

// Backward compatibility
window.VoiceInput = VoiceInput;
