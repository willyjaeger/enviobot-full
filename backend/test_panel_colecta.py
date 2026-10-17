"""Panel de colecta del frontend (cuenta regresiva, colecta en preparación, radar).
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
                sugerido_al_ingreso=0, cobertura_post_colecta=None, aviso_ajuste_units=None, fecha_ingreso=None)
    base.update(kw)
    return base


@unittest.skipUnless(NODE, 'Node no está instalado')
class TestPanelJS(unittest.TestCase):
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

    def test_sin_nada_que_mostrar_el_panel_se_oculta(self):
        out = self._correr([_item()])
        self.assertEqual(out['display'], 'none')

    def test_colecta_en_preparacion_muestra_cobertura_y_aviso(self):
        out = self._correr([_item(in_preparation_stock=100, total_incoming=100, cobertura_post_colecta=23.4,
                                  aviso_ajuste_units=129, fecha_ingreso='2026-10-23')])
        self.assertIn('En la colecta en preparación (1)', out['html'])
        self.assertIn('23 días', out['html'])
        self.assertIn('con 129 u. cubrís 30 días', out['html'])
        self.assertIn('23/10', out['html'])

    def test_radar_solo_lista_lo_que_no_esta_en_colecta(self):
        out = self._correr([
            _item(title='Sin colecta', status='critical', sugerido_al_ingreso=65),
            _item(title='Ya en colecta', status='critical', total_incoming=50, in_preparation_stock=50),
            _item(title='Todo bien', status='ok'),
        ])
        self.assertIn('Enviar 65 u.', out['html'])
        radar = out['html'].split('Por planificar')[1]
        self.assertIn('Sin colecta', radar)
        self.assertNotIn('Ya en colecta', radar)
        self.assertNotIn('Todo bien', out['html'])

    def test_exceso_de_stock_lista_solo_los_marcados_con_su_cobertura(self):
        out = self._correr([
            _item(title='Sobra mucho', sobrestock=True, current_stock=300, total_incoming=40, covered_days_left=62.4,
                  target_stock_days=30, umbral_sobrestock=45),
            _item(title='Normal', covered_days_left=20),
        ])
        self.assertIn('Con exceso de stock (1)', out['html'])
        exceso = out['html'].split('Con exceso de stock')[1]
        self.assertIn('Sobra mucho', exceso)
        self.assertIn('62 días', exceso)
        self.assertIn('+ 40 en camino', exceso)
        self.assertNotIn('Normal', out['html'])

    def test_galpon_aparece_solo_si_hay_estado_cargado(self):
        con = self._correr([_item(in_preparation_stock=50, total_incoming=50, prep_item_id=7, prep_status='packing')])
        self.assertIn('<th>Galpón</th>', con['html'])
        self.assertIn('<option value="packing" selected>Envasando</option>', con['html'])
        self.assertIn('cambiarEstadoGalpon(7, this)', con['html'])
        sin = self._correr([_item(in_preparation_stock=50, total_incoming=50)])
        self.assertNotIn('Galpón', sin['html'])

    def test_estado_de_galpon_raro_no_rompe_el_html(self):
        out = self._correr([_item(in_preparation_stock=5, total_incoming=5, prep_item_id=3, prep_status='"><script>')])
        self.assertNotIn('<script>', out['html'])

    def test_los_titulos_dicen_de_que_colecta_hablan(self):
        prox = {'fecha_retiro': '2026-10-19', 'limite_edicion': '2099-01-09T09:40:00-03:00',
                'segundos_restantes': 999999, 'abierta': True, 'codigo': 'COL-7'}
        out = self._correr([_item(in_preparation_stock=10, total_incoming=10, cobertura_post_colecta=20),
                            _item(title='Falta', status='critical', sugerido_al_ingreso=5)], prox)
        self.assertIn('Colecta del lunes 19/10 (COL-7)', out['html'])
        self.assertIn('En la colecta del lunes 19/10 (1)', out['html'])
        self.assertIn('Por planificar (1)', out['html'])
        self.assertIn('Todavía no están en ninguna colecta', out['html'])
        self.assertNotIn('próxima colecta', out['html'])

    def test_datos_de_afuera_se_escapan(self):
        out = self._correr([_item(title='<img src=x onerror=alert(1)>', sku='"><b>', status='critical',
                                  sugerido_al_ingreso=5)])
        self.assertNotIn('<img', out['html'])
        self.assertNotIn('<b>', out['html'])
        self.assertIn('&lt;img', out['html'])

    def test_banner_cerrado_cuando_paso_el_limite(self):
        prox = {'fecha_retiro': '2020-01-10', 'limite_edicion': '2020-01-09T09:40:00-03:00',
                'segundos_restantes': 0, 'abierta': False, 'codigo': 'COL-1'}
        out = self._correr([_item(status='critical', sugerido_al_ingreso=5)], prox)
        self.assertIn('pc-cerrada', out['html'])
        self.assertIn('no se puede modificar', out['html'])
        # el límite se escribe legible y en hora de Buenos Aires
        self.assertIn('jueves 09/01 a las 09:40', out['html'])

    def test_banner_abierto_muestra_cuanto_falta(self):
        prox = {'fecha_retiro': '2099-01-10', 'limite_edicion': '2099-01-09T09:40:00-03:00',
                'segundos_restantes': 999999, 'abierta': True, 'codigo': 'COL-2'}
        out = self._correr([_item(status='critical', sugerido_al_ingreso=5)], prox)
        self.assertNotIn('pc-cerrada', out['html'])
        self.assertIn('Faltan', out['html'])


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
