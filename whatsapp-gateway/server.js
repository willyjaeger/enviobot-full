const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    makeCacheableSignalKeyStore,
    fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');
const express = require('express');
const pino = require('pino');
const qrcode = require('qrcode');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(express.json());

const silentLogger = pino({ level: 'silent' });

let sock = null;
let currentQR = null;
let connectionStatus = 'disconnected';

const COLECTA_AUTH_BASE = path.join(__dirname, 'auth_colecta');
if (!fs.existsSync(COLECTA_AUTH_BASE)) {
    fs.mkdirSync(COLECTA_AUTH_BASE, { recursive: true });
}

function readInternalSecret() {
    if (process.env.WA_INTERNAL_SECRET) return process.env.WA_INTERNAL_SECRET.trim();
    if (process.env.JWT_SECRET_KEY) return process.env.JWT_SECRET_KEY.trim();
    const candidates = [
        '/var/www/enviobot-full/backend/.env',
        path.join(__dirname, '..', 'backend', '.env'),
    ];
    for (const envPath of candidates) {
        try {
            if (!fs.existsSync(envPath)) continue;
            const raw = fs.readFileSync(envPath, 'utf8');
            let jwtSecret = '';
            for (const line of raw.split(/\r?\n/)) {
                const m = line.match(/^\s*(WA_INTERNAL_SECRET|JWT_SECRET_KEY)\s*=\s*(.+)\s*$/);
                if (!m) continue;
                const val = m[2].replace(/^['"]|['"]$/g, '').trim();
                if (m[1] === 'WA_INTERNAL_SECRET' && val) return val;
                if (m[1] === 'JWT_SECRET_KEY' && val) jwtSecret = val;
            }
            if (jwtSecret) return jwtSecret;
        } catch (_) {}
    }
    return '';
}

// Mapa userId -> { sock, status, qr, phone, reconnectTimer }
const colectaListeners = new Map();
const processedMsgIds = new Set();

function extractMessageText(msg) {
    if (!msg || !msg.message) return '';
    const m = msg.message.ephemeralMessage?.message
        || msg.message.viewOnceMessage?.message
        || msg.message.viewOnceMessageV2?.message
        || msg.message.documentWithCaptionMessage?.message
        || msg.message;
    return (
        m.conversation
        || m.extendedTextMessage?.text
        || m.imageMessage?.caption
        || m.videoMessage?.caption
        || m.documentMessage?.caption
        || ''
    ).trim();
}

function cleanPhoneFromJid(jid) {
    if (!jid) return '';
    return String(jid).split('@')[0].split(':')[0].replace(/\D+/g, '');
}

async function notifyBackendIncoming(payload) {
    try {
        const secret = readInternalSecret();
        const resp = await fetch('http://127.0.0.1:5001/api/full/internal/wa-colecta-incoming', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Internal-Token': secret,
            },
            body: JSON.stringify(payload),
        });
        const data = await resp.json().catch(() => ({}));
        console.log(`[ColectaWA] Backend respondio HTTP ${resp.status}:`, JSON.stringify(data));
    } catch (err) {
        console.error('[ColectaWA] Error notificando al backend:', err.message);
    }
}

async function startColectaListener(userId, forceReset = false) {
    const key = String(userId).replace(/\D+/g, '');
    if (!key) throw new Error('userId invalido');
    const authDir = path.join(COLECTA_AUTH_BASE, `user_${key}`);

    let entry = colectaListeners.get(key);
    if (entry && entry.reconnectTimer) {
        clearTimeout(entry.reconnectTimer);
        entry.reconnectTimer = null;
    }

    if (forceReset && entry && entry.sock) {
        try { entry.sock.ev.removeAllListeners(); entry.sock.end(); } catch (_) {}
        entry.sock = null;
    }
    if (forceReset && fs.existsSync(authDir)) {
        fs.rmSync(authDir, { recursive: true, force: true });
    }
    if (!fs.existsSync(authDir)) {
        fs.mkdirSync(authDir, { recursive: true });
    }

    if (entry && entry.sock && (entry.status === 'open' || (entry.status === 'connecting' && entry.qr && !forceReset))) {
        return entry;
    }

    const { state, saveCreds } = await useMultiFileAuthState(authDir);
    let version = undefined;
    try {
        const vInfo = await fetchLatestBaileysVersion();
        version = vInfo.version;
    } catch (_) {}

    const listenerSock = makeWASocket({
        ...(version ? { version } : {}),
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, silentLogger),
        },
        printQRInTerminal: false,
        logger: silentLogger,
        browser: ['EnvioBot Colectas', 'Chrome', '1.0.0'],
        syncFullHistory: false,
        markOnlineOnConnect: false,
        getMessage: async () => ({ conversation: '' }),
    });

    entry = {
        userId: key,
        sock: listenerSock,
        status: 'connecting',
        qr: null,
        phone: cleanPhoneFromJid(state?.creds?.me?.id),
        reconnectTimer: null,
    };
    colectaListeners.set(key, entry);

    listenerSock.ev.on('creds.update', saveCreds);

    listenerSock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr) {
            entry.qr = await qrcode.toDataURL(qr);
            entry.status = 'connecting';
        }
        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const loggedOut = statusCode === DisconnectReason.loggedOut;
            entry.qr = null;
            entry.status = 'close';
            entry.sock = null;
            if (loggedOut) {
                if (fs.existsSync(authDir)) {
                    fs.rmSync(authDir, { recursive: true, force: true });
                }
                entry.phone = '';
            } else {
                entry.reconnectTimer = setTimeout(() => {
                    startColectaListener(key, false).catch(err => console.error('[ColectaWA] Reconnect error:', err.message));
                }, 4000);
            }
        } else if (connection === 'open') {
            entry.status = 'open';
            entry.qr = null;
            entry.phone = cleanPhoneFromJid(listenerSock.user?.id || state?.creds?.me?.id) || entry.phone;
            console.log(`[ColectaWA] Listener conectado para user_${key}: ${entry.phone}`);
        }
    });

    listenerSock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (!Array.isArray(messages)) return;
        const nowSec = Math.floor(Date.now() / 1000);
        for (const msg of messages) {
            try {
                if (!msg || !msg.key || msg.key.fromMe) continue;
                const remoteJid = msg.key.remoteJid || '';
                if (!remoteJid || remoteJid === 'status@broadcast' || remoteJid.endsWith('@g.us')) continue;
                const msgTs = Number(msg.messageTimestamp || 0);
                if (type !== 'notify' && msgTs && (nowSec - msgTs > 900)) continue;
                const text = extractMessageText(msg);
                if (!text) continue;
                const msgId = msg.key.id || '';
                if (msgId && processedMsgIds.has(`${key}:${msgId}`)) continue;
                if (msgId) {
                    processedMsgIds.add(`${key}:${msgId}`);
                    if (processedMsgIds.size > 500) {
                        const first = processedMsgIds.values().next().value;
                        processedMsgIds.delete(first);
                    }
                }
                const senderPhone = cleanPhoneFromJid(msg.key.participant || remoteJid);
                const senderName = msg.pushName || senderPhone || 'WhatsApp';
                console.log(`[ColectaWA user_${key}] (${type}) Mensaje de ${senderName} (${senderPhone}): ${text.slice(0, 100)}`);
                await notifyBackendIncoming({
                    user_id: Number(key),
                    listener_phone: entry.phone ? `+${entry.phone}` : '',
                    sender_phone: senderPhone ? `+${senderPhone}` : '',
                    sender_name: senderName,
                    text,
                    message_id: msgId,
                });
            } catch (e) {
                console.error('[ColectaWA] Error procesando mensaje:', e.message);
            }
        }
    });

    return entry;
}

function restoreSavedColectaListeners() {
    try {
        const dirs = fs.readdirSync(COLECTA_AUTH_BASE, { withFileTypes: true });
        for (const d of dirs) {
            if (!d.isDirectory() || !d.name.startsWith('user_')) continue;
            const userId = d.name.replace(/^user_/, '');
            const credsFile = path.join(COLECTA_AUTH_BASE, d.name, 'creds.json');
            if (fs.existsSync(credsFile)) {
                console.log(`[ColectaWA] Restaurando sesion guardada para user_${userId}...`);
                startColectaListener(userId, false).catch(e => console.error(`[ColectaWA] Error restaurando user_${userId}:`, e.message));
            }
        }
    } catch (e) {
        console.error('[ColectaWA] Error leyendo sesiones guardadas:', e.message);
    }
}

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('./auth_info');

    sock = makeWASocket({
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, silentLogger),
        },
        printQRInTerminal: true,
        logger: silentLogger,
        browser: ['EnvioBot Gateway', 'Chrome', '1.0.0'],
        getMessage: async () => ({ conversation: '' }),
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            currentQR = await qrcode.toDataURL(qr);
            connectionStatus = 'qr_ready';
            console.log('Nuevo codigo QR generado. Escanealo en /qr');
        }

        if (connection === 'close') {
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
            connectionStatus = 'disconnected';
            currentQR = null;
            console.log('Conexion cerrada. Reconectando:', shouldReconnect);
            if (shouldReconnect) {
                setTimeout(connectToWhatsApp, 4000);
            }
        } else if (connection === 'open') {
            connectionStatus = 'connected';
            currentQR = null;
            console.log('WhatsApp Gateway conectado exitosamente!');
        }
    });
}

// Endpoint para verificar estado general
app.get('/status', (req, res) => {
    res.json({
        status: connectionStatus,
        connected: connectionStatus === 'connected',
        has_qr: !!currentQR
    });
});

// Endpoint visual para escanear el QR desde el navegador
app.get('/qr', (req, res) => {
    if (connectionStatus === 'connected') {
        return res.send('<h2 style="font-family:sans-serif; color:green;">WhatsApp ya esta conectado y listo para enviar alertas!</h2>');
    }
    if (!currentQR) {
        return res.send('<h3 style="font-family:sans-serif;">Generando codigo QR... recarga la pagina en 3 segundos.</h3><script>setTimeout(()=>location.reload(), 3000);</script>');
    }
    res.send(`
        <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:90vh; font-family:sans-serif;">
            <h2>Escanea este QR con el WhatsApp de EnvioBot</h2>
            <p>Abri WhatsApp > Dispositivos vinculados > Vincular un dispositivo</p>
            <img src="${currentQR}" style="width:300px; height:300px; border:2px solid #25D366; border-radius:12px; padding:10px;" />
            <p style="color:#666; font-size:13px;">La pagina se actualizara automaticamente...</p>
            <script>setTimeout(()=>location.reload(), 5000);</script>
        </div>
    `);
});

// ── Endpoints para el WhatsApp receptor de Colectas de cada cuenta ──
app.get('/colecta-listener/:userId/status', (req, res) => {
    const key = String(req.params.userId || '').replace(/\D+/g, '');
    const entry = colectaListeners.get(key);
    if (!entry) {
        return res.json({ ok: true, status: 'close', phone: '', qr: null, has_qr: false });
    }
    res.json({
        ok: true,
        status: entry.status,
        phone: entry.phone || '',
        qr: entry.qr || null,
        has_qr: !!entry.qr,
    });
});

app.post('/colecta-listener/:userId/connect', async (req, res) => {
    try {
        const key = String(req.params.userId || '').replace(/\D+/g, '');
        const forceReset = !!(req.body && req.body.reset);
        const entry = await startColectaListener(key, forceReset);
        for (let i = 0; i < 12 && entry.status === 'connecting' && !entry.qr; i++) {
            await new Promise(r => setTimeout(r, 250));
        }
        res.json({
            ok: true,
            status: entry.status,
            phone: entry.phone || '',
            qr: entry.qr || null,
            has_qr: !!entry.qr,
        });
    } catch (e) {
        res.status(500).json({ ok: false, error: e.message });
    }
});

app.post('/colecta-listener/:userId/logout', async (req, res) => {
    try {
        const key = String(req.params.userId || '').replace(/\D+/g, '');
        const authDir = path.join(COLECTA_AUTH_BASE, `user_${key}`);
        const entry = colectaListeners.get(key);
        if (entry) {
            if (entry.reconnectTimer) clearTimeout(entry.reconnectTimer);
            if (entry.sock) {
                try { await entry.sock.logout(); } catch (_) {}
                try { entry.sock.ev.removeAllListeners(); entry.sock.end(); } catch (_) {}
            }
            colectaListeners.delete(key);
        }
        if (fs.existsSync(authDir)) {
            fs.rmSync(authDir, { recursive: true, force: true });
        }
        res.json({ ok: true, status: 'close', phone: '', qr: null, has_qr: false });
    } catch (e) {
        res.status(500).json({ ok: false, error: e.message });
    }
});

// Endpoint para enviar mensajes desde el backend Python
app.post('/send-message', async (req, res) => {
    try {
        if (connectionStatus !== 'connected' || !sock) {
            return res.status(503).json({ ok: false, error: 'WhatsApp no esta conectado' });
        }

        const { number, text } = req.body;
        if (!number || !text) {
            return res.status(400).json({ ok: false, error: 'Faltan parametros number o text' });
        }

        let cleanNumber = number.toString().replace(/\D/g, '');
        if (cleanNumber.startsWith('5411') && cleanNumber.length === 12) {
            cleanNumber = '54911' + cleanNumber.substring(4);
        }

        const [result] = await sock.onWhatsApp(cleanNumber);
        const jid = (result && result.exists) ? result.jid : `${cleanNumber}@s.whatsapp.net`;

        const sentMsg = await sock.sendMessage(jid, { text: text });
        res.json({
            ok: true,
            message_id: sentMsg.key.id,
            to: jid,
            status: 'sent'
        });

    } catch (error) {
        console.error('Error enviando mensaje:', error);
        res.status(500).json({ ok: false, error: error.message });
    }
});

// Endpoint para enviar mensajes con botones interactivos
app.post('/send-buttons', async (req, res) => {
    try {
        if (connectionStatus !== 'connected' || !sock) {
            return res.status(503).json({ ok: false, error: 'WhatsApp no esta conectado' });
        }

        const { number, title, text, footer, buttons } = req.body;
        if (!number || !text || !Array.isArray(buttons) || buttons.length === 0) {
            return res.status(400).json({ ok: false, error: 'Faltan parametros number, text o buttons' });
        }

        let cleanNumber = number.toString().replace(/\D/g, '');
        if (cleanNumber.startsWith('5411') && cleanNumber.length === 12) {
            cleanNumber = '54911' + cleanNumber.substring(4);
        }

        const [result] = await sock.onWhatsApp(cleanNumber);
        const jid = (result && result.exists) ? result.jid : `${cleanNumber}@s.whatsapp.net`;

        const fullMessage = `${title ? `*${title}*\n\n` : ''}${text}\n\n*Toca el link para confirmar en 1 clic:*\n${buttons[0].url || ''}\n\n_${footer || 'EnvioBot Full'}_`;

        const sentMsg = await sock.sendMessage(jid, {
            text: fullMessage,
            linkPreview: false
        });

        res.json({
            ok: true,
            message_id: sentMsg.key.id,
            to: jid,
            status: 'sent_interactive'
        });

    } catch (error) {
        console.error('Error enviando botones:', error);
        res.status(500).json({ ok: false, error: error.message });
    }
});

const PORT = 8085;
app.listen(PORT, '127.0.0.1', () => {
    console.log(`WhatsApp Gateway corriendo en http://127.0.0.1:${PORT}`);
    connectToWhatsApp();
    restoreSavedColectaListeners();
});
