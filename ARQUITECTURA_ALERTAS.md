# Arquitectura Completa de Alertas Autónomas, WhatsApp y Cron (EnvioBot Full)

Resumen de los componentes desarrollados para el funcionamiento 100% autónomo y cloud de EnvioBot Full:

1. **WhatsApp Service (`backend/whatsapp_service.py`)**:
   - Soporte para **Evolution API** (v1/v2) en DonWeb VPS (costo $0).
   - Soporte para Gateway HTTP alternativo (UltraMsg / W-API).
   - Modo simulación / sandbox automático si no hay credenciales configuradas.
   - Pacing / cola con delay entre mensajes (3-5s) y simulación de tipeo.
   - Normalización de números telefónicos (E.164).
   - Plantillas de 3 niveles: Preventivo, Colecta Hoy y Alerta Crítica.

2. **Motor de Alertas (`backend/alerts_engine.py`)**:
   - Clasificación de publicaciones según días de cobertura vs demora del flete + colchón.
   - Idempotencia con tabla `alert_logs` (evita repetir alertas en menos de 20hs).
   - Generación de **Digest Consolidado** (1 solo mensaje diario por cliente).
   - Despacho multicanal (WhatsApp y Email SMTP DonWeb).
   - Filtrado por rol y depósito de destino de los `alert_recipients`.

3. **Cron de Servidor Linux / DonWeb (`backend/cron_runner.sh` y `backend/crontab.example`)**:
   - `0 8,12,16,20 * * * /bin/bash /var/www/enviobot-full/backend/cron_runner.sh`
   - Ejecución autónoma 24/7 sin depender de que la PC esté encendida.
   - Comandos CLI: `python worker.py --alerts-only` o `python worker.py --user <id>`.

4. **Notificaciones Nativas de Pantalla (`frontend/sw.js` y `frontend/js/notifications.js`)**:
   - Zero instalación de ejecutables (Windows y Mac).
   - Notificaciones nativas con sonido en pantalla mediante Service Worker y Notification API.
   - Cooldown de 4 horas para no saturar al usuario durante el uso de la app.
   - Botón de activación y prueba en el modal de configuración.
