"""Íconos de la interfaz de Full: de contorno, sin emojis de color (criterio común, 2026-10-14).
Lee los archivos del frontend; no necesita base ni servidor.
Uso:  python backend/test_iconos.py
"""
import os
import re
import unittest

FRONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')
ARCHIVOS = ['index.html', 'login.html', 'invitacion.html', os.path.join('js', 'app.js'),
            os.path.join('js', 'notifications.js')]
# Emojis de color: bloque U+1F000-1FAFF, más el triángulo de aviso U+26A0 y el selector FE0F.
EMOJI = re.compile('[\U0001F000-\U0001FAFF⚠️]')


def _leer(rel):
    with open(os.path.join(FRONT, rel), encoding='utf-8') as f:
        return f.read()


class TestIconos(unittest.TestCase):
    def test_sin_emojis_de_color_en_la_interfaz(self):
        for rel in ARCHIVOS:
            for n, linea in enumerate(_leer(rel).splitlines(), 1):
                if 'console.' in linea:  # los 📡 de console.log se quedan
                    continue
                self.assertIsNone(EMOJI.search(linea), f'{rel}:{n} tiene un emoji: {linea.strip()[:80]}')

    def test_iconos_son_de_contorno_y_heredan_color(self):
        js = _leer(os.path.join('js', 'app.js'))
        helper = re.search(r'function iconoSvg\(.*?\n\}', js, re.S)
        self.assertIsNotNone(helper, 'falta iconoSvg()')
        for pedazo in ('viewBox="0 0 24 24"', 'fill="none"', 'stroke="currentColor"',
                       'stroke-width="1.7"', 'stroke-linecap="round"', 'stroke-linejoin="round"'):
            self.assertIn(pedazo, helper.group(0))

    def test_hay_escapeHtml_y_se_usa_con_los_datos_del_evento(self):
        js = _leer(os.path.join('js', 'app.js'))
        self.assertIn('function escapeHtml(', js)
        self.assertIn('escapeHtml(ev.typical_turnos_delay_days)', js)
        self.assertIn('escapeHtml(shortName)', js)


if __name__ == '__main__':
    unittest.main()
