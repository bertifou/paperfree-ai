// ─── Liste des documents ──────────────────────────────────────────────────────

function renderDocList(docs) {
    const el = document.getElementById('docList');
    if (!docs.length) { el.innerHTML = '<p class="text-gray-400 text-sm">Aucun document.</p>'; return; }
    el.innerHTML = docs.map(d => {
        const color = CATEGORY_COLORS[d.category] || 'bg-gray-100 text-gray-500';
        const processing = !d.category;
        return `<div onclick='openDoc(${d.id})'
            class='p-3 rounded-lg border cursor-pointer hover:border-blue-300 hover:bg-blue-50 transition ${currentDocId===d.id?"border-blue-400 bg-blue-50":"border-gray-200"}'>
            <div class='flex items-start justify-between gap-2'>
                <span class='text-sm font-medium text-gray-800 truncate flex-1'>${d.filename}</span>
                ${processing
                    ? `<span class='meta-badge bg-gray-100 text-gray-400 animate-pulse'>⏳</span>`
                    : `<span class='meta-badge ${color}'>${d.category}</span>`}
            </div>
            ${d.summary ? `<p class='text-xs text-gray-500 mt-1 truncate'>${d.summary}</p>` : ''}
            ${d.issuer  ? `<p class='text-xs text-gray-400 mt-0.5'>${d.issuer}</p>` : ''}
            <p class='text-xs text-gray-300 mt-1'>${new Date(d.created_at).toLocaleDateString('fr-CA')}</p>
        </div>`;
    }).join('');
}

async function loadDocuments() {
    try {
        const res = await fetch(`${API_URL}/documents`, { headers: { 'Authorization': authHeader } });
        if (res.status === 401) return logout();
        allDocs = await res.json();
        renderDocList(allDocs);
        if (!document.getElementById('tabClasseur').classList.contains('hidden')) renderClasseur();
    } catch(e) {}
}

// ─── Détail document ──────────────────────────────────────────────────────────

async function openDoc(id) {
    currentDocId = id;
    renderDocList(allDocs);

    const res = await fetch(`${API_URL}/documents/${id}`, { headers: { 'Authorization': authHeader } });
    const doc = await res.json();

    let formData = {};
    try { if (doc.form_data) formData = JSON.parse(doc.form_data); } catch(e) {}

    const isPdf        = doc.filename.toLowerCase().endsWith('.pdf');
    const hasPdfVersion = !!doc.pdf_filename;
    const fileUrl      = `${API_URL}/documents/${id}/file`;
    const pdfUrl       = `${API_URL}/documents/${id}/pdf`;
    const color        = CATEGORY_COLORS[doc.category] || 'bg-gray-100 text-gray-500';

    const pipelineBadge = (() => {
        let sources = doc.pipeline_sources;
        try { if (typeof sources === 'string') sources = JSON.parse(sources); } catch(e) { sources = null; }
        if (!sources || !sources.length) return '';
        if (sources.includes('vision') && sources.includes('ocr+llm'))
            return `<span class='meta-badge bg-purple-100 text-purple-700' title='Double voie'>🔀 Vision+OCR</span>`;
        if (sources.includes('vision'))
            return `<span class='meta-badge bg-purple-100 text-purple-700'>👁 Vision</span>`;
        return `<span class='meta-badge bg-gray-100 text-gray-500'>📝 OCR+LLM</span>`;
    })();

    document.getElementById('detailPanel').innerHTML = `
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
                <button onclick='deleteDoc(${doc.id})'
                    class='text-xs bg-red-50 hover:bg-red-100 text-red-600 px-3 py-1.5 rounded font-medium'>🗑 Supprimer</button>
            </div>
        </div>

        <div class='flex gap-4 border-b mb-4 text-sm'>
            <button onclick='showDocTab("preview")' id='dtPreview' class='pb-2 tab-active'>Aperçu</button>
            <button onclick='showDocTab("ocr")'     id='dtOcr'     class='pb-2 text-gray-500'>Texte OCR</button>
            <button onclick='showDocTab("form")'    id='dtForm'    class='pb-2 text-gray-500'>📝 Formulaire</button>
        </div>

        <div id='dtTabPreview'>
            ${isPdf || hasPdfVersion
                ? `<iframe src='${isPdf ? fileUrl : pdfUrl}#toolbar=0&navpanes=0' id='pdfViewer'
                       style='width:100%;height:500px;border:none;border-radius:8px;' title='Aperçu PDF'>
                   </iframe>
                   <p class='text-xs text-gray-400 mt-1 text-center'>
                       <a href='${isPdf ? fileUrl : pdfUrl}' class='text-blue-500 underline' target='_blank'>↗ Ouvrir dans un nouvel onglet</a>
                   </p>`
                : `<img src='${fileUrl}' class='max-w-full rounded border' alt='${escAttr(doc.filename)}'
                    onerror="this.outerHTML='<p class=text-gray-400 text-sm>Aperçu indisponible.</p>'">`}
        </div>

        <div id='dtTabOcr' class='hidden'>
            ${doc.content
                ? `<pre class='text-xs text-gray-700 bg-gray-50 rounded p-4 overflow-auto max-h-[55vh] whitespace-pre-wrap font-mono'>${escHtml(doc.content)}</pre>`
                : `<p class='text-gray-400 text-sm'>Texte non encore extrait ou document en cours de traitement.</p>`}
        </div>

        <div id='dtTabForm' class='hidden'>
            <p class='text-xs text-gray-400 mb-3'>Champs pré-remplis par le LLM — éditables et sauvegardables.</p>
            <div class='grid grid-cols-2 gap-3 mb-4'>
                ${formField('Catégorie','category', formData.category||doc.category||'')}
                ${formField('Émetteur','issuer',    formData.issuer||doc.issuer||'')}
                ${formField('Date','doc_date',      formData.doc_date||doc.doc_date||'')}
                ${formField('Montant','amount',     formData.amount||doc.amount||'')}
            </div>
            <div class='mb-4'>
                <label class='block text-xs font-medium text-gray-600 mb-1'>Résumé</label>
                <textarea id='form_summary' rows='2' class='w-full p-2 border rounded text-sm'>${escHtml(formData.summary||doc.summary||'')}</textarea>
            </div>
            <div class='mb-4'>
                <label class='block text-xs font-medium text-gray-600 mb-1'>Notes personnelles</label>
                <textarea id='form_notes' rows='3' class='w-full p-2 border rounded text-sm'>${escHtml(formData.notes||'')}</textarea>
            </div>
            <button onclick='saveForm(${doc.id})'
                class='bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium'>💾 Sauvegarder</button>
            <span id='formSaved' class='hidden text-green-600 text-sm ml-3'>✓ Sauvegardé</span>
        </div>`;
}

function showDocTab(name) {
    ['preview','ocr','form'].forEach(t => {
        document.getElementById('dtTab'+cap(t)).classList.toggle('hidden', t!==name);
        const btn = document.getElementById('dt'+cap(t));
        btn.className = 'pb-2 ' + (t===name ? 'tab-active' : 'text-gray-500');
    });
}

async function saveForm(docId) {
    const data = {
        category: document.getElementById('form_category').value,
        issuer:   document.getElementById('form_issuer').value,
        doc_date: document.getElementById('form_doc_date').value,
        amount:   document.getElementById('form_amount').value,
        summary:  document.getElementById('form_summary').value,
        notes:    document.getElementById('form_notes').value,
    };
    await fetch(`${API_URL}/documents/${docId}/form`, {
        method: 'PATCH',
        headers: { 'Authorization': authHeader, 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    const el = document.getElementById('formSaved');
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 2000);
    loadDocuments();
}

async function deleteDoc(docId) {
    if (!confirm('Supprimer ce document ?')) return;
    await fetch(`${API_URL}/documents/${docId}`, {
        method: 'DELETE', headers: { 'Authorization': authHeader }
    });
    currentDocId = null;
    document.getElementById('detailPanel').innerHTML =
        '<div class="flex items-center justify-center h-64 text-gray-300 flex-col gap-2"><span class="text-5xl">📄</span><span class="text-sm">Sélectionnez un document</span></div>';
    loadDocuments();
}

// ─── Recherche ────────────────────────────────────────────────────────────────

async function doSearch(mode) {
    const q = document.getElementById('searchInput').value.trim();
    if (!q) { loadDocuments(); return; }
    const res = await fetch(`${API_URL}/search?q=${encodeURIComponent(q)}&mode=${mode}`, {
        headers: { 'Authorization': authHeader }
    });
    const data = await res.json();
    allDocs = data.results;
    renderDocList(allDocs);
    const llmBox = document.getElementById('llmAnswer');
    if (mode === 'llm' && data.llm_answer) {
        llmBox.textContent = data.llm_answer;
        llmBox.classList.remove('hidden');
    } else {
        llmBox.classList.add('hidden');
    }
}

// ─── Upload ───────────────────────────────────────────────────────────────────

let _pendingFile = null;

function triggerCapture(mode) {
    if (mode === 'camera') document.getElementById('fileInputCamera').click();
    else                   document.getElementById('fileInput').click();
}

function _handleFileSelected(file) {
    if (!file) return;
    _pendingFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
        const preview = document.getElementById('previewContainer');
        const img     = document.getElementById('previewImg');
        const tips    = document.getElementById('qualityTips');
        img.src = e.target.result;
        preview.classList.remove('hidden');
        if (file.type.startsWith('image/')) {
            tips.classList.toggle('hidden', file.size >= 200 * 1024);
        } else {
            tips.classList.add('hidden');
            img.src = '';
            img.alt = `📄 ${file.name}`;
            img.style.padding  = '2rem';
            img.style.fontSize = '3rem';
        }
    };
    reader.readAsDataURL(file);
}

function cancelPreview() {
    _pendingFile = null;
    document.getElementById('previewContainer').classList.add('hidden');
    document.getElementById('fileInput').value        = '';
    document.getElementById('fileInputCamera').value  = '';
}

async function confirmUpload() {
    if (!_pendingFile) return;
    const file = _pendingFile;
    _pendingFile = null;
    document.getElementById('previewContainer').classList.add('hidden');
    document.getElementById('uploadStatus').classList.remove('hidden');
    const formData = new FormData();
    formData.append('file', file);
    await fetch(`${API_URL}/upload`, {
        method: 'POST', body: formData, headers: { 'Authorization': authHeader }
    });
    document.getElementById('fileInput').value        = '';
    document.getElementById('fileInputCamera').value  = '';
    setTimeout(() => document.getElementById('uploadStatus').classList.add('hidden'), 5000);
    loadDocuments();
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('fileInput').onchange        = (e) => _handleFileSelected(e.target.files[0]);
    document.getElementById('fileInputCamera').onchange  = (e) => _handleFileSelected(e.target.files[0]);
});
