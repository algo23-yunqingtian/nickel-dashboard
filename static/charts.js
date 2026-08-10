// Nickel Dashboard v3.0 — Static (GitHub Pages)
// Reads all data from data.json, no backend needed.
const DARK = {
    bg: '#111318', axis: '#22252e', text: '#6b7080', grid: '#161820',
    colors: ['#f97316','#3b82f6','#22c55e','#ef4444','#a855f7','#06b6d4','#eab308','#ec4899']
};

// ═══ Sidebar Navigation ═══
document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const sec = tab.dataset.section;
        document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
        const target = document.getElementById('section-' + sec);
        if (target) {
            target.classList.add('active');
            if (sec === 'news' && !target.dataset.loaded) {
                target.dataset.loaded = '1'; renderNewsFull();
            }
            if (sec === 'analysis' && !target.dataset.loaded) {
                target.dataset.loaded = '1'; renderAI();
            }
        }
        setTimeout(resizeAll, 120);
    });
});

function resizeAll() {
    document.querySelectorAll('.chart').forEach(el => {
        const inst = echarts.getInstanceByDom(el);
        if (inst) inst.resize();
    });
}
window.addEventListener('resize', resizeAll);

// ═══ Generic ECharts Options ═══
function lineOpts(datasets, titleY, titleY2) {
    const series = [], xData = [];
    datasets.forEach(ds => ds.points.forEach(p => { if (!xData.includes(p.date)) xData.push(p.date); }));
    xData.sort();
    datasets.forEach((ds, i) => {
        const vm = {}; ds.points.forEach(p => vm[p.date] = p.value);
        const vals = xData.map(d => vm[d] !== undefined ? vm[d] : null);
        series.push({ name: ds.name, type: 'line', data: vals, smooth: true, symbol: 'none',
            lineStyle: { width: 2, color: DARK.colors[i % 8] },
            yAxisIndex: ds.yAxisIndex || 0, itemStyle: { color: DARK.colors[i % 8] }, connectNulls: true });
    });
    const yAxis = [{ type: 'value', position: 'left', name: titleY,
        nameTextStyle: { color: DARK.text }, axisLine: { lineStyle: { color: DARK.axis } },
        axisLabel: { color: DARK.text }, splitLine: { lineStyle: { color: DARK.grid } } }];
    if (titleY2) yAxis.push({ type: 'value', position: 'right', name: titleY2,
        nameTextStyle: { color: DARK.text }, axisLine: { lineStyle: { color: DARK.axis } },
        axisLabel: { color: DARK.text }, splitLine: { show: false } });
    return { backgroundColor: DARK.bg, tooltip: { trigger: 'axis', backgroundColor: '#1a1d26',
        borderColor: '#2a2d3a', textStyle: { color: '#dfe2ea' } },
        legend: { data: datasets.map(d => d.name), textStyle: { color: DARK.text, fontSize: 10 }, top: 0, right: 10 },
        xAxis: { type: 'category', data: xData, axisLine: { lineStyle: { color: DARK.axis } },
            axisLabel: { color: DARK.text, rotate: 0, fontSize: 9 }, axisTick: { show: false } },
        yAxis, grid: { left: 50, right: 50, top: 36, bottom: 36 }, series };
}

function barOpts(datasets, titleY) {
    const series = [], xData = [];
    datasets.forEach(ds => ds.points.forEach(p => { if (!xData.includes(p.date)) xData.push(p.date); }));
    xData.sort();
    datasets.forEach((ds, i) => {
        const vm = {}; ds.points.forEach(p => vm[p.date] = p.value);
        series.push({ name: ds.name, type: 'bar', data: xData.map(d => vm[d]),
            itemStyle: { color: DARK.colors[i % 8], borderRadius: [2, 2, 0, 0] }, barMaxWidth: 20 });
    });
    return { backgroundColor: DARK.bg, tooltip: { trigger: 'axis', backgroundColor: '#1a1d26',
        borderColor: '#2a2d3a', textStyle: { color: '#dfe2ea' } },
        legend: { data: datasets.map(d => d.name), textStyle: { color: DARK.text, fontSize: 10 }, top: 0, right: 10 },
        xAxis: { type: 'category', data: xData, axisLine: { lineStyle: { color: DARK.axis } },
            axisLabel: { color: DARK.text, fontSize: 9 }, axisTick: { show: false } },
        yAxis: [{ type: 'value', name: titleY, nameTextStyle: { color: DARK.text },
            axisLine: { lineStyle: { color: DARK.axis } }, axisLabel: { color: DARK.text },
            splitLine: { lineStyle: { color: DARK.grid } } }],
        grid: { left: 50, right: 50, top: 36, bottom: 36 }, series };
}

function pt(arr) { return (arr || []).map(p => ({ date: p.date, value: p.value })); }

// ═══ Render Functions ═══
function rA1(d) { if (!d||d.error)return; const c=echarts.init(document.getElementById('chart-a1'));
    c.setOption(lineOpts([{name:'LME总库存',points:pt(d.inventory)},{name:'注册仓单',points:pt(d.registered)},{name:'注销仓单',points:pt(d.cancelled)}],'吨')); }
function rA2(d) { if (!d||d.error)return; const c=echarts.init(document.getElementById('chart-a2'));
    c.setOption(lineOpts([{name:'沪伦比值',points:pt(d.shfe_lme_ratio)},{name:'高冰镍LME折扣%',points:pt(d.magma_discount),yAxisIndex:1},{name:'印尼NPI开工率%',points:pt(d.indonesia_npi_rate),yAxisIndex:1}],'沪伦比值(元/吨)','百分比(%)')); }
function rA3(d) { if (!d||d.error)return; const c=echarts.init(document.getElementById('chart-a3'));
    c.setOption(lineOpts([{name:'SHFE镍结算价',points:pt(d.shfe_settle)},{name:'镍豆价格',points:pt(d.nickel_bean)}],'元/吨')); }
function rA4(d) { if (!d||d.error)return; const c=echarts.init(document.getElementById('chart-a4'));
    c.setOption(lineOpts([{name:'冶炼利润',points:pt(d.profit)},{name:'18家库存',points:pt(d.inv_18),yAxisIndex:1},{name:'27家库存',points:pt(d.inv_27),yAxisIndex:1},{name:'镍豆库存',points:pt(d.bean_inv),yAxisIndex:1}],'利润(元/吨)','库存(吨)')); }
function rB1(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b1')).setOption(lineOpts([{name:'SHFE镍结算价',points:pt(d)}],'元/吨')); }
function rB2(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b2')).setOption(lineOpts([{name:'LME镍3月结算价',points:pt(d)}],'美元/吨')); }
function rB3(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b3')).setOption(lineOpts([{name:'SHFE镍持仓量',points:pt(d)}],'手')); }
function rB4(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b4')).setOption(lineOpts([{name:'沪伦比值',points:pt(d)}],'元/吨')); }
function rB5(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b5')).setOption(lineOpts([{name:'18家库存',points:pt(d.inv_18)},{name:'27家库存',points:pt(d.inv_27)}],'吨')); }
function rB6(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b6')).setOption(lineOpts([{name:'镍豆库存(18家)',points:pt(d)}],'吨')); }
function rB7(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b7')).setOption(lineOpts([{name:'外采高冰镍冶炼利润',points:pt(d)}],'元/吨')); }
function rB8(d) { if (!d||d.error)return; const c=echarts.init(document.getElementById('chart-b8'));
    c.setOption(barOpts([{name:'国内产量',points:pt(d.chinese_prod)},{name:'国内产能',points:pt(d.chinese_cap)}],'吨/月')); }
function rB9(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b9')).setOption(lineOpts([{name:'印尼产量',points:pt(d.indonesia_prod)},{name:'印尼产能',points:pt(d.indonesia_cap)},{name:'印尼开工率%',points:pt(d.indonesia_rate),yAxisIndex:1}],'吨/月','百分比(%)')); }
function rB10(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b10')).setOption(lineOpts([{name:'电池级硫酸镍',points:pt(d)}],'元/吨')); }
function rB11(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b11')).setOption(lineOpts([{name:'LME入库',points:pt(d.inflow)},{name:'LME出库',points:pt(d.outflow)}],'吨')); }
function rB12(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b12')).setOption(barOpts([{name:'精炼镍表观消费',points:pt(d)}],'吨/月')); }
function rB13(d) { if (!d||d.error)return; const c=echarts.init(document.getElementById('chart-b13'));
    c.setOption(lineOpts([{name:'LME总持仓',points:pt(d.position)},{name:'基金多头',points:pt(d.fund_long),yAxisIndex:1},{name:'商业多头',points:pt(d.comm_long),yAxisIndex:1},{name:'商业空头',points:pt(d.comm_short),yAxisIndex:1}],'总持仓(手)','分项持仓(手)')); }
function rB14(d) { if (!d||d.error)return; echarts.init(document.getElementById('chart-b14')).setOption(barOpts([{name:'300系冷轧排产',points:pt(d.cold_rolling)}],'万吨/月')); }

// ═══ Data from data.json ═══
let PAGE_DATA = null;

function renderAll(charts) {
    rA1(charts.A1_lme_inventory); rA2(charts.A2_import_window);
    rA3(charts.A3_substitution); rA4(charts.A4_smelting_pressure);
    rB1(charts.B1_shfe_price); rB2(charts.B2_lme_price); rB3(charts.B3_shfe_oi);
    rB4(charts.B4_ratio); rB5(charts.B5_china_inventory); rB6(charts.B6_bean_inventory);
    rB7(charts.B7_smelting_profit); rB8(charts.B8_china_production); rB9(charts.B9_indonesia);
    rB10(charts.B10_sulfate_price); rB11(charts.B11_lme_flow); rB12(charts.B12_apparent_consumption);
    rB13(charts.B13_lme_funding); rB14(charts.B14_stainless);
    resizeAll();
}

function renderRealtime(data) {
    if (data && data.quotes && data.quotes.length > 0) {
        const q = data.quotes[0];
        const chg = q.change >= 0 ? '+' + q.change.toFixed(0) : q.change.toFixed(0);
        const pct = q.change_pct >= 0 ? '+' + q.change_pct.toFixed(2) + '%' : q.change_pct.toFixed(2) + '%';
        document.getElementById('realtime-price').textContent = q.name + ' ' + q.last.toLocaleString() + ' (' + chg + ' ' + pct + ')';
    }
}

function buildNewsHTML(items, showBody) {
    let h = '';
    items.forEach(n => {
        const lvl = (n.level || 'C').toUpperCase();
        const body = showBody && n.body ? '<div class="news-body">' + n.body + '</div>' : '';
        const link = n.url ? ' onclick="window.open(\'' + n.url + '\',\'_blank\')" class="news-clickable"' : '';
        h += '<div class="news-item"' + link + '><span class="news-level news-level-' + lvl.toLowerCase() + '">' + lvl + '</span><div class="news-content"><div class="news-title">' + (n.title || '') + '</div>' + body + '<div class="news-meta">' + (n.source || '') + ' · ' + (n.time || '') + (n.url ? ' · 🔗' : '') + '</div></div></div>';
    });
    return h;
}

function renderNewsTicker() {
    if (!PAGE_DATA || !PAGE_DATA.news) return;
    const items = PAGE_DATA.news.items || [];
    const el = document.getElementById('news-count');
    if (el) el.textContent = items.length + '条';
    if (!items.length) return;
    const sc = document.getElementById('news-ticker-scroll');
    if (sc) sc.innerHTML = buildNewsHTML(items) + buildNewsHTML(items);
}

function renderNewsFull() {
    if (!PAGE_DATA || !PAGE_DATA.news) return;
    const items = PAGE_DATA.news.items || [];
    const el = document.getElementById('news-count-full');
    if (el) el.textContent = items.length + '条';
    const c = document.getElementById('news-full');
    if (!c) return;
    if (!items.length) { c.innerHTML = '<div class="news-item"><span class="news-title">暂无新闻</span></div>'; return; }
    c.innerHTML = buildNewsHTML(items, true);
}

function renderAnalysis() {
    if (!PAGE_DATA || !PAGE_DATA.analysis) return;
    const d = PAGE_DATA.analysis;
    const bEl = document.getElementById('analysis-b');
    if (bEl && d.fundamental_summary) bEl.innerHTML = '<div style="white-space:pre-line;">' + d.fundamental_summary + '</div>';
    const abEl = document.getElementById('analysis-ab');
    if (abEl) {
        const bull = (d.bull_logic || []).map(x => '<li>' + x + '</li>').join('');
        const bear = (d.bear_logic || []).map(x => '<li>' + x + '</li>').join('');
        abEl.innerHTML = '<div class="bull-section"><div class="bull-label">📈 多头逻辑</div><ul style="padding-left:20px;margin-top:4px;">' + (bull || '<li>暂无</li>') + '</ul></div><div class="bear-section" style="margin-top:12px;"><div class="bear-label">📉 空头逻辑</div><ul style="padding-left:20px;margin-top:4px;">' + (bear || '<li>暂无</li>') + '</ul></div><div style="font-size:11px;color:#6b7280;margin-top:8px;">分析更新: ' + (d.updated_at || '--') + '</div>';
    }
}

function renderAI() {
    if (!PAGE_DATA) return;
    const aiEl = document.getElementById('analysis-ai');
    if (!aiEl) return;
    // Show cached AI from data.json immediately, then refresh via live API
    const cached = PAGE_DATA.ai_analysis || 'AI 解盘服务暂不可用';
    const cachedHtml = cached.replace(/\n/g, '<br>');
    aiEl.innerHTML = '<div class="ai-analysis-content">' + cachedHtml + '</div><div style="font-size:11px;color:#6b7280;margin-top:12px;text-align:right;" id="ai-timestamp">缓存: ' + (PAGE_DATA._updated_at || '--') + '</div>';
    // Live AI call from browser
    fetchAI();
}

function fetchAI() {
    const d = PAGE_DATA;
    if (!d || !d.charts) return;
    const c = d.charts;
    const lastVal = arr => (Array.isArray(arr) && arr.length ? arr[arr.length - 1].value : '--');
    const trend = (arr, n = 5) => {
        if (!Array.isArray(arr) || !arr.length) return [];
        return arr.slice(-n).map(p => p.value);
    };
    const shfe = lastVal(c.B1_shfe_price || []), shfe_t = trend(c.B1_shfe_price || []);
    const lme = lastVal(c.B2_lme_price || []), lme_t = trend(c.B2_lme_price || []);
    const oi = lastVal(c.B3_shfe_oi || []), ratio = lastVal(c.B4_ratio || []);
    const inv18 = lastVal((c.B5_china_inventory || {}).inv_18 || []);
    const bean = lastVal(c.B6_bean_inventory || []), profit = lastVal(c.B7_smelting_profit || []);
    const indo_rate = lastVal((c.B9_indonesia || {}).indonesia_rate || []);
    const lme_inv = lastVal((c.A1_lme_inventory || {}).inventory || []);
    const news = (d.news && d.news.items) || [];
    const nl = news.slice(0, 15).map(n => `[${n.level || 'C'}] ${n.title || ''} (${n.source || ''} ${n.time || ''})`).join('\n');
    const prompt = `你是一位专业的镍(Ni)期货分析师。请根据以下数据给出实时解盘。\n## 基本面\n- SHFE: ${shfe}元/吨（近5日:${JSON.stringify(shfe_t)}） LME: ${lme}美元/吨（近5日:${JSON.stringify(lme_t)}）\n- 沪伦比:${ratio} 持仓:${oi}手 LME库存:${lme_inv}吨\n- 国内18家:${inv18}吨 镍豆:${bean}吨 利润:${profit}元/吨 印尼开工:${indo_rate}%\n## 资讯\n${nl}\n请分点回答(300字内): 1.价格定位 2.核心矛盾 3.多空对比 4.短期关注 5.操作建议`;

    const el = document.getElementById('analysis-ai');
    const tsEl = document.getElementById('ai-timestamp');

    // Detect environment: GitHub Pages has no backend proxy, use cache only
    const isGitHubPages = location.hostname.includes('github.io');

    if (isGitHubPages) {
        // GitHub Pages: show cached AI analysis from data.json
        const cached = PAGE_DATA.ai_analysis || 'AI 解盘数据暂未更新';
        const cachedHtml = cached.replace(/\n/g, '<br>');
        const updated = PAGE_DATA._updated_at || '未知时间';
        if (el) el.innerHTML = '<div class="ai-analysis-content">' + cachedHtml + '</div><div style="font-size:11px;color:#fbbf24;margin-top:12px;text-align:right;" id="ai-timestamp">📦 缓存数据 (Actions 每30min更新): ' + updated + '</div>';
        return;
    }

    // Server version: call AI proxy for real-time analysis
    if (el) el.innerHTML = '<div class="ai-analysis-content" style="color:#9ca3af;text-align:center;padding:40px;">🔄 AI 正在生成实时解盘...</div>';

    const PROXY_URL = '/nickel-gh/api';
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000); // 8s timeout

    fetch(PROXY_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            messages: [
                { role: 'system', content: '你是专业镍期货分析师，中文回答。' },
                { role: 'user', content: prompt }
            ],
            max_tokens: 800,
            temperature: 0.7
        }),
        signal: controller.signal
    })
    .then(r => {
        clearTimeout(timeoutId);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    })
    .then(data => {
        const txt = data.content;
        const html = txt.replace(/\n/g, '<br>');
        const now = new Date().toLocaleString('zh-CN');
        if (el) el.innerHTML = '<div class="ai-analysis-content">' + html + '</div><div style="font-size:11px;color:#34d399;margin-top:12px;text-align:right;" id="ai-timestamp">🟢 实时: ' + now + '</div>';
    })
    .catch(err => {
        clearTimeout(timeoutId);
        console.error('AI fetch failed:', err);
        // Fallback to cached
        const cached = PAGE_DATA.ai_analysis || 'AI 解盘失败';
        const cachedHtml = cached.replace(/\n/g, '<br>');
        if (el) el.innerHTML = '<div class="ai-analysis-content">' + cachedHtml + '</div><div style="font-size:11px;color:#f87171;margin-top:12px;text-align:right;" id="ai-timestamp">⚠️ 使用缓存数据 (实时调用失败)</div>';
    });
}

// ═══ Init: Load data.json ═══
fetch('data.json')
    .then(r => r.json())
    .then(data => {
        PAGE_DATA = data;
        renderAll(data.charts);
        renderRealtime(data.realtime);
        renderNewsTicker();
        renderAnalysis();
        document.getElementById('update-time').textContent = '数据更新: ' + (data._updated_at || '--');
    })
    .catch(e => {
        console.error('Failed to load data.json:', e);
        document.getElementById('update-time').textContent = '数据加载失败';
    });

// Refresh buttons
document.getElementById('btn-refresh-news')?.addEventListener('click', () => { location.reload(); });
document.getElementById('btn-refresh-ai')?.addEventListener('click', () => { location.reload(); });

// ═══ Prompt Engineering Section ═══
function renderPromptSection(data) {
    if (!data || !data.prompt_data) return;
    const pd = data.prompt_data;

    // Ranking table
    const rankingEl = document.getElementById('prompt-ranking');
    if (rankingEl) {
        const sorted = (pd.rankings || []).sort((a, b) => (b.total || 0) - (a.total || 0));
        let html = '<table><thead><tr><th class="rank-col">#</th><th>Prompt</th><th>描述</th><th class="score-col">总分</th></tr></thead><tbody>';
        sorted.forEach((r, i) => {
            html += '<tr><td class="rank-col">' + (i+1) + '</td><td>' + (r.id || '--') + '</td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + (r.desc || '') + '">' + (r.desc || '--') + '</td><td class="score-col">' + (r.total || 0) + '</td></tr>';
        });
        html += '</tbody></table>';
        rankingEl.innerHTML = html;
        document.getElementById('prompt-count').textContent = sorted.length + '个版本';
    }

    // Iwencai vs Local comparison
    const iwencaiEl = document.getElementById('prompt-iwencai');
    if (iwencaiEl && pd.iwencai_output) {
        iwencaiEl.innerHTML = '<div style="white-space:pre-wrap;">' + pd.iwencai_output + '</div>';
    }

    const localEl = document.getElementById('prompt-local');
    if (localEl && pd.local_output) {
        localEl.innerHTML = '<div style="white-space:pre-wrap;">' + pd.local_output + '</div>';
    }

    // Difference summary
    const diffEl = document.getElementById('prompt-diff');
    if (diffEl && pd.diffs) {
        let html = '<table><thead><tr><th>维度</th><th>问财 AI</th><th>本地 AI</th></tr></thead><tbody>';
        pd.diffs.forEach(d => {
            html += '<tr><td>' + d.dim + '</td><td>' + d.iwencai + '</td><td>' + d.local + '</td></tr>';
        });
        html += '</tbody></table>';
        if (pd.key_finding) {
            html += '<div style="margin-top:12px;padding:12px;background:#1a1d26;border-radius:8px;font-size:13px;color:#f97316;">💡 核心发现：' + pd.key_finding + '</div>';
        }
        diffEl.innerHTML = html;
    }
}

// ═══ Old Prompt Section (pre-Zhiji version) ═══
function renderOldPromptSection(data) {
    if (!data || !data.old_prompt_data) return;
    const op = data.old_prompt_data;

    // Input data snapshot
    const inputEl = document.getElementById('old-prompt-input');
    if (inputEl && op.input) {
        const inp = op.input;
        let html = '<table style="width:100%;border-collapse:collapse;"><tr><td style="padding:4px;color:#9ca3af;font-weight:600;">LME库存</td><td style="padding:4px;color:#dfe2ea;">' + (inp.lme_inv?.value||'--') + ' 吨 (' + (inp.lme_inv?.date||'') + ')</td><td style="padding:4px;color:#9ca3af;font-weight:600;">国内库存</td><td style="padding:4px;color:#dfe2ea;">' + (inp.china_inv?.value||'--') + ' 吨 (' + (inp.china_inv?.date||'') + ')</td></tr><tr><td style="padding:4px;color:#9ca3af;font-weight:600;">冶炼利润</td><td style="padding:4px;color:#ef4444;">' + (inp.smelting_profit?.value||'--') + ' 元/吨 (' + (inp.smelting_profit?.date||'') + ')</td><td style="padding:4px;color:#9ca3af;font-weight:600;">印尼产量</td><td style="padding:4px;color:#dfe2ea;">' + (inp.indonesia_prod?.value||'--') + ' 吨/月 (' + (inp.indonesia_prod?.date||'') + ')</td></tr></table>';
        if (inp.news && inp.news.length) {
            html += '<div style="margin-top:8px;"><h4 style="color:#9ca3af;font-size:11px;margin-bottom:4px;">新闻快照</h4>';
            inp.news.forEach(n => { html += '<div style="padding:2px 0;color:#dfe2ea;">[' + (n.level||'C') + '] ' + (n.title||'') + '</div>'; });
            html += '</div>';
        }
        inputEl.innerHTML = html;
    }

    // Old ranking table
    const rankingEl = document.getElementById('old-prompt-ranking');
    if (rankingEl) {
        const sorted = (op.rankings || []).sort((a, b) => (b.total || 0) - (a.total || 0));
        let html = '<table><thead><tr><th class="rank-col">#</th><th>Prompt</th><th>描述</th><th class="score-col">总分</th></tr></thead><tbody>';
        sorted.forEach((r, i) => {
            html += '<tr><td class="rank-col">' + (i+1) + '</td><td>' + (r.id || '--') + '</td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + (r.desc || '') + '">' + (r.desc || '--') + '</td><td class="score-col">' + (r.total || 0) + '</td></tr>';
        });
        html += '</tbody></table>';
        rankingEl.innerHTML = html;
        document.getElementById('old-prompt-count').textContent = sorted.length + '个版本';
    }

    // Old Iwencai vs Local comparison
    const iwencaiEl = document.getElementById('old-prompt-iwencai');
    if (iwencaiEl && op.iwencai) {
        let html = '<div style="margin-bottom:8px;color:#9ca3af;font-size:11px;">查询：<b style="color:#f97316;">' + (op.iwencai.query||'') + '</b><br>结论：<b style="color:#22c55e;">' + (op.iwencai.conclusion||'') + '</b></div>';
        html += '<div style="white-space:pre-wrap;">' + (op.iwencai.output_preview||'') + '</div>';
        iwencaiEl.innerHTML = html;
    }

    const localEl = document.getElementById('old-prompt-local');
    if (localEl && op.rankings && op.rankings.length > 0) {
        const top1 = op.rankings[0];
        let html = '<div style="margin-bottom:8px;color:#9ca3af;font-size:11px;">使用 Prompt #' + top1.idx + '（6步框架，无Zhiji数据）</div>';
        html += '<div style="white-space:pre-wrap;">' + (top1.output||'').substring(0, 1500) + '</div>';
        if ((top1.output||'').length > 1500) {
            html += '<div style="color:#4b5563;font-size:10px;margin-top:4px;">...（已截断，点击下方详情查看完整输出）</div>';
        }
        localEl.innerHTML = html;
    }

    // Detail cards (expandable)
    const detailEl = document.getElementById('old-prompt-detail');
    if (detailEl && op.rankings) {
        const sorted = (op.rankings || []).sort((a, b) => (b.total || 0) - (a.total || 0));
        let html = '';
        sorted.forEach((r, i) => {
            html += '<div class="detail-card">';
            html += '<div class="detail-header" onclick="this.classList.toggle(\'expanded\');this.nextElementSibling.classList.toggle(\'show\')">';
            html += '<span class="rank">' + (i+1) + '</span>';
            html += '<span class="desc">' + (r.desc||'') + '</span>';
            html += '<span class="score">' + (r.total||0) + '</span>';
            html += '<span class="expand-icon">▼</span>';
            html += '</div>';
            html += '<div class="detail-body">';
            html += '<h4>摘要</h4><p>' + (r.summary||'') + '</p>';
            if (r.strengths && r.strengths.length) {
                html += '<h4>优势</h4><ul class="strengths">';
                r.strengths.forEach(s => { html += '<li>' + s + '</li>'; });
                html += '</ul>';
            }
            if (r.weaknesses && r.weaknesses.length) {
                html += '<h4>不足</h4><ul class="weaknesses">';
                r.weaknesses.forEach(w => { html += '<li>' + w + '</li>'; });
                html += '</ul>';
            }
            html += '</div></div>';
        });
        detailEl.innerHTML = html;
    }

    // Radar chart for Top1
    try {
        const top1 = (op.rankings||[]).sort((a,b) => (b.total||0)-(a.total||0))[0];
        if (top1 && top1.score) {
            const sc = top1.score;
            const chart1 = echarts.init(document.getElementById('old-prompt-radar1'));
            chart1.setOption({
                backgroundColor: 'transparent',
                tooltip: {},
                radar: {
                    indicator: [
                        { name: '逻辑', max: 25 }, { name: '数据', max: 25 },
                        { name: '产业', max: 25 }, { name: '洞察', max: 25 },
                        { name: '可操作性', max: 25 }, { name: '表达', max: 25 }
                    ],
                    axisName: { color: '#9ca3af', fontSize: 10 },
                    splitArea: { areaStyle: { color: ['#161820','#1a1d26'] } },
                    axisLine: { lineStyle: { color: '#22252e' } },
                    splitLine: { lineStyle: { color: '#22252e' } }
                },
                series: [{
                    type: 'radar',
                    data: [{
                        name: '#22',
                        value: [sc.score_logic||0, sc.score_data||0, sc.score_industry||0, sc.score_insight||0, sc.score_actionable||0, sc.score_expression||0],
                        areaStyle: { color: 'rgba(249,115,22,0.3)' },
                        lineStyle: { color: '#f97316' },
                        itemStyle: { color: '#f97316' }
                    }]
                }]
            });
        }
    } catch(e) {}

    // Radar chart for Top5 comparison
    try {
        const top5 = (op.rankings||[]).sort((a,b) => (b.total||0)-(a.total||0)).slice(0, 5);
        if (top5.length > 0) {
            const chart2 = echarts.init(document.getElementById('old-prompt-radar2'));
            const colors = ['#f97316','#3b82f6','#22c55e','#a855f7','#facc15'];
            const data = top5.map((r, i) => {
                const sc = r.score || {};
                return {
                    name: r.id || '#'+r.idx,
                    value: [sc.score_logic||0, sc.score_data||0, sc.score_industry||0, sc.score_insight||0, sc.score_actionable||0, sc.score_expression||0],
                    areaStyle: { color: colors[i] + '33' },
                    lineStyle: { color: colors[i] },
                    itemStyle: { color: colors[i] }
                };
            });
            chart2.setOption({
                backgroundColor: 'transparent',
                tooltip: {},
                legend: { data: top5.map(r => r.id||'#'+r.idx), textStyle: { color: '#9ca3af', fontSize: 10 }, top: 0 },
                radar: {
                    indicator: [
                        { name: '逻辑', max: 25 }, { name: '数据', max: 25 },
                        { name: '产业', max: 25 }, { name: '洞察', max: 25 },
                        { name: '可操作性', max: 25 }, { name: '表达', max: 25 }
                    ],
                    axisName: { color: '#9ca3af', fontSize: 10 },
                    splitArea: { areaStyle: { color: ['#161820','#1a1d26'] } },
                    axisLine: { lineStyle: { color: '#22252e' } },
                    splitLine: { lineStyle: { color: '#22252e' } }
                },
                series: [{
                    type: 'radar',
                    data: data
                }]
            });
        }
    } catch(e) {}
}

// Register prompt rendering on tab click
document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const sec = tab.dataset.section;
        if (sec === 'prompt' && !tab.dataset.promptRendered) {
            tab.dataset.promptRendered = '1';
            renderPromptSection(PAGE_DATA);
        }
        if (sec === 'old-prompt' && !tab.dataset.oldPromptRendered) {
            tab.dataset.oldPromptRendered = '1';
            renderOldPromptSection(PAGE_DATA);
        }
    });
});

// ═══ AI Rating Component ═══
(function initRating() {
    const starsEl = document.getElementById('rating-stars');
    const scoreEl = document.getElementById('rating-score');
    const feedbackEl = document.getElementById('rating-feedback');
    const metaEl = document.getElementById('rating-meta');
    const stars = starsEl.querySelectorAll('.star');
    const LS_KEY = 'nickel_ai_ratings';

    // Load saved ratings
    let ratings = [];
    try { ratings = JSON.parse(localStorage.getItem(LS_KEY) || '[]'); } catch(e) { ratings = []; }

    // Current analysis hash (based on timestamp as simple ID)
    function getAnalysisId() {
        return PAGE_DATA ? PAGE_DATA._updated_at || 'unknown' : 'unknown';
    }

    function getCurrentRating() {
        const id = getAnalysisId();
        return ratings.find(r => r.id === id) || null;
    }

    function saveRating(score, feedback) {
        const id = getAnalysisId();
        const existing = ratings.findIndex(r => r.id === id);
        const entry = { id, score, feedback, time: new Date().toISOString() };
        if (existing >= 0) ratings[existing] = entry;
        else ratings.push(entry);
        // Keep last 50 ratings
        if (ratings.length > 50) ratings = ratings.slice(-50);
        localStorage.setItem(LS_KEY, JSON.stringify(ratings));
    }

    function renderStars(score) {
        stars.forEach(s => {
            const sVal = parseInt(s.dataset.score);
            s.classList.toggle('active', sVal <= score);
        });
        scoreEl.textContent = score ? score + '/10' : '未评分';
    }

    function updateMeta() {
        const avg = ratings.length > 0 ? (ratings.reduce((a, b) => a + b.score, 0) / ratings.length).toFixed(1) : '--';
        metaEl.textContent = ratings.length > 0 ? `累计评分 ${ratings.length} 次 | 均分 ${avg}` : '';
    }

    // Restore saved rating for current analysis
    const saved = getCurrentRating();
    if (saved) {
        renderStars(saved.score);
        feedbackEl.value = saved.feedback || '';
    }
    updateMeta();

    // Star click handlers
    stars.forEach(s => {
        s.addEventListener('click', () => {
            const score = parseInt(s.dataset.score);
            renderStars(score);
            saveRating(score, feedbackEl.value);
            updateMeta();
        });
        s.addEventListener('mouseenter', () => {
            const score = parseInt(s.dataset.score);
            renderStars(score);
        });
    });
    starsEl.addEventListener('mouseleave', () => {
        const saved = getCurrentRating();
        renderStars(saved ? saved.score : 0);
    });

    // Feedback auto-save on input
    let saveTimer;
    feedbackEl.addEventListener('input', () => {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => {
            const saved = getCurrentRating();
            if (saved) {
                saveRating(saved.score, feedbackEl.value);
            }
        }, 500);
    });

    // Re-render when data updates
    const origRenderAI = window.renderAI;
    if (origRenderAI) {
        window.renderAI = function() {
            origRenderAI();
            // Reset rating display for new data
            const saved = getCurrentRating();
            renderStars(saved ? saved.score : 0);
            feedbackEl.value = saved ? (saved.feedback || '') : '';
            updateMeta();
        };
    }
})();

