#!/usr/bin/env python3
"""Nickel dashboard data fetcher — runs in GitHub Actions.
Output: data.json (charts + news + analysis + AI + realtime)"""
import json, os, time, sys, hashlib, urllib.request, re, urllib.parse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# 统一新闻打分模块 (scorer v2 + 相关性闸门) + 实时解盘模块 (prompt 同源)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scorer_v2
import analyze

# ── Config ──
# Load .env if present (for local dev; GitHub Actions uses secrets)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    for _line in open(_env_path):
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k, _v)

# ── API Keys (三合一: 观/讯/料) ──
GUAN_KEY  = os.environ.get("GUAN_KEY") or "guan_a3dbade5e217468006af273fdc772f91"
NEWS_KEY  = os.environ.get("NEWS_KEY") or "nws_f5b4b6c653104d0f965fb3463dcf7eed"
DATA_KEY  = os.environ.get("DATA_KEY") or "data_8e863643ecc13f11d2c669bdb672f7db"
# 旧 key 已过期(2026-08-13 401)，不再使用
# KEY = os.environ.get("ZHJI_KEY", DATA_KEY)
KEY = ""  # 旧 key 失效，跳过所有 ?key= 调用
if not KEY:
    print("INFO: ZHJI_KEY not set/expired — using kline(观) + akshare + news(讯) only")
COMMODITY_BASE = "https://zhiji-ai.xyz/commodity/api"
GUAN_BASE = "https://zhiji-ai.xyz/guan/api"
NEWS_BASE = "https://zhiji-ai.xyz/news/api"
SF_KEY = os.environ.get("SILICONFLOW_KEY", "")
SF_URL = "https://api.siliconflow.cn/v1/chat/completions"
SF_MODEL = "Qwen/Qwen2.5-72B-Instruct"

# DashScope (阿里百炼) — 主用 AI
DASHSCOPE_KEY = os.environ.get("DASHSCOPE_KEY", "")
DASHSCOPE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
DASHSCOPE_MODEL = "qwen3.7-max"

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

# ── Cache (persist between runs so partial failures don't zero out charts) ──
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache')
os.makedirs(_CACHE_DIR, exist_ok=True)

def _cache_path(key):
    return os.path.join(_CACHE_DIR, hashlib.md5(key.encode()).hexdigest() + '.json')

def _cache_get(key):
    p = _cache_path(key)
    if os.path.exists(p):
        age = time.time() - os.path.getmtime(p)
        if age < 3600 * 2:  # 2h TTL
            with open(p) as f:
                return json.load(f)
    return None

def _cache_set(key, data):
    p = _cache_path(key)
    with open(p, 'w') as f:
        json.dump(data, f)

def api_get(url, header_key=None, header_value=None, retries=3):
    for attempt in range(retries):
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            if header_key and header_value:
                headers[header_key] = header_value
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 2 * (2 ** attempt)  # 2, 4, 8 seconds
                print(f"    429 rate limited, waiting {wait}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            # DNS resolution failure or connection refused — don't retry, fail fast
            raise
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise

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
    """Fetch series data — old key expired, use DATA_KEY header only"""
    cache_key = f"series:{sid}:{start}:{end}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    # DATA_KEY (料) only — skip old ?key= calls
    url = f"{COMMODITY_BASE}/series?id={DATA_IDS[sid]}&start={start}&end={end}"
    try:
        raw = api_get(url, "X-Data-Key", DATA_KEY)
        result = parse_points(raw)
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        print(f"    series FAIL for {sid}: {e}")
        return []

def fetch_kline(symbol, freq="D", limit=365):
    """Fetch K-line data from Guan API (行情) — supports D/W/M/Y/1/5/15/30/60/T
    返回 [{date, value(结算价优先), open, close, volume, oi}] 升序"""
    cache_key = f"kline:{symbol}:{freq}:{limit}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    url = f"{GUAN_BASE}/kline?symbol={symbol}&freq={freq}&cont=1&limit={limit}"
    raw = api_get(url, "X-Guan-Key", GUAN_KEY)
    # K线接口返回 bars 数组 (time/open/high/low/close/volume/oi/settle)
    r = []
    for b in (raw.get("bars") or raw.get("points") or []):
        t = b.get("time") or b.get("date") or ""
        if not t:
            continue
        v = b.get("settle")
        if v is None:
            v = b.get("close")
        if v is None:
            continue
        r.append({"date": str(t)[:10], "value": float(v),
                  "open": b.get("open"), "close": b.get("close"),
                  "volume": b.get("volume"), "oi": b.get("open_interest")})
    r.sort(key=lambda x: x["date"])
    _cache_set(cache_key, r)
    return r

def fetch_quote(symbol):
    url = f"{GUAN_BASE}/quote?symbols={symbol}"
    return api_get(url, "X-Guan-Key", GUAN_KEY)

# ── 宏观与有色板块层 (P0: 2026-08-16) ──
METAL_SYMBOLS = ["CU", "AL", "ZN", "PB", "NI", "SN"]
METAL_NAMES = {"CU": "铜", "AL": "铝", "ZN": "锌", "PB": "铅", "NI": "镍", "SN": "锡"}

def _norm_index(pts, base=100.0):
    """归一化指数: 首值=base"""
    if not pts:
        return []
    b = pts[0]["value"]
    if not b:
        return []
    return [{"date": p["date"], "value": round(p["value"] / b * base, 3)} for p in pts]

def _series_div(a, b, base=100.0):
    """按日期对齐计算 a/b 比值, 首值=base"""
    bm = {p["date"]: p["value"] for p in b}
    pairs = [(p["date"], p["value"] / bm[p["date"]]) for p in a
             if p["date"] in bm and bm[p["date"]] and p["value"] is not None]
    if not pairs:
        return []
    b0 = pairs[0][1]
    if not b0:
        return []
    return [{"date": d, "value": round(v / b0 * base, 3)} for d, v in pairs]

def fetch_macro():
    """宏观与有色板块联动数据: 6金属等权指数 + 相对强弱 + 跨品种比 + 宏观指标"""
    cache_key = "macro:120"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    out = {"metals": {}, "sectors": {}, "ratios": {}, "macro": {}, "error": None}
    # 1) 6金属日K (120个交易日)
    klines = {}
    for sym in METAL_SYMBOLS:
        try:
            klines[sym] = fetch_kline(sym, "D", 120)
        except Exception as e:
            print(f"  macro kline FAIL {sym}: {e}")
            klines[sym] = []
    # 2) 各金属归一化 + 6金属等权板块指数 (共同日期交集)
    norms = {s: _norm_index(klines[s]) for s in METAL_SYMBOLS}
    date_sets = [set(p["date"] for p in v) for v in norms.values() if v]
    common = set.intersection(*date_sets) if date_sets else set()
    idx_series = []
    if common:
        maps = {s: {p["date"]: p["value"] for p in v} for s, v in norms.items()}
        for d in sorted(common):
            vals = [maps[s][d] for s in METAL_SYMBOLS if d in maps[s]]
            if len(vals) >= 5:  # 至少5个金属才有指数意义
                idx_series.append({"date": d, "value": round(sum(vals) / len(vals), 3)})
    out["sectors"]["equal_weight_6m"] = idx_series
    # 镍相对板块: 镍归一化 / 板块指数 (首值=100)
    out["sectors"]["ni_vs_sector"] = _series_div(
        norms.get("NI", []),
        [{"date": p["date"], "value": p["value"]} for p in idx_series])
    for s in METAL_SYMBOLS:
        out["metals"][s] = {"name": METAL_NAMES[s], "norm": norms.get(s, []),
                            "raw": klines.get(s, [])[-120:]}
    # 3) 跨品种比 (镍/铜, 镍/铝)
    out["ratios"]["ni_cu"] = _series_div(norms.get("NI", []), norms.get("CU", []))
    out["ratios"]["ni_al"] = _series_div(norms.get("NI", []), norms.get("AL", []))
    # 4) 快照: 最新值 + 5日涨跌幅
    snap = {}
    for s in METAL_SYMBOLS:
        pts = klines.get(s, [])
        if not pts:
            continue
        lv = pts[-1]["value"]
        ref = pts[-6]["value"] if len(pts) >= 6 else pts[0]["value"]
        snap[s] = {"last": lv, "chg5d": round((lv / ref - 1) * 100, 2) if ref else None,
                   "date": pts[-1]["date"]}
    out["snapshot"] = snap
    # 5) 宏观指标 (akshare, CI无网时降级为缺失)
    try:
        import akshare as ak
        import warnings
        warnings.filterwarnings("ignore")
        bd = ak.bond_zh_us_rate(start_date=(datetime.now() - timedelta(days=120)).strftime("%Y%m%d"))
        bd = bd.dropna(subset=["美国国债收益率10年", "中国国债收益率10年"])
        out["macro"]["us10y"] = [{"date": str(r["日期"]), "value": float(r["美国国债收益率10年"])} for _, r in bd.iterrows()]
        out["macro"]["cn10y"] = [{"date": str(r["日期"]), "value": float(r["中国国债收益率10年"])} for _, r in bd.iterrows()]
        pm = ak.macro_china_pmi().dropna(subset=["制造业-指数"]).copy()
        # 月份字段可能为 "2025年07" 或 "2025-07"; 接口返回降序, 统一转升序取最近24个月
        pm["ym"] = pm["月份"].astype(str).str.replace("年", "-").str.replace("月", "")
        pm = pm.dropna(subset=["ym"])
        pm["ym"] = pm["ym"].str[:7]
        pm = pm.sort_values("ym").tail(24)
        out["macro"]["cn_pmi"] = [{"date": str(r["ym"]) + "-01", "value": float(r["制造业-指数"])} for _, r in pm.iterrows()]
    except Exception as e:
        print(f"  macro akshare FAIL: {e}")
        out["macro_error"] = str(e)[:200]
    for k in list(out["macro"].keys()):
        pts = out["macro"][k]
        if pts:
            lv = pts[-1]["value"]
            ref = pts[-6]["value"] if len(pts) >= 6 else pts[0]["value"]
            out["macro"][k + "_last"] = {"value": lv, "date": pts[-1]["date"],
                                         "chg": round(lv - ref, 3) if ref else None}
    if not any(out["metals"].values()):
        out["error"] = "all metal klines failed"
        return out
    _cache_set(cache_key, out)
    return out

def last_val(pts):
    if isinstance(pts, list) and pts:
        for p in reversed(pts):
            if p.get("value") is not None:
                return round(p["value"], 2)
    return None

# ── News (multi-source: DB scored → akshare fallback) ──
_EXCLUDE = ['SHFE夜盘收盘','LME夜盘收盘','SHFE最新','LME库存','LME注销仓单',
    'LME现货结算','SHFE.*仓单','上期所基本金属仓单','LME金属技术策略',
    'SHFE夜盘开盘','SHFE开盘_基本','SHFE收盘_基本','本周均价','镍现货报价',
    '金川集团电解镍出厂','镍钴中间品价格']

# ── akshare fallback (full coverage when Zhiji is down/rate-limited) ──
def akshare_fallback():
    """Fetch ALL chart data from akshare when Zhiji API is unavailable."""
    fallback = {}
    try:
        import akshare as ak
        import pandas as pd
        from datetime import datetime, timedelta
        print("  akshare fallback: fetching ALL chart data...")

        # ── SHFE daily loop (B1 settle, B3 OI) via akshare ──
        try:
            from concurrent.futures import ThreadPoolExecutor as TPE, as_completed as ac
            end_date = datetime.now()
            start_date = end_date - timedelta(days=60)
            # Generate only trading days (skip weekends)
            dates = []
            current = start_date
            while current <= end_date:
                if current.weekday() < 5:  # Mon-Fri
                    dates.append(current.strftime("%Y%m%d"))
                current += timedelta(days=1)

            def fetch_one(date_str):
                try:
                    df = ak.get_shfe_daily(date=date_str)
                    ni = df[df['variety'] == 'NI']
                    if len(ni) > 0:
                        main = ni.loc[ni['volume'].idxmax()]
                        return {
                            'date': date_str,
                            'settle': float(main['settle']),
                            'close': float(main['close']),
                            'open_interest': float(main['open_interest']),
                            'volume': float(main['volume']),
                        }
                except:
                    pass
                return None

            shfe_rows = []
            with TPE(max_workers=8) as pool:
                futs = {pool.submit(fetch_one, d): d for d in dates}
                for fut in ac(futs):
                    r = fut.result()
                    if r:
                        shfe_rows.append(r)

            shfe_rows.sort(key=lambda x: x['date'])

            if shfe_rows:
                fallback['shfe_ni_settle'] = [
                    {"date": r['date'], "value": r['settle']} for r in shfe_rows
                ]
                print(f"    B1 SHFE settle: {len(fallback['shfe_ni_settle'])} points, last={shfe_rows[-1]['settle']}")
                fallback['shfe_oi'] = [
                    {"date": r['date'], "value": r['open_interest']} for r in shfe_rows
                ]
                print(f"    B3 SHFE OI: {len(fallback['shfe_oi'])} points")
            else:
                print("    No SHFE data available")
        except Exception as e:
            import traceback
            print(f"    SHFE daily loop failed: {e}")
            traceback.print_exc()

        # ── A1: LME inventory (macro_euro_lme_stock) ──
        try:
            df = ak.macro_euro_lme_stock()
            date_c = '日期'
            inv_c = '镍总库存'
            reg_c = '镍注册库存'
            cancel_c = '镍注销库存'
            # Only take nickel columns
            ni_df = df[[date_c, inv_c, reg_c, cancel_c]].copy()
            ni_df = ni_df[ni_df[inv_c].notna()]
            fallback['lme_inventory'] = [
                {"date": str(r[date_c])[:10], "value": float(r[inv_c])} for _, r in ni_df.iterrows()
            ]
            fallback['lme_registered'] = [
                {"date": str(r[date_c])[:10], "value": float(r[reg_c])} for _, r in ni_df.iterrows() if pd.notna(r[reg_c])
            ]
            fallback['lme_cancelled'] = [
                {"date": str(r[date_c])[:10], "value": float(r[cancel_c])} for _, r in ni_df.iterrows() if pd.notna(r[cancel_c])
            ]
            print(f"    A1 LME inventory: {len(fallback['lme_inventory'])} points, last={ni_df.iloc[-1][inv_c]}")
        except Exception as e:
            print(f"    A1 LME inventory failed: {e}")

        # ── B5: China inventory (futures_inventory_em) ──
        try:
            df = ak.futures_inventory_em(symbol="镍")
            date_c = '日期'
            inv_c = '库存'
            fallback['china_inv_18'] = [
                {"date": str(r[date_c])[:10], "value": float(r[inv_c])} for _, r in df.iterrows()
            ]
            fallback['china_inv_27'] = fallback['china_inv_18'].copy()
            print(f"    B5 China inventory: {len(fallback['china_inv_18'])} points, last={df.iloc[-1][inv_c]}")
        except Exception as e:
            print(f"    B5 China inventory failed: {e}")

        # ── LME inventory weekly + price from futures_inventory_99 ──
        try:
            df = ak.futures_inventory_99(symbol="镍")
            # This gives weekly data with price
            if '收盘价' in df.columns:
                fallback['lme_ni_settle'] = [
                    {"date": str(r['日期'])[:10], "value": float(r['收盘价'])} for _, r in df.iterrows()
                ]
                print(f"    B2 LME price (weekly): {len(fallback['lme_ni_settle'])} points")
        except Exception as e:
            print(f"    B2 LME price fallback failed: {e}")

        # ── LME funding rate (approximate from LME price changes) ──
        # B13: lme_funding - not directly available, skip for now

        # ── Stainless steel cold rolling (B14) ──
        # Not directly available via akshare, skip

        # ── Nickel sulfate price (B10) ──
        # Not directly available via akshare, skip

        # ── Indonesia production (B8/B9) ──
        # Not directly available via akshare, skip

        # ── Import window / ratio (A2, B4) ──
        # Calculate from SHFE/LME prices if both available
        if 'shfe_ni_settle' in fallback and 'lme_ni_settle' in fallback:
            # Rough ratio: SHFE / (LME * USDCNY)
            # Use approximate USDCNY rate
            usdcny = 7.25
            shfe_dates = {p['date']: p['value'] for p in fallback['shfe_ni_settle']}
            fallback['shfe_lme_ratio'] = []
            for p in fallback['lme_ni_settle']:
                d = p['date']
                if d in shfe_dates:
                    ratio = shfe_dates[d] / (p['value'] * usdcny) if p['value'] > 0 else None
                    if ratio:
                        fallback['shfe_lme_ratio'].append({"date": d, "value": round(ratio, 2)})
            if fallback['shfe_lme_ratio']:
                print(f"    A2/B4 SHFE/LME ratio: {len(fallback['shfe_lme_ratio'])} points")

    except ImportError:
        print("  akshare not available for fallback")
    except Exception as e:
        print(f"  akshare fallback failed: {e}")
        import traceback
        traceback.print_exc()

    return fallback

def fetch_news():
    """统一 scorer v2 打分: Zhiji/补充/cache/DB/akshare 全路径走 scorer_v2.build_entry
    返回结构: title/body/source/time/level/score/url/direction/relevant/contradictions/matched_terms"""
    items = []
    _DB_PATH = '/home/ubuntu/analysis/nickel_v1.db'
    _NEWS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'news_cache.json')
    _SOURCE_MAP = {"jin10": "金十", "cls": "财联社", "sina": "新浪", "smm": "上海有色网", "x": "X"}

    def _add(title, content, source, ts, url=''):
        """统一入口: 噪音过滤 + 相关性闸门 + scorer v2 打分"""
        if not title or title == '快讯':
            return
        if scorer_v2.is_noise(content or title):
            return
        items.append(scorer_v2.build_entry(title, content, source, ts, url))

    # 0. 优先从 Zhiji 讯服务拉取镍相关实时新闻（最新、最全）
    try:
        print("  Fetching news from Zhiji 讯服务...")
        news_url = f"{NEWS_BASE}/search?q={urllib.parse.quote('镍')}&hours=48&limit=30&source=all"
        zhiji_news = api_get(news_url, "X-News-Key", NEWS_KEY)
        if zhiji_news and isinstance(zhiji_news, dict) and "items" in zhiji_news:
            for n in zhiji_news["items"]:
                content = n.get("content", "")
                title = n.get("title", "")[:80]
                _add(title, content, _SOURCE_MAP.get(n.get("source", "all"), n.get("source", "all")),
                     n.get("time", ""), n.get("url", ""))
            print(f"  Zhiji 讯服务: got {len(items)} news items for 镍")
    except Exception as e:
        print(f"  Zhiji 讯服务 fetch failed: {e}")

    # 0b. 补充拉取不锈钢/镍铁相关新闻
    if len(items) < 15:
        try:
            seen = {it.get("title") for it in items}
            for keyword in ["镍铁", "不锈钢", "精炼镍", "镍豆"]:
                if len(items) >= 25:
                    break
                news_url = f"{NEWS_BASE}/search?q={urllib.parse.quote(keyword)}&hours=48&limit=15&source=all"
                zhiji_news = api_get(news_url, "X-News-Key", NEWS_KEY)
                if zhiji_news and isinstance(zhiji_news, dict) and "items" in zhiji_news:
                    for n in zhiji_news["items"]:
                        title = n.get("title", "")[:80]
                        if not title or title in seen:
                            continue
                        _add(title, n.get("content", ""),
                             _SOURCE_MAP.get(n.get("source", "all"), n.get("source", "all")),
                             n.get("time", ""), n.get("url", ""))
                        seen.add(title)
            print(f"  补充搜索: total {len(items)} items")
        except Exception as e:
            print(f"  补充搜索 failed: {e}")

    # 1. 从 repo 中 news_cache.json 读取（本地定时导出，GitHub Actions 可访问）
    if len(items) < 10:
        try:
            if os.path.exists(_NEWS_JSON):
                with open(_NEWS_JSON) as f:
                    cached = json.loads(f.read())
                if isinstance(cached, list) and len(cached) >= 5:
                    seen = {it.get("title") for it in items}
                    for c in cached[:20]:
                        if c.get("title") not in seen:
                            _add(c.get("title", ""), c.get("body", c.get("content", "")),
                                 c.get("source", ""), c.get("time", ""), c.get("url", ""))
                            seen.add(c.get("title"))
                    print(f"  cache: got {len(items)} total from news_cache.json")
        except Exception as e:
            print(f"  cache load failed: {e}")

    # 2. 优先从DB获取已评分新闻（按 date DESC 取最新30条）
    if len(items) < 15:
        try:
            import sqlite3
            conn = sqlite3.connect(_DB_PATH)
            c = conn.cursor()
            c.execute('''
                SELECT date, content, tier, source
                FROM news_nickel_scored
                WHERE tier IN ('A', 'B')
                ORDER BY date DESC
                LIMIT 30
            ''')
            seen = {it.get("title") for it in items}
            for row in c.fetchall():
                date, content, tier, source = row
                m = re.search(r'【([^】]+)】', content)
                if m:
                    title = m.group(1).replace('SHMET','').replace('上海金属网','').strip()[:80]
                    body = content[m.end():].strip()[:200]
                else:
                    title = content[:60]
                    body = content[60:].strip()[:200]
                if not title or title == '快讯' or title in seen:
                    continue
                ts = date[:19] if date else ''
                url = f"https://www.smm.cn/search/?keyword={urllib.parse.quote(title)}"
                _add(title, body, source or "SMM", ts, url)
                seen.add(title)
            conn.close()
            print(f"  DB: total {len(items)} scored news items")
        except Exception as e:
            print(f"  DB news fetch failed: {e}")

    # 3. akshare 兜底补充
    if len(items) < 20:
        try:
            import akshare as ak
            df = ak.futures_news_shmet(symbol="镍")
            seen_titles = {it.get('title') for it in items}
            for _, r in df.iterrows():
                ts = str(r.get("发布时间",""))[:19]
                content = str(r.get("内容",""))
                m = re.search(r'【([^】]+)】', content)
                if m:
                    title, body = m.group(1), content[m.end():].strip()[:200]
                else:
                    title, body = content[:60], content[60:].strip()[:200]
                title = title.replace('SHMET','').replace('上海金属网','').strip()
                if not title or title == '快讯' or title in seen_titles:
                    continue
                url = f"https://www.smm.cn/search/?keyword={urllib.parse.quote(title)}"
                _add(title, body, "SMM", ts, url)
                seen_titles.add(title)
                if len(items) >= 20:
                    break
        except Exception as e:
            print(f"  akshare fallback failed: {e}")

    # 统一排序: 相关度优先 + 分数降序 + 时间倒序; 取前20条
    items.sort(key=lambda x: (x.get('relevant', True), x.get('score', 0), x.get('time', '')), reverse=True)
    items = items[:20]

    if not items:
        items = [
            {"title":"LME镍库存动态变化","body":"","source":"SMM","time":"今日","level":"B","score":0,
             "url":"","direction":None,"relevant":True,"contradictions":{},"matched_terms":[]},
            {"title":"国内精炼镍冶炼利润持续收窄","body":"","source":"Mysteel","time":"今日","level":"B","score":0,
             "url":"","direction":None,"relevant":True,"contradictions":{},"matched_terms":[]},
        ]
    return items

# ── Analysis (bull/bear logic) ──
def gen_analysis(charts):
    shfe = last_val(charts.get("B1_shfe_price",[]))
    lme = last_val(charts.get("B2_lme_price",[]))
    lme_inv = last_val(charts.get("A1_lme_inventory",{}).get("inventory",[]))
    inv18 = last_val(charts.get("B5_china_inventory",{}).get("inv_18",[]))
    inv27 = last_val(charts.get("B5_china_inventory",{}).get("inv_27",[]))
    bean = last_val(charts.get("B6_bean_inventory",[]))
    profit = last_val(charts.get("B7_smelting_profit",[]))
    oi = last_val(charts.get("B3_shfe_oi",[]))
    indo_rate = last_val(charts.get("B9_indonesia",{}).get("indonesia_rate",[]))
    china_prod = last_val(charts.get("B8_china_production",{}).get("chinese_prod",[]))
    app_cons = last_val(charts.get("B12_apparent_consumption",[]))
    stainless = last_val(charts.get("B14_stainless",{}).get("cold_rolling",[]))
    fundamentals = []
    if shfe: fundamentals.append(f"SHFE {shfe}元/吨")
    if lme: fundamentals.append(f"LME {lme}美元/吨")
    if lme_inv: fundamentals.append(f"LME库存 {lme_inv}吨")
    if inv18: fundamentals.append(f"国内18家 {inv18}吨")
    if inv27: fundamentals.append(f"国内27家 {inv27}吨")
    if bean: fundamentals.append(f"镍豆库存 {bean}吨")
    if profit is not None: fundamentals.append(f"冶炼利润 {profit}元/吨")
    if indo_rate: fundamentals.append(f"印尼开工率 {indo_rate}%")
    if oi: fundamentals.append(f"SHFE持仓 {oi}手")
    if china_prod: fundamentals.append(f"国内产量 {china_prod}吨/月")
    if app_cons: fundamentals.append(f"表观消费 {app_cons}吨/月")
    if stainless: fundamentals.append(f"不锈钢排产 {stainless}吨")
    bull, bear = [], []
    # 供给端
    if profit is not None and profit < 0: bull.append(f"冶炼利润深度亏损{profit}元/吨，减产预期强烈")
    elif profit is not None and profit < 5000: bull.append(f"冶炼利润压缩至{profit}元/吨，减产预期")
    if lme_inv and lme_inv < 280000: bull.append(f"LME库存仅{lme_inv}吨，偏低")
    if inv18 and inv18 < 8000: bull.append(f"国内库存{inv18}吨，低库存支撑")
    if bean and bean < 1000: bull.append(f"镍豆库存仅{bean}吨，低成本替代紧缺")
    # 需求端
    if oi and oi > 150000: bull.append(f"持仓{oi}手，资金关注度高")
    if china_prod and app_cons and app_cons > china_prod * 1.05: bull.append(f"表观消费{app_cons}吨>产量{china_prod}吨，供需缺口")
    # 利空
    if indo_rate and indo_rate > 85: bear.append(f"印尼开工率{indo_rate}%，供应扩张")
    if profit is not None and profit > 20000: bear.append(f"冶炼利润{profit}元/吨，产能释放充足")
    if lme_inv and lme_inv > 350000: bear.append(f"LME库存{lme_inv}吨，累库压力大")
    if inv18 and inv18 > 15000: bear.append(f"国内库存{inv18}吨，压制价格")
    if bean and bean > 10000: bear.append(f"镍豆库存{bean}吨，低成本替代充足")
    if china_prod and app_cons and app_cons < china_prod * 0.95: bear.append(f"表观消费{app_cons}吨<产量{china_prod}吨，供过于求")
    if stainless and stainless < 60: bear.append(f"不锈钢排产仅{stainless}吨，需求疲软")
    if not bull: bull.append("暂无明确利多驱动")
    if not bear: bear.append("暂无明确利空驱动")
    # 规则方向
    rule_dir = "偏多" if len(bull) > len(bear) else ("偏空" if len(bear) > len(bull) else "中性")
    return {"fundamental_summary": "【基本面快照】 " + " | ".join(fundamentals),
            "bull_logic": bull, "bear_logic": bear, "rule_direction": rule_dir,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

# ── Cross-check: rule vs AI ──
def extract_ai_direction(ai_text):
    """从AI输出中提取方向判断"""
    if "偏多" in ai_text[:200]: return "偏多"
    if "偏空" in ai_text[:200]: return "偏空"
    if "中性" in ai_text[:200]: return "中性"
    return "未知"

def cross_check(rule_dir, ai_dir, bull, bear, ai_text):
    """规则vsAI交叉验证，冲突时标记"""
    conflict = rule_dir != ai_dir and rule_dir != "中性" and ai_dir != "中性"
    return {
        "rule_direction": rule_dir,
        "ai_direction": ai_dir,
        "conflict": conflict,
        "rule_bull_count": len(bull),
        "rule_bear_count": len(bear),
        "ai_excerpt": ai_text[:150] if ai_dir != "未知" else "",
        "note": "⚠️ 规则看{} vs AI看{} 方向冲突".format(rule_dir, ai_dir) if conflict else "方向一致"
    }

# ── AI Analysis (DashScope主用 + SiliconFlow备用) — Champion Prompt ──
def gen_ai(charts, news):
    if not DASHSCOPE_KEY and not SF_KEY:
        return "AI 解盘服务未配置 DASHSCOPE_KEY / SILICONFLOW_KEY，请设置 GitHub Secret。"
    # ── 用 analyze.build_prompt 构建 Prompt（与实时解盘同源）──
    # 新闻打分(scorer_v2)/新鲜度标注/动态权重/研报段 两端自动保持一致
    reports = analyze.fetch_reports()
    prompt = analyze.build_prompt(charts, news, reports)

    # ── 调用 AI：DashScope 主用 → SiliconFlow 备用 ──
    def call_ai(url, key, model):
        payload = {"model": model, "messages": [
            {"role":"system","content":"你是专业镍期货分析师，输出结构化研报。"},
            {"role":"user","content":prompt}
        ], "max_tokens":4096, "temperature":0.7}
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())
            # DashScope reasoning models may put text in reasoning_content
            msg = raw["choices"][0]["message"]
            text = msg.get("content") or msg.get("reasoning_content") or ""
            return text

    # 1) DashScope (阿里百炼)
    if DASHSCOPE_KEY:
        try:
            result = call_ai(DASHSCOPE_URL, DASHSCOPE_KEY, DASHSCOPE_MODEL)
            if result:
                return result
        except Exception as e:
            print(f"  DashScope FAILED: {e}")

    # 2) SiliconFlow 备用
    if SF_KEY:
        try:
            result = call_ai(SF_URL, SF_KEY, SF_MODEL)
            if result:
                return result
        except Exception as e:
            print(f"  SiliconFlow FAILED: {e}")

    return "AI请求失败：所有 API 均不可用"

# ── Main ──
def load_prompt_data():
    """Load prompt evaluation data from nickel_prompt_eval"""
    eval_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompt_eval_data')
    results_file = os.path.join(eval_dir, 'results_20260806_105907.json')
    try:
        with open(results_file) as f:
            results = json.load(f)
        rankings = []
        for item in results:
            score = item.get('score', {})
            total = (score.get('score_logic',0) or 0) + (score.get('score_data',0) or 0) + \
                    (score.get('score_industry',0) or 0) + (score.get('score_insight',0) or 0) + \
                    (score.get('score_actionable',0) or 0)
            rankings.append({
                'idx': item.get('prompt_idx'),
                'id': f'#{item.get("prompt_idx")}',
                'desc': item.get('prompt_preview','')[:80],
                'total': total,
                'score': score,
                'full_prompt': item.get('full_prompt',''),
                'output': item.get('output',''),
                'output_length': item.get('output_length',0),
                'status': item.get('status','')
            })
        rankings.sort(key=lambda x: x['total'], reverse=True)

        # Load prompt21/prompt22 outputs for comparison display
        iwencai_output = ""
        local_output = ""
        try:
            p21_path = os.path.join(eval_dir, 'prompt21_output.md')
            p22_path = os.path.join(eval_dir, 'prompt22_output.md')
            if os.path.exists(p21_path):
                with open(p21_path) as f:
                    iwencai_output = f.read()[:3000]
            if os.path.exists(p22_path):
                with open(p22_path) as f:
                    local_output = f.read()[:3000]
        except Exception as e:
            print(f"  Warning: Could not load prompt outputs: {e}")

        # Build diffs from top 2 rankings
        diffs = []
        key_finding = ""
        if len(rankings) >= 2:
            top1 = rankings[0]
            top2 = rankings[1]
            dim_map = {
                'logic': 'score_logic',
                'data': 'score_data',
                'industry': 'score_industry',
                'insight': 'score_insight',
                'actionable': 'score_actionable'
            }
            for dim_name, dim_key in dim_map.items():
                v1 = (top1.get('score') or {}).get(dim_key, 0)
                v2 = (top2.get('score') or {}).get(dim_key, 0)
                diffs.append({'dim': dim_name, 'iwencai': str(v1), 'local': str(v2)})
            t1 = top1.get('total', 0)
            t2 = top2.get('total', 0)
            winner = top1.get('idx', '?') if t1 >= t2 else top2.get('idx', '?')
            best_score = max(t1, t2)
            max_diff = max(diffs, key=lambda x: abs(int(x['local']) - int(x['iwencai']))) if diffs else None
            max_diff_dim = max_diff['dim'] if max_diff else 'logic'
            key_finding = f"Prompt #{winner} 得分更高({best_score}分)，在{max_diff_dim}维度差距最大"

        return {'rankings': rankings, 'iwencai_output': iwencai_output, 'local_output': local_output, 'diffs': diffs, 'key_finding': key_finding}
    except Exception as e:
        print(f"  Warning: Could not load prompt data: {e}")
        return {'rankings': [], 'iwencai_output': '', 'local_output': '', 'diffs': [], 'key_finding': ''}


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

    # ── Load previous data.json as fallback for failed API calls ──
    prev_charts = {}
    prev_path = os.environ.get("OUTPUT", "data.json")
    if os.path.exists(prev_path):
        try:
            with open(prev_path) as f:
                prev_data = json.load(f)
            prev_charts = prev_data.get("charts", {})
            print(f"  Loaded previous data.json as fallback ({os.path.getsize(prev_path)} bytes)")
        except Exception as e:
            print(f"  Warning: Could not load previous data: {e}")

    results = {}
    failed = []

    # ── [1] Fetch price/OI from Guan kline API (primary source) ──
    kline_data = []
    if GUAN_KEY:
        try:
            print("Fetching NI kline from Guan API (365 days)...")
            kline_data = fetch_kline("NI", "D", 365)
            if kline_data:
                print(f"  Guan kline: got {len(kline_data)} data points")
                # Map kline fields to our series IDs
                results["shfe_ni_settle"] = kline_data  # Use settle/close price
                # Try to extract OI from kline if available
                # Note: kline may have open/high/low/close/volume/oi fields
        except Exception as e:
            print(f"  Guan kline FAIL: {e}")
    
    # ── [2] Fetch commodity series from DATA_KEY (料) ──
    remaining_ids = [sid for sid in unique_ids if sid not in results]
    if DATA_KEY and remaining_ids:
        print(f"Fetching {len(remaining_ids)} series from 料 API ({start} to {end})...")
        zhiji_start = time.time()
        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = {pool.submit(fetch_series, sid, start, end): sid for sid in remaining_ids}
            for fut in as_completed(futs):
                sid = futs[fut]
                try:
                    results[sid] = fut.result(timeout=30)
                except Exception as e:
                    print(f"  FAIL {sid}: {e}")
                    failed.append(sid)
        print(f"  料 API fetch took {time.time()-zhiji_start:.1f}s, got {len(results)} results, {len(failed)} failed")

    # ── akshare fallback for series that returned empty from Zhiji ──
    empty_sids = [sid for sid in unique_ids if sid not in results or not results.get(sid)]
    if empty_sids:
        print(f"  {len(empty_sids)} series empty, trying akshare fallback...")
        ak_fb = akshare_fallback()
        for sid, data in ak_fb.items():
            if sid in empty_sids and data:
                results[sid] = data
        # Re-check failed list
        empty_sids = [sid for sid in unique_ids if sid not in results or not results.get(sid)]

    # ── kline fallback: fetch price/OI data from Guan API if still missing ──
    kline_missing = [sid for sid in ["shfe_ni_settle", "shfe_oi"] if not results.get(sid)]
    if kline_missing:
        try:
            print(f"  Fetching kline fallback for: {kline_missing}")
            kline_data = fetch_kline("NI", "D", 365)
            if kline_data:
                results["shfe_ni_settle"] = kline_data
                print(f"  Kline fallback: got {len(kline_data)} data points")
        except Exception as e:
            print(f"  Kline fallback failed: {e}")

    # ── Merge remaining empty series from previous data ──
    mapping = {
        "lme_inventory":"A1_lme_inventory:inventory","lme_registered":"A1_lme_inventory:registered",
        "lme_cancelled":"A1_lme_inventory:cancelled","shfe_lme_ratio":"A4_ratio",
        "magma_discount":"A2_import_window:magma_discount","indonesia_npi_rate":"A2_import_window:indonesia_npi_rate",
        "nickel_bean_price":"A3_substitution:nickel_bean","shfe_ni_settle":"A3_substitution:shfe_settle",
        "lme_ni_settle":"B2_lme_price","shfe_oi":"B3_shfe_oi",
        "ref_profit":"B7_smelting_profit","china_inv_18":"B5_china_inventory:inv_18",
        "china_inv_27":"B5_china_inventory:inv_27","bean_inv_18":"B6_bean_inventory",
        "indonesia_ref_prod":"B9_indonesia:indonesia_prod","indonesia_ref_cap":"B9_indonesia:indonesia_cap",
        "indonesia_ref_rate":"B9_indonesia:indonesia_rate","chinese_ref_prod":"B8_china_production:chinese_prod",
        "chinese_ref_cap":"B8_china_production:chinese_cap","ni_apparent_cons":"B12_apparent_consumption",
        "lme_outflow":"B11_lme_flow:outflow","lme_inflow":"B11_lme_flow:inflow",
        "lme_sulfate_price":"B10_sulfate_price","lme_position":"B13_lme_funding:position",
        "lme_fund_long":"B13_lme_funding:fund_long","lme_commercial_long":"B13_lme_funding:comm_long",
        "lme_commercial_short":"B13_lme_funding:comm_short","stainless_cold_rolling":"B14_stainless:cold_rolling",
    }
    for sid in failed:
        m = mapping.get(sid, "")
        if m:
            chart_key, sub_key = m.split(":") if ":" in m else (m, None)
            prev_chart = prev_charts.get(chart_key, {})
            if sub_key and isinstance(prev_chart, dict):
                prev_data = prev_chart.get(sub_key)
            elif not sub_key:
                prev_data = prev_chart
            if prev_data:
                results[sid] = prev_data
                print(f"  RESTORED {sid} from previous data.json ({len(prev_data)} points)")
                failed.remove(sid)

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

    # News (相关性闸门: 过滤与镍无关的新闻, 与实时链路同标准)
    print("Fetching news...")
    news = [n for n in fetch_news() if n.get("relevant", True)]
    news = news[:20]

    # Extract A-level news highlights for summary
    news_a = [n for n in news if n.get("level") == "A"]
    news_b = [n for n in news if n.get("level") == "B"]
    news_highlights = news_a[:5] + news_b[:5]

    # Analysis
    print("Generating analysis...")
    analysis = gen_analysis(charts)

    # AI
    print("Generating AI analysis...")
    ai_text = gen_ai(charts, news)

    # Cross-check: rule vs AI
    ai_dir = extract_ai_direction(ai_text)
    cc = cross_check(analysis["rule_direction"], ai_dir, analysis["bull_logic"], analysis["bear_logic"], ai_text)
    print(f"Cross-check: rule={analysis['rule_direction']} vs AI={ai_dir} → {cc['note']}")

    # Prompt evaluation data (from nickel_prompt_eval)
    prompt_data = load_prompt_data()

    # 宏观与有色板块层 (P0)
    print("Fetching macro/sector layer...")
    try:
        macro = fetch_macro()
        print(f"  macro: {sum(len(m['norm']) for m in macro['metals'].values())} metal points, "
              f"sector {len(macro['sectors'].get('equal_weight_6m', []))} pts, "
              f"macro_err={macro.get('macro_error','none')[:60]}")
    except Exception as e:
        print(f"  macro FAIL: {e}")
        macro = {"error": str(e)[:200]}

    data = {"charts": charts,
            "news": {"items": news, "highlights": news_highlights, "updated_at": now.strftime("%Y-%m-%d %H:%M:%S")},
            "analysis": analysis, "ai_analysis": ai_text, "cross_check": cc, "realtime": realtime,
            "prompt_data": prompt_data, "macro": macro,
            "_updated_at": now.strftime("%Y-%m-%d %H:%M:%S")}

    out = os.environ.get("OUTPUT", "data.json")
    with open(out, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"✓ Written to {out} ({os.path.getsize(out)} bytes)")

if __name__ == "__main__":
    main()
