"""Un envío en tránsito que ya debería haber llegado no se cuenta como 'en camino' (se contaba dos veces)."""
import unittest
from datetime import date

import proyeccion as P


def fila(**kw):
    base = {"status": "in_transit", "pickup_date": date(2026, 11, 13), "estimated_arrival_date": date(2026, 11, 16),
            "transit_days": 3, "meli_inbound_status": ""}
    base.update(kw)
    return base


class TransitoVencido(unittest.TestCase):
    def test_vencido_pasada_la_gracia(self):
        # El caso real: retiro 13/11, ingreso 16/11, mirado el 23/11.
        self.assertTrue(P.transito_vencido(fila(), date(2026, 11, 23)))

    def test_dentro_de_la_gracia_sigue_en_camino(self):
        self.assertFalse(P.transito_vencido(fila(), date(2026, 11, 19)))
        self.assertFalse(P.transito_vencido(fila(), date(2026, 11, 14)))

    def test_el_limite_es_mas_de_tres_dias(self):
        self.assertFalse(P.transito_vencido(fila(), date(2026, 11, 19)))   # justo 3 días después
        self.assertTrue(P.transito_vencido(fila(), date(2026, 11, 20)))    # 4 días después

    def test_recibida_por_ml_no_es_vencida(self):
        self.assertFalse(P.transito_vencido(fila(meli_inbound_status="received"), date(2026, 11, 30)))

    def test_solo_aplica_a_en_transito(self):
        self.assertFalse(P.transito_vencido(fila(status="scheduled"), date(2026, 11, 30)))
        self.assertFalse(P.transito_vencido(fila(status="delivered"), date(2026, 11, 30)))

    def test_sin_fecha_de_retiro_no_se_puede_decir(self):
        self.assertFalse(P.transito_vencido(fila(pickup_date=None), date(2026, 11, 30)))

    def test_la_fecha_movida_a_mano_se_respeta(self):
        # Si la movieron al 25/11, el 23/11 todavía no está vencida.
        f = fila(estimated_arrival_date=date(2026, 11, 25))
        self.assertFalse(P.transito_vencido(f, date(2026, 11, 23)))


if __name__ == "__main__":
    unittest.main()
