// =====================================================================
// app.js - Lógica del Panel de Control de EnvioBot Full
// Monitoreo multi-depósito, cálculo de quiebre, alarmas y colecta agrupada
// =====================================================================

const API_BASE = window.location.protocol === 'file:' ? 'http://localhost:5001/api' : '/api';

// Sistema de Notificaciones Toast no bloqueantes (reemplaza alertas emergentes invasivas)
function showToast(message, type = 'info', duration = 2800) {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.style.cssText = 'position: fixed; bottom: 22px; right: 22px; z-index: 999999; display: flex; flex-direction: column; gap: 8px; pointer-events: none;';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast-msg toast-${type}`;
    let borderCol = '#38bdf8';
    let textCol = '#f8fafc';
    let bgCol = '#0f172a';
    if (type === 'success') {
        borderCol = '#10b981';
        textCol = '#ecfdf5';
    } else if (type === 'error') {
        borderCol = '#ef4444';
        textCol = '#fef2f2';
    }
    toast.style.cssText = `background: ${bgCol}; color: ${textCol}; border: 1.5px solid ${borderCol}; border-radius: 8px; padding: 10px 16px; font-size: 13px; font-weight: 600; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.6); pointer-events: auto; opacity: 0; transform: translateY(12px); transition: all 0.22s ease-out; max-width: 380px; line-height: 1.4;`;
    toast.textContent = message;
    container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateY(0)';
    });

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(12px)';
        setTimeout(() => toast.remove(), 250);
    }, duration);
}

// Configuración de Depósitos disponibles
const WAREHOUSES = {
    meli_full: { id: "meli_full", name: "Mercado Envíos Full (Villa Celina)", city: "Villa Celina", defaultTransit: 5, defaultTarget: 30 }
};

let currentWarehouse = 'meli_full';
let currentUser = null;
let currentAccount = 'all';
let currentPlanInfo = null;
let currentAuthTab = 'login';

// Dataset demo interactivo (funciona aún sin backend)
const BASE_ITEMS_CATALOG = [
    {
        id: 1,
        item_id: "MLA1428901234",
        sku: "AUR-BT-PRO-BLK",
        title: "Auriculares Inalámbricos Bluetooth 5.3 Cancelación Ruido",
        thumbnail: "https://http2.mlstatic.com/D_Q_NP_2X_841443-MLA74805728863_032024-T.webp",
        permalink: "https://mercadolibre.com.ar",
        depots: {
            meli_full: { stock: 34,  transit_days: 5, target_days: 30, buffer: 2, vpd: 7.5 }
        }
    },
    {
        id: 2,
        item_id: "MLA1398823121",
        sku: "TERMO-STN-1L-GRN",
        title: "Termo De Acero Inoxidable 1 Litro Con Manija Térmico",
        thumbnail: "https://http2.mlstatic.com/D_Q_NP_2X_723145-MLA71542109821_092023-T.webp",
        permalink: "https://mercadolibre.com.ar",
        depots: {
            meli_full: { stock: 68,  transit_days: 5, target_days: 30, buffer: 2, vpd: 6.7 }
        }
    },
    {
        id: 3,
        item_id: "MLA1445129844",
        sku: "FND-IPH-15P-TRN",
        title: "Funda Protectora Transparente Antigolpe Reforzada",
        thumbnail: "https://http2.mlstatic.com/D_Q_NP_2X_910243-MLA72899451022_112023-T.webp",
        permalink: "https://mercadolibre.com.ar",
        depots: {
            meli_full: { stock: 280, transit_days: 4, target_days: 30, buffer: 2, vpd: 9.6 }
        }
    },
    {
        id: 4,
        item_id: "MLA1311094321",
        sku: "SOP-CEL-MOTO-ALU",
        title: "Soporte Celular Para Moto Bici Aluminio Reforzado Espejo",
        thumbnail: "https://http2.mlstatic.com/D_Q_NP_2X_612984-MLA70198421390_072023-T.webp",
        permalink: "https://mercadolibre.com.ar",
        depots: {
            meli_full: { stock: 0,   transit_days: 6, target_days: 30, buffer: 2, vpd: 2.8 }
        }
    }
];

let itemsData = [];
let currentFilter = 'all';
let currentSearch = '';
let selectedItem = null;
let colectaSelectedItems = new Map(); // id -> units

function getToken() {
    return localStorage.getItem('enviobot_full_token') || localStorage.getItem('token') || '';
}


// ── Cambiar depósito activo ─────────────────────────────────────────
function cambiarDeposito(depotId) {
    currentWarehouse = depotId;
    const wh = WAREHOUSES[depotId] || WAREHOUSES.meli_full;
    
    // Actualizar textos en UI
    const destinoText = document.getElementById('colectaDestinoText');
    if (destinoText) destinoText.textContent = wh.name;

    const depotSingleLabel = document.getElementById('depotSingleLabelPill');
    if (depotSingleLabel) depotSingleLabel.textContent = wh.name;

    const transitText = document.getElementById('depotTransitDaysText');
    if (transitText) transitText.textContent = `${wh.defaultTransit || 5} días`;

    const targetText = document.getElementById('depotTargetDaysText');
    if (targetText) targetText.textContent = `${wh.defaultTarget || 30} días`;

    const sidebarDepot = document.getElementById('sidebarDepotName');
    if (sidebarDepot) sidebarDepot.textContent = wh.name;

    cargarDatos();
}

function poblarSelectoresDepositos() {
    const activeSelect = document.getElementById('activeWarehouseSelect');
    const depotSingleLabel = document.getElementById('depotSingleLabelPill');
    const recipSelect = document.getElementById('newRecipDepot');
    const whKeys = Object.keys(WAREHOUSES);

    if (activeSelect && depotSingleLabel) {
        if (whKeys.length <= 1) {
            activeSelect.style.display = 'none';
            depotSingleLabel.style.display = 'inline-block';
            depotSingleLabel.textContent = (WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full).name;
        } else {
            activeSelect.style.display = 'inline-block';
            depotSingleLabel.style.display = 'none';
            activeSelect.innerHTML = '';
            Object.values(WAREHOUSES).forEach(wh => {
                const opt = document.createElement('option');
                opt.value = wh.id;
                opt.textContent = wh.name;
                if (wh.id === currentWarehouse) opt.selected = true;
                activeSelect.appendChild(opt);
            });
        }
    }

    if (recipSelect) {
        recipSelect.innerHTML = '<option value="all">Todos los depósitos</option>';
        Object.values(WAREHOUSES).forEach(wh => {
            const opt = document.createElement('option');
            opt.value = wh.id;
            opt.textContent = `Solo ${wh.name}`;
            recipSelect.appendChild(opt);
        });
    }

    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    const transitText = document.getElementById('depotTransitDaysText');
    if (transitText) transitText.textContent = `${wh.defaultTransit || 5} días`;
    const targetText = document.getElementById('depotTargetDaysText');
    if (targetText) targetText.textContent = `${wh.defaultTarget || 30} días`;
    const sidebarDepot = document.getElementById('sidebarDepotName');
    if (sidebarDepot) sidebarDepot.textContent = wh.name;
}

// ── Cargar inventario desde API o fallback a demo ──────────────────
async function cargarDatos() {
    const token = getToken();
    const tbody = document.getElementById('stockTableBody');
    if (!tbody) return;

    // Si no hay sesión o no hay MeLi, mostrar estado para conectar cuenta
    if (!token || !currentUser || !currentUser.ml_accounts || currentUser.ml_accounts.length === 0) {
        itemsData = [];
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align: center; padding: 48px 20px; color: var(--text2);">
                    <div style="font-size: 15px; font-weight: 700; color: var(--text); margin-bottom: 8px;">Conectá tu cuenta de Mercado Libre</div>
                    <div style="font-size: 13px; max-width: 460px; margin: 0 auto 18px auto; line-height: 1.5;">Para consultar tu inventario real en depósito Full y calcular automáticamente tus días de stock y fechas de quiebre, vinculá tu cuenta de vendedor.</div>
                    <button onclick="iniciarConexionMeLi()" class="btn btn-meli" style="padding: 10px 22px; font-weight: 700; font-size: 13px; cursor: pointer;">Conectar Mercado Libre</button>
                </td>
            </tr>
        `;
        return;
    }

    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    tbody.innerHTML = `
        <tr>
            <td colspan="8" style="text-align: center; padding: 42px 20px; color: var(--text2);">
                <div style="margin-bottom: 8px;">
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6; animation: spin 1s linear infinite;">
                        <circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="12"></circle>
                    </svg>
                </div>
                <strong style="color: var(--text); font-size: 14px;">Consultando stock real en ${wh.name}...</strong><br>
                <span style="font-size: 12px;">Sincronizando inventario y ritmo de ventas con Mercado Libre.</span>
            </td>
        </tr>
    `;

    try {
        let url = `${API_BASE}/full/items?warehouse=${currentWarehouse}`;
        if (currentAccount && currentAccount !== 'all') {
            url += `&account_id=${currentAccount}`;
        }

        const res = await fetch(url, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();

        if (res.status === 403 && data.subscription_required) {
            if (data.can_start_trial) {
                abrirModalActivarFull(currentUser);
            } else {
                abrirModalSuscripcionVencida(currentUser);
            }
            return;
        }

        if (data.ok) {
            if (data.plan_info) {
                actualizarBadgePlan(data.plan_info);
            }
            if (data.items && data.items.length > 0) {
                itemsData = data.items.map(it => adaptarItemDesdeBackend(it));
                recalcularTodo();
                return;
            } else {
                itemsData = [];
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" style="text-align: center; padding: 50px 20px; color: var(--text2);">
                            <div style="margin-bottom: 12px;">
                                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;">
                                    <path d="M13.21 2.97 L 19.71 6.59 A 2.50 2.50 0 0 1 21.00 8.77 L 21.00 15.23 A 2.50 2.50 0 0 1 19.71 17.41 L 13.21 21.03 A 2.50 2.50 0 0 1 10.79 21.03 L 4.29 17.41 A 2.50 2.50 0 0 1 3.00 15.23 L 3.00 8.77 A 2.50 2.50 0 0 1 4.29 6.59 L 10.79 2.97 A 2.50 2.50 0 0 1 13.21 2.97 Z"></path>
                                    <polyline points="3.4 7.1 12 12 20.6 7.1"></polyline>
                                    <line x1="12" y1="21.1" x2="12" y2="12"></line>
                                </svg>
                            </div>
                            <strong style="font-size: 15px; color: var(--text);">No se encontraron publicaciones activas en Mercado Envíos Full</strong>
                            <p style="font-size: 12.5px; margin-top: 8px; max-width: 520px; margin-left: auto; margin-right: auto; line-height: 1.5;">
                                Tu cuenta de Mercado Libre está vinculada correctamente. En cuanto tengas publicaciones con stock activo en el centro de Full o cargues tu primer envío, figurarán aquí automáticamente.
                            </p>
                            <button onclick="sincronizarAhora()" class="btn btn-secondary btn-sm" style="margin-top: 14px;">
                                Sincronizar Catálogo Ahora
                            </button>
                        </td>
                    </tr>
                `;
                actualizarDashboardSummary();
                return;
            }
        }
    } catch (err) {
        console.warn("Error cargando inventario real:", err);
        itemsData = [];
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align: center; padding: 40px; color: var(--text2);">
                    <div style="margin-bottom: 8px;">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.6;">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="8" x2="12" y2="12"></line>
                            <line x1="12" y1="16" x2="12.01" y2="16"></line>
                        </svg>
                    </div>
                    <strong style="color: var(--text);">No se pudo conectar con el servidor</strong><br>
                    <span style="font-size: 12px;">Verificá tu conexión o volvé a iniciar sesión.</span>
                </td>
            </tr>
        `;
        actualizarDashboardSummary();
    }
}

function adaptarItemDesdeBackend(raw) {
    return {
        id: raw.id,
        item_id: raw.item_id,
        variation_id: raw.variation_id || null,
        variation_name: raw.variation_name || null,
        inventory_id: raw.inventory_id || null,
        sku: raw.sku,
        title: raw.title,
        thumbnail: raw.thumbnail,
        permalink: raw.permalink,
        current_stock: raw.current_stock_full || 0,
        not_available_stock: raw.not_available_stock_full || 0,
        in_process_stock: raw.in_process_stock !== undefined ? raw.in_process_stock : (raw.not_available_stock_full || 0),
        in_transit_stock: raw.in_transit_stock || 0,
        total_incoming: raw.total_incoming || 0,
        covered_days_left: raw.covered_days_left !== undefined ? raw.covered_days_left : null,
        lead_time_days: raw.effective_lead_time !== undefined ? raw.effective_lead_time : 5, // TIEMPO PREPARACIÓN
        transit_delay_days: raw.effective_transit !== undefined ? raw.effective_transit : 2, // DEMORA FLETE
        buffer_days: raw.effective_buffer !== undefined ? raw.effective_buffer : 2,         // COLCHÓN SEGURIDAD
        target_stock_days: raw.target_coverage_days || 30,
        vpd: raw.vpd_weighted || 0,
        channels: raw.channels || [],
        account_nickname: raw.account_nickname || "",
        backend_status: raw.status || 'ok'
    };
}

// ── Motor de cálculo de quiebre y semáforos ────────────────────────
function recalcularTodo() {
    const today = new Date();

    itemsData.forEach(it => {
        const stock = it.current_stock;
        const inProcess = it.in_process_stock || 0;
        const inTransit = it.in_transit_stock || 0;
        const totalIncoming = inProcess + inTransit;
        const totalCoveredStock = stock + totalIncoming;

        const vpd = it.vpd;
        const prep = it.lead_time_days || 5;       // Tiempo para preparar/empaquetar
        const transit = it.transit_delay_days || 2; // Demora del flete / camión
        const buffer = it.buffer_days || 2;        // Colchón de seguridad
        const totalAdvance = prep + transit + buffer;

        if (vpd > 0) {
            it.days_left = Math.round((stock / vpd) * 10) / 10;
            const coveredDays = Math.round((totalCoveredStock / vpd) * 10) / 10;
            it.covered_days_left = coveredDays;

            // Fecha estimada de quiebre
            const stockoutDate = new Date(today);
            stockoutDate.setDate(stockoutDate.getDate() + Math.floor(it.days_left));
            it.stockout_date = stockoutDate.toISOString().split('T')[0];

            // Días hasta tener que empezar a preparar el pedido
            const daysToDeadline = it.days_left - totalAdvance;
            it.days_to_deadline = daysToDeadline;
            it.is_overdue = (stock <= 0 || daysToDeadline <= 0);

            // La fecha para pedir NUNCA puede ser en el pasado
            // Si el producto ya venció o está en quiebre, la fecha de acción es HOY
            const deadlineDate = new Date(today);
            if (daysToDeadline > 0) {
                deadlineDate.setDate(deadlineDate.getDate() + Math.floor(daysToDeadline));
            }
            it.reorder_deadline_date = deadlineDate.toISOString().split('T')[0];

            // Semáforo inteligente considerando mercadería entrante (en recepción Full o en tránsito)
            if (stock <= 0) {
                if (inProcess > 0) {
                    it.status = 'in_reception';
                } else if (inTransit > 0) {
                    it.status = 'in_transit';
                } else {
                    it.status = 'out_of_stock';
                }
            } else if (it.days_left <= (prep + transit)) {
                if (totalIncoming > 0 && coveredDays > totalAdvance) {
                    it.status = inProcess > 0 ? 'in_reception' : 'in_transit';
                } else {
                    it.status = 'critical';
                }
            } else if (it.days_left <= totalAdvance) {
                if (totalIncoming > 0 && coveredDays > totalAdvance) {
                    it.status = inProcess > 0 ? 'in_reception' : 'in_transit';
                } else {
                    it.status = 'warning';
                }
            } else {
                it.status = 'ok';
            }

            // Unidades sugeridas para reponer restando lo que ya viene en camino o en recepción
            const targetDays = it.target_stock_days || 30;
            it.suggested_units = Math.max(0, Math.round((targetDays * vpd) - totalCoveredStock));
        } else {
            it.days_left = 999;
            it.covered_days_left = 999;
            it.days_to_deadline = 999;
            it.is_overdue = false;
            it.stockout_date = null;
            it.reorder_deadline_date = null;
            it.suggested_units = 0;
            if (stock <= 0) {
                if (inProcess > 0) it.status = 'in_reception';
                else if (inTransit > 0) it.status = 'in_transit';
                else it.status = 'out_of_stock';
            } else {
                it.status = 'ok';
            }
        }
    });

    actualizarMetricas();
    renderizarWidgetAlertas();
    renderizarTabla();

    // Evaluar y disparar notificación nativa de pantalla si corresponde
    if (window.EnvioBotNotif && window.EnvioBotNotif.checkAuto) {
        window.EnvioBotNotif.checkAuto(itemsData);
    }
}

function actualizarMetricas() {
    let ok = 0, warn = 0, crit = 0, inProcess = 0, totalUnits = 0;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;

    itemsData.forEach(it => {
        if (it.status === 'ok') ok++;
        else if (it.status === 'warning') warn++;
        else if (it.status === 'in_reception' || it.status === 'in_transit') inProcess++;
        else crit++;

        const targetDays = it.target_stock_days || wh.defaultTarget || 30;
        const totalCovered = it.current_stock + (it.in_process_stock || 0) + (it.in_transit_stock || 0);
        const faltante = Math.max(0, Math.round((targetDays * it.vpd) - totalCovered));
        if ((it.status === 'warning' || it.status === 'critical' || it.status === 'out_of_stock') && faltante > 0) {
            totalUnits += faltante;
        }
    });

    document.getElementById('statTotal').textContent = itemsData.length;
    document.getElementById('statOk').textContent = ok + inProcess;
    document.getElementById('statWarning').textContent = warn;
    document.getElementById('statCritical').textContent = crit;

    // Actualizar datos del depósito en la barra integrada
    const transitText = document.getElementById('depotTransitDaysText');
    if (transitText) transitText.textContent = `${wh.defaultTransit} días`;

    const targetText = document.getElementById('depotTargetDaysText');
    if (targetText) targetText.textContent = `${wh.defaultTarget} días`;

    // Actualizar sidebar derecho
    const sidebarDepot = document.getElementById('sidebarDepotName');
    if (sidebarDepot) sidebarDepot.textContent = wh.name;
}

// ── Widget de Alertas de Reposición (Columna Derecha) ───────────────
function renderizarWidgetAlertas() {
    const container = document.getElementById('widgetAlertContainer');
    if (!container) return;

    const criticalItems = itemsData.filter(x => x.status === 'critical' || x.status === 'out_of_stock');
    const warningItems = itemsData.filter(x => x.status === 'warning');
    const totalAccion = criticalItems.length + warningItems.length;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;

    const allNeedingAction = [...criticalItems, ...warningItems].sort((a, b) => a.days_left - b.days_left);

    if (totalAccion > 0) {
        const mostUrgent = allNeedingAction[0];
        const transit = mostUrgent.transit_delay_days || 5;
        const buffer = mostUrgent.buffer_days || 2;
        const daysToDeadline = mostUrgent.days_to_deadline !== undefined ? mostUrgent.days_to_deadline : (mostUrgent.days_left - transit - buffer);
        const roundedDays = Math.max(1, Math.round(daysToDeadline));

        const isUrgent = (mostUrgent.current_stock <= 0 || daysToDeadline <= 0);
        let askDateStr = '';
        if (mostUrgent.current_stock <= 0) {
            askDateStr = 'PEDIR HOY (Sin Stock)';
        } else if (isUrgent) {
            askDateStr = 'PEDIR HOY URGENTE';
        } else {
            askDateStr = `Pedir el ${formatearFecha(mostUrgent.reorder_deadline_date)} (en ${roundedDays} d)`;
        }

        // Banner principal claro con la fecha para pedir en MeLi
        const proximaColectaBannerHtml = `
            <div class="proxima-colecta-banner" style="border-left: 4px solid ${isUrgent ? 'var(--danger)' : 'var(--warn)'};">
                <div class="proxima-colecta-label">Día para pedir Colecta a MeLi</div>
                <div class="proxima-colecta-date" style="color: ${isUrgent ? 'var(--danger)' : 'var(--accent)'}; font-size: 19px; font-weight: 800;">
                    ${askDateStr}
                </div>
                <div class="proxima-colecta-desc">
                    ${isUrgent ? 
                        `Tenés que pedir el turno en MercadoLibre <strong>hoy</strong> para que el flete llegue antes del quiebre estimado (${mostUrgent.title.substring(0, 30)}...).` :
                        `Generá el envío en MeLi antes del <strong>${formatearFecha(mostUrgent.reorder_deadline_date)}</strong> para que el camión descargue a tiempo.`
                    }
                </div>
            </div>
        `;

        let itemsHtml = '';
        const listaAlertas = allNeedingAction.slice(0, 4);
        listaAlertas.forEach(it => {
            const estadoTexto = it.status === 'out_of_stock' ? 'Sin stock' : (it.status === 'critical' ? 'Quiebre crítico' : 'Preparar');
            itemsHtml += `
                <div class="widget-alert-item">
                    <div class="widget-alert-item-title" title="${it.title}">${it.title}</div>
                    <div class="widget-alert-item-meta">
                        <span>${estadoTexto} · Cobertura: ${it.days_left} d</span>
                        <span style="font-weight: 700; color: var(--accent);">${it.suggested_units} un.</span>
                    </div>
                </div>
            `;
        });

        const statusClass = criticalItems.length > 0 ? 'critical' : 'warning';
        const statusTexto = criticalItems.length > 0 ? 
            `${totalAccion} publicación(es) en quiebre inminente` : 
            `${totalAccion} publicación(es) en fecha de colecta`;

        container.innerHTML = `
            ${proximaColectaBannerHtml}
            <div class="widget-alert-status ${statusClass}">
                ${statusTexto}
            </div>
            <div class="widget-alert-list">
                ${itemsHtml}
            </div>
            <button class="btn btn-sm" style="width: 100%; background: var(--accent); color: #111; font-weight: 700;" onclick="abrirModalColecta()">
                Armar Colecta
            </button>
        `;
    } else {
        container.innerHTML = `
            <div class="proxima-colecta-banner" style="border-left: 4px solid var(--good);">
                <div class="proxima-colecta-label">Día para pedir Colecta a MeLi</div>
                <div class="proxima-colecta-date" style="color: var(--good);">Sin colectas urgentes</div>
                <div class="proxima-colecta-desc">
                    El stock actual en ${wh.name} cubre la demanda de las próximas semanas con holgura.
                </div>
            </div>
            <div class="widget-alert-status ok">
                Sin alertas pendientes
            </div>
            <p style="font-size: 12px; color: var(--text2); line-height: 1.5; margin-bottom: 12px;">
                Todos los productos en ${wh.name} tienen stock suficiente.
            </p>
            <button class="btn btn-secondary btn-sm" style="width: 100%;" onclick="abrirModalColecta()">
                Planificar Envío Preventivo
            </button>
        `;
    }
}

// ── Renderizado de la Tabla Principal ─────────────────────────────
function renderizarTabla() {
    const tbody = document.getElementById('stockTableBody');
    tbody.innerHTML = '';

    const filtrados = itemsData.filter(it => {
        const matchSearch = !currentSearch || 
            it.title.toLowerCase().includes(currentSearch) || 
            (it.sku && it.sku.toLowerCase().includes(currentSearch)) ||
            it.item_id.toLowerCase().includes(currentSearch);

        let matchStatus = true;
        if (currentFilter === 'action_required') {
            matchStatus = it.status === 'warning' || it.status === 'critical' || it.status === 'out_of_stock';
        } else if (currentFilter !== 'all') {
            matchStatus = it.status === currentFilter;
        }

        return matchSearch && matchStatus;
    });

    if (filtrados.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 30px; color: var(--text2);">No hay publicaciones con los filtros seleccionados.</td></tr>';
        return;
    }

    filtrados.forEach(it => {
        const tr = document.createElement('tr');
        tr.style.cursor = 'pointer';
        tr.onclick = (e) => {
            if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'A') {
                seleccionarProducto(it);
            }
        };

        // Semáforo Badge Limpio (Sin Emojis)
        let badgeHtml = '';
        if (it.status === 'ok') {
            badgeHtml = '<span class="badge badge-ok">Óptimo</span>';
        } else if (it.status === 'warning') {
            badgeHtml = '<span class="badge badge-warn">Preparar</span>';
        } else if (it.status === 'critical') {
            badgeHtml = '<span class="badge badge-danger">Crítico</span>';
        } else if (it.status === 'in_reception') {
            badgeHtml = `<span class="badge" style="background: rgba(168, 85, 247, 0.16); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.35); font-weight: 700;" title="${it.in_process_stock} un. recibidas en Villa Celina pendientes de escaneo por feriado">En Recepción Full</span>`;
        } else if (it.status === 'in_transit') {
            badgeHtml = `<span class="badge" style="background: rgba(59, 130, 246, 0.16); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.35); font-weight: 700;" title="${it.in_transit_stock} un. despachadas en camino hacia Full">En Tránsito</span>`;
        } else {
            badgeHtml = '<span class="badge badge-danger">Sin Stock</span>';
        }

        const prep = it.lead_time_days || 5;
        const transit = it.transit_delay_days || 2;
        const buffer = it.buffer_days || 2;
        const totalAdvance = prep + transit + buffer;

        const diasRestantesText = it.days_left >= 900 ? 'Sin ventas' : `${it.days_left} d`;

        // FECHA DE QUIEBRE ESTIMADA
        let quiebraElHtml = '—';
        if (it.status === 'in_reception') {
            quiebraElHtml = `<span style="color: #c084fc; font-weight: 700;" title="Mercadería en depósito MeLi siendo procesada">+${it.in_process_stock} en MeLi</span>`;
        } else if (it.status === 'in_transit') {
            quiebraElHtml = `<span style="color: #60a5fa; font-weight: 700;" title="Envío despachado en camino">+${it.in_transit_stock} en camino</span>`;
        } else if (it.current_stock <= 0) {
            quiebraElHtml = '<span style="color: var(--danger); font-weight: 700;">Agotado</span>';
        } else if (it.days_left >= 900 || !it.stockout_date) {
            quiebraElHtml = '<span style="color: var(--text2);">Sin ventas</span>';
        } else {
            const quiebreFecha = formatearFecha(it.stockout_date);
            const isDanger = it.days_left <= (prep + transit);
            const isWarning = it.days_left <= totalAdvance;
            const color = isDanger ? 'var(--danger)' : (isWarning ? 'var(--accent-text)' : 'var(--text)');
            quiebraElHtml = `<strong style="color: ${color};">${quiebreFecha}</strong>`;
        }

        // CUÁNDO PEDIR COLECTA EN MELI (considerando tiempo de preparación + camión + buffer + mercadería en camino)
        let fechaColectaHtml = '—';
        if (it.status === 'in_reception') {
            fechaColectaHtml = `<span class="badge-date-normal" style="color: #c084fc; font-weight: 700;" title="Entregado en Villa Celina, pendiente de escaneo MeLi">+${it.in_process_stock} un. en ingreso</span>`;
        } else if (it.status === 'in_transit') {
            fechaColectaHtml = `<span class="badge-date-normal" style="color: #60a5fa; font-weight: 700;" title="Despacho en viaje hacia Full">+${it.in_transit_stock} un. en camino</span>`;
        } else if (it.reorder_deadline_date) {
            const daysToDeadline = it.days_to_deadline !== undefined ? it.days_to_deadline : (it.days_left - totalAdvance);
            const roundedDays = Math.max(1, Math.round(daysToDeadline));

            if (it.current_stock <= 0) {
                fechaColectaHtml = `
                    <span class="badge-date-today" style="background: rgba(239, 68, 68, 0.15); color: var(--danger); font-weight: 700;" title="Sin stock en Full. Generar reposición urgente hoy.">PEDIR HOY (Sin Stock)</span>
                `;
            } else if (daysToDeadline <= 0) {
                fechaColectaHtml = `
                    <span class="badge-date-today" style="background: rgba(239, 68, 68, 0.15); color: var(--danger); font-weight: 700;" title="Cobertura crítica. Pedir turno en MeLi hoy para evitar quiebre de stock.">PEDIR HOY URGENTE</span>
                `;
            } else if (daysToDeadline <= 3) {
                fechaColectaHtml = `
                    <span class="badge-date-soon" title="Día límite para iniciar preparación y pedir turno en MeLi">Pedir el ${formatearFecha(it.reorder_deadline_date)} (en ${roundedDays} d)</span>
                `;
            } else {
                fechaColectaHtml = `
                    <span class="badge-date-normal">Pedir el ${formatearFecha(it.reorder_deadline_date)} (en ${roundedDays} d)</span>
                `;
            }
        }

        const thumbSrc = it.thumbnail || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="%238a8d9a" stroke-width="1.5"%3E%3Crect x="3" y="3" width="18" height="18" rx="2"/%3E%3C/svg%3E';

        // Badges de canales de venta hermanas (Clásica / Premium / Catálogo)
        let channelsHtml = '';
        if (it.channels && it.channels.length > 0) {
            channelsHtml = '<span class="channels-container">';
            it.channels.forEach(ch => {
                const typeLabel = ch.is_catalog ? 'Catálogo' : (ch.type_label || (ch.listing_type === 'gold_pro' ? 'Premium' : 'Clásica'));
                const badgeClass = ch.is_catalog ? 'badge-ch-catalog' : (ch.listing_type === 'gold_pro' ? 'badge-ch-pro' : 'badge-ch-classic');
                channelsHtml += `<a href="${ch.permalink}" target="_blank" class="channel-pill ${badgeClass}" title="Publicación ${typeLabel}: ${ch.item_id}" onclick="event.stopPropagation();">${typeLabel}</a>`;
            });
            channelsHtml += '</span>';
        } else {
            channelsHtml = `<a href="${it.permalink || '#'}" target="_blank" style="color: var(--text2); text-decoration: underline;" onclick="event.stopPropagation();">${it.item_id}</a>`;
        }

        const varTagHtml = it.variation_name ? `<span class="variation-tag" title="Variante">${it.variation_name}</span>` : '';
        let incomingBadgesHtml = '';
        if (it.in_process_stock > 0) {
            incomingBadgesHtml += `<span class="not-avail-pill" style="background: rgba(168, 85, 247, 0.15); color: #c084fc; display: inline-block; margin-top: 3px;" title="${it.in_process_stock} unidades entregadas en Villa Celina pendientes de escaneo MeLi">+${it.in_process_stock} en recepción MeLi</span>`;
        }
        if (it.in_transit_stock > 0) {
            incomingBadgesHtml += `<span class="not-avail-pill" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa; display: inline-block; margin-top: 3px;" title="${it.in_transit_stock} unidades despachadas en camino hacia Full">+${it.in_transit_stock} en camino</span>`;
        }

        tr.innerHTML = `
            <td>
                <div class="product-cell">
                    <img src="${thumbSrc}" class="product-thumb" alt="Foto">
                    <div>
                        <div class="product-title" title="${it.title}">
                            <span>${it.title}</span>${varTagHtml}
                        </div>
                        <div class="product-meta">
                            <span>SKU: <strong>${it.sku || 'Sin SKU'}</strong></span> · 
                            ${channelsHtml}
                        </div>
                    </div>
                </div>
            </td>
            <td class="num-cell">
                <strong>${it.current_stock}</strong> un.${incomingBadgesHtml}
            </td>
            <td class="num-cell">${it.vpd} un./d</td>
            <td class="num-cell" style="font-weight: 700; color: ${it.days_left <= (prep + transit) ? 'var(--danger)' : 'var(--text)'};">
                ${diasRestantesText}
            </td>
            <td class="num-cell" style="white-space: nowrap;">
                ${quiebraElHtml}
            </td>
            <td class="num-cell">
                ${fechaColectaHtml}
            </td>
            <td class="num-cell" style="white-space: nowrap;">
                <span style="display: inline-flex; align-items: center; justify-content: flex-end; gap: 4px; white-space: nowrap;">
                    <input type="number" min="1" max="99" class="input-days-2digit" 
                           value="${it.target_stock_days}" 
                           oninput="if(this.value.length>2) this.value=this.value.slice(0,2);"
                           onchange="cambiarStockDeseado(${it.id}, this.value)"
                           title="Días de venta que querés mantener guardados en este depósito">
                    <span style="color: var(--text2); font-size: 11.5px; font-weight: 600;">d</span>
                </span>
            </td>
            <td class="num-cell">${badgeHtml}</td>
        `;
        tbody.appendChild(tr);
    });

    if (!selectedItem && filtrados.length > 0) {
        seleccionarProducto(filtrados[0]);
    }
}

function formatearFecha(dateStr) {
    if (!dateStr) return '—';
    const partes = dateStr.split('-');
    if (partes.length === 3) {
        return `${partes[2]}/${partes[1]}`;
    }
    return dateStr;
}

// ── Modificar Demora Camión (In-place) ──────────────────────────────
function cambiarDemoraCamion(id, nuevoValor) {
    const val = parseInt(nuevoValor, 10);
    if (isNaN(val) || val <= 0) return;

    const it = itemsData.find(x => x.id === id);
    if (!it) return;

    it.transit_delay_days = val;
    recalcularTodo();

    if (selectedItem && selectedItem.id === id) {
        seleccionarProducto(it);
    }

    // Persistir si hay token
    const token = getToken();
    if (token) {
        fetch(`${API_BASE}/full/items/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ lead_time_override: val })
        }).catch(e => console.error("Error guardando demora camión:", e));
    }
}

// ── Modificar Días de Stock Teórico Deseado (In-place) ───────────────
function cambiarStockDeseado(id, nuevoValor) {
    const val = parseInt(nuevoValor, 10);
    if (isNaN(val) || val <= 0) return;

    const it = itemsData.find(x => x.id === id);
    if (!it) return;

    it.target_stock_days = val;
    recalcularTodo();

    if (selectedItem && selectedItem.id === id) {
        seleccionarProducto(it);
    }
}

// ── Selección y Calculadora Lateral ────────────────────────────────
function seleccionarProducto(item) {
    selectedItem = item;
    const planCard = document.getElementById('restockPlannerCard');
    if (!planCard) return;

    document.getElementById('planItemTitle').textContent = item.title;
    document.getElementById('planItemSku').textContent = item.sku || item.item_id;
    document.getElementById('planStockActual').textContent = `${item.current_stock} un.`;
    document.getElementById('planVpd').textContent = `${item.vpd} un./día`;

    calcularUnidadesEnvio();
}

function calcularUnidadesEnvio() {
    if (!selectedItem) return;
    const targetDays = parseInt(document.getElementById('targetDaysSelect').value, 10) || selectedItem.target_stock_days || 30;
    const unidadesNecesarias = Math.max(0, Math.round((targetDays * selectedItem.vpd) - selectedItem.current_stock));
    document.getElementById('planSuggestedUnits').textContent = `${unidadesNecesarias} un.`;
}

// ── Sincronizar / Chequear Stock Actual ─────────────────────────────
async function sincronizarAhora() {
    const btn = document.getElementById('btnCheckStockNow');
    const syncIcon = document.getElementById('syncIcon');
    const syncText = document.getElementById('syncBtnText');

    btn.disabled = true;
    syncText.textContent = 'Consultando MercadoLibre...';
    syncIcon.style.display = 'inline-block';
    syncIcon.style.animation = 'spin 0.8s linear infinite';

    const token = getToken();
    if (token) {
        try {
            await fetch(`${API_BASE}/full/sync-now`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
        } catch (e) {
            console.error(e);
        }
    } else {
        // Delay simulado en demo
        await new Promise(r => setTimeout(r, 600));
    }

    syncIcon.style.animation = 'none';
    syncText.textContent = 'Stock Actualizado';
    document.getElementById('lastSyncText').textContent = 'Recién';

    setTimeout(() => {
        syncText.textContent = 'Chequear Stock Actual';
        btn.disabled = false;
    }, 2500);

    cargarDatos();
}

// ── Filtros y Búsqueda ─────────────────────────────────────────────
function onSearchChange(val) {
    currentSearch = val.toLowerCase().trim();
    renderizarTabla();
}

function onFilterChange(val) {
    currentFilter = val;
    renderizarTabla();
}

// ── MODAL: Colectas y Envíos Inbound a Full (Etapa 2) ──────────────────
let userInboundEnabled = false;
let userIsAdmin = false;
let colectaBoxUnits = new Map(); // id -> units_per_box
let inboundShipmentsList = [];

async function verificarEstadoInboundUsuario() {
    const token = getToken();
    if (!token) return false;
    try {
        const res = await fetch(`${API_BASE}/full/inbound/status`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.ok) {
            userInboundEnabled = Boolean(data.has_inbound);
            userIsAdmin = Boolean(data.is_admin);
            return userInboundEnabled;
        }
    } catch (e) {
        console.warn("Aviso verificando status inbound:", e);
    }
    return false;
}

function getDiasCoberturaColecta() {
    const input = document.getElementById('colectaDiasInput');
    if (input) {
        const val = parseInt(input.value, 10);
        if (!isNaN(val) && val > 0) return val;
    }
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    return (wh && wh.defaultTarget) ? wh.defaultTarget : 15;
}

function onColectaDiasChange() {
    verificarLeadTimeMinimoColecta();
    recalcularColecta();
}

function setColectaDiasPreset(dias) {
    const input = document.getElementById('colectaDiasInput');
    if (input) {
        input.value = dias;
        onColectaDiasChange();
    }
}

function verificarLeadTimeMinimoColecta() {
    const targetDays = getDiasCoberturaColecta();
    const leadTime = parseInt(document.getElementById('cfgLeadTime')?.value, 10) || 5;
    const buffer = parseInt(document.getElementById('cfgSafetyStock')?.value, 10) || 2;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    const transit = wh.defaultTransit || 3;
    const minDaysNeeded = leadTime + buffer + transit;

    const warnBanner = document.getElementById('colectaLeadTimeWarning');
    if (warnBanner) {
        if (targetDays < minDaysNeeded) {
            const elDias = document.getElementById('warnDiasElegidos');
            const elLt = document.getElementById('warnLeadTime');
            const elBuf = document.getElementById('warnBuffer');
            const elTr = document.getElementById('warnTransit');
            const elMin = document.getElementById('warnMinDias');
            if (elDias) elDias.textContent = targetDays;
            if (elLt) elLt.textContent = leadTime;
            if (elBuf) elBuf.textContent = buffer;
            if (elTr) elTr.textContent = transit;
            if (elMin) elMin.textContent = minDaysNeeded;
            warnBanner.style.display = 'block';
        } else {
            warnBanner.style.display = 'none';
        }
    }
    return minDaysNeeded;
}

function toggleColectaFullscreen() {
    const card = document.getElementById('colectaModalCard');
    const btnText = document.getElementById('btnColectaFullscreenText');
    const iconExp = document.getElementById('fsColectaIconExpand');
    const iconComp = document.getElementById('fsColectaIconCompress');
    if (!card) return;

    card.classList.toggle('modal-fullscreen');
    const isFull = card.classList.contains('modal-fullscreen');

    if (btnText) btnText.textContent = isFull ? 'Ventana Normal' : 'Pantalla Completa';
    if (iconExp && iconComp) {
        iconExp.style.display = isFull ? 'none' : 'inline-block';
        iconComp.style.display = isFull ? 'inline-block' : 'none';
    }
}

function toggleResumenColecta() {
    const sec = document.getElementById('colectaHeaderSummarySection');
    const btn = document.getElementById('btnToggleResumenColecta');
    if (!sec) return;

    const isHidden = sec.style.display === 'none';
    sec.style.display = isHidden ? 'block' : 'none';
    if (btn) {
        btn.textContent = isHidden ? 'Plegar Resumen' : 'Mostrar Resumen';
    }
}

async function abrirModalColecta() {
    const modal = document.getElementById('colectaModal');
    if (!modal) return;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    const destText = document.getElementById('colectaDestinoText');
    if (destText) destText.textContent = wh.name;

    // Verificar permisos del módulo pago en backend
    await verificarEstadoInboundUsuario();

    // Cobertura del depósito activo o guardada (default 15 días)
    const targetGlobalDays = wh.defaultTarget || 15;
    const inputDias = document.getElementById('colectaDiasInput');
    if (inputDias) inputDias.value = targetGlobalDays;

    verificarLeadTimeMinimoColecta();

    // Inicializar mapa de selección y unidades por defecto
    colectaSelectedItems.clear();
    colectaBoxUnits.clear();

    const leadTime = parseInt(document.getElementById('cfgLeadTime')?.value, 10) || 5;
    const transit = wh.defaultTransit || 3;
    const daysFactor = targetGlobalDays + leadTime + transit;

    itemsData.forEach(it => {
        const suggested = Math.max(0, Math.ceil((daysFactor * it.vpd) - it.current_stock));
        // Seleccionar por defecto si requiere reposición o tiene riesgo
        const shouldCheck = (it.status === 'warning' || it.status === 'critical' || it.status === 'out_of_stock' || suggested > 0);
        if (shouldCheck) {
            colectaSelectedItems.set(it.id, suggested > 0 ? suggested : Math.max(1, Math.round(it.vpd * 7) || 1));
            // Unidades por caja máster reales del producto guardadas en base de datos
            const defaultUnitsBox = (it.units_per_box && it.units_per_box > 0) ? it.units_per_box : 0;
            colectaBoxUnits.set(it.id, defaultUnitsBox);
        }
    });

    // Fechas estimadas dinámicas
    const today = new Date();
    const pickupDate = new Date(today);
    pickupDate.setDate(pickupDate.getDate() + Math.max(1, leadTime));
    const arrivalDate = new Date(pickupDate);
    arrivalDate.setDate(arrivalDate.getDate() + transit);

    const askEl = document.getElementById('timelineAskDate');
    const pickupEl = document.getElementById('timelinePickupDate');
    const arrivalEl = document.getElementById('timelineArrivalDate');

    if (askEl) askEl.textContent = `PEDIR HOY (${today.getDate()}/${today.getMonth() + 1})`;
    if (pickupEl) pickupEl.textContent = `Retiro: ${pickupDate.getDate()}/${pickupDate.getMonth() + 1}`;
    if (arrivalEl) arrivalEl.textContent = `Disponible Full: ${arrivalDate.getDate()}/${arrivalDate.getMonth() + 1}`;

    const fechaRetiroInput = document.getElementById('colectaFechaRetiroInput');
    if (fechaRetiroInput && !fechaRetiroInput.value) {
        fechaRetiroInput.value = pickupDate.toISOString().split('T')[0];
    }

    switchColectaTab('planificar');
    renderizarFilasColecta();
    modal.style.display = 'flex';

    // Cargar historial en segundo plano para badge
    cargarHistorialColectas(true);
}

function cerrarModalColecta() {
    const modal = document.getElementById('colectaModal');
    if (modal) modal.style.display = 'none';
}

function switchColectaTab(tab) {
    const tabPlan = document.getElementById('colectaTabPlanificar');
    const tabHist = document.getElementById('colectaTabHistorial');
    const btnPlan = document.getElementById('btnTabPlanificarColecta');
    const btnHist = document.getElementById('btnTabHistorialColecta');

    if (tab === 'planificar') {
        if (tabPlan) tabPlan.style.display = 'flex';
        if (tabHist) tabHist.style.display = 'none';
        if (btnPlan) {
            btnPlan.style.background = 'var(--accent)';
            btnPlan.style.color = '#111';
            btnPlan.className = 'btn btn-sm';
        }
        if (btnHist) {
            btnHist.style.background = '';
            btnHist.style.color = '';
            btnHist.className = 'btn btn-secondary btn-sm';
        }
    } else {
        if (tabPlan) tabPlan.style.display = 'none';
        if (tabHist) tabHist.style.display = 'flex';
        if (btnPlan) {
            btnPlan.style.background = '';
            btnPlan.style.color = '';
            btnPlan.className = 'btn btn-secondary btn-sm';
        }
        if (btnHist) {
            btnHist.style.background = 'var(--accent)';
            btnHist.style.color = '#111';
            btnHist.className = 'btn btn-sm';
        }
        cargarHistorialColectas();
    }
}

function recalcularColecta() {
    const targetDays = getDiasCoberturaColecta();
    const leadTime = parseInt(document.getElementById('cfgLeadTime')?.value, 10) || 5;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    const transit = wh.defaultTransit || 3;
    const daysFactor = targetDays + leadTime + transit;

    itemsData.forEach(it => {
        if (colectaSelectedItems.has(it.id)) {
            const suggested = Math.max(0, Math.ceil((daysFactor * it.vpd) - it.current_stock));
            colectaSelectedItems.set(it.id, suggested > 0 ? suggested : 1);
        }
    });
    renderizarFilasColecta();
}

function toggleSelectAllColecta(checked) {
    const targetDays = getDiasCoberturaColecta();
    const leadTime = parseInt(document.getElementById('cfgLeadTime')?.value, 10) || 5;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    const transit = wh.defaultTransit || 3;
    const daysFactor = targetDays + leadTime + transit;

    colectaSelectedItems.clear();
    if (checked) {
        itemsData.forEach(it => {
            const suggested = Math.max(0, Math.ceil((daysFactor * it.vpd) - it.current_stock));
            colectaSelectedItems.set(it.id, suggested > 0 ? suggested : Math.max(1, Math.round(it.vpd * 7) || 1));
            if (!colectaBoxUnits.has(it.id)) {
                colectaBoxUnits.set(it.id, it.units_per_box || 0);
            }
        });
    }
    renderizarFilasColecta();
}

function toggleItemColecta(id, checked) {
    const targetDays = getDiasCoberturaColecta();
    const it = itemsData.find(x => x.id === id);
    if (!it) return;

    if (checked) {
        const leadTime = parseInt(document.getElementById('cfgLeadTime')?.value, 10) || 5;
        const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
        const transit = wh.defaultTransit || 3;
        const daysFactor = targetDays + leadTime + transit;
        const suggested = Math.max(0, Math.ceil((daysFactor * it.vpd) - it.current_stock));
        colectaSelectedItems.set(id, suggested > 0 ? suggested : Math.max(1, Math.round(it.vpd * 7) || 1));
        if (!colectaBoxUnits.has(id)) colectaBoxUnits.set(id, it.units_per_box || 0);
    } else {
        colectaSelectedItems.delete(id);
    }
    actualizarTotalColecta();
}

function cambiarUnidadesColecta(id, val) {
    const cant = Math.max(0, parseInt(val, 10) || 0);
    colectaSelectedItems.set(id, cant);
    actualizarTotalColecta();
}

function cambiarUnidadesPorCajaColecta(id, val) {
    const cant = Math.max(0, parseInt(val, 10) || 0);
    colectaBoxUnits.set(id, cant);

    // Actualizar en memoria y persistir en base de datos
    const it = itemsData.find(x => x.id === id);
    if (it) it.units_per_box = cant;

    const token = getToken();
    if (token) {
        fetch(`${API_BASE}/full/items/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ units_per_box: cant })
        }).catch(e => console.warn("Aviso guardando units_per_box:", e));
    }

    actualizarTotalColecta();
}

function renderizarFilasColecta() {
    const tbody = document.getElementById('colectaTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const targetDays = getDiasCoberturaColecta();
    const leadTime = parseInt(document.getElementById('cfgLeadTime')?.value, 10) || 5;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    const transit = wh.defaultTransit || 3;
    const daysFactor = targetDays + leadTime + transit;

    itemsData.forEach(it => {
        const isSelected = colectaSelectedItems.has(it.id);
        const suggested = Math.max(0, Math.ceil((daysFactor * it.vpd) - it.current_stock));
        const unitsToSend = colectaSelectedItems.get(it.id) !== undefined ? colectaSelectedItems.get(it.id) : suggested;
        const unitsPerBox = colectaBoxUnits.get(it.id) !== undefined ? colectaBoxUnits.get(it.id) : (it.units_per_box || 0);
        const boxesEst = unitsPerBox > 0 ? Math.ceil(unitsToSend / unitsPerBox) : (unitsToSend > 0 ? 1 : 0);

        // Canales badges
        let channelBadges = '';
        if (Array.isArray(it.channels) && it.channels.length > 0) {
            channelBadges = it.channels.map(ch => {
                const label = ch.type === 'clasica' ? 'Clásica' : (ch.type === 'premium' ? 'Premium' : 'Catálogo');
                return `<span class="channel-badge ${ch.type}" style="font-size: 10px; padding: 1px 5px;">${label}</span>`;
            }).join(' ');
        }

        const thumbImg = it.thumbnail 
            ? `<img src="${it.thumbnail}" alt="" style="width: 32px; height: 32px; object-fit: contain; border-radius: 4px; background: #fff; padding: 1px; border: 1px solid var(--border); flex-shrink: 0;">`
            : '';

        const tr = document.createElement('tr');
        tr.style.opacity = isSelected ? '1' : '0.65';
        tr.innerHTML = `
            <td style="text-align: center; vertical-align: middle;">
                <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleItemColecta(${it.id}, this.checked)">
            </td>
            <td style="vertical-align: middle;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    ${thumbImg}
                    <div style="min-width: 0;">
                        <strong style="color: var(--text); font-size: 13px; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 380px;">${it.title}</strong>
                        <div style="font-size: 11px; color: var(--text2); display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                            <span>SKU: <strong>${it.sku || 'Sin SKU'}</strong></span>
                            <span>·</span>
                            <span>Inv: <code>${it.inventory_id || it.item_id}</code></span>
                            ${channelBadges}
                            ${it.variation_name ? `<span>· <em>${it.variation_name}</em></span>` : ''}
                        </div>
                    </div>
                </div>
            </td>
            <td style="text-align: right; vertical-align: middle;">
                <strong>${it.current_stock}</strong> un.
            </td>
            <td style="text-align: right; vertical-align: middle; color: var(--text2);">
                ${it.vpd} un./d
            </td>
            <td style="text-align: right; vertical-align: middle;">
                <span style="color: ${suggested > 0 ? 'var(--accent)' : 'var(--good)'}; font-weight: 700;">${suggested}</span> un.
            </td>
            <td style="text-align: center; vertical-align: middle;">
                <input type="number" min="0" class="unit-input-colecta" 
                       value="${unitsToSend}" 
                       onchange="cambiarUnidadesColecta(${it.id}, this.value)"
                       style="width: 75px; text-align: center; font-weight: 700;">
            </td>
            <td style="text-align: center; vertical-align: middle;">
                <input type="number" min="0" class="unit-input-colecta" 
                       value="${unitsPerBox}" 
                       placeholder="0"
                       title="Unidades por caja máster (0 para caja mixta)"
                       onchange="cambiarUnidadesPorCajaColecta(${it.id}, this.value)"
                       style="width: 65px; text-align: center; font-size: 12px;">
            </td>
            <td style="text-align: center; vertical-align: middle; font-weight: 700; color: #64b5f6;" id="rowBoxes_${it.id}">
                ${boxesEst} cj.
            </td>
        `;
        tbody.appendChild(tr);
    });

    actualizarTotalColecta();
}

function actualizarTotalColecta() {
    let totalUnits = 0;
    let totalSkus = 0;
    let totalBoxes = 0;

    colectaSelectedItems.forEach((units, id) => {
        if (units > 0) {
            totalUnits += units;
            totalSkus += 1;
            const unitsPerBox = colectaBoxUnits.get(id) || 0;
            const boxes = unitsPerBox > 0 ? Math.ceil(units / unitsPerBox) : 1;
            totalBoxes += boxes;

            const rowBoxEl = document.getElementById(`rowBoxes_${id}`);
            if (rowBoxEl) rowBoxEl.textContent = `${boxes} cj.`;
        }
    });

    const skusEl = document.getElementById('colectaTotalSkus');
    const unitsEl = document.getElementById('colectaTotalUnits');
    const boxesEl = document.getElementById('colectaTotalBoxes');

    if (skusEl) skusEl.textContent = totalSkus;
    if (unitsEl) unitsEl.textContent = `${totalUnits} un.`;
    if (boxesEl) boxesEl.textContent = `${totalBoxes} cajas`;
}

function copiarListaColecta() {
    const wh = (WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full).name;
    let texto = `PLAN DE COLECTA ENVIOBOT FULL - ${wh.toUpperCase()}\n`;
    texto += `Fecha: ${new Date().toLocaleDateString('es-AR')}\n`;
    texto += `================================================\n`;

    let totalUnits = 0;
    let totalBoxes = 0;
    itemsData.forEach(it => {
        if (colectaSelectedItems.has(it.id)) {
            const units = colectaSelectedItems.get(it.id) || 0;
            if (units > 0) {
                const uBox = colectaBoxUnits.get(it.id) || 0;
                const boxes = uBox > 0 ? Math.ceil(units / uBox) : 1;
                totalUnits += units;
                totalBoxes += boxes;
                texto += `• [SKU: ${it.sku || it.item_id}] ${it.title}\n`;
                texto += `  Cant: ${units} un. | Cajas: ${boxes} (${uBox > 0 ? `${uBox} un/cj` : 'Bulto mixto'})\n`;
            }
        }
    });

    texto += `================================================\n`;
    texto += `TOTAL: ${totalUnits} unidades en ${totalBoxes} bultos\n`;

    navigator.clipboard.writeText(texto).then(() => {
        showToast("Lista de colecta copiada al portapapeles.", "success");
    }).catch(() => {
        showToast("No se pudo copiar automáticamente.", "error");
    });
}

function exportarColectaCSV() {
    const wh = (WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full).name;
    let csv = `\uFEFFDestino,SKU,Item ID,Inventory ID,Titulo,Stock Actual Full,VPD,Unidades Despachar,Unidades x Caja,Cajas Estimadas\n`;

    itemsData.forEach(it => {
        if (colectaSelectedItems.has(it.id)) {
            const units = colectaSelectedItems.get(it.id) || 0;
            if (units > 0) {
                const uBox = colectaBoxUnits.get(it.id) || 0;
                const boxes = uBox > 0 ? Math.ceil(units / uBox) : 1;
                csv += `"${wh}","${it.sku || ''}","${it.item_id}","${it.inventory_id || ''}","${(it.title || '').replace(/"/g, '""')}",${it.current_stock},${it.vpd},${units},${uBox},${boxes}\n`;
            }
        }
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `colecta_full_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ── Confirmar y Despachar Envío a Backend (Etapa 2) ───────────────────
async function confirmarDespachoColecta() {
    let totalUnits = 0;
    colectaSelectedItems.forEach(u => totalUnits += u);

    if (totalUnits === 0) {
        alert("Seleccioná al menos un producto e indicá unidades mayores a 0 para despachar.");
        return;
    }

    // Comprobar monetización: si no tiene el módulo y no es admin, abrir modal comercial
    if (!userInboundEnabled && !userIsAdmin) {
        const modalUp = document.getElementById('modalInboundUpgrade');
        if (modalUp) modalUp.style.display = 'flex';
        return;
    }

    // Usuario habilitado -> Proceder con la creación del envío
    await crearEnvioInboundBackend();
}

async function crearEnvioInboundBackend() {
    const token = getToken();
    if (!token) {
        alert("Por favor iniciá sesión para registrar la colecta.");
        return;
    }

    const itemsToSend = [];
    itemsData.forEach(it => {
        if (colectaSelectedItems.has(it.id)) {
            const units = colectaSelectedItems.get(it.id) || 0;
            if (units > 0) {
                const unitsPerBox = colectaBoxUnits.get(it.id) || 0;
                const boxCount = unitsPerBox > 0 ? Math.ceil(units / unitsPerBox) : 1;
                itemsToSend.push({
                    item_id: it.item_id,
                    inventory_id: it.inventory_id,
                    variation_id: it.variation_id,
                    variation_name: it.variation_name,
                    sku: it.sku,
                    title: it.title,
                    current_full_stock: it.current_stock,
                    vpd: it.vpd,
                    suggested_units: Math.round(it.vpd * 30),
                    units_to_send: units,
                    units_per_box: unitsPerBox,
                    box_count: boxCount
                });
            }
        }
    });

    const payload = {
        destination_warehouse: 'meli_full',
        target_coverage_days: parseInt(document.getElementById('colectaDiasSelect')?.value, 10) || 30,
        lead_time_days: parseInt(document.getElementById('cfgLeadTime')?.value, 10) || 2,
        transit_days: (WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full).defaultTransit || 3,
        packaging_type: document.getElementById('colectaPackagingSelect')?.value || 'cajas_master',
        carrier_notes: document.getElementById('colectaCarrierNotes')?.value || '',
        pickup_date: document.getElementById('colectaFechaRetiroInput')?.value || null,
        items: itemsToSend
    };

    try {
        const res = await fetch(`${API_BASE}/full/inbound/shipments`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) {
            if (data.requires_upgrade) {
                const modalUp = document.getElementById('modalInboundUpgrade');
                if (modalUp) modalUp.style.display = 'flex';
                return;
            }
            alert(`Error creando envío: ${data.error || 'Verifique los datos.'}`);
            return;
        }

        const shipment = data.shipment;
        alert(`¡Colecta ${shipment.shipment_code} creada con éxito!\n\nSe programaron ${shipment.total_units} unidades en ${shipment.total_boxes} bultos hacia Villa Celina.`);

        // Abrir Remito oficial en pestaña nueva para imprimir
        window.open(`${API_BASE}/full/inbound/shipments/${shipment.id}/remito-html`, '_blank');

        // Cambiar a la pestaña de Historial
        switchColectaTab('historial');
    } catch (err) {
        alert("Error de conexión al crear el envío: " + err.message);
    }
}

async function cargarHistorialColectas(soloBadge = false) {
    const token = getToken();
    const container = document.getElementById('colectaHistorialContainer');
    const badge = document.getElementById('colectaHistorialBadge');
    if (!token) return;

    try {
        const res = await fetch(`${API_BASE}/full/inbound/shipments`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.ok && Array.isArray(data.shipments)) {
            inboundShipmentsList = data.shipments;
            if (badge) badge.textContent = inboundShipmentsList.length;

            if (soloBadge) return;

            if (!container) return;
            if (inboundShipmentsList.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: var(--text2);">
                        <div style="font-size: 32px; margin-bottom: 8px;">📦</div>
                        <strong>No hay envíos registrados todavía.</strong><br>
                        Planificá tu primer despacho desde la pestaña "Planificar Nuevo Envío".
                    </div>
                `;
                return;
            }

            container.innerHTML = inboundShipmentsList.map(sh => {
                const statusMap = {
                    'scheduled': { text: 'Programado / Por Retirar', color: '#64b5f6', bg: 'rgba(33, 150, 243, 0.15)' },
                    'in_transit': { text: 'En Camino a Villa Celina', color: '#ffb74d', bg: 'rgba(255, 152, 0, 0.15)' },
                    'delivered': { text: 'Ingresado en Full', color: '#81c784', bg: 'rgba(76, 175, 80, 0.15)' },
                    'cancelled': { text: 'Cancelado', color: '#9e9e9e', bg: 'rgba(158, 158, 158, 0.15)' }
                };
                const st = statusMap[sh.status] || { text: sh.status, color: '#fff', bg: '#333' };

                return `
                    <div style="background: var(--surf2); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
                            <div>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <strong style="font-size: 15px; color: var(--text);">${sh.shipment_code}</strong>
                                    <span style="background: ${st.bg}; color: ${st.color}; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">
                                        ${st.text}
                                    </span>
                                </div>
                                <div style="font-size: 12px; color: var(--text2); margin-top: 3px;">
                                    Fecha retiro: <strong>${sh.pickup_date || 'A coordinar'}</strong> · Destino: ${sh.destination_name}
                                </div>
                            </div>
                            <div style="display: flex; gap: 6px;">
                                <button type="button" class="btn btn-sm" style="background: var(--accent); color: #111; font-weight: 700;" onclick="window.open('${API_BASE}/full/inbound/shipments/${sh.id}/remito-html', '_blank')">
                                    🖨️ Ver Remito Oficial
                                </button>
                                <select onchange="cambiarEstadoEnvioInbound(${sh.id}, this.value)" class="filter-select" style="padding: 4px 8px; font-size: 11px;">
                                    <option value="scheduled" ${sh.status === 'scheduled' ? 'selected' : ''}>Programado</option>
                                    <option value="in_transit" ${sh.status === 'in_transit' ? 'selected' : ''}>En Camino</option>
                                    <option value="delivered" ${sh.status === 'delivered' ? 'selected' : ''}>Ingresado</option>
                                    <option value="cancelled" ${sh.status === 'cancelled' ? 'selected' : ''}>Cancelar</option>
                                </select>
                                <button type="button" class="btn btn-secondary btn-sm" title="Eliminar envío" onclick="eliminarEnvioInbound(${sh.id})">✕</button>
                            </div>
                        </div>

                        <div style="display: flex; gap: 16px; font-size: 12px; color: var(--text); padding-top: 8px; border-top: 1px dashed var(--border); flex-wrap: wrap;">
                            <div>Total SKUs: <strong>${sh.total_items}</strong></div>
                            <div>Unidades totales: <strong style="color: var(--accent);">${sh.total_units} un.</strong></div>
                            <div>Bultos: <strong>${sh.total_boxes} cajas</strong> (${sh.packaging_type})</div>
                            ${sh.carrier_notes ? `<div>Obs: <em>${sh.carrier_notes}</em></div>` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        if (container) container.innerHTML = `<div style="text-align: center; color: #ef4444; padding: 20px;">Error cargando historial: ${e.message}</div>`;
    }
}

async function cambiarEstadoEnvioInbound(shipmentId, status) {
    const token = getToken();
    if (!token) return;
    try {
        const res = await fetch(`${API_BASE}/full/inbound/shipments/${shipmentId}/status`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ status })
        });
        const data = await res.json();
        if (data.ok) {
            cargarHistorialColectas();
        } else {
            alert(data.error || "No se pudo actualizar el estado.");
        }
    } catch (err) {
        alert("Error de conexión: " + err.message);
    }
}

async function eliminarEnvioInbound(shipmentId) {
    if (!confirm("¿Seguro que deseás eliminar este registro de colecta?")) return;
    const token = getToken();
    if (!token) return;
    try {
        const res = await fetch(`${API_BASE}/full/inbound/shipments/${shipmentId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.ok) {
            cargarHistorialColectas();
        } else {
            alert(data.error || "No se pudo eliminar el envío.");
        }
    } catch (err) {
        alert("Error de conexión: " + err.message);
    }
}

function cerrarModalInboundUpgrade() {
    const modal = document.getElementById('modalInboundUpgrade');
    if (modal) modal.style.display = 'none';
}

function solicitarActivacionInboundWhatsApp() {
    const telefono = "5491148462800";
    const texto = encodeURIComponent("¡Hola Guillermo! Me interesa activar el Módulo Pago de Colectas y Envíos a Full de EnvioBot para mi cuenta. ¿Cómo hacemos?");
    window.open(`https://wa.me/${telefono}?text=${texto}`, '_blank');
}

function abrirModalExplicacionColecta() {
    const modal = document.getElementById('modalExplicacionColecta');
    if (modal) modal.style.display = 'flex';
}

function cerrarModalExplicacionColecta() {
    const modal = document.getElementById('modalExplicacionColecta');
    if (modal) modal.style.display = 'none';
}

// ── Modal de Configuración General y Pestañas ───────────────────────
let recipientsData = [
    { id: 1, name: "Guillermo (Dueño)", phone: "+54 9 11 5555-0001", role: "admin", warehouse_filter: "all", is_verified: 1 },
    { id: 2, name: "Marcos (Depósito)", phone: "+54 9 11 4444-0002", role: "deposito", warehouse_filter: "meli_full", is_verified: 1 }
];
let currentPlanTier = 'pro'; // trial: 1, pro: 2, enterprise: 10
const PLAN_LIMITS = { trial: 1, pro: 2, enterprise: 10 };

function abrirConfiguracion(initialTab = 'meli') {
    document.getElementById('configModal').style.display = 'flex';
    switchConfigTab(initialTab);
    renderizarConfiguracionMeLi();
    renderizarTablaConfiguracionDepositos();
    cargarSettingsBackend();
    cargarDestinatariosBackend();
}

function cerrarConfiguracion() {
    document.getElementById('configModal').style.display = 'none';
}

async function cargarSettingsBackend() {
    const token = getToken();
    if (!token) return;
    try {
        const res = await fetch(`${API_BASE}/full/settings`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.ok && data.settings) {
            const s = data.settings;
            const leadEl = document.getElementById('cfgLeadTime');
            if (leadEl && s.default_lead_time_days !== undefined) {
                leadEl.value = s.default_lead_time_days;
            }
            const safetyEl = document.getElementById('cfgSafetyStock');
            if (safetyEl && s.default_safety_stock_days !== undefined) {
                safetyEl.value = s.default_safety_stock_days;
            }
            const emailEl = document.getElementById('cfgEmail');
            if (emailEl && s.alert_email) {
                emailEl.value = s.alert_email;
            }
            actualizarEstadoVerificacionEmail(s.email_verified);

            // Sincronizar depósitos reales guardados en MariaDB
            if (Array.isArray(s.warehouses) && s.warehouses.length > 0) {
                s.warehouses.forEach(wh => {
                    const whCode = wh.code || wh.id;
                    WAREHOUSES[whCode] = {
                        id: whCode,
                        dbId: wh.id,
                        name: wh.name,
                        city: wh.city || '',
                        defaultTransit: wh.transit_days !== undefined ? wh.transit_days : 5,
                        defaultTarget: wh.target_stock_days !== undefined ? wh.target_stock_days : (s.target_coverage_days || 30)
                    };
                });
                poblarSelectoresDepositos();
                renderizarTablaConfiguracionDepositos();
            }
        }
    } catch (e) {
        console.error("Error cargando settings:", e);
    }
}

async function cargarDestinatariosBackend() {
    const token = getToken();
    if (!token) return;
    try {
        const res = await fetch(`${API_BASE}/full/recipients`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.ok && Array.isArray(data.recipients)) {
            recipientsData = data.recipients;
            if (data.plan_tier) currentPlanTier = data.plan_tier;
            renderizarDestinatariosWA();
        }
    } catch (e) {
        console.error("Error cargando destinatarios:", e);
    }
}

function actualizarEstadoVerificacionEmail(isVerified) {
    const badge = document.getElementById('cfgEmailVerifiedBadge');
    const btnConfirm = document.getElementById('btnVerifyEmailModal');
    if (!badge) return;

    if (isVerified) {
        badge.className = 'badge badge-ok';
        badge.textContent = 'Verificado';
        if (btnConfirm) btnConfirm.style.display = 'none';
    } else {
        badge.className = 'badge badge-warn';
        badge.textContent = 'Pendiente';
        if (btnConfirm) btnConfirm.style.display = 'inline-flex';
    }
}

function abrirModalVerificarEmail() {
    const emailInput = document.getElementById('cfgEmail');
    const email = emailInput ? emailInput.value.trim() : '';
    if (!email) {
        alert("Por favor indicá tu casilla de correo antes de verificar.");
        return;
    }
    const target = document.getElementById('verifyPromptEmailText');
    if (target) target.textContent = email;
    const codeInput = document.getElementById('verifyPromptCodeInput');
    if (codeInput) {
        codeInput.value = '';
        setTimeout(() => codeInput.focus(), 150);
    }
    const modal = document.getElementById('modalVerificarEmailPrompt');
    if (modal) modal.style.display = 'flex';
}

function cerrarModalVerificarEmail() {
    const modal = document.getElementById('modalVerificarEmailPrompt');
    if (modal) modal.style.display = 'none';
}

async function confirmarCodigoEmailManual() {
    const emailInput = document.getElementById('cfgEmail');
    const email = emailInput ? emailInput.value.trim() : '';
    const codeInput = document.getElementById('verifyPromptCodeInput');
    const code = codeInput ? codeInput.value.trim() : '';

    if (!code || code.length !== 6) {
        alert("Por favor ingresá el código de 6 dígitos que enviamos a tu correo.");
        if (codeInput) codeInput.focus();
        return;
    }

    const token = getToken();
    try {
        let headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`${API_BASE}/full/verify/check-email`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ code: code, email: email })
        });
        const data = await res.json();
        if (data.ok && data.verified) {
            actualizarEstadoVerificacionEmail(true);
            cerrarModalVerificarEmail();
            alert("¡Casilla de correo vinculada y confirmada con éxito!");
        } else {
            alert(data.error || "Código incorrecto o vencido.");
        }
    } catch (e) {
        alert("Error de conexión: " + e.message);
    }
}

async function solicitarReenvioCodigoEmail(e) {
    if (e) e.preventDefault();
    const emailInput = document.getElementById('cfgEmail');
    const email = emailInput ? emailInput.value.trim() : '';
    if (!email) {
        alert("Completá tu correo electrónico primero.");
        return;
    }

    const token = getToken();
    try {
        let headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`${API_BASE}/full/verify/send-email`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ email: email })
        });
        const data = await res.json();
        if (data.ok) {
            alert(`Código de vinculación reenviado a ${email}.\nRevisá tu bandeja de entrada o spam.`);
        } else {
            alert(data.error || "No se pudo reenviar el código.");
        }
    } catch (e) {
        alert("Error de conexión: " + e.message);
    }
}

function renderizarTablaConfiguracionDepositos() {
    const tbody = document.getElementById('cfgDepotsTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    Object.values(WAREHOUSES).forEach(wh => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>
                <strong style="color: var(--text); font-size: 13.5px;">${wh.name}</strong><br>
                <small style="color: var(--text2); font-size: 11.5px;">Código: ${wh.id}</small>
            </td>
            <td style="color: var(--text2); font-size: 12.5px;">${wh.city || '—'}</td>
            <td style="text-align: center; white-space: nowrap;">
                <span style="display: inline-flex; align-items: center; justify-content: center; gap: 4px; white-space: nowrap;">
                    <input type="number" min="1" max="99" class="input-days-2digit" 
                           id="cfgTransit_${wh.id}" value="${wh.defaultTransit}"
                           oninput="if(this.value.length>2) this.value=this.value.slice(0,2);"
                           title="Días de demora del flete a este depósito">
                    <span style="color: var(--text2); font-size: 12px; font-weight: 600;">d</span>
                </span>
            </td>
            <td style="text-align: center; white-space: nowrap;">
                <span style="display: inline-flex; align-items: center; justify-content: center; gap: 4px; white-space: nowrap;">
                    <input type="number" min="1" max="99" class="input-days-2digit" 
                           id="cfgTarget_${wh.id}" value="${wh.defaultTarget}"
                           oninput="if(this.value.length>2) this.value=this.value.slice(0,2);"
                           title="Días de stock a cubrir para este depósito">
                    <span style="color: var(--text2); font-size: 12px; font-weight: 600;">d</span>
                </span>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function switchConfigTab(tab) {
    const tabMeli = document.getElementById('configTabMeli');
    const tabGeneral = document.getElementById('configTabGeneral');
    const tabWA = document.getElementById('configTabWhatsapp');
    const tabTeam = document.getElementById('configTabTeam');

    const btnMeli = document.getElementById('tabBtnMeli');
    const btnGeneral = document.getElementById('tabBtnGeneral');
    const btnWA = document.getElementById('tabBtnWhatsapp');
    const btnTeam = document.getElementById('tabBtnTeam');

    const btnSave = document.getElementById('btnConfigSave');
    const btnCancel = document.getElementById('btnConfigCancel');

    [btnMeli, btnGeneral, btnWA, btnTeam].forEach(b => { if (b) b.classList.remove('active'); });
    [tabMeli, tabGeneral, tabWA, tabTeam].forEach(t => { if (t) t.style.display = 'none'; });

    if (tab === 'meli') {
        if (tabMeli) tabMeli.style.display = 'block';
        if (btnMeli) btnMeli.classList.add('active');
        if (btnSave) btnSave.style.display = 'none';
        if (btnCancel) btnCancel.textContent = 'Cerrar';
        renderizarConfiguracionMeLi();
    } else if (tab === 'general') {
        if (tabGeneral) tabGeneral.style.display = 'block';
        if (btnGeneral) btnGeneral.classList.add('active');
        if (btnSave) btnSave.style.display = 'inline-block';
        if (btnCancel) btnCancel.textContent = 'Cancelar';
        renderizarTablaConfiguracionDepositos();
    } else if (tab === 'whatsapp') {
        if (tabWA) tabWA.style.display = 'block';
        if (btnWA) btnWA.classList.add('active');
        if (btnSave) btnSave.style.display = 'none';
        if (btnCancel) btnCancel.textContent = 'Cerrar';
        renderizarDestinatariosWA();
    } else if (tab === 'team') {
        if (tabTeam) tabTeam.style.display = 'block';
        if (btnTeam) btnTeam.classList.add('active');
        if (btnSave) btnSave.style.display = 'none';
        if (btnCancel) btnCancel.textContent = 'Cerrar';
        cargarMiembrosEquipo();
    }
}

// ── GESTIÓN DE EQUIPO Y COLABORADORES (FRAN / MIEMBROS) ───────────────
async function cargarMiembrosEquipo() {
    const tbody = document.getElementById('cfgTeamTableBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 20px; color: var(--text2);">Cargando colaboradores...</td></tr>';

    const token = getToken();
    if (!token) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 20px; color: var(--text2);">Iniciá sesión para ver tu equipo.</td></tr>';
        return;
    }

    try {
        const resp = await fetch(`${API_BASE}/full/team/members`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await resp.json();
        if (!data.ok || !Array.isArray(data.members)) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 20px; color: var(--text2);">No hay colaboradores registrados todavía.</td></tr>';
            return;
        }

        if (data.members.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 20px; color: var(--text2);">No tenés colaboradores en tu equipo aún. Podés invitar a Fran arriba.</td></tr>';
            return;
        }

        tbody.innerHTML = '';
        data.members.forEach(m => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid var(--border)';
            const fecha = m.created_at ? m.created_at.split(' ')[0] : '—';
            tr.innerHTML = `
                <td style="padding: 10px;">
                    <strong style="color: var(--text);">${m.full_name || 'Sin nombre'}</strong>
                </td>
                <td style="padding: 10px; font-family: monospace; color: var(--text2);">${m.email}</td>
                <td style="padding: 10px;">
                    <span class="role-badge role-deposito" style="font-size: 11px;">${m.employee_label || 'Colaborador'}</span>
                </td>
                <td style="padding: 10px; color: var(--text2); font-size: 12px;">${fecha}</td>
                <td style="padding: 10px; text-align: right;">
                    <button type="button" class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 11px; color: #ff6b6b;"
                            onclick="eliminarMiembroEquipo(${m.id}, '${m.full_name || m.email}')" title="Eliminar acceso">
                        Quitar
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Error cargando equipo:", e);
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 20px; color: #ff6b6b;">Error de conexión con el servidor.</td></tr>';
    }
}

async function invitarMiembroEquipo(e) {
    if (e && e.preventDefault) e.preventDefault();
    const nameEl = document.getElementById('newTeamName');
    const emailEl = document.getElementById('newTeamEmail');
    const passEl = document.getElementById('newTeamPassword');
    const resEl = document.getElementById('newTeamInviteResult');

    const name = nameEl ? nameEl.value.trim() : '';
    const email = emailEl ? emailEl.value.trim().toLowerCase() : '';
    const pass = passEl ? passEl.value.trim() : '';

    if (!email) {
        alert("Ingresá el correo electrónico del colaborador a invitar.");
        return;
    }

    const token = getToken();
    if (!token) {
        alert("Iniciá sesión para invitar miembros a tu equipo.");
        return;
    }

    try {
        const resp = await fetch(`${API_BASE}/full/team/invite`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({
                full_name: name || 'Colaborador',
                email: email,
                password: pass
            })
        });
        const data = await resp.json();
        if (!data.ok) {
            alert(data.error || "No se pudo invitar al colaborador.");
            return;
        }

        const clave = data.initial_password;
        if (resEl) {
            resEl.style.display = 'block';
            resEl.innerHTML = `<strong>Acceso listo para ${name || email}:</strong><br>Email: <code>${email}</code><br>Contraseña: <strong><code>${clave}</code></strong><br><small style="color: var(--text2);">Pasale estos datos a ${name || 'tu colaborador'} para que ingrese directamente en Enviobot Full.</small>`;
        }
        showToast(`Colaborador ${name || email} habilitado exitosamente.`, "success");
        
        if (nameEl) nameEl.value = '';
        if (emailEl) emailEl.value = '';
        if (passEl) passEl.value = '';

        cargarMiembrosEquipo();
    } catch (err) {
        console.error("Error invitando miembro:", err);
        showToast(`Error de red: ${err.message}`, "error");
    }
}

async function eliminarMiembroEquipo(memberId, memberName) {
    if (!confirm(`¿Estás seguro de que deseás revocar el acceso a ${memberName}?`)) {
        return;
    }
    const token = getToken();
    if (!token) return;
    try {
        const resp = await fetch(`${API_BASE}/full/team/members/${memberId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await resp.json();
        if (data.ok) {
            showToast(`Acceso de ${memberName} revocado correctamente.`, "info");
            cargarMiembrosEquipo();
        } else {
            showToast(data.error || "No se pudo remover al colaborador.", "error");
        }
    } catch (e) {
        console.error("Error eliminando miembro:", e);
        showToast(`Error al contactar al servidor: ${e.message}`, "error");
    }
}

async function renderizarConfiguracionMeLi() {
    const tbody = document.getElementById('cfgMeliAccountsTableBody');
    const countEl = document.getElementById('cfgMeliAccountsCount');
    const maxEl = document.getElementById('cfgMeliAccountsMax');
    const btnConnect = document.getElementById('btnConnectMeLiModal');
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:18px; color:var(--text2);">Consultando cuentas de Mercado Libre...</td></tr>`;

    let accounts = (currentUser && currentUser.ml_accounts) ? currentUser.ml_accounts : [];
    let maxAllowed = (currentUser && currentUser.limits && currentUser.limits.max_ml_accounts) ? currentUser.limits.max_ml_accounts : 3;

    try {
        const token = getToken();
        if (token) {
            const res = await fetch(`${API_BASE}/full/ml/accounts`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            if (data.ok && data.accounts) {
                accounts = data.accounts;
                if (data.limits && data.limits.max_ml_accounts) {
                    maxAllowed = data.limits.max_ml_accounts;
                }
            }
        }
    } catch (e) {
        console.warn("Error consultando cuentas MeLi para config:", e);
    }

    if (countEl) countEl.textContent = accounts.length;
    if (maxEl) maxEl.textContent = maxAllowed;
    if (btnConnect) {
        btnConnect.disabled = accounts.length >= maxAllowed;
        if (accounts.length >= maxAllowed) {
            btnConnect.title = `Límite alcanzado (${maxAllowed} cuentas permitidas por tu plan).`;
        } else {
            btnConnect.title = "Vincular otra cuenta de Mercado Libre";
        }
    }

    if (accounts.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" style="text-align: center; padding: 28px 14px; color: var(--text2);">
                    <div style="font-size: 13.5px; font-weight: 700; color: var(--text); margin-bottom: 6px;">No tenés cuentas de Mercado Libre vinculadas</div>
                    <div style="font-size: 12px; max-width: 440px; margin: 0 auto 14px auto; line-height: 1.5;">Para que EnvioBot Full monitoree tu stock en el depósito de Villa Celina y pronostique tus fechas de quiebre, vinculá tu tienda.</div>
                    <button type="button" onclick="iniciarConexionMeLi()" class="btn btn-sm" style="padding: 7px 18px; font-size: 12px; font-weight: 700;">Conectar Mercado Libre</button>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = '';
    accounts.forEach(acc => {
        const nickname = acc.ml_nickname || `Vendedor ${acc.ml_user_id}`;
        const isValid = acc.is_valid !== false && acc.is_active !== false && acc.is_active !== 0;
        const statusBadge = isValid 
            ? `<span class="badge badge-ok" style="font-size: 11px;">Conectada</span>`
            : `<span class="badge badge-warn" style="font-size: 11px;">Re-autorizar</span>`;

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="width: 28px; height: 28px; border-radius: 6px; background: var(--surf2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 11px; color: var(--accent);">
                        ML
                    </div>
                    <div>
                        <strong style="color: var(--text); font-size: 13.5px;">${nickname}</strong>
                        <div style="font-size: 11px; color: var(--text2);">Depósito Full (Villa Celina)</div>
                    </div>
                </div>
            </td>
            <td style="color: var(--text2); font-size: 12.5px; font-family: monospace;">${acc.ml_user_id}</td>
            <td style="text-align: center;">${statusBadge}</td>
            <td style="text-align: right;">
                <button type="button" onclick="desconectarCuentaMeLi(${acc.id}, '${nickname.replace(/'/g, "\\'")}')" 
                        class="btn btn-secondary btn-sm" 
                        style="color: var(--danger); border-color: rgba(255, 82, 82, 0.3); font-size: 11.5px; padding: 4px 10px;"
                        title="Desvincular esta cuenta de Mercado Libre">
                    Desconectar
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function desconectarCuentaMeLi(accId, nickname) {
    if (!confirm(`¿Estás seguro de que deseás desconectar la cuenta "${nickname}" de Mercado Libre?\n\nSe desvinculará la sincronización y se eliminarán sus publicaciones de EnvioBot Full.`)) {
        return;
    }

    const token = getToken();
    try {
        const res = await fetch(`${API_BASE}/full/ml/accounts/${accId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.ok) {
            alert(`Cuenta "${nickname}" desvinculada exitosamente.`);
            await checkUserSession();
            await renderizarConfiguracionMeLi();
            await cargarDatos();
        } else {
            alert("Error al desvincular la cuenta: " + (data.error || "Ocurrió un error."));
        }
    } catch (err) {
        alert("Error de conexión al desvincular cuenta: " + err.message);
    }
}

// ── Gestión de Destinatarios de WhatsApp ───────────────────────────
function renderizarDestinatariosWA() {
    const tbody = document.getElementById('recipientsTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const maxAllowed = PLAN_LIMITS[currentPlanTier] || 2;
    const badgeTier = document.getElementById('waPlanBadge');
    if (badgeTier) badgeTier.textContent = `Plan ${currentPlanTier.toUpperCase()}`;
    const countUsedEl = document.getElementById('waCountUsed');
    if (countUsedEl) countUsedEl.textContent = recipientsData.length;
    const maxAllowedEl = document.getElementById('waMaxAllowed');
    if (maxAllowedEl) maxAllowedEl.textContent = maxAllowed;

    const limitMsg = document.getElementById('waLimitReachedMsg');
    const addBox = document.getElementById('addRecipientBox');

    if (recipientsData.length >= maxAllowed) {
        if (limitMsg) limitMsg.style.display = 'block';
        if (addBox) addBox.style.opacity = '0.5';
    } else {
        if (limitMsg) limitMsg.style.display = 'none';
        if (addBox) addBox.style.opacity = '1';
    }

    if (recipientsData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text2); padding: 15px;">No tenés números de WhatsApp configurados todavía.</td></tr>';
        return;
    }

    recipientsData.forEach(r => {
        const tr = document.createElement('tr');
        let roleBadgeClass = 'role-admin';
        let roleLabel = 'Dueño';
        if (r.role === 'deposito') { roleBadgeClass = 'role-deposito'; roleLabel = 'Depósito'; }
        if (r.role === 'flete') { roleBadgeClass = 'role-flete'; roleLabel = 'Fletero'; }

        const whName = r.warehouse_filter === 'all' ? 'Todos' : (WAREHOUSES[r.warehouse_filter]?.name || r.warehouse_filter);

        const isVerified = (r.is_verified === 1 || r.is_verified === true || r.is_verified === '1');
        const verifBadge = isVerified 
            ? `<span class="badge badge-ok" style="font-size: 10px; margin-left: 6px;">Verificado</span>`
            : `<span class="badge badge-warn" style="font-size: 10px; margin-left: 6px;">Pendiente</span>`;

        tr.innerHTML = `
            <td>
                <strong>${r.name}</strong>
                ${verifBadge}
            </td>
            <td style="font-family: monospace; color: var(--text);">${r.phone}</td>
            <td><span class="role-badge ${roleBadgeClass}">${roleLabel}</span></td>
            <td style="color: var(--text2); font-size: 11px;">${whName}</td>
            <td style="text-align: right;">
                <button class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 11px; margin-right: 4px;" 
                        onclick="probarDestinatarioWA('${r.phone}', '${r.name}')" title="Enviar WhatsApp de prueba">
                    Probar
                </button>
                <button class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 11px; color: #ff6b6b;" 
                        onclick="eliminarDestinatarioWA(${r.id})" title="Eliminar número">
                    Quitar
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function agregarDestinatarioWA() {
    const maxAllowed = PLAN_LIMITS[currentPlanTier] || 2;
    if (recipientsData.length >= maxAllowed) {
        alert(`Alcanzaste el límite de ${maxAllowed} números de tu Plan ${currentPlanTier.toUpperCase()}.\n\nPara agregar más integrantes de tu equipo (depósito, fleteros), mejorá al Plan Enterprise.`);
        return;
    }

    const name = document.getElementById('newRecipName').value.trim();
    const phone = document.getElementById('newRecipPhone').value.trim();
    const role = document.getElementById('newRecipRole').value;
    const depot = document.getElementById('newRecipDepot').value;

    if (!name || !phone) {
        alert("Por favor completá el nombre y el celular (ej: +54 9 11 1234-5678).");
        return;
    }

    const token = getToken();
    if (token) {
        try {
            const resp = await fetch(`${API_BASE}/full/recipients`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({
                    name: name,
                    phone: phone,
                    role: role,
                    warehouse_filter: depot
                })
            });
            const data = await resp.json();
            if (!data.ok) {
                alert(data.error || "No se pudo agregar el destinatario.");
                return;
            }
            alert(`Destinatario ${name} agregado con éxito.\nSe envió un mensaje de bienvenida y verificación por WhatsApp a ${phone}.`);
            await cargarDestinatariosBackend();
            document.getElementById('newRecipName').value = '';
            document.getElementById('newRecipPhone').value = '';
            return;
        } catch (e) {
            console.error("Error agregando destinatario en backend:", e);
        }
    }

    const nuevo = {
        id: Date.now(),
        name: name,
        phone: phone,
        role: role,
        warehouse_filter: depot,
        is_verified: 1
    };

    recipientsData.push(nuevo);
    document.getElementById('newRecipName').value = '';
    document.getElementById('newRecipPhone').value = '';

    renderizarDestinatariosWA();
    alert(`Número de WhatsApp de ${name} agregado con éxito.`);
}

async function eliminarDestinatarioWA(id) {
    if (confirm("¿Seguro que deseás quitar este número de las alertas de WhatsApp?")) {
        const token = getToken();
        if (token) {
            try {
                await fetch(`${API_BASE}/full/recipients/${id}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
            } catch (e) {
                console.error("Error eliminando destinatario:", e);
            }
        }
        recipientsData = recipientsData.filter(x => x.id !== id);
        renderizarDestinatariosWA();
    }
}

async function probarDestinatarioWA(phone, name) {
    const token = getToken();
    if (token) {
        try {
            const resp = await fetch(`${API_BASE}/full/recipients/test-whatsapp`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ phone: phone, name: name })
            });
            const data = await resp.json();
            if (data.ok) {
                alert(`WhatsApp enviado a ${phone} (${name}).\n\nRespuesta:\n"${data.preview}"`);
                return;
            } else {
                alert(`Error enviando WhatsApp a ${phone}:\n${data.error || 'Verifique la conexión con Evolution API / Gateway.'}`);
                return;
            }
        } catch (e) {
            console.error('Error probando WhatsApp:', e);
        }
    }
    // Fallback demo/local sin backend
    alert(`WhatsApp de prueba enviado con éxito a ${phone} (${name}):\n\n"Alarma EnvioBot Full\nHola ${name}, tenés publicaciones en fecha límite de reposición para Mercado Envíos Full. Se deben preparar las unidades para el camión de hoy."`);
}

async function probarEmailSaliente() {
    const emailInput = document.getElementById('cfgEmail');
    const email = emailInput ? emailInput.value.trim() : '';
    if (!email) {
        alert("Por favor indicá un correo destinatario para recibir la prueba.");
        if (emailInput) emailInput.focus();
        return;
    }

    const btn = document.getElementById('btnTestEmail');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Enviando...';
    }

    const token = getToken();
    if (token) {
        try {
            const resp = await fetch(`${API_BASE}/full/settings/test-email`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ email: email })
            });
            const data = await resp.json();
            if (data.ok) {
                alert(`Correo de prueba enviado con éxito a: ${email}\n\nDetalle del servidor:\n${data.detail?.subject || 'Reporte de prueba enviado'}`);
                return;
            } else {
                alert(`Error al enviar correo de prueba a ${email}:\n\n${data.error || data.detail?.error || 'Verifique la configuración SMTP de DonWeb en backend/.env'}`);
                return;
            }
        } catch (e) {
            console.error('Error probando email:', e);
            alert(`Error de conexión con el servidor: ${e.message}`);
            return;
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Probar Envío';
            }
        }
    }

    // Fallback demo/local sin backend
    setTimeout(() => {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Probar Envío';
        }
        alert(`[Modo Demo] Correo de prueba simulado hacia ${email}.\n\nRemitente configurado: alertas@enviobot.com.ar (DonWeb SMTP: smtp.donweb.com:465)`);
    }, 400);
}

async function forzarEvaluacionAlertas() {
    const token = getToken();
    if (!token) {
        alert("En modo demostración local. Para disparar alertas en vivo conectá tu backend.");
        return;
    }
    try {
        const resp = await fetch(`${API_BASE}/full/alerts/trigger-now`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await resp.json();
        if (data.ok) {
            alert(`Evaluación de alertas ejecutada:\n\n• Publicaciones evaluadas\n• WhatsApps enviados: ${data.data?.mensajes_whatsapp_enviados || 0}\n• Email enviado: ${data.data?.email_enviado ? 'Sí' : 'No'}`);
        } else {
            alert(`Error: ${data.error}`);
        }
    } catch (e) {
        alert(`Error conectando con el servidor: ${e.message}`);
    }
}

function mostrarInfoUpgrade() {
    alert("PLANES DE ALERTAS DE WHATSAPP MULTIUSUARIO:\n\n• Plan Pro: Hasta 2 números incluidos.\n• Plan Enterprise: Hasta 10 números ($14.900 ARS/mes adicionales o USD 15/mes).\n\nIdeal para notificar en simultáneo al dueño, encargados de depósito y choferes de flete.");
}

async function guardarConfiguracion(e) {
    e.preventDefault();
    const lt = parseInt(document.getElementById('cfgLeadTime').value, 10) || 5;
    const ss = parseInt(document.getElementById('cfgSafetyStock').value, 10) || 2;
    const email = document.getElementById('cfgEmail').value;

    const warehousesList = [];
    let generalTarget = 30;

    // Actualizar parámetros individuales de cada depósito
    Object.values(WAREHOUSES).forEach(wh => {
        const transitEl = document.getElementById(`cfgTransit_${wh.id}`);
        const targetEl = document.getElementById(`cfgTarget_${wh.id}`);
        if (transitEl && targetEl) {
            const newTransit = Math.max(1, parseInt(transitEl.value, 10) || wh.defaultTransit);
            const newTarget = Math.max(5, parseInt(targetEl.value, 10) || wh.defaultTarget);
            wh.defaultTransit = newTransit;
            wh.defaultTarget = newTarget;

            if (wh.id === currentWarehouse || wh.id === 'meli_full') {
                generalTarget = newTarget;
            }

            warehousesList.push({
                id: wh.dbId,
                code: wh.id,
                name: wh.name,
                city: wh.city,
                transit_days: newTransit,
                target_stock_days: newTarget
            });

            // Actualizar catálogo demo para este depósito
            BASE_ITEMS_CATALOG.forEach(it => {
                if (it.depots && it.depots[wh.id]) {
                    it.depots[wh.id].transit_days = newTransit;
                    it.depots[wh.id].target_days = newTarget;
                    it.depots[wh.id].buffer = ss;
                }
            });
        }
    });

    // Actualizar publicaciones del depósito activo actual
    const activeWh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    itemsData.forEach(it => {
        it.lead_time_days = lt;
        it.transit_delay_days = activeWh.defaultTransit;
        it.target_stock_days = activeWh.defaultTarget;
        it.buffer_days = ss;
    });

    poblarSelectoresDepositos();
    recalcularTodo();

    const token = getToken();
    if (token) {
        try {
            await fetch(`${API_BASE}/full/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({
                    default_lead_time_days: lt,
                    default_safety_stock_days: ss,
                    target_coverage_days: generalTarget,
                    alert_email: email,
                    warehouses: warehousesList
                })
            });
        } catch (err) {
            console.error("Error guardando settings:", err);
        }
    }

    cerrarConfiguracion();
    showToast("Configuración guardada correctamente en tu cuenta.", "success");
}

// ── MODAL: Alta de Nuevo Depósito ─────────────────────────────────
function abrirModalNuevoDeposito() {
    const modal = document.getElementById('depotModal');
    if (modal) {
        modal.style.display = 'flex';
        const nameInput = document.getElementById('newDepotName');
        if (nameInput) nameInput.focus();
    }
}

function cerrarModalNuevoDeposito() {
    const modal = document.getElementById('depotModal');
    if (modal) modal.style.display = 'none';
}

function guardarNuevoDeposito(e) {
    e.preventDefault();
    const name = document.getElementById('newDepotName').value.trim();
    const city = document.getElementById('newDepotCity').value.trim();
    const transit = parseInt(document.getElementById('newDepotTransit').value, 10) || 3;
    const target = parseInt(document.getElementById('newDepotTarget').value, 10) || 25;

    if (!name || !city) {
        alert("Por favor completá el nombre y la ciudad del depósito.");
        return;
    }

    const depotId = 'depot_' + Date.now();
    WAREHOUSES[depotId] = {
        id: depotId,
        name: name,
        city: city,
        defaultTransit: transit,
        defaultTarget: target
    };

    // Agregar al selector principal de depósitos
    const select = document.getElementById('activeWarehouseSelect');
    if (select) {
        const option = document.createElement('option');
        option.value = depotId;
        option.textContent = name;
        select.appendChild(option);
        select.value = depotId;
    }

    // Agregar al selector del modal de WhatsApp
    const recipSelect = document.getElementById('newRecipDepot');
    if (recipSelect) {
        const opt = document.createElement('option');
        opt.value = depotId;
        opt.textContent = `Solo ${name}`;
        recipSelect.appendChild(opt);
    }

    // Inicializar stocks demo para el nuevo depósito
    BASE_ITEMS_CATALOG.forEach(it => {
        if (!it.depots[depotId]) {
            it.depots[depotId] = {
                stock: Math.floor(Math.random() * 20),
                transit_days: transit,
                target_days: target,
                buffer: 2,
                vpd: Math.round((Math.random() * 3 + 0.5) * 10) / 10
            };
        }
    });

    // Guardar en backend si hay sesión activa
    const token = getToken();
    if (token) {
        fetch(`${API_BASE}/full/warehouses`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({
                code: depotId,
                name: name,
                city: city,
                transit_days: transit,
                target_stock_days: target
            })
        }).catch(err => console.error("Error guardando nuevo depósito:", err));
    }

    // Limpiar formulario y cerrar modal
    document.getElementById('newDepotName').value = '';
    document.getElementById('newDepotCity').value = '';
    cerrarModalNuevoDeposito();

    // Cambiar inmediatamente al nuevo depósito creado
    cambiarDeposito(depotId);
    showToast(`Depósito "${name}" agregado con éxito.`, "success");
}

// ── Manejo de Autenticación Rápida (Estilo Enviobot Pedidos) ─────────
function abrirModalAuth(tab = 'login') {
    cambiarAuthTab(tab);
    const modal = document.getElementById('modalAuth');
    if (modal) modal.style.display = 'flex';
}

function cerrarModalAuth() {
    const modal = document.getElementById('modalAuth');
    if (modal) modal.style.display = 'none';
}

function cambiarAuthTab(tab) {
    currentAuthTab = tab;
    const tabLogin = document.getElementById('tabAuthLogin');
    const tabReg = document.getElementById('tabAuthRegister');
    const nameGroup = document.getElementById('authNameGroup');
    const btnSubmit = document.getElementById('btnAuthSubmit');
    const errBox = document.getElementById('authErrorMsg');
    if (errBox) errBox.style.display = 'none';

    if (tab === 'login') {
        if (tabLogin) tabLogin.classList.add('active');
        if (tabReg) tabReg.classList.remove('active');
        if (nameGroup) nameGroup.style.display = 'none';
        if (btnSubmit) btnSubmit.textContent = 'Ingresar';
    } else {
        if (tabReg) tabReg.classList.add('active');
        if (tabLogin) tabLogin.classList.remove('active');
        if (nameGroup) nameGroup.style.display = 'flex';
        if (btnSubmit) btnSubmit.textContent = 'Crear Cuenta (30d gratis)';
    }
}

async function handleAuthSubmit(e) {
    e.preventDefault();
    const email = document.getElementById('authEmail').value.trim();
    const password = document.getElementById('authPassword').value.trim();
    const name = document.getElementById('authName') ? document.getElementById('authName').value.trim() : '';
    const errBox = document.getElementById('authErrorMsg');
    const btnSubmit = document.getElementById('btnAuthSubmit');

    btnSubmit.disabled = true;
    btnSubmit.textContent = 'Procesando...';
    if (errBox) errBox.style.display = 'none';

    try {
        const endpoint = currentAuthTab === 'login' ? `${API_BASE}/full/auth/login` : `${API_BASE}/full/auth/register`;
        const payload = currentAuthTab === 'login' ? { email, password } : { email, password, full_name: name };

        let res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        // Fallback a ruta estándar si no estuviera prefijada
        if (res.status === 404) {
            const fallbackEndpoint = currentAuthTab === 'login' ? `${API_BASE}/auth/login` : `${API_BASE}/auth/register`;
            res = await fetch(fallbackEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        const data = await res.json();
        if (!data.ok) {
            throw new Error(data.error || 'Ocurrió un error al autenticar.');
        }

        // Guardar token en localStorage
        localStorage.setItem('enviobot_full_token', data.token);
        localStorage.setItem('token', data.token);
        cerrarModalAuth();

        if (data.existing_user_linked) {
            alert(data.message || 'Detectamos tu cuenta de EnvioBot Pedidos. Se habilitó EnvioBot Full con tu contraseña habitual.');
        }

        // Si es un usuario existente pero NO tiene suscripción a EnvioBot Full:
        if (data.user && data.user.has_full_access === false) {
            currentUser = data.user;
            actualizarBadgePlan(data.user);
            if (data.user.can_start_trial) {
                abrirModalActivarFull(data.user);
            } else {
                abrirModalSuscripcionVencida(data.user);
            }
            return;
        }

        if (data.requires_ml_connect || (data.user && (!data.user.ml_accounts || data.user.ml_accounts.length === 0))) {
            abrirOnboardingMeLi();
        }

        await checkUserSession();
        cargarDatos();

    } catch (err) {
        if (errBox) {
            errBox.textContent = err.message;
            errBox.style.display = 'block';
        } else {
            alert(err.message);
        }
    } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = currentAuthTab === 'login' ? 'Ingresar' : 'Crear Cuenta (30d gratis)';
    }
}

// ── Manejo de Login / Registro Directo en la Pantalla Principal ───
let currentMainAuthTab = 'login';

function cambiarAuthMain(tab) {
    currentMainAuthTab = tab;
    const tabLogin = document.getElementById('tabMainLogin');
    const tabReg = document.getElementById('tabMainRegister');
    const nameGroup = document.getElementById('mainNameGroup');
    const btnSubmit = document.getElementById('btnMainAuthSubmit');
    const toggleText = document.getElementById('mainAuthToggleText');
    const toggleLink = document.getElementById('mainAuthToggleLink');
    const errBox = document.getElementById('mainAuthErrorMsg');
    if (errBox) errBox.style.display = 'none';

    if (tab === 'login') {
        if (tabLogin) {
            tabLogin.style.color = 'var(--accent)';
            tabLogin.style.fontWeight = '700';
            tabLogin.style.borderBottom = '2px solid var(--accent)';
        }
        if (tabReg) {
            tabReg.style.color = 'var(--text2)';
            tabReg.style.fontWeight = '600';
            tabReg.style.borderBottom = 'none';
        }
        if (nameGroup) nameGroup.style.display = 'none';
        if (btnSubmit) btnSubmit.textContent = 'Ingresar a EnvioBot Full';
        if (toggleText) toggleText.textContent = '¿No tenés cuenta todavía?';
        if (toggleLink) toggleLink.textContent = 'Crear cuenta (30 días gratis)';
    } else {
        if (tabReg) {
            tabReg.style.color = 'var(--accent)';
            tabReg.style.fontWeight = '700';
            tabReg.style.borderBottom = '2px solid var(--accent)';
        }
        if (tabLogin) {
            tabLogin.style.color = 'var(--text2)';
            tabLogin.style.fontWeight = '600';
            tabLogin.style.borderBottom = 'none';
        }
        if (nameGroup) nameGroup.style.display = 'block';
        if (btnSubmit) btnSubmit.textContent = 'Crear cuenta (30 días de prueba gratis)';
        if (toggleText) toggleText.textContent = '¿Ya tenés una cuenta registrada?';
        if (toggleLink) toggleLink.textContent = 'Iniciar sesión aquí';
    }
}

function toggleMainAuthMode(e) {
    if (e) e.preventDefault();
    cambiarAuthMain(currentMainAuthTab === 'login' ? 'register' : 'login');
}

async function handleMainAuthSubmit(e) {
    e.preventDefault();
    const email = document.getElementById('mainAuthEmail').value.trim();
    const password = document.getElementById('mainAuthPassword').value.trim();
    const name = document.getElementById('mainAuthName') ? document.getElementById('mainAuthName').value.trim() : '';
    const errBox = document.getElementById('mainAuthErrorMsg');
    const btnSubmit = document.getElementById('btnMainAuthSubmit');

    btnSubmit.disabled = true;
    btnSubmit.textContent = 'Procesando...';
    if (errBox) errBox.style.display = 'none';

    try {
        const endpoint = currentMainAuthTab === 'login' ? `${API_BASE}/full/auth/login` : `${API_BASE}/full/auth/register`;
        const payload = currentMainAuthTab === 'login' ? { email, password } : { email, password, full_name: name };

        let res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.status === 404) {
            const fallbackEndpoint = currentMainAuthTab === 'login' ? `${API_BASE}/auth/login` : `${API_BASE}/auth/register`;
            res = await fetch(fallbackEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        const data = await res.json();
        if (!data.ok) {
            throw new Error(data.error || 'Ocurrió un error al autenticar.');
        }

        localStorage.setItem('enviobot_full_token', data.token);
        localStorage.setItem('token', data.token);

        if (data.existing_user_linked) {
            alert(data.message || 'Detectamos tu cuenta de EnvioBot Pedidos. Se habilitó EnvioBot Full con tu contraseña habitual.');
        }

        if (data.user && data.user.has_full_access === false) {
            currentUser = data.user;
            actualizarBadgePlan(data.user);
            if (data.user.can_start_trial) {
                abrirModalActivarFull(data.user);
            } else {
                abrirModalSuscripcionVencida(data.user);
            }
            return;
        }

        if (data.requires_ml_connect || (data.user && (!data.user.ml_accounts || data.user.ml_accounts.length === 0))) {
            abrirOnboardingMeLi();
        }

        await checkUserSession();
        cargarDatos();

    } catch (err) {
        if (errBox) {
            errBox.textContent = err.message;
            errBox.style.display = 'block';
        } else {
            alert(err.message);
        }
    } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = currentMainAuthTab === 'login' ? 'Ingresar a EnvioBot Full' : 'Crear cuenta (30 días de prueba gratis)';
    }
}

function entrarModoDemo(e) {
    if (e) e.preventDefault();
    cerrarModalAuth();
    // Renderizar demo
    cargarDatos();
}

function cerrarSesion() {
    localStorage.removeItem('enviobot_full_token');
    localStorage.removeItem('token');
    location.reload();
}

// ── Onboarding y Conexión de MercadoLibre ───────────────────────────
function abrirOnboardingMeLi() {
    const modal = document.getElementById('modalOnboardingMeLi');
    if (modal) modal.style.display = 'flex';
}

function cerrarOnboardingMeLi() {
    const modal = document.getElementById('modalOnboardingMeLi');
    if (modal) modal.style.display = 'none';
}

async function iniciarConexionMeLi() {
    const token = getToken();
    let headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    try {
        let res = await fetch(`${API_BASE}/full/ml/auth/login`, { headers });
        if (res.status === 404) {
            res = await fetch(`${API_BASE}/ml/auth/login`, { headers });
        }

        const data = await res.json();
        if (data.ok && data.auth_url) {
            // Redirige en la misma ventana oficial de MeLi para evitar bloqueo de pop-ups
            window.location.href = data.auth_url;
        } else {
            alert(data.error || 'No se pudo iniciar la conexión con MercadoLibre.');
        }
    } catch (err) {
        alert('Error conectando con MercadoLibre: ' + err.message);
    }
}

// ── Manejo de Cuentas MeLi y Plan ──────────────────────────────────
function renderMeLiAccounts(accounts) {
    const select = document.getElementById('mlAccountSelect');
    const btnConnect = document.getElementById('btnConnectMeLiHeader');
    const sidebarAcc = document.getElementById('sidebarAccountName');
    const sidebarStatus = document.getElementById('sidebarConnStatusBadge');

    if (select) {
        select.innerHTML = '<option value="all">Todas las cuentas MeLi</option>';
        if (accounts && accounts.length > 0) {
            accounts.forEach(acc => {
                const opt = document.createElement('option');
                opt.value = acc.id;
                opt.textContent = `Cuenta: ${acc.ml_nickname || acc.ml_user_id}`;
                select.appendChild(opt);
            });
            select.style.display = accounts.length > 1 ? 'inline-block' : 'none';
            if (btnConnect) btnConnect.style.display = 'inline-block';
        } else {
            select.style.display = 'none';
            if (btnConnect) btnConnect.style.display = 'inline-block';
        }
    }

    if (sidebarAcc) {
        if (!accounts || accounts.length === 0) {
            sidebarAcc.textContent = 'Sin vincular';
            if (sidebarStatus) {
                sidebarStatus.className = 'badge badge-warn';
                sidebarStatus.textContent = 'Sin vincular';
            }
        } else {
            if (sidebarStatus) {
                sidebarStatus.className = 'badge badge-ok';
                sidebarStatus.textContent = 'Activo';
            }
            if (currentAccount && currentAccount !== 'all') {
                const found = accounts.find(a => String(a.id) === String(currentAccount));
                sidebarAcc.textContent = found ? (found.ml_nickname || found.ml_user_id) : (accounts[0].ml_nickname || accounts[0].ml_user_id);
            } else if (accounts.length === 1) {
                sidebarAcc.textContent = accounts[0].ml_nickname || accounts[0].ml_user_id;
            } else {
                sidebarAcc.textContent = accounts.map(a => a.ml_nickname || a.ml_user_id).join(', ');
            }
        }
    }
}

function cambiarCuentaMeLi(accId) {
    currentAccount = accId;
    if (currentUser && currentUser.ml_accounts) {
        renderMeLiAccounts(currentUser.ml_accounts);
    }
    cargarDatos();
}

function actualizarBadgePlan(planInfo) {
    currentPlanInfo = planInfo;
    const badge = document.getElementById('planBadge');
    if (!badge || !planInfo) return;

    if (planInfo.has_full_access === false) {
        if (planInfo.can_start_trial) {
            badge.className = 'plan-badge trial';
            badge.textContent = 'Activar 30d gratis';
            badge.onclick = () => abrirModalActivarFull(currentUser);
        } else {
            badge.className = 'plan-badge';
            badge.textContent = 'Requiere suscripción';
            badge.onclick = () => abrirModalSuscripcionVencida(currentUser);
        }
        return;
    }

    badge.onclick = () => abrirModalPlan();
    if (planInfo.plan_tier === 'trial') {
        const days = planInfo.trial_days_left !== undefined ? planInfo.trial_days_left : 30;
        badge.className = 'plan-badge trial';
        badge.textContent = `Prueba Gratis (${days}d restantes)`;
    } else {
        badge.className = 'plan-badge';
        badge.textContent = `Plan ${planInfo.plan_name || planInfo.plan_tier}`;
    }
}

function abrirModalActivarFull(user) {
    const modal = document.getElementById('modalActivateFull');
    const title = document.getElementById('activateFullTitle');
    const msg = document.getElementById('activateFullMsg');
    const actionArea = document.getElementById('activateFullActionArea');
    if (!modal) return;

    if (title) title.textContent = '¡Bienvenido a EnvioBot Full!';
    if (msg) {
        const nombre = (user && (user.full_name || user.email)) ? `Hola <strong>${user.full_name || user.email}</strong>: ` : '';
        msg.innerHTML = `${nombre}Detectamos tu cuenta de EnvioBot. Para comenzar a monitorear el stock de tus depósitos y evitar quiebres, activá tus <strong>30 días de prueba gratuita</strong>.`;
    }
    if (actionArea) {
        actionArea.innerHTML = `
            <button id="btnStartTrialFull" onclick="activarPruebaFull()" class="btn btn-block" style="padding: 13px; font-size: 14px; font-weight: 700; background: var(--accent); color: #111; justify-content: center; cursor: pointer;">
                Activar 30 días de prueba gratis
            </button>
        `;
    }
    modal.style.display = 'flex';
}

function abrirModalSuscripcionVencida(user) {
    const modal = document.getElementById('modalActivateFull');
    const title = document.getElementById('activateFullTitle');
    const msg = document.getElementById('activateFullMsg');
    const actionArea = document.getElementById('activateFullActionArea');
    if (!modal) return;

    if (title) title.textContent = 'Tu período de prueba de 30 días ha finalizado';
    if (msg) {
        msg.innerHTML = `Completaste tus 30 días de prueba gratuita en EnvioBot Full.<br><br>Para continuar monitoreando tu inventario Full y evitar que tus publicaciones quiebren stock, activá tu suscripción o registrá tu cuenta definitiva en <strong>admin.enviobot.com.ar</strong>.<br><br><span style="color: #ff7676; font-size: 12.5px; font-weight: 600;">Atención: Si no activás tu suscripción, los datos temporales de la prueba serán eliminados para liberar espacio.</span>`;
    }
    if (actionArea) {
        actionArea.innerHTML = `
            <a href="https://wa.me/5491155550000?text=Hola,%20finalizo%20mi%20prueba%20de%2030%20dias%20de%20EnvioBot%20Full%20y%20quiero%20suscribirme" target="_blank" class="btn btn-block" style="padding: 13px; font-size: 14px; font-weight: 700; background: var(--accent); color: #111; justify-content: center; text-decoration: none;">
                Suscribirme y Activar Plan
            </a>
            <button onclick="abrirModalAuth('register')" class="btn btn-secondary btn-block" style="margin-top: 8px; font-size: 13px;">
                Registrar cuenta definitiva
            </button>
        `;
    }
    modal.style.display = 'flex';
}

function cerrarModalActivarFull() {
    const modal = document.getElementById('modalActivateFull');
    if (modal) modal.style.display = 'none';
}

async function activarPruebaFull() {
    const token = getToken();
    const btn = document.getElementById('btnStartTrialFull');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Activando tus 30 días...';
    }

    try {
        let res = await fetch(`${API_BASE}/full/auth/activate-trial`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });
        if (res.status === 404) {
            res = await fetch(`${API_BASE}/auth/activate-trial`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
        }
        const data = await res.json();
        if (data.ok) {
            cerrarModalActivarFull();
            await checkUserSession();
            // Abrir inmediatamente la conexión con Mercado Libre
            abrirOnboardingMeLi();
        } else {
            alert(data.error || 'No se pudo activar el período de prueba.');
        }
    } catch (e) {
        alert('Error activando prueba: ' + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Activar 30 días de prueba gratis';
        }
    }
}

function abrirModalPlan() {
    const modal = document.getElementById('modalPlan');
    const details = document.getElementById('planModalDetails');
    if (!modal || !details) return;

    const p = currentPlanInfo || { plan_tier: 'trial', plan_name: 'Prueba Gratis (30 días)', trial_days_left: 30 };
    details.innerHTML = `
        <div style="background: var(--surf2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 14px;">
            <div style="font-size: 11px; text-transform: uppercase; font-weight: 800; color: var(--accent); letter-spacing: 0.5px;">Tu Plan Activo</div>
            <div style="font-size: 18px; font-weight: 800; margin-top: 4px; color: var(--text);">${p.plan_name || p.plan_tier.toUpperCase()}</div>
            <div style="font-size: 12.5px; color: var(--text2); margin-top: 4px;">
                ${p.plan_tier === 'trial' ? `Tenés <strong>${p.trial_days_left || 0} días restantes</strong> de prueba completa sin cargo.` : 'Suscripción activa.'}
            </div>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px;">
            <div style="background: var(--surf2); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                <div style="font-size: 11px; color: var(--text2); font-weight: 700;">Cuentas MeLi permitidas</div>
                <div style="font-size: 16px; font-weight: 800; color: var(--text); margin-top: 2px;">${p.limits ? p.limits.max_ml_accounts : 1}</div>
            </div>
            <div style="background: var(--surf2); padding: 12px; border-radius: 6px; border: 1px solid var(--border);">
                <div style="font-size: 11px; color: var(--text2); font-weight: 700;">Alertas WhatsApp / Equipo</div>
                <div style="font-size: 16px; font-weight: 800; color: var(--text); margin-top: 2px;">${p.limits ? p.limits.max_recipients : 2}</div>
            </div>
        </div>
        <div style="font-size: 12px; color: var(--text2); line-height: 1.5;">
            Los planes se configuran de forma centralizada para tu empresa desde <strong>admin.enviobot.com.ar</strong>.
        </div>
    `;
    modal.style.display = 'flex';
}

function cerrarModalPlan() {
    const modal = document.getElementById('modalPlan');
    if (modal) modal.style.display = 'none';
}

function mostrarInfoUpgrade() {
    abrirModalPlan();
}

// ── Chequeo de Sesión al Arrancar y Manejo de Vistas ───────────────
async function checkUserSession() {
    const token = getToken();
    const userEmailEl = document.getElementById('userEmailText');
    const btnLogout = document.getElementById('btnLogoutBtn');
    const btnLoginHeader = document.getElementById('btnLoginHeader');
    const planBadge = document.getElementById('planBadge');
    const mlAccountSelect = document.getElementById('mlAccountSelect');
    const btnConnectHeader = document.getElementById('btnConnectMeLiHeader');
    const btnAdmin = document.getElementById('btnAdminClientesTop');
    const viewWelcome = document.getElementById('viewOnboardingWelcome');
    const viewDash = document.getElementById('viewMainDashboard');

    if (!token) {
        // MOSTRAR DIRECTAMENTE EL FORMULARIO DE LOGIN
        if (viewWelcome) viewWelcome.style.display = 'flex';
        if (viewDash) viewDash.style.display = 'none';

        if (userEmailEl) userEmailEl.textContent = 'Iniciar sesión';
        if (btnLogout) btnLogout.style.display = 'none';
        if (btnLoginHeader) btnLoginHeader.style.display = 'none';
        if (btnConnectHeader) btnConnectHeader.style.display = 'none';
        if (btnAdmin) btnAdmin.style.display = 'none';
        if (planBadge) planBadge.style.display = 'none';
        if (mlAccountSelect) mlAccountSelect.style.display = 'none';
        return false;
    }

    try {
        let res = await fetch(`${API_BASE}/full/auth/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.status === 404) {
            res = await fetch(`${API_BASE}/auth/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
        }

        if (res.status === 401) {
            localStorage.removeItem('enviobot_full_token');
            if (viewWelcome) viewWelcome.style.display = 'flex';
            if (viewDash) viewDash.style.display = 'none';
            if (userEmailEl) userEmailEl.textContent = 'Iniciar sesión';
            if (btnLoginHeader) btnLoginHeader.style.display = 'none';
            if (btnLogout) btnLogout.style.display = 'none';
            if (btnAdmin) btnAdmin.style.display = 'none';
            return false;
        }

        const data = await res.json();
        if (data.ok && data.user) {
            currentUser = data.user;
            if (userEmailEl) userEmailEl.textContent = data.user.email || data.user.full_name;
            if (btnLogout) btnLogout.style.display = 'inline-flex';
            if (btnLoginHeader) btnLoginHeader.style.display = 'none';

            // Visibilidad de Administración para Guillermo
            const isAdmin = Boolean(
                data.user.is_admin ||
                (data.user.email && (
                    data.user.email.toLowerCase() === 'guillermo.jaeger@gmail.com' ||
                    data.user.email.toLowerCase() === 'admin@enviobot.com.ar'
                ))
            );
            if (btnAdmin) btnAdmin.style.display = isAdmin ? 'inline-flex' : 'none';

            actualizarBadgePlan(data.user);
            renderMeLiAccounts(data.user.ml_accounts);

            // Si venció el plazo de 30 días:
            if (data.user.has_full_access === false) {
                abrirModalSuscripcionVencida(data.user);
                return false;
            }

            // Usuario con sesión iniciada: ocultar pantalla de login y mostrar dashboard
            if (viewWelcome) viewWelcome.style.display = 'none';
            if (viewDash) viewDash.style.display = 'block';

            const trialBanner = document.getElementById('trialWelcomeBanner');
            if (!data.user.ml_accounts || data.user.ml_accounts.length === 0) {
                if (trialBanner) trialBanner.style.display = 'flex';
                if (btnConnectHeader) btnConnectHeader.style.display = 'inline-flex';
            } else {
                if (trialBanner) trialBanner.style.display = 'none';
                if (btnConnectHeader) btnConnectHeader.style.display = 'inline-flex';
                // Solo mostrar wizard si es un usuario virgen sin correo y sin wizard previo
                const wizCompleted = localStorage.getItem('enviobot_wizard_completed_' + currentUser.id) || localStorage.getItem('enviobot_wizard_completed');
                if (!wizCompleted && (!currentUser.email || currentUser.email.includes('meli_')) && currentUser.id !== 45) {
                    abrirWizardOnboarding();
                }
            }

            return true;
        }
    } catch (err) {
        console.error("Error verificando sesión:", err);
    }
    return false;
}

// ── WIZARD DE CONFIGURACIÓN INICIAL (POST-VINCULACIÓN MELI) ───────
function abrirWizardOnboarding() {
    const modal = document.getElementById('modalWizardOnboarding');
    if (!modal) return;

    // Pre-llenar email si está disponible
    const emailInput = document.getElementById('wizAlertEmail');
    if (emailInput && currentUser && currentUser.email) {
        if (!emailInput.value || emailInput.value.includes('meli_')) {
            if (!currentUser.email.includes('meli_')) {
                emailInput.value = currentUser.email;
            }
        }
    }

    // Reset a paso 1
    retrocederWizardPaso1();

    modal.style.display = 'flex';
}

function cerrarWizardOnboarding() {
    const modal = document.getElementById('modalWizardOnboarding');
    if (modal) modal.style.display = 'none';
}

function avanzarWizardPaso2() {
    const step1 = document.getElementById('wizardStep1');
    const step2 = document.getElementById('wizardStep2');
    const step3 = document.getElementById('wizardStep3');
    const b1 = document.getElementById('wizBullet1');
    const b2 = document.getElementById('wizBullet2');
    const b3 = document.getElementById('wizBullet3');
    const tag = document.getElementById('wizardStepTag');
    const title = document.getElementById('wizardStepTitle');

    if (step1) step1.style.display = 'none';
    if (step2) step2.style.display = 'block';
    if (step3) step3.style.display = 'none';

    if (b1) b1.classList.add('active');
    if (b2) b2.classList.add('active');
    if (b3) b3.classList.remove('active');

    if (tag) tag.textContent = 'Paso 2 de 3 · Alertas de WhatsApp y Email';
    if (title) title.textContent = 'Destinatarios de Alertas';

    // Pre-llenar email si está vacío
    const emailInput = document.getElementById('wizAlertEmail');
    if (emailInput && (!emailInput.value || emailInput.value.includes('meli_'))) {
        if (currentUser && currentUser.email && !currentUser.email.includes('meli_')) {
            emailInput.value = currentUser.email;
        }
    }
    // Pre-llenar nombre
    const nameInput = document.getElementById('wizWaName');
    if (nameInput && !nameInput.value && currentUser && currentUser.full_name) {
        nameInput.value = currentUser.full_name;
    }
}

function retrocederWizardPaso1() {
    const step1 = document.getElementById('wizardStep1');
    const step2 = document.getElementById('wizardStep2');
    const step3 = document.getElementById('wizardStep3');
    const b1 = document.getElementById('wizBullet1');
    const b2 = document.getElementById('wizBullet2');
    const b3 = document.getElementById('wizBullet3');
    const tag = document.getElementById('wizardStepTag');
    const title = document.getElementById('wizardStepTitle');

    if (step1) step1.style.display = 'block';
    if (step2) step2.style.display = 'none';
    if (step3) step3.style.display = 'none';

    if (b1) b1.classList.add('active');
    if (b2) b2.classList.remove('active');
    if (b3) b3.classList.remove('active');

    if (tag) tag.textContent = 'Paso 1 de 3 · Depósito y Reposición';
    if (title) title.textContent = 'Parámetros del Depósito Full';
}

function retrocederWizardPaso2() {
    avanzarWizardPaso2();
}

async function avanzarWizardPaso3() {
    const email = document.getElementById('wizAlertEmail').value.trim();
    const phone = document.getElementById('wizWaPhone').value.trim();
    const name = document.getElementById('wizWaName').value.trim() || (currentUser?.full_name || 'Encargado');
    const days = document.getElementById('wizWaDays').value;
    const time = document.getElementById('wizWaTime').value;
    const transitDays = parseInt(document.getElementById('wizTransitDays')?.value, 10) || 3;
    const safetyStock = parseInt(document.getElementById('wizSafetyStock').value, 10) || 2;
    const targetDays = parseInt(document.getElementById('wizTargetDays').value, 10) || 30;

    if (!email) {
        alert("Por favor completá un correo electrónico para recibir el resumen matutino.");
        document.getElementById('wizAlertEmail').focus();
        return;
    }

    if (!phone) {
        alert("Por favor completá un celular de WhatsApp para las alertas urgentes.");
        document.getElementById('wizWaPhone').focus();
        return;
    }

    const btn = document.getElementById('btnWizFinish');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Guardando y enviando verificación...';
    }

    const token = getToken();
    try {
        if (token) {
            // 1. Guardar parámetros en user_settings con send_welcome: true (dispara email con código y WhatsApp)
            await fetch(`${API_BASE}/full/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({
                    default_lead_time_days: transitDays,
                    default_safety_stock_days: safetyStock,
                    target_coverage_days: targetDays,
                    notify_email: true,
                    alert_email: email,
                    notify_whatsapp: true,
                    whatsapp_phone: phone,
                    send_welcome: true
                })
            });

            // 2. Guardar depósito 1 (Mercado Envíos Full)
            await fetch(`${API_BASE}/full/warehouses`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({
                    code: 'meli_full',
                    name: 'Mercado Envíos Full (Bs As)',
                    city: 'Buenos Aires',
                    transit_days: transitDays,
                    target_stock_days: targetDays
                })
            });

            // 3. Guardar destinatario de WhatsApp
            await fetch(`${API_BASE}/full/recipients`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({
                    name: name,
                    phone: phone,
                    role: 'admin',
                    warehouse_filter: 'all',
                    alert_days: days,
                    alert_time: time
                })
            });

            // 4. Disparar sincronización de MeLi en segundo plano
            fetch(`${API_BASE}/full/sync`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            }).catch(e => console.warn("Sync bg:", e));
        }

        // Actualizar variables en memoria
        if (WAREHOUSES.meli_full) {
            WAREHOUSES.meli_full.defaultTransit = transitDays;
            WAREHOUSES.meli_full.defaultTarget = targetDays;
        }

        // Pasar visualmente al Paso 3 de verificación
        const step1 = document.getElementById('wizardStep1');
        const step2 = document.getElementById('wizardStep2');
        const step3 = document.getElementById('wizardStep3');
        const b1 = document.getElementById('wizBullet1');
        const b2 = document.getElementById('wizBullet2');
        const b3 = document.getElementById('wizBullet3');
        const tag = document.getElementById('wizardStepTag');
        const title = document.getElementById('wizardStepTitle');

        if (step1) step1.style.display = 'none';
        if (step2) step2.style.display = 'none';
        if (step3) step3.style.display = 'block';

        if (b1) b1.classList.add('active');
        if (b2) b2.classList.add('active');
        if (b3) b3.classList.add('active');

        if (tag) tag.textContent = 'Paso 3 de 3 · Verificación de Canales';
        if (title) title.textContent = 'Confirmación de Contacto';

        const emailTarget = document.getElementById('wizConfirmEmailTarget');
        if (emailTarget) emailTarget.textContent = email;

        const phoneTarget = document.getElementById('wizConfirmPhoneTarget');
        if (phoneTarget) phoneTarget.textContent = phone;

        const codeInput = document.getElementById('wizEmailCodeInput');
        if (codeInput) {
            codeInput.value = '';
            setTimeout(() => codeInput.focus(), 150);
        }

    } catch (err) {
        console.error("Error guardando paso 2:", err);
        alert("Ocurrió un error guardando la configuración: " + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Guardar y Enviar Verificación';
        }
    }
}

async function confirmarCodigoWizard() {
    const codeInput = document.getElementById('wizEmailCodeInput');
    const code = codeInput ? codeInput.value.trim() : '';
    const email = document.getElementById('wizAlertEmail')?.value.trim() || (currentUser?.email || '');

    if (!code || code.length !== 6) {
        alert("Por favor ingresá el código de 6 dígitos que te enviamos por correo.");
        if (codeInput) codeInput.focus();
        return;
    }

    const btn = document.getElementById('btnWizVerifyConfirm');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Validando código...';
    }

    const token = getToken();
    try {
        let headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`${API_BASE}/full/verify/check-email`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ code: code, email: email })
        });
        const data = await res.json();

        if (data.ok && data.verified) {
            // Marcar wizard como completado
            if (currentUser && currentUser.id) {
                localStorage.setItem('enviobot_wizard_completed_' + currentUser.id, 'true');
            } else {
                localStorage.setItem('enviobot_wizard_completed', 'true');
            }

            cerrarWizardOnboarding();

            // Mostrar dashboard principal y consultar datos reales
            const viewWelcome = document.getElementById('viewOnboardingWelcome');
            const viewDash = document.getElementById('viewMainDashboard');
            if (viewWelcome) viewWelcome.style.display = 'none';
            if (viewDash) viewDash.style.display = 'block';

            alert("Casilla de correo y número de WhatsApp vinculados correctamente. Tus canales de alerta quedaron activos.\n\nCargando tus publicaciones reales...");

            await cargarDatos();
        } else {
            alert(data.error || "Código incorrecto o expirado. Verificá tu correo o hacé clic en 'Reenviar código'.");
        }
    } catch (e) {
        console.error("Error verificando código:", e);
        alert("Error de conexión: " + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Confirmar y Ver Publicaciones';
        }
    }
}

async function reenviarCodigoWizard(e) {
    if (e) e.preventDefault();
    const email = document.getElementById('wizAlertEmail')?.value.trim() || (currentUser?.email || '');
    if (!email) {
        alert("No se encontró la casilla de correo.");
        return;
    }

    const token = getToken();
    try {
        let headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`${API_BASE}/full/verify/send-email`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ email: email })
        });
        const data = await res.json();
        if (data.ok) {
            alert(`Código de verificación reenviado a ${email}.\nRevisá tu bandeja de entrada o spam.`);
        } else {
            alert(data.error || "No se pudo reenviar el código.");
        }
    } catch (e) {
        alert("Error de conexión: " + e.message);
    }
}

function saltarVerificacionWizard(e) {
    if (e) e.preventDefault();
    // Marcar wizard como completado
    if (currentUser && currentUser.id) {
        localStorage.setItem('enviobot_wizard_completed_' + currentUser.id, 'true');
    } else {
        localStorage.setItem('enviobot_wizard_completed', 'true');
    }

    cerrarWizardOnboarding();

    const viewWelcome = document.getElementById('viewOnboardingWelcome');
    const viewDash = document.getElementById('viewMainDashboard');
    if (viewWelcome) viewWelcome.style.display = 'none';
    if (viewDash) viewDash.style.display = 'block';

    alert("Configuración inicial guardada.\n\nPodrás confirmar la vinculación de tu correo más adelante desde el botón de Configuración en el panel.");

    cargarDatos();
}

// ── Inicialización ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    // 1. Detectar si viene token en la URL desde OAuth (?auth_token=... o ?token=...)
    const params = new URLSearchParams(window.location.search);
    const tokenFromUrl = params.get('auth_token') || params.get('token');
    if (tokenFromUrl) {
        localStorage.setItem('enviobot_full_token', tokenFromUrl);
        localStorage.setItem('token', tokenFromUrl);
    }

    const hasMlOk = params.get('ml') === 'ok';
    if (hasMlOk) {
        window.history.replaceState({}, document.title, window.location.pathname);
        showToast("Cuenta de Mercado Libre conectada con éxito.", "success");
    } else if (params.get('ml') === 'error') {
        const msg = params.get('msg') || 'Error en la autorización de MercadoLibre';
        showToast(`Error: ${msg}`, 'error');
        window.history.replaceState({}, document.title, window.location.pathname);
    }

    // 2. Verificar código de vinculación por email desde link de correo (?verify_code=...&email=...)
    const verifyCode = params.get('verify_code');
    if (verifyCode) {
        const verifyEmail = params.get('email') || '';
        try {
            const token = getToken();
            let headers = { 'Content-Type': 'application/json' };
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const vRes = await fetch(`${API_BASE}/full/verify/check-email`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ code: verifyCode, email: verifyEmail })
            });
            const vData = await vRes.json();
            if (vData.ok && vData.verified) {
                showToast("Casilla de correo vinculada y confirmada con éxito.", "success");
                actualizarEstadoVerificacionEmail(true);
            } else {
                showToast("No se pudo verificar el correo: " + (vData.error || "código inválido."), "error");
            }
        } catch (err) {
            console.error("Error verificando código desde URL:", err);
        }
        window.history.replaceState({}, document.title, window.location.pathname);
    }

    // 3. Poblar selectores con depósito Villa Celina
    poblarSelectoresDepositos();

    // 4. Verificar sesión y estado de vinculación
    const hasActiveSession = await checkUserSession();

    // 5. Cargar datos reales de MeLi directamente
    if (hasActiveSession) {
        await cargarSettingsBackend();
        cargarDatos();
    }

    // 7. Verificar visibilidad del botón de instalación de aplicación en escritorio
    checkPwaInstallState();
});

// ── Control de Pantalla Completa para la Card de Stock y Colectas ───────────
function toggleFullscreenTable() {
    const card = document.getElementById('cardStockPrincipal');
    const btnText = document.getElementById('btnToggleFullscreenText');
    const iconExp = document.getElementById('fsIconExpand');
    const iconComp = document.getElementById('fsIconCompress');
    if (!card) return;

    card.classList.toggle('card-fullscreen');
    const isFull = card.classList.contains('card-fullscreen');

    if (btnText) {
        btnText.textContent = isFull ? 'Ventana Normal' : 'Pantalla Completa';
    }
    if (iconExp && iconComp) {
        iconExp.style.display = isFull ? 'none' : 'inline-block';
        iconComp.style.display = isFull ? 'inline-block' : 'none';
    }

    if (isFull) {
        document.body.style.overflow = 'hidden';
    } else {
        document.body.style.overflow = '';
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const card = document.getElementById('cardStockPrincipal');
        if (card && card.classList.contains('card-fullscreen')) {
            toggleFullscreenTable();
        }
    }
});

// -------------------------------------------------------------
// PANEL DE ADMINISTRACIÓN Y CONTROL MANUAL DE CLIENTES
// -------------------------------------------------------------

let adminClientsData = [];

function abrirModalAdminClientes() {
    const modal = document.getElementById('modalAdminClientes');
    if (modal) {
        modal.style.display = 'flex';
        cargarClientesAdmin();
    }
}

function cerrarModalAdminClientes() {
    const modal = document.getElementById('modalAdminClientes');
    if (modal) modal.style.display = 'none';
}

async function cargarClientesAdmin() {
    const token = getToken();
    const tbody = document.getElementById('adminClientsTableBody');
    const statsEl = document.getElementById('adminClientsStats');
    if (!tbody || !token) return;

    tbody.innerHTML = `
        <tr>
            <td colspan="5" style="text-align: center; padding: 24px; color: var(--text2);">
                Cargando clientes desde la base de datos...
            </td>
        </tr>
    `;

    try {
        const res = await fetch(`${API_BASE}/full/admin/clients`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();

        if (!data.ok) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #ef4444; padding: 18px;">${data.error || 'No se pudo cargar la lista.'}</td></tr>`;
            return;
        }

        adminClientsData = data.clients || [];
        renderClientesAdmin(adminClientsData);

        const conFull = adminClientsData.filter(c => c.has_full).length;
        const bloqueados = adminClientsData.filter(c => c.is_blocked).length;
        if (statsEl) {
            statsEl.textContent = `Total: ${adminClientsData.length} clientes · Con Full: ${conFull} · Bloqueados: ${bloqueados}`;
        }
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #ef4444; padding: 18px;">Error: ${err.message}</td></tr>`;
    }
}

function filtrarClientesAdmin() {
    const query = (document.getElementById('adminClientSearchInput')?.value || '').trim().toLowerCase();
    if (!query) {
        renderClientesAdmin(adminClientsData);
        return;
    }

    const filtered = adminClientsData.filter(c => {
        const email = (c.email || '').toLowerCase();
        const name = (c.full_name || '').toLowerCase();
        const biz = (c.business_name || '').toLowerCase();
        const notes = (c.admin_notes || '').toLowerCase();
        return email.includes(query) || name.includes(query) || biz.includes(query) || notes.includes(query);
    });

    renderClientesAdmin(filtered);
}

function renderClientesAdmin(clients) {
    const tbody = document.getElementById('adminClientsTableBody');
    if (!tbody) return;

    if (!clients || clients.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" style="text-align: center; padding: 24px; color: var(--text2);">
                    No se encontraron clientes con ese criterio de búsqueda.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = '';
    clients.forEach(c => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid var(--border)';
        tr.id = `adminRowClient_${c.id}`;

        const pedidosBadge = c.has_pedidos 
            ? `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Habilitado</span>`
            : `<span style="background: rgba(239, 68, 68, 0.15); color: #ef4444; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Sin acceso</span>`;

        const fullBadge = c.has_full 
            ? `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Habilitado</span>`
            : `<span style="background: rgba(239, 68, 68, 0.15); color: #ef4444; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Sin acceso</span>`;

        const inboundBadge = c.has_inbound 
            ? `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Habilitado</span>`
            : `<span style="background: rgba(239, 68, 68, 0.15); color: #ef4444; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Sin acceso</span>`;

        const blockBadge = c.is_blocked
            ? `<span style="color: #ef4444; font-weight: 700; font-size: 11px;">Bloqueado</span>`
            : `<span style="color: var(--text2); font-size: 11px;">Activo</span>`;

        tr.innerHTML = `
            <td style="padding: 10px 12px; vertical-align: middle;">
                <div style="font-weight: 700; color: var(--text);">${c.email}</div>
                <div style="font-size: 11.5px; color: var(--text2); margin-top: 2px;">
                    ${c.full_name || 'Sin nombre'} · ID #${c.id} · ${c.ml_accounts_count} cta(s) MeLi
                    ${c.business_name ? ` · <span style="color: var(--accent);">${c.business_name}</span>` : ''}
                </div>
            </td>
            <td style="padding: 10px 12px; text-align: center; vertical-align: middle;">
                <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer;">
                    <input type="checkbox" id="chkAdminPedidos_${c.id}" ${c.has_pedidos ? 'checked' : ''} onchange="adminTogglePedidos(${c.id}, this.checked)" style="cursor: pointer; width: 16px; height: 16px;">
                    <span id="badgeAdminPedidos_${c.id}">${pedidosBadge}</span>
                </label>
            </td>
            <td style="padding: 10px 12px; text-align: center; vertical-align: middle;">
                <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer;">
                    <input type="checkbox" id="chkAdminFull_${c.id}" ${c.has_full ? 'checked' : ''} onchange="adminToggleFull(${c.id}, this.checked)" style="cursor: pointer; width: 16px; height: 16px;">
                    <span id="badgeAdminFull_${c.id}">${fullBadge}</span>
                </label>
            </td>
            <td style="padding: 10px 12px; text-align: center; vertical-align: middle;">
                <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer;">
                    <input type="checkbox" id="chkAdminInbound_${c.id}" ${c.has_inbound ? 'checked' : ''} onchange="adminToggleInbound(${c.id}, this.checked)" style="cursor: pointer; width: 16px; height: 16px;">
                    <span id="badgeAdminInbound_${c.id}">${inboundBadge}</span>
                </label>
            </td>
            <td style="padding: 10px 12px; text-align: center; vertical-align: middle;">
                <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer;">
                    <input type="checkbox" id="chkAdminBlock_${c.id}" ${c.is_blocked ? 'checked' : ''} onchange="adminToggleBlock(${c.id}, this.checked)" style="cursor: pointer; width: 16px; height: 16px;">
                    <span id="badgeAdminBlock_${c.id}">${blockBadge}</span>
                </label>
            </td>
            <td style="padding: 10px 12px; vertical-align: middle;">
                <input type="text" id="adminNote_${c.id}" value="${(c.admin_notes || '').replace(/"/g, '&quot;')}" placeholder="Anotaciones administrativas..." class="auth-input" style="padding: 6px 10px; font-size: 12px; margin: 0; width: 100%;">
            </td>
            <td style="padding: 10px 12px; text-align: right; vertical-align: middle;">
                <button type="button" id="btnAdminSaveNote_${c.id}" onclick="adminGuardarNotas(${c.id})" class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 5px 12px; white-space: nowrap;">
                    Guardar
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function adminTogglePedidos(userId, enable) {
    const token = getToken();
    const chk = document.getElementById(`chkAdminPedidos_${userId}`);
    const badge = document.getElementById(`badgeAdminPedidos_${userId}`);
    if (!token) return;

    if (chk) chk.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/full/admin/clients/${userId}/toggle-pedidos`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ enable })
        });
        const data = await res.json();
        if (data.ok) {
            const c = adminClientsData.find(item => item.id === userId);
            if (c) c.has_pedidos = enable;

            if (badge) {
                badge.innerHTML = enable
                    ? `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Habilitado</span>`
                    : `<span style="background: rgba(239, 68, 68, 0.15); color: #ef4444; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Sin acceso</span>`;
            }
        } else {
            alert(data.error || 'No se pudo actualizar el estado de Pedidos.');
            if (chk) chk.checked = !enable;
        }
    } catch (err) {
        alert('Error: ' + err.message);
        if (chk) chk.checked = !enable;
    } finally {
        if (chk) chk.disabled = false;
    }
}

async function adminToggleFull(userId, enable) {
    const token = getToken();
    const chk = document.getElementById(`chkAdminFull_${userId}`);
    const badge = document.getElementById(`badgeAdminFull_${userId}`);
    if (!token) return;

    if (chk) chk.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/full/admin/clients/${userId}/toggle-full`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ enable })
        });
        const data = await res.json();
        if (data.ok) {
            const c = adminClientsData.find(item => item.id === userId);
            if (c) c.has_full = enable;

            if (badge) {
                badge.innerHTML = enable
                    ? `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Habilitado</span>`
                    : `<span style="background: rgba(239, 68, 68, 0.15); color: #ef4444; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Sin acceso</span>`;
            }
        } else {
            alert(data.error || 'No se pudo actualizar el estado de Full.');
            if (chk) chk.checked = !enable;
        }
    } catch (err) {
        alert('Error: ' + err.message);
        if (chk) chk.checked = !enable;
    } finally {
        if (chk) chk.disabled = false;
    }
}

async function adminToggleInbound(userId, enable) {
    const token = getToken();
    const chk = document.getElementById(`chkAdminInbound_${userId}`);
    const badge = document.getElementById(`badgeAdminInbound_${userId}`);
    if (!token) return;

    if (chk) chk.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/full/admin/clients/${userId}/toggle-inbound`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ enable })
        });
        const data = await res.json();
        if (data.ok) {
            const c = adminClientsData.find(item => item.id === userId);
            if (c) c.has_inbound = enable;

            if (badge) {
                badge.innerHTML = enable
                    ? `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Habilitado</span>`
                    : `<span style="background: rgba(239, 68, 68, 0.15); color: #ef4444; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">Sin acceso</span>`;
            }
        } else {
            alert(data.error || 'No se pudo actualizar el estado de Colectas.');
            if (chk) chk.checked = !enable;
        }
    } catch (err) {
        alert('Error: ' + err.message);
        if (chk) chk.checked = !enable;
    } finally {
        if (chk) chk.disabled = false;
    }
}

async function adminToggleBlock(userId, isBlocked) {
    const token = getToken();
    const chk = document.getElementById(`chkAdminBlock_${userId}`);
    const badge = document.getElementById(`badgeAdminBlock_${userId}`);
    if (!token) return;

    if (chk) chk.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/full/admin/clients/${userId}/toggle-block`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ is_blocked: isBlocked })
        });
        const data = await res.json();
        if (data.ok) {
            const c = adminClientsData.find(item => item.id === userId);
            if (c) c.is_blocked = isBlocked;

            if (badge) {
                badge.innerHTML = isBlocked
                    ? `<span style="color: #ef4444; font-weight: 700; font-size: 11px;">Bloqueado</span>`
                    : `<span style="color: var(--text2); font-size: 11px;">Activo</span>`;
            }
        } else {
            alert(data.error || 'No se pudo actualizar el bloqueo.');
            if (chk) chk.checked = !isBlocked;
        }
    } catch (err) {
        alert('Error: ' + err.message);
        if (chk) chk.checked = !isBlocked;
    } finally {
        if (chk) chk.disabled = false;
    }
}

async function adminGuardarNotas(userId) {
    const token = getToken();
    const noteInput = document.getElementById(`adminNote_${userId}`);
    const btn = document.getElementById(`btnAdminSaveNote_${userId}`);
    if (!token || !noteInput) return;

    const notes = noteInput.value.trim();
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Guardando...';
    }

    try {
        const res = await fetch(`${API_BASE}/full/admin/clients/${userId}/notes`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ admin_notes: notes })
        });
        const data = await res.json();
        if (data.ok) {
            const c = adminClientsData.find(item => item.id === userId);
            if (c) c.admin_notes = notes;
            if (btn) {
                btn.textContent = 'Guardado';
                setTimeout(() => {
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent = 'Guardar';
                    }
                }, 1400);
            }
        } else {
            alert(data.error || 'No se pudieron guardar las notas.');
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Guardar';
            }
        }
    } catch (err) {
        alert('Error: ' + err.message);
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Guardar';
        }
    }
}

// -------------------------------------------------------------
// PWA & INSTALACIÓN AUTOMÁTICA EN ESCRITORIO (WINDOWS / CHROME / EDGE)
// -------------------------------------------------------------
let deferredPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    window.deferredPrompt = e;
    deferredPrompt = e;
    const btnTop = document.getElementById('btnInstallDesktopApp');
    if (btnTop) btnTop.style.display = 'inline-flex';
});

window.addEventListener('appinstalled', () => {
    window.deferredPrompt = null;
    deferredPrompt = null;
    const btnTop = document.getElementById('btnInstallDesktopApp');
    if (btnTop) btnTop.style.display = 'none';
    showToast('EnvioBot Full se instaló en tu escritorio con éxito.', 'success');
});

function checkPwaInstallState() {
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    const btnTop = document.getElementById('btnInstallDesktopApp');
    if (!btnTop) return;
    if (isStandalone) {
        btnTop.style.display = 'none';
    } else {
        btnTop.style.display = 'inline-flex';
    }
}

async function instalarAppEscritorio() {
    const promptEvent = window.deferredPrompt || deferredPrompt;
    if (promptEvent) {
        promptEvent.prompt();
        const { outcome } = await promptEvent.userChoice;
        if (outcome === 'accepted') {
            window.deferredPrompt = null;
            deferredPrompt = null;
            const btnTop = document.getElementById('btnInstallDesktopApp');
            if (btnTop) btnTop.style.display = 'none';
            showToast('Acceso directo de EnvioBot Full instalado con éxito.', 'success');
        }
    } else {
        const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
        if (isStandalone) {
            showToast('EnvioBot Full ya está ejecutándose como aplicación en tu equipo.', 'info');
            return;
        }

        // Descargar o ejecutar script de acceso directo para Windows sin preguntas de Chrome
        descargarAccesoDirectoWindows();
    }
}

function descargarAccesoDirectoWindows() {
    const batContent = `@echo off\r\nchcp 65001 >nul\r\npowershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'), 'EnvioBot Full.lnk')); $chrome = '${env:ProgramFiles}\\Google\\Chrome\\Application\\chrome.exe'; if (-not (Test-Path $chrome)) { $chrome = '${env:ProgramFiles(x86)}\\Google\\Chrome\\Application\\chrome.exe' }; if (-not (Test-Path $chrome)) { $chrome = '${env:LocalAppData}\\Google\\Chrome\\Application\\chrome.exe' }; if (-not (Test-Path $chrome)) { $chrome = '${env:ProgramFiles(x86)}\\Microsoft\\Edge\\Application\\msedge.exe' }; $s.TargetPath = $chrome; $s.Arguments = '--app=https://enviobot.com.ar/ --start-maximized'; $s.Description = 'EnvioBot Full'; $s.Save()"\r\necho Acceso directo de EnvioBot Full creado en el escritorio.\r\n`;
    const blob = new Blob([batContent], { type: 'application/bat' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'Instalar_EnvioBot_Full_Escritorio.bat';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast('Descargando instalador de escritorio de 1 clic sin confirmaciones de Chrome.', 'success');
}


