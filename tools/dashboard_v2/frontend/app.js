/* Bitvavo Bot — Dashboard V2 controller (Alpine + Chart.js) */

const eur = new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 });

// SVG icons (inline, monochrome)
// Chart.js instances live OUTSIDE Alpine reactive scope to avoid Proxy recursion bugs.
const CHARTS = {};

const ICONS = {
  overview: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3 12 7 8l4 4 4-4 6 6"/><path d="M3 19h18"/></svg>',
  trades:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M5 9h14M5 15h14"/><path d="M9 5l-4 4 4 4M15 11l4 4-4 4"/></svg>',
  ai:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="4"/></svg>',
  memory:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><rect x="4" y="6" width="16" height="12" rx="2"/><path d="M8 10v4M12 10v4M16 10v4"/></svg>',
  shadow:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16"/></svg>',
  roadmap:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 6l16-2v4l-16 2zM4 14l16-2v4l-16 2z"/></svg>',
  params:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2-1.2L14 3h-4l-.6 2.6a7 7 0 0 0-2 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-.9c.6.5 1.3.9 2 1.2L10 21h4l.6-2.6c.7-.3 1.4-.7 2-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z"/></svg>',
  grid:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><rect x="14" y="14" width="6" height="6"/></svg>',
  hodl:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M12 2v20M2 12h20"/><circle cx="12" cy="12" r="9"/></svg>',
  markets:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3 18l6-8 4 4 8-10"/><path d="M14 4h7v7"/></svg>',
  scores:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><rect x="4" y="13" width="3" height="7"/><rect x="10" y="8" width="3" height="12"/><rect x="16" y="4" width="3" height="16"/></svg>',
};

function dash() {
  return {
    tab: 'overview',
    tabs: [
      { id: 'overview',   label: 'Overzicht',  subtitle: 'Live status van je portfolio', icon: ICONS.overview },
      { id: 'trades',     label: 'Trades',     subtitle: 'Open & gesloten posities + statistieken', icon: ICONS.trades },
      { id: 'ai',         label: 'AI',         subtitle: 'Supervisor suggesties & model metrics', icon: ICONS.ai },
      { id: 'memory',     label: 'Geheugen',   subtitle: 'BotMemory facts & log', icon: ICONS.memory },
      { id: 'shadow',     label: 'Shadow',     subtitle: 'Hypothetische rotaties', icon: ICONS.shadow },
      { id: 'roadmap',    label: 'Roadmap',    subtitle: 'Fase & stortingen', icon: ICONS.roadmap },
      { id: 'parameters', label: 'Parameters', subtitle: 'Live config (layer-3)', icon: ICONS.params },
      { id: 'grid',       label: 'Grid',       subtitle: 'Grid trading per markt', icon: ICONS.grid },
      { id: 'hodl',       label: 'HODL',       subtitle: 'Lange-termijn posities', icon: ICONS.hodl },
      { id: 'markets',    label: 'Markten',    subtitle: 'Live markt-metrics', icon: ICONS.markets },
      { id: 'scores',     label: 'Scores',     subtitle: 'Live + historische signal-scores per scan', icon: ICONS.scores },
    ],
    p: {}, t: {}, perf: {}, a: {}, m: {}, s: {}, r: {}, hb: {}, gr: {}, hd: {}, par: {}, rd: {}, d: {}, mk: {}, bh: {}, sg: {}, sc: {},
    closedFilter: '',
    paramFilter: '',
    marketsFilter: '',
    periodEquity: '30d',
    refreshTimer: null,
    secondsAgo: 0,
    lastRefresh: 0,
    toast: { show: false, msg: '', error: false },
    // Live price-flash state — keyed by market.
    // _prevPrices stores the last seen current_price; priceFlash is reactive
    // and toggled per refresh so the CSS animation re-triggers on each change.
    _prevPrices: {},
    priceFlash: {},   // market -> { dir: 'up'|'down', tick: number }
    _refreshing: false,
    _refreshFailStreak: 0,
    theme: (typeof localStorage !== 'undefined' && localStorage.getItem('bvb_theme')) || 'dark',

    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('bvb_theme', this.theme); } catch {}
      document.documentElement.setAttribute('data-theme', this.theme);
      // Re-render charts so colors pick up new theme
      this.$nextTick(() => this.renderCharts());
    },

    currentTab() { return this.tabs.find(x => x.id === this.tab) || this.tabs[0]; },

    // ---------- formatters
    fmtEur(v) { if (v == null || isNaN(v)) return '—'; return eur.format(+v); },
    fmtNum(v, dp = 2) { if (v == null || isNaN(v)) return '—'; return (+v).toLocaleString('nl-NL', { minimumFractionDigits: dp, maximumFractionDigits: dp }); },
    fmtPrice(v) {
      if (v == null || isNaN(v)) return '—';
      const n = +v;
      const dp = n >= 1000 ? 2 : (n >= 10 ? 3 : (n >= 1 ? 4 : (n >= 0.01 ? 5 : 6)));
      return '€' + n.toLocaleString('nl-NL', { minimumFractionDigits: dp, maximumFractionDigits: dp });
    },
    fmtDate(ts) { if (!ts) return '—'; const d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts); return d.toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' }); },
    fmtAge(s) { if (s == null) return '—'; if (s < 60) return Math.round(s) + 's'; if (s < 3600) return Math.round(s / 60) + 'm'; if (s < 86400) return (s / 3600).toFixed(1) + 'h'; return (s / 86400).toFixed(1) + 'd'; },
    ageHrs(ts) { if (!ts) return '—'; const sec = Date.now() / 1000 - (typeof ts === 'number' && ts < 1e12 ? ts : ts / 1000); return this.fmtAge(sec); },

    param(key) {
      for (const sect of Object.values(this.par.sections || {})) if (key in sect) return sect[key];
      if ((this.par.other || {})[key] !== undefined) return this.par.other[key];
      return null;
    },
    impactClass(i) { return i === 'HIGH' ? 'red' : i === 'MEDIUM' ? 'amber' : 'cyan'; },

    closedPct(c) {
      if (c.profit_pct != null) return c.profit_pct;
      const inv = c.initial_invested_eur || c.invested_eur;
      if (inv && c.profit != null) return (c.profit / inv) * 100;
      return null;
    },

    // ---------- PnL aggregation (today/this-week/this-month)
    _pnlBucket(list, key, value) {
      const row = (list || []).find(r => r && r[key] === value);
      return row ? { pnl: +row.pnl || 0, trades: +row.trades || 0, fees: +row.fees || 0 } : { pnl: 0, trades: 0, fees: 0 };
    },
    get pnlToday() {
      const d = new Date();
      const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
      return this._pnlBucket(this.p.daily, 'day', key);
    },
    get pnlWeek() {
      // ISO week — match backend's strftime('%V')
      const d = new Date();
      const target = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
      const dayNr = (target.getUTCDay() + 6) % 7;
      target.setUTCDate(target.getUTCDate() - dayNr + 3);
      const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
      const week = 1 + Math.round(((target - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
      const key = `${target.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
      return this._pnlBucket(this.p.weekly, 'week', key);
    },
    get pnlMonth() {
      const d = new Date();
      const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
      return this._pnlBucket(this.p.monthly, 'month', key);
    },
    get avg7Day() {
      const list = (this.p.daily || []).slice(-7);
      if (!list.length) return 0;
      return list.reduce((a, r) => a + (+r.pnl || 0), 0) / list.length;
    },
    get avg4Week() {
      const list = (this.p.weekly || []).slice(-4);
      if (!list.length) return 0;
      return list.reduce((a, r) => a + (+r.pnl || 0), 0) / list.length;
    },
    filteredClosed() {
      const f = (this.closedFilter || '').toLowerCase();
      const list = this.t.closed_recent || [];
      if (!f) return list;
      return list.filter(c => (c.market || '').toLowerCase().includes(f));
    },
    filteredMarkets() {
      const f = (this.marketsFilter || '').toLowerCase();
      const list = this.mk.markets || [];
      if (!f) return list;
      return list.filter(m => (m.market || '').toLowerCase().includes(f));
    },

    // ---------- scores tab helpers
    scoreBuckets() {
      const order = ['<5','5-7','7-9','9-12','12-15','15-18','>=18'];
      const colors = ['#f87171','#fb923c','#fbbf24','#facc15','#a3e635','#4ade80','#22d3ee'];
      const totals = (this.sc && this.sc.aggregate && this.sc.aggregate.buckets_total) || {};
      const sum = order.reduce((s,k) => s + (+totals[k] || 0), 0) || 1;
      return order.map((k,i) => ({
        label: k,
        count: +totals[k] || 0,
        pct: ((+totals[k] || 0) / sum * 100).toFixed(1),
        color: colors[i],
      }));
    },
    topMarkets(row) {
      const t5 = row && row.top5;
      if (!Array.isArray(t5) || !t5.length) return '—';
      return t5.slice(0,3).map(e => {
        const m = e.m || e.market || '?';
        const s = +(e.s ?? e.score ?? 0);
        return m.replace('-EUR','') + ' ' + s.toFixed(1);
      }).join(' · ');
    },

    // ---------- bootstrap
    async boot() {
      document.documentElement.setAttribute('data-theme', this.theme);
      if ('serviceWorker' in navigator) { try { await navigator.serviceWorker.register('/sw.js'); } catch {} }
      await this.refresh();
      // 5s poll: /api/all is heavy (200KB+, can take several seconds).
      // Use 5s and let the in-flight guard drop overlapping calls.
      this.refreshTimer = setInterval(() => this.refresh(), 5000);
      setInterval(() => { this.secondsAgo = Math.floor(Date.now() / 1000) - this.lastRefresh; }, 1000);
    },

    async refresh() {
      // Prevent overlapping calls: /api/all can take 5-10s on cold runs.
      if (this._refreshing) return;
      this._refreshing = true;
      try {
        const ctrl = new AbortController();
        const timeoutId = setTimeout(() => ctrl.abort(), 30000);
        const res = await fetch('/api/all', { cache: 'no-store', signal: ctrl.signal });
        clearTimeout(timeoutId);
        if (!res.ok) throw new Error('http ' + res.status);
        const d = await res.json();
        this._refreshFailStreak = 0;
        this.p   = d.portfolio  || {};
        this.t   = d.trades     || {};
        this.perf= d.performance|| {};
        this.a   = d.ai         || {};
        this.m   = d.memory     || {};
        this.s   = d.shadow     || {};
        this.r   = d.regime     || {};
        this.hb  = d.heartbeat  || {};
        this.gr  = d.grid       || {};
        this.hd  = d.hodl       || {};
        this.par = d.parameters || {};
        this.rd  = d.roadmap    || {};
        this.d   = d.deposits   || {};
        this.bh  = d.balance_history || {};
        this.sg  = d.signal_status || {};
        this.sc  = d.scores || {};
        // ---- Diff live prices to drive flash animations ----
        // FIX #080: t.open is a DICT keyed by market, not an array — must iterate Object.values.
        const openMap = (this.t && this.t.open) || {};
        const opens = Array.isArray(openMap) ? openMap : Object.values(openMap);
        for (const tr of opens) {
          if (!tr || typeof tr !== 'object') continue;
          const mk = tr.market;
          if (!mk) continue;
          const cur = +tr.current_price;
          if (!isFinite(cur)) continue;
          const prev = this._prevPrices[mk];
          if (prev != null && cur !== prev) {
            this.priceFlash[mk] = { dir: cur > prev ? 'up' : 'down', tick: Date.now() };
          }
          this._prevPrices[mk] = cur;
        }
        // Markets is heavy — fetch separately on demand
        if (this.tab === 'markets' && !this.mk.markets) await this.loadMarkets();
        this.lastRefresh = Math.floor(Date.now() / 1000);
        this.secondsAgo = 0;
        await this.$nextTick();
        this.renderCharts();
      } catch (e) {
        console.warn('refresh failed', e);
        this._refreshFailStreak += 1;
        // Only surface a toast after 5 consecutive failures (~25s of silence).
        if (this._refreshFailStreak === 5) {
          this.flash('Verbinding traag of mislukt — retry op de achtergrond', true);
        }
      } finally {
        this._refreshing = false;
      }
    },

    async loadMarkets() {
      try {
        const r = await fetch('/api/markets'); this.mk = await r.json();
      } catch {}
    },

    async refreshBalanceHistory() {
      try {
        const r = await fetch('/api/balance-history?period=' + this.periodEquity);
        this.bh = await r.json();
        await this.$nextTick();
        this.renderEquity();
      } catch {}
    },

    async saveParam(key, valueStr) {
      let value;
      try { value = JSON.parse(valueStr); } catch { value = valueStr; }
      try {
        const r = await fetch('/api/parameters', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key, value }),
        });
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        this.flash(`Saved ${key} = ${JSON.stringify(value)}`);
        await this.refresh();
      } catch (e) {
        this.flash('Save mislukt: ' + e.message, true);
      }
    },

    flash(msg, error = false) {
      this.toast = { show: true, msg, error };
      setTimeout(() => { this.toast.show = false; }, 3500);
    },

    // ---------- charts
    renderCharts() {
      this.renderEquity();
      this.renderAlloc();
      this.renderDaily();
      this.renderPerMarket();
    },

    renderEquity() {
      const ctx = document.getElementById('chartEquity'); if (!ctx) return;
      const bh = this.bh || {};
      const labels = bh.labels || [];
      const values = bh.values || [];
      this._upsert('chartEquity', ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Account €',
            data: values,
            borderColor: '#10b981',
            backgroundColor: ctx => {
              const c = ctx.chart.ctx, g = c.createLinearGradient(0, 0, 0, 220);
              g.addColorStop(0, 'rgba(16,185,129,0.30)'); g.addColorStop(1, 'rgba(16,185,129,0)');
              return g;
            },
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2,
          }]
        },
        options: this._opts({ legend: false, ticksX: 6 })
      });
    },

    renderAlloc() {
      const ctx = document.getElementById('chartAlloc'); if (!ctx) return;
      const open = this.t.open || {};
      const labels = [], data = [];
      for (const [m, tr] of Object.entries(open)) {
        labels.push(m.replace('-EUR', ''));
        data.push(tr.current_value_eur || tr.initial_invested_eur || 0);
      }
      const eurFree = +(this.p.eur_balance || 0);
      if (eurFree > 0.5) { labels.push('EUR'); data.push(eurFree); }
      const palette = ['#10b981','#06b6d4','#3b82f6','#8b5cf6','#ec4899','#f43f5e','#f59e0b','#84cc16','#14b8a6','#a855f7'];
      this._upsert('chartAlloc', ctx, {
        type: 'doughnut',
        data: { labels, datasets: [{ data, backgroundColor: palette, borderWidth: 0 }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          cutout: '65%',
          plugins: {
            legend: { position: 'right', labels: { color: this.theme === 'light' ? '#1A2238' : '#cbd5e1', font: { size: 11 }, boxWidth: 10 } },
            tooltip: { callbacks: { label: (c) => `${c.label}: ${eur.format(c.raw)}` } }
          }
        }
      });
    },

    renderDaily() {
      const ctx = document.getElementById('chartDaily'); if (!ctx) return;
      const data = this.p.daily || [];
      const labels = data.map(d => d.day);
      const values = data.map(d => d.pnl);
      this._upsert('chartDaily', ctx, {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Daily PnL €',
            data: values,
            backgroundColor: values.map(v => v >= 0 ? 'rgba(16,185,129,.75)' : 'rgba(244,63,94,.75)'),
            borderRadius: 3, borderSkipped: false,
          }]
        },
        options: this._opts({ legend: false })
      });
    },

    renderPerMarket() {
      const ctx = document.getElementById('chartPerMarket'); if (!ctx) return;
      const arr = (this.perf.per_market || []).slice(0, 15);
      this._upsert('chartPerMarket', ctx, {
        type: 'bar',
        data: {
          labels: arr.map(x => (x.market || '').replace('-EUR', '')),
          datasets: [{
            label: 'PnL €',
            data: arr.map(x => x.pnl),
            backgroundColor: arr.map(x => x.pnl >= 0 ? 'rgba(16,185,129,.75)' : 'rgba(244,63,94,.75)'),
            borderRadius: 3
          }]
        },
        options: { ...this._opts({ legend: false }), indexAxis: 'y' }
      });
    },

    _upsert(key, ctx, cfg) {
      if (CHARTS[key]) { CHARTS[key].data = cfg.data; CHARTS[key].update('none'); return; }
      CHARTS[key] = new Chart(ctx, cfg);
    },

    _opts({ legend = true, ticksX = 8 } = {}) {
      const isLight = this.theme === 'light';
      const tick = isLight ? '#5A6786' : '#94a3b8';
      const lbl  = isLight ? '#1A2238' : '#cbd5e1';
      const grid = isLight ? 'rgba(28,40,70,.08)' : 'rgba(148,163,184,.07)';
      const ttipBg = isLight ? 'rgba(255,255,255,.97)' : 'rgba(15,23,42,.95)';
      const ttipBd = isLight ? '#DDE4EE' : '#1f2937';
      const ttipTitle = isLight ? '#1A2238' : '#fff';
      const ttipBody  = isLight ? '#5A6786' : '#cbd5e1';
      return {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 250 },
        plugins: {
          legend: { display: legend, labels: { color: lbl, font: { size: 11 } } },
          tooltip: { backgroundColor: ttipBg, borderColor: ttipBd, borderWidth: 1, titleColor: ttipTitle, bodyColor: ttipBody, padding: 10 }
        },
        scales: {
          x: { ticks: { color: tick, font: { size: 10 }, maxTicksLimit: ticksX, autoSkip: true, maxRotation: 0 }, grid: { color: grid } },
          y: { ticks: { color: tick, font: { size: 10 } }, grid: { color: grid } }
        }
      };
    },
  };
}
