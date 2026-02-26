// ─── Paramètres LLM ───────────────────────────────────────────────────────────

let _backends = [];

async function loadBackends() {
    try {
        const res = await fetch(`${API_URL}/backends`);
        if (!res.ok) return;
        const data = await res.json();
        _backends = data.backends || [];
        const container = document.getElementById('backendButtons');
        if (!container) return;
        const ICONS = { lm_studio: '🖥', ollama: '🦙', openai: '🤖', gemini: '✨' };
        container.innerHTML = _backends.map(b => `
            <button onclick='applyBackend("${b.id}")'
                class='backend-btn border-2 border-gray-200 rounded-xl p-2 text-center hover:border-blue-400 hover:bg-blue-50 transition text-xs'>
                <div class='text-lg'>${ICONS[b.id] || '⚙️'}</div>
                <div class='font-semibold text-gray-700 mt-0.5'>${b.label}</div>
            </button>`).join('');
    } catch(e) {}
}

function applyBackend(id) {
    const b = _backends.find(x => x.id === id);
    if (!b) return;
    document.getElementById('settingLlmUrl').value   = b.base_url;
    document.getElementById('settingLlmKey').value   = b.api_key || '';
    document.getElementById('settingLlmModel').value = b.models[0] || '';
    const sel = document.getElementById('modelSuggestions');
    if (b.models.length > 1) {
        sel.innerHTML = '<option value="">— suggestions —</option>' +
            b.models.map(m => `<option value="${m}">${m}</option>`).join('');
        sel.classList.remove('hidden');
    } else {
        sel.classList.add('hidden');
    }
    const hint = document.getElementById('settingLlmKeyHint');
    if (b.hint) { hint.textContent = '💡 ' + b.hint; hint.classList.remove('hidden'); }
    else         { hint.classList.add('hidden'); }
    _highlightActiveBackend_btn(id);
}

function _highlightActiveBackend_btn(id) {
    document.querySelectorAll('.backend-btn').forEach(btn => {
        btn.classList.remove('border-blue-500', 'bg-blue-50');
        btn.classList.add('border-gray-200');
    });
    const active = document.querySelector(`.backend-btn[onclick='applyBackend("${id}")']`);
    if (active) { active.classList.remove('border-gray-200'); active.classList.add('border-blue-500','bg-blue-50'); }
}

function applyModelSuggestion() {
    const sel = document.getElementById('modelSuggestions');
    if (sel.value) document.getElementById('settingLlmModel').value = sel.value;
}

async function loadSettings() {
    const res = await fetch(`${API_URL}/settings`, { headers: { 'Authorization': authHeader } });
    const s   = await res.json();
    document.getElementById('settingLlmUrl').value   = s.llm_base_url || '';
    document.getElementById('settingLlmModel').value = s.llm_model    || '';
    document.getElementById('settingLlmKey').value   = s.llm_api_key  || '';
    await loadBackends();
    _highlightActiveBackend(s.llm_base_url || '');
    // OCR / Vision
    document.getElementById('settingOcrCorrection').checked   = (s.ocr_llm_correction !== 'false');
    const thr = parseInt(s.ocr_correction_threshold || '80');
    document.getElementById('settingOcrThreshold').value      = thr;
    document.getElementById('ocrThresholdVal').textContent    = thr + '%';
    document.getElementById('settingVisionEnabled').checked   = (s.llm_vision_enabled === 'true');
    document.getElementById('settingVisionProvider').value    = s.llm_vision_provider || 'local';
    document.getElementById('settingVisionModel').value       = s.llm_vision_model    || '';
    document.getElementById('settingVisionApiKey').value      = s.llm_vision_api_key  || '';
    document.getElementById('settingVisionBaseUrl').value     = s.llm_vision_base_url || '';
    document.getElementById('settingOcrVisionFusion').checked = (s.ocr_vision_fusion !== 'false');
    toggleVisionPanel();
    toggleVisionProvider();
    // Email IMAP
    document.getElementById('settingEmailHost').value           = s.email_host                 || '';
    document.getElementById('settingEmailUser').value           = s.email_user                 || '';
    document.getElementById('settingEmailPass').value           = s.email_password             || '';
    document.getElementById('settingEmailFolder').value         = s.email_folder               || 'INBOX';
    document.getElementById('settingEmailTreated').value        = s.email_treated_folder       || 'PaperFree-Traité';
    document.getElementById('settingEmailAttachInterval').value = s.email_attach_interval_min  || '15';
    document.getElementById('settingEmailPurgeInterval').value  = s.email_purge_interval_hours || '24';
    document.getElementById('settingEmailPromoDays').value      = s.email_promo_days           || '7';
    // OAuth Microsoft
    document.getElementById('settingOauthClientId').value     = s.oauth_client_id     || '';
    document.getElementById('settingOauthClientSecret').value = s.oauth_client_secret || '';
    document.getElementById('settingOauthRedirectUri').value  = s.oauth_redirect_uri  || 'http://localhost:8000/email/oauth/callback';
    // OAuth Google
    document.getElementById('settingGoogleClientId').value     = s.google_client_id     || '';
    document.getElementById('settingGoogleClientSecret').value = s.google_client_secret || '';
    document.getElementById('settingGoogleRedirectUri').value  = s.google_redirect_uri  || 'http://localhost:8000/email/oauth/google/callback';
    refreshOauthStatus();
}

function _highlightActiveBackend(currentUrl) {
    if (!currentUrl || !_backends.length) return;
    const match = _backends.find(b => currentUrl.startsWith(b.base_url.split('/v1')[0]));
    if (!match) return;
    _highlightActiveBackend_btn(match.id);
}

async function saveSettings() {
    const pairs = [
        ['llm_base_url', document.getElementById('settingLlmUrl').value],
        ['llm_model',    document.getElementById('settingLlmModel').value],
        ['llm_api_key',  document.getElementById('settingLlmKey').value],
    ];
    for (const [k, v] of pairs)
        await fetch(`${API_URL}/settings?key=${k}&value=${encodeURIComponent(v)}`,
            { method: 'POST', headers: { 'Authorization': authHeader } });
    const el = document.getElementById('settingsSaved');
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 2000);
}

async function saveOcrVisionSettings() {
    const pairs = [
        ['ocr_llm_correction',       document.getElementById('settingOcrCorrection').checked ? 'true' : 'false'],
        ['ocr_correction_threshold', document.getElementById('settingOcrThreshold').value],
        ['llm_vision_enabled',       document.getElementById('settingVisionEnabled').checked ? 'true' : 'false'],
        ['llm_vision_provider',      document.getElementById('settingVisionProvider').value],
        ['llm_vision_model',         document.getElementById('settingVisionModel').value],
        ['llm_vision_api_key',       document.getElementById('settingVisionApiKey').value],
        ['llm_vision_base_url',      document.getElementById('settingVisionBaseUrl').value],
        ['ocr_vision_fusion',        document.getElementById('settingOcrVisionFusion').checked ? 'true' : 'false'],
    ];
    for (const [k, v] of pairs)
        await fetch(`${API_URL}/settings?key=${k}&value=${encodeURIComponent(v)}`,
            { method: 'POST', headers: { 'Authorization': authHeader } });
    const el = document.getElementById('ocrVisionSaved');
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 2500);
}

function toggleVisionPanel() {
    const enabled = document.getElementById('settingVisionEnabled').checked;
    document.getElementById('visionPanel').classList.toggle('hidden', !enabled);
}

function toggleVisionProvider() {
    const provider = document.getElementById('settingVisionProvider').value;
    const isLocal  = provider === 'local';
    document.getElementById('visionLocalNote').classList.toggle('hidden', !isLocal);
    document.getElementById('visionExternalNote').classList.toggle('hidden', isLocal);
    document.getElementById('visionBaseUrlField').classList.toggle('hidden', !isLocal);
    if (provider === 'gemini') {
        document.getElementById('visionExternalNote').classList.remove('hidden');
        document.getElementById('visionBaseUrlField').classList.add('hidden');
    }
}

async function saveEmailSettings() {
    const pairs = [
        ['email_host',                 document.getElementById('settingEmailHost').value],
        ['email_user',                 document.getElementById('settingEmailUser').value],
        ['email_password',             document.getElementById('settingEmailPass').value],
        ['email_folder',               document.getElementById('settingEmailFolder').value],
        ['email_treated_folder',       document.getElementById('settingEmailTreated').value],
        ['email_attach_interval_min',  document.getElementById('settingEmailAttachInterval').value],
        ['email_purge_interval_hours', document.getElementById('settingEmailPurgeInterval').value],
        ['email_promo_days',           document.getElementById('settingEmailPromoDays').value],
    ];
    for (const [k, v] of pairs)
        await fetch(`${API_URL}/settings?key=${k}&value=${encodeURIComponent(v)}`,
            { method: 'POST', headers: { 'Authorization': authHeader } });
    const el = document.getElementById('emailSettingsSaved');
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 3000);
}

async function testEmailConnection() {
    const el = document.getElementById('emailTestResult');
    el.classList.remove('hidden');
    el.textContent = '⏳ Test en cours...';
    el.className = 'text-sm mt-1 text-blue-500';
    try {
        await saveEmailSettings();
        const res  = await fetch(`${API_URL}/email/test`, { headers: { 'Authorization': authHeader } });
        const data = await res.json();
        if (data.ok) {
            el.textContent = `✅ Connexion réussie — ${data.folders_count} dossier(s) trouvé(s) — ${data.oauth ? 'OAuth2' : 'Auth basique'}`;
            el.className = 'text-sm mt-1 text-green-600';
            loadEmailFolders();
        } else {
            el.textContent = `❌ ${data.error || 'Connexion impossible'}`;
            el.className = 'text-sm mt-1 text-red-600';
        }
    } catch(e) {
        el.textContent = `❌ Erreur réseau : ${e.message}`;
        el.className = 'text-sm mt-1 text-red-600';
    }
    setTimeout(() => el.classList.add('hidden'), 8000);
}

// ─── OAuth Microsoft ──────────────────────────────────────────────────────────

async function saveOauthSettings() {
    const pairs = [
        ['oauth_client_id',     document.getElementById('settingOauthClientId').value],
        ['oauth_client_secret', document.getElementById('settingOauthClientSecret').value],
        ['oauth_redirect_uri',  document.getElementById('settingOauthRedirectUri').value],
    ];
    for (const [k, v] of pairs)
        await fetch(`${API_URL}/settings?key=${k}&value=${encodeURIComponent(v)}`,
            { method: 'POST', headers: { 'Authorization': authHeader } });
    document.getElementById('oauthSettingsSaved').classList.remove('hidden');
    setTimeout(() => document.getElementById('oauthSettingsSaved').classList.add('hidden'), 3000);
}

async function saveGoogleOauthSettings() {
    const pairs = [
        ['google_client_id',     document.getElementById('settingGoogleClientId').value],
        ['google_client_secret', document.getElementById('settingGoogleClientSecret').value],
        ['google_redirect_uri',  document.getElementById('settingGoogleRedirectUri').value],
    ];
    for (const [k, v] of pairs)
        await fetch(`${API_URL}/settings?key=${k}&value=${encodeURIComponent(v)}`,
            { method: 'POST', headers: { 'Authorization': authHeader } });
    document.getElementById('googleOauthSettingsSaved').classList.remove('hidden');
    setTimeout(() => document.getElementById('googleOauthSettingsSaved').classList.add('hidden'), 3000);
}

async function refreshOauthStatus() {
    try {
        const res  = await fetch(`${API_URL}/email/oauth/status`, { headers: { 'Authorization': authHeader } });
        if (!res.ok) return;
        const data = await res.json();
        _renderOauthStatus('microsoft', data.microsoft, 'oauthStatus', 'btnOauthConnect', 'btnOauthDisconnect', 'Outlook');
        _renderOauthStatus('google', data.google, 'googleOauthStatus', 'btnGoogleConnect', 'btnGoogleDisconnect', 'Gmail');
    } catch(e) {}
}

function _renderOauthStatus(provider, state, elId, btnConnId, btnDiscId, label) {
    const el         = document.getElementById(elId);
    const btnConn    = document.getElementById(btnConnId);
    const btnDisc    = document.getElementById(btnDiscId);
    if (!el || !btnConn || !btnDisc) return;
    if (state.connected) {
        const exp = state.expires_at ? new Date(state.expires_at * 1000).toLocaleString('fr-CA') : '?';
        el.innerHTML = `<span class='text-green-600'>✅ Connecté (${escHtml(state.email_user)}) — expire ${exp}</span>`;
        btnConn.classList.add('hidden');
        btnDisc.classList.remove('hidden');
    } else if (state.configured) {
        el.innerHTML = `<span class='text-orange-500'>⚠️ Configuré mais non connecté</span>`;
        btnConn.classList.remove('hidden');
        btnDisc.classList.add('hidden');
    } else {
        el.innerHTML = `<span class='text-gray-400'>Non configuré</span>`;
        btnConn.classList.remove('hidden');
        btnDisc.classList.add('hidden');
    }
}

function startOauthFlow(provider) {
    const urls = {
        microsoft: `${API_URL}/email/oauth/start`,
        google:    `${API_URL}/email/oauth/google/start`,
    };
    const popup = window.open(urls[provider], 'oauth_popup', 'width=540,height=660,resizable=yes,scrollbars=yes');
    const handler = (event) => {
        if (!event.data || event.data.provider !== provider) return;
        window.removeEventListener('message', handler);
        popup?.close();
        if (event.data.type === 'oauth_success') {
            const who = event.data.email ? ` (${event.data.email})` : '';
            showEmailMsg(`✅ Compte ${provider === 'google' ? 'Gmail' : 'Outlook'} connecté${who} !`, 'green');
            refreshOauthStatus();
        } else if (event.data.type === 'oauth_error') {
            showEmailMsg(`❌ Erreur OAuth ${provider} : ${event.data.error}`, 'red');
        }
    };
    window.addEventListener('message', handler);
    const interval = setInterval(() => {
        if (popup?.closed) { clearInterval(interval); window.removeEventListener('message', handler); }
    }, 1000);
}

async function oauthDisconnect(provider) {
    const labels = { microsoft: 'Outlook/Hotmail', google: 'Gmail' };
    if (!confirm(`Déconnecter le compte ${labels[provider]} ?`)) return;
    const endpoints = {
        microsoft: `${API_URL}/email/oauth/disconnect`,
        google:    `${API_URL}/email/oauth/google/disconnect`,
    };
    await fetch(endpoints[provider], { method: 'POST', headers: { 'Authorization': authHeader } });
    refreshOauthStatus();
}
