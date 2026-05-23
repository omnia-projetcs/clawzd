/**
 * Clawzd WebAudioEngine — Moteur de prévisualisation multi-pistes temps réel.
 * Inspiré par l'architecture d'openDAW.
 */
window.ClawzdWebAudioEngine = class ClawzdWebAudioEngine {
  constructor() {
    this.audioCtx = null;
    this.masterGainNode = null;
    this.activeSources = [];
    this.audioBuffers = new Map(); // Cache des fichiers pré-chargés
    this.isPlaying = false;
    this.startTime = 0; // Temps absolu du début de lecture dans l'AudioContext
    this.pauseOffset = 0; // Position de la tête de lecture en secondes
  }

  init() {
    if (this.audioCtx) return;
    this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    this.masterGainNode = this.audioCtx.createGain();
    this.masterGainNode.connect(this.audioCtx.destination);
  }

  /**
   * Pré-charge un fichier audio dans l'AudioContext pour une lecture instantanée.
   */
  async preloadAsset(url) {
    if (this.audioBuffers.has(url)) {
      return this.audioBuffers.get(url);
    }
    this.init();

    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const arrayBuffer = await response.arrayBuffer();
      
      // Decodes audio in browser worker or main thread
      const audioBuffer = await new Promise((resolve, reject) => {
        this.audioCtx.decodeAudioData(
          arrayBuffer,
          (decoded) => resolve(decoded),
          (err) => reject(err)
        );
      });
      
      this.audioBuffers.set(url, audioBuffer);
      console.log(`🔊 [WebAudioEngine] Asset pré-chargé avec succès : ${url}`);
      return audioBuffer;
    } catch (err) {
      console.error(`❌ Impossible de charger/décoder l'audio : ${url}`, err);
      return null;
    }
  }

  /**
   * Démarre la lecture de la timeline multi-piste à une position donnée de la tête de lecture.
   */
  playTimeline(clips, playheadPosition, getTrackTypeFunc) {
    this.init();
    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }

    this.stopTimeline();
    this.isPlaying = true;
    this.pauseOffset = playheadPosition;
    this.startTime = this.audioCtx.currentTime;

    clips.forEach(clip => {
      // openDAW pattern: planifier uniquement les clips de type audio (ou vidéo avec piste audio)
      const trackType = getTrackTypeFunc(clip.track);
      if (trackType !== 'audio' && trackType !== 'video') return;

      // Déterminer l'URL du clip
      let url = "";
      if (trackType === 'audio') {
        url = clip.filename.toLowerCase().endsWith('.mp3') || clip.filename.toLowerCase().endsWith('.wav') ? 
          `/data/audio/${clip.filename}` : `/data/images/${clip.filename}`;
      } else {
        url = `/data/images/${clip.filename}`;
      }

      const buffer = this.audioBuffers.get(url);
      if (!buffer) {
        // Si l'asset n'est pas encore pré-chargé, on essaie de le pré-charger silencieusement en arrière-plan
        this.preloadAsset(url);
        return;
      }

      const clipStart = parseFloat(clip.start) || 0.0; // Temps d'apparition sur la timeline (s)
      const clipDuration = parseFloat(clip.duration) || 5.0; // Durée de présence sur la timeline (s)
      const trimStart = parseFloat(clip.trim_start) || 0.0;
      const speed = parseFloat(clip.speed) || 1.0;
      const volume = clip.volume !== undefined ? parseFloat(clip.volume) : 1.0;

      // Calculer quand jouer le clip par rapport à la tête de lecture courante
      let when = 0;
      let offset = trimStart;
      let duration = clipDuration;

      if (clipStart >= playheadPosition) {
        // Le clip commence après la tête de lecture
        when = this.startTime + (clipStart - playheadPosition);
      } else if (clipStart + clipDuration > playheadPosition) {
        // La tête de lecture se situe au milieu du clip
        when = this.startTime;
        offset = trimStart + (playheadPosition - clipStart) * speed;
        duration = clipDuration - (playheadPosition - clipStart);
      } else {
        // Le clip est déjà passé
        return;
      }

      // Créer et connecter les nœuds Web Audio pour ce clip
      try {
        const source = this.audioCtx.createBufferSource();
        source.buffer = buffer;
        source.playbackRate.value = speed;

        const gainNode = this.audioCtx.createGain();
        gainNode.gain.setValueAtTime(volume, this.audioCtx.currentTime);

        source.connect(gainNode);
        gainNode.connect(this.masterGainNode);

        // Planification précise à l'échantillon près
        source.start(when, offset, duration);
        this.activeSources.push({ source, gainNode, url });
      } catch (err) {
        console.error("❌ Erreur de planification Web Audio pour le clip :", clip.filename, err);
      }
    });
  }

  stopTimeline() {
    this.isPlaying = false;
    this.activeSources.forEach(item => {
      try {
        item.source.stop();
      } catch (e) { /* Déjà arrêté */ }
      try {
        item.source.disconnect();
        item.gainNode.disconnect();
      } catch (e) {}
    });
    this.activeSources = [];
  }
}
