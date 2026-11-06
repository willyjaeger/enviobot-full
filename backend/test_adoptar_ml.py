"""Productos del PDF que todavía no son Full (caso real: Nueces Pecan, 2026-11-06). Sin red ni base: ML se simula con las respuestas reales."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adoptar_ml  # noqa: E402
import esquema  # noqa: E402
import pdf_envio_ml  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


class _Resp:
    def __init__(self, codigo, cuerpo=None):
        self.status_code, self._cuerpo = codigo, cuerpo

    def json(self):
        return self._cuerpo


class _Http:
    """Responde por URL; anota cada pedido para comprobar que no se gasta cuota de más."""
    def __init__(self, respuestas):
        self.respuestas, self.pedidos = respuestas, []

    def get(self, url, headers=None, timeout=None):
        self.pedidos.append((url, headers["Authorization"]))
        r = self.respuestas.get(url)
        if isinstance(r, Exception):
            raise r
        return r or _Resp(404, {})


INVENTARIO = adoptar_ml.MELI_API + "/inventories/YFSK63695/stock/fulfillment"
ITEM = adoptar_ml.MELI_API + "/items/MLA4154119370"
# Respuestas reales de ML del 2026-11-06 (recortadas a lo que importa).
INV_REAL = {"inventory_id": "YFSK63695", "total": 0, "external_references": [{"type": "item", "id": "MLA4154119370", "variation_id": None}]}
ITEM_REAL = {"id": "MLA4154119370", "title": "Nueces Premium Mr Nut Pecan 1 Kilo", "status": "active", "sub_status": [], "seller_custom_field": None,
             "inventory_id": "YFSK63695", "listing_type_id": "gold_special", "thumbnail": "http://x/t.jpg", "permalink": "http://x/p", "variations": []}
PDF_PECAN = {"codigo_ml": "YFSK63695", "sku": "", "titulo": "Nueces Premium Mr Nut Pecan 1 Kilo", "unidades": 24}
CREDS = [{"id": 1, "token": "token-de-prueba"}]


class TestResolver(unittest.TestCase):
    def test_la_pecan_se_resuelve_por_su_codigo_ml(self):
        http = _Http({INVENTARIO: _Resp(200, INV_REAL), ITEM: _Resp(200, ITEM_REAL)})
        nuevos, sin = adoptar_ml.resolver([PDF_PECAN], CREDS, http)
        self.assertEqual(sin, [])
        f = nuevos[0]["fila"]
        self.assertEqual((f["item_id"], f["inventory_id"], f["status"], f["variation_id"]), ("MLA4154119370", "YFSK63695", "active", ""))
        self.assertEqual(f["title"], "Nueces Premium Mr Nut Pecan 1 Kilo")
        self.assertEqual(f["sku"], "")                       # sin SKU en ML: queda vacío, no inventado
        self.assertEqual(nuevos[0]["unidades"], 24)          # lo que dice el PDF no se toca
        self.assertEqual(f["current_stock_full"], 0)

    def test_solo_lee_dos_pedidos_por_producto_y_sin_reintentos(self):
        http = _Http({INVENTARIO: _Resp(200, INV_REAL), ITEM: _Resp(200, ITEM_REAL)})
        adoptar_ml.resolver([PDF_PECAN], CREDS, http)
        self.assertEqual(len(http.pedidos), 2)
        self.assertTrue(all(u.startswith(adoptar_ml.MELI_API) and "/users/" not in u for u, _ in http.pedidos))

    def test_si_ml_no_lo_conoce_queda_como_no_encontrado(self):
        for resp in (_Resp(403, {}), _Resp(404, {}), _Resp(429, {}), _Resp(200, {"external_references": []})):
            nuevos, sin = adoptar_ml.resolver([PDF_PECAN], CREDS, _Http({INVENTARIO: resp}))
            self.assertEqual((nuevos, sin), ([], [PDF_PECAN]))

    def test_si_falla_la_red_no_rompe_la_carga(self):
        nuevos, sin = adoptar_ml.resolver([PDF_PECAN], CREDS, _Http({INVENTARIO: OSError("sin red")}))
        self.assertEqual((nuevos, sin), ([], [PDF_PECAN]))

    def test_con_dos_cuentas_prueba_la_segunda_si_la_primera_no_es_la_duena(self):
        class DosCuentas(_Http):
            def get(self, url, headers=None, timeout=None):
                if headers["Authorization"].endswith("ajena"):
                    self.pedidos.append((url, headers["Authorization"]))
                    return _Resp(403, {})
                return super().get(url, headers, timeout)
        http = DosCuentas({INVENTARIO: _Resp(200, INV_REAL), ITEM: _Resp(200, ITEM_REAL)})
        nuevos, sin = adoptar_ml.resolver([PDF_PECAN], [{"id": 9, "token": "ajena"}, {"id": 2, "token": "propia"}], http)
        self.assertEqual(len(nuevos), 1)
        self.assertEqual(nuevos[0]["fila"]["ml_credential_id"], 2)

    def test_no_consulta_mas_de_diez_productos(self):
        muchos = [dict(PDF_PECAN, codigo_ml="COD%02d" % i) for i in range(15)]
        http = _Http({})
        nuevos, sin = adoptar_ml.resolver(muchos, CREDS, http)
        self.assertEqual(len(sin), 15)
        self.assertEqual(len(http.pedidos), adoptar_ml.MAX_PRODUCTOS)

    def test_el_sku_sale_del_campo_de_ml_o_del_atributo(self):
        con_campo = dict(ITEM_REAL, seller_custom_field=" 03055 ")
        con_atributo = dict(ITEM_REAL, attributes=[{"id": "SELLER_SKU", "value_name": "03055"}])
        for cuerpo in (con_campo, con_atributo):
            nuevos, _ = adoptar_ml.resolver([PDF_PECAN], CREDS, _Http({INVENTARIO: _Resp(200, INV_REAL), ITEM: _Resp(200, cuerpo)}))
            self.assertEqual(nuevos[0]["fila"]["sku"], "03055")

    def test_una_variacion_trae_su_nombre_y_su_sku(self):
        inv = {"external_references": [{"type": "item", "id": "MLA4154119370", "variation_id": 777}]}
        cuerpo = dict(ITEM_REAL, variations=[{"id": 777, "seller_custom_field": "V-1", "attribute_combinations": [{"value_name": "500 g"}]}])
        nuevos, _ = adoptar_ml.resolver([PDF_PECAN], CREDS, _Http({INVENTARIO: _Resp(200, inv), ITEM: _Resp(200, cuerpo)}))
        f = nuevos[0]["fila"]
        self.assertEqual((f["variation_id"], f["variation_name"], f["sku"]), ("777", "500 g", "V-1"))


class TestConElEmparejado(unittest.TestCase):
    def test_lo_que_no_estaba_en_el_catalogo_ahora_se_encuentra_y_lo_demas_sigue_igual(self):
        filas = [{"id": 1, "item_id": "MLA1", "variation_id": "", "variation_name": None, "inventory_id": "AAAA11111", "sku": "01011", "title": "Nueces", "current_stock_full": 5}]
        pdf = [{"codigo_ml": "AAAA11111", "sku": "01011", "titulo": "Nueces", "unidades": 10}, PDF_PECAN]
        encontrados, sin_match = pdf_envio_ml.emparejar_productos(pdf, filas)
        self.assertEqual([p["codigo_ml"] for p in sin_match], ["YFSK63695"])
        nuevos, sin = adoptar_ml.resolver(sin_match, CREDS, _Http({INVENTARIO: _Resp(200, INV_REAL), ITEM: _Resp(200, ITEM_REAL)}))
        self.assertEqual(sin, [])
        # la comparación contra una colecta ya cargada lo ve como producto agregado, con su Código ML (el SKU está vacío)
        cambios = pdf_envio_ml.comparar_con_existente(
            [{"id": 7, "sku": "01011", "inventory_id": "AAAA11111", "variation_id": "", "title": "Nueces", "units_to_send": 10}], encontrados + nuevos)
        self.assertEqual([a["codigo_ml"] for a in cambios["agregados"]], ["YFSK63695"])


class _Cur:
    def __init__(self, tiene_sub_status=True):
        self.sqls, self.tiene = [], tiene_sub_status

    def execute(self, sql, params=()):
        self.sqls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return {"COUNT(*)": 1 if self.tiene else 0}


class TestGuardar(unittest.TestCase):
    def setUp(self):
        esquema.olvidar()

    def _nuevos(self):
        return adoptar_ml.resolver([PDF_PECAN], CREDS, _Http({INVENTARIO: _Resp(200, INV_REAL), ITEM: _Resp(200, ITEM_REAL)}))[0]

    def test_inserta_el_producto_con_stock_cero_y_se_puede_repetir(self):
        cur = _Cur()
        adoptar_ml.guardar(cur, 45, self._nuevos())
        sql, params = cur.sqls[0]
        self.assertIn("INSERT INTO full_items", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)           # si el worker ya lo trajo, se actualiza y no se duplica
        self.assertNotIn("is_monitored", sql)                    # queda con el valor de siempre (monitoreado)
        self.assertEqual(params[0], 45)
        self.assertIn("MLA4154119370", params)
        self.assertIn("YFSK63695", params)

    def test_sin_nuevos_no_escribe_nada(self):
        cur = _Cur()
        adoptar_ml.guardar(cur, 45, [])
        self.assertEqual(cur.sqls, [])


class TestEnElServidor(unittest.TestCase):
    def test_la_vista_previa_no_escribe_en_el_catalogo(self):
        app = open(os.path.join(AQUI, "app.py"), encoding="utf-8").read()
        tramo = app[app.index("def import_pdf") if "def import_pdf" in app else app.index("_adoptar_ml.resolver"):]
        previa = tramo.index('return jsonify({"ok": True, "preview": True, "envio": resumen})')
        self.assertIn("_adoptar_ml.resolver(", tramo[:previa])          # leer de ML sí, en la vista previa
        self.assertNotIn("_adoptar_ml.guardar(", tramo[:previa])        # escribir no
        self.assertIn("_adoptar_ml.guardar(cur, account_id, nuevos_catalogo)", tramo[previa:])

    def test_los_productos_agregados_a_una_colecta_existente_se_reconocen_por_codigo_ml(self):
        app = open(os.path.join(AQUI, "app.py"), encoding="utf-8").read()
        self.assertIn('nuevos_codigos = {a["codigo_ml"] for a in cambios["agregados"]}', app)
        self.assertNotIn("nuevos_skus", app)

    def test_la_vista_previa_del_frontend_lo_dice_y_no_mete_html_sin_escapar(self):
        js = open(os.path.join(AQUI, "..", "frontend", "js", "app.js"), encoding="utf-8").read()
        fn = js[js.index("function htmlVistaPreviaPdf"):js.index("async function enviarPdfColecta")]
        self.assertIn("agregados_al_catalogo", fn)
        self.assertIn("sin SKU: cargalo en Mercado Libre", fn)
        self.assertIn("escapeHtml(p.titulo)", fn)


if __name__ == "__main__":
    unittest.main()
