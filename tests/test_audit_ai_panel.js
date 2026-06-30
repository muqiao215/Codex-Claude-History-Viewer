const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");


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
    this.offsetWidth = 960;
    this.offsetHeight = 640;
    this.clientHeight = 640;
    this.scrollHeight = 640;
    this.scrollTop = 0;
  }
  appendChild(child) {
    if (!child) return child;
    if (child.tagName === "#FRAGMENT") {
      const fragChildren = [...child.children];
      fragChildren.forEach((c) => this.appendChild(c));
      child.children = [];
      return child;
    }
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

async function loadApp() {
  const repoDir = path.resolve(__dirname, "..");
  const sourcePath = path.join(repoDir, "static", "app.js");
  const localStorage = createStorage();
  const document = createDocument();
  Object.assign(globalThis, {
    __CCHV_TEST__: true,
    __testApi: undefined,
    document,
    localStorage,
    navigator: { clipboard: { writeText: async () => {} } },
    window: document.defaultView,
    fetch: async () => ({
      ok: true,
      json: async () => ({ items: [], has_more: false, next_offset: 0, matches: [] }),
    }),
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
  return { api: globalThis.__testApi };
}

// --- Test fixtures ---

function sampleAiAudit({
  source = "heuristic",
  model = null,
  user_intent = "Build a REST API with auth and pagination.",
  checklist = [
    { item: "Create src/api.py", status: "done", evidence_ids: ["sess:file:src/api.py"] },
    { item: "Run TEST suite (4x)", status: "partial", evidence_ids: ["sess:tool:shell:0"] },
    { item: "Fix ImportError", status: "failed", evidence_ids: [] },
  ],
  deliverables = ["src/api.py", "src/auth.py"],
  gaps = ["2 errors encountered", "outcome partially_completed"],
  next_action = "Resolve the ImportError, then re-run tests.",
} = {}) {
  return { source, model, user_intent, checklist, deliverables, gaps, next_action };
}

// --- Tests ---

async function testSectionAiHeuristicSource() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ source: "heuristic" }));
  assert.match(html, /ai-audit-section/, "must wrap in ai-audit-section");
  assert.match(html, /ai-source-heuristic/, "must carry heuristic source badge");
  assert.match(html, /Heuristic Audit/, "heuristic label rendered");
}

async function testSectionAiLlmSource() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ source: "llm", model: "gpt-4o" }));
  assert.match(html, /ai-source-llm/, "must carry llm source badge");
  assert.match(html, /AI Audit · gpt-4o/, "llm label includes model name");
}

async function testSectionAiIntentRendered() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ user_intent: "Do the thing" }));
  assert.match(html, /ai-intent/, "intent container present");
  assert.ok(html.indexOf("Do the thing") >= 0, "intent text rendered");
}

async function testSectionAiChecklistStatusIcons() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit());
  assert.ok(html.indexOf("✓") >= 0, "done icon ✓ rendered");
  assert.ok(html.indexOf("◐") >= 0, "partial icon ◐ rendered");
  assert.ok(html.indexOf("✕") >= 0, "failed icon ✕ rendered");
}

async function testSectionAiChecklistCssClasses() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit());
  assert.match(html, /ai-status-done/, "done status class");
  assert.match(html, /ai-status-partial/, "partial status class");
  assert.match(html, /ai-status-failed/, "failed status class");
}

async function testSectionAiEvidenceChips() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit());
  assert.match(html, /ai-evidence-chip/, "evidence chip class present");
  assert.match(html, /data-evidence-id="sess:file:src\/api\.py"/, "chip carries data-evidence-id");
}

async function testSectionAiEvidenceChipShortLabel() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({
    checklist: [{ item: "Task", status: "done", evidence_ids: ["sess:tool:shell:5"] }],
  }));
  assert.ok(html.indexOf(">5<") >= 0 || html.indexOf(">shell:5<") >= 0, "chip short label is last segment");
}

async function testSectionAiDeliverablesList() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ deliverables: ["src/main.py", "tests/test_main.py"] }));
  assert.match(html, /ai-list/, "deliverables list rendered");
  assert.ok(html.indexOf("src/main.py") >= 0, "first deliverable rendered");
  assert.ok(html.indexOf("tests/test_main.py") >= 0, "second deliverable rendered");
}

async function testSectionAiDeliverablesOmittedWhenEmpty() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ deliverables: [] }));
  const matches = html.match(/ai-subsection-label">Deliverables/g);
  assert.equal(matches, null, "Deliverables subsection absent when empty");
}

async function testSectionAiGapsList() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ gaps: ["Error A", "Error B"] }));
  assert.match(html, /ai-gaps/, "gaps list has ai-gaps class");
  assert.ok(html.indexOf("Error A") >= 0, "first gap rendered");
}

async function testSectionAiGapsOmittedWhenEmpty() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ gaps: [] }));
  const matches = html.match(/ai-gaps/g);
  assert.equal(matches, null, "gaps subsection absent when empty");
}

async function testSectionAiNextAction() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ next_action: "Ship it." }));
  assert.match(html, /ai-next-action/, "next action box present");
  assert.ok(html.indexOf("Ship it.") >= 0, "next action text rendered");
}

async function testSectionAiChecklistOmittedWhenEmpty() {
  const { api } = await loadApp();
  const html = api.auditSectionAi(sampleAiAudit({ checklist: [] }));
  const matches = html.match(/ai-checklist"/g);
  assert.equal(matches, null, "checklist container absent when empty");
}

async function testUpdateButtonsNoAiAuditShowsGenerate() {
  const { api } = await loadApp();
  api.setCurrentAiAudit(null);
  api.setCurrentAudit({ value_score: 50 });
  api.updateAiAuditButtons();
  assert.equal(api.getAuditGenerateBtn().hidden, false, "Generate visible when no ai_audit");
  assert.equal(api.getAuditDeleteBtn().hidden, true, "Delete hidden when no ai_audit");
}

async function testUpdateButtonsWithAiAuditShowsDelete() {
  const { api } = await loadApp();
  api.setCurrentAiAudit(sampleAiAudit());
  api.updateAiAuditButtons();
  assert.equal(api.getAuditGenerateBtn().hidden, true, "Generate hidden when ai_audit exists");
  assert.equal(api.getAuditDeleteBtn().hidden, false, "Delete visible when ai_audit exists");
}

async function testUpdateButtonsLowValueWarns() {
  const { api } = await loadApp();
  api.setCurrentAiAudit(null);
  api.setCurrentAudit({ value_score: 5 });
  api.updateAiAuditButtons();
  assert.match(api.getAuditGenerateBtn().title, /low/i, "title warns when value < 20");
}

async function testUpdateButtonsHighValueNoWarning() {
  const { api } = await loadApp();
  api.setCurrentAiAudit(null);
  api.setCurrentAudit({ value_score: 80 });
  api.updateAiAuditButtons();
  assert.doesNotMatch(api.getAuditGenerateBtn().title, /low/i, "title clean when value >= 20");
}

// --- Runner ---

const tests = [
  testSectionAiHeuristicSource,
  testSectionAiLlmSource,
  testSectionAiIntentRendered,
  testSectionAiChecklistStatusIcons,
  testSectionAiChecklistCssClasses,
  testSectionAiEvidenceChips,
  testSectionAiEvidenceChipShortLabel,
  testSectionAiDeliverablesList,
  testSectionAiDeliverablesOmittedWhenEmpty,
  testSectionAiGapsList,
  testSectionAiGapsOmittedWhenEmpty,
  testSectionAiNextAction,
  testSectionAiChecklistOmittedWhenEmpty,
  testUpdateButtonsNoAiAuditShowsGenerate,
  testUpdateButtonsWithAiAuditShowsDelete,
  testUpdateButtonsLowValueWarns,
  testUpdateButtonsHighValueNoWarning,
];

(async () => {
  let passed = 0;
  let failed = 0;
  for (const test of tests) {
    try {
      await test();
      passed += 1;
    } catch (err) {
      failed += 1;
      console.error(`FAIL ${test.name}: ${err.message}`);
    }
  }
  console.log(`\n${passed}/${tests.length} tests passed (${failed} failed)`);
  if (failed > 0) process.exitCode = 1;
})();
