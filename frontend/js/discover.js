/**
 * DocScrub — Name Discovery mode
 *
 * Owns: discover screen drop zone, method picker, scan handler,
 *       results table with checkboxes, CSV generation, save-as-roster flow.
 */
'use strict';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _discFile     = null;
let _discFindings = [];   // [{text, pii_type, confidence, source, _checked}]
let _discFilename = '';

// ---------------------------------------------------------------------------
// Phase management: 'upload' | 'scanning' | 'results'
// ---------------------------------------------------------------------------

function _showDiscPhase(phase) {
  document.getElementById('discover-upload-phase').hidden   = (phase !== 'upload');
  document.getElementById('discover-scanning-phase').hidden = (phase !== 'scanning');
  document.getElementById('discover-results-phase').hidden  = (phase !== 'results');
}

// ---------------------------------------------------------------------------
// File selection
// ---------------------------------------------------------------------------

function _setDiscFile(file) {
  _discFile = file;
  const label = document.getElementById('discover-file-name');
  if (label) { label.textContent = `Selected: ${file.name}`; label.hidden = false; }
  document.getElementById('btn-discover-scan').disabled = false;
}

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------

async function _runScan() {
  if (!_discFile) return;
  _showDiscPhase('scanning');

  const method = document.querySelector('input[name="discover-method"]:checked')?.value || 'quick';
  const fd = new FormData();
  fd.append('file', _discFile, _discFile.name);
  fd.append('method', method);
  if (method === 'deep') {
    fd.append('llm_endpoint', DS.config.llm_endpoint || 'http://localhost:11434');
    fd.append('model', DS.config.model || 'llama3.1:8b');
  }

  try {
    const resp = await fetch('/discover', { method: 'POST', body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Server error ${resp.status}`);
    }
    const data = await resp.json();
    _discFilename = data.filename;
    _discFindings = data.findings.map(f => ({ ...f, _checked: true }));
    (data.warnings || []).forEach(w => toast(w, 'warn'));
    _renderDiscResults();
    _showDiscPhase('results');
  } catch (err) {
    toast(`Scan failed: ${err.message}`, 'error');
    _showDiscPhase('upload');
  }
}

// ---------------------------------------------------------------------------
// Results table
// ---------------------------------------------------------------------------

const _PII_COLORS = {
  PERSON: '#fde68a', ORG: '#bfdbfe', EMAIL: '#bbf7d0', PHONE: '#fecaca',
  ADDRESS: '#e9d5ff', SSN: '#fed7aa', ACCOUNT: '#fbcfe8', ID: '#a5f3fc',
  DOB: '#d9f99d', OTHER: '#e2e8f0',
};

function _esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _renderDiscResults() {
  const summary = document.getElementById('discover-summary');
  const wrap    = document.getElementById('discover-table-wrap');

  if (summary) {
    const n = _discFindings.length;
    summary.textContent = `${n} PII item${n === 1 ? '' : 's'} found in "${_discFilename}". Uncheck items to exclude from the name list.`;
  }

  if (!wrap) return;

  if (!_discFindings.length) {
    wrap.innerHTML = '<p class="empty-msg">No PII detected in this document.</p>';
    return;
  }

  const table = document.createElement('table');
  table.className = 'map-table disc-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th><input type="checkbox" id="disc-check-all" checked title="Toggle all" /></th>
        <th>Text</th>
        <th>Type</th>
        <th>Confidence</th>
        <th>Source</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector('tbody');

  _discFindings.forEach((f, i) => {
    const color = _PII_COLORS[f.pii_type] || '#e2e8f0';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="checkbox" class="disc-check" data-idx="${i}" ${f._checked ? 'checked' : ''} /></td>
      <td class="disc-text">${_esc(f.text)}</td>
      <td><span class="pii-badge" style="background:${color}">${_esc(f.pii_type)}</span></td>
      <td class="disc-confidence">${_esc(f.confidence)}</td>
      <td class="disc-source">${_esc(f.source || '')}</td>
    `;
    tr.querySelector('.disc-check').addEventListener('change', e => {
      _discFindings[i]._checked = e.target.checked;
      _syncHeaderCheckbox();
    });
    tbody.appendChild(tr);
  });

  wrap.innerHTML = '';
  wrap.appendChild(table);

  document.getElementById('disc-check-all').addEventListener('change', e => {
    const checked = e.target.checked;
    _discFindings.forEach((f, i) => { f._checked = checked; });
    wrap.querySelectorAll('.disc-check').forEach(cb => { cb.checked = checked; });
  });
}

function _syncHeaderCheckbox() {
  const allCb = document.getElementById('disc-check-all');
  if (!allCb) return;
  const all = _discFindings.length;
  const checked = _discFindings.filter(f => f._checked).length;
  allCb.indeterminate = checked > 0 && checked < all;
  allCb.checked = checked === all;
}

// ---------------------------------------------------------------------------
// CSV generation
// PERSON → first_name / last_name (split on first space; single word → first_name only)
// EMAIL  → email column
// other  → also_remove column
// ---------------------------------------------------------------------------

function _buildCsv() {
  const checked = _discFindings.filter(f => f._checked);
  if (!checked.length) return null;

  const rows = [['first_name', 'last_name', 'email', 'also_remove']];
  checked.forEach(f => {
    const row = ['', '', '', ''];
    if (f.pii_type === 'EMAIL') {
      row[2] = f.text;
    } else if (f.pii_type === 'PERSON') {
      const spaceIdx = f.text.indexOf(' ');
      if (spaceIdx === -1) {
        row[0] = f.text;          // single word → first_name (triggers exact-match fallback)
      } else {
        row[0] = f.text.slice(0, spaceIdx);
        row[1] = f.text.slice(spaceIdx + 1);
      }
    } else {
      row[3] = f.text;
    }
    rows.push(row);
  });

  return rows.map(row =>
    row.map(cell => {
      if (/[,"\n\r]/.test(cell)) return '"' + cell.replace(/"/g, '""') + '"';
      return cell;
    }).join(',')
  ).join('\r\n') + '\r\n';
}

function _downloadCsv() {
  const csv = _buildCsv();
  if (!csv) { toast('No items selected', 'warn'); return; }
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `namelist_${_discFilename.replace(/\.[^.]+$/, '')}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

// ---------------------------------------------------------------------------
// Save as name list → POST /rosters + POST /rosters/{id}/entries
// ---------------------------------------------------------------------------

async function _saveAsNameList() {
  const csv = _buildCsv();
  if (!csv) { toast('No items selected', 'warn'); return; }

  const btn = document.getElementById('btn-disc-save');
  btn.disabled = true;
  btn.textContent = 'Saving…';

  try {
    const name = `Discovered from ${_discFilename}`;
    const roster = await API.post('/rosters', { name });

    const fd = new FormData();
    fd.append('file', new Blob([csv], { type: 'text/csv' }), 'discovered.csv');
    const resp = await fetch(`/rosters/${roster.id}/entries`, { method: 'POST', body: fd });
    if (!resp.ok) throw new Error(`Upload failed: ${resp.status}`);
    const result = await resp.json();

    toast(`Saved "${name}" — ${result.count} entries`, 'success');
    // Refresh the roster dropdown on the upload screen and pre-select the new list
    await window.loadRosters?.(roster.id);
    DS.config.roster_id = roster.id;
    showScreen('screen-upload');
  } catch (err) {
    toast(`Save failed: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save as Name List';
  }
}

// ---------------------------------------------------------------------------
// Reset discover screen back to upload phase
// ---------------------------------------------------------------------------

function _resetDiscover() {
  _discFile     = null;
  _discFindings = [];
  _discFilename = '';
  const label = document.getElementById('discover-file-name');
  if (label) { label.textContent = ''; label.hidden = true; }
  const scanBtn = document.getElementById('btn-discover-scan');
  if (scanBtn) scanBtn.disabled = true;
  const wrap = document.getElementById('discover-table-wrap');
  if (wrap) wrap.innerHTML = '';
  _showDiscPhase('upload');
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  // Entry point button on the upload screen
  document.getElementById('btn-discover-mode')?.addEventListener('click', () => {
    _resetDiscover();
    showScreen('screen-discover');
  });

  // Drop zone
  const dropZone  = document.getElementById('discover-drop');
  const fileInput = document.getElementById('discover-file-input');

  dropZone?.addEventListener('dragover', e => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });
  dropZone?.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone?.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) _setDiscFile(file);
  });
  dropZone?.addEventListener('click', e => {
    if (!e.target.closest('label')) fileInput?.click();
  });
  fileInput?.addEventListener('change', () => {
    if (fileInput.files[0]) _setDiscFile(fileInput.files[0]);
    fileInput.value = '';
  });

  // Scan + cancel buttons
  document.getElementById('btn-discover-scan')?.addEventListener('click', _runScan);
  document.getElementById('btn-discover-cancel')?.addEventListener('click', () => showScreen('screen-upload'));

  // Results action buttons
  document.getElementById('btn-disc-save')?.addEventListener('click', _saveAsNameList);
  document.getElementById('btn-disc-csv')?.addEventListener('click', _downloadCsv);
  document.getElementById('btn-disc-rescan')?.addEventListener('click', _resetDiscover);

  document.getElementById('btn-disc-select-all')?.addEventListener('click', () => {
    _discFindings.forEach(f => { f._checked = true; });
    document.querySelectorAll('.disc-check').forEach(cb => { cb.checked = true; });
    const allCb = document.getElementById('disc-check-all');
    if (allCb) { allCb.checked = true; allCb.indeterminate = false; }
  });
  document.getElementById('btn-disc-deselect-all')?.addEventListener('click', () => {
    _discFindings.forEach(f => { f._checked = false; });
    document.querySelectorAll('.disc-check').forEach(cb => { cb.checked = false; });
    const allCb = document.getElementById('disc-check-all');
    if (allCb) { allCb.checked = false; allCb.indeterminate = false; }
  });
});
