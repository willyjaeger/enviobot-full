"""Tests del receptor de notificaciones de ML sobre stock de Full."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notificaciones_ml as n  # noqa: E402

BUENA = {"resource": "/stock/fulfillment/operations/9876", "user_id": 1234, "topic": "fbm_stock_operations",
         "application_id": 4025969768673074, "attempts": 1}


class TestValidar(unittest.TestCase):
    def v(self, **cambios):
        return n.validar({**BUENA, **cambios}, "4025969768673074", [1234, "999"])

    def test_la_notificacion_buena_pasa(self):
        self.assertEqual(self.v(), (True, ""))

    def test_otro_tema_se_ignora(self):
        self.assertEqual(self.v(topic="orders_v2")[1], "tema")

    def test_otra_aplicacion_se_ignora(self):
        self.assertEqual(self.v(application_id=1)[1], "aplicacion")

    def test_vendedor_desconocido_se_ignora(self):
        self.assertEqual(self.v(user_id=777)[1], "vendedor")

    def test_solo_se_consulta_una_operacion_de_stock(self):
        for malo in ("/users/me", "/stock/fulfillment/operations/1/../../x", "https://otro.com/stock/fulfillment/operations/1",
                     "/stock/fulfillment/operations/abc", "/stock/fulfillment/operations/"):
            self.assertEqual(self.v(resource=malo)[1], "recurso", malo)

    def test_cuerpo_que_no_es_json_de_objeto(self):
        self.assertFalse(n.validar(None, "1", [1])[0])
        self.assertFalse(n.validar([1], "1", [1])[0])


class TestProcesar(unittest.TestCase):
    def test_consulta_con_el_token_del_vendedor_y_devuelve_la_operacion(self):
        visto = {}

        def consultar(ruta, token):
            visto.update(ruta=ruta, token=token)
            return 200, {"id": 9876, "type": "INBOUND_RECEPTION", "inventory_id": "ABC1"}
        op = n.procesar(BUENA, lambda uid: "tok" if uid == 1234 else None, consultar)
        self.assertEqual(op["type"], "INBOUND_RECEPTION")
        self.assertEqual(visto, {"ruta": "/stock/fulfillment/operations/9876", "token": "tok"})

    def test_sin_token_no_consulta(self):
        self.assertIsNone(n.procesar(BUENA, lambda uid: None, lambda r, t: self.fail("no debe consultar")))

    def test_error_http_o_excepcion_no_rompen(self):
        self.assertIsNone(n.procesar(BUENA, lambda uid: "t", lambda r, t: (429, {"error": "over_quota"})))

        def explota(r, t):
            raise RuntimeError("red")
        self.assertIsNone(n.procesar(BUENA, lambda uid: "t", explota))


if __name__ == "__main__":
    unittest.main()
