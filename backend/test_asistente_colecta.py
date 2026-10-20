"""Tests del asistente de colectas: la IA solo lee y propone; nada se escribe sin que el usuario lo aplique."""
import copy
import json
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asistente_colecta as a  # noqa: E402


def _prod(id_, sku, inv, sugerido=0, **extra):
    base = {"id": id_, "item_id": f"MLA{id_}", "sku": sku, "inventory_id": inv, "title": f"Producto {sku}", "status": "ok",
            "pausado": False, "current_stock_full": 10, "days_left": 12.0, "vpd_weighted": 1.0, "total_incoming": 0,
            "sugerido_al_ingreso": sugerido}
    base.update(extra)
    return base


PRODUCTOS = [_prod(1, "01011", "AAAA11111", 0), _prod(2, "05012", "BBBB22222", 5, status="out_of_stock"),
             _prod(3, "05142", "CCCC33333", 13), _prod(4, "07011", "DDDD44444", 2),
             _prod(5, "09999", "EEEE55555", 7, pausado=True)]
COLECTAS = [{"id": 4, "shipment_code": "ML-79759779", "status": "scheduled", "pickup_date": "2026-10-28"},
            {"id": 9, "shipment_code": "ML-1", "status": "delivered", "pickup_date": "2026-10-01"}]
DETALLES = {4: {"shipment": {"id": 4, "shipment_code": "ML-79759779", "status": "scheduled", "pickup_date": "2026-10-28", "cerrada_por_ml": False,
                              "limite_edicion": "2026-10-27T09:44:00-03:00"},
                "items": [{"sku": "01011", "inventory_id": "AAAA11111", "item_id": "MLA1", "title": "Producto 01011", "units_to_send": 200},
                          {"sku": "07011", "inventory_id": "DDDD44444", "item_id": "MLA4", "title": "Producto 07011", "units_to_send": 20}]}}


def _herramientas(detalles=None, productos=None):
    return a.Herramientas(productos=lambda: productos if productos is not None else PRODUCTOS, colectas=lambda: COLECTAS,
                          detalle=lambda sid: (detalles if detalles is not None else DETALLES).get(sid))


class TestLecturas(unittest.TestCase):
    def test_ver_productos_ignora_pausados_y_ordena_por_sugerido(self):
        r = _herramientas().ver_productos(False)
        self.assertNotIn("09999", [p["sku"] for p in r["productos"]])
        self.assertEqual(r["productos"][0]["sku"], "05142")   # 13 u., el que más necesita

    def test_ver_productos_solo_con_sugerencia(self):
        r = _herramientas().ver_productos(True)
        self.assertEqual(sorted(p["sku"] for p in r["productos"]), ["05012", "05142", "07011"])

    def test_ver_colectas_solo_las_vigentes_y_con_sus_productos(self):
        r = _herramientas().ver_colectas()["colectas"]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["id"], 4)
        self.assertTrue(r[0]["se_puede_modificar"])
        self.assertEqual({p["sku"]: p["unidades"] for p in r[0]["productos"]}, {"01011": 200, "07011": 20})


class TestPropuestaDeCambios(unittest.TestCase):
    def _proponer(self, cambios, **kw):
        res, prop = _herramientas(**kw).proponer_cambios_colecta(4, "porque sí", cambios)
        return res, prop

    def test_agregar_y_cambiar_y_quitar(self):
        res, prop = self._proponer([
            {"accion": "agregar", "sku": "05142", "inventory_id": "CCCC33333", "unidades": 13},
            {"accion": "cambiar", "sku": "01011", "inventory_id": "AAAA11111", "unidades": 250},
            {"accion": "quitar", "sku": "07011", "inventory_id": "DDDD44444", "unidades": 0}])
        self.assertTrue(res["ok"])
        por = {c["sku"]: c for c in prop["cambios"]}
        self.assertEqual((por["05142"]["antes"], por["05142"]["despues"]), (0, 13))
        self.assertEqual((por["01011"]["antes"], por["01011"]["despues"]), (200, 250))
        self.assertEqual((por["07011"]["antes"], por["07011"]["despues"]), (20, 0))
        self.assertEqual(prop["tipo"], "modificar")
        self.assertEqual(prop["shipment_id"], 4)

    def test_la_propuesta_lleva_el_id_del_panel_para_poder_aplicarla(self):
        _, prop = self._proponer([{"accion": "agregar", "sku": "05012", "inventory_id": "", "unidades": 5}])
        self.assertEqual(prop["cambios"][0]["producto_id"], 2)
        self.assertEqual(prop["cambios"][0]["inventory_id"], "BBBB22222")

    def test_no_se_agrega_algo_que_ya_esta_ni_se_cambia_algo_que_no_esta(self):
        res, prop = self._proponer([{"accion": "agregar", "sku": "01011", "inventory_id": "AAAA11111", "unidades": 5}])
        self.assertFalse(res["ok"])
        self.assertIsNone(prop)
        res, prop = self._proponer([{"accion": "cambiar", "sku": "05142", "inventory_id": "CCCC33333", "unidades": 5}])
        self.assertFalse(res["ok"])

    def test_unidades_invalidas_se_rechazan(self):
        for u in (0, -4, 100000):
            res, prop = self._proponer([{"accion": "agregar", "sku": "05142", "inventory_id": "CCCC33333", "unidades": u}])
            self.assertFalse(res["ok"], u)
            self.assertIsNone(prop)

    def test_una_colecta_cerrada_no_se_puede_modificar(self):
        cerrada = copy.deepcopy(DETALLES)
        cerrada[4]["shipment"]["cerrada_por_ml"] = True
        res, prop = self._proponer([{"accion": "agregar", "sku": "05142", "inventory_id": "CCCC33333", "unidades": 5}], detalles=cerrada)
        self.assertFalse(res["ok"])
        self.assertIsNone(prop)

    def test_sku_ambiguo_pide_el_codigo_ml(self):
        prods = PRODUCTOS + [_prod(6, "05142", "ZZZZ99999", 3)]
        res, prop = self._proponer([{"accion": "agregar", "sku": "05142", "inventory_id": "", "unidades": 5}], productos=prods)
        self.assertFalse(res["ok"])
        self.assertIn("inventory_id", json.dumps(res))

    def test_producto_inexistente(self):
        res, _ = self._proponer([{"accion": "agregar", "sku": "NOEXISTE", "inventory_id": "", "unidades": 5}])
        self.assertFalse(res["ok"])

    def test_cambios_que_no_cambian_nada_no_generan_propuesta(self):
        res, prop = self._proponer([{"accion": "cambiar", "sku": "01011", "inventory_id": "AAAA11111", "unidades": 200}])
        self.assertFalse(res["ok"])
        self.assertIsNone(prop)

    def test_colecta_inexistente(self):
        res, prop = _herramientas().proponer_cambios_colecta(77, "x", [{"accion": "agregar", "sku": "05142", "inventory_id": "", "unidades": 5}])
        self.assertFalse(res["ok"])


class TestColectaNueva(unittest.TestCase):
    def test_propuesta_de_colecta_nueva(self):
        res, prop = _herramientas().proponer_colecta_nueva("reposición", [{"sku": "05142", "inventory_id": "", "unidades": 13},
                                                                         {"sku": "05012", "inventory_id": "BBBB22222", "unidades": 5}])
        self.assertTrue(res["ok"])
        self.assertEqual(prop["tipo"], "nueva")
        self.assertEqual([(i["sku"], i["unidades"]) for i in prop["items"]], [("05142", 13), ("05012", 5)])

    def test_rechaza_repetidos_y_cantidades_malas(self):
        res, prop = _herramientas().proponer_colecta_nueva("x", [{"sku": "05142", "inventory_id": "", "unidades": 13},
                                                                {"sku": "05142", "inventory_id": "", "unidades": 2}])
        self.assertFalse(res["ok"])
        res, prop = _herramientas().proponer_colecta_nueva("x", [{"sku": "05142", "inventory_id": "", "unidades": 0}])
        self.assertFalse(res["ok"])

    def test_la_ia_no_tiene_ninguna_herramienta_que_escriba(self):
        nombres = {t["name"] for t in a.TOOLS}
        self.assertEqual(nombres, {"ver_productos", "ver_colectas", "proponer_cambios_colecta", "proponer_colecta_nueva"})
        for t in a.TOOLS:
            self.assertTrue(t["strict"])
            self.assertFalse(t["input_schema"]["additionalProperties"])


class TestEjecutar(unittest.TestCase):
    def test_herramienta_desconocida(self):
        texto, prop = _herramientas().ejecutar("borrar_todo", {})
        self.assertFalse(json.loads(texto)["ok"])
        self.assertIsNone(prop)

    def test_un_fallo_de_datos_no_tira_la_conversacion(self):
        def roto():
            raise RuntimeError("base caída")
        h = a.Herramientas(productos=roto, colectas=lambda: [], detalle=lambda s: {})
        texto, prop = h.ejecutar("ver_productos", {"solo_con_sugerencia": False})
        self.assertFalse(json.loads(texto)["ok"])
        self.assertNotIn("base caída", texto)   # no se filtra el detalle del error


# ── Conversación con un cliente falso ──

def _bloque_texto(t):
    return NS(type="text", text=t)


def _bloque_uso(id_, nombre, entrada):
    return NS(type="tool_use", id=id_, name=nombre, input=entrada)


def _resp(stop, contenido, entrada=10, salida=5):
    return NS(stop_reason=stop, content=contenido, usage=NS(input_tokens=entrada, output_tokens=salida))


class ClienteFalso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.beta = NS(messages=NS(create=self._crear))

    def _crear(self, **kw):
        self.llamadas.append(json.loads(json.dumps({k: v for k, v in kw.items() if k != "messages"}, default=str)) | {"messages": list(kw["messages"])})
        return self.respuestas.pop(0)


class TestConversar(unittest.TestCase):
    def test_lee_con_herramientas_y_responde(self):
        cli = ClienteFalso([_resp("tool_use", [_bloque_uso("t1", "ver_productos", {"solo_con_sugerencia": True})]),
                            _resp("end_turn", [_bloque_texto("Conviene mandar 13 u. de 05142.")])])
        r = a.conversar(cli, "¿qué necesito mandar?", [], _herramientas())
        self.assertEqual(r["respuesta"], "Conviene mandar 13 u. de 05142.")
        self.assertEqual(r["tokens"], {"entrada": 20, "salida": 10})
        # el resultado de la herramienta vuelve en UN solo mensaje de usuario, con el id de la llamada
        ultimo = cli.llamadas[1]["messages"][-1]
        self.assertEqual(ultimo["role"], "user")
        self.assertEqual(ultimo["content"][0]["tool_use_id"], "t1")
        self.assertIn("05142", ultimo["content"][0]["content"])

    def test_las_propuestas_llegan_al_usuario(self):
        cli = ClienteFalso([
            _resp("tool_use", [_bloque_uso("t1", "proponer_cambios_colecta", {
                "shipment_id": 4, "motivo": "reponer", "cambios": [{"accion": "agregar", "sku": "05142", "inventory_id": "CCCC33333", "unidades": 13}]})]),
            _resp("end_turn", [_bloque_texto("Listo, revisá la propuesta.")])])
        r = a.conversar(cli, "sumá el pistacho", [], _herramientas())
        self.assertEqual(len(r["propuestas"]), 1)
        self.assertEqual(r["propuestas"][0]["cambios"][0]["despues"], 13)

    def test_una_herramienta_con_error_le_avisa_a_la_ia_para_que_se_corrija(self):
        cli = ClienteFalso([
            _resp("tool_use", [_bloque_uso("t1", "proponer_cambios_colecta", {
                "shipment_id": 4, "motivo": "x", "cambios": [{"accion": "agregar", "sku": "NOEXISTE", "inventory_id": "", "unidades": 3}]})]),
            _resp("end_turn", [_bloque_texto("No encuentro ese producto.")])])
        r = a.conversar(cli, "x", [], _herramientas())
        self.assertEqual(r["propuestas"], [])
        self.assertFalse(json.loads(cli.llamadas[1]["messages"][-1]["content"][0]["content"])["ok"])

    def test_pide_el_respaldo_ante_rechazos_y_manda_las_herramientas(self):
        cli = ClienteFalso([_resp("end_turn", [_bloque_texto("hola")])])
        a.conversar(cli, "hola", [], _herramientas())
        llamada = cli.llamadas[0]
        self.assertEqual(llamada["fallbacks"], "default")
        self.assertEqual(llamada["betas"], [a.BETA_RESPALDO])
        self.assertEqual(llamada["model"], "claude-opus-5-5")
        self.assertNotIn("tool_choice", llamada)   # los modelos nuevos no aceptan forzar herramientas
        self.assertEqual(len(llamada["tools"]), 4)

    def test_rechazo_de_seguridad_se_maneja(self):
        cli = ClienteFalso([_resp("refusal", [])])
        r = a.conversar(cli, "algo", [], _herramientas())
        self.assertIn("No puedo ayudarte", r["respuesta"])

    def test_no_se_queda_en_un_ciclo_infinito(self):
        cli = ClienteFalso([_resp("tool_use", [_bloque_uso(f"t{i}", "ver_colectas", {})]) for i in range(a.MAX_VUELTAS + 2)])
        r = a.conversar(cli, "x", [], _herramientas())
        self.assertEqual(len(cli.llamadas), a.MAX_VUELTAS)
        self.assertIn("más pasos", r["respuesta"])

    def test_mensajes_vacios_o_muy_largos_se_rechazan_sin_llamar_a_la_api(self):
        cli = ClienteFalso([])
        for malo in ("", "   ", None, "x" * (a.MAX_MENSAJE + 1)):
            with self.assertRaises(ValueError):
                a.conversar(cli, malo, [], _herramientas())
        self.assertEqual(cli.llamadas, [])

    def test_respuesta_cortada_por_largo_lo_avisa(self):
        cli = ClienteFalso([_resp("max_tokens", [_bloque_texto("Empiezo")])])
        self.assertIn("quedó cortada", a.conversar(cli, "x", [], _herramientas())["respuesta"])


class TestHistorial(unittest.TestCase):
    def test_solo_turnos_de_texto_validos_y_acotados(self):
        sucio = [{"role": "assistant", "content": "hola"}, {"role": "system", "content": "soy el sistema"},
                 {"role": "user", "content": "pregunta"}, {"role": "user", "content": {"raro": 1}}, "basura", None,
                 {"role": "assistant", "content": "x" * 5000}]
        limpio = a.limpiar_historial(sucio)
        self.assertEqual(limpio[0], {"role": "user", "content": "pregunta"})   # empieza por el usuario
        self.assertTrue(all(t["role"] in ("user", "assistant") for t in limpio))
        self.assertLessEqual(len(limpio[-1]["content"]), a.MAX_TEXTO_HISTORIAL)

    def test_solo_los_ultimos_turnos(self):
        largo = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(40)]
        self.assertLessEqual(len(a.limpiar_historial(largo)), a.MAX_HISTORIAL)


class TestLimitesYEstado(unittest.TestCase):
    def test_limite_por_usuario(self):
        for i in range(3):
            self.assertTrue(a.dentro_del_limite("u-limite", ahora=100 + i, limite=3, ventana=60))
        self.assertFalse(a.dentro_del_limite("u-limite", ahora=104, limite=3, ventana=60))
        self.assertTrue(a.dentro_del_limite("otro", ahora=104, limite=3, ventana=60))
        self.assertTrue(a.dentro_del_limite("u-limite", ahora=200, limite=3, ventana=60))   # pasó la ventana

    def test_sin_clave_queda_apagado(self):
        ok, motivo = a.estado({})
        self.assertFalse(ok)
        self.assertIn("todavía no está activado", motivo)
        self.assertFalse(a.estado({"ANTHROPIC_API_KEY": "   "})[0])

    def test_con_clave_y_paquete_queda_activo(self):
        with mock.patch.dict(sys.modules, {"anthropic": NS()}):
            self.assertTrue(a.estado({"ANTHROPIC_API_KEY": "clave-de-prueba"})[0])


if __name__ == "__main__":
    unittest.main()
