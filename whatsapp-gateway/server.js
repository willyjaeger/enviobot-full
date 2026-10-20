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

const PORT = 8085;
const AUTH_DIR = path.join(__dirname, 'auth_info');
const COLECTA_AUTH_BASE = path.join(__dirname, 'auth_colecta');
if (!fs.existsSync(COLECTA_AUTH_BASE)) {
    fs.mkdirSync(COLECTA_AUTH_BASE, { recursive: true });
}

const silentLogger = pino({ level: 'silent' });

let sock = null;
let currentQr = null;
let currentQrDataUrl = null;
let connectionStatus = 'close'; // 'close' | 'connecting' | 'open'
let connectedPhone = null;

// Ultimos mensajes enviados: WhatsApp los pide de nuevo cuando el telefono del destinatario
// no logra descifrarlos ("Esperando mensaje..."). Sin esto no se pueden reenviar.
const mensajesEnviados = new Map();
function guardarMensaje(resultado) {
    if (resultado && resultado.key && resultado.key.id && resultado.message) {
        mensajesEnviados.set(resultado.key.id, resultado.message);
        if (mensajesEnviados.size > 500) {
            mensajesEnviados.delete(mensajesEnviados.keys().next().value);
        }
    }
}

function readInternalSecret() {
    if (process.env.WA_INTERNAL_SECRET) return process.env.WA_INTERNAL_SECRET.trim();
    const candidates = [
        '/var/www/enviobot-full/backend/.env',
        path.join(__dirname, '..', 'backend', '.env'),
    ];
    for (const envPath of candidates) {
        try {
            if (!fs.existsSync(envPath)) continue;
            const raw = fs.readFileSync(envPath, 'utf8');
            for (const line of raw.split(/\r?\n/)) {
                const m = line.match(/^\s*WA_INTERNAL_SECRET\s*=\s*(.+)\s*$/);
                if (!m) continue;
                const val = m[1].replace(/^['"]|['"]$/g, '').trim();
                if (val) return val;
            }
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

async function startWhatsApp() {
    connectionStatus = 'connecting';
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

    sock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
        logger: silentLogger,
        browser: ['EnvioBot Full', 'Chrome', '120.0.0'],
        getMessage: async (key) => mensajesEnviados.get(key.id)
    });

    const enviarOriginal = sock.sendMessage.bind(sock);
    sock.sendMessage = async (...args) => {
        const resultado = await enviarOriginal(...args);
        guardarMensaje(resultado);
        return resultado;
    };

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            currentQr = qr;
            try {
                currentQrDataUrl = await qrcode.toDataURL(qr);
            } catch (e) {
                console.error('Error generando QR data URL:', e);
            }
            connectionStatus = 'connecting';
            console.log('[WhatsApp Gateway] Nuevo codigo QR generado listo para escanear.');
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            connectionStatus = 'close';
            currentQr = null;
            currentQrDataUrl = null;
            connectedPhone = null;
            console.log(`[WhatsApp Gateway] Conexion cerrada (${statusCode}). Reintentando: ${shouldReconnect}`);

            if (shouldReconnect) {
                setTimeout(startWhatsApp, 3000);
            } else {
                console.log('[WhatsApp Gateway] Sesion cerrada / Logged out. Limpiando credenciales...');
                try {
                    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
                } catch (e) {}
                setTimeout(startWhatsApp, 2000);
            }
        } else if (connection === 'open') {
            connectionStatus = 'open';
            currentQr = null;
            currentQrDataUrl = null;
            const jid = sock.user?.id || '';
            connectedPhone = jid.split(':')[0] || jid.split('@')[0];
            console.log(`[WhatsApp Gateway] Conectado exitosamente como: ${connectedPhone}`);
        }
    });
}

// ENDPOINTS HTTP (Instancia principal EnvioBot Full)
app.get('/status', (req, res) => {
    res.json({
        ok: true,
        status: connectionStatus,
        connected: connectionStatus === 'open',
        phone: connectedPhone,
        has_qr: !!currentQrDataUrl
    });
});

app.get('/instance/status', (req, res) => {
    res.json({
        ok: true,
        status: connectionStatus,
        phone: connectedPhone,
        qr: currentQrDataUrl,
        has_qr: !!currentQrDataUrl
    });
});

app.get('/qr', (req, res) => res.redirect('/instance/qr'));

app.get('/instance/qr', (req, res) => {
    if (connectionStatus === 'open') {
        return res.send(`<html><body style="font-family:sans-serif;text-align:center;padding:50px;">
            <h2 style="color:#22c55e;">&#10004; WhatsApp ya esta conectado</h2>
            <p>Numero vinculado: <b>+${connectedPhone}</b></p>
        </body></html>`);
    }
    if (!currentQrDataUrl) {
        return res.send(`<html><body style="font-family:sans-serif;text-align:center;padding:50px;">
            <h2>Iniciando instancia...</h2>
            <p>Espera 3 segundos y recarga esta pagina.</p>
            <script>setTimeout(() => location.reload(), 3000);</script>
        </body></html>`);
    }
    res.send(`<html><body style="font-family:sans-serif;text-align:center;padding:30px;background:#111;color:#fff;">
        <h2>Escanear con WhatsApp Business</h2>
        <p style="color:#aaa;">Abre WhatsApp &gt; Dispositivos vinculados &gt; Vincular un dispositivo</p>
        <img src="${currentQrDataUrl}" style="width:280px;height:280px;border-radius:12px;background:#fff;padding:12px;margin:16px 0;" />
        <p style="font-size:12px;color:#888;">Esta pagina se actualiza sola.</p>
        <script>
            setInterval(async () => {
                const r = await fetch('/instance/status');
                const d = await r.json();
                if (d.status === 'open') location.reload();
            }, 3000);
        </script>
    </body></html>`);
});

// Envio de texto simple (/message/sendText/:instance y alias /send-message)
async function handleSendText(req, res) {
    if (connectionStatus !== 'open' || !sock) {
        return res.status(503).json({
            ok: false,
            error: 'WhatsApp no esta conectado. Escanea el codigo QR primero.'
        });
    }

    try {
        const rawNumber = req.body.number || req.body.to || '';
        let text = '';
        if (req.body.textMessage && req.body.textMessage.text) {
            text = req.body.textMessage.text;
        } else if (req.body.text) {
            text = req.body.text;
        } else if (req.body.body) {
            text = req.body.body;
        }

        if (!rawNumber || !text) {
            return res.status(400).json({ ok: false, error: 'Falta number o texto del mensaje.' });
        }

        let clean = String(rawNumber).replace(/[^\d]/g, '');
        if (clean.startsWith('5411') && clean.length === 12) {
            clean = '54911' + clean.substring(4);
        }
        const jid = `${clean}@s.whatsapp.net`;

        const result = await sock.sendMessage(jid, { text: text });
        res.json({
            ok: true,
            message_id: result.key?.id,
            to: clean,
            status: 'SENT'
        });
    } catch (err) {
        console.error('[Error enviando mensaje WhatsApp]:', err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
}

app.post('/message/sendText/:instance', handleSendText);
app.post('/send-message', handleSendText);

// Envio de imagen (por URL publica) con texto al pie
app.post('/message/sendMedia/:instance', async (req, res) => {
    if (connectionStatus !== 'open' || !sock) {
        return res.status(503).json({ ok: false, error: 'WhatsApp no esta conectado.' });
    }
    try {
        const m = req.body.mediaMessage || {};
        const clean = String(req.body.number || '').replace(/[^\d]/g, '');
        if (!clean || !m.media) {
            return res.status(400).json({ ok: false, error: 'Falta number o media.' });
        }
        const result = await sock.sendMessage(`${clean}@s.whatsapp.net`, { image: { url: m.media }, caption: m.caption || '' });
        res.json({ ok: true, message_id: result.key?.id, to: clean, status: 'SENT' });
    } catch (err) {
        console.error('[Error enviando imagen WhatsApp]:', err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

// Envio de tarjeta de contacto (vCard 3.0)
app.post('/message/sendContact/:instance', async (req, res) => {
    if (connectionStatus !== 'open' || !sock) {
        return res.status(503).json({
            ok: false,
            error: 'WhatsApp no esta conectado. Escanea el codigo QR primero.'
        });
    }

    try {
        const rawNumber = req.body.number || req.body.to || '';
        if (!rawNumber) {
            return res.status(400).json({ ok: false, error: 'Falta number del destinatario.' });
        }

        let clean = String(rawNumber).replace(/[^\d]/g, '');
        let jid = `${clean}@s.whatsapp.net`;

        let vcards = [];
        let displayName = req.body.displayName || req.body.name || 'EnvioBot Full';

        if (req.body.vcard) {
            vcards.push({ vcard: req.body.vcard });
        } else if (Array.isArray(req.body.contact)) {
            for (const c of req.body.contact) {
                const cName = c.fullName || c.name || displayName;
                const cPhone = String(c.phoneNumber || c.phone || c.wuid || connectedPhone || '5491128594631').replace(/[^\d]/g, '');
                displayName = cName;
                const vcard = [
                    'BEGIN:VCARD',
                    'VERSION:3.0',
                    `FN:${cName}`,
                    `ORG:${c.organization || 'EnvioBot'};`,
                    `TITLE:${c.title || 'Alertas de Stock Full'}`,
                    `TEL;type=CELL;type=VOICE;waid=${cPhone}:+${cPhone}`,
                    `URL:${c.url || 'https://enviobot.com.ar'}`,
                    `NOTE:${c.note || 'Asistente oficial de alertas de reposicion y colecta en Mercado Envios Full.'}`,
                    'END:VCARD'
                ].join('\n');
                vcards.push({ vcard });
            }
        } else {
            const c = req.body.contact || {};
            const cName = c.name || req.body.name || req.body.displayName || displayName;
            const cPhone = String(c.phone || req.body.phone || connectedPhone || '5491128594631').replace(/[^\d]/g, '');
            displayName = cName;
            const vcard = [
                'BEGIN:VCARD',
                'VERSION:3.0',
                `FN:${cName}`,
                `ORG:${c.org || c.organization || 'EnvioBot'};`,
                `TITLE:${c.title || 'Alertas de Stock Full'}`,
                `TEL;type=CELL;type=VOICE;waid=${cPhone}:+${cPhone}`,
                `URL:${c.url || 'https://enviobot.com.ar'}`,
                `NOTE:${c.note || 'Asistente oficial de alertas de reposicion y colecta en Mercado Envios Full.'}`,
                'END:VCARD'
            ].join('\n');
            vcards.push({ vcard });
        }

        const result = await sock.sendMessage(jid, {
            contacts: {
                displayName: displayName,
                contacts: vcards
            }
        });

        res.json({
            ok: true,
            message_id: result.key?.id,
            to: clean,
            displayName: displayName,
            status: 'SENT'
        });
    } catch (err) {
        console.error('[Error enviando contacto vCard WhatsApp]:', err);
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
});

// Reiniciar sesion o desconectar
app.post('/instance/logout', async (req, res) => {
    try {
        if (sock) {
            await sock.logout().catch(() => {});
        }
        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        connectionStatus = 'close';
        currentQr = null;
        currentQrDataUrl = null;
        connectedPhone = null;
        setTimeout(startWhatsApp, 2000);
        res.json({ ok: true, message: 'Sesion cerrada y reiniciando...' });
    } catch (e) {
        res.status(500).json({ ok: false, error: e.message });
    }
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

app.listen(PORT, '127.0.0.1', () => {
    console.log(`[WhatsApp Gateway] Servidor listo en http://127.0.0.1:${PORT}`);
    startWhatsApp();
    restoreSavedColectaListeners();
});
