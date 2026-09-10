const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

// loadApp() replaces globalThis.process with a stub; keep the real one for
// exit-code signalling.
const nodeProcess = process;


class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...tokens) { tokens.forEach((t) => this.values.add(t)); }
  remove(...tokens) { tokens.forEach((t) => this.values.delete(t)); }
  toggle(token, force) {
    if (force === true) { this.values.add(token); return true; }
    if (force === false) { this.values.delete(token); return false; }
    if (this.values.has(token)) { this.values.delete(token); return false; }
    this.values.add(token); return true;
  }
  contains(token) { return this.values.has(token); }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.eventListeners = new Map();
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.checked = true;
    this.parentNode = null;
    this.ownerDocument = null;
    this._rect = { top: 0, bottom: 0, width: 960, height: 640 };
  }
  appendChild(child) {
    if (!child) return child;
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      this.dataset[key] = String(value);
    }
  }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  removeAttribute(name) { this.attributes.delete(name); }
  addEventListener(type, handler) { this.eventListeners.set(type, handler); }
  removeEventListener(type) { this.eventListeners.delete(type); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  scrollIntoView() {}
  scrollTo(value) {
    if (typeof value === "number") { this.scrollTop = value; return; }
    if (value && typeof value === "object" && Number.isFinite(value.top)) { this.scrollTop = value.top; }
  }
  getBoundingClientRect() { return this._rect; }
}

function createStorage() {
  const store = new Map();
  return {
    getItem(key) { return store.has(key) ? store.get(key) : null; },
    setItem(key, value) { store.set(key, String(value)); },
    removeItem(key) { store.delete(key); },
    clear() { store.clear(); },
  };
}

function createDocument() {
  const elements = new Map();
  const documentElement = new FakeElement("html");
  documentElement.dataset = {};
  const body = new FakeElement("body");
  const fakeWindow = {
    addEventListener() {},
    removeEventListener() {},
    requestAnimationFrame(callback) { queueMicrotask(callback); return 1; },
    cancelAnimationFrame() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    ResizeObserver: null,
    performance: { now: () => Date.now() },
    location: { search: "", pathname: "/", origin: "http://localhost" },
    history: { replaceState() {} },
  };
  documentElement.ownerDocument = { defaultView: fakeWindow };
  body.ownerDocument = { defaultView: fakeWindow };
  const roleInputs = ["user", "assistant", "system", "developer", "tool", "other"].map((role) => {
    const input = new FakeElement("input");
    input.dataset.role = role;
    input.checked = true;
    input.ownerDocument = { defaultView: fakeWindow };
    return input;
  });

  const document = {
    documentElement,
    body,
    defaultView: fakeWindow,
    getElementById(id) {
      if (!elements.has(id)) {
        const el = new FakeElement("div");
        el.ownerDocument = document;
        elements.set(id, el);
      }
      return elements.get(id);
    },
    querySelectorAll(selector) {
      if (selector === ".roles input[type=checkbox]") return roleInputs;
      return [];
    },
    createElement(tagName) {
      const el = new FakeElement(tagName);
      el.ownerDocument = document;
      return el;
    },
    createDocumentFragment() {
      const el = new FakeElement("#fragment");
      el.ownerDocument = document;
      return el;
    },
    createTextNode(text) {
      return { nodeValue: String(text), textContent: String(text), parentNode: null };
    },
    createTreeWalker() { return { nextNode() { return null; } }; },
  };
  fakeWindow.document = document;
  return document;
}

async function loadApp({ fetchImpl } = {}) {
  const repoDir = path.resolve(__dirname, "..");
  const sourcePath = path.join(repoDir, "static", "app.js");
  const localStorage = createStorage();
  const document = createDocument();
  // renderSessionHeader needs a working querySelector on the session header.
  const sessionTitleEl = new FakeElement("div");
  const sessionMetaEl = new FakeElement("div");
  const sessionHeaderEl = document.getElementById("sessionHeader");
  sessionHeaderEl.querySelector = (selector) => {
    if (selector === ".session-title") return sessionTitleEl;
    if (selector === ".session-meta") return sessionMetaEl;
    return null;
  };
  const defaultFetch = async () => ({
    ok: true,
    json: async () => ({ items: [], has_more: false, next_offset: 0, matches: [] }),
  });
  // Node 22 exposes a getter-only navigator; replace it for this DOM fixture.
  Object.defineProperty(globalThis, "navigator", { value: {}, writable: true, configurable: true });
  Object.assign(globalThis, {
    __CCHV_TEST__: true,
    __testApi: undefined,
    document,
    localStorage,
    navigator: { clipboard: { writeText: async () => {} } },
    window: document.defaultView,
    fetch: (...args) => (fetchImpl ? fetchImpl(...args) : defaultFetch()),
    requestAnimationFrame(callback) { queueMicrotask(callback); return 1; },
    cancelAnimationFrame() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    alert() {},
    URLSearchParams,
    Element: FakeElement,
    NodeFilter: { SHOW_TEXT: 4 },
    IntersectionObserver: class { observe() {} unobserve() {} disconnect() {} },
    process: { env: { NODE_ENV: "test" } },
  });

  const href = `${pathToFileURL(sourcePath).href}?test=${Date.now()}-${Math.random()}`;
  await import(href);
  return { api: globalThis.__testApi, localStorage };
}

function flushAsync() {
  return new Promise((resolve) => setImmediate(resolve));
}

// --- Fixtures ---

function sampleUsageData() {
  return {
    totals: { session_count: 4, input: 12000, output: 3400, cached: 800, reasoning: 500, total: 16700 },
    has_usage_data: true,
    by_day: [
      { day: "2026-09-06", session_count: 3, input: 9000, output: 2400, cached: 500, reasoning: 300, total: 12200 },
      { day: "2026-09-05", session_count: 1, input: 3000, output: 1000, cached: 300, reasoning: 200, total: 4500 },
    ],
    by_project: [
      { project: "/home/muqiao/ControlMesh", session_count: 2, input: 7000, output: 2000, cached: 400, reasoning: 300, total: 9700 },
    ],
    top_sessions: [
      { id: "sess-1", title: "Ship the usage panel", cwd: "/ControlMesh", start_ts_ms: 1788600000000, tokens_input: 7000, tokens_output: 2000, tokens_cached: 400, tokens_reasoning: 300, tokens_total: 9700 },
    ],
  };
}

function sampleBriefing() {
  return {
    version: 1,
    date: "2026-09-06",
    source: "codex",
    overview: { session_count: 3, merged_count: 1, project_count: 2, outcomes: { completed: 2, errored: 1 }, friction_total: 6, tokens_total: 15000 },
    highlights: [
      { session_id: "a", title: "Ship the feature", project: "/proj", value_score: 90, outcome_signal: "completed", goal: "Build the thing", next_action: "Deploy it", tokens_total: 12000, merged_count: 1 },
    ],
    blocked: [
      { session_id: "b", title: "Broken build", project: "/proj", outcome_signal: "errored", friction_score: 6, error_sample: "Traceback (boom)" },
    ],
    deliverables: [{ path: "/proj/app.py", write_count: 2, edit_count: 1 }],
  };
}

// --- Tests ---

async function testUsageHtmlEmptyState() {
  const { api } = await loadApp();
  const html = api.buildUsageHtml({ totals: {}, has_usage_data: false, by_day: [], by_project: [], top_sessions: [] });
  assert.match(html, /insight-empty/);
  assert.match(html, /No token usage recorded/);
}

async function testUsageHtmlRendersChipsBarsAndTopSessions() {
  const { api } = await loadApp();
  const html = api.buildUsageHtml(sampleUsageData());
  assert.match(html, /usage-chip-value[^>]*>16,700</);
  assert.match(html, /2026-09-06/);
  assert.match(html, /usage-bar-fill/);
  assert.match(html, /\/home\/muqiao\/ControlMesh/);
  assert.match(html, /data-usage-session="sess-1"/);
  assert.match(html, /Ship the usage panel/);
}

async function testUsagePanelRenderSetsSummaryAndContent() {
  const { api } = await loadApp();
  api.renderUsagePanel(sampleUsageData());
  const content = api.getUsageContentElement();
  assert.match(content.innerHTML, /usage-totals/);
  assert.equal(api.getCurrentUsage().totals.total, 16700);
}

async function testBriefingHtmlEmptyState() {
  const { api } = await loadApp();
  const html = api.buildBriefingHtml({ overview: { session_count: 0 }, date: "2026-09-06" });
  assert.match(html, /No sessions recorded/);
}

async function testBriefingHtmlRendersSections() {
  const { api } = await loadApp();
  const html = api.buildBriefingHtml(sampleBriefing());
  assert.match(html, /Highlights/);
  assert.match(html, /Ship the feature/);
  assert.match(html, /Deploy it/);
  assert.match(html, /Blocked/);
  assert.match(html, /Traceback \(boom\)/);
  assert.match(html, /Deliverables/);
  assert.match(html, /data-file-path="\/proj\/app\.py"/);
  assert.match(html, /outcome-errored/);
}

async function testPlanListHtmlEmptyAndPopulated() {
  const { api } = await loadApp();
  assert.match(api.buildPlanListHtml([]), /No planning files/);
  const html = api.buildPlanListHtml([
    {
      name: "task_plan.md",
      rel_path: "plans/x/task_plan.md",
      mtime_ms: 1788600000000,
      size: 120,
      sections: { status: "完成：usage 已交付。", next_step: "Wait for review." },
    },
  ]);
  assert.match(html, /task_plan\.md/);
  assert.match(html, /plans\/x\/task_plan\.md/);
  assert.match(html, /plan-section-key">status</);
  assert.match(html, /Wait for review\./);
}

async function testHandoffHtmlDocRendersMarkdownAndTheme() {
  const { api } = await loadApp();
  const text = "[HANDOFF]\n\nremaining:\n- Finish the release\n\nverified:\n- npm test -> pass";
  const html = api.buildHandoffHtmlDoc(text, "feishu");
  assert.match(html, /<!doctype html>/);
  assert.match(html, /Finish the release/);
  assert.match(html, /#3370ff/);
  const plain = api.buildHandoffHtmlDoc(text, "plain");
  assert.doesNotMatch(plain, /#3370ff/);
}

async function testSetHandoffThemeSwitchesClassAndPersists() {
  const { api, localStorage } = await loadApp();
  const next = api.setHandoffTheme("card", { persist: true });
  assert.equal(next, "card");
  assert.equal(localStorage.getItem("historyViewer.ui.handoffTheme"), "card");
  const body = api.getHandoffPreviewBodyElement();
  assert.equal(body.classList.contains("handoff-theme-card"), true);
  assert.equal(body.classList.contains("handoff-theme-plain"), false);
  const coerced = api.setHandoffTheme("unknown-theme", { persist: false });
  assert.equal(coerced, "plain");
}

async function testRenderHandoffPreviewUsesCurrentHandoff() {
  const { api } = await loadApp();
  api.setCurrentHandoff({ compact: "compact text", standard: "standard text\n\n- item one" });
  api.renderHandoffPreview();
  const body = api.getHandoffPreviewBodyElement();
  assert.match(body.innerHTML, /standard text/);
  assert.match(body.innerHTML, /<li>item one<\/li>/);
}

async function testHandoffFilenameSanitizesSessionId() {
  const { api } = await loadApp();
  api.setCurrentSession({ id: "weird/id with spaces" });
  const name = api.handoffFilename("md");
  assert.match(name, /^handoff-weird-id-wit\.md$/);
}

// --- Review-fix regression tests ---

const MINIMAL_AUDIT = {
  session_id: "sess-b",
  first_user_prompt: "Do the thing.",
  last_assistant_reply: "Done.",
  outcome_signal: "completed",
  value_score: 40,
  friction_score: 0,
  files_touched: {},
  command_intents: {},
  errors: { count: 0, samples: [] },
  evidence: [],
};

async function testAuditFetchRefreshesVisibleHandoffPreview() {
  // Review fix: switching sessions must not leave session A's handoff under
  // session B's transcript.
  const { api } = await loadApp({
    fetchImpl: async (url) => {
      if (String(url).endsWith("/audit")) {
        return {
          ok: true,
          json: async () => ({
            audit: MINIMAL_AUDIT,
            ai_audit: null,
            handoff: { compact: "HANDOFF_NEW_B compact", standard: "HANDOFF_NEW_B standard" },
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    },
  });
  api.setCurrentHandoff({ compact: "HANDOFF_OLD_A compact", standard: "HANDOFF_OLD_A standard" });
  api.toggleHandoffPreview();
  assert.equal(api.isHandoffPreviewVisible(), true);
  assert.match(api.getHandoffPreviewBodyElement().innerHTML, /HANDOFF_OLD_A/);

  await api.fetchAuditPanel("sess-b");
  assert.match(api.getHandoffPreviewBodyElement().innerHTML, /HANDOFF_NEW_B/);
  assert.doesNotMatch(api.getHandoffPreviewBodyElement().innerHTML, /HANDOFF_OLD_A/);
}

async function testSessionChangeReloadsVisiblePlansPanel() {
  // Review fix: an open Plans panel must follow the newly selected session.
  let plansForSession = "PLAN_OF_SESSION_A";
  const { api } = await loadApp({
    fetchImpl: async (url) => {
      if (String(url).endsWith("/plans")) {
        const name = plansForSession;
        return { ok: true, json: async () => ({ cwd: "/proj", items: [
          { name, rel_path: `plans/x/${name}.md`, mtime_ms: 1788600000000, size: 10, sections: { status: name } },
        ] }) };
      }
      return { ok: true, json: async () => ({}) };
    },
  });
  api.setCurrentSession({ id: "sess-a" });
  api.togglePlanPanel();
  await api.fetchPlanPanel();
  assert.match(api.getPlanContentElement().innerHTML, /PLAN_OF_SESSION_A/);

  plansForSession = "PLAN_OF_SESSION_B";
  api.setCurrentSession({ id: "sess-b" });
  api.onSessionChanged();
  await flushAsync();
  assert.match(api.getPlanContentElement().innerHTML, /PLAN_OF_SESSION_B/);
  assert.doesNotMatch(api.getPlanContentElement().innerHTML, /PLAN_OF_SESSION_A/);
}

async function testNarrativeClearedWhenBriefingMovesToAnotherDate() {
  // Review fix: a narrative generated for one day must not stay visible when
  // the briefing reloads for another day.
  const { api } = await loadApp({
    fetchImpl: async (url) => {
      if (String(url).includes("/briefing")) {
        return {
          ok: true,
          json: async () => ({
            briefing: { date: "2026-09-06", overview: { session_count: 0 } },
            markdown: "",
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    },
  });
  api.setCurrentNarrative({ date: "2026-09-05" });
  const box = api.getBriefingNarrativeBoxElement();
  box.hidden = false;
  box.innerHTML = "<div>OLD_NARRATIVE_FOR_SEPT_5</div>";

  await api.fetchBriefingPanel();
  assert.equal(box.hidden, true);
  assert.equal(box.innerHTML, "");
  assert.equal(api.getCurrentNarrative(), null);
}

async function testNarrativeDroppedWhenDateMovedMidFlight() {
  // Review fix: a slow narrative POST whose date no longer matches the view
  // must be dropped instead of overwriting the visible briefing.
  const { api } = await loadApp({
    fetchImpl: async (url) => {
      if (String(url).includes("/briefing") && typeof url === "string") {
        return {
          ok: true,
          json: async () => ({
            briefing: { date: "2026-09-05", overview: { session_count: 3 } },
            markdown: "",
            narrative: { narrative: "SLOW_STALE_NARRATIVE", suggestions: [], source: "heuristic" },
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    },
  });
  const dateInput = globalThis.document.getElementById("briefingDate");
  assert.ok(dateInput, "briefing date input must be reachable");
  dateInput.value = "2026-09-05";

  const generation = api.generateBriefingNarrative();
  // User switches the date while the POST is in flight.
  dateInput.value = "2026-09-06";
  await generation;
  await flushAsync();

  const box = api.getBriefingNarrativeBoxElement();
  assert.doesNotMatch(String(box.innerHTML), /SLOW_STALE_NARRATIVE/);
  assert.equal(api.getCurrentNarrative(), null);
}

function documentDateInput(api) {
  // The shim caches elements by id; reach the briefing date input directly.
  return globalThis.document.getElementById("briefingDate");
}

async function testBriefingHtmlShowsTruncationNotice() {
  // M1/A4: the safety-cap flag must reach the UI, never stay silent.
  const { api } = await loadApp();
  const truncated = sampleBriefing();
  truncated.truncated = true;
  truncated.session_limit = 2000;
  truncated.overview.session_count = 2000;
  const html = api.buildBriefingHtml(truncated);
  assert.match(html, /briefing-truncated-note/);
  assert.match(html, /safety cap/);
  assert.match(html, /partial/);
  const clean = api.buildBriefingHtml(sampleBriefing());
  assert.doesNotMatch(clean, /briefing-truncated-note/);
}

async function testAudit404ClearsHandoffPreview() {
  // M1/A2: a session without audit data must not keep the previous
  // session's handoff visible.
  const { api } = await loadApp({
    fetchImpl: async (url) => {
      if (String(url).endsWith("/audit")) {
        return { ok: false, status: 404, json: async () => ({ error: "not_found" }) };
      }
      return { ok: true, json: async () => ({}) };
    },
  });
  api.setCurrentHandoff({ compact: "STALE_A compact", standard: "STALE_A standard" });
  api.toggleHandoffPreview();
  assert.match(api.getHandoffPreviewBodyElement().innerHTML, /STALE_A/);

  await api.fetchAuditPanel("sess-no-audit");
  assert.match(api.getHandoffPreviewBodyElement().innerHTML, /No handoff available/);
  assert.doesNotMatch(api.getHandoffPreviewBodyElement().innerHTML, /STALE_A/);
}

async function testOutOfOrderAuditResponseKeepsLatestSession() {
  // M1/A2: a slow audit response for session A must not overwrite session
  // B's preview that already rendered.
  let resolveFirstAudit;
  let auditCallCount = 0;
  const { api } = await loadApp({
    fetchImpl: async (url) => {
      if (String(url).endsWith("/audit")) {
        auditCallCount += 1;
        if (auditCallCount === 1) {
          return new Promise((resolve) => { resolveFirstAudit = resolve; }).then(() => ({
            ok: true,
            json: async () => ({
              audit: MINIMAL_AUDIT,
              ai_audit: null,
              handoff: { compact: "LATE_A compact", standard: "LATE_A standard" },
            }),
          }));
        }
        return {
          ok: true,
          json: async () => ({
            audit: MINIMAL_AUDIT,
            ai_audit: null,
            handoff: { compact: "FAST_B compact", standard: "FAST_B standard" },
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    },
  });
  api.setCurrentHandoff({ compact: "INITIAL compact", standard: "INITIAL standard" });
  api.toggleHandoffPreview();

  const first = api.fetchAuditPanel("sess-a");
  const second = api.fetchAuditPanel("sess-b");
  await second;
  assert.match(api.getHandoffPreviewBodyElement().innerHTML, /FAST_B/);
  resolveFirstAudit({ ok: true, json: async () => ({}) });
  await first;
  await flushAsync();
  assert.match(api.getHandoffPreviewBodyElement().innerHTML, /FAST_B/, "late response for A must be dropped");
  assert.doesNotMatch(api.getHandoffPreviewBodyElement().innerHTML, /LATE_A/);
}

async function main() {
  const tests = [
    testUsageHtmlEmptyState,
    testUsageHtmlRendersChipsBarsAndTopSessions,
    testUsagePanelRenderSetsSummaryAndContent,
    testBriefingHtmlEmptyState,
    testBriefingHtmlRendersSections,
    testBriefingHtmlShowsTruncationNotice,
    testPlanListHtmlEmptyAndPopulated,
    testHandoffHtmlDocRendersMarkdownAndTheme,
    testSetHandoffThemeSwitchesClassAndPersists,
    testRenderHandoffPreviewUsesCurrentHandoff,
    testHandoffFilenameSanitizesSessionId,
    testAuditFetchRefreshesVisibleHandoffPreview,
    testAudit404ClearsHandoffPreview,
    testOutOfOrderAuditResponseKeepsLatestSession,
    testSessionChangeReloadsVisiblePlansPanel,
    testNarrativeClearedWhenBriefingMovesToAnotherDate,
    testNarrativeDroppedWhenDateMovedMidFlight,
  ];
  for (const test of tests) {
    await test();
    console.log(`ok - ${test.name}`);
  }
}

main().catch((err) => {
  console.error(err);
  nodeProcess.exitCode = 1;
});
