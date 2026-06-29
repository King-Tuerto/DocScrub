/**
 * DocScrub — processing + review screen logic
 *
 * Owns: SSE progress consumer, diff view renderer, mapping table,
 *       editable mapping entries, manual PII flagging.
 */
'use strict';

// ---------------------------------------------------------------------------
// SSE — stream anonymize
// ---------------------------------------------------------------------------

const STEP_LABELS = {
  extract:     'Extracting text…',
  llm_detect:  'LLM PII detection…',
  regex_detect:'Regex safety net…',
  map:         'Building mapping…',
  replace:     'Applying replacements…',
  done:        'Finalising…',
  complete:    'Complete ✓',
};

async function streamAnonymize(jobId) {
  return new Promise((resolve, reject) => {
    // EventSource only does GET; use fetch + ReadableStream for POST+SSE
    fetch(`/jobs/${jobId}/anonymize/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: DS.config.model,
        llm_endpoint: DS.config.llm_endpoint,
        tier: DS.config.tier || 'full',
        roster_id: DS.config.roster_id || null,
      }),
    })
      .then(resp => {
        if (!resp.ok) return reject(new Error(`${resp.status}`));

        const indicator = document.getElementById('step-indicator');
        const barsEl    = document.getElementById('progress-bars');
        const reader    = resp.body.getReader();
        const decoder   = new TextDecoder();
        let   buf       = '';
        let   pipelineWarnings = [];

        function read() {
          reader.read().then(({ done, value }) => {
            if (done) {
              loadReview(jobId)
                .then(() => {
                  pipelineWarnings.forEach(w => toast(`LLM warning: ${w}`, 'warn'));
                  resolve();
                })
                .catch(reject);
              return;
            }
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop();  // incomplete line

            lines.forEach(line => {
              if (!line.startsWith('data:')) return;
              try {
                const ev = JSON.parse(line.slice(5).trim());
                if (ev.step) {
                  const label = STEP_LABELS[ev.step] || ev.step;
                  if (indicator) indicator.textContent = label;
                  appendProgressStep(barsEl, label, ev.step === 'complete');
                }
                if (ev.warnings && ev.warnings.length) {
                  pipelineWarnings = ev.warnings;
                }
                if (ev.error) {
                  toast(`Pipeline error: ${ev.error}`, 'error');
                }
              } catch { /* partial JSON — ignore */ }
            });
            read();
          }).catch(reject);
        }
        read();
      })
      .catch(reject);
  });
}

function appendProgressStep(container, label, done = false) {
  if (!container) return;
  const row = document.createElement('div');
  row.className = `progress-step${done ? ' done' : ''}`;
  row.innerHTML = `<span class="step-dot">${done ? '✓' : '…'}</span> ${escHtml(label)}`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

// ---------------------------------------------------------------------------
// Load review data
// ---------------------------------------------------------------------------

async function loadReview(jobId) {
  const data = await API.get(`/jobs/${jobId}/review`);
  DS.fileResults = data.files || [];
  DS.mapping     = data.mapping || [];

  renderDiffView(DS.fileResults);
  renderMappingTable(DS.mapping);
  showScreen('screen-review');
}

// ---------------------------------------------------------------------------
// Diff view
// ---------------------------------------------------------------------------

const PII_COLORS = {
  PERSON:  '#fde68a', ORG:     '#bfdbfe', EMAIL:   '#bbf7d0',
  PHONE:   '#fecaca', ADDRESS: '#e9d5ff', SSN:     '#fed7aa',
  ACCOUNT: '#fbcfe8', ID:      '#a5f3fc', DOB:     '#d9f99d',
  OTHER:   '#e2e8f0',
};

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function highlightAnonymized(text, positions) {
  if (!positions || positions.length === 0) return escHtml(text);
  let out = '';
  let cursor = 0;
  // positions are already in output-string order
  const sorted = [...positions].sort((a, b) => a.start - b.start);
  sorted.forEach(pos => {
    out += escHtml(text.slice(cursor, pos.start));
    const color = PII_COLORS[pos.pii_type] || PII_COLORS.OTHER;
    const span = escHtml(text.slice(pos.start, pos.end));
    out += `<mark class="pii-mark" style="background:${color}" title="${escHtml(pos.pii_type)}">${span}</mark>`;
    cursor = pos.end;
  });
  out += escHtml(text.slice(cursor));
  return out;
}

let currentFileIdx = 0;

function renderDiffView(files) {
  if (!files.length) return;
  currentFileIdx = 0;
  renderFileTabs(files);
  showFileResult(files, 0);
}

function renderFileTabs(files) {
  const reviewEl = document.getElementById('screen-review');
  let tabBar = reviewEl.querySelector('.file-tabs');
  if (tabBar) tabBar.remove();

  if (files.length <= 1) return;

  tabBar = document.createElement('div');
  tabBar.className = 'file-tabs';
  files.forEach((f, i) => {
    const btn = document.createElement('button');
    btn.className = `tab-btn${i === 0 ? ' active' : ''}`;
    btn.textContent = f.filename;
    btn.dataset.idx = i;
    btn.addEventListener('click', () => {
      reviewEl.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFileIdx = i;
      showFileResult(files, i);
    });
    tabBar.appendChild(btn);
  });
  const reviewArea = document.getElementById('review-area');
  reviewArea.parentNode.insertBefore(tabBar, reviewArea);
}

function showFileResult(files, idx) {
  const f = files[idx];
  const origEl = document.getElementById('text-original');
  const anonEl = document.getElementById('text-anonymized');
  if (origEl) origEl.textContent = f.original_text || '';
  if (anonEl) anonEl.innerHTML = highlightAnonymized(f.anonymized_text || '', f.positions || []);
}

// ---------------------------------------------------------------------------
// Mapping table
// ---------------------------------------------------------------------------

function renderMappingTable(mapping) {
  const container = document.getElementById('mapping-table');
  if (!container) return;

  if (!mapping.length) {
    container.innerHTML = '<p class="empty-msg">No PII found.</p>';
    return;
  }

  const table = document.createElement('table');
  table.className = 'map-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th>Placeholder</th>
        <th>Original Value</th>
        <th>Type</th>
        <th>Source</th>
        <th></th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector('tbody');

  mapping.forEach(entry => {
    const tr = document.createElement('tr');
    tr.dataset.placeholder = entry.placeholder;
    tr.innerHTML = `
      <td><code>${escHtml(entry.placeholder)}</code></td>
      <td class="original-cell"><span class="orig-text">${escHtml(entry.original)}</span>
          <input class="orig-input" type="text" value="${escHtml(entry.original)}" hidden /></td>
      <td><span class="pii-badge" style="background:${PII_COLORS[entry.pii_type]||'#e2e8f0'}">${escHtml(entry.pii_type)}</span></td>
      <td>${escHtml(entry.source || '')}</td>
      <td>
        <button class="btn-edit" data-ph="${escHtml(entry.placeholder)}">Edit</button>
        <button class="btn-delete" data-ph="${escHtml(entry.placeholder)}">Delete</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  container.innerHTML = '';
  container.appendChild(table);

  // Attach edit handlers
  container.querySelectorAll('.btn-edit').forEach(btn => {
    btn.addEventListener('click', () => startEditEntry(btn.dataset.ph));
  });

  // Attach delete handlers
  container.querySelectorAll('.btn-delete').forEach(btn => {
    btn.addEventListener('click', () => deleteMapping(btn.dataset.ph));
  });
}

function startEditEntry(placeholder) {
  const row = document.querySelector(`tr[data-placeholder="${CSS.escape(placeholder)}"]`);
  if (!row) return;
  const span  = row.querySelector('.orig-text');
  const input = row.querySelector('.orig-input');
  const btn   = row.querySelector('.btn-edit');
  if (!span || !input || !btn) return;

  span.hidden = true;
  input.hidden = false;
  input.focus();
  btn.textContent = 'Save';

  btn.onclick = async () => {
    const newVal = input.value.trim();
    if (!newVal) return;
    try {
      await API.patch(`/jobs/${DS.jobId}/mapping/${encodeURIComponent(placeholder)}`, { original: newVal });
      span.textContent = newVal;
      input.value = newVal;
      span.hidden = false;
      input.hidden = true;
      btn.textContent = 'Edit';
      btn.onclick = () => startEditEntry(placeholder);
      // Update local state
      const entry = DS.mapping.find(e => e.placeholder === placeholder);
      if (entry) entry.original = newVal;
      toast('Mapping updated', 'success');
    } catch (err) {
      toast(`Save failed: ${err.message}`, 'error');
    }
  };
}

// ---------------------------------------------------------------------------
// Manual PII button
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btn-add-manual')?.addEventListener('click', addManualPII);
  document.getElementById('btn-export')?.addEventListener('click', () => showScreen('screen-export'));
  document.getElementById('btn-rerun')?.addEventListener('click', () => {
    openSettings();
    toast('Change the model in Settings, then re-scrub', 'info');
  });
});

async function addManualPII() {
  if (!DS.jobId) { toast('No active job', 'warn'); return; }
  const val = window.prompt('Enter text to redact:');
  if (!val?.trim()) return;
  const type = window.prompt('PII type (PERSON / EMAIL / PHONE / OTHER):', 'OTHER') || 'OTHER';
  try {
    const entry = await API.post(`/jobs/${DS.jobId}/mapping`, {
      text: val.trim(),
      pii_type: type.trim().toUpperCase(),
    });
    DS.mapping.push({
      id: entry.id,
      original: entry.original,
      placeholder: entry.placeholder,
      pii_type: entry.pii_type,
      source: entry.source,
    });
    renderMappingTable(DS.mapping);
    toast(`Added ${entry.placeholder} for "${entry.original}"`, 'success');
  } catch (err) {
    toast(`Failed to add PII: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Mapping delete
// ---------------------------------------------------------------------------

async function deleteMapping(placeholder) {
  if (!confirm(`Delete mapping for ${placeholder}? The original text will reappear in the preview.`)) return;
  try {
    await API.delete(`/jobs/${DS.jobId}/mapping/${encodeURIComponent(placeholder)}`);
    // Reload review data to reflect the revert
    const data = await API.get(`/jobs/${DS.jobId}/review`);
    DS.fileResults = data.files || [];
    DS.mapping     = data.mapping || [];
    renderDiffView(DS.fileResults);
    renderMappingTable(DS.mapping);
    toast(`Mapping deleted — original text restored`, 'success');
  } catch (err) {
    toast(`Delete failed: ${err.message}`, 'error');
  }
}

// Expose for upload.js
window.streamAnonymize = streamAnonymize;
window.loadReview = loadReview;
