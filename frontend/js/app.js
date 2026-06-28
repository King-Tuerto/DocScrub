/* DocScrub — main app logic (Piece 9) */
'use strict';

const API = {
  base: '',
  async get(path) { return fetch(this.base + path); },
  async post(path, body) {
    return fetch(this.base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },
};

// Screen navigation
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.hidden = true);
  const target = document.getElementById(id);
  if (target) target.hidden = false;
}

document.addEventListener('DOMContentLoaded', () => {
  showScreen('screen-upload');

  document.getElementById('settings-btn')?.addEventListener('click', () => {
    document.getElementById('settings-modal').hidden = false;
  });
  document.getElementById('btn-settings-cancel')?.addEventListener('click', () => {
    document.getElementById('settings-modal').hidden = true;
  });
});
