"""Cuánto permite la cita de una colecta (pedido de Guillermo, 2026-11-01). Sin base."""
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cita_ml  # noqa: E402
import esquema  # noqa: E402
from test_panel_colecta import _leer  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


class TestRango(unittest.TestCase):
    def test_las_dos_colectas_reales_de_mercado_libre(self):
        # #81021895: 645 u. → "entre 451 y 839". #79759779: 755 u. declaradas → "entre 528 y 982".
        self.assertEqual(cita_ml.rango(645), (451, 839))
        self.assertEqual(cita_ml.rango(755), (528, 982))

    def test_no_se_mueve_con_el_total_actual_solo_con_lo_declarado(self):
        # La colecta de 755 u. se subió a 793 y Mercado Libre siguió mostrando 528 a 982.
        r = cita_ml.resumen({"total_declarado": 755, "total_units": 793})
        self.assertEqual((r["min"], r["max"]), (528, 982))

    def test_sin_total_no_hay_rango(self):
        for v in (None, 0, -5, "", "x"):
            self.assertIsNone(cita_ml.rango(v))

    def test_cuentas_exactas_sin_decimales_flotantes(self):
        self.assertEqual(cita_ml.rango(10), (7, 13))
        self.assertEqual(cita_ml.rango(100), (70, 130))
        self.assertEqual(cita_ml.rango(3), (2, 4))     # 2,1 baja a 2; 3,9 sube a 4


class TestEstado(unittest.TestCase):
    def test_dentro_debajo_y_arriba(self):
        self.assertEqual(cita_ml.estado(645, 451, 839)["estado"], "ok")
        self.assertEqual(cita_ml.estado(451, 451, 839)["estado"], "ok")
        self.assertEqual(cita_ml.estado(839, 451, 839)["estado"], "ok")
        bajo = cita_ml.estado(400, 451, 839)
        self.assertEqual((bajo["estado"], bajo["faltan"]), ("bajo", 51))
        alto = cita_ml.estado(900, 451, 839)
        self.assertEqual((alto["estado"], alto["sobran"]), ("alto", 61))


class TestResumen(unittest.TestCase):
    def test_lo_cargado_a_mano_manda_sobre_el_calculo(self):
        r = cita_ml.resumen({"total_declarado": 645, "cita_min": 500, "cita_max": 900})
        self.assertEqual((r["min"], r["max"], r["manual"]), (500, 900, True))

    def test_sin_datos_no_inventa(self):
        self.assertIsNone(cita_ml.resumen({}))
        self.assertIsNone(cita_ml.resumen({"total_declarado": None, "cita_min": 5, "cita_max": None}))


class TestRangoManualEnElPUT(unittest.TestCase):
    def test_sin_las_claves_no_cambia_nada(self):
        self.assertEqual(cita_ml.leer_manual({"items": []}), ("sin_cambio",))

    def test_dos_nulos_vuelven_al_calculo(self):
        self.assertEqual(cita_ml.leer_manual({"cita_min": None, "cita_max": None}), ("borrar",))

    def test_numeros_validos(self):
        self.assertEqual(cita_ml.leer_manual({"cita_min": "451", "cita_max": 839}), ("fijar", 451, 839))

    def test_rechaza_lo_que_no_sirve(self):
        for malo in ({"cita_min": 900, "cita_max": 800}, {"cita_min": "a", "cita_max": 5}, {"cita_min": 5},
                     {"cita_min": -1, "cita_max": 5}, {"cita_min": 1, "cita_max": 10 ** 9}):
            with self.assertRaises(ValueError, msg=str(malo)):
                cita_ml.leer_manual(malo)


class _Cur:
    def __init__(self, tiene_columnas=True):
        self.tiene, self.sqls = tiene_columnas, []

    def execute(self, sql, params=()):
        self.sqls.append((sql, params))

    def fetchone(self):
        return {"COUNT(*)": 1 if self.tiene else 0}


class TestGuardado(unittest.TestCase):
    def setUp(self):
        esquema.olvidar()

    def test_el_total_declarado_se_fija_una_sola_vez(self):
        cur = _Cur()
        cita_ml.fijar_declarado(cur, 4, 45, 755)
        sql, params = cur.sqls[-1]
        self.assertIn("total_declarado IS NULL", sql)    # si ya había uno, no lo pisa
        self.assertEqual(params, (755, 4, 45))

    def test_sin_las_columnas_no_hace_nada(self):
        cur = _Cur(False)
        cita_ml.fijar_declarado(cur, 4, 45, 755)
        cita_ml.guardar_manual(cur, 4, 45, ("fijar", 1, 2))
        self.assertFalse([s for s in cur.sqls if s[0].lstrip().upper().startswith("UPDATE")])

    def test_volver_al_calculo_borra_el_rango_manual(self):
        cur = _Cur()
        cita_ml.guardar_manual(cur, 4, 45, ("borrar",))
        self.assertEqual(cur.sqls[-1][1], (None, None, 4, 45))

    def test_sin_total_no_guarda_nada(self):
        cur = _Cur()
        cita_ml.fijar_declarado(cur, 4, 45, 0)
        self.assertEqual(cur.sqls, [])


class TestMigracion009(unittest.TestCase):
    def test_agrega_las_tres_columnas_y_se_puede_correr_dos_veces(self):
        sql = open(os.path.join(AQUI, "migration_009_cita_ml.sql"), encoding="utf-8").read()
        for col in ("total_declarado", "cita_min", "cita_max"):
            self.assertIn("COLUMN_NAME = '%s'" % col, sql)
            self.assertIn("ADD COLUMN %s INT NULL" % col, sql)
        self.assertEqual(sql.count("SELECT COUNT(*) FROM information_schema.COLUMNS"), 3)
        self.assertNotRegex(sql, r"(?i)\b(DROP|DELETE|TRUNCATE)\b")

    def test_el_servidor_usa_las_funciones_nuevas(self):
        app = open(os.path.join(AQUI, "app.py"), encoding="utf-8").read()
        self.assertEqual(app.count("_cita_ml.fijar_declarado("), 3)    # PDF existente, PDF nuevo y primera edición
        self.assertIn('shipment["cita"] = _cita_ml.resumen(shipment)', app)
        self.assertIn("_cita_ml.guardar_manual(", app)


class TestCitaEnElPanel(unittest.TestCase):
    """Mostrar cuánto permite la cita (30 % sobre lo declarado) y avisar si el total queda afuera."""

    def _js(self):
        return _leer(os.path.join('js', 'app.js'))

    def _ejecutar(self, expresion):
        import json
        js = self._js()
        fn = js[js.index('function rangoCitaML'):js.index('function citaVigenteEdicion')]
        r = subprocess.run(['node', '-e', fn + "\nconsole.log(JSON.stringify(%s));" % expresion],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_el_rango_del_panel_coincide_con_el_del_servidor_y_con_mercado_libre(self):
        r = self._ejecutar('[rangoCitaML(645), rangoCitaML(755), rangoCitaML(0)]')
        self.assertEqual(r, [{'min': 451, 'max': 839}, {'min': 528, 'max': 982}, None])
        for d in (3, 10, 645, 755, 1234):
            js_r = self._ejecutar('rangoCitaML(%d)' % d)
            self.assertEqual((js_r['min'], js_r['max']), cita_ml.rango(d))

    def test_avisa_cuando_el_total_queda_afuera(self):
        r = self._ejecutar('[estadoCitaML(645, {min:451,max:839}), estadoCitaML(400, {min:451,max:839}), estadoCitaML(900, {min:451,max:839})]')
        self.assertEqual([x['estado'] for x in r], ['ok', 'bajo', 'alto'])
        self.assertEqual((r[1]['faltan'], r[2]['sobran']), (51, 61))

    def test_solo_aparece_en_colectas_de_ml_abiertas_y_se_actualiza_con_los_totales(self):
        js = self._js()
        cuerpo = js[js.index('function renderizarCitaML'):js.index('function corregirCitaML')]
        self.assertIn('edicionCerrada', cuerpo)
        self.assertIn('/^ML-/i.test(codigoEnvioEnEdicion)', cuerpo)
        self.assertIn('Calculado', cuerpo)            # se dice que es un cálculo, no un dato de ML
        tot = js[js.index('function actualizarTotalesEdicion'):js.index('function onBuscarArticuloParaAgregar')]
        self.assertIn('renderizarCitaML()', tot)

    def test_lo_corregido_a_mano_viaja_al_guardar_y_se_reinicia_al_abrir(self):
        js = self._js()
        guardar = js[js.index('async function guardarEdicionEnvio'):js.index('window.guardarEdicionEnvio')]
        self.assertIn('cita_min', guardar)
        self.assertIn('citaCorregida !== undefined', guardar)
        abrir = js[js.index('async function abrirModalEditarEnvio'):js.index('window.abrirModalEditarEnvio')]
        self.assertIn('citaEnEdicion = sh.cita', abrir)
        self.assertIn('citaCorregida = undefined', abrir)

    def test_nada_del_servidor_se_mete_como_html_sin_escapar(self):
        js = self._js()
        cuerpo = js[js.index('function renderizarCitaML'):js.index('function corregirCitaML')]
        self.assertIn('Number(cita.min)', cuerpo)
        self.assertIn('escapeHtml(origen)', cuerpo)
        self.assertIn('escapeHtml(msg)', cuerpo)

    def test_si_no_entra_en_pantalla_los_botones_siguen_a_la_vista(self):
        # Con la caja de la cita y la lista de cambios la ventana se pasaba de alto y recortaba Guardar y Cancelar.
        html = _leer('index.html')
        self.assertIn('id="editarEnvioPie"', html)
        pie = html[html.index('id="editarEnvioPie"'):]
        self.assertIn('btnGuardarEdicionEnvio', pie[:1500])      # el pie es el que tiene los botones
        css = _leer(os.path.join('css', 'style.css'))
        self.assertRegex(css, r'#modalEditarEnvio \.modal-card \{[^}]*overflow-y: auto')
        self.assertRegex(css, r'#editarEnvioPie \{[^}]*position: sticky[^}]*bottom: 0')

    def test_la_caja_existe_y_usa_colores_de_variables(self):
        self.assertIn('id="editarEnvioCita"', _leer('index.html'))
        css = _leer(os.path.join('css', 'style.css'))
        bloque = css[css.index('/* Cita de la colecta'):]
        self.assertIsNone(re.search(r'#[0-9a-fA-F]{3,8}\b', bloque))


if __name__ == "__main__":
    unittest.main()
