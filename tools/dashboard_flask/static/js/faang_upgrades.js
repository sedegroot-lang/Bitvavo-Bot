/* =====================================================
   FAANG-LEVEL JAVASCRIPT v1.0
   Google/Tesla/Apple Quality Standards
   ===================================================== */

(function() {
    'use strict';

    // =====================================================
    // 1. TOAST NOTIFICATION SYSTEM
    // =====================================================
    
    const ToastManager = {
        container: null,
        
        init() {
            if (this.container) return;
            
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            this.container.setAttribute('role', 'alert');
            this.container.setAttribute('aria-live', 'polite');
            document.body.appendChild(this.container);
        },
        
        show(options) {
            this.init();
            
            const {
                type = 'info',
                title = '',
                message = '',
                duration = 5000,
                closable = true
            } = options;
            
            const icons = {
                success: '✓',
                error: '✕',
                warning: '⚠',
                info: 'ℹ'
            };
            
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.innerHTML = `
                <span class="toast-icon" aria-hidden="true">${icons[type] || icons.info}</span>
                <div class="toast-content">
                    ${title ? `<div class="toast-title">${this.escapeHtml(title)}</div>` : ''}
                    ${message ? `<div class="toast-message">${this.escapeHtml(message)}</div>` : ''}
                </div>
                ${closable ? '<button class="toast-close" aria-label="Sluiten">×</button>' : ''}
                <div class="toast-progress" style="color: var(--${type === 'success' ? 'profit' : type === 'error' ? 'loss' : type === 'warning' ? 'gold' : 'accent'})"></div>
            `;
            
            this.container.appendChild(toast);
            
            // Animate in
            requestAnimationFrame(() => {
                toast.classList.add('show');
            });
            
            // Close button
            if (closable) {
                toast.querySelector('.toast-close').addEventListener('click', () => {
                    this.hide(toast);
                });
            }
            
            // Auto dismiss
            if (duration > 0) {
                setTimeout(() => this.hide(toast), duration);
            }
            
            return toast;
        },
        
        hide(toast) {
            toast.classList.remove('show');
            toast.classList.add('hiding');
            setTimeout(() => toast.remove(), 400);
        },
        
        success(message, title = 'Succes') {
            return this.show({ type: 'success', title, message });
        },
        
        error(message, title = 'Fout') {
            return this.show({ type: 'error', title, message });
        },
        
        warning(message, title = 'Waarschuwing') {
            return this.show({ type: 'warning', title, message });
        },
        
        info(message, title = 'Info') {
            return this.show({ type: 'info', title, message });
        },
        
        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    };
    
    window.Toast = ToastManager;
    window.showToast = (message, type = 'info') => ToastManager[type]?.(message) || ToastManager.info(message);

    // =====================================================
    // 2. LOADING STATE MANAGER
    // =====================================================
    
    const LoadingManager = {
        overlay: null,
        
        createOverlay() {
            if (this.overlay) return this.overlay;
            
            this.overlay = document.createElement('div');
            this.overlay.className = 'loading-overlay';
            this.overlay.innerHTML = `
                <div class="loading-content">
                    <div class="pulse-loader">
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                    <p class="loading-text" style="margin-top: 16px; color: var(--text-secondary);">Laden...</p>
                </div>
            `;
            document.body.appendChild(this.overlay);
            return this.overlay;
        },
        
        show(text = 'Laden...') {
            const overlay = this.createOverlay();
            overlay.querySelector('.loading-text').textContent = text;
            requestAnimationFrame(() => overlay.classList.add('active'));
        },
        
        hide() {
            if (this.overlay) {
                this.overlay.classList.remove('active');
            }
        },
        
        // Create skeleton for a container
        showSkeleton(container, type = 'card') {
            const skeleton = document.createElement('div');
            skeleton.className = 'skeleton-card skeleton-shimmer';
            skeleton.innerHTML = this.getSkeletonTemplate(type);
            container.innerHTML = '';
            container.appendChild(skeleton);
            return skeleton;
        },
        
        getSkeletonTemplate(type) {
            switch(type) {
                case 'card':
                    return `
                        <div class="skeleton-header">
                            <div class="skeleton skeleton-avatar skeleton-shimmer"></div>
                            <div style="flex: 1;">
                                <div class="skeleton skeleton-text md skeleton-shimmer" style="margin-bottom: 8px;"></div>
                                <div class="skeleton skeleton-text sm skeleton-shimmer"></div>
                            </div>
                        </div>
                        <div class="skeleton skeleton-text lg skeleton-shimmer" style="margin-bottom: 12px;"></div>
                        <div class="skeleton skeleton-chart skeleton-shimmer"></div>
                    `;
                case 'table':
                    return `
                        <div class="skeleton skeleton-text" style="height: 40px; margin-bottom: 8px;"></div>
                        <div class="skeleton skeleton-text" style="height: 40px; margin-bottom: 8px;"></div>
                        <div class="skeleton skeleton-text" style="height: 40px; margin-bottom: 8px;"></div>
                    `;
                default:
                    return `<div class="skeleton skeleton-text lg skeleton-shimmer"></div>`;
            }
        }
    };
    
    window.Loading = LoadingManager;

    // =====================================================
    // 3. KEYBOARD NAVIGATION
    // =====================================================
    
    const KeyboardNav = {
        shortcuts: {},
        enabled: true,
        
        init() {
            document.addEventListener('keydown', (e) => this.handleKeydown(e));
            this.registerDefaults();
        },
        
        registerDefaults() {
            // Global shortcuts
            this.register('r', () => {
                if (typeof requestRefresh === 'function') requestRefresh();
            }, 'Refresh data');
            
            this.register('/', () => {
                const search = document.querySelector('[type="search"], .search-input');
                if (search) search.focus();
            }, 'Focus search');
            
            this.register('Escape', () => {
                document.activeElement?.blur();
                this.closeModals();
            }, 'Close/Blur');
            
            // Tab navigation with numbers
            for (let i = 1; i <= 9; i++) {
                this.register(String(i), () => {
                    const tabs = document.querySelectorAll('.nav-tab');
                    if (tabs[i - 1]) tabs[i - 1].click();
                }, `Go to tab ${i}`);
            }
        },
        
        register(key, callback, description = '') {
            this.shortcuts[key.toLowerCase()] = { callback, description };
        },
        
        handleKeydown(e) {
            if (!this.enabled) return;
            
            // Ignore if typing in input
            if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) {
                if (e.key !== 'Escape') return;
            }
            
            const key = e.key.toLowerCase();
            const shortcut = this.shortcuts[key];
            
            if (shortcut && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                shortcut.callback();
            }
        },
        
        closeModals() {
            document.querySelectorAll('.modal.show, [data-modal].show').forEach(m => {
                m.classList.remove('show');
            });
        },
        
        showHelp() {
            const shortcuts = Object.entries(this.shortcuts)
                .map(([key, { description }]) => `<kbd>${key}</kbd> - ${description}`)
                .join('<br>');
            
            Toast.info(shortcuts, 'Keyboard Shortcuts');
        }
    };
    
    // Register ? for help
    KeyboardNav.register('?', () => KeyboardNav.showHelp(), 'Show shortcuts');
    
    window.KeyboardNav = KeyboardNav;

    // =====================================================
    // 4. CONNECTION STATUS BANNER
    // =====================================================
    
    const ConnectionBanner = {
        banner: null,
        
        init() {
            this.banner = document.createElement('div');
            this.banner.className = 'connection-banner';
            this.banner.setAttribute('role', 'alert');
            document.body.prepend(this.banner);
            
            // Listen for connection events
            window.addEventListener('online', () => this.hide());
            window.addEventListener('offline', () => this.show('Geen internetverbinding'));
        },
        
        show(message, type = 'error') {
            this.banner.textContent = message;
            this.banner.className = `connection-banner show ${type}`;
        },
        
        hide() {
            this.banner.classList.remove('show');
        },
        
        showReconnecting() {
            this.show('Verbinding herstellen...', 'reconnecting');
        }
    };
    
    window.ConnectionBanner = ConnectionBanner;

    // =====================================================
    // 5. ANIMATED VALUE UPDATES
    // =====================================================
    
    const ValueAnimator = {
        animate(element, newValue, options = {}) {
            const {
                duration = 400,
                prefix = '',
                suffix = '',
                decimals = 2,
                highlightChange = true
            } = options;
            
            const currentText = element.textContent.replace(/[^0-9.-]/g, '');
            const currentValue = parseFloat(currentText) || 0;
            const targetValue = parseFloat(newValue) || 0;
            
            if (Math.abs(currentValue - targetValue) < 0.001) return;
            
            // Highlight direction
            if (highlightChange) {
                const className = targetValue > currentValue ? 'price-flash-up' : 'price-flash-down';
                element.classList.add(className);
                setTimeout(() => element.classList.remove(className), 600);
            }
            
            // Animate number
            const startTime = performance.now();
            const animate = (currentTime) => {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                
                // Easing
                const easeOut = 1 - Math.pow(1 - progress, 3);
                const value = currentValue + (targetValue - currentValue) * easeOut;
                
                element.textContent = prefix + value.toFixed(decimals) + suffix;
                
                if (progress < 1) {
                    requestAnimationFrame(animate);
                }
            };
            
            requestAnimationFrame(animate);
        }
    };
    
    window.ValueAnimator = ValueAnimator;

    // =====================================================
    // 6. ACCESSIBILITY ENHANCEMENTS
    // =====================================================
    
    const A11y = {
        init() {
            this.addSkipLink();
            this.enhanceInteractiveElements();
            this.announceUpdates();
        },
        
        addSkipLink() {
            const skip = document.createElement('a');
            skip.href = '#main-content';
            skip.className = 'skip-to-main';
            skip.textContent = 'Ga naar hoofdinhoud';
            document.body.prepend(skip);
            
            // Add id to main content
            const main = document.querySelector('main, .main-content');
            if (main) main.id = 'main-content';
        },
        
        enhanceInteractiveElements() {
            // Add missing button roles
            document.querySelectorAll('[onclick]:not(button):not(a)').forEach(el => {
                if (!el.getAttribute('role')) {
                    el.setAttribute('role', 'button');
                    el.setAttribute('tabindex', '0');
                }
            });
            
            // Add aria-labels to icon buttons
            document.querySelectorAll('.btn:not([aria-label])').forEach(btn => {
                const text = btn.textContent.trim();
                if (text.length <= 2) { // Likely an icon
                    const title = btn.getAttribute('title');
                    if (title) btn.setAttribute('aria-label', title);
                }
            });
        },
        
        announceUpdates() {
            // Create live region for announcements
            const liveRegion = document.createElement('div');
            liveRegion.setAttribute('role', 'status');
            liveRegion.setAttribute('aria-live', 'polite');
            liveRegion.className = 'sr-only';
            liveRegion.id = 'a11y-announcer';
            document.body.appendChild(liveRegion);
        },
        
        announce(message) {
            const announcer = document.getElementById('a11y-announcer');
            if (announcer) {
                announcer.textContent = message;
                setTimeout(() => announcer.textContent = '', 1000);
            }
        }
    };
    
    window.A11y = A11y;

    // =====================================================
    // 7. PERFORMANCE MONITORING
    // =====================================================
    
    const PerfMonitor = {
        metrics: {},
        
        mark(name) {
            this.metrics[name] = performance.now();
        },
        
        measure(name, startMark) {
            const end = performance.now();
            const start = this.metrics[startMark] || end;
            const duration = end - start;
            
            if (duration > 100) {
                console.warn(`[Perf] ${name}: ${duration.toFixed(2)}ms (slow)`);
            }
            
            return duration;
        },
        
        // Log Core Web Vitals
        logVitals() {
            if ('PerformanceObserver' in window) {
                // LCP
                new PerformanceObserver((list) => {
                    const entries = list.getEntries();
                    const lcp = entries[entries.length - 1];
                    console.log('[Vitals] LCP:', lcp.startTime.toFixed(2), 'ms');
                }).observe({ type: 'largest-contentful-paint', buffered: true });
                
                // FID
                new PerformanceObserver((list) => {
                    const entries = list.getEntries();
                    entries.forEach(entry => {
                        console.log('[Vitals] FID:', entry.processingStart - entry.startTime, 'ms');
                    });
                }).observe({ type: 'first-input', buffered: true });
            }
        }
    };
    
    window.PerfMonitor = PerfMonitor;

    // =====================================================
    // 8. LAZY LOADING FOR CARDS
    // =====================================================
    
    const LazyLoader = {
        observer: null,
        
        init() {
            if (!('IntersectionObserver' in window)) return;
            
            this.observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const card = entry.target;
                        this.loadCard(card);
                        this.observer.unobserve(card);
                    }
                });
            }, {
                rootMargin: '100px',
                threshold: 0.1
            });
        },
        
        observe(element) {
            if (this.observer) {
                this.observer.observe(element);
            }
        },
        
        loadCard(card) {
            // Load chart if present
            const canvas = card.querySelector('canvas[data-lazy]');
            if (canvas) {
                const market = canvas.dataset.market;
                if (typeof initializeTradeChart === 'function') {
                    initializeTradeChart(market);
                }
            }
            
            card.classList.add('loaded');
        }
    };
    
    window.LazyLoader = LazyLoader;

    // =====================================================
    // 9. SMOOTH SCROLL
    // =====================================================
    
    const SmoothScroll = {
        init() {
            document.querySelectorAll('a[href^="#"]').forEach(anchor => {
                anchor.addEventListener('click', (e) => {
                    const target = document.querySelector(anchor.getAttribute('href'));
                    if (target) {
                        e.preventDefault();
                        target.scrollIntoView({
                            behavior: 'smooth',
                            block: 'start'
                        });
                    }
                });
            });
        }
    };
    
    window.SmoothScroll = SmoothScroll;

    // =====================================================
    // 10. INITIALIZE ON DOM READY
    // =====================================================
    
    document.addEventListener('DOMContentLoaded', () => {
        // Initialize all modules
        ToastManager.init();
        KeyboardNav.init();
        ConnectionBanner.init();
        A11y.init();
        LazyLoader.init();
        SmoothScroll.init();
        
        // Performance logging in dev
        if (location.hostname === 'localhost') {
            PerfMonitor.logVitals();
        }
        
        console.log('[FAANG] All modules initialized');
    });

    // =====================================================
    // 11. ERROR BOUNDARY
    // =====================================================
    
    window.addEventListener('error', (event) => {
        console.error('[Error]', event.message);
        
        // Show user-friendly error
        if (event.message.includes('fetch') || event.message.includes('network')) {
            Toast.error('Netwerk fout. Controleer je verbinding.', 'Verbindingsprobleem');
        }
    });
    
    window.addEventListener('unhandledrejection', (event) => {
        console.error('[Promise Error]', event.reason);
        
        if (event.reason?.message?.includes('fetch')) {
            Toast.error('Data kon niet worden geladen', 'Fout');
        }
    });

})();
