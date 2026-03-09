/**
 * Grid Trading Chart - Professional Visualization
 * Shows grid levels with amounts, current price, and order status
 */

class GridChart {
    constructor(containerId, gridData) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error('Container not found:', containerId);
            return;
        }

        this.gridData = gridData;
        this.canvas = null;
        this.ctx = null;
        this.tooltip = null;
        this.hoveredLevel = null;

        // Color palette
        this.colors = {
            bg: '#0d1117',
            gridLine: 'rgba(255,255,255,0.035)',
            buyLine: 'rgba(46, 204, 113, 0.5)',
            buyFill: 'rgba(46, 204, 113, 0.04)',
            buyLabel: '#2ecc71',
            sellLine: 'rgba(231, 76, 60, 0.5)',
            sellFill: 'rgba(231, 76, 60, 0.04)',
            sellLabel: '#e74c3c',
            currentPrice: '#3498db',
            textPrimary: 'rgba(255,255,255,0.85)',
            textMuted: 'rgba(255,255,255,0.4)',
            placedDot: '#3498db',
            filledDot: '#2ecc71',
            errorDot: '#e74c3c',
            cancelledDot: 'rgba(255,255,255,0.15)',
        };

        this.chartHeight = 320;

        this.init();
    }

    init() {
        this.container.innerHTML = '';

        // Create wrapper
        const wrapper = document.createElement('div');
        wrapper.style.position = 'relative';
        this.container.appendChild(wrapper);

        // Create canvas
        this.canvas = document.createElement('canvas');
        const dpr = window.devicePixelRatio || 1;
        const rect = this.container.getBoundingClientRect();
        const height = this.chartHeight;

        this.canvas.width = rect.width * dpr;
        this.canvas.height = height * dpr;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = height + 'px';
        this.canvas.style.borderRadius = '4px';

        wrapper.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');
        this.ctx.scale(dpr, dpr);

        // Create tooltip element
        this.tooltip = document.createElement('div');
        this.tooltip.className = 'grid-chart-tooltip';
        this.tooltip.style.cssText = 'position:absolute;display:none;background:rgba(15,20,30,0.95);border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:8px 12px;font-size:12px;color:#fff;pointer-events:none;z-index:10;white-space:nowrap;box-shadow:0 4px 12px rgba(0,0,0,0.5);';
        wrapper.appendChild(this.tooltip);

        // Store layout for hit-testing
        this.levelPositions = [];

        // Mouse move for tooltips
        this.canvas.addEventListener('mousemove', (e) => this.handleMouseMove(e));
        this.canvas.addEventListener('mouseleave', () => {
            this.tooltip.style.display = 'none';
            this.hoveredLevel = null;
        });

        // Resize handler
        this._resizeHandler = () => this.handleResize();
        window.addEventListener('resize', this._resizeHandler);

        this.render();
    }

    handleResize() {
        const dpr = window.devicePixelRatio || 1;
        const rect = this.container.getBoundingClientRect();
        const height = this.chartHeight;

        this.canvas.width = rect.width * dpr;
        this.canvas.height = height * dpr;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = height + 'px';

        this.ctx = this.canvas.getContext('2d');
        this.ctx.scale(dpr, dpr);
        this.render();
    }

    handleMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        const mouseY = e.clientY - rect.top;

        let closest = null;
        let closestDist = Infinity;

        for (const lp of this.levelPositions) {
            const dist = Math.abs(mouseY - lp.y);
            if (dist < closestDist && dist < 20) {
                closestDist = dist;
                closest = lp;
            }
        }

        if (closest) {
            const level = closest.level;
            const asset = this.gridData.market ? this.gridData.market.split('-')[0] : 'COIN';
            let html = '<div style="margin-bottom:4px;font-weight:700;color:' + (level.type === 'buy' ? this.colors.buyLabel : this.colors.sellLabel) + '">' + level.type.toUpperCase() + ' @ \u20AC' + level.price.toFixed(2) + '</div>';
            html += '<div>Amount: <b>' + (level.amount ? level.amount.toFixed(8) : '\u2014') + '</b> ' + asset + '</div>';
            html += '<div>Value: <b>\u20AC' + (level.value_eur ? level.value_eur.toFixed(2) : '\u2014') + '</b></div>';
            html += '<div>Status: <b style="color:' + this.getStatusColor(level.status) + '">' + (level.status || 'unknown').toUpperCase() + '</b></div>';
            if (level.order_id) {
                html += '<div style="font-size:10px;color:rgba(255,255,255,0.3);margin-top:2px">ID: ' + level.order_id.substring(0, 12) + '...</div>';
            }

            this.tooltip.innerHTML = html;
            this.tooltip.style.display = 'block';
            this.tooltip.style.left = (e.clientX - rect.left + 16) + 'px';
            this.tooltip.style.top = (e.clientY - rect.top - 20) + 'px';

            // Keep tooltip in bounds
            const ttRect = this.tooltip.getBoundingClientRect();
            if (ttRect.right > rect.right - 10) {
                this.tooltip.style.left = (e.clientX - rect.left - ttRect.width - 16) + 'px';
            }

            this.hoveredLevel = closest;
            this.render();
        } else {
            this.tooltip.style.display = 'none';
            if (this.hoveredLevel) {
                this.hoveredLevel = null;
                this.render();
            }
        }
    }

    getStatusColor(status) {
        switch (status) {
            case 'placed': return this.colors.placedDot;
            case 'filled': return this.colors.filledDot;
            case 'error': return this.colors.errorDot;
            case 'cancelled': return this.colors.cancelledDot;
            default: return this.colors.textMuted;
        }
    }

    render() {
        const ctx = this.ctx;
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.chartHeight;

        ctx.clearRect(0, 0, width, height);

        // Background
        ctx.fillStyle = this.colors.bg;
        ctx.fillRect(0, 0, width, height);

        const levels = this.gridData.levels || [];
        const upperPrice = this.gridData.upper_price;
        const lowerPrice = this.gridData.lower_price;
        const currentPrice = this.gridData.current_price;
        const priceRange = upperPrice - lowerPrice;

        if (priceRange <= 0) return;

        // Layout - compact right margin
        const margin = { top: 30, right: 170, bottom: 30, left: 65 };
        const chartWidth = width - margin.left - margin.right;
        const chartHeight = height - margin.top - margin.bottom;

        const priceToY = (price) => {
            const ratio = (upperPrice - price) / priceRange;
            return margin.top + ratio * chartHeight;
        };

        // Reset level positions
        this.levelPositions = [];

        // === Background Grid ===
        this.drawBackgroundGrid(ctx, margin, chartWidth, chartHeight);

        // === Grid Level Bands ===
        this.drawLevelBands(ctx, levels, margin, chartWidth, priceToY);

        // === Grid Level Lines & Labels ===
        this.drawLevelLines(ctx, levels, margin, chartWidth, width, priceToY);

        // === Current Price ===
        this.drawCurrentPrice(ctx, currentPrice, margin, chartWidth, width, priceToY);

        // === Left Price Axis ===
        this.drawPriceAxis(ctx, margin, chartHeight, upperPrice, lowerPrice, priceRange, priceToY);

        // === Title ===
        ctx.fillStyle = this.colors.textMuted;
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(this.gridData.market + ' Grid Levels', margin.left, 18);

        // === Legend ===
        const legendX = width - margin.right + 10;
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'left';

        // Buy legend
        ctx.fillStyle = this.colors.buyLabel;
        ctx.fillRect(legendX, 10, 10, 10);
        ctx.fillStyle = this.colors.textMuted;
        ctx.fillText('BUY', legendX + 14, 19);

        // Sell legend
        ctx.fillStyle = this.colors.sellLabel;
        ctx.fillRect(legendX + 50, 10, 10, 10);
        ctx.fillStyle = this.colors.textMuted;
        ctx.fillText('SELL', legendX + 64, 19);

        // Current legend
        ctx.fillStyle = this.colors.currentPrice;
        ctx.fillRect(legendX + 105, 10, 10, 10);
        ctx.fillStyle = this.colors.textMuted;
        ctx.fillText('NOW', legendX + 119, 19);
    }

    drawBackgroundGrid(ctx, margin, chartWidth, chartHeight) {
        ctx.strokeStyle = this.colors.gridLine;
        ctx.lineWidth = 1;

        // Horizontal
        const hLines = 8;
        for (let i = 0; i <= hLines; i++) {
            const y = margin.top + (chartHeight / hLines) * i;
            ctx.beginPath();
            ctx.moveTo(margin.left, y);
            ctx.lineTo(margin.left + chartWidth, y);
            ctx.stroke();
        }

        // Vertical
        const vLines = 6;
        for (let i = 0; i <= vLines; i++) {
            const x = margin.left + (chartWidth / vLines) * i;
            ctx.beginPath();
            ctx.moveTo(x, margin.top);
            ctx.lineTo(x, margin.top + chartHeight);
            ctx.stroke();
        }
    }

    drawLevelBands(ctx, levels, margin, chartWidth, priceToY) {
        // Sort levels by price descending
        const sorted = [...levels].sort((a, b) => b.price - a.price);

        for (let i = 0; i < sorted.length; i++) {
            const level = sorted[i];
            const y = priceToY(level.price);

            // Draw subtle band
            const bandHeight = i < sorted.length - 1
                ? Math.abs(priceToY(sorted[i + 1].price) - y)
                : 20;

            if (level.type === 'buy') {
                ctx.fillStyle = this.colors.buyFill;
            } else {
                ctx.fillStyle = this.colors.sellFill;
            }
            ctx.fillRect(margin.left, y, chartWidth, bandHeight / 2);
        }
    }

    drawLevelLines(ctx, levels, margin, chartWidth, width, priceToY) {
        const asset = this.gridData.market ? this.gridData.market.split('-')[0] : '';
        const MIN_LABEL_SPACING = 20; // px minimum between label rows to avoid overlap

        // Pre-compute Y positions and sort to do anti-overlap pass
        const levelsSorted = [...levels].map(level => ({
            level,
            y: priceToY(level.price),
            labelY: priceToY(level.price) // will be adjusted
        })).sort((a, b) => a.y - b.y); // top to bottom

        // Anti-overlap: push labels down if too close to previous
        for (let i = 1; i < levelsSorted.length; i++) {
            const prev = levelsSorted[i - 1];
            const curr = levelsSorted[i];
            if (curr.labelY - prev.labelY < MIN_LABEL_SPACING) {
                curr.labelY = prev.labelY + MIN_LABEL_SPACING;
            }
        }

        // Build a map from level -> adjusted labelY
        const labelYMap = new Map();
        for (const item of levelsSorted) {
            labelYMap.set(item.level, item.labelY);
        }

        for (const level of levels) {
            const y = priceToY(level.price);
            const labelY = labelYMap.get(level) ?? y;
            const isBuy = level.type === 'buy';
            const isHovered = this.hoveredLevel && this.hoveredLevel.level === level;

            // Store position for hit-testing
            this.levelPositions.push({ y, level });

            // === Dashed grid line ===
            ctx.strokeStyle = isBuy ? this.colors.buyLine : this.colors.sellLine;
            ctx.lineWidth = isHovered ? 2 : 1;
            ctx.setLineDash(isHovered ? [] : [4, 4]);

            ctx.beginPath();
            ctx.moveTo(margin.left, y);
            ctx.lineTo(margin.left + chartWidth, y);
            ctx.stroke();
            ctx.setLineDash([]);

            // === Status dot ===
            const dotX = margin.left + chartWidth + 8;
            const dotRadius = isHovered ? 6 : 4;
            const statusColor = this.getStatusColor(level.status);

            if (level.status === 'placed') {
                // Filled dot
                ctx.fillStyle = statusColor;
                ctx.beginPath();
                ctx.arc(dotX, y, dotRadius, 0, Math.PI * 2);
                ctx.fill();

                // Pulsing ring for placed
                ctx.strokeStyle = statusColor;
                ctx.lineWidth = 1;
                ctx.globalAlpha = 0.4;
                ctx.beginPath();
                ctx.arc(dotX, y, dotRadius + 3, 0, Math.PI * 2);
                ctx.stroke();
                ctx.globalAlpha = 1;
            } else if (level.status === 'filled') {
                ctx.fillStyle = statusColor;
                ctx.beginPath();
                ctx.arc(dotX, y, dotRadius, 0, Math.PI * 2);
                ctx.fill();
                // Checkmark
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(dotX - 2, y);
                ctx.lineTo(dotX - 0.5, y + 2);
                ctx.lineTo(dotX + 3, y - 2);
                ctx.stroke();
            } else if (level.status === 'error') {
                ctx.fillStyle = statusColor;
                ctx.beginPath();
                ctx.arc(dotX, y, dotRadius, 0, Math.PI * 2);
                ctx.fill();
                // X mark
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(dotX - 2, y - 2);
                ctx.lineTo(dotX + 2, y + 2);
                ctx.moveTo(dotX + 2, y - 2);
                ctx.lineTo(dotX - 2, y + 2);
                ctx.stroke();
            } else {
                // Cancelled or other - outline only
                ctx.strokeStyle = statusColor;
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.arc(dotX, y, dotRadius, 0, Math.PI * 2);
                ctx.stroke();
            }

            // === Right side label === (use labelY to prevent overlap)
            const labelX = dotX + 14;

            // Side + Price
            ctx.font = isHovered ? 'bold 11px JetBrains Mono, monospace' : '11px JetBrains Mono, monospace';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';

            // Draw connector line from dot to label if label was shifted
            if (Math.abs(labelY - y) > 4) {
                ctx.strokeStyle = isBuy ? this.colors.buyLine : this.colors.sellLine;
                ctx.lineWidth = 0.5;
                ctx.globalAlpha = 0.4;
                ctx.setLineDash([2, 3]);
                ctx.beginPath();
                ctx.moveTo(dotX + dotRadius + 2, y);
                ctx.lineTo(labelX - 4, labelY - 7);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.globalAlpha = 1;
            }

            // Side label
            const sideText = isBuy ? 'BUY' : 'SELL';
            ctx.fillStyle = isBuy ? this.colors.buyLabel : this.colors.sellLabel;
            ctx.fillText(sideText, labelX, labelY - 7);

            // Price
            ctx.fillStyle = this.colors.textPrimary;
            const priceStr = '\u20AC' + level.price.toFixed(2);
            ctx.fillText(priceStr, labelX + 32, labelY - 7);

            // Amount + Value (second line)
            ctx.font = '9.5px JetBrains Mono, monospace';
            ctx.fillStyle = this.colors.textMuted;

            let detailStr = '';
            if (level.amount && level.amount > 0) {
                detailStr = level.amount.toFixed(6) + ' ' + asset;
                if (level.value_eur) {
                    detailStr += ' (\u20AC' + level.value_eur.toFixed(2) + ')';
                }
            } else {
                detailStr = '\u2014';
            }
            ctx.fillText(detailStr, labelX, labelY + 7);

            // Status text
            const statusText = (level.status || '').toUpperCase();
            ctx.font = 'bold 8px system-ui, sans-serif';
            ctx.fillStyle = this.getStatusColor(level.status);
            const statusW = ctx.measureText(statusText).width;
            ctx.fillText(statusText, Math.min(labelX + 130, width - statusW - 8), labelY - 7);
        }
    }

    drawCurrentPrice(ctx, currentPrice, margin, chartWidth, width, priceToY) {
        const y = priceToY(currentPrice);

        // Glowing line
        ctx.shadowColor = this.colors.currentPrice;
        ctx.shadowBlur = 6;
        ctx.strokeStyle = this.colors.currentPrice;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(margin.left, y);
        ctx.lineTo(margin.left + chartWidth, y);
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Price badge on left
        const badgeW = 62;
        const badgeH = 22;
        const badgeX = margin.left - badgeW - 4;

        // Badge background
        ctx.fillStyle = this.colors.currentPrice;
        this.roundRect(ctx, badgeX, y - badgeH / 2, badgeW, badgeH, 4);
        ctx.fill();

        // Badge text
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 11px JetBrains Mono, monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('\u20AC' + currentPrice.toFixed(2), badgeX + badgeW / 2, y);

        // Arrow on right side of badge
        ctx.fillStyle = this.colors.currentPrice;
        ctx.beginPath();
        ctx.moveTo(badgeX + badgeW, y - 5);
        ctx.lineTo(badgeX + badgeW + 6, y);
        ctx.lineTo(badgeX + badgeW, y + 5);
        ctx.closePath();
        ctx.fill();
    }

    drawPriceAxis(ctx, margin, chartHeight, upperPrice, lowerPrice, priceRange, priceToY) {
        ctx.fillStyle = this.colors.textMuted;
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';

        const steps = 6;
        for (let i = 0; i <= steps; i++) {
            const price = upperPrice - (priceRange / steps) * i;
            const y = priceToY(price);

            ctx.fillText('\u20AC' + price.toFixed(0), margin.left - 8, y);
        }
    }

    roundRect(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
    }

    updateData(newGridData) {
        this.gridData = newGridData;
        this.render();
    }

    destroy() {
        window.removeEventListener('resize', this._resizeHandler);
        if (this.canvas && this.canvas.parentNode) {
            this.canvas.parentNode.removeChild(this.canvas);
        }
    }
}

// Export
window.GridChart = GridChart;
