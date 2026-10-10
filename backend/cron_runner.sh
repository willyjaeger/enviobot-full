#!/bin/bash
# ==============================================================================
# cron_runner.sh - Ejecutor programado para EnvioBot Full (DonWeb VPS)
# Sincroniza stocks de MeLi Full y dispara alertas por WhatsApp / Email.
# ==============================================================================

set -e

# Directorio base del proyecto
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${BASE_DIR}/logs"
LOG_FILE="${LOG_DIR}/worker_$(date +'%Y%m%d').log"

# Asegurar existencia de directorio de logs
mkdir -p "${LOG_DIR}"

echo "==================================================================" >> "${LOG_FILE}"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando ejecución de EnvioBot Full Worker..." >> "${LOG_FILE}"

# Activar entorno virtual de Python si existe
if [ -d "${BASE_DIR}/venv" ]; then
    source "${BASE_DIR}/venv/bin/activate"
fi

# Ejecutar el worker de sincronización y alertas
cd "${BASE_DIR}"
python3 worker.py >> "${LOG_FILE}" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ejecución finalizada con éxito." >> "${LOG_FILE}"
echo "==================================================================" >> "${LOG_FILE}"
