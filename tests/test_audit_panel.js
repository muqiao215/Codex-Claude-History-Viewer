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

function sampleFileFootprint(path, { edit_count = 0, write_count = 0, confidence = "medium" } = {}) {
  return { path, edit_count, write_count, confidence, remote: false, source: "tool" };
}

function sampleAudit({
  first_user_prompt = "Build a codex history viewer with audit panel.",
  last_assistant_reply = "Done: shipped audit panel with 6 sections and click-to-scroll evidence.",
  outcome_signal = "completed",
  value_score = 85,
  friction_score = 5,
  files_touched = {},
  command_intents = {},
  errors = {},
  evidence = [],
} = {}) {
  return {
    session_id: "test-session-1",
    first_user_prompt,
    last_assistant_reply,
    outcome_signal,
    value_score,
    friction_score,
    files_touched,
    command_intents,
    errors,
    evidence,
  };
}

// --- Tests ---

async function testRenderAuditPanelEmptyWhenAuditIsNull() {
  const { api } = await loadApp();
  api.renderAuditPanel(null);
  const panel = api.getAuditPanelElement();
  assert.match(panel.innerHTML, /audit-empty/, "null audit must render empty state");
  assert.match(panel.innerHTML, /Audit unavailable/, "empty state must explain why");
}

async function testRenderAuditPanelHasAllSixSections() {
  const { api } = await loadApp();
  const audit = sampleAudit({
    files_touched: { local: [sampleFileFootprint("/src/app.py", { write_count: 2, edit_count: 3, confidence: "high" })] },
    command_intents: { TEST: 2, BUILD: 1 },
    errors: { count: 1, samples: ["bash: pytest: command not found"] },
    evidence: [{ id: "test-session-1:error:tool:0", type: "error", message_index: 7 }],
  });
  api.renderAuditPanel(audit);
  const html = api.getAuditPanelElement().innerHTML;
  const requiredSections = ["Intent", "Outcome", "Deliverables", "Command intents", "Friction", "Value"];
  requiredSections.forEach((title) => {
    assert.ok(html.indexOf(title) >= 0, `panel must include ${title} section`);
  });
  assert.match(html, /audit-sections/, "panel body wrapped in sections container");
}

async function testAuditExpandableTruncatesLongText() {
  const { api } = await loadApp();
  const long = "x".repeat(500);
  const html = api.auditExpandable(long, 280, "intent");
  assert.ok(html.indexOf("audit-text-preview") >= 0, "long text must produce preview span");
  assert.ok(html.indexOf("audit-text-full") >= 0, "long text must keep full text in hidden span");
  assert.ok(html.indexOf('data-audit-expand="intent"') >= 0, "expand button must carry kind attr");
}

async function testAuditExpandableShortTextNoExpand() {
  const { api } = await loadApp();
  const short = "short prompt";
  const html = api.auditExpandable(short, 280, "intent");
  assert.ok(html.indexOf("audit-text-preview") < 0, "short text must not produce preview span");
  assert.ok(html.indexOf("audit-text") >= 0, "short text wrapped in audit-text span");
  assert.ok(html.indexOf(short) >= 0, "short text rendered verbatim");
}

async function testAuditExpandableEmpty() {
  const { api } = await loadApp();
  const html = api.auditExpandable("", 280, "intent");
  assert.ok(html.indexOf("audit-muted") >= 0, "empty text shows muted dash");
}

async function testFileRowHasDataAttributes() {
  const { api } = await loadApp();
  const html = api.auditFileRow(sampleFileFootprint("/src/lib.py", { write_count: 1, edit_count: 4, confidence: "high" }), "local");
  assert.ok(html.indexOf('data-file-path="/src/lib.py"') >= 0, "file row carries path attr");
  assert.ok(html.indexOf('data-file-bucket="local"') >= 0, "file row carries bucket attr");
  assert.ok(html.indexOf('data-confidence="high"') >= 0, "file row carries confidence attr");
  assert.ok(html.indexOf("w:1") >= 0, "write count rendered");
  assert.ok(html.indexOf("e:4") >= 0, "edit count rendered");
  assert.ok(html.indexOf("audit-file-row") >= 0, "row carries clickable class");
}

async function testDeliverablesEmptyState() {
  const { api } = await loadApp();
  const html = api.auditSectionDeliverables(sampleAudit({ files_touched: {} }));
  assert.ok(html.indexOf("No files touched") >= 0, "empty files_touched shows empty state");
}

async function testDeliverablesRendersGroups() {
  const { api } = await loadApp();
  const html = api.auditSectionDeliverables(sampleAudit({
    files_touched: {
      local: [sampleFileFootprint("/a.py")],
      remote: [sampleFileFootprint("/etc/conf.yml", { confidence: "low" })],
      inferred: [sampleFileFootprint("/tmp/x", { confidence: "low" })],
    },
  }));
  assert.ok(html.indexOf(">Local") >= 0, "Local group labelled");
  assert.ok(html.indexOf(">Remote") >= 0, "Remote group labelled");
  assert.ok(html.indexOf(">Inferred") >= 0, "Inferred group labelled");
  assert.ok((html.match(/class="audit-group"/g) || []).length === 3, "exactly 3 groups");
}

async function testCommandIntentsHistogramSorted() {
  const { api } = await loadApp();
  const html = api.auditSectionCommandIntents(sampleAudit({ command_intents: { TEST: 1, DEBUG: 5, BUILD: 2 } }));
  const debugIdx = html.indexOf("Debug");
  const buildIdx = html.indexOf("Build");
  const testIdx = html.indexOf("Test");
  assert.ok(debugIdx >= 0 && buildIdx >= 0 && testIdx >= 0, "all intents labelled");
  assert.ok(debugIdx < buildIdx && buildIdx < testIdx, "intents sorted by count desc");
  assert.ok(html.indexOf("width:63%") >= 0, "highest intent fills bar proportional to total (DEBUG=5/8 -> 63%)");
}

async function testCommandIntentsEmpty() {
  const { api } = await loadApp();
  const html = api.auditSectionCommandIntents(sampleAudit({ command_intents: {} }));
  assert.ok(html.indexOf("No shell commands classified") >= 0, "empty intents shows muted message");
}

async function testFrictionAttachesEvidenceIdToSample() {
  const { api } = await loadApp();
  const html = api.auditSectionFriction(sampleAudit({
    friction_score: 30,
    errors: { count: 2, samples: ["err one", "err two"] },
    evidence: [
      { id: "s:error:tool:3", type: "error", message_index: 3 },
      { id: "s:error:tool:7", type: "error", message_index: 7 },
    ],
  }));
  assert.ok(html.indexOf('data-evidence-id="s:error:tool:3"') >= 0, "first error sample carries evidence id");
  assert.ok(html.indexOf('data-evidence-id="s:error:tool:7"') >= 0, "second error sample carries evidence id");
  assert.ok(html.indexOf("Friction 30") >= 0, "friction score rendered in badge");
}

async function testFrictionCapsSamplesAtThree() {
  const { api } = await loadApp();
  const html = api.auditSectionFriction(sampleAudit({
    errors: { count: 10, samples: ["a", "b", "c", "d", "e"] },
    evidence: [],
  }));
  assert.equal((html.match(/audit-error-row/g) || []).length, 3, "samples limited to 3");
}

async function testValueTierThresholds() {
  const { api } = await loadApp();
  const high = api.auditSectionValue(sampleAudit({ value_score: 85 }));
  assert.ok(high.indexOf("audit-value-high") >= 0, "score>=70 -> high tier");
  const med = api.auditSectionValue(sampleAudit({ value_score: 50 }));
  assert.ok(med.indexOf("audit-value-medium") >= 0, "30<=score<70 -> medium tier");
  const low = api.auditSectionValue(sampleAudit({ value_score: 5 }));
  assert.ok(low.indexOf("audit-value-low") >= 0, "score<30 -> low tier");
}

async function testFindEvidenceByIdReturnsMatch() {
  const { api } = await loadApp();
  api.setCurrentAudit({
    evidence: [
      { id: "x:tool:0", type: "tool_call", message_index: 4 },
      { id: "x:error:tool:7", type: "error", message_index: 7 },
    ],
  });
  const found = api.findEvidenceById("x:error:tool:7");
  assert.ok(found && found.type === "error", "findEvidenceById returns matching evidence");
  assert.equal(api.findEvidenceById("missing"), null, "missing id returns null");
  assert.equal(api.findEvidenceById(null), null, "null id returns null");
}

async function testFindEvidenceByIdHandlesNullAudit() {
  const { api } = await loadApp();
  api.setCurrentAudit(null);
  assert.equal(api.findEvidenceById("anything"), null, "null audit -> null result");
}

Promise.resolve()
  .then(testRenderAuditPanelEmptyWhenAuditIsNull)
  .then(testRenderAuditPanelHasAllSixSections)
  .then(testAuditExpandableTruncatesLongText)
  .then(testAuditExpandableShortTextNoExpand)
  .then(testAuditExpandableEmpty)
  .then(testFileRowHasDataAttributes)
  .then(testDeliverablesEmptyState)
  .then(testDeliverablesRendersGroups)
  .then(testCommandIntentsHistogramSorted)
  .then(testCommandIntentsEmpty)
  .then(testFrictionAttachesEvidenceIdToSample)
  .then(testFrictionCapsSamplesAtThree)
  .then(testValueTierThresholds)
  .then(testFindEvidenceByIdReturnsMatch)
  .then(testFindEvidenceByIdHandlesNullAudit)
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  });
