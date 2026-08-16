#!/usr/bin/env python3
"""
Nickel real-time AI analyzer module.
Reads data.json + fetches news -> builds prompt -> calls AI -> returns analysis.
"""
import json, os, re, sys, sqlite3, urllib.request, urllib.parse, socket
from datetime import datetime

# 统一新闻打分模块 (scorer v2 + 相关性闸门)
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scorer_v2

# Force IPv4 — dashscope IPv6 endpoint times out
_original_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(*args, **kwargs):
    results = _original_getaddrinfo(*args, **kwargs)
    return [r for r in results if r[0] == socket.AF_INET]
socket.getaddrinfo = _ipv4_only_getaddrinfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, "data.json")
GH_STATIC_DATA = "/home/ubuntu/nickel_gh_static/data.json"
NICKEL_DB = "/home/ubuntu/analysis/nickel_v1.db"

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

# ── News filtering ──
# 低优先级噪音：收盘/开盘/报价/技术面总结（基本面无价值）
_EXCLUDE_NOISE = ['SHFE夜盘收盘','LME夜盘收盘','SHFE最新','LME库存','LME注销仓单',
    'LME现货结算','SHFE.*仓单','上期所基本金属仓单','LME金属技术策略',
    'SHFE夜盘开盘','SHFE开盘_基本','SHFE收盘_基本','本周均价','镍现货报价',
    '金川集团电解镍出厂','镍钴中间品价格',
    # 盘后走势总结/技术面分析（与基本面关系极小）
    '收盘总结','走势总结','盘后总结','日度回顾','周度回顾','月度回顾',
    '技术面','技术形态','均线','MACD','KDJ','RSI','布林','金叉','死叉',
    '支撑位','压力位','突破','回落','反弹','震荡整理','多空博弈']
# 高权重关键词（印尼政策/配额等，历史新闻也要保留）
_HIGH_WEIGHT_KW = ['印尼','RKAB','配额','出口税','出口政策','禁矿令','NPI税率',
    '罢工','停产','事故','制裁','关税','海关','环保督查','限产','产能']
# 重要基本面关键词
_BASIC_KW = ['LME','库存','产量','检修','配额','印尼','关税','不锈钢','排产',
    '冶炼','精炼','镍矿','红土镍','MHP','高冰镍','镍铁','硫酸镍',
    '表观消费','进出口','进口盈亏','仓单','注册','注销',
    '新能源','电池','锂电','宁德时代','比亚迪','特斯拉',
    '基金持仓','持仓','多头','空头','期现','基差','进口']
def fetch_news():
    """Get recent nickel-related news — 统一 scorer v2 打分 (与 fetch_data.py 同一标准)
    结构: title/body/source/time/level/score/url/direction/relevant/contradictions/matched_terms"""
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
                    if scorer_v2.is_noise(content):
                        continue
                    title = n.get("title", "")[:80]
                    if not title:
                        continue
                    src_name = source_map.get(n.get("source","all"), n.get("source",""))
                    items.append(scorer_v2.build_entry(
                        title, content, src_name,
                        n.get("time",""), n.get("url","")))
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
                m = re.search(r'【([^】]+)】', content)
                if m:
                    title, body = m.group(1), content[m.end():].strip()[:200]
                else:
                    title, body = content[:60], content[60:].strip()[:200]
                title = title.replace('SHMET','').replace('上海金属网','').strip()
                if not title or title == '快讯':
                    continue
                if scorer_v2.is_noise(content):
                    continue
                # 去重：如果 Zhiji 已有相似标题则跳过（用 Jaccard 相似度）
                def _similar(t1, t2):
                    s1 = set(t1)
                    s2 = set(t2)
                    if not s2:
                        return False
                    return len(s1 & s2) / len(s1 | s2) > 0.6
                if not any(_similar(title, x["title"]) for x in items):
                    items.append(scorer_v2.build_entry(
                        title[:80], content, source or "SMM",
                        ts[:19] if ts else ""))
            conn.close()
        except Exception as e:
            if not items:
                items = [{"title":"新闻获取失败","body":str(e)[:100],"source":"系统","time":datetime.now().strftime("%Y-%m-%d %H:%M"),"level":"C","score":0}]

    return items[:20]

def fetch_reports():
    """研报/策略观点 — Zhiji 讯服务(实时) + 本地DB(fallback)"""
    reports = []

    # 0. 优先从 Zhiji 讯服务拉取研报类资讯
    try:
        NEWS_BASE = "https://zhiji-ai.xyz/news/api"
        env_keys = _load_env_keys()
        news_key = env_keys.get("NEWS_KEY", "")
        if news_key:
            import urllib.request as _ur
            for q in ["镍 策略", "镍 研报", "精炼镍 展望", "镍期货 分析"]:
                if len(reports) >= 5:
                    break
                url = f"{NEWS_BASE}/search?q={urllib.parse.quote(q)}&hours=72&limit=5&source=all"
                req = _ur.Request(url, headers={"X-News-Key": news_key, "User-Agent": "Mozilla/5.0"})
                with _ur.urlopen(req, timeout=8) as resp:
                    zhiji_res = json.loads(resp.read())
                if zhiji_res and isinstance(zhiji_res, dict) and "items" in zhiji_res:
                    seen = {r["title"] for r in reports}
                    for n in zhiji_res["items"]:
                        title = n.get("title", "")[:80]
                        if not title or title in seen:
                            continue
                        content = n.get("content", "")
                        if not any(k in content for k in ['策略','研报','推荐','看好','看空','目标价','展望','趋势','建议','多空','方向']):
                            continue
                        reports.append({
                            "title": title,
                            "body": content[:200],
                            "time": n.get("time", "")[:19],
                            "source": "研报"
                        })
                        seen.add(title)
            print(f"  [analyze] Zhiji reports: {len(reports)} items")
    except Exception as e:
        print(f"  [analyze] Zhiji reports failed: {e}")

    # 1. 本地DB补充（SMM高分新闻作为 fallback）
    if len(reports) < 5:
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
                        if title not in {r["title"] for r in reports}:
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
    # 新闻新鲜度标注：计算每条新闻距今多少小时
    def _age_hours(time_str):
        if not time_str:
            return "?"
        try:
            # 支持 "2026-08-15 14:30:00" 或 "2026-08-15T14:30:00"
            ts = time_str.replace("T", " ")[:16]
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
            diff = (datetime.now() - dt).total_seconds() / 3600
            return f"{diff:.0f}h" if diff < 24 else f"{diff/24:.1f}d"
        except Exception:
            return "?"

    nl = "\n".join(f"[{n.get('level','C')}] {n.get('title','')} ({n.get('source','')} | {n.get('time','')} | 距今{_age_hours(n.get('time',''))})" for n in (news or [])[:15])
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

    # ── 动态权重调整 ──
    def _volatility(vals):
        """近5日波动率"""
        if len(vals) < 3:
            return 0
        avg = sum(vals) / len(vals)
        if avg == 0:
            return 0
        return (sum((v - avg) ** 2 for v in vals) / len(vals)) ** 0.5 / abs(avg)

    supply_vol = _volatility(b7_t) + _volatility(b9_rate_t)
    inventory_vol = _volatility(a1_inv_t) + _volatility(b5_18_t)
    demand_vol = _volatility(b12_t) + _volatility(b14_cr_t)
    capital_vol = _volatility(b3_t) if b3_t else 0

    max_vol = max(supply_vol, inventory_vol, demand_vol, capital_vol, 0.001)
    w_supply = max(20, min(45, int(35 + (supply_vol / max_vol - 0.5) * 15)))
    w_inventory = max(15, min(35, int(25 + (inventory_vol / max_vol - 0.5) * 15)))
    w_demand = max(10, min(30, int(20 + (demand_vol / max_vol - 0.5) * 10)))
    w_capital = max(5, min(25, int(15 + (capital_vol / max_vol - 0.5) * 15)))
    w_info = max(5, 100 - w_supply - w_inventory - w_demand - w_capital)

    weight_note = f"当前动态权重：供给{w_supply}% | 库存{w_inventory}% | 需求{w_demand}% | 资金{w_capital}% | 资讯{w_info}%"

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
{weight_note}
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
