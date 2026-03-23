const sessionListEl = document.getElementById("sessionList");
const messagesEl = document.getElementById("messages");
const sessionHeaderEl = document.getElementById("sessionHeader");
const resultCountEl = document.getElementById("resultCount");
const resultsLabelEl = document.getElementById("resultsLabel");
const sessionSortWrapEl = document.getElementById("sessionSortWrap");
const sessionSortEl = document.getElementById("sessionSort");
const systemTabsEl = document.getElementById("systemTabs");
const sourceTabsEl = document.getElementById("sourceTabs");
const listFooterEl = document.getElementById("listFooter");
const listLoadMoreBtn = document.getElementById("listLoadMore");
const searchForm = document.getElementById("searchForm");
const keywordInput = document.getElementById("q");
const startInput = document.getElementById("start");
const endInput = document.getElementById("end");
const sessionSearchInput = document.getElementById("sessionSearch");
const sessionSearchCount = document.getElementById("sessionSearchCount");
const prevMatchBtn = document.getElementById("prevMatch");
const nextMatchBtn = document.getElementById("nextMatch");
const clearSessionSearch = document.getElementById("clearSessionSearch");
const workdirValueEl = document.getElementById("workdirValue");
const resumeValueEl = document.getElementById("resumeValue");
const resumeCmdPsEl = document.getElementById("resumeCmdPs");
const resumeCmdWslEl = document.getElementById("resumeCmdWsl");
const copyWorkdirBtn = document.getElementById("copyWorkdir");
const copyResumeIdBtn = document.getElementById("copyResumeId");
const copyResumeCmdPsBtn = document.getElementById("copyResumeCmdPs");
const copyResumeCmdWslBtn = document.getElementById("copyResumeCmdWsl");
const resumeCmdPrimaryLabelEl = document.getElementById("resumeCmdPrimaryLabel");
const resumeCmdSecondaryLabelEl = document.getElementById("resumeCmdSecondaryLabel");
const sessionActionsEl = document.getElementById("sessionActions");
const pinSessionBtn = document.getElementById("pinSession");
const renameSessionBtn = document.getElementById("renameSession");
const archiveSessionBtn = document.getElementById("archiveSession");
const projectCrumbEl = document.getElementById("projectCrumb");
const backToProjectsBtn = document.getElementById("backToProjects");
const deleteProjectSessionsBtn = document.getElementById("deleteProjectSessions");
const cleanupWeakSessionsBtn = document.getElementById("cleanupWeakSessions");
const sidebarEl = document.getElementById("sidebar");
const sidebarTopEl = document.getElementById("sidebarTop");
const sidebarSessionsResizerEl = document.getElementById("sidebarSessionsResizer");
const sidebarResizerEl = document.getElementById("sidebarResizer");
const headerResizerEl = document.getElementById("headerResizer");
const mainEl = document.getElementById("main");
const codeThemeButtons = document.querySelectorAll("[data-code-theme]");

let currentSession = null;
let currentMessages = [];
let currentSystem = "windows";
let currentSource = "codex"; // "codex" | "claude" | "openclaw"
let browseMode = "sessions"; // "sessions" | "projects"
let currentProject = null; // string (cwd)
let currentMarks = [];
let activeMarkIndex = -1;
let lastSessionTerm = "";
let listReloadTimer = null;
let sessionSearchTimer = null;
let sessionsFetchSeq = 0;
let projectsFetchSeq = 0;
let sessionFetchSeq = 0;
let sessionSearchFetchSeq = 0;
let messageRenderSeq = 0;
let currentCodeTheme = "light";
let currentSessionSort = "start"; // "start" | "last"
let expandedMessageIndexes = new Set();
let currentSessionSearch = createEmptySessionSearchState();
let currentListItems = [];
let currentListHasMore = false;
let currentListNextOffset = 0;
let currentListLoadingMore = false;
let runtimeSystem = "windows";
let currentWslDistro = "Ubuntu-22.04";
let availableSystems = ["windows", "wsl", "linux"];
let availableSourcesBySystem = new Map([
  ["windows", ["codex", "claude", "openclaw"]],
  ["wsl", ["codex", "claude", "openclaw"]],
  ["linux", ["codex", "claude", "openclaw"]],
]);
const SYSTEM_ORDER = ["windows", "wsl", "linux"];
const SOURCE_ORDER = ["codex", "claude", "openclaw"];
const LIST_RELOAD_DEBOUNCE_MS = 200;
const SESSION_SEARCH_DEBOUNCE_MS = 220;
const MESSAGE_RENDER_BATCH_SIZE = 20;
const MESSAGE_COLLAPSE_THRESHOLD = 12_000;
const MESSAGE_PREVIEW_CHARS = 4_000;
const SESSION_LIST_PAGE_LIMIT = 50;
const PROJECT_LIST_PAGE_LIMIT = 40;
const MARKDOWN_CACHE_INDEX_KEY = "historyViewer.markdownCache.v1.index";
const MARKDOWN_CACHE_ENTRY_PREFIX = "historyViewer.markdownCache.v1.entry.";
const MARKDOWN_CACHE_MAX_ENTRIES = 80;
const MARKDOWN_CACHE_MAX_TOTAL_CHARS = 2_500_000;
const MARKDOWN_CACHE_MAX_ENTRY_CHARS = 160_000;
const messageRenderCache = new WeakMap();
let markdownCacheIndex = null;

function createEmptySessionSearchState(query = "") {
  return {
    query,
    matches: new Map(),
    matchCount: 0,
    messageMatchCount: 0,
    loading: false,
    error: "",
  };
}

const UI_STORAGE_KEYS = {
  roleFilters: "historyViewer.ui.roleFilters",
  codeTheme: "historyViewer.ui.codeTheme",
  sessionSort: "historyViewer.ui.sessionSort",
  system: "historyViewer.ui.system",
  source: "historyViewer.ui.source",
};

const LAYOUT_STORAGE_KEYS = {
  sidebarWidth: "historyViewer.layout.sidebarWidthPx",
  sidebarTopHeight: "historyViewer.layout.sidebarTopHeightPx",
  headerHeight: "historyViewer.layout.headerHeightPx",
};

const LAYOUT_LIMITS = {
  minSidebarWidthPx: 280,
  minMainWidthPx: 420,
  minSidebarTopHeightPx: 200,
  minSidebarResultsHeightPx: 180,
  minHeaderHeightPx: 140,
  minMessagesHeightPx: 220,
};

function apiBase() {
  return `/api/${currentSystem}/${currentSource}`;
}

function getSystemLabel(system = currentSystem) {
  if (system === "wsl") return "WSL";
  if (system === "linux") return "Linux";
  return "Windows";
}

function getAvailableSystems() {
  return Array.isArray(availableSystems) && availableSystems.length > 0
    ? availableSystems
    : [runtimeSystem || "windows"];
}

function getAvailableSources(system = currentSystem) {
  const items = availableSourcesBySystem.get(system);
  return Array.isArray(items) && items.length > 0 ? items : ["codex"];
}

function formatTime(ms) {
  if (!ms) return "";
  const date = new Date(ms);
  return date.toLocaleString();
}

function formatDate(ms) {
  if (!ms) return "";
  const date = new Date(ms);
  return date.toLocaleDateString();
}

function getRoleFilters() {
  const inputs = document.querySelectorAll(".roles input[type=checkbox]");
  const roles = {};
  inputs.forEach((input) => {
    roles[input.dataset.role] = input.checked;
  });
  return roles;
}

function roleToClass(role) {
  if (role === "user") return "user";
  if (role === "assistant") return "assistant";
  if (role === "system") return "system";
  if (role === "developer") return "developer";
  if (role === "tool") return "tool";
  return "other";
}

function kindLabel(kind) {
  if (kind === "agent_reasoning") return "assistant (thinking)";
  if (kind === "reasoning_summary") return "assistant (reasoning summary)";
  if (kind === "thinking") return "assistant (thinking)";
  if (kind === "tool_use") return "tool (use)";
  if (kind === "tool_result") return "tool (result)";
  return null;
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeDateInput(value) {
  const s = (value || "").trim();
  if (!s) return "";
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : "";
}

function isWindowsPath(value) {
  return /^[A-Za-z]:[\\/]/.test(value || "");
}

function quotePowerShell(value) {
  return `'${String(value || "").replaceAll("'", "''")}'`;
}

function quotePowerShellDouble(value) {
  return `"${String(value || "").replaceAll("`", "``").replaceAll('"', '`"')}"`;
}

function quoteShell(value) {
  return `'${String(value || "").replaceAll("'", `'\\''`)}'`;
}

function toWslPath(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^[A-Za-z]:[\\/]/.test(raw)) {
    const drive = raw[0].toLowerCase();
    const rest = raw.slice(2).replaceAll("\\", "/");
    return `/mnt/${drive}${rest}`;
  }
  return raw.replaceAll("\\", "/");
}

function getSourceLabel(source = currentSource) {
  if (source === "claude") return "Claude Code";
  if (source === "openclaw") return "OpenClaw";
  return "Codex";
}

function getResumeCommandLabels(system = currentSystem) {
  if (system === "linux") {
    return {
      primary: "Resume Shell",
      secondary: "Resume Plain",
    };
  }
  return {
    primary: "Resume PS",
    secondary: "Resume WSL",
  };
}

function renderSystemTabs() {
  if (!systemTabsEl) return;
  systemTabsEl.innerHTML = "";
  getAvailableSystems().forEach((system) => {
    const btn = document.createElement("button");
    const active = system === currentSystem;
    btn.type = "button";
    btn.className = `tab${active ? " active" : ""}`;
    btn.dataset.system = system;
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", active ? "true" : "false");
    btn.textContent = getSystemLabel(system);
    systemTabsEl.appendChild(btn);
  });
}

function renderSourceTabs() {
  if (!sourceTabsEl) return;
  sourceTabsEl.innerHTML = "";
  getAvailableSources().forEach((source) => {
    const btn = document.createElement("button");
    const active = source === currentSource;
    btn.type = "button";
    btn.className = `tab${active ? " active" : ""}`;
    btn.dataset.source = source;
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", active ? "true" : "false");
    btn.textContent = getSourceLabel(source);
    sourceTabsEl.appendChild(btn);
  });
}

function updateResumeCommandLabels() {
  const labels = getResumeCommandLabels(currentSystem);
  if (resumeCmdPrimaryLabelEl) resumeCmdPrimaryLabelEl.textContent = labels.primary;
  if (resumeCmdSecondaryLabelEl) resumeCmdSecondaryLabelEl.textContent = labels.secondary;
}

function normalizeSystem(system) {
  const allowed = new Set(getAvailableSystems());
  const fallback = allowed.has(runtimeSystem) ? runtimeSystem : (getAvailableSystems()[0] || "windows");
  return allowed.has(system) ? system : fallback;
}

function normalizeSource(source, system = currentSystem) {
  const allowed = getAvailableSources(system);
  return allowed.includes(source) ? source : (allowed[0] || "codex");
}

function buildResumeInvocation(system, source, sessionId) {
  if (!sessionId || sessionId === "-") return "";
  if (source === "codex") return `codex resume ${sessionId}`;
  if (source === "claude") return `claude -r ${sessionId}`;
  return "";
}

function buildResumeCommands(system, source, cwd, sessionId) {
  const command = buildResumeInvocation(system, source, sessionId);
  if (!command) {
    return { ps: "-", wsl: "-" };
  }

  if (system === "wsl") {
    const shellCommand = cwd
      ? `source ~/.bashrc >/dev/null 2>&1; cd ${quoteShell(cwd)} && ${command}`
      : `source ~/.bashrc >/dev/null 2>&1; ${command}`;
    return {
      ps: `wsl.exe -d ${currentWslDistro} -- bash -lc ${quotePowerShellDouble(shellCommand)}`,
      wsl: shellCommand,
    };
  }

  if (system === "linux") {
    const shell = cwd
      ? `cd ${quoteShell(cwd)} && ${command}`
      : command;
    return { ps: shell, wsl: command };
  }

  const ps = cwd && isWindowsPath(cwd)
    ? `Set-Location -LiteralPath ${quotePowerShell(cwd)}; ${command}`
    : command;
  const wsl = cwd
    ? `cd ${quoteShell(toWslPath(cwd))} && ${command}`
    : command;
  return { ps, wsl };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function readStoredInt(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const value = Number.parseInt(raw, 10);
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}

function writeStoredInt(key, value) {
  try {
    localStorage.setItem(key, String(Math.round(value)));
  } catch {
    // ignore
  }
}

function safeJsonParse(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function hashString(input) {
  const text = String(input || "");
  let hash = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function loadMarkdownCacheIndex() {
  if (markdownCacheIndex) return markdownCacheIndex;
  const fallback = { entries: [] };
  try {
    const parsed = safeJsonParse(localStorage.getItem(MARKDOWN_CACHE_INDEX_KEY));
    if (!parsed || !Array.isArray(parsed.entries)) {
      markdownCacheIndex = fallback;
      return markdownCacheIndex;
    }
    markdownCacheIndex = {
      entries: parsed.entries.filter((entry) =>
        entry
        && typeof entry.key === "string"
        && Number.isFinite(entry.size)
        && Number.isFinite(entry.at)
      ),
    };
    return markdownCacheIndex;
  } catch {
    markdownCacheIndex = fallback;
    return markdownCacheIndex;
  }
}

function persistMarkdownCacheIndex() {
  if (!markdownCacheIndex) return;
  try {
    localStorage.setItem(MARKDOWN_CACHE_INDEX_KEY, JSON.stringify(markdownCacheIndex));
  } catch {
    // ignore
  }
}

function touchMarkdownCacheEntry(cacheKey, size) {
  const index = loadMarkdownCacheIndex();
  const next = {
    key: cacheKey,
    size: Math.max(0, Number(size) || 0),
    at: Date.now(),
  };
  index.entries = index.entries.filter((entry) => entry.key !== cacheKey);
  index.entries.unshift(next);
}

function pruneMarkdownCacheIndex() {
  const index = loadMarkdownCacheIndex();
  let total = 0;
  const kept = [];
  index.entries.forEach((entry) => {
    if (!entry || typeof entry.key !== "string") return;
    if (kept.length >= MARKDOWN_CACHE_MAX_ENTRIES) {
      try {
        localStorage.removeItem(entry.key);
      } catch {
        // ignore
      }
      return;
    }
    if (total + entry.size > MARKDOWN_CACHE_MAX_TOTAL_CHARS) {
      try {
        localStorage.removeItem(entry.key);
      } catch {
        // ignore
      }
      return;
    }
    kept.push(entry);
    total += entry.size;
  });
  index.entries = kept;
  persistMarkdownCacheIndex();
}

function readPersistentMarkdownCache(cacheKey) {
  try {
    const value = localStorage.getItem(cacheKey);
    if (typeof value !== "string" || !value) return null;
    touchMarkdownCacheEntry(cacheKey, value.length);
    persistMarkdownCacheIndex();
    return value;
  } catch {
    return null;
  }
}

function writePersistentMarkdownCache(cacheKey, html) {
  const value = String(html || "");
  if (!value || value.length > MARKDOWN_CACHE_MAX_ENTRY_CHARS) return;
  try {
    localStorage.setItem(cacheKey, value);
    touchMarkdownCacheEntry(cacheKey, value.length);
    pruneMarkdownCacheIndex();
  } catch {
    const index = loadMarkdownCacheIndex();
    index.entries = index.entries.filter((entry) => entry.key !== cacheKey);
    pruneMarkdownCacheIndex();
    try {
      localStorage.setItem(cacheKey, value);
      touchMarkdownCacheEntry(cacheKey, value.length);
      pruneMarkdownCacheIndex();
    } catch {
      // ignore
    }
  }
}

function buildMessageMarkdownCacheKey(msg, mode, text) {
  const renderedText = String(text || "");
  const sessionId = currentSession?.id || "";
  const messageIndex = Number.isInteger(msg?.message_index) ? msg.message_index : -1;
  const scope = [
    currentSystem || "",
    currentSource || "",
    sessionId,
    msg?.role || "",
    msg?.kind || "",
    String(messageIndex),
    mode || "full",
    String(renderedText.length),
    hashString(renderedText),
  ].join("|");
  return `${MARKDOWN_CACHE_ENTRY_PREFIX}${hashString(scope)}.${renderedText.length}.${hashString(renderedText)}`;
}

function getOrRenderMarkdownHtml(cacheKey, text) {
  if (cacheKey) {
    const persisted = readPersistentMarkdownCache(cacheKey);
    if (typeof persisted === "string") return persisted;
  }
  const html = renderMarkdown(text);
  if (cacheKey) {
    writePersistentMarkdownCache(cacheKey, html);
  }
  return html;
}

function getSearchExcerptHtml(msg, searchMatch) {
  const excerptText = typeof searchMatch?.excerpt_text === "string" ? searchMatch.excerpt_text : "";
  if (!excerptText) return "";
  const excerptStart = Number.isFinite(searchMatch?.excerpt_start) ? searchMatch.excerpt_start : 0;
  const excerptEnd = Number.isFinite(searchMatch?.excerpt_end) ? searchMatch.excerpt_end : excerptText.length;
  const cacheMode = `search:${excerptStart}:${excerptEnd}`;
  const cacheKey = buildMessageMarkdownCacheKey(msg, cacheMode, excerptText);
  return getOrRenderMarkdownHtml(cacheKey, excerptText);
}

function setCodeTheme(theme, { persist } = { persist: false }) {
  const aliases = { dim: "warm" };
  const normalized = aliases[theme] || theme;
  const allowed = new Set(["light", "slate", "warm", "forest", "grape", "dark"]);
  const next = allowed.has(normalized) ? normalized : "light";
  currentCodeTheme = next;
  document.documentElement.dataset.codeTheme = next;

  codeThemeButtons.forEach((btn) => {
    const active = btn.dataset.codeTheme === next;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });

  if (persist) {
    try {
      localStorage.setItem(UI_STORAGE_KEYS.codeTheme, next);
    } catch {
      // ignore
    }
  }
}

function applyStoredCodeTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem(UI_STORAGE_KEYS.codeTheme);
  } catch {
    saved = null;
  }
  setCodeTheme(saved || "light", { persist: false });
}

function setSessionSort(sort, { persist } = { persist: false }) {
  const allowed = new Set(["start", "last"]);
  const next = allowed.has(sort) ? sort : "start";
  currentSessionSort = next;
  if (sessionSortEl) sessionSortEl.value = next;
  if (!persist) return;
  try {
    localStorage.setItem(UI_STORAGE_KEYS.sessionSort, next);
  } catch {
    // ignore
  }
}

function applyStoredSessionSort() {
  let saved = null;
  try {
    saved = localStorage.getItem(UI_STORAGE_KEYS.sessionSort);
  } catch {
    saved = null;
  }
  setSessionSort(saved || "start", { persist: false });
}

function setCurrentSystem(system, { persist } = { persist: false }) {
  const next = normalizeSystem(system);
  currentSystem = next;
  currentSource = normalizeSource(currentSource, currentSystem);
  renderSystemTabs();
  renderSourceTabs();
  updateResumeCommandLabels();
  if (persist) {
    try {
      localStorage.setItem(UI_STORAGE_KEYS.system, currentSystem);
      localStorage.setItem(UI_STORAGE_KEYS.source, currentSource);
    } catch {
      // ignore
    }
  }
}

function setCurrentSource(source, { persist } = { persist: false }) {
  const next = normalizeSource(source, currentSystem);
  currentSource = next;
  renderSourceTabs();
  if (persist) {
    try {
      localStorage.setItem(UI_STORAGE_KEYS.source, currentSource);
    } catch {
      // ignore
    }
  }
}

function applyStoredSourceContext() {
  let savedSystem = null;
  let savedSource = null;
  try {
    savedSystem = localStorage.getItem(UI_STORAGE_KEYS.system);
    savedSource = localStorage.getItem(UI_STORAGE_KEYS.source);
  } catch {
    savedSystem = null;
    savedSource = null;
  }
  setCurrentSystem(savedSystem || runtimeSystem, { persist: false });
  setCurrentSource(savedSource || currentSource, { persist: false });
}

function sortByKnownOrder(values, order) {
  const known = order.filter((item) => values.includes(item));
  const extra = values.filter((item) => !known.includes(item)).sort();
  return known.concat(extra);
}

async function loadSourceCatalog() {
  try {
    const res = await fetch("/api/sources");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const nextRuntimeSystem = typeof data.runtime_system === "string" ? data.runtime_system : runtimeSystem;
    const nextSystems = [];
    const nextSourcesBySystem = new Map();

    (data.sources || []).forEach((item) => {
      const system = String(item?.system || "").trim();
      const source = String(item?.source || "").trim();
      if (!system || !source) return;
      if (!nextSystems.includes(system)) nextSystems.push(system);
      const existing = nextSourcesBySystem.get(system) || [];
      if (!existing.includes(source)) {
        existing.push(source);
        nextSourcesBySystem.set(system, existing);
      }
    });

    runtimeSystem = nextRuntimeSystem;
    if (typeof data.wsl_distro === "string" && data.wsl_distro.trim()) {
      currentWslDistro = data.wsl_distro.trim();
    }
    availableSystems = sortByKnownOrder(nextSystems, SYSTEM_ORDER);
    if (availableSystems.length === 0) {
      availableSystems = [runtimeSystem];
    }
    availableSourcesBySystem = new Map();
    nextSourcesBySystem.forEach((sources, system) => {
      availableSourcesBySystem.set(system, sortByKnownOrder(sources, SOURCE_ORDER));
    });
  } catch {
    runtimeSystem = normalizeSystem(runtimeSystem);
  }

  renderSystemTabs();
  renderSourceTabs();
  updateResumeCommandLabels();
}

function applyRoleFiltersFromStorage(roleInputs) {
  let raw = null;
  try {
    raw = localStorage.getItem(UI_STORAGE_KEYS.roleFilters);
  } catch {
    raw = null;
  }
  const saved = safeJsonParse(raw);
  if (!saved || typeof saved !== "object") return;
  roleInputs.forEach((input) => {
    const key = input.dataset.role;
    if (!key) return;
    const value = saved[key];
    if (typeof value === "boolean") {
      input.checked = value;
    }
  });
}

function persistRoleFilters(roleInputs) {
  const roleMap = {};
  roleInputs.forEach((input) => {
    const key = input.dataset.role;
    if (!key) return;
    roleMap[key] = !!input.checked;
  });
  try {
    localStorage.setItem(UI_STORAGE_KEYS.roleFilters, JSON.stringify(roleMap));
  } catch {
    // ignore
  }
}

function clampSidebarWidthPx(valuePx) {
  const viewportWidth = document.documentElement.clientWidth || window.innerWidth || 0;
  const resizerWidth = sidebarResizerEl ? sidebarResizerEl.getBoundingClientRect().width : 0;
  const maxSidebarWidth = Math.max(
    LAYOUT_LIMITS.minSidebarWidthPx,
    viewportWidth - resizerWidth - LAYOUT_LIMITS.minMainWidthPx,
  );
  return clamp(valuePx, LAYOUT_LIMITS.minSidebarWidthPx, maxSidebarWidth);
}

function setSidebarWidthPx(valuePx, { persist } = { persist: false }) {
  const clamped = clampSidebarWidthPx(valuePx);
  document.documentElement.style.setProperty("--sidebar-width", `${clamped}px`);
  if (persist) writeStoredInt(LAYOUT_STORAGE_KEYS.sidebarWidth, clamped);
  return clamped;
}

function clampSidebarTopHeightPx(valuePx) {
  if (!sidebarEl || !sidebarSessionsResizerEl) return valuePx;
  const sidebarHeight = sidebarEl.getBoundingClientRect().height;
  const resizerHeight = sidebarSessionsResizerEl.getBoundingClientRect().height;
  const maxTopHeight = Math.max(
    LAYOUT_LIMITS.minSidebarTopHeightPx,
    sidebarHeight - resizerHeight - LAYOUT_LIMITS.minSidebarResultsHeightPx,
  );
  return clamp(valuePx, LAYOUT_LIMITS.minSidebarTopHeightPx, maxTopHeight);
}

function setSidebarTopHeightPx(valuePx, { persist } = { persist: false }) {
  if (!sidebarTopEl) return null;
  const clamped = clampSidebarTopHeightPx(valuePx);
  sidebarTopEl.style.height = `${clamped}px`;
  if (persist) writeStoredInt(LAYOUT_STORAGE_KEYS.sidebarTopHeight, clamped);
  return clamped;
}

function clampHeaderHeightPx(valuePx) {
  if (!mainEl || !headerResizerEl) return valuePx;
  const mainHeight = mainEl.getBoundingClientRect().height;
  const resizerHeight = headerResizerEl.getBoundingClientRect().height;
  const maxHeaderHeight = Math.max(
    LAYOUT_LIMITS.minHeaderHeightPx,
    mainHeight - resizerHeight - LAYOUT_LIMITS.minMessagesHeightPx,
  );
  return clamp(valuePx, LAYOUT_LIMITS.minHeaderHeightPx, maxHeaderHeight);
}

function setHeaderHeightPx(valuePx, { persist } = { persist: false }) {
  if (!sessionHeaderEl) return null;
  const clamped = clampHeaderHeightPx(valuePx);
  sessionHeaderEl.style.height = `${clamped}px`;
  if (persist) writeStoredInt(LAYOUT_STORAGE_KEYS.headerHeight, clamped);
  return clamped;
}

function applyStoredLayout() {
  const sidebarWidth = readStoredInt(LAYOUT_STORAGE_KEYS.sidebarWidth);
  if (typeof sidebarWidth === "number") {
    setSidebarWidthPx(sidebarWidth, { persist: false });
  }

  const sidebarTopHeight = readStoredInt(LAYOUT_STORAGE_KEYS.sidebarTopHeight);
  if (typeof sidebarTopHeight === "number") {
    setSidebarTopHeightPx(sidebarTopHeight, { persist: false });
  }

  const headerHeight = readStoredInt(LAYOUT_STORAGE_KEYS.headerHeight);
  if (typeof headerHeight === "number") {
    setHeaderHeightPx(headerHeight, { persist: false });
  }
}

function clampLayoutToViewport() {
  const sidebarWidth = readStoredInt(LAYOUT_STORAGE_KEYS.sidebarWidth);
  if (typeof sidebarWidth === "number") {
    setSidebarWidthPx(sidebarWidth, { persist: true });
  }

  const sidebarTopHeight = readStoredInt(LAYOUT_STORAGE_KEYS.sidebarTopHeight);
  if (typeof sidebarTopHeight === "number") {
    setSidebarTopHeightPx(sidebarTopHeight, { persist: true });
  }

  const headerHeight = readStoredInt(LAYOUT_STORAGE_KEYS.headerHeight);
  if (typeof headerHeight === "number") {
    setHeaderHeightPx(headerHeight, { persist: true });
  }
}

function applyInlineMarkdown(text) {
  let output = text;
  output = output.replace(/`([^`]+)`/g, "<code>$1</code>");
  output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  output = output.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, "$1<em>$2</em>");
  output = output.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  output = output.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, url) => {
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      return match;
    }
    return `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`;
  });
  return output;
}

function renderInlineMarkdown(text) {
  const lines = text.split("\n");
  let html = "";
  let listType = null;
  let inBlockquote = false;
  let paragraph = [];

  function isHorizontalRule(line) {
    return /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line.trim());
  }

  function splitTableRow(line) {
    let s = line.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split("|").map((cell) => cell.trim());
  }

  function parseTableAlign(separatorLine) {
    const raw = splitTableRow(separatorLine);
    return raw.map((cell) => {
      const c = cell.replace(/\s+/g, "");
      const left = c.startsWith(":");
      const right = c.endsWith(":");
      if (left && right) return "center";
      if (right) return "right";
      if (left) return "left";
      return "";
    });
  }

  function isTableSeparator(line) {
    if (!line.includes("|")) return false;
    const cells = splitTableRow(line);
    if (!cells.length) return false;
    return cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
  }

  function flushParagraph() {
    if (!paragraph.length) return;
    const body = paragraph.join("<br>");
    html += `<p>${applyInlineMarkdown(body)}</p>`;
    paragraph = [];
  }

  function closeList() {
    if (!listType) return;
    html += `</${listType}>`;
    listType = null;
  }

  function closeBlockquote() {
    if (!inBlockquote) return;
    html += "</blockquote>";
    inBlockquote = false;
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.trim()) {
      flushParagraph();
      closeList();
      closeBlockquote();
      continue;
    }

    if (isHorizontalRule(line)) {
      flushParagraph();
      closeList();
      closeBlockquote();
      html += "<hr>";
      continue;
    }

    // GFM-style table: header row + separator row, then optional body rows.
    if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const headerCells = splitTableRow(line);
      const align = parseTableAlign(lines[i + 1]);

      const rows = [];
      i += 2;
      while (i < lines.length) {
        const rowLine = lines[i];
        if (!rowLine.trim()) break;
        if (!rowLine.includes("|")) break;
        if (isHorizontalRule(rowLine)) break;
        rows.push(splitTableRow(rowLine));
        i += 1;
      }
      i -= 1; // compensate for loop increment

      flushParagraph();
      closeList();
      closeBlockquote();

      let tableHtml = "<div class=\"table-wrap\"><table><thead><tr>";
      headerCells.forEach((cell, idx) => {
        const a = align[idx] ? ` style=\"text-align:${align[idx]}\"` : "";
        tableHtml += `<th${a}>${applyInlineMarkdown(cell)}</th>`;
      });
      tableHtml += "</tr></thead><tbody>";
      rows.forEach((row) => {
        tableHtml += "<tr>";
        headerCells.forEach((_, idx) => {
          const a = align[idx] ? ` style=\"text-align:${align[idx]}\"` : "";
          const value = row[idx] || "";
          tableHtml += `<td${a}>${applyInlineMarkdown(value)}</td>`;
        });
        tableHtml += "</tr>";
      });
      tableHtml += "</tbody></table></div>";
      html += tableHtml;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      closeList();
      closeBlockquote();
      const level = heading[1].length;
      html += `<h${level}>${applyInlineMarkdown(heading[2])}</h${level}>`;
      continue;
    }

    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeList();
      if (!inBlockquote) {
        html += "<blockquote>";
        inBlockquote = true;
      }
      html += `<p>${applyInlineMarkdown(quote[1])}</p>`;
      continue;
    }

    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ol) {
      flushParagraph();
      closeBlockquote();
      if (listType !== "ol") {
        closeList();
        listType = "ol";
        html += "<ol>";
      }
      html += `<li>${applyInlineMarkdown(ol[1])}</li>`;
      continue;
    }
    if (ul) {
      flushParagraph();
      closeBlockquote();
      if (listType !== "ul") {
        closeList();
        listType = "ul";
        html += "<ul>";
      }
      html += `<li>${applyInlineMarkdown(ul[1])}</li>`;
      continue;
    }

    if (listType) {
      closeList();
    }
    if (inBlockquote) {
      closeBlockquote();
    }

    paragraph.push(line);
  }

  flushParagraph();
  closeList();
  closeBlockquote();
  return html;
}

function splitFencedCodeBlocks(text) {
  const segments = [];
  const normalized = (text || "").replaceAll("\r\n", "\n");
  const lines = normalized.split("\n");

  let markdownLines = [];
  let codeLines = [];
  let inCode = false;
  let fence = null;
  let fenceLang = "";

  function flushMarkdown() {
    if (!markdownLines.length) return;
    segments.push({ type: "markdown", text: markdownLines.join("\n") });
    markdownLines = [];
  }

  function flushCode() {
    segments.push({ type: "code", lang: fenceLang, text: codeLines.join("\n") });
    codeLines = [];
  }

  const openRe = /^\s*(```+)\s*([a-zA-Z0-9_+#-]+)?\s*$/;
  const closeRe = /^\s*(```+)\s*$/;

  for (const rawLine of lines) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (!inCode) {
      const m = line.match(openRe);
      if (m) {
        flushMarkdown();
        inCode = true;
        fence = m[1];
        fenceLang = (m[2] || "").trim();
        continue;
      }
      markdownLines.push(line);
      continue;
    }

    const m = line.match(closeRe);
    if (m && fence && m[1].length >= fence.length) {
      flushCode();
      inCode = false;
      fence = null;
      fenceLang = "";
      continue;
    }
    codeLines.push(line);
  }

  if (inCode) {
    flushCode();
  } else {
    flushMarkdown();
  }

  return segments;
}

function renderMarkdown(text) {
  const segments = splitFencedCodeBlocks(text || "");
  let html = "";

  segments.forEach((segment) => {
    if (segment.type === "code") {
      const rawCode = segment.text || "";
      const normalizedLang = (segment.lang || "").toLowerCase();
      const isLikelyDiff =
        !normalizedLang &&
        (/^diff --git /m.test(rawCode) || /^@@ /m.test(rawCode) || /^(---|\\+\\+\\+)\\s/m.test(rawCode));

      if (normalizedLang === "diff" || normalizedLang === "patch" || isLikelyDiff) {
        const diffLines = rawCode.split("\n").map((rawLine) => {
          let cls = "";
          if (rawLine.startsWith("+") && !rawLine.startsWith("+++")) cls = "add";
          else if (rawLine.startsWith("-") && !rawLine.startsWith("---")) cls = "del";
          else if (rawLine.startsWith("@@")) cls = "hunk";
          else if (
            rawLine.startsWith("diff ") ||
            rawLine.startsWith("index ") ||
            rawLine.startsWith("---") ||
            rawLine.startsWith("+++")
          ) {
            cls = "meta";
          }
          const classAttr = cls ? ` diff-${cls}` : "";
          return `<span class="diff-line${classAttr}">${escapeHtml(rawLine)}</span>`;
        }).join("");
        const langClass = normalizedLang || "diff";
        html += `<pre class="diff"><code class="lang-${langClass}">${diffLines}</code></pre>`;
      } else {
        const classAttr = normalizedLang ? ` class="lang-${normalizedLang}"` : "";
        html += `<pre><code${classAttr}>${escapeHtml(rawCode)}</code></pre>`;
      }
      return;
    }

    html += renderInlineMarkdown(escapeHtml(segment.text || ""));
  });

  return html;
}

function highlightElement(element, term) {
  if (!term) return 0;
  const regex = new RegExp(escapeRegExp(term), "gi");
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let node;
  while ((node = walker.nextNode())) {
    nodes.push(node);
  }
  let matches = 0;
  nodes.forEach((textNode) => {
    const text = textNode.nodeValue;
    if (!text) return;
    regex.lastIndex = 0;
    if (!regex.test(text)) return;

    const fragment = document.createDocumentFragment();
    let lastIndex = 0;
    regex.lastIndex = 0;
    let match;
    while ((match = regex.exec(text)) !== null) {
      const before = text.slice(lastIndex, match.index);
      if (before) fragment.appendChild(document.createTextNode(before));
      const mark = document.createElement("mark");
      mark.textContent = match[0];
      fragment.appendChild(mark);
      matches += 1;
      lastIndex = match.index + match[0].length;
    }
    const after = text.slice(lastIndex);
    if (after) fragment.appendChild(document.createTextNode(after));
    textNode.parentNode.replaceChild(fragment, textNode);
  });
  return matches;
}

function humanizeToolUseMessage(msg) {
  if (!msg || msg.kind !== "tool_use") return msg?.text || "";
  const text = msg.text || "";
  if (!text.startsWith("Tool use:")) return text;

  const toolNameMatch = text.match(/^Tool use:\\s*([^\\n]+)\\s*$/m);
  const toolName = toolNameMatch ? toolNameMatch[1].trim() : "";
  const toolKey = toolName.toLowerCase();

  const toolIdMatch = text.match(/^Tool ID:\\s*(.+)\\s*$/m);
  const toolIdLine = toolIdMatch ? `Tool ID: ${toolIdMatch[1].trim()}` : null;
  const descMatch = text.match(/^Description:\\s*(.+)\\s*$/m);
  const descLine = descMatch ? `Description: ${descMatch[1].trim()}` : null;

  const inputFenced = text.match(/Input:\\s*\\n```json\\n([\\s\\S]*?)\\n```/m);
  let inputJson = null;
  if (inputFenced) {
    try {
      inputJson = JSON.parse(inputFenced[1]);
    } catch {
      inputJson = null;
    }
  } else {
    const inputRaw = text.match(/Input:\\s*\\n([\\s\\S]*)$/m);
    if (inputRaw) {
      const candidate = (inputRaw[1] || "").trim();
      if (candidate.startsWith("{") || candidate.startsWith("[")) {
        try {
          inputJson = JSON.parse(candidate);
        } catch {
          inputJson = null;
        }
      }
    }
  }

  if (!inputJson || typeof inputJson !== "object") return text;

  const lines = [`Tool use: ${toolName}`];
  if (toolIdLine) lines.push(toolIdLine);
  if (descLine) lines.push(descLine);

  if (toolKey === "grep") {
    if (typeof inputJson.pattern === "string") lines.push("Pattern: `" + inputJson.pattern + "`");
    if (typeof inputJson.path === "string") lines.push("Path: `" + inputJson.path + "`");
    if (typeof inputJson.output_mode === "string") lines.push("Mode: `" + inputJson.output_mode + "`");
    if (typeof inputJson.head_limit === "number") lines.push("Limit: `" + inputJson.head_limit + "`");
    return lines.join("\\n");
  }

  if (toolKey === "glob") {
    if (typeof inputJson.pattern === "string") lines.push("Pattern: `" + inputJson.pattern + "`");
    if (typeof inputJson.path === "string") lines.push("Path: `" + inputJson.path + "`");
    return lines.join("\\n");
  }

  if (toolKey === "askuserquestion") {
    const questions = Array.isArray(inputJson.questions) ? inputJson.questions : [];
    questions.forEach((q) => {
      if (!q || typeof q !== "object") return;
      const header = typeof q.header === "string" ? q.header.trim() : "";
      const question = typeof q.question === "string" ? q.question.trim() : "";
      lines.push(header ? `Question (${header}):` : "Question:");
      if (question) lines.push(question);
      const options = Array.isArray(q.options) ? q.options : [];
      if (options.length) lines.push("Options:");
      options.forEach((opt) => {
        if (!opt || typeof opt !== "object") return;
        const label = typeof opt.label === "string" ? opt.label.trim() : "";
        const description = typeof opt.description === "string" ? opt.description.trim() : "";
        if (!label) return;
        lines.push(description ? `- ${label} — ${description}` : `- ${label}`);
      });
      if (typeof q.multiSelect === "boolean") lines.push("Multi-select: `" + q.multiSelect + "`");
    });
    return lines.join("\\n");
  }

  return text;
}

function sessionSortKeyMs(session) {
  const start = typeof session?.start_ts_ms === "number" ? session.start_ts_ms : 0;
  const end = typeof session?.end_ts_ms === "number" ? session.end_ts_ms : 0;
  if (currentSessionSort === "last") return end || start || 0;
  return start || end || 0;
}

function sortSessionsForSidebar(sessions) {
  const list = Array.isArray(sessions) ? [...sessions] : [];
  list.sort((a, b) => {
    const pinA = a?.pinned ? 1 : 0;
    const pinB = b?.pinned ? 1 : 0;
    if (pinB !== pinA) return pinB - pinA;
    const keyDiff = sessionSortKeyMs(b) - sessionSortKeyMs(a);
    if (keyDiff) return keyDiff;
    const startDiff = (b?.start_ts_ms || 0) - (a?.start_ts_ms || 0);
    if (startDiff) return startDiff;
    const endDiff = (b?.end_ts_ms || 0) - (a?.end_ts_ms || 0);
    if (endDiff) return endDiff;
    return String(a?.id || "").localeCompare(String(b?.id || ""));
  });
  return list;
}

function formatSessionMeta(session) {
  const start = formatTime(session?.start_ts_ms);
  const end = formatTime(session?.end_ts_ms);
  const msgCount = session?.message_count || 0;
  const timeRange = start && end && end !== start ? `${start} → ${end}` : start || end || "";
  return timeRange ? `${timeRange} • ${msgCount} msgs` : `${msgCount} msgs`;
}

function updateListFooter() {
  if (!listFooterEl || !listLoadMoreBtn) return;
  const count = currentListItems.length;
  resultCountEl.textContent = currentListHasMore ? `${count}+` : `${count}`;
  listFooterEl.style.display = currentListHasMore || currentListLoadingMore ? "flex" : "none";
  listLoadMoreBtn.style.display = currentListHasMore || currentListLoadingMore ? "inline-flex" : "none";
  listLoadMoreBtn.disabled = currentListLoadingMore;
  listLoadMoreBtn.textContent = currentListLoadingMore ? "Loading..." : "Load more";
}

function renderSessions(sessions) {
  const sorted = sortSessionsForSidebar(sessions);
  sessionListEl.innerHTML = "";
  let lastDate = "";
  sorted.forEach((session) => {
    const date = formatDate(sessionSortKeyMs(session));
    if (date && date !== lastDate) {
      const divider = document.createElement("div");
      divider.className = "date-divider";
      divider.textContent = date;
      sessionListEl.appendChild(divider);
      lastDate = date;
    }

    const item = document.createElement("div");
    item.className = "session-item";
    if (session.pinned) item.classList.add("pinned");
    if (currentSession?.id && currentSession.id === session.id) item.classList.add("active");
    item.dataset.sessionId = session.id;
    const pinIcon = session.pinned ? '<span class="pin-icon">📌</span>' : '';
    item.innerHTML = `
      <div class="session-title">${pinIcon}${escapeHtml(session.title || "Session")}</div>
      <div class="session-meta">${escapeHtml(formatSessionMeta(session))}</div>
    `;
    sessionListEl.appendChild(item);
  });
}

function renderProjects(projects) {
  sessionListEl.innerHTML = "";
  projects.forEach((project) => {
    const item = document.createElement("div");
    item.className = "session-item";
    item.dataset.project = project.project;
    item.innerHTML = `
      <div class="session-title">${escapeHtml(project.project || "Project")}</div>
      <div class="session-meta">${formatTime(project.last_ts_ms)} • ${project.session_count || 0} sessions</div>
    `;
    sessionListEl.appendChild(item);
  });
}

function cancelPendingMessageRender() {
  if (sessionSearchTimer) {
    clearTimeout(sessionSearchTimer);
    sessionSearchTimer = null;
  }
  messageRenderSeq += 1;
}

function buildCollapsedPreviewText(text) {
  const value = String(text || "");
  if (value.length <= MESSAGE_COLLAPSE_THRESHOLD) return value;

  let preview = value.slice(0, MESSAGE_PREVIEW_CHARS);
  const lastNewline = preview.lastIndexOf("\n");
  if (lastNewline >= Math.floor(MESSAGE_PREVIEW_CHARS * 0.6)) {
    preview = preview.slice(0, lastNewline);
  }

  const fenceCount = (preview.match(/```/g) || []).length;
  if (fenceCount % 2 === 1) {
    preview += "\n```";
  }

  return `${preview}\n\n---\nPreview truncated for performance. Expand to render the full message.`;
}

function getMessageRenderData(msg) {
  let cached = messageRenderCache.get(msg);
  if (cached) return cached;

  const renderedText = humanizeToolUseMessage(msg) || "";
  const serverPreviewPending = !!msg?.is_truncated && !msg?.full_text_loaded;
  const charCount = Number.isFinite(msg?.char_count) ? msg.char_count : renderedText.length;
  const collapsible = serverPreviewPending || renderedText.length > MESSAGE_COLLAPSE_THRESHOLD;
  cached = {
    charCount,
    collapsible,
    serverPreviewPending,
    fullText: renderedText,
    previewText: serverPreviewPending
      ? renderedText
      : (collapsible ? buildCollapsedPreviewText(renderedText) : renderedText),
    fullCacheKey: buildMessageMarkdownCacheKey(msg, "full", renderedText),
    previewCacheKey: null,
    fullHtml: null,
    previewHtml: null,
  };
  cached.previewCacheKey = buildMessageMarkdownCacheKey(msg, "preview", cached.previewText);
  messageRenderCache.set(msg, cached);
  return cached;
}

function getMessageHtml(msg, expanded) {
  const cached = getMessageRenderData(msg);
  if (!cached.collapsible || expanded) {
    if (cached.fullHtml === null) {
      cached.fullHtml = getOrRenderMarkdownHtml(cached.fullCacheKey, cached.fullText);
    }
    return cached.fullHtml;
  }
  if (cached.previewHtml === null) {
    cached.previewHtml = getOrRenderMarkdownHtml(cached.previewCacheKey, cached.previewText);
  }
  return cached.previewHtml;
}

function getMessageBodyHtml(msg, { expanded = false, searchMatch = null } = {}) {
  const cached = getMessageRenderData(msg);
  const hasSearchExcerpt = !!(
    !expanded
    && cached.collapsible
    && typeof searchMatch?.excerpt_text === "string"
    && searchMatch.excerpt_text
  );
  if (hasSearchExcerpt) {
    return {
      html: getSearchExcerptHtml(msg, searchMatch),
      mode: "search-excerpt",
    };
  }
  return {
    html: getMessageHtml(msg, expanded),
    mode: !cached.collapsible || expanded ? "full" : "preview",
  };
}

function getSessionSearchMatch(index, term) {
  if (!term) return null;
  if (currentSessionSearch.query !== term) return null;
  return currentSessionSearch.matches.get(index) || null;
}

function buildMessageElement(msg, index, term) {
  const roleClass = roleToClass(msg.role);
  const cached = getMessageRenderData(msg);
  const expandedByUser = expandedMessageIndexes.has(index);
  const searchMatch = getSessionSearchMatch(index, term);
  const expanded = !cached.collapsible || expandedByUser;

  const wrapper = document.createElement("div");
  wrapper.className = `msg ${roleClass}`;
  if (msg.kind === "agent_reasoning" || msg.kind === "reasoning_summary") {
    wrapper.classList.add("thinking");
  }
  const trimmedText = (msg.text || "").trim();
  if (trimmedText === "[Request interrupted by user]") {
    wrapper.classList.add("interrupted");
  }
  const turnTagMatch = trimmedText.match(/^<turn_([a-zA-Z0-9_-]+)>/i);
  if (turnTagMatch) {
    const turnKind = turnTagMatch[1].toLowerCase();
    if (turnKind === "aborted" || turnKind === "interrupted" || turnKind === "canceled" || turnKind === "cancelled") {
      wrapper.classList.add("interrupted");
    } else {
      wrapper.classList.add("error");
    }
  }
  if (msg.kind === "tool_result") {
    const isToolError = trimmedText.includes("Status: error")
      || /\bHTTP\s+(4\d\d|5\d\d)\b/.test(trimmedText)
      || /\bTraceback\b/.test(trimmedText)
      || /\bException\b/.test(trimmedText)
      || /\bECONN\w*\b/i.test(trimmedText)
      || /\bEPIPE\b/i.test(trimmedText);
    if (isToolError) wrapper.classList.add("error");
  }

  const label = kindLabel(msg.kind) || msg.role;
  const header = document.createElement("div");
  header.className = "msg-header";
  header.textContent = `${label} ? ${formatTime(msg.ts_ms)}`;

  const body = document.createElement("div");
  body.className = "msg-body";
  const bodyRender = getMessageBodyHtml(msg, { expanded, searchMatch });
  const showingSearchExcerpt = bodyRender.mode === "search-excerpt";
  body.innerHTML = bodyRender.html;

  wrapper.appendChild(header);
  wrapper.appendChild(body);

  let hits = 0;
  if (term && searchMatch) {
    hits = highlightElement(body, term);
  }

  if (cached.collapsible) {
    const controls = document.createElement("div");
    controls.className = "msg-controls";

    const note = document.createElement("div");
    note.className = "msg-note muted";
    if (showingSearchExcerpt) {
      const excerptStart = Number.isFinite(searchMatch?.excerpt_start) ? searchMatch.excerpt_start : 0;
      const excerptEnd = Number.isFinite(searchMatch?.excerpt_end) ? searchMatch.excerpt_end : excerptStart;
      const shownChars = Math.max(0, excerptEnd - excerptStart);
      note.textContent = `Search hit excerpt. Showing ${shownChars.toLocaleString()} of ${cached.charCount.toLocaleString()} chars near the match.`;
    } else if (cached.serverPreviewPending) {
      note.textContent = `Previewing ${Math.min((msg.text || "").length, cached.charCount).toLocaleString()} of ${cached.charCount.toLocaleString()} chars. Expand to fetch the full message.`;
    } else if (expanded) {
      note.textContent = `Long message. ${cached.charCount.toLocaleString()} chars rendered.`;
    } else {
      note.textContent = `Previewing ${Math.min(MESSAGE_PREVIEW_CHARS, cached.charCount).toLocaleString()} of ${cached.charCount.toLocaleString()} chars.`;
    }
    controls.appendChild(note);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "btn small msg-toggle";
    toggle.dataset.messageToggle = String(index);
    if (cached.serverPreviewPending && !expanded) {
      toggle.textContent = "Load full message";
    } else {
      toggle.textContent = expanded ? "Collapse long message" : "Expand full message";
    }
    controls.appendChild(toggle);

    wrapper.appendChild(controls);
  }

  return { wrapper, hits };
}

function renderMessages(messages) {
  cancelPendingMessageRender();
  const renderSeq = messageRenderSeq;
  messagesEl.innerHTML = "";
  const roleFilters = getRoleFilters();
  const term = sessionSearchInput.value.trim();
  currentMarks = [];
  activeMarkIndex = -1;
  prevMatchBtn.disabled = true;
  nextMatchBtn.disabled = true;

  const visibleMessages = [];
  messages.forEach((msg, index) => {
    const roleClass = roleToClass(msg.role);
    if (!roleFilters[roleClass]) return;
    visibleMessages.push({ msg, index });
  });
  const renderedCount = visibleMessages.length;

  if (renderedCount === 0) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = messages.length
      ? "No messages match the current role filters."
      : "No messages in this session.";
    messagesEl.appendChild(empty);
    if (term) {
      if (currentSessionSearch.query === term) {
        if (currentSessionSearch.loading) {
          sessionSearchCount.textContent = "Searching...";
        } else if (currentSessionSearch.error) {
          sessionSearchCount.textContent = currentSessionSearch.error;
        } else {
          sessionSearchCount.textContent = `${currentSessionSearch.matchCount} matches in ${currentSessionSearch.messageMatchCount} messages`;
        }
      } else {
        sessionSearchCount.textContent = "Searching...";
      }
    } else {
      sessionSearchCount.textContent = "";
    }
    updateMatchNavState(term);
    return;
  }

  if (term) {
    sessionSearchCount.textContent = currentSessionSearch.loading ? "Searching..." : "Rendering...";
  } else {
    sessionSearchCount.textContent = "";
  }

  let offset = 0;
  const renderBatch = () => {
    if (renderSeq !== messageRenderSeq) return;

    const fragment = document.createDocumentFragment();
    const batchEnd = Math.min(offset + MESSAGE_RENDER_BATCH_SIZE, renderedCount);
    for (; offset < batchEnd; offset += 1) {
      const { msg, index } = visibleMessages[offset];
      const rendered = buildMessageElement(msg, index, term);
      fragment.appendChild(rendered.wrapper);
    }
    messagesEl.appendChild(fragment);

    if (offset < renderedCount) {
      requestAnimationFrame(renderBatch);
      return;
    }

    if (term) {
      currentMarks = Array.from(messagesEl.querySelectorAll("mark"));
      if (currentSessionSearch.query === term) {
        if (currentSessionSearch.loading) {
          sessionSearchCount.textContent = "Searching...";
        } else if (currentSessionSearch.error) {
          sessionSearchCount.textContent = currentSessionSearch.error;
        } else {
          sessionSearchCount.textContent = `${currentSessionSearch.matchCount} matches in ${currentSessionSearch.messageMatchCount} messages`;
        }
      } else {
        sessionSearchCount.textContent = "Searching...";
      }
    } else {
      sessionSearchCount.textContent = "";
    }

    updateMatchNavState(term);
  };

  renderBatch();
}

function updateMatchNavState(term) {
  const hasMarks = !!(term && currentMarks.length);
  prevMatchBtn.disabled = !hasMarks;
  nextMatchBtn.disabled = !hasMarks;

  if (!hasMarks) {
    lastSessionTerm = term || "";
    return;
  }

  // Reset active index when term changes.
  if (term !== lastSessionTerm) {
    setActiveMarkIndex(0, { scroll: false });
    lastSessionTerm = term;
    return;
  }

  // Ensure an active mark exists after re-render.
  if (activeMarkIndex === -1) {
    setActiveMarkIndex(0, { scroll: false });
  }
}

function setActiveMarkIndex(index, { scroll }) {
  if (!currentMarks.length) return;
  if (activeMarkIndex >= 0 && activeMarkIndex < currentMarks.length) {
    currentMarks[activeMarkIndex].classList.remove("active");
  }
  const wrapped = ((index % currentMarks.length) + currentMarks.length) % currentMarks.length;
  activeMarkIndex = wrapped;
  const el = currentMarks[activeMarkIndex];
  el.classList.add("active");
  if (scroll) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function resetSessionPane() {
  cancelPendingMessageRender();
  sessionSearchFetchSeq += 1;
  currentSessionSearch = createEmptySessionSearchState();
  currentSession = null;
  currentMessages = [];
  expandedMessageIndexes = new Set();
  sessionSearchInput.value = "";
  sessionSearchCount.textContent = "";
  currentMarks = [];
  activeMarkIndex = -1;
  lastSessionTerm = "";
  sessionHeaderEl.querySelector(".session-title").textContent = "Select a session";
  sessionHeaderEl.querySelector(".session-meta").textContent = "";
  workdirValueEl.textContent = "-";
  resumeValueEl.textContent = "-";
  resumeCmdPsEl.textContent = "-";
  resumeCmdWslEl.textContent = "-";
  messagesEl.innerHTML = "";
  if (sessionActionsEl) sessionActionsEl.style.display = "none";
  updateMatchNavState("");
}

function gotoNextMatch(delta) {
  const term = sessionSearchInput.value.trim();
  if (!term || !currentMarks.length) return;
  if (activeMarkIndex === -1) {
    setActiveMarkIndex(delta > 0 ? 0 : currentMarks.length - 1, { scroll: true });
    return;
  }
  setActiveMarkIndex(activeMarkIndex + delta, { scroll: true });
}

function renderSessionHeader(session) {
  if (!session) return;
  const titleEl = sessionHeaderEl.querySelector(".session-title");
  const metaEl = sessionHeaderEl.querySelector(".session-meta");
  titleEl.textContent = session.title || "Session";
  const parts = [formatTime(session.start_ts_ms)];
  if (session.cwd) {
    parts.push(session.cwd);
  }
  metaEl.textContent = parts.filter(Boolean).join(" • ");

  const cwd = session.cwd || "-";
  workdirValueEl.textContent = cwd;
  const resumeId = session.id || "-";
  resumeValueEl.textContent = resumeId;
  const resumeCommands = buildResumeCommands(currentSystem, currentSource, session.cwd, resumeId);
  updateResumeCommandLabels();
  resumeCmdPsEl.textContent = resumeCommands.ps;
  resumeCmdWslEl.textContent = resumeCommands.wsl;

  if (sessionActionsEl) sessionActionsEl.style.display = "flex";
  if (pinSessionBtn) {
    pinSessionBtn.textContent = session.pinned ? "📌 Unpin" : "📌 Pin";
  }
}

function setResultsHeader() {
  const showingSessions = !(browseMode === "projects" && !currentProject);
  const showingProjectActions = browseMode === "projects" && !!currentProject;
  if (sessionSortWrapEl) {
    sessionSortWrapEl.style.display = showingSessions ? "flex" : "none";
  }
  backToProjectsBtn.style.display = showingProjectActions ? "inline-block" : "none";
  if (deleteProjectSessionsBtn) {
    deleteProjectSessionsBtn.style.display = showingProjectActions ? "inline-block" : "none";
  }

  if (browseMode === "projects" && !currentProject) {
    resultsLabelEl.textContent = "Projects";
    projectCrumbEl.textContent = "";
    return;
  }
  resultsLabelEl.textContent = "Sessions";
  if (browseMode === "projects" && currentProject) {
    projectCrumbEl.textContent = currentProject;
  } else {
    projectCrumbEl.textContent = "";
  }
}

function renderStatusMessage(text, { kind } = { kind: "muted" }) {
  cancelPendingMessageRender();
  messagesEl.innerHTML = "";
  sessionSearchCount.textContent = "";
  const div = document.createElement("div");
  div.className = kind === "error" ? "msg other error" : "muted";
  div.textContent = text;
  if (kind === "error") {
    div.className = "msg other error";
    div.innerHTML = `<div class="msg-header">error</div><div class="msg-body">${escapeHtml(text)}</div>`;
  }
  messagesEl.appendChild(div);
}

function scheduleReloadList() {
  if (listReloadTimer) {
    clearTimeout(listReloadTimer);
  }
  listReloadTimer = setTimeout(() => {
    listReloadTimer = null;
    reloadList();
  }, LIST_RELOAD_DEBOUNCE_MS);
}

function scheduleSessionSearchRender() {
  if (sessionSearchTimer) {
    clearTimeout(sessionSearchTimer);
  }
  sessionSearchTimer = setTimeout(() => {
    sessionSearchTimer = null;
    refreshSessionSearch();
  }, SESSION_SEARCH_DEBOUNCE_MS);
}

async function refreshSessionSearch() {
  const term = sessionSearchInput.value.trim();
  const fetchSeq = (sessionSearchFetchSeq += 1);

  if (!term || !currentSession) {
    currentSessionSearch = createEmptySessionSearchState();
    renderMessages(currentMessages);
    return;
  }

  currentSessionSearch = {
    query: term,
    matches: new Map(),
    matchCount: 0,
    messageMatchCount: 0,
    loading: true,
    error: "",
  };
  renderMessages(currentMessages);

  try {
    const res = await fetch(`${apiBase()}/session/${encodeURIComponent(currentSession.id)}/search?q=${encodeURIComponent(term)}`);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    if (fetchSeq !== sessionSearchFetchSeq) return;

    const matches = new Map();
    for (const match of data.matches || []) {
      matches.set(match.message_index, match);
    }

    currentSessionSearch = {
      query: term,
      matches,
      matchCount: Number.isFinite(data.match_count) ? data.match_count : 0,
      messageMatchCount: Number.isFinite(data.message_match_count) ? data.message_match_count : matches.size,
      loading: false,
      error: "",
    };
    renderMessages(currentMessages);
  } catch (err) {
    if (fetchSeq !== sessionSearchFetchSeq) return;
    currentSessionSearch = {
      query: term,
      matches: new Map(),
      matchCount: 0,
      messageMatchCount: 0,
      loading: false,
      error: `Search failed (${err?.message || err})`,
    };
    renderMessages(currentMessages);
  }
}

async function fetchFullMessage(index) {
  if (!currentSession || !Number.isInteger(index) || index < 0) {
    throw new Error("Invalid message index");
  }
  const msg = currentMessages[index];
  if (!msg) {
    throw new Error("Message not found");
  }
  if (!msg.is_truncated || msg.full_text_loaded) {
    return msg;
  }

  const res = await fetch(`${apiBase()}/session/${encodeURIComponent(currentSession.id)}/message/${index}`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  const data = await res.json();
  const fullMessage = data.message;
  if (!fullMessage || typeof fullMessage.text !== "string") {
    throw new Error("Malformed response");
  }

  msg.preview_text = msg.preview_text || msg.text || "";
  msg.text = fullMessage.text;
  msg.char_count = Number.isFinite(fullMessage.char_count) ? fullMessage.char_count : fullMessage.text.length;
  msg.is_truncated = false;
  msg.full_text_loaded = true;
  messageRenderCache.delete(msg);
  return msg;
}

function buildListParams(limit, offset) {
  const q = (keywordInput.value || "").trim();
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (browseMode === "projects" && !currentProject) {
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    return params;
  }

  const start = normalizeDateInput(startInput.value);
  const end = normalizeDateInput(endInput.value);
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (currentProject) params.set("project", currentProject);
  if (currentSessionSort) params.set("sort", currentSessionSort);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return params;
}

function applyListPage(items, { append, hasMore, nextOffset }) {
  currentListItems = append ? currentListItems.concat(items) : items;
  currentListHasMore = !!hasMore;
  currentListNextOffset = Number.isInteger(nextOffset) ? nextOffset : currentListItems.length;
  currentListLoadingMore = false;
  if (browseMode === "projects" && !currentProject) {
    renderProjects(currentListItems);
  } else {
    renderSessions(currentListItems);
  }
  updateListFooter();
}

function resetListPagination() {
  currentListItems = [];
  currentListHasMore = false;
  currentListNextOffset = 0;
  currentListLoadingMore = false;
  updateListFooter();
}

async function fetchSessions({ append = false } = {}) {
  const seq = (sessionsFetchSeq += 1);
  const limit = SESSION_LIST_PAGE_LIMIT;
  const offset = append ? currentListNextOffset : 0;
  const params = buildListParams(limit, offset);
  currentListLoadingMore = append;
  updateListFooter();

  try {
    const res = await fetch(`${apiBase()}/sessions?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (seq !== sessionsFetchSeq) return;
    applyListPage(data.sessions || [], {
      append,
      hasMore: data.has_more,
      nextOffset: data.next_offset,
    });
  } catch (err) {
    if (seq !== sessionsFetchSeq) return;
    currentListLoadingMore = false;
    if (!append) {
      currentListItems = [];
      renderSessions([]);
      resultCountEl.textContent = "0";
    }
    updateListFooter();
  }
}

async function fetchSession(sessionId) {
  const seq = (sessionFetchSeq += 1);
  expandedMessageIndexes = new Set();
  renderStatusMessage("Loading…");
  try {
    const res = await fetch(`${apiBase()}/session/${encodeURIComponent(sessionId)}`);
    if (!res.ok) {
      renderStatusMessage(`Failed to load session (${res.status})`, { kind: "error" });
      return;
    }
    const data = await res.json();
    if (seq !== sessionFetchSeq) return;
    currentSession = data.session;
    currentMessages = (data.messages || []).map((msg) => ({
      ...msg,
      preview_text: msg?.is_truncated ? (msg.text || "") : null,
      full_text_loaded: !msg?.is_truncated,
    }));
    expandedMessageIndexes = new Set();
    renderSessionHeader(currentSession);
    renderMessages(currentMessages);
  } catch (err) {
    if (seq !== sessionFetchSeq) return;
    renderStatusMessage(`Failed to load session (${err?.message || err})`, { kind: "error" });
  }
}

async function fetchProjects({ append = false } = {}) {
  const seq = (projectsFetchSeq += 1);
  const limit = PROJECT_LIST_PAGE_LIMIT;
  const offset = append ? currentListNextOffset : 0;
  const params = buildListParams(limit, offset);
  currentListLoadingMore = append;
  updateListFooter();
  try {
    const res = await fetch(`${apiBase()}/projects?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (seq !== projectsFetchSeq) return;
    applyListPage(data.projects || [], {
      append,
      hasMore: data.has_more,
      nextOffset: data.next_offset,
    });
  } catch (err) {
    if (seq !== projectsFetchSeq) return;
    currentListLoadingMore = false;
    if (!append) {
      currentListItems = [];
      renderProjects([]);
      resultCountEl.textContent = "0";
    }
    updateListFooter();
  }
}

async function reloadList() {
  resetListPagination();
  setResultsHeader();
  if (browseMode === "projects" && !currentProject) {
    return fetchProjects({ append: false });
  }
  return fetchSessions({ append: false });
}

async function loadMoreList() {
  if (!currentListHasMore || currentListLoadingMore) return;
  if (browseMode === "projects" && !currentProject) {
    return fetchProjects({ append: true });
  }
  return fetchSessions({ append: true });
}

async function deleteProjectSessions(project) {
  const name = (project || "").trim();
  if (!name) return;
  const countHint = resultCountEl.textContent && resultCountEl.textContent !== "0"
    ? `\n\nThis currently shows ${resultCountEl.textContent} session(s).`
    : "";
  const confirmed = confirm(
    `Delete all indexed chats for project:\n${name}\n\nThe source JSONL files will be moved to deleted_projects for backup.${countHint}`
  );
  if (!confirmed) return;

  const res = await fetch(`${apiBase()}/project/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project: name }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert(data.error || "Delete project chats failed.");
    return;
  }

  currentProject = null;
  const prev = sessionListEl.querySelector(".session-item.active");
  if (prev) prev.classList.remove("active");
  resetSessionPane();
  await reloadList();
  const backupLine = data.backup_dir ? `\nBackup: ${data.backup_dir}` : "";
  alert(`Deleted ${data.deleted_count || 0} session(s).${backupLine}`);
}

async function cleanupWeakSessions() {
  const scopeLabel = currentProject
    ? `project:\n${currentProject}`
    : `${getSystemLabel(currentSystem)} ${getSourceLabel()} source`;
  const confirmed = confirm(
    `Cleanup weak chats in ${scopeLabel}?\n\nRule:\n- fewer than 5 user prompts\n\nExamples that will be deleted:\n- "hello"\n- "Set-Location -LiteralPath ...; codex resume ..."\n\nSource JSONL files will be moved to deleted_projects for backup.`
  );
  if (!confirmed) return;

  const payload = { min_user_messages: 5 };
  if (currentProject) payload.project = currentProject;

  const res = await fetch(`${apiBase()}/cleanup/weak-sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert(data.error || "Cleanup weak chats failed.");
    return;
  }

  resetSessionPane();
  await reloadList();

  if (!data.deleted_count) {
    alert("No weak chats matched the cleanup rules.");
    return;
  }
  const backupLine = data.backup_dir ? `\nBackup: ${data.backup_dir}` : "";
  alert(`Deleted ${data.deleted_count} weak session(s).${backupLine}`);
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch (err) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }
}

sessionListEl.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : event.target?.parentElement;
  const item = target ? target.closest(".session-item") : null;
  if (!item) return;
  const prev = sessionListEl.querySelector(".session-item.active");
  if (prev) prev.classList.remove("active");
  item.classList.add("active");

  if (browseMode === "projects" && !currentProject) {
    const project = item.dataset.project;
    if (!project) return;
    currentProject = project;
    resetSessionPane();
    reloadList();
    return;
  }

  const sessionId = item.dataset.sessionId;
  if (!sessionId) return;
  fetchSession(sessionId);
});

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  reloadList();
});

keywordInput.addEventListener("input", () => {
  scheduleReloadList();
});

startInput.addEventListener("input", () => {
  scheduleReloadList();
});

endInput.addEventListener("input", () => {
  scheduleReloadList();
});

sessionSearchInput.addEventListener("input", () => {
  scheduleSessionSearchRender();
});

sessionSearchInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  gotoNextMatch(event.shiftKey ? -1 : 1);
});

prevMatchBtn.addEventListener("click", () => {
  gotoNextMatch(-1);
});

nextMatchBtn.addEventListener("click", () => {
  gotoNextMatch(1);
});

clearSessionSearch.addEventListener("click", () => {
  sessionSearchInput.value = "";
  sessionSearchFetchSeq += 1;
  currentSessionSearch = createEmptySessionSearchState();
  renderMessages(currentMessages);
});

if (listLoadMoreBtn) {
  listLoadMoreBtn.addEventListener("click", () => {
    loadMoreList();
  });
}

backToProjectsBtn.addEventListener("click", () => {
  currentProject = null;
  const prev = sessionListEl.querySelector(".session-item.active");
  if (prev) prev.classList.remove("active");
  resetSessionPane();
  reloadList();
});

if (deleteProjectSessionsBtn) {
  deleteProjectSessionsBtn.addEventListener("click", async () => {
    if (!currentProject) return;
    await deleteProjectSessions(currentProject);
  });
}

if (cleanupWeakSessionsBtn) {
  cleanupWeakSessionsBtn.addEventListener("click", async () => {
    await cleanupWeakSessions();
  });
}

copyWorkdirBtn.addEventListener("click", () => {
  copyText(workdirValueEl.textContent || "");
});

copyResumeIdBtn.addEventListener("click", () => {
  copyText(resumeValueEl.textContent || "");
});

copyResumeCmdPsBtn.addEventListener("click", () => {
  copyText(resumeCmdPsEl.textContent || "");
});

copyResumeCmdWslBtn.addEventListener("click", () => {
  copyText(resumeCmdWslEl.textContent || "");
});

messagesEl.addEventListener("click", async (event) => {
  const target = event.target instanceof Element ? event.target : event.target?.parentElement;
  const toggle = target ? target.closest("[data-message-toggle]") : null;
  if (!toggle) return;
  const index = Number(toggle.dataset.messageToggle);
  if (!Number.isInteger(index)) return;
  const willExpand = !expandedMessageIndexes.has(index);
  const msg = currentMessages[index];

  if (willExpand && msg?.is_truncated && !msg?.full_text_loaded) {
    toggle.setAttribute("disabled", "true");
    try {
      await fetchFullMessage(index);
    } catch (err) {
      alert(`Failed to load full message (${err?.message || err}).`);
      return;
    } finally {
      toggle.removeAttribute("disabled");
    }
  }

  if (!willExpand) {
    expandedMessageIndexes.delete(index);
  } else {
    expandedMessageIndexes.add(index);
  }
  renderMessages(currentMessages);
});

pinSessionBtn.addEventListener("click", async () => {
  if (!currentSession) return;
  const newPinned = !currentSession.pinned;
  const base = apiBase();
  await fetch(`${base}/session/${encodeURIComponent(currentSession.id)}/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pinned: newPinned }),
  });
  currentSession.pinned = newPinned ? 1 : 0;
  renderSessionHeader(currentSession);
  reloadList();
});

renameSessionBtn.addEventListener("click", async () => {
  if (!currentSession) return;
  const newTitle = prompt("New session name:", currentSession.title || "");
  if (newTitle === null || newTitle.trim() === "") return;
  const base = apiBase();
  const res = await fetch(`${base}/session/${encodeURIComponent(currentSession.id)}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: newTitle.trim() }),
  });
  if (!res.ok) {
    alert("Rename failed.");
    return;
  }
  const payload = await res.json().catch(() => ({}));
  if (!payload.ok) {
    alert(payload.error || "Rename failed.");
    return;
  }
  currentSession.title = newTitle.trim();
  renderSessionHeader(currentSession);
  reloadList();
});

archiveSessionBtn.addEventListener("click", async () => {
  if (!currentSession) return;
  const title = currentSession.title || currentSession.id;
  if (!confirm(`Archive session "${title}"?\n\nThe file will be moved to archived_sessions.`)) return;
  const base = apiBase();
  const res = await fetch(`${base}/session/${encodeURIComponent(currentSession.id)}/archive`, {
    method: "POST",
  });
  if (res.ok) {
    resetSessionPane();
    reloadList();
  } else {
    alert("Archive failed.");
  }
});

codeThemeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const theme = btn.dataset.codeTheme;
    if (!theme || theme === currentCodeTheme) return;
    setCodeTheme(theme, { persist: true });
  });
});
applyStoredCodeTheme();
applyStoredSessionSort();

if (sessionSortEl) {
  sessionSortEl.addEventListener("change", () => {
    setSessionSort(sessionSortEl.value, { persist: true });
    reloadList();
  });
}

const roleInputs = document.querySelectorAll(".roles input[type=checkbox]");
applyRoleFiltersFromStorage(roleInputs);
roleInputs.forEach((input) => {
  input.addEventListener("change", () => {
    persistRoleFilters(roleInputs);
    renderMessages(currentMessages);
  });
});

if (sourceTabsEl) {
  sourceTabsEl.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-source]") : null;
    const source = target?.dataset?.source;
    if (!source || source === currentSource) return;
    setCurrentSource(source, { persist: true });
    currentProject = null;
    resetSessionPane();
    messagesEl.innerHTML = "";
    reloadList();
  });
}

if (systemTabsEl) {
  systemTabsEl.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-system]") : null;
    const system = target?.dataset?.system;
    if (!system || system === currentSystem) return;
    setCurrentSystem(system, { persist: true });
    currentProject = null;
    resetSessionPane();
    messagesEl.innerHTML = "";
    reloadList();
  });
}

document.querySelectorAll("[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    if (!view || view === browseMode) return;
    browseMode = view;
    currentProject = null;

    document.querySelectorAll("[data-view]").forEach((b) => {
      const active = b.dataset.view === browseMode;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    });

    const prev = sessionListEl.querySelector(".session-item.active");
    if (prev) prev.classList.remove("active");
    reloadList();
  });
});

function setupResizers() {
  if (sidebarResizerEl && sidebarEl) {
    sidebarResizerEl.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = sidebarEl.getBoundingClientRect().width;
      let lastWidth = startWidth;

      document.body.classList.add("is-resizing");
      document.body.style.cursor = "col-resize";
      sidebarResizerEl.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        if (e.pointerId !== event.pointerId) return;
        const dx = e.clientX - startX;
        lastWidth = setSidebarWidthPx(startWidth + dx, { persist: false });
      };

      const onEnd = (e) => {
        if (e.pointerId !== event.pointerId) return;
        setSidebarWidthPx(lastWidth, { persist: true });
        document.body.classList.remove("is-resizing");
        document.body.style.cursor = "";
        sidebarResizerEl.removeEventListener("pointermove", onMove);
        sidebarResizerEl.removeEventListener("pointerup", onEnd);
        sidebarResizerEl.removeEventListener("pointercancel", onEnd);
      };

      sidebarResizerEl.addEventListener("pointermove", onMove);
      sidebarResizerEl.addEventListener("pointerup", onEnd);
      sidebarResizerEl.addEventListener("pointercancel", onEnd);
    });
  }

  if (sidebarSessionsResizerEl && sidebarTopEl) {
    sidebarSessionsResizerEl.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const startY = event.clientY;
      const startHeight = sidebarTopEl.getBoundingClientRect().height;
      let lastHeight = startHeight;

      document.body.classList.add("is-resizing");
      document.body.style.cursor = "row-resize";
      sidebarSessionsResizerEl.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        if (e.pointerId !== event.pointerId) return;
        const dy = e.clientY - startY;
        const nextHeight = startHeight + dy;
        const clamped = setSidebarTopHeightPx(nextHeight, { persist: false });
        if (typeof clamped === "number") lastHeight = clamped;
      };

      const onEnd = (e) => {
        if (e.pointerId !== event.pointerId) return;
        setSidebarTopHeightPx(lastHeight, { persist: true });
        document.body.classList.remove("is-resizing");
        document.body.style.cursor = "";
        sidebarSessionsResizerEl.removeEventListener("pointermove", onMove);
        sidebarSessionsResizerEl.removeEventListener("pointerup", onEnd);
        sidebarSessionsResizerEl.removeEventListener("pointercancel", onEnd);
      };

      sidebarSessionsResizerEl.addEventListener("pointermove", onMove);
      sidebarSessionsResizerEl.addEventListener("pointerup", onEnd);
      sidebarSessionsResizerEl.addEventListener("pointercancel", onEnd);
    });
  }

  if (headerResizerEl && sessionHeaderEl) {
    headerResizerEl.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const startY = event.clientY;
      const startHeight = sessionHeaderEl.getBoundingClientRect().height;
      let lastHeight = startHeight;

      document.body.classList.add("is-resizing");
      document.body.style.cursor = "row-resize";
      headerResizerEl.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        if (e.pointerId !== event.pointerId) return;
        const dy = e.clientY - startY;
        const nextHeight = startHeight + dy;
        const clamped = setHeaderHeightPx(nextHeight, { persist: false });
        if (typeof clamped === "number") lastHeight = clamped;
      };

      const onEnd = (e) => {
        if (e.pointerId !== event.pointerId) return;
        setHeaderHeightPx(lastHeight, { persist: true });
        document.body.classList.remove("is-resizing");
        document.body.style.cursor = "";
        headerResizerEl.removeEventListener("pointermove", onMove);
        headerResizerEl.removeEventListener("pointerup", onEnd);
        headerResizerEl.removeEventListener("pointercancel", onEnd);
      };

      headerResizerEl.addEventListener("pointermove", onMove);
      headerResizerEl.addEventListener("pointerup", onEnd);
      headerResizerEl.addEventListener("pointercancel", onEnd);
    });
  }
}

applyStoredLayout();
setupResizers();
window.addEventListener("resize", () => {
  clampLayoutToViewport();
});

async function bootstrapApp() {
  await loadSourceCatalog();
  applyStoredSourceContext();
  updateResumeCommandLabels();
  reloadList();
}

bootstrapApp();
