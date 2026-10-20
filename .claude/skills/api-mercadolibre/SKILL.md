---
name: api-mercadolibre
description: Reglas para usar la API de Mercado Libre en EnvioBot Full sin adivinar. Usar antes de proponer, escribir o probar cualquier llamada a api.mercadolibre.com (items, inventarios, operaciones de stock, envíos, notificaciones) o antes de afirmar qué puede o no puede hacer la API.
---

# API de Mercado Libre: no adivinar

Guillermo pidió expresamente que no se adivine con esta API ("cuando te pones a adivinar sos muy peligroso").

## Regla de trabajo
1. **Antes de afirmar o probar un endpoint, leer la documentación oficial** (WebFetch o el navegador integrado) en `developers.mercadolibre.com.ar` (envíos Fulfillment: `/envios-fulfillment`; notificaciones: `/devsite/receive-notifications`; convivencia Full y Flex: `/convivencia-full-y-flex`). La documentación de otros países (`.com.br`, `.cl`) puede diferir: aclararlo.
2. **Separar siempre tres cosas al responder**: verificado con la cuenta real, leído en la documentación (con enlace), y suposición. Nunca presentar una suposición como hecho.
3. **No cambiar nombres de columnas, rutas ni parámetros a ojo.** Si un script falla por un nombre, buscar el nombre real en el código (`grep`) antes de reintentar.
4. Pruebas contra la API: solo lectura, con el token en memoria (nunca impreso), y **un solo reintento** si da 429. No insistir: gasta cuota.
5. Todo lo que se pruebe y su resultado se anota abajo.

## Verificado con la cuenta MISTERNUT (usuario 45)
- `GET /items`, `/inventories/{inventory_id}/stock/fulfillment`, `/orders/search`: funcionan (los usa el worker).
- `sub_status` de /items trae `out_of_stock` para publicaciones pausadas por quiebre.
- `GET /stock/fulfillment/operations/search` (2026-10-20): la ruta existe pero respondió **429 over_quota** dos veces seguidas, también tras 45 s. Causa sin confirmar (cuota de la aplicación en cero o no habilitada). Pendiente revisar la aplicación en el devcenter.
- `GET /marketplace/stock/fulfillment/operations/search`: **403 Invalid caller.id**. Es de Global Selling; no sirve para esta cuenta.

## Según la documentación (no probado con la cuenta)
- La documentación de Fulfillment (sitio de Brasil) dice que el envío de mercadería a los galpones lo hace el vendedor desde el Seller Center, y que por API solo se consulta stock y operaciones.
- Las operaciones de stock tienen `type` (por ejemplo `inbound_reception`, `sale_confirmation`); la búsqueda filtra por vendedor, inventario, fechas, tipo y envío; por defecto 15 días, historial de 12 meses.
- Notificaciones de stock de Full (leído en la doc oficial el 2026-10-20): tema **`fbm_stock_operations`**, aviso `{"resource": "/stock/fulfillment/operations/9876", "user_id", "topic", "application_id", "attempts", "sent", "received"}`. Hay que responder HTTP 200 en **menos de 500 ms** o ML desactiva el tema; reintenta durante 1 hora. No trae firma. (Una búsqueda web había dicho `marketplace_fbm_stock`: era incorrecto para Argentina.)
- **Recomendación de reposición** (doc "Planes de reposición para fulfilment", 17/09/2026): `GET /marketplace/fbm/user-products/{user_product_id}/replenishment?country=AR` devuelve stock total, urgencia de envío (`shipping_urgency`), ventas semanales, `recommendation` (cantidad sugerida exacta o rango, plazo) y beneficios. Límite 500 solicitudes/60 s por vendedor; repetir requests idénticos puede bloquear al vendedor. Requiere el `user_product_id` (prefijo MLAU). NO probado con la cuenta.
- La API de creación de inbound (`POST /marketplace/fbm/inbounds`) es solo del modelo Fulfillment China de Global Selling.

## Aplicación de ML que usa el servidor (devcenter, leído 2026-10-20)
- El servidor usa la aplicación **EnvioBot WEB** (Client ID 4025969768673074), compartida con Pedidos; no "EnvioBot Full". Hay 9 aplicaciones en la cuenta LOGAX S.R.L., todas "no certificadas" en el listado.
- Sin ningún tema de notificaciones tildado y con la "Notificaciones callbacks URL" **vacía**. El tema `fbm stock operations` existe (grupo Shipments) pero no está activado. Receptor listo en `POST /api/full/ml/notificaciones` (`notificaciones_ml.py`); falta cargar la URL y tildar el tema.
- Editar la aplicación pide verificación por código al celular del titular: la hace la persona.

## Sin evidencia (no afirmar que existe)
- Crear o modificar la colecta (envío a Full), su franja horaria, transportista, código de autorización o patente por API.
- Pausar/reactivar con `PUT /items/{id}` y cambiar precio: es de uso general, pero no lo usamos ni probamos en Full.
