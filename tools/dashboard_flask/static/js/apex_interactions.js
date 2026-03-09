/* =====================================================
   APEX INTERACTIONS v1.0
   Next-gen JavaScript for trading dashboard
   Features: Particles, Ticker, Notifications, Sparklines,
   Cursor Glow, Page Transitions, Animated Counters,
   Scroll Progress, Live Clock, P&L Ambient Glow
   ===================================================== */

(function() {
    'use strict';

    // =====================================================
    // 1. PARTICLE NETWORK BACKGROUND
    // =====================================================

    const ParticleNetwork = {
        canvas: null,
        ctx: null,
        particles: [],
        mouse: { x: null, y: null },
        animFrame: null,
        config: {
            particleCount: 50,
            lineDistance: 150,
            particleSpeed: 0.3,
            particleSize: 1.5,
            colors: {
                dark: {
                    particle: 'rgba(56, 97, 251, 0.5)',
                    line: 'rgba(56, 97, 251, %opacity%)',
                    accent: 'rgba(22, 199, 132, 0.4)'
                },
                light: {
                    particle: 'rgba(56, 97, 251, 0.3)',
                    line: 'rgba(56, 97, 251, %opacity%)',
                    accent: 'rgba(22, 199, 132, 0.2)'
                }
            }
        },

        init() {
            this.canvas = document.getElementById('particle-canvas');
            if (!this.canvas) {
                this.canvas = document.createElement('canvas');
                this.canvas.id = 'particle-canvas';
                document.body.prepend(this.canvas);
            }
            this.ctx = this.canvas.getContext('2d');
            this.resize();
            this.createParticles();
            this.bindEvents();
            this.animate();
        },

        resize() {
            this.canvas.width = window.innerWidth;
            this.canvas.height = window.innerHeight;
        },

        createParticles() {
            this.particles = [];
            for (let i = 0; i < this.config.particleCount; i++) {
                this.particles.push({
                    x: Math.random() * this.canvas.width,
                    y: Math.random() * this.canvas.height,
                    vx: (Math.random() - 0.5) * this.config.particleSpeed,
                    vy: (Math.random() - 0.5) * this.config.particleSpeed,
                    size: Math.random() * this.config.particleSize + 0.5,
                    isAccent: Math.random() < 0.2
                });
            }
        },

        bindEvents() {
            window.addEventListener('resize', () => {
                this.resize();
                this.createParticles();
            });

            document.addEventListener('mousemove', (e) => {
                this.mouse.x = e.clientX;
                this.mouse.y = e.clientY;
            });

            document.addEventListener('mouseleave', () => {
                this.mouse.x = null;
                this.mouse.y = null;
            });
        },

        getColors() {
            const theme = document.documentElement.getAttribute('data-theme') || 'dark';
            return this.config.colors[theme] || this.config.colors.dark;
        },

        animate() {
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
            const colors = this.getColors();

            // Update & draw particles
            this.particles.forEach((p, i) => {
                p.x += p.vx;
                p.y += p.vy;

                // Bounce off edges
                if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
                if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;

                // Mouse interaction
                if (this.mouse.x && this.mouse.y) {
                    const dx = p.x - this.mouse.x;
                    const dy = p.y - this.mouse.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < 200) {
                        p.x += dx * 0.001;
                        p.y += dy * 0.001;
                    }
                }

                // Draw particle
                this.ctx.beginPath();
                this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
                this.ctx.fillStyle = p.isAccent ? colors.accent : colors.particle;
                this.ctx.fill();

                // Draw connections
                for (let j = i + 1; j < this.particles.length; j++) {
                    const p2 = this.particles[j];
                    const dx = p.x - p2.x;
                    const dy = p.y - p2.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);

                    if (dist < this.config.lineDistance) {
                        const opacity = (1 - dist / this.config.lineDistance) * 0.15;
                        this.ctx.beginPath();
                        this.ctx.moveTo(p.x, p.y);
                        this.ctx.lineTo(p2.x, p2.y);
                        this.ctx.strokeStyle = colors.line.replace('%opacity%', opacity.toFixed(3));
                        this.ctx.lineWidth = 0.5;
                        this.ctx.stroke();
                    }
                }
            });

            this.animFrame = requestAnimationFrame(() => this.animate());
        },

        destroy() {
            if (this.animFrame) cancelAnimationFrame(this.animFrame);
            if (this.canvas) this.canvas.remove();
        }
    };

    // =====================================================
    // 2. LIVE TICKER TAPE
    // =====================================================

    const TickerTape = {
        container: null,
        track: null,
        markets: [
            { symbol: 'BTC', name: 'Bitcoin', mock: true },
            { symbol: 'ETH', name: 'Ethereum', mock: true },
            { symbol: 'SOL', name: 'Solana', mock: true },
            { symbol: 'XRP', name: 'Ripple', mock: true },
            { symbol: 'ADA', name: 'Cardano', mock: true },
            { symbol: 'LINK', name: 'Chainlink', mock: true },
            { symbol: 'AVAX', name: 'Avalanche', mock: true },
            { symbol: 'DOT', name: 'Polkadot', mock: true },
            { symbol: 'DOGE', name: 'Dogecoin', mock: true },
            { symbol: 'LTC', name: 'Litecoin', mock: true },
            { symbol: 'UNI', name: 'Uniswap', mock: true },
            { symbol: 'AAVE', name: 'Aave', mock: true },
            { symbol: 'NEAR', name: 'Near', mock: true },
            { symbol: 'OP', name: 'Optimism', mock: true },
            { symbol: 'INJ', name: 'Injective', mock: true }
        ],
        prices: {},

        init() {
            this.container = document.getElementById('ticker-tape');
            if (!this.container) return;

            this.track = this.container.querySelector('.ticker-tape-track');
            if (!this.track) return;

            this.render();
            this.startLiveUpdates();
        },

        render() {
            // Create items, duplicate for seamless loop
            const items = this.markets.map(m => this.createItem(m)).join('');
            this.track.innerHTML = items + items; // duplicate for infinite scroll
        },

        createItem(market) {
            const price = this.prices[market.symbol + '-EUR'] || this.prices[market.symbol] || null;
            const change = price ? ((Math.random() - 0.48) * 8).toFixed(2) : null;
            const isUp = change && parseFloat(change) >= 0;

            return `
                <div class="ticker-item" data-ticker-market="${market.symbol}-EUR">
                    <span class="ticker-symbol">${market.symbol}</span>
                    <span class="ticker-price" data-ticker-price="${market.symbol}-EUR">
                        ${price ? '€' + parseFloat(price).toLocaleString('nl-NL', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—'}
                    </span>
                    ${change !== null ? `<span class="ticker-change ${isUp ? 'up' : 'down'}">${isUp ? '+' : ''}${change}%</span>` : ''}
                </div>
            `;
        },

        startLiveUpdates() {
            // Hook into existing WebSocket price updates
            if (typeof window.onPriceUpdate === 'function') {
                window.onPriceUpdate((prices) => {
                    this.prices = prices;
                    this.updatePrices(prices);
                });
            }

            // Also fetch periodically
            this.fetchPrices();
            setInterval(() => this.fetchPrices(), 30000);
        },

        async fetchPrices() {
            try {
                const resp = await fetch('/api/prices');
                if (resp.ok) {
                    const data = await resp.json();
                    this.prices = data.prices || data;
                    this.updatePrices(this.prices);
                }
            } catch (e) {
                // Silent fail
            }
        },

        updatePrices(prices) {
            if (!prices || !this.track) return;

            this.track.querySelectorAll('[data-ticker-price]').forEach(el => {
                const market = el.dataset.tickerPrice;
                const price = prices[market];
                if (price) {
                    const formatted = '€' + parseFloat(price).toLocaleString('nl-NL', {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2
                    });
                    if (el.textContent.trim() !== formatted) {
                        el.textContent = formatted;
                        // Flash animation
                        el.closest('.ticker-item')?.classList.add('flash-update');
                        setTimeout(() => el.closest('.ticker-item')?.classList.remove('flash-update'), 600);
                    }
                }
            });
        }
    };

    // =====================================================
    // 3. NOTIFICATION CENTER
    // =====================================================

    const NotificationCenter = {
        panel: null,
        backdrop: null,
        bell: null,
        notifications: [],
        isOpen: false,
        maxNotifications: 50,

        init() {
            this.createPanel();
            this.createBell();
            this.loadNotifications();
            this.hookWebSocket();
        },

        createPanel() {
            // Backdrop
            this.backdrop = document.createElement('div');
            this.backdrop.className = 'notification-panel-backdrop';
            this.backdrop.addEventListener('click', () => this.close());
            document.body.appendChild(this.backdrop);

            // Panel
            this.panel = document.createElement('div');
            this.panel.className = 'notification-panel';
            this.panel.innerHTML = `
                <div class="notification-panel-header">
                    <h3>Notificaties</h3>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <button class="notification-panel-close" onclick="NotificationCenter.markAllRead()" title="Alles gelezen markeren" style="font-size: 0.7rem;">✓ Alles</button>
                        <button class="notification-panel-close" onclick="NotificationCenter.close()" title="Sluiten">✕</button>
                    </div>
                </div>
                <div class="notification-list" id="notification-list"></div>
            `;
            document.body.appendChild(this.panel);
        },

        createBell() {
            // Find the nav-status area
            const navStatus = document.querySelector('.nav-status');
            if (!navStatus) return;

            this.bell = document.createElement('button');
            this.bell.className = 'notification-bell';
            this.bell.innerHTML = '🔔';
            this.bell.title = 'Notificaties';
            this.bell.addEventListener('click', () => this.toggle());

            // Insert before first child
            navStatus.insertBefore(this.bell, navStatus.firstChild);
        },

        toggle() {
            this.isOpen ? this.close() : this.open();
        },

        open() {
            this.isOpen = true;
            this.panel.classList.add('open');
            this.backdrop.classList.add('open');
            this.renderNotifications();
        },

        close() {
            this.isOpen = false;
            this.panel.classList.remove('open');
            this.backdrop.classList.remove('open');
        },

        addNotification(notification) {
            const entry = {
                id: Date.now() + Math.random(),
                type: notification.type || 'info',
                title: notification.title || '',
                text: notification.text || '',
                time: new Date().toISOString(),
                read: false,
                icon: notification.icon || this.getIcon(notification.type)
            };

            this.notifications.unshift(entry);
            if (this.notifications.length > this.maxNotifications) {
                this.notifications = this.notifications.slice(0, this.maxNotifications);
            }

            this.updateBadge();
            this.saveNotifications();

            if (this.isOpen) {
                this.renderNotifications();
            }
        },

        getIcon(type) {
            const icons = {
                trade: '💰',
                alert: '⚠️',
                info: 'ℹ️',
                ai: '🤖',
                success: '✅',
                error: '❌'
            };
            return icons[type] || icons.info;
        },

        renderNotifications() {
            const list = document.getElementById('notification-list');
            if (!list) return;

            if (this.notifications.length === 0) {
                list.innerHTML = `
                    <div style="text-align: center; padding: 40px 20px; color: var(--text-muted);">
                        <div style="font-size: 2rem; margin-bottom: 8px;">🔔</div>
                        <div style="font-size: 0.8rem;">Geen notificaties</div>
                    </div>
                `;
                return;
            }

            list.innerHTML = this.notifications.map(n => `
                <div class="notification-entry ${n.read ? '' : 'unread'}" data-notification-id="${n.id}">
                    <div class="notification-icon ${n.type}">
                        ${n.icon}
                    </div>
                    <div class="notification-body">
                        <div class="notification-title">${this.escapeHtml(n.title)}</div>
                        <div class="notification-text">${this.escapeHtml(n.text)}</div>
                        <div class="notification-time">${this.formatTime(n.time)}</div>
                    </div>
                </div>
            `).join('');

            // Mark as read on click
            list.querySelectorAll('.notification-entry').forEach(el => {
                el.addEventListener('click', () => {
                    const id = parseFloat(el.dataset.notificationId);
                    const notif = this.notifications.find(n => n.id === id);
                    if (notif) {
                        notif.read = true;
                        el.classList.remove('unread');
                        this.updateBadge();
                        this.saveNotifications();
                    }
                });
            });
        },

        markAllRead() {
            this.notifications.forEach(n => n.read = true);
            this.updateBadge();
            this.saveNotifications();
            this.renderNotifications();
        },

        updateBadge() {
            if (!this.bell) return;
            const unread = this.notifications.filter(n => !n.read).length;
            let badge = this.bell.querySelector('.badge-count');

            if (unread > 0) {
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'badge-count';
                    this.bell.appendChild(badge);
                }
                badge.textContent = unread > 99 ? '99+' : unread;
            } else {
                if (badge) badge.remove();
            }
        },

        formatTime(isoString) {
            const date = new Date(isoString);
            const now = new Date();
            const diffMs = now - date;
            const diffMin = Math.floor(diffMs / 60000);
            const diffHour = Math.floor(diffMs / 3600000);

            if (diffMin < 1) return 'Zojuist';
            if (diffMin < 60) return `${diffMin}m geleden`;
            if (diffHour < 24) return `${diffHour}u geleden`;
            return date.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' });
        },

        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        },

        saveNotifications() {
            try {
                localStorage.setItem('dashboard_notifications', JSON.stringify(this.notifications.slice(0, 30)));
            } catch (e) { /* quota exceeded */ }
        },

        loadNotifications() {
            try {
                const saved = localStorage.getItem('dashboard_notifications');
                if (saved) {
                    this.notifications = JSON.parse(saved);
                    this.updateBadge();
                }
            } catch (e) { /* parse error */ }
        },

        hookWebSocket() {
            // Hook into socket events for live notifications
            if (typeof window.socket !== 'undefined' && window.socket) {
                window.socket.on('trade_opened', (data) => {
                    this.addNotification({
                        type: 'trade',
                        title: `Trade geopend: ${data.market || '?'}`,
                        text: `€${data.amount || '?'} geïnvesteerd`,
                        icon: '📈'
                    });
                });

                window.socket.on('trade_closed', (data) => {
                    const pnl = data.profit || data.pnl || 0;
                    this.addNotification({
                        type: pnl >= 0 ? 'success' : 'alert',
                        title: `Trade gesloten: ${data.market || '?'}`,
                        text: `P&L: ${pnl >= 0 ? '+' : ''}€${parseFloat(pnl).toFixed(2)}`,
                        icon: pnl >= 0 ? '✅' : '📉'
                    });

                    // Celebrate profit
                    if (pnl > 0 && typeof window.Confetti !== 'undefined') {
                        window.Confetti.fire({ count: 80, duration: 2500 });
                    }
                });

                window.socket.on('ai_recommendation', (data) => {
                    this.addNotification({
                        type: 'ai',
                        title: 'AI Aanbeveling',
                        text: data.message || data.summary || 'Nieuwe AI analyse beschikbaar',
                        icon: '🤖'
                    });
                });
            }

            // Fallback: poll status for notifications
            setInterval(() => this.checkForAlerts(), 60000);
        },

        async checkForAlerts() {
            try {
                const resp = await fetch('/api/status');
                if (!resp.ok) return;
                const data = await resp.json();

                // Check for bot offline
                if (data.bot_online === false) {
                    const lastBotAlert = this.notifications.find(n =>
                        n.title === 'Bot Offline' && (Date.now() - new Date(n.time).getTime()) < 300000
                    );
                    if (!lastBotAlert) {
                        this.addNotification({
                            type: 'alert',
                            title: 'Bot Offline',
                            text: 'De trading bot lijkt niet meer actief te zijn',
                            icon: '⚠️'
                        });
                    }
                }
            } catch (e) { /* offline */ }
        }
    };

    // =====================================================
    // 4. CURSOR GLOW EFFECT
    // =====================================================

    const CursorGlow = {
        element: null,

        init() {
            // Don't init on touch devices
            if ('ontouchstart' in window) return;

            this.element = document.createElement('div');
            this.element.className = 'cursor-glow';
            document.body.appendChild(this.element);

            document.addEventListener('mousemove', (e) => {
                this.element.style.left = e.clientX + 'px';
                this.element.style.top = e.clientY + 'px';
                this.element.classList.add('active');
            });

            document.addEventListener('mouseleave', () => {
                this.element.classList.remove('active');
            });
        }
    };

    // =====================================================
    // 5. SCROLL PROGRESS BAR
    // =====================================================

    const ScrollProgress = {
        bar: null,

        init() {
            this.bar = document.createElement('div');
            this.bar.className = 'scroll-progress';
            document.body.prepend(this.bar);

            window.addEventListener('scroll', () => this.update(), { passive: true });
        },

        update() {
            const scrollTop = window.scrollY;
            const docHeight = document.documentElement.scrollHeight - window.innerHeight;
            const progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
            this.bar.style.width = progress + '%';
        }
    };

    // =====================================================
    // 6. LIVE CLOCK
    // =====================================================

    const LiveClock = {
        element: null,

        init() {
            this.element = document.getElementById('live-clock');
            if (!this.element) {
                // Try to add to footer
                const footer = document.querySelector('.dashboard-footer');
                if (footer) {
                    const clock = document.createElement('span');
                    clock.className = 'live-clock';
                    clock.id = 'live-clock';
                    footer.insertBefore(clock, footer.firstChild);
                    this.element = clock;
                }
            }
            if (this.element) {
                this.update();
                setInterval(() => this.update(), 1000);
            }
        },

        update() {
            if (!this.element) return;
            const now = new Date();
            this.element.textContent = now.toLocaleTimeString('nl-NL', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            }) + ' • ' + now.toLocaleDateString('nl-NL', {
                weekday: 'short',
                day: 'numeric',
                month: 'short'
            });
        }
    };

    // =====================================================
    // 7. ANIMATED NUMBER COUNTERS ON LOAD
    // =====================================================

    const AnimatedCounters = {
        init() {
            // Animate hero values on page load
            const heroValues = document.querySelectorAll('.hero-value');
            heroValues.forEach((el, index) => {
                const text = el.textContent.trim();
                const match = text.match(/([+\-€]*)([0-9.,]+)(.*)/);
                if (!match) return;

                const prefix = match[1];
                // Python renders decimals with dot (2.79); Dutch format uses dot as thousands sep (1.234,56).
                // Only strip dots if a comma is also present (true Dutch thousands format).
                const raw = match[2];
                const numStr = raw.includes(',') ? raw.replace(/\./g, '').replace(',', '.') : raw;
                const suffix = match[3];
                const target = parseFloat(numStr);

                if (isNaN(target)) return;

                el.textContent = prefix + '0.00' + suffix;

                setTimeout(() => {
                    this.count(el, 0, target, 800, prefix, suffix);
                }, 100 + index * 100);
            });
        },

        count(element, start, end, duration, prefix, suffix) {
            const startTime = performance.now();
            const isNegative = end < 0;
            const absEnd = Math.abs(end);

            const update = (currentTime) => {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 3);
                const current = start + (absEnd - start) * eased;

                const formatted = current.toLocaleString('nl-NL', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                });

                element.textContent = prefix + formatted + suffix;

                if (progress < 1) {
                    requestAnimationFrame(update);
                }
            };

            requestAnimationFrame(update);
        }
    };

    // =====================================================
    // 8. P&L AMBIENT GLOW
    // =====================================================

    const AmbientGlow = {
        init() {
            this.update();
            // Re-check periodically
            setInterval(() => this.update(), 10000);

            // Also listen for price updates
            if (typeof window.onPriceUpdate === 'function') {
                window.onPriceUpdate(() => setTimeout(() => this.update(), 500));
            }
        },

        update() {
            const pnlEl = document.querySelector('.hero-value.text-success, .hero-value.text-danger, #hero-real-profit');
            if (!pnlEl) return;

            const text = pnlEl.textContent.trim();
            const isPositive = text.includes('+') || pnlEl.classList.contains('text-success');
            const isNegative = text.includes('-') || pnlEl.classList.contains('text-danger');

            document.body.classList.remove('pnl-positive', 'pnl-negative');
            if (isPositive) {
                document.body.classList.add('pnl-positive');
            } else if (isNegative) {
                document.body.classList.add('pnl-negative');
            }
        }
    };

    // =====================================================
    // 9. SPARKLINE MINI-CHARTS
    // =====================================================

    const SparklineCharts = {
        cache: {},

        init() {
            this.createSparklines();
        },

        createSparklines() {
            document.querySelectorAll('[data-sparkline-market]').forEach(container => {
                const market = container.dataset.sparklineMarket;
                if (!market) return;
                this.fetchAndDraw(container, market);
            });
        },

        async fetchAndDraw(container, market) {
            try {
                // Try to get candle data from API
                const resp = await fetch(`/api/candles/${market}?interval=1h&limit=24`);
                let data;
                if (resp.ok) {
                    data = await resp.json();
                } else {
                    // Generate mock data for demo
                    data = this.generateMockData();
                }

                const prices = Array.isArray(data) ? data.map(c => c.close || c[4] || c) : data.prices || this.generateMockData();
                this.draw(container, prices);
            } catch (e) {
                // Draw with mock data
                this.draw(container, this.generateMockData());
            }
        },

        generateMockData() {
            const points = [];
            let price = 100;
            for (let i = 0; i < 24; i++) {
                price += (Math.random() - 0.48) * 3;
                points.push(Math.max(price, 10));
            }
            return points;
        },

        draw(container, prices) {
            if (!prices || prices.length < 2) return;

            const canvas = document.createElement('canvas');
            const dpr = window.devicePixelRatio || 1;
            const width = container.offsetWidth || 120;
            const height = container.offsetHeight || 40;

            canvas.width = width * dpr;
            canvas.height = height * dpr;
            canvas.style.width = width + 'px';
            canvas.style.height = height + 'px';

            const ctx = canvas.getContext('2d');
            ctx.scale(dpr, dpr);

            const min = Math.min(...prices);
            const max = Math.max(...prices);
            const range = max - min || 1;
            const isUp = prices[prices.length - 1] >= prices[0];
            const color = isUp ? '#16c784' : '#ea3943';

            // Draw line
            ctx.beginPath();
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.5;
            ctx.lineJoin = 'round';
            ctx.lineCap = 'round';

            prices.forEach((price, i) => {
                const x = (i / (prices.length - 1)) * width;
                const y = height - ((price - min) / range) * (height * 0.8) - height * 0.1;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();

            // Draw gradient fill
            const gradient = ctx.createLinearGradient(0, 0, 0, height);
            gradient.addColorStop(0, isUp ? 'rgba(22, 199, 132, 0.2)' : 'rgba(234, 57, 67, 0.2)');
            gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

            ctx.lineTo(width, height);
            ctx.lineTo(0, height);
            ctx.closePath();
            ctx.fillStyle = gradient;
            ctx.fill();

            container.innerHTML = '';
            container.appendChild(canvas);
        }
    };

    // =====================================================
    // 10. PAGE TRANSITIONS
    // =====================================================

    const PageTransitions = {
        overlay: null,

        init() {
            this.overlay = document.createElement('div');
            this.overlay.className = 'page-transition-overlay';
            document.body.appendChild(this.overlay);

            // Intercept nav tab clicks
            document.querySelectorAll('.nav-tab').forEach(link => {
                link.addEventListener('click', (e) => {
                    const href = link.getAttribute('href');
                    if (!href || href === '#' || href === window.location.pathname) return;

                    e.preventDefault();
                    this.transition(href);
                });
            });
        },

        transition(url) {
            this.overlay.classList.add('active');
            setTimeout(() => {
                window.location.href = url;
            }, 200);
        }
    };

    // =====================================================
    // 11. KEYBOARD SHORTCUTS ENHANCEMENT
    // =====================================================

    const KeyboardShortcuts = {
        init() {
            document.addEventListener('keydown', (e) => {
                // Don't handle if typing in input
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;

                // Number keys for tab navigation
                const tabs = document.querySelectorAll('.nav-tab');
                if (e.key >= '1' && e.key <= '9') {
                    const index = parseInt(e.key) - 1;
                    if (tabs[index]) {
                        e.preventDefault();
                        tabs[index].click();
                    }
                }

                // N for notifications
                if (e.key === 'n' && !e.ctrlKey && !e.metaKey) {
                    e.preventDefault();
                    NotificationCenter.toggle();
                }

                // Escape to close panels
                if (e.key === 'Escape') {
                    NotificationCenter.close();
                }
            });
        }
    };

    // =====================================================
    // 12. MINI DONUT CHART RENDERER
    // =====================================================

    const DonutChart = {
        create(container, data, options = {}) {
            if (!container) return;

            const size = options.size || 100;
            const lineWidth = options.lineWidth || 8;
            const canvas = document.createElement('canvas');
            const dpr = window.devicePixelRatio || 1;

            canvas.width = size * dpr;
            canvas.height = size * dpr;
            canvas.style.width = size + 'px';
            canvas.style.height = size + 'px';

            const ctx = canvas.getContext('2d');
            ctx.scale(dpr, dpr);

            const centerX = size / 2;
            const centerY = size / 2;
            const radius = (size - lineWidth) / 2;
            const total = data.reduce((sum, d) => sum + d.value, 0);
            let currentAngle = -Math.PI / 2;

            // Draw background ring
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.lineWidth = lineWidth;
            ctx.stroke();

            // Draw segments
            data.forEach(d => {
                const sliceAngle = (d.value / total) * Math.PI * 2;
                ctx.beginPath();
                ctx.arc(centerX, centerY, radius, currentAngle, currentAngle + sliceAngle);
                ctx.strokeStyle = d.color;
                ctx.lineWidth = lineWidth;
                ctx.lineCap = 'round';
                ctx.stroke();
                currentAngle += sliceAngle;
            });

            container.innerHTML = '';
            container.appendChild(canvas);

            // Add center text if specified
            if (options.centerText) {
                const text = document.createElement('div');
                text.className = 'donut-center-text';
                text.textContent = options.centerText;
                container.appendChild(text);
            }
        }
    };

    window.DonutChart = DonutChart;

    // =====================================================
    // 13. INTERSECTION OBSERVER - Lazy animations
    // =====================================================

    const LazyAnimations = {
        init() {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('in-view');
                        observer.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.1 });

            // Observe cards and panels
            document.querySelectorAll('.glass-panel, .hero-card, .status-card, .trade-card-simple').forEach(el => {
                el.classList.add('observe-animate');
                observer.observe(el);
            });
        }
    };

    // Add CSS for lazy animations
    const lazyStyle = document.createElement('style');
    lazyStyle.textContent = `
        .observe-animate {
            opacity: 0;
            transform: translateY(20px);
            transition: opacity 0.5s cubic-bezier(0.16, 1, 0.3, 1),
                        transform 0.5s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .observe-animate.in-view {
            opacity: 1;
            transform: translateY(0);
        }
        /* Stagger */
        .observe-animate:nth-child(2) { transition-delay: 0.05s; }
        .observe-animate:nth-child(3) { transition-delay: 0.1s; }
        .observe-animate:nth-child(4) { transition-delay: 0.15s; }
        .observe-animate:nth-child(5) { transition-delay: 0.2s; }
    `;
    document.head.appendChild(lazyStyle);

    // =====================================================
    // INITIALIZE ALL MODULES
    // =====================================================

    document.addEventListener('DOMContentLoaded', () => {
        console.log('[Apex] Initializing advanced UI/UX modules...');

        // Core visual effects
        ParticleNetwork.init();
        CursorGlow.init();
        ScrollProgress.init();

        // Ticker & data visualization
        TickerTape.init();
        SparklineCharts.init();

        // Interaction modules
        NotificationCenter.init();
        PageTransitions.init();
        KeyboardShortcuts.init();

        // Animation modules
        AnimatedCounters.init();
        AmbientGlow.init();
        LazyAnimations.init();

        // Live clock
        LiveClock.init();

        console.log('[Apex] All modules initialized ✓');
        console.log('[Apex] Press N for notifications, 1-9 for tabs, Ctrl+K for commands');
    });

    // Expose for external use
    window.ParticleNetwork = ParticleNetwork;
    window.TickerTape = TickerTape;
    window.NotificationCenter = NotificationCenter;
    window.SparklineCharts = SparklineCharts;
    window.AnimatedCounters = AnimatedCounters;
    window.AmbientGlow = AmbientGlow;

})();
