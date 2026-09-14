'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}
const elements = Object.fromEntries(['workspaceStatus', 'sourceStatus', 'attentionList', 'workList', 'workspaceRetry'].map(id => [id, new Element('div')]));
const document = {getElementById: id => elements[id], createElement: tag => new Element(tag)};
const flatten = node => node.textContent + '\n' + node.children.map(flatten).join('\n');
let fetcher = async () => ({ok: true, json: async () => ({work: []})});
const context = {document, window: {}, fetch: (...args) => fetcher(...args), Date, encodeURIComponent};
vm.createContext(context);
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '../static/workspace.js'), 'utf8'), context);
const api = context.window.__workspaceTestApi;
(async () => {
  await api.loadWorkspace();
  const now = Date.parse('2026-09-15T00:00:00Z');
  const base = {id: 'a&evil="', system: 'codex', source: 'local', title: '<img src=x onerror=alert(1)>', status: 'completed', updated_at: now};
  api.renderWorkspace({work: [base], observed_at: now}, now);
  let record = elements.workList.children[0];
  assert.equal(record.children[0].tag, 'h3');
  assert.equal(record.children[0].textContent, base.title);
  assert.match(flatten(record), /历史自报完成 · 当前成果未验证/);
  const labels = record.children.at(-1).children.map(node => node.children[0].textContent);
  assert.deepEqual(Array.from(labels), ['进展', '成果', '阻塞', '待决定', '下一步', '证据']);
  assert.match(record.children.at(-1).children.at(-1).children.at(-1).href, /session=a%26evil%3D%22/);
  assert.match(flatten(record), /CM 未连接/);
  assert.match(flatten(record), /当前 Git HEAD 也不是历史基线证明/);
  api.renderWorkspace({work: [{...base, status: 'failed', blockers: ['build failed'], decisions: ['choose version'], verified: [{command: 'pytest', status: 'passed', evidence_id: 'e1'}], evidence: [{message_index: 3, line_no: 9, summary: 'exit 0'}]}]}, now);
  const failed = flatten(elements.attentionList);
  for (const expected of ['build failed', 'choose version', 'pytest', '消息 3 / 原始行 9', '历史记录有失败']) assert.ok(failed.includes(expected));
  api.renderWorkspace({work: [{...base, updated_at: now - 8 * 86400000}]}, now);
  assert.match(flatten(elements.attentionList), /记录已过期/);
  api.renderWorkspace({work: [{...base, evidence_status: 'unavailable'}]}, now);
  assert.match(flatten(elements.attentionList), /证据读取失败/);
  api.renderWorkspace({work: [], demo: true, errors: [{source: '<script>bad</script>', system: 'claude'}], sources: [{system:'codex', source:'local', status:'unavailable', last_refreshed_at:null}]}, now);
  const sources = flatten(elements.sourceStatus);
  for (const expected of ['历史记录为空', '演示数据', '来源缺失或读取失败', '<script>bad</script>', '时间未知', '索引新鲜度未知']) assert.ok(sources.includes(expected));
  fetcher = async () => ({ok: false});
  await api.loadWorkspace();
  assert.match(elements.workspaceStatus.textContent, /读取失败/);
  assert.equal(elements.attentionList.children.length, 0);
  assert.equal(elements.sourceStatus.children.length, 0);
  // A late response from an older reload must not replace a newer snapshot.
  let resolveOld;
  fetcher = () => new Promise(resolve => { resolveOld = resolve; });
  const pending = api.loadWorkspace();
  fetcher = async () => ({ok: true, json: async () => ({work:[{...base, title:'new snapshot'}]})});
  await api.loadWorkspace();
  resolveOld({ok: true, json: async () => ({work:[{...base, title:'old snapshot'}]})});
  await pending;
  assert.ok((flatten(elements.workList) + flatten(elements.attentionList)).includes('new snapshot'));
  assert.ok(!(flatten(elements.workList) + flatten(elements.attentionList)).includes('old snapshot'));
  assert.equal(typeof elements.workspaceRetry.listeners.click, 'function');
  console.log('workspace: six facts, provenance, freshness, failure, demo, escaping and reload race passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
