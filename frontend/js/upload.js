/**
 * DocScrub — upload screen logic
 *
 * Owns: drag-drop zone, file picker, queued-file list, upload call,
 *       image review screen (thumbnail grid + checkboxes).
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

  // Remove buttons
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
  if (btn) btn.disabled = queuedFiles.length === 0;
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
    // Deduplicate by name
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

    // Check for images (kick off extraction in background)
    showScreen('screen-image-review');
    await loadImages();
  } catch (err) {
    toast(`Upload failed: ${err.message}`, 'error');
    btn.disabled = false;
    btn.textContent = 'Next →';
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
    // Auto-advance to processing since there's nothing to review
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
// Wire: select-all / deselect-all
// ---------------------------------------------------------------------------

function setAllChecked(checked) {
  document.querySelectorAll('.thumb-check').forEach(cb => { cb.checked = checked; });
}

// ---------------------------------------------------------------------------
// Tier / roster controls
// ---------------------------------------------------------------------------

function updateScrubBtn() {
  const scrubBtn = document.getElementById('btn-scrub');
  if (!scrubBtn) return;
  const tierSelect   = document.getElementById('tier-select');
  const rosterSelect = document.getElementById('roster-select');
  const tier     = tierSelect   ? tierSelect.value   : 'full';
  const rosterId = rosterSelect ? rosterSelect.value : '';
  const needsRoster = tier === 'names' || tier === 'names_patterns';
  scrubBtn.disabled = needsRoster && !rosterId;
}

async function loadRosters(selectId) {
  const sel = document.getElementById('roster-select');
  if (!sel) return;
  try {
    const rosters = await API.get('/rosters');
    sel.innerHTML = '<option value="">— select a roster —</option>';
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
    toast(`Roster "${name}" loaded — ${result.count} entries`, 'success');
  } catch (err) {
    toast(`Roster upload failed: ${err.message}`, 'error');
  }

  if (rosterFileInput) rosterFileInput.value = '';
}

// ---------------------------------------------------------------------------
// Start anonymisation
// ---------------------------------------------------------------------------

async function startScrub() {
  // Read tier and roster_id from the UI controls
  const tierSelect   = document.getElementById('tier-select');
  const rosterSelect = document.getElementById('roster-select');
  DS.config.tier      = tierSelect   ? tierSelect.value   : 'full';
  DS.config.roster_id = rosterSelect ? (rosterSelect.value || null) : null;

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
    dropZone.addEventListener('click', () => fileInput?.click());
  }

  // File picker
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      addFiles(fileInput.files);
      fileInput.value = '';
    });
  }

  // Next button
  nextBtn?.addEventListener('click', uploadFiles);

  // Scrub button
  scrubBtn?.addEventListener('click', startScrub);

  // Tier / roster change → update scrub button state
  document.getElementById('tier-select')
    ?.addEventListener('change', updateScrubBtn);
  document.getElementById('roster-select')
    ?.addEventListener('change', updateScrubBtn);

  // Roster CSV upload
  document.getElementById('roster-file-input')
    ?.addEventListener('change', e => {
      const file = e.target.files[0];
      if (file) uploadRosterFile(file);
    });

  // Select-all toggles
  selAll?.addEventListener('click', () => setAllChecked(true));
  deselAll?.addEventListener('click', () => setAllChecked(false));

  // Load rosters when image review screen is shown
  loadRosters();
});
