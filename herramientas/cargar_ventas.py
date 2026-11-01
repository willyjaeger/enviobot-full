"""Corre EN EL SERVIDOR. Carga inicial del historial de ventas por dia (120 dias) de una cuenta, sin esperar a la proxima
sincronizacion. Solo escribe en ventas_diarias (migracion 006). Se puede correr de nuevo: solo repasa los ultimos dias.
Uso:  cd /var/www/enviobot-full/backend && venv/bin/python ../herramientas/cargar_ventas.py <user_id>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import worker  # noqa: E402
import ventas_historial  # noqa: E402

user_id = int(sys.argv[1])
conn = worker.get_db()
with conn.cursor() as cur:
    cur.execute("SELECT id, user_id, ml_user_id, ml_access_token, ml_refresh_token, ml_token_expires_at FROM ml_credentials WHERE user_id=%s", (user_id,))
    creds = cur.fetchall()
    for cred in creds:
        token = worker.get_valid_token_for_cred(conn, cred)
        cur.execute("SELECT item_id, variation_id FROM full_items WHERE user_id=%s AND ml_credential_id=%s", (user_id, cred["id"]))
        por_item = {}
        for f in cur.fetchall():
            por_item.setdefault(f["item_id"], set()).add(f["variation_id"] or "")
        ok = 0
        for n, (item_id, vars_) in enumerate(por_item.items(), 1):
            if ventas_historial.sincronizar_item(conn, token, cred["ml_user_id"], user_id, item_id, vars_):
                ok += 1
            print(f"{n}/{len(por_item)} {item_id}", flush=True)
        print(f"Cuenta {cred['ml_user_id']}: {ok} de {len(por_item)} publicaciones cargadas")
ventas_historial.consolidar(conn)
conn.close()
