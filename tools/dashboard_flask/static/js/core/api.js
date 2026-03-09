/**
 * API Client
 * Centralized API calls with error handling
 */

export class ApiClient {
    constructor(baseUrl = '/api/v1') {
        this.baseUrl = baseUrl;
    }
    
    async get(endpoint) {
        return this.request('GET', endpoint);
    }
    
    async post(endpoint, data) {
        return this.request('POST', endpoint, data);
    }
    
    async put(endpoint, data) {
        return this.request('PUT', endpoint, data);
    }
    
    async delete(endpoint) {
        return this.request('DELETE', endpoint);
    }
    
    async request(method, endpoint, data = null) {
        const url = `${this.baseUrl}${endpoint}`;
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
        };
        
        if (data && (method === 'POST' || method === 'PUT')) {
            options.body = JSON.stringify(data);
        }
        
        try {
            const response = await fetch(url, options);
            
            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new ApiError(
                    error.message || `HTTP ${response.status}`,
                    response.status,
                    error
                );
            }
            
            return await response.json();
        } catch (error) {
            if (error instanceof ApiError) {
                throw error;
            }
            console.error(`[API] ${method} ${endpoint} failed:`, error);
            throw new ApiError('Network error', 0, { originalError: error });
        }
    }
    
    // Convenience methods for common endpoints
    
    async getPortfolio() {
        return this.get('/portfolio');
    }
    
    async getTrades() {
        return this.get('/trades');
    }
    
    async getOpenTrades() {
        return this.get('/trades/open');
    }
    
    async getClosedTrades() {
        return this.get('/trades/closed');
    }
    
    async getConfig() {
        return this.get('/config');
    }
    
    async getHeartbeat() {
        return this.get('/heartbeat');
    }
    
    async getPrices() {
        return this.get('/prices');
    }
    
    async getPrice(market) {
        return this.get(`/prices/${market}`);
    }
    
    async getDeposits() {
        return this.get('/deposits');
    }
    
    async getAiSuggestions() {
        return this.get('/ai/suggestions');
    }
    
    async invalidateCache(key = null) {
        return this.post('/cache/invalidate', { key });
    }
}

class ApiError extends Error {
    constructor(message, status, data) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.data = data;
    }
}

// Singleton instance
export const api = new ApiClient();
