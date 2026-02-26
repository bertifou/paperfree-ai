// ─── Email ────────────────────────────────────────────────────────────────────

const EMAIL_CATEGORY_COLORS = {
    'Promotionnel': 'bg-orange-100 text-orange-700',
    'Facture':      'bg-blue-100 text-blue-700',
    'Notification': 'bg-yellow-100 text-yellow-700',
    'Personnel':    'bg-green-100 text-green-700',
    'Autre':        'bg-gray-100 text-gray-500',
};

async function loadEmailFolders() {
    try {
        const res = await fetch(`${API_URL}/email/folders`, { headers: { 'Authorization': authHeader } });
        if (!res.ok) return;
        const data    = await res.json();
        const sel     = document.getElementById('emailFolderSelect');
        const current = sel.value;
        sel.innerHTML = '';
        data.folders.forEach(f => {
            const opt = document.createElement('option');
            opt.value = f; opt.textContent = f;
            if (f === current) opt.selected = true;
            sel.appendChild(opt);
        });
    } catch(e) {}
}

async function loadEmails() {
    const folder = document.getElementById('emailFolderSelect').value || 'INBOX';
    document.getElementById('emailLoading').classList.remove('hidden');
    document.getElementById('emailEmpty').classList.add('hidden');
    document.getElementById('emailList').innerHTML = '';
    document.getElementById('emailStats').classList.add('hidden');
    try {
        const res = await fetch(
            `${API_URL}/email/messages?folder=${encodeURIComponent(folder)}&limit=50`,
            { headers: { 'Authorization': authHeader } }
        );
        document.getElementById('emailLoading').classList.add('hidden');
        if (!res.ok) {
            const err = await res.json();
            document.getElementById('emailEmpty').textContent = `⚠️ ${err.detail || 'Erreur'}`;
            document.getElementById('emailEmpty').classList.remove('hidden');
            return;
        }
        const data = await res.json();
        if (!data.messages.length) { document.getElementById('emailEmpty').classList.remove('hidden'); return; }

        const unread = data.messages.filter(m => !m.is_read).length;
        const withPJ = data.messages.filter(m => m.has_attachment).length;
        const stats  = document.getElementById('emailStats');
        stats.textContent = `${data.count} email(s) — ${unread} non lu(s) — ${withPJ} avec pièce(s) jointe(s)`;
        stats.classList.remove('hidden');

        const tbody = document.getElementById('emailList');
        tbody.innerHTML = data.messages.map(m => {
            const date    = new Date(m.date);
            const dateStr = isNaN(date) ? m.date : date.toLocaleString('fr-CA', {dateStyle:'short',timeStyle:'short'});
            return `<tr class='border-t hover:bg-gray-50 ${m.is_read ? "text-gray-500" : "font-medium text-gray-800"}'>
                <td class='px-4 py-2'>${m.is_read ? '' : '<span class="inline-block w-2 h-2 rounded-full bg-blue-500"></span>'}</td>
                <td class='px-4 py-2 max-w-xs truncate text-xs'>${escHtml(m.sender)}</td>
                <td class='px-4 py-2 max-w-sm truncate'>${escHtml(m.subject)}</td>
                <td class='px-4 py-2 text-xs text-gray-400 whitespace-nowrap'>${dateStr}</td>
                <td class='px-4 py-2 text-center'>${m.has_attachment ? '📎' : ''}</td>
                <td class='px-4 py-2 text-right whitespace-nowrap'>
                    <button onclick='emailMarkRead("${escAttr(m.uid)}","${escAttr(folder)}")'
                        class='text-xs text-blue-500 hover:underline mr-2'>✓ Lu</button>
                    <button onclick='emailMove("${escAttr(m.uid)}","${escAttr(folder)}")'
                        class='text-xs text-green-500 hover:underline mr-2'>📁</button>
                    <button onclick='emailDelete("${escAttr(m.uid)}","${escAttr(folder)}")'
                        class='text-xs text-red-400 hover:underline'>🗑</button>
                </td>
            </tr>`;
        }).join('');
    } catch(e) {
        document.getElementById('emailLoading').classList.add('hidden');
    }
}

async function emailDelete(uid, folder) {
    if (!confirm('Supprimer cet email ?')) return;
    await fetch(`${API_URL}/email/messages/${uid}?folder=${encodeURIComponent(folder)}`,
        { method: 'DELETE', headers: { 'Authorization': authHeader } });
    loadEmails();
}

async function emailMove(uid, folder) {
    const dest = prompt('Dossier de destination :', 'PaperFree-Traité');
    if (!dest) return;
    await fetch(`${API_URL}/email/messages/${uid}/move?source_folder=${encodeURIComponent(folder)}&destination_folder=${encodeURIComponent(dest)}`,
        { method: 'POST', headers: { 'Authorization': authHeader } });
    loadEmails();
}

async function emailMarkRead(uid, folder) {
    await fetch(`${API_URL}/email/messages/${uid}/read?folder=${encodeURIComponent(folder)}`,
        { method: 'POST', headers: { 'Authorization': authHeader } });
    loadEmails();
}

async function syncAttachments() {
    showEmailMsg('Synchronisation lancée...', 'blue');
    const res = await fetch(`${API_URL}/email/sync-attachments`,
        { method: 'POST', headers: { 'Authorization': authHeader } });
    if (res.ok) showEmailMsg("✅ Sync pièces jointes en cours — vérifiez l'onglet Documents", 'green');
    else        showEmailMsg('❌ Erreur lors de la synchronisation', 'red');
}

async function purgePromo(dryRun) {
    const label = dryRun ? 'Simulation' : 'Purge';
    showEmailMsg(`${label} en cours... (peut prendre quelques secondes)`, 'blue');
    const days = dryRun ? 0 : -1;
    const res  = await fetch(`${API_URL}/email/purge-promotional?dry_run=${dryRun}&older_than_days=${days}`,
        { method: 'POST', headers: { 'Authorization': authHeader } });
    if (res.ok) {
        const r = await res.json();
        let msg;
        if (dryRun) {
            msg = `👁 Simulation — ${r.total} email(s), ${r.analysed} analysé(s), `
                + `${r.too_recent} ignoré(s), ${r.deleted} promotionnel(s) détecté(s), ${r.kept} conservé(s)`;
        } else {
            msg = `✅ Purge terminée — ${r.analysed} analysé(s), ${r.deleted} supprimé(s), `
                + `${r.too_recent} ignoré(s), ${r.errors} erreur(s)`;
        }
        showEmailMsg(msg, r.deleted > 0 ? 'green' : 'blue');
        if (!dryRun) loadEmails();
    } else {
        const err = await res.json().catch(() => ({}));
        showEmailMsg(`❌ Erreur : ${err.detail || 'Connexion ou config manquante'}`, 'red');
    }
}

function showEmailMsg(msg, color) {
    const el = document.getElementById('emailActionMsg');
    el.textContent = msg;
    el.className   = `text-sm ${color === 'green' ? 'text-green-600' : color === 'red' ? 'text-red-500' : 'text-blue-500'}`;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 5000);
}

async function loadEmailLogs() {
    try {
        const res = await fetch(`${API_URL}/email/logs?limit=50`, { headers: { 'Authorization': authHeader } });
        if (!res.ok) return;
        const logs      = await res.json();
        const container = document.getElementById('emailLogs');
        if (!logs.length) {
            container.innerHTML = '<p class="text-xs text-gray-400">Aucune action enregistrée.</p>';
            return;
        }
        const ACTION_LABELS = {
            'download_attachment': '📎 Pièce jointe',
            'delete_promo':        '🗑 Promo supprimé',
            'manual_delete':       '🗑 Suppression manuelle',
            'move':                '📁 Déplacé',
            'purge_promo':         '🧹 Purge promotionnels',
        };
        container.innerHTML = logs.map(l => {
            const dt    = new Date(l.created_at).toLocaleString('fr-CA', {dateStyle:'short',timeStyle:'short'});
            const label = ACTION_LABELS[l.action] || l.action;
            return `<div class='flex items-start gap-2 text-xs text-gray-600 py-1 border-b border-gray-50'>
                <span class='text-gray-400 whitespace-nowrap'>${dt}</span>
                <span class='font-medium'>${label}</span>
                ${l.subject ? `<span class='truncate text-gray-500'>${escHtml(l.subject)}</span>` : ''}
                ${l.detail  ? `<span class='text-gray-400 truncate'>${escHtml(l.detail)}</span>` : ''}
            </div>`;
        }).join('');
    } catch(e) {}
}
