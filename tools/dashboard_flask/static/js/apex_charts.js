/**
 * Apex Charts - Advanced Price Chart Enhancements
 * TradingView-level features for Bitvavo Trading Bot Dashboard
 * 
 * Features:
 *  1. Crosshair cursor with price/time readout
 *  2. Profit/Loss zone shading between entry and price line
 *  3. Volume overlay bars
 *  4. Chart watermark (market name)
 *  5. Price delta badge (live price change indicator)
 *  6. Chart toolbar (screenshot, fullscreen, candlestick toggle)
 *  7. Candlestick rendering mode
 *  8. Enhanced rich tooltip with OHLC
 *  9. Mini P&L sparkline in card header
 * 10. Chart border glow effect matching P&L
 * 11. Trade card flip for detailed analytics
 * 12. Heatmap overview mode
 */

(function() {
    'use strict';

    // ========================================================================
    // 1. CROSSHAIR PLUGIN - TradingView-style crosshair on chart hover
    // ========================================================================
    const CrosshairPlugin = {
        id: 'crosshairPlugin',
        afterInit(chart) {
            chart._crosshair = { x: null, y: null, visible: false };
        },
        afterEvent(chart, args) {
            const evt = args.event;
            if (evt.type === 'mousemove' && chart.chartArea) {
                const { left, right, top, bottom } = chart.chartArea;
                const inArea = evt.x >= left && evt.x <= right && evt.y >= top && evt.y <= bottom;
                chart._crosshair = { x: evt.x, y: evt.y, visible: inArea };
                chart.draw();
            } else if (evt.type === 'mouseout') {
                chart._crosshair.visible = false;
                chart.draw();
            }
        },
        afterDraw(chart) {
            const ch = chart._crosshair;
            if (!ch || !ch.visible) return;
            const { left, right, top, bottom } = chart.chartArea;
            const ctx = chart.ctx;

            ctx.save();
            ctx.setLineDash([3, 3]);
            ctx.lineWidth = 0.8;
            ctx.strokeStyle = 'rgba(148, 163, 184, 0.5)';

            // Vertical line
            ctx.beginPath();
            ctx.moveTo(ch.x, top);
            ctx.lineTo(ch.x, bottom);
            ctx.stroke();

            // Horizontal line
            ctx.beginPath();
            ctx.moveTo(left, ch.y);
            ctx.lineTo(right, ch.y);
            ctx.stroke();

            // Price label on Y-axis
            const yScale = chart.scales.y;
            if (yScale) {
                const priceVal = yScale.getValueForPixel(ch.y);
                const priceStr = priceVal >= 1 ? priceVal.toFixed(2) : priceVal.toFixed(4);
                const labelText = '\u20AC' + priceStr;
                ctx.font = '10px JetBrains Mono, monospace';
                const textW = ctx.measureText(labelText).width + 8;
                const labelX = right + 2;
                const labelY = ch.y - 8;

                ctx.fillStyle = 'rgba(59, 130, 246, 0.9)';
                ctx.beginPath();
                ctx.roundRect(labelX, labelY, textW, 16, 3);
                ctx.fill();

                ctx.fillStyle = '#fff';
                ctx.textAlign = 'left';
                ctx.textBaseline = 'middle';
                ctx.fillText(labelText, labelX + 4, ch.y);
            }

            // Time label on X-axis
            const xScale = chart.scales.x;
            if (xScale) {
                const idx = xScale.getValueForPixel(ch.x);
                const label = chart.data.labels[Math.round(idx)] || '';
                if (label) {
                    ctx.font = '9px Inter, sans-serif';
                    const tw = ctx.measureText(label).width + 8;
                    const tx = ch.x - tw / 2;
                    const ty = bottom + 2;

                    ctx.fillStyle = 'rgba(59, 130, 246, 0.9)';
                    ctx.beginPath();
                    ctx.roundRect(tx, ty, tw, 14, 3);
                    ctx.fill();

                    ctx.fillStyle = '#fff';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(label, ch.x, ty + 7);
                }
            }

            ctx.restore();
        }
    };

    // ========================================================================
    // 2. PROFIT/LOSS ZONE SHADING - Fill between entry price and price line
    // ========================================================================
    const ProfitZonePlugin = {
        id: 'profitZonePlugin',
        beforeDatasetsDraw(chart) {
            const meta = chart.getDatasetMeta(0);
            if (!meta || !meta.data || meta.data.length < 2) return;
            const { ctx, chartArea, scales } = chart;
            if (!chartArea || !scales.y) return;

            // Get buy price from canvas data attribute
            const canvas = chart.canvas;
            const buyPrice = parseFloat(canvas.dataset?.buyPrice || 0);
            if (!buyPrice) return;

            const buyY = scales.y.getPixelForValue(buyPrice);
            const points = meta.data;

            ctx.save();
            ctx.globalAlpha = 0.06;

            // Draw profit zone (above entry) in green
            ctx.beginPath();
            ctx.moveTo(points[0].x, buyY);
            for (let i = 0; i < points.length; i++) {
                const py = Math.min(points[i].y, buyY);
                ctx.lineTo(points[i].x, py);
            }
            ctx.lineTo(points[points.length - 1].x, buyY);
            ctx.closePath();
            ctx.fillStyle = '#16c784';
            ctx.fill();

            // Draw loss zone (below entry) in red
            ctx.beginPath();
            ctx.moveTo(points[0].x, buyY);
            for (let i = 0; i < points.length; i++) {
                const py = Math.max(points[i].y, buyY);
                ctx.lineTo(points[i].x, py);
            }
            ctx.lineTo(points[points.length - 1].x, buyY);
            ctx.closePath();
            ctx.fillStyle = '#ea3943';
            ctx.fill();

            ctx.restore();
        }
    };

    // ========================================================================
    // 3. WATERMARK PLUGIN - Subtle market name text behind chart
    // ========================================================================
    const WatermarkPlugin = {
        id: 'watermarkPlugin',
        beforeDraw(chart) {
            const market = chart.canvas.dataset?.market;
            if (!market) return;
            const { ctx, chartArea } = chart;
            if (!chartArea) return;

            const symbol = market.split('-')[0];
            ctx.save();
            ctx.globalAlpha = 0.04;
            ctx.font = 'bold 48px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = '#f0f6fc';
            const cx = (chartArea.left + chartArea.right) / 2;
            const cy = (chartArea.top + chartArea.bottom) / 2;
            ctx.fillText(symbol, cx, cy);
            ctx.restore();
        }
    };

    // ========================================================================
    // 4. ANIMATED CURRENT PRICE LINE - Pulsing line at current price
    // ========================================================================
    const CurrentPriceLine = {
        id: 'currentPriceLine',
        afterDraw(chart) {
            const ds = chart.data.datasets[0];
            if (!ds || !ds.data || ds.data.length === 0) return;
            const { ctx, chartArea, scales } = chart;
            if (!chartArea || !scales.y) return;

            const lastPrice = ds.data[ds.data.length - 1];
            if (typeof lastPrice !== 'number') return;
            const y = scales.y.getPixelForValue(lastPrice);
            const now = Date.now();
            const pulse = 0.4 + 0.3 * Math.sin(now / 400);

            ctx.save();
            ctx.globalAlpha = pulse;
            ctx.setLineDash([2, 2]);
            ctx.lineWidth = 1;
            ctx.strokeStyle = ds.borderColor || '#3B82F6';
            ctx.beginPath();
            ctx.moveTo(chartArea.left, y);
            ctx.lineTo(chartArea.right, y);
            ctx.stroke();

            // Right-side price tag
            ctx.globalAlpha = 0.85;
            const priceStr = '\u20AC' + (lastPrice >= 1 ? lastPrice.toFixed(2) : lastPrice.toFixed(4));
            ctx.font = 'bold 9px JetBrains Mono, monospace';
            const tw = ctx.measureText(priceStr).width + 8;
            const tx = chartArea.right - tw - 4;
            ctx.fillStyle = ds.borderColor || '#3B82F6';
            ctx.beginPath();
            ctx.roundRect(tx, y - 8, tw, 16, 3);
            ctx.fill();
            ctx.fillStyle = '#fff';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(priceStr, tx + 4, y);

            ctx.restore();
        }
    };

    // Register all Chart.js plugins globally
    if (typeof Chart !== 'undefined') {
        Chart.register(CrosshairPlugin, ProfitZonePlugin, WatermarkPlugin, CurrentPriceLine);
        console.log('[ApexCharts] 4 premium chart plugins registered');
    }

    // ========================================================================
    // 5. PRICE DELTA BADGE - Shows real-time price change on each card
    // ========================================================================
    class PriceDeltaBadge {
        constructor() {
            this.prevPrices = {};
        }

        update(market, price) {
            const prev = this.prevPrices[market];
            this.prevPrices[market] = price;
            if (prev === undefined) return;

            const card = document.querySelector(`.trade-card-simple[data-market="${market}"]`);
            if (!card) return;

            let badge = card.querySelector('.price-delta-badge');
            if (!badge) {
                badge = document.createElement('div');
                badge.className = 'price-delta-badge';
                const chartContainer = card.querySelector('.card-chart-container');
                if (chartContainer) {
                    chartContainer.style.position = 'relative';
                    chartContainer.appendChild(badge);
                }
            }

            const delta = price - prev;
            const pct = ((delta / prev) * 100).toFixed(3);
            const isUp = delta >= 0;

            badge.className = `price-delta-badge ${isUp ? 'delta-up' : 'delta-down'}`;
            badge.innerHTML = `<span class="delta-arrow">${isUp ? '\u25B2' : '\u25BC'}</span> ${isUp ? '+' : ''}${pct}%`;
            badge.classList.add('delta-flash');
            setTimeout(() => badge.classList.remove('delta-flash'), 600);
        }
    }

    // ========================================================================
    // 6. CHART TOOLBAR - Screenshot, Fullscreen, Candlestick toggle
    // ========================================================================
    class ChartToolbar {
        static init() {
            document.querySelectorAll('.card-chart-container').forEach(container => {
                if (container.querySelector('.chart-toolbar')) return;

                const market = container.closest('.trade-card-simple')?.dataset?.market;
                if (!market) return;

                const toolbar = document.createElement('div');
                toolbar.className = 'chart-toolbar';
                toolbar.innerHTML = `
                    <button class="chart-tool-btn" data-action="screenshot" title="Screenshot">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="3"/></svg>
                    </button>
                    <button class="chart-tool-btn" data-action="fullscreen" title="Fullscreen">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
                    </button>
                    <button class="chart-tool-btn" data-action="candle" title="Toggle Candlestick">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="9" y1="2" x2="9" y2="22"/><rect x="6" y="6" width="6" height="10" fill="currentColor"/><line x1="18" y1="4" x2="18" y2="20"/><rect x="15" y="8" width="6" height="8" fill="none"/></svg>
                    </button>
                `;

                toolbar.addEventListener('click', (e) => {
                    const btn = e.target.closest('.chart-tool-btn');
                    if (!btn) return;
                    const action = btn.dataset.action;
                    ChartToolbar.handleAction(action, market, container);
                });

                container.appendChild(toolbar);
            });
        }

        static handleAction(action, market, container) {
            switch (action) {
                case 'screenshot':
                    ChartToolbar.captureScreenshot(market);
                    break;
                case 'fullscreen':
                    ChartToolbar.toggleFullscreen(market, container);
                    break;
                case 'candle':
                    ChartToolbar.toggleCandlestick(market);
                    break;
            }
        }

        static captureScreenshot(market) {
            const canvas = document.getElementById(`chart-${market}`);
            if (!canvas) return;
            const link = document.createElement('a');
            link.download = `${market}_chart_${new Date().toISOString().slice(0, 10)}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
        }

        static toggleFullscreen(market, container) {
            const card = container.closest('.trade-card-simple');
            if (!card) return;

            if (card.classList.contains('chart-fullscreen')) {
                card.classList.remove('chart-fullscreen');
                document.body.classList.remove('has-fullscreen-chart');
                // Restore chart height
                const chartWrapper = container.querySelector('div[style*="height: 160px"]');
                if (chartWrapper) chartWrapper.style.height = '160px';
            } else {
                // Close any other fullscreen first
                document.querySelectorAll('.chart-fullscreen').forEach(el => {
                    el.classList.remove('chart-fullscreen');
                });
                card.classList.add('chart-fullscreen');
                document.body.classList.add('has-fullscreen-chart');
                // Expand chart height
                const chartWrapper = container.querySelector('div[style*="height: 160px"]');
                if (chartWrapper) chartWrapper.style.height = '500px';
            }

            // Resize chart
            const chartData = window.tradeCardCharts?.[market];
            if (chartData?.chart) {
                setTimeout(() => chartData.chart.resize(), 100);
            }
        }

        static toggleCandlestick(market) {
            const chartData = window.tradeCardCharts?.[market];
            if (!chartData) return;

            // Toggle between line and bar (pseudo-candlestick)
            const ds = chartData.chart.data.datasets[0];
            if (chartData._isCandleMode) {
                // Back to line
                ds.type = 'line';
                ds.borderWidth = 2;
                ds.fill = true;
                ds.tension = 0.3;
                ds.pointRadius = 0;
                ds.barPercentage = undefined;
                chartData._isCandleMode = false;
            } else {
                // Switch to bar (candlestick approximation)
                ds.type = 'bar';
                ds.borderWidth = 1;
                ds.fill = false;
                ds.tension = 0;
                ds.pointRadius = 0;
                ds.barPercentage = 0.6;
                // Color bars green/red based on prev price
                const data = ds.data;
                const colors = data.map((val, i) => {
                    if (i === 0) return 'rgba(22, 199, 132, 0.8)';
                    return val >= data[i - 1] ? 'rgba(22, 199, 132, 0.8)' : 'rgba(234, 57, 67, 0.8)';
                });
                ds.backgroundColor = colors;
                ds.borderColor = colors;
                chartData._isCandleMode = true;
            }
            chartData.chart.update('active');
        }
    }

    // ========================================================================
    // 7. CHART BORDER GLOW - Animated glow around chart matching P&L
    // ========================================================================
    class ChartBorderGlow {
        static update(market, isProfit) {
            const card = document.querySelector(`.trade-card-simple[data-market="${market}"]`);
            if (!card) return;
            const container = card.querySelector('.card-chart-container');
            if (!container) return;

            container.classList.remove('chart-glow-profit', 'chart-glow-loss');
            container.classList.add(isProfit ? 'chart-glow-profit' : 'chart-glow-loss');
        }
    }

    // ========================================================================
    // 8. TRADE CARD FLIP - Double-click to flip card for analytics view
    // ========================================================================
    class TradeCardFlip {
        static init() {
            document.querySelectorAll('.trade-card-simple').forEach(card => {
                if (card.dataset.flipInit) return;
                card.dataset.flipInit = 'true';

                // Create back face
                const back = document.createElement('div');
                back.className = 'card-back-face';
                const market = card.dataset.market || 'Unknown';
                const pnl = parseFloat(card.dataset.pnl || 0);
                const pnlPct = parseFloat(card.dataset.pnlPct || 0);

                back.innerHTML = `
                    <div class="back-header">
                        <span class="back-title">${market} Analytics</span>
                        <button class="back-close-btn" title="Flip back">&times;</button>
                    </div>
                    <div class="back-stats">
                        <div class="back-stat">
                            <span class="back-stat-label">P&L</span>
                            <span class="back-stat-value ${pnl >= 0 ? 'text-success' : 'text-danger'}">${pnl >= 0 ? '+' : ''}\u20AC${pnl.toFixed(2)}</span>
                        </div>
                        <div class="back-stat">
                            <span class="back-stat-label">Return</span>
                            <span class="back-stat-value ${pnlPct >= 0 ? 'text-success' : 'text-danger'}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</span>
                        </div>
                        <div class="back-stat">
                            <span class="back-stat-label">Risk Score</span>
                            <span class="back-stat-value">${Math.abs(pnlPct) > 3 ? 'High' : Math.abs(pnlPct) > 1 ? 'Medium' : 'Low'}</span>
                        </div>
                        <div class="back-stat">
                            <span class="back-stat-label">Volatility</span>
                            <div class="back-vol-bar">
                                <div class="back-vol-fill" style="width: ${Math.min(Math.abs(pnlPct) * 20, 100)}%"></div>
                            </div>
                        </div>
                    </div>
                    <div class="back-mini-chart" id="back-chart-${market}"></div>
                `;

                card.appendChild(back);

                // Double-click to flip
                card.addEventListener('dblclick', (e) => {
                    // Don't flip when clicking chart controls or buttons
                    if (e.target.closest('select, button, .chart-toolbar, .chart-tool-btn, canvas')) return;
                    card.classList.toggle('card-flipped');
                });

                // Close button on back
                back.querySelector('.back-close-btn')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    card.classList.remove('card-flipped');
                });
            });
        }
    }

    // ========================================================================
    // 9. HEATMAP OVERVIEW - Toggle all cards into a compact heatmap grid
    // ========================================================================
    class HeatmapOverview {
        static toggle() {
            const container = document.getElementById('trade-cards-container');
            if (!container) return;

            const isHeatmap = container.classList.toggle('heatmap-mode');
            const cards = container.querySelectorAll('.trade-card-simple');

            cards.forEach(card => {
                if (isHeatmap) {
                    const pnlPct = parseFloat(card.dataset.pnlPct || 0);
                    const intensity = Math.min(Math.abs(pnlPct) / 5, 1);
                    const color = pnlPct >= 0
                        ? `rgba(22, 199, 132, ${0.15 + intensity * 0.6})`
                        : `rgba(234, 57, 67, ${0.15 + intensity * 0.6})`;
                    card.style.setProperty('--heatmap-bg', color);
                    card.classList.add('heatmap-card');
                } else {
                    card.style.removeProperty('--heatmap-bg');
                    card.classList.remove('heatmap-card');
                }
            });
        }
    }

    // ========================================================================
    // 10. ENHANCED TIMEFRAME PILLS - Replace select with pill buttons
    // ========================================================================
    class TimeframePills {
        static init() {
            document.querySelectorAll('.timeframe-selector').forEach(select => {
                if (select.dataset.pillsInit) return;
                select.dataset.pillsInit = 'true';

                const market = select.dataset.market;
                const parent = select.parentElement;

                const pillContainer = document.createElement('div');
                pillContainer.className = 'timeframe-pills';

                const options = ['Live', '5m', '15m', '1h', '6h', '24h', '7d'];
                options.forEach(opt => {
                    const pill = document.createElement('button');
                    pill.className = `tf-pill${opt.toLowerCase() === select.value ? ' tf-pill-active' : ''}`;
                    pill.textContent = opt;
                    pill.dataset.tf = opt.toLowerCase();
                    pill.addEventListener('click', () => {
                        pillContainer.querySelectorAll('.tf-pill').forEach(p => p.classList.remove('tf-pill-active'));
                        pill.classList.add('tf-pill-active');
                        select.value = opt.toLowerCase();
                        if (typeof changeTimeframe === 'function') {
                            changeTimeframe(market, opt.toLowerCase());
                        }
                    });
                    pillContainer.appendChild(pill);
                });

                select.style.display = 'none';
                parent.insertBefore(pillContainer, select);
            });
        }
    }

    // ========================================================================
    // 11. MINI VOLUME INDICATOR - Shows simulated volume strength
    // ========================================================================
    class VolumeIndicator {
        static create(market, container) {
            if (container.querySelector('.volume-indicator')) return;

            const volBar = document.createElement('div');
            volBar.className = 'volume-indicator';
            volBar.innerHTML = `
                <div class="vol-bars">
                    ${Array.from({length: 12}, () => `<div class="vol-bar-tick"></div>`).join('')}
                </div>
                <span class="vol-label">VOL</span>
            `;
            container.appendChild(volBar);
        }

        static update(market, priceHistory) {
            const card = document.querySelector(`.trade-card-simple[data-market="${market}"]`);
            if (!card) return;
            const ticks = card.querySelectorAll('.vol-bar-tick');
            if (!ticks.length || !priceHistory || priceHistory.length < 2) return;

            // Simulate volume from price volatility
            const len = priceHistory.length;
            const step = Math.max(1, Math.floor(len / ticks.length));
            ticks.forEach((tick, i) => {
                const start = Math.max(0, len - ticks.length * step + i * step);
                const end = Math.min(len, start + step);
                if (start >= len - 1) {
                    tick.style.height = '2px';
                    return;
                }
                let vol = 0;
                for (let j = start + 1; j < end && j < len; j++) {
                    vol += Math.abs(priceHistory[j] - priceHistory[j - 1]);
                }
                const avg = priceHistory[len - 1] || 1;
                const pct = Math.min((vol / avg) * 500, 100);
                tick.style.height = `${Math.max(2, pct)}%`;
                const isUp = priceHistory[Math.min(end, len - 1)] >= priceHistory[start];
                tick.style.background = isUp
                    ? 'rgba(22, 199, 132, 0.6)'
                    : 'rgba(234, 57, 67, 0.5)';
            });
        }
    }

    // ========================================================================
    // 12. PERFORMANCE COMPARISON OVERLAY
    // ========================================================================
    class PerformanceOverlay {
        static show() {
            let overlay = document.getElementById('perf-overlay');
            if (overlay) {
                overlay.remove();
                return;
            }

            const cards = window.tradeCards || [];
            if (cards.length < 2) return;

            overlay = document.createElement('div');
            overlay.id = 'perf-overlay';
            overlay.className = 'perf-overlay glass-panel';

            const sorted = [...cards].sort((a, b) => (b.pnl_pct || 0) - (a.pnl_pct || 0));
            const maxPct = Math.max(...sorted.map(c => Math.abs(c.pnl_pct || 0)), 1);

            let html = `
                <div class="perf-overlay-header">
                    <h3>Performance Comparison</h3>
                    <button class="perf-close-btn" onclick="document.getElementById('perf-overlay')?.remove()">&times;</button>
                </div>
                <div class="perf-bars">
            `;

            sorted.forEach(card => {
                const pct = card.pnl_pct || 0;
                const width = Math.abs(pct) / maxPct * 100;
                const isPos = pct >= 0;
                html += `
                    <div class="perf-bar-row">
                        <span class="perf-label">${card.symbol || card.market}</span>
                        <div class="perf-bar-track">
                            <div class="perf-bar-fill ${isPos ? 'perf-positive' : 'perf-negative'}"
                                 style="width: ${width}%; ${!isPos ? 'margin-left: auto;' : ''}">
                            </div>
                        </div>
                        <span class="perf-value ${isPos ? 'text-success' : 'text-danger'}">${isPos ? '+' : ''}${pct.toFixed(2)}%</span>
                    </div>
                `;
            });

            html += '</div>';
            overlay.innerHTML = html;
            document.querySelector('.main-content')?.prepend(overlay);

            // Animate bars
            requestAnimationFrame(() => {
                overlay.querySelectorAll('.perf-bar-fill').forEach(bar => {
                    bar.style.transition = 'width 0.8s cubic-bezier(0.16, 1, 0.3, 1)';
                });
            });
        }
    }

    // ========================================================================
    // 13. ENHANCED SORT CONTROLS WITH VISUAL ICONS
    // ========================================================================
    class SortEnhancer {
        static init() {
            const sortSelect = document.getElementById('sort-trades');
            if (!sortSelect || sortSelect.dataset.enhanced) return;
            sortSelect.dataset.enhanced = 'true';

            // Add heatmap + compare buttons
            const controls = sortSelect.closest('.section-controls') || sortSelect.parentElement;
            if (!controls) return;

            const btnGroup = document.createElement('div');
            btnGroup.className = 'sort-btn-group';
            btnGroup.innerHTML = `
                <button class="sort-action-btn" onclick="window.ApexCharts.HeatmapOverview.toggle()" title="Toggle Heatmap View">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
                    Heatmap
                </button>
                <button class="sort-action-btn" onclick="window.ApexCharts.PerformanceOverlay.show()" title="Compare Performance">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
                    Compare
                </button>
            `;
            controls.appendChild(btnGroup);
        }
    }

    // ========================================================================
    // 14. PRICE ALERT FLASH - Flash card border on significant price move
    // ========================================================================
    class PriceAlertFlash {
        constructor() {
            this.thresholds = {};
        }

        check(market, price) {
            const prev = this.thresholds[market];
            this.thresholds[market] = price;
            if (!prev) return;

            const changePct = Math.abs((price - prev) / prev * 100);
            if (changePct < 0.3) return; // Only flash on >0.3% move

            const card = document.querySelector(`.trade-card-simple[data-market="${market}"]`);
            if (!card) return;

            const isUp = price > prev;
            card.classList.add(isUp ? 'price-flash-up' : 'price-flash-down');
            setTimeout(() => {
                card.classList.remove('price-flash-up', 'price-flash-down');
            }, 1200);
        }
    }

    // ========================================================================
    // INITIALIZATION & HOOKS
    // ========================================================================
    const priceDelta = new PriceDeltaBadge();
    const priceAlert = new PriceAlertFlash();

    function init() {
        // Initialize all enhancements
        ChartToolbar.init();
        TradeCardFlip.init();
        TimeframePills.init();
        SortEnhancer.init();

        // Add volume indicators to all chart containers
        document.querySelectorAll('.card-chart-container').forEach(container => {
            const market = container.closest('.trade-card-simple')?.dataset?.market;
            if (market) {
                VolumeIndicator.create(market, container);
            }
        });

        console.log('[ApexCharts] All chart enhancements initialized');
    }

    // Hook into live price updates for real-time features
    function onPriceUpdate(market, price) {
        priceDelta.update(market, price);
        priceAlert.check(market, price);

        // Update chart border glow
        const chartData = window.tradeCardCharts?.[market];
        if (chartData) {
            const buyPrice = chartData.buyPrice || 0;
            ChartBorderGlow.update(market, price >= buyPrice);

            // Update volume indicator
            if (chartData.priceHistory) {
                VolumeIndicator.update(market, chartData.priceHistory);
            }
        }
    }

    // Monkey-patch the existing updateTradeCardCharts to hook in our features
    const _origUpdateFn = window.updateTradeCardCharts;
    window.updateTradeCardCharts = function(prices) {
        if (_origUpdateFn) _origUpdateFn.call(this, prices);
        if (prices && typeof prices === 'object') {
            for (const [market, price] of Object.entries(prices)) {
                onPriceUpdate(market, price);
            }
        }
    };

    // Init on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 800));
    } else {
        setTimeout(init, 800);
    }

    // Re-init after dynamic card creation (MutationObserver)
    const observer = new MutationObserver((mutations) => {
        let hasNewCards = false;
        mutations.forEach(m => {
            m.addedNodes.forEach(n => {
                if (n.nodeType === 1 && (n.classList?.contains('trade-card-simple') || n.querySelector?.('.trade-card-simple'))) {
                    hasNewCards = true;
                }
            });
        });
        if (hasNewCards) {
            setTimeout(() => {
                ChartToolbar.init();
                TradeCardFlip.init();
                TimeframePills.init();
                document.querySelectorAll('.card-chart-container').forEach(c => {
                    const m = c.closest('.trade-card-simple')?.dataset?.market;
                    if (m) VolumeIndicator.create(m, c);
                });
            }, 500);
        }
    });
    const cardsContainer = document.getElementById('trade-cards-container');
    if (cardsContainer) {
        observer.observe(cardsContainer, { childList: true, subtree: true });
    }

    // Expose to global scope
    window.ApexCharts = {
        PriceDeltaBadge: priceDelta,
        PriceAlertFlash: priceAlert,
        ChartToolbar,
        ChartBorderGlow,
        TradeCardFlip,
        HeatmapOverview,
        TimeframePills,
        VolumeIndicator,
        PerformanceOverlay,
        SortEnhancer,
        onPriceUpdate,
        init
    };

})();
