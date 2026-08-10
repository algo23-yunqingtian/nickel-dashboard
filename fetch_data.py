#!/usr/bin/env python3
"""Nickel dashboard data fetcher — runs in GitHub Actions.
Output: data.json (charts + news + analysis + AI + realtime)"""
import json, os, time, sys, hashlib, urllib.request, re, urllib.parse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Config ──
KEY = os.environ.get("ZHJI_KEY")
if not KEY:
    print("ERROR: ZHJI_KEY secret not set in GitHub Actions")
    sys.exit(1)
COMMODITY_BASE = "https://zhiji-ai.xyz/commodity/api"
GUAN_BASE = "https://zhiji-ai.xyz/guan/api"
SF_KEY = os.environ.get("SILICONFLOW_KEY", "")
SF_URL = "https://api.siliconflow.cn/v1/chat/completions"
SF_MODEL = "Qwen/Qwen2.5-72B-Instruct"

DATA_IDS = {
    "lme_inventory":"FU00014815","lme_registered":"FU00014817","lme_cancelled":"FU00014818",
    "lme_outflow":"FU00022586","lme_inflow":"FU00023167","shfe_lme_ratio":"a10156412",
    "magma_discount":"ID01532826","indonesia_npi_rate":"ID01002077","indonesia_ref_prod":"ID02026189",
    "indonesia_ref_cap":"ID02026192","indonesia_ref_rate":"ID02026188","nickel_bean_price":"a10100354",
    "shfe_ni_settle":"FU00014982","lme_ni_settle":"FU00014810","shfe_oi":"FU00017556",
    "china_inv_18":"ID01001673","china_inv_27":"ID01490913","bean_inv_18":"ID01366691",
    "ref_profit":"ID01959846","chinese_ref_prod":"a10124958","chinese_ref_rate":"ID002084",
    "ni_apparent_cons":"ID01001570","lme_sulfate_price":"ID00408401",
    # Added from prompt_opt (资金面 + 需求侧)
    "lme_position":"FU00033038","lme_fund_long":"FU00082051","lme_commercial_long":"FU00082053",
    "lme_commercial_short":"FU00082055","stainless_cold_rolling":"ID01706382","chinese_ref_cap":"ID01002081",
}

def api_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def parse_points(data):
    pts = data.get("points", [])
    r = []
    for p in pts:
        v = p.get("value")
        if v is not None:
            r.append({"date": p.get("date",""), "value": float(v)})
    r.sort(key=lambda x: x["date"])
    return r

def fetch_series(sid, start, end):
    url = f"{COMMODITY_BASE}/series?id={DATA_IDS[sid]}&start={start}&end={end}&key={KEY}"
    raw = api_get(url)
    return parse_points(raw)

def fetch_quote(symbol):
    url = f"{GUAN_BASE}/quote?symbols={symbol}&key={KEY}"
    return api_get(url)

def last_val(pts):
    if isinstance(pts, list) and pts:
        for p in reversed(pts):
            if p.get("value") is not None:
                return round(p["value"], 2)
    return None

# ── News (akshare) ──
_EXCLUDE = ['SHFE夜盘收盘','LME夜盘收盘','SHFE最新','LME库存','LME注销仓单',
    'LME现货结算','SHFE.*仓单','上期所基本金属仓单','LME金属技术策略',
    'SHFE夜盘开盘','SHFE开盘_基本','SHFE收盘_基本','本周均价','镍现货报价',
    '金川集团电解镍出厂','镍钴中间品价格']

def fetch_news():
    items = []
    try:
        import akshare as ak
        df = ak.futures_news_shmet(symbol="镍")
        for _, r in df.iterrows():
            ts = str(r.get("发布时间",""))[:19]
            content = str(r.get("内容",""))
            if any(re.search(p, content) for p in _EXCLUDE):
                continue
            m = re.search(r'【([^】]+)】', content)
            if m:
                title, body = m.group(1), content[m.end():].strip()[:200]
            else:
                title, body = content[:60], content[60:].strip()[:200]
            title = title.replace('SHMET','').replace('上海金属网','').strip()
            if not title or title == '快讯':
                continue
            kw_a = ["RKAB","印尼","禁运","关税","罢工","限产","禁令","地缘","出口","能矿部","ESDM","配额","扩产","投产"]
            kw_b = ["库存","利润","开工","减产","消费","需求","检修","预测","净利","市况","下行","上行","策略"]
            level = "A" if any(k in content for k in kw_a) else ("B" if any(k in content for k in kw_b) else "C")
            url = f"https://www.smm.cn/search/?keyword={urllib.parse.quote(title)}"
            items.append({"title":title[:80],"body":body,"source":"SMM","time":ts,"level":level,"url":url})
    except Exception as e:
        print(f"News fetch failed: {e}")
    items = items[:20]
    if not items:
        items = [
            {"title":"LME镍库存动态变化","body":"","source":"SMM","time":"今日","level":"B","url":""},
            {"title":"国内精炼镍冶炼利润持续收窄","body":"","source":"Mysteel","time":"今日","level":"B","url":""},
        ]
    return items

# ── Analysis (bull/bear logic) ──
def gen_analysis(charts):
    shfe = last_val(charts.get("B1_shfe_price",[]))
    lme = last_val(charts.get("B2_lme_price",[]))
    lme_inv = last_val(charts.get("A1_lme_inventory",{}).get("inventory",[]))
    inv18 = last_val(charts.get("B5_china_inventory",{}).get("inv_18",[]))
    bean = last_val(charts.get("B6_bean_inventory",[]))
    profit = last_val(charts.get("B7_smelting_profit",[]))
    oi = last_val(charts.get("B3_shfe_oi",[]))
    indo_rate = last_val(charts.get("B9_indonesia",{}).get("indonesia_rate",[]))
    fundamentals = []
    if shfe: fundamentals.append(f"SHFE {shfe}元/吨")
    if lme: fundamentals.append(f"LME {lme}美元/吨")
    if lme_inv: fundamentals.append(f"LME库存 {lme_inv}吨")
    if inv18: fundamentals.append(f"国内18家 {inv18}吨")
    if bean: fundamentals.append(f"镍豆库存 {bean}吨")
    if profit is not None: fundamentals.append(f"冶炼利润 {profit}元/吨")
    if indo_rate: fundamentals.append(f"印尼开工率 {indo_rate}%")
    if oi: fundamentals.append(f"SHFE持仓 {oi}手")
    bull, bear = [], []
    if lme_inv and lme_inv < 280000: bull.append(f"LME库存仅{lme_inv}吨，偏低")
    if inv18 and inv18 < 8000: bull.append(f"国内库存{inv18}吨，低库存支撑")
    if profit and profit < 5000: bull.append(f"冶炼利润压缩至{profit}元/吨，减产预期")
    if oi and oi > 150000: bull.append(f"持仓{oi}手，资金关注度高")
    if indo_rate and indo_rate > 85: bear.append(f"印尼开工率{indo_rate}%，供应扩张")
    if profit and profit > 20000: bear.append(f"冶炼利润{profit}元/吨，产能释放充足")
    if lme_inv and lme_inv > 350000: bear.append(f"LME库存{lme_inv}吨，累库压力大")
    if inv18 and inv18 > 15000: bear.append(f"国内库存{inv18}吨，压制价格")
    if bean and bean > 10000: bear.append(f"镍豆库存{bean}吨，低成本替代充足")
    if not bull: bull.append("暂无明确利多驱动")
    if not bear: bear.append("暂无明确利空驱动")
    return {"fundamental_summary": "【基本面快照】 " + " | ".join(fundamentals),
            "bull_logic": bull, "bear_logic": bear,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

# ── AI Analysis (SiliconFlow) ──
def gen_ai(charts, news):
    if not SF_KEY:
        return "AI 解盘服务未配置 SILICONFLOW_KEY，请设置 GitHub Secret。"
    def trend(pts, n=5):
        if isinstance(pts, list) and pts:
            recent = [p["value"] for p in pts[-n:] if p.get("value") is not None][-n:]
            return recent if len(recent) >= 2 else []
        return []
    shfe = last_val(charts.get("B1_shfe_price",[])); shfe_t = trend(charts.get("B1_shfe_price",[]))
    lme = last_val(charts.get("B2_lme_price",[])); lme_t = trend(charts.get("B2_lme_price",[]))
    oi = last_val(charts.get("B3_shfe_oi",[])); ratio = last_val(charts.get("B4_ratio",[]))
    inv18 = last_val(charts.get("B5_china_inventory",{}).get("inv_18",[]))
    bean = last_val(charts.get("B6_bean_inventory",[])); profit = last_val(charts.get("B7_smelting_profit",[]))
    indo_rate = last_val(charts.get("B9_indonesia",{}).get("indonesia_rate",[]))
    lme_inv = last_val(charts.get("A1_lme_inventory",{}).get("inventory",[]))
    nl = "\n".join(f"[{n.get('level','C')}] {n.get('title','')} ({n.get('source','')} {n.get('time','')})" for n in (news or [])[:15])
    prompt = f"""你是一位专业的镍(Ni)期货分析师。请根据以下数据给出实时解盘。
## 基本面
- SHFE: {shfe}元/吨（近5日:{shfe_t}） LME: {lme}美元/吨（近5日:{lme_t}）
- 沪伦比:{ratio} 持仓:{oi}手 LME库存:{lme_inv}吨
- 国内18家:{inv18}吨 镍豆:{bean}吨 利润:{profit}元/吨 印尼开工:{indo_rate}%
## 资讯
{nl}
请分点回答(300字内): 1.价格定位 2.核心矛盾 3.多空对比 4.短期关注 5.操作建议"""
    try:
        payload = {"model": SF_MODEL, "messages": [{"role":"system","content":"你是专业镍期货分析师。"},{"role":"user","content":prompt}], "max_tokens":800, "temperature":0.7}
        req = urllib.request.Request(SF_URL, data=json.dumps(payload).encode(),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {SF_KEY}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI请求失败: {str(e)[:100]}"

# ── Main ──
def main():
    now = datetime.now()
    start = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    unique_ids = {"lme_inventory","lme_registered","lme_cancelled","shfe_lme_ratio","magma_discount",
        "indonesia_npi_rate","nickel_bean_price","shfe_ni_settle","lme_ni_settle","shfe_oi",
        "ref_profit","china_inv_18","china_inv_27","bean_inv_18","indonesia_ref_prod",
        "indonesia_ref_cap","indonesia_ref_rate","chinese_ref_prod","ni_apparent_cons",
        "lme_outflow","lme_inflow","lme_sulfate_price",
        # Added: 资金面 + 需求侧
        "lme_position","lme_fund_long","lme_commercial_long","lme_commercial_short",
        "stainless_cold_rolling","chinese_ref_cap"}

    results = {}
    print(f"Fetching {len(unique_ids)} series ({start} to {end})...")
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(fetch_series, sid, start, end): sid for sid in unique_ids}
        for fut in as_completed(futs):
            sid = futs[fut]
            try: results[sid] = fut.result()
            except Exception as e: print(f"  FAIL {sid}: {e}")

    # Assemble charts
    charts = {
        "A1_lme_inventory": {"inventory":results.get("lme_inventory"), "registered":results.get("lme_registered"), "cancelled":results.get("lme_cancelled")},
        "A2_import_window": {"shfe_lme_ratio":results.get("shfe_lme_ratio"), "magma_discount":results.get("magma_discount"), "indonesia_npi_rate":results.get("indonesia_npi_rate")},
        "A3_substitution": {"nickel_bean":results.get("nickel_bean_price"), "shfe_settle":results.get("shfe_ni_settle")},
        "A4_smelting_pressure": {"profit":results.get("ref_profit"), "inv_18":results.get("china_inv_18"), "inv_27":results.get("china_inv_27"), "bean_inv":results.get("bean_inv_18")},
        "B1_shfe_price": results.get("shfe_ni_settle"), "B2_lme_price": results.get("lme_ni_settle"),
        "B3_shfe_oi": results.get("shfe_oi"), "B4_ratio": results.get("shfe_lme_ratio"),
        "B5_china_inventory": {"inv_18":results.get("china_inv_18"), "inv_27":results.get("china_inv_27")},
        "B6_bean_inventory": results.get("bean_inv_18"), "B7_smelting_profit": results.get("ref_profit"),
        "B8_china_production": {"chinese_prod":results.get("chinese_ref_prod"), "chinese_cap":results.get("chinese_ref_cap")},
        "B9_indonesia": {"indonesia_prod":results.get("indonesia_ref_prod"), "indonesia_cap":results.get("indonesia_ref_cap"), "indonesia_rate":results.get("indonesia_ref_rate")},
        "B10_sulfate_price": results.get("lme_sulfate_price"),
        "B11_lme_flow": {"outflow":results.get("lme_outflow"), "inflow":results.get("lme_inflow")},
        "B12_apparent_consumption": results.get("ni_apparent_cons"),
        # Added: 资金面 + 需求侧
        "B13_lme_funding": {"position":results.get("lme_position"), "fund_long":results.get("lme_fund_long"),
            "comm_long":results.get("lme_commercial_long"), "comm_short":results.get("lme_commercial_short")},
        "B14_stainless": {"cold_rolling":results.get("stainless_cold_rolling")},
    }

    # Realtime
    realtime = {}
    try:
        print("Fetching realtime quote...")
        realtime = fetch_quote("NI")
    except Exception as e:
        print(f"  Realtime FAIL: {e}")

    # News
    print("Fetching news...")
    news = fetch_news()

    # Analysis
    print("Generating analysis...")
    analysis = gen_analysis(charts)

    # AI
    print("Generating AI analysis...")
    ai_text = gen_ai(charts, news)

    data = {"charts": charts, "news": {"items": news, "updated_at": now.strftime("%Y-%m-%d %H:%M:%S")},
            "analysis": analysis, "ai_analysis": ai_text, "realtime": realtime,
            "_updated_at": now.strftime("%Y-%m-%d %H:%M:%S")}

    out = os.environ.get("OUTPUT", "data.json")
    with open(out, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"✓ Written to {out} ({os.path.getsize(out)} bytes)")

if __name__ == "__main__":
    main()
