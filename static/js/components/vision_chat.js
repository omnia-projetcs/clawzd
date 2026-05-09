/**
 * Clawzd — Vision Chat Component
 *
 * Handles image upload, paste, drag-and-drop for multimodal vision chat.
 * Images are queued as base64 data URLs and sent alongside the user message.
 */
(function () {
  'use strict';

  /** @type {string[]} Queue of base64 data URLs */
  let pendingImages = [];

  const MAX_IMAGES = 5;
  const MAX_SIZE_MB = 10;

  // ---------------------------------------------------------------------------
  // DOM references (resolved lazily)
  // ---------------------------------------------------------------------------
  function $(id) { return document.getElementById(id); }

  function getPreviewStrip() { return $('chat-image-preview'); }
  function getVisionInput() { return $('chat-vision-input'); }
  function getVisionBtn() { return $('btn-vision-upload'); }
  function getChatInput() { return $('chat-input'); }
  function getWrapper() { return document.querySelector('.chat-input-wrapper'); }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /** Get queued images and clear the queue. */
  window.visionChatGetImages = function () {
    const imgs = [...pendingImages];
    pendingImages = [];
    _renderPreview();
    return imgs;
  };

  /** Check if there are pending images. */
  window.visionChatHasImages = function () {
    return pendingImages.length > 0;
  };

  // ---------------------------------------------------------------------------
  // Image processing
  // ---------------------------------------------------------------------------

  /**
   * Read a File object and add to the pending queue as a base64 data URL.
   * @param {File} file
   */
  function addImageFile(file) {
    if (!file.type.startsWith('image/')) return;
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      console.warn('[VisionChat] Image too large:', file.name, file.size);
      return;
    }
    if (pendingImages.length >= MAX_IMAGES) {
      console.warn('[VisionChat] Max images reached:', MAX_IMAGES);
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      pendingImages.push(e.target.result);
      _renderPreview();
    };
    reader.readAsDataURL(file);
  }

  // ---------------------------------------------------------------------------
  // Preview rendering
  // ---------------------------------------------------------------------------

  function _renderPreview() {
    const strip = getPreviewStrip();
    const btn = getVisionBtn();
    if (!strip) return;

    if (pendingImages.length === 0) {
      strip.style.display = 'none';
      strip.innerHTML = '';
      if (btn) btn.classList.remove('has-images');
      return;
    }

    strip.style.display = 'flex';
    if (btn) btn.classList.add('has-images');

    strip.innerHTML = pendingImages.map((dataUrl, idx) => `
      <div class="vision-thumb" data-idx="${idx}">
        <img src="${dataUrl}" alt="Image ${idx + 1}">
        <button class="vision-thumb-remove" data-idx="${idx}" title="Remove">&times;</button>
      </div>
    `).join('');

    // Bind remove buttons
    strip.querySelectorAll('.vision-thumb-remove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.idx, 10);
        pendingImages.splice(idx, 1);
        _renderPreview();
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Event bindings
  // ---------------------------------------------------------------------------

  function init() {
    const visionBtn = getVisionBtn();
    const visionInput = getVisionInput();
    const chatInput = getChatInput();
    const wrapper = getWrapper();

    // Vision upload button click
    if (visionBtn && visionInput) {
      visionBtn.addEventListener('click', () => visionInput.click());
      visionInput.addEventListener('change', (e) => {
        for (const file of e.target.files) {
          addImageFile(file);
        }
        visionInput.value = '';
      });
    }

    // Paste images into chat input
    if (chatInput) {
      chatInput.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
          if (item.type.startsWith('image/')) {
            e.preventDefault();
            const file = item.getAsFile();
            if (file) addImageFile(file);
          }
        }
      });
    }

    // Drag-and-drop images onto input area
    if (wrapper) {
      wrapper.addEventListener('dragover', (e) => {
        e.preventDefault();
        wrapper.classList.add('vision-dragover');
      });
      wrapper.addEventListener('dragleave', () => {
        wrapper.classList.remove('vision-dragover');
      });
      wrapper.addEventListener('drop', (e) => {
        e.preventDefault();
        wrapper.classList.remove('vision-dragover');
        for (const file of e.dataTransfer.files) {
          if (file.type.startsWith('image/')) {
            addImageFile(file);
          }
        }
      });
    }

    console.log('[VisionChat] Initialized');
  }

  // Init on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
