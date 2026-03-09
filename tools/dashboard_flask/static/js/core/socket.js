/**
 * WebSocket Connection Manager
 * Handles real-time price updates and status
 */

export class SocketManager {
    constructor() {
        this.socket = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnects = 10;
        this.callbacks = new Map();
        this.priceUpdateQueue = [];
        this.rafScheduled = false;
    }
    
    connect() {
        if (typeof io === 'undefined') {
            console.error('[Socket] Socket.IO not loaded');
            return;
        }
        
        this.socket = io({
            reconnection: true,
            reconnectionAttempts: this.maxReconnects,
            reconnectionDelay: 2000,
            reconnectionDelayMax: 10000,
        });
        
        this.socket.on('connect', () => this.handleConnect());
        this.socket.on('disconnect', (reason) => this.handleDisconnect(reason));
        this.socket.on('price_update', (data) => this.handlePriceUpdate(data));
        this.socket.on('status_update', (data) => this.emit('status', data));
        this.socket.on('error', (error) => this.handleError(error));
        
        return this;
    }
    
    handleConnect() {
        this.connected = true;
        this.reconnectAttempts = 0;
        console.log('[Socket] Connected');
        this.emit('connection', { status: 'online' });
        this.updateConnectionUI(true);
        this.socket.emit('request_refresh');
    }
    
    handleDisconnect(reason) {
        this.connected = false;
        console.log('[Socket] Disconnected:', reason);
        this.emit('connection', { status: 'offline', reason });
        this.updateConnectionUI(false);
    }
    
    handlePriceUpdate(data) {
        // Queue updates and use RAF for batching
        this.priceUpdateQueue.push(data);
        
        if (!this.rafScheduled) {
            this.rafScheduled = true;
            requestAnimationFrame(() => {
                this.processPriceUpdates();
                this.rafScheduled = false;
            });
        }
    }
    
    processPriceUpdates() {
        if (this.priceUpdateQueue.length === 0) return;
        
        // Merge all queued updates
        const mergedPrices = {};
        for (const update of this.priceUpdateQueue) {
            if (update.prices) {
                Object.assign(mergedPrices, update.prices);
            }
        }
        
        // Clear queue
        this.priceUpdateQueue = [];
        
        // Emit merged update
        this.emit('prices', { prices: mergedPrices });
    }
    
    handleError(error) {
        console.error('[Socket] Error:', error);
        this.emit('error', error);
    }
    
    updateConnectionUI(connected) {
        const statusEl = document.getElementById('connection-status');
        const wsStatusEl = document.getElementById('ws-status-text');
        const wsDot = document.getElementById('ws-dot');
        
        if (statusEl) {
            statusEl.textContent = connected ? 'Live' : 'Offline';
            statusEl.className = `connection-status connection-status--${connected ? 'online' : 'offline'}`;
        }
        
        if (wsStatusEl) {
            wsStatusEl.textContent = connected ? 'Connected' : 'Disconnected';
        }
        
        if (wsDot) {
            wsDot.classList.toggle('active', connected);
            wsDot.classList.toggle('inactive', !connected);
        }
    }
    
    on(event, callback) {
        if (!this.callbacks.has(event)) {
            this.callbacks.set(event, []);
        }
        this.callbacks.get(event).push(callback);
        return this;
    }
    
    off(event, callback) {
        if (this.callbacks.has(event)) {
            const callbacks = this.callbacks.get(event);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        }
        return this;
    }
    
    emit(event, data) {
        const handlers = this.callbacks.get(event) || [];
        handlers.forEach(fn => {
            try {
                fn(data);
            } catch (error) {
                console.error(`[Socket] Error in ${event} handler:`, error);
            }
        });
    }
    
    requestRefresh() {
        if (this.connected && this.socket) {
            this.socket.emit('request_refresh');
        }
    }
    
    disconnect() {
        if (this.socket) {
            this.socket.disconnect();
        }
    }
}

// Singleton instance
export const socketManager = new SocketManager();

// Auto-connect on module load if in browser
if (typeof window !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        socketManager.connect();
    });
}
