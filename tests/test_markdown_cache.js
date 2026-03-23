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

function loadApp() {
  const repoDir = path.resolve(__dirname, "..");
  const sourcePath = path.join(repoDir, "static", "app.js");
  const source = fs.readFileSync(sourcePath, "utf8") + `
globalThis.__testApi = {
  getMessageHtml,
  buildMessageElement,
  buildResumeCommands,
  getResumeCommandLabels,
  setCurrentSession(value) { currentSession = value; },
  setCurrentSystem(value) { currentSystem = value; },
  setCurrentSource(value) { currentSource = value; },
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
    fetch: async () => ({
      ok: true,
      json: async () => ({ items: [], has_more: false, next_offset: 0, matches: [] }),
    }),
    requestAnimationFrame(callback) {
      callback();
      return 1;
    },
    setTimeout() {
      return 1;
    },
    clearTimeout() {},
    alert() {},
    URLSearchParams,
    Element: FakeElement,
    NodeFilter: { SHOW_TEXT: 4 },
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

function testLinuxResumeCommandsUseShellFriendlyVariants() {
  const { api } = loadApp();
  const labels = api.getResumeCommandLabels("linux");
  assert.equal(labels.primary, "Resume Shell");
  assert.equal(labels.secondary, "Resume Plain");

  const commands = api.buildResumeCommands("linux", "codex", "/home/muqiao/work/demo", "019-demo");
  assert.equal(commands.ps, "cd '/home/muqiao/work/demo' && codex resume 019-demo");
  assert.equal(commands.wsl, "codex resume 019-demo");
}

testPersistentCacheReusesRenderedHtmlAcrossMessageObjects();
testPreviewAndFullModesUseDistinctPersistentEntries();
testSearchHitUsesExcerptInsteadOfAutoExpandingFullLongMessage();
testLinuxResumeCommandsUseShellFriendlyVariants();
