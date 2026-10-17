---
name: logistica-meli-full
description: Reglas de logística de Mercado Libre Full para EnvioBot Full. Usar al tocar el cálculo de cobertura, quiebre, sobrestock, colectas (inbound), límites de edición, alertas o el panel de colecta.
---

# Logística Full: reglas de EnvioBot Full

Estas son las reglas acordadas con Guillermo. Antes de cambiar un cálculo, leer esto y los tests (`backend/test_proyeccion.py`). El cálculo vive en `backend/proyeccion.py` (funciones puras) y se usa desde `app.py` y `worker.py`.

## Idea central

Lo que pase en Full entre hoy y el ingreso de una colecta **no se puede cambiar**. Mostrar "quiebre inminente" de algo que ya está en una colecta es ruido. Lo que sí se puede cambiar es **cuánto mandar**, y solo **hasta el límite de edición**. Por eso se mira desde el día del ingreso hacia adelante.

## Velocidad de venta (VPD)

`0,50·(v7/7) + 0,35·(v15/15) + 0,15·(v30/30)`. **No se cambia esa ponderación.**
Corrección: cada ventana se divide por los días con stock, no por todos (`vpd_ponderado`). Con menos de 3 días activos no se corrige (sería ruido). Sin historial da igual que siempre. Los días sin stock salen de `stock_daily` (foto diaria que anota el worker; un día cuenta como sin stock si el máximo del día fue 0). Solo se anota con stock real de ML, nunca con el declarado.

## Mercadería entrante y cuándo llega

- `scheduled` (en preparación): llega en `estimated_arrival_date`; si falta, `pickup_date + transit_days`; si falta, preparación + flete.
- `in_transit`: solo el flete.
- recepción (`not_available_stock_full`): 1 día. No 0: ML tarda en dejarla vendible.
- Se proyecta al ingreso más lejano (es el más cauto).

## Cuentas

- Stock al ingreso = `max(0, stock hoy − VPD × días hasta ingreso)`. Nunca negativo.
- Cobertura post-colecta = (stock al ingreso + lo que entra) / VPD.
- Sugerido al ingreso = `max(0, objetivo × VPD − stock al ingreso − lo que entra)`.
- Aviso de ajuste ("subió la venta, preparar N"): solo si la colecta cubre menos del 80 % del objetivo.
- Sobrestock: cobertura (con lo que viene) mayor a `sobrestock_factor` × objetivo (por defecto 1,5). Regla nuestra, no de ML. Sin ventas no se marca.

## Límite de edición de la colecta

La colecta se puede modificar hasta el **día hábil anterior al retiro a las 9:40, hora de Buenos Aires** (una colecta del lunes se cierra el viernes; dato de Guillermo con su cuenta, no confirmado que valga para todos; no contempla feriados). La hora es configurable por depósito (`warehouses.edit_cutoff_time`). Pasada la hora el panel dice que ya no se puede y se calla el aviso de ajuste.

Una hora antes del límite `backend/aviso_limite_colecta.py` avisa por WhatsApp y mail (una vez por colecta y por canal). Necesita un cron cada 10 minutos en el servidor, que se carga aparte y con OK de Guillermo.

## Horario de WhatsApp

Los WhatsApp salen **solo de lunes a viernes de 8:30 a 18:00** (Buenos Aires), en cualquier alerta (`backend/horario_whatsapp.py`). Fuera de horario no se manda ni se anota como enviado: sale en la próxima corrida dentro del horario. El mail no tiene esa restricción. El control de repetición (cooldown) es por canal, para que un mail ya enviado no bloquee el WhatsApp pendiente.

## Qué NO hacer

- No mostrar alertas rojas de quiebre de lo que ya está en una colecta.
- No tocar la ponderación del VPD ni los estados existentes (`ok/warning/critical/out_of_stock/in_*`): los usan las alertas de los clientes.
- No prometer crear la colecta en ML por API: no está confirmado (ver `docs/Datos_EnvioBot_Full.xlsx`, hojas 4 y 6).
- No usar predicción con IA: la fórmula es determinista y explicable. Si algún día hace falta estacionalidad (Cyber Monday) se hace con historial diario de ventas, no con un modelo opaco.
- Nada de plata ni ventas en el panel del cliente (criterio común 6).

## Datos de ML que podemos usar

Ver `docs/Datos_EnvioBot_Full.xlsx`. Hoy se leen: publicaciones, stock Full (`available_quantity`, `not_available_quantity`), ventas. Documentado pero sin verificar: `GET /stock/fulfillment/operations/search` (ingresos reales) para marcar la colecta como recibida sola.

## Cambios de base

Todo cambio de estructura sale en un `migration_NNN_*.sql` que verifica el estado antes de alterar, se aplica con el servicio apagado, con respaldo y con OK de Guillermo. El código nuevo se apaga solo si falta la columna (`backend/esquema.py`).
