"""Panel de inicio del frontend (estado general, colecta, qué hacer hoy, tienen de más).
Ejecuta el JS real del panel con un DOM de mentira (hace falta Node; si no hay, se saltea).
Uso:  python backend/test_panel_colecta.py
"""
import json
import sys
import os
import re
import shutil
import subprocess
import tempfile
import unittest

FRONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')
NODE = shutil.which('node')


def _leer(rel):
    with open(os.path.join(FRONT, rel), encoding='utf-8') as f:
        return f.read()


def _corte(js, desde, hasta):
    i, j = js.index(desde), js.index(hasta)
    return js[i:j]


HARNESS = r"""
const vm = require('vm');
const src = require('fs').readFileSync(process.argv[2], 'utf8'), caso = JSON.parse(process.argv[3]);
const cont = { style: {}, innerHTML: '' }, colectas = { style: {}, innerHTML: '' };
const ctx = { document: { getElementById: id => id === 'panelColecta' ? cont : (id === 'panelColectasTab' ? colectas : null) },
              setInterval: () => 1, Date, Math, String, console };
ctx.itemsData = caso.items;
vm.createContext(ctx);
vm.runInContext(src + '\nthis.__render = renderizarPanelColecta;', ctx);
vm.runInContext('proximaColecta = ' + JSON.stringify(caso.prox), ctx);
vm.runInContext('colectasData = ' + JSON.stringify(caso.colectas || []), ctx);
vm.runInContext('cambiosPendientes = ' + JSON.stringify(caso.pendientes || {}), ctx);
ctx.__render();
process.stdout.write(JSON.stringify({ html: colectas.innerHTML + cont.innerHTML, display: cont.style.display }));
"""


def _item(**kw):
    base = dict(title='Almendras', sku='ALM-1', variation_name=None, current_stock=10, total_incoming=0,
                in_preparation_stock=0, status='ok', target_stock_days=30, stock_al_ingreso=0,
                sugerido_al_ingreso=0, cobertura_post_colecta=None, aviso_ajuste_units=None, fecha_ingreso=None,
                days_left=30, covered_days_left=30, sobrestock=False)
    base.update(kw)
    return base


@unittest.skipUnless(NODE, 'Node no está instalado')
class TestPanelJS(unittest.TestCase):
    """Panel de inicio: estado general, tarjeta de colecta, qué hacer hoy, ajustar, tienen de más."""

    @classmethod
    def setUpClass(cls):
        js = _leer(os.path.join('js', 'app.js'))
        cabecera = _corte(js, '// Escapa datos de afuera', '// Sistema de Notificaciones Toast')
        panel = _corte(js, '// ── Panel de colecta', '// ── Motor de cálculo')
        cls.src = cabecera + panel
        cls.src_tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
        cls.src_tmp.write(cls.src)
        cls.src_tmp.close()
        cls.src_path = cls.src_tmp.name
        cls.tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
        cls.tmp.write(HARNESS)
        cls.tmp.close()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.tmp.name)
        os.unlink(cls.src_tmp.name)

    def _correr(self, items, prox=None, colectas=None, pendientes=None):
        r = subprocess.run([NODE, self.tmp.name, self.src_path, json.dumps({'items': items, 'prox': prox, 'colectas': colectas or [], 'pendientes': pendientes or {}})],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def _prox(self, abierta=True, retiro='2026-10-19', codigo='COL-7'):
        limite = '2099-01-09T09:40:00-03:00' if abierta else '2020-01-09T09:40:00-03:00'
        return {'fecha_retiro': retiro, 'limite_edicion': limite, 'codigo': codigo}

    # ── estado general ──
    def test_sin_productos_el_panel_se_oculta(self):
        self.assertEqual(self._correr([])['display'], 'none')

    def test_todo_bien_tranquiliza_y_no_pide_colecta(self):
        out = self._correr([_item(), _item(title='Otro')])
        self.assertIn('Todo bajo control: tus 2 productos tienen stock suficiente', out['html'])
        self.assertIn('No hace falta armar ninguna colecta por ahora', out['html'])
        self.assertIn('Hoy no tenés nada pendiente', out['html'])

    def test_urgentes_sin_colecta_avisan_con_claridad(self):
        out = self._correr([_item(title='Pasas', status='out_of_stock', current_stock=0, sugerido_al_ingreso=48),
                            _item(title='Bien')])
        self.assertIn('Atención: 1 producto está por quedarse sin stock y todavía no está en una colecta', out['html'])
        self.assertIn('Mandar 48 u. en la próxima colecta', out['html'])
        self.assertIn('Sin stock hoy', out['html'])

    def test_solo_conviene_mandar_pronto_es_un_mensaje_suave(self):
        out = self._correr([_item(title='Pistachos', status='warning', days_left=4, sugerido_al_ingreso=30),
                            _item(title='Bien')])
        self.assertIn('Vas bien: 1 de tus 2 productos están cubiertos', out['html'])
        self.assertIn('Te alcanza para 4 días', out['html'])

    def test_lo_que_ya_viaja_en_una_colecta_no_se_marca_como_urgente(self):
        out = self._correr([_item(title='En colecta', status='critical', total_incoming=50, in_preparation_stock=50,
                                  cobertura_post_colecta=20, fecha_ingreso='2026-10-22')], self._prox())
        self.assertIn('Todo bajo control', out['html'])
        self.assertNotIn('Atención', out['html'])

    def test_un_articulo_pausado_en_ml_no_cuenta_como_urgente_ni_en_el_total(self):
        out = self._correr([_item(title='Pausado', status='paused', pausado=True, current_stock=0, sugerido_al_ingreso=20),
                            _item(title='Bien')])
        self.assertIn('Todo bajo control', out['html'])
        self.assertNotIn('Atención', out['html'])
        self.assertNotIn('Pausado', out['html'])

    def test_stock_suficiente_dice_para_cuantos_dias_y_avisa_si_ml_podria_cobrar(self):
        def fila(**kw):
            base = dict(id=3, title='Mix', sku='07011', sobrestock=True, current_stock=4, vpd=0.01, ventas_30d=2, covered_days_left=400)
            base.update(kw)
            return self._correr([_item(**base), _item(id=9, sku='Z', sobrestock=True)])['html']
        chico = fila()                       # 4 u. con 2 ventas en 30 días: 60 días reales, no 400
        self.assertIn('title="Stock estimado para 60 días."', chico)
        self.assertIn('promedio de 30 días', chico)
        self.assertIn('4 ÷ 0,07 = 60 días', chico)
        self.assertNotIn('400 días', chico)
        mucho = fila(current_stock=300, vpd=1, ventas_30d=30)     # 300 días de venta
        self.assertIn('title="Stock estimado para 300 días."', mucho)
        self.assertIn('title="Atención: supera los 60 días de almacenamiento. Mercado Libre no lo informa explícitamente por API, pero podría generarte cargos por exceso de stock almacenado."', mucho)
        sano = fila(current_stock=30, vpd=1, ventas_30d=30)      # 30 días: sin alerta
        self.assertIn('title="Stock estimado para 30 días."', sano)
        sin_ventas = fila(current_stock=5, vpd=0, ventas_30d=0)
        self.assertIn('Stock estimado: sin ventas en los últimos 30 días.', sin_ventas)

    def test_el_listado_muestra_en_que_colectas_esta_cada_producto(self):
        harness = r"""
const vm = require('vm');
const ctx = { document: { getElementById: () => null }, setInterval: () => 1, Date, Math, String, console };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('colectasData = ' + process.argv[2] + ';', ctx);
const it = { sku: '07011' };
process.stdout.write(JSON.stringify({
  html: vm.runInContext('htmlColectasDeItem(' + JSON.stringify(it) + ')', ctx), n: vm.runInContext('colectasDeItem(' + JSON.stringify(it) + ').length', ctx),
  otro: vm.runInContext('colectasDeItem({ sku: "999" }).length', ctx),
  prep: vm.runInContext('htmlPreparacionPorColecta(' + JSON.stringify(it) + ')', ctx),
  num: vm.runInContext('[numeroColecta({codigo:"ML-79759779"}), numeroColecta({codigo:"COL-FULL-20261012-002"})]', ctx)
}));
"""
        cols = [{'id': 1, 'codigo': 'ML-78889570', 'fecha_retiro': '2026-10-19', 'productos': [{'sku': '07011', 'unidades': 40}]},
                {'id': 2, 'codigo': 'ML-79759779', 'fecha_retiro': '2026-10-26', 'productos': [{'sku': '07011', 'unidades': 10}, {'sku': '5', 'unidades': 3}]},
                {'id': 3, 'codigo': 'COL-X', 'fecha_retiro': '2026-11-02', 'productos': [{'sku': '5', 'unidades': 3}]}]
        r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps(cols)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d['n'], 2)
        self.assertEqual(d['otro'], 0)
        self.assertIn('<b>#78889570</b></div>', d['html'])
        self.assertNotIn('+40 u.', d['html'])
        self.assertIn('<b>#79759779</b></div>', d['html'])
        self.assertIn('+40 en preparación', d['prep'])
        self.assertIn('+10 en preparación', d['prep'])
        self.assertNotIn('COL-X', d['html'])
        self.assertEqual(d['num'], ['#79759779', 'COL-FULL-20261012-002'])

    def test_cada_fila_se_puede_identificar_y_abre_su_grafico(self):
        it = _item(id=7, title='Granola', sku='06032', sobrestock=True, covered_days_left=667, current_stock=4000, vpd=6,
                   inventory_id='RCUM58244', item_id='MLA1', channels=[{'item_id': 'MLA1', 'listing_type': 'gold_pro', 'status': 'active'},
                                                                      {'item_id': 'MLA2', 'is_catalog': True, 'status': 'paused'}])
        html = self._correr([it, _item(id=8, sku='X', sobrestock=True, covered_days_left=100)])['html']
        for frase in ('data-copiar="06032"', 'data-copiar="RCUM58244"', '>MLA1</a> Premium', '>MLA2</a> Catálogo (pausada)', 'https://articulo.mercadolibre.com.ar/MLA1',
                      'abrirGraficoDeProducto(7)', 'En Full 4.000 u.', 'vendés 6 u. por día', '4.000 ÷ 6 = 667 días'):
            self.assertIn(frase, html, frase)

    def test_la_barra_explica_que_es_cada_color_solo_de_los_que_aparecen(self):
        todo = self._correr([_item(), _item(status='critical', sugerido_al_ingreso=1), _item(status='warning', sugerido_al_ingreso=1)])['html']
        self.assertIn('<b>Tranquilos:</b> tienen stock suficiente, o ya hay una colecta en camino que los cubre y solo falta esperar que entre.', todo)
        self.assertIn('<b>Conviene mandar pronto:</b>', todo)
        self.assertIn('<b>Urgentes:</b>', todo)
        solo_ok = self._correr([_item(), _item()])['html']
        self.assertIn('<b>Tranquilos:</b>', solo_ok)
        self.assertNotIn('<b>Urgentes:</b>', solo_ok)
        self.assertNotIn('<b>Conviene mandar pronto:</b>', solo_ok)

    def test_el_detalle_de_tranquilos_dice_que_los_cubre_la_colecta(self):
        harness = r"""
const vm = require('vm');
const tip = { style: {}, innerHTML: '' };
const barra = { classList: { add() {} } };
const ctx = { document: { getElementById: id => id === 'pc-tip' ? tip : null, createElement: () => tip, body: { appendChild() {} },
              querySelectorAll: () => [] }, setInterval: () => 1, Date, Math, String, console,
              window: { innerWidth: 1000, innerHeight: 800 } };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('grupoBarraPanel = { tranquilos: ' + process.argv[2] + ' };', ctx);
ctx.__ev = { currentTarget: { parentElement: barra, classList: { add() {} } }, clientX: 10, clientY: 10 };
vm.runInContext('mostrarDetalleSegmento(__ev, "tranquilos")', ctx);
process.stdout.write(tip.innerHTML);
"""
        items = [{'title': 'Con colecta', 'current_stock': 0, 'total_incoming': 300, 'covered_days_left': 40},
                 {'title': 'Con stock', 'current_stock': 90, 'total_incoming': 0, 'covered_days_left': 60}]
        r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps(items)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        html = r.stdout
        self.assertIn('ya tienen una colecta en camino que los cubre', html)
        self.assertIn('40 días', html)
        self.assertIn('0 en Full + 300 en colectas', html)
        self.assertLess(html.index('Con colecta'), html.index('Con stock'))   # primero al que menos le dura

    def test_el_conteo_de_la_leyenda_cierra_con_el_total(self):
        out = self._correr([_item(), _item(), _item(status='critical', sugerido_al_ingreso=1),
                            _item(status='warning', sugerido_al_ingreso=1), _item(sobrestock=True, covered_days_left=99)])
        for texto in ('3 tranquilos', '1 conviene mandar pronto', '1 urgentes'):   # los que tienen de más cuentan entre los tranquilos
            self.assertIn(texto, out['html'])
        hero = out['html'].split('Qué hacer hoy')[0]
        self.assertNotIn('tienen de más', hero)                                   # ya no es una franja de la información principal
        self.assertNotIn('data-grupo="deMas"', hero)

    # ── colecta ──
    def test_tarjeta_de_colecta_cerrada_dice_que_ya_no_se_puede_cambiar(self):
        out = self._correr([_item(in_preparation_stock=100, total_incoming=100, cobertura_post_colecta=20,
                                  fecha_ingreso='2026-10-22')], self._prox(abierta=False))
        self.assertIn('Tu colecta del lunes 19/10', out['html'])
        self.assertIn('COL-7', out['html'])
        self.assertIn('1 producto, 100 unidades', out['html'])
        self.assertIn('Ya no se puede cambiar: cerró el jueves 09/01 a las 09:40', out['html'])
        self.assertIn('Entra a Full el jueves 22/10', out['html'])
        self.assertIn('pc-cerrada', out['html'])

    def test_tarjeta_de_colecta_abierta_dice_hasta_cuando_y_cuanto_falta(self):
        out = self._correr([_item(in_preparation_stock=10, total_incoming=10, cobertura_post_colecta=20)], self._prox())
        self.assertIn('Podés modificarla hasta el', out['html'])
        self.assertIn('faltan', out['html'])
        self.assertNotIn('pc-cerrada', out['html'])

    def test_colecta_abierta_ofrece_editarla_y_cerrada_solo_verla(self):
        it = _item(in_preparation_stock=10, total_incoming=10, cobertura_post_colecta=20)
        abierta = dict(self._prox(), id=7)
        self.assertIn('abrirModalEditarEnvio(7)', self._correr([it], abierta)['html'])
        cerrada = dict(self._prox(abierta=False), id=7)
        out = self._correr([it], cerrada)['html']
        self.assertNotIn('abrirModalEditarEnvio', out)
        self.assertIn('Ver detalle', out)

    def test_la_tarjeta_muestra_los_cuatro_pasos_y_marca_donde_esta(self):
        it = _item(in_preparation_stock=10, total_incoming=10, cobertura_post_colecta=20)
        for paso in ('Propuesta', 'Armada en ML', 'Retirada', 'Recibida'):
            self.assertIn('>' + paso + '</li>', self._correr([it], self._prox(codigo='ML-1'))['html'])
        de_ml = self._correr([it], self._prox(codigo='ML-78889570'))['html']
        self.assertIn('pc-paso-hecho">Propuesta', de_ml)
        self.assertIn('pc-paso-actual">Armada en ML', de_ml)
        self.assertIn('https://vendedores.mercadolibre.com.ar/shipping/inbounds/78889570/details', de_ml)
        self.assertIn('Ver en ML ↗', de_ml)
        self.assertIn('avisarHorarioColecta(', de_ml)
        propia = self._correr([it], self._prox(codigo='COL-FULL-1'))['html']
        self.assertIn('pc-paso-actual">Propuesta', propia)
        self.assertIn('https://vendedores.mercadolibre.com.ar/shipping/inbounds"', propia)
        self.assertIn('Gestión Full en ML ↗', propia)

    def test_tarjeta_de_colecta_recibida_lo_dice_simple_y_marca_el_paso(self):
        it = _item(in_preparation_stock=10, total_incoming=10, cobertura_post_colecta=20)
        col = {'id': 3, 'codigo': 'ML-78889570', 'estado': 'in_transit', 'etapa': 'recibida', 'unidades_en_proceso': 57,
               'fecha_retiro': '2026-10-19', 'fecha_ingreso': '2026-10-22', 'limite_edicion': '2020-10-16T09:44:00-03:00',
               'abierta': False, 'de_ml': True, 'total_unidades': 785, 'productos': []}
        html = self._correr([it], None, [col])['html']
        self.assertIn('pc-paso-actual">Recibida', html)
        self.assertIn('Mercado Libre ya la recibió y la está procesando', html)
        self.assertIn('faltan poner a la venta 57 unidades', html)
        self.assertNotIn('Entra a Full el', html)
        self.assertNotIn('está en camino', html)
        en_camino = dict(col, etapa='retirada', unidades_en_proceso=0)
        html = self._correr([it], None, [en_camino])['html']
        self.assertIn('pc-paso-actual">Retirada', html)
        self.assertIn('Ya salió: está en camino a Full.', html)
        self.assertIn('Entra a Full el', html)

    def test_el_calendario_marca_recibida_en_la_fecha_real_y_ingresa_en_la_estimada(self):
        from datetime import date
        it = _item(in_preparation_stock=10, total_incoming=10, cobertura_post_colecta=20)
        hoy = date.today().isoformat()
        base = {'id': 3, 'codigo': 'ML-78889570', 'estado': 'in_transit', 'fecha_retiro': hoy, 'fecha_ingreso': hoy,
                'limite_edicion': '2020-10-16T09:44:00-03:00', 'abierta': False, 'de_ml': True, 'total_unidades': 10, 'productos': []}
        recibida = self._correr([it], None, [dict(base, etapa='recibida', unidades_en_proceso=5, ingreso_estimado=False)])['html']
        self.assertIn('Recibida 9570', recibida)
        self.assertNotIn('Ingresa 9570', recibida)
        self.assertIn('fecha real', recibida)
        en_camino = self._correr([it], None, [dict(base, etapa='retirada', ingreso_estimado=True)])['html']
        self.assertIn('Ingresa 9570', en_camino)
        self.assertNotIn('Recibida 9570', en_camino)

    def test_comparar_con_la_propuesta(self):
        harness = (
            "const vm=require('vm');const ctx={document:{getElementById:()=>null},setInterval:()=>1,Date,Math,String,console};"
            "vm.createContext(ctx);vm.runInContext(require('fs').readFileSync(process.argv[1],'utf8')+';'+'this.f=compararConPropuesta;',ctx);"
            "const r=[[100,100],[90,100],[50,100],[200,100],[10,0],[10,null]].map(a=>ctx.f(a[0],a[1]).estado);"
            "process.stdout.write(JSON.stringify(r));"
        )
        r = subprocess.run([NODE, '-e', harness, self.src_path], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ['ok', 'ok', 'corto', 'demas', 'demas', 'sinDato'])

    # ── varias colectas y calendario ──
    def _col(self, id, retiro_dias, abierta, de_ml=True, estado='scheduled', codigo=None):
        from datetime import date, timedelta
        hoy = date.today()
        retiro = hoy + timedelta(days=retiro_dias)
        limite = (retiro - timedelta(days=1)).isoformat() + ('T23:00:00-03:00' if abierta else 'T00:01:00-03:00')
        if not abierta:
            limite = (hoy - timedelta(days=1)).isoformat() + 'T09:44:00-03:00'
        return {'id': id, 'codigo': codigo or ('ML-%d' % (79000000 + id)), 'estado': estado, 'fecha_retiro': retiro.isoformat(),
                'limite_edicion': limite, 'abierta': abierta, 'fecha_ingreso': (retiro + timedelta(days=3)).isoformat(),
                'de_ml': de_ml, 'total_unidades': 400,
                'productos': [{'titulo': 'Dátil', 'sku': '12072', 'unidades': 100}, {'titulo': 'Nueces', 'sku': '01011', 'unidades': 300}]}

    def test_con_varias_colectas_hay_calendario_y_una_tarjeta_por_colecta(self):
        cols = [self._col(3, 2, False), self._col(4, 11, True)]
        html = self._correr([_item()], None, cols)['html']
        self.assertIn('Calendario de colectas', html)
        self.assertEqual(len(re.findall(r'class="pc-banner[ "]', html)), 2)
        self.assertIn('id="colecta-3"', html)
        self.assertIn('id="colecta-4"', html)

    def test_cada_colecta_marca_limite_retiro_e_ingreso(self):
        html = self._correr([_item()], None, [self._col(4, 11, True)])['html']
        for texto in ('Límite 0004', 'Retiro 0004', 'Ingresa 0004'):
            self.assertIn(texto, html)

    def test_la_cerrada_se_ve_cerrada_y_la_abierta_ofrece_editar(self):
        cols = [self._col(3, 2, False), self._col(4, 11, True)]
        html = self._correr([_item()], None, cols)['html']
        cerrada = html.split('id="colecta-3"')[1].split('id="colecta-4"')[0]
        abierta = html.split('id="colecta-4"')[1]
        self.assertIn('Ya no se puede cambiar', cerrada)
        self.assertNotIn('abrirModalEditarEnvio(3)', cerrada)
        self.assertIn('abrirModalEditarEnvio(4)', abierta)
        self.assertIn('pc-cerrada', html.split('id="colecta-3"')[0][-60:])

    def test_si_hay_una_abierta_el_ajuste_apunta_a_ella(self):
        corto = _item(title='Dátil', in_preparation_stock=100, total_incoming=100, cobertura_post_colecta=9, aviso_ajuste_units=170)
        pendiente = _item(title='Pasas', status='critical', current_stock=2, days_left=1, sugerido_al_ingreso=48)
        cols = [self._col(3, 2, False), self._col(4, 11, True)]
        html = self._correr([corto, pendiente], None, cols)['html']
        self.assertIn('Todavía podés ajustarlo en la colecta del', html)
        self.assertIn('Agregar 48 u. a la colecta del', html)
        self.assertNotIn('ajustalo en la siguiente', html)

    def test_si_todas_estan_cerradas_el_ajuste_va_a_la_siguiente(self):
        corto = _item(title='Dátil', in_preparation_stock=100, total_incoming=100, cobertura_post_colecta=9, aviso_ajuste_units=170)
        html = self._correr([corto], None, [self._col(3, 2, False)])['html']
        self.assertIn('ajustalo en la siguiente', html)

    def test_colecta_en_camino_no_ofrece_editar(self):
        html = self._correr([_item()], None, [self._col(5, 1, False, estado='in_transit')])['html']
        self.assertIn('en camino a Full', html)
        self.assertNotIn('abrirModalEditarEnvio', html)

    def test_retiro_e_ingreso_se_arrastran_aunque_ml_haya_cerrado(self):
        html = self._correr([_item()], None, [self._col(3, 2, False), self._col(4, 11, True)])['html']
        self.assertEqual(html.count('draggable="true"'), 4)   # retiro e ingreso de cada colecta
        self.assertIn("arrastrarMarca(event, 3, 'retiro')", html)
        self.assertIn("arrastrarMarca(event, 3, 'ingreso')", html)

    def test_el_limite_no_se_arrastra_y_la_que_ya_salio_solo_mueve_el_ingreso(self):
        html = self._correr([_item()], None, [self._col(5, 1, False, estado='in_transit')])['html']
        self.assertIn("arrastrarMarca(event, 5, 'ingreso')", html)
        self.assertNotIn("arrastrarMarca(event, 5, 'retiro')", html)
        self.assertNotIn("'limite')", html)

    def test_la_caja_del_calculo_va_debajo_de_la_grilla(self):
        html = self._correr([_item()], None, [self._col(4, 11, True)])['html']
        self.assertGreater(html.index('id="pc-cal-impacto"'), html.index('pc-cal-grilla'))

    def test_un_cambio_propuesto_se_ve_punteado_y_pide_confirmar(self):
        from datetime import date, timedelta
        col = self._col(4, 11, True)
        nueva = (date.today() + timedelta(days=13)).isoformat()
        out = self._correr([_item()], None, [col], {'4': {'retiro': nueva}})['html']
        self.assertIn('pc-pendiente', out)
        self.assertIn('Cambios propuestos (todavía sin confirmar)', out)
        self.assertIn('confirmarCambiosCalendario()', out)
        self.assertIn('descartarCambiosCalendario()', out)
        self.assertNotIn('Cambios propuestos', self._correr([_item()], None, [col])['html'])

    def test_el_ingreso_acompana_al_retiro_salvo_que_se_mueva_a_mano(self):
        harness = r"""
const vm = require('vm');
const ctx = { document: { getElementById: () => null }, setInterval: () => 1, Date, Math, String, console };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('colectasData = [' + process.argv[2] + ']; cambiosPendientes = {};', ctx);
const c = vm.runInContext('colectasData[0]', ctx);
const a = vm.runInContext('fechasConCambio(colectasData[0], { retiro: "2026-10-30" })', ctx);
const b = vm.runInContext('fechasConCambio(colectasData[0], { retiro: "2026-10-30", ingreso: "2026-11-05" })', ctx);
const d = vm.runInContext('diaHabilAnteriorISO("2026-10-19")', ctx);
process.stdout.write(JSON.stringify({ a, b, d }));
"""
        col = {'id': 4, 'fecha_retiro': '2026-10-28', 'fecha_ingreso': '2026-10-31'}
        r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps(col)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['a'], {'retiro': '2026-10-30', 'ingreso': '2026-11-02'})
        self.assertEqual(out['b'], {'retiro': '2026-10-30', 'ingreso': '2026-11-05'})
        self.assertEqual(out['d'], '2026-10-16')   # el límite de un lunes es el viernes

    def test_los_dias_pasados_no_reciben_colectas(self):
        html = self._correr([_item()], None, [self._col(4, 11, True)])['html']
        self.assertIn('ondrop="soltarEnDia(event,', html)
        celdas = html.split('class="pc-cal-dia')
        pasadas = [c for c in celdas if c.startswith(' pc-cal-pasado')]
        self.assertTrue(pasadas)
        self.assertTrue(all('ondrop' not in c.split('</div>')[0] for c in pasadas))

    def test_clic_en_la_marca_edita_si_esta_abierta_y_si_no_va_a_la_tarjeta(self):
        harness = r"""
const vm = require('vm'); const log = [];
const ctx = { log, document: { getElementById: () => null }, setInterval: () => 1, Date, Math, String, console,
              abrirModalEditarEnvio: id => log.push('editar' + id) };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('colectasData = ' + process.argv[2] + '; irAColecta = id => log.push("ir" + id);', ctx);
vm.runInContext('clicEnMarca(4); clicEnMarca(3);', ctx);
process.stdout.write(JSON.stringify(log));
"""
        datos = json.dumps([{'id': 4, 'abierta': True, 'estado': 'scheduled'}, {'id': 3, 'abierta': False, 'estado': 'scheduled'}])
        r = subprocess.run([NODE, '-e', harness, self.src_path, datos], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ['editar4', 'ir3'])

    def _impacto(self, item, c, nueva):
        harness = r"""
const vm = require('vm');
const ctx = { document: { getElementById: () => null }, setInterval: () => 1, Date, Math, String, console };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('itemsData = ' + process.argv[2] + '; colectasData = [' + process.argv[3] + '];', ctx);
const r = vm.runInContext('impactoDeMover(colectasData[0], ' + JSON.stringify(process.argv[4]) + ', new Date(2026, 9, 17))', ctx);
const html = vm.runInContext('htmlImpactoMovimiento(colectasData[0], ' + JSON.stringify(process.argv[4]) + ')', ctx);
const texto = vm.runInContext('textoImpactoMovimiento(colectasData[0], ' + JSON.stringify(process.argv[4]) + ')', ctx);
process.stdout.write(JSON.stringify({ r, html, texto }));
"""
        p = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps([item]), json.dumps(c), nueva],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    COL = {'id': 4, 'codigo': 'ML-79759779', 'estado': 'scheduled', 'fecha_retiro': '2026-10-28', 'fecha_ingreso': '2026-10-31',
           'productos': [{'titulo': 'Dátil', 'sku': '12072', 'unidades': 100}]}

    def test_mover_un_dia_mas_tarde_aumenta_lo_que_hace_falta(self):
        item = {'sku': '12072', 'vpd': 10, 'current_stock': 300, 'target_stock_days': 30, 'total_incoming': 100}
        out = self._impacto(item, self.COL, '2026-10-29')
        f = out['r']['filas'][0]
        self.assertEqual((f['antes'], f['despues']), (140, 150))
        self.assertEqual(out['r']['totalDelta'], 10)
        self.assertEqual(out['r']['nuevoIngreso'], '2026-11-01')
        self.assertEqual(f['cobertura'], 25)
        self.assertIn('(+10)', out['html'])   # el texto exacto depende del día en que se corre
        self.assertIn('necesitás', out['html'])
        self.assertIn('1 día más tarde', out['texto'])

    def test_mover_antes_baja_lo_que_hace_falta(self):
        item = {'sku': '12072', 'vpd': 10, 'current_stock': 300, 'target_stock_days': 30, 'total_incoming': 100}
        out = self._impacto(item, self.COL, '2026-10-27')
        self.assertEqual(out['r']['totalDelta'], -10)
        self.assertIn('(-10)', out['html'])

    def test_si_el_producto_se_queda_sin_stock_antes_de_entrar_lo_dice(self):
        item = {'sku': '12072', 'vpd': 10, 'current_stock': 100, 'target_stock_days': 30, 'total_incoming': 100}
        out = self._impacto(item, self.COL, '2026-10-29')
        self.assertTrue(out['r']['filas'][0]['sinStock'])
        self.assertIn('sin stock antes de entrar', out['html'])

    def test_sin_ventas_no_inventa_numeros(self):
        item = {'sku': '12072', 'vpd': 0, 'current_stock': 100, 'target_stock_days': 30, 'total_incoming': 100}
        out = self._impacto(item, self.COL, '2026-10-29')
        self.assertEqual(out['r']['filas'], [])
        self.assertIn('No tengo ventas', out['html'])

    def test_el_calendario_trae_la_caja_del_impacto_y_las_armadas_en_enviobot_avisan_que_falta_ml(self):
        html = self._correr([_item()], None, [self._col(4, 11, True, de_ml=False, codigo='COL-FULL-1')])['html']
        self.assertIn('id="pc-cal-impacto"', html)
        self.assertIn('Falta cargarla en Mercado Libre', html)
        self.assertNotIn('Falta cargarla en Mercado Libre', self._correr([_item()], None, [self._col(4, 11, True)])['html'])

    def test_el_detalle_de_tienen_de_mas_explica_y_muestra_dias_no_stock_en_cero(self):
        harness = r"""
const vm = require('vm');
const tip = { style: {}, innerHTML: '' };
const barra = { classList: { add() {} } };
const ctx = { document: { getElementById: id => id === 'pc-tip' ? tip : null, createElement: () => tip, body: { appendChild() {} },
              querySelectorAll: () => [] }, setInterval: () => 1, Date, Math, String, console,
              window: { innerWidth: 1000, innerHeight: 800 } };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('grupoBarraPanel = { deMas: ' + process.argv[2] + ' };', ctx);
const ev = { currentTarget: { parentElement: barra, classList: { add() {} } }, clientX: 10, clientY: 10 };
ctx.__ev = ev;
vm.runInContext('mostrarDetalleSegmento(__ev, "deMas")', ctx);
process.stdout.write(tip.innerHTML);
"""
        items = [{'title': 'Poco', 'current_stock': 50, 'total_incoming': 0, 'covered_days_left': 60},
                 {'title': 'Nueces', 'current_stock': 0, 'total_incoming': 300, 'covered_days_left': 267}]
        r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps(items)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        html = r.stdout
        self.assertIn('Tienen de más: no mandes más por ahora', html)
        self.assertIn('alcanza para mucho más que tu objetivo', html)
        self.assertIn('267 días', html)
        self.assertIn('0 en Full + 300 en colectas', html)
        self.assertLess(html.index('Nueces'), html.index('Poco'))   # primero el que más le sobra

    def _proy(self, expr, item, colectas):
        harness = r"""
const vm = require('vm');
const ctx = { document: { getElementById: () => null }, setInterval: () => 1, Date, Math, String, console };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('itemsData = [' + process.argv[2] + ']; colectasData = ' + process.argv[3] + ';', ctx);
const r = vm.runInContext(process.argv[4], ctx);
process.stdout.write(JSON.stringify(r));
"""
        r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps(item), json.dumps(colectas), expr],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    ITEM = {'sku': '12072', 'title': 'Dátil', 'vpd': 10, 'current_stock': 100, 'lead_time_days': 3, 'transit_delay_days': 2, 'buffer_days': 2, 'target_stock_days': 15}

    def _col_proy(self, dia, unidades, id=4):
        from datetime import date, timedelta
        return {'id': id, 'fecha_ingreso': (date.today() + timedelta(days=dia)).isoformat(), 'productos': [{'sku': '12072', 'unidades': unidades}]}

    def test_proyeccion_baja_lo_que_se_vende_y_sube_cuando_entra_la_colecta(self):
        r = self._proy('proyeccionProducto(itemsData[0], colectasData, new Date(), 0)', self.ITEM, [self._col_proy(5, 300)])
        stock = [p['stock'] for p in r['puntos']]
        self.assertEqual(stock[0], 100)
        self.assertEqual(stock[4], 60)
        self.assertEqual(stock[5], 50 + 300)       # día 5: llegaron 300
        self.assertEqual(r['umbral'], 70)          # 10 por día x (3 + 2 + 2) días

    def test_nunca_baja_de_cero_y_marca_el_quiebre(self):
        r = self._proy('proyeccionProducto(itemsData[0], colectasData, new Date(), 0)', self.ITEM, [])
        self.assertEqual(min(p['stock'] for p in r['puntos']), 0)
        self.assertEqual(r['quiebreDia'], 10)
        self.assertTrue(r['sinStockAntes'])

    def test_el_dia_de_reponer_cuenta_la_colecta_que_ya_viene(self):
        sin = self._proy('proyeccionProducto(itemsData[0], colectasData, new Date(), 0)', self.ITEM, [])
        con = self._proy('proyeccionProducto(itemsData[0], colectasData, new Date(), 0)', self.ITEM, [self._col_proy(5, 300)])
        self.assertEqual(sin['reponerDia'], 3)       # sin colecta: ya está por debajo del nivel enseguida
        self.assertGreater(con['reponerDia'], 20)    # con 300 u. entrando, lo que hay que reponer es mucho más adelante
        self.assertFalse(con['sinStockAntes'])

    def test_la_demora_de_ml_atrasa_el_momento_en_que_queda_en_venta(self):
        con0 = self._proy('proyeccionProducto(itemsData[0], colectasData, new Date(), 0)', self.ITEM, [self._col_proy(5, 300)])
        con2 = self._proy('proyeccionProducto(itemsData[0], colectasData, new Date(), 2)', self.ITEM, [self._col_proy(5, 300)])
        self.assertEqual(con0['llegadas'][0]['dia'], 5)
        self.assertEqual((con2['llegadas'][0]['ingresoDia'], con2['llegadas'][0]['dia']), (5, 7))
        self.assertEqual(con2['puntos'][7]['stock'], 30 + 300)

    def _juntos(self, n_productos, estado='{}', dias=42):
        harness = r"""
const vm = require('vm');
const ctx = { document: { getElementById: () => null }, setInterval: () => 1, Date, Math, String, console };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('itemsData = ' + process.argv[2] + '; colectasData = ' + process.argv[3] + ';', ctx);
const html = vm.runInContext('htmlTodosJuntos(colectasData[0], colectasData, new Date(), ' + process.argv[5] + ', 2, ' + process.argv[4] + ')', ctx);
process.stdout.write(html);
"""
        items, prods = [], []
        for i in range(n_productos):
            sku = 'S%02d' % i
            items.append(dict(self.ITEM, sku=sku, title='Prod %d' % i, vpd=2 + i, current_stock=20 * (n_productos - i)))
            prods.append({'sku': sku, 'titulo': 'Prod %d' % i, 'unidades': 100})
        col = {'id': 4, 'codigo': 'ML-79759779', 'fecha_ingreso': self._col_proy(8, 1)['fecha_ingreso'], 'productos': prods}
        r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps(items), json.dumps([col]), estado, str(dias)],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_todos_juntos_tiene_leyenda_ejes_con_nombre_zoom_y_tabla(self):
        html = self._juntos(3)
        self.assertIn('Días de venta que le quedan', html)             # eje Y con nombre
        self.assertIn('Hora de reponer: menos de', html)
        self.assertIn('Tu objetivo', html)
        self.assertIn('en venta el', html)                              # la raya vertical dice qué es
        self.assertEqual(html.count('class="pc-chip '), 3)              # un botón por producto en la leyenda
        for i in range(3):
            self.assertIn('Prod %d</button>' % i, html)
        self.assertIn('cambiarRangoProyeccion(4, 14)', html)            # zoom
        self.assertIn('alternarTabla(4)', html)                         # vista como tabla
        # el mouse lo recibe la línea de cada producto (no una capa encima de todo): resalta, muestra SUS números y abre el detalle
        self.assertNotIn('class="pc-g-captura"', html)
        self.assertEqual(html.count('class="pc-g-hit"'), 3)
        self.assertIn('moverSobreSerie(event,', html)
        self.assertIn('salirDeSerie(', html)
        self.assertIn('abrirDetalleProducto(4, this.dataset.sku)', html)
        self.assertIn('class="pc-g-hover"', html)

    def test_el_cartelito_de_una_linea_muestra_solo_los_numeros_de_ese_producto(self):
        harness = r"""
const vm = require('vm');
const ctx = { document: { getElementById: () => null }, setInterval: () => 1, Date, Math, String, console };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('itemsData = ' + process.argv[2] + '; colectasData = ' + process.argv[3] + ';', ctx);
const r = vm.runInContext(`(function () {
  const hoy = new Date();
  const s = seriesDeColecta(colectasData[0], colectasData, hoy, 2)[0];
  return filasTooltipSerie(s, 5, hoy);
})()`, ctx);
process.stdout.write(JSON.stringify(r));
"""
        item = dict(self.ITEM, title='Dátil', vpd=10, current_stock=100)
        col = {'id': 4, 'codigo': 'ML-1', 'fecha_ingreso': self._col_proy(3, 1)['fecha_ingreso'],
               'productos': [{'sku': '12072', 'titulo': 'Dátil', 'unidades': 200}]}
        r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps([item]), json.dumps([col])], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d['titulo'], 'Dátil')
        self.assertEqual([f['clave'].split(' el ')[0] for f in d['filas']], ['de venta le quedan', 'en Full', 'vendés por día'])
        self.assertEqual(d['filas'][0]['valor'], '25 días')      # día 5: 100 - 50 + 200 (entra el día 5) = 250 u. / 10 por día
        self.assertTrue(d['filas'][1]['valor'].startswith('250'))
        self.assertEqual(d['filas'][2]['valor'], '10 u.')
        self.assertTrue(d['nota'])

    def test_solo_cinco_productos_van_en_color_el_resto_en_gris(self):
        html = self._juntos(8)
        self.assertEqual(len(re.findall(r'class="pc-g-serie pc-s[0-4]"', html)), 5)
        self.assertEqual(len(re.findall(r'class="pc-g-serie pc-g-gris"', html)), 3)
        self.assertNotIn('pc-s5', html)                                 # nunca un sexto color
        self.assertEqual(html.count('pc-chip-gris'), 3)

    def test_los_colores_siguen_al_producto_y_se_pueden_cambiar(self):
        html = self._juntos(8, '{"slots": {"S07": 0, "S00": 3}}')
        self.assertEqual(len(re.findall(r'class="pc-g-serie pc-s\d"', html)), 2)
        self.assertRegex(html, r'class="pc-g-serie pc-s0" points="[^"]*" data-k="S07"')
        self.assertRegex(html, r'class="pc-g-serie pc-s3" points="[^"]*" data-k="S00"')
        self.assertEqual(len(re.findall(r'class="pc-g-serie pc-g-gris"', self._juntos(8, '{"slots": {}}'))), 8)

    def test_el_trazo_sube_de_golpe_cuando_entra_la_colecta(self):
        html = self._juntos(1)
        puntos = re.search(r'class="pc-g-serie pc-s0" points="([^"]+)"', html).group(1).split()
        xs = [p.split(',')[0] for p in puntos]
        self.assertTrue(any(xs[i] == xs[i + 1] for i in range(len(xs) - 1)))   # dos puntos con el mismo x: escalón vertical

    def test_la_tabla_dice_lo_mismo_que_el_grafico(self):
        html = self._juntos(3, '{"tabla": true}')
        self.assertIn('<table class="pc-table pc-tabla-proy">', html)
        self.assertIn('Reponer antes del', html)
        self.assertIn('En 6 semanas', html)
        self.assertNotIn('<svg', html)
        self.assertIn('Ver gráfico', html)

    def test_las_referencias_van_en_pildora_y_la_zona_de_reposicion_en_el_detalle(self):
        html = self._juntos(2)
        self.assertIn('class="pc-g-pil"', html)

    def test_la_paleta_son_cinco_colores_y_estan_en_ambos_modos(self):
        css = _leer(os.path.join('css', 'style.css'))
        self.assertEqual(len(re.findall(r'--serie-\d+:', css)), 10)   # 5 en oscuro + 5 en claro
        self.assertNotIn('--serie-6', css)
        for h in ('#3987e5', '#008300', '#d55181', '#9085e9', '#199e70',   # modo oscuro, validado
                  '#2a78d6', '#e87ba4', '#6250d6', '#1baf7a'):               # modo claro, validado
            self.assertIn(h, css)

    def test_el_detalle_grande_explica_cada_numero(self):
        harness = r"""
const vm = require('vm');
let creado = null;
const doc = { getElementById: () => null, body: { appendChild: el => { creado = el; } },
              createElement: () => ({ setAttribute() {}, remove() {} }), addEventListener() {} };
const ctx = { document: doc, setInterval: () => 1, Date, Math, String, console };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('itemsData = ' + process.argv[2] + '; colectasData = ' + process.argv[3] + ';', ctx);
vm.runInContext('abrirDetalleProducto(4, "12072")', ctx);
process.stdout.write(creado ? creado.innerHTML : '');
"""
        item = dict(self.ITEM)
        r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps([item]), json.dumps([self._col_proy(8, 150)])],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        html = r.stdout
        self.assertIn('pc-graf-grande', html)
        for frase in ('Hoy: 100 u.', 'Zona de reposición: menos de 70 u.', '+150 u. en venta el', 'Reponer antes del',
                      'Vendés por día', 'Hoy en Full', 'Tu objetivo', '3 de preparación + 2 de flete + 2 de colchón = 7 días',
                      'Qué le entra', 'Qué hacer', 'Cómo leer el gráfico', 'La franja gris'):
            self.assertIn(frase, html, frase)

    def test_el_grafico_se_abre_desde_el_listado_aunque_no_haya_colecta(self):
        harness = r"""
const vm = require('vm');
let creado = null;
const doc = { getElementById: () => null, body: { appendChild: el => { creado = el; } },
              createElement: () => ({ setAttribute() {}, remove() {} }), addEventListener() {} };
const ctx = { document: doc, setInterval: () => 1, Date, Math, String, console };
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext('itemsData = ' + process.argv[2] + '; colectasData = [];', ctx);
vm.runInContext('abrirGraficoDeProducto(1)', ctx);
process.stdout.write(creado ? creado.innerHTML : '');
"""
        for item, esperado in ((dict(self.ITEM, id=1), 'pc-graf-grande'),
                               (dict(self.ITEM, id=1, vpd=0), 'no vendió en los últimos 30 días'),
                               (dict(self.ITEM, id=1, pausado=True), 'Pausada en Mercado Libre')):
            r = subprocess.run([NODE, '-e', harness, self.src_path, json.dumps([item])], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(esperado, r.stdout)

    def test_sin_ventas_no_se_proyecta(self):
        item = dict(self.ITEM, vpd=0)
        self.assertIsNone(self._proy('proyeccionProducto(itemsData[0], colectasData, new Date(), 0)', item, []))

    def test_cada_colecta_trae_los_graficos_por_producto_y_juntos(self):
        item = dict(self.ITEM)
        col = self._col(4, 11, True)
        col['productos'] = [{'titulo': 'Dátil', 'sku': '12072', 'unidades': 150}]
        html = self._correr([item], None, [col])['html']
        self.assertIn('Ver cómo se van agotando los productos', html)
        self.assertIn('Uno por producto', html)
        self.assertIn('data-vista="juntos"', html)               # por defecto: todos juntos
        self.assertLess(html.index('>Todos juntos<'), html.index('>Uno por producto<'))
        self.assertIn('abrirDetalleProducto(4, this.dataset.sku)', html)   # el gráfico chico se agranda al tocarlo
        self.assertIn('Todos juntos', html)
        self.assertIn('<svg class="pc-graf', html)
        self.assertIn('Reponer antes del', html)

    def test_el_mensaje_de_mover_avisa_que_hay_que_cambiar_ml(self):
        js = _leer(os.path.join('js', 'app.js'))
        self.assertIn('Después tenés que hacer el mismo cambio en Mercado Libre', js)

    def test_calendario_escapa_los_codigos(self):
        html = self._correr([_item()], None, [self._col(6, 5, True, codigo='ML-<script>x')])['html']
        self.assertNotIn('<script>', html)

    def test_sin_lista_de_colectas_se_usa_la_tarjeta_de_siempre(self):
        out = self._correr([_item(in_preparation_stock=10, total_incoming=10, cobertura_post_colecta=20)], self._prox())['html']
        self.assertNotIn('Calendario de colectas', out)
        self.assertIn('Tu colecta del', out)

    def test_sin_colecta_armada_no_hay_tarjeta(self):
        out = self._correr([_item(status='critical', sugerido_al_ingreso=5)], None)
        self.assertNotIn('Tu colecta', out['html'])

    def test_los_productos_de_la_colecta_quedan_a_un_clic(self):
        out = self._correr([_item(in_preparation_stock=100, total_incoming=100, cobertura_post_colecta=23.4,
                                  fecha_ingreso='2026-10-23')], self._prox())
        self.assertIn('Ver los 1 productos', out['html'])
        self.assertIn('23 días', out['html'])
        self.assertIn('23/10', out['html'])

    def test_galpon_aparece_solo_si_hay_estado_cargado(self):
        con = self._correr([_item(in_preparation_stock=50, total_incoming=50, prep_item_id=7, prep_status='packing')], self._prox())
        self.assertIn('<th>Galpón</th>', con['html'])
        self.assertIn('<option value="packing" selected>Envasando</option>', con['html'])
        self.assertIn('cambiarEstadoGalpon(7, this)', con['html'])
        sin = self._correr([_item(in_preparation_stock=50, total_incoming=50)], self._prox())
        self.assertNotIn('Galpón', sin['html'])

    def test_estado_de_galpon_raro_no_rompe_el_html(self):
        out = self._correr([_item(in_preparation_stock=5, total_incoming=5, prep_item_id=3, prep_status='"><script>')], self._prox())
        self.assertNotIn('<script>', out['html'])

    # ── ajustar ──
    def test_ajustar_solo_aparece_donde_la_colecta_quedo_corta(self):
        corto = _item(title='Dátil', in_preparation_stock=100, total_incoming=100, cobertura_post_colecta=9,
                      aviso_ajuste_units=170, target_stock_days=15)
        bien = _item(title='Nueces', in_preparation_stock=300, total_incoming=300, cobertura_post_colecta=26)
        out = self._correr([corto, bien], self._prox())
        self.assertIn('Ya en tu colecta, pero conviene ajustar', out['html'])
        seccion = out['html'].split('Ya en tu colecta, pero conviene ajustar')[-1]
        self.assertIn('Con 100 u. cubrís 9 días: convendría 170', seccion)
        self.assertNotIn('Nueces', seccion)
        self.assertIn('Todavía podés ajustarlo', seccion)

    def test_ajustar_con_colecta_cerrada_manda_a_la_siguiente(self):
        corto = _item(in_preparation_stock=100, total_incoming=100, cobertura_post_colecta=9, aviso_ajuste_units=170)
        out = self._correr([corto], self._prox(abierta=False))
        self.assertIn('ya no se puede cambiar: ajustalo en la siguiente', out['html'])

    # ── tienen de más ──
    def test_tienen_de_mas_lista_solo_los_marcados(self):
        out = self._correr([_item(title='Sobra mucho', sobrestock=True, covered_days_left=267), _item(title='Normal')])
        self.assertIn('Artículos con stock suficiente', out['html'])
        seccion = out['html'].split('Artículos con stock suficiente')[-1]
        self.assertIn('Sobra mucho', seccion)
        self.assertIn('Stock suficiente', seccion)
        self.assertNotIn('Stock suficiente:', seccion)
        self.assertNotIn('Normal', seccion)

    # ── barras ──
    def test_la_barra_marca_el_objetivo_y_se_acota_al_doble(self):
        out = self._correr([_item(title='Sobra', sobrestock=True, covered_days_left=900, target_stock_days=15)])
        self.assertIn('width: 100.0%', out['html'])   # nunca pasa del 100 %
        self.assertIn('pc-bar-meta', out['html'])     # la raya del objetivo
        medio = self._correr([_item(status='warning', days_left=15, target_stock_days=15, sugerido_al_ingreso=3)])
        self.assertIn('width: 50.0%', medio['html'])  # estar justo en el objetivo = mitad de barra

    def test_sin_jerga_vieja_en_la_pantalla(self):
        out = self._correr([_item(status='critical', sugerido_al_ingreso=5, title='A'),
                            _item(sobrestock=True, covered_days_left=99, title='B')], self._prox())
        for jerga in ('Por planificar', 'Con exceso de stock', 'Pronóstico', 'Radar'):
            self.assertNotIn(jerga, out['html'])

    # ── seguridad ──
    def test_datos_de_afuera_se_escapan(self):
        out = self._correr([_item(title='<img src=x onerror=alert(1)>', sku='"><b>', status='critical',
                                  sugerido_al_ingreso=5, variation_name='<i>x</i>')])
        self.assertNotIn('<img', out['html'])
        propio = out['html'].replace('<div class="pc-leyenda-expl"><b>', '')   # la leyenda de la barra usa <b> a propósito
        self.assertIn('&quot;&gt;&lt;b&gt;', propio)   # el SKU malicioso queda escapado
        self.assertNotIn('data-copiar=""><b>', propio)
        self.assertNotIn('<i>x', out['html'])
        self.assertIn('&lt;img', out['html'])

    def test_codigo_de_colecta_raro_se_escapa(self):
        prox = self._prox(codigo='<script>x</script>')
        out = self._correr([_item(in_preparation_stock=1, total_incoming=1, cobertura_post_colecta=20)], prox)
        self.assertNotIn('<script>', out['html'])


HARNESS_SUGERIDO = r"""
const vm = require('vm');
const src = process.argv[2], caso = JSON.parse(process.argv[3]);
const ctx = { itemsData: caso.items, Math, String, console };
vm.createContext(ctx);
vm.runInContext(src + '\nthis.__f = sugeridoEdicion;', ctx);
process.stdout.write(JSON.stringify(caso.consultas.map(c => ctx.__f(c))));
"""


@unittest.skipUnless(NODE, 'Node no está instalado')
class TestSugeridoEnEdicion(unittest.TestCase):
    """El Sugerido de Editar envío aparece solo si la colecta quedó corta contra el objetivo."""

    @classmethod
    def setUpClass(cls):
        js = _leer(os.path.join('js', 'app.js'))
        cls.src = _corte(js, 'const TOLERANCIA_AVISO_AJUSTE', 'const ESTADOS_GALPON')
        cls.tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
        cls.tmp.write(HARNESS_SUGERIDO)
        cls.tmp.close()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.tmp.name)

    def _sug(self, vivos, consultas):
        r = subprocess.run([NODE, self.tmp.name, self.src, json.dumps({'items': vivos, 'consultas': consultas})],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def _vivo(self, **kw):
        base = dict(sku='A', item_id='MLA1', inventory_id=None, vpd=10, stock_al_ingreso=0, target_stock_days=15)
        base.update(kw)
        return base

    def test_colecta_corta_sugiere_para_llegar_al_objetivo(self):
        # 100 u. a 10/día cubren 10 días de 15 (menos del 80 %): conviene 150.
        self.assertEqual(self._sug([self._vivo()], [{'sku': 'A', 'units_to_send': 100}]), [150])

    def test_colecta_suficiente_no_sugiere(self):
        # 130 u. cubren 13 días: dentro de la tolerancia (12 o más).
        self.assertEqual(self._sug([self._vivo()], [{'sku': 'A', 'units_to_send': 130}]), [None])
        self.assertEqual(self._sug([self._vivo()], [{'sku': 'A', 'units_to_send': 400}]), [None])

    def test_descuenta_lo_que_queda_en_full_al_ingreso(self):
        # Quedan 40 al ingreso: 100 u. cubren 14 días, bien.
        self.assertEqual(self._sug([self._vivo(stock_al_ingreso=40)], [{'sku': 'A', 'units_to_send': 100}]), [None])

    def test_sin_datos_vivos_o_sin_ventas_no_sugiere(self):
        self.assertEqual(self._sug([self._vivo()], [{'sku': 'OTRO', 'units_to_send': 1}]), [None])
        self.assertEqual(self._sug([self._vivo(vpd=0)], [{'sku': 'A', 'units_to_send': 1}]), [None])
        self.assertEqual(self._sug([self._vivo(stock_al_ingreso=None)], [{'sku': 'A', 'units_to_send': 1}]), [None])

    def test_busca_por_inventory_id_y_por_publicacion(self):
        vivo = self._vivo(sku='', inventory_id='INV9', item_id='MLA9')
        self.assertEqual(self._sug([vivo], [{'inventory_id': 'INV9', 'units_to_send': 50}]), [150])
        self.assertEqual(self._sug([vivo], [{'item_id': 'MLA9', 'units_to_send': 50}]), [150])

    def test_la_tolerancia_es_la_misma_que_en_el_backend(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import proyeccion
        self.assertEqual(proyeccion.TOLERANCIA_AVISO, 0.8)
        self.assertIn('const TOLERANCIA_AVISO_AJUSTE = 0.8;', self.src)

    def test_la_pantalla_de_edicion_ya_no_usa_el_sugerido_guardado(self):
        js = _leer(os.path.join('js', 'app.js'))
        fn = js[js.index('function renderizarItemsEdicion'):js.index('window.renderizarItemsEdicion')]
        self.assertIn('sugeridoEdicion(it)', fn)
        self.assertNotIn('it.suggested_units', fn)


class TestEditarEnvioSinBultos(unittest.TestCase):
    """Pedido de Guillermo (2026-10-16): en Editar envío no van Unid./Caja ni Bultos."""

    def test_la_tabla_de_edicion_no_tiene_esas_columnas(self):
        html = _leer('index.html')
        self.assertIn('editarEnvioTbody', html)
        self.assertNotIn('Unid. / Caja', html)
        self.assertNotIn('>Bultos<', html)
        self.assertNotIn('editarEnvioTotalBoxes', html)

    def test_las_filas_ya_no_pintan_cajas_y_el_vacio_ocupa_las_5_columnas(self):
        js = _leer(os.path.join('js', 'app.js'))
        fn = js[js.index('function renderizarItemsEdicion'):js.index('window.renderizarItemsEdicion')]
        self.assertNotIn('editarItemCajas_', fn)
        self.assertNotIn('onCambiarUnitsPerBoxEdicion', fn)
        self.assertIn('colspan="5"', fn)


class TestBotonesVisibles(unittest.TestCase):
    """Pedido de Guillermo (2026-10-17): Armar colecta e Historial de envíos tienen que estar arriba y a la vista."""

    def test_los_botones_estan_arriba_de_todo_el_panel(self):
        html = _leer('index.html')
        barra = html.index('class="pc-toolbar"')
        self.assertLess(barra, html.index('id="panelColecta"'))
        self.assertLess(barra, html.index('id="cardStockPrincipal"'))
        zona = html[barra:html.index('id="panelColecta"')]
        self.assertIn('abrirModalColecta()', zona)
        self.assertIn('Armar colecta', zona)
        # el historial pasó al menú lateral, siempre a la vista
        self.assertIn('onclick="abrirHistorialColectas()"', html)
        self.assertIn('data-label="Historial de envíos"', html)

    def test_el_contador_del_historial_sigue_existiendo_una_sola_vez(self):
        html = _leer('index.html')
        self.assertEqual(html.count('id="topbarHistorialBadge"'), 1)
        self.assertEqual(html.count('id="btnHistorialColectasTop"'), 1)

    def test_no_quedan_los_botones_viejos_escondidos_en_la_tarjeta_grande(self):
        html = _leer('index.html')
        tarjeta = html[html.index('id="cardStockPrincipal"'):]
        self.assertNotIn('Armar Colecta', tarjeta[:3000])
        self.assertIn('Todos tus productos', tarjeta[:3000])
        self.assertNotIn('Pronóstico y Rotación', html)

    def test_las_tarjetas_viejas_siguen_en_el_codigo_pero_ocultas(self):
        html = _leer('index.html')
        self.assertIn('<div class="status-bar" hidden>', html)
        for ident in ('statTotal', 'statOk', 'statWarning', 'statCritical'):
            self.assertIn(f'id="{ident}"', html)  # el JS las sigue llenando


class TestPanelEstatico(unittest.TestCase):
    def test_el_contenedor_esta_en_el_html_antes_de_la_tabla(self):
        html = _leer('index.html')
        self.assertLess(html.index('id="panelColecta"'), html.index('id="cardStockPrincipal"'))

    def test_se_dibuja_despues_de_cargar_los_datos(self):
        js = _leer(os.path.join('js', 'app.js'))
        self.assertRegex(js, r'recalcularTodo\(\);\s*renderizarPanelColecta\(\);')

    def test_el_css_del_panel_usa_variables_y_no_colores_fijos(self):
        css = _leer(os.path.join('css', 'style.css'))
        bloque = css[css.index('/* ── Panel de colecta'):]
        self.assertIsNone(re.search(r'#[0-9a-fA-F]{3,8}\b', bloque))


if __name__ == '__main__':
    unittest.main()
