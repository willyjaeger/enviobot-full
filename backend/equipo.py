"""Equipo de EnvioBot Full: usuarios del negocio, rol en Full, invitaciones por link
y qué cuentas de MercadoLibre ve cada persona.

Es la versión de Full de backend/equipo.py de EnvioBot Pedidos (misma idea, mismas
tablas de la migración 047, que ya están en la base `enviobot_web` compartida). La
especificación está en enviobot-comun/ESPECIFICACION_USUARIOS.md.

Diferencias con Pedidos:
  - En Full todos trabajan sobre la cuenta del titular (`get_account_user_id`), no
    hay PC ni impresoras. Las cuentas de ML las conectan los administradores y al
    resto se les habilita cuáles VE.
  - El rol manda de verdad: Solo ver no modifica nada, Operador trabaja (items,
    colectas, sincronizar) y Administrador gestiona equipo, cuentas, destinatarios
    y configuración.
  - La invitación sale por WhatsApp desde el número de Full (Evolution) o por mail,
    y la persona crea su contraseña al abrir el link. Nunca hay clave inicial.

Todo viaja APAGADO: solo vale para el abono del titular al que el admin le puso la
funcionalidad "equipo" en "on" a mano (user_features). Sin eso, o si las tablas de
la migración 047 no existen, nada cambia, nada se bloquea y los endpoints viejos de
equipo siguen como estaban.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required

APP = 'full'
FEATURE = 'equipo'
ROLES = ('viewer', 'operator', 'admin')
RANGO = {'none': -1, 'viewer': 0, 'operator': 1, 'admin': 2}
ROL_ETIQUETA = {'none': 'Sin acceso', 'viewer': 'Solo ver', 'operator': 'Operador', 'admin': 'Administrador'}
VENCE_DIAS = 7

bp = Blueprint('equipo', __name__)
_deps = {}


def init(app, get_db, enviar_mail, enviar_whatsapp, hash_pw, server_url):
    """Enchufa el módulo a la app. `enviar_mail(to, nombre, asunto, html, texto)` y
    `enviar_whatsapp(telefono, texto)` usan los servicios de siempre; `hash_pw` es el
    hash de contraseñas de la app (el mismo que Pedidos)."""
    _deps.update(get_db=get_db, enviar_mail=enviar_mail, enviar_whatsapp=enviar_whatsapp,
                 hash_pw=hash_pw, server_url=server_url.rstrip('/'))
    app.register_blueprint(bp)


# ── Lógica (probable sin Flask ni base) ─────────────────────────────────────

def hash_codigo(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def raiz(cur, user_id):
    """El usuario principal al que pertenece `user_id`."""
    for _ in range(5):
        cur.execute('SELECT owner_id, abono_de FROM users WHERE id = %s LIMIT 1', (user_id,))
        u = cur.fetchone()
        padre = (u or {}).get('owner_id') or (u or {}).get('abono_de')
        if not padre:
            return user_id
        user_id = padre
    return user_id


def equipo_activo(cur, user_id):
    """¿El admin prendió "equipo" para el abono de este usuario? Solo vale un "on"
    puesto a mano: ni la prueba gratis ni el valor por defecto lo prenden."""
    try:
        cur.execute('SELECT mode FROM user_features WHERE user_id = %s AND feature_code = %s LIMIT 1',
                    (raiz(cur, user_id), FEATURE))
        f = cur.fetchone()
        return bool(f and f['mode'] == 'on')
    except Exception:
        return False


def asegurar_negocio(cur, user_id):
    """Id del negocio del usuario; si todavía no tiene, lo crea con el principal de Owner."""
    root = raiz(cur, user_id)
    cur.execute('SELECT id FROM accounts WHERE owner_user_id = %s LIMIT 1', (root,))
    fila = cur.fetchone()
    if fila:
        cuenta = fila['id']
    else:
        cur.execute('SELECT business_name, full_name, email FROM users WHERE id = %s LIMIT 1', (root,))
        u = cur.fetchone() or {}
        nombre = (u.get('business_name') or '').strip() or (u.get('full_name') or '').strip() or u.get('email') or 'Negocio'
        cur.execute('INSERT INTO accounts (name, owner_user_id) VALUES (%s, %s)', (nombre, root))
        cuenta = cur.lastrowid
    cur.execute('UPDATE users SET account_id = %s WHERE id IN (%s, %s) AND account_id IS NULL', (cuenta, root, user_id))
    cur.execute('INSERT IGNORE INTO user_app_roles (user_id, app, role) VALUES (%s, %s, %s)', (root, APP, 'admin'))
    return cuenta


def rol_de(cur, user_id):
    """Rol del usuario en Full. Sin fila: el principal es administrador, un
    colaborador de Full (owner_id) es operador y cualquier otro no tiene acceso."""
    cur.execute('SELECT role FROM user_app_roles WHERE user_id = %s AND app = %s LIMIT 1', (user_id, APP))
    f = cur.fetchone()
    if f:
        return f['role']
    if raiz(cur, user_id) == user_id:
        return 'admin'
    cur.execute('SELECT owner_id FROM users WHERE id = %s LIMIT 1', (user_id,))
    return 'operator' if (cur.fetchone() or {}).get('owner_id') else 'none'


def es_admin(cur, user_id):
    return rol_de(cur, user_id) == 'admin'


def cuentas_del_negocio(cur, account_id):
    """Cuentas de ML conectadas por cualquiera del negocio, una vez cada una."""
    cur.execute(
        '''SELECT m.ml_user_id AS ext, MAX(m.ml_nickname) AS nombre
           FROM ml_credentials m JOIN users u ON u.id = m.user_id
           WHERE u.account_id = %s AND m.ml_user_id IS NOT NULL GROUP BY m.ml_user_id ORDER BY nombre''', (account_id,))
    return [{'platform': 'ml', 'external_id': str(r['ext']), 'nombre': r['nombre'] or f"Cuenta {r['ext']}", 'imprime': False}
            for r in cur.fetchall()]


def cuentas_visibles(cur, user_id):
    """ml_user_id que este usuario puede ver, o None si ve todas. Ve todas el que
    no tiene "equipo" prendido, el titular y los administradores. Nunca esconde
    por error: ante cualquier falla devuelve None (todas)."""
    try:
        if not equipo_activo(cur, user_id):
            return None
        if raiz(cur, user_id) == user_id or es_admin(cur, user_id):
            return None
        cur.execute("SELECT external_id FROM user_channel_access WHERE user_id = %s AND platform = 'ml'", (user_id,))
        return [int(r['external_id']) for r in cur.fetchall() if str(r['external_id']).isdigit()]
    except Exception as e:
        print(f'⚠ cuentas_visibles falló, se muestran todas: {e}')
        return None


def _normalizar_cuentas(cuentas, validas):
    ok = {(c['platform'], c['external_id']) for c in validas}
    vistas, salida = set(), []
    for c in cuentas or []:
        k = (str(c.get('platform') or 'ml'), str(c.get('external_id') or ''))
        if k in ok and k not in vistas:
            vistas.add(k)
            salida.append({'platform': k[0], 'external_id': k[1]})
    return salida


def guardar_cuentas(cur, user_id, cuentas):
    cur.execute('DELETE FROM user_channel_access WHERE user_id = %s', (user_id,))
    for c in cuentas:
        cur.execute('INSERT IGNORE INTO user_channel_access (user_id, platform, external_id) VALUES (%s, %s, %s)',
                    (user_id, c['platform'], c['external_id']))


def crear_invitacion(cur, account_id, invitado_por, nombre, email, celular, rol, cuentas, ahora=None):
    """Crea la invitación (solo se guarda la huella del código). Devuelve (code, id, vence)."""
    ahora = ahora or datetime.now()
    vence = ahora + timedelta(days=VENCE_DIAS)
    code = secrets.token_urlsafe(9)
    canal = 'whatsapp' if celular else ('email' if email else 'link')
    grants = {'roles': {APP: rol}, 'cuentas': cuentas, 'code': code}
    cur.execute(
        '''INSERT INTO invitations (account_id, invited_by, full_name, email, phone, channel, token_hash, grants_json, expires_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (account_id, invitado_por, nombre or None, email or None, celular or None, canal,
         hash_codigo(code), json.dumps(grants), vence))
    return code, cur.lastrowid, vence


def invitacion_valida(cur, code, ahora=None):
    """La invitación abierta de ese código, o None si no existe, se usó, se canceló o venció."""
    ahora = ahora or datetime.now()
    cur.execute('SELECT id, account_id, full_name, email, grants_json, expires_at FROM invitations '
                'WHERE token_hash = %s AND used_at IS NULL AND cancelled_at IS NULL LIMIT 1', (hash_codigo(code or ''),))
    inv = cur.fetchone()
    if not inv or inv['expires_at'] < ahora:
        return None
    g = inv['grants_json']
    inv['grants'] = json.loads(g) if isinstance(g, (str, bytes)) else (g or {})
    return inv


def tipo_de(u, owner_user_id):
    if u['id'] == owner_user_id:
        return 'titular'
    if u.get('owner_id'):
        return 'colaborador'
    return 'usuario_pedidos'


def chequear_rol(minimo):
    """None si puede pasar; si no, la respuesta 403 para devolver. Con "equipo"
    apagado, o ante cualquier falla, siempre deja pasar."""
    conn = None
    try:
        conn = _deps['get_db']()
        cur = conn.cursor()
        uid = int(get_jwt_identity())
        if equipo_activo(cur, uid) and RANGO.get(rol_de(cur, uid), -1) < RANGO[minimo]:
            return jsonify({'ok': False, 'error': 'Tu rol no permite hacer esto. Pedile a un administrador de tu equipo.'}), 403
    except Exception as e:
        print(f'⚠ chequear_rol falló, se deja pasar: {e}')
    finally:
        if conn:
            conn.close()
    return None


def requiere_rol(minimo):
    """Decorador para endpoints de Full (va DEBAJO de @jwt_required). Con "equipo"
    apagado no hace nada. Prendido, exige un rol mínimo en Full."""
    def deco(fn):
        @wraps(fn)
        def inner(*a, **k):
            no = chequear_rol(minimo)
            return no if no else fn(*a, **k)
        return inner
    return deco


# ── Endpoints ───────────────────────────────────────────────────────────────

def _conn():
    """Conexión con transacción manual: Full abre las suyas en autocommit y acá un
    alta o un cambio de rol tiene que guardarse entero o nada."""
    conn = _deps['get_db']()
    conn.autocommit(False)
    return conn


def _tablas_listas(cur):
    cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name IN ('accounts','user_app_roles','invitations','user_channel_access')")
    return cur.fetchone()['n'] == 4


@bp.route('/api/full/equipo/estado', methods=['GET'])
@jwt_required()
def estado():
    conn = _conn()
    try:
        cur = conn.cursor()
        yo = int(get_jwt_identity())
        return jsonify({'ok': True, 'habilitado': bool(_tablas_listas(cur) and equipo_activo(cur, yo))})
    except Exception as e:
        print(f'✗ Error en equipo/estado: {e}')
        return jsonify({'ok': True, 'habilitado': False})
    finally:
        conn.close()


def _pedido():
    """Abre la base y exige que "equipo" esté prendido. Devuelve
    (conn, cur, yo, root, account_id) o (None, None, respuesta, None, None)."""
    conn = _conn()
    if not conn:
        return None, None, (jsonify({'ok': False, 'error': 'Error conectando a la base.'}), 500), None, None
    cur = conn.cursor()
    try:
        yo = int(get_jwt_identity())
        if not _tablas_listas(cur) or not equipo_activo(cur, yo):
            raise LookupError
        account_id = asegurar_negocio(cur, yo)
        conn.commit()
        return conn, cur, yo, raiz(cur, yo), account_id
    except LookupError:
        conn.close()
        return None, None, (jsonify({'ok': False, 'error': 'Esta función todavía no está habilitada para tu cuenta.'}), 403), None, None
    except Exception as e:
        conn.close()
        print(f'✗ Error en equipo: {e}')
        return None, None, (jsonify({'ok': False, 'error': 'No se pudo cargar el equipo.'}), 500), None, None


def _exigir_admin(cur, yo):
    if not es_admin(cur, yo):
        return jsonify({'ok': False, 'error': 'Solo un Administrador puede hacer esto.'}), 403
    return None


def _json(valor):
    return json.loads(valor) if isinstance(valor, (str, bytes)) else (valor or {})


@bp.route('/api/full/equipo', methods=['GET'])
@jwt_required()
def listar():
    conn, cur, yo, root, account_id = _pedido()
    if conn is None:
        return yo
    try:
        cuentas = cuentas_del_negocio(cur, account_id)
        cur.execute('SELECT id, email, full_name, owner_id, abono_de, active FROM users WHERE account_id = %s '
                    'ORDER BY (id = %s) DESC, full_name', (account_id, root))
        miembros = []
        for u in cur.fetchall():
            rol = rol_de(cur, u['id'])
            cur.execute('SELECT platform, external_id FROM user_channel_access WHERE user_id = %s', (u['id'],))
            habil = [{'platform': a['platform'], 'external_id': a['external_id']} for a in cur.fetchall()]
            miembros.append({'id': u['id'], 'nombre': u['full_name'] or u['email'], 'email': u['email'], 'rol': rol,
                             'tipo': tipo_de(u, root), 'activo': bool(u['active']), 'soy_yo': u['id'] == yo,
                             'habilitadas': habil})
        cur.execute('''SELECT id, full_name, email, phone, expires_at, grants_json FROM invitations
                       WHERE account_id = %s AND used_at IS NULL AND cancelled_at IS NULL AND expires_at > NOW()
                       ORDER BY created_at DESC''', (account_id,))
        pendientes = []
        for i in cur.fetchall():
            g = _json(i['grants_json'])
            if (g.get('roles') or {}).get(APP) is None:
                continue  # invitación hecha desde Pedidos
            pendientes.append({'id': i['id'], 'nombre': i['full_name'], 'email': i['email'], 'celular': i['phone'],
                               'code': g.get('code'), 'vence': i['expires_at'].isoformat(),
                               'rol': g['roles'][APP], 'cuentas': g.get('cuentas') or []})
        cur.execute('SELECT name FROM accounts WHERE id = %s', (account_id,))
        return jsonify({'ok': True, 'negocio': (cur.fetchone() or {}).get('name'), 'soy_admin': es_admin(cur, yo),
                        'cuentas': cuentas, 'miembros': miembros, 'pendientes': pendientes,
                        'roles': [{'codigo': k, 'nombre': ROL_ETIQUETA[k]} for k in ('admin', 'operator', 'viewer')]})
    finally:
        conn.close()


def _rol_valido(valor):
    return valor if valor in ROLES else 'operator'


def _texto_invitacion(nombre, negocio, link):
    primero = (nombre or '').split(' ')[0]
    return (f'Hola {primero}! Te invito a usar EnvioBot Full con {negocio}. '
            f'Entrá con este link y elegí tu contraseña (vale {VENCE_DIAS} días): {link}')


@bp.route('/api/full/equipo/invitaciones', methods=['POST'])
@jwt_required()
def invitar():
    conn, cur, yo, root, account_id = _pedido()
    if conn is None:
        return yo
    try:
        no = _exigir_admin(cur, yo)
        if no:
            return no
        b = request.get_json() or {}
        nombre = (b.get('nombre') or '').strip()[:100]
        email = (b.get('email') or '').strip().lower()[:255]
        celular = (b.get('celular') or '').strip()[:30]
        if not nombre:
            return jsonify({'ok': False, 'error': 'Poné el nombre de la persona.'}), 400
        if email and '@' not in email:
            return jsonify({'ok': False, 'error': 'Ese email no parece válido.'}), 400
        if email:
            cur.execute('SELECT id, account_id FROM users WHERE email = %s LIMIT 1', (email,))
            ya = cur.fetchone()
            if ya and ya['account_id'] == account_id:
                return jsonify({'ok': False, 'error': 'Esa persona ya está en tu negocio. Dale acceso a Full desde la lista, con el rol.'}), 409
            if ya:
                return jsonify({'ok': False, 'error': 'Ese email ya tiene usuario en EnvioBot en otro negocio.'}), 409
        cuentas = _normalizar_cuentas(b.get('cuentas'), cuentas_del_negocio(cur, account_id))
        code, inv_id, vence = crear_invitacion(cur, account_id, yo, nombre, email, celular, _rol_valido(b.get('rol')), cuentas)
        conn.commit()
        link = f"{_deps['server_url']}/invitacion.html?inv={code}"
        cur.execute('SELECT name FROM accounts WHERE id = %s', (account_id,))
        negocio = (cur.fetchone() or {}).get('name') or 'su negocio'
        texto = _texto_invitacion(nombre, negocio, link)
        enviado = {'email': False, 'whatsapp': None}
        if email and b.get('enviar_email'):
            html = (f'<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:480px;color:#1c1e26;line-height:1.6">'
                    f'<p>Hola {nombre.split(" ")[0]},</p><p>Te invitaron a usar <b>EnvioBot Full</b> con el negocio <b>{negocio}</b>.</p>'
                    f'<p><a href="{link}" style="background:#f5a623;color:#1c1e26;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:bold">Aceptar la invitación</a></p>'
                    f'<p style="color:#6b6f7a;font-size:13px">El link vence en {VENCE_DIAS} días y sirve una sola vez.</p></div>')
            enviado['email'] = bool(_deps['enviar_mail'](email, nombre, f'{negocio} te invita a EnvioBot Full', html, texto))
        if celular and b.get('enviar_whatsapp'):
            enviado['whatsapp'] = _deps['enviar_whatsapp'](celular, texto)
        return jsonify({'ok': True, 'id': inv_id, 'code': code, 'link': link, 'vence': vence.isoformat(),
                        'texto': texto, 'enviado': enviado})
    except Exception as e:
        conn.rollback()
        print(f'✗ Error en equipo/invitar: {e}')
        return jsonify({'ok': False, 'error': 'No se pudo crear la invitación.'}), 500
    finally:
        conn.close()


@bp.route('/api/full/equipo/invitaciones/<int:inv_id>/whatsapp', methods=['POST'])
@jwt_required()
def reenviar_invitacion_whatsapp(inv_id):
    """Manda de nuevo la invitación por WhatsApp desde el servidor (sin abrir WhatsApp en el navegador)."""
    conn, cur, yo, root, account_id = _pedido()
    if conn is None:
        return yo
    try:
        no = _exigir_admin(cur, yo)
        if no:
            return no
        cur.execute('SELECT full_name, phone, grants_json FROM invitations WHERE id = %s AND account_id = %s '
                    'AND used_at IS NULL AND cancelled_at IS NULL AND expires_at > NOW() LIMIT 1', (inv_id, account_id))
        inv = cur.fetchone()
        if not inv or not inv.get('phone'):
            return jsonify({'ok': False, 'error': 'Esa invitación no existe, venció o no tiene celular.'}), 404
        code = (json.loads(inv['grants_json'] or '{}')).get('code')
        if not code:
            return jsonify({'ok': False, 'error': 'No se pudo armar el link de esa invitación.'}), 409
        cur.execute('SELECT name FROM accounts WHERE id = %s', (account_id,))
        negocio = (cur.fetchone() or {}).get('name') or 'su negocio'
        link = f"{_deps['server_url']}/invitacion.html?inv={code}"
        res = _deps['enviar_whatsapp'](inv['phone'], _texto_invitacion(inv['full_name'], negocio, link))
        ok = bool(res and res.get('ok') and not res.get('simulated'))
        return jsonify({'ok': ok, 'error': None if ok else 'No se pudo enviar por WhatsApp. Probá con Copiar link.'})
    finally:
        conn.close()


@bp.route('/api/full/equipo/invitaciones/<int:inv_id>', methods=['DELETE'])
@jwt_required()
def cancelar_invitacion(inv_id):
    conn, cur, yo, root, account_id = _pedido()
    if conn is None:
        return yo
    try:
        no = _exigir_admin(cur, yo)
        if no:
            return no
        cur.execute('UPDATE invitations SET cancelled_at = NOW() WHERE id = %s AND account_id = %s '
                    'AND used_at IS NULL AND cancelled_at IS NULL', (inv_id, account_id))
        if not cur.rowcount:
            return jsonify({'ok': False, 'error': 'No encontré esa invitación.'}), 404
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@bp.route('/api/full/equipo/miembros/<int:miembro_id>', methods=['PUT'])
@jwt_required()
def editar_miembro(miembro_id):
    """Cambia el rol en Full (o lo da, si todavía no tenía) y las cuentas que ve."""
    conn, cur, yo, root, account_id = _pedido()
    if conn is None:
        return yo
    try:
        no = _exigir_admin(cur, yo)
        if no:
            return no
        cur.execute('SELECT id FROM users WHERE id = %s AND account_id = %s LIMIT 1', (miembro_id, account_id))
        if not cur.fetchone():
            return jsonify({'ok': False, 'error': 'Esa persona no está en tu negocio.'}), 404
        b = request.get_json() or {}
        if miembro_id == root and b.get('rol') not in (None, 'admin'):
            return jsonify({'ok': False, 'error': 'El titular siempre es Administrador.'}), 400
        if 'rol' in b:
            rol = _rol_valido(b['rol'])
            if rol != 'admin':
                cur.execute('SELECT COUNT(*) AS n FROM user_app_roles r JOIN users u ON u.id = r.user_id '
                            'WHERE u.account_id = %s AND r.app = %s AND r.role = %s AND r.user_id != %s',
                            (account_id, APP, 'admin', miembro_id))
                if not cur.fetchone()['n']:
                    return jsonify({'ok': False, 'error': 'Tiene que quedar al menos un Administrador.'}), 400
            cur.execute('INSERT INTO user_app_roles (user_id, app, role) VALUES (%s, %s, %s) '
                        'ON DUPLICATE KEY UPDATE role = VALUES(role)', (miembro_id, APP, rol))
            cur.execute('UPDATE users SET has_full = 1 WHERE id = %s', (miembro_id,))
        if 'cuentas' in b:
            guardar_cuentas(cur, miembro_id, _normalizar_cuentas(b['cuentas'], cuentas_del_negocio(cur, account_id)))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        print(f'✗ Error en equipo/editar: {e}')
        return jsonify({'ok': False, 'error': 'No se pudo guardar.'}), 500
    finally:
        conn.close()


@bp.route('/api/full/equipo/miembros/<int:miembro_id>', methods=['DELETE'])
@jwt_required()
def quitar_miembro(miembro_id):
    """Saca a alguien de Full. NO borra su usuario (es compartido con Pedidos): le quita
    el rol y el acceso a Full, y si era colaborador de Full lo desvincula del titular."""
    conn, cur, yo, root, account_id = _pedido()
    if conn is None:
        return yo
    try:
        no = _exigir_admin(cur, yo)
        if no:
            return no
        if miembro_id == root:
            return jsonify({'ok': False, 'error': 'El titular no se puede quitar.'}), 400
        if miembro_id == yo:
            return jsonify({'ok': False, 'error': 'No podés quitarte a vos mismo.'}), 400
        cur.execute('SELECT id, owner_id, has_pedidos FROM users WHERE id = %s AND account_id = %s LIMIT 1', (miembro_id, account_id))
        u = cur.fetchone()
        if not u:
            return jsonify({'ok': False, 'error': 'Esa persona no está en tu negocio.'}), 404
        cur.execute('DELETE FROM user_app_roles WHERE user_id = %s AND app = %s', (miembro_id, APP))
        cur.execute('UPDATE users SET has_full = 0 WHERE id = %s', (miembro_id,))
        if u['owner_id']:
            cur.execute('UPDATE users SET owner_id = NULL, account_id = NULL, active = %s WHERE id = %s',
                        (1 if u['has_pedidos'] else 0, miembro_id))
            cur.execute('DELETE FROM user_channel_access WHERE user_id = %s', (miembro_id,))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        print(f'✗ Error en equipo/quitar: {e}')
        return jsonify({'ok': False, 'error': 'No se pudo quitar.'}), 500
    finally:
        conn.close()


# ── Alta por link (públicos: la persona todavía no tiene usuario) ───────────

@bp.route('/api/full/equipo/invitacion/<code>', methods=['GET'])
def ver_invitacion(code):
    conn = _conn()
    try:
        cur = conn.cursor()
        inv = invitacion_valida(cur, code)
        if not inv:
            return jsonify({'ok': False, 'error': 'La invitación no es válida o ya venció. Pedile una nueva a quien te invitó.'}), 404
        cur.execute('SELECT name FROM accounts WHERE id = %s', (inv['account_id'],))
        return jsonify({'ok': True, 'negocio': (cur.fetchone() or {}).get('name'), 'nombre': inv['full_name'],
                        'email': inv['email'], 'pide_email': not inv['email'],
                        'rol': ROL_ETIQUETA.get((inv['grants'].get('roles') or {}).get(APP), '')})
    finally:
        conn.close()


@bp.route('/api/full/equipo/aceptar', methods=['POST'])
def aceptar():
    """La persona abre el link y elige su contraseña: se crea su usuario como colaborador del
    titular (así Full le muestra la cuenta del negocio) y entra directo."""
    b = request.get_json() or {}
    password = (b.get('password') or '').strip()
    if len(password) < 6:
        return jsonify({'ok': False, 'error': 'La contraseña debe tener al menos 6 caracteres.'}), 400
    conn = _conn()
    try:
        cur = conn.cursor()
        inv = invitacion_valida(cur, b.get('code'))
        if not inv:
            return jsonify({'ok': False, 'error': 'La invitación no es válida o ya venció. Pedile una nueva a quien te invitó.'}), 404
        email = (inv['email'] or b.get('email') or '').strip().lower()
        if not email or '@' not in email:
            return jsonify({'ok': False, 'error': 'Poné tu email.'}), 400
        nombre = (b.get('full_name') or inv['full_name'] or email.split('@')[0]).strip()[:100]
        cur.execute('SELECT id FROM users WHERE email = %s LIMIT 1', (email,))
        if cur.fetchone():
            return jsonify({'ok': False, 'error': 'Ese email ya tiene usuario en EnvioBot. Pedile a un administrador que te dé acceso desde su lista.'}), 409
        cur.execute('SELECT owner_user_id FROM accounts WHERE id = %s', (inv['account_id'],))
        root = (cur.fetchone() or {}).get('owner_user_id')
        if not root:
            return jsonify({'ok': False, 'error': 'La invitación ya no es válida.'}), 404
        cur.execute(
            '''INSERT INTO users (email, password_hash, full_name, owner_id, employee_label, has_full, has_pedidos,
                                  active, must_change_password, account_id)
               VALUES (%s, %s, %s, %s, 'Colaborador', 1, 0, 1, 0, %s)''',
            (email, _deps['hash_pw'](password), nombre, root, inv['account_id']))
        nuevo = cur.lastrowid
        for app, rol in (inv['grants'].get('roles') or {}).items():
            if rol in ROLES:
                cur.execute('INSERT INTO user_app_roles (user_id, app, role) VALUES (%s, %s, %s) '
                            'ON DUPLICATE KEY UPDATE role = VALUES(role)', (nuevo, app, rol))
        guardar_cuentas(cur, nuevo, inv['grants'].get('cuentas') or [])
        cur.execute('UPDATE invitations SET used_by = %s, used_at = NOW() WHERE id = %s', (nuevo, inv['id']))
        conn.commit()
        return jsonify({'ok': True, 'token': create_access_token(identity=str(nuevo)), 'email': email})
    except Exception as e:
        conn.rollback()
        print(f'✗ Error en equipo/aceptar: {e}')
        return jsonify({'ok': False, 'error': 'No se pudo completar el alta. Probá de nuevo.'}), 500
    finally:
        conn.close()
