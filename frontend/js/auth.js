// ─── Auth ─────────────────────────────────────────────────────────────────────

async function checkStatus() {
    try {
        const res = await fetch(`${API_URL}/status`);
        if (!res.ok) { showSection('login'); return; }
        const data = await res.json();
        if (data.setup_required) { showSection('setup'); }
        else if (!authHeader)    { showSection('login'); }
        else { showSection('app'); loadDocuments(); loadSettings(); }
    } catch(e) {
        showSection('login');
        const el = document.getElementById('loginError');
        if (el) {
            el.textContent = '⚠️ Impossible de joindre le serveur. Vérifiez que le backend est démarré.';
            el.classList.remove('hidden');
        }
    }
}

function showSection(name) {
    ['setup','login','app'].forEach(s => document.getElementById(s+'Section').classList.add('hidden'));
    document.getElementById(name+'Section').classList.remove('hidden');
}

async function handleSetup() {
    const user = document.getElementById('setupUser').value;
    const pass = document.getElementById('setupPass').value;
    const url  = document.getElementById('setupLlm').value;
    try {
        const res = await fetch(`${API_URL}/setup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user, password: pass, llm_url: url })
        });
        if (res.ok) { showSection('login'); return; }
        const err = document.getElementById('setupError');
        let msg = 'Erreur lors de la configuration';
        try {
            const body = await res.json();
            if (body.detail) {
                msg = Array.isArray(body.detail)
                    ? body.detail.map(e => e.msg || JSON.stringify(e)).join(' | ')
                    : body.detail;
            } else {
                msg = JSON.stringify(body);
            }
        } catch(e) {}
        err.textContent = `❌ ${res.status}: ${msg}`;
        err.classList.remove('hidden');
    } catch(e) {
        const err = document.getElementById('setupError');
        err.textContent = '⚠️ Impossible de joindre le serveur : ' + e.message;
        err.classList.remove('hidden');
    }
}

async function handleLogin() {
    const user  = document.getElementById('loginUser').value;
    const pass  = document.getElementById('loginPass').value;
    const errEl = document.getElementById('loginError');
    errEl.classList.add('hidden');
    try {
        const res = await fetch(`${API_URL}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user, password: pass })
        });
        if (!res.ok) {
            let msg = 'Identifiants incorrects';
            try { const body = await res.json(); msg = body.detail || msg; } catch(e) {}
            errEl.textContent = msg;
            errEl.classList.remove('hidden');
            authHeader = null;
            return;
        }
        const data   = await res.json();
        authHeader   = 'Bearer ' + data.access_token;
        refreshToken = data.refresh_token;
        localStorage.setItem('paperfree_auth',    authHeader);
        localStorage.setItem('paperfree_refresh', refreshToken);
        showSection('app');
        loadDocuments();
        loadSettings();
    } catch(e) {
        errEl.textContent = '⚠️ Erreur réseau : ' + e.message;
        errEl.classList.remove('hidden');
        authHeader = null;
    }
}

function logout() {
    localStorage.removeItem('paperfree_auth');
    localStorage.removeItem('paperfree_refresh');
    authHeader   = null;
    refreshToken = null;
    checkStatus();
}
