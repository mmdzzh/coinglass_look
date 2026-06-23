const API_BASE = '';
let oiChart = null;
let latestTable = null;
let changeTable = null;
let pairsMap = {};
let sources = [];
let currentSource = '';
let currentSymbol = '';
let currentInterval = '1d';

function formatNumber(value) {
    if (value === null || value === undefined || isNaN(value)) return '-';
    const num = Number(value);
    if (Math.abs(num) >= 1e12) return (num / 1e12).toFixed(2) + 'T';
    if (Math.abs(num) >= 1e9) return (num / 1e9).toFixed(2) + 'B';
    if (Math.abs(num) >= 1e6) return (num / 1e6).toFixed(2) + 'M';
    if (Math.abs(num) >= 1e3) return (num / 1e3).toFixed(2) + 'K';
    return num.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatDateTime(isoString) {
    if (!isoString) return '-';
    const d = new Date(isoString);
    return d.toLocaleString('zh-CN', { hour12: false });
}

function formatDate(isoString) {
    if (!isoString) return '-';
    return new Date(isoString).toLocaleDateString('zh-CN');
}

function toInputValue(date) {
    return date.toISOString().slice(0, 10);
}

function setLoading(el, text = '-') {
    el.textContent = text;
}

async function loadSources() {
    const res = await fetch(`${API_BASE}/api/sources`);
    sources = await res.json();
    const select = document.getElementById('sourceSelect');
    select.innerHTML = '';
    sources.forEach(s => {
        const option = document.createElement('option');
        option.value = s;
        option.textContent = s.toUpperCase();
        select.appendChild(option);
    });
    currentSource = sources[0] || '';
    select.value = currentSource;
    select.addEventListener('change', async () => {
        currentSource = select.value;
        await loadPairs();
        await loadLatest();
        await loadChart();
    });
}

async function loadPairs() {
    const res = await fetch(`${API_BASE}/api/pairs?source=${currentSource}&active_only=true`);
    const pairs = await res.json();
    const select = document.getElementById('symbolSelect');
    const datalist = document.getElementById('symbolList');
    const previousSymbol = currentSymbol;
    select.innerHTML = '';
    datalist.innerHTML = '';
    pairsMap = {};
    pairs.forEach(p => {
        pairsMap[p.symbol] = p;
        const option = document.createElement('option');
        option.value = p.symbol;
        option.textContent = p.symbol;
        select.appendChild(option);

        const dlOption = document.createElement('option');
        dlOption.value = p.symbol;
        datalist.appendChild(dlOption);
    });
    if (pairs.length > 0) {
        // Try to keep the previously selected symbol if it exists in the new source.
        let target = pairs.find(p => p.symbol === previousSymbol);
        if (!target) {
            target = pairs.find(p => p.symbol === 'BTCUSDT') || pairs[0];
        }
        currentSymbol = target.symbol;
        select.value = target.symbol;
        updateOverviewCards(target);
    }
}

function filterSymbols(query) {
    const select = document.getElementById('symbolSelect');
    const options = Array.from(select.options);
    const q = query.trim().toUpperCase();
    options.forEach(opt => {
        opt.style.display = (!q || opt.value.toUpperCase().includes(q)) ? '' : 'none';
    });
}

function selectSymbol(symbol) {
    const upper = symbol.trim().toUpperCase();
    if (!upper || !pairsMap[upper]) return false;
    currentSymbol = upper;
    document.getElementById('symbolSelect').value = currentSymbol;
    document.getElementById('symbolSearch').value = '';
    filterSymbols('');
    updateOverviewCards(pairsMap[currentSymbol]);
    loadChart();
    return true;
}

function updateOverviewCards(meta) {
    if (!meta) return;
    document.getElementById('activeOnboard').textContent = formatDateTime(meta.onboard_date);
}

async function loadLatest() {
    try {
        const res = await fetch(`${API_BASE}/api/oi/latest?source=${currentSource}&limit=100`);
        const data = await res.json();
        if (!Array.isArray(data)) return;

        renderLatestTable(data);
        renderChangeTable(data);
        updateTotalOverview(data);
    } catch (err) {
        console.error('loadLatest failed:', err);
    }
}

function updateTotalOverview(data) {
    if (!data.length) return;
    const total = data.reduce((sum, row) => sum + (Number(row.sum_open_interest_value) || 0), 0);
    document.getElementById('totalOiValue').textContent = formatNumber(total);

    // Compute 24h change using the last two daily snapshots available (data is already latest per symbol)
    // This is an approximation; for true 24h change we'd need historical snapshot per symbol.
    document.getElementById('totalOiChange').textContent = '-';
}

function renderLatestTable(data) {
    const rows = data.map((row, index) => [
        index + 1,
        `<a href="#" class="pair-link" data-symbol="${row.symbol}">${row.symbol}</a>`,
        formatNumber(row.sum_open_interest_value),
        formatNumber(row.sum_open_interest),
    ]);

    if (latestTable) {
        latestTable.clear().rows.add(rows).draw();
    } else {
        latestTable = new DataTable('#latestTable', {
            pageLength: 10,
            order: [[0, 'asc']],
            autoWidth: false,
            columnDefs: [{ targets: [0], width: '40px' }],
        });
        latestTable.clear().rows.add(rows).draw();
    }

    document.querySelectorAll('#latestTable .pair-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            currentSymbol = e.target.dataset.symbol;
            document.getElementById('symbolSelect').value = currentSymbol;
            updateOverviewCards(pairsMap[currentSymbol]);
            loadChart();
        });
    });
}

function renderChangeTable(data) {
    const rows = data.map((row, index) => {
        const change = row.change_percent;
        let changeClass = 'muted';
        let changeText = '-';
        if (change !== null && change !== undefined) {
            changeClass = change >= 0 ? 'positive' : 'negative';
            changeText = (change >= 0 ? '+' : '') + change.toFixed(2) + '%';
        }
        return [
            index + 1,
            row.symbol,
            formatNumber(row.sum_open_interest_value),
            formatNumber(row.prev_open_interest_value),
            `<span class="${changeClass}">${changeText}</span>`,
        ];
    });

    if (changeTable) {
        changeTable.clear().rows.add(rows).draw();
    } else {
        changeTable = new DataTable('#changeTable', {
            pageLength: 10,
            order: [[0, 'asc']],
            autoWidth: false,
            columnDefs: [{ targets: [0], width: '40px' }],
        });
        changeTable.clear().rows.add(rows).draw();
    }
}

async function loadChart() {
    if (!currentSymbol || !currentSource) return;

    const start = document.getElementById('startDate').value;
    const end = document.getElementById('endDate').value;
    const params = new URLSearchParams({ source: currentSource, interval: currentInterval });
    if (start) params.append('start', new Date(start).toISOString());
    if (end) params.append('end', new Date(end).toISOString());

    const res = await fetch(`${API_BASE}/api/oi/${currentSymbol}?${params.toString()}`);
    const json = await res.json();
    const data = json.data || [];

    updateChartStats(data);
    renderChart(currentSymbol, currentInterval, data);
}

function updateChartStats(data) {
    if (!data.length) {
        document.getElementById('activeOi').textContent = '-';
        document.getElementById('activeOiValue').textContent = '-';
        return;
    }
    const latest = data[data.length - 1];
    document.getElementById('activeOi').textContent = formatNumber(latest.sum_open_interest);
    document.getElementById('activeOiValue').textContent = formatNumber(latest.sum_open_interest_value);
}

function renderChart(symbol, interval, data) {
    if (!oiChart) {
        oiChart = echarts.init(document.getElementById('oiChart'));
    }

    const times = data.map(d => formatDateTime(d.timestamp));
    const oiValues = data.map(d => d.sum_open_interest);
    const oiValueValues = data.map(d => d.sum_open_interest_value);

    const option = {
        backgroundColor: 'transparent',
        textStyle: { color: '#f0f2f5' },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: '#181c27',
            borderColor: '#2e3547',
            textStyle: { color: '#f0f2f5' }
        },
        legend: {
            data: ['持仓量（币）', '持仓价值（USDT）'],
            top: 0,
            right: 0,
            textStyle: { color: '#8b95a8' }
        },
        grid: { left: '3%', right: '4%', bottom: '10%', top: '12%', containLabel: true },
        xAxis: {
            type: 'category',
            data: times,
            axisLine: { lineStyle: { color: '#2e3547' } },
            axisLabel: { color: '#8b95a8' }
        },
        yAxis: [
            {
                type: 'value',
                name: '持仓量',
                position: 'left',
                axisLine: { show: false },
                axisLabel: { color: '#f7a600' },
                splitLine: { lineStyle: { color: '#242a38' } },
                nameTextStyle: { color: '#8b95a8' }
            },
            {
                type: 'value',
                name: '持仓价值',
                position: 'right',
                axisLine: { show: false },
                axisLabel: { color: '#00c582' },
                splitLine: { show: false },
                nameTextStyle: { color: '#8b95a8' }
            }
        ],
        dataZoom: [
            { type: 'inside', start: 0, end: 100 },
            { type: 'slider', start: 0, end: 100, bottom: 0, height: 20, borderColor: '#242a38', fillerColor: 'rgba(247, 166, 0, 0.2)' }
        ],
        series: [
            {
                name: '持仓量（币）',
                type: 'line',
                data: oiValues,
                smooth: true,
                showSymbol: false,
                itemStyle: { color: '#f7a600' },
                lineStyle: { width: 2 },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(247, 166, 0, 0.35)' },
                        { offset: 1, color: 'rgba(247, 166, 0, 0.02)' }
                    ])
                }
            },
            {
                name: '持仓价值（USDT）',
                type: 'line',
                yAxisIndex: 1,
                data: oiValueValues,
                smooth: true,
                showSymbol: false,
                itemStyle: { color: '#00c582' },
                lineStyle: { width: 2 }
            }
        ]
    };

    oiChart.setOption(option, true);
}

function resetDates() {
    const end = new Date();
    const start = new Date('2020-01-01');
    document.getElementById('startDate').value = toInputValue(start);
    document.getElementById('endDate').value = toInputValue(end);
}

async function triggerSync() {
    const btn = document.getElementById('syncBtn');
    btn.disabled = true;
    btn.textContent = '同步中...';
    try {
        const res = await fetch(`${API_BASE}/admin/sync?source=${currentSource}&symbols=${encodeURIComponent(currentSymbol)}`, { method: 'POST' });
        const data = await res.json();
        if (data.running) {
            pollSyncStatus();
        } else {
            await loadPairs();
            await loadLatest();
            await loadChart();
            btn.disabled = false;
            btn.textContent = '立即同步';
        }
    } catch (err) {
        console.error('Sync failed:', err);
        btn.disabled = false;
        btn.textContent = '立即同步';
    }
}

function pollSyncStatus() {
    const btn = document.getElementById('syncBtn');
    const interval = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/admin/sync/status?source=${currentSource}`);
            const data = await res.json();
            if (!data.running) {
                clearInterval(interval);
                await loadPairs();
                await loadLatest();
                await loadChart();
                btn.disabled = false;
                btn.textContent = '立即同步';
                console.log('Sync finished:', data.message);
            } else {
                btn.textContent = data.message || `同步中... (${data.rows || 0} rows)`;
            }
        } catch (err) {
            console.error('Sync status poll failed:', err);
            clearInterval(interval);
            btn.disabled = false;
            btn.textContent = '立即同步';
        }
    }, 2000);
}

document.addEventListener('DOMContentLoaded', async () => {
    resetDates();
    await loadSources();
    await loadPairs();
    await loadLatest();
    await loadChart();

    document.getElementById('loadBtn').addEventListener('click', loadChart);
    document.getElementById('syncBtn').addEventListener('click', triggerSync);
    document.getElementById('symbolSelect').addEventListener('change', (e) => {
        currentSymbol = e.target.value;
        updateOverviewCards(pairsMap[currentSymbol]);
        loadChart();
    });

    const searchInput = document.getElementById('symbolSearch');
    searchInput.addEventListener('input', (e) => {
        filterSymbols(e.target.value);
    });
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const q = e.target.value.trim().toUpperCase();
            if (!q) return;
            // exact match first
            if (selectSymbol(q)) return;
            const options = Array.from(document.getElementById('symbolSelect').options);
            const visible = options.filter(o => o.style.display !== 'none');
            // prefer exact "q + USDT" match
            const usdtMatch = visible.find(o => o.value.toUpperCase() === q + 'USDT');
            if (usdtMatch) {
                selectSymbol(usdtMatch.value);
                return;
            }
            // prefer shortest prefix match
            const prefixMatches = visible.filter(o => o.value.toUpperCase().startsWith(q));
            if (prefixMatches.length > 0) {
                prefixMatches.sort((a, b) => a.value.length - b.value.length);
                selectSymbol(prefixMatches[0].value);
                return;
            }
            // fallback to first visible option
            if (visible.length > 0) selectSymbol(visible[0].value);
        }
    });
    searchInput.addEventListener('change', (e) => {
        // triggered when user selects from datalist
        selectSymbol(e.target.value);
    });

    document.querySelectorAll('.interval-tabs button').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.interval-tabs button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentInterval = btn.dataset.interval;
            loadChart();
        });
    });

    window.addEventListener('resize', () => {
        if (oiChart) oiChart.resize();
    });
});
