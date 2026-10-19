// EnvioBot Full - versión para teléfono. Usa la misma API que el panel de escritorio.
// Reparte los productos igual que el panel (clasificarItemsPanel en app.js): urgentes, conviene mandar,
// tranquilos, stock suficiente y pausados en ML.
(function () {
    'use strict';

    const API = '/api/full';
    const TOKEN_KEY = 'enviobot_full_token';
    const NF = new Intl.NumberFormat('es-AR');
    const UMBRAL_EXCEDENTE_ML_DIAS = 60;  // más allá, ML podría cobrar almacenamiento (estimación nuestra)

    const GRUPOS = [
        { id: 'urgentes',   nombre: 'Urgentes',          corto: 'Urgentes',   color: 'var(--crit)' },
        { id: 'pronto',     nombre: 'Conviene mandar',   corto: 'Mandar pronto', color: 'var(--warn)' },
        { id: 'tranquilos', nombre: 'Tranquilos',        corto: 'Tranquilos', color: 'var(--ok)' },
        { id: 'deMas',      nombre: 'Stock suficiente',  corto: 'Stock suficiente', color: 'var(--exceso)' },
        { id: 'pausados',   nombre: 'Pausados en ML',    corto: 'Pausados',   color: 'var(--pausa)' }
    ];
    const GRUPO = {}; GRUPOS.forEach(g => { GRUPO[g.id] = g; });
    const GALPON = [
        { id: 'to_buy',  nombre: 'A comprar',     color: 'var(--crit)' },
        { id: 'packing', nombre: 'Envasando',     color: 'var(--warn)' },
        { id: 'boxed',   nombre: 'Listo en caja', color: 'var(--ok)' }
    ];
    const PALETA = ['#f5a623', '#5b9bff', '#34d399', '#b58cff', '#ff7aa8', '#8f94a3'];

    const estado = { tab: 'resumen', filtro: 'todos', busqueda: '', items: [], colectas: [], avisos: [], user: null,
        cargando: true, error: null, cargadoEn: Date.now() };
    const $ = (id) => document.getElementById(id);

    function esc(v) {
        return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function token() {
        try { return localStorage.getItem(TOKEN_KEY) || localStorage.getItem('token') || ''; } catch (e) { return ''; }
    }
    function irALogin() { window.location.href = 'login.html'; }
    function aviso(msg) {
        const t = $('toast'); t.textContent = msg; t.classList.add('visible');
        clearTimeout(aviso._t); aviso._t = setTimeout(() => t.classList.remove('visible'), 2600);
    }
    async function api(ruta, opciones) {
        const res = await fetch(API + ruta, Object.assign({ headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' } }, opciones || {}));
        if (res.status === 401 || res.status === 422) { irALogin(); throw new Error('sesion'); }
        return { status: res.status, data: await res.json() };
    }
    function icono(path, cls) {
        return `<svg class="${cls || 'ico'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
    }
    const ICO_ALERTA = '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>';
    const ICO_COPIAR = '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>';
    const ICO_LINK = '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>';

    // ── Tortas SVG ──────────────────────────────────────────────────────────────
    // segs: [{valor, color, id?}]. Cada arco usa pathLength=100, así el largo es un porcentaje.
    function torta(clase, segs, centroNum, centroCap, grosor, opts) {
        opts = opts || {};
        const r = 50 - grosor / 2 - 2;
        const total = segs.reduce((a, s) => a + s.valor, 0);
        const HUECO = segs.filter(s => s.valor > 0).length > 1 ? 1.6 : 0;
        let acumulado = 0;
        let arcos = `<circle class="pista" cx="50" cy="50" r="${r}" stroke-width="${grosor}"/>`;
        if (total > 0) {
            segs.forEach((s) => {
                if (!(s.valor > 0)) return;
                const largo = s.valor / total * 100;
                const dibujo = Math.max(0.1, largo - HUECO);
                const inicio = acumulado;
                acumulado += largo;
                arcos += `<circle class="arco${s.id ? ' tocable' : ''}" data-largo="${dibujo.toFixed(2)}" ${s.id ? `data-seg="${esc(s.id)}"` : ''} cx="50" cy="50" r="${r}" pathLength="100" stroke="${s.color}" style="--glow:${s.color}" stroke-width="${grosor}" stroke-dasharray="0 100" stroke-dashoffset="${(-inicio).toFixed(2)}"/>`;
            });
        }
        return `<div class="torta ${clase}" ${opts.id ? `id="${opts.id}"` : ''}><svg viewBox="0 0 100 100" aria-hidden="true">${arcos}</svg>` +
            `<div class="centro"><div class="num"${opts.colorNum ? ` style="color:${opts.colorNum}"` : ''}>${centroNum}</div><div class="cap">${centroCap}</div></div></div>`;
    }
    // Anima: arranca en 0 y crece hasta el largo real.
    function animarTortas(raiz) {
        const arcos = (raiz || document).querySelectorAll('.arco[data-largo]');
        requestAnimationFrame(() => requestAnimationFrame(() => {
            arcos.forEach(a => { a.setAttribute('stroke-dasharray', `${a.dataset.largo} 100`); });
        }));
    }

    // ── Datos derivados ─────────────────────────────────────────────────────────
    function adaptar(raw) {
        const enProceso = raw.in_process_stock !== undefined ? raw.in_process_stock : (raw.not_available_stock_full || 0);
        return {
            id: raw.id, item_id: raw.item_id, sku: raw.sku || '', title: raw.title || '', variation_name: raw.variation_name || '',
            inventory_id: raw.inventory_id || '', permalink: raw.permalink, account_nickname: raw.account_nickname || '',
            channels: raw.channels || [], status: raw.status || 'ok', pausado: !!raw.pausado, canales_pausados: raw.canales_pausados || 0,
            stock: raw.current_stock_full || 0, no_disponible: raw.not_available_stock_full || 0,
            en_proceso: enProceso, en_prep: raw.in_preparation_stock || 0, en_camino: raw.in_transit_stock || 0,
            entrante: raw.total_incoming || 0,
            vpd: raw.vpd_weighted || 0, ventas30: raw.sales_last_30d || 0,
            dias: raw.days_left !== undefined ? raw.days_left : 999, dias_cubiertos: raw.covered_days_left !== undefined ? raw.covered_days_left : null,
            objetivo: raw.target_coverage_days || 30, quiebre: raw.stockout_date || null,
            sugerido: raw.sugerido_al_ingreso || 0, sobrestock: !!raw.sobrestock, prep_status: raw.prep_status || null
        };
    }
    // Igual que clasificarItemsPanel del panel de escritorio.
    function grupoDe(it) {
        if (it.pausado) return 'pausados';
        const cubierto = it.entrante > 0;
        if (it.sobrestock) return 'deMas';
        if (!cubierto && (it.status === 'critical' || it.status === 'out_of_stock')) return 'urgentes';
        if (!cubierto && it.status === 'warning') return 'pronto';
        return 'tranquilos';
    }
    function conteos() {
        const c = { urgentes: 0, pronto: 0, tranquilos: 0, deMas: 0, pausados: 0 };
        estado.items.forEach(it => { c[grupoDe(it)]++; });
        return c;
    }
    // Venta por día realista: nunca menos que el promedio de los últimos 30 días.
    function vpdReal(it) { return Math.max(it.vpd, it.ventas30 / 30); }
    function diasReales(it) {
        const v = vpdReal(it);
        return v > 0 ? (it.stock + it.en_proceso + it.en_camino + it.en_prep) / v : null;
    }
    function ringDias(it) {
        const obj = it.objetivo;
        const g = grupoDe(it);
        const d = g === 'deMas' || g === 'tranquilos' && it.entrante > 0 ? diasReales(it) : (it.vpd > 0 ? it.dias : null);
        if (d === null || d === undefined) return { frac: 1, texto: '–' };
        return { frac: Math.max(0.04, Math.min(1, d / obj)), texto: d >= 100 ? '99+' : String(Math.round(d)) };
    }
    // Producto que hoy no alcanza con lo que hay en Full, pero que lo que ya viaja en colectas cubre.
    function cubiertoPorColecta(it) {
        const g = grupoDe(it);
        return (g === 'deMas' || g === 'tranquilos') && it.entrante > 0 && vpdReal(it) > 0 && it.stock / vpdReal(it) < it.objetivo;
    }
    // Rótulo y color de cada producto: el grupo, salvo que lo cubra una colecta.
    function etiquetaItem(it) {
        if (cubiertoPorColecta(it)) return { corto: 'Cubierto por colecta', nombre: 'Cubierto por colecta', color: 'var(--camino)' };
        return GRUPO[grupoDe(it)];
    }

    function segundosA(s) {
        const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
        if (d > 0) return `${d}d ${h}h`;
        if (h > 0) return `${h}h ${m}m`;
        return `${m} min`;
    }
    function restaDe(col) { return Math.floor((Date.parse(col.limite_edicion) - Date.now()) / 1000); }
    function fechaCorta(iso) {
        if (!iso) return '';
        const d = new Date(iso + (iso.length <= 10 ? 'T12:00:00' : ''));
        return d.toLocaleDateString('es-AR', { weekday: 'short', day: '2-digit', month: '2-digit' });
    }
    function horaDe(iso) {
        return new Date(iso).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/Argentina/Buenos_Aires' });
    }
    function nombreCorto(it) {
        const t = (it.title || it.sku || 'Producto').trim();
        return t.length > 22 ? t.slice(0, 21) + '…' : t;
    }
    function tituloItem(it) { return it.title + (it.variation_name ? ` (${it.variation_name})` : ''); }

    // ── Colecta: una torta de cuenta regresiva por colecta ─────────────────────
    function tortaColecta(col, clase, id) {
        const resta = restaDe(col);
        const SEMANA = 7 * 86400;
        if (col.estado === 'in_transit') {
            return { html: torta(clase, [{ valor: 100, color: 'var(--camino)' }], 'En camino', 'a Full', 11, { id, colorNum: 'var(--camino)' }), modo: 'camino' };
        }
        if (!col.abierta || resta <= 0) {
            return { html: torta(clase, [{ valor: 100, color: 'var(--crit)' }], 'Cerrada', 'edición', 11, { id, colorNum: 'var(--crit)' }), modo: 'cerrada' };
        }
        const t = segundosA(resta);
        const color = resta < 86400 ? 'var(--crit)' : (resta < 2 * 86400 ? 'var(--warn)' : 'var(--ok)');
        const frac = Math.max(0.03, Math.min(1, resta / SEMANA));
        return { html: torta(clase, [{ valor: frac * 100, color }, { valor: (1 - frac) * 100, color: 'transparent' }],
            `<span class="cuentaNum" data-lim="${esc(col.limite_edicion)}" style="font-size:${t.length > 6 ? 22 : 26}px">${t}</span>`, 'para el límite', 11, { id }), modo: 'abierta' };
    }
    function textoColecta(col, modo) {
        const lineas = [];
        if (modo === 'camino') lineas.push(`<b>En camino a Full</b><span>Ingreso estimado: ${esc(fechaCorta(col.fecha_ingreso))}</span>`);
        else if (modo === 'cerrada') lineas.push(`<b>Edición cerrada</b><span>Mercado Libre ya no admite cambios.</span>`);
        else lineas.push(`<b>Podés editarla hasta</b><span>${esc(fechaCorta(col.limite_edicion))} a las ${esc(horaDe(col.limite_edicion))}</span>`);
        lineas.push(`<span>Retiro: ${esc(fechaCorta(col.fecha_retiro))} · Ingreso: ${esc(fechaCorta(col.fecha_ingreso))}</span>`);
        lineas.push(`<span>${NF.format(col.total_unidades || 0)} unid.${col.codigo ? ' · ' + esc(col.codigo) : ''}</span>`);
        return lineas.join('');
    }
    function proximaColecta() {
        const vigentes = estado.colectas.filter(c => c.estado === 'scheduled');
        return vigentes.find(c => c.abierta) || vigentes[0] || estado.colectas[0] || null;
    }

    // ── Vistas ──────────────────────────────────────────────────────────────────
    function vistaResumen() {
        const c = conteos();
        const total = estado.items.length;
        const activos = total - c.pausados;
        const accion = c.urgentes + c.pronto;
        const segs = GRUPOS.map(g => ({ valor: c[g.id], color: g.color, id: g.id }));
        const saludo = accion > 0 ? `${accion} ${accion === 1 ? 'producto necesita' : 'productos necesitan'} atención` : 'Todo el stock está bajo control';
        const hero = `<section class="card hero">
            <div class="saludo">${saludo}</div>
            ${torta('grande', segs, NF.format(total), total === 1 ? 'artículo en Full' : 'artículos en Full', 13, { id: 'tortaHero' })}
            <div class="leyenda">${GRUPOS.map(g => `<button class="ley" data-filtro="${g.id}" style="--c:${g.color}"><i></i><div><b>${c[g.id]}</b><br><span>${g.nombre}</span></div></button>`).join('')}</div>
            ${c.pausados ? `<div class="nota-hero">${activos} activos y ${c.pausados} pausados en Mercado Libre</div>` : ''}
        </section>`;

        const col = proximaColecta();
        let cardColecta;
        if (col) {
            const tc = tortaColecta(col, 'media', 'tortaCuenta');
            cardColecta = `<section class="card"><h2>${estado.colectas.length > 1 ? 'Próxima colecta' : 'Colecta'} <a href="#" data-ir="colecta">Ver${estado.colectas.length > 1 ? ' todas' : ''}</a></h2><div class="colecta-top">${tc.html}<div class="txt">${textoColecta(col, tc.modo)}</div></div></section>`;
        } else {
            cardColecta = `<section class="card"><h2>Colecta</h2><div class="sin-datos">No hay una colecta en preparación.<br>Armala desde el panel y acá vas a ver la cuenta regresiva.</div></section>`;
        }

        // Quién vende más (participación en la velocidad de venta). Los pausados no venden.
        const conVentas = estado.items.filter(it => !it.pausado && it.vpd > 0).sort((a, b) => b.vpd - a.vpd);
        let cardVentas = '';
        if (conVentas.length) {
            const top = conVentas.slice(0, 5);
            const resto = conVentas.slice(5).reduce((a, it) => a + it.vpd, 0);
            const partes = top.map((it, i) => ({ nombre: nombreCorto(it), valor: it.vpd, color: PALETA[i] }));
            if (resto > 0) partes.push({ nombre: 'Otros', valor: resto, color: PALETA[5] });
            const totalVpd = partes.reduce((a, p) => a + p.valor, 0);
            cardVentas = `<section class="card"><h2>Quién vende más</h2><div class="fila-torta">
                ${torta('media', partes, NF.format(Math.round(totalVpd)), 'unid. por día', 14)}
                <div class="lista">${partes.map(p => `<div class="lin" style="--c:${p.color}"><i></i><span class="n">${esc(p.nombre)}</span><span class="v">${Math.round(p.valor / totalVpd * 100)}%</span></div>`).join('')}</div>
            </div></section>`;
        }

        const urgentes = estado.items.filter(it => grupoDe(it) === 'urgentes').slice(0, 3);
        const cardUrg = urgentes.length ? `<section class="card"><h2>Hay que reponer ya <a href="#" data-filtro="urgentes">Ver todos</a></h2><div class="apilado">${urgentes.map(filaProducto).join('')}</div></section>` : '';

        return hero + cardColecta + cardVentas + cardUrg;
    }

    function subTexto(it) {
        const g = grupoDe(it);
        if (g === 'pausados') return `${NF.format(it.stock)} en Full · no se vende`;
        if (cubiertoPorColecta(it)) {
            return `${NF.format(it.stock)} en Full + ${NF.format(it.entrante)} en colecta · alcanza ${NF.format(Math.round(diasReales(it)))} días`;
        }
        if (g === 'deMas') {
            const d = diasReales(it);
            return `${NF.format(it.stock)} en Full · ${d === null ? 'sin ventas en 30 días' : 'dura ' + NF.format(Math.round(d)) + ' días'}`;
        }
        return `${NF.format(it.stock)} en Full · ${it.vpd > 0 ? (Math.round(it.vpd * 10) / 10).toLocaleString('es-AR') + '/día' : 'sin ventas'}`;
    }
    function filaProducto(it) {
        const g = etiquetaItem(it);
        const r = ringDias(it);
        const idx = estado.items.indexOf(it);
        const alerta = grupoDe(it) === 'deMas' && (diasReales(it) === null || diasReales(it) > UMBRAL_EXCEDENTE_ML_DIAS);
        return `<button class="prod" data-prod="${idx}">
            ${torta('mini', [{ valor: r.frac * 100, color: g.color }, { valor: (1 - r.frac) * 100, color: 'transparent' }], r.texto, '', 11)}
            <div class="info"><div class="tit">${esc(tituloItem(it))}</div>
            <div class="sub"><span class="etiqueta" style="--c:${g.color}">${esc(g.corto)}</span>${alerta ? icono(ICO_ALERTA, 'ico-chico adv') : ''}${subTexto(it)}</div></div>
        </button>`;
    }

    function listaFiltrada() {
        const q = estado.busqueda.trim().toLowerCase();
        return estado.items.filter(it => (estado.filtro === 'todos' || grupoDe(it) === estado.filtro) &&
            (!q || it.title.toLowerCase().includes(q) || it.sku.toLowerCase().includes(q) || it.item_id.toLowerCase().includes(q)));
    }
    function vistaProductos() {
        const c = conteos();
        const chips = [{ id: 'todos', nombre: 'Todos', n: estado.items.length }].concat(GRUPOS.map(g => ({ id: g.id, nombre: g.corto, n: c[g.id], color: g.color }))).filter(ch => ch.id === 'todos' || ch.n > 0 || ch.id === estado.filtro);
        const lista = listaFiltrada();
        return `<input class="buscador" id="buscador" type="search" placeholder="Buscar por nombre, SKU o MLA" value="${esc(estado.busqueda)}" autocomplete="off">
            <div class="filtros">${chips.map(ch => `<button class="chip${estado.filtro === ch.id ? ' activo' : ''}" data-filtro="${ch.id}" ${ch.color ? `style="--c:${ch.color}"` : ''}>${ch.color ? '<i></i>' : ''}${esc(ch.nombre)} ${ch.n}</button>`).join('')}</div>
            <div class="contador" id="contador">Mostrando ${lista.length} de ${estado.items.length}</div>
            ${estado.filtro === 'deMas' ? '<div class="explica">Los días cuentan el stock que hay hoy en Full más lo que ya viaja en tus colectas. Si dice "Cubierto por colecta", hoy no alcanza solo, pero lo que viene sí: solo falta esperar que entre.</div>' : ''}
            <div id="listaProd" class="apilado">${lista.length ? lista.map(filaProducto).join('') : '<div class="vacio">No hay productos con ese filtro.</div>'}</div>`;
    }

    function tarjetaColecta(col, i) {
        const tc = tortaColecta(col, 'media', 'tortaCol' + i);
        const prods = (col.productos || []);
        return `<section class="card"><div class="colecta-top">${tc.html}<div class="txt">${textoColecta(col, tc.modo)}</div></div>
            ${col.de_ml ? '<div class="nota-col">Cargada desde Mercado Libre</div>' : (col.estado === 'scheduled' ? '<div class="nota-col">Armada en EnvioBot: recordá cargarla en Mercado Libre</div>' : '')}
            ${prods.length ? `<details class="desplegable"><summary>${prods.length} ${prods.length === 1 ? 'producto' : 'productos'}</summary>${prods.map(p => `<div class="lin"><span class="n">${esc(p.titulo || p.sku)}</span><span class="v">${NF.format(p.unidades)}</span></div>`).join('')}</details>` : ''}
        </section>`;
    }
    function vistaColecta() {
        const cols = estado.colectas;
        const cabecera = cols.length ? cols.map(tarjetaColecta).join('')
            : `<section class="card"><h2>Colectas</h2><div class="sin-datos">No hay una colecta vigente.</div></section>`;

        const enPrep = estado.items.filter(it => it.en_prep > 0 && !it.pausado);
        const unidades = { to_buy: 0, packing: 0, boxed: 0 };
        enPrep.forEach(it => { unidades[it.prep_status || 'to_buy'] += it.en_prep; });
        const totalU = unidades.to_buy + unidades.packing + unidades.boxed;
        const galpon = totalU > 0 ? `<section class="card"><h2>Estado del galpón</h2><div class="fila-torta">
            ${torta('media', GALPON.map(g => ({ valor: unidades[g.id], color: g.color })), NF.format(totalU), 'unidades', 14)}
            <div class="lista">${GALPON.map(g => `<div class="lin" style="--c:${g.color}"><i></i><span class="n">${g.nombre}</span><span class="v">${NF.format(unidades[g.id])}</span></div>`).join('')}</div>
        </div></section>` : '';

        const proxima = estado.items.filter(it => ['urgentes', 'pronto'].includes(grupoDe(it)) && it.sugerido > 0).sort((a, b) => b.sugerido - a.sugerido).slice(0, 8);
        const cardProx = proxima.length ? `<section class="card"><h2>Para la próxima colecta</h2><div class="apilado">${proxima.map(it => {
            const g = GRUPO[grupoDe(it)];
            return `<button class="prod" data-prod="${estado.items.indexOf(it)}"><div class="info"><div class="tit">${esc(tituloItem(it))}</div><div class="sub"><span class="etiqueta" style="--c:${g.color}">${esc(g.corto)}</span>Sugerido: <b style="color:var(--text)">${NF.format(it.sugerido)}</b> unid.</div></div></button>`;
        }).join('')}</div></section>` : '';

        const suf = estado.items.filter(it => grupoDe(it) === 'deMas').sort((a, b) => (diasReales(b) || 1e9) - (diasReales(a) || 1e9));
        const cardSuf = suf.length ? `<section class="card"><h2>Artículos con stock suficiente</h2><div class="apilado">${suf.slice(0, 10).map(filaProducto).join('')}</div>
            ${suf.length > 10 ? '<a class="enlace-centro" href="#" data-filtro="deMas">Ver los ' + suf.length + '</a>' : ''}</section>` : '';

        return cabecera + galpon + cardProx + cardSuf;
    }

    function vistaMas() {
        const u = estado.user || {};
        const nuevos = avisosNuevos();
        return `<section class="card"><h2>Cuenta</h2>
            <div class="lin"><span class="n">${esc(u.email || u.name || '')}</span></div>
            <button class="btn" id="btnSync">Sincronizar con Mercado Libre</button>
            <button class="btn sec" data-avisos="1">Avisos${nuevos ? ' (' + nuevos + ' nuevos)' : ''}</button>
            <a class="btn sec" href="index.html?escritorio=1">Ver panel completo</a>
            <button class="btn sec peligro" id="btnSalir">Cerrar sesión</button></section>
            <div class="sin-datos">Los datos se actualizan solos cada 4 horas.</div>`;
    }

    // ── Detalle de producto ─────────────────────────────────────────────────────
    function filaCopiable(rotulo, valor) {
        if (!valor) return '';
        return `<button class="copiable" data-copiar="${esc(valor)}"><span>${esc(rotulo)}</span><b>${esc(valor)}</b>${icono(ICO_COPIAR, 'ico-chico')}</button>`;
    }
    function abrirDetalle(idx) {
        const it = estado.items[idx];
        if (!it) return;
        const g = etiquetaItem(it);
        const r = ringDias(it);
        const dReal = diasReales(it);
        const partes = [
            { valor: it.stock, color: 'var(--ok)', nombre: 'En Full' },
            { valor: it.en_proceso, color: 'var(--camino)', nombre: 'Recibiendo' },
            { valor: it.en_camino, color: 'var(--exceso)', nombre: 'En camino' },
            { valor: it.en_prep, color: 'var(--warn)', nombre: 'En preparación' }
        ];
        const tot = partes.reduce((a, p) => a + p.valor, 0);
        let nota = '', notaColor = g.color;
        const gid = grupoDe(it);
        if (gid === 'pausados') nota = 'Todas sus publicaciones están pausadas en Mercado Libre: no vende, por eso no cuenta como urgencia.';
        else if (gid === 'urgentes') nota = 'Se queda sin stock antes de que le entre mercadería. Conviene sumarlo a la próxima colecta.';
        else if (gid === 'pronto') nota = 'Todavía hay stock, pero conviene sumarlo a la próxima colecta.';
        else if (cubiertoPorColecta(it)) nota = `Hoy en Full hay ${NF.format(it.stock)} unidades (${NF.format(Math.round(it.stock / vpdReal(it)))} días de venta), pero la colecta que ya está en camino suma ${NF.format(it.entrante)} y con eso alcanza para ${NF.format(Math.round(dReal))} días. No hace falta mandar más: solo esperar que entre.`;
        else if (gid === 'deMas') nota = 'Entre lo que hay en Full y lo que viaja en tus colectas alcanza para mucho más que tu objetivo. No mandes más por ahora.';
        else if (it.entrante > 0) nota = 'Hay mercadería en camino que lo cubre: solo falta esperar que entre.';
        let advertencia = '';
        if (gid === 'deMas' && (dReal === null || dReal > UMBRAL_EXCEDENTE_ML_DIAS)) {
            advertencia = `<div class="aviso" style="--c:var(--warn)">${icono(ICO_ALERTA, 'ico-chico adv')} Supera los ${UMBRAL_EXCEDENTE_ML_DIAS} días de almacenamiento. Mercado Libre no lo informa por API, pero podría cobrarte por exceso de stock almacenado.</div>`;
        }
        const v = vpdReal(it);
        const dec = (n) => (Math.round(n * 100) / 100).toLocaleString('es-AR');
        const cuenta = v > 0 ? `${dec(tot)} ÷ ${dec(v)} por día = ${Math.round(tot / v)} días` : 'Sin ventas en los últimos 30 días';
        const pubs = (it.channels.length ? it.channels : [{ item_id: it.item_id, permalink: it.permalink }]).map(ch => {
            const tipo = ch.is_catalog ? 'Catálogo' : (ch.type_label || '');
            const url = /^https?:\/\//.test(ch.permalink || '') ? ch.permalink : 'https://articulo.mercadolibre.com.ar/' + encodeURIComponent(ch.item_id);
            const pausada = (ch.status || 'active') !== 'active';
            return `<a class="pub" href="${esc(url)}" target="_blank" rel="noopener"><span>${esc(ch.item_id)}${tipo ? ' · ' + esc(tipo) : ''}${pausada ? ' · pausada' : ''}</span>${icono(ICO_LINK, 'ico-chico')}</a>`;
        }).join('');
        const sheet = $('sheet');
        sheet.innerHTML = `<div class="agarre"></div>
            <h3>${esc(tituloItem(it))}</h3>
            <div class="meta">${esc(it.account_nickname)}</div>
            <div class="fila-torta">
                ${torta('media', [{ valor: r.frac * 100, color: g.color }, { valor: (1 - r.frac) * 100, color: 'transparent' }], r.texto, r.texto === '–' ? 'sin ventas' : 'días de stock', 12, { id: 'tortaDetalle' })}
                <div class="lista"><span class="etiqueta" style="--c:${g.color}">${esc(g.nombre)}</span><div class="chico">Objetivo: ${it.objetivo} días de cobertura</div></div>
            </div>
            ${nota ? `<div class="aviso" style="--c:${notaColor}">${esc(nota)}</div>` : ''}
            ${advertencia}
            <div class="datos">
                <div class="dato"><b>${NF.format(it.stock)}</b><span>Unidades en Full</span></div>
                <div class="dato"><b>${v > 0 ? (Math.round(v * 10) / 10).toLocaleString('es-AR') : '0'}</b><span>Ventas por día</span></div>
                <div class="dato"><b>${gid === 'pausados' || gid === 'deMas' || cubiertoPorColecta(it) || !it.quiebre ? '–' : esc(fechaCorta(it.quiebre))}</b><span>Se quiebra</span></div>
                <div class="dato"><b>${NF.format(it.sugerido)}</b><span>Sugerido a mandar</span></div>
            </div>
            <div class="chico cuenta">${esc(cuenta)}${it.no_disponible ? ' · ' + NF.format(it.no_disponible) + ' no disponibles' : ''}</div>
            ${tot > 0 ? `<div class="card" style="margin-top:12px;box-shadow:none"><h2>Dónde está tu stock</h2><div class="fila-torta">
                ${torta('media', partes, NF.format(tot), 'unidades', 14)}
                <div class="lista">${partes.map(p => `<div class="lin" style="--c:${p.color}"><i></i><span class="n">${p.nombre}</span><span class="v">${NF.format(p.valor)}</span></div>`).join('')}</div></div></div>` : ''}
            <div class="ident">${filaCopiable('SKU', it.sku)}${filaCopiable('Cód. Full', it.inventory_id)}${pubs}</div>`;
        mostrarHoja();
        animarTortas(sheet);
    }

    // ── Avisos (cambios de ritmo de venta) ──────────────────────────────────────
    function vistosHasta() { try { return Number(localStorage.getItem('avisosVistosHasta')) || 0; } catch (e) { return 0; } }
    function avisosNuevos() { const h = vistosHasta(); return estado.avisos.filter(a => a.fecha && Date.parse(a.fecha) > h).length; }
    function actualizarCampana() {
        const n = avisosNuevos();
        const b = $('campanaBadge');
        b.textContent = n; b.style.display = n ? 'grid' : 'none';
        $('btnAvisos').classList.toggle('sin-leer', n > 0);
    }
    function abrirAvisos() {
        const h = vistosHasta();
        const html = estado.avisos.length ? estado.avisos.map(a => {
            const baja = a.sentido === 'baja';
            const color = a.revertido ? 'var(--text2)' : (baja ? 'var(--camino)' : 'var(--crit)');
            const titulo = a.revertido ? 'Se revirtió: el ritmo de venta volvió a la normalidad'
                : (baja ? 'Bajó el ritmo de venta' : 'Se aceleró la venta: puede faltar stock');
            const f = a.fecha ? new Date(a.fecha).toLocaleString('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
            const nuevo = a.fecha && Date.parse(a.fecha) > h;
            return `<details class="aviso-item" style="--c:${color}"><summary><b>${nuevo ? '● ' : ''}${esc(titulo)}</b><span>${esc(a.producto)}</span><small>${esc(f)}</small></summary>
                <p>${esc(a.detalle)}</p></details>`;
        }).join('') : '<div class="sin-datos">No hay avisos en la última semana.</div>';
        $('sheet').innerHTML = `<div class="agarre"></div><h3>Avisos</h3><div class="meta">Productos cuya venta se aceleró y pueden quedarse sin stock antes de que entre la reposición. Se muestra la última semana.</div>${html}`;
        mostrarHoja();
        try { localStorage.setItem('avisosVistosHasta', String(Date.now())); } catch (e) {}
        setTimeout(actualizarCampana, 0);
    }
    function mostrarHoja() {
        const sheet = $('sheet');
        $('sheetFondo').classList.add('abierta');
        sheet.classList.add('abierta');
        sheet.scrollTop = 0;
    }
    function cerrarHoja() { $('sheet').classList.remove('abierta'); $('sheetFondo').classList.remove('abierta'); }

    // ── Render y eventos ────────────────────────────────────────────────────────
    function render() {
        const vista = $('vista');
        if (estado.cargando) { vista.innerHTML = '<div class="esqueleto" style="height:360px"></div><div class="esqueleto"></div><div class="esqueleto"></div>'; return; }
        if (estado.error) { vista.innerHTML = `<div class="card"><div class="sin-datos">${esc(estado.error)}</div><button class="btn" id="btnReintentar">Reintentar</button></div>`; return; }
        if (!estado.items.length && estado.tab !== 'mas') {
            vista.innerHTML = '<div class="card"><div class="sin-datos">Todavía no hay publicaciones de Full para mostrar.<br>Conectá Mercado Libre desde el panel completo.</div><a class="btn" href="index.html?escritorio=1">Abrir panel completo</a></div>';
            return;
        }
        vista.innerHTML = ({ resumen: vistaResumen, productos: vistaProductos, colecta: vistaColecta, mas: vistaMas })[estado.tab]();
        animarTortas(vista);
        document.querySelectorAll('#tabbar button').forEach(b => b.classList.toggle('activa', b.dataset.tab === estado.tab));
        const urg = conteos().urgentes;
        const bProd = document.querySelector('#tabbar [data-tab="productos"]');
        let punto = bProd.querySelector('.punto');
        if (urg > 0) { if (!punto) { punto = document.createElement('span'); punto.className = 'punto'; bProd.appendChild(punto); } punto.textContent = urg; }
        else if (punto) punto.remove();
        actualizarCampana();
    }
    function irA(tab, filtro) {
        estado.tab = tab;
        if (filtro) estado.filtro = filtro;
        render();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    function copiar(texto) {
        const listo = () => aviso('Copiado: ' + texto);
        try { if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(texto).then(listo, () => {}); return; } } catch (e) {}
        const t = document.createElement('textarea'); t.value = texto; document.body.appendChild(t); t.select();
        try { document.execCommand('copy'); listo(); } catch (e) {} t.remove();
    }

    document.addEventListener('click', (ev) => {
        const t = ev.target;
        const tab = t.closest('#tabbar button');
        if (tab) { cerrarHoja(); return irA(tab.dataset.tab); }
        const cop = t.closest('[data-copiar]');
        if (cop) return copiar(cop.dataset.copiar);
        if (t.closest('#btnAvisos') || t.closest('[data-avisos]')) return abrirAvisos();
        const seg = t.closest('[data-seg]');
        if (seg) return irA('productos', seg.dataset.seg);
        const ir = t.closest('[data-ir]');
        if (ir) { ev.preventDefault(); return irA(ir.dataset.ir); }
        const fil = t.closest('[data-filtro]');
        if (fil) { ev.preventDefault(); estado.filtro = fil.dataset.filtro; return irA('productos'); }
        const prod = t.closest('[data-prod]');
        if (prod) return abrirDetalle(Number(prod.dataset.prod));
        if (t.id === 'sheetFondo') return cerrarHoja();
        if (t.closest('#btnRefrescar') || t.id === 'btnReintentar') return cargar(true);
        if (t.id === 'btnSalir') { try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem('token'); } catch (e) {} return irALogin(); }
        if (t.id === 'btnSync') return sincronizar(t);
    });
    document.addEventListener('input', (ev) => {
        if (ev.target.id !== 'buscador') return;
        estado.busqueda = ev.target.value;
        const lista = listaFiltrada();
        $('listaProd').innerHTML = lista.length ? lista.map(filaProducto).join('') : '<div class="vacio">No hay productos con ese filtro.</div>';
        $('contador').textContent = `Mostrando ${lista.length} de ${estado.items.length}`;
        animarTortas($('listaProd'));
    });
    // Deslizar la hoja hacia abajo para cerrarla.
    (function () {
        let y0 = null;
        const sh = $('sheet');
        sh.addEventListener('touchstart', e => { y0 = sh.scrollTop <= 0 ? e.touches[0].clientY : null; }, { passive: true });
        sh.addEventListener('touchend', e => { if (y0 !== null && e.changedTouches[0].clientY - y0 > 90) cerrarHoja(); y0 = null; }, { passive: true });
    })();

    async function sincronizar(btn) {
        btn.textContent = 'Sincronizando...'; btn.disabled = true;
        try {
            const r = await api('/sync-now', { method: 'POST' });
            aviso(r.data.ok ? 'Sincronización pedida' : (r.data.error || 'No se pudo sincronizar'));
            if (r.data.ok) setTimeout(() => cargar(true), 2500);
        } catch (e) { aviso('No se pudo sincronizar'); }
        btn.textContent = 'Sincronizar con Mercado Libre'; btn.disabled = false;
    }

    async function cargar(manual) {
        const b = $('btnRefrescar');
        b.classList.add('girando');
        if (!manual) { estado.cargando = true; render(); }
        try {
            if (!estado.user) {
                const me = await api('/auth/me');
                estado.user = me.data.user || me.data;
            }
            const r = await api('/items?warehouse=meli_full');
            if (r.status === 403 && r.data.subscription_required) {
                estado.error = 'Tu acceso a EnvioBot Full necesita activarse. Abrí el panel completo para activarlo.';
            } else if (r.data.ok) {
                estado.items = (r.data.items || []).map(adaptar);
                estado.colectas = r.data.colectas || [];
                estado.cargadoEn = Date.now();
                estado.error = null;
                const hora = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false });
                $('subtitulo').textContent = `Actualizado ${hora}`;
            } else {
                estado.error = r.data.error || 'No se pudieron cargar los datos.';
            }
            try { const a = await api('/avisos'); if (a.data.ok) estado.avisos = a.data.avisos || []; } catch (e) { if (e.message === 'sesion') throw e; }
        } catch (e) {
            if (e.message !== 'sesion') estado.error = 'No hay conexión con el servidor.';
        }
        estado.cargando = false;
        b.classList.remove('girando');
        if (manual) aviso(estado.error ? 'No se pudo actualizar' : 'Datos actualizados');
        render();
    }

    // Cuenta regresiva viva: se refresca el número cada 30 s sin redibujar todo.
    setInterval(() => {
        document.querySelectorAll('.cuentaNum').forEach(el => {
            const resta = Math.floor((Date.parse(el.dataset.lim) - Date.now()) / 1000);
            if (resta > 0) el.textContent = segundosA(resta);
        });
    }, 30000);

    if (!token()) { irALogin(); return; }
    render();
    cargar(false);
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
})();
