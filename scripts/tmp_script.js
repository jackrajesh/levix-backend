
        let currentTab = 'inbox';
        let allOrders = [];
        let allInventory = [];
        let invInsights = [];

        // ===== LEVIX Premium Audio Engine (Smooth-Comfort Edition) =====
        const LevixAudio = {
            ctx: null,
            isMuted: localStorage.getItem('levix_mute_sounds') === 'true',
            
            init() {
                if (!this.ctx) {
                    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
                }
            },

            play(type) {
                if (this.isMuted) return;
                this.init();
                if (this.ctx.state === 'suspended') this.ctx.resume();

                const now = this.ctx.currentTime;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();

                osc.connect(gain);
                gain.connect(this.ctx.destination);

                switch(type) {
                    case 'success':
                        osc.type = 'sine';
                        osc.frequency.setValueAtTime(329.63, now); // E4 (Warm)
                        osc.frequency.exponentialRampToValueAtTime(523.25, now + 0.2); // C5
                        gain.gain.setValueAtTime(0, now);
                        gain.gain.linearRampToValueAtTime(0.12, now + 0.05);
                        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
                        osc.start(now);
                        osc.stop(now + 0.4);
                        break;
                    case 'save':
                        osc.type = 'sine';
                        osc.frequency.setValueAtTime(392.00, now); // G4
                        osc.frequency.exponentialRampToValueAtTime(440.00, now + 0.3); // A4
                        gain.gain.setValueAtTime(0, now);
                        gain.gain.linearRampToValueAtTime(0.15, now + 0.08);
                        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
                        osc.start(now);
                        osc.stop(now + 0.6);
                        break;
                    case 'notification': 
                        const osc2 = this.ctx.createOscillator();
                        const gain2 = this.ctx.createGain();
                        osc2.connect(gain2); gain2.connect(this.ctx.destination);
                        osc.type = 'sine'; osc2.type = 'sine';
                        osc.frequency.setValueAtTime(349.23, now); // F4
                        osc2.frequency.setValueAtTime(440.00, now + 0.1); // A4
                        gain.gain.setValueAtTime(0, now);
                        gain.gain.linearRampToValueAtTime(0.14, now + 0.08);
                        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.8);
                        gain2.gain.setValueAtTime(0, now + 0.1);
                        gain2.gain.linearRampToValueAtTime(0.1, now + 0.18);
                        gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.8);
                        osc.start(now); osc.stop(now + 0.8);
                        osc2.start(now + 0.1); osc2.stop(now + 0.8);
                        break;
                    case 'delete':
                        osc.type = 'sine';
                        osc.frequency.setValueAtTime(220.00, now); // A3
                        osc.frequency.linearRampToValueAtTime(164.81, now + 0.3); // E3
                        gain.gain.setValueAtTime(0, now);
                        gain.gain.linearRampToValueAtTime(0.15, now + 0.05);
                        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
                        osc.start(now);
                        osc.stop(now + 0.5);
                        break;
                    case 'error': 
                        osc.type = 'triangle';
                        osc.frequency.setValueAtTime(196.00, now); // G3
                        osc.frequency.setValueAtTime(174.61, now + 0.1); // F3
                        gain.gain.setValueAtTime(0, now);
                        gain.gain.linearRampToValueAtTime(0.2, now + 0.05);
                        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
                        osc.start(now);
                        osc.stop(now + 0.6);
                        break;
                }
            },

            toggleMute() {
                this.isMuted = !this.isMuted;
                localStorage.setItem('levix_mute_sounds', this.isMuted);
                return this.isMuted;
            }
        };

        // Initialize Audio context on first user interaction to satisfy browser policies
        document.addEventListener('click', () => LevixAudio.init(), { once: true });

        // Premium Number Counting Animation - Optimized
        const animationCache = {};
        function animateNumber(id, end, prefix = '', suffix = '', decimals = 0) {
            const el = document.getElementById(id);
            if (!el) return;
            
            // Skip animation if the value is already loaded and hasn't changed
            if (animationCache[id] === end) {
                el.textContent = `${prefix}${end.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`;
                return;
            }
            
            animationCache[id] = end;
            const duration = 1500;
            const start = 0;
            let startTime = null;

            const step = (timestamp) => {
                if (!startTime) startTime = timestamp;
                const progress = Math.min((timestamp - startTime) / duration, 1);
                const current = progress * (end - start) + start;
                
                el.textContent = `${prefix}${current.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`;
                
                if (progress < 1) {
                    window.requestAnimationFrame(step);
                } else {
                    el.textContent = `${prefix}${end.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`;
                }
            };
            window.requestAnimationFrame(step);
        }

        async function authFetch(url, options = {}) {
            const token = localStorage.getItem('token');
            if (!token) { window.location.href = '/'; return; }
            options.headers = { ...options.headers, 'Authorization': `Bearer ${token}` };
            if (options.body && typeof options.body === 'object') {
                options.body = JSON.stringify(options.body);
                options.headers['Content-Type'] = 'application/json';
            }
            const res = await fetch(url, options);
            if (res.status === 401) { logout(); return; }
            return res;
        }

        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('active');
            document.getElementById('sidebar-overlay').classList.toggle('active');
        }

        function logout() {
             showConfirm('Logout', 'Are you sure you want to sign out?', () => {
                localStorage.removeItem('token');
                window.location.href = '/login';
             });
        }

        function switchTab(id) {
            currentTab = id;
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            
            document.getElementById(`tab-content-${id}`).classList.add('active');
            const navBtn = document.getElementById(`tab-${id}`);
            if (navBtn) navBtn.classList.add('active');
            
            const mapping = {
                inbox: ['Inbox', 'Customer inquiries and message queue'],
                orders: ['Orders', 'Transaction and fulfillment management'],
                inventory: ['Inventory', 'Product stock and pricing control'],
                sales: ['Sales History', 'Complete record of completed transactions'],
                analytics: ['Analytics', 'Real-time performance metrics'],
                settings: ['Settings', 'Shop profile and integrations']
            };
            document.getElementById('tab-title').textContent = mapping[id][0];
            document.getElementById('tab-desc').textContent = mapping[id][1];
            
            if (window.innerWidth <= 1024) toggleSidebar();
            fetchTabData();
        }

        function fetchTabData() {
            if (currentTab === 'inbox') fetchInbox();
            if (currentTab === 'orders') fetchOrders();
            if (currentTab === 'inventory') fetchInventory();
            if (currentTab === 'sales') fetchSales();
            if (currentTab === 'analytics') fetchAnalytics();
            if (currentTab === 'settings') fetchSettings();
        }

        // --- PROFESSIONAL LIVE REFRESH SYSTEM (SSE + Fallback Polling) ---
        const LevixSmartRefresh = {
            source: null,
            isLive: false,
            fallbackTimer: null,
            reconnectCount: 0,
            
            init() {
                this.connect();
                console.log("Levix Smart Refresh Initialized");
            },

            setStatus(status) {
                const dot = document.getElementById('live-dot');
                const text = document.getElementById('live-text');
                if (status === 'live') {
                    dot.style.background = 'var(--accent-yes)';
                    text.textContent = 'LIVE';
                    text.style.color = 'var(--accent-yes)';
                    this.isLive = true;
                    if (this.fallbackTimer) { clearInterval(this.fallbackTimer); this.fallbackTimer = null; }
                } else {
                    dot.style.background = '#ef4444';
                    text.textContent = status === 'reconnecting' ? 'RECONNECTING...' : 'OFFLINE';
                    text.style.color = '#ef4444';
                    this.isLive = false;
                    this.startFallbackPolling();
                }
            },

            connect() {
                if (this.source) this.source.close();
                
                const token = localStorage.getItem('token');
                this.source = new EventSource(`/events?token=${token}`);
                
                this.source.onopen = () => {
                    this.setStatus('live');
                    this.reconnectCount = 0;
                };

                this.source.onerror = () => {
                    this.setStatus('reconnecting');
                    setTimeout(() => { if (!this.isLive) this.connect(); }, Math.min(10000, 2000 * Math.pow(2, this.reconnectCount++)));
                };

                this.source.addEventListener('pending_created', () => this.onMessageReceived());
                this.source.addEventListener('pending_updated', () => this.onMessageReceived(false));
                this.source.addEventListener('new_order', (e) => this.onOrderReceived(e.data));
                this.source.addEventListener('order_updated', () => this.refreshData('orders'));
            },

            startFallbackPolling() {
                if (this.fallbackTimer) return;
                console.warn("Switching to slow fallback polling...");
                this.fallbackTimer = setInterval(() => {
                    if (!this.isLive) {
                        fetchBadgeCounts();
                        fetchTabData();
                    }
                }, 30000); // 30s slow fallback
            },

            onMessageReceived(playSound = true) {
                if (playSound) LevixAudio.play('notification');
                fetchBadgeCounts();
                if (currentTab === 'inbox') fetchInbox(true); // true = animate new
            },

            onOrderReceived(data) {
                LevixAudio.play('notification');
                fetchBadgeCounts();
                const order = data ? JSON.parse(data) : null;
                if (order) showToast(`New Order from ${order.customer || 'Customer'}!`, 'success');
                if (currentTab === 'orders') fetchOrders(true);
            },

            refreshData(tab) {
                fetchBadgeCounts();
                if (currentTab === tab) fetchTabData();
            }
        };

        // Initialize Live System
        // Moved to DOMContentLoaded for stability

        async function fetchBadgeCounts() {
            try {
                const res = await authFetch('/dashboard/counts');
                const counts = await res.json();
                const bInbox = document.getElementById('badge-inbox');
                const bOrders = document.getElementById('badge-orders');
                
                if (counts.inbox > 0) { bInbox.textContent = counts.inbox; bInbox.style.display = 'flex'; }
                else bInbox.style.display = 'none';

                if (counts.orders > 0) { bOrders.textContent = counts.orders; bOrders.style.display = 'flex'; }
                else bOrders.style.display = 'none';
            } catch(e) {}
        }

        function renderInboxSkeleton() {
            const list = document.getElementById('inbox-list');
            list.innerHTML = Array(3).fill(0).map(() => `
                <div class="skeleton-card" style="margin-bottom: var(--sp-md); display:flex; justify-content:space-between; align-items:center">
                    <div style="flex:1">
                        <div class="skeleton skeleton-title"></div>
                        <div class="skeleton skeleton-text" style="width: 80%"></div>
                        <div class="skeleton skeleton-text" style="width: 40%; height: 10px"></div>
                    </div>
                    <div style="display:flex; gap:12px">
                        <div class="skeleton" style="width:100px; height:36px; border-radius: var(--radius-md)"></div>
                        <div class="skeleton" style="width:100px; height:36px; border-radius: var(--radius-md)"></div>
                    </div>
                </div>
            `).join('');
        }

        function renderOrdersSkeleton() {
            const grid = document.getElementById('orders-grid');
            grid.innerHTML = Array(4).fill(0).map(() => `
                <div class="skeleton-card" style="height: 300px">
                    <div style="display:flex; justify-content:space-between; margin-bottom: 24px">
                        <div class="skeleton" style="width:120px; height:24px"></div>
                        <div class="skeleton" style="width:80px; height:24px; border-radius:99px"></div>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom: 24px">
                        <div>
                            <div class="skeleton skeleton-text" style="width:40%"></div>
                            <div class="skeleton skeleton-text"></div>
                            <div class="skeleton skeleton-text" style="width:70%"></div>
                        </div>
                        <div>
                            <div class="skeleton skeleton-text" style="width:40%"></div>
                            <div class="skeleton skeleton-text"></div>
                            <div class="skeleton" style="width:60px; height:24px; margin-top:8px"></div>
                        </div>
                    </div>
                    <div class="skeleton" style="width:100%; height:48px; border-radius: var(--radius-md)"></div>
                </div>
            `).join('');
        }

        function renderInventorySkeleton() {
            const list = document.getElementById('inventory-list');
            list.innerHTML = Array(5).fill(0).map(() => `
                <div class="skeleton-card" style="display:grid; grid-template-columns: 2fr 1.5fr 1fr; align-items: center; gap: var(--sp-lg); margin-bottom: var(--sp-md)">
                    <div style="display:flex; align-items:center; gap:16px">
                        <div class="skeleton" style="width:20px; height:20px; border-radius:4px"></div>
                        <div style="flex:1">
                            <div class="skeleton skeleton-title" style="width:70%"></div>
                            <div class="skeleton skeleton-text" style="width:40%"></div>
                        </div>
                    </div>
                    <div>
                        <div class="skeleton skeleton-title" style="width:50%; margin-bottom:4px"></div>
                        <div class="skeleton skeleton-text" style="width:30%"></div>
                    </div>
                    <div style="display:flex; gap:12px">
                        <div class="skeleton" style="width:80px; height:32px"></div>
                        <div class="skeleton" style="width:80px; height:32px"></div>
                    </div>
                </div>
            `).join('');
        }

        function renderSalesSkeleton() {
            const body = document.getElementById('sales-table-body');
            body.innerHTML = Array(5).fill(0).map(() => `
                <tr>
                    <td style="padding:16px"><div class="skeleton skeleton-text" style="width:80%"></div></td>
                    <td style="padding:16px"><div class="skeleton skeleton-text" style="width:60%"></div></td>
                    <td style="padding:16px"><div class="skeleton skeleton-text" style="width:40%"></div></td>
                    <td style="padding:16px"><div class="skeleton skeleton-text" style="width:50%"></div></td>
                    <td style="padding:16px"><div class="skeleton skeleton-text" style="width:70%"></div></td>
                    <td style="padding:16px"><div class="skeleton" style="width:60px; height:24px"></div></td>
                </tr>
            `).join('');
        }

        function renderAnalyticsSkeleton() {
            const summary = document.getElementById('analytics-summary');
            // Only show skeleton for summary if it's currently empty or has skeletons already
            if (summary.innerHTML.trim() === '' || summary.querySelector('.skeleton-card')) {
                summary.innerHTML = Array(4).fill(0).map(() => `
                    <div class="skeleton-card">
                        <div class="skeleton skeleton-text" style="width:40%"></div>
                        <div class="skeleton skeleton-title" style="width:70%; margin-bottom:0"></div>
                    </div>
                `).join('');
            }

            const lists = ['analytics-demand-list', 'analytics-sales-list', 'analytics-customers-list', 'analytics-stock-list'];
            lists.forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    el.innerHTML = Array(4).fill(0).map(() => `
                        <div style="display:flex; justify-content:space-between; padding:12px 0; border-bottom:1px solid #f8fafc">
                            <div class="skeleton skeleton-text" style="width:50%; margin:0"></div>
                            <div class="skeleton skeleton-text" style="width:20%; margin:0"></div>
                        </div>
                    `).join('');
                }
            });
        }

        let lastInboxIds = [];
        async function fetchInbox(shouldAnimate = false) {
            const list = document.getElementById('inbox-list');
            if (!shouldAnimate) renderInboxSkeleton();
            const res = await authFetch('/pending');
            const data = await res.json();
            
            if (!data || data.length === 0) {
                list.style.display = 'none';
                document.getElementById('inbox-empty').style.display = 'block';
                lastInboxIds = [];
                return;
            }
            list.style.display = 'flex';
            document.getElementById('inbox-empty').style.display = 'none';
            
            const newIds = data.map(item => item.id).filter(id => !lastInboxIds.includes(id));
            
            list.innerHTML = data.map(item => {
                const isNew = shouldAnimate && newIds.includes(item.id);
                return `
                <div class="inbox-card ${isNew ? 'slide-in highlight-new' : ''}" style="padding:20px; display:flex; justify-content:space-between; align-items:center; margin-bottom:12px">
                    <div style="display:flex; align-items:center; gap:16px">
                        <input type="checkbox" class="inbox-checkbox" data-id="${item.id}" onchange="updateInboxSelection()" style="width:20px; height:20px">
                        <div>
                            <div style="font-weight:800; font-size:1.1rem; color:var(--accent)">${item.product}</div>
                            <p style="font-size:0.9rem; margin: 4px 0">${item.customer_message || 'Inquiry for ' + item.product}</p>
                            <span style="font-size:0.75rem; color:var(--text-muted)">${new Date(item.created_at).toLocaleString()}</span>
                        </div>
                    </div>
                    <div style="display:flex; gap:12px">
                        <button class="btn" style="padding:8px 16px; background:var(--primary); color:white" onclick="openInboxAddModal('${item.product}', ${item.id})">ADD TO INVENTORY</button>
                        <button class="btn btn-danger btn-outline" style="padding:8px 16px" onclick="rejectInbox(${item.id})">REJECT</button>
                    </div>
                </div>
            `}).join('');
            lastInboxIds = data.map(item => item.id);
        }

        function updateInboxSelection() {
            const count = document.querySelectorAll('.inbox-checkbox:checked').length;
            document.getElementById('inbox-bulk-bar').style.display = count > 0 ? 'flex' : 'none';
            document.getElementById('inbox-selected-count').textContent = `${count} Requests Selected`;
        }
        function toggleSelectAllInbox(c) { document.querySelectorAll('.inbox-checkbox').forEach(cb => cb.checked = c); updateInboxSelection(); }

        async function bulkDeleteInbox() {
            const ids = [...document.querySelectorAll('.inbox-checkbox:checked')].map(cb => parseInt(cb.dataset.id));
            showConfirm('Delete Requests', `Delete ${ids.length} inquiries from inbox?`, async () => {
                await authFetch('/pending/bulk-delete', { method: 'POST', body: { ids } });
                LevixAudio.play('delete');
                fetchInbox();
                updateInboxSelection();
                fetchBadgeCounts();
            });
        }

        async function rejectInbox(id) {
            showConfirm('Reject Inquiry', 'Remove this inquiry from your inbox?', async () => {
                await authFetch('/pending/bulk-delete', { method: 'POST', body: { ids: [id] } });
                LevixAudio.play('delete');
                fetchInbox();
                fetchBadgeCounts();
            });
        }

        function openInboxAddModal(name, requestId) {
            document.getElementById('add-p-name').value = name;
            // Record which ID we're converting so we can delete it on success
            window.activeInboxRequestId = requestId;
            openModal('modal-add-product');
        }

        function openAddModal() {
            window.activeInboxRequestId = null;
            document.getElementById('add-p-name').value = '';
            openModal('modal-add-product');
        }

        async function resolveInbox(id, type) {
            const res = await authFetch(type === 'stock' ? `/yes/${id}` : `/no/${id}`, { method: 'POST' });
            if (res.ok) { showToast('Response sent to customer', 'success'); fetchInbox(); fetchBadgeCounts(); }
        }

        // Tab Logic: Orders
        let lastOrderIds = [];
        async function fetchOrders(shouldAnimate = false) {
            if (!shouldAnimate) renderOrdersSkeleton();
            const status = document.getElementById('filter-order-status').value;
            const res = await authFetch(`/orders?status=${status}`);
            allOrders = await res.json();
            filterOrders(shouldAnimate);
        }

        function filterOrders(shouldAnimate = false) {
            const q = document.getElementById('order-search').value.toLowerCase();
            const sort = document.getElementById('sort-orders').value;
            
            let filtered = allOrders.filter(o => 
                o.order_id.toLowerCase().includes(q) || 
                o.customer_name.toLowerCase().includes(q) || 
                o.phone.toLowerCase().includes(q)
            );
            
            if (sort === 'oldest') filtered.sort((a,b) => new Date(a.created_at) - new Date(b.created_at));
            else filtered.sort((a,b) => new Date(b.created_at) - new Date(a.created_at));
            
            renderOrders(filtered, shouldAnimate);
        }

        function renderOrders(items, shouldAnimate = false) {
            const grid = document.getElementById('orders-grid');
            if (items.length === 0) { grid.innerHTML = '<div style="grid-column:1/-1; padding:40px; text-align:center; color:var(--text-muted)">No matching orders.</div>'; lastOrderIds = []; return; }
            
            const newIds = items.map(o => o.id).filter(id => !lastOrderIds.includes(id));

            grid.innerHTML = items.map(o => {
                const isNew = shouldAnimate && newIds.includes(o.id);
                return `
                <div class="order-card ${isNew ? 'slide-in highlight-new' : ''}" style="padding:0">
                    <div style="padding:20px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; align-items:flex-start">
                        <div style="display:flex; gap:12px; align-items:center">
                            <input type="checkbox" class="order-checkbox" data-id="${o.id}" onchange="updateOrderSelection()" style="width:18px; height:18px">
                            <div>
                                <h4 style="font-weight:800; font-size:1.1rem">#${o.order_id}</h4>
                                <span style="font-size:0.7rem; color:var(--text-muted); font-weight:600">BOOKING ID: ${o.booking_id}</span>
                            </div>
                        </div>
                        <div style="text-align:right">
                            <div style="padding:4px 12px; border-radius:99px; font-size:0.7rem; font-weight:800; text-transform:uppercase" class="status-badge-${o.status}">
                                ${o.status}
                            </div>
                            <span style="font-size:0.75rem; color:var(--text-muted); display:block; margin-top:4px">${new Date(o.created_at).toLocaleDateString()}</span>
                        </div>
                    </div>
                    <div style="padding:24px; display:grid; grid-template-columns:1fr 1fr; gap:20px">
                        <div>
                            <label class="form-label">CUSTOMER</label>
                            <p style="font-weight:800">${o.customer_name}</p>
                            <p style="font-size:0.85rem; color:var(--text-muted)">📞 ${o.phone}</p>
                            <p style="font-size:0.85rem; color:var(--text-muted)">📍 ${o.address}</p>
                        </div>
                        <div>
                            <label class="form-label">REQUEST</label>
                            <p style="font-weight:800; color:var(--accent)">${o.product}</p>
                            <span style="display:inline-block; padding:2px 8px; background:var(--primary); color:white; border-radius:6px; font-size:0.75rem; font-weight:800">x ${o.quantity}</span>
                            <div style="margin-top:16px">
                                <span style="font-size:0.7rem; color:var(--text-muted)">TOTAL AMOUNT</span>
                                <div style="font-size:1.25rem; font-weight:800">₹${o.total_amount}</div>
                            </div>
                        </div>
                    </div>
                    <div style="padding:16px 20px; background:#f8fafc; display:flex; gap:12px">
                        ${o.status === 'pending' ? `
                            <button class="btn" style="flex:1" onclick="updateOrderStatus('${o.booking_id}', 'accept')">ACCEPT</button>
                            <button class="btn btn-outline" style="border-color:#fee2e2; color:#ef4444" onclick="updateOrderStatus('${o.booking_id}', 'reject')">REJECT</button>
                        ` : o.status === 'accepted' ? `
                             <button class="btn btn-success" style="flex:1" onclick="updateOrderStatus('${o.booking_id}', 'complete')">MARK COMPLETED</button>
                        ` : `<div style="flex:1; text-align:center; font-size:0.85rem; color:var(--text-muted); font-weight:600">Completed Transaction</div>`}
                    </div>
                </div>
            `;
            }).join('');
            
            // Re-apply status colors manually or via dynamic classes
            document.querySelectorAll('.status-badge-pending').forEach(el => { el.style.background = '#fef3c7'; el.style.color = '#92400e'; });
            document.querySelectorAll('.status-badge-accepted').forEach(el => { el.style.background = '#dcfce7'; el.style.color = '#15803d'; });
            document.querySelectorAll('.status-badge-completed').forEach(el => { el.style.background = '#eff6ff'; el.style.color = '#1d4ed8'; });
            document.querySelectorAll('.status-badge-rejected').forEach(el => { el.style.background = '#fee2e2'; el.style.color = '#b91c1c'; });

            lastOrderIds = items.map(o => o.id);
        }

        async function updateOrderStatus(bid, action) {
            const res = await authFetch(`/orders/${bid}/${action}`, { method: 'PATCH' });
            if (res.ok) { showToast(`Order marked as ${action}ed`, 'success'); fetchOrders(); fetchBadgeCounts(); }
        }

        function updateOrderSelection() {
            const count = document.querySelectorAll('.order-checkbox:checked').length;
            document.getElementById('orders-bulk-bar').style.display = count > 0 ? 'flex' : 'none';
            document.getElementById('order-selected-count').textContent = `${count} Orders Selected`;
        }
        function toggleSelectAllOrders(c) { document.querySelectorAll('.order-checkbox').forEach(cb => cb.checked = c); updateOrderSelection(); }
        async function bulkDeleteOrders() {
             const ids = [...document.querySelectorAll('.order-checkbox:checked')].map(cb => parseInt(cb.dataset.id));
             showConfirm('Delete History', `Permanently delete ${ids.length} orders from history?`, async () => {
                 LevixAudio.play('delete');
                 const res = await authFetch('/orders/bulk-delete', { method: 'POST', body: { ids } });
                 if (res.ok) { showToast('Orders deleted', 'success'); fetchOrders(); updateOrderSelection(); }
             });
        }

        // Tab Logic: Inventory
        async function fetchInventory() {
            renderInventorySkeleton();
            const [base, insights] = await Promise.all([
                  authFetch('/inventory'),
                  authFetch('/inventory/insights')
            ]);
            allInventory = await base.json();
            const ins = await insights.json();
            invInsights = ins.items || [];
            filterInventory();
        }

        let invPage = 1;
        let invPageSize = 10;
        let filteredInvCount = 0;

        function filterInventory() {
            const q = document.getElementById('inv-search').value.toLowerCase();
            const filtered = allInventory.filter(i => i.name.toLowerCase().includes(q) || i.aliases.some(a => a.toLowerCase().includes(q)));
            
            filteredInvCount = filtered.length;
            const totalPages = Math.ceil(filteredInvCount / invPageSize);
            if (invPage > totalPages && totalPages > 0) invPage = totalPages;

            const start = (invPage - 1) * invPageSize;
            const paginated = filtered.slice(start, start + invPageSize);
            
            renderInventory(paginated);
            renderInvPagination();
        }

        function changeInvPageSize(sz) {
            invPageSize = parseInt(sz);
            invPage = 1;
            filterInventory();
        }

        function setInvPage(p) {
            invPage = p;
            filterInventory();
        }

        function renderInvPagination() {
            const totalPages = Math.ceil(filteredInvCount / invPageSize);
            const controls = document.getElementById('inv-page-controls');
            const info = document.getElementById('inv-page-info');
            
            if (totalPages <= 1) {
                controls.innerHTML = '';
                info.textContent = `Showing all ${filteredInvCount} items`;
                return;
            }

            let btns = '';
            // Prev
            btns += `<button class="btn btn-outline" style="padding:6px 12px" ${invPage === 1 ? 'disabled' : ''} onclick="setInvPage(${invPage - 1})">PREV</button>`;
            
            // Pages
            for(let i=1; i<=totalPages; i++) {
                if (i === 1 || i === totalPages || (i >= invPage - 1 && i <= invPage + 1)) {
                    btns += `<button class="btn ${i === invPage ? '' : 'btn-outline'}" style="padding:6px 12px; min-width:38px" onclick="setInvPage(${i})">${i}</button>`;
                } else if (i === invPage - 2 || i === invPage + 2) {
                    btns += `<span style="padding:6px; color:var(--text-muted)">...</span>`;
                }
            }

            btns += `<button class="btn btn-outline" style="padding:6px 12px" ${invPage === totalPages ? 'disabled' : ''} onclick="setInvPage(${invPage + 1})">NEXT</button>`;
            
            controls.innerHTML = btns;
            info.textContent = `Page ${invPage} of ${totalPages} (${filteredInvCount} total items)`;
        }

        function renderInventory(items) {
            const list = document.getElementById('inventory-list');
            if (items.length === 0) { list.innerHTML = '<div style="padding:40px; text-align:center; color:var(--text-muted)">No products in inventory.</div>'; return; }
            
            list.innerHTML = items.map(i => {
                const insight = invInsights.find(ins => ins.id === i.id) || {};
                return `
                <div class="inventory-card">
                    <div style="display:flex; align-items:center; gap:16px">
                        <input type="checkbox" class="inv-checkbox" data-id="${i.id}" onchange="updateInvSelection()" style="width:20px; height:20px">
                        <div>
                            <h4 style="font-weight:800; font-size:1.1rem">${i.name}</h4>
                            <p style="font-size:0.75rem; color:var(--text-muted)">Aliases: ${i.aliases.join(', ')}</p>
                        </div>
                    </div>
                    <div style="display:flex; flex-direction:column; gap:4px">
                        <div style="font-weight:800; font-size:1.1rem; color:var(--accent)">₹${i.price}</div>
                        <span style="font-size:0.7rem; color:var(--text-muted); font-weight:600">DEMAND: ${insight.demand_rate || 0}/day</span>
                    </div>
                    <div class="controls" style="display:flex; align-items:center; gap:24px">
                        <div style="display:flex; align-items:center; gap:8px">
                            <button class="btn btn-outline" style="padding:4px 10px" onclick="adjustQty(${i.id}, -1)">-</button>
                            <span style="font-weight:800; min-width:30px; text-align:center">${i.quantity}</span>
                            <button class="btn btn-outline" style="padding:4px 10px" onclick="adjustQty(${i.id}, 1)">+</button>
                        </div>
                        <div class="select-group">
                             <select style="padding:6px 30px 6px 12px; font-size:0.75rem" onchange="updateItemStatus(${i.id}, this.value)">
                                <option value="available" ${i.status==='available' ? 'selected' : ''}>Available</option>
                                <option value="out_of_stock" ${i.status==='out_of_stock' ? 'selected' : ''}>OOS</option>
                                <option value="coming_soon" ${i.status==='coming_soon' ? 'selected' : ''}>Coming Soon</option>
                             </select>
                        </div>
                        <div style="display:flex; gap: 8px">
                            <button class="btn btn-outline" style="padding:8px" onclick="openEditModal(${JSON.stringify(i).replace(/"/g, '&quot;')})">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                            </button>
                            <button class="btn btn-danger" style="background:none; border:none; padding:8px" onclick="deleteItem(${i.id})">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 6h18m-2 0v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6m3 0V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
                            </button>
                        </div>
                    </div>
                </div>
            `}).join('');
        }

        async function adjustQty(id, amt) {
            const res = await authFetch(`/inventory/${id}/quantity`, { method: 'POST', body: { amount: amt } });
            if (res.ok) fetchInventory();
        }
        async function updateItemStatus(id, s) {
            const res = await authFetch(`/inventory/update-status/${id}`, { method: 'POST', body: { status: s } });
            if (res.ok) showToast('Product status updated', 'success');
        }
        function updateInvSelection() {
            const count = document.querySelectorAll('.inv-checkbox:checked').length;
            document.getElementById('inv-bulk-bar').style.display = count > 0 ? 'flex' : 'none';
            document.getElementById('inv-selected-count').textContent = `${count} Items Selected`;
        }
        function toggleSelectAllInv(c) { document.querySelectorAll('.inv-checkbox').forEach(cb => cb.checked = c); updateInvSelection(); }
        async function bulkDeleteInv() {
             const ids = [...document.querySelectorAll('.inv-checkbox:checked')].map(cb => parseInt(cb.dataset.id));
             showConfirm('Delete Products', `Delete ${ids.length} products from inventory?`, async () => {
                 LevixAudio.play('delete');
                 const res = await authFetch('/inventory/bulk-delete', { method: 'POST', body: { ids } });
                 if (res.ok) { fetchInventory(); updateInvSelection(); }
             });
        }
        async function deleteItem(id) { 
            showConfirm('Delete Product', 'Remove this product from your inventory?', async () => {
                LevixAudio.play('delete');
                await authFetch('/inventory/bulk-delete', { method: 'POST', body: { ids: [id] } }); 
                fetchInventory(); 
            });
        }

        let confirmCallback = null;
        function showConfirm(title, msg, onConfirm) {
            document.getElementById('confirm-title').textContent = title;
            document.getElementById('confirm-message').textContent = msg;
            confirmCallback = onConfirm;
            openModal('modal-confirm');
        }
        document.getElementById('confirm-yes-btn').onclick = () => {
            if (confirmCallback) confirmCallback();
            closeModal('modal-confirm');
        };

        function openModal(id) { 
            document.getElementById(id).style.display = 'flex'; 
        }
        function closeModal(id) { 
            document.getElementById(id).style.display = 'none'; 
        }

        async function submitAddProduct() {
            const name = document.getElementById('add-p-name').value;
            const aliases = document.getElementById('add-p-aliases').value.split(',').map(s => s.trim());
            const price = parseFloat(document.getElementById('add-p-price').value);
            const qty = parseInt(document.getElementById('add-p-qty').value);
            
            const res = await authFetch('/inventory/add', { method: 'POST', body: { name, aliases, price, quantity: qty } });
            if (res.ok) { 
                showToast('Product added successfully', 'success'); 
                closeModal('modal-add-product'); 
                fetchInventory();
                
                // If this came from an inbox request, delete it now
                if (window.activeInboxRequestId) {
                    await authFetch('/pending/bulk-delete', { method: 'POST', body: { ids: [window.activeInboxRequestId] } });
                    window.activeInboxRequestId = null;
                    fetchInbox();
                    fetchBadgeCounts();
                }
            }
        }

        let editingProductId = null;
        function openEditModal(item) {
            editingProductId = item.id;
            document.getElementById('edit-p-name').value = item.name;
            document.getElementById('edit-p-aliases').value = item.aliases.join(', ');
            document.getElementById('edit-p-price').value = item.price;
            document.getElementById('edit-p-qty').value = item.quantity;
            openModal('modal-edit-product');
        }

        async function submitEditProduct() {
            const name = document.getElementById('edit-p-name').value;
            const aliases = document.getElementById('edit-p-aliases').value.split(',').map(s => s.trim());
            const price = parseFloat(document.getElementById('edit-p-price').value);
            const qty = parseInt(document.getElementById('edit-p-qty').value);
            
            const res = await authFetch(`/inventory/edit/${editingProductId}`, { method: 'POST', body: { name, aliases, price, quantity: qty } });
            if (res.ok) { showToast('Product updated', 'success'); closeModal('modal-edit-product'); fetchInventory(); }
        }

        // Tab Logic: Sales History
        function setSalesRange(days) {
            const end = new Date();
            const start = new Date();
            start.setDate(end.getDate() - days);
            
            document.getElementById('sales-start').value = start.toISOString().split('T')[0];
            document.getElementById('sales-end').value = end.toISOString().split('T')[0];
            fetchSales();
        }

        async function fetchSales() {
              const start = document.getElementById('sales-start').value;
              const end = document.getElementById('sales-end').value;
              renderSalesSkeleton();
              const res = await authFetch(`/sales?start_date=${start}&end_date=${end}`);
              const data = await res.json();
              
              const body = document.getElementById('sales-table-body');
              let tqty = 0; let trev = 0;
              
              const records = data.records || [];
              
              if (records.length === 0) {
                  body.innerHTML = '<tr><td colspan="6" style="padding:40px; text-align:center; color:var(--text-muted)">No sales data for this period.</td></tr>';
                  document.getElementById('stat-sales-qty').textContent = '0';
                  document.getElementById('stat-sales-rev').textContent = '₹0';
                  return;
              }

              body.innerHTML = records.map(s => {
                  const tot = s.quantity * s.price;
                  tqty += s.quantity; trev += tot;
                  return `
                    <tr style="border-bottom:1px solid #f1f5f9">
                        <td style="padding:16px; font-weight:800">${s.product_name}</td>
                        <td style="padding:16px; color:var(--text-muted)">${s.date}</td>
                        <td style="padding:16px; font-weight:600">${s.quantity}</td>
                        <td style="padding:16px">₹${s.price.toFixed(2)}</td>
                        <td style="padding:16px; font-weight:800; color:var(--accent)">₹${tot.toFixed(2)}</td>
                        <td style="padding:16px; text-align:right">
                            <button class="btn btn-danger" style="padding:4px 8px; font-size:0.7rem" onclick="deleteSale(${s.id})">DELETE</button>
                        </td>
                    </tr>
                  `;
              }).join('');
              
              animateNumber('stat-sales-qty', tqty);
              animateNumber('stat-sales-rev', trev, '₹');
        }
        async function deleteSale(id) { 
            showConfirm('Delete Sale Record', 'Remove this transaction from sales history?', async () => {
                 LevixAudio.play('delete');
                 await authFetch(`/sales/${id}`, { method:'DELETE' }); 
                 fetchSales(); 
            });
        }

        // Tab Logic: Record Sale Modal
        // Tab Logic: Record Sale Modal
        async function openRecordSaleModal() {
            try {
                const res = await authFetch('/inventory');
                if (res && res.ok) {
                    allInventory = await res.json();
                }
            } catch(e) { console.error("Failed to fetch inventory for sales modal", e); }
            
            openModal('modal-record-sale');
            switchSaleTab('inv');
        }

        function switchSaleTab(tab) {
            const bInv = document.getElementById('sale-tab-inv-btn');
            const bMan = document.getElementById('sale-tab-manual-btn');
            const sInv = document.getElementById('sale-section-inv');
            const sMan = document.getElementById('sale-section-manual');
            const fInv = document.getElementById('sale-section-footer-inv');

            if (tab === 'inv') {
                bInv.style.background = 'white'; bInv.style.color = 'var(--text-main)';
                bInv.style.boxShadow = 'var(--shadow-md)'; bInv.style.border = '1px solid var(--border)';
                bMan.style.background = 'transparent'; bMan.style.color = 'var(--text-muted)';
                bMan.style.boxShadow = 'none'; bMan.style.border = 'none';
                
                sInv.style.display = 'block'; sMan.style.display = 'none';
                fInv.style.display = 'block';
                document.getElementById('sale-inv-search').value = '';
                searchSaleInventory();
            } else {
                bMan.style.background = 'white'; bMan.style.color = 'var(--text-main)';
                bMan.style.boxShadow = 'var(--shadow-md)'; bMan.style.border = '1px solid var(--border)';
                bInv.style.background = 'transparent'; bInv.style.color = 'var(--text-muted)';
                bInv.style.boxShadow = 'none'; bInv.style.border = 'none';
                
                sMan.style.display = 'block'; sInv.style.display = 'none';
                fInv.style.display = 'none';
                document.getElementById('manual-s-date').value = new Date().toISOString().split('T')[0];
            }
        }

        function searchSaleInventory() {
            const q = document.getElementById('sale-inv-search').value.toLowerCase();
            let filtered = allInventory;
            if (q) {
                filtered = allInventory.filter(i => i.name.toLowerCase().includes(q) || i.aliases.some(a => a.toLowerCase().includes(q)));
            }
            
            // Sort alphabetically as requested
            filtered.sort((a,b) => a.name.localeCompare(b.name));

            const list = document.getElementById('sale-inv-list');
            if (filtered.length === 0) { list.innerHTML = '<p style="padding:20px; text-align:center; color:var(--text-muted)">No matching products.</p>'; return; }
            
            list.innerHTML = filtered.map(i => {
                const isOutOfStock = i.quantity <= 0;
                return `
                <div style="padding:12px 16px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; opacity: ${isOutOfStock ? '0.6' : '1'}">
                    <div>
                        <div style="font-weight:700; color: ${isOutOfStock ? 'var(--text-muted)' : 'inherit'}">${i.name}</div>
                        <div style="font-size:0.75rem; color:var(--text-muted)">₹${i.price} • ${isOutOfStock ? '<span style="color:var(--accent-no); font-weight:800">OUT OF STOCK</span>' : i.quantity + ' in stock'}</div>
                    </div>
                    <button class="btn btn-outline" style="padding:6px; border-radius:50%; ${isOutOfStock ? 'cursor: not-allowed; opacity: 0.5' : ''}" 
                        onclick="${isOutOfStock ? '' : `prepareItemSale(${JSON.stringify(i).replace(/"/g, '&quot;')})`}">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                    </button>
                </div>
            `;}).join('');
        }

        let pendingSaleItem = null;
        function prepareItemSale(item) {
            pendingSaleItem = item;
            document.getElementById('record-qty-name').textContent = item.name;
            document.getElementById('item-s-qty').value = 1;
            document.getElementById('item-s-date').value = new Date().toISOString().split('T')[0];
            openModal('modal-record-item-qty');
        }

        async function submitItemSale() {
            const qty = parseInt(document.getElementById('item-s-qty').value);
            const date = document.getElementById('item-s-date').value;

            if (qty > pendingSaleItem.quantity) {
                showToast(`Insufficient Stock! Only ${pendingSaleItem.quantity} available.`, 'error');
                return;
            }

            const res = await authFetch('/sales/set', { method: 'POST', body: { product_id: pendingSaleItem.id, quantity: qty, date } });
            if (res.ok) { showToast('Sale recorded', 'success'); closeModal('modal-record-item-qty'); closeModal('modal-record-sale'); fetchSales(); fetchInventory(); }
        }

        async function submitManualSale() {
            const name = document.getElementById('manual-s-name').value;
            const price = parseFloat(document.getElementById('manual-s-price').value);
            const qty = parseInt(document.getElementById('manual-s-qty').value);
            const date = document.getElementById('manual-s-date').value;
            
            if (!name) { showToast('Enter product name', 'error'); return; }
            const res = await authFetch('/sales/set', { method: 'POST', body: { product_name: name, quantity: qty, price, date } });
            if (res.ok) { showToast('Manual sale recorded', 'success'); closeModal('modal-record-sale'); fetchSales(); }
        }

        async function exportSalesExcel() {
             const start = document.getElementById('sales-start').value;
             const end = document.getElementById('sales-end').value;
             const res = await authFetch(`/sales/export-excel?start_date=${start}&end_date=${end}`);
             if (!res.ok) return;
             const blob = await res.blob();
             const url = window.URL.createObjectURL(blob);
             const a = document.createElement('a');
             a.href = url;
             a.download = `Levix_Sales_${new Date().toISOString().split('T')[0]}.xlsx`;
             document.body.appendChild(a); a.click(); a.remove();
        }

        // Tab Logic: Analytics
        function setAnalyticsRange(days) {
            const end = new Date();
            const start = new Date();
            start.setDate(end.getDate() - days);
            document.getElementById('analytics-date-start').value = start.toISOString().split('T')[0];
            document.getElementById('analytics-date-end').value = end.toISOString().split('T')[0];
            fetchAnalytics();
        }

        async function fetchAnalytics() {
            let start = document.getElementById('analytics-date-start').value;
            let end = document.getElementById('analytics-date-end').value;
            renderAnalyticsSkeleton();
            
            // Auto-init if empty
            if (!start || !end) {
                const e = new Date();
                const s = new Date();
                s.setDate(e.getDate() - 7);
                start = s.toISOString().split('T')[0];
                end = e.toISOString().split('T')[0];
                document.getElementById('analytics-date-start').value = start;
                document.getElementById('analytics-date-end').value = end;
            }

            try {
                const res = await authFetch(`/analytics?start_date=${start}&end_date=${end}`);
                if (!res || !res.ok) throw new Error('Analytics fetch failed');
                const data = await res.json();
                
                // Rebuild the summary grid with real data structure (replacing skeletons)
                const summary = document.getElementById('analytics-summary');
                summary.innerHTML = `
                    <div class="stat-card-new"><span class="label">INQUIRIES</span><div class="value" id="an-total-req">0</div></div>
                    <div class="stat-card-new"><span class="label">REVENUE</span><div class="value" id="an-total-rev">₹0</div></div>
                    <div class="stat-card-new"><span class="label">DEMAND RATE</span><div class="value" id="an-demand">0/day</div></div>
                    <div class="stat-card-new"><span class="label">ORDERS</span><div class="value" id="an-total-ord">0</div></div>
                `;

                animateNumber('an-total-req', data.total_requests || 0);
                animateNumber('an-total-rev', data.total_revenue || 0, '₹');
                animateNumber('an-demand', (data.total_requests / 7) || 0, '', '/day', 1);
                animateNumber('an-total-ord', data.total_orders || 0);
                
                const demandList = document.getElementById('analytics-demand-list');
                if (data.top_requested_products && data.top_requested_products.length > 0) {
                    demandList.innerHTML = data.top_requested_products.map(p => `
                        <div style="display:flex; justify-content:space-between; padding:12px 0; border-bottom:1px solid #f8fafc">
                            <span style="font-weight:700">${p.name}</span>
                            <span style="font-weight:800; color:var(--accent)">${p.score} inquires</span>
                        </div>
                    `).join('');
                } else {
                    demandList.innerHTML = '<p style="text-align:center; padding:20px; color:var(--text-muted)">No data found</p>';
                }
                
                const salesList = document.getElementById('analytics-sales-list');
                if (data.top_sold_products && data.top_sold_products.length > 0) {
                    salesList.innerHTML = data.top_sold_products.map(p => `
                        <div style="display:flex; justify-content:space-between; padding:12px 0; border-bottom:1px solid #f8fafc">
                            <span style="font-weight:700">${p.name}</span>
                            <span style="font-weight:800; color:var(--accent-yes)">₹${p.revenue.toLocaleString()}</span>
                        </div>
                    `).join('');
                } else {
                    salesList.innerHTML = '<p style="text-align:center; padding:20px; color:var(--text-muted)">No data found</p>';
                }

                const customerList = document.getElementById('analytics-customers-list');
                if (data.top_customers && data.top_customers.length > 0) {
                    customerList.innerHTML = data.top_customers.map(c => `
                        <div style="display:flex; justify-content:space-between; padding:12px 0; border-bottom:1px solid #f8fafc">
                            <div>
                                <div style="font-weight:700">${c.name || 'Anonymous'}</div>
                                <div style="font-size:0.75rem; color:var(--text-muted)">${c.phone}</div>
                            </div>
                            <span style="font-weight:800; color:var(--accent)">${c.orders} orders</span>
                        </div>
                    `).join('');
                } else {
                    customerList.innerHTML = '<p style="text-align:center; padding:20px; color:var(--text-muted)">No data found</p>';
                }

                const stockList = document.getElementById('analytics-stock-list');
                if (data.low_stock_items && data.low_stock_items.length > 0) {
                    stockList.innerHTML = data.low_stock_items.map(i => `
                        <div style="display:flex; justify-content:space-between; padding:12px 0; border-bottom:1px solid #f8fafc">
                            <span style="font-weight:700">${i.name}</span>
                            <span style="font-weight:800; color:#ef4444">${i.qty} left</span>
                        </div>
                    `).join('');
                } else {
                    stockList.innerHTML = '<p style="text-align:center; padding:20px; color:var(--text-muted)">All stock normal</p>';
                }
            } catch(e) { console.error("Analytics error:", e); }
        }

        async function exportExcel() {
             const start = document.getElementById('analytics-date-start').value;
             const end = document.getElementById('analytics-date-end').value;
             const btn = event.currentTarget;
             const originalHtml = btn.innerHTML;
             
             btn.innerHTML = 'PREPARING...';
             btn.disabled = true;

             try {
                const res = await authFetch(`/analytics/export?start_date=${start}&end_date=${end}`);
                if (!res.ok) throw new Error('Export failed');
                
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = `Levix_Analytics_${new Date().toISOString().split('T')[0]}.xlsx`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                showToast('Analytics exported successfully', 'success');
             } catch (e) {
                showToast('Failed to export analytics: ' + e.message, 'error');
             } finally {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
             }
        }

        function handleMuteToggle() {
            const isMuted = LevixAudio.toggleMute();
            showToast(isMuted ? 'Sounds muted' : 'Sounds enabled', 'info');
        }

        async function fetchSettings() {
             const res = await authFetch('/me');
             const data = await res.json();
             document.getElementById('set-shop-name').value = data.shop_name;
             document.getElementById('mute-toggle').checked = !LevixAudio.isMuted;
             
             const wa = await authFetch('/admin/whatsapp/status');
             const waData = await wa.json();
             const indicator = document.getElementById('wa-indicator');
             const text = document.getElementById('wa-status-text');
             if (waData.connected) {
                  indicator.style.background = 'var(--accent-yes)';
                  text.textContent = 'CONNECTED (' + waData.phone_number_id + ')';
             } else {
                  indicator.style.background = '#ef4444';
                  text.textContent = 'DISCONNECTED';
             }
        }
        async function updateShopName() {
            const name = document.getElementById('set-shop-name').value;
            const res = await authFetch('/admin/shop-name', { method:'POST', body: { shop_name: name } });
            if (res.ok) { 
                LevixAudio.play('save');
                showToast('Shop name updated', 'success'); 
                document.getElementById('shop-name-display').textContent = name; 
            }
        }
        async function submitWAConfig() {
            const pid = document.getElementById('wa-phone-id').value;
            const token = document.getElementById('wa-token').value;
            const res = await authFetch('/admin/whatsapp/config', { method:'POST', body: { phone_number_id: pid, access_token: token } });
            if (res.ok) { 
                LevixAudio.play('save');
                showToast('WhatsApp credentials saved', 'success'); 
                closeModal('modal-wa-config'); 
                fetchSettings(); 
            }
        }

        function showToast(msg, type='info') {
            const t = document.createElement('div');
            
            // Audio Feedback
            if (type === 'success') LevixAudio.play('success');
            else if (type === 'error') LevixAudio.play('error');
            
            t.style.padding = '12px 20px';
            t.style.borderLeft = type === 'success' ? '4px solid var(--accent-yes)' : '4px solid var(--accent)';
            t.innerHTML = `<span style="font-weight:700">${msg}</span>`;
            document.getElementById('toast-container').appendChild(t);
            setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translateX(20px)'; setTimeout(() => t.remove(), 400); }, 3000);
        }

        function logout() { localStorage.removeItem('token'); window.location.href = '/'; }

        // Auto Poll Removed (Now SSE Driven)

        // Init
        document.addEventListener('DOMContentLoaded', () => {
             const today = new Date().toISOString().split('T')[0];
             const lastWeek = new Date(Date.now() - 7*24*60*60*1000).toISOString().split('T')[0];
             ['sales-start', 'analytics-date-start'].forEach(id => document.getElementById(id).value = lastWeek);
             ['sales-end', 'analytics-date-end'].forEach(id => document.getElementById(id).value = today);
             
             authFetch('/me').then(r => r.json()).then(d => { document.getElementById('shop-name-display').textContent = d.shop_name; });
             
             // Init Real-time Refresh
             LevixSmartRefresh.init();
             
             fetchBadgeCounts();
             switchTab('inbox');
        });
    