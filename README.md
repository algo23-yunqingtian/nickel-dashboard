# 镍(Ni)产业看板 v3.0

Dark ECharts 高密度独立页面，数据由 GitHub Actions 每 4 小时自动更新。

## 访问地址

👉 https://algo23-yunqingtian.github.io/nickel-dashboard/

## 结构

| 文件/目录 | 说明 |
|-----------|------|
| `index.html` | 主看板页面 |
| `static/` | CSS/JS 资源 |
| `data.json` | 数据源（Actions 更新） |
| `fetch_data.py` | 数据抓取脚本 |
| `.github/workflows/fetch.yml` | 定时数据更新（每 4h） |
| `docs/` | 文档（协作规范、变更日志） |

## 协作

两个 Hermes Agent 共同维护本仓库，详见 [协作规范](docs/collaboration.md)。

- **微信端**: 数据管道（fetch_data.py, data.json, workflow）
- **飞书端**: 前端（index.html, CSS, 图表）

## 技术栈

- 纯静态 HTML + ECharts 5
- GitHub Pages 托管
- GitHub Actions 定时数据更新
- 数据源：Zhiji API + SMM + SiliconFlow AI
