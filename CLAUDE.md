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

Cuenta regresiva hasta el límite de edición (día hábil anterior al retiro, 9:44 como lo muestra ML; lunes cierra el viernes) y aviso una hora antes (`aviso_limite_colecta.py`, necesita cron cada 10 min cargado en el servidor con OK). WhatsApp solo lun-vie 8:30 a 18:00 (`horario_whatsapp.py`), proyección a la fecha de ingreso, bloques "Colecta en preparación", "Para la próxima colecta" y "Con exceso de stock". Lógica en `backend/proyeccion.py`; reglas completas en la skill `.claude/skills/logistica-meli-full/`. **Pendiente de aplicar en producción:** `backend/migration_001_colecta_ajustes.sql` (y las 002 a 005, que van juntas con `herramientas/aplicar_migraciones.py`; la 005 es el historial diario del índice de quiebres del Resumen, `indice_quiebres`) (umbral de sobrestock editable, hora límite por depósito, estado del galpón, historial `stock_daily`). El código ya la espera y se apaga solo si falta (`esquema.py`). Se aplica con el servicio apagado, respaldo y OK de Guillermo. Sin verificar con ML: crear la colecta por API y marcarla recibida con `operations/search`.

## Avisos pausados (2026-10-17)

Por decisión de Guillermo no sale ningún aviso automático (WhatsApp ni mail de stock, ni el aviso de una hora antes del límite) hasta definir cuáles mandar. Solo pasa el de cambio de tasa de venta (`pausa_avisos.TIPOS_PERMITIDOS`). La pausa es el valor por defecto: se levanta con `ENVIOBOT_AVISOS=activos` en el `.env` del servidor y reinicio. Quedan fuera porque los pide una persona en el momento: verificar un número, invitar, mensaje de prueba, altas de cuenta. Todo envío nuevo tiene que preguntar `pausa_avisos.puede_enviar(tipo)`.

**Mails de ML sobre la colecta (2026-10-19):** `backend/correo_colectas.py` lee una casilla IMAP común (`colectas@enviobot.com.ar`) donde cada cliente reenvía los mails de Mercado Libre. Cada cliente carga en Configuración (WhatsApp) su mail de Mercado Libre (`user_settings.colecta_email`, migración 004); el script reconoce la cuenta por la dirección a la que llegó el mail y avisa por WhatsApp a la agenda de envíos de ESA cuenta, según el menú **Avisos** de cada destinatario (`avisos_tipos.py`, `alert_recipients.avisos`, migración 003; sin ella todos reciben todo), diciendo de qué cuenta es ("La colecta de MISTERNUT está programada para..."). Los avisos de stock, cierre de colecta y ritmo de venta también respetan ese menú. Está en `TIPOS_PERMITIDOS` (`colecta_mail`) porque lo pidió Guillermo. En el `.env` del servidor solo hacen falta `COLECTAS_IMAP_USER` y `COLECTAS_IMAP_PASSWORD`, y el cron de 5 minutos (`crontab.example`). El formato real del mail de ML no está verificado: los tests usan el texto de la página del envío.

## Asistente de colectas (2026-10-20)

IA dentro del panel (`backend/asistente_colecta.py`, endpoints `/api/full/asistente/estado` y `/api/full/asistente/colecta`, botón flotante "Asistente"). **Solo lee y propone**: las herramientas son `ver_productos`, `ver_colectas`, `proponer_cambios_colecta` y `proponer_colecta_nueva`; ninguna escribe. Cada propuesta aparece con un botón que abre la colecta (o Armar colecta) con los cambios cargados y el usuario revisa y guarda; ahí aparece la lista "Cambios para hacer en Mercado Libre" y el botón amarillo que baja la planilla. **No toca Mercado Libre y no debe hacerlo**: ML no tiene API para crear o modificar envíos a Full y el punto 7.6 de sus términos de desarrollador prohíbe usar robots o scraping sobre su sitio (violarlo puede costar la revocación de las claves de la aplicación compartida con Pedidos); el punto 7.9 prohíbe guardar claves de los usuarios de ML. No agregar herramientas que escriban ni automatizar el sitio de ML. Se activa con `ANTHROPIC_API_KEY` en el `.env` del servidor y `pip install anthropic` en el entorno virtual (el despliegue seguro no toca el entorno virtual); sin eso queda apagado y la app sigue igual. Modelo `claude-opus-5-5` (`ASISTENTE_MODELO` lo cambia), tope de 20 consultas cada 10 minutos por usuario y proceso. Solo para clientes con el módulo de colectas.

**Decisión de Guillermo (2026-10-20): NO se pone en vigencia.** El código queda en el repositorio pero apagado (sin `ANTHROPIC_API_KEY` ni el paquete en el servidor no aparece). Queda como posibilidad para vender según el abono; idea de precio: unos 10 dólares por mes, sin certeza de que lo valga. Costo estimado (sin medir con datos reales): unos 0,13 USD por consulta con Opus y 0,06 con Sonnet, o sea unos 2 a 4 USD por cliente al mes con 30 consultas. **Antes de venderlo falta:** cuota mensual por cliente y registro de uso por cliente (tabla nueva, migración con OK), Sonnet por defecto, tope global en la consola de Anthropic (crédito prepago o límite mensual), medir los tokens reales y probarlo con la API real. El tope actual de 20 cada 10 minutos frena abusos pero no limita el gasto mensual.

## Ritmo de venta con margen (2026-11-01)

El VPD de siempre (0,5·v7 + 0,35·v15 + 0,15·v30) era inexacto y, sobre todo, un número único: **se queda corto la mitad de las veces**. `herramientas/backtest_demanda.py` lo probó con ventas reales (14 días hacia adelante, 273 pronósticos): ningún método baja de 35 % de error, el mejor es el promedio simple de 28 días (error 35 %, cobertura 49 %) y los "limpios" (inferir quiebres por ceros, recortar rebotes) no mejoraron nada, por eso se sacaron. Para no quebrar hace falta margen según cuánto varía cada producto: promedio + 0,5 desvío diario cubre 80 % de los casos (+42 % de stock) y + 1 desvío cubre 96 % (+86 %). `backend/demanda.py` devuelve `base` (promedio 28 días, coincide con las ventas de 30 días de ML), `protegido` (base + `K_SERVICIO` desvíos, hoy 0,5) y `alto` (base + 1 desvío). El panel (`/api/full/items`) planifica con el protegido (días de stock, semáforo, colecta sugerida), muestra el promedio en la columna Venta/día y explica el cálculo y el rango en el detalle de cada producto. Si falla o falta historia, vuelve al cálculo de siempre. Solo se descartan los días de `stock_daily` con stock 0 (ML informa 0 días sin stock en todo, así que ese dato puede estar sobrando; no se infieren quiebres).

Datos: `backend/ventas_historial.py` guarda ventas por día (migración 006: `ventas_diarias` 120 días, `ventas_semanales` hasta 2 años; `herramientas/cargar_ventas.py` hace la carga inicial) y `backend/ml_reposicion.py` guarda lo que informa ML por producto (migración 007, `ml_reposicion`: ventas de 30 días, por semana, reposición recomendada y urgencia; columna "Venta/día ML" del listado). El worker llena ambas en cada sincronización y guarda el ritmo protegido en `forecasts`. `herramientas/propuesta_demanda.py` es la prueba de solo lectura.

`cambio_tasa.py` (rediseñado a pedido de Guillermo) ya no avisa subas: avisa la baja sostenida (venta de la última semana y de los últimos 3 días 30 % o más por debajo de las buenas semanas recientes, `referencia` de `demanda.estimar`) que deja stock de más (cobertura sobre el umbral de sobrestock, al menos 20 unidades y 10 días de sobrante) y dice si todavía se puede achicar la colecta en preparación. **Su WhatsApp está en modo prueba** (decisión de Guillermo, 2026-11-01): solo anota en `alert_logs` (tipo `cambio_tasa_wa`) lo que habría mandado y por qué, con tope de 1 por día y 3 por semana por persona; se ve en la ventana de Avisos. Para mandar de verdad: `ENVIOBOT_CAMBIO_TASA_WA=activo` en el `.env` del servidor y reiniciar.

**Pendiente:** nivel de servicio por producto (`K_SERVICIO` es global; para productos caros como las nueces conviene bajarlo), estacionalidad con el año anterior (bajar 365 días a `ventas_semanales`) y un tope de plata inmovilizada por producto.

## Una sola regla para "hay que mandar hoy" (2026-11-01)

Pedido de Guillermo: un solo número, sin marear. La regla es la del índice de quiebres del frontend (`calcularIndiceQuiebres` en `app.js`): un producto es "de hoy" si, con lo que hay en Full y las colectas cargadas, se queda sin stock **antes de que una colecta nueva pueda llegar**; los que se quedan sin stock más adelante pero tienen tiempo cuentan como "no hace falta nada hoy". `accionHoyPorProducto()` / `requiereColectaHoy()` la exponen y la usan la dona de estado, la dona de la meta, el título, "Qué hacer hoy", la colecta automática (borrador: solo estos productos, con las unidades para llegar a sus días objetivo), "Armar colecta" y el filtro "Requieren colecta". Sin ritmo de venta el producto no está en el índice y queda el estado de siempre (`status` del servidor). Los chips de estado de la tabla, las tarjetas de arriba (Crítico/Preparar) y el widget de alertas usan la misma regla (`unificarEstadoConRegla` al final de `recalcularTodo`: rojo = Crítico, sumar = Preparar). **Todavía con la regla vieja:** solo los avisos del servidor (`alerts_engine.py`, pausados). La cadencia de 15 días es la meta, no un piso: se puede armar otra colecta a pocos días de la anterior (`DIAS_MIN_ENTRE_COLECTAS`, 4), y cada producto va en la última colecta que todavía llega antes de quedarse sin stock (decisión de Guillermo, 2026-11-01). La colecta automática tiene dos tarjetas: la de hoy y la **colecta siguiente** (`colectaSiguienteVirtual`: retiro recomendado dictado por el primer producto que quiebra y que la de hoy no resuelve, y las unidades para que todos lleguen a la colecta que sigue a los días de objetivo). Las unidades de cada producto son las que lo dejan con sus días objetivo al entrar la colecta (`unidadesParaObjetivo`). Con tendencia a la baja el ritmo de planificación no suma margen (`demanda.py`). La colecta con exceso (`exceso_colecta`) va en rojo de alerta, no en azul, y el "Sacar" no se confunde con el amarillo de "Agregar". Cada ventana tiene botón Volver (`agregarBotonesVolver`). `herramientas/volcar_panel.py` vuelca lo que recibe el panel para reproducirlo en local.

**Mercado Libre manda (2026-11-01):** cargar de nuevo el PDF de una colecta que ya existe (mismo número `ML-…`) la actualiza para que quede igual que el PDF: cantidades, productos agregados o quitados y fecha de retiro (`comparar_con_existente` en `pdf_envio_ml.py`, endpoint `import-pdf`). Antes devolvía "ya está cargada". No toca las ingresadas ni las canceladas. La ventana de editar un envío tiene **Imprimir hoja** (`imprimirCambiosML`): tabla con Sacar / Cambiar / Agregar, producto, SKU, código ML, lo que Mercado Libre tiene hoy y lo que hay que dejar, con tilde por fila. La base "lo que tiene Mercado Libre" se guarda en el servidor (`inbound_shipments.ml_base`, `base_ml.py`, **migración 008 pendiente de aplicar**, `herramientas/aplicar_migracion_008.py`): se renueva con cada PDF cargado y la primera vez que se edita acá una colecta `ML-` queda la foto de lo que había; así todas las computadoras de la cuenta ven la misma hoja. Sin la columna, la app usa una copia en el navegador (`enviobot_base_ml_<id>`). Pendiente: que el cálculo trate como fijas solo las colectas con número `ML-` y las armadas acá sin número como modificables.

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
