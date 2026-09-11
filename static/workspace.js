const status = document.getElementById('workspaceStatus');
function text(tag, content, className) {
  const node = document.createElement(tag);
  node.textContent = content;
  if (className) node.className = className;
  return node;
}
function record(item) {
  const node = text('article', '', 'work-record');
  node.append(text('h3', item.goal || item.title));
  const labels = {completed:'历史报告完成', partial:'仍有待确认工作', failed:'历史记录有失败', blocked:'历史记录有阻塞', unknown:'状态待核对'};
  const project = item.project ? item.project.replace(/\\/g, '/').split('/').filter(Boolean).pop() : '项目未绑定';
  const projectLine = text('p', `${project} · ${labels[item.status] || '状态待核对'}`, 'muted');
  if (item.project) projectLine.title = item.project;
  node.append(projectLine);
  const nextAction = !item.next_action || item.next_action.startsWith('Session outcome is ')
    ? '核对未完成项与当前代码后继续' : item.next_action;
  node.append(text('p', `下一步：${nextAction}`, 'work-next'));
  if (item.updated_at) node.append(text('p', `最近记录：${new Date(item.updated_at).toLocaleString()}`, 'muted'));
  const evidence = document.createElement('details');
  evidence.append(text('summary', '查看成果与验证依据'));
  const list = document.createElement('ul');
  for (const change of item.changed || []) list.append(text('li', `变更：${change.path || '未记录路径'}`));
  for (const check of item.verified || []) list.append(text('li', `历史验证：${check.command || '未记录命令'}（${check.status || 'unknown'}）`));
  for (const remaining of item.remaining || []) list.append(text('li', `待完成：${remaining}`));
  if (!list.children.length) list.append(text('li', '未提取到验证依据，需要进入历史核对。'));
  evidence.append(list); node.append(evidence);
  const link = text('a', '进入历史核对');
  link.href = `/history?system=${encodeURIComponent(item.system)}&source=${encodeURIComponent(item.source)}&session=${encodeURIComponent(item.id)}`;
  node.append(link);
  return node;
}
try {
  const response = await fetch('/api/workspace');
  if (!response.ok) throw new Error('workspace_unavailable');
  const data = await response.json();
  const attention = document.getElementById('attentionList');
  const work = document.getElementById('workList');
  let needsAttention = 0, results = 0;
  for (const item of data.work || []) {
    if (item.status !== 'completed' || (item.remaining || []).length) { attention.append(record(item)); needsAttention++; }
    else { work.append(record(item)); results++; }
  }
  if (!needsAttention) attention.append(text('p', '当前历史快照未列出待核对项；这不代表所有运行任务都已完成。', 'muted'));
  if (!results) work.append(text('p', '尚无可展示的完成记录，可从历史入口查找项目。', 'muted'));
  status.textContent = `历史快照更新于 ${new Date(data.observed_at).toLocaleString()}${data.errors?.length ? '；部分来源不可用，结果不完整' : ''}`;
} catch {
  status.textContent = '暂时无法读取工作记录。请检查后台服务，或进入历史入口查看已有记录。';
}
