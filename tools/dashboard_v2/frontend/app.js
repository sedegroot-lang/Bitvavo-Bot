/* Bitvavo Bot Dashboard V2 — Alpine controller + chart helpers */

const eur = new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' });

function dash() {
  return {
    tab: 'overview',
    tabs: [
      { id: 'overview', label: 'Overzicht' },
      { id: 'trades', label: 'Trades' },
      { id: 'ai', label: 'AI' },
      { id: 'memory', label: 'Geheugen' },
      { id: 'shadow', label: 'Shadow rotatie' },
    ],
    p: {}, t: {}, a: {}, m: {}, s: {}, r: {}, hb: {}, config: {},
    refreshTimer: null,
    chartDaily: null,
    chartWeekly: null,

    fmtEur(v) {
      if (v == null || isNaN(v)) return '—';
      return eur.format(+v);
    },
    fmtNum(v, dp = 2) {
      if (v == null || isNaN(v)) return '—';
      return (+v).toLocaleString('nl-NL', { minimumFractionDigits: dp, maximumFractionDigits: dp });
    },
    fmtDate(ts) {
      if (!ts) return '—';
      const d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
      return d.toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' });
    },
    ageHrs(ts) {
      if (!ts) return '—';
      const sec = Date.now() / 1000 - (typeof ts === 'number' && ts < 1e12 ? ts : ts / 1000);
      const h = sec / 3600;
      if (h < 1) return Math.round(sec / 60) + 'm';
      if (h < 48) return h.toFixed(1) + 'h';
      return (h / 24).toFixed(1) + 'd';
    },

    async boot() {
      // Register service worker (PWA install)
      if ('serviceWorker' in navigator) {
        try { await navigator.serviceWorker.register('/sw.js'); } catch (e) { /* ignore */ }
      }
      await this.refresh();
      this.refreshTimer = setInterval(() => this.refresh(), 15000);
    },

    async refresh() {
      try {
        const res = await fetch('/api/all', { cache: 'no-store' });
        if (!res.ok) throw new Error('http ' + res.status);
        const d = await res.json();
        this.p = d.portfolio || {};
        this.t = d.trades || {};
        this.a = d.ai || {};
        this.m = d.memory || {};
        this.s = d.shadow || {};
        this.r = d.regime || {};
        this.hb = d.heartbeat || {};
        this.renderCharts();
      } catch (e) {
        console.warn('refresh failed', e);
      }
    },

    renderCharts() {
      // Daily PnL bar chart
      const ctxD = document.getElementById('chartDaily');
      if (ctxD) {
        const data = this.p.daily || [];
        const labels = data.map(d => d.day);
        const values = data.map(d => d.pnl);
        const ds = {
          labels,
          datasets: [{
            label: 'Daily PnL (€)',
            data: values,
            backgroundColor: values.map(v => v >= 0 ? 'rgba(52,211,153,0.7)' : 'rgba(244,63,94,0.7)'),
            borderRadius: 3,
          }]
        };
        if (this.chartDaily) {
          this.chartDaily.data = ds;
          this.chartDaily.update('none');
        } else {
          this.chartDaily = new Chart(ctxD, {
            type: 'bar', data: ds,
            options: chartOpts()
          });
        }
      }
      // Weekly cumulative line
      const ctxW = document.getElementById('chartWeekly');
      if (ctxW) {
        const data = this.p.weekly || [];
        let cum = 0;
        const cumValues = data.map(d => (cum += d.pnl));
        const ds = {
          labels: data.map(d => d.week),
          datasets: [
            { label: 'Week PnL (€)', data: data.map(d => d.pnl), backgroundColor: 'rgba(34,211,238,0.6)', type: 'bar' },
            { label: 'Cumulatief', data: cumValues, borderColor: 'rgb(52,211,153)', backgroundColor: 'transparent', tension: 0.3, type: 'line', yAxisID: 'y' }
          ]
        };
        if (this.chartWeekly) {
          this.chartWeekly.data = ds;
          this.chartWeekly.update('none');
        } else {
          this.chartWeekly = new Chart(ctxW, { type: 'bar', data: ds, options: chartOpts() });
        }
      }
    },
  };
}

function chartOpts() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: '#cbd5e1', font: { size: 11 } } },
      tooltip: { backgroundColor: 'rgba(15,23,42,0.95)', titleColor: '#fff', bodyColor: '#cbd5e1' }
    },
    scales: {
      x: { ticks: { color: '#94a3b8', font: { size: 10 }, maxRotation: 0, autoSkip: true }, grid: { color: 'rgba(148,163,184,0.1)' } },
      y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: 'rgba(148,163,184,0.1)' } }
    }
  };
}
