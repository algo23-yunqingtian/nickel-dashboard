1|#!/usr/bin/env python3
2|"""
3|Nickel real-time AI analyzer module.
4|Reads data.json + fetches news -> builds prompt -> calls AI -> returns analysis.
5|"""
6|import json, os, re, sqlite3, urllib.request, urllib.parse
7|from datetime import datetime
8|
9|BASE_DIR = os.path.dirname(os.path.abspath(__file__))
10|DATA_JSON = os.path.join(BASE_DIR, "data.json")
11|GH_STATIC_DATA = "/home/ubuntu/nickel_gh_static/data.json"
12|
13|ZSUN_URL = "https://zsun.funkits.cn/v1/chat/completions"
14|ZSUN_MODEL = "Qwen36"
15|
16|def load_data():
17|    # Priority: gh_static (synced from GH Actions, has real data) > local data.json
18|    for path in [GH_STATIC_DATA, DATA_JSON]:
19|        if os.path.exists(path):
20|            with open(path) as f:
21|                return json.load(f)
22|    return None
23|
24|# ── News fetching ──
25|_EXCLUDE = ['SHFE夜盘收盘','LME夜盘收盘','SHFE最新','LME库存','LME注销仓单',
26|    'LME现货结算','SHFE.*仓单','上期所基本金属仓单','LME金属技术策略',
27|    'SHFE夜盘开盘','SHFE开盘_基本','SHFE收盘_基本','本周均价','镍现货报价',
28|    '金川集团电解镍出厂','镍钴中间品价格']
29|
30|NICKEL_DB = "/home/ubuntu/analysis/nickel_v1.db"
31|
32|def fetch_news():
33|    """从 nickel_v1.db 读取评分后的新闻，替代 akshare 直抓。"""
34|    items = []
35|    try:
36|        conn = sqlite3.connect(NICKEL_DB)
37|        c = conn.cursor()
38|        c.execute("SELECT date, content, score, tier, matched_terms, source FROM news_nickel_scored ORDER BY score DESC, date DESC LIMIT 20")
39|        for row in c.fetchall():
40|            ts, content, score, tier, matched, source = row
41|            # 用 【】 解析 title + body
42|            m = re.search(r'【([^】]+)】', content)
43|            if m:
44|                title, body = m.group(1), content[m.end():].strip()[:200]
45|            else:
46|                title, body = content[:60], content[60:].strip()[:200]
47|            title = title.replace('SHMET','').replace('上海金属网','').strip()
48|            if not title or title == '快讯':
49|                continue
50|            # 二次排除看板不想显示的
51|            if any(re.search(p, content) for p in _EXCLUDE):
52|                continue
53|            items.append({
54|                "title": title[:80],
55|                "body": body,
56|                "source": source or "SMM",
57|                "time": ts[:19] if ts else "",
58|                "level": tier,
59|                "score": score,
60|            })
61|        conn.close()
62|    except Exception as e:
63|        items = [{"title":"新闻获取失败","body":str(e)[:100],"source":"系统","time":datetime.now().strftime("%Y-%m-%d %H:%M"),"level":"C"}]
64|    return items[:20]
65|
66|def fetch_reports():
67|    """期货公司研报观点 — 从本地DB或快速API获取，不阻塞AI分析"""
68|    reports = []
69|    # Skip akshare direct call (blocks HTTPServer single thread)
70|    # Read from local DB news table as a fallback
71|    try:
72|        conn = sqlite3.connect(NICKEL_DB)
73|        c = conn.cursor()
74|        c.execute("SELECT date, content FROM news_nickel_scored WHERE score >= 8 ORDER BY score DESC LIMIT 5")
75|        for row in c.fetchall():
76|            ts, content = row
77|            m = re.search(r'【([^】]+)】', content)
78|            if m:
79|                title = m.group(1).replace('SHMET','').replace('上海金属网','').strip()
80|                body = content[m.end():].strip()[:200]
81|                if any(k in content for k in ['策略','研报','推荐','看好','看空','目标价']):
82|                    reports.append({"title":title,"body":body,"time":ts[:19],"source":"DB"})
83|        conn.close()
84|    except Exception:
85|        pass
86|    return reports[:5]
87|
88|# ── Data extraction helpers ──
89|def last_val(pts):
90|    if isinstance(pts, list) and pts:
91|        for p in reversed(pts):
92|            if p.get("value") is not None:
93|                return round(p["value"], 2)
94|    return None
95|
96|def gv(chart_key, sub_key=None, charts=None):
97|    if charts is None:
98|        return (None, [])
99|    c = charts.get(chart_key, [])
100|    if sub_key and isinstance(c, dict):
101|        pts = c.get(sub_key, []) or []  # Handle null JSON values
102|    else:
103|        pts = c if isinstance(c, list) else []
104|    recent = [p["value"] for p in pts[-5:] if p.get("value") is not None][-5:]
105|    lv = recent[-1] if recent else None
106|    return (lv, recent)
107|
108|def fmt(v, unit="", suffix=""):
109|    if v is not None:
110|        return f"{v:,.0f}{unit}{suffix}"
111|    return "N/A"
112|
113|def trend_str(t):
114|    if len(t) >= 3:
115|        d = t[-1] - t[0]
116|        return f"{'↑' if d>0 else '↓'}{abs(d):,.0f}"
117|    return "—"
118|
119|# ── Build prompt from data ──
120|def build_prompt(charts, news, reports):
121|    nl = "\n".join(f"[{n.get('level','C')}] {n.get('title','')} ({n.get('source','')} {n.get('time','')})" for n in (news or [])[:15])
122|    rp = "\n".join(f"[研报] {r.get('title','')}: {r.get('body','')[:100]} ({r.get('time','')})" for r in (reports or [])[:8])
123|
124|    # 提取18个指标
125|    a1_inv, a1_inv_t = gv("A1_lme_inventory", "inventory", charts)
126|    a1_reg, _ = gv("A1_lme_inventory", "registered", charts)
127|    a1_canc, _ = gv("A1_lme_inventory", "cancelled", charts)
128|    a2_ratio, a2_ratio_t = gv("A2_import_window", "shfe_lme_ratio", charts)
129|    a2_magma, _ = gv("A2_import_window", "magma_discount", charts)
130|    a2_npi, _ = gv("A2_import_window", "indonesia_npi_rate", charts)
131|    a3_bean, _ = gv("A3_substitution", "nickel_bean", charts)
132|    a3_shfe, _ = gv("A3_substitution", "shfe_settle", charts)
133|    a4_profit, a4_profit_t = gv("A4_smelting_pressure", "profit", charts)
134|    a4_inv18, _ = gv("A4_smelting_pressure", "inv_18", charts)
135|    a4_inv27, _ = gv("A4_smelting_pressure", "inv_27", charts)
136|    a4_bean, _ = gv("A4_smelting_pressure", "bean_inv", charts)
137|    b1, b1_t = gv("B1_shfe_price", charts=charts)
138|    b2, b2_t = gv("B2_lme_price", charts=charts)
139|    b3, b3_t = gv("B3_shfe_oi", charts=charts)
140|    b4, b4_t = gv("B4_ratio", charts=charts)
141|    b5_18, b5_18_t = gv("B5_china_inventory", "inv_18", charts)
142|    b5_27, b5_27_t = gv("B5_china_inventory", "inv_27", charts)
143|    b6, b6_t = gv("B6_bean_inventory", charts=charts)
144|    b7, b7_t = gv("B7_smelting_profit", charts=charts)
145|    b8_prod, _ = gv("B8_china_production", "chinese_prod", charts)
146|    b8_cap, _ = gv("B8_china_production", "chinese_cap", charts)
147|    b9_prod, _ = gv("B9_indonesia", "indonesia_prod", charts)
148|    b9_cap, _ = gv("B9_indonesia", "indonesia_cap", charts)
149|    b9_rate, b9_rate_t = gv("B9_indonesia", "indonesia_rate", charts)
150|    b10, b10_t = gv("B10_sulfate_price", charts=charts)
151|    b11_out, _ = gv("B11_lme_flow", "outflow", charts)
152|    b11_in, _ = gv("B11_lme_flow", "inflow", charts)
153|    b12, b12_t = gv("B12_apparent_consumption", charts=charts)
154|    b13_pos, _ = gv("B13_lme_funding", "position", charts)
155|    b13_fl, _ = gv("B13_lme_funding", "fund_long", charts)
156|    b13_cl, _ = gv("B13_lme_funding", "comm_long", charts)
157|    b13_cs, _ = gv("B13_lme_funding", "comm_short", charts)
158|    b14_cr, b14_cr_t = gv("B14_stainless", "cold_rolling", charts)
159|
160|    prompt = f"""你是一位专业的镍(Ni)期货分析师。请根据以下数据，按【6步框架】给出实时解盘。
161|
162|## 一、输入数据（18个Chart）
163|
164|### 基准价格
165|- SHFE镍价: {fmt(b1,"元/吨")}（近5日:{b1_t}，变化:{trend_str(b1_t)}）
166|- LME镍价: {fmt(b2,"美元/吨")}（近5日:{b2_t}，变化:{trend_str(b2_t)}）
167|- 沪伦比: {fmt(b4,"")}（近5日:{b4_t}）
168|- 镍豆/SHFE结算: {fmt(a3_bean,"元/吨")} / {fmt(a3_shfe,"元/吨")}
169|
170|### LME库存与仓单
171|- LME总库存: {fmt(a1_inv,"吨")}（变化:{trend_str(a1_inv_t)}）
172|- 注册仓单: {fmt(a1_reg,"吨")} | 注销仓单: {fmt(a1_canc,"吨")}
173|- LME流入: {fmt(b11_in,"吨")} | 流出: {fmt(b11_out,"吨")}
174|
175|### 国内库存
176|- 18家仓库: {fmt(b5_18,"吨")}（变化:{trend_str(b5_18_t)}）
177|- 27家仓库: {fmt(b5_27,"吨")}（变化:{trend_str(b5_27_t)}）
178|- 镍豆库存: {fmt(b6,"吨")}（变化:{trend_str(b6_t)}）
179|
180|### 冶炼与供给
181|- 冶炼利润: {fmt(b7,"元/吨")}（变化:{trend_str(b7_t)}）
182|- 中国产量: {fmt(b8_prod,"吨/月")} | 产能: {fmt(b8_cap,"吨/月")} | 开工率: {fmt(b9_rate,"%")}
183|- 印尼产量: {fmt(b9_prod,"吨/月")} | 产能: {fmt(b9_cap,"吨/月")}
184|- 印尼NPI税率: {fmt(a2_npi,"%")} | 镍镁差: {fmt(a2_magma,"")}
185|
186|### 需求侧
187|- 表观消费: {fmt(b12,"吨/月")}（变化:{trend_str(b12_t)}）
188|- 硫酸镍价格: {fmt(b10,"元/吨")}
189|- 不锈钢冷轧排产: {fmt(b14_cr,"吨")}（变化:{trend_str(b14_cr_t)}）
190|
191|### 资金面
192|- SHFE持仓: {fmt(b3,"手")}（变化:{trend_str(b3_t)}）
193|- LME持仓: {fmt(b13_pos,"手")} | 基金多头: {fmt(b13_fl,"手")}
194|- 商业多头: {fmt(b13_cl,"手")} | 商业空头: {fmt(b13_cs,"手")}
195|
196|### 产业资讯
197|{nl}
198|
199|### 研报观点
200|{rp if rp else "暂无研报观点"}
201|
202|## 二、分析流程（思维链·内部完成）
203|
204|### 第1步：信号分类
205|将上方18个指标逐一归类为利多或利空信号，标注强弱（强/中/弱）。
206|
207|### 第2步：权重打分
208|- 供给端（冶炼利润、产量、开工率）：权重 35%
209|- 库存端（LME、国内18/27家、镍豆）：权重 25%
210|- 需求端（表观消费、不锈钢排产、硫酸镍）：权重 20%
211|- 资金端（SHFE/LME持仓、期比）：权重 15%
212|- 资讯端（新闻+研报观点）：权重 5%
213|→ 计算多空加权总分，得出方向判断。
214|
215|### 第3步：核心矛盾识别
216|找出当前权重最高且边际变化最大的1-2个矛盾点。
217|
218|### 第4步：因果推演
219|从核心矛盾出发，推导价格传导链条（指标→供需→价格→资金反应）。
220|
221|### 第5步：交叉验证
222|用其他指标验证核心矛盾方向是否一致，标记冲突信号。
223|
224|**以上步骤在内部完成，不输出中间过程。**
225|
226|## 三、最终输出（结构化研报，面向客户）
227|
228|**【结论】**偏多/偏空/中性（一句话概括行情阶段+核心矛盾，20字以内）
229|
230|**【核心矛盾】**当前最核心的供需矛盾是什么，用数据支撑（1-2条，每条50字以内）
231|
232|**【多空对比】**
233|- 利多：信号1（强度·验证状态）；信号2（强度·验证状态）
234|- 利空：信号1（强度·验证状态）；信号2（强度·验证状态）
235|
236|**【风险】**3-5条具体证伪路径（"若X发生→Y逻辑被证伪→价格方向"，每条40字以内）
237|
238|**【建议】**方向 + 关键价位（支撑/阻力） + 确认条件 + 止损触发
239|
240|**【资讯与研报】**从上方产业资讯和研报观点中提炼3-5条最核心的信息，每条格式：`[事件/观点] → [影响方向] → [对镍价影响]`，控制在3句话以内。
241|
242|## 四、硬约束
243|1. 所有数据必须来自输入，禁止编造
244|2. 明确给出"偏多/偏空/中性"判断，禁止模棱两可
245|3. N/A的数据标注"缺失"，不要推测
246|4. 每条风险必须有具体触发条件
247|5. 结论与多空信号方向必须一致
248|6. 输出控制在800字以内"""
249|    return prompt
250|
251|# ── Call AI ──
252|def call_ai(prompt, key):
253|    payload = {"model": ZSUN_MODEL, "messages": [
254|        {"role":"system","content":"你是专业镍期货分析师，输出结构化研报，面向客户展示。"},
255|        {"role":"user","content": prompt}
256|    ], "max_tokens": 1500, "temperature": 0.7}
257|    req = urllib.request.Request(ZSUN_URL, data=json.dumps(payload).encode(),
258|        headers={"Content-Type":"application/json","Authorization": f"Bearer {key}"})
259|    with urllib.request.urlopen(req, timeout=60) as resp:
260|        result = json.loads(resp.read())
261|    return {
262|        "content": result["choices"][0]["message"]["content"],
263|        "model": ZSUN_MODEL,
264|        "usage": result.get("usage", {}),
265|        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
266|    }
267|
268|# ── Main entry: generate full real-time analysis ──
269|def analyze(key):
270|    data = load_data()
271|    if not data:
272|        return {"error": "无法加载 data.json 数据"}
273|    charts = data.get("charts", {})
274|    news = fetch_news()
275|    reports = fetch_reports()
276|    prompt = build_prompt(charts, news, reports)
277|    ai_result = call_ai(prompt, key)
278|    # 提取方向
279|    content = ai_result["content"]
280|    ai_dir = "偏多" if "偏多" in content[:300] else ("偏空" if "偏空" in content[:300] else ("中性" if "中性" in content[:300] else "未知"))
281|    return {
282|        "ai_analysis": content,
283|        "ai_direction": ai_dir,
284|        "news": news[:15],
285|        "reports": reports[:8],
286|        "model": ai_result["model"],
287|        "usage": ai_result["usage"],
288|        "timestamp": ai_result["timestamp"],
289|        "prompt": prompt
290|    }
291|