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
  llm_detect:  'AI scanning for PII…',
  regex_detect:'Regex safety net…',
  map:         'Building mapping…',
  replace:     'Applying replacements…',
  done:        'Finalising…',
  complete:    'Complete ✓',
};

function _fmtEta(remainingMs) {
  const s = Math.round(remainingMs / 1000);
  if (s < 90)  return `~${s}s remaining`;
  const m = Math.round(s / 60);
  return `~${m} min remaining`;
}

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
        let   llmRow    = null;   // single row kept for chunk-level updates

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

                if (ev.step === 'llm_detect' && ev.chunk != null) {
                  // Chunk-level update — update existing row in place, never append
                  const remaining = ev.avg_ms != null
                    ? _fmtEta(ev.avg_ms * (ev.total - ev.chunk))
                    : null;
                  const label = `Processing chunk ${ev.chunk} of ${ev.total}${remaining ? ' · ' + remaining : ''}`;
                  if (indicator) indicator.textContent = label;
                  if (!llmRow) {
                    llmRow = appendProgressStep(barsEl, label, false);
                  } else {
                    const span = llmRow.querySelector('.step-label');
                    if (span) span.textContent = label;
                  }
                } else if (ev.step) {
                  const label = STEP_LABELS[ev.step] || ev.step;
                  if (indicator) indicator.textContent = label;
                  appendProgressStep(barsEl, label, ev.step === 'complete');
                  if (ev.step !== 'llm_detect') llmRow = null;
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
  if (!container) return null;
  const row = document.createElement('div');
  row.className = `progress-step${done ? ' done' : ''}`;
  row.innerHTML = `<span class="step-dot">${done ? '✓' : '…'}</span> <span class="step-label">${escHtml(label)}</span>`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  return row;
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
  DS.scrubDone = true;
  window.updateNavTabs?.();
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

// Pick the best display value from a group of entries sharing a placeholder.
// For PERSON: prefer Title Case "First Last" over initials or reversed forms.
// For other types: prefer the non-lowercase original.
function _canonicalOriginal(entries) {
  if (entries[0].pii_type === 'PERSON') {
    const titled = entries
      .filter(e => /^[A-Z]/.test(e.original) && e.original.includes(' ') && !/^\w\.\s/.test(e.original))
      .sort((a, b) => b.original.length - a.original.length);
    if (titled.length) return titled[0].original;
  }
  const notLower = entries.find(e => e.original !== e.original.toLowerCase());
  return (notLower || entries[0]).original;
}

// Count occurrences of a placeholder string across all file anonymized texts
function _countPlaceholder(placeholder) {
  const re = new RegExp(placeholder.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
  return DS.fileResults.reduce((acc, f) => {
    return acc + ((f.anonymized_text || '').match(re) || []).length;
  }, 0);
}

function renderMappingTable(mapping) {
  const container = document.getElementById('mapping-table');
  if (!container) return;

  if (!mapping.length) {
    container.innerHTML = '<p class="empty-msg">No PII found.</p>';
    return;
  }

  // Group entries by placeholder — one row per placeholder
  const groups = {};
  const order = [];
  mapping.forEach(entry => {
    if (!groups[entry.placeholder]) {
      groups[entry.placeholder] = [];
      order.push(entry.placeholder);
    }
    groups[entry.placeholder].push(entry);
  });

  const table = document.createElement('table');
  table.className = 'map-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th>Placeholder</th>
        <th>Original Value</th>
        <th>Type</th>
        <th>Count</th>
        <th>Source</th>
        <th></th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector('tbody');

  order.forEach(placeholder => {
    const entries = groups[placeholder];
    const canonical = _canonicalOriginal(entries);
    const piiType  = entries[0].pii_type;
    const source   = entries[0].source || '';
    const count    = _countPlaceholder(placeholder);

    const tr = document.createElement('tr');
    tr.dataset.placeholder = placeholder;
    tr.innerHTML = `
      <td><code>${escHtml(placeholder)}</code></td>
      <td class="original-cell"><span class="orig-text">${escHtml(canonical)}</span>
          <input class="orig-input" type="text" value="${escHtml(canonical)}" hidden /></td>
      <td><span class="pii-badge" style="background:${PII_COLORS[piiType]||'#e2e8f0'}">${escHtml(piiType)}</span></td>
      <td class="count-cell${count === 0 ? ' count-zero' : ''}" title="${count === 0 ? 'Not found in anonymized text' : `${count} replacement${count === 1 ? '' : 's'}`}">${count}</td>
      <td>${escHtml(source)}</td>
      <td>
        <button class="btn-edit" data-ph="${escHtml(placeholder)}">Edit</button>
        <button class="btn-delete" data-ph="${escHtml(placeholder)}">Delete</button>
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
      // Re-fetch review so anonymized text reflects the updated original value
      const data = await API.get(`/jobs/${DS.jobId}/review`);
      DS.fileResults = data.files || [];
      DS.mapping     = data.mapping || [];
      renderDiffView(DS.fileResults);
      renderMappingTable(DS.mapping);
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

  // Sync scroll between original and anonymized panels
  const origPre = document.getElementById('text-original');
  const anonPre = document.getElementById('text-anonymized');
  const syncCb  = document.getElementById('sync-scroll-cb');
  let _syncing  = false;

  function _makeScrollHandler(source, target) {
    return () => {
      if (!syncCb?.checked || _syncing) return;
      _syncing = true;
      target.scrollTop = source.scrollTop;
      _syncing = false;
    };
  }

  origPre?.addEventListener('scroll', _makeScrollHandler(origPre, anonPre));
  anonPre?.addEventListener('scroll', _makeScrollHandler(anonPre, origPre));
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
    // Re-fetch review so anonymized text reflects the new entry
    const data = await API.get(`/jobs/${DS.jobId}/review`);
    DS.fileResults = data.files || [];
    DS.mapping     = data.mapping || [];
    renderDiffView(DS.fileResults);
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
