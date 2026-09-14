const status = document.getElementById('workspaceStatus');
const listOf = value => Array.isArray(value) ? value : [];
function text(tag, content, className) {
  const node = document.createElement(tag);
  node.textContent = content == null ? '' : String(content);
  if (className) node.className = className;
  return node;
}
function historyLink(item, label) {
  const link = text('a', label);
  link.href = `/history?system=${encodeURIComponent(item.system || '')}&source=${encodeURIComponent(item.source || '')}&session=${encodeURIComponent(item.id || '')}`;
  return link;
}
function section(label, entries, empty) {
  const node = text('section', '', 'work-fact');
  node.append(text('h4', label));
  const list = document.createElement('ul');
  for (const entry of entries) list.append(text('li', entry));
  node.append(entries.length ? list : text('p', empty, 'muted'));
  return node;
}
function isStale(item, now) {
  const timestamp = new Date(item.updated_at).getTime();
  return item.updated_at != null && Number.isFinite(timestamp) && now - timestamp > 7 * 86400000;
}
function record(item, now = Date.now()) {
  const node = text('article', '', 'work-record');
  node.append(text('h3', item.goal || item.title || '未命名记录'));
  const labels = {completed:'历史自报完成 · 当前成果未验证', partial:'历史记录部分完成', failed:'历史记录有失败', blocked:'历史记录有阻塞', unknown:'历史进展未知'};
  const project = item.project ? String(item.project).replace(/\\/g, '/').split('/').filter(Boolean).pop() : '项目未绑定';
  const projectLine = text('p', `${project} · ${item.system || '来源未知'} / ${item.source || '来源未知'}`, 'muted');
  if (item.project) projectLine.title = item.project;
  node.append(projectLine);
  if (isStale(item, now)) node.append(text('p', '记录已过期：超过 7 天未见新记录，请核对当前项目。', 'work-warning'));
  const timestamp = new Date(item.updated_at).getTime();
  node.append(text('p', item.updated_at != null && Number.isFinite(timestamp) ? `历史记录时间：${new Date(timestamp).toLocaleString()}` : '历史记录时间未知', 'muted'));
  const facts = text('div', '', 'work-facts');
  facts.append(section('进展', [labels[item.status] || labels.unknown], '历史进展未知'));
  facts.append(section('成果', listOf(item.changed).map(change => `历史变更：${change.path || '未记录路径'}`), '未提取到变更记录；不代表没有成果。'));
  const blockers = listOf(item.blockers).map(value => typeof value === 'string' ? value : value.summary || value.description || '历史阻塞待核对');
  if (!blockers.length && ['failed', 'blocked'].includes(item.status)) blockers.push('历史记录出现失败或阻塞，需进入原文核对是否解除。');
  facts.append(section('阻塞', blockers, '未提取到历史阻塞；当前是否受阻未知。'));
  const decisions = listOf(item.decisions).map(value => typeof value === 'string' ? value : value.summary || value.description || '历史决定待核对');
  facts.append(section('待决定', decisions, '未记录待决定事项；CM 未连接，实时审批状态未知。'));
  const next = !item.next_action || String(item.next_action).startsWith('Session outcome is ') ? '核对未完成项与当前代码后继续' : item.next_action;
  facts.append(section('下一步', [next, ...listOf(item.remaining).filter(value => value !== item.next_action).map(value => String(value).startsWith('Session outcome is ') ? '核对历史会话中尚未收口的工作。' : value)], '核对当前项目后继续'));
  const evidence = section('证据', listOf(item.verified).map(check => `历史验证记录：${check.command || '未记录命令'}（${check.status || 'unknown'}${check.evidence_id ? `；证据 ${check.evidence_id}` : '；未关联证据'}）`), item.evidence_status === 'unavailable' ? '证据读取失败或来源不支持，请进入历史核对。' : '未提取到验证依据，请进入历史核对。');
  evidence.append(text('p', '命令成功与历史自报不等于当前代码已验证；当前 Git HEAD 也不是历史基线证明。', 'muted'));
  for (const ref of listOf(item.evidence)) {
    const location = Number.isInteger(ref.message_index) ? `消息 ${ref.message_index}` : `证据 ${ref.id || '未知'}`;
    evidence.append(text('p', `${location}${Number.isInteger(ref.line_no) ? ` / 原始行 ${ref.line_no}` : ''}：${ref.summary || '查看原文'}`));
  }
  evidence.append(historyLink(item, '进入此会话核对证据'));
  facts.append(evidence);
  node.append(facts);
  return node;
}
function renderWorkspace(data, now = Date.now()) {
  const attention = document.getElementById('attentionList');
  const work = document.getElementById('workList');
  const sources = document.getElementById('sourceStatus');
  attention.replaceChildren(); work.replaceChildren(); sources.replaceChildren();
  let needsAttention = 0, results = 0;
  for (const item of listOf(data.work)) {
    if (item.status !== 'completed' || listOf(item.remaining).length || item.evidence_status === 'unavailable' || isStale(item, now)) { attention.append(record(item, now)); needsAttention++; }
    else { work.append(record(item, now)); results++; }
  }
  if (!needsAttention) attention.append(text('p', '当前历史快照未列出待核对项；这不代表所有运行任务都已完成。', 'muted'));
  if (!results) work.append(text('p', '暂无近期完成记录。进入历史可检索更早会话。', 'muted'));
  if (!listOf(data.work).length) sources.append(text('p', '历史记录为空。请在“搜索历史与设置”中检查来源配置并刷新索引。'));
  if (data.demo === true || data.is_demo === true || data.mode === 'demo') sources.append(text('p', '演示数据：这些记录用于体验，不代表你的真实工作。', 'work-warning'));
  for (const error of listOf(data.errors)) sources.append(text('p', `来源缺失或读取失败：${error.system || '未知'} / ${error.source || '未知'}。当前结果不完整，请检查来源路径与权限。`, 'work-warning'));
  for (const source of listOf(data.sources)) {
    const refreshed = source.last_refreshed_at ? new Date(source.last_refreshed_at).getTime() : NaN;
    sources.append(text('p', `来源 ${source.system || '未知'} / ${source.source || '未知'}：${source.status === 'readable' ? '可读取' : '不可用'}；索引刷新${Number.isFinite(refreshed) ? `于 ${new Date(refreshed).toLocaleString()}` : '时间未知'}。`, 'muted'));
  }
  sources.append(text('p', '索引新鲜度未知：页面读取时间不表示所有来源已刷新。', 'muted'));
  const observed = new Date(data.observed_at).getTime();
  status.textContent = `历史快照${Number.isFinite(observed) ? `读取于 ${new Date(observed).toLocaleString()}` : '读取时间未知'}。当前执行状态：unknown（CM 未连接）。`;
}
let requestSequence = 0;
async function loadWorkspace() {
  const sequence = ++requestSequence;
  status.textContent = '正在读取工作记录…';
  try {
    const response = await fetch('/api/workspace');
    if (!response.ok) throw new Error('workspace_unavailable');
    const data = await response.json();
    if (sequence !== requestSequence) return;
    if (!data || !Array.isArray(data.work)) throw new Error('invalid_workspace');
    renderWorkspace(data);
  } catch {
    if (sequence !== requestSequence) return;
    document.getElementById('attentionList').replaceChildren();
    document.getElementById('workList').replaceChildren();
    document.getElementById('sourceStatus').replaceChildren();
    status.textContent = '工作记录读取失败。请重试，或进入“搜索历史与设置”检查后台服务和来源；未展示的数据不代表没有工作。';
  }
}
document.getElementById('workspaceRetry').addEventListener('click', loadWorkspace);
if (typeof window !== 'undefined') window.__workspaceTestApi = {renderWorkspace, record, loadWorkspace, isStale};
loadWorkspace();
