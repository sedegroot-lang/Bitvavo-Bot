/* =====================================================
   FAANG 10/10 - ULTIMATE JAVASCRIPT
   Advanced interactions for Google/Tesla/Apple level
   ===================================================== */

(function() {
    'use strict';

    // =====================================================
    // 1. COMMAND PALETTE (⌘K / Ctrl+K)
    // =====================================================
    
    const CommandPalette = {
        element: null,
        input: null,
        results: null,
        commands: [],
        activeIndex: 0,
        isOpen: false,
        
        init() {
            this.createPalette();
            this.registerDefaultCommands();
            this.bindEvents();
        },
        
        createPalette() {
            this.element = document.createElement('div');
            this.element.className = 'command-palette';
            this.element.innerHTML = `
                <input type="text" class="command-palette-input" placeholder="Type a command or search..." aria-label="Command palette">
                <div class="command-palette-results" role="listbox"></div>
            `;
            document.body.appendChild(this.element);
            
            this.input = this.element.querySelector('.command-palette-input');
            this.results = this.element.querySelector('.command-palette-results');
            
            // Backdrop
            this.backdrop = document.createElement('div');
            this.backdrop.className = 'command-palette-backdrop';
            this.backdrop.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.5);
                z-index: 9999;
                opacity: 0;
                visibility: hidden;
                transition: opacity 0.2s ease;
            `;
            document.body.appendChild(this.backdrop);
        },
        
        registerDefaultCommands() {
            this.register({
                id: 'goto-portfolio',
                name: 'Go to Portfolio',
                icon: '📊',
                shortcut: '1',
                action: () => window.location.href = '/portfolio'
            });
            this.register({
                id: 'goto-hodl',
                name: 'Go to HODL',
                icon: '💎',
                shortcut: '2',
                action: () => window.location.href = '/hodl'
            });
            this.register({
                id: 'goto-analytics',
                name: 'Go to Analytics',
                icon: '📈',
                shortcut: '8',
                action: () => window.location.href = '/analytics'
            });
            this.register({
                id: 'refresh',
                name: 'Refresh Data',
                icon: '🔄',
                shortcut: 'R',
                action: () => typeof requestRefresh === 'function' && requestRefresh()
            });
            this.register({
                id: 'toggle-theme',
                name: 'Toggle Theme',
                icon: '🌓',
                action: () => typeof toggleTheme === 'function' && toggleTheme()
            });
            this.register({
                id: 'show-shortcuts',
                name: 'Show Keyboard Shortcuts',
                icon: '⌨️',
                shortcut: '?',
                action: () => window.KeyboardNav?.showHelp()
            });
        },
        
        register(command) {
            this.commands.push(command);
        },
        
        bindEvents() {
            // Open with Ctrl+K or Cmd+K
            document.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                    e.preventDefault();
                    this.toggle();
                }
                
                if (this.isOpen) {
                    if (e.key === 'Escape') {
                        this.close();
                    } else if (e.key === 'ArrowDown') {
                        e.preventDefault();
                        this.navigate(1);
                    } else if (e.key === 'ArrowUp') {
                        e.preventDefault();
                        this.navigate(-1);
                    } else if (e.key === 'Enter') {
                        e.preventDefault();
                        this.executeSelected();
                    }
                }
            });
            
            this.input.addEventListener('input', () => this.filter());
            this.backdrop.addEventListener('click', () => this.close());
        },
        
        toggle() {
            this.isOpen ? this.close() : this.open();
        },
        
        open() {
            this.isOpen = true;
            this.element.classList.add('open');
            this.backdrop.style.opacity = '1';
            this.backdrop.style.visibility = 'visible';
            this.input.value = '';
            this.activeIndex = 0;
            this.filter();
            setTimeout(() => this.input.focus(), 100);
        },
        
        close() {
            this.isOpen = false;
            this.element.classList.remove('open');
            this.backdrop.style.opacity = '0';
            this.backdrop.style.visibility = 'hidden';
        },
        
        filter() {
            const query = this.input.value.toLowerCase();
            const filtered = this.commands.filter(cmd => 
                cmd.name.toLowerCase().includes(query)
            );
            
            this.results.innerHTML = filtered.map((cmd, i) => `
                <div class="command-palette-item ${i === this.activeIndex ? 'active' : ''}" 
                     data-index="${i}" role="option">
                    <span class="command-icon">${cmd.icon || '⚡'}</span>
                    <span class="command-name">${cmd.name}</span>
                    ${cmd.shortcut ? `<kbd class="kbd" style="margin-left: auto;">${cmd.shortcut}</kbd>` : ''}
                </div>
            `).join('');
            
            // Bind click events
            this.results.querySelectorAll('.command-palette-item').forEach((item, i) => {
                item.addEventListener('click', () => {
                    this.activeIndex = i;
                    this.executeSelected();
                });
            });
        },
        
        navigate(delta) {
            const items = this.results.querySelectorAll('.command-palette-item');
            if (items.length === 0) return;
            
            items[this.activeIndex]?.classList.remove('active');
            this.activeIndex = (this.activeIndex + delta + items.length) % items.length;
            items[this.activeIndex]?.classList.add('active');
            items[this.activeIndex]?.scrollIntoView({ block: 'nearest' });
        },
        
        executeSelected() {
            const query = this.input.value.toLowerCase();
            const filtered = this.commands.filter(cmd => 
                cmd.name.toLowerCase().includes(query)
            );
            
            if (filtered[this.activeIndex]) {
                this.close();
                filtered[this.activeIndex].action();
            }
        }
    };
    
    window.CommandPalette = CommandPalette;

    // =====================================================
    // 2. CONFETTI CELEBRATION
    // =====================================================
    
    const Confetti = {
        colors: ['#16c784', '#3861fb', '#f0b90b', '#8b5cf6', '#ea3943'],
        
        fire(options = {}) {
            const {
                count = 100,
                duration = 3000,
                spread = 70
            } = options;
            
            const container = document.createElement('div');
            container.className = 'confetti-container';
            document.body.appendChild(container);
            
            for (let i = 0; i < count; i++) {
                const confetti = document.createElement('div');
                confetti.className = 'confetti';
                confetti.style.cssText = `
                    left: ${Math.random() * 100}%;
                    background: ${this.colors[Math.floor(Math.random() * this.colors.length)]};
                    width: ${Math.random() * 10 + 5}px;
                    height: ${Math.random() * 10 + 5}px;
                    animation-delay: ${Math.random() * 0.5}s;
                    animation-duration: ${duration / 1000 + Math.random()}s;
                `;
                container.appendChild(confetti);
            }
            
            setTimeout(() => container.remove(), duration + 1000);
        },
        
        celebrateProfit() {
            this.fire({ count: 150, duration: 4000 });
        }
    };
    
    window.Confetti = Confetti;

    // =====================================================
    // 3. SMOOTH NUMBER COUNTER
    // =====================================================
    
    const NumberCounter = {
        animate(element, endValue, options = {}) {
            const {
                duration = 1000,
                decimals = 2,
                prefix = '',
                suffix = ''
            } = options;
            
            const startValue = parseFloat(element.textContent.replace(/[^0-9.-]/g, '')) || 0;
            const startTime = performance.now();
            
            const update = (currentTime) => {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                
                // Easing function
                const eased = 1 - Math.pow(1 - progress, 4);
                const current = startValue + (endValue - startValue) * eased;
                
                element.textContent = prefix + current.toFixed(decimals) + suffix;
                
                if (progress < 1) {
                    requestAnimationFrame(update);
                }
            };
            
            requestAnimationFrame(update);
        },
        
        countUp(element, endValue, options = {}) {
            return this.animate(element, endValue, { ...options });
        }
    };
    
    window.NumberCounter = NumberCounter;

    // =====================================================
    // 4. 3D TILT EFFECT
    // =====================================================
    
    const TiltEffect = {
        init(selector = '.card-tilt') {
            document.querySelectorAll(selector).forEach(card => {
                card.addEventListener('mousemove', (e) => this.handleMove(e, card));
                card.addEventListener('mouseleave', (e) => this.handleLeave(e, card));
            });
        },
        
        handleMove(e, card) {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            
            const rotateX = (y - centerY) / 10;
            const rotateY = (centerX - x) / 10;
            
            card.style.transform = `
                perspective(1000px) 
                rotateX(${rotateX}deg) 
                rotateY(${rotateY}deg) 
                translateY(-4px)
            `;
        },
        
        handleLeave(e, card) {
            card.style.transform = '';
        }
    };
    
    window.TiltEffect = TiltEffect;

    // =====================================================
    // 5. RIPPLE EFFECT
    // =====================================================
    
    const RippleEffect = {
        init(selector = '.ripple, .btn') {
            document.querySelectorAll(selector).forEach(el => {
                el.addEventListener('click', (e) => this.create(e, el));
            });
        },
        
        create(e, element) {
            const ripple = document.createElement('span');
            const rect = element.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;
            
            ripple.style.cssText = `
                position: absolute;
                width: ${size}px;
                height: ${size}px;
                left: ${x}px;
                top: ${y}px;
                background: rgba(255, 255, 255, 0.3);
                border-radius: 50%;
                transform: scale(0);
                animation: ripple-animation 0.6s ease-out;
                pointer-events: none;
            `;
            
            element.style.position = 'relative';
            element.style.overflow = 'hidden';
            element.appendChild(ripple);
            
            setTimeout(() => ripple.remove(), 600);
        }
    };
    
    // Add ripple animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes ripple-animation {
            to { transform: scale(4); opacity: 0; }
        }
    `;
    document.head.appendChild(style);
    
    window.RippleEffect = RippleEffect;

    // =====================================================
    // 6. RETRY BUTTON HANDLER
    // =====================================================
    
    document.addEventListener('click', (e) => {
        const retryBtn = e.target.closest('[data-retry-target]');
        if (retryBtn) {
            const targetId = retryBtn.dataset.retryTarget;
            if (targetId) {
                const target = document.getElementById(targetId);
                if (target) target.click();
            } else {
                location.reload();
            }
        }
    });

    // =====================================================
    // 7. PROGRESS BAR AUTO-ANIMATE
    // =====================================================
    
    const ProgressAnimator = {
        init() {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const fill = entry.target;
                        const width = fill.dataset.width || '0';
                        setTimeout(() => {
                            fill.style.width = width + '%';
                        }, 100);
                    }
                });
            }, { threshold: 0.1 });
            
            document.querySelectorAll('[data-width]').forEach(el => {
                observer.observe(el);
            });
        }
    };
    
    window.ProgressAnimator = ProgressAnimator;

    // =====================================================
    // 8. PRICE FLASH EFFECT
    // =====================================================
    
    const PriceFlash = {
        flash(element, direction) {
            const className = direction > 0 ? 'price-flash-up' : 'price-flash-down';
            element.classList.add(className);
            setTimeout(() => element.classList.remove(className), 600);
        },
        
        update(element, newValue, oldValue) {
            if (newValue > oldValue) {
                this.flash(element, 1);
            } else if (newValue < oldValue) {
                this.flash(element, -1);
            }
        }
    };
    
    window.PriceFlash = PriceFlash;

    // =====================================================
    // 9. HAPTIC FEEDBACK (for supported devices)
    // =====================================================
    
    const Haptic = {
        light() {
            if ('vibrate' in navigator) {
                navigator.vibrate(10);
            }
        },
        
        medium() {
            if ('vibrate' in navigator) {
                navigator.vibrate(25);
            }
        },
        
        heavy() {
            if ('vibrate' in navigator) {
                navigator.vibrate([50, 30, 50]);
            }
        },
        
        success() {
            if ('vibrate' in navigator) {
                navigator.vibrate([10, 50, 10, 50, 10]);
            }
        },
        
        error() {
            if ('vibrate' in navigator) {
                navigator.vibrate([100, 50, 100]);
            }
        }
    };
    
    window.Haptic = Haptic;

    // =====================================================
    // 10. INITIALIZE ON DOM READY
    // =====================================================
    
    document.addEventListener('DOMContentLoaded', () => {
        CommandPalette.init();
        TiltEffect.init();
        RippleEffect.init();
        ProgressAnimator.init();
        
        console.log('[FAANG Ultimate] All premium modules initialized');
        console.log('[FAANG Ultimate] Press Ctrl+K for Command Palette');
    });

})();
