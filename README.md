# Nickel Dashboard (镍产业看板)

实时镍期货产业数据看板，数据源为 Zhiji API + akshare。

## 部署

- **在线访问**: GitHub Pages (main 分支)
- **数据更新**: GitHub Actions 每 4 小时自动运行

## 配置 (仓库 Settings → Secrets)

| Secret | 说明 |
|---|---|
| `ZHJI_KEY` | Zhiji API 访问密钥 |
| `SILICONFLOW_KEY` | SiliconFlow API Key（AI 解盘，可选） |

## 本地测试

```bash
pip install -r requirements.txt
python fetch_data.py
# 用任意静态服务器打开 index.html
python3 -m http.server 8080
```

## 目录结构

```
├── index.html          # 主页面
├── static/
│   ├── style.css       # 样式
│   └── charts.js       # 图表逻辑 (读取 data.json)
├── fetch_data.py       # 数据抓取脚本 (GitHub Actions)
├── data.json           # 生成的数据文件
└── .github/workflows/
    └── fetch.yml       # 定时任务
```
