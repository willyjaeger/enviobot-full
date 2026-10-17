# EnvioBot Full — guía para Claude

@../enviobot-comun/CRITERIOS_ENVIOBOT.md

Lo de arriba son los criterios comunes a todas las apps de EnvioBot (forma de trabajar, marca, íconos, seguridad, deploy). **Lo que sigue es solo lo propio de EnvioBot Full.** Si hay conflicto, mandan los criterios comunes.

## Qué es

**EnvioBot Full** es la app para vendedores de MercadoLibre Argentina que usan Mercado Envíos Full. Mira el stock en la bodega de MeLi, calcula la velocidad de venta, proyecta cuándo se quiebra el stock y avisa con tiempo para preparar el envío. Además tiene un módulo pago de colectas (inbound) para reponer Full. Es un producto independiente de EnvioBot Pedidos: un cliente puede usar uno, el otro o los dos (con un solo usuario, ver criterios comunes).

## Arquitectura

```
Navegador (frontend/)  --HTTP+JWT-->  Flask + MySQL (backend/)  <--cron cada 4 h--  worker.py  -->  API de MercadoLibre
```

| Pieza | Dónde | Notas |
|---|---|---|
| API | `backend/app.py` (~2.500 líneas) | Auth, OAuth de MeLi con PKCE, items, settings, destinatarios, depósitos, equipo, admin de clientes, inbound. También sirve el frontend |
| Sincronización y pronóstico | `backend/worker.py` | Cron cada 4 h; renueva tokens, trae publicaciones `fulfillment`, stock real y ventas 7/15/30 días |
| Alertas | `backend/alerts_engine.py` | Clasifica ok/warning/critical, no repite en 20 h, digest diario por cliente |
| WhatsApp / Email | `backend/whatsapp_service.py`, `email_service.py` | Evolution API o gateway HTTP (con modo simulación); SMTP |
| Colectas | `backend/inbound_service.py` | Envíos a Full, cajas, remito HTML |
| Equipo | `backend/equipo.py`, `frontend/invitacion.html`, sección Equipo de `app.js` | Roles por app, invitación por link (WhatsApp/mail), cuentas de ML visibles por persona. Usa las tablas de la migración 047 (`enviobot-web/backend/`, base compartida). **Apagado salvo** `user_features` "equipo" = on puesto a mano. Spec en `enviobot-comun/ESPECIFICACION_USUARIOS.md` |
| Panel | `frontend/index.html`, `js/app.js` (~4.100 líneas), `sw.js` | PWA con notificaciones nativas |
| Base | MySQL, base `enviobot_web` | `backend/schema.sql` está desactualizado respecto del código |

## Modelo de negocio

- **Velocidad de venta (VPD)** = 0,5·(v7/7) + 0,35·(v15/15) + 0,15·(v30/30). Días restantes = stock / VPD.
- **Crítico:** días restantes ≤ demora del flete. **Preparar envío:** ≤ demora + colchón. **Óptimo:** más que eso.
- **Acceso por cliente:** `users.has_full`, `has_pedidos`, `has_inbound`, `is_blocked`. Colaboradores con `owner_id` ven la cuenta del titular (`get_account_user_id`).
- **Planes** (`PLAN_LIMITS` en `app.py`): límites de cuentas de MeLi, destinatarios y depósitos.
- **Una publicación puede tener variaciones**, cada una con su `inventory_id` y SKU; el stock real sale de `/inventories/{id}/stock/fulfillment`.
- Colectas (inbound) es un módulo **pago**, con interruptor por cliente (`has_inbound`).

## Panel de colecta (2026-10-16)

Cuenta regresiva hasta el límite de edición (día hábil anterior al retiro, 9:40; lunes cierra el viernes) y aviso una hora antes (`aviso_limite_colecta.py`, necesita cron cada 10 min cargado en el servidor con OK). WhatsApp solo lun-vie 8:30 a 18:00 (`horario_whatsapp.py`), proyección a la fecha de ingreso, bloques "Colecta en preparación", "Para la próxima colecta" y "Con exceso de stock". Lógica en `backend/proyeccion.py`; reglas completas en la skill `.claude/skills/logistica-meli-full/`. **Pendiente de aplicar en producción:** `backend/migration_001_colecta_ajustes.sql` (umbral de sobrestock editable, hora límite por depósito, estado del galpón, historial `stock_daily`). El código ya la espera y se apaga solo si falta (`esquema.py`). Se aplica con el servicio apagado, respaldo y OK de Guillermo. Sin verificar con ML: crear la colecta por API y marcarla recibida con `operations/search`.

## Brechas contra los criterios comunes (a cerrar, de a una, con OK de Guillermo)

1. **Secretos (a medias, 2026-10-15):** sacados del código y cargados en el servidor; desplegado. La caja de claves REAL que lee la app es `/var/www/enviobot-full/backend/.env` (la de la raíz `/var/www/enviobot-full/.env` no se lee: `load_dotenv()` encuentra primero la de `backend/`). Ambas quedaron en chmod 600. Root del VPS: rotada. **FALTA ROTAR** lo que sigue visible en el historial de GitHub: secreto de ML, contraseñas de los mails y la de la base. **Ojo con la de la base:** el usuario `enviobot` y su clave son COMPARTIDOS con EnvioBot Pedidos (`/opt/enviobot-web/backend/.env`); hay que cambiarla en las dos apps a la vez (ALTER USER + las 2 cajas + reiniciar ambos servicios, con OK de Guillermo y fuera del horario de impresión). `herramientas/rotar_clave_base.py` frena a propósito mientras Pedidos la use.
2. **Admin por email (a medias):** ya no vale `"admin" in email`; queda una lista exacta de 2 emails en `app.py`. Falta pasar a solo `is_admin` en la base (con OK: hay que marcar a Guillermo en la tabla) y un `admin_required`.
3. **Deploy (hecho):** `desplegar_seguro.py` (llave SSH `enviobot-vps`, respaldo, verificación y vuelta atrás), lanzado con `SUBIR_A_PRODUCCION.bat`. Quedan en el servidor `/var/www/enviobot-full/` (el criterio común dice `/opt/<app>/`; mover es decisión aparte) y los respaldos en `backups/`. El `.env` del servidor no se toca por script.
4. **Archivos sueltos:** tres `admin_index_*.html` y dos copias de la matriz xlsx en la raíz.
5. **Documentación vieja:** `README.md` y `backend/schema.sql` describen una base `enviobot_full` independiente; el código usa `enviobot_web` y `ml_access_token`. No hay migraciones numeradas.
6. **Estética:** revisar el panel contra los criterios de marca e íconos (nombre "EnvioBot Full", cero emojis, íconos de contorno).
7. **Usuario único:** definir con Pedidos cómo se detecta el mismo usuario y que ambas apps usen el mismo hash de contraseña.

## Referencias

- `README.md` (modelo de pronóstico; el resto está desactualizado), `ARQUITECTURA_ALERTAS.md`, `docs/`.
- App hermana: `C:\Proyectos\enviobot-web` (EnvioBot Pedidos).
