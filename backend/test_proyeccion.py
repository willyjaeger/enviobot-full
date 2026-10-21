"""Proyección a la fecha de ingreso de la colecta. Sin base ni ML.
Uso:  python backend/test_proyeccion.py
"""
import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proyeccion as p  # noqa: E402

HOY = date(2026, 10, 16)


class TestDiasHastaIngreso(unittest.TestCase):
    def test_con_fecha_de_llegada_usa_esa_fecha(self):
        self.assertEqual(p.dias_hasta_ingreso('scheduled', HOY, date(2026, 10, 23), 5, 2), 7)

    def test_sin_fecha_usa_preparacion_mas_flete(self):
        self.assertEqual(p.dias_hasta_ingreso('scheduled', HOY, None, 5, 2), 7)
        self.assertEqual(p.dias_hasta_ingreso(None, HOY, None, 5, 2), 7)

    def test_fecha_pasada_no_da_dias_negativos(self):
        self.assertEqual(p.dias_hasta_ingreso('scheduled', HOY, date(2026, 10, 10), 5, 2), 0)

    def test_en_transito_solo_flete(self):
        self.assertEqual(p.dias_hasta_ingreso('in_transit', HOY, date(2026, 10, 30), 5, 2), 2)

    def test_en_recepcion_un_dia(self):
        self.assertEqual(p.dias_hasta_ingreso('in_reception', HOY, None, 5, 2), 1)


class TestProyeccion(unittest.TestCase):
    def test_stock_al_ingreso_nunca_es_negativo(self):
        # 10 u. hoy, 3 por día, 7 días de espera: se agota al día 4 y llega a 0, no a -11.
        self.assertEqual(p.stock_al_ingreso(10, 3, 7), 0)

    def test_stock_al_ingreso_descuenta_lo_vendido(self):
        self.assertEqual(p.stock_al_ingreso(100, 3, 7), 79)

    def test_cobertura_post_colecta(self):
        # 0 en Full al ingreso + 90 u. de colecta, 3 por día = 30 días.
        self.assertEqual(p.cobertura_post_colecta(10, 3, 7, 90), 30.0)

    def test_cobertura_sin_ventas_es_none(self):
        self.assertIsNone(p.cobertura_post_colecta(10, 0, 7, 90))

    def test_sugerido_cuenta_desde_el_ingreso(self):
        # objetivo 30 días a 3/día = 90; al ingreso quedan 0; nada en camino: mandar 90.
        self.assertEqual(p.sugerido_al_ingreso(10, 3, 7, 0, 30), 90)
        # con 40 ya en la colecta faltan 50.
        self.assertEqual(p.sugerido_al_ingreso(10, 3, 7, 40, 30), 50)

    def test_sugerido_no_es_negativo(self):
        self.assertEqual(p.sugerido_al_ingreso(500, 1, 7, 100, 30), 0)

    def test_sugerido_sin_ventas_es_cero(self):
        self.assertEqual(p.sugerido_al_ingreso(10, 0, 7, 0, 30), 0)


class TestAvisoAjuste(unittest.TestCase):
    def test_sin_colecta_no_avisa(self):
        self.assertIsNone(p.aviso_ajuste(10, 3, 7, 0, 30))

    def test_colecta_suficiente_no_avisa(self):
        self.assertIsNone(p.aviso_ajuste(10, 3, 7, 90, 30))

    def test_colecta_corta_sugiere_cuanto_preparar(self):
        # 100 u. a 4,3/día cubren ~23 días de 30: conviene preparar 129 (30*4.3).
        self.assertEqual(p.aviso_ajuste(0, 4.3, 7, 100, 30), 129)

    def test_leve_faltante_no_molesta(self):
        # 26 de 30 días (87%) está dentro de la tolerancia.
        self.assertIsNone(p.aviso_ajuste(0, 1.0, 7, 26, 30))


class TestSobrestock(unittest.TestCase):
    def test_umbral_es_un_multiplo_del_objetivo(self):
        self.assertEqual(p.umbral_sobrestock(30), 45)

    def test_pasado_del_umbral_es_sobrestock(self):
        # 50 días de cobertura contra un objetivo de 30.
        self.assertTrue(p.es_sobrestock(150, 0, 3, 30))

    def test_justo_en_el_umbral_no_es_sobrestock(self):
        self.assertFalse(p.es_sobrestock(135, 0, 3, 30))

    def test_cuenta_lo_que_viene_en_camino(self):
        self.assertTrue(p.es_sobrestock(60, 100, 3, 30))
        self.assertFalse(p.es_sobrestock(60, 0, 3, 30))

    def test_sin_ventas_no_se_marca(self):
        self.assertFalse(p.es_sobrestock(500, 0, 0, 30))


class TestFactorEditable(unittest.TestCase):
    def test_factor_propio_cambia_el_umbral(self):
        self.assertEqual(p.umbral_sobrestock(30, 2), 60)
        self.assertFalse(p.es_sobrestock(150, 0, 3, 30, 2))   # 50 días < 60
        self.assertTrue(p.es_sobrestock(190, 0, 3, 30, 2))    # 63 días > 60

    def test_factor_vacio_o_invalido_usa_el_de_siempre(self):
        for malo in (None, '', 'abc', 0, 1, -3):
            self.assertEqual(p.umbral_sobrestock(30, malo), 45, malo)

    def test_factor_viene_como_decimal_de_la_base(self):
        from decimal import Decimal
        self.assertEqual(p.umbral_sobrestock(30, Decimal('1.50')), 45)


class TestHoraLimite(unittest.TestCase):
    def test_parsear_formas_de_hora(self):
        from datetime import time, timedelta
        self.assertEqual(p.parsear_hora('09:40'), (9, 40))
        self.assertEqual(p.parsear_hora('9:40:00'), (9, 40))
        self.assertEqual(p.parsear_hora(timedelta(hours=10, minutes=15)), (10, 15))
        self.assertEqual(p.parsear_hora(time(8, 5)), (8, 5))

    def test_hora_invalida_devuelve_none(self):
        for malo in (None, '', 'tarde', '25:00', '10:70'):
            self.assertIsNone(p.parsear_hora(malo), malo)

    def test_limite_con_hora_propia(self):
        lim = p.limite_edicion(date(2026, 10, 23), '11:15')
        self.assertEqual((lim.day, lim.hour, lim.minute), (22, 11, 15))

    def test_hora_invalida_vuelve_a_las_9_44(self):
        lim = p.limite_edicion(date(2026, 10, 23), 'cualquiera')
        self.assertEqual((lim.hour, lim.minute), (9, 44))


class TestVpdCorregido(unittest.TestCase):
    def test_sin_dias_sin_stock_da_la_formula_de_siempre(self):
        # No-regresión: 0,5*(14/7) + 0,35*(30/15) + 0,15*(90/30) = 1,0 + 0,7 + 0,45
        self.assertEqual(p.vpd_ponderado(14, 30, 90), 2.15)
        self.assertEqual(p.vpd_ponderado(14, 30, 90, 0, 0, 0), 2.15)

    def test_quebrado_diez_dias_sube_la_velocidad(self):
        sin = p.vpd_ponderado(0, 0, 60)            # 60 vendidas en 30 días
        con = p.vpd_ponderado(0, 0, 60, 0, 0, 10)  # pero estuvo 10 días sin stock
        self.assertEqual(sin, 0.3)
        self.assertEqual(con, 0.45)

    def test_casi_todo_el_periodo_sin_stock_no_se_corrige(self):
        # 29 de 30 días quebrado: quedaría 1 día activo, puro ruido; se deja como estaba.
        self.assertEqual(p.vpd_ponderado(0, 0, 60, 0, 0, 29), p.vpd_ponderado(0, 0, 60))

    def test_dias_sin_stock_negativos_se_ignoran(self):
        self.assertEqual(p.vpd_ponderado(7, 0, 0, -5, 0, 0), p.vpd_ponderado(7, 0, 0))


class TestCuentaRegresiva(unittest.TestCase):
    def test_limite_es_el_dia_anterior_a_las_9_44_de_buenos_aires(self):
        lim = p.limite_edicion(date(2026, 10, 23))
        self.assertEqual((lim.year, lim.month, lim.day, lim.hour, lim.minute), (2026, 10, 22, 9, 44))
        self.assertEqual(lim.utcoffset().total_seconds(), -3 * 3600)

    def test_faltan_dos_dias_y_tres_horas(self):
        ahora = datetime(2026, 10, 20, 6, 44, tzinfo=p.HORA_BA)
        r = p.cuenta_regresiva(date(2026, 10, 23), ahora)
        self.assertTrue(r['abierta'])
        self.assertEqual(r['segundos_restantes'], (2 * 24 + 3) * 3600)

    def test_despues_de_las_9_44_queda_cerrada(self):
        ahora = datetime(2026, 10, 22, 9, 45, tzinfo=p.HORA_BA)
        r = p.cuenta_regresiva(date(2026, 10, 23), ahora)
        self.assertFalse(r['abierta'])
        self.assertEqual(r['segundos_restantes'], 0)

    def test_justo_a_las_9_44_ya_no_alcanza(self):
        ahora = datetime(2026, 10, 22, 9, 44, tzinfo=p.HORA_BA)
        self.assertFalse(p.cuenta_regresiva(date(2026, 10, 23), ahora)['abierta'])


class TestBloqueadaPorMl(unittest.TestCase):
    RETIRO = date(2026, 10, 19)  # lunes: cierra el viernes 16 a las 9:44

    def _ahora(self, d, h, mi):
        return datetime(d.year, d.month, d.day, h, mi, tzinfo=p.HORA_BA)

    def test_de_ml_pasado_el_limite_queda_bloqueada(self):
        self.assertTrue(p.bloqueada_por_ml('ML-78889570', self.RETIRO, ahora=self._ahora(date(2026, 10, 17), 10, 0)))

    def test_de_ml_antes_del_limite_se_puede_editar(self):
        self.assertFalse(p.bloqueada_por_ml('ML-78889570', self.RETIRO, ahora=self._ahora(date(2026, 10, 16), 9, 0)))

    def test_las_armadas_en_enviobot_nunca_se_bloquean(self):
        self.assertFalse(p.bloqueada_por_ml('COL-FULL-20261012-002', self.RETIRO, ahora=self._ahora(date(2026, 10, 18), 10, 0)))

    def test_sin_fecha_no_bloquea(self):
        self.assertFalse(p.bloqueada_por_ml('ML-1', None))


class TestArmarColecta(unittest.TestCase):
    FILA = {'id': 4, 'shipment_code': 'ML-79759779', 'status': 'scheduled',
            'pickup_date': date(2026, 10, 28), 'estimated_arrival_date': date(2026, 10, 31), 'transit_days': 3}
    PROD = [{'title': 'Dátil', 'sku': '12072', 'units_to_send': 100}, {'title': 'Nueces', 'sku': '01011', 'units_to_send': 300}]

    def test_fechas_y_totales(self):
        ahora = datetime(2026, 10, 17, 12, 0, tzinfo=p.HORA_BA)
        c = p.armar_colecta(self.FILA, self.PROD, ahora=ahora)
        self.assertEqual((c['fecha_retiro'], c['fecha_ingreso']), ('2026-10-28', '2026-10-31'))
        self.assertTrue(c['limite_edicion'].startswith('2026-10-27T09:44'))
        self.assertTrue(c['abierta'])
        self.assertTrue(c['de_ml'])
        self.assertEqual(c['total_unidades'], 400)
        self.assertEqual(c['productos'][0], {'titulo': 'Dátil', 'sku': '12072', 'unidades': 100})

    def test_cerrada_pasado_el_limite(self):
        ahora = datetime(2026, 10, 27, 10, 0, tzinfo=p.HORA_BA)
        self.assertFalse(p.armar_colecta(self.FILA, self.PROD, ahora=ahora)['abierta'])

    def test_en_camino_nunca_figura_abierta(self):
        ahora = datetime(2026, 10, 17, 12, 0, tzinfo=p.HORA_BA)
        self.assertFalse(p.armar_colecta(dict(self.FILA, status='in_transit'), self.PROD, ahora=ahora)['abierta'])

    def test_sin_fecha_de_ingreso_usa_el_transito(self):
        fila = dict(self.FILA, estimated_arrival_date=None, transit_days=2)
        self.assertEqual(p.armar_colecta(fila, self.PROD)['fecha_ingreso'], '2026-10-30')

    def test_la_armada_en_enviobot_no_es_de_ml(self):
        self.assertFalse(p.armar_colecta(dict(self.FILA, shipment_code='COL-FULL-1'), self.PROD)['de_ml'])


class TestCalcularCambioFechas(unittest.TestCase):
    HOY = date(2026, 10, 17)
    RETIRO, INGRESO = date(2026, 10, 28), date(2026, 10, 31)

    def _c(self, **kw):
        return p.calcular_cambio_fechas(self.RETIRO, self.INGRESO, 3, hoy=self.HOY, **kw)

    def test_mover_el_retiro_corre_el_ingreso_con_la_misma_demora(self):
        r = self._c(nuevo_retiro=date(2026, 10, 30))
        self.assertEqual((r['retiro'], r['ingreso'], r['transito_dias']), (date(2026, 10, 30), date(2026, 11, 2), 3))

    def test_mover_solo_el_ingreso_cambia_la_demora(self):
        r = self._c(nuevo_ingreso=date(2026, 11, 4))
        self.assertEqual((r['retiro'], r['ingreso'], r['transito_dias']), (self.RETIRO, date(2026, 11, 4), 7))

    def test_si_se_mueven_los_dos_gana_el_ingreso_elegido(self):
        r = self._c(nuevo_retiro=date(2026, 10, 30), nuevo_ingreso=date(2026, 11, 3))
        self.assertEqual((r['retiro'], r['ingreso']), (date(2026, 10, 30), date(2026, 11, 3)))

    def test_no_a_un_retiro_pasado_ni_a_un_ingreso_pasado(self):
        self.assertIn('anterior a hoy', self._c(nuevo_retiro=date(2026, 10, 16))['error'])
        self.assertIn('anterior a hoy', self._c(nuevo_ingreso=date(2026, 10, 16))['error'])

    def test_el_ingreso_no_puede_ser_antes_del_retiro(self):
        self.assertIn('antes del retiro', self._c(nuevo_ingreso=date(2026, 10, 27))['error'])

    def test_una_colecta_cerrada_en_ml_igual_se_puede_mover(self):
        # retiro el lunes 19 (límite ya pasó): la agenda puede cambiar por ML o por nosotros
        r = p.calcular_cambio_fechas(date(2026, 10, 19), date(2026, 10, 22), 3, nuevo_retiro=date(2026, 10, 21), hoy=self.HOY)
        self.assertEqual(r['retiro'], date(2026, 10, 21))

    def test_sin_fecha_de_ingreso_usa_el_transito(self):
        r = p.calcular_cambio_fechas(self.RETIRO, None, 2, nuevo_retiro=date(2026, 10, 30), hoy=self.HOY)
        self.assertEqual(r['ingreso'], date(2026, 11, 1))


class TestPausaPorQuiebre(unittest.TestCase):
    def _ch(self, status, sub=''):
        return {'status': status, 'sub_status': sub}

    def test_pausada_por_falta_de_stock_es_quiebre(self):
        self.assertTrue(p.pausa_por_quiebre([self._ch('paused', 'out_of_stock')], 0))

    def test_pausada_por_el_vendedor_no_es_quiebre(self):
        self.assertFalse(p.pausa_por_quiebre([self._ch('paused', '')], 0))
        self.assertFalse(p.pausa_por_quiebre([self._ch('paused', 'suspended')], 0))

    def test_sin_el_motivo_guardado_no_se_asume_quiebre(self):
        self.assertFalse(p.pausa_por_quiebre([self._ch('paused')], 0))

    def test_si_otra_publicacion_sigue_activa_no_es_pausa(self):
        self.assertFalse(p.pausa_por_quiebre([self._ch('paused', 'out_of_stock'), self._ch('active')], 0))

    def test_con_stock_en_full_no_es_quiebre(self):
        self.assertFalse(p.pausa_por_quiebre([self._ch('paused', 'out_of_stock')], 5))



class TestEtapaColecta(unittest.TestCase):
    def test_sin_salir_es_propuesta_o_armada_segun_el_codigo(self):
        self.assertEqual(p.etapa_colecta('COL-FULL-1', 'scheduled'), 'propuesta')
        self.assertEqual(p.etapa_colecta('ML-78889570', 'scheduled'), 'armada')

    def test_en_transito_es_retirada(self):
        self.assertEqual(p.etapa_colecta('ML-1', 'in_transit', 0), 'retirada')

    def test_en_transito_con_unidades_en_proceso_es_recibida(self):
        self.assertEqual(p.etapa_colecta('ML-1', 'in_transit', 57), 'recibida')

    def test_sin_salir_nunca_es_recibida_aunque_haya_stock_en_proceso(self):
        # ese stock puede ser de una colecta anterior con los mismos productos
        self.assertEqual(p.etapa_colecta('ML-2', 'scheduled', 500), 'armada')

    def test_armar_colecta_acota_lo_en_proceso_a_lo_enviado(self):
        fila = dict(TestArmarColecta.FILA, status='in_transit', shipment_code='ML-78889570')
        c = p.armar_colecta(fila, TestArmarColecta.PROD, en_proceso=10**6)
        self.assertEqual(c['etapa'], 'recibida')
        self.assertEqual(c['unidades_en_proceso'], c['total_unidades'])
        self.assertEqual(p.armar_colecta(dict(fila, status='scheduled'), TestArmarColecta.PROD, en_proceso=5)['unidades_en_proceso'], 0)


class TestRepartirEntrante(unittest.TestCase):
    def test_sin_colectas_recibidas_da_lo_mismo_que_antes(self):
        self.assertEqual(p.repartir_entrante(0, 0, 100), (0, 100))
        self.assertEqual(p.repartir_entrante(30, 0, 100), (30, 70))     # lo no disponible sale de lo que venía
        self.assertEqual(p.repartir_entrante(150, 0, 100), (150, 0))
        self.assertEqual(p.repartir_entrante(0, 0, 0), (0, 0))

    def test_lo_que_ml_ya_recibio_esta_en_procesamiento_no_en_camino(self):
        # colecta 78889570: ML la recibió (100 u.) pero todavía no figuran como no disponibles
        self.assertEqual(p.repartir_entrante(0, 100, 0), (100, 0))
        # además viaja otra colecta de 40 u.
        self.assertEqual(p.repartir_entrante(0, 100, 40), (100, 40))

    def test_no_se_cuenta_dos_veces_lo_recibido_y_lo_no_disponible(self):
        self.assertEqual(p.repartir_entrante(100, 100, 0), (100, 0))
        self.assertEqual(p.repartir_entrante(120, 100, 40), (120, 20))   # 20 u. no disponibles más allá de lo recibido

    def test_datos_raros_no_rompen(self):
        self.assertEqual(p.repartir_entrante(None, None, None), (0, 0))
        self.assertEqual(p.repartir_entrante(-5, 0, 10), (0, 10))


class TestDemoraAprendida(unittest.TestCase):
    def test_sin_muestras_no_hay_demora(self):
        self.assertIsNone(p.demora_aprendida([]))
        self.assertIsNone(p.demora_aprendida(None))

    def test_una_muestra_es_esa_demora(self):
        self.assertEqual(p.demora_aprendida([0]), 0)

    def test_usa_la_mediana_y_no_se_deja_llevar_por_un_valor_raro(self):
        self.assertEqual(p.demora_aprendida([1, 1, 2, 30, 1]), 1)

    def test_solo_cuentan_las_ultimas_cinco(self):
        self.assertEqual(p.demora_aprendida([1, 1, 1, 1, 1, 9, 9, 9]), 1)

    FILA = {'pickup_date': date(2026, 10, 19), 'transit_days': 2, 'estimated_arrival_date': date(2026, 10, 21)}

    def test_la_fecha_automatica_se_corrige_con_la_demora_real(self):
        self.assertEqual(p.ingreso_estimado(self.FILA, 0), date(2026, 10, 19))
        self.assertEqual(p.ingreso_estimado(self.FILA, None), date(2026, 10, 21))

    def test_la_fecha_movida_a_mano_se_respeta(self):
        mano = dict(self.FILA, estimated_arrival_date=date(2026, 10, 25))
        self.assertEqual(p.ingreso_estimado(mano, 0), date(2026, 10, 25))

    def test_recibida_deja_la_fecha_real(self):
        real = dict(self.FILA, estimated_arrival_date=date(2026, 10, 19), meli_inbound_status='received')
        self.assertEqual(p.ingreso_estimado(real, 5), date(2026, 10, 19))
        c = p.armar_colecta(dict(real, id=1, shipment_code='ML-1', status='in_transit'), [], demora_real=5)
        self.assertEqual(c['etapa'], 'recibida')
        self.assertEqual(c['fecha_ingreso'], '2026-10-19')
        self.assertFalse(c['ingreso_estimado'])

    def test_recibida_sigue_recibida_aunque_ya_no_haya_stock_en_proceso(self):
        self.assertEqual(p.etapa_colecta('ML-1', 'in_transit', 0, True), 'recibida')
        self.assertEqual(p.etapa_colecta('ML-1', 'delivered', 0), 'recibida')

if __name__ == '__main__':
    unittest.main()
