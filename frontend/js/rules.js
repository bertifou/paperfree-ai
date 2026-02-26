// ─── Règles de classification ─────────────────────────────────────────────────
// frontend/js/rules.js

const RULE_CATEGORIES = ['Facture','Impôts','Santé','Banque','Contrat','Assurance','Travail','Courrier','Autre'];
const RULE_FIELDS = {
    issuer:   '🏢 Émetteur',
    content:  '📄 Contenu (texte)',
    category: '🏷 Catégorie LLM',
};

let allRules = [];

async function loadRules() {
    try {
        const res = await apiFetch('/rules');
        allRules = await res.json();
        renderRules();
    } catch(e) {
        console.error('Erreur chargement règles:', e);
    }
}

function renderRules() {
    const container = document.getElementById('rulesContainer');
    if (!container) return;

    if (!allRules.length) {
        container.innerHTML = `<p class="text-sm text-gray-400 text-center p-6">Aucune règle configurée.<br>Ajoutez une règle pour personnaliser la classification.</p>`;
        return;
    }

    container.innerHTML = allRules.map(r => `
        <div class="rule-item flex items-center gap-3 p-3 bg-white border rounded-lg shadow-sm hover:shadow-md transition">
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                    <span class="font-medium text-sm text-gray-800">${escHtml(r.name)}</span>
                    <span class="text-xs px-2 py-0.5 rounded-full ${r.enabled === 'true' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}">
                        ${r.enabled === 'true' ? '✓ Active' : '✗ Désactivée'}
                    </span>
                    <span class="text-xs text-gray-400">priorité ${r.priority}</span>
                </div>
                <p class="text-xs text-gray-500 mt-1">
                    Si <b>${RULE_FIELDS[r.match_field] || r.match_field}</b> contient <code class="bg-gray-100 px-1 rounded">${escHtml(r.match_value)}</code>
                    → classer en <span class="font-semibold text-blue-600">${escHtml(r.target_category)}</span>
                </p>
            </div>
            <div class="flex gap-1 flex-shrink-0">
                <button onclick="toggleRule(${r.id}, '${r.enabled === 'true' ? 'false' : 'true'}')"
                    class="text-xs px-2 py-1 rounded ${r.enabled === 'true' ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100' : 'bg-green-50 text-green-700 hover:bg-green-100'}">
                    ${r.enabled === 'true' ? '⏸' : '▶'}
                </button>
                <button onclick="deleteRule(${r.id})"
                    class="text-xs px-2 py-1 rounded bg-red-50 text-red-600 hover:bg-red-100">🗑</button>
            </div>
        </div>
    `).join('');
}

async function addRule() {
    const name     = document.getElementById('ruleNameInput').value.trim();
    const field    = document.getElementById('ruleFieldSelect').value;
    const value    = document.getElementById('ruleValueInput').value.trim();
    const category = document.getElementById('ruleCategorySelect').value;
    const priority = parseInt(document.getElementById('rulePriorityInput').value) || 0;

    if (!name || !value || !category) {
        alert('Veuillez remplir tous les champs.');
        return;
    }

    try {
        await apiFetch('/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, match_field: field, match_value: value, target_category: category, priority }),
        });
        document.getElementById('ruleNameInput').value = '';
        document.getElementById('ruleValueInput').value = '';
        document.getElementById('rulePriorityInput').value = '0';
        await loadRules();
        showToast('Règle ajoutée ✓');
    } catch(e) {
        alert('Erreur lors de la création de la règle.');
    }
}

async function toggleRule(id, enabled) {
    await apiFetch(`/rules/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
    });
    await loadRules();
}

async function deleteRule(id) {
    if (!confirm('Supprimer cette règle ?')) return;
    await apiFetch(`/rules/${id}`, { method: 'DELETE' });
    await loadRules();
    showToast('Règle supprimée');
}

function showToast(msg) {
    const t = document.createElement('div');
    t.className = 'fixed bottom-4 right-4 bg-gray-800 text-white text-sm px-4 py-2 rounded shadow-lg z-50';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2500);
}

function initRulesSection() {
    // Peupler le select catégories
    const sel = document.getElementById('ruleCategorySelect');
    if (sel && !sel.options.length) {
        RULE_CATEGORIES.forEach(c => {
            const opt = document.createElement('option');
            opt.value = opt.textContent = c;
            sel.appendChild(opt);
        });
    }
    loadRules();
}
