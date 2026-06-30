export {};

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
const clearRenderCacheBtn = document.getElementById("clearRenderCache");
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
const scrollBottomBtn = document.getElementById("scrollBottomBtn");
const auditPanelEl = document.getElementById("auditPanel");
const auditActionsEl = document.getElementById("auditActions");
const auditToggleEl = document.getElementById("auditToggle");
const toolActionsEl = document.getElementById("toolActions");
const expandAllToolsBtn = document.getElementById("expandAllTools");
const collapseAllToolsBtn = document.getElementById("collapseAllTools");
const toolTimelineEl = document.getElementById("toolTimeline");
const codeThemeButtons = document.querySelectorAll("[data-code-theme]");

let currentSession = null;
let currentMessages = [];
let currentBrowseMessages = [];
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
let sourceMeta = new Map();
let availableSourcesBySystem = new Map([
  ["windows", ["codex", "claude", "openclaw"]],
  ["wsl", ["codex", "claude", "openclaw"]],
  ["linux", ["codex", "claude", "openclaw", "opencode"]],
]);
const SYSTEM_ORDER = ["windows", "wsl", "linux"];
const SOURCE_ORDER = ["codex", "claude", "openclaw", "opencode", "hermes"];
const LIST_RELOAD_DEBOUNCE_MS = 200;
const SESSION_SEARCH_DEBOUNCE_MS = 220;
const MESSAGE_RENDER_PAGE_SIZE = 200;
const MESSAGE_COLLAPSE_THRESHOLD = 12_000;
const MESSAGE_PREVIEW_CHARS = 4_000;
const MESSAGE_LAZY_RENDER_ROOT_MARGIN = "800px 0px";
const SESSION_LIST_PAGE_LIMIT = 50;
const PROJECT_LIST_PAGE_LIMIT = 40;
const MARKDOWN_RENDER_VERSION = "2026-05-27-1";
const MARKDOWN_CACHE_INDEX_KEY = "historyViewer.markdownCache.v1.index";
const MARKDOWN_CACHE_ENTRY_PREFIX = "historyViewer.markdownCache.v1.entry.";
const MARKDOWN_CACHE_MAX_ENTRIES = 80;
const MARKDOWN_CACHE_MAX_TOTAL_CHARS = 2_500_000;
const MARKDOWN_CACHE_MAX_ENTRY_CHARS = 160_000;
let messageRenderCache = new WeakMap();
let markdownCacheIndex = null;
let messageBodyObserver = null;
const pendingLazyMessageBodies = new Map();
let currentMessageOffset = 0;
let currentMessageTotal = 0;
let currentMessagesLoadingEarlier = false;
let currentSearchRenderLimit = MESSAGE_RENDER_PAGE_SIZE;
let pinSessionInFlight = false;
let currentAudit = null;
let auditFetchSeq = 0;
let auditCollapsed = false;
let currentFilePathFilter = "";
let toolsCollapsedByDefault = true;
let expandedToolIndexes = new Set();
let collapsedToolIndexes = new Set();
let fullToolOutputIndexes = new Set();

if (scrollBottomBtn) {
  const updateScrollBottomBtn = () => {
    const maxScroll = messagesEl.scrollHeight - messagesEl.clientHeight;
    scrollBottomBtn.hidden = messagesEl.scrollTop >= maxScroll - 200;
  };
  messagesEl.addEventListener("scroll", updateScrollBottomBtn, { passive: true });
  scrollBottomBtn.addEventListener("click", () => {
    messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" });
  });
}

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

function resetMessageRenderCount() {
  currentSearchRenderLimit = MESSAGE_RENDER_PAGE_SIZE;
}

function getSafeMessageRenderCount() {
  return Math.max(MESSAGE_RENDER_PAGE_SIZE, Number(currentSearchRenderLimit) || 0);
}

function disconnectMessageBodyObserver() {
  pendingLazyMessageBodies.clear();
  if (!messageBodyObserver) return;
  messageBodyObserver.disconnect();
  messageBodyObserver = null;
}

function takePendingLazyMessageBody(body) {
  const render = pendingLazyMessageBodies.get(body);
  if (!render) return null;
  pendingLazyMessageBodies.delete(body);
  if (messageBodyObserver) {
    messageBodyObserver.unobserve(body);
  }
  return render;
}

function flushLazyMessageBody(body) {
  const render = takePendingLazyMessageBody(body);
  if (!render) return false;
  render();
  return true;
}

function ensureMessageBodyObserver() {
  if (messageBodyObserver || typeof IntersectionObserver !== "function") {
    return messageBodyObserver;
  }

  messageBodyObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      flushLazyMessageBody(entry.target);
    });
  }, {
    root: messagesEl,
    rootMargin: MESSAGE_LAZY_RENDER_ROOT_MARGIN,
  });

  return messageBodyObserver;
}

function queueLazyMessageBody(body, render) {
  if (typeof render !== "function") return;
  const observer = ensureMessageBodyObserver();
  if (!observer) {
    render();
    return;
  }
  pendingLazyMessageBodies.set(body, render);
  observer.observe(body);
}

function collectPendingLazyMessageBodies(root, results = []) {
  if (!root || !root.children) return results;
  Array.from(root.children).forEach((child) => {
    if (pendingLazyMessageBodies.has(child)) {
      results.push(child);
    }
    collectPendingLazyMessageBodies(child, results);
  });
  return results;
}

function flushPendingLazyMessageBodiesForRoot(root) {
  const bodies = collectPendingLazyMessageBodies(root, []);
  const renders = bodies.map((body) => ({ body, render: takePendingLazyMessageBody(body) }));
  renders.forEach(({ render }) => {
    if (typeof render === "function") {
      render();
    }
  });
  return bodies.length;
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

function sourceMetaKey(system = currentSystem, source = currentSource) {
  return `${system}:${source}`;
}

function getSourceMeta(system = currentSystem, source = currentSource) {
  return sourceMeta.get(sourceMetaKey(system, source)) || {};
}

function sourceIsReadOnly(system = currentSystem, source = currentSource) {
  return !!getSourceMeta(system, source).read_only;
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
  if (source === "opencode") return "OpenCode";
  if (source === "hermes") return "Hermes";
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
  if (source === "claude") return `claude -r ${sessionId} --dangerously-skip-permissions`;
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

function clearMarkdownRenderCache() {
  const keys = new Set([MARKDOWN_CACHE_INDEX_KEY]);
  const index = loadMarkdownCacheIndex();
  index.entries.forEach((entry) => {
    if (entry?.key) keys.add(entry.key);
  });
  try {
    const length = Number(localStorage.length);
    if (Number.isFinite(length)) {
      for (let i = 0; i < length; i += 1) {
        const key = localStorage.key(i);
        if (typeof key === "string" && key.startsWith("historyViewer.markdownCache")) {
          keys.add(key);
        }
      }
    }
  } catch {
    // ignore
  }
  try {
    Object.keys(localStorage).forEach((key) => {
      if (key.startsWith("historyViewer.markdownCache")) {
        keys.add(key);
      }
    });
  } catch {
    // ignore
  }

  messageRenderCache = new WeakMap();
  markdownCacheIndex = { entries: [] };
  keys.forEach((key) => {
    try {
      localStorage.removeItem(key);
    } catch {
      // ignore
    }
  });
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
    MARKDOWN_RENDER_VERSION,
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
  const allowed = new Set(["start", "last", "value"]);
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
    sourceMeta = new Map();
    availableSourcesBySystem = new Map();
    nextSourcesBySystem.forEach((sources, system) => {
      availableSourcesBySystem.set(system, sortByKnownOrder(sources, SOURCE_ORDER));
    });
    (data.sources || []).forEach((item) => {
      const system = String(item?.system || "").trim();
      const source = String(item?.source || "").trim();
      if (!system || !source) return;
      sourceMeta.set(sourceMetaKey(system, source), {
        read_only: !!item?.read_only,
      });
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
    if (currentSessionSort === "value") {
      const valDiff = (b?.value_score || 0) - (a?.value_score || 0);
      if (valDiff) return valDiff;
    }
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

const OUTCOME_ICONS = {
  completed: "\u2713",
  partially_completed: "\u2713",
  errored: "\u2717",
  interrupted: "\u23F8",
  incomplete: "\u2026",
  exploration: "?",
  unknown: "?",
};

function _fileCount(session) {
  const ft = session?.files_touched;
  if (!ft || typeof ft !== "object") return 0;
  return (Array.isArray(ft.local) ? ft.local.length : 0)
    + (Array.isArray(ft.remote) ? ft.remote.length : 0)
    + (Array.isArray(ft.inferred) ? ft.inferred.length : 0);
}

function _toolCount(session) {
  const tools = session?.tools_used;
  if (!tools || typeof tools !== "object") return 0;
  return Object.values(tools).reduce((sum, n) => sum + (Number(n) || 0), 0);
}

function _hasIntent(session, label) {
  const intents = session?.command_intents;
  return !!intents && typeof intents === "object" && Number(intents[label] || 0) > 0;
}

function _hasRemote(session) {
  const rc = session?.remote_context;
  if (!rc) return false;
  if (Array.isArray(rc)) return rc.length > 0;
  if (typeof rc === "object") return Object.keys(rc).length > 0;
  return false;
}

function renderSessionBadges(session) {
  const chips = [];
  const files = _fileCount(session);
  if (files > 0) chips.push(`<span class="audit-badge badge-files" title="${files} file(s) touched">\u{1F4C2} ${files}</span>`);
  const tools = _toolCount(session);
  if (tools > 0) chips.push(`<span class="audit-badge badge-tools" title="${tools} tool call(s)">\u{1F6E0} ${tools}</span>`);
  if (_hasRemote(session)) chips.push(`<span class="audit-badge badge-remote" title="Remote commands detected">\u{1F310} Remote</span>`);
  if (_hasIntent(session, "TEST")) chips.push(`<span class="audit-badge badge-test" title="Test commands">\u{1F9EA} Test</span>`);
  if (_hasIntent(session, "DEPLOY")) chips.push(`<span class="audit-badge badge-deploy" title="Deploy commands">\u{1F680} Deploy</span>`);
  if (_hasIntent(session, "DEBUG")) chips.push(`<span class="audit-badge badge-debug" title="Debug commands">\u{1F41E} Debug</span>`);
  const friction = Number(session?.friction_score || 0);
  if (friction > 0) chips.push(`<span class="audit-badge badge-friction" title="Friction score (errors + retries + interrupts)">\u26A0\uFE0F ${friction}</span>`);
  const outcome = session?.outcome_signal || "unknown";
  const icon = OUTCOME_ICONS[outcome] || "?";
  chips.push(`<span class="audit-badge badge-outcome outcome-${escapeHtml(outcome)}" title="Outcome: ${escapeHtml(outcome)}">${icon}</span>`);
  const value = Number(session?.value_score || 0);
  chips.push(`<span class="audit-badge badge-value" title="Value score (0-100)">\u25C6 ${value}</span>`);
  if (chips.length === 0) return "";
  return `<div class="audit-badges">${chips.join("")}</div>`;
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
  const pinned = sorted.filter((session) => !!session.pinned);
  const unpinned = sorted.filter((session) => !session.pinned);
  sessionListEl.innerHTML = "";
  const appendSessionItem = (session) => {
    const item = document.createElement("div");
    item.className = "session-item";
    if (session.pinned) item.classList.add("pinned");
    if (currentSession?.id && currentSession.id === session.id) item.classList.add("active");
    item.dataset.sessionId = session.id;
    const pinIcon = session.pinned ? '<span class="pin-icon">\u{1F4CC}</span>' : '';
    item.innerHTML = `
      <div class="session-title">${pinIcon}${escapeHtml(session.title || "Session")}</div>
      <div class="session-meta">${escapeHtml(formatSessionMeta(session))}</div>
      ${renderSessionBadges(session)}
    `;
    sessionListEl.appendChild(item);
  };

  if (pinned.length > 0) {
    const divider = document.createElement("div");
    divider.className = "date-divider pinned-divider";
    divider.textContent = "Pinned";
    sessionListEl.appendChild(divider);
    pinned.forEach(appendSessionItem);
  }

  let lastDate = "";
  const useDateDividers = currentSessionSort !== "value";
  unpinned.forEach((session) => {
    if (useDateDividers) {
      const date = formatDate(sessionSortKeyMs(session));
      if (date && date !== lastDate) {
        const divider = document.createElement("div");
        divider.className = "date-divider";
        divider.textContent = date;
        sessionListEl.appendChild(divider);
        lastDate = date;
      }
    }
    appendSessionItem(session);
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
  disconnectMessageBodyObserver();
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
  if (msg?.is_search_excerpt) {
    return {
      html: getOrRenderMarkdownHtml(buildMessageMarkdownCacheKey(msg, "search-excerpt", cached.fullText), cached.fullText),
      mode: "search-excerpt",
    };
  }
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

function renderMessageBodyInto(body, msg, { expanded = false, searchMatch = null, term = "" } = {}) {
  const bodyRender = getMessageBodyHtml(msg, { expanded, searchMatch });
  body.innerHTML = bodyRender.html;
  body.classList.remove("pending");
  const hits = term && searchMatch ? highlightElement(body, term) : 0;
  return { ...bodyRender, hits };
}

function buildMessageRenderPlan(messages, roleFilters, term, sessionSearch, renderCount) {
  const normalizedTerm = String(term || "").trim();
  const visibleMessages = [];
  messages.forEach((msg, localIndex) => {
    const roleClass = roleToClass(msg.role);
    if (!roleFilters[roleClass]) return;
    const index = Number.isInteger(msg?.message_index) ? msg.message_index : currentMessageOffset + localIndex;
    visibleMessages.push({ msg, index });
  });

  const safeRenderCount = Math.max(MESSAGE_RENDER_PAGE_SIZE, Number(renderCount) || 0);
  if (!normalizedTerm) {
    return {
      mode: "browse",
      items: visibleMessages,
      totalVisible: currentMessageTotal || visibleMessages.length,
      hiddenBefore: Math.max(0, currentMessageOffset),
      hiddenAfter: 0,
      loading: false,
      error: "",
    };
  }

  if (sessionSearch?.query !== normalizedTerm) {
    return {
      mode: "search",
      items: [],
      totalVisible: 0,
      hiddenBefore: 0,
      hiddenAfter: 0,
      loading: true,
      error: "",
    };
  }

  if (sessionSearch?.loading) {
    return {
      mode: "search",
      items: [],
      totalVisible: 0,
      hiddenBefore: 0,
      hiddenAfter: 0,
      loading: true,
      error: "",
    };
  }

  if (sessionSearch?.error) {
    return {
      mode: "search",
      items: [],
      totalVisible: 0,
      hiddenBefore: 0,
      hiddenAfter: 0,
      loading: false,
      error: sessionSearch.error,
    };
  }

  const matches = sessionSearch?.matches && typeof sessionSearch.matches.has === "function"
    ? sessionSearch.matches
    : new Map();
  const matchedMessages = [];
  matches.forEach((match, index) => {
    const roleClass = roleToClass(match?.role);
    if (!roleFilters[roleClass]) return;
    matchedMessages.push({
      msg: {
        ...match,
        text: match.excerpt_text || "",
        is_search_excerpt: true,
        is_truncated: false,
        full_text_loaded: true,
      },
      index,
    });
  });
  const totalVisible = Number.isFinite(sessionSearch?.messageMatchCount)
    ? sessionSearch.messageMatchCount
    : matchedMessages.length;
  const items = matchedMessages.slice(0, safeRenderCount);
  return {
    mode: "search",
    items,
    totalVisible,
    hiddenBefore: 0,
    hiddenAfter: Math.max(0, totalVisible - items.length),
    loading: false,
    error: "",
  };
}

function buildMessageWindowControl(plan) {
  if (!plan) return null;
  if (plan.mode === "browse" && plan.hiddenBefore <= 0) return null;
  if (plan.mode === "search" && plan.hiddenAfter <= 0) return null;

  const wrapper = document.createElement("div");
  wrapper.className = "message-window-card";

  const note = document.createElement("div");
  note.className = "message-window-note";
  if (plan.mode === "browse") {
    note.textContent = `Showing messages ${(currentMessageOffset + 1).toLocaleString()}-${(currentMessageOffset + plan.items.length).toLocaleString()} of ${plan.totalVisible.toLocaleString()}.`;
  } else {
    note.textContent = `Showing ${plan.items.length.toLocaleString()} of ${plan.totalVisible.toLocaleString()} matched messages. Load more matches if needed.`;
  }
  wrapper.appendChild(note);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn small";
  button.dataset.messageWindowAction = "more";
  button.textContent = plan.mode === "browse"
    ? `Load ${Math.min(MESSAGE_RENDER_PAGE_SIZE, plan.hiddenBefore).toLocaleString()} earlier messages`
    : `Load ${Math.min(MESSAGE_RENDER_PAGE_SIZE, plan.hiddenAfter).toLocaleString()} more matches`;
  wrapper.appendChild(button);

  return wrapper;
}

// BDD cross-ref (002 §M5): tool_use/tool_result blocks render a one-line summary
// header and collapse the full body, so a dense transcript stays scannable.
const TOOL_CATEGORY_META = {
  shell: { icon: "\u25B6", label: "Shell", cls: "badge-test" },
  edit: { icon: "\u270E", label: "Edit", cls: "badge-deploy" },
  read: { icon: "\u{1F441}", label: "Read", cls: "badge-tools" },
  search: { icon: "\u{1F50D}", label: "Search", cls: "badge-tools" },
  deploy: { icon: "\u{1F680}", label: "Deploy", cls: "badge-remote" },
  other: { icon: "\u{1F6E0}", label: "Tool", cls: "badge-tools" },
};

function isToolMessage(msg) {
  return msg?.kind === "tool_use" || msg?.kind === "tool_result";
}

function isToolMessageCollapsed(index) {
  if (expandedToolIndexes.has(index)) return false;
  if (collapsedToolIndexes.has(index)) return true;
  return toolsCollapsedByDefault;
}

function expandToolMessage(index) {
  expandedToolIndexes.add(index);
  collapsedToolIndexes.delete(index);
}

function collapseToolMessage(index) {
  collapsedToolIndexes.add(index);
  expandedToolIndexes.delete(index);
}

function toggleToolMessage(index) {
  if (isToolMessageCollapsed(index)) expandToolMessage(index);
  else collapseToolMessage(index);
}

function expandAllToolMessages() {
  toolsCollapsedByDefault = false;
  expandedToolIndexes = new Set();
  collapsedToolIndexes = new Set();
}

function collapseAllToolMessages() {
  toolsCollapsedByDefault = true;
  expandedToolIndexes = new Set();
  collapsedToolIndexes = new Set();
}

function renderToolStatusHtml(summary) {
  if (summary.is_error) {
    return `<span class="msg-tool-status error" title="Error">\u2715</span>`;
  }
  const status = summary.exit_status;
  if (status === "ok") {
    const code = Number(summary.exit_code);
    const tip = Number.isFinite(code) ? `Exit ${code}` : "Exit 0";
    return `<span class="msg-tool-status ok" title="${escapeHtml(tip)}">\u2713</span>`;
  }
  if (status === "error") {
    return `<span class="msg-tool-status error" title="Error">\u2715</span>`;
  }
  return `<span class="msg-tool-status unknown" title="Status unknown">\u00B7</span>`;
}

function renderToolSummaryHtml(msg) {
  const s = msg?.tool_summary;
  if (!s || typeof s !== "object") return null;
  const cat = String(s.category || "other").toLowerCase();
  const meta = TOOL_CATEGORY_META[cat] || TOOL_CATEGORY_META.other;
  const name = String(s.name || (msg.kind === "tool_use" ? "tool use" : "tool result"));
  const headline = s.headline ? escapeHtml(String(s.headline)) : "";
  const parts = [`<span class="msg-tool-icon ${escapeHtml(meta.cls)}" aria-hidden="true">${meta.icon}</span>`];
  parts.push(`<span class="msg-tool-name">${escapeHtml(name)}</span>`);
  if (headline) parts.push(`<span class="msg-tool-headline">${headline}</span>`);
  if (s.file_path) {
    parts.push(`<span class="msg-tool-path" title="${escapeHtml(s.file_path)}">${escapeHtml(s.file_path)}</span>`);
  }
  const added = Number(s.lines_added) || 0;
  const removed = Number(s.lines_removed) || 0;
  const diffParts = [];
  if (added > 0) diffParts.push(`<span class="msg-tool-diff add">+${added}</span>`);
  if (removed > 0) diffParts.push(`<span class="msg-tool-diff rem">-${removed}</span>`);
  if (diffParts.length) parts.push(`<span class="msg-tool-counts">${diffParts.join("")}</span>`);
  parts.push(renderToolStatusHtml(s));
  return parts.join("");
}

function updateToolActionsVisibility() {
  if (!toolActionsEl) return;
  const hasTools = currentMessages.some(isToolMessage);
  toolActionsEl.style.display = hasTools ? "flex" : "none";
}

function renderToolTimeline() {
  if (!toolTimelineEl) return;
  const toolEntries = [];
  for (let i = 0; i < currentMessages.length; i++) {
    const msg = currentMessages[i];
    if (!isToolMessage(msg)) continue;
    const summary = msg.tool_summary;
    let statusClass = "unknown";
    if (summary) {
      if (summary.is_error) statusClass = "error";
      else if (summary.exit_status === "ok") statusClass = "ok";
      else if (summary.exit_status === "error") statusClass = "error";
    }
    toolEntries.push({ index: i, statusClass, summary });
  }
  if (toolEntries.length === 0) {
    toolTimelineEl.hidden = true;
    toolTimelineEl.innerHTML = "";
    return;
  }
  toolTimelineEl.hidden = false;
  const total = currentMessages.length;
  let html = "";
  for (const entry of toolEntries) {
    const top = total > 1 ? (entry.index / (total - 1)) * 100 : 0;
    const title = entry.summary
      ? `${entry.summary.name || "tool"}: ${entry.summary.headline || ""}`
      : `Tool msg #${entry.index}`;
    html += `<div class="tool-timeline-dot ${entry.statusClass}" style="top:${top}%;" data-message-index="${entry.index}" title="${escapeHtml(title)}" role="button" tabindex="0" aria-label="Jump to tool call at message ${entry.index}"></div>`;
  }
  toolTimelineEl.innerHTML = html;
}

function updateToolTimelineCurrent(activeIndex) {
  if (!toolTimelineEl) return;
  const dots = toolTimelineEl.querySelectorAll(".tool-timeline-dot");
  dots.forEach((dot) => {
    if (parseInt(dot.dataset.messageIndex, 10) === activeIndex)
      dot.classList.add("current");
    else
      dot.classList.remove("current");
  });
}

const TOOL_OUTPUT_PREVIEW_LINES = 20;

function renderToolMessageBody(body, msg, { index, expanded, searchMatch, term }) {
  if (msg.kind !== "tool_result") {
    return renderMessageBodyInto(body, msg, { expanded, searchMatch, term });
  }
  const cached = getMessageRenderData(msg);
  const showFull = fullToolOutputIndexes.has(index);
  const lines = cached.fullText.split("\n");
  if (!showFull && lines.length > TOOL_OUTPUT_PREVIEW_LINES) {
    const previewText = lines.slice(0, TOOL_OUTPUT_PREVIEW_LINES).join("\n");
    const hiddenCount = lines.length - TOOL_OUTPUT_PREVIEW_LINES;
    const cacheKey = buildMessageMarkdownCacheKey(msg, "tool-preview", previewText);
    let html = getOrRenderMarkdownHtml(cacheKey, previewText);
    html += `<div class="msg-tool-output-truncated muted">${hiddenCount} more line(s) hidden. <button type="button" class="btn small msg-tool-output-toggle" data-tool-output-toggle="${index}">Show all ${lines.length} lines</button></div>`;
    body.innerHTML = html;
    body.classList.remove("pending");
    const hits = term && searchMatch ? highlightElement(body, term) : 0;
    return { mode: "tool-preview", hits };
  }
  return renderMessageBodyInto(body, msg, { expanded, searchMatch, term });
}

function buildMessageElement(msg, index, term) {
  const roleClass = roleToClass(msg.role);
  const cached = getMessageRenderData(msg);
  const expandedByUser = expandedMessageIndexes.has(index);
  const searchMatch = getSessionSearchMatch(index, term);
  const expanded = !cached.collapsible || expandedByUser;

  const wrapper = document.createElement("div");
  wrapper.className = `msg ${roleClass}`;
  wrapper.dataset.messageIndex = String(index);
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

  const isTool = isToolMessage(msg);
  const toolCollapsed = isTool && isToolMessageCollapsed(index) && !searchMatch;
  if (isTool) {
    wrapper.classList.add(msg.kind === "tool_use" ? "tool-use" : "tool-result");
    wrapper.classList.add(toolCollapsed ? "tool-collapsed" : "tool-expanded");
  }

  const label = kindLabel(msg.kind) || msg.role;
  const header = document.createElement("div");
  header.className = "msg-header";
  header.textContent = `${label} ? ${formatTime(msg.ts_ms)}`;

  const body = document.createElement("div");
  body.className = "msg-body";
  const deferBodyRender = !term;
  let bodyRender = null;
  if (toolCollapsed) {
    body.hidden = true;
  } else if (isTool) {
    bodyRender = renderToolMessageBody(body, msg, { index, expanded, searchMatch, term });
  } else if (deferBodyRender) {
    body.classList.add("pending");
    body.textContent = cached.collapsible ? "Rendering preview..." : "Rendering message...";
    queueLazyMessageBody(body, () => {
      if ("isConnected" in body && !body.isConnected) return;
      renderMessageBodyInto(body, msg, { expanded, searchMatch: null, term: "" });
    });
  } else {
    bodyRender = renderMessageBodyInto(body, msg, { expanded, searchMatch, term });
  }
  const showingSearchExcerpt = bodyRender?.mode === "search-excerpt";

  wrapper.appendChild(header);
  if (isTool) {
    const summaryBar = document.createElement("div");
    summaryBar.className = "msg-tool-summary";
    summaryBar.dataset.toolToggle = String(index);
    summaryBar.setAttribute("role", "button");
    summaryBar.setAttribute("tabindex", "0");
    summaryBar.setAttribute("aria-expanded", String(!toolCollapsed));
    const chevron = toolCollapsed ? "\u25B6" : "\u25BC";
    const summaryHtml = renderToolSummaryHtml(msg);
    const fallback = `<span class="msg-tool-name muted">${escapeHtml(msg.kind === "tool_use" ? "tool use" : "tool result")}</span>`;
    summaryBar.innerHTML = `<span class="msg-tool-chevron" aria-hidden="true">${chevron}</span>${summaryHtml || fallback}`;
    wrapper.appendChild(summaryBar);
  }
  wrapper.appendChild(body);

  let hits = bodyRender?.hits || 0;

  if (cached.collapsible && !toolCollapsed) {
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

function renderMessages(messages, { scrollToBottom = false } = {}) {
  updateToolActionsVisibility();
  renderToolTimeline();
  cancelPendingMessageRender();
  const containerTop = messagesEl.getBoundingClientRect().top;
  let scrollAnchor = null;
  if (!scrollToBottom) {
    const oldMsgEls = messagesEl.querySelectorAll(".msg");
    for (let i = 0; i < oldMsgEls.length; i++) {
      const r = oldMsgEls[i].getBoundingClientRect();
      if (r.bottom > containerTop + 1) {
        scrollAnchor = { index: i, viewportOffset: r.top - containerTop };
        break;
      }
    }
  }
  const roleFilters = getRoleFilters();
  const term = sessionSearchInput.value.trim();
  currentMarks = [];
  activeMarkIndex = -1;
  prevMatchBtn.disabled = true;
  nextMatchBtn.disabled = true;

  const renderPlan = buildMessageRenderPlan(
    messages,
    roleFilters,
    term,
    currentSessionSearch,
    getSafeMessageRenderCount(),
  );
  const activeMessages = renderPlan.items;
  const renderedCount = activeMessages.length;
  const hasHiddenMessages = !term && currentMessageOffset > 0;
  const fragment = document.createDocumentFragment();

  if (renderedCount === 0) {
    const empty = document.createElement("div");
    empty.className = "muted";
    if (term) {
      if (renderPlan.loading) {
        empty.textContent = "Searching within this session…";
      } else if (renderPlan.error) {
        empty.textContent = renderPlan.error;
      } else {
        empty.textContent = "No messages match the current search.";
      }
    } else {
      empty.textContent = messages.length
        ? "No messages match the current role filters."
        : "No messages in this session.";
    }
    fragment.appendChild(empty);
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
    messagesEl.replaceChildren(fragment);
    updateMatchNavState(term);
    return;
  }

  const windowControl = buildMessageWindowControl(renderPlan);
  if (windowControl) {
    fragment.appendChild(windowControl);
  }

  if (term) {
    sessionSearchCount.textContent = currentSessionSearch.loading ? "Searching..." : "Rendering…";
  } else {
    if (hasHiddenMessages) {
      sessionSearchCount.textContent = `Showing ${renderedCount.toLocaleString()} of ${currentMessageTotal.toLocaleString()} messages`;
    } else {
      sessionSearchCount.textContent = "";
    }
  }

  activeMessages.forEach(({ msg, index }) => {
    const rendered = buildMessageElement(msg, index, term);
    fragment.appendChild(rendered.wrapper);
  });
  messagesEl.replaceChildren(fragment);

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
  }

  updateMatchNavState(term);
  if (scrollToBottom) {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  } else if (scrollAnchor) {
    const newMsgEls = messagesEl.querySelectorAll(".msg");
    if (scrollAnchor.index < newMsgEls.length) {
      const target = newMsgEls[scrollAnchor.index];
      const delta = scrollAnchor.viewportOffset - (target.getBoundingClientRect().top - containerTop);
      messagesEl.scrollTop += delta;
    }
  }
  flushPendingLazyMessageBodiesForRoot(messagesEl);
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
  currentBrowseMessages = [];
  currentMessageOffset = 0;
  currentMessageTotal = 0;
  currentMessagesLoadingEarlier = false;
  resetMessageRenderCount();
  expandedMessageIndexes = new Set();
  toolsCollapsedByDefault = true;
  expandedToolIndexes = new Set();
  collapsedToolIndexes = new Set();
  fullToolOutputIndexes = new Set();
  if (toolActionsEl) toolActionsEl.style.display = "none";
  if (toolTimelineEl) { toolTimelineEl.hidden = true; toolTimelineEl.innerHTML = ""; }
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
  if (auditActionsEl) auditActionsEl.style.display = "none";
  if (auditPanelEl) {
    auditPanelEl.hidden = true;
    auditPanelEl.innerHTML = "";
  }
  currentAudit = null;
  auditFetchSeq += 1;
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

  if (sessionActionsEl) sessionActionsEl.style.display = sourceIsReadOnly() ? "none" : "flex";
  if (pinSessionBtn) {
    pinSessionBtn.textContent = session.pinned ? "📌 Unpin" : "📌 Pin";
    pinSessionBtn.disabled = pinSessionInFlight || sourceIsReadOnly();
  }
}

// BDD cross-ref (002 §M4): the panel renders sections in this fixed order so a
// reviewer can answer the six audit questions without scrolling the transcript.
const AUDIT_INTENT_PREVIEW_CHARS = 280;
const AUDIT_OUTCOME_SUMMARY_CHARS = 280;
const AUDIT_ERROR_SAMPLE_LIMIT = 3;
const AUDIT_FILE_ROW_LIMIT = 12;

const COMMAND_INTENT_META = {
  TEST: { icon: "\u{1F9EA}", label: "Test", cls: "badge-test" },
  BUILD: { icon: "\u{1F528}", label: "Build", cls: "badge-deploy" },
  DEPLOY: { icon: "\u{1F680}", label: "Deploy", cls: "badge-deploy" },
  REMOTE: { icon: "\u{1F310}", label: "Remote", cls: "badge-remote" },
  DEBUG: { icon: "\u{1F41E}", label: "Debug", cls: "badge-debug" },
  NETWORK: { icon: "\u{1F310}", label: "Network", cls: "badge-remote" },
  SEARCH: { icon: "\u{1F50D}", label: "Search", cls: "badge-tools" },
  READ: { icon: "\u{1F4D6}", label: "Read", cls: "badge-tools" },
  UNKNOWN: { icon: "?", label: "Other", cls: "badge-tools" },
};

function renderAuditPanel(audit) {
  if (!auditPanelEl) return;
  if (!audit) {
    auditPanelEl.innerHTML = `<div class="audit-empty muted">Audit unavailable for this source.</div>`;
    return;
  }
  const html = [
    _auditSectionIntent(audit),
    _auditSectionOutcome(audit),
    _auditSectionDeliverables(audit),
    _auditSectionCommandIntents(audit),
    _auditSectionFriction(audit),
    _auditSectionValue(audit),
  ].filter(Boolean).join("");
  auditPanelEl.innerHTML = html ? `<div class="audit-sections">${html}</div>` : `<div class="audit-empty muted">No audit signals.</div>`;
  auditPanelEl.scrollTop = 0;
}

function _auditSection(title, icon, bodyHtml) {
  return `<section class="audit-section"><div class="audit-section-head"><span class="audit-section-icon" aria-hidden="true">${icon}</span><span class="audit-section-title">${title}</span></div><div class="audit-section-body">${bodyHtml}</div></section>`;
}

function _auditExpandable(text, previewChars, kind) {
  const safe = String(text || "");
  if (!safe) return `<span class="audit-muted muted">—</span>`;
  if (safe.length <= previewChars) return `<span class="audit-text">${escapeHtml(safe)}</span>`;
  const preview = safe.slice(0, previewChars);
  return `<span class="audit-text audit-truncated" data-audit-kind="${escapeHtml(kind)}"><span class="audit-text-preview">${escapeHtml(preview)}<button type="button" class="audit-expand" data-audit-expand="${escapeHtml(kind)}" aria-expanded="false">…</button></span><span class="audit-text-full" hidden>${escapeHtml(safe)}</span></span>`;
}

function _auditSectionIntent(audit) {
  const prompt = audit.first_user_prompt || audit.last_user_prompt || "";
  if (!prompt) return "";
  return _auditSection("Intent", "\u{1F4AC}", _auditExpandable(prompt, AUDIT_INTENT_PREVIEW_CHARS, "intent"));
}

function _auditSectionOutcome(audit) {
  const outcome = audit.outcome_signal || "unknown";
  const reply = audit.last_assistant_reply || "";
  const meta = COMMAND_INTENT_META[outcome.toUpperCase()] || { icon: "?", label: outcome };
  const replyHtml = reply
    ? _auditExpandable(reply, AUDIT_OUTCOME_SUMMARY_CHARS, "outcome")
    : `<span class="audit-muted muted">No assistant reply recorded.</span>`;
  return _auditSection("Outcome", meta.icon, `<div class="audit-outcome"><span class="audit-badge badge-outcome outcome-${escapeHtml(outcome)}">${escapeHtml(outcome)}</span></div>${replyHtml}`);
}

function _auditFileRow(footprint, bucket) {
  const path = footprint.path || "";
  if (!path) return "";
  const edits = Number(footprint.edit_count) || 0;
  const writes = Number(footprint.write_count) || 0;
  const conf = footprint.confidence || "medium";
  const counts = [];
  if (writes > 0) counts.push(`<span class="audit-file-count">w:${writes}</span>`);
  if (edits > 0) counts.push(`<span class="audit-file-count">e:${edits}</span>`);
  const countsHtml = counts.length ? `<span class="audit-file-counts">${counts.join("")}</span>` : "";
  return `<div class="audit-row audit-file-row" data-file-path="${escapeHtml(path)}" data-file-bucket="${escapeHtml(bucket)}" data-confidence="${escapeHtml(conf)}"><span class="audit-file-path" title="${escapeHtml(path)}">${escapeHtml(path)}</span>${countsHtml}<span class="audit-file-confidence audit-confidence-${escapeHtml(conf)}">${escapeHtml(conf)}</span></div>`;
}

function _auditSectionDeliverables(audit) {
  const ft = audit.files_touched || {};
  const local = Array.isArray(ft.local) ? ft.local.slice(0, AUDIT_FILE_ROW_LIMIT) : [];
  const remote = Array.isArray(ft.remote) ? ft.remote.slice(0, AUDIT_FILE_ROW_LIMIT) : [];
  const inferred = Array.isArray(ft.inferred) ? ft.inferred.slice(0, AUDIT_FILE_ROW_LIMIT) : [];
  if (!local.length && !remote.length && !inferred.length) {
    return _auditSection("Deliverables", "\u{1F4C2}", `<span class="audit-muted muted">No files touched in this session.</span>`);
  }
  const groups = [];
  if (local.length) {
    groups.push(`<div class="audit-group"><div class="audit-group-label">Local <span class="audit-muted">(${local.length})</span></div>${local.map(f => _auditFileRow(f, "local")).join("")}</div>`);
  }
  if (remote.length) {
    groups.push(`<div class="audit-group"><div class="audit-group-label">Remote <span class="audit-muted">(${remote.length})</span></div>${remote.map(f => _auditFileRow(f, "remote")).join("")}</div>`);
  }
  if (inferred.length) {
    groups.push(`<div class="audit-group"><div class="audit-group-label">Inferred <span class="audit-muted">(${inferred.length})</span></div>${inferred.map(f => _auditFileRow(f, "inferred")).join("")}</div>`);
  }
  return _auditSection("Deliverables", "\u{1F4C2}", groups.join(""));
}

function _auditSectionCommandIntents(audit) {
  const intents = audit.command_intents || {};
  const entries = Object.entries(intents).filter(([, n]) => Number(n) > 0);
  if (!entries.length) return _auditSection("Command intents", "\u{1F6E0}", `<span class="audit-muted muted">No shell commands classified.</span>`);
  const total = entries.reduce((sum, [, n]) => sum + (Number(n) || 0), 0) || 1;
  const sorted = entries.sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0));
  const rows = sorted.map(([key, count]) => {
    const upper = String(key || "UNKNOWN").toUpperCase();
    const meta = COMMAND_INTENT_META[upper] || COMMAND_INTENT_META.UNKNOWN;
    const pct = Math.round((Number(count) || 0) / total * 100);
    return `<div class="audit-row audit-intent-row" title="${escapeHtml(meta.label)}: ${Number(count) || 0} command(s)">
      <span class="audit-badge ${escapeHtml(meta.cls)}">${meta.icon} ${escapeHtml(meta.label)}</span>
      <span class="audit-bar"><span class="audit-bar-fill" style="width:${pct}%"></span></span>
      <span class="audit-intent-count">${Number(count) || 0}</span>
    </div>`;
  }).join("");
  return _auditSection("Command intents", "\u{1F6E0}", `<div class="audit-intents">${rows}</div>`);
}

function _auditSectionFriction(audit) {
  const score = Number(audit.friction_score) || 0;
  const errs = audit.errors || {};
  const samples = Array.isArray(errs.samples) ? errs.samples.slice(0, AUDIT_ERROR_SAMPLE_LIMIT) : [];
  const errCount = Number(errs.count) || samples.length;
  const errorEvidence = (audit.evidence || []).filter(ev => ev?.type === "error").slice(0, AUDIT_ERROR_SAMPLE_LIMIT);
  const head = `<div class="audit-friction-head"><span class="audit-badge ${score > 0 ? "badge-friction" : "badge-outcome"}">\u26A0\uFE0F Friction ${score}</span>${errCount > 0 ? `<span class="audit-muted">${errCount} error(s)</span>` : ""}</div>`;
  if (!samples.length) {
    return _auditSection("Friction", "\u26A0\uFE0F", `${head}<span class="audit-muted muted">No errors recorded.</span>`);
  }
  const rows = samples.map((sample, idx) => {
    const ev = errorEvidence[idx];
    const evAttr = ev?.id ? ` data-evidence-id="${escapeHtml(ev.id)}"` : "";
    const preview = String(sample || "").slice(0, 200);
    return `<div class="audit-row audit-error-row"${evAttr}><span class="audit-error-text">${escapeHtml(preview)}</span></div>`;
  }).join("");
  return _auditSection("Friction", "\u26A0\uFE0F", `${head}${rows}`);
}

function _auditSectionValue(audit) {
  const score = Number(audit.value_score) || 0;
  const tier = score >= 70 ? "high" : score >= 30 ? "medium" : "low";
  const interpretation = score >= 70 ? "Strong signal: meaningful work shipped."
    : score >= 30 ? "Mixed signal: some progress, but limited payoff."
    : "Low signal: little demonstrable value captured.";
  return _auditSection("Value", "\u{1F48E}", `<div class="audit-value"><span class="audit-badge badge-value">\u25C6 ${score}</span><span class="audit-value-tier audit-value-${tier}">${escapeHtml(tier)}</span></div><div class="audit-value-note muted">${escapeHtml(interpretation)}</div>`);
}

async function fetchAuditPanel(sessionId) {
  if (!auditPanelEl) return;
  const seq = (auditFetchSeq += 1);
  auditCollapsed = false;
  auditPanelEl.hidden = false;
  if (auditToggleEl) {
    auditToggleEl.textContent = "📊 Hide audit";
    auditToggleEl.setAttribute("aria-expanded", "true");
  }
  auditPanelEl.innerHTML = `<div class="audit-loading muted">Loading audit…</div>`;
  try {
    const res = await fetch(`${apiBase()}/session/${encodeURIComponent(sessionId)}/audit`);
    if (seq !== auditFetchSeq) return;
    if (res.status === 404) {
      currentAudit = null;
      renderAuditPanel(null);
      if (auditActionsEl) auditActionsEl.style.display = "none";
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (seq !== auditFetchSeq) return;
    currentAudit = data.audit || null;
    renderAuditPanel(currentAudit);
    if (auditActionsEl) auditActionsEl.style.display = currentAudit ? "flex" : "none";
  } catch (err) {
    if (seq !== auditFetchSeq) return;
    currentAudit = null;
    auditPanelEl.innerHTML = `<div class="audit-error">Audit load failed: ${escapeHtml(err?.message || String(err))}</div>`;
    if (auditActionsEl) auditActionsEl.style.display = "none";
  }
}

function toggleAuditPanel() {
  if (!auditPanelEl) return;
  auditCollapsed = !auditCollapsed;
  auditPanelEl.hidden = auditCollapsed;
  if (auditToggleEl) {
    auditToggleEl.textContent = auditCollapsed ? "📊 Show audit" : "📊 Hide audit";
    auditToggleEl.setAttribute("aria-expanded", auditCollapsed ? "false" : "true");
  }
}

function findEvidenceById(evidenceId) {
  if (!evidenceId || !currentAudit?.evidence) return null;
  return currentAudit.evidence.find(ev => ev?.id === evidenceId) || null;
}

function findMessageElByIndex(messageIndex) {
  if (!Number.isInteger(messageIndex)) return null;
  return messagesEl.querySelector(`.msg[data-message-index="${messageIndex}"]`) || null;
}

async function ensureMessageLoaded(messageIndex) {
  if (findMessageElByIndex(messageIndex)) return true;
  if (!currentSession || !Number.isInteger(messageIndex)) return false;
  const offset = Math.max(0, messageIndex - 1);
  const limit = Math.max(MESSAGE_RENDER_PAGE_SIZE, messageIndex - offset + 40);
  try {
    await loadMessageWindow({ offset, limit, replace: true, scrollToBottom: false });
    return !!findMessageElByIndex(messageIndex);
  } catch (err) {
    return false;
  }
}

async function scrollToMessage(messageIndex) {
  if (!Number.isInteger(messageIndex)) return false;
  if (!(await ensureMessageLoaded(messageIndex))) return false;
  const el = findMessageElByIndex(messageIndex);
  if (!el) return false;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("audit-flash");
  setTimeout(() => el.classList.remove("audit-flash"), 1600);
  return true;
}

function filterSessionsByFilePath(filePath) {
  const path = String(filePath || "").trim();
  const params = new URLSearchParams(window.location.search);
  if (path) {
    params.set("file", path);
  } else {
    params.delete("file");
  }
  const newSearch = params.toString();
  const newUrl = newSearch ? `${window.location.pathname}?${newSearch}` : window.location.pathname;
  window.history.replaceState({}, "", newUrl);
  currentFilePathFilter = path;
  updateFilePathFilterBanner();
  reloadList();
}

function updateFilePathFilterBanner() {
  const banner = document.getElementById("fileFilterBanner");
  if (!banner) return;
  if (currentFilePathFilter) {
    banner.hidden = false;
    const label = banner.querySelector("[data-file-filter-label]");
    if (label) label.textContent = currentFilePathFilter;
  } else {
    banner.hidden = true;
  }
}

function clearFilePathFilter() {
  if (!currentFilePathFilter) return;
  filterSessionsByFilePath("");
}

function loadFilePathFilterFromUrl() {
  const params = new URLSearchParams(window.location.search);
  currentFilePathFilter = (params.get("file") || "").trim();
  updateFilePathFilterBanner();
}

function setResultsHeader() {
  const showingSessions = !(browseMode === "projects" && !currentProject);
  const showingProjectActions = browseMode === "projects" && !!currentProject;
  const allowMutations = !sourceIsReadOnly();
  if (sessionSortWrapEl) {
    sessionSortWrapEl.style.display = showingSessions ? "flex" : "none";
  }
  backToProjectsBtn.style.display = showingProjectActions ? "inline-block" : "none";
  if (deleteProjectSessionsBtn) {
    deleteProjectSessionsBtn.style.display = showingProjectActions && allowMutations ? "inline-block" : "none";
  }
  if (cleanupWeakSessionsBtn) {
    cleanupWeakSessionsBtn.style.display = allowMutations ? "inline-block" : "none";
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
  messagesEl.scrollTop = 0;
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

async function refreshSessionSearch({ resetRenderCount = true } = {}) {
  const term = sessionSearchInput.value.trim();
  const fetchSeq = (sessionSearchFetchSeq += 1);

  if (!term || !currentSession) {
    currentSessionSearch = createEmptySessionSearchState();
    if (resetRenderCount) resetMessageRenderCount();
    currentMessages = currentBrowseMessages;
    renderMessages(currentMessages);
    return;
  }

  if (resetRenderCount) resetMessageRenderCount();
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
    const params = new URLSearchParams({
      q: term,
      limit: String(getSafeMessageRenderCount()),
    });
    const res = await fetch(`${apiBase()}/session/${encodeURIComponent(currentSession.id)}/messages/search?${params.toString()}`);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    if (fetchSeq !== sessionSearchFetchSeq) return;

    const matches = new Map();
    for (const match of data.matches || []) {
      matches.set(match.message_index, match);
    }
    currentMessages = [];

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
  const msg = currentMessages.find((item) => item?.message_index === index)
    || currentBrowseMessages.find((item) => item?.message_index === index);
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
  if (currentFilePathFilter) params.set("file", currentFilePathFilter);
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
  currentMessagesLoadingEarlier = false;
  expandedMessageIndexes = new Set();
  const expandToolsParam = new URLSearchParams(window.location.search).get("expand_tools");
  toolsCollapsedByDefault = expandToolsParam === "1" ? false : true;
  expandedToolIndexes = new Set();
  collapsedToolIndexes = new Set();
  fullToolOutputIndexes = new Set();
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
    currentBrowseMessages = [];
    currentMessages = [];
    currentMessageTotal = Number.isFinite(currentSession?.message_total)
      ? currentSession.message_total
      : (Number.isFinite(currentSession?.message_count) ? currentSession.message_count : 0);
    currentMessageOffset = Math.max(0, currentMessageTotal - MESSAGE_RENDER_PAGE_SIZE);
    expandedMessageIndexes = new Set();
    renderSessionHeader(currentSession);
    fetchAuditPanel(currentSession.id);
    await loadMessageWindow({
      offset: currentMessageOffset,
      limit: MESSAGE_RENDER_PAGE_SIZE,
      replace: true,
      scrollToBottom: true,
      seq,
    });
  } catch (err) {
    if (seq !== sessionFetchSeq) return;
    renderStatusMessage(`Failed to load session (${err?.message || err})`, { kind: "error" });
  }
}

function normalizeMessageWindow(messages) {
  return (messages || []).map((msg) => ({
    ...msg,
    preview_text: msg?.is_truncated ? (msg.text || "") : null,
    full_text_loaded: !msg?.is_truncated,
  }));
}

async function loadMessageWindow({ offset, limit, replace = false, prepend = false, scrollToBottom = false, seq = sessionFetchSeq } = {}) {
  if (!currentSession) return;
  const params = new URLSearchParams({
    offset: String(Math.max(0, Number(offset) || 0)),
    limit: String(Math.max(1, Number(limit) || MESSAGE_RENDER_PAGE_SIZE)),
  });
  const res = await fetch(`${apiBase()}/session/${encodeURIComponent(currentSession.id)}/messages?${params.toString()}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (seq !== sessionFetchSeq) return;
  const messages = normalizeMessageWindow(data.messages || []);
  currentMessageOffset = Number.isFinite(data.offset) ? data.offset : Number(params.get("offset"));
  currentMessageTotal = Number.isFinite(data.total) ? data.total : currentMessageTotal;
  if (prepend) {
    currentBrowseMessages = messages.concat(currentBrowseMessages);
  } else if (replace) {
    currentBrowseMessages = messages;
  } else {
    currentBrowseMessages = messages;
  }
  currentMessages = currentBrowseMessages;
  renderMessages(currentMessages, { scrollToBottom });
}

async function loadEarlierMessages() {
  if (!currentSession || currentMessagesLoadingEarlier || currentMessageOffset <= 0) return;
  const nextOffset = Math.max(0, currentMessageOffset - MESSAGE_RENDER_PAGE_SIZE);
  const nextLimit = currentMessageOffset - nextOffset;
  currentMessagesLoadingEarlier = true;
  try {
    await loadMessageWindow({
      offset: nextOffset,
      limit: nextLimit,
      prepend: true,
      scrollToBottom: false,
    });
  } catch (err) {
    alert(`Failed to load earlier messages (${err?.message || err}).`);
  } finally {
    currentMessagesLoadingEarlier = false;
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
  resetMessageRenderCount();
  renderMessages(currentMessages);
});

if (clearRenderCacheBtn) {
  clearRenderCacheBtn.addEventListener("click", () => {
    clearMarkdownRenderCache();
    renderMessages(currentMessages);
  });
}

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

if (auditToggleEl) {
  auditToggleEl.addEventListener("click", () => {
    toggleAuditPanel();
  });
}

if (expandAllToolsBtn) {
  expandAllToolsBtn.addEventListener("click", () => {
    expandAllToolMessages();
    renderMessages(currentMessages);
  });
}
if (collapseAllToolsBtn) {
  collapseAllToolsBtn.addEventListener("click", () => {
    collapseAllToolMessages();
    renderMessages(currentMessages);
  });
}

if (toolTimelineEl) {
  toolTimelineEl.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const dot = target ? target.closest("[data-message-index]") : null;
    if (!dot) return;
    const index = Number(dot.dataset.messageIndex);
    if (Number.isInteger(index)) scrollToMessage(index);
  });
}

const clearFileFilterBtn = document.getElementById("clearFileFilter");
if (clearFileFilterBtn) {
  clearFileFilterBtn.addEventListener("click", () => {
    clearFilePathFilter();
  });
}

if (auditPanelEl) {
  auditPanelEl.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const expandBtn = target.closest("[data-audit-expand]");
    if (expandBtn) {
      const wrap = expandBtn.closest(".audit-truncated");
      if (!wrap) return;
      const preview = wrap.querySelector(".audit-text-preview");
      const full = wrap.querySelector(".audit-text-full");
      const expanded = full && !full.hidden;
      if (preview && full) {
        preview.hidden = expanded;
        full.hidden = !expanded;
        expandBtn.textContent = expanded ? "…" : "⤬";
        expandBtn.setAttribute("aria-expanded", expanded ? "false" : "true");
      }
      return;
    }
    const fileRow = target.closest("[data-file-path]");
    if (fileRow) {
      filterSessionsByFilePath(fileRow.dataset.filePath || "");
      return;
    }
    const evidenceRow = target.closest("[data-evidence-id]");
    if (evidenceRow) {
      const ev = findEvidenceById(evidenceRow.dataset.evidenceId || "");
      if (ev && Number.isInteger(ev.message_index)) {
        await scrollToMessage(ev.message_index);
      }
    }
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
  const loadMore = target ? target.closest("[data-load-more-messages]") : null;
  if (loadMore) {
    await loadEarlierMessages();
    return;
  }
  const windowAction = target ? target.closest("[data-message-window-action]") : null;
  if (windowAction) {
    if (sessionSearchInput.value.trim()) {
      currentSearchRenderLimit += MESSAGE_RENDER_PAGE_SIZE;
      refreshSessionSearch({ resetRenderCount: false });
    } else {
      await loadEarlierMessages();
    }
    return;
  }
  const toolOutputToggle = target ? target.closest("[data-tool-output-toggle]") : null;
  if (toolOutputToggle) {
    const index = Number(toolOutputToggle.dataset.toolOutputToggle);
    if (Number.isInteger(index)) {
      fullToolOutputIndexes.add(index);
      renderMessages(currentMessages);
    }
    return;
  }
  const toolToggle = target ? target.closest("[data-tool-toggle]") : null;
  if (toolToggle) {
    const index = Number(toolToggle.dataset.toolToggle);
    if (Number.isInteger(index)) {
      toggleToolMessage(index);
      renderMessages(currentMessages);
    }
    return;
  }
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

async function handlePinSessionClick() {
  if (!currentSession) return;
  if (pinSessionInFlight || sourceIsReadOnly()) return;
  const newPinned = !currentSession.pinned;
  const base = apiBase();
  pinSessionInFlight = true;
  renderSessionHeader(currentSession);
  try {
    const res = await fetch(`${base}/session/${encodeURIComponent(currentSession.id)}/pin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned: newPinned }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    currentSession.pinned = newPinned ? 1 : 0;
    renderSessionHeader(currentSession);
    await reloadList();
  } catch (err) {
    alert(`Pin session failed: ${err?.message || err}`);
  } finally {
    pinSessionInFlight = false;
    if (currentSession) renderSessionHeader(currentSession);
  }
}

pinSessionBtn.addEventListener("click", handlePinSessionClick);

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
    resetMessageRenderCount();
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
  loadFilePathFilterFromUrl();
  reloadList();
}

bootstrapApp();

if (globalThis.__CCHV_TEST__) {
  globalThis.__testApi = {
    getMessageHtml,
    buildMessageElement,
    buildResumeCommands,
    getResumeCommandLabels,
    flushLazyMessageBodies() {
      const observers = (globalThis.IntersectionObserver?.instances || []).slice();
      observers.forEach((observer) => {
        const entries = [...observer.targets].map((target) => ({ target, isIntersecting: true }));
        if (entries.length) {
          observer.callback(entries);
        }
      });
    },
    flushPendingLazyMessageBodiesForRoot,
    setCurrentSession(value) { currentSession = value; },
    getCurrentSession() { return currentSession; },
    setCurrentSystem(value) { currentSystem = value; },
    setCurrentSource(value) { currentSource = value; },
    setCurrentMessageWindow({ offset = 0, total = 0 } = {}) {
      currentMessageOffset = offset;
      currentMessageTotal = total;
    },
    setCurrentSessionSearchData(query, entries) {
      currentSessionSearch = {
        query,
        matches: new Map(entries || []),
        matchCount: Array.isArray(entries) ? entries.length : 0,
        messageMatchCount: Array.isArray(entries) ? entries.length : 0,
        loading: false,
        error: "",
      };
    },
    setExpandedMessageIndexes(values) {
      expandedMessageIndexes = new Set(values || []);
    },
    setRenderMarkdown(value) { renderMarkdown = value; },
    getStorageKeyInfo() {
      return {
        index: MARKDOWN_CACHE_INDEX_KEY,
        prefix: MARKDOWN_CACHE_ENTRY_PREFIX,
        rendererVersion: MARKDOWN_RENDER_VERSION,
      };
    },
    clearMarkdownRenderCache,
    buildMessageRenderPlan,
    renderMessages,
    getMessagesElement() { return messagesEl; },
    handlePinSessionClick,
    renderAuditPanel,
    auditSectionIntent: _auditSectionIntent,
    auditSectionOutcome: _auditSectionOutcome,
    auditSectionDeliverables: _auditSectionDeliverables,
    auditSectionCommandIntents: _auditSectionCommandIntents,
    auditSectionFriction: _auditSectionFriction,
    auditSectionValue: _auditSectionValue,
    auditExpandable: _auditExpandable,
    auditFileRow: _auditFileRow,
    findEvidenceById,
    setCurrentAudit(value) { currentAudit = value; },
    getCurrentAudit() { return currentAudit; },
    setCurrentFilePathFilter(value) { currentFilePathFilter = String(value || ""); },
    getCurrentFilePathFilter() { return currentFilePathFilter; },
    getAuditPanelElement() { return auditPanelEl; },
    renderToolSummaryHtml,
    renderToolStatusHtml,
    isToolMessage,
    isToolMessageCollapsed,
    toggleToolMessage,
    expandToolMessage,
    collapseToolMessage,
    expandAllToolMessages,
    collapseAllToolMessages,
    setToolsCollapsedByDefault(value) { toolsCollapsedByDefault = !!value; },
    getToolsCollapsedByDefault() { return toolsCollapsedByDefault; },
    setExpandedToolIndexes(values) { expandedToolIndexes = new Set(values || []); },
    getExpandedToolIndexes() { return expandedToolIndexes; },
    setCollapsedToolIndexes(values) { collapsedToolIndexes = new Set(values || []); },
    getCollapsedToolIndexes() { return collapsedToolIndexes; },
    setFullToolOutputIndexes(values) { fullToolOutputIndexes = new Set(values || []); },
    getFullToolOutputIndexes() { return fullToolOutputIndexes; },
    getToolActionsElement() { return toolActionsEl; },
    getToolOutputPreviewLines() { return TOOL_OUTPUT_PREVIEW_LINES; },
    renderToolMessageBody,
    renderToolTimeline,
    updateToolTimelineCurrent,
    getToolTimelineElement() { return toolTimelineEl; },
  };
}
