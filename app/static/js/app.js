// Stock Talk - Main JavaScript

// Utility functions
const utils = {
    formatCurrency(value, decimals = 2) {
        if (value === null || value === undefined) return 'N/A';
        return '$' + value.toFixed(decimals);
    },

    formatPercent(value, decimals = 1) {
        if (value === null || value === undefined) return 'N/A';
        const sign = value > 0 ? '+' : '';
        return sign + value.toFixed(decimals) + '%';
    },

    formatNumber(value, decimals = 2) {
        if (value === null || value === undefined) return 'N/A';
        return value.toFixed(decimals);
    },

    formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    },

    formatShortDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric'
        });
    },

    getSignalClass(value, thresholds) {
        if (value === null || value === undefined) return '';
        if (thresholds.bullish && value < thresholds.bullish) return 'text-green-400';
        if (thresholds.bearish && value > thresholds.bearish) return 'text-red-400';
        return '';
    }
};

// API helper
const api = {
    async get(endpoint) {
        const response = await fetch(`/api${endpoint}`);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    },

    async post(endpoint, data) {
        const response = await fetch(`/api${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    }
};

// Make utilities available globally
window.utils = utils;
window.api = api;

// Dark mode toggle (already dark by default)
document.addEventListener('DOMContentLoaded', () => {
    // Initialize any global listeners

    // Handle keyboard navigation for search
    document.addEventListener('keydown', (e) => {
        // Cmd/Ctrl + K to focus search
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            const searchInput = document.querySelector('input[placeholder="Search stocks..."]');
            if (searchInput) {
                searchInput.focus();
            }
        }
    });
});

// Service worker registration for offline support (optional future enhancement)
if ('serviceWorker' in navigator) {
    // Uncomment to enable service worker
    // navigator.serviceWorker.register('/static/js/sw.js');
}
