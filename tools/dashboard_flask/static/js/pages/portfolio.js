/**
 * Portfolio Page Logic
 * Handles trade cards, price updates, and sorting
 */

import { socketManager } from '../core/socket.js';
import { formatEuro, formatPercent, debounce } from '../core/utils.js';

class PortfolioPage {
    constructor() {
        this.cards = new Map();
        this.sortCriteria = 'pnl-desc';
        this.init();
    }
    
    init() {
        // Initialize card references
        this.initializeCards();
        
        // Subscribe to price updates
        socketManager.on('prices', (data) => this.updatePrices(data.prices));
        
        // Initialize sorting
        const sortSelect = document.getElementById('sort-trades');
        if (sortSelect) {
            sortSelect.addEventListener('change', (e) => {
                this.sortCriteria = e.target.value;
                this.sortCards();
            });
        }
        
        // Initialize refresh button
        const refreshBtn = document.getElementById('refresh-portfolio');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.refresh());
        }
        
        // Set initial trailing bar widths from data attributes
        this.initializeTrailingBars();
        
        console.log('[Portfolio] Initialized with', this.cards.size, 'cards');
    }
    
    initializeCards() {
        document.querySelectorAll('.trade-card').forEach(cardEl => {
            const market = cardEl.dataset.market;
            if (!market) return;
            
            this.cards.set(market, {
                element: cardEl,
                pnlEl: cardEl.querySelector('[data-pnl]'),
                pnlPctEl: cardEl.querySelector('[data-pnl-pct]'),
                priceEl: cardEl.querySelector('[data-live-price]'),
                valueEl: cardEl.querySelector('[data-current-value]'),
                trailingFillEl: cardEl.querySelector('[data-trailing-fill]'),
                trailingPctEl: cardEl.querySelector('[data-trailing-pct]'),
                buyPrice: parseFloat(cardEl.dataset.buyPrice) || 0,
                amount: parseFloat(cardEl.dataset.amount) || 0,
                invested: parseFloat(cardEl.dataset.invested) || 0,
            });
        });
    }
    
    initializeTrailingBars() {
        document.querySelectorAll('[data-trailing-fill]').forEach(el => {
            const progress = parseFloat(el.dataset.progress) || 0;
            el.style.width = `${Math.min(100, Math.max(0, progress))}%`;
        });
    }
    
    updatePrices(prices) {
        if (!prices) return;
        
        let totalCurrent = 0;
        let totalInvested = 0;
        let totalPnl = 0;
        
        for (const [market, price] of Object.entries(prices)) {
            const card = this.cards.get(market);
            if (!card || !price) continue;
            
            const currentValue = price * card.amount;
            const pnl = currentValue - card.invested;
            const pnlPct = card.invested > 0 
                ? ((currentValue / card.invested) - 1) * 100 
                : 0;
            
            // Update DOM elements
            if (card.priceEl) {
                card.priceEl.textContent = formatEuro(price);
                card.priceEl.classList.toggle('positive', pnl >= 0);
                card.priceEl.classList.toggle('negative', pnl < 0);
            }
            
            if (card.pnlEl) {
                card.pnlEl.textContent = formatEuro(pnl, true);
            }
            
            if (card.pnlPctEl) {
                card.pnlPctEl.textContent = `(${formatPercent(pnlPct, true)})`;
            }
            
            if (card.valueEl) {
                card.valueEl.textContent = formatEuro(currentValue);
                card.valueEl.classList.toggle('positive', pnl >= 0);
                card.valueEl.classList.toggle('negative', pnl < 0);
            }
            
            // Update PNL section styling
            const pnlSection = card.element.querySelector('.trade-card__pnl');
            if (pnlSection) {
                pnlSection.classList.toggle('trade-card__pnl--positive', pnl >= 0);
                pnlSection.classList.toggle('trade-card__pnl--negative', pnl < 0);
            }
            
            // Calculate trailing progress if applicable
            this.updateTrailingProgress(card, price);
            
            // Track totals
            totalCurrent += currentValue;
            totalInvested += card.invested;
            totalPnl += pnl;
            
            // Store current values for sorting
            card.currentValue = currentValue;
            card.pnl = pnl;
        }
        
        // Update totals in hero section
        this.updateTotals(totalInvested, totalCurrent, totalPnl);
    }
    
    updateTrailingProgress(card, livePrice) {
        if (!card.trailingFillEl) return;
        
        const buyPrice = card.buyPrice;
        const activationPct = 0.02; // Default 2%
        const activationPrice = buyPrice * (1 + activationPct);
        
        if (activationPrice > buyPrice && livePrice) {
            const progress = ((livePrice - buyPrice) / (activationPrice - buyPrice)) * 100;
            const clampedProgress = Math.max(0, Math.min(100, progress));
            
            card.trailingFillEl.style.width = `${clampedProgress}%`;
            
            if (card.trailingPctEl) {
                card.trailingPctEl.textContent = `${Math.round(clampedProgress)}%`;
            }
        }
    }
    
    updateTotals(invested, current, pnl) {
        const totalPnlEl = document.getElementById('total-pnl');
        const accountValueEl = document.getElementById('account-value');
        const realProfitEl = document.getElementById('real-profit');
        
        if (totalPnlEl) {
            totalPnlEl.textContent = formatEuro(pnl, true);
        }
        
        if (accountValueEl) {
            // Add EUR balance if available
            const eurBalance = parseFloat(document.getElementById('eur-balance')?.textContent?.replace(/[€,]/g, '')) || 0;
            accountValueEl.textContent = formatEuro(current + eurBalance);
        }
    }
    
    sortCards() {
        const container = document.getElementById('trade-cards-container');
        if (!container) return;
        
        const cards = [...container.querySelectorAll('.trade-card')];
        
        cards.sort((a, b) => {
            const cardA = this.cards.get(a.dataset.market);
            const cardB = this.cards.get(b.dataset.market);
            
            if (!cardA || !cardB) return 0;
            
            switch (this.sortCriteria) {
                case 'pnl-desc':
                    return (cardB.pnl || 0) - (cardA.pnl || 0);
                case 'pnl-asc':
                    return (cardA.pnl || 0) - (cardB.pnl || 0);
                case 'value-desc':
                    return (cardB.currentValue || 0) - (cardA.currentValue || 0);
                case 'value-asc':
                    return (cardA.currentValue || 0) - (cardB.currentValue || 0);
                case 'symbol-asc':
                    return a.dataset.symbol?.localeCompare(b.dataset.symbol) || 0;
                case 'symbol-desc':
                    return b.dataset.symbol?.localeCompare(a.dataset.symbol) || 0;
                default:
                    return 0;
            }
        });
        
        // Reorder DOM
        cards.forEach(card => container.appendChild(card));
    }
    
    refresh() {
        socketManager.requestRefresh();
    }
}

// Initialize on page load
let portfolioPage = null;

document.addEventListener('DOMContentLoaded', () => {
    // Only initialize on portfolio page
    if (document.querySelector('.trade-cards-grid') || document.querySelector('[data-page="portfolio"]')) {
        portfolioPage = new PortfolioPage();
    }
});

export { PortfolioPage, portfolioPage };
