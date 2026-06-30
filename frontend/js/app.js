/**
 * DocScrub — core app module
 *
 * Owns: global state, screen navigation, settings modal, API wrapper.
 * No framework dependencies — ES2020 vanilla JS.
 */
'use strict';

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------

window.DS = {
  jobId: null,
  scrubDone: false,   // true once anonymize completes; gates Review/Export tabs
  files: [],          // [{filename, size_bytes, file_type}]
  mapping: [],        // [{id, original, placeholder, pii_type, source}]
  fileResults: [],    // [{filename, original_text, anonymized_text, positions}]
  config: {
    llm_endpoint: 'http://localhost:11434',
    model: 'llama3.1:8b',
    tier: '',
    roster_id: null,
  },
};

// ---------------------------------------------------------------------------
// Screen navigation
// ---------------------------------------------------------------------------

const SCREENS = [
  'screen-upload',
  'screen-image-review',
  'screen-processing',
  'screen-review',
  'screen-export',
  'reidentify',
];

function showScreen(id) {
  SCREENS.forEach(sid => {
    const el = document.getElementById(sid);
    if (el) el.hidden = (sid !== id);
  });
  // Highlight the matching nav tab (if any)
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelector(`.nav-tab[data-screen="${id}"]`)?.classList.add('active');
  window.scrollTo(0, 0);
}

function updateNavTabs() {
  const enabled = DS.scrubDone;
  document.querySelectorAll('.nav-tab-job').forEach(t => {
    t.classList.toggle('nav-tab-disabled', !enabled);
  });
}

// ---------------------------------------------------------------------------
// API wrapper
// ---------------------------------------------------------------------------

const API = {
  base: '',

  async get(path) {
    const r = await fetch(this.base + path);
    if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
    return r.json();
  },

  async post(path, body) {
    const r = await fetch(this.base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
    return r.json();
  },

  async patch(path, body) {
    const r = await fetch(this.base + path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`PATCH ${path} → ${r.status}`);
    return r.json();
  },

  async delete(path) {
    const r = await fetch(this.base + path, { method: 'DELETE' });
    if (!r.ok && r.status !== 204) throw new Error(`DELETE ${path} → ${r.status}`);
    return r;
  },

  async postForm(path, formData) {
    const r = await fetch(this.base + path, { method: 'POST', body: formData });
    if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
    return r.json();
  },

  async getBlob(path) {
    const r = await fetch(this.base + path);
    if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
    return { blob: await r.blob(), headers: r.headers };
  },

  async postBlob(path, body) {
    const r = await fetch(this.base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
    return { blob: await r.blob(), headers: r.headers };
  },
};

// ---------------------------------------------------------------------------
// Notification toast
// ---------------------------------------------------------------------------

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ---------------------------------------------------------------------------
// Settings modal
// ---------------------------------------------------------------------------

async function loadModels() {
  const sel = document.getElementById('model-select');
  if (!sel) return;
  try {
    const data = await API.get('/models');
    sel.innerHTML = '';
    const models = data.models || [];
    if (models.length === 0) {
      const opt = document.createElement('option');
      opt.value = DS.config.model;
      opt.textContent = DS.config.model + ' (type to change)';
      sel.appendChild(opt);
    } else {
      models.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        if (name === DS.config.model) opt.selected = true;
        sel.appendChild(opt);
      });
    }
    if (data.error) toast('LLM not reachable — check Ollama is running', 'warn');
  } catch {
    sel.innerHTML = `<option value="${DS.config.model}">${DS.config.model}</option>`;
  }
}

function openSettings() {
  const modal = document.getElementById('settings-modal');
  const epInput = document.getElementById('llm-endpoint');
  if (epInput) epInput.value = DS.config.llm_endpoint;
  loadModels();
  modal.hidden = false;
}

function closeSettings() {
  document.getElementById('settings-modal').hidden = true;
}

function saveSettings() {
  const ep = document.getElementById('llm-endpoint')?.value?.trim();
  const model = document.getElementById('model-select')?.value?.trim();
  if (ep) DS.config.llm_endpoint = ep;
  if (model) DS.config.model = model;
  closeSettings();
  toast('Settings saved', 'success');
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  showScreen('screen-upload');
  updateNavTabs();   // start with Review/Export disabled

  // Nav: logo resets, tabs navigate
  document.getElementById('nav-home')?.addEventListener('click', e => {
    e.preventDefault();
    window.newJob?.();  // defined in export.js
  });
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', e => {
      e.preventDefault();
      if (tab.classList.contains('nav-tab-disabled')) return;
      const screen = tab.dataset.screen;
      if (screen === 'reidentify') {
        const inp = document.getElementById('reid-job-id');
        if (inp && DS.jobId) inp.value = DS.jobId;
      }
      if (screen === 'screen-export' && DS.scrubDone) {
        window.populateSummary?.();
      }
      showScreen(screen);
    });
  });

  document.getElementById('settings-btn')
    ?.addEventListener('click', openSettings);
  document.getElementById('btn-settings-cancel')
    ?.addEventListener('click', closeSettings);
  document.getElementById('btn-settings-save')
    ?.addEventListener('click', saveSettings);

  // Close modal on backdrop click
  document.getElementById('settings-modal')
    ?.addEventListener('click', e => {
      if (e.target === e.currentTarget) closeSettings();
    });
});

// Expose for other modules
window.showScreen = showScreen;
window.updateNavTabs = updateNavTabs;
window.API = API;
window.toast = toast;
