#!/usr/bin/env python3
"""
Nickel real-time AI analyzer module.
Reads data.json + fetches news -> builds prompt -> calls AI -> returns analysis.
"""
import json, os, re, sqlite3, urllib.request, urllib.parse, socket
from datetime import datetime

# Force IPv4 — dashscope IPv6 endpoint times out
_original_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(*args, **kwargs):
    results = _original_getaddrinfo(*args, **kwargs)
    return [r for r in results if r[0] == socket.AF_INET]
socket.getaddrinfo = _ipv4_only_getaddrinfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, "data.json")
GH_STATIC_DATA = "/home/ubuntu/nickel_gh_static/data.json"

DASHSCOPE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
DASHSCOPE_MODEL = "qwen3.7-max"

ZSUN_URL = "https://zsun.funkits.cn/v1/chat/completions"
ZSUN_MODEL = "Qwen36_35B"

def load_data():
    # Priority: gh_static (synced from GH Actions, has real data) > local data.json
    for path in [GH_STATIC_DATA, DATA_JSON]:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return None

# ── News fetching ──
_EXCLUDE = ['SHFE夜盘收盘','LME夜盘收盘','SHFE最新','LME库存','LME注销仓单',
    'LME现货结算','SHFE.*仓单','上期所基本金属仓单','LME金属技术策略',
    'SHFE夜盘开盘','SHFE开盘_基本','SHFE收盘_基本','本周均价','镍现货报价',
    '金川集团电解镍出厂','镍钴中间品价格']
def fetch_news():
    """Get recent nickel-related news — Zhiji 讯服务 (实时) + 本地DB (补充)"""
    items = []

    # 0. 优先从 Zhiji 讯服务拉取（最新、最全、实时）
    NEWS_BASE = "https://zhiji-ai.xyz/news/api"
    env_keys = _load_env_keys()
    news_key = env_keys.get("NEWS_KEY", "")
    if news_key:
        try:
            import urllib.request as _ur
            url = f"{NEWS_BASE}/search?q={urllib.parse.quote('镍')}&hours=48&limit=30&source=all"
            req = _ur.Request(url, headers={"X-News-Key": news_key, "User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(req, timeout=10) as resp:
                zhiji_news = json.loads(resp.read())
            if zhiji_news and isinstance(zhiji_news, dict) and "items" in zhiji_news:
                source_map = {"jin10":"金十","cls":"财联社","sina":"新浪","smm":"上海有色网","x":"X"}
                for n in zhiji_news["items"]:
                    content = n.get("content", "")
                    if any(re.search(p, content) for p in _EXCLUDE):
                        continue
                    title = n.get("title", "")[:80]
                    if not title:
                        continue
                    src_name = source_map.get(n.get("source","all"), n.get("source",""))
                    level = "A" if n.get("importance", 0) == 1 else ("A" if any(k in content for k in ['LME','库存','产量','检修','配额','印尼','关税','不锈钢','排产']) else "B")
                    items.append({
                        "title": title,
                        "body": content[:200],
                        "source": src_name,
                        "time": n.get("time","")[:19],
                        "level": level,
                        "score": 8 if level == "A" else 6,
                        "url": n.get("url", ""),
                    })
                print(f"  [analyze] Zhiji news: {len(items)} items")
        except Exception as e:
            print(f"  [analyze] Zhiji news failed: {e}")

    # 1. 本地DB补充（SMM日报缓存，作为 fallback）
    if len(items) < 10:
        try:
            conn = sqlite3.connect(NICKEL_DB)
            c = conn.cursor()
            c.execute("SELECT date, content, source FROM news_nickel_scored WHERE date >= date('now', '-7 days') ORDER BY date DESC LIMIT 20")
            for row in c.fetchall():
                ts, content, source = row
                tier = 'A' if any(k in content for k in ['LME','库存','产量','检修','配额','印尼','关税','不锈钢','排产']) else ('B' if any(k in content for k in ['利润','开工','加工费','进口','出口']) else 'C')
                m = re.search(r'【([^】]+)】', content)
                if m:
                    title, body = m.group(1), content[m.end():].strip()[:200]
                else:
                    title, body = content[:60], content[60:].strip()[:200]
                title = title.replace('SHMET','').replace('上海金属网','').strip()
                if not title or title == '快讯':
                    continue
                if any(re.search(p, content) for p in _EXCLUDE):
                    continue
                # 去重：如果 Zhiji 已有相似标题则跳过
                if not any(title[:10] in x["title"] for x in items):
                    items.append({
                        "title": title[:80],
                        "body": body,
                        "source": source or "SMM",
                        "time": ts[:19] if ts else "",
                        "level": tier,
                        "score": 8 if tier == 'A' else (6 if tier == 'B' else 4),
                    })
            conn.close()
        except Exception as e:
            if not items:
                items = [{"title":"新闻获取失败","body":str(e)[:100],"source":"系统","time":datetime.now().strftime("%Y-%m-%d %H:%M"),"level":"C"}]

    return items[:20]

def fetch_reports():
    """期货公司研报观点 — 从本地DB或快速API获取，不阻塞AI分析"""
    reports = []
    # Skip akshare direct call (blocks HTTPServer single thread)
    # Read from local DB news table as a fallback
    try:
        conn = sqlite3.connect(NICKEL_DB)
        c = conn.cursor()
        c.execute("SELECT date, content FROM news_nickel_scored WHERE score >= 8 ORDER BY score DESC LIMIT 5")
        for row in c.fetchall():
            ts, content = row
            m = re.search(r'【([^】]+)】', content)
            if m:
                title = m.group(1).replace('SHMET','').replace('上海金属网','').strip()
                body = content[m.end():].strip()[:200]
                if any(k in content for k in ['策略','研报','推荐','看好','看空','目标价']):
                    reports.append({"title":title,"body":body,"time":ts[:19],"source":"DB"})
        conn.close()
    except Exception:
        pass
    return reports[:5]

# ── Data extraction helpers ──
def last_val(pts):
    if isinstance(pts, list) and pts:
        for p in reversed(pts):
            if p.get("value") is not None:
                return round(p["value"], 2)
    return None

def gv(chart_key, sub_key=None, charts=None):
    if charts is None:
        return (None, [])
    c = charts.get(chart_key, [])
    if sub_key and isinstance(c, dict):
        pts = c.get(sub_key, []) or []  # Handle null JSON values
    else:
        pts = c if isinstance(c, list) else []
    recent = [p["value"] for p in pts[-5:] if p.get("value") is not None][-5:]
    lv = recent[-1] if recent else None
    return (lv, recent)

def fmt(v, unit="", suffix=""):
    if v is not None:
        return f"{v:,.0f}{unit}{suffix}"
    return "N/A"

def trend_str(t):
    if len(t) >= 3:
        d = t[-1] - t[0]
        return f"{'↑' if d>0 else '↓'}{abs(d):,.0f}"
    return "—"

# ── Build prompt from data ──
def build_prompt(charts, news, reports):
    nl = "\n".join(f"[{n.get('level','C')}] {n.get('title','')} ({n.get('source','')} {n.get('time','')})" for n in (news or [])[:15])
    rp = "\n".join(f"[研报] {r.get('title','')}: {r.get('body','')[:100]} ({r.get('time','')})" for r in (reports or [])[:8])

    # 提取18个指标
    a1_inv, a1_inv_t = gv("A1_lme_inventory", "inventory", charts)
    a1_reg, _ = gv("A1_lme_inventory", "registered", charts)
    a1_canc, _ = gv("A1_lme_inventory", "cancelled", charts)
    a2_ratio, a2_ratio_t = gv("A2_import_window", "shfe_lme_ratio", charts)
    a2_magma, _ = gv("A2_import_window", "magma_discount", charts)
    a2_npi, _ = gv("A2_import_window", "indonesia_npi_rate", charts)
    a3_bean, _ = gv("A3_substitution", "nickel_bean", charts)
    a3_shfe, _ = gv("A3_substitution", "shfe_settle", charts)
    a4_profit, a4_profit_t = gv("A4_smelting_pressure", "profit", charts)
    a4_inv18, _ = gv("A4_smelting_pressure", "inv_18", charts)
    a4_inv27, _ = gv("A4_smelting_pressure", "inv_27", charts)
    a4_bean, _ = gv("A4_smelting_pressure", "bean_inv", charts)
    b1, b1_t = gv("B1_shfe_price", charts=charts)
    b2, b2_t = gv("B2_lme_price", charts=charts)
    b3, b3_t = gv("B3_shfe_oi", charts=charts)
    b4, b4_t = gv("B4_ratio", charts=charts)
    b5_18, b5_18_t = gv("B5_china_inventory", "inv_18", charts)
    b5_27, b5_27_t = gv("B5_china_inventory", "inv_27", charts)
    b6, b6_t = gv("B6_bean_inventory", charts=charts)
    b7, b7_t = gv("B7_smelting_profit", charts=charts)
    b8_prod, _ = gv("B8_china_production", "chinese_prod", charts)
    b8_cap, _ = gv("B8_china_production", "chinese_cap", charts)
    b9_prod, _ = gv("B9_indonesia", "indonesia_prod", charts)
    b9_cap, _ = gv("B9_indonesia", "indonesia_cap", charts)
    b9_rate, b9_rate_t = gv("B9_indonesia", "indonesia_rate", charts)
    b10, b10_t = gv("B10_sulfate_price", charts=charts)
    b11_out, _ = gv("B11_lme_flow", "outflow", charts)
    b11_in, _ = gv("B11_lme_flow", "inflow", charts)
    b12, b12_t = gv("B12_apparent_consumption", charts=charts)
    b13_pos, _ = gv("B13_lme_funding", "position", charts)
    b13_fl, _ = gv("B13_lme_funding", "fund_long", charts)
    b13_cl, _ = gv("B13_lme_funding", "comm_long", charts)
    b13_cs, _ = gv("B13_lme_funding", "comm_short", charts)
    b14_cr, b14_cr_t = gv("B14_stainless", "cold_rolling", charts)

    prompt = f"""你是一位专业的镍(Ni)期货分析师。请根据以下数据，按【6步框架】给出实时解盘。

## 一、输入数据（18个Chart）

### 基准价格
- SHFE镍价: {fmt(b1,"元/吨")}（近5日:{b1_t}，变化:{trend_str(b1_t)}）
- LME镍价: {fmt(b2,"美元/吨")}（近5日:{b2_t}，变化:{trend_str(b2_t)}）
- 沪伦比: {fmt(b4,"")}（近5日:{b4_t}）
- 镍豆/SHFE结算: {fmt(a3_bean,"元/吨")} / {fmt(a3_shfe,"元/吨")}

### LME库存与仓单
- LME总库存: {fmt(a1_inv,"吨")}（变化:{trend_str(a1_inv_t)}）
- 注册仓单: {fmt(a1_reg,"吨")} | 注销仓单: {fmt(a1_canc,"吨")}
- LME流入: {fmt(b11_in,"吨")} | 流出: {fmt(b11_out,"吨")}

### 国内库存
- 18家仓库: {fmt(b5_18,"吨")}（变化:{trend_str(b5_18_t)}）
- 27家仓库: {fmt(b5_27,"吨")}（变化:{trend_str(b5_27_t)}）
- 镍豆库存: {fmt(b6,"吨")}（变化:{trend_str(b6_t)}）

### 冶炼与供给
- 冶炼利润: {fmt(b7,"元/吨")}（变化:{trend_str(b7_t)}）
- 中国产量: {fmt(b8_prod,"吨/月")} | 产能: {fmt(b8_cap,"吨/月")} | 开工率: {fmt(b9_rate,"%")}
- 印尼产量: {fmt(b9_prod,"吨/月")} | 产能: {fmt(b9_cap,"吨/月")}
- 印尼NPI税率: {fmt(a2_npi,"%")} | 镍镁差: {fmt(a2_magma,"")}

### 需求侧
- 表观消费: {fmt(b12,"吨/月")}（变化:{trend_str(b12_t)}）
- 硫酸镍价格: {fmt(b10,"元/吨")}
- 不锈钢冷轧排产: {fmt(b14_cr,"吨")}（变化:{trend_str(b14_cr_t)}）

### 资金面
- SHFE持仓: {fmt(b3,"手")}（变化:{trend_str(b3_t)}）
- LME持仓: {fmt(b13_pos,"手")} | 基金多头: {fmt(b13_fl,"手")}
- 商业多头: {fmt(b13_cl,"手")} | 商业空头: {fmt(b13_cs,"手")}

### 产业资讯
{nl}

### 研报观点
{rp if rp else "暂无研报观点"}

## 二、分析流程（思维链·内部完成）

### 第1步：信号分类
将上方18个指标逐一归类为利多或利空信号，标注强弱（强/中/弱）。

### 第2步：权重打分
- 供给端（冶炼利润、产量、开工率）：权重 35%
- 库存端（LME、国内18/27家、镍豆）：权重 25%
- 需求端（表观消费、不锈钢排产、硫酸镍）：权重 20%
- 资金端（SHFE/LME持仓、期比）：权重 15%
- 资讯端（新闻+研报观点）：权重 5%
→ 计算多空加权总分，得出方向判断。

### 第3步：核心矛盾识别
找出当前权重最高且边际变化最大的1-2个矛盾点。

### 第4步：因果推演
从核心矛盾出发，推导价格传导链条（指标→供需→价格→资金反应）。

### 第5步：交叉验证
用其他指标验证核心矛盾方向是否一致，标记冲突信号。

**以上步骤在内部完成，不输出中间过程。**

## 三、最终输出（结构化研报，面向客户）

**【结论】**偏多/偏空/中性（一句话概括行情阶段+核心矛盾，20字以内）

**【核心矛盾】**当前最核心的供需矛盾是什么，用数据支撑（1-2条，每条50字以内）

**【多空对比】**
- 利多：信号1（强度·验证状态）；信号2（强度·验证状态）
- 利空：信号1（强度·验证状态）；信号2（强度·验证状态）

**【风险】**3-5条具体证伪路径（"若X发生→Y逻辑被证伪→价格方向"，每条40字以内）

**【建议】**方向 + 关键价位（支撑/阻力） + 确认条件 + 止损触发

**【资讯与研报】**从上方产业资讯和研报观点中提炼3-5条最核心的信息，每条格式：`[事件/观点] → [影响方向] → [对镍价影响]`，控制在3句话以内。

## 四、硬约束
1. 所有数据必须来自输入，禁止编造
2. 明确给出"偏多/偏空/中性"判断，禁止模棱两可
3. N/A的数据标注"缺失"，不要推测
4. 每条风险必须有具体触发条件
5. 结论与多空信号方向必须一致
6. 输出控制在800字以内"""
    return prompt

# ── Call AI (DashScope primary, ZSUN fallback) ──
def _load_env_keys():
    keys = {}
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    keys[k.strip()] = v.strip().strip('"').strip("'")
    return keys

def call_ai(prompt, key):
    # Try DashScope (阿里百炼) first — stable, persistent token
    env_keys = _load_env_keys()
    dash_key = env_keys.get("DASHSCOPE_KEY", "")
    dash_model = env_keys.get("DASHSCOPE_MODEL", DASHSCOPE_MODEL)
    
    if dash_key:
        try:
            payload = {"model": dash_model, "messages": [
                {"role":"system","content":"你是专业镍期货分析师，输出结构化研报，面向客户展示。"},
                {"role":"user","content": prompt}
            ], "max_tokens": 4096, "temperature": 0.7}
            req = urllib.request.Request(DASHSCOPE_URL, data=json.dumps(payload).encode(),
                headers={"Content-Type":"application/json","Authorization": f"Bearer {dash_key}"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            msg = result["choices"][0]["message"]
            # reasoning models (qwen3.x) may put text in reasoning_content
            content = msg.get("content") or msg.get("reasoning_content") or ""
            return {
                "content": content,
                "model": dash_model,
                "usage": result.get("usage", {}),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "provider": "dashscope"
            }
        except Exception as e:
            print(f"[analyze.py] DashScope failed: {e}, falling back to zsun")
    
    # Fallback: zsun.funkits.cn
    zsun_key = key or env_keys.get("ZSUN_KEY", "")
    payload = {"model": ZSUN_MODEL, "messages": [
        {"role":"system","content":"你是专业镍期货分析师，输出结构化研报，面向客户展示。"},
        {"role":"user","content": prompt}
    ], "max_tokens": 1500, "temperature": 0.7}
    req = urllib.request.Request(ZSUN_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","Authorization": f"Bearer {zsun_key}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    msg = result["choices"][0]["message"]
    content = msg.get("content") or msg.get("reasoning_content") or ""
    return {
        "content": content,
        "model": ZSUN_MODEL,
        "usage": result.get("usage", {}),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provider": "zsun"
    }

# ── Main entry: generate full real-time analysis ──
def analyze(key):
    data = load_data()
    if not data:
        return {"error": "无法加载 data.json 数据"}
    charts = data.get("charts", {})
    news = fetch_news()
    reports = fetch_reports()
    prompt = build_prompt(charts, news, reports)
    ai_result = call_ai(prompt, key)
    # 提取方向
    content = ai_result["content"]
    ai_dir = "偏多" if "偏多" in content[:300] else ("偏空" if "偏空" in content[:300] else ("中性" if "中性" in content[:300] else "未知"))
    return {
        "ai_analysis": content,
        "ai_direction": ai_dir,
        "news": news[:15],
        "reports": reports[:8],
        "model": ai_result["model"],
        "usage": ai_result["usage"],
        "timestamp": ai_result["timestamp"],
        "prompt": prompt
    }
