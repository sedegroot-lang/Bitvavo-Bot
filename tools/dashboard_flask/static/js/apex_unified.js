/**
 * Apex Unified JS - Shared utilities for all dashboard tabs
 * 
 * Provides:
 *  - apexToast()      - Universal toast notifications
 *  - apexModal()      - Premium modal dialogs (replace confirm/prompt/alert)
 *  - apexConfirm()    - Promise-based confirm dialog
 *  - apexPrompt()     - Promise-based prompt dialog
 *  - formatEuro()     - Currency formatting
 *  - formatPct()      - Percentage formatting
 *  - formatTime()     - Time formatting
 *  - escapeHtml()     - XSS protection
 *  - collapsibleInit() - Auto-init collapsible sections
 *  - skeletonLoad()   - Skeleton loading placeholders
 */

(function() {
    'use strict';

    // ========================================================================
    // TOAST NOTIFICATION SYSTEM
    // ========================================================================
    let toastContainer = null;

    function ensureToastContainer() {
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'apex-toast-container';
            document.body.appendChild(toastContainer);
        }
        return toastContainer;
    }

    const TOAST_ICONS = {
        success: '\u2713',
        error: '\u2717',
        warning: '\u26A0',
        info: '\u2139'
    };

    /**
     * Show a toast notification
     * @param {string} message - Toast message
     * @param {string} type - 'success'|'error'|'warning'|'info'
     * @param {number} duration - Auto-dismiss in ms (default 4000, 0 = sticky)
     */
    function apexToast(message, type, duration) {
        type = type || 'info';
        duration = duration !== undefined ? duration : 4000;
        const container = ensureToastContainer();

        const toast = document.createElement('div');
        toast.className = 'apex-toast apex-toast-' + type;
        toast.innerHTML =
            '<span class="apex-toast-icon">' + (TOAST_ICONS[type] || '') + '</span>' +
            '<span>' + escapeHtml(message) + '</span>' +
            '<button class="apex-toast-close" aria-label="Close">\u00D7</button>';

        toast.querySelector('.apex-toast-close').addEventListener('click', function() {
            dismissToast(toast);
        });

        container.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(function() {
            toast.classList.add('show');
        });

        if (duration > 0) {
            setTimeout(function() { dismissToast(toast); }, duration);
        }

        return toast;
    }

    function dismissToast(toast) {
        toast.classList.remove('show');
        setTimeout(function() {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 400);
    }

    // ========================================================================
    // MODAL SYSTEM
    // ========================================================================

    /**
     * Show a modal dialog
     * @param {Object} options
     * @param {string} options.title - Modal title
     * @param {string} options.body - HTML content for modal body
     * @param {Array} options.buttons - [{text, type, onClick}]
     * @returns {Object} {overlay, modal, close}
     */
    function apexModal(options) {
        options = options || {};
        var overlay = document.createElement('div');
        overlay.className = 'apex-modal-overlay';

        var buttonsHtml = '';
        var buttons = options.buttons || [];
        buttons.forEach(function(btn, i) {
            var cls = 'apex-modal-btn';
            if (btn.type === 'primary') cls += ' apex-modal-btn-primary';
            else if (btn.type === 'danger') cls += ' apex-modal-btn-danger';
            else cls += ' apex-modal-btn-cancel';
            buttonsHtml += '<button class="' + cls + '" data-btn-idx="' + i + '">' + escapeHtml(btn.text || 'OK') + '</button>';
        });

        overlay.innerHTML =
            '<div class="apex-modal">' +
                '<div class="apex-modal-header">' +
                    '<span class="apex-modal-title">' + escapeHtml(options.title || '') + '</span>' +
                    '<button class="apex-modal-close" aria-label="Close">\u00D7</button>' +
                '</div>' +
                '<div class="apex-modal-body">' + (options.body || '') + '</div>' +
                (buttonsHtml ? '<div class="apex-modal-footer">' + buttonsHtml + '</div>' : '') +
            '</div>';

        document.body.appendChild(overlay);

        function closeModal() {
            overlay.classList.remove('active');
            setTimeout(function() {
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
            }, 300);
        }

        // Close button
        overlay.querySelector('.apex-modal-close').addEventListener('click', closeModal);

        // Overlay click to close
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeModal();
        });

        // Escape key
        function onEsc(e) {
            if (e.key === 'Escape') {
                closeModal();
                document.removeEventListener('keydown', onEsc);
            }
        }
        document.addEventListener('keydown', onEsc);

        // Button click handlers
        buttons.forEach(function(btn, i) {
            var el = overlay.querySelector('[data-btn-idx="' + i + '"]');
            if (el && btn.onClick) {
                el.addEventListener('click', function() {
                    btn.onClick(closeModal);
                });
            }
        });

        // Show with animation
        requestAnimationFrame(function() {
            overlay.classList.add('active');
        });

        return { overlay: overlay, close: closeModal };
    }

    /**
     * Promise-based confirm dialog (replaces window.confirm)
     * @param {string} title
     * @param {string} message
     * @returns {Promise<boolean>}
     */
    function apexConfirm(title, message) {
        return new Promise(function(resolve) {
            apexModal({
                title: title || 'Bevestigen',
                body: '<p>' + escapeHtml(message || 'Weet je het zeker?') + '</p>',
                buttons: [
                    { text: 'Annuleren', type: 'cancel', onClick: function(close) { close(); resolve(false); } },
                    { text: 'Bevestigen', type: 'primary', onClick: function(close) { close(); resolve(true); } }
                ]
            });
        });
    }

    /**
     * Promise-based prompt dialog (replaces window.prompt)
     * @param {string} title
     * @param {string} message
     * @param {string} defaultValue
     * @param {string} placeholder
     * @returns {Promise<string|null>}
     */
    function apexPrompt(title, message, defaultValue, placeholder) {
        return new Promise(function(resolve) {
            var inputId = 'apex-prompt-' + Date.now();
            var body = '';
            if (message) body += '<p>' + escapeHtml(message) + '</p>';
            body += '<input class="apex-modal-input" id="' + inputId + '" type="text"' +
                    ' value="' + escapeHtml(defaultValue || '') + '"' +
                    ' placeholder="' + escapeHtml(placeholder || '') + '">';

            var modal = apexModal({
                title: title || 'Invoer',
                body: body,
                buttons: [
                    { text: 'Annuleren', type: 'cancel', onClick: function(close) { close(); resolve(null); } },
                    { text: 'OK', type: 'primary', onClick: function(close) {
                        var input = document.getElementById(inputId);
                        close();
                        resolve(input ? input.value : '');
                    }}
                ]
            });

            // Focus input
            setTimeout(function() {
                var input = document.getElementById(inputId);
                if (input) {
                    input.focus();
                    input.select();
                }
            }, 100);

            // Enter key submits
            var input = modal.overlay.querySelector('#' + inputId);
            if (input) {
                input.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter') {
                        modal.close();
                        resolve(input.value);
                    }
                });
            }
        });
    }

    // ========================================================================
    // FORMATTING UTILITIES
    // ========================================================================

    /**
     * Format a number as Euro currency
     * @param {number} value
     * @param {number} decimals (default 2)
     * @returns {string}
     */
    function formatEuro(value, decimals) {
        if (value === null || value === undefined || isNaN(value)) return '\u20AC0.00';
        decimals = decimals !== undefined ? decimals : 2;
        var num = Number(value);
        var sign = num >= 0 ? '' : '-';
        var abs = Math.abs(num);
        return sign + '\u20AC' + abs.toFixed(decimals);
    }

    /**
     * Format percentage with sign
     * @param {number} value
     * @param {number} decimals (default 2)
     * @returns {string}
     */
    function formatPct(value, decimals) {
        if (value === null || value === undefined || isNaN(value)) return '0.00%';
        decimals = decimals !== undefined ? decimals : 2;
        var num = Number(value);
        return (num >= 0 ? '+' : '') + num.toFixed(decimals) + '%';
    }

    /**
     * Format timestamp to locale time string
     * @param {number|string} ts - Timestamp or ISO string
     * @returns {string}
     */
    function formatTime(ts) {
        if (!ts) return '-';
        var d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
        return d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    /**
     * Format timestamp to locale date string
     * @param {number|string} ts
     * @returns {string}
     */
    function formatDate(ts) {
        if (!ts) return '-';
        var d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
        return d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    /**
     * Format a large number with k/M suffix
     * @param {number} value
     * @returns {string}
     */
    function formatCompact(value) {
        if (value === null || value === undefined) return '0';
        var num = Number(value);
        if (Math.abs(num) >= 1e6) return (num / 1e6).toFixed(1) + 'M';
        if (Math.abs(num) >= 1e3) return (num / 1e3).toFixed(1) + 'k';
        return num.toFixed(num % 1 === 0 ? 0 : 2);
    }

    // ========================================================================
    // XSS PROTECTION
    // ========================================================================

    var escapeEl = null;
    /**
     * Escape HTML to prevent XSS
     * @param {string} str
     * @returns {string}
     */
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        if (!escapeEl) escapeEl = document.createElement('div');
        escapeEl.textContent = String(str);
        return escapeEl.innerHTML;
    }

    // ========================================================================
    // COLLAPSIBLE SECTIONS
    // ========================================================================

    function collapsibleInit() {
        document.querySelectorAll('.collapsible-header').forEach(function(header) {
            if (header.dataset.collapsibleInit) return;
            header.dataset.collapsibleInit = 'true';

            var content = header.nextElementSibling;
            if (!content || !content.classList.contains('collapsible-content')) return;

            // Check localStorage for saved state
            var key = 'collapse_' + (header.dataset.section || header.textContent.trim().slice(0, 20));
            var saved = localStorage.getItem(key);
            if (saved === 'expanded' || (!saved && header.classList.contains('expanded'))) {
                header.classList.add('expanded');
                content.classList.add('expanded');
            }

            header.addEventListener('click', function() {
                var isExpanded = header.classList.toggle('expanded');
                content.classList.toggle('expanded');
                localStorage.setItem(key, isExpanded ? 'expanded' : 'collapsed');
            });
        });
    }

    // ========================================================================
    // SKELETON LOADING
    // ========================================================================

    /**
     * Create skeleton loading placeholder
     * @param {number} lines - Number of skeleton lines
     * @returns {string} HTML string
     */
    function skeletonLoad(lines) {
        lines = lines || 3;
        var html = '<div class="skeleton-container">';
        for (var i = 0; i < lines; i++) {
            var width = i === lines - 1 ? '60%' : (70 + Math.random() * 30) + '%';
            html += '<div class="skeleton skeleton-line" style="width: ' + width + '"></div>';
        }
        html += '</div>';
        return html;
    }

    // ========================================================================
    // DATA PAGE ATTRIBUTE
    // ========================================================================

    function setPageAttribute() {
        // Set data-page on main-content for tab-specific CSS
        var path = window.location.pathname;
        var page = 'portfolio';
        if (path.indexOf('/hodl') !== -1) page = 'hodl';
        else if (path.indexOf('/hedge') !== -1) page = 'hedge';
        else if (path.indexOf('/grid') !== -1) page = 'grid';
        else if (path.indexOf('/ai') !== -1) page = 'ai';
        else if (path.indexOf('/parameters') !== -1) page = 'parameters';
        else if (path.indexOf('/performance') !== -1) page = 'performance';
        else if (path.indexOf('/analytics') !== -1) page = 'analytics';
        else if (path.indexOf('/reports') !== -1) page = 'reports';
        else if (path.indexOf('/settings') !== -1) page = 'settings';

        var main = document.getElementById('main-content');
        if (main) main.setAttribute('data-page', page);
        document.body.setAttribute('data-page', page);
    }

    // ========================================================================
    // INIT
    // ========================================================================

    function init() {
        setPageAttribute();
        collapsibleInit();
        console.log('[ApexUnified] Shared utilities loaded');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // ========================================================================
    // GLOBAL EXPORTS
    // ========================================================================

    // Universal functions available everywhere
    window.apexToast = apexToast;
    window.apexModal = apexModal;
    window.apexConfirm = apexConfirm;
    window.apexPrompt = apexPrompt;
    window.formatEuro = window.formatEuro || formatEuro;
    window.formatPct = formatPct;
    window.formatTime = formatTime;
    window.formatDate = formatDate;
    window.formatCompact = formatCompact;
    window.escapeHtml = escapeHtml;
    window.skeletonLoad = skeletonLoad;
    window.collapsibleInit = collapsibleInit;

    // Also expose as namespace
    window.ApexUnified = {
        toast: apexToast,
        modal: apexModal,
        confirm: apexConfirm,
        prompt: apexPrompt,
        formatEuro: formatEuro,
        formatPct: formatPct,
        formatTime: formatTime,
        formatDate: formatDate,
        formatCompact: formatCompact,
        escapeHtml: escapeHtml,
        skeletonLoad: skeletonLoad
    };

    // Backward compatibility: remap showToast/showNotification to apexToast
    window.showToast = apexToast;
    window.showNotification = function(msg, type) { apexToast(msg, type || 'info'); };

    // --- Mobile hamburger navigation ---
    window.toggleMobileNav = function() {
        const tabs = document.getElementById('nav-tabs');
        const btn = document.getElementById('nav-hamburger');
        if (!tabs || !btn) return;
        const open = tabs.classList.toggle('mobile-open');
        btn.classList.toggle('active', open);
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        // Prevent body scroll when nav overlay is open
        document.body.style.overflow = open ? 'hidden' : '';
    };

    // Close mobile nav when a tab link is clicked, or when tapping the overlay background
    document.addEventListener('click', function(e) {
        const navTabs = document.getElementById('nav-tabs');
        if (!navTabs || !navTabs.classList.contains('mobile-open')) return;
        // Close when tapping a tab link
        if (e.target.closest('.nav-tab')) {
            // Let the link navigate — don't preventDefault
            toggleMobileNav();
            return;
        }
        // Close when tapping the overlay background (not on a tab)
        if (e.target === navTabs) {
            toggleMobileNav();
        }
    });

    // --- Visibility-aware intervals ---
    // Pause heavy intervals when tab is hidden to save CPU
    window._apexIntervals = [];
    window.apexSetInterval = function(fn, ms) {
        const id = { fn: fn, ms: ms, timer: null, paused: false };
        id.timer = setInterval(fn, ms);
        window._apexIntervals.push(id);
        return id;
    };
    document.addEventListener('visibilitychange', function() {
        window._apexIntervals.forEach(function(id) {
            if (document.hidden) {
                if (id.timer) { clearInterval(id.timer); id.timer = null; id.paused = true; }
            } else {
                if (id.paused) { id.timer = setInterval(id.fn, id.ms); id.paused = false; }
            }
        });
    });

})();
