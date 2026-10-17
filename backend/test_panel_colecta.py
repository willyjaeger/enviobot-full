"""Panel de colecta del frontend (cuenta regresiva, colecta en preparación, radar).
Ejecuta el JS real del panel con un DOM de mentira (hace falta Node; si no hay, se saltea).
Uso:  python backend/test_panel_colecta.py
"""
import json
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
        self.assertIn('Colecta en preparación (1)', out['html'])
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
        radar = out['html'].split('Para la próxima colecta')[1]
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
