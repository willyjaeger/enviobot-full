"""Corre EN EL SERVIDOR. Carga inicial de lo que Mercado Libre informa de cada producto (tabla ml_reposicion, migracion 007),
sin esperar a la proxima sincronizacion. Solo lee de ML y escribe en ml_reposicion. Se puede correr de nuevo.
Uso:  cd /var/www/enviobot-full/backend && PYTHONPATH=. venv/bin/python /ruta/cargar_reposicion_ml.py <user_id>
"""
import sys

import worker
import ml_reposicion

user_id = int(sys.argv[1])
conn = worker.get_db()
with conn.cursor() as cur:
    cur.execute("SELECT id, user_id, ml_user_id, ml_access_token, ml_refresh_token, ml_token_expires_at FROM ml_credentials WHERE user_id=%s", (user_id,))
    creds = cur.fetchall()
    for cred in creds:
        token = worker.get_valid_token_for_cred(conn, cred)
        cur.execute("SELECT DISTINCT item_id FROM full_items WHERE user_id=%s AND ml_credential_id=%s", (user_id, cred["id"]))
        items = [f["item_id"] for f in cur.fetchall()]
        ok = 0
        for n, item_id in enumerate(items, 1):
            if ml_reposicion.sincronizar_item(conn, token, user_id, item_id):
                ok += 1
            print(f"{n}/{len(items)} {item_id}", flush=True)
        print(f"Cuenta {cred['ml_user_id']}: {ok} de {len(items)} publicaciones con datos de ML")
conn.close()
