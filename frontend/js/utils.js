// ─── Config & état global ─────────────────────────────────────────────────────
const API_URL = 'http://localhost:8000';

// Migration Basic→JWT : vide les anciens tokens Basic Auth stockés
(function () {
    const stored = localStorage.getItem('paperfree_auth');
    if (stored && stored.startsWith('Basic ')) { localStorage.removeItem('paperfree_auth'); }
})();

let authHeader   = localStorage.getItem('paperfree_auth'); // "Bearer <jwt>"
let refreshToken = localStorage.getItem('paperfree_refresh');
let currentDocId = null;
let allDocs      = [];

// ─── Couleurs catégories documents ───────────────────────────────────────────
const CATEGORY_COLORS = {
    'Facture':   'bg-orange-100 text-orange-700',
    'Impôts':    'bg-red-100 text-red-700',
    'Santé':     'bg-green-100 text-green-700',
    'Banque':    'bg-blue-100 text-blue-700',
    'Contrat':   'bg-purple-100 text-purple-700',
    'Assurance': 'bg-yellow-100 text-yellow-700',
    'Travail':   'bg-indigo-100 text-indigo-700',
    'Courrier':  'bg-gray-100 text-gray-700',
    'Autre':     'bg-gray-100 text-gray-500',
};

// ─── Helpers HTML ─────────────────────────────────────────────────────────────
function escHtml(s)  { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(s)  { return String(s||'').replace(/'/g,'&#39;').replace(/"/g,'&quot;'); }
function cap(s)      { return s.charAt(0).toUpperCase() + s.slice(1); }

function formField(label, key, value) {
    return `<div>
        <label class='block text-xs font-medium text-gray-600 mb-1'>${label}</label>
        <input type='text' id='form_${key}' value='${escAttr(value)}'
            class='w-full p-2 border rounded text-sm'>
    </div>`;
}

// ─── Navigation onglets principaux ────────────────────────────────────────────
function showTab(name) {
    document.getElementById('tabDocs').classList.toggle('hidden',     name !== 'docs');
    document.getElementById('tabClasseur').classList.toggle('hidden', name !== 'classeur');
    document.getElementById('tabEmail').classList.toggle('hidden',    name !== 'email');
    document.getElementById('tabSettings').classList.toggle('hidden', name !== 'settings');

    ['docs','classeur','email','settings'].forEach(t => {
        const btn = document.getElementById('btn' + cap(t));
        if (btn) btn.className = 'text-sm px-3 py-1 rounded ' + (t === name ? 'tab-active' : 'text-gray-500');
    });

    if (name === 'email')    { loadEmailFolders(); loadEmails(); loadEmailLogs(); }
    if (name === 'classeur') { renderClasseur(); }
    if (name === 'settings') { initRulesSection(); }
}

// ─── Guides provider email ────────────────────────────────────────────────────
function showGuide(provider) {
    document.querySelectorAll('.guide-panel').forEach(p => p.classList.add('hidden'));
    const panel = document.getElementById('guide-' + provider);
    if (panel) panel.classList.toggle('hidden');
    if (panel && !panel.classList.contains('hidden')) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function fillImap(host) {
    document.getElementById('settingEmailHost').value = host;
    document.getElementById('settingEmailHost').focus();
}
