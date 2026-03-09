/**
 * Main JavaScript Entry Point
 * Initializes core modules and page-specific logic
 */

import { SocketManager, socketManager } from './core/socket.js';
import { ApiClient, api } from './core/api.js';
import { formatEuro, formatPercent, formatCryptoAmount } from './core/utils.js';

// Make utilities available globally for inline usage
window.formatEuro = formatEuro;
window.formatPercent = formatPercent;
window.formatCryptoAmount = formatCryptoAmount;
window.api = api;

/**
 * Initialize application on DOM ready
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log('[App] Initializing Quantum Bot Dashboard');
    
    // Initialize WebSocket connection
    if (typeof io !== 'undefined') {
        socketManager.connect();
        window.socketManager = socketManager;
    } else {
        console.warn('[App] Socket.IO not available');
    }
    
    // Initialize page-specific modules
    initCurrentPage();
    
    // Setup global event listeners
    setupGlobalListeners();
});

/**
 * Initialize current page based on body class or URL
 */
function initCurrentPage() {
    const path = window.location.pathname;
    const pageModules = {
        '/portfolio': () => import('./pages/portfolio.js'),
        '/': () => import('./pages/portfolio.js'),
        '/grid': () => import('./pages/grid.js'),
        '/performance': () => import('./pages/performance.js'),
        '/analytics': () => import('./pages/analytics.js'),
    };
    
    const loader = pageModules[path];
    if (loader) {
        loader()
            .then(module => {
                if (module.init) {
                    module.init();
                }
                console.log(`[App] Loaded module for ${path}`);
            })
            .catch(err => {
                // Module not found - that's okay, not all pages have dedicated JS
                console.debug(`[App] No module for ${path}:`, err.message);
            });
    }
}

/**
 * Setup global event listeners
 */
function setupGlobalListeners() {
    // Toast notifications
    document.addEventListener('show-toast', (e) => {
        showToast(e.detail.message, e.detail.type);
    });
    
    // Connection status indicator
    if (socketManager) {
        socketManager.on('connection', ({ status }) => {
            updateConnectionStatus(status === 'online');
        });
    }
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl+R: Manual refresh
        if (e.ctrlKey && e.key === 'r' && !e.shiftKey) {
            e.preventDefault();
            if (socketManager) {
                socketManager.requestRefresh();
                showToast('Refreshing data...', 'info');
            }
        }
    });
}

/**
 * Show toast notification
 */
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container') || createToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `
        <span class="toast__message">${message}</span>
        <button class="toast__close" onclick="this.parentElement.remove()">×</button>
    `;
    
    container.appendChild(toast);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        toast.classList.add('toast--fade-out');
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
}

/**
 * Update connection status UI
 */
function updateConnectionStatus(online) {
    const indicator = document.getElementById('connection-status');
    if (indicator) {
        indicator.classList.toggle('status-dot--online', online);
        indicator.classList.toggle('status-dot--offline', !online);
        indicator.title = online ? 'Connected' : 'Disconnected';
    }
}

// Export for use in other modules
export { showToast, updateConnectionStatus };
