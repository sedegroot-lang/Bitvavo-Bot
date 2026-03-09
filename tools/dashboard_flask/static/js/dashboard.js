/* =====================================================
   BITVAVO TRADING BOT - FLASK DASHBOARD JAVASCRIPT
   WebSocket connection and live updates
   ===================================================== */

// Theme Management
function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    // Update toggle button icon
    const btn = document.getElementById('theme-toggle');
    if (btn) {
        btn.textContent = newTheme === 'dark' ? '🌞' : '🌙';
        btn.title = newTheme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
    }
    
    console.log('[Dashboard] Theme switched to:', newTheme);
}

// Load saved theme on page load
document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    
    const btn = document.getElementById('theme-toggle');
    if (btn) {
        btn.textContent = savedTheme === 'dark' ? '🌞' : '🌙';
        btn.title = savedTheme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
    }
});

// Global state
const DashboardApp = {
    socket: null,
    connected: false,
    lastUpdate: null,
    reconnectAttempts: 0,
    maxReconnectAttempts: 10,
    reconnectDelay: 2000,
    markets: [],
    prices: {},
    updateCallbacks: []
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('[Dashboard] Initializing...');
    initializeSocket();
    initializeRefreshButton();
    startHeartbeat();
    loadInitialStatus();
});

// Load initial status data from API
function loadInitialStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            console.log('[Dashboard] Initial status loaded:', data);
            updateStatusBar(data);
        })
        .catch(error => console.error('[Dashboard] Status fetch error:', error));
    
    // Also load open trades count
    fetch('/api/trades/open')
        .then(response => response.json())
        .then(data => {
            if (data && data.totals) {
                updatePortfolioStats(data.totals);
            }
        })
        .catch(error => console.error('[Dashboard] Trades fetch error:', error));
}

// Update status bar with actual data
function updateStatusBar(data) {
    const openTradesEl = document.getElementById('open-trades-count');
    const eurBalanceEl = document.getElementById('eur-balance');
    const totalPnlEl = document.getElementById('total-pnl');
    
    if (openTradesEl && data.open_trades !== undefined) {
        openTradesEl.textContent = data.open_trades;
    }
    if (eurBalanceEl && data.eur_balance !== undefined) {
        eurBalanceEl.textContent = formatEuro(data.eur_balance);
    }
    
    // Update bot/ai status indicators
    updateBotStatus(data.bot_online);
    updateAiStatus(data.ai_online);
}

// Update portfolio totals in status bar
function updatePortfolioStats(totals) {
    const openTradesEl = document.getElementById('open-trades-count');
    const totalPnlEl = document.getElementById('total-pnl');
    
    if (openTradesEl && totals.trade_count !== undefined) {
        openTradesEl.textContent = totals.trade_count;
    }
    if (totalPnlEl && totals.total_pnl !== undefined) {
        const pnl = totals.total_pnl;
        totalPnlEl.textContent = (pnl >= 0 ? '+' : '') + formatEuro(pnl);
        totalPnlEl.classList.remove('pnl-positive', 'pnl-negative', 'pnl-neutral');
        totalPnlEl.classList.add(pnl > 0 ? 'pnl-positive' : pnl < 0 ? 'pnl-negative' : 'pnl-neutral');
    }
}

// Update bot status indicator
function updateBotStatus(online) {
    const indicator = document.querySelector('#bot-status .status-dot');
    if (indicator) {
        indicator.classList.remove('online', 'offline');
        indicator.classList.add(online ? 'online' : 'offline');
    }
}

// Update AI status indicator
function updateAiStatus(online) {
    const indicator = document.querySelector('#exchange-status .status-dot');
    if (indicator) {
        indicator.classList.remove('online', 'offline');
        indicator.classList.add(online ? 'online' : 'offline');
    }
}

/* =====================================================
   SOCKET.IO CONNECTION
   ===================================================== */

function initializeSocket() {
    // Check if Socket.IO is loaded
    if (typeof io === 'undefined') {
        console.error('[Dashboard] Socket.IO not loaded!');
        updateConnectionStatus('error');
        return;
    }

    // Create socket connection
    DashboardApp.socket = io({
        reconnection: true,
        reconnectionAttempts: DashboardApp.maxReconnectAttempts,
        reconnectionDelay: DashboardApp.reconnectDelay,
        timeout: 10000
    });

    // Export to window for templates
    window.socket = DashboardApp.socket;

    // Connection events
    DashboardApp.socket.on('connect', function() {
        console.log('[Dashboard] Connected to WebSocket');
        DashboardApp.connected = true;
        DashboardApp.reconnectAttempts = 0;
        updateConnectionStatus('online');
        
        // Request initial data
        DashboardApp.socket.emit('request_refresh');
    });

    DashboardApp.socket.on('disconnect', function(reason) {
        console.log('[Dashboard] Disconnected:', reason);
        DashboardApp.connected = false;
        updateConnectionStatus('offline');
    });

    DashboardApp.socket.on('connect_error', function(error) {
        console.error('[Dashboard] Connection error:', error);
        DashboardApp.reconnectAttempts++;
        updateConnectionStatus('connecting');
    });

    // Price updates
    DashboardApp.socket.on('price_update', function(data) {
        console.log('[Dashboard] Price update received:', Object.keys(data.prices || {}).length, 'markets');
        DashboardApp.prices = data.prices || {};
        DashboardApp.lastUpdate = new Date();
        
        // Update UI
        updatePriceDisplays(data.prices);
        updateLastUpdateTime();
        
        // Call registered callbacks
        DashboardApp.updateCallbacks.forEach(function(callback) {
            try {
                callback(data.prices);
            } catch (e) {
                console.error('[Dashboard] Callback error:', e);
            }
        });
    });

    // Status updates
    DashboardApp.socket.on('status_update', function(data) {
        console.log('[Dashboard] Status update:', data);
        updateStatusIndicators(data);
    });

    // Full refresh
    DashboardApp.socket.on('full_refresh', function(data) {
        console.log('[Dashboard] Full refresh received');
        if (data.reload) {
            location.reload();
        }
    });
}

/* =====================================================
   PRICE UPDATE FUNCTIONS
   ===================================================== */

function updatePriceDisplays(prices) {
    if (!prices) return;

    // Update all elements with data-market attribute EXCEPT trade cards
    // (trade cards are handled by updateTradeCards in portfolio.html)
    document.querySelectorAll('[data-market]').forEach(function(element) {
        // Skip trade card components; they are handled by updateTradeCards
        if (element.closest('.trade-card') || element.closest('.trade-card-simple')) {
            return;
        }

        const market = element.dataset.market;
        const price = prices[market];
        
        if (price !== undefined) {
            updatePriceElement(element, price);
        }
    });

    // Only update trade cards if the updateTradeCards function exists (portfolio page)
    if (typeof updateTradeCards === 'function') {
        updateTradeCards(prices);
    }

    // Update portfolio totals if function exists
    if (typeof updatePortfolioTotals === 'function') {
        updatePortfolioTotals();
    }
}

function updatePriceElement(element, price) {
    const type = element.dataset.type || 'price';
    const buyPrice = parseFloat(element.dataset.buyPrice) || 0;
    const amount = parseFloat(element.dataset.amount) || 0;
    const invested = parseFloat(element.dataset.invested) || 0;

    switch (type) {
        case 'price':
            element.textContent = formatPrice(price);
            break;
            
        case 'value':
            const value = price * amount;
            element.textContent = formatEuro(value);
            break;
            
        case 'pnl':
            const currentValue = price * amount;
            const pnl = currentValue - invested;
            element.textContent = formatEuro(pnl);
            element.classList.toggle('text-success', pnl >= 0);
            element.classList.toggle('text-danger', pnl < 0);
            break;
            
        case 'pnl-pct':
            if (invested > 0) {
                const pnlPct = ((price * amount - invested) / invested * 100);
                element.textContent = formatPercent(pnlPct);
                element.classList.toggle('text-success', pnlPct >= 0);
                element.classList.toggle('text-danger', pnlPct < 0);
            }
            break;
    }
}

/* =====================================================
   STATUS INDICATORS
   ===================================================== */

function updateConnectionStatus(status) {
    const wsIndicator = document.getElementById('ws-status');
    const wsText = document.getElementById('ws-status-text');
    
    if (wsIndicator) {
        wsIndicator.className = 'status-dot';
        switch (status) {
            case 'online':
                wsIndicator.classList.add('online');
                if (wsText) wsText.textContent = 'Live';
                break;
            case 'offline':
                wsIndicator.classList.add('offline');
                if (wsText) wsText.textContent = 'Offline';
                break;
            case 'connecting':
                wsIndicator.classList.add('connecting');
                if (wsText) wsText.textContent = 'Connecting...';
                break;
            case 'error':
                wsIndicator.classList.add('offline');
                if (wsText) wsText.textContent = 'Error';
                break;
        }
    }

    // Update live indicator in header
    const liveIndicator = document.querySelector('.live-indicator');
    if (liveIndicator) {
        liveIndicator.style.opacity = status === 'online' ? '1' : '0.5';
    }
}

function updateStatusIndicators(data) {
    // Bot status
    if (data.bot_status !== undefined) {
        const botStatus = document.getElementById('bot-status');
        if (botStatus) {
            botStatus.textContent = data.bot_status ? 'Online' : 'Offline';
            botStatus.closest('.status-card').classList.toggle('status-online', data.bot_status);
            botStatus.closest('.status-card').classList.toggle('status-offline', !data.bot_status);
        }
    }

    // AI status
    if (data.ai_status !== undefined) {
        const aiStatus = document.getElementById('ai-status');
        if (aiStatus) {
            aiStatus.textContent = data.ai_status ? 'Active' : 'Inactive';
        }
    }

    // Open trades count
    if (data.open_trades !== undefined) {
        const tradesCount = document.getElementById('open-trades-count');
        if (tradesCount) {
            tradesCount.textContent = data.open_trades;
        }
    }

    // Balance
    if (data.balance !== undefined) {
        const balance = document.getElementById('eur-balance');
        if (balance) {
            balance.textContent = formatEuro(data.balance);
        }
    }
}

function updateLastUpdateTime() {
    const lastUpdateEl = document.getElementById('last-update');
    if (lastUpdateEl && DashboardApp.lastUpdate) {
        const timeStr = DashboardApp.lastUpdate.toLocaleTimeString('nl-NL');
        lastUpdateEl.textContent = timeStr;
    }
}

/* =====================================================
   REFRESH CONTROLS
   ===================================================== */

function initializeRefreshButton() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', function() {
            requestRefresh();
        });
    }
}

function requestRefresh() {
    if (DashboardApp.socket && DashboardApp.connected) {
        console.log('[Dashboard] Requesting refresh...');
        DashboardApp.socket.emit('request_refresh');
        
        // Visual feedback
        const refreshBtn = document.getElementById('refresh-btn');
        if (refreshBtn) {
            refreshBtn.disabled = true;
            refreshBtn.innerHTML = '⟳ Refreshing...';
            setTimeout(function() {
                refreshBtn.disabled = false;
                refreshBtn.innerHTML = '🔄 Refresh';
            }, 1000);
        }
    } else {
        console.warn('[Dashboard] Cannot refresh - not connected');
        location.reload();
    }
}

/* =====================================================
   HEARTBEAT (Connection health check)
   ===================================================== */

function startHeartbeat() {
    setInterval(function() {
        if (DashboardApp.lastUpdate) {
            const age = (new Date() - DashboardApp.lastUpdate) / 1000;
            
            // If no update for 30 seconds, mark as stale
            if (age > 30) {
                updateConnectionStatus('connecting');
            }
            
            // If no update for 60 seconds, try to reconnect
            if (age > 60 && DashboardApp.socket) {
                console.warn('[Dashboard] Connection stale, reconnecting...');
                DashboardApp.socket.disconnect();
                DashboardApp.socket.connect();
            }
        }
    }, 10000);
}

/* =====================================================
   UTILITY FUNCTIONS
   ===================================================== */

function formatPrice(value) {
    if (value === null || value === undefined) return '—';
    return '€' + parseFloat(value).toLocaleString('nl-NL', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 6
    });
}

function formatEuro(value) {
    if (value === null || value === undefined) return '—';
    const num = parseFloat(value);
    const prefix = num >= 0 ? '+' : '';
    return prefix + '€' + Math.abs(num).toLocaleString('nl-NL', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function formatPercent(value) {
    if (value === null || value === undefined) return '—';
    const num = parseFloat(value);
    const prefix = num >= 0 ? '+' : '';
    return prefix + num.toFixed(2) + '%';
}

function formatAmount(value, decimals) {
    if (value === null || value === undefined) return '—';
    decimals = decimals !== undefined ? decimals : 8;
    return parseFloat(value).toLocaleString('nl-NL', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

function formatTimestamp(timestamp) {
    if (!timestamp) return '—';
    const date = new Date(timestamp);
    return date.toLocaleString('nl-NL', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/* =====================================================
   CALLBACK REGISTRATION
   ===================================================== */

function onPriceUpdate(callback) {
    if (typeof callback === 'function') {
        DashboardApp.updateCallbacks.push(callback);
    }
}

/* =====================================================
   API CALLS
   ===================================================== */

async function apiCall(endpoint, options) {
    try {
        const response = await fetch('/api' + endpoint, {
            headers: {
                'Content-Type': 'application/json'
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('[Dashboard] API call failed:', endpoint, error);
        throw error;
    }
}

async function getHealth() {
    return apiCall('/health');
}

async function getConfig() {
    return apiCall('/config');
}

async function getTrades() {
    return apiCall('/trades');
}

async function getOpenTrades() {
    return apiCall('/trades/open');
}

async function getClosedTrades() {
    return apiCall('/trades/closed');
}

async function getHeartbeat() {
    return apiCall('/heartbeat');
}

async function getMetrics() {
    return apiCall('/metrics');
}

async function getPrices() {
    return apiCall('/prices');
}

async function getStatus() {
    return apiCall('/status');
}

async function updateConfig(key, value) {
    return apiCall('/config/update', {
        method: 'POST',
        body: JSON.stringify({ key, value })
    });
}

/* =====================================================
   EXPORT FOR WINDOW
   ===================================================== */

window.DashboardApp = DashboardApp;
window.formatPrice = formatPrice;
window.formatEuro = formatEuro;
window.formatPercent = formatPercent;
window.formatAmount = formatAmount;
window.formatTimestamp = formatTimestamp;
window.requestRefresh = requestRefresh;
window.onPriceUpdate = onPriceUpdate;
window.apiCall = apiCall;

/* =====================================================
   TRADE CARD SORTING & INTERACTIONS
   ===================================================== */

// Sort trade cards by different criteria
function sortTradeCards(sortBy) {
    const container = document.getElementById('trade-cards-container');
    if (!container) return;
    
    const cards = Array.from(container.querySelectorAll('.trade-card-simple, .trade-card'));
    if (cards.length === 0) return;
    
    cards.sort((a, b) => {
        switch (sortBy) {
            case 'pnl-desc':
                return parseFloat(b.dataset.pnl || 0) - parseFloat(a.dataset.pnl || 0);
            case 'pnl-asc':
                return parseFloat(a.dataset.pnl || 0) - parseFloat(b.dataset.pnl || 0);
            case 'pnl-pct-desc':
                return parseFloat(b.dataset.pnlPct || 0) - parseFloat(a.dataset.pnlPct || 0);
            case 'value-desc':
                return parseFloat(b.dataset.value || 0) - parseFloat(a.dataset.value || 0);
            case 'symbol-asc':
                return (a.dataset.symbol || '').localeCompare(b.dataset.symbol || '');
            default:
                return 0;
        }
    });
    
    // Re-append cards in sorted order
    cards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.05}s`;
        container.appendChild(card);
    });
    
    console.log('[Dashboard] Cards sorted by:', sortBy);
}

// Toggle card details panel
function toggleCardDetails(market) {
    const safeMarket = market.replace(/-/g, '_');
    const panel = document.getElementById(`details-${safeMarket}`);
    
    if (panel) {
        const isVisible = panel.style.display !== 'none';
        panel.style.display = isVisible ? 'none' : 'block';
        
        // Animate panel
        if (!isVisible) {
            panel.style.animation = 'slideDown 0.2s ease-out';
        }
    }
}

// Show trade details modal
function showTradeDetails(market) {
    console.log('[Dashboard] Showing details for:', market);
    
    // Find the card element
    const card = document.querySelector(`.trade-card-simple[data-market="${market}"], .trade-card[data-market="${market}"]`);
    if (!card) return;
    
    // Get data from card
    const pnl = card.dataset.pnl;
    const pnlPct = card.dataset.pnlPct;
    const value = card.dataset.value;
    const symbol = card.dataset.symbol;
    
    // For now, just toggle the details panel
    // In future, this could open a full modal with trade history
    toggleCardDetails(market);
}

// Expose functions to window
window.sortTradeCards = sortTradeCards;
window.toggleCardDetails = toggleCardDetails;
window.showTradeDetails = showTradeDetails;

/* =====================================================
   STRATEGY PROFILE MANAGEMENT
   ===================================================== */

// Activate a strategy profile
async function activateProfile(profileId) {
    console.log('[Dashboard] Activating profile:', profileId);
    
    try {
        const response = await fetch(`/api/strategy/profile/${profileId}/activate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (response.ok) {
            showToast('Profile geactiveerd', 'success');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            const data = await response.json();
            showToast(data.error || 'Activatie mislukt', 'error');
        }
    } catch (error) {
        console.error('[Dashboard] Profile activation error:', error);
        showToast('Activatie mislukt: ' + error.message, 'error');
    }
}

// Edit a strategy profile
function editProfile(profileId) {
    console.log('[Dashboard] Editing profile:', profileId);
    window.location.href = `/parameters?edit=${profileId}`;
}

// Delete a strategy profile
async function deleteProfile(profileId) {
    if (!confirm('Weet je zeker dat je dit profiel wilt verwijderen?')) {
        return;
    }
    
    console.log('[Dashboard] Deleting profile:', profileId);
    
    try {
        const response = await fetch(`/api/strategy/profile/${profileId}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (response.ok) {
            showToast('Profile verwijderd', 'success');
            setTimeout(() => window.location.reload(), 1000);
        } else {
            const data = await response.json();
            showToast(data.error || 'Verwijderen mislukt', 'error');
        }
    } catch (error) {
        console.error('[Dashboard] Profile deletion error:', error);
        showToast('Verwijderen mislukt: ' + error.message, 'error');
    }
}

// Show toast notification
function showToast(message, type = 'info') {
    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️'}</span>
        <span class="toast-message">${message}</span>
    `;
    
    // Style the toast
    Object.assign(toast.style, {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        padding: '12px 20px',
        borderRadius: '8px',
        background: type === 'success' ? 'rgba(16, 185, 129, 0.9)' : 
                   type === 'error' ? 'rgba(239, 68, 68, 0.9)' : 
                   'rgba(59, 130, 246, 0.9)',
        color: 'white',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        zIndex: '9999',
        animation: 'slideIn 0.3s ease-out',
        boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)'
    });
    
    document.body.appendChild(toast);
    
    // Remove after 3 seconds
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease-in';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Expose profile functions to window
window.activateProfile = activateProfile;
window.editProfile = editProfile;
window.deleteProfile = deleteProfile;
window.showToast = showToast;

/* =====================================================
   ADDITIONAL ANIMATIONS
   ===================================================== */

// Add CSS for toast animations
const toastStyles = document.createElement('style');
toastStyles.textContent = `
@keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}

@keyframes slideOut {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
}

@keyframes slideDown {
    from { opacity: 0; transform: translateY(-10px) scaleY(0.95); }
    to { opacity: 1; transform: translateY(0) scaleY(1); }
}
`;
document.head.appendChild(toastStyles);
