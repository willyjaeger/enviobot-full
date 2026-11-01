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

- `GET /items/{id}` trae `user_product_id` (MLAU...). `GET /marketplace/fbm/user-products/{user_product_id}/replenishment?country=AR` (2026-10-20): **200 OK con la cuenta MISTERNUT**. Producto 01011: `total_stock` 583 contra 274 en nuestro stock disponible (la doc dice que `total_stock` suma lo almacenado, lo que espera arribo y lo reservado en transferencia), `shipping_urgency` NO_URGENCY, recomendación NO_REPLENISHMENT con cantidad 0, y ventas de 6 semanas con `days_out_of_stock`. La diferencia 583-274 podría ser la colecta en camino: SUPOSICIÓN, sin verificar.

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

## Pantallas de ML (Seller Center), vistas en el navegador el 2026-10-20 con la cuenta LOGAX/MISTERNUT
- Gestión de envíos Full: `vendedores.mercadolibre.com.ar/shipping/inbounds`. Detalle de un envío: `/shipping/inbounds/{n}/hub-v2`. Editar productos: `/shipping/inbounds/{n}/units`. Reserva: `/shipping/inbounds/{n}/appointment`. Carga por planilla: `/shipping/import/excel/upload` (plantilla en `/api/shipping/import/excel/template`).
- Un envío en preparación se puede modificar (cantidades, agregar y quitar productos con un buscador, sin planilla) **hasta 1 día hábil antes de la reserva** (envío #79759779, retiro 28/10: hasta el 27/10 09:44). Enviar una cantidad distinta de la declarada, o cancelar la cita pasada esa hora, tiene **cargos por incumplimiento**.
- La pantalla de edición muestra por producto "Aptas y en camino" (total, en camino, aptas para vender): confirma que el total que ML informa incluye lo que está en camino.
- Todo esto es la interfaz web, NO una API documentada. No se automatiza (ver más arriba: sin evidencia de API para crear o modificar envíos).

## Sin evidencia (no afirmar que existe)
- Crear o modificar la colecta (envío a Full), su franja horaria, transportista, código de autorización o patente por API.
- Pausar/reactivar con `PUT /items/{id}` y cambiar precio: es de uso general, pero no lo usamos ni probamos en Full.

## Revisado el 2026-11-01: ¿hay dato de la cita (mínimo y máximo de unidades) o de la colecta en la API?
- **Doc leída** (`/es_ar/envios-fulfillment` y `/es_ar/planes-de-reposicion-para-fulfilment`): no hay recurso para consultar, ver el detalle ni editar un envío a Full, ni para saber cuánto permite la cita (ML mostró "Tu cita permite entre 451 y 839 u." en la pantalla de editar el envío #81021895). Lo único cercano: `stock.minimum_distributable_stock` de la reposición (es por producto, no por cita) y la advertencia de que la cantidad admitida depende de "validaciones operativas y de capacidad", sin endpoint para consultarlas.
- **Verificado con la cuenta MISTERNUT** (producto 01011): la reposición devuelve `minimum_distributable_stock: 0`, `recommendation` REPLENISH exacta 606, `shipping_urgency` THIS_WEEK, `replenishment_frequency` 4.
- Las operaciones `inbound_reception` traen `external_references` con tipo `inbound_id`, pero `operations/search` sigue dando 429.
- No se miró ni se usa lo que llame la propia pantalla web de ML (punto 7.6 de los términos).
