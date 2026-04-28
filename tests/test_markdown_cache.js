const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...tokens) {
    tokens.forEach((token) => this.values.add(token));
  }

  remove(...tokens) {
    tokens.forEach((token) => this.values.delete(token));
  }

  toggle(token, force) {
    if (force === true) {
      this.values.add(token);
      return true;
    }
    if (force === false) {
      this.values.delete(token);
      return false;
    }
    if (this.values.has(token)) {
      this.values.delete(token);
      return false;
    }
    this.values.add(token);
    return true;
  }

  contains(token) {
    return this.values.has(token);
  }
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
    this.checked = true;
    this.parentNode = null;
    this._queryCache = new Map();
  }

  appendChild(child) {
    if (!child) return child;
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChild(nextChild, prevChild) {
    const index = this.children.indexOf(prevChild);
    if (index >= 0) {
      nextChild.parentNode = this;
      this.children[index] = nextChild;
    }
    return prevChild;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) {
      this.children.splice(index, 1);
    }
    return child;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  addEventListener(type, handler) {
    this.eventListeners.set(type, handler);
  }

  removeEventListener(type) {
    this.eventListeners.delete(type);
  }

  querySelector(selector) {
    if (!this._queryCache.has(selector)) {
      this._queryCache.set(selector, new FakeElement("div"));
    }
    return this._queryCache.get(selector);
  }

  querySelectorAll() {
    return [];
  }

  closest() {
    return null;
  }

  scrollIntoView() {}

  setPointerCapture() {}

  getBoundingClientRect() {
    return { width: 960, height: 640 };
  }
}

function createStorage() {
  const store = new Map();
  return {
    getItem(key) {
      return store.has(key) ? store.get(key) : null;
    },
    setItem(key, value) {
      store.set(key, String(value));
    },
    removeItem(key) {
      store.delete(key);
    },
    clear() {
      store.clear();
    },
  };
}

function createDocument() {
  const elements = new Map();
  const documentElement = new FakeElement("html");
  documentElement.dataset = {};
  const body = new FakeElement("body");

  return {
    documentElement,
    body,
    getElementById(id) {
      if (!elements.has(id)) {
        elements.set(id, new FakeElement("div"));
      }
      return elements.get(id);
    },
    querySelectorAll() {
      return [];
    },
    createElement(tagName) {
      return new FakeElement(tagName);
    },
    createDocumentFragment() {
      return new FakeElement("#fragment");
    },
    createTextNode(text) {
      return { nodeValue: String(text), textContent: String(text), parentNode: null };
    },
    createTreeWalker() {
      return {
        nextNode() {
          return null;
        },
      };
    },
  };
}

class FakeIntersectionObserver {
  constructor(callback) {
    this.callback = callback;
    this.targets = new Set();
    FakeIntersectionObserver.instances.push(this);
  }

  observe(target) {
    this.targets.add(target);
  }

  unobserve(target) {
    this.targets.delete(target);
  }

  disconnect() {
    this.targets.clear();
  }
}

FakeIntersectionObserver.instances = [];

function loadApp({ fetchImpl, alertImpl } = {}) {
  const repoDir = path.resolve(__dirname, "..");
  const sourcePath = path.join(repoDir, "static", "app.js");
  const source = fs.readFileSync(sourcePath, "utf8") + `
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
  getBrowseVirtualRefreshScrollTop,
  setCurrentSession(value) { currentSession = value; },
  getCurrentSession() { return currentSession; },
  setCurrentSystem(value) { currentSystem = value; },
  setCurrentSource(value) { currentSource = value; },
  setBrowseVirtualRenderScrollTop(value) {
    currentBrowseVirtualRenderScrollTop = value;
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
    };
  },
  buildMessageRenderPlan,
  buildVirtualWindow,
  handlePinSessionClick,
};
`;

  const localStorage = createStorage();
  const document = createDocument();
  const context = vm.createContext({
    console,
    document,
    localStorage,
    navigator: {
      clipboard: {
        writeText: async () => {},
      },
    },
    window: {
      addEventListener() {},
    },
    fetch: fetchImpl || (async () => ({
      ok: true,
      json: async () => ({ items: [], has_more: false, next_offset: 0, matches: [] }),
    })),
    requestAnimationFrame(callback) {
      callback();
      return 1;
    },
    cancelAnimationFrame() {},
    setTimeout() {
      return 1;
    },
    clearTimeout() {},
    alert: alertImpl || (() => {}),
    URLSearchParams,
    Element: FakeElement,
    NodeFilter: { SHOW_TEXT: 4 },
    IntersectionObserver: FakeIntersectionObserver,
  });

  vm.runInContext(source, context, { filename: sourcePath });
  return {
    api: context.__testApi,
    localStorage,
  };
}

function testPersistentCacheReusesRenderedHtmlAcrossMessageObjects() {
  const { api, localStorage } = loadApp();
  let renderCalls = 0;
  api.setCurrentSystem("windows");
  api.setCurrentSource("codex");
  api.setCurrentSession({ id: "session-1" });
  api.setRenderMarkdown((text) => {
    renderCalls += 1;
    return `rendered:${text}`;
  });

  const msgA = { message_index: 0, role: "assistant", kind: "message", text: "# hello" };
  const htmlA = api.getMessageHtml(msgA, false);
  assert.equal(htmlA, "rendered:# hello");
  assert.equal(renderCalls, 1);

  const msgB = { message_index: 0, role: "assistant", kind: "message", text: "# hello" };
  const htmlB = api.getMessageHtml(msgB, false);
  assert.equal(htmlB, "rendered:# hello");
  assert.equal(renderCalls, 1, "expected persistent cache hit for equivalent message object");

  const storageKeys = api.getStorageKeyInfo();
  assert.ok(localStorage.getItem(storageKeys.index), "expected markdown cache index to be persisted");
}

function testPreviewAndFullModesUseDistinctPersistentEntries() {
  const { api } = loadApp();
  let renderCalls = 0;
  api.setCurrentSystem("windows");
  api.setCurrentSource("codex");
  api.setCurrentSession({ id: "session-2" });
  api.setRenderMarkdown((text) => {
    renderCalls += 1;
    return `html:${text.length}`;
  });

  const longText = "A".repeat(13_500);
  const msgA = { message_index: 3, role: "assistant", kind: "message", text: longText };
  const previewA = api.getMessageHtml(msgA, false);
  const fullA = api.getMessageHtml(msgA, true);
  assert.notEqual(previewA, fullA);
  assert.equal(renderCalls, 2);

  const msgB = { message_index: 3, role: "assistant", kind: "message", text: longText };
  const previewB = api.getMessageHtml(msgB, false);
  const fullB = api.getMessageHtml(msgB, true);
  assert.equal(previewB, previewA);
  assert.equal(fullB, fullA);
  assert.equal(renderCalls, 2, "expected preview/full html to come from persistent cache on reload");
}

function testSearchHitUsesExcerptInsteadOfAutoExpandingFullLongMessage() {
  const { api } = loadApp();
  const renderedInputs = [];
  api.setCurrentSystem("windows");
  api.setCurrentSource("codex");
  api.setCurrentSession({ id: "session-search" });
  api.setExpandedMessageIndexes([]);
  api.setCurrentSessionSearchData("needle", [[0, {
    excerpt_text: "...\nneedle nearby\n...",
    excerpt_start: 1800,
    excerpt_end: 1813,
    hit_count: 1,
  }]]);
  api.setRenderMarkdown((text) => {
    renderedInputs.push(text);
    return `rendered:${text}`;
  });

  const msg = {
    message_index: 0,
    role: "assistant",
    kind: "message",
    text: `${"A".repeat(8000)}needle${"B".repeat(8000)}`,
  };
  const rendered = api.buildMessageElement(msg, 0, "needle");
  const body = rendered.wrapper.children[1];
  assert.equal(body.innerHTML, "rendered:...\nneedle nearby\n...");
  assert.deepEqual(renderedInputs, ["...\nneedle nearby\n..."]);
}

function testMessageBodiesRenderLazilyUntilVisible() {
  const { api } = loadApp();
  const renderedInputs = [];
  api.setCurrentSystem("windows");
  api.setCurrentSource("codex");
  api.setCurrentSession({ id: "session-lazy" });
  api.setExpandedMessageIndexes([]);
  api.setCurrentSessionSearchData("", []);
  api.setRenderMarkdown((text) => {
    renderedInputs.push(text);
    return `rendered:${text}`;
  });

  const msg = {
    message_index: 0,
    role: "assistant",
    kind: "message",
    text: "lazy body",
  };
  const rendered = api.buildMessageElement(msg, 0, "");
  const body = rendered.wrapper.children[1];

  assert.equal(body.textContent, "Rendering message...");
  assert.equal(body.innerHTML, "");
  assert.deepEqual(renderedInputs, []);

  api.flushLazyMessageBodies();

  assert.equal(body.innerHTML, "rendered:lazy body");
  assert.deepEqual(renderedInputs, ["lazy body"]);
}

function testMountedVirtualWindowBodiesFlushWithoutIntersectionObserver() {
  const { api } = loadApp();
  const renderedInputs = [];
  api.setCurrentSystem("linux");
  api.setCurrentSource("codex");
  api.setCurrentSession({ id: "session-virtual-lazy" });
  api.setExpandedMessageIndexes([]);
  api.setCurrentSessionSearchData("", []);
  api.setRenderMarkdown((text) => {
    renderedInputs.push(text);
    return `rendered:${text}`;
  });

  const root = new FakeElement("div");
  const first = api.buildMessageElement({
    message_index: 41,
    role: "assistant",
    kind: "message",
    text: "mounted virtual row",
  }, 41, "");
  const second = api.buildMessageElement({
    message_index: 42,
    role: "user",
    kind: "message",
    text: "second mounted row",
  }, 42, "");
  root.appendChild(first.wrapper);
  root.appendChild(second.wrapper);

  const firstBody = first.wrapper.children[1];
  const secondBody = second.wrapper.children[1];
  assert.equal(firstBody.textContent, "Rendering message...");
  assert.equal(secondBody.textContent, "Rendering message...");
  assert.deepEqual(renderedInputs, []);

  const flushed = api.flushPendingLazyMessageBodiesForRoot(root);

  assert.equal(flushed, 2);
  assert.equal(firstBody.innerHTML, "rendered:mounted virtual row");
  assert.equal(secondBody.innerHTML, "rendered:second mounted row");
  assert.deepEqual(renderedInputs, ["mounted virtual row", "second mounted row"]);
}

function testBrowseVirtualRefreshUsesInFlightRestoreScrollTop() {
  const { api } = loadApp();
  api.setBrowseVirtualRenderScrollTop(20_000);
  assert.equal(api.getBrowseVirtualRefreshScrollTop(0), 20_000);
  assert.equal(api.getBrowseVirtualRefreshScrollTop(75), 20_000);
  api.setBrowseVirtualRenderScrollTop(null);
  assert.equal(api.getBrowseVirtualRefreshScrollTop(75), 75);
}

function testLinuxResumeCommandsUseShellFriendlyVariants() {
  const { api } = loadApp();
  const labels = api.getResumeCommandLabels("linux");
  assert.equal(labels.primary, "Resume Shell");
  assert.equal(labels.secondary, "Resume Plain");

  const commands = api.buildResumeCommands("linux", "codex", "/home/muqiao/work/demo", "019-demo");
  assert.equal(commands.ps, "cd '/home/muqiao/work/demo' && codex resume 019-demo");
  assert.equal(commands.wsl, "codex resume 019-demo");
}

function testClaudeResumeCommandsAppendDangerousSkipPermissions() {
  const { api } = loadApp();
  const commands = api.buildResumeCommands("windows", "claude", "C:\\Users\\11614", "8f9b64e5-af3f-4735-af95-7b1d6147ddf5");
  assert.equal(
    commands.ps,
    "Set-Location -LiteralPath 'C:\\Users\\11614'; claude -r 8f9b64e5-af3f-4735-af95-7b1d6147ddf5 --dangerously-skip-permissions",
  );
  assert.equal(
    commands.wsl,
    "cd '/mnt/c/Users/11614' && claude -r 8f9b64e5-af3f-4735-af95-7b1d6147ddf5 --dangerously-skip-permissions",
  );
}

function testBrowseRenderPlanShowsLatestWindowOnly() {
  const { api } = loadApp();
  const messages = Array.from({ length: 450 }, (_, index) => ({
    role: "assistant",
    kind: "message",
    text: `msg-${index}`,
  }));
  const plan = api.buildMessageRenderPlan(
    messages,
    {
      user: true,
      assistant: true,
      system: true,
      developer: true,
      tool: true,
      other: true,
    },
    "",
    { query: "", matches: new Map(), loading: false, error: "" },
    200,
  );
  assert.equal(plan.mode, "browse");
  assert.equal(plan.totalVisible, 450);
  assert.equal(plan.hiddenBefore, 250);
  assert.equal(plan.items.length, 200);
  assert.equal(plan.items[0].msg.text, "msg-250");
  assert.equal(plan.items.at(-1).msg.text, "msg-449");
}

function testSearchRenderPlanOnlyReturnsMatchedWindow() {
  const { api } = loadApp();
  const messages = Array.from({ length: 250 }, (_, index) => ({
    role: index % 2 === 0 ? "assistant" : "tool",
    kind: "message",
    text: `message-${index}`,
  }));
  const matches = new Map(messages.map((_, index) => [index, { hit_count: 1 }]));
  const plan = api.buildMessageRenderPlan(
    messages,
    {
      user: true,
      assistant: true,
      system: true,
      developer: true,
      tool: true,
      other: true,
    },
    "ta",
    { query: "ta", matches, loading: false, error: "" },
    200,
  );
  assert.equal(plan.mode, "search");
  assert.equal(plan.totalVisible, 250);
  assert.equal(plan.items.length, 200);
  assert.equal(plan.hiddenAfter, 50);
  assert.equal(plan.items[0].index, 0);
  assert.equal(plan.items.at(-1).index, 199);
}

function testVirtualWindowKeepsBoundedVisibleRangeWithSpacers() {
  const { api } = loadApp();
  const heights = Array.from({ length: 1000 }, () => 100);
  const plan = api.buildVirtualWindow(heights, 50_000, 600, 300);

  assert.equal(plan.totalHeight, 100_000);
  assert.ok(plan.start > 0, "expected a non-zero start range for deep scroll");
  assert.ok(plan.end < heights.length, "expected range to stop before the full list");
  assert.ok(plan.end - plan.start <= 16, "expected bounded DOM range with overscan");
  assert.ok(plan.topSpacer > 0, "expected top spacer to preserve scroll height");
  assert.ok(plan.bottomSpacer > 0, "expected bottom spacer to preserve scroll height");
  assert.equal(
    plan.topSpacer + plan.bottomSpacer + (plan.end - plan.start) * 100,
    plan.totalHeight,
  );
}

function testVirtualWindowUsesMeasuredVariableHeights() {
  const { api } = loadApp();
  const heights = [100, 100, 500, 100, 100, 100];
  const plan = api.buildVirtualWindow(heights, 250, 120, 0);

  assert.equal(plan.totalHeight, 1000);
  assert.equal(plan.start, 2);
  assert.equal(plan.end, 3);
  assert.equal(plan.topSpacer, 200);
  assert.equal(plan.bottomSpacer, 300);
}

async function testPinFailureDoesNotMutateCurrentSession() {
  const alerts = [];
  const { api } = loadApp({
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({ ok: false, error: "unsupported" }),
    }),
    alertImpl: (message) => alerts.push(message),
  });
  api.setCurrentSystem("windows");
  api.setCurrentSource("codex");
  api.setCurrentSession({ id: "session-pin", pinned: 0 });

  await api.handlePinSessionClick();

  assert.equal(api.getCurrentSession().pinned, 0);
  assert.equal(alerts.length, 1);
  assert.match(alerts[0], /unsupported/);
}

testPersistentCacheReusesRenderedHtmlAcrossMessageObjects();
testPreviewAndFullModesUseDistinctPersistentEntries();
testSearchHitUsesExcerptInsteadOfAutoExpandingFullLongMessage();
testMessageBodiesRenderLazilyUntilVisible();
testMountedVirtualWindowBodiesFlushWithoutIntersectionObserver();
testBrowseVirtualRefreshUsesInFlightRestoreScrollTop();
testLinuxResumeCommandsUseShellFriendlyVariants();
testClaudeResumeCommandsAppendDangerousSkipPermissions();
testBrowseRenderPlanShowsLatestWindowOnly();
testSearchRenderPlanOnlyReturnsMatchedWindow();
testVirtualWindowKeepsBoundedVisibleRangeWithSpacers();
testVirtualWindowUsesMeasuredVariableHeights();
testPinFailureDoesNotMutateCurrentSession().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
