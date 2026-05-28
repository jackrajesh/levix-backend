/**
 * LEVIX CORE SYSTEMS (Tier 1 Production Core)
 * Stabilized real-time state, events, and rendering layer.
 */

// ════════════════════════════════════════════════════════════
// 1. LEVIX EVENT BUS (Centralized & Clean Subscriptions)
// ════════════════════════════════════════════════════════════
class LevixEventBus {
    constructor() {
        this.listeners = new Map();
    }

    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, new Set());
        }
        this.listeners.get(event).add(callback);
    }

    off(event, callback) {
        if (!this.listeners.has(event)) return;
        const set = this.listeners.get(event);
        set.delete(callback);
        if (set.size === 0) {
            this.listeners.delete(event);
        }
    }

    emit(event, data) {
        if (!this.listeners.has(event)) return;
        this.listeners.get(event).forEach(callback => {
            try {
                callback(data);
            } catch (err) {
                console.error(`[EventBus] Error in listener for "${event}":`, err);
            }
        });
    }

    clear() {
        this.listeners.clear();
        console.log("[EventBus] All listeners purged successfully.");
    }
}

window.LevixEventBus = new LevixEventBus();

// ════════════════════════════════════════════════════════════
// 2. LEVIX STATE STORE (Centralized Store, Version Verification & Safety Capping)
// ════════════════════════════════════════════════════════════
class LevixStateStore {
    constructor() {
        this.inbox = [];
        this.orders = [];
        this.inventory = [];
        this.sales = [];
        this.analytics = {};
        this.versions = {}; // entity_id -> version number
        
        // Memory boundary thresholds
        this.MAX_INBOX_SIZE = 100; 
        this.DEDUP_WINDOW_MS = 5000;
        this.processedEventIds = new Set();
    }

    loadFromSessionStorage() {
        const tabs = ['inbox', 'orders', 'inventory', 'sales', 'analytics'];
        tabs.forEach(tab => {
            const cached = sessionStorage.getItem(`levix_cache_${tab}`);
            if (cached) {
                try {
                    this[tab] = JSON.parse(cached);
                } catch (e) {
                    console.error(`[StateStore] Failed to restore sessionStorage for "${tab}":`, e);
                }
            }
        });
        console.log("[StateStore] State loaded from Cache.");
    }

    saveToSessionStorage(tab) {
        try {
            sessionStorage.setItem(`levix_cache_${tab}`, JSON.stringify(this[tab]));
        } catch (e) {
            console.error(`[StateStore] Failed to save sessionStorage for "${tab}":`, e);
        }
    }

    // Duplicate event verification
    isDuplicateEvent(eventId) {
        if (!eventId) return false;
        if (this.processedEventIds.has(eventId)) {
            console.warn(`[StateStore] Duplicate event rejected: ${eventId}`);
            return true;
        }
        this.processedEventIds.add(eventId);
        setTimeout(() => this.processedEventIds.delete(eventId), this.DEDUP_WINDOW_MS);
        return false;
    }

    patchEntity(type, id, updates, serverVersion = null) {
        console.log(`[StateStore] Patching ${type} ${id}:`, updates);
        const list = this[type];
        if (!list) return;

        const index = list.findIndex(item => item.id === id || (type === 'orders' && item.booking_id === id));
        if (index !== -1) {
            const currentItem = list[index];
            const currentVersion = currentItem.version || 0;
            
            // Stale update rejection (server version verification)
            if (serverVersion !== null && serverVersion < currentVersion) {
                console.warn(`[StateStore] Stale update rejected for ${type} ${id}. Local: ${currentVersion}, Server: ${serverVersion}`);
                return;
            }
            
            const newVersion = serverVersion !== null ? serverVersion : currentVersion + 1;
            const oldStatus = currentItem.status;
            
            Object.assign(currentItem, updates, { 
                version: newVersion, 
                updated_at: new Date().toISOString() 
            });
            
            this.saveToSessionStorage(type);
            window.LevixEventBus.emit(`entity_updated:${type}`, currentItem);
            
            // Safe DOM micro-patching on status change
            if (updates.status && updates.status !== oldStatus) {
                this.updateDOMEntity(type, currentItem);
            }
        } else {
            console.warn(`[StateStore] Entity not found for patch: ${type} ${id}`);
        }
    }

    updateDOMEntity(type, entity) {
        if (type === 'orders') {
            const card = document.getElementById(`order-card-${entity.id}`);
            if (card) {
                console.log(`[StateStore] Dynamic DOM micro-patching order-card-${entity.id}`);
                const badge = card.querySelector('[class^="status-badge-"]');
                if (badge) {
                    badge.className = `status-badge-${entity.status.toLowerCase()}`;
                    badge.textContent = entity.status;
                    
                    const statusLower = entity.status.toLowerCase();
                    if (statusLower === 'pending') {
                        badge.style.background = '#fef3c7'; badge.style.color = '#92400e';
                    } else if (statusLower === 'accepted' || statusLower === 'confirmed') {
                        badge.style.background = '#dcfce7'; badge.style.color = '#15803d';
                    } else if (statusLower === 'completed' || statusLower === 'delivered') {
                        badge.style.background = '#eff6ff'; badge.style.color = '#1d4ed8';
                    } else if (statusLower === 'rejected' || statusLower === 'cancelled') {
                        badge.style.background = '#fee2e2'; badge.style.color = '#b91c1c';
                    }
                }
                
                const footer = card.querySelector('div[style*="background:#f8fafc"]');
                if (footer) {
                    const statusLower = entity.status.toLowerCase();
                    if (statusLower === 'pending') {
                        footer.innerHTML = (typeof hasPerm === 'function' && hasPerm('orders_edit')) ? `
                            <button class="btn" style="flex:1" onclick="updateOrderStatus('${entity.booking_id}', 'accept')">ACCEPT</button>
                            <button class="btn btn-outline" style="border-color:#fee2e2; color:#ef4444" onclick="updateOrderStatus('${entity.booking_id}', 'reject')">REJECT</button>
                        ` : `<div style="flex:1; text-align:center; font-size:0.85rem; color:var(--text-muted); font-weight:600">Awaiting Store Response</div>`;
                    } else if (statusLower === 'accepted' || statusLower === 'confirmed') {
                        footer.innerHTML = (typeof hasPerm === 'function' && hasPerm('orders_edit')) ? `
                             <button class="btn btn-success" style="flex:1" onclick="updateOrderStatus('${entity.booking_id}', 'complete')">MARK COMPLETED</button>
                        ` : `<div style="flex:1; text-align:center; font-size:0.85rem; color:var(--text-muted); font-weight:600">Order Accepted</div>`;
                    } else if (statusLower === 'rejected' || statusLower === 'cancelled') {
                        footer.innerHTML = `<div style="flex:1; text-align:center; font-size:0.85rem; color:var(--text-muted); font-weight:600">Order Rejected</div>`;
                    } else {
                        footer.innerHTML = `<div style="flex:1; text-align:center; font-size:0.85rem; color:var(--text-muted); font-weight:600">Transaction Completed</div>`;
                    }
                }
            }
        }
    }
}

window.LevixStateStore = new LevixStateStore();
window.LevixStateStore.loadFromSessionStorage();

// Backward compatibility bindings
window.LevixState = window.LevixStateStore;

// ════════════════════════════════════════════════════════════
// 3. RENDER PIPELINE & targeted renderers (RenderGuard)
// ════════════════════════════════════════════════════════════
class RenderPipeline {
    constructor() {
        this.scheduledRenders = new Set();
        this.lastRenderTime = new Map();
        this.THROTTLE_MS = 100;
    }

    queue(tabName) {
        if (this.scheduledRenders.has(tabName)) return;

        // RenderGuard: prevent thrashes
        const now = Date.now();
        const lastTime = this.lastRenderTime.get(tabName) || 0;
        if (now - lastTime < this.THROTTLE_MS) {
            setTimeout(() => this.queue(tabName), this.THROTTLE_MS - (now - lastTime));
            return;
        }

        this.scheduledRenders.add(tabName);
        window.requestAnimationFrame(() => {
            this.scheduledRenders.delete(tabName);
            this.lastRenderTime.set(tabName, Date.now());
            console.log(`[RenderPipeline] Executing targeted render for tab: ${tabName}`);
            this.renderTab(tabName);
        });
    }

    renderTab(tabName) {
        if (tabName === 'orders' && window.currentTab === 'orders') {
            if (typeof filterOrders === 'function') filterOrders();
        } else if (tabName === 'inventory' && window.currentTab === 'inventory') {
            if (typeof filterInventory === 'function') filterInventory();
        } else if (tabName === 'inbox' && window.currentTab === 'inbox') {
            if (typeof fetchInbox === 'function') fetchInbox(true);
        } else if (tabName === 'sales' && window.currentTab === 'sales') {
            if (typeof fetchSales === 'function') fetchSales();
        }
    }
}

window.RenderPipeline = new RenderPipeline();
window.RenderQueue = window.RenderPipeline; // Backward compatibility

// ════════════════════════════════════════════════════════════
// 4. REALTIME LIFECYCLE MANAGER (SSE Reconnect Safety, Network degraded mode)
// ════════════════════════════════════════════════════════════
class RealtimeLifecycleManager {
    constructor() {
        this.source = null;
        this.isLive = false;
        this.connecting = false;
        this.fallbackTimer = null;
        this.reconnectTimer = null;
        this.connectionTimer = null;
        this.watchdogTimer = null;
        this.reconnectCount = 0;
    }

    resetWatchdog() {
        if (this.watchdogTimer) clearTimeout(this.watchdogTimer);
        if (this.connectionTimer) { clearTimeout(this.connectionTimer); this.connectionTimer = null; }
        
        // Pings from backend are every 30s. If we miss 45s => connection dead.
        this.watchdogTimer = setTimeout(() => {
            console.warn("🚨 [SSE Watchdog] Connection died silently! Forcing reconnect.");
            this.handleDisconnect();
        }, 45000);
    }

    init() {
        this.connect();
        console.log("[Realtime] Lifecycle Manager Initialized");
    }

    setStatus(status) {
        const dots = document.querySelectorAll('.live-dot');
        const texts = document.querySelectorAll('.live-text');
        const overlay = document.getElementById('reconnect-overlay');
        
        if (status === 'live') {
            dots.forEach(dot => dot.style.background = 'var(--accent-yes)');
            texts.forEach(text => {
                text.textContent = 'LIVE';
                text.style.color = 'var(--accent-yes)';
            });
            this.isLive = true;
            this.reconnectCount = 0;
            if (this.fallbackTimer) { clearInterval(this.fallbackTimer); this.fallbackTimer = null; }
            if (overlay) overlay.style.display = 'none'; // Hide non-blocking indicator
            this.resetWatchdog();
        } else {
            dots.forEach(dot => dot.style.background = '#ef4444');
            const label = status === 'reconnecting' ? 'RECONNECTING...' : 'OFFLINE';
            texts.forEach(text => {
                text.textContent = label;
                text.style.color = '#ef4444';
            });
            this.isLive = false;
            if (this.watchdogTimer) { clearTimeout(this.watchdogTimer); this.watchdogTimer = null; }
            
            // Show premium non-blocking indicator if element is in DOM
            if (overlay) {
                overlay.style.display = 'flex';
            }
            this.startFallbackPolling();
        }
    }

    connect() {
        if (this.connecting) {
            console.log("[Realtime] Connection already in progress. Skipping.");
            return;
        }
        this.connecting = true;

        this.closeConnection();
        
        const token = localStorage.getItem('token');
        if (!token) {
            console.warn("[Realtime] No auth token found. Skipping connection.");
            this.connecting = false;
            this.setStatus('offline');
            return;
        }
        
        console.log("[Realtime] Connecting EventSource...");
        
        // Strict 15s handshake timeout
        this.connectionTimer = setTimeout(() => {
            if (!this.isLive) {
                console.warn("🚨 [Realtime] Handshake timed out! Forcing reconnect.");
                this.handleDisconnect();
            }
        }, 15000);

        try {
            this.source = new EventSource(`/events?token=${encodeURIComponent(token)}`);
            
            this.source.onopen = () => {
                console.log("[Realtime] Connection opened successfully.");
                this.connecting = false;
                this.setStatus('live');
            };

            this.source.onerror = (err) => {
                console.error("[Realtime] EventSource error:", err);
                this.connecting = false;
                this.handleDisconnect();
            };

            // Register stable listeners
            this.source.addEventListener('connected', (e) => {
                console.log("[Realtime] Server confirmed connected");
                this.resetWatchdog();
            });

            this.source.addEventListener('ping', () => {
                this.resetWatchdog();
            });

            this.source.addEventListener('hard_reload', () => {
                console.log("[Realtime] Hard Reload Triggered");
                location.reload();
            });

            this.source.addEventListener('pending_created', (e) => {
                if (window.LevixStateStore.isDuplicateEvent(e.lastEventId)) return;
                console.log("[Realtime] pending_created");
                this.resetWatchdog();
                this.onMessageReceived();
                if (window.currentTab === 'analytics' && typeof fetchAnalytics === 'function') fetchAnalytics();
            });

            this.source.addEventListener('pending_updated', (e) => {
                if (window.LevixStateStore.isDuplicateEvent(e.lastEventId)) return;
                console.log("[Realtime] pending_updated");
                this.resetWatchdog();
                if (typeof fetchInbox === 'function') fetchInbox(true);
                if (typeof fetchBadgeCounts === 'function') fetchBadgeCounts();
                if (window.currentTab === 'analytics' && typeof fetchAnalytics === 'function') fetchAnalytics();
            });

            this.source.addEventListener('conversation_updated', (e) => {
                if (window.LevixStateStore.isDuplicateEvent(e.lastEventId)) return;
                console.log("[Realtime] conversation_updated");
                this.resetWatchdog();
                sessionStorage.removeItem('levix_cache_inbox');
                if (typeof fetchInbox === 'function') fetchInbox(true);
                if (typeof fetchBadgeCounts === 'function') fetchBadgeCounts();
                if (window.activeConversationId && typeof fetchConversationMessages === 'function') {
                    fetchConversationMessages(window.activeConversationId);
                }
            });

            this.source.addEventListener('new_order', (e) => {
                if (window.LevixStateStore.isDuplicateEvent(e.lastEventId)) return;
                console.log("[Realtime] new_order");
                this.resetWatchdog();
                this.onOrderReceived(e.data);
                if (window.currentTab === 'analytics' && typeof fetchAnalytics === 'function') fetchAnalytics();
            });

            this.source.addEventListener('order_updated', (e) => {
                if (window.LevixStateStore.isDuplicateEvent(e.lastEventId)) return;
                console.log("[Realtime] order_updated");
                this.resetWatchdog();
                try {
                    const payload = JSON.parse(e.data);
                    if (payload && payload.booking_id) {
                        window.LevixStateStore.patchEntity('orders', payload.booking_id, { status: payload.status }, payload.version);
                    } else {
                        window.RenderPipeline.queue('orders');
                    }
                } catch (err) {
                    window.RenderPipeline.queue('orders');
                }
                if (typeof fetchBadgeCounts === 'function') fetchBadgeCounts();
                if (window.currentTab === 'analytics' && typeof fetchAnalytics === 'function') fetchAnalytics();
            });

        } catch (e) {
            console.error("[Realtime] Failed to initialize EventSource:", e);
            this.connecting = false;
            this.handleDisconnect();
        }
    }

    closeConnection() {
        if (this.source) {
            this.source.close();
            this.source = null;
        }
        if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
        if (this.connectionTimer) { clearTimeout(this.connectionTimer); this.connectionTimer = null; }
        if (this.watchdogTimer) { clearTimeout(this.watchdogTimer); this.watchdogTimer = null; }
    }

    handleDisconnect() {
        this.closeConnection();
        this.setStatus('reconnecting');
        
        // Exponential backoff reconnect
        const nextRetry = Math.min(30000, 5000 * Math.pow(1.5, this.reconnectCount++));
        console.log(`[Realtime] Attempting reconnect in ${nextRetry/1000}s...`);
        this.reconnectTimer = setTimeout(() => {
            if (!this.isLive) this.connect();
        }, nextRetry);
    }

    startFallbackPolling() {
        if (this.fallbackTimer) return;
        console.warn("[Realtime] Network degraded mode active: Slow polling fallback enabled.");
        this.fallbackTimer = setInterval(() => {
            if (!this.isLive) {
                if (typeof fetchBadgeCounts === 'function') fetchBadgeCounts();
                window.RenderPipeline.queue(window.currentTab);
            }
        }, 30000); // 30s slow fallback
    }

    onMessageReceived(playSound = true) {
        if (playSound && typeof LevixAudio !== 'undefined') {
            LevixAudio.play('notification');
            showToast('New customer inquiry received', 'success');
        }
        if (typeof fetchBadgeCounts === 'function') fetchBadgeCounts();
        window.RenderPipeline.queue('inbox');
    }

    onOrderReceived(data) {
        if (typeof LevixAudio !== 'undefined') LevixAudio.play('notification');
        if (typeof fetchBadgeCounts === 'function') fetchBadgeCounts();
        const order = data ? JSON.parse(data) : null;
        if (order) showToast(`New Order from ${order.customer || 'Customer'}!`, 'success');
        window.RenderPipeline.queue('orders');
    }
}

window.LevixSmartRefresh = new RealtimeLifecycleManager();
window.sseManager = window.LevixSmartRefresh;
