/**
 * DocScrub — export + re-identify screen logic
 *
 * Owns: job summary, download buttons, new-job reset,
 *       re-identify flow (drop anonymized + mapping, call /reidentify).
 */
'use strict';

// ---------------------------------------------------------------------------
// Export screen
// ---------------------------------------------------------------------------

function populateSummary() {
  const piiCount = DS.mapping?.length ?? 0;
  const fileCount = DS.files?.length ?? 0;
  const model = DS.config?.model ?? '—';

  setText('summary-files', `${fileCount} file${fileCount !== 1 ? 's' : ''} anonymized`);
  setText('summary-pii',   `${piiCount} PII item${piiCount !== 1 ? 's' : ''} found`);
  setText('summary-model', `Model: ${model}`);
  setText('summary-timestamp', `Exported: ${new Date().toLocaleString()}`);
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

// ---------------------------------------------------------------------------
// Downloads
// ---------------------------------------------------------------------------

async function downloadFiles() {
  if (!DS.jobId) { toast('No job to export', 'warn'); return; }
  try {
    const { blob, headers } = await API.getBlob(`/jobs/${DS.jobId}/export`);
    const cd = headers.get('content-disposition') || '';
    const match = cd.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : `docscrub_${DS.jobId}.bin`;
    triggerDownload(blob, filename);
  } catch (err) {
    toast(`Download failed: ${err.message}`, 'error');
  }
}

async function downloadMapping() {
  if (!DS.jobId) { toast('No job to export', 'warn'); return; }
  try {
    const { blob } = await API.getBlob(`/jobs/${DS.jobId}/export/mapping`);
    triggerDownload(blob, `mapping_${DS.jobId}.json`);
  } catch (err) {
    toast(`Download failed: ${err.message}`, 'error');
  }
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// ---------------------------------------------------------------------------
// New job reset
// ---------------------------------------------------------------------------

function newJob() {
  DS.jobId = null;
  DS.files = [];
  DS.mapping = [];
  DS.fileResults = [];

  // Reset upload screen
  document.getElementById('file-list').innerHTML = '';
  document.getElementById('btn-next').disabled = true;
  document.getElementById('progress-bars').innerHTML = '';
  document.getElementById('step-indicator').textContent = 'Initialising…';
  document.getElementById('mapping-table').innerHTML = '';
  document.getElementById('text-original').textContent = '';
  document.getElementById('text-anonymized').innerHTML = '';
  document.querySelector('.file-tabs')?.remove();

  showScreen('screen-upload');
}

// ---------------------------------------------------------------------------
// Re-identify screen
// ---------------------------------------------------------------------------

let reidFiles  = [];  // anonymized file objects dropped by user
let reidMapping = null; // parsed mapping JSON

function renderReidDropZone(zoneId, labelText, onDrop) {
  const zone = document.getElementById(zoneId);
  if (!zone) return;
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    onDrop(e.dataTransfer.files);
  });
  zone.addEventListener('click', () => {
    const inp = document.createElement('input');
    inp.type = 'file';
    if (zoneId === 'reid-mapping-drop') inp.accept = '.json';
    inp.addEventListener('change', () => onDrop(inp.files));
    inp.click();
  });
}

async function doReidentify() {
  if (!reidMapping) { toast('Drop a mapping JSON file first', 'warn'); return; }

  const jobId = document.getElementById('reid-job-id')?.value?.trim() || DS.jobId;
  if (!jobId) { toast('Enter the Job ID from your mapping filename', 'warn'); return; }

  // Convert list format [{placeholder, original, ...}] → {placeholder: original} dict
  const mapping = {};
  const entries = Array.isArray(reidMapping) ? reidMapping : [reidMapping];
  entries.forEach(e => { if (e.placeholder && e.original) mapping[e.placeholder] = e.original; });

  if (!Object.keys(mapping).length) {
    toast('Mapping file has no valid entries', 'warn');
    return;
  }

  try {
    const { blob, headers } = await API.postBlob('/reidentify', { job_id: jobId, mapping });
    const cd = headers.get('content-disposition') || '';
    const match = cd.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : `restored_${jobId}.bin`;
    triggerDownload(blob, filename);
    toast('Documents restored — download started', 'success');
  } catch (err) {
    toast(`Re-identify failed: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  // Export screen: populate summary whenever screen becomes visible
  document.getElementById('btn-export')?.addEventListener('click', () => {
    populateSummary();
    showScreen('screen-export');
  });

  // Download buttons
  document.querySelectorAll('[data-action="download-files"]').forEach(btn => {
    btn.addEventListener('click', downloadFiles);
  });
  document.querySelectorAll('[data-action="download-mapping"]').forEach(btn => {
    btn.addEventListener('click', downloadMapping);
  });

  // New job (export screen button)
  document.getElementById('btn-new-job')?.addEventListener('click', newJob);

  // Start Over (review screen button)
  document.getElementById('btn-start-over')?.addEventListener('click', newJob);

  // Back from re-identify → upload
  document.getElementById('btn-reid-back')?.addEventListener('click', () => showScreen('screen-upload'));

  // Site nav: logo → new job, re-identify link → reid screen
  document.getElementById('nav-home')?.addEventListener('click', e => {
    e.preventDefault();
    newJob();
  });
  document.getElementById('nav-reidentify')?.addEventListener('click', e => {
    e.preventDefault();
    // Pre-fill job ID if there's an active job
    const inp = document.getElementById('reid-job-id');
    if (inp && DS.jobId) inp.value = DS.jobId;
    showScreen('reidentify');
  });

  // Re-identify drop zones
  renderReidDropZone('reid-drop-zone', 'Drop anonymized files here', files => {
    reidFiles = Array.from(files);
    const zone = document.getElementById('reid-drop-zone');
    if (zone) zone.querySelector('.drop-zone-main').textContent =
      `${reidFiles.length} file${reidFiles.length !== 1 ? 's' : ''} ready`;
  });

  renderReidDropZone('reid-mapping-drop', 'Drop mapping JSON here', files => {
    const file = files[0];
    if (!file) return;
    // Try to extract job ID from filename: mapping_<job-id>.json
    const m = file.name.match(/^mapping_(.+)\.json$/i);
    if (m) {
      const inp = document.getElementById('reid-job-id');
      if (inp && !inp.value) inp.value = m[1];
    }
    const reader = new FileReader();
    reader.onload = e => {
      try {
        reidMapping = JSON.parse(e.target.result);
        const count = Array.isArray(reidMapping) ? reidMapping.length : Object.keys(reidMapping).length;
        const zone = document.getElementById('reid-mapping-drop');
        if (zone) zone.querySelector('.drop-zone-main').textContent = `Mapping loaded: ${count} entries`;
        toast('Mapping file loaded', 'success');
      } catch {
        toast('Invalid JSON mapping file', 'error');
      }
    };
    reader.readAsText(file);
  });

  // Restore button
  document.getElementById('btn-restore')?.addEventListener('click', doReidentify);
});
