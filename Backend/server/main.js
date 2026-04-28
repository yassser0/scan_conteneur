require('dotenv').config();

const path = require('path');
const express = require('express');
const session = require('express-session');
const cors = require('cors');
const { MongoClient, ObjectId } = require('mongodb');
const multer = require('multer');
const http = require('http');
const bcrypt = require('bcryptjs');
function callOllama(prompt) {
    return new Promise((resolve) => {
        const body = JSON.stringify({
            model: process.env.OLLAMA_MODEL || 'mistral:7b',
            prompt,
            stream: false
        });

        const url = new URL(`${process.env.OLLAMA_URL || 'http://localhost:11434'}/api/generate`);
        const options = {
            hostname: url.hostname,
            port: url.port || 11434,
            path: url.pathname,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(body)
            }
        };

        const req = http.request(options, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    const json = JSON.parse(data);
                    resolve(json.response || '');
                } catch {
                    resolve('');
                }
            });
        });

        req.on('error', () => resolve(''));
        req.setTimeout(30000, () => { req.destroy(); resolve(''); });
        req.write(body);
        req.end();
    });
}

const app = express();
app.use(cors({ origin: 'http://localhost:5173', credentials: true }));
app.use(express.json());

// Store image in memory so we can save it as BinData in MongoDB
const upload = multer({ storage: multer.memoryStorage() });
app.use(session({
    secret: process.env.SESSION_SECRET || 'secret-key-marsa-scan',
    resave: true,
    saveUninitialized: true,
    cookie: { 
        secure: false, // Set to true if using https
        maxAge: 30 * 24 * 60 * 60 * 1000 // 30 days limit
    }
}));

const client = new MongoClient(process.env.MONGO_URI);

let db;
let users;
let teams;
let cameras;
let containers;
let scans;
let scan_sessions;
let verifications;
let alerts;
let terminals;
let stops;


async function connectDB() {
    try {
        await client.connect();

        db = client.db(process.env.DB_NAME);
        users        = db.collection("users");
        teams        = db.collection("teams");
        cameras      = db.collection("cameras");
        await cameras.dropIndex("camera_code_1").catch(() => {});
        containers   = db.collection("containers");
        scans        = db.collection("scans");
        scan_sessions = db.collection("scan_sessions");
        verifications = db.collection("verifications");
        alerts       = db.collection("alerts");
        terminals    = db.collection("terminals");
        stops        = db.collection("stops");

        // Always ensure the default admin user exists with the correct password
        const adminEmail = (process.env.DEFAULT_ADMIN_EMAIL || 'admin@marsa.ma').toLowerCase();
        const hashedPassword = await bcrypt.hash(process.env.DEFAULT_ADMIN_PASSWORD || 'admin123', 10);
        await users.updateOne(
            { email: adminEmail },
            { $set: { email: adminEmail, password: hashedPassword, role: 'admin' }, $setOnInsert: { created_at: new Date() } },
            { upsert: true }
        );
        console.log("✅ Default admin user ready");

        console.log("✅ MongoDB connected");

    } catch (error) {
        console.error("❌ MongoDB connection failed:", error);
    }
}

connectDB();



app.post('/extract-code', upload.single('screenshot'), async (req, res) => {

    const { container_code, iso_size_type, shipping_company, camera_id } = req.body;

    if (!container_code) {
        return res.status(400).json({
            error: "container_code is required"
        });
    }

    try {

        const result = await scans.updateOne(

            { container_code: container_code },

            {
                $set: {
                    iso_code: iso_size_type || "Non Scanné",
                    shipping_company: shipping_company || "Non spécifié",
                    camera_id: camera_id || "1",
                    ...(req.file && {
                        screenshot: req.file.buffer,
                        screenshot_mime: req.file.mimetype
                    })
                },

                $setOnInsert: {
                    container_code: container_code,
                    created_at: new Date()
                }
            },

            { upsert: true }
        );

        res.json({
            message: "Container saved successfully",
            result: result
        });

    } catch (error) {

        console.error(error);

        res.status(500).json({
            error: "Server error"
        });

    }

});


// ---------------- SERVE CONTAINER SCREENSHOT ----------------

app.get('/container-image/:container_code', async (req, res) => {
    try {
        const doc = await scans.findOne(
            { container_code: req.params.container_code },
            { projection: { screenshot: 1, screenshot_mime: 1 } }
        );

        if (!doc || !doc.screenshot) {
            return res.status(404).json({ error: "No image found" });
        }

        const mime = doc.screenshot_mime || 'image/jpeg';
        const buffer = Buffer.isBuffer(doc.screenshot)
            ? doc.screenshot
            : Buffer.from(doc.screenshot.buffer);

        res.set('Content-Type', mime);
        res.send(buffer);

    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});


// ---------------- AUTHENTICATION ----------------
app.post('/login', async (req, res) => {
    const { email, password } = req.body;

    if (!email || !password) {
        return res.status(400).json({ success: false, message: "Email et mot de passe requis" });
    }

    try {
        const user = await users.findOne({ email: email.toLowerCase().trim() });

        if (!user) {
            return res.status(401).json({ success: false, message: "Identifiants invalides" });
        }

        const match = await bcrypt.compare(password, user.password);

        if (!match) {
            return res.status(401).json({ success: false, message: "Identifiants invalides" });
        }

        req.session.user = { email: user.email, role: user.role };
        return res.json({ success: true, message: "Connecté avec succès" });

    } catch (error) {
        console.error("Login error:", error);
        return res.status(500).json({ success: false, message: "Erreur serveur" });
    }
});

app.post('/logout', (req, res) => {
    req.session.destroy();
    res.json({ success: true, message: "Logged out" });
});

app.get('/auth/status', (req, res) => {
    if (req.session.user) {
        res.json({ authenticated: true, user: req.session.user });
    } else {
        res.json({ authenticated: false });
    }
});


// ---------------- GET ALL CONTAINERS ----------------

app.get('/view-data', async (req, res) => {

    if (!req.session.user) {
        return res.status(401).json({ error: "Unauthorized" });
    }

    try {

        // Get all scans sorted by newest (exclude binary screenshot field)
        const data = await scans
            .find({}, { projection: { screenshot: 0, screenshot_mime: 0 } })
            .sort({ created_at: -1 })
            .toArray();

        res.json(data);

    } catch (error) {

        console.error(error);

        res.status(500).json({
            error: "Server error"
        });

    }

});

// ---------------- UPDATE / DELETE SCAN ----------------

app.put('/scans/:id', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    const { container_code, iso_code, shipping_company } = req.body;
    try {
        const update = {};
        if (container_code !== undefined) update.container_code = container_code;
        if (iso_code !== undefined) update.iso_code = iso_code;
        if (shipping_company !== undefined) update.shipping_company = shipping_company;
        await scans.updateOne({ _id: new ObjectId(req.params.id) }, { $set: update });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: error.message || "Server error" });
    }
});

app.delete('/scans/:id', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    try {
        await scans.deleteOne({ _id: new ObjectId(req.params.id) });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: error.message || "Server error" });
    }
});

// ---------------- ALERTS COUNT ----------------

app.get('/alerts/count', async (req, res) => {
    if (!req.session.user) {
        return res.status(401).json({ error: "Unauthorized" });
    }

    try {
        const count = await alerts.countDocuments();
        res.json({ count });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

// ---------------- ALERTS RECENT (LATEST 5) ----------------

app.get('/alerts/recent', async (req, res) => {
    if (!req.session.user) {
        return res.status(401).json({ error: "Unauthorized" });
    }

    try {
        const recent = await alerts
            .find({}, { projection: { screenshot: 0, screenshot_mime: 0 } })
            .sort({ created_at: -1 })
            .limit(5)
            .toArray();
        res.json(recent);
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});


// ---------------- GENERATE REPORT (CSV or PDF ) ----------------

app.get('/generate-report', async (req, res) => {
    if (!req.session.user) {
        return res.status(401).json({ error: "Unauthorized" });
    }

    const format = (req.query.format || 'csv').toLowerCase();

    try {
        // Fetch all data
        const data = await scans
            .find({}, { projection: { screenshot: 0, screenshot_mime: 0 } })
            .sort({ created_at: -1 })
            .toArray();

        const allTeams = await teams.find({}).sort({ created_at: 1 }).toArray();
        const allCameras = await cameras.find({}).toArray();

        // Helper: resolve camera name from _id
        const camName = (id) => {
            const c = allCameras.find(c => String(c._id) === String(id));
            return c ? c.name : String(id);
        };

        // Build statistics
        const cameraStats = {};
        const companyStats = {};
        data.forEach(c => {
            const cam = camName(c.camera_id || '1');
            cameraStats[cam] = (cameraStats[cam] || 0) + 1;
            const company = c.shipping_company || 'Non spécifié';
            companyStats[company] = (companyStats[company] || 0) + 1;
        });

        const cameraText = Object.entries(cameraStats).map(([k, v]) => `${k}: ${v}`).join(', ');
        const companyText = Object.entries(companyStats).slice(0, 5).map(([k, v]) => `${k}: ${v}`).join(', ');
        const teamsText = allTeams.map(t => `${t.name} (chef: ${t.leader_name}, ${(t.camera_ids||[]).length} caméra(s))`).join('; ');

        // Call Ollama for AI-generated analysis
        let aiSummary = `Rapport généré automatiquement. Total: ${data.length} conteneurs détectés.`;
        const ollamaResult = await callOllama(
            `Tu es un assistant d'analyse portuaire. Génère un rapport concis en français pour le système de détection de conteneurs du port de Marsa Maroc. Données: ${data.length} conteneurs détectés au total. Par caméra: ${cameraText}. Principales entreprises: ${companyText}. Équipes: ${teamsText}. Génère 3-4 phrases d'analyse professionnelle incluant les statistiques clés et une conclusion opérationnelle.`
        );
        if (ollamaResult) aiSummary = ollamaResult;

        const now = new Date();
        const dateStr = now.toLocaleString('fr-FR');

        // ---- CSV ----
        if (format === 'csv') {
            res.setHeader('Content-Type', 'text/csv; charset=utf-8');
            res.setHeader('Content-Disposition', `attachment; filename="rapport_conteneurs_${now.toISOString().slice(0, 10)}.csv"`);

            let csv = '\uFEFF';
            csv += `Rapport de détection de conteneurs - Marsa Maroc\n`;
            csv += `Généré le: ${dateStr}\n`;
            csv += `Total conteneurs: ${data.length}\n\n`;
            csv += `Analyse IA:\n"${aiSummary.replace(/"/g, '""')}"\n\n`;

            // Teams section
            csv += `ÉQUIPES\n`;
            csv += `Équipe,Chef d'équipe,Nombre de caméras,Conteneurs détectés\n`;
            allTeams.forEach(t => {
                const teamScanCount = data.filter(s => (t.camera_ids || []).some(id => String(id) === String(s.camera_id))).length;
                csv += `"${t.name}","${t.leader_name}","${(t.camera_ids||[]).length}","${teamScanCount}"\n`;
            });
            csv += `\n`;

            // Scans section
            csv += `CONTENEURS SCANNÉS\n`;
            csv += `Équipe,Caméra,Code Conteneur,Code ISO,Entreprise,Date d'ajout\n`;
            data.forEach(c => {
                const cName = camName(c.camera_id || '1');
                const team = allTeams.find(t => (t.camera_ids || []).some(id => String(id) === String(c.camera_id)));
                const teamName = team ? team.name : 'Non assignée';
                const code = c.container_code || '';
                const iso = c.iso_code || 'Non Scanné';
                const company = (c.shipping_company || 'Non spécifié').replace(/"/g, '""');
                const date = c.created_at ? new Date(c.created_at).toLocaleString('fr-FR') : '';
                csv += `"${teamName}","${cName}","${code}","${iso}","${company}","${date}"\n`;
            });

            return res.send(csv);
        }

        // ---- PDF ----
        if (format === 'pdf') {
            const PDFDocument = require('pdfkit');
            const logoPath = path.join(__dirname, 'assets', 'logo2.png');
            const doc = new PDFDocument({ margin: 50 });

            res.setHeader('Content-Type', 'application/pdf');
            res.setHeader('Content-Disposition', `attachment; filename="rapport_conteneurs_${now.toISOString().slice(0, 10)}.pdf"`);

            doc.pipe(res);

            // Logo
            try { doc.image(logoPath, 50, 30, { height: 50 }); } catch (_) {}

            const titleX = 160;
            doc.fontSize(18).fillColor('#1f93ff').text('Rapport de Détection de Conteneurs', titleX, 30, { width: 385 });
            doc.fontSize(11).fillColor('#475569').text('Marsa Maroc — Système de Surveillance Portuaire', titleX, doc.y, { width: 385 });
            doc.fontSize(9).fillColor('#94a3b8').text(`Généré le: ${dateStr}`, titleX, doc.y + 2, { width: 385 });

            doc.moveDown(1);
            const headerBottom = Math.max(doc.y, 90);
            doc.moveTo(50, headerBottom).lineTo(545, headerBottom).strokeColor('#334155').lineWidth(1).stroke();
            doc.y = headerBottom + 12;

            // Statistics
            doc.fontSize(14).fillColor('#1f93ff').text('Statistiques Générales');
            doc.moveDown(0.4);
            doc.fontSize(11).fillColor('#1e293b').text(`Total conteneurs détectés: ${data.length}`);
            doc.fontSize(10).fillColor('#475569').text(`Nombre d'équipes: ${allTeams.length}`);
            doc.fontSize(10).fillColor('#475569').text(`Nombre de caméras: ${allCameras.length}`);
            Object.entries(cameraStats).forEach(([cam, count]) => {
                doc.fontSize(10).fillColor('#475569').text(`  • ${cam}: ${count} conteneur(s)`);
            });
            doc.moveDown(1);

            
            doc.fontSize(14).fillColor('#1f93ff').text('Analyse');
            doc.moveDown(0.4);
            doc.fontSize(11).fillColor('#1e293b').text(aiSummary, { lineGap: 4 });
            doc.moveDown(1);
            doc.moveTo(50, doc.y).lineTo(545, doc.y).strokeColor('#334155').lineWidth(1).stroke();
            doc.moveDown(1);

            // Teams section
            doc.fontSize(14).fillColor('#1f93ff').text('Équipes');
            doc.moveDown(0.6);

            const teamColWidths = [160, 160, 90, 85];
            const teamCols = ['Équipe', 'Chef d\'équipe', 'Nb. Caméras', 'Conteneurs'];
            const startX = 50;
            let y = doc.y;

            doc.fillColor('#0f172a').rect(startX, y, 495, 20).fill();
            doc.fontSize(9).fillColor('#94a3b8');
            let x = startX + 5;
            teamCols.forEach((col, i) => {
                doc.text(col, x, y + 5, { width: teamColWidths[i] - 5, lineBreak: false });
                x += teamColWidths[i];
            });
            y += 20;

            allTeams.forEach((t, rowIndex) => {
                if (y > 720) { doc.addPage(); y = 50; }
                const bgColor = rowIndex % 2 === 0 ? '#f8fafc' : '#f1f5f9';
                doc.fillColor(bgColor).rect(startX, y, 495, 18).fill();
                doc.fontSize(8).fillColor('#1e293b');
                x = startX + 5;
                const teamScanCount = data.filter(s => (t.camera_ids || []).some(id => String(id) === String(s.camera_id))).length;
                const row = [
                    t.name,
                    t.leader_name,
                    String((t.camera_ids || []).length),
                    String(teamScanCount)
                ];
                row.forEach((cell, i) => {
                    doc.text(cell, x, y + 4, { width: teamColWidths[i] - 5, lineBreak: false });
                    x += teamColWidths[i];
                });
                y += 18;
            });

            doc.moveDown(2);
            doc.y = y + 20;
            doc.moveTo(50, doc.y).lineTo(545, doc.y).strokeColor('#334155').lineWidth(1).stroke();
            doc.moveDown(1);

            // Scans table
            doc.fontSize(14).fillColor('#1f93ff').text('Liste des Conteneurs Scannés');
            doc.moveDown(0.6);

            const colWidths = [90, 95, 110, 60, 75, 65];
            const cols = ['Équipe', 'Caméra', 'Code Conteneur', 'Code ISO', 'Entreprise', 'Date'];
            y = doc.y;

            doc.fillColor('#0f172a').rect(startX, y, 495, 20).fill();
            doc.fontSize(9).fillColor('#94a3b8');
            x = startX + 5;
            cols.forEach((col, i) => {
                doc.text(col, x, y + 5, { width: colWidths[i] - 5, lineBreak: false });
                x += colWidths[i];
            });
            y += 20;

            data.forEach((c, rowIndex) => {
                if (y > 720) { doc.addPage(); y = 50; }
                const bgColor = rowIndex % 2 === 0 ? '#f8fafc' : '#f1f5f9';
                doc.fillColor(bgColor).rect(startX, y, 495, 18).fill();
                doc.fontSize(8).fillColor('#1e293b');
                x = startX + 5;
                const team = allTeams.find(t => (t.camera_ids || []).some(id => String(id) === String(c.camera_id)));
                const row = [
                    team ? team.name : 'Non assignée',
                    camName(c.camera_id || '1'),
                    c.container_code || '',
                    c.iso_code || 'N/A',
                    c.shipping_company || 'Non spécifié',
                    c.created_at ? new Date(c.created_at).toLocaleDateString('fr-FR') : ''
                ];
                row.forEach((cell, i) => {
                    doc.text(cell, x, y + 4, { width: colWidths[i] - 5, lineBreak: false });
                    x += colWidths[i];
                });
                y += 18;
            });

            doc.end();
            return;
        }

        res.status(400).json({ error: "Format must be 'csv' or 'pdf'" });

    } catch (error) {
        console.error('Report generation error:', error);
        res.status(500).json({ error: "Failed to generate report" });
    }
});


// ---------------- MONTHLY STATS ----------------

app.get('/stats/monthly', async (req, res) => {
    if (!req.session.user) {
        return res.status(401).json({ error: "Unauthorized" });
    }

    try {
        const thirtyDaysAgo = new Date();
        thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 29);
        thirtyDaysAgo.setHours(0, 0, 0, 0);

        const pipeline = [
            { $match: { created_at: { $gte: thirtyDaysAgo } } },
            {
                $group: {
                    _id: {
                        $dateToString: { format: "%Y-%m-%d", date: "$created_at" }
                    },
                    count: { $sum: 1 }
                }
            },
            { $sort: { _id: 1 } }
        ];

        const result = await scans.aggregate(pipeline).toArray();
        res.json(result);
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});


// ---------------- CAMERAS ----------------

app.get('/cameras', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    try {
        const data = await cameras.find({}).sort({ created_at: 1 }).toArray();
        res.json(data);
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.post('/cameras', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    const { name, ip_address } = req.body;
    if (!name) return res.status(400).json({ error: "name est requis" });
    try {
        const result = await cameras.insertOne({ name, ip_address: ip_address || '', created_at: new Date() });
        res.json({ success: true, id: result.insertedId });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: error.message || "Server error" });
    }
});

app.delete('/cameras/:id', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    try {
        await cameras.deleteOne({ _id: new ObjectId(req.params.id) });
        await teams.updateMany({}, { $pull: { camera_ids: req.params.id } });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});


// ---------------- TEAMS ----------------

app.get('/teams', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    try {
        const data = await teams.find({}).sort({ created_at: -1 }).toArray();
        res.json(data);
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.post('/teams', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    const { name, leader_name, leader_phone, members } = req.body;
    if (!name || !leader_name) return res.status(400).json({ error: "name et leader_name sont requis" });
    try {
        const result = await teams.insertOne({ name, leader_name, leader_phone: leader_phone || '', members: members || [], camera_ids: [], created_at: new Date() });
        res.json({ success: true, id: result.insertedId });
    } catch (error) {
        if (error.code === 11000) return res.status(400).json({ error: "Une équipe avec ce nom existe déjà" });
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.put('/teams/:id', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    const { name, leader_name, leader_phone, camera_ids } = req.body;
    try {
        const update = {};
        if (name !== undefined) update.name = name;
        if (leader_name !== undefined) update.leader_name = leader_name;
        if (leader_phone !== undefined) update.leader_phone = leader_phone;
        if (camera_ids !== undefined) update.camera_ids = camera_ids;
        await teams.updateOne({ _id: new ObjectId(req.params.id) }, { $set: update });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.post('/teams/:id/members', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    const { member } = req.body;
    if (!member) return res.status(400).json({ error: "member requis" });
    try {
        await teams.updateOne({ _id: new ObjectId(req.params.id) }, { $push: { members: member } });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.delete('/teams/:id/members', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    const { member } = req.body;
    if (!member) return res.status(400).json({ error: "member requis" });
    try {
        await teams.updateOne({ _id: new ObjectId(req.params.id) }, { $pull: { members: member } });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.delete('/teams/:id', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    try {
        await teams.deleteOne({ _id: new ObjectId(req.params.id) });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});


// ---------------- STOPS (ARRÊTS) ----------------

app.get('/stops', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    try {
        const data = await stops.find({}).sort({ start_time: -1 }).toArray();
        res.json(data);
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.post('/stops', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    const { reason, team_id, team_name, start_time, confirmation_time, status } = req.body;
    if (!reason || !start_time) return res.status(400).json({ error: "reason et start_time sont requis" });
    try {
        const doc = {
            reason,
            team_id: team_id || null,
            team_name: team_name || '',
            start_time: new Date(start_time),
            confirmation_time: confirmation_time ? new Date(confirmation_time) : null,
            status: status || 'active',
            created_at: new Date()
        };
        const result = await stops.insertOne(doc);
        res.json({ success: true, id: result.insertedId });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.put('/stops/:id', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    const { reason, team_id, team_name, start_time, confirmation_time, status } = req.body;
    try {
        const update = {};
        if (reason !== undefined) update.reason = reason;
        if (team_id !== undefined) update.team_id = team_id;
        if (team_name !== undefined) update.team_name = team_name;
        if (start_time !== undefined) update.start_time = new Date(start_time);
        if (confirmation_time !== undefined) update.confirmation_time = confirmation_time ? new Date(confirmation_time) : null;
        if (status !== undefined) update.status = status;
        await stops.updateOne({ _id: new ObjectId(req.params.id) }, { $set: update });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});

app.delete('/stops/:id', async (req, res) => {
    if (!req.session.user) return res.status(401).json({ error: "Unauthorized" });
    try {
        await stops.deleteOne({ _id: new ObjectId(req.params.id) });
        res.json({ success: true });
    } catch (error) {
        console.error(error);
        res.status(500).json({ error: "Server error" });
    }
});



const PORT = process.env.PORT || 82;

// Start Express server
app.listen(PORT, () => {
    console.log(` Server running on port ${PORT}`);
});