# Findings

## Workspace state

- 当前仓库已有多个未提交修改与新文件，必须保留。
- GitHub remote 为 `muqiao215/Codex-Claude-History-Viewer`。
- GitHub CLI 已以 `muqiao215` 认证，具备创建私有或公开仓库的权限。
- 指定的 Obsidian 目录存在，尚无 `SpecMesh/` 子目录。

## Project identity

- 项目是本地优先、无第三方运行依赖的多 Agent 会话历史浏览器和价值审计工具。
- 长期产品方向是将原始 transcript 变成可搜索、可回溯的工程账本，而不是企业观测平台。
- 确定性证据提取与可选 AI 语义解释的分层是关键不变量。
- 当前工作区正在增加独立于 AI Audit 的确定性 Agent handoff capsule。

## Architecture

- `app.py` 集中了解析、索引、HTTP API 和启动逻辑，是高影响修改区。
- JSONL 来源经过解析后进入本地 SQLite 缓存；OpenCode/Hermes 通过只读适配器接入。
- 前端是无 build step 的静态 HTML/CSS/JavaScript。

## SpecMesh repository

- Canonical 本地仓库已建立于 `/home/muqiao/桌面/obsidian/my-programming-world/编程/SpecMesh`。
- GitHub 公开仓库为 `https://github.com/muqiao215/specmesh`。
- 首个提交为 `a2697ae` (`docs: publish SpecMesh v1.0`)。
