"""Equipo en Full: roles, qué cuentas ve cada persona y que todo viaje APAGADO.
Sin base ni ML: cursor falso en memoria.
Uso:  python backend/test_equipo.py
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import equipo  # noqa: E402


class _Cursor:
    """users {id: {owner_id, abono_de}}, features {user_id: 'on'}, roles {user_id: rol},
    habilitadas {(user_id, platform, ext)}, invitaciones {hash: fila}."""

    def __init__(self, users, features=None, roles=None, habilitadas=(), invitaciones=None, falla=False):
        self.users, self.features, self.roles = users, features or {}, roles or {}
        self.habilitadas, self.invitaciones, self.falla = set(habilitadas), invitaciones or {}, falla
        self._r, self._rows = None, []

    def execute(self, sql, params=()):
        if self.falla:
            raise RuntimeError("Table 'user_features' doesn't exist")
        s = ' '.join(sql.split())
        if s.startswith('SELECT owner_id, abono_de FROM users'):
            self._r = self.users.get(params[0])
        elif s.startswith('SELECT owner_id FROM users'):
            self._r = self.users.get(params[0])
        elif 'FROM user_features' in s:
            m = self.features.get(params[0])
            self._r = {'mode': m} if m else None
        elif 'FROM user_app_roles' in s:
            r = self.roles.get(params[0])
            self._r = {'role': r} if r else None
        elif 'FROM user_channel_access' in s:
            self._rows = [{'external_id': e} for (u, p, e) in self.habilitadas if u == params[0] and p == 'ml']
        elif 'FROM invitations' in s:
            self._r = self.invitaciones.get(params[0])

    def fetchone(self):
        return self._r

    def fetchall(self):
        return self._rows


# 1 titular, 2 usuario de Pedidos (abono_de 1), 3 colaborador de Full (owner_id 1)
USERS = {1: {'owner_id': None, 'abono_de': None},
         2: {'owner_id': None, 'abono_de': 1},
         3: {'owner_id': 1, 'abono_de': None}}
ON = {1: 'on'}


class Test(unittest.TestCase):
    def test_apagado_no_cambia_nada(self):
        cur = _Cursor(USERS, roles={2: 'viewer'})
        self.assertFalse(equipo.equipo_activo(cur, 2))
        self.assertIsNone(equipo.cuentas_visibles(cur, 2))

    def test_la_prueba_gratis_no_lo_prende(self):
        self.assertFalse(equipo.equipo_activo(_Cursor(USERS), 1))
        self.assertTrue(equipo.equipo_activo(_Cursor(USERS, features=ON), 2))  # vale el del titular

    def test_titular_y_administradores_ven_todas(self):
        self.assertIsNone(equipo.cuentas_visibles(_Cursor(USERS, features=ON), 1))
        self.assertIsNone(equipo.cuentas_visibles(_Cursor(USERS, features=ON, roles={2: 'admin'}), 2))

    def test_el_resto_ve_solo_las_habilitadas(self):
        cur = _Cursor(USERS, features=ON, roles={2: 'operator'}, habilitadas={(2, 'ml', '555')})
        self.assertEqual(equipo.cuentas_visibles(cur, 2), [555])

    def test_sin_cuentas_habilitadas_no_ve_ninguna(self):
        self.assertEqual(equipo.cuentas_visibles(_Cursor(USERS, features=ON, roles={2: 'viewer'}), 2), [])

    def test_un_error_nunca_esconde_cuentas(self):
        self.assertIsNone(equipo.cuentas_visibles(_Cursor(USERS, features=ON, falla=True), 2))

    def test_rol_sin_fila(self):
        self.assertEqual(equipo.rol_de(_Cursor(USERS), 1), 'admin')      # titular
        self.assertEqual(equipo.rol_de(_Cursor(USERS), 3), 'operator')   # colaborador de Full
        self.assertEqual(equipo.rol_de(_Cursor(USERS), 2), 'none')       # de Pedidos, sin acceso a Full
        self.assertEqual(equipo.rol_de(_Cursor(USERS, roles={2: 'viewer'}), 2), 'viewer')

    def test_rangos(self):
        self.assertLess(equipo.RANGO['none'], equipo.RANGO['viewer'])
        self.assertLess(equipo.RANGO['viewer'], equipo.RANGO['operator'])
        self.assertLess(equipo.RANGO['operator'], equipo.RANGO['admin'])

    def test_invitacion_vigente_vencida_o_inexistente(self):
        ahora = datetime(2026, 10, 16, 12, 0)
        h = equipo.hash_codigo('abc')
        fila = {'id': 7, 'account_id': 2, 'full_name': 'Dani', 'email': None,
                'grants_json': json.dumps({'roles': {'full': 'operator'}}), 'expires_at': ahora + timedelta(days=3)}
        self.assertEqual(equipo.invitacion_valida(_Cursor(USERS, invitaciones={h: dict(fila)}), 'abc', ahora)['id'], 7)
        vencida = dict(fila, expires_at=ahora - timedelta(seconds=1))
        self.assertIsNone(equipo.invitacion_valida(_Cursor(USERS, invitaciones={h: vencida}), 'abc', ahora))
        self.assertIsNone(equipo.invitacion_valida(_Cursor(USERS), 'otro', ahora))

    def test_cuentas_invitadas_solo_las_del_negocio(self):
        validas = [{'platform': 'ml', 'external_id': '555', 'nombre': 'MISTERNUT', 'imprime': False}]
        pedidas = [{'platform': 'ml', 'external_id': '555'}, {'platform': 'ml', 'external_id': '999'}]
        self.assertEqual(equipo._normalizar_cuentas(pedidas, validas), [{'platform': 'ml', 'external_id': '555'}])

    def test_tipos_de_miembro(self):
        self.assertEqual(equipo.tipo_de({'id': 1, 'owner_id': None}, 1), 'titular')
        self.assertEqual(equipo.tipo_de({'id': 2, 'owner_id': None}, 1), 'usuario_pedidos')
        self.assertEqual(equipo.tipo_de({'id': 3, 'owner_id': 1}, 1), 'colaborador')


if __name__ == '__main__':
    unittest.main()
