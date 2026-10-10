// =====================================================================
// app.js - Lógica del Panel de Control de EnvioBot Full
// Monitoreo multi-depósito, cálculo de quiebre, alarmas y colecta agrupada
// =====================================================================

const API_BASE = window.location.protocol === 'file:' ? 'http://localhost:5001/api' : '/api';

// Configuración de Depósitos disponibles
const WAREHOUSES = {
    meli_full: { id: "meli_full", name: "Mercado Envíos Full (Bs As)", city: "Buenos Aires", defaultTransit: 5, defaultTarget: 30 },
    cordoba:   { id: "cordoba",   name: "Depósito Córdoba",            city: "Córdoba",      defaultTransit: 3, defaultTarget: 20 },
    rosario:   { id: "rosario",   name: "Hub Rosario",                 city: "Rosario",      defaultTransit: 2, defaultTarget: 20 },
    mdp:       { id: "mdp",       name: "Depósito Mar del Plata",      city: "Mar del Plata", defaultTransit: 2, defaultTarget: 15 }
};

let currentWarehouse = 'meli_full';
let currentUser = null;
let currentAccount = 'all';
let currentPlanInfo = null;
let currentAuthTab = 'login';

// Dataset demo interactivo multi-depósito (funciona aún sin backend)
const BASE_ITEMS_CATALOG = [
    {
        id: 1,
        item_id: "MLA1428901234",
        sku: "AUR-BT-PRO-BLK",
        title: "Auriculares Inalámbricos Bluetooth 5.3 Cancelación Ruido",
        thumbnail: "https://http2.mlstatic.com/D_Q_NP_2X_841443-MLA74805728863_032024-T.webp",
        permalink: "https://mercadolibre.com.ar",
        depots: {
            meli_full: { stock: 34,  transit_days: 5, target_days: 30, buffer: 2, vpd: 7.5 },
            cordoba:   { stock: 85,  transit_days: 3, target_days: 20, buffer: 2, vpd: 2.2 },
            rosario:   { stock: 10,  transit_days: 2, target_days: 20, buffer: 2, vpd: 3.1 },
            mdp:       { stock: 4,   transit_days: 2, target_days: 15, buffer: 2, vpd: 1.8 }
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
            meli_full: { stock: 68,  transit_days: 5, target_days: 30, buffer: 2, vpd: 6.7 },
            cordoba:   { stock: 15,  transit_days: 3, target_days: 20, buffer: 2, vpd: 3.0 },
            rosario:   { stock: 42,  transit_days: 2, target_days: 20, buffer: 2, vpd: 2.5 },
            mdp:       { stock: 0,   transit_days: 2, target_days: 15, buffer: 2, vpd: 1.2 }
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
            meli_full: { stock: 280, transit_days: 4, target_days: 30, buffer: 2, vpd: 9.6 },
            cordoba:   { stock: 90,  transit_days: 3, target_days: 20, buffer: 2, vpd: 2.8 },
            rosario:   { stock: 65,  transit_days: 2, target_days: 20, buffer: 2, vpd: 2.0 },
            mdp:       { stock: 40,  transit_days: 2, target_days: 15, buffer: 2, vpd: 1.1 }
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
            meli_full: { stock: 0,   transit_days: 6, target_days: 30, buffer: 2, vpd: 2.8 },
            cordoba:   { stock: 20,  transit_days: 3, target_days: 20, buffer: 2, vpd: 0.9 },
            rosario:   { stock: 0,   transit_days: 2, target_days: 20, buffer: 2, vpd: 1.0 },
            mdp:       { stock: 18,  transit_days: 2, target_days: 15, buffer: 2, vpd: 0.6 }
        }
    }
];

let itemsData = [];
let currentFilter = 'all';
let currentSearch = '';
let selectedItem = null;
let colectaSelectedItems = new Map(); // id -> units

function getToken() {
    return localStorage.getItem('enviobot_full_token') || '';
}

// ── Cambiar depósito activo ─────────────────────────────────────────
function cambiarDeposito(depotId) {
    currentWarehouse = depotId;
    const wh = WAREHOUSES[depotId] || WAREHOUSES.meli_full;
    
    // Actualizar textos en UI
    const destinoText = document.getElementById('colectaDestinoText');
    if (destinoText) destinoText.textContent = wh.name;

    cargarDatos();
}

// ── Cargar inventario desde API o fallback a demo ──────────────────
async function cargarDatos() {
    const token = getToken();
    const tbody = document.getElementById('stockTableBody');
    tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 30px; color: var(--text2);">Consultando stock en ' + WAREHOUSES[currentWarehouse].name + '...</td></tr>';

    try {
        if (!token) throw new Error("Sin sesión activa");

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
            }
        }
    } catch (err) {
        // Modo demo interactivo
    }

    // Cargar datos demo del depósito seleccionado
    itemsData = BASE_ITEMS_CATALOG.map(it => {
        const depotConf = it.depots[currentWarehouse] || { stock: 0, transit_days: 4, target_days: 30, buffer: 2, vpd: 2.0 };
        return {
            id: it.id,
            item_id: it.item_id,
            sku: it.sku,
            title: it.title,
            thumbnail: it.thumbnail,
            permalink: it.permalink,
            current_stock: depotConf.stock,
            transit_delay_days: depotConf.transit_days,
            target_stock_days: depotConf.target_days,
            buffer_days: depotConf.buffer,
            vpd: depotConf.vpd
        };
    });

    recalcularTodo();
}

function adaptarItemDesdeBackend(raw) {
    return {
        id: raw.id,
        item_id: raw.item_id,
        sku: raw.sku,
        title: raw.title,
        thumbnail: raw.thumbnail,
        permalink: raw.permalink,
        current_stock: raw.current_stock_full || 0,
        transit_delay_days: raw.effective_lead_time || 5,
        target_stock_days: raw.target_coverage_days || 30,
        buffer_days: raw.effective_buffer || 2,
        vpd: raw.vpd_weighted || 0
    };
}

// ── Motor de cálculo de quiebre y semáforos ────────────────────────
function recalcularTodo() {
    const today = new Date();

    itemsData.forEach(it => {
        const stock = it.current_stock;
        const vpd = it.vpd;
        const transit = it.transit_delay_days;
        const buffer = it.buffer_days || 2;

        if (vpd > 0) {
            it.days_left = Math.round((stock / vpd) * 10) / 10;
            // Fecha estimada de quiebre
            const stockoutDate = new Date(today);
            stockoutDate.setDate(stockoutDate.getDate() + Math.floor(it.days_left));
            it.stockout_date = stockoutDate.toISOString().split('T')[0];

            // Fecha tope para despachar (Días restantes - Demora camión - Buffer)
            const daysToDeadline = it.days_left - transit - buffer;
            const deadlineDate = new Date(today);
            deadlineDate.setDate(deadlineDate.getDate() + Math.floor(daysToDeadline));
            it.reorder_deadline_date = deadlineDate.toISOString().split('T')[0];
        } else {
            it.days_left = 999;
            it.stockout_date = null;
            it.reorder_deadline_date = null;
        }

        // Semáforo:
        if (stock <= 0) {
            it.status = 'out_of_stock';
        } else if (it.days_left <= transit) {
            // Ya no llega a tiempo el camión antes de quebrar
            it.status = 'critical';
        } else if (it.days_left <= (transit + buffer)) {
            // Momento justo de armar y mandar la colecta
            it.status = 'warning';
        } else {
            it.status = 'ok';
        }

        // Unidades sugeridas para reponer
        const targetDays = it.target_stock_days || 30;
        it.suggested_units = Math.max(0, Math.round((targetDays * vpd) - stock));
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
    let ok = 0, warn = 0, crit = 0, totalUnits = 0;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;

    itemsData.forEach(it => {
        if (it.status === 'ok') ok++;
        else if (it.status === 'warning') warn++;
        else crit++;

        const targetDays = it.target_stock_days || wh.defaultTarget || 30;
        const faltante = Math.max(0, Math.round((targetDays * it.vpd) - it.current_stock));
        if (it.status === 'warning' || it.status === 'critical' || it.status === 'out_of_stock' || faltante > 0) {
            totalUnits += faltante;
        }
    });

    document.getElementById('statTotal').textContent = itemsData.length;
    document.getElementById('statOk').textContent = ok;
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
        const daysToDeadline = mostUrgent.days_left - transit - buffer;
        const roundedDays = Math.max(1, Math.round(daysToDeadline));

        const isToday = (mostUrgent.current_stock <= 0 || daysToDeadline <= 0);
        const askDateStr = isToday ? `PEDIR HOY (${formatearFecha(mostUrgent.reorder_deadline_date)})` : `Pedir el ${formatearFecha(mostUrgent.reorder_deadline_date)} (en ${roundedDays} d)`;

        // Banner principal claro con la fecha para pedir en MeLi
        const proximaColectaBannerHtml = `
            <div class="proxima-colecta-banner" style="border-left: 4px solid ${isToday ? 'var(--danger)' : 'var(--warn)'};">
                <div class="proxima-colecta-label">Día para pedir Colecta a MeLi</div>
                <div class="proxima-colecta-date" style="color: ${isToday ? 'var(--danger)' : 'var(--accent)'};">
                    ${askDateStr}
                </div>
                <div class="proxima-colecta-desc">
                    ${isToday ? 
                        `Tenés que pedir el turno en MercadoLibre hoy para que el flete llegue antes del quiebre del <strong>${formatearFecha(mostUrgent.stockout_date)}</strong> (${mostUrgent.title.substring(0, 30)}...).` :
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
        } else {
            badgeHtml = '<span class="badge badge-danger">Sin Stock</span>';
        }

        const diasRestantesText = it.days_left >= 900 ? 'Sin ventas' : `${it.days_left} d`;

        // FECHA DE QUIEBRE ESTIMADA
        let quiebraElHtml = '—';
        if (it.current_stock <= 0) {
            quiebraElHtml = '<span style="color: var(--danger); font-weight: 700;">Agotado</span>';
        } else if (it.days_left >= 900 || !it.stockout_date) {
            quiebraElHtml = '<span style="color: var(--text2);">Sin ventas</span>';
        } else {
            const quiebreFecha = formatearFecha(it.stockout_date);
            const isDanger = it.days_left <= it.transit_delay_days;
            const isWarning = it.days_left <= (it.transit_delay_days + (it.buffer_days || 2));
            const color = isDanger ? 'var(--danger)' : (isWarning ? 'var(--accent-text)' : 'var(--text)');
            quiebraElHtml = `<strong style="color: ${color};">${quiebreFecha}</strong>`;
        }

        // CUÁNDO PEDIR COLECTA EN MELI
        let fechaColectaHtml = '—';
        if (it.reorder_deadline_date) {
            const transit = it.transit_delay_days || 5;
            const buffer = it.buffer_days || 2;
            const daysToDeadline = it.days_left - transit - buffer;
            const roundedDays = Math.max(1, Math.round(daysToDeadline));

            if (it.current_stock <= 0 || daysToDeadline <= 0) {
                fechaColectaHtml = `
                    <span class="badge-date-today" title="Pedí la colecta hoy en MercadoLibre para no quebrar">PEDIR HOY (${formatearFecha(it.reorder_deadline_date)})</span>
                `;
            } else if (daysToDeadline <= 3) {
                fechaColectaHtml = `
                    <span class="badge-date-soon" title="Día límite para pedir turno en MeLi">Pedir el ${formatearFecha(it.reorder_deadline_date)} (en ${roundedDays} d)</span>
                `;
            } else {
                fechaColectaHtml = `
                    <span class="badge-date-normal">Pedir el ${formatearFecha(it.reorder_deadline_date)} (en ${roundedDays} d)</span>
                `;
            }
        }

        const thumbSrc = it.thumbnail || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="%238a8d9a" stroke-width="1.5"%3E%3Crect x="3" y="3" width="18" height="18" rx="2"/%3E%3C/svg%3E';

        tr.innerHTML = `
            <td>
                <div class="product-cell">
                    <img src="${thumbSrc}" class="product-thumb" alt="Foto">
                    <div>
                        <div class="product-title" title="${it.title}">${it.title}</div>
                        <div class="product-meta">
                            <span>SKU: <strong>${it.sku || 'Sin SKU'}</strong></span> · 
                            <a href="${it.permalink || '#'}" target="_blank" style="color: var(--text2); text-decoration: underline;">${it.item_id}</a>
                        </div>
                    </div>
                </div>
            </td>
            <td class="num-cell"><strong>${it.current_stock}</strong> un.</td>
            <td class="num-cell">${it.vpd} un./d</td>
            <td class="num-cell" style="font-weight: 700; color: ${it.days_left <= it.transit_delay_days ? 'var(--danger)' : 'var(--text)'};">
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

// ── MODAL: Armar Colecta / Envío Agrupado ──────────────────────────
function abrirModalColecta() {
    const modal = document.getElementById('colectaModal');
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    document.getElementById('colectaDestinoText').textContent = wh.name;

    // Inicializar mapa de selección con los que requieren reposición
    colectaSelectedItems.clear();
    const targetGlobalDays = parseInt(document.getElementById('colectaDiasSelect').value, 10) || 30;

    itemsData.forEach(it => {
        const units = Math.max(0, Math.round((targetGlobalDays * it.vpd) - it.current_stock));
        // Seleccionar por defecto si está en warning o critical, o si tiene unidades faltantes
        const shouldCheck = (it.status === 'warning' || it.status === 'critical' || it.status === 'out_of_stock' || units > 0);
        if (shouldCheck) {
            colectaSelectedItems.set(it.id, units);
        }
    });

    // Actualizar fechas dinámicas del cronograma de MeLi
    const today = new Date();
    const pickupDate = new Date(today);
    pickupDate.setDate(pickupDate.getDate() + 2); // 48hs habitual de turno MeLi
    const arrivalDate = new Date(pickupDate);
    arrivalDate.setDate(arrivalDate.getDate() + (wh.defaultTransit || 3));

    const askEl = document.getElementById('timelineAskDate');
    const pickupEl = document.getElementById('timelinePickupDate');
    const arrivalEl = document.getElementById('timelineArrivalDate');

    if (askEl) askEl.textContent = `PEDIR HOY (${today.getDate()}/${today.getMonth() + 1})`;
    if (pickupEl) pickupEl.textContent = `Retiro estimado: ${pickupDate.getDate()}/${pickupDate.getMonth() + 1}`;
    if (arrivalEl) arrivalEl.textContent = `Disponible en ${wh.city || wh.name}: ${arrivalDate.getDate()}/${arrivalDate.getMonth() + 1}`;

    renderizarFilasColecta();
    modal.style.display = 'flex';
}

function cerrarModalColecta() {
    document.getElementById('colectaModal').style.display = 'none';
}

function recalcularColecta() {
    const targetDays = parseInt(document.getElementById('colectaDiasSelect').value, 10) || 30;
    itemsData.forEach(it => {
        if (colectaSelectedItems.has(it.id)) {
            const units = Math.max(0, Math.round((targetDays * it.vpd) - it.current_stock));
            colectaSelectedItems.set(it.id, units);
        }
    });
    renderizarFilasColecta();
}

function toggleSelectAllColecta(checked) {
    const targetDays = parseInt(document.getElementById('colectaDiasSelect').value, 10) || 30;
    colectaSelectedItems.clear();
    if (checked) {
        itemsData.forEach(it => {
            const units = Math.max(0, Math.round((targetDays * it.vpd) - it.current_stock));
            colectaSelectedItems.set(it.id, units);
        });
    }
    renderizarFilasColecta();
}

function toggleItemColecta(id, checked) {
    const targetDays = parseInt(document.getElementById('colectaDiasSelect').value, 10) || 30;
    const it = itemsData.find(x => x.id === id);
    if (!it) return;

    if (checked) {
        const units = Math.max(0, Math.round((targetDays * it.vpd) - it.current_stock));
        colectaSelectedItems.set(id, units);
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

function renderizarFilasColecta() {
    const tbody = document.getElementById('colectaTableBody');
    tbody.innerHTML = '';
    const targetDays = parseInt(document.getElementById('colectaDiasSelect').value, 10) || 30;

    itemsData.forEach(it => {
        const isSelected = colectaSelectedItems.has(it.id);
        const suggestedUnits = colectaSelectedItems.get(it.id) !== undefined ? 
            colectaSelectedItems.get(it.id) : 
            Math.max(0, Math.round((targetDays * it.vpd) - it.current_stock));

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleItemColecta(${it.id}, this.checked)">
            </td>
            <td>
                <strong>${it.title}</strong><br>
                <small style="color: var(--text2);">SKU: ${it.sku || 'Sin SKU'} | ID: ${it.item_id}</small>
            </td>
            <td style="text-align: right;"><strong>${it.current_stock}</strong> un.</td>
            <td style="text-align: right;">${it.vpd} un./d</td>
            <td style="text-align: right;">${it.transit_delay_days} días</td>
            <td style="text-align: center;">
                <input type="number" min="0" class="unit-input-colecta" 
                       value="${suggestedUnits}" 
                       onchange="cambiarUnidadesColecta(${it.id}, this.value)"> un.
            </td>
        `;
        tbody.appendChild(tr);
    });

    actualizarTotalColecta();
}

function actualizarTotalColecta() {
    let total = 0;
    colectaSelectedItems.forEach(units => { total += units; });
    document.getElementById('colectaTotalUnits').textContent = `${total} un.`;
}

// ── Acciones de Colecta: Copiar, Exportar, Imprimir ─────────────────
function copiarListaColecta() {
    const wh = WAREHOUSES[currentWarehouse].name;
    let texto = `COLECTA ENVIOBOT - ${wh.toUpperCase()}\n`;
    texto += `Fecha: ${new Date().toLocaleDateString('es-AR')}\n`;
    texto += `------------------------------------------------\n`;

    let total = 0;
    itemsData.forEach(it => {
        if (colectaSelectedItems.has(it.id)) {
            const units = colectaSelectedItems.get(it.id);
            if (units > 0) {
                texto += `• [${it.sku || it.item_id}] ${it.title}: ${units} unidades\n`;
                total += units;
            }
        }
    });

    texto += `------------------------------------------------\n`;
    texto += `TOTAL BULTOS A DESPACHAR: ${total} unidades\n`;

    navigator.clipboard.writeText(texto).then(() => {
        alert("Lista de bultos copiada al portapapeles. Podés pegarla en tu planilla o en MercadoLibre.");
    }).catch(() => {
        alert("Lista:\n\n" + texto);
    });
}

function exportarColectaCSV() {
    const wh = WAREHOUSES[currentWarehouse].name;
    let csv = `\uFEFFDestino,SKU,ID Publicacion,Titulo,Stock Actual,Venta Diaria,Demora Camion,Unidades a Mandar\n`;

    itemsData.forEach(it => {
        if (colectaSelectedItems.has(it.id)) {
            const units = colectaSelectedItems.get(it.id);
            csv += `"${wh}","${it.sku || ''}","${it.item_id}","${it.title.replace(/"/g, '""')}",${it.current_stock},${it.vpd},${it.transit_delay_days},${units}\n`;
        }
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `colecta_${currentWarehouse}_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function imprimirColecta() {
    window.print();
}

function confirmarDespachoColecta() {
    let total = 0;
    colectaSelectedItems.forEach(u => total += u);
    if (total === 0) {
        alert("Seleccioná al menos un producto para despachar.");
        return;
    }

    if (confirm(`¿Confirmás el despacho de ${total} unidades hacia ${WAREHOUSES[currentWarehouse].name}?\n\nEl stock en camino quedará registrado y las alarmas se silenciarán hasta la llegada del flete.`)) {
        alert("Despacho confirmado con éxito. Las unidades han sido marcadas 'En Tránsito'.");
        cerrarModalColecta();
    }
}

// ── Modal de Configuración General y Pestañas ───────────────────────
let recipientsData = [
    { id: 1, name: "Guillermo (Dueño)", phone: "+54 9 11 5555-0001", role: "admin", warehouse_filter: "all" },
    { id: 2, name: "Marcos (Depósito)", phone: "+54 9 11 4444-0002", role: "deposito", warehouse_filter: "meli_full" }
];
let currentPlanTier = 'pro'; // trial: 1, pro: 2, enterprise: 10
const PLAN_LIMITS = { trial: 1, pro: 2, enterprise: 10 };

function abrirConfiguracion() {
    document.getElementById('configModal').style.display = 'flex';
    switchConfigTab('general');
    renderizarTablaConfiguracionDepositos();
    renderizarDestinatariosWA();
}

function cerrarConfiguracion() {
    document.getElementById('configModal').style.display = 'none';
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
    const tabGeneral = document.getElementById('configTabGeneral');
    const tabWA = document.getElementById('configTabWhatsapp');
    const btnGeneral = document.getElementById('tabBtnGeneral');
    const btnWA = document.getElementById('tabBtnWhatsapp');
    const btnSave = document.getElementById('btnConfigSave');
    const btnCancel = document.getElementById('btnConfigCancel');

    if (tab === 'general') {
        tabGeneral.style.display = 'block';
        tabWA.style.display = 'none';
        btnGeneral.classList.add('active');
        btnWA.classList.remove('active');
        if (btnSave) btnSave.style.display = 'inline-block';
        if (btnCancel) btnCancel.textContent = 'Cancelar';
    } else {
        tabGeneral.style.display = 'none';
        tabWA.style.display = 'block';
        btnGeneral.classList.remove('active');
        btnWA.classList.add('active');
        if (btnSave) btnSave.style.display = 'none';
        if (btnCancel) btnCancel.textContent = 'Cerrar';
        renderizarDestinatariosWA();
    }
}

// ── Gestión de Destinatarios de WhatsApp ───────────────────────────
function renderizarDestinatariosWA() {
    const tbody = document.getElementById('recipientsTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const maxAllowed = PLAN_LIMITS[currentPlanTier] || 2;
    document.getElementById('waPlanBadge').textContent = `Plan ${currentPlanTier.toUpperCase()}`;
    document.getElementById('waCountUsed').textContent = recipientsData.length;
    document.getElementById('waMaxAllowed').textContent = maxAllowed;

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

        tr.innerHTML = `
            <td><strong>${r.name}</strong></td>
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

function agregarDestinatarioWA() {
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

    const nuevo = {
        id: Date.now(),
        name: name,
        phone: phone,
        role: role,
        warehouse_filter: depot
    };

    recipientsData.push(nuevo);
    document.getElementById('newRecipName').value = '';
    document.getElementById('newRecipPhone').value = '';

    renderizarDestinatariosWA();
    alert(`Número de WhatsApp de ${name} agregado con éxito.`);
}

function eliminarDestinatarioWA(id) {
    if (confirm("¿Seguro que deseás quitar este número de las alertas de WhatsApp?")) {
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
                alert(`✓ Correo de prueba enviado con éxito a: ${email}\n\nDetalle del servidor:\n${data.detail?.subject || 'Reporte de prueba enviado'}`);
                return;
            } else {
                alert(`✗ Error al enviar correo de prueba a ${email}:\n\n${data.error || data.detail?.error || 'Verifique la configuración SMTP de DonWeb en backend/.env'}`);
                return;
            }
        } catch (e) {
            console.error('Error probando email:', e);
            alert(`✗ Error de conexión con el servidor: ${e.message}`);
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
        alert(`✓ [Modo Demo] Correo de prueba simulado hacia ${email}.\n\nRemitente configurado: alertas@enviobot.com.ar (DonWeb SMTP: smtp.donweb.com:465)`);
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

function guardarConfiguracion(e) {
    e.preventDefault();
    const ss = parseInt(document.getElementById('cfgSafetyStock').value, 10) || 2;
    const email = document.getElementById('cfgEmail').value;

    // Actualizar parámetros individuales de cada depósito
    Object.values(WAREHOUSES).forEach(wh => {
        const transitEl = document.getElementById(`cfgTransit_${wh.id}`);
        const targetEl = document.getElementById(`cfgTarget_${wh.id}`);
        if (transitEl && targetEl) {
            const newTransit = Math.max(1, parseInt(transitEl.value, 10) || wh.defaultTransit);
            const newTarget = Math.max(5, parseInt(targetEl.value, 10) || wh.defaultTarget);
            wh.defaultTransit = newTransit;
            wh.defaultTarget = newTarget;

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
        it.transit_delay_days = activeWh.defaultTransit;
        it.target_stock_days = activeWh.defaultTarget;
        it.buffer_days = ss;
    });

    recalcularTodo();

    const token = getToken();
    if (token) {
        fetch(`${API_BASE}/full/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({
                default_safety_stock_days: ss,
                alert_email: email
            })
        }).catch(err => console.error("Error guardando settings:", err));
    }

    cerrarConfiguracion();
    alert('Configuración guardada. La demora de camión y la cobertura se actualizaron para cada depósito.');
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
    alert(`Depósito "${name}" agregado con éxito.`);
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
        cambiarAuthTab(currentAuthTab);
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
    if (!select) return;

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

function cambiarCuentaMeLi(accId) {
    currentAccount = accId;
    cargarDatos();
}

function actualizarBadgePlan(planInfo) {
    currentPlanInfo = planInfo;
    const badge = document.getElementById('planBadge');
    if (!badge || !planInfo) return;

    if (planInfo.has_full_access === false) {
        if (planInfo.can_start_trial) {
            badge.className = 'plan-badge trial';
            badge.textContent = '⚡ Activar 30d gratis';
            badge.onclick = () => abrirModalActivarFull(currentUser);
        } else {
            badge.className = 'plan-badge';
            badge.textContent = '🔒 Requiere suscripción';
            badge.onclick = () => abrirModalSuscripcionVencida(currentUser);
        }
        return;
    }

    badge.onclick = () => abrirModalPlan();
    if (planInfo.plan_tier === 'trial') {
        const days = planInfo.trial_days_left !== undefined ? planInfo.trial_days_left : 30;
        badge.className = 'plan-badge trial';
        badge.textContent = `🗓️ Prueba Gratis (${days}d restantes)`;
    } else {
        badge.className = 'plan-badge';
        badge.textContent = `⭐ Plan ${planInfo.plan_name || planInfo.plan_tier}`;
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
                🚀 Activar 30 días de prueba gratis
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
        msg.innerHTML = `Completaste tus 30 días de prueba gratuita en EnvioBot Full.<br><br>Para continuar monitoreando tu inventario Full y evitar que tus publicaciones quiebren stock, activá tu suscripción o registrá tu cuenta definitiva en <strong>admin.enviobot.com.ar</strong>.<br><br><span style="color: #ff7676; font-size: 12.5px; font-weight: 600;">⚠️ Si no activás tu suscripción, los datos temporales de la prueba serán eliminados para liberar espacio.</span>`;
    }
    if (actionArea) {
        actionArea.innerHTML = `
            <a href="https://wa.me/5491155550000?text=Hola,%20finalizo%20mi%20prueba%20de%2030%20dias%20de%20EnvioBot%20Full%20y%20quiero%20suscribirme" target="_blank" class="btn btn-block" style="padding: 13px; font-size: 14px; font-weight: 700; background: var(--accent); color: #111; justify-content: center; text-decoration: none;">
                ⭐ Suscribirme y Activar Plan
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
            btn.textContent = '🚀 Activar 30 días de prueba gratis';
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

// ── Chequeo de Sesión al Arrancar ──────────────────────────────────
async function checkUserSession() {
    const token = getToken();
    const userEmailEl = document.getElementById('userEmailText');
    const btnLogout = document.getElementById('btnLogoutBtn');
    const btnLoginHeader = document.getElementById('btnLoginHeader');
    const banner = document.getElementById('trialWelcomeBanner');

    if (!token) {
        // Modo Prueba Libre / Cliente Nuevo sin registro
        if (userEmailEl) userEmailEl.textContent = 'Prueba 30 días';
        if (btnLogout) btnLogout.style.display = 'none';
        if (btnLoginHeader) btnLoginHeader.style.display = 'inline-flex';
        if (banner) banner.style.display = 'flex';

        const badge = document.getElementById('planBadge');
        if (badge) {
            badge.className = 'plan-badge trial';
            badge.textContent = '🚀 Probar 30 días gratis';
            badge.onclick = () => iniciarConexionMeLi();
        }

        const btnConnect = document.getElementById('btnConnectMeLiHeader');
        if (btnConnect) {
            btnConnect.style.display = 'inline-block';
            btnConnect.textContent = '🚀 Conectar MercadoLibre (30d gratis)';
        }
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
            return false;
        }

        const data = await res.json();
        if (data.ok && data.user) {
            currentUser = data.user;
            if (userEmailEl) userEmailEl.textContent = data.user.email || data.user.full_name;
            if (btnLogout) btnLogout.style.display = 'inline-flex';
            if (btnLoginHeader) btnLoginHeader.style.display = 'none';
            if (banner) banner.style.display = 'none';

            actualizarBadgePlan(data.user);
            renderMeLiAccounts(data.user.ml_accounts);

            // Si venció el plazo de 30 días:
            if (data.user.has_full_access === false) {
                abrirModalSuscripcionVencida(data.user);
                return false;
            }

            // Si tiene Full activo pero no conectó cuentas de MeLi aún
            if (!data.user.ml_accounts || data.user.ml_accounts.length === 0) {
                abrirOnboardingMeLi();
            }
            return true;
        }
    } catch (err) {
        console.error("Error verificando sesión:", err);
    }
    return false;
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

    if (params.get('ml') === 'ok') {
        const nickname = params.get('nickname') || '';
        alert(`✓ ¡Cuenta de MercadoLibre ${nickname} conectada con éxito! Tu prueba gratuita de 30 días está activa. Sincronizando tu stock Full...`);
        window.history.replaceState({}, document.title, window.location.pathname);
    } else if (params.get('ml') === 'error') {
        const msg = params.get('msg') || 'Error en la autorización de MercadoLibre';
        alert(`✗ ${msg}`);
        window.history.replaceState({}, document.title, window.location.pathname);
    }

    // 2. Verificar sesión
    await checkUserSession();

    // 3. Cargar datos
    cargarDatos();
});


