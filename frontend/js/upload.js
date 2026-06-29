/**
 * DocScrub — upload screen logic
 *
 * Owns: tier card selection, roster loading, drag-drop zone, file picker,
 *       queued-file list, upload call, image review screen.
 */
'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let queuedFiles = [];   // File objects from the picker / drop

// ---------------------------------------------------------------------------
// File list rendering
// ---------------------------------------------------------------------------

const ALLOWED_EXTS = ['.pdf', '.docx'];

function extOf(name) {
  return name.slice(name.lastIndexOf('.')).toLowerCase();
}

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function renderFileList() {
  const ul = document.getElementById('file-list');
  if (!ul) return;
  ul.innerHTML = '';
  queuedFiles.forEach((f, i) => {
    const li = document.createElement('li');
    li.className = 'file-item';
    li.innerHTML = `
      <span class="file-icon">${f.name.endsWith('.pdf') ? '📄' : '📝'}</span>
      <span class="file-name">${f.name}</span>
      <span class="file-size">${fmtBytes(f.size)}</span>
      <button class="btn-remove" data-idx="${i}" title="Remove">✕</button>
    `;
    ul.appendChild(li);
  });

  ul.querySelectorAll('.btn-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      queuedFiles.splice(Number(btn.dataset.idx), 1);
      renderFileList();
      updateNextBtn();
    });
  });

  updateNextBtn();
}

function updateNextBtn() {
  const btn = document.getElementById('btn-next');
  if (!btn) return;
  btn.disabled = queuedFiles.length === 0 || !DS.config.tier;
}

// ---------------------------------------------------------------------------
// Add files
// ---------------------------------------------------------------------------

function addFiles(fileList) {
  const newFiles = Array.from(fileList).filter(f => {
    const ext = extOf(f.name);
    if (!ALLOWED_EXTS.includes(ext)) {
      toast(`${f.name}: only PDF and DOCX are supported`, 'warn');
      return false;
    }
    return !queuedFiles.some(q => q.name === f.name);
  });
  queuedFiles.push(...newFiles);
  renderFileList();
}

// ---------------------------------------------------------------------------
// Upload → backend
// ---------------------------------------------------------------------------

async function uploadFiles() {
  const btn = document.getElementById('btn-next');
  btn.disabled = true;
  btn.textContent = 'Uploading…';

  try {
    const fd = new FormData();
    queuedFiles.forEach(f => fd.append('files', f, f.name));

    const data = await API.postForm('/upload', fd);
    DS.jobId = data.job_id;
    DS.files = data.files;

    showScreen('screen-image-review');
    await loadImages();
  } catch (err) {
    toast(`Upload failed: ${err.message}`, 'error');
    btn.disabled = false;
    btn.textContent = 'Continue →';
  }
}

// ---------------------------------------------------------------------------
// Image review screen
// ---------------------------------------------------------------------------

async function loadImages() {
  const grid = document.getElementById('image-grid');
  if (!grid) return;
  grid.innerHTML = '<p class="loading-msg">Loading images…</p>';

  try {
    const images = await API.get(`/jobs/${DS.jobId}/images`);
    renderImageGrid(Array.isArray(images) ? images : []);
  } catch {
    renderImageGrid([]);
  }
}

function renderImageGrid(images) {
  const grid = document.getElementById('image-grid');
  if (!grid) return;

  if (images.length === 0) {
    grid.innerHTML = '<p class="no-images">No embedded images found in these documents.</p>';
    document.getElementById('btn-scrub').textContent = 'Proceed to Anonymize';
    return;
  }

  grid.innerHTML = '';
  images.forEach((img, i) => {
    const item = document.createElement('div');
    item.className = 'thumb-item';
    item.setAttribute('role', 'listitem');
    item.innerHTML = `
      <label class="thumb-label">
        <input type="checkbox" class="thumb-check" data-idx="${i}" checked />
        <img src="data:image/png;base64,${img.b64}" alt="Image ${i + 1}"
             class="thumb-img" />
        <span class="thumb-caption">Page ${img.page ?? '?'}, img ${i + 1}</span>
      </label>
    `;
    grid.appendChild(item);
  });
}

// ---------------------------------------------------------------------------
// Select-all / deselect-all
// ---------------------------------------------------------------------------

function setAllChecked(checked) {
  document.querySelectorAll('.thumb-check').forEach(cb => { cb.checked = checked; });
}

// ---------------------------------------------------------------------------
// Tier card selection
// ---------------------------------------------------------------------------

function selectTier(tier) {
  DS.config.tier = tier;

  document.querySelectorAll('.tier-card').forEach(card => {
    const active = card.dataset.tier === tier;
    card.classList.toggle('selected', active);
    card.setAttribute('aria-checked', active ? 'true' : 'false');
  });

  const rosterSection = document.getElementById('roster-section');
  const llmSection    = document.getElementById('llm-section');

  // Roster shown for all tiers — required for 1 & 2, optional for Full Scan
  if (rosterSection) rosterSection.hidden = false;
  if (llmSection)    llmSection.hidden    = tier !== 'full';

  // Heading and hint reflect whether roster is required or optional
  const rosterHeading = document.querySelector('.roster-section-heading');
  if (rosterHeading) {
    rosterHeading.textContent = tier === 'full'
      ? 'Load your class roster (optional)'
      : 'Load your class roster';
  }
  const rosterHint = document.getElementById('roster-optional-hint');
  if (rosterHint) rosterHint.hidden = tier !== 'full';

  if (tier === 'full') {
    const epInput = document.getElementById('llm-endpoint-inline');
    if (epInput && !epInput.value) epInput.value = DS.config.llm_endpoint;
    loadModelsInline();
  }

  updateNextBtn();
  updateScrubBtn();
}

// ---------------------------------------------------------------------------
// Scrub button state (Screen 2)
// ---------------------------------------------------------------------------

function updateScrubBtn() {
  const scrubBtn = document.getElementById('btn-scrub');
  if (!scrubBtn) return;
  const tier      = DS.config.tier || 'full';
  const rosterId  = DS.config.roster_id || '';
  const needsRoster = tier === 'names' || tier === 'names_patterns';
  scrubBtn.disabled = needsRoster && !rosterId;
}

// ---------------------------------------------------------------------------
// Roster loading
// ---------------------------------------------------------------------------

async function loadRosters(selectId) {
  const sel = document.getElementById('roster-select');
  if (!sel) return;
  try {
    const rosters = await API.get('/rosters');
    sel.innerHTML = '<option value="">— select a saved roster —</option>';
    (rosters || []).forEach(r => {
      const opt = document.createElement('option');
      opt.value = r.id;
      opt.textContent = `${r.name} (${r.entry_count || 0} entries)`;
      sel.appendChild(opt);
    });
    if (selectId) sel.value = selectId;
  } catch { /* roster endpoint optional */ }
  updateScrubBtn();
}

async function uploadRosterFile(file) {
  const rosterFileInput = document.getElementById('roster-file-input');
  const name = file.name.replace(/\.[^.]+$/, '');

  try {
    const roster = await API.post('/rosters', { name });

    const fd = new FormData();
    fd.append('file', file, file.name);
    const result = await API.postForm(`/rosters/${roster.id}/entries`, fd);

    await loadRosters(roster.id);
    DS.config.roster_id = roster.id;
    updateScrubBtn();
    updateNextBtn();
    toast(`Roster "${name}" loaded — ${result.count} entries`, 'success');
  } catch (err) {
    toast(`Roster upload failed: ${err.message}`, 'error');
  }

  if (rosterFileInput) rosterFileInput.value = '';
}

// ---------------------------------------------------------------------------
// LLM model loading (inline section)
// ---------------------------------------------------------------------------

async function loadModelsInline() {
  const sel = document.getElementById('model-select-inline');
  if (!sel) return;
  try {
    const data   = await API.get('/models');
    const models = data.models || [];
    if (models.length > 0) {
      sel.innerHTML = '';
      models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        if (m === DS.config.model) opt.selected = true;
        sel.appendChild(opt);
      });
    }
  } catch { /* keep default option */ }
}

// ---------------------------------------------------------------------------
// Start anonymisation
// ---------------------------------------------------------------------------

async function startScrub() {
  // tier and roster_id already set in DS.config from Screen 1
  showScreen('screen-processing');
  document.getElementById('step-indicator').textContent = 'Starting…';
  document.getElementById('progress-bars').innerHTML = '';

  try {
    await streamAnonymize(DS.jobId);
  } catch (err) {
    toast(`Anonymization failed: ${err.message}`, 'error');
    showScreen('screen-upload');
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  const nextBtn   = document.getElementById('btn-next');
  const scrubBtn  = document.getElementById('btn-scrub');
  const selAll    = document.getElementById('select-all');
  const deselAll  = document.getElementById('deselect-all');

  // Tier cards
  document.querySelectorAll('.tier-card').forEach(card => {
    const activate = () => selectTier(card.dataset.tier);
    card.addEventListener('click', activate);
    card.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
    });
  });

  // Roster select → sync DS.config
  document.getElementById('roster-select')?.addEventListener('change', e => {
    DS.config.roster_id = e.target.value || null;
    updateScrubBtn();
    updateNextBtn();
  });

  // Roster CSV upload
  document.getElementById('roster-file-input')?.addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) uploadRosterFile(file);
  });

  // Inline LLM fields → sync DS.config
  document.getElementById('llm-endpoint-inline')?.addEventListener('change', e => {
    DS.config.llm_endpoint = e.target.value.trim() || 'http://localhost:11434';
  });
  document.getElementById('model-select-inline')?.addEventListener('change', e => {
    DS.config.model = e.target.value;
  });

  // Check Ollama connection
  document.getElementById('btn-check-ollama')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-check-ollama');
    const prev = btn.textContent;
    btn.textContent = 'Checking…';
    btn.disabled = true;
    try {
      await API.get('/models');
      toast('Ollama is running and reachable ✓', 'success');
    } catch {
      toast('Cannot reach Ollama — make sure it is running on ' +
            (DS.config.llm_endpoint || 'http://localhost:11434'), 'error');
    } finally {
      btn.textContent = prev;
      btn.disabled = false;
    }
  });

  // Drag-drop
  if (dropZone) {
    dropZone.addEventListener('dragover', e => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      addFiles(e.dataTransfer.files);
    });
    dropZone.addEventListener('click', e => {
      if (!e.target.closest('label')) fileInput?.click();
    });
  }

  // File picker
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      addFiles(fileInput.files);
      fileInput.value = '';
    });
  }

  // Next / Scrub buttons
  nextBtn?.addEventListener('click', uploadFiles);
  scrubBtn?.addEventListener('click', startScrub);

  // Select-all toggles
  selAll?.addEventListener('click', () => setAllChecked(true));
  deselAll?.addEventListener('click', () => setAllChecked(false));

  // Pre-load roster list (silent — backend may not be running yet)
  loadRosters();
});
