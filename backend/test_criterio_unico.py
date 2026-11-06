"""Un solo criterio para "cuánto mandar": el Resumen y Editar envío tienen que pedir lo mismo.

Pedido de Guillermo (2026-11-01): el Resumen pedía 3, 15, 8, 4 y 4 unidades de cinco productos que la colecta ML-81021895 ya cubría
(el servidor decía "no falta nada" para los cinco), y Editar envío mostraba otra cosa. Estos tests corren la app.js real con los
números reales de ese día (datos_prueba/panel_colecta_81021895.json).
"""
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
APP_JS = os.path.join(AQUI, '..', 'frontend', 'js', 'app.js')
DATOS = os.path.join(AQUI, 'datos_prueba', 'panel_colecta_81021895.json')
NODE = shutil.which('node')

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [rutaApp, rutaDatos, extra] = process.argv.slice(2);
const RAW = JSON.parse(fs.readFileSync(rutaDatos, 'utf8'));
const cambios = JSON.parse(extra || '{}');
(RAW.items || []).forEach(it => { if (cambios[it.sku]) Object.assign(it, cambios[it.sku]); });
const universal = () => new Proxy(function () {}, {
    get: (t, k) => (k === Symbol.toPrimitive ? () => '' : k === 'length' ? 0 : k === 'style' ? {} : k === 'classList' ? { add() {}, remove() {}, toggle() {}, contains() { return false; } } : universal()),
    apply: () => universal(), construct: () => universal(), set: () => true,
});
// El día de los datos reales (1/11/2026 a la noche): las fechas de la colecta ya pasaron hoy y la prueba no puede depender del reloj.
const AHORA = new Date('2026-11-01T21:34:00-03:00').getTime();
class FechaFija extends Date { constructor(...a) { if (a.length === 0) super(AHORA); else super(...a); } static now() { return AHORA; } }
const ctx = {
    console, Intl, Date: FechaFija, Math, JSON, Number, String, Array, Object, Map, Set, Promise, parseInt, parseFloat, isNaN, URLSearchParams,
    setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    document: universal(), localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, sessionStorage: { getItem: () => null, setItem() {} },
    navigator: { userAgent: 'node' }, location: { protocol: 'http:', href: 'http://x/', hash: '', search: '', pathname: '/' },
    history: { replaceState() {} }, fetch: async () => ({ ok: true, json: async () => ({}) }),
    addEventListener() {}, removeEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    innerWidth: 1200, requestAnimationFrame: () => 0, getComputedStyle: () => ({}), dispatchEvent: () => true,
};
ctx.window = ctx; ctx.self = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(rutaApp, 'utf8'), ctx, { filename: 'app.js' });
ctx.__RAW = RAW;
const salida = vm.runInContext(`(function () {
  itemsData = __RAW.items.map(it => adaptarItemDesdeBackend(it));
  colectasData = __RAW.colectas || []; colectasRecibidasData = [];
  const col = colectasData.find(c => c.abierta);
  const resumen = colectaAutomaticaVirtual().filas.map(f => ({ sku: f.it.sku, unidades: f.unidades }));
  const filas = col.productos.map(p => { const v = itemsData.find(x => x.sku === p.sku) || {};
      return { sku: p.sku, inventory_id: v.inventory_id, item_id: v.item_id, units_to_send: p.unidades }; });
  itemsOriginalesEdicion = filas.map(f => Object.assign({}, f));
  const editar = filas.map(f => ({ sku: f.sku, cargado: f.units_to_send, sugerido: sugeridoEdicion(f), dejar: sugeridoQuitarEdicion(f) }));
  return { resumen: resumen, editar: editar };
})()`, ctx);
process.stdout.write(JSON.stringify(salida));
"""


@unittest.skipUnless(NODE, 'Node no está instalado')
class TestCriterioUnico(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
        cls.tmp.write(HARNESS)
        cls.tmp.close()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.tmp.name)

    def _correr(self, cambios=None):
        r = subprocess.run([NODE, self.tmp.name, APP_JS, DATOS, json.dumps(cambios or {})],
                           capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_los_datos_reales_dicen_que_el_servidor_no_pedia_nada_para_los_cinco(self):
        with open(DATOS, encoding='utf-8') as f:
            datos = json.load(f)
        for it in datos['items']:
            self.assertEqual(it['sugerido_al_ingreso'], 0, it['sku'])

    def test_el_resumen_ya_no_pide_lo_que_la_colecta_cargada_cubre(self):
        # Antes pedía 02103: 3 u., 05142: 15 u., 06032: 8 u., 02101: 4 u. y 01031: 4 u.
        self.assertEqual(self._correr()['resumen'], [])

    def test_editar_envio_pide_lo_mismo_que_el_resumen_y_el_servidor(self):
        editar = {f['sku']: f for f in self._correr()['editar']}
        for sku in ('02103', '05142', '06032', '02101', '01031'):
            self.assertIsNone(editar[sku]['sugerido'], sku)
            self.assertIsNone(editar[sku]['dejar'], sku)
        # El servidor marcó exceso en el dátil (150 cargadas, recomendado 37): Editar envío propone dejar 37, igual que el aviso del Resumen.
        self.assertEqual(editar['12072']['dejar'], 37)

    def test_si_el_servidor_pide_unidades_las_pide_el_resumen_y_las_pide_editar_envio(self):
        r = self._correr({'05142': {'sugerido_al_ingreso': 12}})
        self.assertIn({'sku': '05142', 'unidades': 12}, r['resumen'])          # el Resumen pide 12
        editar = {f['sku']: f for f in r['editar']}
        self.assertEqual(editar['05142']['sugerido'], 29 + 12)                  # Editar envío: lo cargado (29) + lo que falta (12)

    def test_al_cargar_el_pdf_nuevo_el_servidor_recalcula_y_el_pedido_desaparece(self):
        # Antes de cargar el PDF con el cambio: faltaban 12. Después, la colecta ya las trae y el servidor dice 0.
        antes = self._correr({'05142': {'sugerido_al_ingreso': 12}})
        despues = self._correr({'05142': {'sugerido_al_ingreso': 0}})
        self.assertTrue(any(f['sku'] == '05142' for f in antes['resumen']))
        self.assertFalse(any(f['sku'] == '05142' for f in despues['resumen']))


if __name__ == '__main__':
    unittest.main()
