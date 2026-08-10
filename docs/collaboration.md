# Nickel Dashboard — 协作规范

## 仓库信息

- **URL**: https://github.com/algo23-yunqingtian/nickel-dashboard
- **Pages**: https://algo23-yunqingtian.github.io/nickel-dashboard/
- **默认分支**: `main`

## 两个 Agent 分工

| 角色 | 负责文件 | 不碰的文件 |
|------|----------|-----------|
| **微信端 Hermes** | `fetch_data.py`, `data.json`, `requirements.txt`, `.github/workflows/fetch.yml` | `index.html`, `static/` |
| **飞书端 Hermes** | `index.html`, `static/*` (CSS/JS), UI 逻辑 | `data.json`, `fetch_data.py`, workflow |

## 协作规则

### 日常开发
- 各自改各自的文件 → commit → push 到 `main`
- 因为文件隔离，极少冲突
- 如果冲突（同时改同一个 workflow），后推的人先 pull rebase 再 push

### 大改动
1. 开 feature branch: `git checkout -b feature/xxx`
2. 开发完成后 push branch
3. 创建 PR: `gh pr create --base main --head feature/xxx --title "描述" --body "改了什么"`
4. 另一方 review 后 merge

### 变更日志
每次改动在 `docs/change_log.md` 加一行：
```
[YYYY-MM-DD HH:MM] [微信/飞书] 简述改动
```

### 数据管道
- GitHub Actions 每 4 小时自动运行 `fetch.yml`
- 需要改 API key 时更新 GitHub Secrets（Settings → Secrets）
- Secrets: `ZHJI_KEY`, `SILICONFLOW_KEY`

### 紧急修复
- 直接在 `main` 上改 → commit → push
- 事后在 change_log 补记录

## 文件说明

| 文件 | 用途 |
|------|------|
| `index.html` | 主页面（Dark ECharts 看板） |
| `static/style.css` | 样式 |
| `data.json` | 数据源（Actions 更新） |
| `fetch_data.py` | 数据抓取脚本 |
| `.github/workflows/fetch.yml` | 定时数据更新 |
| `docs/frame.md` | 镍品种分析框架 |
| `docs/change_log.md` | 变更记录 |

## 本地开发

```bash
# Clone
git clone https://github.com/algo23-yunqingtian/nickel-dashboard.git

# Push
git add -A && git commit -m "描述" && git push origin main
```
