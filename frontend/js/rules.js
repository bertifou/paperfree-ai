// ─── Règles de classification (multi-conditions AND) ─────────────────────────
// frontend/js/rules.js

const RULE_CATEGORIES = ['Facture','Impôts','Santé','Banque','Contrat','Assurance','Travail','Courrier','Autre'];

const RULE_FIELDS = {
    issuer:          '🏢 Émetteur contient',
    content:         '📄 Contenu contient',
    category:        '🏷 Catégorie LLM est',
    amount_not_null: '💶 Montant non nul',
    amount_null:     '💶 Montant absent',
};

const FIELD_NO_VALUE = new Set(['amount_not_null', 'amount_null']);

let allRules = [];

// ─── Helper fetch authentifié ─────────────────────────────────────────────────
async function rulesFetch(path, options = {}) {
    return fetch(`${API_URL}${path}`, {
        ...options,
        headers: { 'Authorization': authHeader, ...(options.headers || {}) },
    });
}

// ─── Chargement ──────────────────────────────────────────────────────────────

async function loadRules() {
    try {
        const res = await rulesFetch('/rules');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        allRules = await res.json();
        renderRules();
    } catch(e) {
        console.error('Erreur chargement règles:', e);
        const c = document.getElementById('rulesContainer');
        if (c) c.innerHTML = `<p class="text-sm text-red-400 p-4">Erreur chargement : ${e.message}</p>`;
    }
}

// ─── Affichage ────────────────────────────────────────────────────────────────

function renderRules() {
    const container = document.getElementById('rulesContainer');
    if (!container) return;

    if (!allRules.length) {
        container.innerHTML = `<p class="text-sm text-gray-400 text-center p-6">
            Aucune règle configurée. Créez votre première règle ci-dessus.
        </p>`;
        return;
    }

    container.innerHTML = allRules.map(r => {
        const conds = r.conditions || [];
        const condHtml = conds.length
            ? conds.map((c, i) => {
                const label = RULE_FIELDS[c.match_field] || c.match_field;
                const val   = c.match_value ? ` "<b>${escHtml(c.match_value)}</b>"` : '';
                return (i > 0 ? `<span class="text-gray-400 text-xs mx-1 font-bold">ET</span>` : '')
                    + `<span class="inline-block bg-blue-50 text-blue-700 text-xs px-2 py-0.5 rounded-full">${label}${val}</span>`;
            }).join('')
            : `<span class="text-xs text-red-400">⚠ Aucune condition</span>`;

        return `
        <div class="border rounded-xl p-4 bg-white shadow-sm" id="rule-card-${r.id}">
            <div class="flex items-start justify-between gap-3">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap mb-2">
                        <span class="font-semibold text-gray-800">${escHtml(r.name)}</span>
                        <span class="text-xs px-2 py-0.5 rounded-full font-medium ${r.enabled === 'true'
                            ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'}">
                            ${r.enabled === 'true' ? '✓ Active' : '✗ Désactivée'}
                        </span>
                        <span class="text-xs text-gray-400">priorité ${r.priority}</span>
                    </div>
                    <div class="flex flex-wrap gap-1 items-center mb-2">${condHtml}</div>
                    <div class="text-xs text-gray-500">
                        → Classer en <span class="font-bold text-blue-600">${escHtml(r.target_category)}</span>
                    </div>
                </div>
                <div class="flex flex-col gap-1 flex-shrink-0">
                    <button onclick="toggleRule(${r.id}, '${r.enabled === 'true' ? 'false' : 'true'}')"
                        class="text-xs px-3 py-1.5 rounded ${r.enabled === 'true'
                            ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100'
                            : 'bg-green-50 text-green-700 hover:bg-green-100'}">
                        ${r.enabled === 'true' ? '⏸ Désactiver' : '▶ Activer'}
                    </button>
                    <button onclick="deleteRule(${r.id})"
                        class="text-xs px-3 py-1.5 rounded bg-red-50 text-red-600 hover:bg-red-100 font-medium">
                        🗑 Supprimer
                    </button>
                </div>
            </div>
        </div>`;
    }).join('');
}

// ─── Conditions dynamiques dans le formulaire ─────────────────────────────────

let _condCount = 0;

function addConditionRow(field, value) {
    field = field || 'issuer';
    value = value || '';
    const id    = ++_condCount;
    const noVal = FIELD_NO_VALUE.has(field);
    const row   = document.createElement('div');
    row.className = 'cond-row flex gap-2 items-center';
    row.id = `cond-${id}`;
    row.innerHTML = `
        <select class="cond-field p-2 border rounded text-sm flex-shrink-0 w-52"
            onchange="onCondFieldChange(this, ${id})">
            ${Object.entries(RULE_FIELDS).map(([k, v]) =>
                `<option value="${k}" ${k === field ? 'selected' : ''}>${v}</option>`
            ).join('')}
        </select>
        <input type="text" id="cond-val-${id}"
            class="cond-value p-2 border rounded text-sm flex-1 ${noVal ? 'hidden' : ''}"
            placeholder="valeur (insensible à la casse)…" value="${escAttr(value)}">
        <span class="text-xs text-gray-400 italic ${noVal ? '' : 'hidden'}" id="cond-noval-${id}">(sans valeur)</span>
        <button onclick="removeCondRow(${id})"
            class="text-red-400 hover:text-red-600 text-xl leading-none px-1 flex-shrink-0">×</button>`;
    document.getElementById('condRows').appendChild(row);
}

function onCondFieldChange(sel, id) {
    const noVal = FIELD_NO_VALUE.has(sel.value);
    document.getElementById(`cond-val-${id}`).classList.toggle('hidden', noVal);
    document.getElementById(`cond-noval-${id}`).classList.toggle('hidden', !noVal);
}

function removeCondRow(id) {
    const el = document.getElementById(`cond-${id}`);
    if (el) el.remove();
}

function getConditions() {
    const result = [];
    document.querySelectorAll('.cond-row').forEach(row => {
        const field = row.querySelector('.cond-field').value;
        const valEl = row.querySelector('.cond-value');
        const value = FIELD_NO_VALUE.has(field) ? null : (valEl ? valEl.value.trim() : '');
        if (!FIELD_NO_VALUE.has(field) && !value) return;
        result.push({ match_field: field, match_value: value });
    });
    return result;
}

// ─── Créer une règle ──────────────────────────────────────────────────────────

async function addRule() {
    const name     = document.getElementById('ruleNameInput').value.trim();
    const category = document.getElementById('ruleCategorySelect').value;
    const priority = parseInt(document.getElementById('rulePriorityInput').value) || 0;
    const conditions = getConditions();

    if (!name || !category) {
        alert('Veuillez renseigner le nom et la catégorie cible.');
        return;
    }
    if (!conditions.length) {
        alert('Ajoutez au moins une condition.');
        return;
    }

    try {
        const res = await rulesFetch('/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, target_category: category, priority, conditions }),
        });
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || `HTTP ${res.status}`);
        }
        document.getElementById('ruleNameInput').value = '';
        document.getElementById('rulePriorityInput').value = '0';
        document.getElementById('condRows').innerHTML = '';
        _condCount = 0;
        addConditionRow();
        await loadRules();
        showRulesToast('✓ Règle créée');
    } catch(e) {
        alert('Erreur lors de la création : ' + e.message);
    }
}

// ─── Activer / désactiver ─────────────────────────────────────────────────────

async function toggleRule(id, enabled) {
    try {
        const res = await rulesFetch(`/rules/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await loadRules();
    } catch(e) {
        alert('Erreur : ' + e.message);
    }
}

// ─── Supprimer ────────────────────────────────────────────────────────────────

async function deleteRule(id) {
    if (!confirm('Supprimer cette règle et toutes ses conditions ?')) return;
    try {
        const res = await rulesFetch(`/rules/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await loadRules();
        showRulesToast('Règle supprimée');
    } catch(e) {
        alert('Erreur lors de la suppression : ' + e.message);
    }
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function showRulesToast(msg) {
    const t = document.createElement('div');
    t.className = 'fixed bottom-4 right-4 bg-gray-800 text-white text-sm px-4 py-2 rounded shadow-lg z-50';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, 2500);
}

// ─── Init ─────────────────────────────────────────────────────────────────────

function initRulesSection() {
    const sel = document.getElementById('ruleCategorySelect');
    if (sel && !sel.options.length) {
        RULE_CATEGORIES.forEach(c => {
            const opt = document.createElement('option');
            opt.value = opt.textContent = c;
            sel.appendChild(opt);
        });
        sel.value = 'Impôts';
    }
    const rows = document.getElementById('condRows');
    if (rows && !rows.children.length) addConditionRow();
    loadRules();
}
