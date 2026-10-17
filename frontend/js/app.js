// =====================================================================
// app.js - Lógica del Panel de Control de EnvioBot Full
// Monitoreo multi-depósito, cálculo de quiebre, alarmas y colecta agrupada
// =====================================================================

const API_BASE = window.location.protocol === 'file:' ? 'http://localhost:5001/api' : '/api';

// Escapa datos de afuera (nombres, títulos, SKU) antes de pintarlos con innerHTML.
function escapeHtml(valor) {
    return String(valor == null ? '' : valor)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Íconos de contorno (criterio común: viewBox 24, trazo ~1.7, color heredado, nunca emojis).
// Como son HTML, hay que usarlos con innerHTML y escapar con escapeHtml() todo dato de afuera.
const ICONOS_SVG = {
    alerta: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    campana: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M4 4L2.5 5.5M20 4l1.5 1.5"/>',
    calendario: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    paquete: '<line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
    candado: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    llama: '<path d="M12 12c2-2.96 0-7-1-8 0 3.038-1.773 4.741-3 6-1.226 1.26-2 3.24-2 5a6 6 0 1 0 12 0c0-1.532-1.056-3.94-2-5-1.786 3-2.791 3-4 2z"/>',
    reloj: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    bombilla: '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.3h6c0-1 .4-1.8 1-2.3A7 7 0 0 0 12 2z"/>',
    radar: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    capas: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    escudo: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/>',
    camion: '<rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>'
};

function iconoSvg(nombre, tam = 14) {
    return `<svg width="${tam}" height="${tam}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -2px; margin-right: 4px;" aria-hidden="true">${ICONOS_SVG[nombre] || ''}</svg>`;
}

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
let currentLogisticEvents = [];
let currentNextLogisticEvent = null;
let activeColectaMultiplier = 1.0;
let activeColectaEventName = '';

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
window.setItemsData = (items) => { itemsData = items; };
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
            cargarMonitorEventosLogisticos();
            if (data.items && data.items.length > 0) {
                itemsData = data.items.map(it => adaptarItemDesdeBackend(it));
                proximaColecta = data.proxima_colecta || null;
                recalcularTodo();
                renderizarPanelColecta();
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
        in_preparation_stock: raw.in_preparation_stock || 0,
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
        backend_status: raw.status || 'ok',
        units_per_box: raw.units_per_box || 0,
        dias_hasta_ingreso: raw.dias_hasta_ingreso !== undefined ? raw.dias_hasta_ingreso : null,
        stock_al_ingreso: raw.stock_al_ingreso !== undefined ? raw.stock_al_ingreso : null,
        cobertura_post_colecta: raw.cobertura_post_colecta !== undefined ? raw.cobertura_post_colecta : null,
        sugerido_al_ingreso: raw.sugerido_al_ingreso || 0,
        aviso_ajuste_units: raw.aviso_ajuste_units || null,
        fecha_ingreso: raw.fecha_ingreso || null,
        prep_item_id: raw.prep_item_id || null,
        prep_status: raw.prep_status || null,
        dias_sin_stock_30d: raw.dias_sin_stock_30d || 0,
        sobrestock: !!raw.sobrestock,
        umbral_sobrestock: raw.umbral_sobrestock || null
    };
}

// ── Panel de colecta: cuenta regresiva + colecta en preparación + radar ─────────
let proximaColecta = null;
let panelColectaTimer = null;

function textoCuentaRegresiva(limiteIso) {
    const ms = new Date(limiteIso).getTime() - Date.now();
    if (!(ms > 0)) return null;
    const minTotal = Math.floor(ms / 60000);
    const dias = Math.floor(minTotal / 1440);
    const horas = Math.floor((minTotal % 1440) / 60);
    const min = minTotal % 60;
    const partes = [];
    if (dias) partes.push(`${dias} ${dias === 1 ? 'día' : 'días'}`);
    if (horas || dias) partes.push(`${horas} ${horas === 1 ? 'hora' : 'horas'}`);
    if (!dias) partes.push(`${min} min`);
    return partes.join(' y ');
}

// "jueves 22/10 a las 09:40", siempre en hora de Buenos Aires.
function textoLimiteEdicion(limiteIso) {
    const partes = {};
    new Intl.DateTimeFormat('es-AR', {
        weekday: 'long', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
        hourCycle: 'h23', timeZone: 'America/Argentina/Buenos_Aires'
    }).formatToParts(new Date(limiteIso)).forEach(p => { partes[p.type] = p.value; });
    return `${partes.weekday} ${partes.day}/${partes.month} a las ${partes.hour}:${partes.minute}`;
}

// Misma regla que proyeccion.aviso_ajuste: se sugiere solo si lo cargado cubre menos del 80 % del objetivo.
const TOLERANCIA_AVISO_AJUSTE = 0.8;

// Unidades que conviene mandar de un producto de la colecta que se está editando, o null si lo
// cargado está bien. Se calcula con los datos de hoy del panel (objetivo del depósito, stock al
// ingreso), no con un número guardado al crear la colecta.
function sugeridoEdicion(it) {
    const vivo = (itemsData || []).find(x =>
        (it.inventory_id && x.inventory_id === it.inventory_id) ||
        (it.sku && x.sku === it.sku) ||
        (it.item_id && x.item_id === it.item_id));
    if (!vivo || !(vivo.vpd > 0) || vivo.stock_al_ingreso === null || vivo.stock_al_ingreso === undefined) return null;
    const objetivo = vivo.target_stock_days || 30;
    const unidades = it.units_to_send || 0;
    if ((vivo.stock_al_ingreso + unidades) / vivo.vpd >= objetivo * TOLERANCIA_AVISO_AJUSTE) return null;
    const ideal = Math.max(0, Math.round(objetivo * vivo.vpd - vivo.stock_al_ingreso));
    return ideal > unidades ? ideal : null;
}

const ESTADOS_GALPON = [['to_buy', 'A comprar'], ['packing', 'Envasando'], ['boxed', 'Listo en caja']];

function selectorGalpon(it) {
    const opciones = ESTADOS_GALPON.map(([valor, nombre]) =>
        `<option value="${valor}"${it.prep_status === valor ? ' selected' : ''}>${nombre}</option>`).join('');
    return `<select class="filter-select pc-galpon" data-previo="${escapeHtml(it.prep_status)}" onchange="cambiarEstadoGalpon(${Number(it.prep_item_id)}, this)">${opciones}</select>`;
}

async function cambiarEstadoGalpon(prepItemId, selectEl) {
    const nuevo = selectEl.value;
    const previo = selectEl.getAttribute('data-previo');
    try {
        const res = await fetch(`${API_BASE}/full/inbound/items/${prepItemId}/prep`, {
            method: 'PUT',
            headers: { 'Authorization': `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ prep_status: nuevo })
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'No se pudo guardar');
        selectEl.setAttribute('data-previo', nuevo);
        const it = itemsData.find(x => x.prep_item_id === prepItemId);
        if (it) it.prep_status = nuevo;
    } catch (err) {
        selectEl.value = previo;  // si falla, queda lo anterior
        showToast(err.message || 'No se pudo guardar el estado', 'error');
    }
}

// ── Ajustes de colecta (Configuración): umbral de exceso y hora límite ──────────
async function cargarAjustesColecta() {
    const aviso = document.getElementById('ajColectaAviso');
    if (!aviso) return;
    try {
        const res = await fetch(`${API_BASE}/full/ajustes-colecta`, { headers: { 'Authorization': `Bearer ${getToken()}` } });
        const data = await res.json();
        if (!data.ok) return;
        document.getElementById('ajSobrestockFactor').value = String(data.sobrestock_factor).replace('.', ',');
        document.getElementById('ajHoraLimite').value = data.hora_limite;
        const bloqueado = !data.editable;
        document.getElementById('ajSobrestockFactor').disabled = bloqueado;
        document.getElementById('ajHoraLimite').disabled = bloqueado;
        document.getElementById('btnGuardarAjColecta').disabled = bloqueado;
        aviso.textContent = bloqueado
            ? 'Estos ajustes se habilitan con la próxima actualización de la base. Mientras tanto rigen los valores que ves.'
            : 'Cómo se marca el exceso de stock y hasta qué hora se puede modificar una colecta.';
    } catch (err) {
        console.warn('No se pudieron cargar los ajustes de colecta:', err);
    }
}

async function guardarAjustesColecta() {
    try {
        const res = await fetch(`${API_BASE}/full/ajustes-colecta`, {
            method: 'PUT',
            headers: { 'Authorization': `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sobrestock_factor: document.getElementById('ajSobrestockFactor').value,
                hora_limite: document.getElementById('ajHoraLimite').value
            })
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'No se pudo guardar');
        showToast('Ajustes de colecta guardados', 'success');
        cargarDatos();
    } catch (err) {
        showToast(err.message || 'No se pudo guardar', 'error');
    }
}

// "lunes 19/10" a partir de "2026-10-19" (sin depender de la zona horaria del navegador).
function nombreDiaColecta(iso) {
    if (!iso) return '';
    const [a, m, d] = String(iso).slice(0, 10).split('-').map(Number);
    const dias = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
    const dia = dias[new Date(Date.UTC(a, m - 1, d)).getUTCDay()];
    return `${dia} ${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}`;
}

function formatearFechaCorta(iso) {
    if (!iso) return '-';
    const [a, m, d] = String(iso).slice(0, 10).split('-');
    return `${d}/${m}`;
}

function nombreItemPanel(it) {
    const variacion = it.variation_name ? ` (${escapeHtml(it.variation_name)})` : '';
    return `${escapeHtml(it.title)}${variacion}<span class="pc-sku">${it.sku ? escapeHtml(it.sku) : ''}</span>`;
}

// ── Panel de inicio: estado general, colecta, qué hacer hoy ─────────────────────────────
// Reparte los productos en grupos que el usuario entiende sin explicación:
//  - urgentes / conviene mandar pronto: faltan y todavía no están en ninguna colecta
//  - tienen de más: cobertura por encima del umbral de exceso
//  - tranquilos: todo lo demás (incluye lo que ya viaja en una colecta)
function clasificarItemsPanel(items) {
    const g = { urgentes: [], pronto: [], deMas: [], tranquilos: [], enColecta: [] };
    items.forEach(it => {
        const cubierto = (it.total_incoming || 0) > 0;
        if (it.sobrestock) g.deMas.push(it);
        else if (!cubierto && (it.status === 'critical' || it.status === 'out_of_stock')) g.urgentes.push(it);
        else if (!cubierto && it.status === 'warning') g.pronto.push(it);
        else g.tranquilos.push(it);
        if ((it.in_preparation_stock || 0) > 0) g.enColecta.push(it);
    });
    return g;
}

function pluralizar(n, singular, plural) {
    return `${n} ${n === 1 ? singular : plural}`;
}

// Barra de días de cobertura: la escala llega al doble del objetivo y la raya blanca marca el objetivo.
function barraCobertura(dias, objetivo, clase) {
    const escala = Math.max(1, (objetivo || 30) * 2);
    const pct = Math.max(0, Math.min(100, ((dias || 0) / escala) * 100));
    return `<div class="pc-bar"><div class="pc-bar-fill ${clase}" style="width: ${pct.toFixed(1)}%"></div><div class="pc-bar-meta"></div></div>`;
}

function filaConBarra(it, opciones) {
    return `<div class="pc-fila">
        <div class="pc-fila-top">
            <span class="pc-fila-nombre">${opciones.icono}${escapeHtml(it.title)}${it.variation_name ? ` (${escapeHtml(it.variation_name)})` : ''}</span>
            <span class="${opciones.claseDerecha || 'pc-accion'}">${opciones.derecha}</span>
        </div>
        ${barraCobertura(opciones.dias, it.target_stock_days, opciones.claseBarra)}
        <div class="pc-fila-nota">${opciones.nota}</div>
    </div>`;
}

function seccionPanel(titulo, contenidoHtml) {
    return `<div><h3 class="pc-block-title">${titulo}</h3><div class="pc-lista">${contenidoHtml}</div></div>`;
}

function tarjetaEstadoGeneral(g, total) {
    const accion = g.urgentes.length + g.pronto.length;
    let icono, clase, titulo, sub;
    if (g.urgentes.length > 0) {
        icono = iconoSvg('alerta', 28); clase = 'pc-hero-urgente';
        titulo = `Atención: ${pluralizar(g.urgentes.length, 'producto está', 'productos están')} por quedarse sin stock y todavía no ${g.urgentes.length === 1 ? 'está' : 'están'} en una colecta`;
        sub = 'Armá una colecta con ellos para no quebrar. Abajo te digo cuántas unidades mandar.';
    } else if (g.pronto.length > 0) {
        icono = iconoSvg('reloj', 28); clase = 'pc-hero-pronto';
        titulo = `Vas bien: ${total - accion} de tus ${total} productos están cubiertos`;
        sub = `${pluralizar(g.pronto.length, 'producto conviene', 'productos convienen')} mandarlo en tu próxima colecta. Todavía hay tiempo.`;
    } else {
        icono = iconoSvg('escudo', 28); clase = 'pc-hero-ok';
        titulo = `Todo bajo control: tus ${total} productos tienen stock suficiente`;
        sub = g.enColecta.length > 0 ? 'Contando lo que ya viaja en tu colecta.' : 'No hace falta armar ninguna colecta por ahora.';
    }
    const seg = (n, color) => n > 0 ? `<div style="flex: ${n}; background: var(${color});"></div>` : '';
    const dato = (n, color, texto, estado) => n > 0
        ? `<span class="pc-leyenda-item${estado ? ' pc-click' : ''}"${estado ? ` onclick="irAEstado('${estado}')"` : ''}><span style="color: var(${color});">●</span> ${escapeHtml(texto)}</span>` : '';
    return `<div class="pc-hero ${clase}">
        <div class="pc-hero-top"><span class="pc-hero-icono">${icono.replace('margin-right: 4px;', '')}</span>
            <div><div class="pc-hero-titulo">${titulo}</div><div class="pc-hero-sub">${sub}</div></div></div>
        <div class="pc-segmentos">${seg(g.tranquilos.length, '--good')}${seg(g.pronto.length, '--warn')}${seg(g.urgentes.length, '--danger')}${seg(g.deMas.length, '--info')}</div>
        <div class="pc-leyenda">
            ${dato(g.tranquilos.length, '--good', `${g.tranquilos.length} tranquilos`, 'ok')}
            ${dato(g.pronto.length, '--warn', `${g.pronto.length} conviene mandar pronto`, 'warning')}
            ${dato(g.urgentes.length, '--danger', `${g.urgentes.length} urgentes`, 'critical')}
            ${dato(g.deMas.length, '--info', `${g.deMas.length} tienen de más`, '')}
        </div></div>`;
}

function tablaProductosColecta(enColecta) {
    const hayGalpon = enColecta.some(it => it.prep_item_id && it.prep_status);
    const filas = enColecta.map(it => {
        const celdaGalpon = hayGalpon ? `<td>${it.prep_item_id ? selectorGalpon(it) : ''}</td>` : '';
        const cob = it.cobertura_post_colecta;
        return `<tr>
            <td>${nombreItemPanel(it)}</td>
            <td class="pc-num">${escapeHtml(it.in_preparation_stock)} u.</td>
            ${celdaGalpon}
            <td class="pc-num">${formatearFechaCorta(it.fecha_ingreso)}</td>
            <td class="pc-num">${cob === null ? '-' : `${Math.round(cob)} días`}</td>
        </tr>`;
    }).join('');
    return `<table class="pc-table">
        <thead><tr><th>Producto</th><th class="pc-num">Unidades</th>${hayGalpon ? '<th>Galpón</th>' : ''}<th class="pc-num">Ingresa</th><th class="pc-num">Cubre al ingresar</th></tr></thead>
        <tbody>${filas}</tbody></table>`;
}

function tarjetaColecta(enColecta) {
    if (!proximaColecta && enColecta.length === 0) return '';
    const resto = proximaColecta ? textoCuentaRegresiva(proximaColecta.limite_edicion) : null;
    const ms = proximaColecta ? new Date(proximaColecta.limite_edicion).getTime() - Date.now() : 0;
    const clase = proximaColecta ? (!resto ? 'pc-cerrada' : (ms <= 3600000 ? 'pc-urgente' : '')) : '';
    const unidades = enColecta.reduce((a, it) => a + (it.in_preparation_stock || 0), 0);
    const ingresos = enColecta.map(it => it.fecha_ingreso).filter(Boolean).sort();
    const entra = ingresos.length ? ` Entra a Full el ${escapeHtml(nombreDiaColecta(ingresos[ingresos.length - 1]))}.` : '';
    const titulo = proximaColecta ? `Tu colecta del ${escapeHtml(nombreDiaColecta(proximaColecta.fecha_retiro))}` : 'Tenés una colecta en preparación';
    const codigo = proximaColecta && proximaColecta.codigo ? ` <span class="pc-sku-inline">${escapeHtml(proximaColecta.codigo)}</span>` : '';
    const cuanto = enColecta.length ? `${pluralizar(enColecta.length, 'producto', 'productos')}, ${unidades.toLocaleString('es-AR')} unidades. ` : '';
    let estado = '';
    if (proximaColecta) {
        const lim = textoLimiteEdicion(proximaColecta.limite_edicion);
        estado = resto
            ? `Podés modificarla hasta el ${escapeHtml(lim)} (faltan ${escapeHtml(resto)}).`
            : `Ya no se puede cambiar: cerró el ${escapeHtml(lim)}.`;
    }
    const detalle = enColecta.length
        ? `<details class="pc-detalle"><summary>Ver los ${enColecta.length} productos</summary>${tablaProductosColecta(enColecta)}</details>` : '';
    return `<div class="pc-banner ${clase}">
        <span class="pc-banner-icon">${iconoSvg('camion', 24).replace('margin-right: 4px;', '')}</span>
        <div class="pc-banner-text">
            <div class="pc-banner-titulo">${titulo}${codigo}</div>
            <div class="pc-banner-sub">${cuanto}${estado}${entra}</div>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" onclick="abrirHistorialColectas()">Ver detalle</button>
        ${detalle}
    </div>`;
}

function renderizarPanelColecta() {
    const cont = document.getElementById('panelColecta');
    if (!cont) return;
    if (!itemsData || itemsData.length === 0) {
        cont.style.display = 'none';
        return;
    }
    const g = clasificarItemsPanel(itemsData);
    const abierta = proximaColecta ? !!textoCuentaRegresiva(proximaColecta.limite_edicion) : false;
    const maxFilas = 8;

    // Qué hacer hoy: faltan y todavía no están en una colecta (urgentes primero)
    const hacer = g.urgentes.slice().sort((a, b) => (a.days_left || 0) - (b.days_left || 0))
        .map(it => ({ it, urgente: true }))
        .concat(g.pronto.slice().sort((a, b) => (a.days_left || 0) - (b.days_left || 0)).map(it => ({ it, urgente: false })));
    let htmlHacer;
    if (hacer.length === 0) {
        htmlHacer = '<div class="pc-vacio">Hoy no tenés nada pendiente.</div>';
    } else {
        htmlHacer = hacer.slice(0, maxFilas).map(({ it, urgente }) => filaConBarra(it, {
            icono: iconoSvg(urgente ? 'alerta' : 'reloj', 15).replace('margin-right: 4px;', 'margin-right: 6px;'),
            derecha: it.sugerido_al_ingreso > 0 ? `Mandar ${escapeHtml(it.sugerido_al_ingreso)} u. en la próxima colecta` : 'Revisar',
            dias: it.current_stock > 0 ? it.days_left : 0,
            claseBarra: urgente ? 'pc-fill-danger' : 'pc-fill-warn',
            nota: it.current_stock > 0
                ? `Te alcanza para ${Math.round(it.days_left || 0)} ${Math.round(it.days_left || 0) === 1 ? 'día' : 'días'}. Objetivo: ${escapeHtml(it.target_stock_days)} días.`
                : `Sin stock hoy. Objetivo: ${escapeHtml(it.target_stock_days)} días.`
        })).join('');
        if (hacer.length > maxFilas) {
            htmlHacer += `<div class="pc-mas">Y ${hacer.length - maxFilas} más. <a onclick="irAEstado('action_required')">Verlos en la lista completa</a></div>`;
        }
    }

    // Ya en la colecta, pero conviene ajustar
    const cortos = g.enColecta.filter(it => it.aviso_ajuste_units);
    const htmlAjustar = cortos.length === 0 ? '' : seccionPanel(
        'Ya en tu colecta, pero conviene ajustar',
        cortos.map(it => filaConBarra(it, {
            icono: iconoSvg('bombilla', 15).replace('margin-right: 4px;', 'margin-right: 6px;'),
            derecha: `Con ${escapeHtml(it.in_preparation_stock)} u. cubrís ${Math.round(it.cobertura_post_colecta || 0)} días: convendría ${escapeHtml(it.aviso_ajuste_units)}`,
            dias: it.cobertura_post_colecta,
            claseBarra: 'pc-fill-good',
            nota: abierta ? 'Todavía podés ajustarlo.' : 'Esta colecta ya no se puede cambiar: ajustalo en la siguiente.'
        })).join(''));

    // Tienen de más
    const deMas = g.deMas.slice().sort((a, b) => (b.covered_days_left || 0) - (a.covered_days_left || 0));
    const htmlDeMas = deMas.length === 0 ? '' : seccionPanel(
        'Tienen de más (no mandes más por ahora)',
        deMas.slice(0, 6).map(it => filaConBarra(it, {
            icono: iconoSvg('capas', 15).replace('margin-right: 4px;', 'margin-right: 6px;'),
            derecha: `Tenés para ${Math.round(it.covered_days_left || 0)} días`,
            claseDerecha: 'pc-info',
            dias: it.covered_days_left,
            claseBarra: 'pc-fill-info',
            nota: `Objetivo: ${escapeHtml(it.target_stock_days)} días.`
        })).join('') + (deMas.length > 6 ? `<div class="pc-mas">Y ${deMas.length - 6} más.</div>` : ''));

    cont.innerHTML = tarjetaEstadoGeneral(g, itemsData.length)
        + tarjetaColecta(g.enColecta)
        + seccionPanel('Qué hacer hoy', htmlHacer)
        + htmlAjustar
        + htmlDeMas;
    cont.style.display = 'flex';

    // La cuenta regresiva se refresca sola cada minuto.
    if (!panelColectaTimer) {
        panelColectaTimer = setInterval(renderizarPanelColecta, 60000);
    }
}

// ── Motor de cálculo de quiebre y semáforos ────────────────────────
function recalcularTodo() {
    const today = new Date();

    itemsData.forEach(it => {
        const stock = it.current_stock;
        const inProcess = it.in_process_stock || 0;
        const inPrep = it.in_preparation_stock || 0;
        const inTransit = it.in_transit_stock || 0;
        const totalIncoming = inProcess + inPrep + inTransit;
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

            // Semáforo inteligente considerando mercadería entrante (en recepción Full, en tránsito o en preparación)
            if (stock <= 0) {
                if (inProcess > 0) {
                    it.status = 'in_reception';
                } else if (inTransit > 0) {
                    it.status = 'in_transit';
                } else if (inPrep > 0) {
                    it.status = 'in_preparation';
                } else {
                    it.status = 'out_of_stock';
                }
            } else if (inProcess > 0 && (stock + inProcess) / Math.max(vpd, 0.01) > (prep + transit)) {
                it.status = 'in_reception';
            } else if (inTransit > 0 && (stock + inProcess + inTransit) / Math.max(vpd, 0.01) > (prep + transit)) {
                it.status = 'in_transit';
            } else if (inPrep > 0) {
                it.status = 'in_preparation';
            } else if (it.days_left <= (prep + transit)) {
                it.status = 'critical';
            } else if (it.days_left <= totalAdvance) {
                it.status = 'warning';
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
                else if (inPrep > 0) it.status = 'in_preparation';
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
        else if (it.status === 'in_reception' || it.status === 'in_transit' || it.status === 'in_preparation') inProcess++;
        else crit++;

        const targetDays = it.target_stock_days || wh.defaultTarget || 30;
        const totalCovered = it.current_stock + (it.in_process_stock || 0) + (it.in_transit_stock || 0) + (it.in_preparation_stock || 0);
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

// ── Navegación Rápida por Tarjetas Superiores y Resaltado ──────────
function actualizarCardsActivas(activeCardId) {
    ['statCardTotal', 'statCardOk', 'statCardWarning', 'statCardCritical'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (id === activeCardId) {
            el.classList.add('stat-active');
        } else {
            el.classList.remove('stat-active');
        }
    });
}

function irAQuiebreInminente() {
    actualizarCardsActivas('statCardCritical');

    // 1. Filtrar por crítico / sin stock
    currentFilter = 'critical';
    const filterSelect = document.getElementById('filterStatusSelect');
    if (filterSelect) filterSelect.value = 'critical';

    // 2. Limpiar búsqueda para asegurar visibilidad del artículo crítico
    currentSearch = '';
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.value = '';

    // 3. Ordenar por días restantes (ascendente) para que el más urgente quede al inicio
    currentSortColumn = 'days_left';
    currentSortOrder = 'asc';

    // 4. Renderizar la tabla con este filtro
    renderizarTabla();

    // 5. Encontrar el artículo con mayor urgencia (sin stock o quiebre inminente)
    const critItems = itemsData.filter(it => it.status === 'critical' || it.status === 'out_of_stock' || it.current_stock <= 0);
    critItems.sort((a, b) => {
        const daysA = a.days_left !== undefined ? a.days_left : 999;
        const daysB = b.days_left !== undefined ? b.days_left : 999;
        return daysA - daysB;
    });

    const targetItem = critItems[0];

    // 6. Hacer scroll suave hacia ese artículo y resaltarlo con destello dorado
    setTimeout(() => {
        if (targetItem) {
            const rowEl = document.getElementById(`stock_row_${targetItem.id}`);
            if (rowEl) {
                rowEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                rowEl.classList.remove('row-highlight');
                void rowEl.offsetWidth; // Forzar reflow para reiniciar animación
                rowEl.classList.add('row-highlight');
                return;
            }
        }
        const tableCard = document.getElementById('cardStockPrincipal');
        if (tableCard) tableCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 60);
}

function irAEstado(estado) {
    if (estado === 'critical') {
        irAQuiebreInminente();
        return;
    }

    const cardMap = {
        'all': 'statCardTotal',
        'ok': 'statCardOk',
        'warning': 'statCardWarning',
        'critical': 'statCardCritical'
    };
    actualizarCardsActivas(cardMap[estado] || null);

    currentFilter = estado;
    const filterSelect = document.getElementById('filterStatusSelect');
    if (filterSelect) filterSelect.value = estado;

    renderizarTabla();

    setTimeout(() => {
        if (estado === 'warning') {
            const warnItem = itemsData.find(it => it.status === 'warning');
            if (warnItem) {
                const rowEl = document.getElementById(`stock_row_${warnItem.id}`);
                if (rowEl) {
                    rowEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    rowEl.classList.remove('row-highlight');
                    void rowEl.offsetWidth;
                    rowEl.classList.add('row-highlight');
                    return;
                }
            }
        }
        const tableCard = document.getElementById('cardStockPrincipal');
        if (tableCard) tableCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 60);
}

function abrirModalColectaConItem(id) {
    abrirModalColecta(id);
}

// Exponer globalmente para eventos en HTML inline
window.actualizarCardsActivas = actualizarCardsActivas;
window.irAQuiebreInminente = irAQuiebreInminente;
window.irAEstado = irAEstado;
window.abrirModalColectaConItem = abrirModalColectaConItem;

// ── Estado y Lógica de Ordenamiento de Columnas ───────────────────
let currentSortColumn = 'days_left';
let currentSortOrder = 'asc';

function ordenarPor(columna) {
    if (currentSortColumn === columna) {
        currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
    } else {
        currentSortColumn = columna;
        // Orden predeterminado según el tipo de columna
        currentSortOrder = (columna === 'title') ? 'asc' : 'asc';
    }
    actualizarIconosOrden();
    renderizarTabla();
}

function actualizarIconosOrden() {
    const cols = ['title', 'current_stock', 'vpd', 'days_left', 'stockout_date', 'reorder_deadline_date', 'target_stock_days', 'status'];
    cols.forEach(col => {
        const icon = document.getElementById(`sort-icon-${col}`);
        if (!icon) return;
        if (col === currentSortColumn) {
            icon.className = 'sort-icon active';
            icon.textContent = currentSortOrder === 'asc' ? '▲' : '▼';
        } else {
            icon.className = 'sort-icon';
            icon.textContent = '↕';
        }
    });
}

// ── Renderizado de la Tabla Principal (Estilo Sobrio y Despojado) ─
function renderizarTabla() {
    actualizarIconosOrden();
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
        } else if (currentFilter === 'critical') {
            matchStatus = it.status === 'critical' || it.status === 'out_of_stock' || it.current_stock <= 0;
        } else if (currentFilter !== 'all') {
            matchStatus = it.status === currentFilter;
        }

        return matchSearch && matchStatus;
    });

    if (filtrados.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 30px; color: var(--text2);">No hay publicaciones con los filtros seleccionados.</td></tr>';
        return;
    }

    // Ordenamiento por columna activa
    filtrados.sort((a, b) => {
        let valA, valB;
        if (currentSortColumn === 'title') {
            valA = (a.title || a.sku || '').toLowerCase();
            valB = (b.title || b.sku || '').toLowerCase();
            const cmp = valA.localeCompare(valB);
            return currentSortOrder === 'asc' ? cmp : -cmp;
        } else if (currentSortColumn === 'current_stock') {
            valA = Number(a.current_stock !== undefined ? a.current_stock : 0);
            valB = Number(b.current_stock !== undefined ? b.current_stock : 0);
        } else if (currentSortColumn === 'vpd') {
            valA = Number(a.vpd !== undefined ? a.vpd : 0);
            valB = Number(b.vpd !== undefined ? b.vpd : 0);
        } else if (currentSortColumn === 'days_left') {
            valA = Number(a.days_left !== undefined ? a.days_left : 999);
            valB = Number(b.days_left !== undefined ? b.days_left : 999);
        } else if (currentSortColumn === 'stockout_date') {
            valA = a.current_stock <= 0 ? '0000-00-00' : (a.stockout_date || '9999-99-99');
            valB = b.current_stock <= 0 ? '0000-00-00' : (b.stockout_date || '9999-99-99');
            const cmp = valA.localeCompare(valB);
            return currentSortOrder === 'asc' ? cmp : -cmp;
        } else if (currentSortColumn === 'reorder_deadline_date') {
            valA = a.current_stock <= 0 ? '0000-00-00' : (a.reorder_deadline_date || '9999-99-99');
            valB = b.current_stock <= 0 ? '0000-00-00' : (b.reorder_deadline_date || '9999-99-99');
            const cmp = valA.localeCompare(valB);
            return currentSortOrder === 'asc' ? cmp : -cmp;
        } else if (currentSortColumn === 'target_stock_days') {
            valA = Number(a.target_stock_days !== undefined ? a.target_stock_days : 0);
            valB = Number(b.target_stock_days !== undefined ? b.target_stock_days : 0);
        } else if (currentSortColumn === 'status') {
            const statusOrder = { 'out_of_stock': 1, 'critical': 2, 'warning': 3, 'in_preparation': 4, 'in_transit': 5, 'in_reception': 6, 'ok': 7 };
            valA = statusOrder[a.status] || 99;
            valB = statusOrder[b.status] || 99;
        } else {
            valA = a[currentSortColumn];
            valB = b[currentSortColumn];
        }

        if (valA < valB) return currentSortOrder === 'asc' ? -1 : 1;
        if (valA > valB) return currentSortOrder === 'asc' ? 1 : -1;
        return 0;
    });

    filtrados.forEach(it => {
        const tr = document.createElement('tr');
        tr.id = `stock_row_${it.id}`;
        tr.dataset.status = it.status;
        tr.style.cursor = 'pointer';
        tr.onclick = (e) => {
            if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'A' && e.target.tagName !== 'BUTTON') {
                seleccionarProducto(it);
            }
        };

        // Estado Sobrio (Texto limpio, sin cajas llamativas)
        let badgeHtml = '';
        if (it.status === 'ok') {
            badgeHtml = '<span class="badge badge-ok">Óptimo</span>';
        } else if (it.status === 'warning') {
            badgeHtml = '<span class="badge badge-warn">Preparar</span>';
        } else if (it.status === 'critical') {
            badgeHtml = '<span class="badge badge-danger">Crítico</span>';
        } else if (it.status === 'in_preparation') {
            badgeHtml = `<span style="color: #64b5f6; font-size: 12px; font-weight: 700;" title="${it.in_preparation_stock} un. en colecta generada / en preparación en depósito">En preparación</span>`;
        } else if (it.status === 'in_transit') {
            badgeHtml = `<span style="color: #ffb74d; font-size: 12px; font-weight: 700;" title="${it.in_transit_stock} un. despachadas en camino hacia Full">En tránsito</span>`;
        } else if (it.status === 'in_reception') {
            badgeHtml = `<span style="color: #81c784; font-size: 12px; font-weight: 700;" title="${it.in_process_stock} un. en recepción en MeLi">En recepción</span>`;
        } else {
            badgeHtml = '<span class="badge badge-danger">Sin stock</span>';
        }

        const prep = it.lead_time_days || 5;
        const transit = it.transit_delay_days || 2;
        const buffer = it.buffer_days || 2;
        const totalAdvance = prep + transit + buffer;

        const diasRestantesText = it.days_left >= 900 ? 'Sin ventas' : `${it.days_left} d`;

        // FECHA DE QUIEBRE ESTIMADA (Sobria y legible)
        let quiebraElHtml = '—';
        if (it.status === 'in_preparation') {
            quiebraElHtml = `<span style="color: #64b5f6; font-weight: 600;" title="Colecta generada en depósito">+${it.in_preparation_stock} en preparación</span>`;
        } else if (it.status === 'in_transit') {
            quiebraElHtml = `<span style="color: #ffb74d; font-weight: 600;" title="Envío despachado en camino">+${it.in_transit_stock} en camino</span>`;
        } else if (it.status === 'in_reception') {
            quiebraElHtml = `<span style="color: #81c784; font-weight: 600;" title="Mercadería en depósito MeLi siendo procesada">+${it.in_process_stock} en MeLi</span>`;
        } else if (it.current_stock <= 0) {
            quiebraElHtml = '<span style="color: var(--danger); font-weight: 600;">Agotado</span>';
        } else if (it.days_left >= 900 || !it.stockout_date) {
            quiebraElHtml = '<span style="color: var(--text2);">Sin ventas</span>';
        } else {
            const quiebreFecha = formatearFecha(it.stockout_date);
            const isDanger = it.days_left <= (prep + transit);
            const color = isDanger ? 'var(--danger)' : 'var(--text)';
            quiebraElHtml = `<span style="color: ${color}; font-weight: ${isDanger ? '700' : '500'};">${quiebreFecha}</span>`;
        }

        // CUÁNDO PEDIR COLECTA EN MELI (Limpio y directo, con botón de acción)
        let fechaColectaHtml = '—';
        if (it.status === 'in_preparation') {
            fechaColectaHtml = `<span style="color: #64b5f6; font-weight: 600;" title="Colecta generada, pendiente de retiro">+${it.in_preparation_stock} un. en preparación</span>`;
        } else if (it.status === 'in_transit') {
            fechaColectaHtml = `<span style="color: #ffb74d; font-weight: 600;" title="Despacho en viaje hacia Full">+${it.in_transit_stock} un. en camino</span>`;
        } else if (it.status === 'in_reception') {
            fechaColectaHtml = `<span style="color: #81c784; font-weight: 600;" title="Pendiente de escaneo en MeLi">+${it.in_process_stock} un. en ingreso</span>`;
        } else if (it.reorder_deadline_date || it.current_stock <= 0 || it.status === 'critical' || it.status === 'out_of_stock') {
            const daysToDeadline = it.days_to_deadline !== undefined ? it.days_to_deadline : (it.days_left - totalAdvance);
            const roundedDays = Math.max(1, Math.round(daysToDeadline));

            if (it.current_stock <= 0 || it.status === 'out_of_stock') {
                fechaColectaHtml = `<div style="display: flex; align-items: center; justify-content: flex-end; gap: 6px;"><span style="color: var(--danger); font-weight: 700;">Pedir hoy</span> <button class="btn-pedir-colecta" onclick="event.stopPropagation(); abrirModalColectaConItem(${it.id})" title="Abrir colecta con este artículo incluido">+ Colecta</button></div>`;
            } else if (daysToDeadline <= 0 || it.status === 'critical') {
                fechaColectaHtml = `<div style="display: flex; align-items: center; justify-content: flex-end; gap: 6px;"><span style="color: var(--accent); font-weight: 700;">Pedir hoy</span> <button class="btn-pedir-colecta" onclick="event.stopPropagation(); abrirModalColectaConItem(${it.id})" title="Abrir colecta con este artículo incluido">+ Colecta</button></div>`;
            } else if (daysToDeadline <= 3 || it.status === 'warning') {
                fechaColectaHtml = `<div style="display: flex; align-items: center; justify-content: flex-end; gap: 6px;"><span style="color: var(--text); font-weight: 600;">El ${formatearFecha(it.reorder_deadline_date)} <span style="color: var(--text2); font-weight: 400;">(${roundedDays}d)</span></span> <button class="btn-pedir-colecta" onclick="event.stopPropagation(); abrirModalColectaConItem(${it.id})" title="Planificar colecta para este artículo">+ Colecta</button></div>`;
            } else {
                fechaColectaHtml = `<span style="color: var(--text2);">El ${formatearFecha(it.reorder_deadline_date)} <span style="font-weight: 400;">(${roundedDays}d)</span></span>`;
            }
        }

        const thumbSrc = it.thumbnail || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="%238a8d9a" stroke-width="1.5"%3E%3Crect x="3" y="3" width="18" height="18" rx="2"/%3E%3C/svg%3E';

        // Metadatos de Publicación (Limpios y despojados)
        let channelsHtml = '';
        if (it.channels && it.channels.length > 0) {
            const chItems = it.channels.map(ch => {
                const typeLabel = ch.is_catalog ? 'Catálogo' : (ch.type_label || (ch.listing_type === 'gold_pro' ? 'Premium' : 'Clásica'));
                return `<a href="${ch.permalink}" target="_blank" class="channel-pill" onclick="event.stopPropagation();">${typeLabel}</a>`;
            });
            channelsHtml = chItems.join(' · ');
        } else if (it.permalink) {
            channelsHtml = `<a href="${it.permalink}" target="_blank" class="channel-pill" onclick="event.stopPropagation();">${it.item_id}</a>`;
        }

        const meliCodeText = it.inventory_id ? `<span>·</span> <span>Cód: ${it.inventory_id}</span>` : '';
        const meliItemLink = (it.item_id && (!it.channels || it.channels.length === 0)) ? '' : (it.item_id ? `<span>·</span> <a href="${it.permalink || `https://articulo.mercadolibre.com.ar/${it.item_id}`}" target="_blank" class="channel-pill" onclick="event.stopPropagation();">${it.item_id}</a>` : '');

        let incomingSummary = '';
        const incUnits = (it.in_process_stock || 0) + (it.in_transit_stock || 0) + (it.in_preparation_stock || 0);
        if (incUnits > 0) {
            incomingSummary = ` <span style="color: var(--text2); font-size: 11px;">(+${incUnits})</span>`;
        }

        tr.innerHTML = `
            <td>
                <div class="product-cell">
                    <img src="${thumbSrc}" class="product-thumb" alt="Foto">
                    <div>
                        <div class="product-title" title="${it.title}">
                            <span>${it.title}</span>${it.variation_name ? ` · <span style="color: var(--text2); font-weight: 400;">${it.variation_name}</span>` : ''}
                        </div>
                        <div class="product-meta">
                            <span>SKU: <strong>${it.sku || 'Sin SKU'}</strong></span>
                            ${meliCodeText}
                            ${meliItemLink}
                            ${channelsHtml ? `<span>·</span> ${channelsHtml}` : ''}
                        </div>
                    </div>
                </div>
            </td>
            <td class="num-cell">
                <strong>${it.current_stock}</strong> un.${incomingSummary}
            </td>
            <td class="num-cell">${it.vpd} un./d</td>
            <td class="num-cell" style="font-weight: 600; color: ${it.days_left <= (prep + transit) ? 'var(--danger)' : 'var(--text)'};">
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
    const headerSyncBtn = document.getElementById('headerSyncBtn');
    const btn = document.getElementById('btnCheckStockNow');
    const syncIcon = document.getElementById('syncIcon');
    const syncText = document.getElementById('syncBtnText');

    if (btn) btn.disabled = true;
    if (syncText) syncText.textContent = 'Consultando MercadoLibre...';
    if (headerSyncBtn) {
        headerSyncBtn.textContent = 'Sincronizando...';
        headerSyncBtn.style.pointerEvents = 'none';
    }
    if (syncIcon) {
        syncIcon.style.display = 'inline-block';
        syncIcon.style.animation = 'spin 0.8s linear infinite';
    }

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

    if (syncIcon) syncIcon.style.animation = 'none';
    if (syncText) syncText.textContent = 'Stock Actualizado';
    if (headerSyncBtn) headerSyncBtn.textContent = 'Actualizado';
    const lastSync = document.getElementById('lastSyncText');
    if (lastSync) lastSync.textContent = 'Recién';

    setTimeout(() => {
        if (syncText) syncText.textContent = 'Chequear Stock Actual';
        if (headerSyncBtn) {
            headerSyncBtn.textContent = 'Sincronizar';
            headerSyncBtn.style.pointerEvents = 'auto';
        }
        if (btn) btn.disabled = false;
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
    const cardMap = {
        'all': 'statCardTotal',
        'ok': 'statCardOk',
        'warning': 'statCardWarning',
        'critical': 'statCardCritical'
    };
    actualizarCardsActivas(cardMap[val] || null);
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

function calcularSugeridoColectaItem(it, daysFactor) {
    const mult = (activeColectaMultiplier && activeColectaMultiplier > 1.0) ? activeColectaMultiplier : 1.0;
    const effectiveVpd = (it.vpd || 0) * mult;
    let suggested = Math.max(0, Math.ceil((daysFactor * effectiveVpd) - (it.current_stock || 0)));
    if ((it.status === 'critical' || it.status === 'out_of_stock' || (it.current_stock || 0) <= 0) && suggested <= 0) {
        suggested = Math.max(1, Math.round(effectiveVpd * daysFactor) || 5);
    }
    return suggested;
}

function actualizarBannerModoEventoColecta() {
    const banner = document.getElementById('colectaEventoBufferBanner');
    const textEl = document.getElementById('colectaEventoNombreText');
    if (!banner) return;
    if (activeColectaMultiplier && activeColectaMultiplier > 1.0) {
        banner.style.display = 'flex';
        const pct = Math.round((activeColectaMultiplier - 1) * 100);
        if (textEl) textEl.textContent = `${activeColectaEventName || 'Mega-Evento'} (+${pct}%)`;
    } else {
        banner.style.display = 'none';
    }
}

function quitarModoEventoColecta() {
    activeColectaMultiplier = 1.0;
    activeColectaEventName = '';
    actualizarBannerModoEventoColecta();
    recalcularColecta();
    showToast("Buffer de evento desactivado. Se restauró demanda habitual.", "info");
}

async function abrirModalColecta(targetItemId = null, options = {}) {
    cerrarModalHistorialEnvios();
    const modalEdit = document.getElementById('modalEditarEnvio');
    if (modalEdit) modalEdit.style.display = 'none';
    const modal = document.getElementById('colectaModal');
    if (!modal) return;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    const destText = document.getElementById('colectaDestinoText');
    if (destText) destText.textContent = wh.name;

    // Configuración de modo evento comercial
    if (options && options.multiplier) {
        activeColectaMultiplier = options.multiplier;
        activeColectaEventName = options.eventName || '';
    } else if (!options || !options.keepMultiplier) {
        activeColectaMultiplier = 1.0;
        activeColectaEventName = '';
    }
    actualizarBannerModoEventoColecta();

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
        let suggested = calcularSugeridoColectaItem(it, daysFactor);
        const isTarget = targetItemId && (it.id === targetItemId || it.id === Number(targetItemId));
        const isUrgent = (it.status === 'warning' || it.status === 'critical' || it.status === 'out_of_stock' || it.current_stock <= 0);

        // Si el artículo requiere reposición urgente o es el target, asegurar unidades positivas
        if (isUrgent || isTarget) {
            if (suggested <= 0) {
                const effectiveVpd = (it.vpd || 0) * (activeColectaMultiplier || 1.0);
                suggested = Math.max(1, Math.round(effectiveVpd * daysFactor) || 5);
            }
            colectaSelectedItems.set(it.id, suggested);
            const defaultUnitsBox = (it.units_per_box && it.units_per_box > 0) ? it.units_per_box : 0;
            colectaBoxUnits.set(it.id, defaultUnitsBox);
        } else if (suggested > 0) {
            colectaSelectedItems.set(it.id, suggested);
            const defaultUnitsBox = (it.units_per_box && it.units_per_box > 0) ? it.units_per_box : 0;
            colectaBoxUnits.set(it.id, defaultUnitsBox);
        }
    });

    // Asegurar que si vino un targetItemId específico esté seleccionado
    if (targetItemId) {
        const targetObj = itemsData.find(x => x.id === targetItemId || x.id === Number(targetItemId));
        if (targetObj && !colectaSelectedItems.has(targetObj.id)) {
            let suggested = calcularSugeridoColectaItem(targetObj, daysFactor);
            if (suggested <= 0) {
                const effectiveVpd = (targetObj.vpd || 0) * (activeColectaMultiplier || 1.0);
                suggested = Math.max(1, Math.round(effectiveVpd * daysFactor) || 5);
            }
            colectaSelectedItems.set(targetObj.id, suggested);
            colectaBoxUnits.set(targetObj.id, targetObj.units_per_box || 0);
        }
    }

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
    renderizarFilasColecta(targetItemId);
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
            let suggested = calcularSugeridoColectaItem(it, daysFactor);
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
            let suggested = calcularSugeridoColectaItem(it, daysFactor);
            const mult = (activeColectaMultiplier && activeColectaMultiplier > 1.0) ? activeColectaMultiplier : 1.0;
            const effectiveVpd = (it.vpd || 0) * mult;
            colectaSelectedItems.set(it.id, suggested > 0 ? suggested : Math.max(1, Math.round(effectiveVpd * 7) || 1));
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
        let suggested = calcularSugeridoColectaItem(it, daysFactor);
        const mult = (activeColectaMultiplier && activeColectaMultiplier > 1.0) ? activeColectaMultiplier : 1.0;
        const effectiveVpd = (it.vpd || 0) * mult;
        colectaSelectedItems.set(id, suggested > 0 ? suggested : Math.max(1, Math.round(effectiveVpd * 7) || 1));
        if (!colectaBoxUnits.has(id)) colectaBoxUnits.set(id, it.units_per_box || 0);
    } else {
        colectaSelectedItems.delete(id);
    }
    actualizarTotalColecta();
    renderizarFilasColecta();
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

function renderizarFilasColecta(highlightItemId = null) {
    const tbody = document.getElementById('colectaTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const targetDays = getDiasCoberturaColecta();
    const leadTime = parseInt(document.getElementById('cfgLeadTime')?.value, 10) || 5;
    const wh = WAREHOUSES[currentWarehouse] || WAREHOUSES.meli_full;
    const transit = wh.defaultTransit || 3;
    const daysFactor = targetDays + leadTime + transit;

    // Ordenar artículos por máxima urgencia: Quiebres y Críticos SIEMPRE ARRIBA
    const itemsOrdenados = [...itemsData].sort((a, b) => {
        // 1. Si uno es el highlightItemId, ponerlo primero
        const isTargetA = highlightItemId && (a.id === highlightItemId || a.id === Number(highlightItemId));
        const isTargetB = highlightItemId && (b.id === highlightItemId || b.id === Number(highlightItemId));
        if (isTargetA && !isTargetB) return -1;
        if (!isTargetA && isTargetB) return 1;

        // 2. Score de urgencia
        const scoreUrgencia = (it) => {
            if (it.status === 'out_of_stock' || it.current_stock <= 0) return 1;
            if (it.status === 'critical') return 2;
            if (it.status === 'warning') return 3;
            if (colectaSelectedItems.has(it.id)) return 4;
            return 5;
        };

        const scoreA = scoreUrgencia(a);
        const scoreB = scoreUrgencia(b);
        if (scoreA !== scoreB) return scoreA - scoreB;

        // 3. Menos días de stock primero
        const daysA = a.days_left !== undefined ? a.days_left : 999;
        const daysB = b.days_left !== undefined ? b.days_left : 999;
        return daysA - daysB;
    });

    itemsOrdenados.forEach(it => {
        const isSelected = colectaSelectedItems.has(it.id);
        let suggested = calcularSugeridoColectaItem(it, daysFactor);
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

        // Badge de urgencia bien visible en la fila de Colecta
        let urgenciaBadge = '';
        if (it.status === 'out_of_stock' || it.current_stock <= 0) {
            urgenciaBadge = '<span class="badge badge-danger" style="margin-left: 6px; font-size: 10px; padding: 1px 6px;">Sin stock</span>';
        } else if (it.status === 'critical') {
            urgenciaBadge = '<span class="badge badge-danger" style="margin-left: 6px; font-size: 10px; padding: 1px 6px;">Quiebre inminente</span>';
        } else if (it.status === 'warning') {
            urgenciaBadge = '<span class="badge badge-warn" style="margin-left: 6px; font-size: 10px; padding: 1px 6px;">Preparar</span>';
        }

        const isHighlighted = highlightItemId && (it.id === highlightItemId || it.id === Number(highlightItemId));
        const tr = document.createElement('tr');
        tr.id = `colecta_row_${it.id}`;
        tr.style.opacity = isSelected ? '1' : '0.65';
        if (isHighlighted) {
            tr.classList.add('row-highlight');
        }

        tr.innerHTML = `
            <td style="text-align: center; vertical-align: middle;">
                <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleItemColecta(${it.id}, this.checked)">
            </td>
            <td style="vertical-align: middle;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    ${thumbImg}
                    <div style="min-width: 0;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <strong style="color: var(--text); font-size: 13px; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 380px;">${it.title}</strong>
                            ${urgenciaBadge}
                        </div>
                        <div style="font-size: 11px; color: var(--text2); display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                            <span>Cód ML: <strong style="color: var(--accent);">${it.inventory_id || it.item_id}</strong></span>
                            ${it.item_id ? `<span>·</span><span style="color: var(--text2);">${it.item_id}</span>` : ''}
                            ${channelBadges ? `<span>·</span> ${channelBadges}` : ''}
                            ${it.variation_name ? `<span>· <em>${it.variation_name}</em></span>` : ''}
                        </div>
                    </div>
                </div>
            </td>
            <td style="text-align: right; vertical-align: middle;">
                <strong style="${it.current_stock <= 0 ? 'color: var(--danger);' : ''}">${it.current_stock}</strong> un.
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
                       style="width: 75px; text-align: center; font-weight: 700; ${isSelected && unitsToSend > 0 ? 'border-color: var(--accent);' : ''}">
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

    if (highlightItemId) {
        setTimeout(() => {
            const rowEl = document.getElementById(`colecta_row_${highlightItemId}`);
            if (rowEl) {
                rowEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }, 70);
    }
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
        showToast(`Colecta ${shipment.shipment_code} creada con éxito: ${shipment.total_units} unidades en ${shipment.total_boxes} bultos hacia Villa Celina.`, 'success');

        // Abrir Hoja de Despacho en pestaña nueva para imprimir (autenticado)
        abrirRemitoOficial(shipment.id);

        // Actualizar tabla principal de stock para reflejar mercadería en tránsito
        cargarDatos();

        // Cerrar planificador y abrir Historial de Envíos
        cerrarModalColecta();
        abrirHistorialColectas();
    } catch (err) {
        showToast("Error de conexión al crear el envío: " + err.message, "error");
    }
}

function abrirRemitoOficial(shipmentId) {
    const token = getToken();
    const url = `${API_BASE}/full/inbound/shipments/${shipmentId}/remito-html?token=${encodeURIComponent(token || '')}`;
    window.open(url, '_blank');
}
const abrirHojaDespacho = abrirRemitoOficial;
window.abrirHojaDespacho = abrirRemitoOficial;
window.abrirRemitoOficial = abrirRemitoOficial;

// ── Cargar una colecta que ya está en Mercado Libre (arrastrando el PDF) ──────────
let importPdfArchivo = null;

function importPdfMostrar(paso) {
    ['importPdfPaso1', 'importPdfPaso2'].forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.style.display = (id === 'importPdfPaso' + paso) ? 'block' : 'none';
    });
    const bc = document.getElementById('btnConfirmarImportPdf');
    if (bc) bc.style.display = paso === 2 ? '' : 'none';
}

function abrirImportarColectaPdf() {
    const modal = document.getElementById('modalImportarPdf');
    if (!modal) return;
    importPdfArchivo = null;
    importPdfMostrar(1);
    const err = document.getElementById('importPdfError');
    if (err) err.textContent = '';
    modal.style.display = 'flex';
}

function cerrarImportarColectaPdf() {
    const modal = document.getElementById('modalImportarPdf');
    if (modal) modal.style.display = 'none';
    importPdfArchivo = null;
}

function htmlVistaPreviaPdf(envio) {
    const filas = (envio.productos || []).map(function (p) {
        return '<tr><td>' + escapeHtml(p.titulo) + '</td><td class="pc-sku-inline">' + escapeHtml(p.sku) +
            '</td><td style="text-align:right;font-weight:700;">' + escapeHtml(p.unidades) + ' u.</td></tr>';
    }).join('');
    const faltan = (envio.sin_match || []).map(function (p) {
        return escapeHtml(p.titulo) + ' (' + escapeHtml(p.unidades) + ' u.)';
    });
    const aviso = faltan.length
        ? '<div class="pc-vacio" style="margin-top:10px;">No encontré en EnvioBot ' + faltan.length +
          (faltan.length === 1 ? ' producto' : ' productos') + ', así que no se cargan: ' + faltan.join(', ') + '.</div>'
        : '';
    const existe = envio.ya_existe
        ? '<div class="pc-vacio" style="margin-top:10px;">Esta colecta ya está cargada en EnvioBot.</div>'
        : '';
    return '<div class="pc-hero-titulo">Envío #' + escapeHtml(envio.numero_ml) + '</div>' +
        '<div class="pc-hero-sub">' + (envio.productos || []).length + ' productos, ' + escapeHtml(envio.total_unidades) + ' unidades</div>' +
        '<div style="max-height:240px;overflow:auto;margin-top:10px;"><table class="pc-table"><tbody>' + filas + '</tbody></table></div>' +
        aviso + existe;
}

async function enviarPdfColecta(archivo, fechaRetiro) {
    const fd = new FormData();
    fd.append('file', archivo);
    if (fechaRetiro) fd.append('pickup_date', fechaRetiro);
    const res = await fetch(`${API_BASE}/full/inbound/import-pdf`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${getToken()}` },
        body: fd
    });
    let data = {};
    try { data = await res.json(); } catch (e) { data = { error: 'El servidor no respondió bien.' }; }
    return { ok: res.ok, data: data };
}

async function procesarPdfColecta(archivo) {
    abrirImportarColectaPdf();
    const err = document.getElementById('importPdfError');
    if (!archivo || !/\.pdf$/i.test(archivo.name || '')) {
        if (err) err.textContent = 'Ese archivo no es un PDF. Arrastrá el PDF de instrucciones de preparación de Mercado Libre.';
        return;
    }
    try {
        const r = await enviarPdfColecta(archivo, null);
        if (!r.ok) {
            if (err) err.textContent = r.data.error || 'No pude leer el PDF.';
            return;
        }
        importPdfArchivo = archivo;
        document.getElementById('importPdfVista').innerHTML = htmlVistaPreviaPdf(r.data.envio);
        const btn = document.getElementById('btnConfirmarImportPdf');
        if (btn) btn.disabled = !!r.data.envio.ya_existe || !(r.data.envio.productos || []).length;
        const e2 = document.getElementById('importPdfErrorPaso2');
        if (e2) e2.textContent = '';
        importPdfMostrar(2);
    } catch (e) {
        if (err) err.textContent = 'Error de conexión: ' + e.message;
    }
}

async function confirmarImportPdf() {
    const fecha = (document.getElementById('importPdfFecha') || {}).value;
    const err = document.getElementById('importPdfErrorPaso2');
    if (err) err.textContent = '';
    if (!fecha) {
        if (err) err.textContent = 'Poné la fecha de retiro (en Mercado Libre figura como "Turno reservado").';
        return;
    }
    try {
        const r = await enviarPdfColecta(importPdfArchivo, fecha);
        if (!r.ok) {
            if (err) err.textContent = r.data.error || 'No pude cargar la colecta.';
            return;
        }
        showToast('Colecta ' + r.data.shipment.shipment_code + ' cargada: ' + r.data.shipment.total_units + ' unidades.', 'success');
        cerrarImportarColectaPdf();
        cargarDatos();
    } catch (e) {
        if (err) err.textContent = 'Error de conexión: ' + e.message;
    }
}

// Arrastrar un PDF a cualquier parte de la pantalla abre la carga.
['dragover', 'drop'].forEach(function (nombre) {
    window.addEventListener(nombre, function (ev) {
        const tipos = ev.dataTransfer && ev.dataTransfer.types;
        if (!tipos || Array.prototype.indexOf.call(tipos, 'Files') < 0) return;
        ev.preventDefault();
        if (nombre === 'drop') {
            const f = ev.dataTransfer.files && ev.dataTransfer.files[0];
            if (f) procesarPdfColecta(f);
        }
    });
});

window.abrirImportarColectaPdf = abrirImportarColectaPdf;
window.cerrarImportarColectaPdf = cerrarImportarColectaPdf;
window.procesarPdfColecta = procesarPdfColecta;
window.confirmarImportPdf = confirmarImportPdf;

// ── Modales Independientes: Armar Colecta vs Historial de Envíos ──

function abrirHistorialColectas() {
    cerrarModalColecta();
    const modalEdit = document.getElementById('modalEditarEnvio');
    if (modalEdit) modalEdit.style.display = 'none';
    const modal = document.getElementById('modalHistorialEnvios');
    if (modal) modal.style.display = 'flex';
    cargarHistorialColectas();
}
window.abrirHistorialColectas = abrirHistorialColectas;

function cerrarModalHistorialEnvios() {
    const modal = document.getElementById('modalHistorialEnvios');
    if (modal) modal.style.display = 'none';
}
window.cerrarModalHistorialEnvios = cerrarModalHistorialEnvios;

function irACrearColectaDesdeHistorial() {
    cerrarModalHistorialEnvios();
    abrirModalColecta();
}
window.irACrearColectaDesdeHistorial = irACrearColectaDesdeHistorial;

function irAHistorialDesdeColecta() {
    cerrarModalColecta();
    abrirHistorialColectas();
}
window.irAHistorialDesdeColecta = irAHistorialDesdeColecta;

async function cargarHistorialColectas(soloBadge = false) {
    const token = getToken();
    const container = document.getElementById('historialEnviosContainer') || document.getElementById('colectaHistorialContainer');
    const badge = document.getElementById('colectaHistorialBadge');
    const topBadge = document.getElementById('topbarHistorialBadge');
    const totalBadge = document.getElementById('historialTotalBadge');
    if (!token) return;

    try {
        const res = await fetch(`${API_BASE}/full/inbound/shipments`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.ok && Array.isArray(data.shipments)) {
            inboundShipmentsList = data.shipments;
            const count = inboundShipmentsList.length;
            if (badge) badge.textContent = count;
            if (topBadge) topBadge.textContent = count;
            if (totalBadge) totalBadge.textContent = `${count} ${count === 1 ? 'envío' : 'envíos'}`;

            if (soloBadge) return;

            if (!container) return;
            if (count === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 48px 20px; color: var(--text2);">
                        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.45; margin-bottom: 10px;">
                            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                            <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                            <line x1="12" y1="22.08" x2="12" y2="12"></line>
                        </svg><br>
                        <strong style="font-size: 15px; color: var(--text);">No hay envíos registrados todavía.</strong><br>
                        <span style="font-size: 13px; margin-top: 4px; display: inline-block;">Podés planificar tu primer despacho con el botón <strong>+ Armar Nuevo Envío</strong>.</span>
                    </div>
                `;
                return;
            }

            container.innerHTML = inboundShipmentsList.map(sh => {
                const statusMap = {
                    'scheduled': { text: 'En Preparación', color: '#64b5f6', bg: 'rgba(33, 150, 243, 0.15)' },
                    'in_transit': { text: 'En Tránsito', color: '#ffb74d', bg: 'rgba(255, 152, 0, 0.15)' },
                    'delivered': { text: 'Ingresado en Full', color: '#81c784', bg: 'rgba(76, 175, 80, 0.15)' },
                    'cancelled': { text: 'Cancelado', color: '#9e9e9e', bg: 'rgba(158, 158, 158, 0.15)' }
                };
                const st = statusMap[sh.status] || { text: sh.status, color: '#fff', bg: '#333' };
                const esEditable = (sh.status === 'scheduled' || sh.status === 'draft');

                const btnEditarHtml = esEditable
                    ? `<button type="button" class="btn btn-secondary btn-sm" onclick="abrirModalEditarEnvio(${sh.id})" title="Editar cantidades, artículos o fecha de este envío">Editar Envío</button>`
                    : `<button type="button" class="btn btn-secondary btn-sm" disabled style="opacity: 0.45; cursor: not-allowed;" title="Envío no editable: ya fue despachado o cancelado">Despachado (No editable)</button>`;

                return `
                    <div style="background: var(--surf2); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; transition: border-color 0.15s ease;">
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
                            <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
                                <button type="button" class="btn btn-sm" style="background: var(--accent); color: #111; font-weight: 700;" onclick="abrirRemitoOficial(${sh.id})">
                                    Ver Hoja de Despacho
                                </button>
                                ${btnEditarHtml}
                                <button type="button" class="btn btn-secondary btn-sm" id="btnToggleDetalle_${sh.id}" onclick="toggleDetalleArticulosHistorial(${sh.id})" title="Ver lista de artículos de este envío">
                                    Ver Artículos (${sh.total_items})
                                </button>
                                <select onchange="cambiarEstadoEnvioInbound(${sh.id}, this.value)" class="filter-select" style="padding: 4px 8px; font-size: 11px;">
                                    <option value="scheduled" ${sh.status === 'scheduled' ? 'selected' : ''}>En Preparación</option>
                                    <option value="in_transit" ${sh.status === 'in_transit' ? 'selected' : ''}>En Tránsito</option>
                                    <option value="delivered" ${sh.status === 'delivered' ? 'selected' : ''}>Ingresado en Full</option>
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

                        <!-- Detalle desplegable de artículos del envío -->
                        <div id="detalleArticulos_${sh.id}" style="display: none; margin-top: 10px; border-top: 1px solid var(--border); padding-top: 10px;">
                            <div style="text-align: center; color: var(--text2); font-size: 12px; padding: 8px;">Cargando detalle de artículos...</div>
                        </div>
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        if (container) container.innerHTML = `<div style="text-align: center; color: #ef4444; padding: 20px;">Error cargando historial: ${e.message}</div>`;
    }
}
window.cargarHistorialColectas = cargarHistorialColectas;

async function toggleDetalleArticulosHistorial(shipmentId) {
    const el = document.getElementById(`detalleArticulos_${shipmentId}`);
    const btn = document.getElementById(`btnToggleDetalle_${shipmentId}`);
    if (!el) return;

    if (el.style.display === 'block') {
        el.style.display = 'none';
        if (btn) btn.textContent = btn.textContent.replace('Ocultar', 'Ver');
        return;
    }

    el.style.display = 'block';
    if (btn) btn.textContent = btn.textContent.replace('Ver', 'Ocultar');

    const token = getToken();
    if (!token) return;

    try {
        const res = await fetch(`${API_BASE}/full/inbound/shipments/${shipmentId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.ok && Array.isArray(data.items)) {
            if (data.items.length === 0) {
                el.innerHTML = `<div style="color: var(--text2); font-size: 12px; padding: 6px;">No hay artículos registrados en este envío.</div>`;
                return;
            }
            el.innerHTML = `
                <table style="width: 100%; font-size: 11.5px; border-collapse: collapse;">
                    <thead>
                        <tr style="color: var(--text2); text-align: left; border-bottom: 1px solid var(--border);">
                            <th style="padding: 4px 8px;">Artículo</th>
                            <th style="padding: 4px 8px;">SKU</th>
                            <th style="padding: 4px 8px; text-align: center;">Stock Full</th>
                            <th style="padding: 4px 8px; text-align: center;">VPD</th>
                            <th style="padding: 4px 8px; text-align: center;">Unidades</th>
                            <th style="padding: 4px 8px; text-align: center;">Unid./Caja</th>
                            <th style="padding: 4px 8px; text-align: center;">Bultos</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.items.map(it => `
                            <tr style="border-bottom: 1px dashed rgba(255,255,255,0.05);">
                                <td style="padding: 6px 8px; color: var(--text);">${it.title}</td>
                                <td style="padding: 6px 8px; font-family: monospace; color: var(--accent);">${it.sku || '-'}</td>
                                <td style="padding: 6px 8px; text-align: center;">${it.current_full_stock}</td>
                                <td style="padding: 6px 8px; text-align: center;">${it.vpd}</td>
                                <td style="padding: 6px 8px; text-align: center; font-weight: 700; color: var(--accent);">${it.units_to_send}</td>
                                <td style="padding: 6px 8px; text-align: center;">${it.units_per_box || '-'}</td>
                                <td style="padding: 6px 8px; text-align: center; font-weight: 700; color: var(--good);">${it.box_count}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        } else {
            el.innerHTML = `<div style="color: #ef4444; font-size: 12px; padding: 6px;">Error cargando detalle: ${data.error || 'Respuesta inválida'}</div>`;
        }
    } catch (e) {
        el.innerHTML = `<div style="color: #ef4444; font-size: 12px; padding: 6px;">Error de conexión: ${e.message}</div>`;
    }
}
window.toggleDetalleArticulosHistorial = toggleDetalleArticulosHistorial;

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
            // Actualizar stock principal para recalcular stock en tránsito
            if (typeof cargarDatos === 'function') cargarDatos();
        } else {
            alert(data.error || "No se pudo actualizar el estado.");
        }
    } catch (err) {
        alert("Error de conexión: " + err.message);
    }
}
window.cambiarEstadoEnvioInbound = cambiarEstadoEnvioInbound;

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
            if (typeof cargarDatos === 'function') cargarDatos();
        } else {
            alert(data.error || "No se pudo eliminar el envío.");
        }
    } catch (err) {
        alert("Error de conexión: " + err.message);
    }
}
window.eliminarEnvioInbound = eliminarEnvioInbound;

// ── Lógica del Editor de Envíos Inbound (Edición Total) ──

let shipmentEnEdicionId = null;
let itemsEnEdicion = [];

async function abrirModalEditarEnvio(shipmentId) {
    const token = getToken();
    if (!token) return;

    cerrarModalColecta();
    cerrarModalHistorialEnvios();

    try {
        const res = await fetch(`${API_BASE}/full/inbound/shipments/${shipmentId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        if (!data.ok || !data.shipment) {
            alert(data.error || "No se pudo cargar el envío para editar.");
            abrirHistorialColectas();
            return;
        }

        const sh = data.shipment;
        if (['in_transit', 'delivered', 'cancelled'].includes(sh.status)) {
            alert(`No se puede modificar un envío en estado '${sh.status}'. Solo se pueden editar envíos en preparación o borradores.`);
            abrirHistorialColectas();
            return;
        }

        shipmentEnEdicionId = shipmentId;
        itemsEnEdicion = (data.items || []).map(it => ({
            id: it.id,
            item_id: String(it.item_id || ''),
            inventory_id: it.inventory_id || null,
            variation_id: it.variation_id || null,
            variation_name: it.variation_name || null,
            sku: it.sku || '',
            title: it.title || 'Producto sin título',
            current_full_stock: parseInt(it.current_full_stock, 10) || 0,
            vpd: parseFloat(it.vpd) || 0,
            suggested_units: parseInt(it.suggested_units, 10) || 0,
            units_to_send: parseInt(it.units_to_send, 10) || 1,
            units_per_box: parseInt(it.units_per_box, 10) || 0,
            box_count: parseInt(it.box_count, 10) || 1
        }));

        // Llenar cabecera del modal
        const headerCode = document.getElementById('editarEnvioCodigoHeader');
        if (headerCode) headerCode.textContent = sh.shipment_code;

        const badge = document.getElementById('editarEnvioStatusBadge');
        if (badge) {
            badge.textContent = 'En Preparación / Editable';
            badge.style.background = 'rgba(33, 150, 243, 0.15)';
            badge.style.color = '#64b5f6';
        }

        // Llenar campos de formulario
        const fechaInput = document.getElementById('editarEnvioFechaRetiro');
        if (fechaInput) {
            fechaInput.value = sh.pickup_date ? String(sh.pickup_date).split('T')[0] : '';
        }

        const packSelect = document.getElementById('editarEnvioPackaging');
        if (packSelect) {
            packSelect.value = sh.packaging_type || 'cajas_master';
        }

        const notasInput = document.getElementById('editarEnvioNotas');
        if (notasInput) {
            notasInput.value = sh.carrier_notes || '';
        }

        // Limpiar buscador de artículos
        const searchInput = document.getElementById('editarEnvioBuscarInput');
        if (searchInput) searchInput.value = '';
        const resultadosContainer = document.getElementById('editarEnvioResultadosBusqueda');
        if (resultadosContainer) {
            resultadosContainer.innerHTML = '';
            resultadosContainer.style.display = 'none';
        }

        renderizarItemsEdicion();
        verificarAlertasStockEdicion();

        const modal = document.getElementById('modalEditarEnvio');
        if (modal) modal.style.display = 'flex';
    } catch (e) {
        alert("Error de conexión al cargar envío: " + e.message);
        abrirHistorialColectas();
    }
}
window.abrirModalEditarEnvio = abrirModalEditarEnvio;

function cerrarModalEditarEnvio(volverAlHistorial = true) {
    const modal = document.getElementById('modalEditarEnvio');
    if (modal) modal.style.display = 'none';
    shipmentEnEdicionId = null;
    itemsEnEdicion = [];
    if (volverAlHistorial) {
        abrirHistorialColectas();
    }
}
window.cerrarModalEditarEnvio = cerrarModalEditarEnvio;

function verificarAlertasStockEdicion() {
    const alertBox = document.getElementById('editarEnvioAlertasStock');
    const listContainer = document.getElementById('editarEnvioListaSugeridosCriticos');
    if (!alertBox || !listContainer) return;

    if (!Array.isArray(itemsData) || itemsData.length === 0) {
        alertBox.style.display = 'none';
        return;
    }

    const idsEnEdicion = new Set(itemsEnEdicion.map(it => String(it.item_id || '')));
    const skusEnEdicion = new Set(itemsEnEdicion.map(it => (it.sku || '').toLowerCase()).filter(Boolean));

    // Buscar productos críticos o con quiebre que NO están en la colecta actual
    const criticosFuera = itemsData.filter(it => {
        const itemIdStr = String(it.item_id || it.id);
        const itemSku = (it.sku || '').toLowerCase();
        if (idsEnEdicion.has(itemIdStr)) return false;
        if (itemSku && skusEnEdicion.has(itemSku)) return false;

        const isRisk = (it.status === 'critical' || it.status === 'warning' || it.status === 'out_of_stock' || (it.days_left !== null && it.days_left <= 10) || it.current_stock <= 0);
        return isRisk;
    });

    if (criticosFuera.length === 0) {
        alertBox.style.display = 'none';
        listContainer.innerHTML = '';
        return;
    }

    alertBox.style.display = 'block';
    listContainer.innerHTML = criticosFuera.slice(0, 5).map(it => {
        const vpd = parseFloat(it.vpd) || 0;
        const stock = parseInt(it.current_stock, 10) || 0;
        let sug = Math.max(1, Math.ceil((25 * vpd) - stock));
        if (sug <= 0) sug = Math.max(1, Math.round(vpd * 25) || 5);
        const skuStr = it.sku ? `SKU: ${it.sku}` : 'Sin SKU';

        return `
            <div style="display: flex; justify-content: space-between; align-items: center; background: var(--surf2); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; gap: 8px;">
                <div style="flex: 1; min-width: 0;">
                    <div style="font-weight: 700; color: var(--text); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${it.title}</div>
                    <div style="font-size: 11px; color: var(--text2); display: flex; gap: 8px; margin-top: 1px;">
                        <span style="color: var(--accent); font-family: monospace;">${skuStr}</span>
                        <span>Stock Full: <strong style="color: ${stock <= 0 ? '#ef4444' : 'var(--text)'};">${stock}</strong></span>
                        <span>Ritmo: <strong>${vpd}/día</strong></span>
                        <span style="color: #64b5f6;">Sugerido: <strong>${sug} un.</strong></span>
                    </div>
                </div>
                <button type="button" class="btn btn-sm" style="background: var(--accent); color: #111; font-weight: 700; font-size: 11px; padding: 4px 9px; white-space: nowrap;" 
                        onclick="agregarItemCriticoAEdicion(${it.id}, ${sug})">
                    + Sumar a esta colecta
                </button>
            </div>
        `;
    }).join('');
}
window.verificarAlertasStockEdicion = verificarAlertasStockEdicion;

function agregarItemCriticoAEdicion(itemId, sugUnits) {
    const it = itemsData.find(x => x.id === itemId);
    if (!it) return;

    const upb = (it.units_per_box && it.units_per_box > 0) ? it.units_per_box : 0;
    const unitsToSend = Math.max(1, sugUnits || upb || 10);
    const boxCount = upb > 0 ? Math.ceil(unitsToSend / upb) : 1;

    itemsEnEdicion.push({
        id: null,
        item_id: String(it.item_id || it.id),
        inventory_id: it.inventory_id || null,
        variation_id: it.variation_id || null,
        variation_name: it.variation_name || null,
        sku: it.sku || '',
        title: it.title || 'Producto sin título',
        current_full_stock: parseInt(it.current_stock, 10) || 0,
        vpd: parseFloat(it.vpd) || 0,
        suggested_units: unitsToSend,
        units_to_send: unitsToSend,
        units_per_box: upb,
        box_count: boxCount
    });

    renderizarItemsEdicion();
    verificarAlertasStockEdicion();
    showToast(`Artículo "${it.sku || it.title.substring(0, 25)}" sumado al envío (${unitsToSend} un.).`, "info");
}
window.agregarItemCriticoAEdicion = agregarItemCriticoAEdicion;

function onAjustarSugeridoEdicion(idx, units) {
    if (!itemsEnEdicion[idx]) return;
    onCambiarUnidadesEdicion(idx, units);
    renderizarItemsEdicion();
}
window.onAjustarSugeridoEdicion = onAjustarSugeridoEdicion;

function renderizarItemsEdicion() {
    const tbody = document.getElementById('editarEnvioTbody');
    if (!tbody) return;

    if (itemsEnEdicion.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" style="text-align: center; padding: 30px; color: var(--text2);">
                    No hay productos en este envío. Podés sumar artículos con el buscador de arriba o desde las sugerencias de quiebre.
                </td>
            </tr>
        `;
        actualizarTotalesEdicion();
        return;
    }

    tbody.innerHTML = itemsEnEdicion.map((it, idx) => {
        const skuHtml = it.sku ? `<span style="font-family: monospace; font-size: 11px; color: var(--accent);">${it.sku}</span>` : `<span style="font-size: 11px; color: var(--text2);">-</span>`;
        const varHtml = it.variation_name ? `<span style="font-size: 11px; color: var(--text2); display: block;">${it.variation_name}</span>` : '';

        let sugHintHtml = '';
        const sugerido = sugeridoEdicion(it);
        if (sugerido) {
            sugHintHtml = `
                <div style="font-size: 10.5px; color: var(--accent); margin-top: 3px; display: flex; align-items: center; justify-content: center; gap: 4px;">
                    <span title="Para cubrir tu stock objetivo con lo que se vende hasta que entre la colecta">Sugerido: <strong>${sugerido}</strong></span>
                    <button type="button" class="btn btn-secondary btn-xs" style="font-size: 9.5px; padding: 1px 4px; border-radius: 3px;" onclick="onAjustarSugeridoEdicion(${idx}, ${sugerido})" title="Ajustar cantidad a unidades sugeridas">
                        Ajustar
                    </button>
                </div>
            `;
        }

        return `
            <tr style="border-bottom: 1px solid var(--border);">
                <td style="padding: 8px 10px;">
                    <div style="font-weight: 600; color: var(--text);">${it.title}</div>
                    <div style="display: flex; gap: 8px; align-items: center; margin-top: 2px;">
                        ${skuHtml}
                        ${varHtml}
                    </div>
                </td>
                <td style="padding: 8px 10px; text-align: center; color: var(--text);">${it.current_full_stock}</td>
                <td style="padding: 8px 10px; text-align: center; color: var(--text2);">${it.vpd}</td>
                <td style="padding: 8px 10px; text-align: center;">
                    <input type="number" min="1" max="99999" value="${it.units_to_send}" 
                           oninput="onCambiarUnidadesEdicion(${idx}, this.value)" 
                           style="width: 80px; text-align: center; padding: 4px 6px; font-size: 13px; font-weight: 700; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; color: var(--text);">
                    ${sugHintHtml}
                </td>
                <td style="padding: 8px 10px; text-align: center;">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="quitarItemDeEdicion(${idx})" title="Quitar del envío" style="padding: 2px 7px;">
                        ✕
                    </button>
                </td>
            </tr>
        `;
    }).join('');

    actualizarTotalesEdicion();
}
window.renderizarItemsEdicion = renderizarItemsEdicion;

function onCambiarUnidadesEdicion(idx, val) {
    if (!itemsEnEdicion[idx]) return;
    const units = Math.max(1, parseInt(val, 10) || 1);
    itemsEnEdicion[idx].units_to_send = units;

    const upb = itemsEnEdicion[idx].units_per_box || 0;
    const boxCount = upb > 0 ? Math.ceil(units / upb) : 1;
    itemsEnEdicion[idx].box_count = boxCount;

    const spanCajas = document.getElementById(`editarItemCajas_${idx}`);
    if (spanCajas) spanCajas.textContent = `${boxCount} cj.`;

    actualizarTotalesEdicion();
}
window.onCambiarUnidadesEdicion = onCambiarUnidadesEdicion;

function onCambiarUnitsPerBoxEdicion(idx, val) {
    if (!itemsEnEdicion[idx]) return;
    const upb = Math.max(0, parseInt(val, 10) || 0);
    itemsEnEdicion[idx].units_per_box = upb;

    const units = itemsEnEdicion[idx].units_to_send || 1;
    const boxCount = upb > 0 ? Math.ceil(units / upb) : 1;
    itemsEnEdicion[idx].box_count = boxCount;

    const spanCajas = document.getElementById(`editarItemCajas_${idx}`);
    if (spanCajas) spanCajas.textContent = `${boxCount} cj.`;

    actualizarTotalesEdicion();
}
window.onCambiarUnitsPerBoxEdicion = onCambiarUnitsPerBoxEdicion;

function quitarItemDeEdicion(idx) {
    if (!itemsEnEdicion[idx]) return;
    const itemQuitado = itemsEnEdicion[idx];
    itemsEnEdicion.splice(idx, 1);
    renderizarItemsEdicion();
    verificarAlertasStockEdicion();
    showToast(`Artículo "${itemQuitado.sku || itemQuitado.title.substring(0, 25)}" quitado del envío.`, "info");
}
window.quitarItemDeEdicion = quitarItemDeEdicion;

function actualizarTotalesEdicion() {
    const totalItems = itemsEnEdicion.length;
    const totalUnits = itemsEnEdicion.reduce((acc, it) => acc + (it.units_to_send || 0), 0);
    const totalBoxes = itemsEnEdicion.reduce((acc, it) => acc + (it.box_count || 0), 0);

    const elItems = document.getElementById('editarEnvioTotalItems');
    const elUnits = document.getElementById('editarEnvioTotalUnits');
    const elBoxes = document.getElementById('editarEnvioTotalBoxes');

    if (elItems) elItems.textContent = totalItems;
    if (elUnits) elUnits.textContent = `${totalUnits} un.`;
    if (elBoxes) elBoxes.textContent = `${totalBoxes} cajas`;
}

function onBuscarArticuloParaAgregar(query) {
    const contenedor = document.getElementById('editarEnvioResultadosBusqueda');
    if (!contenedor) return;

    const q = (query || '').trim().toLowerCase();
    if (q.length < 2) {
        contenedor.innerHTML = '';
        contenedor.style.display = 'none';
        return;
    }

    if (!Array.isArray(itemsData) || itemsData.length === 0) {
        contenedor.innerHTML = `<div style="padding: 10px; color: var(--text2); font-size: 12px;">No hay productos cargados en el catálogo.</div>`;
        contenedor.style.display = 'block';
        return;
    }

    // Filtrar excluyendo los que ya están en el envío
    const idsEnEdicion = new Set(itemsEnEdicion.map(it => String(it.item_id)));
    const skusEnEdicion = new Set(itemsEnEdicion.map(it => (it.sku || '').toLowerCase()).filter(Boolean));

    const matches = itemsData.filter(it => {
        const itemIdStr = String(it.item_id || it.id);
        const itemSku = (it.sku || '').toLowerCase();
        if (idsEnEdicion.has(itemIdStr)) return false;
        if (itemSku && skusEnEdicion.has(itemSku)) return false;

        const titleMatch = (it.title || '').toLowerCase().includes(q);
        const skuMatch = itemSku.includes(q);
        const idMatch = itemIdStr.toLowerCase().includes(q);
        return titleMatch || skuMatch || idMatch;
    }).slice(0, 15);

    if (matches.length === 0) {
        contenedor.innerHTML = `<div style="padding: 10px; color: var(--text2); font-size: 12px; text-align: center;">No se encontraron artículos que coincidan con "${query}".</div>`;
        contenedor.style.display = 'block';
        return;
    }

    contenedor.innerHTML = matches.map(it => {
        const skuText = it.sku ? `SKU: ${it.sku}` : 'Sin SKU';
        return `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--border); gap: 10px; cursor: pointer;" 
                 onmouseover="this.style.background='rgba(255,255,255,0.04)'" 
                 onmouseout="this.style.background='transparent'">
                <div style="flex: 1; min-width: 0;">
                    <div style="font-size: 12.5px; font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${it.title}</div>
                    <div style="font-size: 11px; color: var(--text2); display: flex; gap: 8px; margin-top: 2px;">
                        <span style="color: var(--accent); font-family: monospace;">${skuText}</span>
                        <span>Stock Full: <strong>${it.current_stock || 0}</strong></span>
                        <span>VPD: <strong>${it.vpd || 0}</strong></span>
                    </div>
                </div>
                <button type="button" class="btn btn-sm" style="background: var(--accent); color: #111; font-weight: 700; padding: 4px 10px; font-size: 11px;" 
                        onclick="agregarItemAEdicion(${it.id})">
                    + Agregar
                </button>
            </div>
        `;
    }).join('');
    contenedor.style.display = 'block';
}
window.onBuscarArticuloParaAgregar = onBuscarArticuloParaAgregar;

function agregarItemAEdicion(itemId) {
    const it = itemsData.find(x => x.id === itemId);
    if (!it) return;

    const upb = (it.units_per_box && it.units_per_box > 0) ? it.units_per_box : 0;
    const unitsToSend = upb > 0 ? upb : 10;
    const boxCount = upb > 0 ? Math.ceil(unitsToSend / upb) : 1;

    itemsEnEdicion.push({
        id: null,
        item_id: String(it.item_id || it.id),
        inventory_id: it.inventory_id || null,
        variation_id: it.variation_id || null,
        variation_name: it.variation_name || null,
        sku: it.sku || '',
        title: it.title || 'Producto sin título',
        current_full_stock: parseInt(it.current_stock, 10) || 0,
        vpd: parseFloat(it.vpd) || 0,
        suggested_units: parseInt(it.suggested_units, 10) || 0,
        units_to_send: unitsToSend,
        units_per_box: upb,
        box_count: boxCount
    });

    const searchInput = document.getElementById('editarEnvioBuscarInput');
    if (searchInput) searchInput.value = '';
    const contenedor = document.getElementById('editarEnvioResultadosBusqueda');
    if (contenedor) {
        contenedor.innerHTML = '';
        contenedor.style.display = 'none';
    }

    renderizarItemsEdicion();
    verificarAlertasStockEdicion();
    showToast(`Artículo "${it.sku || it.title.substring(0, 25)}" sumado al envío.`, "info");
}
window.agregarItemAEdicion = agregarItemAEdicion;

async function guardarEdicionEnvio() {
    if (!shipmentEnEdicionId) {
        alert("Error interno: no se encontró ID del envío en edición.");
        return;
    }

    if (itemsEnEdicion.length === 0) {
        alert("El envío debe contener al menos un producto con unidades mayor a cero.");
        return;
    }

    const fechaRetiro = document.getElementById('editarEnvioFechaRetiro')?.value || null;
    const packagingType = document.getElementById('editarEnvioPackaging')?.value || 'cajas_master';
    const carrierNotes = (document.getElementById('editarEnvioNotas')?.value || '').trim();

    const payload = {
        pickup_date: fechaRetiro,
        packaging_type: packagingType,
        carrier_notes: carrierNotes,
        items: itemsEnEdicion.map(it => ({
            item_id: it.item_id,
            inventory_id: it.inventory_id,
            variation_id: it.variation_id,
            variation_name: it.variation_name,
            sku: it.sku,
            title: it.title,
            current_full_stock: it.current_full_stock,
            vpd: it.vpd,
            suggested_units: it.suggested_units,
            units_to_send: it.units_to_send,
            units_per_box: it.units_per_box,
            box_count: it.box_count
        }))
    };

    const btnGuardar = document.getElementById('btnGuardarEdicionEnvio');
    if (btnGuardar) {
        btnGuardar.disabled = true;
        btnGuardar.textContent = 'Guardando...';
    }

    const token = getToken();
    try {
        const res = await fetch(`${API_BASE}/full/inbound/shipments/${shipmentEnEdicionId}`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.ok) {
            showToast("Envío actualizado correctamente.", "success");
            cerrarModalEditarEnvio(true);
            // Actualizar tabla principal de stock para reflejar nuevo stock en preparación / tránsito
            if (typeof cargarDatos === 'function') cargarDatos();
        } else {
            alert(data.error || "No se pudo actualizar el envío.");
        }
    } catch (e) {
        alert("Error de conexión al guardar cambios: " + e.message);
    } finally {
        if (btnGuardar) {
            btnGuardar.disabled = false;
            btnGuardar.textContent = 'Guardar Cambios';
        }
    }
}
window.guardarEdicionEnvio = guardarEdicionEnvio;

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
    cargarAjustesColecta();
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
            const syncEl = document.getElementById('cfgSyncFrequency');
            if (syncEl && s.sync_frequency_hours !== undefined) {
                syncEl.value = String(s.sync_frequency_hours);
            }
            actualizarEstadoVerificacionEmail(s.email_verified);

            // Sincronizar branding y co-branding personalizado
            if (s.brand_enabled !== undefined) {
                const branding = {
                    brand_enabled: Boolean(s.brand_enabled),
                    brand_name: s.brand_name || '',
                    brand_logo_url: s.brand_logo_url || '',
                    brand_primary_color: s.brand_primary_color || '',
                    brand_show_powered_by: s.brand_show_powered_by !== undefined ? Boolean(s.brand_show_powered_by) : true
                };
                window.currentBranding = branding;
                localStorage.setItem('enviobot_client_branding', JSON.stringify(branding));
                aplicarBrandingUI(branding);
            }

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
    const tabBranding = document.getElementById('configTabBranding');

    const btnMeli = document.getElementById('tabBtnMeli');
    const btnGeneral = document.getElementById('tabBtnGeneral');
    const btnWA = document.getElementById('tabBtnWhatsapp');
    const btnTeam = document.getElementById('tabBtnTeam');
    const btnBranding = document.getElementById('tabBtnBranding');

    const btnSave = document.getElementById('btnConfigSave');
    const btnCancel = document.getElementById('btnConfigCancel');

    [btnMeli, btnGeneral, btnWA, btnTeam, btnBranding].forEach(b => { if (b) b.classList.remove('active'); });
    [tabMeli, tabGeneral, tabWA, tabTeam, tabBranding].forEach(t => { if (t) t.style.display = 'none'; });

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
        cargarEquipoNuevo();
    } else if (tab === 'branding') {
        if (tabBranding) tabBranding.style.display = 'block';
        if (btnBranding) btnBranding.classList.add('active');
        if (btnSave) btnSave.style.display = 'inline-block';
        if (btnCancel) btnCancel.textContent = 'Cancelar';
        cargarBrandingEnFormulario();
    }
}

// ── EQUIPO: personas del negocio, rol en Full, cuentas que ven e invitaciones ──
// Solo aparece si el admin prendió "equipo" para este abono; si no, queda la pantalla vieja.
let _equipo = null;
const _EQ_ROLES = {
    admin: ['Administrador', 'Gestiona el equipo, las cuentas, los destinatarios y la configuración.'],
    operator: ['Operador', 'Trabaja con los productos, las colectas y la sincronización. No gestiona equipo ni cuentas.'],
    viewer: ['Solo ver', 'Consulta el panel sin modificar nada.']
};
const _EQ_TIPO = { titular: 'Titular', colaborador: 'Colaborador de Full', usuario_pedidos: 'Usuario de Pedidos' };

function eqEsc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function eqFetch(ruta, metodo, cuerpo) {
    const opts = { method: metodo || 'GET', headers: { 'Authorization': `Bearer ${getToken()}` } };
    if (cuerpo !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(cuerpo); }
    return fetch(`${API_BASE}${ruta}`, opts).then(r => r.json());
}

async function cargarEquipoNuevo() {
    const nuevo = document.getElementById('equipoNuevoBox');
    const viejo = document.getElementById('equipoLegacy');
    if (!nuevo || !viejo) { cargarMiembrosEquipo(); return; }
    try {
        const e = getToken() ? await eqFetch('/full/equipo/estado') : { habilitado: false };
        if (e.ok && e.habilitado) {
            nuevo.style.display = 'block';
            viejo.style.display = 'none';
            await recargarEquipo();
            return;
        }
    } catch (err) { /* sin conexión o sin la función: pantalla vieja */ }
    nuevo.style.display = 'none';
    viejo.style.display = 'block';
    cargarMiembrosEquipo();
}

async function recargarEquipo() {
    const box = document.getElementById('equipoNuevoBox');
    const d = await eqFetch('/full/equipo');
    if (!d.ok) { box.textContent = d.error || 'No se pudo cargar el equipo.'; return; }
    _equipo = d;
    const formAbierto = !!(document.getElementById('equipoForm') && document.getElementById('equipoForm').innerHTML);
    box.innerHTML = `
        <div class="eq-barra">
            <h4 style="font-size: 14.5px; font-weight: 700; color: var(--text); margin: 0;">Equipo de ${eqEsc(d.negocio || 'tu negocio')}</h4>
            ${d.soy_admin ? `<button type="button" class="btn btn-secondary btn-sm" onclick="equipoAbrirForm()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align: -2px;"><path d="M12 5v14M5 12h14"/></svg> Invitar persona</button>` : ''}
        </div>
        <div class="eq-nota">Cada persona entra con su propio email y contraseña. Elegís qué rol tiene en EnvioBot Full y qué cuentas de MercadoLibre ve. Las cuentas las conectan los administradores.</div>
        <div id="equipoForm"></div>
        <div id="equipoLista"></div>
        <div id="equipoPend"></div>`;
    pintarEquipo();
    if (formAbierto) equipoAbrirForm();
}

function pintarEquipo() {
    const d = _equipo;
    document.getElementById('equipoLista').innerHTML = d.miembros.map(m => {
        const ini = (m.nombre || '?').trim().split(/\s+/).slice(0, 2).map(s => s[0]).join('').toUpperCase();
        const editable = d.soy_admin && m.tipo !== 'titular';
        const opciones = (m.rol === 'none' ? '<option value="none" selected>Sin acceso a Full</option>' : '') +
            d.roles.map(r => `<option value="${r.codigo}"${r.codigo === m.rol ? ' selected' : ''}>${eqEsc(r.nombre)}</option>`).join('');
        const rolHtml = editable
            ? `<select class="filter-select" style="font-size: 12px; padding: 5px 8px;" onchange="equipoCambiarRol(${m.id}, this.value)" aria-label="Rol de ${eqEsc(m.nombre)}">${opciones}</select>`
            : `<span class="eq-estado">${m.rol === 'none' ? 'Sin acceso a Full' : eqEsc((_EQ_ROLES[m.rol] || [m.rol])[0])}</span>`;
        const quitar = editable && !m.soy_yo && m.rol !== 'none'
            ? `<a class="eq-link" onclick="equipoQuitar(${m.id})">Quitar de Full</a>` : '';
        let cuentasHtml;
        if (m.rol === 'none') {
            cuentasHtml = '<div class="eq-cuenta">Todavía no tiene acceso a EnvioBot Full. Elegí un rol para darle acceso.</div>';
        } else if (m.rol === 'admin') {
            cuentasHtml = '<div class="eq-cuenta">Ve todas las cuentas del negocio (los administradores ven y conectan cualquiera).</div>';
        } else if (!d.cuentas.length) {
            cuentasHtml = '<div class="eq-cuenta">Todavía no hay cuentas de MercadoLibre conectadas en el negocio.</div>';
        } else {
            cuentasHtml = d.cuentas.map(c => {
                const hab = m.habilitadas.some(h => h.platform === c.platform && h.external_id === c.external_id);
                const id = `eqc-${m.id}-${c.platform}-${eqEsc(c.external_id)}`;
                return `<div class="eq-cuenta"><input type="checkbox" id="${id}" data-p="${eqEsc(c.platform)}" data-e="${eqEsc(c.external_id)}"
                    ${hab ? 'checked' : ''} ${editable ? '' : 'disabled'} onchange="equipoGuardarCuentas(${m.id})">
                    <label for="${id}">${eqEsc(c.nombre)}</label></div>`;
            }).join('');
        }
        return `<div class="eq-fila" id="eqm-${m.id}">
            <div class="eq-av" aria-hidden="true">${eqEsc(ini)}</div>
            <div class="eq-cuerpo">
                <div class="eq-cab">
                    <div>
                        <div class="eq-nombre">${eqEsc(m.nombre)}<span class="eq-etiqueta">${eqEsc(_EQ_TIPO[m.tipo] || '')}</span>${m.soy_yo ? '<span class="eq-etiqueta eq-yo">Vos</span>' : ''}</div>
                        <div class="eq-mail">${eqEsc(m.email)}</div>
                    </div>
                    <div class="eq-ctrl">${rolHtml}${quitar}</div>
                </div>
                <div class="eq-cuentas"><div style="margin-bottom: 2px;">Cuentas de MercadoLibre que ve</div>${cuentasHtml}</div>
            </div>
        </div>`;
    }).join('');

    document.getElementById('equipoPend').innerHTML = d.pendientes.length
        ? `<div style="font-size: 13px; font-weight: 700; color: var(--text); margin: 14px 0 4px;">Invitaciones sin usar</div>` + d.pendientes.map(p => `
            <div class="eq-pend">
                <span><b style="color: var(--text);">${eqEsc(p.nombre || '')}</b> · ${eqEsc((_EQ_ROLES[p.rol] || [''])[0])}
                    ${p.email ? ' · ' + eqEsc(p.email) : ''}${p.celular ? ' · ' + eqEsc(p.celular) : ''}
                    · vence ${new Date(p.vence).toLocaleDateString('es-AR')}</span>
                <span class="eq-ctrl">
                    <a class="eq-link" onclick="equipoCopiar('${eqEsc(p.code)}')">Copiar link</a>
                    ${p.celular ? `<a class="eq-link" onclick="window.open(equipoUrlWhatsApp('${eqEsc(p.celular)}', '${eqEsc(p.nombre || '')}', '${eqEsc(p.code)}'), '_blank')">WhatsApp</a>` : ''}
                    ${d.soy_admin ? `<a class="eq-link" onclick="equipoCancelar(${p.id})">Cancelar</a>` : ''}
                </span>
            </div>`).join('')
        : '';
}

async function equipoCambiarRol(id, rol) {
    const d = await eqFetch(`/full/equipo/miembros/${id}`, 'PUT', { rol });
    if (!d.ok) showToast(d.error || 'No se pudo cambiar el rol.', 'error');
    await recargarEquipo();
}

async function equipoGuardarCuentas(id) {
    const fila = document.getElementById(`eqm-${id}`);
    const cuentas = [...fila.querySelectorAll('input[type=checkbox]:checked')].map(i => ({ platform: i.dataset.p, external_id: i.dataset.e }));
    const d = await eqFetch(`/full/equipo/miembros/${id}`, 'PUT', { cuentas });
    showToast(d.ok ? 'Cuentas guardadas.' : (d.error || 'No se pudo guardar.'), d.ok ? 'success' : 'error');
    await recargarEquipo();
}

async function equipoQuitar(id) {
    const m = _equipo.miembros.find(x => x.id === id);
    if (!confirm(`¿Sacar a ${m ? m.nombre : 'esta persona'} de EnvioBot Full? Su usuario no se borra: solo pierde el acceso a Full.`)) return;
    const d = await eqFetch(`/full/equipo/miembros/${id}`, 'DELETE');
    if (!d.ok) showToast(d.error || 'No se pudo quitar.', 'error');
    await recargarEquipo();
}

async function equipoCancelar(id) {
    if (!confirm('¿Cancelar esta invitación? El link deja de funcionar.')) return;
    const d = await eqFetch(`/full/equipo/invitaciones/${id}`, 'DELETE');
    if (!d.ok) showToast(d.error || 'No se pudo cancelar.', 'error');
    await recargarEquipo();
}

function equipoAbrirForm() {
    const form = document.getElementById('equipoForm');
    if (!form) return;
    const d = _equipo;
    form.innerHTML = `<div class="eq-form">
        <div style="font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 10px;">Invitar a una persona</div>
        <div class="eq-campos">
            <div><label for="eqNombre">Nombre</label><input id="eqNombre" class="filter-input" style="width: 100%;" autocomplete="off" placeholder="Ej: Dani"></div>
            <div><label for="eqCelular">Celular (para WhatsApp)</label><input id="eqCelular" class="filter-input" style="width: 100%;" inputmode="tel" autocomplete="off" placeholder="Ej: 11 5555 0000"></div>
            <div><label for="eqEmail">Email (opcional)</label><input id="eqEmail" type="email" class="filter-input" style="width: 100%;" autocomplete="off" placeholder="nombre@correo.com"></div>
        </div>
        <div class="eq-tit">Qué rol tiene en EnvioBot Full</div>
        <div class="eq-roles">${d.roles.map(r => `
            <label class="eq-rol"><b><input type="radio" name="eqRol" value="${r.codigo}"${r.codigo === 'operator' ? ' checked' : ''}>${eqEsc(_EQ_ROLES[r.codigo][0])}</b>${eqEsc(_EQ_ROLES[r.codigo][1])}</label>`).join('')}</div>
        <div class="eq-tit">Cuentas de MercadoLibre que ve</div>
        <div id="eqCuentasInv">${d.cuentas.length ? d.cuentas.map(c => `
            <div class="eq-cuenta"><input type="checkbox" id="eqi-${c.platform}-${eqEsc(c.external_id)}" data-p="${eqEsc(c.platform)}" data-e="${eqEsc(c.external_id)}" checked>
            <label for="eqi-${c.platform}-${eqEsc(c.external_id)}">${eqEsc(c.nombre)}</label></div>`).join('')
            : '<div class="eq-cuenta">Todavía no hay cuentas conectadas en el negocio.</div>'}</div>
        <div class="eq-acciones">
            <button type="button" class="btn btn-sm" onclick="equipoEnviar('whatsapp')">Enviar por WhatsApp</button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="equipoEnviar('email')">Enviar por email</button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="equipoEnviar('link')">Solo copiar el link</button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('equipoForm').innerHTML = ''">Cerrar</button>
        </div>
        <div class="eq-nota" style="margin: 10px 0 0;">La persona recibe un link que vale 7 días y sirve una sola vez. Al abrirlo elige su contraseña y entra directo.</div>
    </div>`;
    document.getElementById('eqNombre').focus();
}

function equipoLinkInvitacion(code) {
    return `${location.origin}${location.pathname.replace(/[^/]*$/, '')}invitacion.html?inv=${encodeURIComponent(code)}`;
}

// Para abrir WhatsApp a mano (el botón "WhatsApp" de una invitación pendiente).
function equipoNumeroWhatsApp(crudo) {
    let n = (crudo || '').replace(/\D/g, '').replace(/^0+/, '');
    if (!n) return '';
    if (!n.startsWith('54')) n = '54' + n;
    if (!n.startsWith('549')) n = '549' + n.slice(2);
    return n;
}

function equipoUrlWhatsApp(celular, nombre, code) {
    const primero = (nombre || '').split(' ')[0];
    const negocio = _equipo && _equipo.negocio ? _equipo.negocio : 'mi negocio';
    const texto = `Hola ${primero}! Te invito a usar EnvioBot Full con ${negocio}. Entrá con este link y elegí tu contraseña (vale 7 días): ${equipoLinkInvitacion(code)}`;
    return `https://wa.me/${equipoNumeroWhatsApp(celular)}?text=${encodeURIComponent(texto)}`;
}

async function equipoCopiar(code) {
    try {
        await navigator.clipboard.writeText(equipoLinkInvitacion(code));
        showToast('Link copiado. Pasáselo a la persona.', 'success');
    } catch (e) {
        prompt('Copiá este link y pasáselo a la persona:', equipoLinkInvitacion(code));
    }
}

async function equipoEnviar(via) {
    const nombre = document.getElementById('eqNombre').value.trim();
    const celular = document.getElementById('eqCelular').value.trim();
    const email = document.getElementById('eqEmail').value.trim();
    if (!nombre) { showToast('Poné el nombre de la persona.', 'error'); return; }
    if (via === 'whatsapp' && !celular) { showToast('Para WhatsApp falta el celular.', 'error'); return; }
    if (via === 'email' && !email) { showToast('Para el email falta la dirección.', 'error'); return; }
    const rol = (document.querySelector('input[name=eqRol]:checked') || {}).value || 'operator';
    const cuentas = [...document.querySelectorAll('#eqCuentasInv input:checked')].map(i => ({ platform: i.dataset.p, external_id: i.dataset.e }));
    const d = await eqFetch('/full/equipo/invitaciones', 'POST', {
        nombre, rol, cuentas,
        celular: via === 'email' ? '' : celular,
        email: via === 'whatsapp' ? '' : email,
        enviar_whatsapp: via === 'whatsapp',
        enviar_email: via === 'email'
    });
    if (!d.ok) { showToast(d.error || 'No se pudo crear la invitación.', 'error'); return; }
    if (via === 'whatsapp') {
        const w = d.enviado && d.enviado.whatsapp;
        if (w && w.ok && !w.simulated) showToast(`Invitación enviada por WhatsApp a ${nombre}.`, 'success');
        else { window.open(equipoUrlWhatsApp(celular, nombre, d.code), '_blank'); showToast('El envío automático no está activo: se abrió WhatsApp con el mensaje listo.', 'info'); }
    } else if (via === 'email') {
        if (d.enviado && d.enviado.email) showToast(`Invitación enviada a ${email}.`, 'success');
        else { await equipoCopiar(d.code); showToast('No se pudo mandar el email desde acá. Copié el link para que se lo pases.', 'info'); }
    } else {
        await equipoCopiar(d.code);
    }
    document.getElementById('equipoForm').innerHTML = '';
    await recargarEquipo();
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

        // Renderizar usuarios satélite detectados en EnvioBot Pedidos
        const satSection = document.getElementById('cfgTeamSatellitesSection');
        const satList = document.getElementById('cfgTeamSatellitesList');
        if (satSection && satList) {
            if (data.satellites_pedidos && data.satellites_pedidos.length > 0) {
                satList.innerHTML = '';
                satSection.style.display = 'block';
                data.satellites_pedidos.forEach(s => {
                    const row = document.createElement('div');
                    row.style.cssText = 'display: flex; justify-content: space-between; align-items: center; background: var(--surf1); border: 1px solid var(--border); border-radius: 6px; padding: 9px 12px; font-size: 12.5px;';
                    row.innerHTML = `
                        <div>
                            <strong style="color: var(--text);">${s.full_name || 'Usuario Satélite'}</strong>
                            <span style="color: var(--text2); font-family: monospace; margin-left: 8px;">(${s.email})</span>
                            <span class="role-badge" style="margin-left: 6px; font-size: 10px; background: rgba(56, 189, 248, 0.15); color: var(--accent);">EnvioBot Pedidos</span>
                        </div>
                        <button type="button" class="btn btn-sm" style="background: var(--accent); color: #111; font-weight: 700; padding: 5px 12px; font-size: 11.5px;"
                                onclick="habilitarSateliteEnFull('${s.email}', '${s.full_name || ''}')">
                            Habilitar en Full
                        </button>
                    `;
                    satList.appendChild(row);
                });
            } else {
                satSection.style.display = 'none';
            }
        }

        if (data.members.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 20px; color: var(--text2);">No tenés colaboradores en tu equipo aún. Podés habilitar a Fran arriba.</td></tr>';
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

async function habilitarSateliteEnFull(email, name) {
    const token = getToken();
    if (!token) return;
    try {
        const resp = await fetch(`${API_BASE}/full/team/invite`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({
                full_name: name || 'Colaborador',
                email: email,
                password: ''
            })
        });
        const data = await resp.json();
        if (data.ok) {
            showToast(`${name || email} habilitado en Full con su contraseña de Pedidos.`, "success");
            cargarMiembrosEquipo();
        } else {
            showToast(data.error || "No se pudo habilitar al colaborador.", "error");
        }
    } catch (e) {
        console.error("Error habilitando satélite:", e);
        showToast("Error de conexión al habilitar satélite.", "error");
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
        showToast("Ingresá el correo electrónico del colaborador a invitar.", "error");
        return;
    }

    const token = getToken();
    if (!token) {
        showToast("Iniciá sesión para invitar miembros a tu equipo.", "error");
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
            showToast(data.error || "No se pudo invitar al colaborador.", "error");
            return;
        }

        if (data.is_existing_user || data.uses_existing_password) {
            if (resEl) {
                resEl.style.display = 'block';
                resEl.innerHTML = `<strong>${data.member.full_name || email} ya es usuario de EnvioBot:</strong><br><span style="color: var(--text2);">Su acceso a Full quedó habilitado. <strong>Mantiene la misma contraseña que ya utiliza habitualmente en EnvioBot Pedidos.</strong></span>`;
            }
            showToast(`${data.member.full_name || email} habilitado con su clave habitual de Pedidos.`, "success");
        } else {
            const clave = data.initial_password || pass || '123456';
            if (resEl) {
                resEl.style.display = 'block';
                resEl.innerHTML = `<strong>Nuevo Colaborador Creado (${data.member.full_name || email}):</strong><br>Email: <code>${email}</code><br>Contraseña Inicial: <strong><code>${clave}</code></strong><br><small style="color: var(--text2);">Al ingresar por primera vez con esta clave temporal se le solicitará definir su contraseña personal.</small>`;
            }
            showToast(`Colaborador ${name || email} creado con éxito.`, "success");
        }
        
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

// ── MANEJO DE CAMBIO DE CONTRASEÑA OBLIGATORIO PARA NUEVOS USUARIOS ──
function abrirModalChangePassword() {
    const m = document.getElementById('modalChangePassword');
    if (m) m.style.display = 'flex';
}

async function confirmarCambioContraseña() {
    const p1 = document.getElementById('changePwInput').value.trim();
    const p2 = document.getElementById('changePwConfirmInput').value.trim();
    const err = document.getElementById('changePwError');
    if (err) err.style.display = 'none';

    if (p1.length < 6) {
        if (err) { err.textContent = 'La nueva contraseña debe tener al menos 6 caracteres.'; err.style.display = 'block'; }
        return;
    }
    if (p1 === '123456') {
        if (err) { err.textContent = 'Debés ingresar una contraseña personal diferente a la clave inicial 123456.'; err.style.display = 'block'; }
        return;
    }
    if (p1 !== p2) {
        if (err) { err.textContent = 'Las contraseñas no coinciden.'; err.style.display = 'block'; }
        return;
    }

    const token = getToken();
    try {
        const resp = await fetch(`${API_BASE}/auth/change-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ new_password: p1 })
        });
        const d = await resp.json();
        if (d.ok) {
            const m = document.getElementById('modalChangePassword');
            if (m) m.style.display = 'none';
            showToast('Tu contraseña personal fue guardada exitosamente.', 'success');
        } else {
            if (err) { err.textContent = d.error || 'Error al actualizar contraseña.'; err.style.display = 'block'; }
        }
    } catch (e) {
        if (err) { err.textContent = e.message; err.style.display = 'block'; }
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
                ${isVerified ? '' : `<button class="btn btn-primary btn-sm" style="padding: 3px 8px; font-size: 11px; margin-right: 4px;" 
                        onclick="reenviarVerificacionWA('${r.phone}', '${r.name}')" title="Reenviar el botón de verificación">
                    Reenviar verificación
                </button>`}
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
            alert(`Destinatario ${name} agregado con éxito.\nLe enviamos un WhatsApp a ${phone} con el botón para verificar el número.`);
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

async function reenviarVerificacionWA(phone, name) {
    try {
        const resp = await fetch(`${API_BASE}/full/verify/send-whatsapp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
            body: JSON.stringify({ phone, name })
        });
        const data = await resp.json();
        alert(data.ok ? `Reenviamos el botón de verificación a ${phone}.` : (data.error || 'No se pudo reenviar.'));
    } catch (e) {
        alert('No se pudo reenviar la verificación.');
    }
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

    // Branding y Co-Branding
    const brandEnabled = document.getElementById('cfgBrandEnabled')?.checked || false;
    const brandName = document.getElementById('cfgBrandName')?.value.trim() || '';
    const brandLogoUrl = window.currentBrandLogoDataUrl || document.getElementById('cfgBrandLogoPreviewImg')?.src || '';
    const brandColor = document.getElementById('cfgBrandPrimaryColor')?.value || '#f5a623';
    const brandShowPowered = true;

    const brandingPayload = {
        brand_enabled: brandEnabled,
        brand_name: brandName,
        brand_logo_url: brandLogoUrl,
        brand_primary_color: brandColor,
        brand_show_powered_by: true
    };
    window.currentBranding = brandingPayload;
    localStorage.setItem('enviobot_client_branding', JSON.stringify(brandingPayload));
    aplicarBrandingUI(brandingPayload);

    const token = getToken();
    if (token) {
        try {
            const syncFreq = parseInt(document.getElementById('cfgSyncFrequency')?.value, 10) || 4;
            await fetch(`${API_BASE}/full/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({
                    default_lead_time_days: lt,
                    default_safety_stock_days: ss,
                    target_coverage_days: generalTarget,
                    sync_frequency_hours: syncFreq,
                    alert_email: email,
                    warehouses: warehousesList,
                    brand_enabled: brandEnabled,
                    brand_name: brandName,
                    brand_logo_url: brandLogoUrl,
                    brand_primary_color: brandColor,
                    brand_show_powered_by: brandShowPowered
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
            showToast(data.message || 'Detectamos tu cuenta de EnvioBot Pedidos. Se habilitó EnvioBot Full con tu contraseña habitual.', 'success');
        }

        // Si se le exige cambio de contraseña al nuevo colaborador que ingresó con clave inicial
        if (data.must_change_password || (data.user && data.user.must_change_password)) {
            abrirModalChangePassword();
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
            errBox.style.lineHeight = '1.45';
        } else {
            showToast(err.message, 'error');
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
    const headerAcc = document.getElementById('headerMeliAccount');
    const headerDot = document.getElementById('headerMeliDot');

    let accountDisplay = 'Sin vincular';
    let isConnected = false;

    if (accounts && accounts.length > 0) {
        isConnected = true;
        if (currentAccount && currentAccount !== 'all') {
            const found = accounts.find(a => String(a.id) === String(currentAccount));
            accountDisplay = found ? (found.ml_nickname || found.ml_user_id) : (accounts[0].ml_nickname || accounts[0].ml_user_id);
        } else if (accounts.length === 1) {
            accountDisplay = accounts[0].ml_nickname || accounts[0].ml_user_id;
        } else {
            accountDisplay = accounts.map(a => a.ml_nickname || a.ml_user_id).join(', ');
        }
    }

    // Actualizar estado en Encabezado
    if (headerAcc) {
        headerAcc.textContent = accountDisplay;
    }
    if (headerDot) {
        headerDot.style.background = isConnected ? '#4CAF50' : 'var(--text2)';
    }

    // Selector de cuentas múltiples
    if (select) {
        select.innerHTML = '<option value="all">Todas las cuentas</option>';
        if (accounts && accounts.length > 1) {
            accounts.forEach(acc => {
                const opt = document.createElement('option');
                opt.value = acc.id;
                opt.textContent = acc.ml_nickname || acc.ml_user_id;
                if (String(currentAccount) === String(acc.id)) opt.selected = true;
                select.appendChild(opt);
            });
            select.style.display = 'inline-block';
        } else {
            select.style.display = 'none';
        }
        if (btnConnect) btnConnect.style.display = 'inline-block';
    }

    // Compatibilidad si existiera sidebar
    if (sidebarAcc) {
        sidebarAcc.textContent = accountDisplay;
        if (sidebarStatus) {
            sidebarStatus.className = isConnected ? 'badge badge-ok' : 'badge badge-warn';
            sidebarStatus.textContent = isConnected ? 'Activo' : 'Sin vincular';
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
    badge.style.display = 'inline-flex';

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
    if (planInfo.plan_tier === 'trial' || planInfo.plan === 'trial') {
        const days = planInfo.trial_days_left !== undefined ? planInfo.trial_days_left : (planInfo.days_left !== undefined ? planInfo.days_left : 30);
        badge.className = 'plan-badge trial';
        badge.textContent = `Prueba (${days}d restantes)`;
    } else {
        const planName = planInfo.plan_name || planInfo.plan_tier || planInfo.plan || 'Activo';
        badge.className = 'plan-badge';
        badge.textContent = `Plan ${planName}`;
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
        if (viewWelcome) viewWelcome.style.display = 'flex';
        if (viewDash) viewDash.style.display = 'none';
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
    // 0. Inicializar Branding y Co-Branding de la cuenta
    if (typeof inicializarBranding === 'function') {
        inicializarBranding();
    }

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
        cargarHistorialColectas(true);
        cargarMonitorEventosLogisticos();
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
    const batLines = [
        '@echo off',
        'chcp 65001 >nul',
        'echo Creando acceso directo en el escritorio de Windows...',
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [System.Environment]::GetFolderPath(\'Desktop\'); $shortcutPath = [System.IO.Path]::Combine($desktop, \'EnvioBot Full.lnk\'); $chrome = \'${env:ProgramFiles}\\Google\\Chrome\\Application\\chrome.exe\'; if (-not (Test-Path $chrome)) { $chrome = \'${env:ProgramFiles(x86)}\\Google\\Chrome\\Application\\chrome.exe\' }; if (-not (Test-Path $chrome)) { $chrome = \'${env:LocalAppData}\\Google\\Chrome\\Application\\chrome.exe\' }; if (-not (Test-Path $chrome)) { $chrome = \'${env:ProgramFiles(x86)}\\Microsoft\\Edge\\Application\\msedge.exe\' }; $s = $ws.CreateShortcut($shortcutPath); $s.TargetPath = $chrome; $s.Arguments = \'--app=https://enviobot.com.ar/full/ --start-maximized\'; $s.Description = \'EnvioBot Full\'; $s.Save(); Write-Host \'Acceso directo creado exitosamente.\'"',
        'echo Acceso directo creado con exito en tu escritorio.',
        'timeout /t 3 >nul'
    ];
    const batContent = batLines.join('\r\n') + '\r\n';
    const blob = new Blob([batContent], { type: 'application/bat' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'Instalar_EnvioBot_Full_Escritorio.bat';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast('Descargando instalador de escritorio de 1 clic.', 'success');
}

// ── MÓDULO DE CO-BRANDING Y PERSONALIZACIÓN DE MARCA ──────────────────
window.currentBranding = null;
window.currentBrandLogoDataUrl = '';

function inicializarBranding() {
    try {
        const local = localStorage.getItem('enviobot_client_branding');
        if (local) {
            window.currentBranding = JSON.parse(local);
            aplicarBrandingUI(window.currentBranding);
        }
    } catch (e) {
        console.warn("Aviso inicializando branding local:", e);
    }

    configurarDropzoneBranding();
}

function aplicarBrandingUI(branding) {
    if (!branding) return;

    const defaultLogo = document.getElementById('defaultBrandLogo');
    const customLogo = document.getElementById('customBrandLogo');
    const clientLogoImg = document.getElementById('headerClientLogoImg');
    const poweredByPill = document.getElementById('headerPoweredByPill');

    if (branding.brand_enabled && branding.brand_logo_url) {
        // 1. Mostrar logo del cliente y co-branding
        if (defaultLogo) defaultLogo.style.display = 'none';
        if (customLogo) customLogo.style.display = 'flex';
        if (clientLogoImg) {
            clientLogoImg.src = branding.brand_logo_url;
            clientLogoImg.alt = branding.brand_name || 'Logo Empresa';
        }
        if (poweredByPill) {
            poweredByPill.style.display = 'inline-flex';
        }

        // 2. Aplicar colores personalizados si existen
        if (branding.brand_primary_color) {
            const hex = branding.brand_primary_color;
            document.documentElement.style.setProperty('--accent', hex);
            document.documentElement.style.setProperty('--accent-text', hex);
            document.documentElement.style.setProperty('--accent-d', hex);
        }
    } else {
        // Restaurar branding original EnvioBot Full
        if (defaultLogo) defaultLogo.style.display = 'flex';
        if (customLogo) customLogo.style.display = 'none';

        // Restaurar naranja original
        document.documentElement.style.removeProperty('--accent');
        document.documentElement.style.removeProperty('--accent-text');
        document.documentElement.style.removeProperty('--accent-d');
    }
}

function cargarBrandingEnFormulario() {
    let b = window.currentBranding;
    if (!b) {
        try {
            const local = localStorage.getItem('enviobot_client_branding');
            if (local) b = JSON.parse(local);
        } catch (e) {}
    }
    b = b || {
        brand_enabled: false,
        brand_name: '',
        brand_logo_url: '',
        brand_primary_color: '#f5a623',
        brand_show_powered_by: true
    };

    const chkEnabled = document.getElementById('cfgBrandEnabled');
    const inputName = document.getElementById('cfgBrandName');
    const inputColor = document.getElementById('cfgBrandPrimaryColor');
    const hexColor = document.getElementById('cfgBrandColorHex');
    const previewImg = document.getElementById('cfgBrandLogoPreviewImg');
    const noLogoText = document.getElementById('cfgBrandNoLogoText');

    if (chkEnabled) chkEnabled.checked = Boolean(b.brand_enabled);
    if (inputName) {
        let bName = b.brand_name || '';
        if (/copia\s+de\s+seguridad/i.test(bName) || /corel/i.test(bName)) {
            bName = 'Mister Nut';
        }
        inputName.value = bName;
    }
    if (inputColor) inputColor.value = b.brand_primary_color || '#f5a623';
    if (hexColor) hexColor.textContent = b.brand_primary_color || '#f5a623';

    const btnQuitar = document.getElementById('btnQuitarLogo');
    const dropStatus = document.getElementById('dropzoneStatusText');

    if (b.brand_logo_url) {
        window.currentBrandLogoDataUrl = b.brand_logo_url;
        if (previewImg) {
            previewImg.src = b.brand_logo_url;
            previewImg.style.display = 'block';
        }
        if (noLogoText) noLogoText.style.display = 'none';
        if (btnQuitar) btnQuitar.style.display = 'inline-flex';
        if (dropStatus) dropStatus.style.display = 'block';
    } else {
        window.currentBrandLogoDataUrl = '';
        if (previewImg) {
            previewImg.src = '';
            previewImg.style.display = 'none';
        }
        if (noLogoText) noLogoText.style.display = 'block';
        if (btnQuitar) btnQuitar.style.display = 'none';
        if (dropStatus) dropStatus.style.display = 'none';
    }

    actualizarEstadoBrandingForm();
    actualizarPreviewBranding();
}

function actualizarEstadoBrandingForm() {
    const enabled = document.getElementById('cfgBrandEnabled')?.checked || false;
    const container = document.getElementById('cfgBrandFieldsContainer');
    if (!container) return;

    if (enabled) {
        container.style.opacity = '1';
        container.style.pointerEvents = 'auto';
    } else {
        container.style.opacity = '0.65';
    }
    actualizarPreviewBranding();
}

function actualizarPreviewBranding() {
    const name = document.getElementById('cfgBrandName')?.value.trim() || 'Tu Empresa';
    const logoUrl = window.currentBrandLogoDataUrl || document.getElementById('cfgBrandLogoPreviewImg')?.src || '';

    const mockupLogo = document.getElementById('mockupLogoPlaceholder');
    const mockupPowered = document.getElementById('mockupPoweredBy');

    if (mockupLogo) {
        if (logoUrl) {
            mockupLogo.innerHTML = `<img src="${logoUrl}" style="max-height: 44px; max-width: 190px; object-fit: contain;">`;
        } else {
            mockupLogo.textContent = name;
        }
    }
    if (mockupPowered) {
        mockupPowered.style.display = 'inline-flex';
    }
}

function configurarDropzoneBranding() {
    const dropzone = document.getElementById('brandDropzone');
    if (!dropzone) return;

    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('dragover');
        }, false);
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files && files.length > 0) {
            procesarArchivoLogo(files[0]);
        }
    }, false);
}

function manejarSeleccionLogo(event) {
    const files = event.target.files;
    if (files && files.length > 0) {
        procesarArchivoLogo(files[0]);
    }
}

function procesarArchivoLogo(file) {
    if (!file || !file.type.startsWith('image/')) {
        alert("Por favor subí un archivo de imagen válido (PNG, JPG, SVG, WebP).");
        return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
        const img = new Image();
        img.onload = () => {
            optimizarYExtraerPaletaLogo(img, file.name);
        };
        img.src = e.target.result;
    };
    reader.readAsDataURL(file);
}

function optimizarYExtraerPaletaLogo(img, fileName = '') {
    // 1. Crear canvas temporal de análisis
    const srcCanvas = document.createElement('canvas');
    srcCanvas.width = img.naturalWidth || img.width;
    srcCanvas.height = img.naturalHeight || img.height;
    const ctx = srcCanvas.getContext('2d');
    ctx.drawImage(img, 0, 0);

    const w = srcCanvas.width;
    const h = srcCanvas.height;
    const imgData = ctx.getImageData(0, 0, w, h);
    const data = imgData.data;

    // 2. Auto-recorte inteligente de márgenes vacíos o blancos
    let minX = w, minY = h, maxX = 0, maxY = 0;
    let hasAlpha = false;

    for (let i = 3; i < data.length; i += 4) {
        if (data[i] < 240) {
            hasAlpha = true;
            break;
        }
    }

    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            const idx = (y * w + x) * 4;
            const r = data[idx];
            const g = data[idx + 1];
            const b = data[idx + 2];
            const a = data[idx + 3];

            let isContent = false;
            if (hasAlpha) {
                isContent = a > 20;
            } else {
                isContent = (r < 245 || g < 245 || b < 245);
            }

            if (isContent) {
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
            }
        }
    }

    if (minX >= maxX || minY >= maxY) {
        minX = 0; minY = 0; maxX = w; maxY = h;
    }

    const pad = 4;
    minX = Math.max(0, minX - pad);
    minY = Math.max(0, minY - pad);
    maxX = Math.min(w, maxX + pad);
    maxY = Math.min(h, maxY + pad);

    const cropW = maxX - minX;
    const cropH = maxY - minY;

    // 3. Normalizar altura estándar (104px para retina 2x a 52px de pantalla)
    const targetHeight = 104;
    const targetWidth = Math.round(cropW * (targetHeight / cropH));
    const outCanvas = document.createElement('canvas');
    outCanvas.width = Math.min(480, Math.max(20, targetWidth));
    outCanvas.height = targetHeight;
    const outCtx = outCanvas.getContext('2d');
    outCtx.imageSmoothingEnabled = true;
    outCtx.imageSmoothingQuality = 'high';

    outCtx.drawImage(srcCanvas, minX, minY, cropW, cropH, 0, 0, outCanvas.width, outCanvas.height);

    // 4. Extracción de color dominante insignia
    const outData = outCtx.getImageData(0, 0, outCanvas.width, outCanvas.height).data;
    const colorScores = [];

    for (let i = 0; i < outData.length; i += 4) {
        const r = outData[i];
        const g = outData[i + 1];
        const b = outData[i + 2];
        const a = outData[i + 3];

        if (a < 120) continue;

        const hsl = rgbToHsl(r, g, b);
        if (hsl.s > 0.18 && hsl.l > 0.15 && hsl.l < 0.85) {
            const score = hsl.s * (1 - Math.abs(hsl.l - 0.5));
            colorScores.push({ r, g, b, hsl, score });
        }
    }

    let dominantHex = '#f5a623';
    if (colorScores.length > 0) {
        colorScores.sort((a, b) => b.score - a.score);
        const best = colorScores[Math.floor(colorScores.length * 0.15)];
        dominantHex = rgbToHex(best.r, best.g, best.b);
    }

    // 5. Exportar DataURL optimizado
    const optimizedDataUrl = outCanvas.toDataURL('image/png');
    window.currentBrandLogoDataUrl = optimizedDataUrl;

    const previewImg = document.getElementById('cfgBrandLogoPreviewImg');
    const noLogoText = document.getElementById('cfgBrandNoLogoText');
    const btnQuitar = document.getElementById('btnQuitarLogo');
    const dropStatus = document.getElementById('dropzoneStatusText');
    if (previewImg) {
        previewImg.src = optimizedDataUrl;
        previewImg.style.display = 'block';
    }
    if (noLogoText) noLogoText.style.display = 'none';
    if (btnQuitar) btnQuitar.style.display = 'inline-flex';
    if (dropStatus) dropStatus.style.display = 'block';

    // No autocompletar el nombre de la empresa con el nombre del archivo en disco
    const nameInput = document.getElementById('cfgBrandName');
    if (nameInput && (/copia\s+de\s+seguridad/i.test(nameInput.value) || /corel/i.test(nameInput.value))) {
        nameInput.value = 'Mister Nut';
    }

    const colorInput = document.getElementById('cfgBrandPrimaryColor');
    const hexSpan = document.getElementById('cfgBrandColorHex');
    if (colorInput) colorInput.value = dominantHex;
    if (hexSpan) hexSpan.textContent = dominantHex;

    const chkEnabled = document.getElementById('cfgBrandEnabled');
    if (chkEnabled) chkEnabled.checked = true;

    actualizarEstadoBrandingForm();
    actualizarPreviewBranding();
    cambiarColorPrimarioBranding(dominantHex);

    showToast(`Logo optimizado. Color detectado: ${dominantHex}`, "info");
}

function cambiarColorPrimarioBranding(hex) {
    const hexSpan = document.getElementById('cfgBrandColorHex');
    if (hexSpan) hexSpan.textContent = hex;

    document.documentElement.style.setProperty('--accent', hex);
    document.documentElement.style.setProperty('--accent-text', hex);
    document.documentElement.style.setProperty('--accent-d', hex);
}

function cargarDemoMisterNut() {
    const nutDataUrl = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAI4AAAAvCAYAAAA1vfJDAAAQlUlEQVR4nO1dWWxc13n+zl2Gw01cRFLiroWSLNKRLcnyltiym9RJjSJoaneLg7RFgSLIg/vW9qGPfSkC5KUoWhSG4QJFG6exY8dbZcX7Isu1FlILxUWixOGQHA45C2efuef+xX+G22gWDodD0g/zQQQ595773zP3fuffzn+OBBGhgp2HPzpEs8GP0d7wJBprBgQfiybdJISBanOP+rxdsD2jRIFp2IFpIOIDWXFAMyGqG6C17Id+5LQwtrNDFeTGfPgCjXlfQih+EzZSTBzMBN8nd+Bd1Dg60N/+PLYatvcm2a5B2O4hyJkboKAbsC0ApP4xRPUu6ANPM3moQpwdRtzy0kzwfYRi45CUwNziOdSa3eQKvIVI0o3alAfB2Ag1VB/ZMq0jr54h69o7sGeHQfFFgCRwtyUynND7vwfz1J9ANLRXNM5OI5JwYT5yQZGGkbB8uLXwCyQsvxrtCWsBocQEGqqPlP3eFPSQNfQmrKtvghZnAFvmbqgZ0A+dhvnQcxC70mazonF2GL7IIBKp+ZXPBFuRZxnSjitylRu06KHUZy/CGj4DJKNpk5QHWnMvjOPPrJCGUSHODmIhfJFc/jcVWfKBIBFPzZb93taFX8Ea/t8l0hSAbkDrvg967/EMU1khzg5gLnSeZhbfw9zi55B2rHBjYnPmxkLkEu2uzXx5pcIafIOs4bPrk4YdYrMWYvfBrONaOTpSQfFw+d+isbkXMBv8EJYdBRUwEQw+zz7OiOff1bXYJGzXZbIuvw4KzqStE4lMK3X3HarqoDV3ZcmpaJxtxOzip3TH92uE47cLmqe7YVMKwdgoUvJlaMKgzsbvlqx5rJvnYHvHWCqgpBBgi1XGMJHEGvY4aiCq6rLkVDTONiGccJHL/xuEE3c2RJpVEGKpGbgCb8MfvVqS5rHnbpI98QVg3WUe1xKF/1aaKE0iTkBC6FmyKsTZJngWP1YRFHGOpETwtcHoDXhCn5Z2/fwEaGEiO0cj1vyohiLdRB1bZlEmKsTZBsRSczS7+JEyOZsFy5gPX1RJwY1em7r0OshK54vyYoksQjGDQMkYKBXPalYhzjbAH7mKWBlD6lhyFqH4rQ1dYwdmyZ69ClARZnKtB5WMgCILWU0qxNkGhBI3Ycl1wu4NwKY4IsmpDV1DszcAmdzwvSgVA/ndWccrxNkGBGLXS3SIc4Nlxddkm4uB7b6Wf0qhEKwEKJStLSvE2WLEUrMUSUwWTOlvFEQ2/NHLGPW8ULRQ23uzODOVdaHkOS1QYDrjXhXibDFSVnhlArOciKW8ajL0i9t/Q8HYjXUJRLHFEslLinQUzNQ6FeJsMXyxQdiqrqX8YM0TiF7HtZl/xnTwt4VZsYk3TTEfbL+rPOIoOFMpHSyAaGqGJhZ+SZO+35QlDC+U21mMj2Js7j9wa/7lvO9EOBvuCpc2AGnB9nC2eRVa8r2fkxz7pCAJKOSl1If/QnJqkJgwqU9foNS5l2Cde0l9xtcI1qVXSd78LGef5PBZsqeGSuqvdfk1kjfWGdVrEIyNgGe+oyr62dpHxOSJJt2443sVE/O/yHkzbc8RLCVnSrkDz3FlypPjn8O69EqW87MWcuILWNfPgHyTkOOfwZ6+Cq3rfkjPKORdAncatusS5I33QGFv1veh+VugxdLyKbZnBLbvTtHtq41WmHpDVpJ2K8GR1m3fK7iVgzza3iOAlj11UCzsoAvSdWVFrqKgPTcOeTN3Gps1inRdAkUDyiun6AJgOqF3HktPfiXC+FrBtmBPDYK8ORJk6i2W+Cb52g1c2lgzIPbUPwJTr8X2gRBPLeDm/H9iyv92Rm9FcxdEyRqHvfw47JnrKx816Ca0znshJ87DnhnOejTSdRGwktAaO9IlhAceVWRJvPOPoNActPZ+fK1gONU7llNDO90THGj5oeho+A4MRZ7tW6jAyUaX/y3OH61qiLaDgouySgYrjfnVwahBCOg9JyCaumCNvJ/R1p4bI3viS+hdx4C6VnBbrfMbwnz8JzDu+R2Yj/01tI70Ug4lO+wlCs3lHJfWhV+SPXFu/bDR7yJanC1dwTtqoHUOKM1oL9zecf+rv/15sW/3s6h1rD/iDa0amjDLcFeu4bmNmeAHmYdr2jZFYNvH+ag00hSsqoVx+DSsobfYnyF9/8NKuhz5MF062HMSYuL8ykWipimtuqtW1bC8fobk5EWQLaH3niRj4PeE7b5Ctn9KzXew32E3dkGL+Ai6QzlrWnOPWFmaMX2F1/OAoj4IswaiuYe0jgHovafWEHOeWI7W+wDIOw475AWMKuh7DkPrum+pnYDWdkhpQ5an7d6X/QD8k8TfzXz4xzmfonRdJgpMQdS1pE00Z0/9LlAsAGvoDdV/vfv+jBrcQjjU+udil7OPeIbcH72uaoqXZ8mZTA69AXVV+9BYcxQL4cvwRQc37VBzrbI3dB67a49TW/2jqp/8zGXgdvbseLGI+mDP3yGtpXdplYPQoHWfENrsCLF/oO9/mNfXkO0dh3HiWWitB9dU+kDNmNoLk6x90p0c+5isq+9A3/+Qyi3I0Y9WpljtuVFlHykeAkKedFhnVvFDB9ADOfIByfFPAMOEaDnIBFCmkfyTkENvwL59gYz7vg/R2CEQX4Qc+0j5Y6KhA6KuFRTxwXIPQQt5iV+m+jrVjRBV9crXQf9TWd+fr2EHnzWkqGvNevnsQCvSJaKwQx41x0OxoPptz41BGA5QWx8E+DsUhz313xQNVYconJhAODmFpAypR+rQ61Dr6EZNVRdrJVFjtlMgdq0MITzX73gwFzqHtvpH1RGt/Qjk6NnSMsgsMREBvwNGhtHTuu+H9eV/88sheeN9aO1Hoe9bHfHLECuVPmnIO/8HrecEjFN/ptqmPn+JaG4U5pPPC35x5HNRKhmB2HME5oPPrcizhs+SHP4t9MOnYdz7dNZ97Nlhsi7+CqnB1+A4/VM1Upi0PHLUUo2mbnWNdfVtsr56GVpt89IXMaDtvSdNsskLpPecFNmO7nLBSW4I9uf6vgWjsUOw+U0lohB1u2Ge/mnJut4x7UJjMo6Ww8/klVHn7E0XT5WpBMMfvcY/1FQzILTGdgjdAJWakLRTgEz3K8PoanuPClbzyTM/Y/8A+j3fLk6gtCAMMyP0Ew2dK59Fc7dgJ1yYztU+zN8h1kz6ocdykma5P+Y3/woITkOOvK/CGuGohfnIX6yQhqGu101INzvE6dGktR0SbKa4vjYLxJQR69SkiLSW4z/r25R8NoubgXRfgX3zi4Kpj8XYLRCVL9PM67LCSyUYwlED9T1KxXKpaa6aY/2eJ1XOQus9CW3NyykEvfs4UpdfhdZ7irTWPqEfeGTd64jrXqN+NQdiDb6e3+jKlDJ/bOLYNCkz17A3W762PAZWT+l9j0G++zPY01dI6/jGygkhWGcWsPObiNpzwXZf5SQrrGtnQGE21yM8YIiDEq172TcD19jQ9OJZ2GUkjiWjqthdQRGHyc9msgSwJtTM3MQRjV3CPP0T4t/FytP7nxLSO6bMhXHiWdL2rL9c1eYqe90EJUJAslCtCkGra4PY3VNQHmsXNq0ytFpuoPWcEFrHAMnbX0HrSPtjCoIr+ym/refjZYqeraG3iBOs0jsKS6RgV3Fu7DrEpXGIyQ+g9X+brH39iNjsj3yBQHS4vDPpsLkCMf3BcKrAo1TpwqxWqx6UqJwNNkCaZZgn/gjWxf9Ro8rQDFpyqPN3QgAaLys9/oOi70Xe8bzf2XzoR8q3kaOfZBw3+r+L1OXXOHm1eq1mLK2PLkCcTWRZl2FdO0Opz1+EtTgFb4eB4G4HUqYAacuxxh0g8jKSM81IIJReLrOJmuR8SMlFdpSpyqxKv/jlgbNR1DZBazuQjtDK1Tn2A4xj31cmwxp8jSOTwvNfnELasJNWwJndtVeIupasBtq+U0JU13NyU5kn1Sn2taxk+icX2AE0HNgMyO8meeMDUHAa8Wpg6oAJT7eJhXYDvj06fHuWfjfEEZbTSMnQlpCGwWUdSrbugFiTQtkYBLSWA1tTVsEOq3n/H4JC85C3zhVu66wDhZdU6BZDNPVATl0GJdIrF4VzFygZBSUjOdvzOVbrm4KedqalmX7Eat3btu5yk2OqhbVoqQNC01XuauUjygyORLQ9h2D7Ci+U53CZi4vyzWSvBYfzm+mTsf9BIB5Se7/wQxT1rUK07FORY9a9/FNEnhEVem8GYlebkN/5Ma48fQiXHq9BrD7fo+b4js9tHas4vBfQlyLJ0u4j6vdy8LPFhVxWUuULCoEdaNF6UGWU5cR5yjf9kPrsRbKG391Ud0Rrn2DnmrPSy46nvu8hVSpAvkm6uxKAE5d6+wA2i5ragwIOJ6Qh8mobU69Hc+1xNNbcgyqjhVdqotzQtSoIoafD/BIK1tknNPqfgqhfdQUM5SgVjeW2mcyVkxeJU/Iq1R9wq1JDY+B7ea5dhXnyj0Xqy/8ia/B1nqEnre0gRG0LkOLM9G1VIsEawjj+g7wy8nbxLui9p9IF20sN9K77YLuvIPXVy5zoI84229NDkK5BGEef4imPTEklKoRqsx2L8XGVUsjVWd5x61DbX0LXTBVR3V54BZFkebc1MeCE02wVdnKCVAZ8Q/pbqIhVP/hopkx971Fo9a3rXq7C3bqW1YnE5p50QmlpvkVyvYpnVI1o/eAjnDzMeNSiuZsd6Cy55oM/FHL0A5Luq5Bj7vRyU3bkNF1lmvUDD/P+LGlZDqfag65gP5u6c5oZNo08HyeWsstqV6n7/4Dk2MfgHEs60rDVyNIPP5HtZPOcl7MeG0Vb/SOYD38Ji7JTDqwF6qt60VTTn74fqdw4yg09teR0xwJLa6SKvwe/Y73v8Yx8kzpu+6dJNLavn7ALzlLOxNvy+fC8YjNnh0VjZ/b8T3ieckU9GW0CbmKHldP9oiUd9mW1WZwljqBQRrC5Ii4daevbEkdjyP1PNB18766MsEC9cz+Odf4tdjkPq/tOB9+ja9M/h7Xe1icbAPs1XdYAjvb9A2joLJKf/Csgiyye52qInpNwPPk858gy98cphjRKRgHSqPN1LRwOFzy/7j0aO9c1nOUmjZLZ3LMhg71RHOv8O16MTZ7wZ2o/HHaGG6oP42j78yukYcRTc7DLHJILSXAkdVBgDsnzLxXv4/CUC+/E9cBzWaRhVLY52SYc6/p7MR/+ijyhT1BlNIMLvGoc2Zq53PXJhgSqghFY4/+2NLNdhHw1T9cN88EfwTj8rZxjqkKcbURL3QOipe6BvOcdRpPye8oxM74MLUUwXaOwvYki141rKtFnnnoO+n2/n1cRV4jzNYLTbIGuVasirHLBkSSYkRhXdhXRuE7VkhsP/Cn0vsIT1RXifA22QPFHhhC35lXhlYooywTe2qYuKOFI0PpaprEb+tHfhX7kSWh7V/2ufKgQZwfhDpwlztvwrqLp+SS7rCUVRoqwyy/V77wwnTD6noBx8hku5Cs6RqgQZ4fgDZ2nUc8LvLP6lshnbcOkqQ/I1Z3aVEmCCZjVqp5aa78X+pEnYBzK7QAXQoU4O7j1iRAaZ3TLKJUziFLVAFRFLLR5IqhOCogaJ8D/gUdNU7quu/2ocoC1ztUVKhuFqPzvMTsDX2SIuKyznOCiLZuSINuGM5xEvScM3SK1KoWL+7WGvRBNuVIAG8f/A9+19G8LMaEaAAAAAElFTkSuQmCC";
    window.currentBrandLogoDataUrl = nutDataUrl;

    const chkEnabled = document.getElementById('cfgBrandEnabled');
    const inputName = document.getElementById('cfgBrandName');
    const inputColor = document.getElementById('cfgBrandPrimaryColor');
    const hexSpan = document.getElementById('cfgBrandColorHex');
    const previewImg = document.getElementById('cfgBrandLogoPreviewImg');
    const noLogoText = document.getElementById('cfgBrandNoLogoText');

    if (chkEnabled) chkEnabled.checked = true;
    if (inputName) inputName.value = 'Mister Nut';
    if (inputColor) inputColor.value = '#e67e22';
    if (hexSpan) hexSpan.textContent = '#e67e22';
    if (previewImg) {
        previewImg.src = nutDataUrl;
        previewImg.style.display = 'block';
    }
    if (noLogoText) noLogoText.style.display = 'none';

    const btnQuitar = document.getElementById('btnQuitarLogo');
    const dropStatus = document.getElementById('dropzoneStatusText');
    if (btnQuitar) btnQuitar.style.display = 'inline-flex';
    if (dropStatus) dropStatus.style.display = 'block';

    actualizarEstadoBrandingForm();
    actualizarPreviewBranding();
    cambiarColorPrimarioBranding('#e67e22');

    showToast("Demo de Mister Nut cargada. Hacé clic en 'Guardar Cambios' para conservarla.", "info");
}

function quitarLogoBranding() {
    window.currentBrandLogoDataUrl = '';
    const fileInput = document.getElementById('brandFileInput');
    if (fileInput) fileInput.value = '';

    const previewImg = document.getElementById('cfgBrandLogoPreviewImg');
    const noLogoText = document.getElementById('cfgBrandNoLogoText');
    if (previewImg) {
        previewImg.src = '';
        previewImg.style.display = 'none';
    }
    if (noLogoText) noLogoText.style.display = 'block';

    const btnQuitar = document.getElementById('btnQuitarLogo');
    if (btnQuitar) btnQuitar.style.display = 'none';

    const dropStatus = document.getElementById('dropzoneStatusText');
    if (dropStatus) dropStatus.style.display = 'none';

    actualizarPreviewBranding();
    showToast("Logo eliminado del formulario. Hacé clic en 'Guardar Cambios' para confirmar.", "info");
}

function restaurarBrandingOriginal() {
    const chkEnabled = document.getElementById('cfgBrandEnabled');
    if (chkEnabled) chkEnabled.checked = false;

    window.currentBrandLogoDataUrl = '';
    const fileInput = document.getElementById('brandFileInput');
    if (fileInput) fileInput.value = '';

    const previewImg = document.getElementById('cfgBrandLogoPreviewImg');
    const noLogoText = document.getElementById('cfgBrandNoLogoText');
    if (previewImg) {
        previewImg.src = '';
        previewImg.style.display = 'none';
    }
    if (noLogoText) noLogoText.style.display = 'block';

    const btnQuitar = document.getElementById('btnQuitarLogo');
    const dropStatus = document.getElementById('dropzoneStatusText');
    if (btnQuitar) btnQuitar.style.display = 'none';
    if (dropStatus) dropStatus.style.display = 'none';

    const inputColor = document.getElementById('cfgBrandPrimaryColor');
    const hexSpan = document.getElementById('cfgBrandColorHex');
    if (inputColor) inputColor.value = '#f5a623';
    if (hexSpan) hexSpan.textContent = '#f5a623';

    actualizarEstadoBrandingForm();
    actualizarPreviewBranding();

    aplicarBrandingUI({ brand_enabled: false });
    showToast("Restaurado a EnvioBot Full original.", "info");
}

function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;

    if (max === min) {
        h = s = 0;
    } else {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        switch (max) {
            case r: h = (g - b) / d + (g < b ? 6 : 0); break;
            case g: h = (b - r) / d + 2; break;
            case b: h = (r - g) / d + 4; break;
        }
        h /= 6;
    }
    return { h, s, l };
}

function rgbToHex(r, g, b) {
    return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}

// Exponer funciones globales
window.inicializarBranding = inicializarBranding;
window.aplicarBrandingUI = aplicarBrandingUI;
window.cargarBrandingEnFormulario = cargarBrandingEnFormulario;
window.actualizarEstadoBrandingForm = actualizarEstadoBrandingForm;
window.actualizarPreviewBranding = actualizarPreviewBranding;
window.manejarSeleccionLogo = manejarSeleccionLogo;
window.procesarArchivoLogo = procesarArchivoLogo;
window.cambiarColorPrimarioBranding = cambiarColorPrimarioBranding;
window.cargarDemoMisterNut = cargarDemoMisterNut;
window.quitarLogoBranding = quitarLogoBranding;
window.restaurarBrandingOriginal = restaurarBrandingOriginal;

// =====================================================================
// MÓDULO: MONITOR LOGÍSTICO DE MEGA-EVENTOS Y CALENDARIO FULL
// =====================================================================

async function cargarMonitorEventosLogisticos() {
    const banner = document.getElementById('logisticEventBanner');
    if (!banner) return;
    const token = getToken();
    if (!token) {
        banner.style.display = 'none';
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/full/logistic-events`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();

        if (data.ok && data.next_event) {
            currentLogisticEvents = data.events || [];
            currentNextLogisticEvent = data.next_event;
            const ev = data.next_event;

            const nameEl = document.getElementById('eventNameText');
            const cutoffEl = document.getElementById('eventCutoffBadge');
            const turnosEl = document.getElementById('eventTurnosBadge');
            const msgEl = document.getElementById('eventMessageText');
            const iconEl = document.getElementById('eventIcon');

            if (nameEl) nameEl.textContent = ev.name;

            const [cYear, cMonth, cDay] = ev.inbound_cutoff_date.split('-');
            const meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
            const cutoffTexto = `${parseInt(cDay, 10)} de ${meses[parseInt(cMonth, 10) - 1] || cMonth}`;

            if (cutoffEl) {
                if (ev.days_to_cutoff <= 0) {
                    cutoffEl.textContent = `Corte Full: CERRADO (${cutoffTexto})`;
                    cutoffEl.style.background = 'rgba(239, 68, 68, 0.25)';
                    cutoffEl.style.color = '#fca5a5';
                } else {
                    cutoffEl.textContent = `Corte Full: ${cutoffTexto} (Faltan ${ev.days_to_cutoff} días)`;
                }
            }

            if (turnosEl) {
                turnosEl.innerHTML = `${iconoSvg('alerta', 12)}Turnos en Celina: demora de ${escapeHtml(ev.typical_turnos_delay_days)} días`;
            }

            if (msgEl) {
                if (ev.days_to_cutoff <= 0) {
                    msgEl.innerHTML = `El período de ingresos a Villa Celina para <strong>${escapeHtml(ev.name)}</strong> ya finalizó. Full opera en <em>Dock Freeze</em> para expedición.`;
                } else if (ev.safe_booking_days_left <= 0) {
                    msgEl.innerHTML = `${iconoSvg('alerta')}<strong>¡Atención crítica!</strong> La demora actual de turnos (${escapeHtml(ev.typical_turnos_delay_days)}d) ya supera los días hasta el corte (${escapeHtml(ev.days_to_cutoff)}d). Si sacás turno hoy, podrías ingresar después de la fecha límite.`;
                } else {
                    msgEl.innerHTML = `Corte de ingresos a Villa Celina el <strong>${cutoffTexto}</strong>. Con turnos a ${ev.typical_turnos_delay_days} días, <strong>te quedan solo ${ev.safe_booking_days_left} días de margen para sacar turno</strong> antes de que se agoten los slots pre-evento.`;
                }
            }

            if (iconEl) {
                iconEl.innerHTML = iconoSvg(ev.is_booking_urgent ? 'campana' : 'calendario', 18).replace('margin-right: 4px;', '');
            }

            // Botón dinámico de buffer
            const pctBuffer = Math.round((ev.demand_multiplier - 1) * 100);
            const btnBuffer = banner.querySelector('button[onclick*="abrirColectaConModoEvento"]');
            if (btnBuffer) {
                const shortName = ev.name.includes('Cyber') ? 'Cyber' : (ev.name.includes('Black') ? 'Black Friday' : 'Evento');
                btnBuffer.innerHTML = `${iconoSvg('paquete')}Planificar para ${escapeHtml(shortName)} (+${escapeHtml(pctBuffer)}%)`;
            }

            banner.style.display = 'flex';
        } else {
            banner.style.display = 'none';
        }
    } catch (err) {
        console.warn("Error cargando eventos logísticos:", err);
        banner.style.display = 'none';
    }
}

function abrirModalCalendarioEventos() {
    const modal = document.getElementById('modalCalendarioEventos');
    if (!modal) return;
    
    const delayInput = document.getElementById('inputTurnosDelayModal');
    if (delayInput && currentNextLogisticEvent) {
        delayInput.value = currentNextLogisticEvent.typical_turnos_delay_days || 7;
    }

    renderizarListaEventosModal(currentLogisticEvents);
    modal.style.display = 'flex';
}

function cerrarModalCalendarioEventos() {
    const modal = document.getElementById('modalCalendarioEventos');
    if (modal) modal.style.display = 'none';
}

async function guardarDemoraTurnosModal() {
    const delayInput = document.getElementById('inputTurnosDelayModal');
    if (!delayInput || !currentNextLogisticEvent) return;

    const delay = parseInt(delayInput.value, 10);
    if (isNaN(delay) || delay < 1) {
        showToast("Ingresá una cantidad de días válida.", "warning");
        return;
    }

    const token = getToken();
    try {
        const res = await fetch(`${API_BASE}/full/logistic-events/${currentNextLogisticEvent.id}/turnos-delay`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ delay_days: delay })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`Demora de turnos en Celina actualizada a ${delay} días.`, "success");
            await cargarMonitorEventosLogisticos();
            renderizarListaEventosModal(currentLogisticEvents);
        } else {
            showToast("No se pudo actualizar la demora: " + (data.error || "error"), "error");
        }
    } catch (err) {
        console.error("Error actualizando demora de turnos:", err);
        showToast("Error de conexión al guardar demora.", "error");
    }
}

function renderizarListaEventosModal(events) {
    const container = document.getElementById('listaEventosLogisticosContainer');
    if (!container) return;

    if (!events || events.length === 0) {
        container.innerHTML = `
            <div style="padding: 24px; text-align: center; color: var(--text2); font-size: 13px;">
                No hay eventos logísticos configurados en este momento.
            </div>
        `;
        return;
    }

    const meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
    const fmt = (dStr) => {
        if (!dStr) return '—';
        const [y, m, d] = dStr.split('-');
        return `${parseInt(d, 10)} ${meses[parseInt(m, 10) - 1] || m} ${y}`;
    };

    container.innerHTML = events.map(ev => {
        const pctBuffer = Math.round((ev.demand_multiplier - 1) * 100);
        const isUrgent = ev.is_booking_urgent;
        const borderColor = isUrgent ? 'rgba(239, 68, 68, 0.4)' : 'var(--border)';

        let statusText = 'Próximo';
        let statusColor = '#3b82f6';
        if (ev.status === 'inbound_warning') {
            statusText = `${iconoSvg('alerta', 12)}Ventana de Ingreso Crítica`;
            statusColor = '#f59e0b';
        } else if (ev.status === 'inbound_locked') {
            statusText = `${iconoSvg('candado', 12)}Dock Freeze (Ingreso Cerrado)`;
            statusColor = '#ef4444';
        } else if (ev.status === 'event_active') {
            statusText = `${iconoSvg('llama', 12)}Evento en Curso`;
            statusColor = '#10b981';
        }

        return `
            <div style="background: var(--surface); border: 1.5px solid ${borderColor}; border-radius: 8px; padding: 14px 16px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;">
                    <div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <strong style="font-size: 15px; color: var(--text);">${ev.name}</strong>
                            <span style="font-size: 11px; font-weight: 700; color: ${statusColor}; background: rgba(0,0,0,0.2); padding: 2px 7px; border-radius: 4px; border: 1px solid ${statusColor};">
                                ${statusText}
                            </span>
                        </div>
                        <div style="font-size: 12px; color: var(--text2); margin-top: 3px;">
                            Fecha del evento: <strong>${fmt(ev.event_start)} al ${fmt(ev.event_end)}</strong>
                        </div>
                    </div>
                    <button type="button" class="btn btn-sm" onclick="cerrarModalCalendarioEventos(); abrirColectaConModoEvento(${ev.demand_multiplier}, '${ev.name}');" style="background: var(--accent); color: #111; font-weight: 800; font-size: 11.5px; padding: 5px 12px;">
                        Planificar con +${pctBuffer}%
                    </button>
                </div>

                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; background: var(--surf2); border-radius: 6px; padding: 10px 12px; margin-top: 8px; font-size: 12px;">
                    <div>
                        <div style="color: var(--text2); font-size: 11px;">Corte de Ingreso Full:</div>
                        <strong style="color: #ff8080;">${fmt(ev.inbound_cutoff_date)}</strong>
                        <div style="font-size: 11px; color: var(--text2);">Faltan: <strong>${ev.days_to_cutoff} días</strong></div>
                    </div>
                    <div>
                        <div style="color: var(--text2); font-size: 11px;">Congelamiento (Dock Freeze):</div>
                        <strong style="color: #f59e0b;">${fmt(ev.dock_freeze_start)}</strong>
                        <div style="font-size: 11px; color: var(--text2);">Muelle cerrado a recepción</div>
                    </div>
                    <div>
                        <div style="color: var(--text2); font-size: 11px;">Margen Seguro para Turno:</div>
                        <strong style="color: ${ev.safe_booking_days_left <= 3 ? '#ff4d4d' : 'var(--good)'};">
                            ${ev.safe_booking_days_left > 0 ? `${ev.safe_booking_days_left} días restantes` : '0 días (Turnos colapsados)'}
                        </strong>
                        <div style="font-size: 11px; color: var(--text2);">Demora en Celina: ${ev.typical_turnos_delay_days}d</div>
                    </div>
                </div>

                <div style="font-size: 11.5px; color: var(--text2); margin-top: 8px; line-height: 1.4;">
                    ${ev.description || ''}
                </div>
            </div>
        `;
    }).join('');
}

function abrirColectaConModoEvento(multiplier = null, eventName = null) {
    if (!multiplier && currentNextLogisticEvent) {
        multiplier = currentNextLogisticEvent.demand_multiplier || 1.5;
    }
    if (!eventName && currentNextLogisticEvent) {
        eventName = currentNextLogisticEvent.name || 'Evento Comercial';
    }
    if (!multiplier) multiplier = 1.5;
    if (!eventName) eventName = 'Mega-Evento';

    activeColectaMultiplier = multiplier;
    activeColectaEventName = eventName;

    abrirModalColecta(null, { multiplier: activeColectaMultiplier, eventName: activeColectaEventName, keepMultiplier: true });

    const pct = Math.round((multiplier - 1) * 100);
    showToast(`Modo ${eventName} activado (+${pct}% demanda buffer)`, "info");
}

window.cargarMonitorEventosLogisticos = cargarMonitorEventosLogisticos;
window.abrirModalCalendarioEventos = abrirModalCalendarioEventos;
window.cerrarModalCalendarioEventos = cerrarModalCalendarioEventos;
window.guardarDemoraTurnosModal = guardarDemoraTurnosModal;
window.abrirColectaConModoEvento = abrirColectaConModoEvento;
window.quitarModoEventoColecta = quitarModoEventoColecta;



