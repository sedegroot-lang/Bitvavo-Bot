/**
 * Grid page JavaScript module
 */

import { api } from '../core/api.js';
import { formatEuro, formatPercent } from '../core/utils.js';

let gridChart = null;

/**
 * Initialize grid page
 */
export function init() {
    console.log('[Grid] Initializing grid page');
    
    // Initialize grid chart if element exists
    const chartContainer = document.getElementById('grid-chart-container');
    if (chartContainer && window.GridChart) {
        initGridChart(chartContainer);
    }
    
    // Setup form handlers
    setupGridForm();
    
    // Load active grids
    loadActiveGrids();
}

/**
 * Initialize grid visualization chart
 */
function initGridChart(container) {
    const configEl = container.querySelector('[data-grid-config]');
    if (!configEl) return;
    
    try {
        const config = JSON.parse(configEl.dataset.gridConfig);
        gridChart = new window.GridChart(container, config);
    } catch (e) {
        console.error('[Grid] Failed to parse grid config:', e);
    }
}

/**
 * Setup grid creation form
 */
function setupGridForm() {
    const form = document.getElementById('grid-form');
    if (!form) return;
    
    // Market selector change
    const marketSelect = form.querySelector('[name="market"]');
    if (marketSelect) {
        marketSelect.addEventListener('change', async () => {
            await updateGridPreview();
        });
    }
    
    // Investment amount change
    const investmentInput = form.querySelector('[name="investment"]');
    if (investmentInput) {
        investmentInput.addEventListener('input', updateGridPreview);
    }
    
    // Grid levels change
    const levelsInput = form.querySelector('[name="grid_levels"]');
    if (levelsInput) {
        levelsInput.addEventListener('input', updateGridPreview);
    }
    
    // Form submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await createGrid(new FormData(form));
    });
}

/**
 * Update grid preview based on form values
 */
async function updateGridPreview() {
    const form = document.getElementById('grid-form');
    if (!form) return;
    
    const market = form.querySelector('[name="market"]')?.value;
    const investment = parseFloat(form.querySelector('[name="investment"]')?.value) || 0;
    const levels = parseInt(form.querySelector('[name="grid_levels"]')?.value) || 10;
    
    if (!market || investment <= 0) return;
    
    // Get current price
    try {
        const response = await api.get(`/prices/${market}`);
        const currentPrice = response.price;
        
        // Calculate default range (±5%)
        const lowerPrice = currentPrice * 0.95;
        const upperPrice = currentPrice * 1.05;
        
        // Update preview
        updatePreviewUI({
            market,
            currentPrice,
            lowerPrice,
            upperPrice,
            levels,
            investment,
        });
    } catch (e) {
        console.error('[Grid] Failed to get price:', e);
    }
}

/**
 * Update preview UI
 */
function updatePreviewUI(config) {
    const preview = document.getElementById('grid-preview');
    if (!preview) return;
    
    const spacing = ((config.upperPrice / config.lowerPrice) ** (1 / (config.levels - 1)) - 1) * 100;
    const perLevel = config.investment / config.levels;
    
    preview.innerHTML = `
        <div class="preview-stat">
            <span class="preview-stat__label">Current Price</span>
            <span class="preview-stat__value">${formatEuro(config.currentPrice)}</span>
        </div>
        <div class="preview-stat">
            <span class="preview-stat__label">Price Range</span>
            <span class="preview-stat__value">${formatEuro(config.lowerPrice)} - ${formatEuro(config.upperPrice)}</span>
        </div>
        <div class="preview-stat">
            <span class="preview-stat__label">Grid Spacing</span>
            <span class="preview-stat__value">${spacing.toFixed(2)}%</span>
        </div>
        <div class="preview-stat">
            <span class="preview-stat__label">Per Level</span>
            <span class="preview-stat__value">${formatEuro(perLevel)}</span>
        </div>
    `;
}

/**
 * Load active grids
 */
async function loadActiveGrids() {
    try {
        const grids = await api.get('/grid/active');
        renderActiveGrids(grids);
    } catch (e) {
        console.error('[Grid] Failed to load active grids:', e);
    }
}

/**
 * Render active grids
 */
function renderActiveGrids(grids) {
    const container = document.getElementById('active-grids');
    if (!container) return;
    
    if (!grids || grids.length === 0) {
        container.innerHTML = '<p class="text-muted">No active grids</p>';
        return;
    }
    
    container.innerHTML = grids.map(grid => `
        <div class="card card--interactive" data-grid-id="${grid.market}">
            <div class="card__header">
                <h4 class="card__title">${grid.symbol}</h4>
                <span class="badge badge--${grid.status}">${grid.status}</span>
            </div>
            <div class="card__body">
                <div class="stat-row">
                    <span>Investment</span>
                    <span>${formatEuro(grid.investment)}</span>
                </div>
                <div class="stat-row">
                    <span>Profit</span>
                    <span class="${grid.total_profit >= 0 ? 'text-success' : 'text-danger'}">
                        ${formatEuro(grid.total_profit)}
                    </span>
                </div>
                <div class="stat-row">
                    <span>Trades</span>
                    <span>${grid.trades_count}</span>
                </div>
            </div>
        </div>
    `).join('');
}

/**
 * Create new grid
 */
async function createGrid(formData) {
    const data = Object.fromEntries(formData.entries());
    
    try {
        const result = await api.post('/grid/activate', data);
        showToast('Grid created successfully', 'success');
        await loadActiveGrids();
    } catch (e) {
        showToast('Failed to create grid: ' + e.message, 'danger');
    }
}

function showToast(message, type) {
    document.dispatchEvent(new CustomEvent('show-toast', {
        detail: { message, type }
    }));
}
