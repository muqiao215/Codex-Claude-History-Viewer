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

const DEFAULT_SHELL_SUMMARY = {
  name: "shell_command",
  category: "shell",
  headline: "ls -la",
  file_path: null,
  change_kind: null,
  lines_added: 0,
  lines_removed: 0,
  exit_status: null,
  exit_code: null,
  output_preview: null,
  is_error: false,
};

function sampleToolUseMessage({ kind = "tool_use", summary } = {}) {
  return {
    role: "tool",
    kind,
    text: "Tool use: shell_command\nTool ID: call_1\nInput:\n```json\n{\"command\":\"ls -la\"}\n```",
    tool_summary: summary === undefined ? DEFAULT_SHELL_SUMMARY : summary,
  };
}

function sampleToolResultMessage({ kind = "tool_result", summary = null, text = null } = {}) {
  return {
    role: "tool",
    kind,
    text: text || "Exit code: 0\nWall time: 0.05 seconds\nOutput:\nfile1.py\nfile2.py",
    tool_summary: summary || {
      name: "shell_command",
      category: "shell",
      headline: null,
      file_path: null,
      change_kind: null,
      lines_added: 0,
      lines_removed: 0,
      exit_status: "ok",
      exit_code: 0,
      output_preview: "file1.py file2.py",
      is_error: false,
    },
  };
}

function sampleEditToolUse() {
  return sampleToolUseMessage({
    summary: {
      name: "apply_patch",
      category: "edit",
      headline: "Modify src/app.py",
      file_path: "src/app.py",
      change_kind: "modify",
      lines_added: 15,
      lines_removed: 3,
      exit_status: null,
      exit_code: null,
      output_preview: null,
      is_error: false,
    },
  });
}

function sampleNonToolMessage() {
  return { role: "assistant", kind: "text", text: "I'll help you with that." };
}


// ===========================================================================
// TEST: isToolMessage
// ===========================================================================

async function testIsToolMessage() {
  const { api } = await loadApp();
  assert.equal(api.isToolMessage(sampleToolUseMessage()), true);
  assert.equal(api.isToolMessage(sampleToolResultMessage()), true);
  assert.equal(api.isToolMessage(sampleNonToolMessage()), false);
  assert.equal(api.isToolMessage({ role: "assistant", kind: "thinking", text: "..." }), false);
}


// ===========================================================================
// TEST: isToolMessageCollapsed — default, expand, collapse overrides
// ===========================================================================

async function testCollapsedDefault() {
  const { api } = await loadApp();
  api.setToolsCollapsedByDefault(true);
  api.setExpandedToolIndexes(new Set());
  api.setCollapsedToolIndexes(new Set());
  assert.equal(api.isToolMessageCollapsed(0), true, "should be collapsed by default");
  assert.equal(api.isToolMessageCollapsed(5), true);
}

async function testExpandedOverride() {
  const { api } = await loadApp();
  api.setToolsCollapsedByDefault(true);
  api.setExpandedToolIndexes(new Set([2, 4]));
  api.setCollapsedToolIndexes(new Set());
  assert.equal(api.isToolMessageCollapsed(0), true, "non-expanded still collapsed");
  assert.equal(api.isToolMessageCollapsed(2), false, "expanded index not collapsed");
  assert.equal(api.isToolMessageCollapsed(4), false);
}

async function testCollapsedOverrideWhenDefaultExpanded() {
  const { api } = await loadApp();
  api.setToolsCollapsedByDefault(false);
  api.setExpandedToolIndexes(new Set());
  api.setCollapsedToolIndexes(new Set([1, 3]));
  assert.equal(api.isToolMessageCollapsed(0), false, "default expanded");
  assert.equal(api.isToolMessageCollapsed(1), true, "collapsed override");
  assert.equal(api.isToolMessageCollapsed(3), true);
  assert.equal(api.isToolMessageCollapsed(5), false);
}


// ===========================================================================
// TEST: toggleToolMessage / expandToolMessage / collapseToolMessage
// ===========================================================================

async function testToggleToolMessage() {
  const { api } = await loadApp();
  api.setToolsCollapsedByDefault(true);
  api.setExpandedToolIndexes(new Set());
  api.setCollapsedToolIndexes(new Set());

  api.expandToolMessage(3);
  assert.equal(api.isToolMessageCollapsed(3), false, "expand should make visible");

  api.setExpandedToolIndexes(new Set());
  api.collapseToolMessage(3);
  assert.equal(api.isToolMessageCollapsed(3), true, "collapse should hide");

  api.setToolsCollapsedByDefault(false);
  api.setExpandedToolIndexes(new Set());
  api.setCollapsedToolIndexes(new Set());
  assert.equal(api.isToolMessageCollapsed(3), false, "default expanded");

  api.collapseToolMessage(3);
  assert.equal(api.isToolMessageCollapsed(3), true, "collapse overrides default-expanded");

  api.toggleToolMessage(3);
  assert.equal(api.isToolMessageCollapsed(3), false, "toggle flips collapsed→expanded");
}


// ===========================================================================
// TEST: expandAllToolMessages / collapseAllToolMessages
// ===========================================================================

async function testExpandCollapseAll() {
  const { api } = await loadApp();
  api.setToolsCollapsedByDefault(true);
  api.setExpandedToolIndexes(new Set([1, 2]));
  api.setCollapsedToolIndexes(new Set([3]));

  api.expandAllToolMessages();
  assert.equal(api.getToolsCollapsedByDefault(), false, "expand-all flips default");
  assert.equal(api.getExpandedToolIndexes().size, 0, "expanded set cleared");
  assert.equal(api.getCollapsedToolIndexes().size, 0, "collapsed set cleared");
  assert.equal(api.isToolMessageCollapsed(0), false);
  assert.equal(api.isToolMessageCollapsed(1), false);

  api.collapseAllToolMessages();
  assert.equal(api.getToolsCollapsedByDefault(), true, "collapse-all flips default");
  assert.equal(api.isToolMessageCollapsed(0), true);
  assert.equal(api.isToolMessageCollapsed(1), true);
}


// ===========================================================================
// TEST: renderToolSummaryHtml — basic structure
// ===========================================================================

async function testRenderSummaryBasic() {
  const { api } = await loadApp();
  const msg = sampleToolUseMessage({ summary: null });
  const html = api.renderToolSummaryHtml(msg);
  assert.equal(html, null, "should return null for message with null tool_summary");
}

async function testRenderSummaryShell() {
  const { api } = await loadApp();
  const msg = sampleToolUseMessage();
  msg.tool_summary = {
    name: "shell_command",
    category: "shell",
    headline: "rg -n 'function' src/",
    file_path: null,
    change_kind: null,
    lines_added: 0,
    lines_removed: 0,
    exit_status: null,
    exit_code: null,
    output_preview: null,
    is_error: false,
  };
  const html = api.renderToolSummaryHtml(msg);
  assert.ok(html !== null, "should return HTML for tool message with summary");
  assert.ok(html.includes("msg-tool-icon"), "icon span present");
  assert.ok(html.includes("shell_command"), "tool name present");
  assert.ok(html.includes("rg"), "headline present");
  assert.ok(html.includes("msg-tool-name"), "name span class present");
}

async function testRenderSummaryEdit() {
  const { api } = await loadApp();
  const msg = sampleEditToolUse();
  const html = api.renderToolSummaryHtml(msg);
  assert.ok(html.includes("src/app.py"), "file path present");
  assert.ok(html.includes("+15"), "lines_added present");
  assert.ok(html.includes("-3"), "lines_removed present");
  assert.ok(html.includes("msg-tool-diff"), "diff class present");
}

async function testRenderSummaryNoHeadline() {
  const { api } = await loadApp();
  const msg = sampleToolUseMessage();
  msg.tool_summary.headline = null;
  const html = api.renderToolSummaryHtml(msg);
  assert.ok(html !== null);
  assert.ok(!html.includes("msg-tool-headline"), "headline span omitted when null");
}


// ===========================================================================
// TEST: renderToolStatusHtml — ok / error / unknown
// ===========================================================================

async function testRenderStatusOk() {
  const { api } = await loadApp();
  const html = api.renderToolStatusHtml({ is_error: false, exit_status: "ok", exit_code: 0 });
  assert.ok(html.includes("msg-tool-status"), "status class present");
  assert.ok(html.includes("ok"), "ok class applied");
  assert.ok(html.includes("✓"), "checkmark icon");
}

async function testRenderStatusError() {
  const { api } = await loadApp();
  const html = api.renderToolStatusHtml({ is_error: true, exit_status: "error", exit_code: 1 });
  assert.ok(html.includes("error"), "error class applied");
  assert.ok(html.includes("✕"), "cross icon");
}

async function testRenderStatusUnknown() {
  const { api } = await loadApp();
  const html = api.renderToolStatusHtml({ is_error: false, exit_status: null, exit_code: null });
  assert.ok(html.includes("unknown"), "unknown class applied");
}

async function testRenderStatusIsErrorOverridesExitStatus() {
  const { api } = await loadApp();
  const html = api.renderToolStatusHtml({ is_error: true, exit_status: "ok", exit_code: 0 });
  assert.ok(html.includes("error"), "is_error=true overrides exit_status=ok");
}


// ===========================================================================
// TEST: renderToolMessageBody — truncation at 20 lines
// ===========================================================================

async function testToolBodyPreviewLines() {
  const { api } = await loadApp();
  assert.equal(api.getToolOutputPreviewLines(), 20, "preview line limit is 20");
}

async function testToolBodyTruncationShortOutput() {
  const { api } = await loadApp();
  const body = new FakeElement("div");
  const msg = sampleToolResultMessage({ text: "line1\nline2\nline3" });
  api.setFullToolOutputIndexes(new Set());
  api.renderToolMessageBody(body, msg, { index: 0, expanded: true, searchMatch: false, term: "" });
  assert.ok(!body.innerHTML.includes("msg-tool-output-truncated"),
    "no truncation notice for short output");
}

async function testToolBodyTruncationLongOutput() {
  const { api } = await loadApp();
  const body = new FakeElement("div");
  const longText = Array.from({ length: 50 }, (_, i) => `output_line_${i}`).join("\n");
  const msg = sampleToolResultMessage({ text: longText });
  api.setFullToolOutputIndexes(new Set());
  api.renderToolMessageBody(body, msg, { index: 0, expanded: true, searchMatch: false, term: "" });
  assert.ok(body.innerHTML.includes("msg-tool-output-truncated"),
    "truncation notice for 50-line output");
  assert.ok(body.innerHTML.includes("50"), "total line count in button text");
  assert.ok(body.innerHTML.includes("data-tool-output-toggle"), "toggle button present");
}

async function testToolBodyFullOutputWhenRequested() {
  const { api } = await loadApp();
  const body = new FakeElement("div");
  const longText = Array.from({ length: 50 }, (_, i) => `line_${i}`).join("\n");
  const msg = sampleToolResultMessage({ text: longText });
  api.setFullToolOutputIndexes(new Set([0]));
  api.renderToolMessageBody(body, msg, { index: 0, expanded: true, searchMatch: false, term: "" });
  assert.ok(!body.innerHTML.includes("msg-tool-output-truncated"),
    "no truncation when full output requested");
}


// ===========================================================================
// Runner
// ===========================================================================

const tests = [
  ["isToolMessage identifies tool kinds", testIsToolMessage],
  ["collapsed by default returns true for all indexes", testCollapsedDefault],
  ["expanded override takes precedence over default", testExpandedOverride],
  ["collapsed override takes precedence over default-expanded", testCollapsedOverrideWhenDefaultExpanded],
  ["toggle/expand/collapse manipulate sets correctly", testToggleToolMessage],
  ["expand-all/collapse-all flip default and clear sets", testExpandCollapseAll],
  ["renderToolSummaryHtml returns null without tool_summary", testRenderSummaryBasic],
  ["renderToolSummaryHtml renders shell tool correctly", testRenderSummaryShell],
  ["renderToolSummaryHtml renders edit tool with diff counts", testRenderSummaryEdit],
  ["renderToolSummaryHtml omits headline span when null", testRenderSummaryNoHeadline],
  ["renderToolStatusHtml renders ok status", testRenderStatusOk],
  ["renderToolStatusHtml renders error status", testRenderStatusError],
  ["renderToolStatusHtml renders unknown status", testRenderStatusUnknown],
  ["renderToolStatusHtml is_error overrides exit_status", testRenderStatusIsErrorOverridesExitStatus],
  ["TOOL_OUTPUT_PREVIEW_LINES is 20", testToolBodyPreviewLines],
  ["renderToolMessageBody no truncation for short output", testToolBodyTruncationShortOutput],
  ["renderToolMessageBody truncates 50-line output with Show-all button", testToolBodyTruncationLongOutput],
  ["renderToolMessageBody full output when index in fullToolOutputIndexes", testToolBodyFullOutputWhenRequested],
];

(async () => {
  let passed = 0;
  let failed = 0;
  for (const [name, fn] of tests) {
    try {
      await fn();
      passed++;
    } catch (err) {
      failed++;
      console.error(`FAIL: ${name}`);
      console.error(`  ${err.message}`);
      if (err.stack) console.error(`  ${err.stack.split("\n").slice(1, 3).join("\n  ")}`);
    }
  }
  if (failed > 0) {
    console.error(`\n${passed}/${tests.length} passed, ${failed} FAILED`);
    process.exitCode = 1;
  } else {
    console.log(`\n${passed}/${tests.length} passed`);
  }
})();
