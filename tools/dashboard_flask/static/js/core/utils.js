/**
 * Utility Functions
 * Formatters and helpers
 */

/**
 * Format number as EUR currency
 */
export function formatEuro(value, showSign = false) {
    const formatted = new Intl.NumberFormat('nl-NL', {
        style: 'currency',
        currency: 'EUR',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(Math.abs(value));
    
    if (showSign) {
        return value >= 0 ? `+${formatted}` : `-${formatted}`;
    }
    return value < 0 ? `-${formatted}` : formatted;
}

/**
 * Format number as percentage
 */
export function formatPercent(value, showSign = false, decimals = 2) {
    const formatted = `${Math.abs(value).toFixed(decimals)}%`;
    
    if (showSign) {
        return value >= 0 ? `+${formatted}` : `-${formatted}`;
    }
    return value < 0 ? `-${formatted}` : formatted;
}

/**
 * Format crypto amount with appropriate decimals
 */
export function formatCrypto(value, decimals = 6) {
    return parseFloat(value).toFixed(decimals);
}

/**
 * Format price with auto-decimals
 */
export function formatPrice(value) {
    if (value >= 1) {
        return formatEuro(value);
    }
    // Small values need more decimals
    return `€${parseFloat(value).toFixed(6)}`;
}

/**
 * Format timestamp to locale time
 */
export function formatTime(timestamp) {
    if (!timestamp) return '-';
    
    const date = typeof timestamp === 'string' 
        ? new Date(timestamp) 
        : new Date(timestamp * 1000);
    
    return date.toLocaleTimeString('nl-NL', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

/**
 * Format timestamp to locale date
 */
export function formatDate(timestamp) {
    if (!timestamp) return '-';
    
    const date = typeof timestamp === 'string' 
        ? new Date(timestamp) 
        : new Date(timestamp * 1000);
    
    return date.toLocaleDateString('nl-NL', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
    });
}

/**
 * Format timestamp to relative time (e.g., "2 minutes ago")
 */
export function formatRelativeTime(timestamp) {
    if (!timestamp) return '-';
    
    const date = typeof timestamp === 'string' 
        ? new Date(timestamp) 
        : new Date(timestamp * 1000);
    
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);
    
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

/**
 * Debounce function
 */
export function debounce(fn, delay) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
}

/**
 * Throttle function
 */
export function throttle(fn, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            fn.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Parse URL query parameters
 */
export function parseQueryParams() {
    const params = new URLSearchParams(window.location.search);
    const result = {};
    for (const [key, value] of params) {
        result[key] = value;
    }
    return result;
}

/**
 * Update element text content safely
 */
export function setText(selector, text) {
    const el = typeof selector === 'string' 
        ? document.querySelector(selector) 
        : selector;
    if (el) el.textContent = text;
}

/**
 * Update element innerHTML safely
 */
export function setHTML(selector, html) {
    const el = typeof selector === 'string' 
        ? document.querySelector(selector) 
        : selector;
    if (el) el.innerHTML = html;
}

/**
 * Add/remove class based on condition
 */
export function toggleClass(selector, className, condition) {
    const el = typeof selector === 'string' 
        ? document.querySelector(selector) 
        : selector;
    if (el) el.classList.toggle(className, condition);
}

/**
 * Get crypto symbol from market string
 */
export function getSymbolFromMarket(market) {
    return market.replace('-EUR', '').replace('-BTC', '');
}

/**
 * Show toast notification
 */
export function showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.textContent = message;
    
    const container = document.getElementById('toast-container') || document.body;
    container.appendChild(toast);
    
    // Trigger animation
    requestAnimationFrame(() => {
        toast.classList.add('toast--visible');
    });
    
    setTimeout(() => {
        toast.classList.remove('toast--visible');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/**
 * Copy text to clipboard
 */
export async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard', 'success');
        return true;
    } catch {
        showToast('Failed to copy', 'error');
        return false;
    }
}
