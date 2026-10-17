/* Teclado en formularios — criterio común de EnvioBot (ver CRITERIOS_ENVIOBOT.md).
 *
 *   TAB         campo siguiente según tabindex (lo hace el navegador)
 *   ENTER       igual que TAB, solo dentro de un <form> o un cuadro de diálogo
 *   CTRL+ENTER  guarda los cambios
 *
 * Fuente única: enviobot-comun/teclado-formularios.js. Cada app lleva una copia
 * (Full: frontend/js/; Pedidos: bloque marcado dentro de index.html y admin/index.html).
 * Si se cambia acá, se copia a las dos.
 *
 * Opt-out puntual: data-enter-nativo en el campo o en un ancestro (ENTER conserva
 * su acción propia). Botón de guardado explícito: data-guardar.
 */
(function () {
    if (window.__tecladoFormularios) return;
    window.__tecladoFormularios = true;

    const CONTENEDOR = 'form, .modal-card, .modal, .dlg, [role="dialog"], [role="alertdialog"]';
    const CAMPOS = 'input, select, textarea';
    const NO_AVANZA = ['button', 'submit', 'reset', 'image', 'file', 'hidden'];

    function visible(el) {
        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }

    function esCampo(el) {
        if (!el.matches(CAMPOS) || el.disabled || el.readOnly || el.tabIndex < 0) return false;
        if (el.tagName === 'INPUT' && NO_AVANZA.includes(el.type)) return false;
        return visible(el);
    }

    // Orden de TAB: tabindex positivos ascendentes, después los 0 en orden del documento.
    function camposDe(cont) {
        const lista = Array.from(cont.querySelectorAll(CAMPOS)).filter(esCampo);
        const pos = lista.filter(el => el.tabIndex > 0).sort((a, b) => a.tabIndex - b.tabIndex);
        return pos.concat(lista.filter(el => el.tabIndex === 0));
    }

    function botonGuardar(cont) {
        const botones = Array.from(cont.querySelectorAll('button, input[type="submit"]'))
            .filter(b => !b.disabled && visible(b));
        return botones.find(b => b.hasAttribute('data-guardar'))
            || botones.find(b => b.type === 'submit')
            || botones.find(b => /^\s*(guardar|crear|agregar|confirmar|aceptar|enviar|entrar)/i.test(b.textContent || b.value || ''));
    }

    function guardar(origen) {
        // El más cercano al campo manda: sube de contenedor en contenedor.
        for (let el = origen; el && el !== document.documentElement; el = el.parentElement) {
            if (!el.matches || !el.matches(CONTENEDOR)) continue;
            const b = botonGuardar(el);
            if (b) { b.click(); return true; }
            if (el.tagName === 'FORM' && el.requestSubmit) { el.requestSubmit(); return true; }
        }
        // Sin diálogo ni form: el diálogo abierto más alto de la página.
        const abiertos = Array.from(document.querySelectorAll('.modal-overlay, .dlg-fondo')).filter(visible);
        const tope = abiertos[abiertos.length - 1];
        const b = tope && botonGuardar(tope);
        if (b) { b.click(); return true; }
        return false;
    }

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' || e.defaultPrevented || e.isComposing || e.altKey || e.shiftKey) return;
        const el = e.target;
        if (!el || !el.matches) return;

        if (e.ctrlKey || e.metaKey) {
            if (guardar(el)) e.preventDefault();
            return;
        }

        if (!el.matches(CAMPOS) || el.tagName === 'TEXTAREA') return;
        if (el.tagName === 'INPUT' && NO_AVANZA.includes(el.type)) return;
        if (el.closest('[data-enter-nativo]')) return;
        const cont = el.closest(CONTENEDOR);
        if (!cont) return;

        const campos = camposDe(cont);
        const i = campos.indexOf(el);
        if (i === -1) return;
        if (i === campos.length - 1) {
            // Último campo: un <form> conserva su envío nativo; un diálogo sin form no hace nada.
            if (cont.tagName !== 'FORM') e.preventDefault();
            return;
        }
        e.preventDefault();
        const sig = campos[i + 1];
        sig.focus();
        if (sig.select && sig.tagName === 'INPUT') { try { sig.select(); } catch (_) { /* tipos sin selección */ } }
    });
})();
