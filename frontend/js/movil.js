// EnvioBot Full - versión para teléfono. Usa la misma API que el panel de escritorio.
(function () {
    'use strict';

    const API = '/api/full';
    const TOKEN_KEY = 'enviobot_full_token';
    const NF = new Intl.NumberFormat('es-AR');

    const ESTADOS = {
        ok:       { grupo: 'ok',     nombre: 'Óptimo',         color: 'var(--ok)' },
        warning:  { grupo: 'warn',   nombre: 'Preparar envío', color: 'var(--warn)' },
        critical: { grupo: 'crit',   nombre: 'Crítico',        color: 'var(--crit)' },
        out_of_stock: { grupo: 'crit', nombre: 'Sin stock',    color: 'var(--crit)' },
        in_reception: { grupo: 'camino', nombre: 'Recibiendo', color: 'var(--camino)' },
        in_transit:   { grupo: 'camino', nombre: 'En camino',  color: 'var(--camino)' },
        in_preparation: { grupo: 'camino', nombre: 'En preparación', color: 'var(--camino)' }
    };
    const GRUPOS = [
        { id: 'crit',   nombre: 'Críticos',     color: 'var(--crit)' },
        { id: 'warn',   nombre: 'Preparar envío', color: 'var(--warn)' },
        { id: 'ok',     nombre: 'Óptimos',      color: 'var(--ok)' },
        { id: 'camino', nombre: 'En camino',    color: 'var(--camino)' }
    ];
    const GALPON = [
        { id: 'to_buy',  nombre: 'A comprar',   color: 'var(--crit)' },
        { id: 'packing', nombre: 'Envasando',   color: 'var(--warn)' },
        { id: 'boxed',   nombre: 'Listo en caja', color: 'var(--ok)' }
    ];
    const PALETA = ['#f5a623', '#5b9bff', '#34d399', '#b58cff', '#ff7aa8', '#8f94a3'];

    const estado = { tab: 'resumen', filtro: 'todos', busqueda: '', items: [], colecta: null, user: null, cargando: true, error: null };
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
            segs.forEach((s, i) => {
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
    function grupoDe(it) { return (ESTADOS[it.status] || ESTADOS.ok).grupo; }
    function conteos() {
        const c = { crit: 0, warn: 0, ok: 0, camino: 0 };
        estado.items.forEach(it => { c[grupoDe(it)]++; });
        return c;
    }
    function diasTexto(it) {
        if (!(it.vpd_weighted > 0)) return 'Sin ventas';
        return it.days_left >= 999 ? 'Sin ventas' : `${Math.round(it.days_left)} d`;
    }
    function ringDias(it) {
        const obj = it.target_coverage_days || 30;
        const dias = it.vpd_weighted > 0 ? Math.min(it.days_left, obj) : obj;
        return { frac: Math.max(0.04, dias / obj), texto: it.vpd_weighted > 0 ? String(Math.round(it.days_left)) : '–' };
    }
    function segundosATexto(s) {
        const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
        if (d > 0) return { n: `${d}d ${h}h`, cap: 'para el límite' };
        if (h > 0) return { n: `${h}h ${m}m`, cap: 'para el límite' };
        return { n: `${m} min`, cap: 'para el límite' };
    }
    function fechaCorta(iso) {
        if (!iso) return '';
        const d = new Date(iso + (iso.length <= 10 ? 'T12:00:00' : ''));
        return d.toLocaleDateString('es-AR', { weekday: 'short', day: '2-digit', month: '2-digit' });
    }

    // ── Vistas ──────────────────────────────────────────────────────────────────
    function tortaColecta() {
        const c = estado.colecta;
        if (!c) return null;
        const resta = Math.max(0, c.segundos_restantes - Math.floor((Date.now() - estado.cargadoEn) / 1000));
        const SEMANA = 7 * 86400;
        if (!c.abierta || resta <= 0) {
            return { html: torta('media', [{ valor: 100, color: 'var(--crit)' }], 'Cerrada', 'edición', 11, { id: 'tortaCuenta', colorNum: 'var(--crit)' }), cerrada: true, resta: 0 };
        }
        const t = segundosATexto(resta);
        const urgente = resta < 86400;
        const color = urgente ? 'var(--crit)' : (resta < 2 * 86400 ? 'var(--warn)' : 'var(--ok)');
        const frac = Math.max(0.03, Math.min(1, resta / SEMANA));
        return { html: torta('media', [{ valor: frac * 100, color }, { valor: (1 - frac) * 100, color: 'transparent' }], `<span id="cuentaNum" style="font-size:${t.n.length > 6 ? 22 : 26}px">${t.n}</span>`, t.cap, 11, { id: 'tortaCuenta' }), cerrada: false, resta };
    }

    function vistaResumen() {
        const c = conteos();
        const total = estado.items.length;
        const accion = c.crit + c.warn;
        const segs = GRUPOS.map(g => ({ valor: c[g.id], color: g.color, id: g.id }));
        const hero = `<section class="card hero">
            <div class="saludo">${accion > 0 ? `${accion} ${accion === 1 ? 'producto necesita' : 'productos necesitan'} atención` : 'Todo el stock está bajo control'}</div>
            ${torta('grande', segs, NF.format(total), total === 1 ? 'producto en Full' : 'productos en Full', 13, { id: 'tortaHero' })}
            <div class="leyenda">${GRUPOS.map(g => `<button class="ley" data-filtro="${g.id}" style="--c:${g.color}"><i></i><div><b>${c[g.id]}</b><br><span>${g.nombre}</span></div></button>`).join('')}</div>
        </section>`;

        // Próxima colecta
        const tc = tortaColecta();
        const col = estado.colecta;
        const cardColecta = `<section class="card"><h2>Próxima colecta <a href="#" data-ir="colecta">Ver</a></h2>` + (tc ?
            `<div class="colecta-top">${tc.html}<div class="txt"><b>${tc.cerrada ? 'Edición cerrada' : 'Podés editarla hasta'}</b><span>${tc.cerrada ? 'Mercado Libre ya no admite cambios.' : esc(fechaCorta(col.limite_edicion)) + ' a las ' + esc(horaDe(col.limite_edicion))}</span><span>Retiro: ${esc(fechaCorta(col.fecha_retiro))}${col.codigo ? ' · ' + esc(col.codigo) : ''}</span></div></div>`
            : `<div class="sin-datos">No hay una colecta en preparación.<br>Armala desde el panel y acá vas a ver la cuenta regresiva.</div>`) + `</section>`;

        // Quién vende más (participación en la velocidad de venta)
        const conVentas = estado.items.filter(it => it.vpd_weighted > 0).sort((a, b) => b.vpd_weighted - a.vpd_weighted);
        let cardVentas = '';
        if (conVentas.length) {
            const top = conVentas.slice(0, 5);
            const resto = conVentas.slice(5).reduce((a, it) => a + it.vpd_weighted, 0);
            const partes = top.map((it, i) => ({ nombre: nombreCorto(it), valor: it.vpd_weighted, color: PALETA[i] }));
            if (resto > 0) partes.push({ nombre: 'Otros', valor: resto, color: PALETA[5] });
            const totalVpd = partes.reduce((a, p) => a + p.valor, 0);
            cardVentas = `<section class="card"><h2>Quién vende más</h2><div class="fila-torta">
                ${torta('media', partes, NF.format(Math.round(totalVpd)), 'unid. por día', 14)}
                <div class="lista">${partes.map(p => `<div class="lin" style="--c:${p.color}"><i></i><span class="n">${esc(p.nombre)}</span><span class="v">${Math.round(p.valor / totalVpd * 100)}%</span></div>`).join('')}</div>
            </div></section>`;
        }

        // Urgentes
        const urgentes = estado.items.filter(it => grupoDe(it) === 'crit').slice(0, 3);
        const cardUrg = urgentes.length ? `<section class="card"><h2>Hay que reponer ya <a href="#" data-filtro="crit">Ver todos</a></h2><div style="display:flex;flex-direction:column;gap:10px">${urgentes.map(filaProducto).join('')}</div></section>` : '';

        return hero + cardColecta + cardVentas + cardUrg;
    }

    function horaDe(iso) {
        return new Date(iso).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/Argentina/Buenos_Aires' });
    }
    function nombreCorto(it) {
        const t = (it.title || it.sku || 'Producto').trim();
        return t.length > 22 ? t.slice(0, 21) + '…' : t;
    }

    function filaProducto(it) {
        const e = ESTADOS[it.status] || ESTADOS.ok;
        const r = ringDias(it);
        const idx = estado.items.indexOf(it);
        return `<button class="prod" data-prod="${idx}">
            ${torta('mini', [{ valor: r.frac * 100, color: e.color }, { valor: (1 - r.frac) * 100, color: 'transparent' }], r.texto, '', 11)}
            <div class="info"><div class="tit">${esc(it.title)}</div>
            <div class="sub"><span class="etiqueta" style="--c:${e.color}">${esc(e.nombre)}</span>${NF.format(it.current_stock_full || 0)} en Full · ${it.vpd_weighted > 0 ? (Math.round(it.vpd_weighted * 10) / 10).toLocaleString('es-AR') + '/día' : 'sin ventas'}</div></div>
        </button>`;
    }

    function vistaProductos() {
        const c = conteos();
        const chips = [{ id: 'todos', nombre: 'Todos', n: estado.items.length }].concat(GRUPOS.map(g => ({ id: g.id, nombre: g.nombre, n: c[g.id], color: g.color })));
        const q = estado.busqueda.trim().toLowerCase();
        const lista = estado.items.filter(it => (estado.filtro === 'todos' || grupoDe(it) === estado.filtro) &&
            (!q || (it.title || '').toLowerCase().includes(q) || (it.sku || '').toLowerCase().includes(q)));
        return `<input class="buscador" id="buscador" type="search" placeholder="Buscar por nombre o SKU" value="${esc(estado.busqueda)}" autocomplete="off">
            <div class="filtros">${chips.map(ch => `<button class="chip${estado.filtro === ch.id ? ' activo' : ''}" data-filtro="${ch.id}" ${ch.color ? `style="--c:${ch.color}"` : ''}>${ch.color ? '<i></i>' : ''}${esc(ch.nombre)} ${ch.n}</button>`).join('')}</div>
            <div id="listaProd" style="display:flex;flex-direction:column;gap:10px">${lista.length ? lista.map(filaProducto).join('') : '<div class="vacio">No hay productos con ese filtro.</div>'}</div>`;
    }

    function vistaColecta() {
        const tc = tortaColecta();
        const col = estado.colecta;
        const enPrep = estado.items.filter(it => it.in_preparation_stock > 0);
        const unidades = { to_buy: 0, packing: 0, boxed: 0 };
        enPrep.forEach(it => { unidades[it.prep_status || 'to_buy'] += it.in_preparation_stock; });
        const totalU = unidades.to_buy + unidades.packing + unidades.boxed;

        const cabecera = `<section class="card hero">
            <h2 style="justify-content:center">Cuenta regresiva</h2>` + (tc ?
            `${tc.html.replace('torta media', 'torta grande').replace('id="tortaCuenta"', 'id="tortaCuenta"')}
            <div class="saludo" style="margin-top:12px">${tc.cerrada ? 'La edición cerró. Retiro ' + esc(fechaCorta(col.fecha_retiro)) : 'Editable hasta el ' + esc(fechaCorta(col.limite_edicion)) + ' a las ' + esc(horaDe(col.limite_edicion))}${col.codigo ? '<br>' + esc(col.codigo) : ''}</div>`
            : `<div class="sin-datos">No hay una colecta en preparación con fecha de retiro.</div>`) + `</section>`;

        const galpon = totalU > 0 ? `<section class="card"><h2>Estado del galpón</h2><div class="fila-torta">
            ${torta('media', GALPON.map(g => ({ valor: unidades[g.id], color: g.color })), NF.format(totalU), 'unidades', 14)}
            <div class="lista">${GALPON.map(g => `<div class="lin" style="--c:${g.color}"><i></i><span class="n">${g.nombre}</span><span class="v">${NF.format(unidades[g.id])}</span></div>`).join('')}</div>
        </div></section>` : '';

        const proxima = estado.items.filter(it => it.sugerido_al_ingreso > 0 && it.in_preparation_stock === 0).sort((a, b) => b.sugerido_al_ingreso - a.sugerido_al_ingreso).slice(0, 8);
        const cardProx = proxima.length ? `<section class="card"><h2>Para la próxima colecta</h2><div style="display:flex;flex-direction:column;gap:10px">${proxima.map(it => {
            const idx = estado.items.indexOf(it), e = ESTADOS[it.status] || ESTADOS.ok;
            return `<button class="prod" data-prod="${idx}"><div class="info"><div class="tit">${esc(it.title)}</div><div class="sub"><span class="etiqueta" style="--c:${e.color}">${esc(e.nombre)}</span>Sugerido: <b style="color:var(--text)">${NF.format(it.sugerido_al_ingreso)}</b> unid.</div></div></button>`;
        }).join('')}</div></section>` : '';

        const exceso = estado.items.filter(it => it.sobrestock);
        const cardEx = exceso.length ? `<section class="card"><h2>Con exceso de stock</h2><div style="display:flex;flex-direction:column;gap:10px">${exceso.slice(0, 6).map(it => {
            const idx = estado.items.indexOf(it);
            return `<button class="prod" data-prod="${idx}"><div class="info"><div class="tit">${esc(it.title)}</div><div class="sub"><span class="etiqueta" style="--c:var(--exceso)">Exceso</span>${NF.format(it.current_stock_full || 0)} en Full · no mandes más por ahora</div></div></button>`;
        }).join('')}</div></section>` : '';

        return cabecera + galpon + cardProx + cardEx;
    }

    function vistaMas() {
        const u = estado.user || {};
        return `<section class="card"><h2>Cuenta</h2>
            <div class="lin"><span class="n">${esc(u.email || u.name || '')}</span></div>
            <button class="btn" id="btnSync">Sincronizar con Mercado Libre</button>
            <a class="btn sec" href="index.html?escritorio=1">Ver panel completo</a>
            <button class="btn sec peligro" id="btnSalir">Cerrar sesión</button></section>
            <div class="sin-datos">Los datos se actualizan solos cada 4 horas.</div>`;
    }

    // ── Hoja de detalle ─────────────────────────────────────────────────────────
    function abrirDetalle(idx) {
        const it = estado.items[idx];
        if (!it) return;
        const e = ESTADOS[it.status] || ESTADOS.ok;
        const r = ringDias(it);
        const obj = it.target_coverage_days || 30;
        const partes = [
            { valor: it.current_stock_full || 0, color: 'var(--ok)', nombre: 'En Full' },
            { valor: it.in_process_stock || 0, color: 'var(--camino)', nombre: 'Recibiendo' },
            { valor: it.in_transit_stock || 0, color: 'var(--exceso)', nombre: 'En camino' },
            { valor: it.in_preparation_stock || 0, color: 'var(--warn)', nombre: 'En preparación' }
        ];
        const tot = partes.reduce((a, p) => a + p.valor, 0);
        let nota = '';
        if (e.grupo === 'crit') nota = `Te queda stock para ${it.vpd_weighted > 0 ? Math.round(it.days_left) + ' días' : 'poco tiempo'}, menos que lo que tarda en llegar un envío.`;
        else if (e.grupo === 'warn') nota = 'Ya conviene preparar el próximo envío.';
        else if (e.grupo === 'camino') nota = 'Hay mercadería en camino a Full.';
        else if (it.sobrestock) nota = 'Tenés más stock del necesario para el objetivo de cobertura.';
        const sheet = $('sheet');
        sheet.innerHTML = `<div class="agarre"></div>
            <h3>${esc(it.title)}</h3>
            <div class="meta">${it.sku ? 'SKU ' + esc(it.sku) + ' · ' : ''}${esc(it.account_nickname || '')}</div>
            <div class="fila-torta">
                ${torta('media', [{ valor: r.frac * 100, color: e.color }, { valor: (1 - r.frac) * 100, color: 'transparent' }], r.texto, it.vpd_weighted > 0 ? 'días de stock' : 'sin ventas', 12, { id: 'tortaDetalle' })}
                <div class="lista"><span class="etiqueta" style="--c:${e.color}">${esc(e.nombre)}</span><div style="font-size:12.5px;color:var(--text2)">Objetivo: ${obj} días de cobertura</div></div>
            </div>
            ${nota ? `<div class="aviso" style="--c:${e.color}">${esc(nota)}</div>` : ''}
            <div class="datos">
                <div class="dato"><b>${NF.format(it.current_stock_full || 0)}</b><span>Unidades en Full</span></div>
                <div class="dato"><b>${it.vpd_weighted > 0 ? (Math.round(it.vpd_weighted * 10) / 10).toLocaleString('es-AR') : '0'}</b><span>Ventas por día</span></div>
                <div class="dato"><b>${it.stockout_date ? esc(fechaCorta(it.stockout_date)) : '–'}</b><span>Se quiebra</span></div>
                <div class="dato"><b>${NF.format(it.sugerido_al_ingreso || 0)}</b><span>Sugerido a mandar</span></div>
            </div>
            ${tot > 0 ? `<div class="card" style="margin-top:12px;box-shadow:none"><h2>Dónde está tu stock</h2><div class="fila-torta">
                ${torta('media', partes, NF.format(tot), 'unidades', 14)}
                <div class="lista">${partes.map(p => `<div class="lin" style="--c:${p.color}"><i></i><span class="n">${p.nombre}</span><span class="v">${NF.format(p.valor)}</span></div>`).join('')}</div></div></div>` : ''}
            ${it.permalink ? `<a class="btn sec" href="${esc(it.permalink)}" target="_blank" rel="noopener">Ver publicación en Mercado Libre</a>` : ''}`;
        $('sheetFondo').classList.add('abierta');
        sheet.classList.add('abierta');
        sheet.scrollTop = 0;
        animarTortas(sheet);
    }
    function cerrarDetalle() { $('sheet').classList.remove('abierta'); $('sheetFondo').classList.remove('abierta'); }

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
        const crit = conteos().crit;
        const bProd = document.querySelector('#tabbar [data-tab="productos"]');
        let punto = bProd.querySelector('.punto');
        if (crit > 0) { if (!punto) { punto = document.createElement('span'); punto.className = 'punto'; bProd.appendChild(punto); } punto.textContent = crit; }
        else if (punto) punto.remove();
    }
    function irA(tab, filtro) {
        estado.tab = tab;
        if (filtro) estado.filtro = filtro;
        render();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    document.addEventListener('click', (ev) => {
        const t = ev.target;
        const tab = t.closest('#tabbar button');
        if (tab) { cerrarDetalle(); return irA(tab.dataset.tab); }
        const seg = t.closest('[data-seg]');
        if (seg) return irA('productos', seg.dataset.seg);
        const ir = t.closest('[data-ir]');
        if (ir) { ev.preventDefault(); return irA(ir.dataset.ir); }
        const fil = t.closest('[data-filtro]');
        if (fil) { ev.preventDefault(); estado.filtro = fil.dataset.filtro; return irA('productos'); }
        const prod = t.closest('[data-prod]');
        if (prod) return abrirDetalle(Number(prod.dataset.prod));
        if (t.id === 'sheetFondo') return cerrarDetalle();
        if (t.id === 'btnRefrescar' || t.closest('#btnRefrescar') || t.id === 'btnReintentar') return cargar(true);
        if (t.id === 'btnSalir') { try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem('token'); } catch (e) {} return irALogin(); }
        if (t.id === 'btnSync') return sincronizar(t);
    });
    document.addEventListener('input', (ev) => {
        if (ev.target.id !== 'buscador') return;
        estado.busqueda = ev.target.value;
        const q = estado.busqueda.trim().toLowerCase();
        const lista = estado.items.filter(it => (estado.filtro === 'todos' || grupoDe(it) === estado.filtro) &&
            (!q || (it.title || '').toLowerCase().includes(q) || (it.sku || '').toLowerCase().includes(q)));
        $('listaProd').innerHTML = lista.length ? lista.map(filaProducto).join('') : '<div class="vacio">No hay productos con ese filtro.</div>';
        animarTortas($('listaProd'));
    });
    // Deslizar la hoja hacia abajo para cerrarla.
    (function () {
        let y0 = null;
        const sh = $('sheet');
        sh.addEventListener('touchstart', e => { y0 = sh.scrollTop <= 0 ? e.touches[0].clientY : null; }, { passive: true });
        sh.addEventListener('touchend', e => { if (y0 !== null && e.changedTouches[0].clientY - y0 > 90) cerrarDetalle(); y0 = null; }, { passive: true });
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
                estado.items = r.data.items || [];
                estado.colecta = r.data.proxima_colecta || null;
                estado.cargadoEn = Date.now();
                estado.error = null;
                const hora = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false });
                $('subtitulo').textContent = `Actualizado ${hora}`;
            } else {
                estado.error = r.data.error || 'No se pudieron cargar los datos.';
            }
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
        if (!estado.colecta || estado.cargando) return;
        if (estado.tab === 'resumen' || estado.tab === 'colecta') {
            const sc = document.getElementById('cuentaNum');
            const resta = estado.colecta.segundos_restantes - Math.floor((Date.now() - estado.cargadoEn) / 1000);
            if (sc && resta > 0) sc.textContent = segundosATexto(resta).n;
        }
    }, 30000);

    if (!token()) { irALogin(); return; }
    render();
    cargar(false);
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
})();
