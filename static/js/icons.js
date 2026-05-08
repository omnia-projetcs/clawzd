/**
 * Clawzd SVG Icon System
 * Modern, clean icons sized 16×16 using currentColor
 */
const ICONS = {
  // ---- Navigation / General ----
  bolt: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-bolt"></use></svg>`,

  chat: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-chat"></use></svg>`,

  monitor: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-monitor"></use></svg>`,

  settings: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-settings"></use></svg>`,

  // ---- File Tree ----
  folder: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-folder"></use></svg>`,

  folderOpen: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-folder-open"></use></svg>`,

  filePlus: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-file-plus"></use></svg>`,

  refresh: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-refresh"></use></svg>`,

  search: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-search"></use></svg>`,

  upload: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-upload"></use></svg>`,

  // ---- Terminal ----
  terminal: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-terminal"></use></svg>`,

  trash: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-trash"></use></svg>`,

  clipboard: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-clipboard"></use></svg>`,

  chevronDown: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-chevron-down"></use></svg>`,

  chevronUp: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-chevron-up"></use></svg>`,

  helpCircle: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-help-circle"></use></svg>`,

  // ---- Git ----
  gitBranch: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-git-branch"></use></svg>`,

  gitCommit: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-git-commit"></use></svg>`,

  gitMerge: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-git-merge"></use></svg>`,

  gitPull: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-git-pull"></use></svg>`,

  arrowDown: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-arrow-down"></use></svg>`,

  arrowUp: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-arrow-up"></use></svg>`,

  plus: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-plus"></use></svg>`,

  check: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-check"></use></svg>`,

  x: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-x"></use></svg>`,

  clock: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-clock"></use></svg>`,

  // ---- Graph / Chart ----
  barChart: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-bar-chart"></use></svg>`,

  // ---- Link ----
  link: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-link"></use></svg>`,

  // ---- File ----
  file: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-file"></use></svg>`,

  fileText: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-file-text"></use></svg>`,

  // ---- Send ----
  send: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-send"></use></svg>`,

  // ---- Activity ----
  activity: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-activity"></use></svg>`,

  // ---- Code ----
  code: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-code"></use></svg>`,

  // ---- Pen / Write ----
  pen: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-pen"></use></svg>`,

  // ---- Shield / Audit ----
  shield: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-shield"></use></svg>`,

  // ---- Layout / Architect ----
  layers: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-layers"></use></svg>`,

  // ---- Palette / Design ----
  palette: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-palette"></use></svg>`,

  // ---- Diff ----
  diff: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-diff"></use></svg>`,

  // ---- Download ----
  download: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-download"></use></svg>`,

  // ---- Mic ----
  mic: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-mic"></use></svg>`,

  // ---- Paperclip / Attach ----
  paperclip: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-paperclip"></use></svg>`,

  // ---- Save ----
  save: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-save"></use></svg>`,

  // ---- Copy ----
  copy: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-copy"></use></svg>`,

  // ---- Eye ----
  eye: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-eye"></use></svg>`,

  // ---- Model / CPU ----
  cpu: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-cpu"></use></svg>`,

  // ---- Record / Dot ----
  circle: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-circle"></use></svg>`,

  // ---- Menu ----
  menu: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-menu"></use></svg>`,

  // ---- Tablet ----
  tablet: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-tablet"></use></svg>`,

  // ---- Smartphone ----
  smartphone: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-smartphone"></use></svg>`,

  // ---- External Link ----
  externalLink: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-external-link"></use></svg>`,

  // ---- New additions for Media/Automation ----
  play: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-play"></use></svg>`,
  pause: (s = 16) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>`,
  music: (s = 16) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
  sparkles: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-sparkles"></use></svg>`,
  image: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-image"></use></svg>`,
  video: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-video"></use></svg>`,
  camera: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-camera"></use></svg>`,
  flower: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-flower"></use></svg>`,
  film: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-film"></use></svg>`,
  box: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-box"></use></svg>`,
  bot: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-bot"></use></svg>`,
  sunset: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-sunset"></use></svg>`,
  penTool: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-pen-tool"></use></svg>`,
  cloud: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-cloud"></use></svg>`,
  hourglass: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-hourglass"></use></svg>`,
  checkSquare: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-check-square"></use></svg>`,
  archive: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-archive"></use></svg>`,
  chevronLeft: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-chevron-left"></use></svg>`,
  chevronRight: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-chevron-right"></use></svg>`,
  wand: (s = 16) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 4-2 2"/><path d="m17 6-2 2"/><path d="m19 8-2 2"/><path d="m21 10-2 2"/><path d="M14 6l4 4"/><path d="M3 21l11-11"/><path d="M21 3l-3 3"/><path d="m12 15-2 2"/></svg>`,
  kanban: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-kanban"></use></svg>`,
  timeline: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-timeline"></use></svg>`,
  importTxt: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-import-txt"></use></svg>`,
  github: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-github"></use></svg>`,
  sparkles2: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-sparkles2"></use></svg>`,
  layout: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-layout"></use></svg>`,
  undo: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-undo"></use></svg>`,
  redo: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-redo"></use></svg>`,
  githubAlt: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-github-alt"></use></svg>`,
  grid: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-grid"></use></svg>`,
  list: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-list"></use></svg>`,
  circleSlash: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-circle-slash"></use></svg>`,
  tableIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-table-icon"></use></svg>`,
  imageIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-image-icon"></use></svg>`,
  fileTextIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-file-text-icon"></use></svg>`,
  clipboardCheck: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-clipboard-check"></use></svg>`,
  monitorIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-monitor-icon"></use></svg>`,
  presentationIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-presentation-icon"></use></svg>`,
  smile: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-smile"></use></svg>`,
  square: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-square"></use></svg>`,
  rectangle: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-rectangle"></use></svg>`,
  circleIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-circle-icon"></use></svg>`,
  triangle: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-triangle"></use></svg>`,
  diamond: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-diamond"></use></svg>`,
  pentagon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-pentagon"></use></svg>`,
  hexagon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-hexagon"></use></svg>`,
  star: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-star"></use></svg>`,
  heart: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-heart"></use></svg>`,
  cross: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-cross"></use></svg>`,
  arrowRight: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-arrow-right"></use></svg>`,
  chevronRightIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-chevron-right-icon"></use></svg>`,
  cloudIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-cloud-icon"></use></svg>`,
  cylinder: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-cylinder"></use></svg>`,
  chatIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-chat-icon"></use></svg>`,
  trapezoid: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-trapezoid"></use></svg>`,
  parallelogram: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-parallelogram"></use></svg>`,
  doubleCircle: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-double-circle"></use></svg>`,
  undoIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-undo-icon"></use></svg>`,
  redoIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-redo-icon"></use></svg>`,
  settingsIcon: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-settings-icon"></use></svg>`,
  bell: (s = 16) => `<svg class="ic" width="${s}" height="${s}"><use href="#icon-bell"></use></svg>`,
};

// Helper: create icon element
function icon(name, size) {
  const fn = ICONS[name];
  if (!fn) return '';
  return fn(size);
}
window.icon = icon;
