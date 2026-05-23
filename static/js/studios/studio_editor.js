/**
 * Clawzd — Premiere-style Studio Editor Frontend Engine.
 * Fully modular timeline manager, playhead transport system, and clip inspector.
 */

window.StudioEditor = {
  // Timeline State
  duration: 30.0,
  zoom: 30, // Pixels per second
  playhead: 0.0,
  isPlaying: false,
  currentTool: 'select', // 'select' or 'split'
  selectedClipId: null,
  clips: [], // List of timeline clip models
  mediaBinItems: [], // List of gallery items in Resource Bin
  
  // Dynamic Tracks
  tracks: [
    { id: 'video_1', type: 'video', name: 'Video Track 1' },
    { id: 'audio_1', type: 'audio', name: 'Audio Track 1' },
    { id: 'text_1', type: 'text', name: 'Text Track 1' }
  ],

  getTrackType(trackId) {
    const track = this.tracks.find(t => t.id === trackId);
    return track ? track.type : 'video';
  },

  ensureTrackExists(trackId) {
    if (this.tracks.some(t => t.id === trackId)) return trackId;
    
    // Map legacy 'video', 'audio', 'text' to default dynamic tracks
    if (trackId === 'video') return 'video_1';
    if (trackId === 'audio') return 'audio_1';
    if (trackId === 'text') return 'text_1';
    
    // If not matching, create new dynamic track
    let type = 'video';
    if (trackId.includes('audio')) type = 'audio';
    else if (trackId.includes('text')) type = 'text';
    
    const count = this.tracks.filter(t => t.type === type).length + 1;
    const typeLabel = type.charAt(0).toUpperCase() + type.slice(1);
    this.tracks.push({
      id: trackId,
      type,
      name: `${typeLabel} Track ${count}`
    });
    return trackId;
  },

  addTrack(type) {
    const count = this.tracks.filter(t => t.type === type).length + 1;
    const typeLabel = type.charAt(0).toUpperCase() + type.slice(1);
    const id = `${type}_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`;
    this.tracks.push({
      id,
      type,
      name: `${typeLabel} Track ${count}`
    });
    this.renderTimeline();
    if (window.toast) window.toast(`➕ Added new ${typeLabel} Track`);
  },

  deleteTrack(trackId) {
    // Check if there are any clips on this track
    const hasClips = this.clips.some(c => c.track === trackId);
    if (hasClips) {
      if (!confirm("This track contains clips. Are you sure you want to delete it and all its clips?")) {
        return;
      }
    }
    this.clips = this.clips.filter(c => c.track !== trackId);
    this.tracks = this.tracks.filter(t => t.id !== trackId);
    if (this.selectedClipId && !this.clips.some(c => c.id === this.selectedClipId)) {
      this.selectedClipId = null;
      this.selectClip(null);
    }
    this.renderTimeline();
    this.syncPreview();
    if (window.toast) window.toast("🗑️ Track deleted successfully");
  },

  // Playback timer variables
  lastFrameTime: 0,
  animationFrameId: null,

  // HTML Elements
  elements: {},

  init() {
    logger = console; // local logger fallback
    
    // Bind elements
    this.elements = {
      modal: document.getElementById("media-studio-editor-modal"),
      closeBtn: document.getElementById("editor-close-btn"),
      renderBtn: document.getElementById("editor-render-btn"),
      playPauseBtn: document.getElementById("btn-play-pause"),
      stopBtn: document.getElementById("btn-stop"),
      seekStartBtn: document.getElementById("btn-seek-start"),
      seekEndBtn: document.getElementById("btn-seek-end"),
      timecode: document.getElementById("timecode-display"),
      binContainer: document.getElementById("bin-list-container"),
      searchBin: document.getElementById("bin-search"),
      zoomSlider: document.getElementById("timeline-zoom"),
      ruler: document.getElementById("timeline-time-ruler"),
      playheadLine: document.getElementById("timeline-playhead-line"),
      timelineGrid: document.getElementById("timeline-tracks-grid-el"),
      scrollContainer: document.getElementById("timeline-scroll-container"),
      inspectorPlaceholder: document.getElementById("inspector-placeholder"),
      inspectorControls: document.getElementById("inspector-controls"),
      liveText: document.getElementById("live-text-overlay"),
      videoPreview: document.getElementById("editor-preview-video"),
      asciiPreview: document.getElementById("editor-preview-ascii"),
      audioPreview: document.getElementById("editor-preview-audio"),
      previewPlaceholder: document.getElementById("preview-placeholder-msg"),
      toolSelect: document.getElementById("tool-select"),
      toolSplit: document.getElementById("tool-split"),
      toolClear: document.getElementById("tool-clear"),
      aiPrompt: document.getElementById("ai-prompt-input"),
      aiPlanBtn: document.getElementById("ai-plan-btn"),
      trackAddVideo: document.getElementById("track-add-video"),
      trackAddAudio: document.getElementById("track-add-audio"),
      trackAddText: document.getElementById("track-add-text"),
      stockSearchType: document.getElementById("stock-search-type"),
      stockSearchQuery: document.getElementById("stock-search-query"),
      stockSearchBtn: document.getElementById("stock-search-btn"),
      stockListContainer: document.getElementById("stock-list-container"),
      silenceSection: document.getElementById("prop-silence-section"),
      silenceDb: document.getElementById("prop-silence-db"),
      silenceDur: document.getElementById("prop-silence-dur"),
      silencePadding: document.getElementById("prop-silence-padding"),
      silenceMode: document.getElementById("prop-silence-mode"),
      silenceBtn: document.getElementById("prop-silence-btn"),
      snapshotBtn: document.getElementById("btn-snapshot"),
      losslessSection: document.getElementById("prop-lossless-section"),
      losslessTrimBtn: document.getElementById("prop-lossless-trim-btn"),
      streamInfoDetails: document.getElementById("stream-info-details")
    };

    if (!this.elements.modal) return;

    // Bind launch button
    const launchBtn = document.getElementById("media-studio-editor-btn");
    if (launchBtn) {
      launchBtn.addEventListener("click", () => this.open());
    }

    this.bindEvents();
    this.setupInspectorListeners();
    this.updateZoom(parseInt(this.elements.zoomSlider.value));
  },

  bindEvents() {
    const el = this.elements;

    // Global toggle buttons
    el.closeBtn.addEventListener("click", () => this.close());
    el.renderBtn.addEventListener("click", () => this.exportTimeline());

    // Playback transport buttons
    el.playPauseBtn.addEventListener("click", () => this.togglePlay());
    el.stopBtn.addEventListener("click", () => this.stop());
    el.seekStartBtn.addEventListener("click", () => this.seekTo(0));
    el.seekEndBtn.addEventListener("click", () => this.seekTo(this.duration));

    // Sidebar tab toggles
    document.querySelectorAll(".sidebar-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".sidebar-tab").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
        
        tab.classList.add("active");
        const contentId = `tab-${tab.dataset.tab}`;
        document.getElementById(contentId).classList.add("active");
      });
    });

    // Zoom slider
    el.zoomSlider.addEventListener("input", (e) => {
      this.updateZoom(parseInt(e.target.value));
    });

    // Search media bin
    el.searchBin.addEventListener("input", (e) => {
      this.filterMediaBin(e.target.value);
    });

    // AI Montage Planner Event
    if (el.aiPlanBtn) {
      el.aiPlanBtn.addEventListener("click", () => this.generateAIPlan());
    }

    // Dynamic track adders
    if (el.trackAddVideo) el.trackAddVideo.addEventListener("click", () => this.addTrack("video"));
    if (el.trackAddAudio) el.trackAddAudio.addEventListener("click", () => this.addTrack("audio"));
    if (el.trackAddText) el.trackAddText.addEventListener("click", () => this.addTrack("text"));

    // Action tools
    el.toolSelect.addEventListener("click", () => this.setTool('select'));
    el.toolSplit.addEventListener("click", () => this.setTool('split'));
    el.toolClear.addEventListener("click", () => this.clearTimeline());

    // Stock Search Event listeners
    if (el.stockSearchBtn) {
      el.stockSearchBtn.addEventListener("click", () => this.searchStockMedia());
    }
    if (el.stockSearchQuery) {
      el.stockSearchQuery.addEventListener("keypress", (e) => {
        if (e.key === "Enter") this.searchStockMedia();
      });
    }

    // Silence Cut Event listener
    if (el.silenceBtn) {
      el.silenceBtn.addEventListener("click", () => this.autoSilenceCutClip());
    }

    // Lossless Cut & Snapshot Event listeners
    if (el.snapshotBtn) {
      el.snapshotBtn.addEventListener("click", () => this.captureSnapshot());
    }
    if (el.losslessTrimBtn) {
      el.losslessTrimBtn.addEventListener("click", () => this.triggerLosslessTrim());
    }

    // Timeline Ruler playhead seeking
    el.ruler.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      e.preventDefault();

      const seek = (evt) => {
        const rect = el.ruler.getBoundingClientRect();
        // Offset click coordinate by 120px to match ruler pad/ticks starting position
        const x = evt.clientX - (rect.left + 120) + el.scrollContainer.scrollLeft;
        const time = Math.max(0, Math.min(x / this.zoom, this.duration));
        this.seekTo(Math.round(time * 10) / 10);
      };

      seek(e);

      const onMouseMove = (moveEvt) => seek(moveEvt);
      const onMouseUp = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });
  },

  open() {
    this.elements.modal.style.display = "block";
    this.stop();
    this.loadGalleryAssets();
    this.renderTimeline();
    this.syncPreview();
    
    // Automatically trigger SVG icon styling compilation
    if (window.icon) {
      document.querySelectorAll('#media-studio-editor-modal .media-icon[data-icon]').forEach(n => {
        n.innerHTML = window.icon(n.dataset.icon, 14);
      });
    }
  },

  close() {
    this.stop();
    this.elements.modal.style.display = "none";
  },

  async loadGalleryAssets() {
    try {
      this.mediaBinItems = [];
      
      // Fetch image/video gallery
      const imageResp = await fetch('/image/gallery', { cache: 'no-store' });
      if (imageResp.ok) {
        const data = await imageResp.json();
        const files = data.images || [];
        files.forEach(f => {
          this.mediaBinItems.push({
            filename: f.filename,
            url: f.url,
            type: f.filename.toLowerCase().endsWith('.mp4') || f.filename.toLowerCase().endsWith('.webm') ? 'video' : 'image',
            duration: f.duration || 5.0
          });
        });
      }

      // Fetch audio gallery
      try {
        const audioResp = await fetch('/audio/gallery', { cache: 'no-store' });
        if (audioResp.ok) {
          const data = await audioResp.json();
          const files = data.audio_files || [];
          files.forEach(f => {
            this.mediaBinItems.push({
              filename: f.filename,
              url: f.url,
              type: 'audio',
              duration: f.duration || 5.0
            });
          });
        }
      } catch (ae) { /* optional audio */ }

      this.renderMediaBin();
    } catch (e) {
      console.error("Failed to load media assets into Editor bin", e);
    }
  },

  renderMediaBin() {
    const container = this.elements.binContainer;
    container.innerHTML = '';

    if (this.mediaBinItems.length === 0) {
      container.innerHTML = `
        <div class="empty-inspector" style="padding-top:20px;">
          <p>No media files found in your gallery.</p>
        </div>
      `;
      return;
    }

    this.mediaBinItems.forEach(item => {
      const el = document.createElement("div");
      el.className = "bin-item";
      
      let thumbnailMarkup = '<span class="media-icon" data-icon="file"></span>';
      if (item.type === 'image') {
        thumbnailMarkup = `<img src="${item.url}" alt="thumb">`;
      } else if (item.type === 'video') {
        thumbnailMarkup = `<span class="media-icon" data-icon="video"></span>`;
      } else if (item.type === 'audio') {
        thumbnailMarkup = `<span class="media-icon" data-icon="music"></span>`;
      }

      el.innerHTML = `
        <div class="bin-thumbnail">${thumbnailMarkup}</div>
        <div class="bin-info">
          <div class="bin-name">${item.filename}</div>
          <div class="bin-meta">
            <span>${item.type.toUpperCase()}</span>
            <span>${parseFloat(item.duration).toFixed(1)}s</span>
          </div>
        </div>
        <button class="bin-add-btn" title="Add to Timeline">+ Add</button>
      `;

      // Quick Add action
      el.querySelector(".bin-add-btn").addEventListener("click", () => {
        this.addClipToTimeline(item);
      });

      container.appendChild(el);
    });

    if (window.icon) {
      container.querySelectorAll('.media-icon[data-icon]').forEach(n => {
        n.innerHTML = window.icon(n.dataset.icon, 14);
      });
    }
  },

  filterMediaBin(query) {
    const q = query.toLowerCase();
    const items = document.querySelectorAll(".bin-item");
    items.forEach(el => {
      const name = el.querySelector(".bin-name").textContent.toLowerCase();
      el.style.display = name.includes(q) ? "flex" : "none";
    });
  },

  addClipToTimeline(mediaItem) {
    const trackType = mediaItem.type === 'audio' ? 'audio' : 'video';
    const firstTrack = this.tracks.find(t => t.type === trackType);
    if (!firstTrack) {
      if (window.toast) {
        window.toast(`⚠️ Please add a ${trackType.charAt(0).toUpperCase() + trackType.slice(1)} Track first!`);
      } else {
        alert(`Please add a ${trackType.charAt(0).toUpperCase() + trackType.slice(1)} Track first!`);
      }
      return;
    }
    const id = `clip_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    
    const newClip = {
      id,
      filename: mediaItem.filename,
      track: firstTrack.id,
      start: this.playhead,
      duration: mediaItem.duration,
      trim_start: 0.0,
      speed: 1.0,
      volume: 1.0,
      filter: 'none',
      text: 'Sample Subtitle',
      color: 'white',
      font_size: 28,
      position: 'bottom'
    };

    this.clips.push(newClip);
    this.renderTimeline();
    this.selectClip(id);
    this.syncPreview();
    
    // Automatically grow timeline duration if clip overflows
    const clipEnd = newClip.start + newClip.duration;
    if (clipEnd > this.duration) {
      this.duration = Math.ceil(clipEnd + 5.0);
      this.renderTimeline();
    }
  },

  selectClip(clipId) {
    this.selectedClipId = clipId;
    
    // Highlight active element on timeline
    document.querySelectorAll(".timeline-clip").forEach(el => {
      el.classList.toggle("selected", el.dataset.clipId === clipId);
    });

    const clip = this.clips.find(c => c.id === clipId);
    if (!clip) {
      this.elements.inspectorPlaceholder.style.display = "flex";
      this.elements.inspectorControls.style.display = "none";
      if (this.elements.losslessSection) this.elements.losslessSection.style.display = "none";
      return;
    }

    // Populate inspector
    this.elements.inspectorPlaceholder.style.display = "none";
    this.elements.inspectorControls.style.display = "block";
    
    document.getElementById("inspector-clip-name").textContent = clip.filename.substr(0, 15) + '...';
    document.getElementById("prop-start").value = clip.start;
    document.getElementById("prop-duration").value = clip.duration;
    document.getElementById("prop-trim-start").value = clip.trim_start;
    
    const trackType = this.getTrackType(clip.track);
    
    // Dynamic Move to Track dropdown populator
    const trackSelect = document.getElementById("prop-track-select");
    if (trackSelect) {
      trackSelect.innerHTML = '';
      const compatibleTracks = this.tracks.filter(t => t.type === trackType);
      compatibleTracks.forEach(t => {
        const opt = document.createElement("option");
        opt.value = t.id;
        opt.textContent = t.name;
        opt.selected = t.id === clip.track;
        trackSelect.appendChild(opt);
      });
    }
    
    const filterGroup = document.querySelector(".inspector-video-only");
    const audioGroup = document.querySelector(".inspector-audio-only");
    const textGroup = document.querySelector(".inspector-text-only");

    // Toggle track fields
    if (trackType === 'video') {
      filterGroup.style.display = "flex";
      audioGroup.style.display = "none";
      textGroup.style.display = "none";
      if (this.elements.silenceSection) this.elements.silenceSection.style.display = "block";
      if (this.elements.losslessSection) this.elements.losslessSection.style.display = "block";
      document.getElementById("prop-filter").value = clip.filter;
      this.loadStreamInfo(clip.filename);
    } else if (trackType === 'audio') {
      filterGroup.style.display = "none";
      audioGroup.style.display = "flex";
      textGroup.style.display = "none";
      if (this.elements.silenceSection) this.elements.silenceSection.style.display = "block";
      if (this.elements.losslessSection) this.elements.losslessSection.style.display = "block";
      document.getElementById("prop-volume").value = clip.volume;
      document.getElementById("prop-vol-val").textContent = clip.volume;
      this.loadStreamInfo(clip.filename);
    } else if (trackType === 'text') {
      filterGroup.style.display = "none";
      audioGroup.style.display = "none";
      textGroup.style.display = "block";
      if (this.elements.silenceSection) this.elements.silenceSection.style.display = "none";
      if (this.elements.losslessSection) this.elements.losslessSection.style.display = "none";
      document.getElementById("prop-text-str").value = clip.text;
      document.getElementById("prop-text-color").value = clip.color;
      document.getElementById("prop-text-size").value = clip.font_size;
      document.getElementById("prop-text-position").value = clip.position;
    }

    document.getElementById("prop-speed").value = clip.speed;
    document.getElementById("prop-speed-val").textContent = clip.speed;
  },

  setupInspectorListeners() {
    // Volume slider val update
    document.getElementById("prop-volume").addEventListener("input", (e) => {
      document.getElementById("prop-vol-val").textContent = e.target.value;
      this.updateSelectedClipProperty('volume', parseFloat(e.target.value));
    });

    // Speed slider val update
    document.getElementById("prop-speed").addEventListener("input", (e) => {
      document.getElementById("prop-speed-val").textContent = e.target.value;
      this.updateSelectedClipProperty('speed', parseFloat(e.target.value));
    });

    // Precision inputs update
    document.getElementById("prop-start").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('start', parseFloat(e.target.value) || 0.0);
    });

    document.getElementById("prop-duration").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('duration', parseFloat(e.target.value) || 1.0);
    });

    document.getElementById("prop-trim-start").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('trim_start', parseFloat(e.target.value) || 0.0);
    });

    document.getElementById("prop-filter").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('filter', e.target.value);
    });

    document.getElementById("prop-track-select").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('track', e.target.value);
      this.renderTimeline();
    });

    // Subtitle specific properties
    document.getElementById("prop-text-str").addEventListener("input", (e) => {
      this.updateSelectedClipProperty('text', e.target.value);
    });
    document.getElementById("prop-text-color").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('color', e.target.value);
    });
    document.getElementById("prop-text-size").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('font_size', parseInt(e.target.value) || 24);
    });
    document.getElementById("prop-text-position").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('position', e.target.value);
    });

    // Inspector Delete Clip
    document.getElementById("prop-delete-btn").addEventListener("click", () => {
      if (this.selectedClipId) {
        this.clips = this.clips.filter(c => c.id !== this.selectedClipId);
        this.selectedClipId = null;
        this.selectClip(null);
        this.renderTimeline();
        this.syncPreview();
      }
    });
  },

  updateSelectedClipProperty(prop, value) {
    if (!this.selectedClipId) return;
    const clip = this.clips.find(c => c.id === this.selectedClipId);
    if (clip) {
      clip[prop] = value;
      
      // Live updates
      const clipEl = document.querySelector(`.timeline-clip[data-clip-id="${clip.id}"]`);
      if (clipEl) {
        if (prop === 'start') {
          clipEl.style.left = (value * this.zoom) + 'px';
        } else if (prop === 'duration') {
          clipEl.style.width = (value * this.zoom) + 'px';
        }
      }
      
      this.syncPreview();
    }
  },

  setTool(tool) {
    this.currentTool = tool;
    this.elements.toolSelect.classList.toggle("active", tool === 'select');
    this.elements.toolSplit.classList.toggle("active", tool === 'split');

    if (tool === 'split') {
      this.splitClipAtPlayhead();
      // Auto revert to selection tool
      setTimeout(() => this.setTool('select'), 300);
    }
  },

  splitClipAtPlayhead() {
    // Find active clip at playhead
    const t = this.playhead;
    const clipToSplit = this.clips.find(c => t > c.start && t < (c.start + c.duration));
    
    if (!clipToSplit) {
      if (window.toast) window.toast("❌ No clip found under playhead to split");
      return;
    }

    const duration1 = t - clipToSplit.start;
    const duration2 = clipToSplit.duration - duration1;
    
    // Resize original clip
    clipToSplit.duration = duration1;

    // Create split copy
    const id = `clip_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    const clipCopy = {
      ...clipToSplit,
      id,
      start: t,
      duration: duration2,
      trim_start: clipToSplit.trim_start + (duration1 * clipToSplit.speed)
    };

    this.clips.push(clipCopy);
    this.renderTimeline();
    this.selectClip(id);
    this.syncPreview();

    if (window.toast) window.toast("✂️ Clip split successfully");
  },

  clearTimeline() {
    if (confirm("Are you sure you want to clear the timeline?")) {
      this.clips = [];
      this.selectedClipId = null;
      this.selectClip(null);
      this.seekTo(0);
      this.renderTimeline();
      this.syncPreview();
    }
  },

  updateZoom(z) {
    this.zoom = z;
    this.renderTimeline();
    this.updatePlayheadLine();
  },

  seekTo(time) {
    this.playhead = Math.max(0, Math.min(time, this.duration));
    this.updatePlayheadLine();
    this.syncPreview();
  },

  updatePlayheadLine() {
    const leftPos = (this.playhead * this.zoom) + 120;
    this.elements.playheadLine.style.left = leftPos + 'px';
    
    // Center viewport scrolling around playhead if playing
    if (this.isPlaying) {
      const container = this.elements.scrollContainer;
      const width = container.clientWidth;
      if (leftPos > container.scrollLeft + width - 100) {
        container.scrollLeft = leftPos - 100;
      }
    }

    // Format Digital Timecode
    const formatTimecode = (sec) => {
      const h = Math.floor(sec / 3600).toString().padStart(2, '0');
      const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
      const s = Math.floor(sec % 60).toString().padStart(2, '0');
      const ms = Math.floor((sec % 1) * 100).toString().padStart(2, '0');
      return `${h}:${m}:${s}.${ms}`;
    };

    this.elements.timecode.textContent = formatTimecode(this.playhead);
  },

  renderTimeline() {
    const ruler = this.elements.ruler;
    const totalWidth = this.duration * this.zoom;

    // Stretch ruler and grid width to container width if needed to prevent empty spaces
    const containerWidth = this.elements.scrollContainer ? (this.elements.scrollContainer.clientWidth || 0) : 0;
    const gridWidth = Math.max(totalWidth + 120, containerWidth);

    // Render Ruler Tick Marks
    ruler.style.width = gridWidth + 'px';
    ruler.innerHTML = '';
    
    for (let s = 0; s <= this.duration; s++) {
      if (s % 5 === 0 || this.zoom > 35) {
        const tick = document.createElement("div");
        tick.className = "ruler-tick";
        // Tick is shifted by 120px to align perfectly with track lanes
        tick.style.left = (s * this.zoom) + 120 + 'px';
        if (s % 5 === 0 || this.zoom > 50) {
          tick.textContent = s + "s";
        }
        ruler.appendChild(tick);
      }
    }

    // Adjust grid width
    this.elements.timelineGrid.style.width = gridWidth + 'px';

    // Clear dynamic track rows
    const gridEl = this.elements.timelineGrid;
    
    // Clear all existing track-row elements
    gridEl.querySelectorAll(".track-row").forEach(r => r.remove());

    // Render each dynamic track row
    this.tracks.forEach(track => {
      const row = document.createElement("div");
      row.className = "track-row";
      row.dataset.track = track.id;

      let iconName = 'film';
      if (track.type === 'audio') iconName = 'music';
      else if (track.type === 'text') iconName = 'chat';

      row.innerHTML = `
        <div class="track-info">
          <span class="media-icon" data-icon="${iconName}"></span>
          <span style="flex-grow: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 5px;">${track.name}</span>
          <button class="track-delete-btn" data-track-id="${track.id}" title="Delete Track" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px; display: flex; align-items: center; justify-content: center; border-radius: 4px; transition: background 0.2s;">
            <span class="media-icon" data-icon="x"></span>
          </button>
        </div>
        <div class="track-lane" id="${track.id}-track-lane"></div>
      `;

      // Bind delete track button
      row.querySelector(".track-delete-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        this.deleteTrack(track.id);
      });

      gridEl.appendChild(row);
    });

    // Populate clips in dynamic tracks
    this.clips.forEach(clip => {
      // Ensure target track still exists, or default it to first compatible one
      clip.track = this.ensureTrackExists(clip.track);

      const clipEl = document.createElement("div");
      clipEl.className = "timeline-clip";
      clipEl.dataset.clipId = clip.id;
      clipEl.dataset.trackType = this.getTrackType(clip.track);
      clipEl.style.left = (clip.start * this.zoom) + 'px';
      clipEl.style.width = (clip.duration * this.zoom) + 'px';
      clipEl.textContent = clip.filename.substr(0, 20);

      if (this.selectedClipId === clip.id) {
        clipEl.classList.add("selected");
      }

      // Drag to Move timeline clip
      clipEl.addEventListener("mousedown", (e) => {
        if (this.currentTool !== 'select') return;
        e.stopPropagation();
        e.preventDefault();

        this.selectClip(clip.id);

        const startX = e.clientX;
        const initialStart = clip.start;

        const onMouseMove = (moveEvt) => {
          const deltaX = moveEvt.clientX - startX;
          const deltaT = deltaX / this.zoom;
          let newStart = Math.max(0, initialStart + deltaT);
          
          // Snap start time to 0.1s steps
          newStart = Math.round(newStart * 10) / 10;
          
          clip.start = newStart;
          clipEl.style.left = (newStart * this.zoom) + 'px';

          const startInput = document.getElementById("prop-start");
          if (startInput) startInput.value = newStart;
          
          this.updatePlayheadLine();
        };

        const onMouseUp = () => {
          document.removeEventListener("mousemove", onMouseMove);
          document.removeEventListener("mouseup", onMouseUp);
          this.renderTimeline();
          this.syncPreview();
        };

        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
      });

      const lane = document.getElementById(`${clip.track}-track-lane`);
      if (lane) {
        lane.appendChild(clipEl);
      }
    });

    // Automatically recompile dynamic SVG icons for new track headers
    if (window.icon) {
      gridEl.querySelectorAll('.media-icon[data-icon]').forEach(n => {
        n.innerHTML = window.icon(n.dataset.icon, 13);
      });
    }
  },

  syncPreview(isLoopRunning = false) {
    const vEl = this.elements.videoPreview;
    const aEl = this.elements.audioPreview;
    const placeholder = this.elements.previewPlaceholder;
    const textOverlay = this.elements.liveText;

    // Find active clips at current playhead
    const activeVideo = this.clips.find(c => this.getTrackType(c.track) === 'video' && this.playhead >= c.start && this.playhead < (c.start + c.duration));
    const activeAudio = this.clips.find(c => this.getTrackType(c.track) === 'audio' && this.playhead >= c.start && this.playhead < (c.start + c.duration));
    const activeText = this.clips.find(c => this.getTrackType(c.track) === 'text' && this.playhead >= c.start && this.playhead < (c.start + c.duration));

    // 1. VIDEO PREVIEW SYNC
    if (activeVideo) {
      placeholder.style.display = "none";
      
      const videoSrc = `/data/images/${activeVideo.filename}`;
      if (vEl.dataset.currentSrc !== videoSrc) {
        vEl.src = videoSrc;
        vEl.dataset.currentSrc = videoSrc;
        vEl.load();
      }

      // Calculate time offset inside source clip
      const offset = (this.playhead - activeVideo.start) * activeVideo.speed + activeVideo.trim_start;
      
      // Apply filters live in preview screen using CSS mapping
      vEl.className = '';
      if (activeVideo.filter && activeVideo.filter !== 'none') {
        vEl.classList.add(`filter-${activeVideo.filter}`);
      }

      if (vEl.readyState >= 1) {
        if (!isLoopRunning || Math.abs(vEl.currentTime - offset) > 0.25) {
          vEl.currentTime = offset;
        }
      }

      if (this.isPlaying) {
        vEl.play().catch(() => {});
      } else {
        vEl.pause();
      }

      // Handle ASCII Art preview versus standard video display
      if (activeVideo.filter === 'ascii_art') {
        vEl.style.display = "none";
        this.elements.asciiPreview.style.display = "flex";
        this.updateAsciiPreview(vEl);
      } else {
        this.elements.asciiPreview.style.display = "none";
        vEl.style.display = "block";
      }
    } else {
      vEl.style.display = "none";
      vEl.pause();
      this.elements.asciiPreview.style.display = "none";
      placeholder.style.display = "flex";
    }

    // 2. AUDIO PREVIEW SYNC
    if (activeAudio) {
      const audioSrc = activeAudio.filename.toLowerCase().endsWith('.mp3') || activeAudio.filename.toLowerCase().endsWith('.wav') ? 
        `/data/audio/${activeAudio.filename}` : `/data/images/${activeAudio.filename}`;
        
      if (aEl.dataset.currentSrc !== audioSrc) {
        aEl.src = audioSrc;
        aEl.dataset.currentSrc = audioSrc;
        aEl.load();
      }

      const offset = (this.playhead - activeAudio.start) * activeAudio.speed + activeAudio.trim_start;
      aEl.volume = activeAudio.volume;

      if (aEl.readyState >= 1) {
        if (!isLoopRunning || Math.abs(aEl.currentTime - offset) > 0.25) {
          aEl.currentTime = offset;
        }
      }

      if (this.isPlaying) {
        aEl.play().catch(() => {});
      } else {
        aEl.pause();
      }
    } else {
      aEl.pause();
    }

    // 3. TEXT OVERLAY PREVIEW SYNC
    if (activeText) {
      textOverlay.style.display = "block";
      textOverlay.textContent = activeText.text;
      textOverlay.style.color = activeText.color;
      textOverlay.style.fontSize = activeText.font_size + 'px';
      
      // Reset position classes
      textOverlay.className = "live-text-container " + activeText.position;
    } else {
      textOverlay.style.display = "none";
    }
  },

  updateAsciiPreview(videoEl) {
    const asciiEl = this.elements.asciiPreview;
    if (!videoEl || videoEl.readyState < 2) {
      return;
    }

    // Lazy load temporary canvas
    if (!this.asciiCanvas) {
      this.asciiCanvas = document.createElement("canvas");
      this.asciiCtx = this.asciiCanvas.getContext("2d");
    }

    const canvas = this.asciiCanvas;
    const ctx = this.asciiCtx;

    // Grid size for the monospace layout preview
    const cols = 120;
    const rows = 52;

    canvas.width = cols;
    canvas.height = rows;

    // Draw the active frame to canvas
    ctx.drawImage(videoEl, 0, 0, cols, rows);

    let imgData;
    try {
      imgData = ctx.getImageData(0, 0, cols, rows).data;
    } catch (e) {
      return;
    }

    const CHARS = " .:-=+*#%@";
    const numChars = CHARS.length;
    let asciiStr = "";

    for (let y = 0; y < rows; y++) {
      let line = "";
      for (let x = 0; x < cols; x++) {
        const offset = (y * cols + x) * 4;
        const r = imgData[offset];
        const g = imgData[offset + 1];
        const b = imgData[offset + 2];

        // Luma formula for grayscale mapping
        const brightness = 0.299 * r + 0.587 * g + 0.114 * b;
        const charIdx = Math.min(Math.floor(brightness / 256 * numChars), numChars - 1);
        line += CHARS[charIdx];
      }
      asciiStr += line + "\n";
    }

    asciiEl.textContent = asciiStr;
  },

  togglePlay() {
    if (this.isPlaying) {
      this.pause();
    } else {
      this.play();
    }
  },

  play() {
    this.isPlaying = true;
    this.elements.playPauseBtn.innerHTML = window.icon ? window.icon('pause', 20) : '⏸';
    this.lastFrameTime = performance.now();
    this.animationFrameId = requestAnimationFrame((t) => this.playbackStep(t));
    this.syncPreview();
    
    const editorStatus = document.getElementById("editor-status-text");
    if (editorStatus) editorStatus.textContent = "Playing preview";
  },

  pause() {
    this.isPlaying = false;
    this.elements.playPauseBtn.innerHTML = window.icon ? window.icon('play', 20) : '▶';
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
    }
    
    // Pause previews
    this.elements.videoPreview.pause();
    this.elements.audioPreview.pause();
    
    const editorStatus = document.getElementById("editor-status-text");
    if (editorStatus) editorStatus.textContent = "Paused";
  },

  stop() {
    this.pause();
    this.seekTo(0);
  },

  playbackStep(now) {
    if (!this.isPlaying) return;
    const delta = (now - this.lastFrameTime) / 1000;
    this.lastFrameTime = now;

    this.playhead += delta;

    if (this.playhead >= this.duration) {
      this.stop();
      return;
    }

    this.updatePlayheadLine();
    this.syncPreview(true);

    this.animationFrameId = requestAnimationFrame((t) => this.playbackStep(t));
  },

  async exportTimeline() {
    const renderBtn = this.elements.renderBtn;
    const progressContainer = document.getElementById("editor-progress-container");
    const progressBar = document.getElementById("editor-progress-bar");
    const progressPct = document.getElementById("editor-progress-pct");
    const statusText = document.getElementById("editor-status-text");

    const format = document.getElementById("export-format").value;
    const res = document.getElementById("export-res").value;
    const fps = document.getElementById("export-fps").value;

    if (this.clips.length === 0) {
      if (window.toast) window.toast("⚠️ Import at least one video, image, or audio clip to render !");
      return;
    }

    this.pause();

    // Map properties strictly for backend compiler
    const videoTrackClips = this.clips.filter(c => this.getTrackType(c.track) === 'video').map(c => ({
      filename: c.filename,
      start: c.start,
      duration: c.duration,
      trim_start: c.trim_start,
      speed: c.speed,
      filter: c.filter
    }));

    const audioTrackClips = this.clips.filter(c => this.getTrackType(c.track) === 'audio').map(c => ({
      filename: c.filename,
      start: c.start,
      duration: c.duration,
      trim_start: c.trim_start,
      volume: c.volume,
      speed: c.speed
    }));

    const textTrackClips = this.clips.filter(c => this.getTrackType(c.track) === 'text').map(c => ({
      text: c.text,
      start: c.start,
      duration: c.duration,
      color: c.color,
      font_size: c.font_size,
      position: c.position
    }));

    // Trigger rendering progress state
    renderBtn.disabled = true;
    progressContainer.style.display = "flex";
    statusText.textContent = "Rendering...";
    
    // Simulate compilation progress
    let simPct = 0;
    progressBar.style.width = '0%';
    progressPct.textContent = '0%';
    const progressInterval = setInterval(() => {
      simPct = Math.min(simPct + Math.floor(Math.random() * 5) + 1, 95);
      progressBar.style.width = simPct + '%';
      progressPct.textContent = simPct + '%';
    }, 400);

    try {
      const resp = await fetch("/studio/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          export_format: format,
          resolution: res,
          fps: parseInt(fps),
          tracks: {
            video: videoTrackClips,
            audio: audioTrackClips,
            text: textTrackClips
          }
        })
      });

      clearInterval(progressInterval);

      if (resp.ok) {
        const result = await resp.json();
        
        progressBar.style.width = '100%';
        progressPct.textContent = '100%';
        
        setTimeout(() => {
          progressContainer.style.display = "none";
          renderBtn.disabled = false;
          statusText.textContent = "Idle";
          
          if (window.toast) window.toast("🎉 Compilation completed! Saved to gallery.");
          
          this.close();

          // Sync the main Clawzd Media Studio gallery view immediately
          const mediaStudioEl = document.getElementById("media-refresh");
          if (mediaStudioEl) {
            mediaStudioEl.click();
          }
        }, 1000);

      } else {
        const err = await resp.json();
        throw new Error(err.detail || "Server failed to compile timeline");
      }

    } catch (e) {
      clearInterval(progressInterval);
      progressContainer.style.display = "none";
      renderBtn.disabled = false;
      statusText.textContent = "Error";
      
      console.error(e);
      if (window.toast) window.toast("❌ Rendering failed: " + e.message);
    }
  },

  async generateAIPlan() {
    const promptInput = this.elements.aiPrompt;
    const planBtn = this.elements.aiPlanBtn;
    if (!promptInput || !planBtn) return;
    const promptVal = promptInput.value.trim();

    if (!promptVal) {
      if (window.toast) window.toast("⚠️ Please enter a prompt for the AI to plan!");
      return;
    }

    const originalHtml = planBtn.innerHTML;
    planBtn.disabled = true;
    planBtn.innerHTML = `⚡ Planning...`;

    try {
      const resp = await fetch("/studio/ai_plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptVal })
      });

      if (!resp.ok) {
        throw new Error("Server failed to generate a plan");
      }

      const plan = await resp.json();
      if (plan && plan.clips) {
        this.clips = [];
        this.duration = parseFloat(plan.duration) || 30.0;
        
        plan.clips.forEach(clip => {
          if (!clip.id) {
            clip.id = "clip_" + Math.random().toString(36).substr(2, 9);
          }
          // Ensure the planned track exists or maps perfectly
          clip.track = this.ensureTrackExists(clip.track);
          this.clips.push(clip);
        });

        this.renderTimeline();
        this.seekTo(0);
        
        if (window.toast) {
          if (plan.error_fallback) {
            window.toast("⚡ AI Montage fallback generated using gallery assets!");
          } else {
            window.toast("🎉 AI Smart Montage successfully generated & populated!");
          }
        }
      } else {
        throw new Error("Invalid plan schema returned from server");
      }
    } catch (e) {
      console.error(e);
      if (window.toast) window.toast("❌ AI Planning failed: " + e.message);
    } finally {
      planBtn.disabled = false;
      planBtn.innerHTML = originalHtml;
    }
  },

  async searchStockMedia() {
    const query = this.elements.stockSearchQuery.value.trim();
    const type = this.elements.stockSearchType.value;
    const btn = this.elements.stockSearchBtn;
    const list = this.elements.stockListContainer;
    if (!list) return;

    list.innerHTML = `<div class="empty-inspector" style="padding:20px; color:var(--text-secondary);">🔍 Searching stock library...</div>`;
    btn.disabled = true;

    try {
      const resp = await fetch("/studio/search_stock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, type })
      });

      if (!resp.ok) throw new Error("Search failed");

      const data = await resp.json();
      list.innerHTML = "";

      if (!data.results || data.results.length === 0) {
        list.innerHTML = `<div class="empty-inspector" style="padding:20px; color:var(--text-secondary);">No results found. Try another query like 'cyberpunk' or 'sunrise'!</div>`;
        return;
      }

      data.results.forEach(item => {
        const card = document.createElement("div");
        card.className = "gallery-item-card";
        card.style = "display: flex; gap: 10px; background: rgba(255,255,255,0.02); border: 1px solid var(--border); padding: 8px; border-radius: var(--radius-sm); align-items: center; position: relative;";
        
        let thumbHtml = "";
        if (item.thumbnail) {
          thumbHtml = `<img src="${item.thumbnail}" style="width: 60px; height: 45px; object-fit: cover; border-radius: 3px;" alt="${item.title}">`;
        } else {
          thumbHtml = `<div style="width: 60px; height: 45px; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.3); border-radius: 3px; font-size: 16px;">🎵</div>`;
        }

        card.innerHTML = `
          ${thumbHtml}
          <div style="flex: 1; min-width: 0;">
            <h4 style="font-size: 12px; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text-primary);">${item.title}</h4>
            <span style="font-size: 10px; color: var(--text-secondary);">${Math.round(item.duration)}s • ${item.type.toUpperCase()}</span>
          </div>
          <button class="editor-btn primary" data-url="${item.url}" data-title="${item.title}" data-type="${item.type}" style="padding: 4px 8px; font-size: 10px; background: var(--accent); color: white; border: none; border-radius: var(--radius-xs); cursor: pointer;">
            📥 Ingest
          </button>
        `;

        card.querySelector("button").addEventListener("click", (e) => this.downloadStockMedia(e.currentTarget));
        list.appendChild(card);
      });

    } catch (e) {
      console.error(e);
      list.innerHTML = `<div class="empty-inspector" style="padding:20px; color:red;">❌ Error loading stock results</div>`;
    } finally {
      btn.disabled = false;
    }
  },

  async downloadStockMedia(btn) {
    const url = btn.dataset.url;
    const title = btn.dataset.title;
    const type = btn.dataset.type;

    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = "⏳ Ingesting...";

    try {
      const resp = await fetch("/studio/download_stock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, title, type })
      });

      if (!resp.ok) throw new Error("Download failed");

      const res = await resp.json();
      if (window.toast) window.toast(`🎉 Ingested "${title}" into gallery!`);
      btn.innerHTML = "✅ Ingested";
      btn.style.background = "#22c55e";

      // Reload gallery assets instantly
      await this.loadGalleryAssets();

    } catch (e) {
      console.error(e);
      if (window.toast) window.toast("❌ Ingest failed: " + e.message);
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  },

  async autoSilenceCutClip() {
    if (!this.selectedClipId) return;
    const clip = this.clips.find(c => c.id === this.selectedClipId);
    if (!clip) return;

    const threshold = parseFloat(this.elements.silenceDb.value);
    const minDur = parseFloat(this.elements.silenceDur.value);
    const padding = parseFloat(this.elements.silencePadding.value) || 0.1;
    const mode = this.elements.silenceMode.value; // "remove" or "speed_up"
    const btn = this.elements.silenceBtn;

    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `⏳ Parsing...`;

    try {
      const resp = await fetch("/studio/silence_detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: clip.filename,
          threshold_db: threshold,
          min_duration: minDur,
          padding: padding
        })
      });

      if (!resp.ok) {
        throw new Error("Silence detection failed on server");
      }

      const res = await resp.json();
      const segments = res.speech_segments; // Speech intervals: [{start: 0, end: 1.2}, ...]
      const silences = res.silences; // Silence intervals: [{start: 1.2, end: 2.5, duration: 1.3}, ...]

      if (!segments || segments.length === 0) {
        if (window.toast) window.toast("❌ No speech segments detected!");
        return;
      }

      const origClipStart = clip.start;
      const origClipTrim = clip.trim_start;
      const origClipSpeed = clip.speed;

      const newClips = [];

      if (mode === "remove") {
        let currentTimelineOffset = origClipStart;
        
        segments.forEach((seg, idx) => {
          const sourceDuration = seg.end - seg.start;
          const timelineDuration = sourceDuration / origClipSpeed;
          const trimStart = origClipTrim + seg.start;

          const newId = `clip_${Date.now()}_speech_${idx}_${Math.random().toString(36).substr(2, 4)}`;
          newClips.push({
            ...clip,
            id: newId,
            start: currentTimelineOffset,
            duration: timelineDuration,
            trim_start: trimStart
          });

          currentTimelineOffset += timelineDuration;
        });

      } else if (mode === "speed_up") {
        let currentTimelineOffset = origClipStart;
        const allIntervals = [];

        segments.forEach(s => allIntervals.push({ type: 'speech', start: s.start, end: s.end }));
        silences.forEach(s => allIntervals.push({ type: 'silence', start: s.start, end: s.end }));
        allIntervals.sort((a, b) => a.start - b.start);

        allIntervals.forEach((interval, idx) => {
          const sourceDuration = interval.end - interval.start;
          if (sourceDuration < 0.05) return;

          const speedMultiplier = interval.type === 'silence' ? 6.0 : 1.0;
          const clipSpeed = origClipSpeed * speedMultiplier;

          const timelineDuration = sourceDuration / clipSpeed;
          const trimStart = origClipTrim + interval.start;

          const newId = `clip_${Date.now()}_${interval.type}_${idx}_${Math.random().toString(36).substr(2, 4)}`;
          newClips.push({
            ...clip,
            id: newId,
            start: currentTimelineOffset,
            duration: timelineDuration,
            trim_start: trimStart,
            speed: clipSpeed,
            filter: interval.type === 'silence' ? 'grayscale' : clip.filter
          });

          currentTimelineOffset += timelineDuration;
        });
      }

      this.clips = this.clips.filter(c => c.id !== clip.id);
      this.clips.push(...newClips);

      this.renderTimeline();
      this.selectClip(null);
      this.syncPreview();

      const timeSaved = Math.round(clip.duration - newClips.reduce((sum, c) => sum + c.duration, 0));
      if (window.toast) {
        window.toast(`✂️ Auto Silence Cut complete! Saved ~${timeSaved}s of empty silence!`);
      }

    } catch (e) {
      console.error(e);
      if (window.toast) window.toast("❌ Silence Cut failed: " + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  },

  async loadStreamInfo(filename) {
    if (!this.elements.streamInfoDetails) return;
    this.elements.streamInfoDetails.textContent = "⏳ Loading stream details...";
    
    try {
      const resp = await fetch("/studio/stream_info", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename })
      });
      
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.streams) {
          const videoStream = data.streams.find(s => s.codec_type === 'video');
          const audioStream = data.streams.find(s => s.codec_type === 'audio');
          
          let infoText = "";
          if (videoStream) {
            infoText += `📹 Video: ${videoStream.codec_name} (${videoStream.r_frame_rate} fps)\n`;
          }
          if (audioStream) {
            infoText += `🎵 Audio: ${audioStream.codec_name} (${audioStream.channels}ch)\n`;
          }
          if (!videoStream && !audioStream) {
            infoText = "No streams detected.";
          }
          
          this.elements.streamInfoDetails.textContent = infoText.trim();
        } else {
          this.elements.streamInfoDetails.textContent = "Unavailable metadata format.";
        }
      } else {
        this.elements.streamInfoDetails.textContent = "Failed to load metadata.";
      }
    } catch (e) {
      console.error(e);
      this.elements.streamInfoDetails.textContent = "Error reading streams.";
    }
  },

  async captureSnapshot() {
    // Find active video clip under playhead
    const activeVideo = this.clips.find(
      c => this.getTrackType(c.track) === 'video' && 
      this.playhead >= c.start && 
      this.playhead < (c.start + c.duration)
    );

    if (!activeVideo) {
      if (window.toast) window.toast("⚠️ No active video clip under playhead to capture !");
      return;
    }

    const sourceTime = (this.playhead - activeVideo.start) * activeVideo.speed + activeVideo.trim_start;
    if (window.toast) window.toast("📸 Snapping high-res frame...");

    try {
      const resp = await fetch("/studio/snapshot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: activeVideo.filename,
          time: sourceTime
        })
      });

      if (resp.ok) {
        if (window.toast) window.toast("🎉 Frame snapped successfully! Saved in gallery.");
        await this.loadGalleryAssets();
        
        // Auto refresh base studio if elements exists
        const refreshEl = document.getElementById("media-refresh");
        if (refreshEl) refreshEl.click();
      } else {
        throw new Error("Server failed to extract snapshot");
      }
    } catch (e) {
      console.error(e);
      if (window.toast) window.toast("❌ Snapshot failed: " + e.message);
    }
  },

  async triggerLosslessTrim() {
    if (!this.selectedClipId) return;
    const clip = this.clips.find(c => c.id === this.selectedClipId);
    if (!clip) return;

    const startVal = parseFloat(document.getElementById("prop-trim-start").value) || 0.0;
    const durationVal = parseFloat(document.getElementById("prop-duration").value) || 5.0;
    const btn = this.elements.losslessTrimBtn;
    
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `⚡ Cutting...`;

    try {
      const resp = await fetch("/studio/lossless_trim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: clip.filename,
          start: startVal,
          duration: durationVal
        })
      });

      if (resp.ok) {
        const data = await resp.json();
        if (window.toast) window.toast(`✂️ Fast Cut success! Created: ${data.filename}`);
        
        // Update clip with newly trimmed lossless asset
        clip.filename = data.filename;
        clip.trim_start = 0.0;
        
        this.renderTimeline();
        await this.loadGalleryAssets();
        this.selectClip(clip.id);
        this.syncPreview();
        
        const refreshEl = document.getElementById("media-refresh");
        if (refreshEl) refreshEl.click();
      } else {
        const err = await resp.json();
        throw new Error(err.detail || "Server failed to crop clip");
      }
    } catch (e) {
      console.error(e);
      if (window.toast) window.toast("❌ Fast Cut failed: " + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
};

// Auto initialize on DOM Load
document.addEventListener("DOMContentLoaded", () => {
  window.StudioEditor.init();
});
