// ─── Classeur virtuel ─────────────────────────────────────────────────────────

const CATEGORY_ORDER = [
    'Facture', 'Impôts', 'Banque', 'Assurance',
    'Travail', 'Santé', 'Contrat', 'Courrier', 'Autre'
];
const CATEGORY_ICONS = {
    'Facture':'🧾','Impôts':'📋','Santé':'💊','Banque':'🏦',
    'Contrat':'📝','Assurance':'🛡','Travail':'💼','Courrier':'✉️','Autre':'📁',
};
const _openCategories = new Set();

function _sortKey(doc, sortBy) {
    if (sortBy === 'doc_date')   return doc.doc_date   || doc.created_at || '';
    if (sortBy === 'created_at') return doc.created_at || '';
    if (sortBy === 'filename')   return (doc.filename  || '').toLowerCase();
    return '';
}

function _formatDate(str) {
    if (!str) return '—';
    const d = new Date(str);
    if (isNaN(d)) return str;
    return d.toLocaleDateString('fr-CA');
}

function renderClasseur() {
    const sortBy    = document.getElementById('classeurSort')?.value || 'doc_date';
    const container = document.getElementById('classeurAccordion');
    if (!container) return;

    const groups = {};
    for (const doc of allDocs) {
        const cat = doc.category || 'Autre';
        if (!groups[cat]) groups[cat] = [];
        groups[cat].push(doc);
    }

    const descSort = sortBy !== 'filename';
    for (const cat in groups) {
        groups[cat].sort((a, b) => {
            const ka = _sortKey(a, sortBy);
            const kb = _sortKey(b, sortBy);
            return descSort ? kb.localeCompare(ka) : ka.localeCompare(kb);
        });
    }

    const unknownCats = Object.keys(groups).filter(c => !CATEGORY_ORDER.includes(c)).sort();
    const orderedCats = [...CATEGORY_ORDER, ...unknownCats].filter(c => groups[c]);

    if (!orderedCats.length) {
        container.innerHTML = '<p class="text-sm text-gray-400 text-center p-8">Aucun document classé.</p>';
        return;
    }

    container.innerHTML = orderedCats.map(cat => {
        const docs  = groups[cat];
        const icon  = CATEGORY_ICONS[cat] || '📁';
        const color = CATEGORY_COLORS[cat] || 'bg-gray-100 text-gray-500';
        const isOpen = _openCategories.has(cat) || (_openCategories.size === 0 && cat === orderedCats[0]);

        const rows = docs.map(doc => {
            const dateSrc = sortBy === 'created_at' ? doc.created_at : (doc.doc_date || doc.created_at);
            return `<div class='classeur-item' id='citem-${doc.id}' onclick='openClasseurDoc(${doc.id})'>
                <div class='flex-1 min-w-0'>
                    <p class='text-sm font-medium text-gray-800 truncate'>${escHtml(doc.filename)}</p>
                    ${doc.issuer  ? `<p class='text-xs text-gray-400 mt-0.5 truncate'>🏢 ${escHtml(doc.issuer)}</p>` : ''}
                    ${doc.summary ? `<p class='text-xs text-gray-400 mt-0.5 truncate'>${escHtml(doc.summary)}</p>` : ''}
                    ${doc.amount  ? `<span class='text-xs text-green-600 font-medium'>💶 ${escHtml(doc.amount)}</span>` : ''}
                    ${!doc.category ? `<span class='text-xs text-gray-400 animate-pulse'>⏳ traitement...</span>` : ''}
                </div>
                <div class='classeur-date-col'>
                    ${doc.doc_date ? `<span class='font-medium text-gray-600'>${_formatDate(doc.doc_date)}</span>` : ''}
                    ${!doc.doc_date && doc.created_at ? `<span class='italic'>${_formatDate(doc.created_at)}</span>` : ''}
                </div>
            </div>`;
        }).join('');

        return `<div class='accordion-section' data-cat='${escAttr(cat)}'>
            <div class='accordion-header ${isOpen ? "open" : ""}' onclick='toggleAccordion(this)'>
                <div class='flex items-center gap-2'>
                    <span class='text-lg'>${icon}</span>
                    <span class='font-semibold text-gray-700 text-sm'>${escHtml(cat)}</span>
                    <span class='meta-badge ${color} ml-1'>${docs.length}</span>
                </div>
                <span class='accordion-chevron'>▶</span>
            </div>
            <div class='accordion-body ${isOpen ? "" : "closed"}' style='max-height:${isOpen ? docs.length * 80 + "px" : "0"}'>
                ${rows}
            </div>
        </div>`;
    }).join('');
}

function toggleAccordion(header) {
    const cat    = header.closest('.accordion-section').dataset.cat;
    const body   = header.nextElementSibling;
    const isNowOpen = !header.classList.contains('open');
    header.classList.toggle('open', isNowOpen);
    body.classList.toggle('closed', !isNowOpen);
    if (isNowOpen) {
        const rows = body.querySelectorAll('.classeur-item').length;
        body.style.maxHeight = (rows * 80 + 20) + 'px';
        body.style.opacity   = '1';
        _openCategories.add(cat);
    } else {
        body.style.maxHeight = '0';
        body.style.opacity   = '0';
        _openCategories.delete(cat);
    }
}

let _classeurCurrentDocId = null;

async function openClasseurDoc(id) {
    document.querySelectorAll('.classeur-item').forEach(el => el.classList.remove('active'));
    const item = document.getElementById('citem-' + id);
    if (item) item.classList.add('active');
    _classeurCurrentDocId = id;

    const res = await fetch(`${API_URL}/documents/${id}`, { headers: { 'Authorization': authHeader } });
    const doc = await res.json();

    let formData = {};
    try { if (doc.form_data) formData = JSON.parse(doc.form_data); } catch(e) {}

    const isPdf        = doc.filename.toLowerCase().endsWith('.pdf');
    const hasPdfVersion = !!doc.pdf_filename;
    const fileUrl      = `${API_URL}/documents/${id}/file`;
    const pdfUrl       = `${API_URL}/documents/${id}/pdf`;
    const color        = CATEGORY_COLORS[doc.category] || 'bg-gray-100 text-gray-500';
    const panel        = document.getElementById('classeurDetailPanel');

    const pipelineBadge = (() => {
        let sources = doc.pipeline_sources;
        try { if (typeof sources === 'string') sources = JSON.parse(sources); } catch(e) { sources = null; }
        if (!sources || !sources.length) return '';
        if (sources.includes('vision') && sources.includes('ocr+llm'))
            return `<span class='meta-badge bg-purple-100 text-purple-700'>🔀 Vision+OCR</span>`;
        if (sources.includes('vision'))
            return `<span class='meta-badge bg-purple-100 text-purple-700'>👁 Vision</span>`;
        return `<span class='meta-badge bg-gray-100 text-gray-500'>📝 OCR+LLM</span>`;
    })();

    panel.innerHTML = `
        <div class='flex items-start justify-between mb-4 gap-2'>
            <div class='flex-1 min-w-0'>
                <h2 class='text-lg font-bold text-gray-800 truncate'>${escHtml(doc.filename)}</h2>
                <div class='flex flex-wrap gap-2 mt-1'>
                    ${doc.category ? `<span class='meta-badge ${color}'>${escHtml(doc.category)}</span>` : ''}
                    ${doc.issuer   ? `<span class='meta-badge bg-gray-100 text-gray-600'>🏢 ${escHtml(doc.issuer)}</span>` : ''}
                    ${doc.doc_date ? `<span class='meta-badge bg-blue-50 text-blue-600'>📅 ${doc.doc_date}</span>` : ''}
                    ${doc.amount   ? `<span class='meta-badge bg-green-50 text-green-700'>💶 ${escHtml(doc.amount)}</span>` : ''}
                    ${pipelineBadge}
                </div>
            </div>
            <div class='flex gap-2 flex-shrink-0'>
                <a href='${fileUrl}' target='_blank'
                    class='text-xs bg-gray-100 hover:bg-gray-200 px-3 py-1.5 rounded font-medium'>⬇ Télécharger</a>
                ${hasPdfVersion ? `<a href='${pdfUrl}' target='_blank'
                    class='text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 px-3 py-1.5 rounded font-medium'>📄 PDF</a>` : ''}
                <button onclick='deleteClasseurDoc(${doc.id})'
                    class='text-xs bg-red-50 hover:bg-red-100 text-red-600 px-3 py-1.5 rounded font-medium'>🗑</button>
            </div>
        </div>

        <div class='flex gap-4 border-b mb-4 text-sm'>
            <button onclick='showClasseurTab("preview")' id='cdPreview' class='pb-2 tab-active'>Aperçu</button>
            <button onclick='showClasseurTab("ocr")'     id='cdOcr'     class='pb-2 text-gray-500'>Texte OCR</button>
            <button onclick='showClasseurTab("form")'    id='cdForm'    class='pb-2 text-gray-500'>📝 Formulaire</button>
        </div>

        <div id='cdTabPreview'>
            ${isPdf || hasPdfVersion
                ? `<iframe src='${isPdf ? fileUrl : pdfUrl}#toolbar=0&navpanes=0'
                       style='width:100%;height:500px;border:none;border-radius:8px;' title='Aperçu PDF'>
                   </iframe>
                   <p class='text-xs text-gray-400 mt-1 text-center'>
                       <a href='${isPdf ? fileUrl : pdfUrl}' class='text-blue-500 underline' target='_blank'>↗ Ouvrir dans un nouvel onglet</a>
                   </p>`
                : `<img src='${fileUrl}' class='max-w-full rounded border' alt='${escAttr(doc.filename)}'>`}
        </div>

        <div id='cdTabOcr' class='hidden'>
            ${doc.content
                ? `<pre class='text-xs text-gray-700 bg-gray-50 rounded p-4 overflow-auto max-h-[55vh] whitespace-pre-wrap font-mono'>${escHtml(doc.content)}</pre>`
                : `<p class='text-gray-400 text-sm'>Texte non disponible.</p>`}
        </div>

        <div id='cdTabForm' class='hidden'>
            <p class='text-xs text-gray-400 mb-3'>Champs pré-remplis par le LLM — éditables et sauvegardables.</p>
            <div class='grid grid-cols-2 gap-3 mb-4'>
                ${formField('Catégorie','cd_category', formData.category||doc.category||'')}
                ${formField('Émetteur','cd_issuer',    formData.issuer||doc.issuer||'')}
                ${formField('Date','cd_doc_date',      formData.doc_date||doc.doc_date||'')}
                ${formField('Montant','cd_amount',     formData.amount||doc.amount||'')}
            </div>
            <div class='mb-4'>
                <label class='block text-xs font-medium text-gray-600 mb-1'>Résumé</label>
                <textarea id='cd_summary' rows='2' class='w-full p-2 border rounded text-sm'>${escHtml(formData.summary||doc.summary||'')}</textarea>
            </div>
            <div class='mb-4'>
                <label class='block text-xs font-medium text-gray-600 mb-1'>Notes personnelles</label>
                <textarea id='cd_notes' rows='3' class='w-full p-2 border rounded text-sm'>${escHtml(formData.notes||'')}</textarea>
            </div>
            <button onclick='saveClasseurForm(${doc.id})'
                class='bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium'>💾 Sauvegarder</button>
            <span id='cdFormSaved' class='hidden text-green-600 text-sm ml-3'>✓ Sauvegardé</span>
        </div>`;
}

function showClasseurTab(name) {
    ['preview','ocr','form'].forEach(t => {
        document.getElementById('cdTab'+cap(t)).classList.toggle('hidden', t!==name);
        const btn = document.getElementById('cd'+cap(t));
        btn.className = 'pb-2 ' + (t===name ? 'tab-active' : 'text-gray-500');
    });
}

async function saveClasseurForm(docId) {
    const data = {
        category: document.getElementById('cd_category').value,
        issuer:   document.getElementById('cd_issuer').value,
        doc_date: document.getElementById('cd_doc_date').value,
        amount:   document.getElementById('cd_amount').value,
        summary:  document.getElementById('cd_summary').value,
        notes:    document.getElementById('cd_notes').value,
    };
    await fetch(`${API_URL}/documents/${docId}/form`, {
        method: 'PATCH',
        headers: { 'Authorization': authHeader, 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    const el = document.getElementById('cdFormSaved');
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 2000);
    await loadDocuments();
    renderClasseur();
}

async function deleteClasseurDoc(docId) {
    if (!confirm('Supprimer ce document ?')) return;
    await fetch(`${API_URL}/documents/${docId}`, {
        method: 'DELETE', headers: { 'Authorization': authHeader }
    });
    _classeurCurrentDocId = null;
    document.getElementById('classeurDetailPanel').innerHTML =
        '<div class="flex items-center justify-center h-64 text-gray-300 flex-col gap-2"><span class="text-5xl">🗂</span><span class="text-sm">Sélectionnez un document dans le classeur</span></div>';
    await loadDocuments();
    renderClasseur();
}
