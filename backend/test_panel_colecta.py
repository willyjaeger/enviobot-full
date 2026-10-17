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
const src = process.argv[2], caso = JSON.parse(process.argv[3]);
const cont = { style: {}, innerHTML: '' };
const ctx = { document: { getElementById: id => id === 'panelColecta' ? cont : null },
              setInterval: () => 1, Date, Math, String, console };
ctx.itemsData = caso.items;
vm.createContext(ctx);
vm.runInContext(src + '\nthis.__render = renderizarPanelColecta;', ctx);
vm.runInContext('proximaColecta = ' + JSON.stringify(caso.prox), ctx);
ctx.__render();
process.stdout.write(JSON.stringify({ html: cont.innerHTML, display: cont.style.display }));
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
        cls.tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
        cls.tmp.write(HARNESS)
        cls.tmp.close()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.tmp.name)

    def _correr(self, items, prox=None):
        r = subprocess.run([NODE, self.tmp.name, self.src, json.dumps({'items': items, 'prox': prox})],
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

    def test_el_conteo_de_la_leyenda_cierra_con_el_total(self):
        out = self._correr([_item(), _item(), _item(status='critical', sugerido_al_ingreso=1),
                            _item(status='warning', sugerido_al_ingreso=1), _item(sobrestock=True, covered_days_left=99)])
        for texto in ('2 tranquilos', '1 conviene mandar pronto', '1 urgentes', '1 tienen de más'):
            self.assertIn(texto, out['html'])

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
        seccion = out['html'].split('Ya en tu colecta, pero conviene ajustar')[1]
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
        self.assertIn('Tienen de más (no mandes más por ahora)', out['html'])
        seccion = out['html'].split('Tienen de más (no mandes más por ahora)')[1]
        self.assertIn('Sobra mucho', seccion)
        self.assertIn('Tenés para 267 días', seccion)
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
        for jerga in ('Por planificar', 'exceso de stock', 'Pronóstico', 'Radar'):
            self.assertNotIn(jerga, out['html'])

    # ── seguridad ──
    def test_datos_de_afuera_se_escapan(self):
        out = self._correr([_item(title='<img src=x onerror=alert(1)>', sku='"><b>', status='critical',
                                  sugerido_al_ingreso=5, variation_name='<i>x</i>')])
        self.assertNotIn('<img', out['html'])
        self.assertNotIn('<b>', out['html'])
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
        self.assertIn('abrirHistorialColectas()', zona)
        self.assertIn('Armar colecta', zona)
        self.assertIn('Historial de envíos', zona)

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
