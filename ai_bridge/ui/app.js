/* AI Bridge – app.js */
'use strict';

// ── Icons ─────────────────────────────────────────────────────────────────────

const ICONS = {
  claude_code: `<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="20" cy="20" r="20" fill="#1a1a2e"/>
    <g transform="translate(20,20)">
      <circle cx="0" cy="-8" r="2.2" fill="#e07b39"/>
      <circle cx="6.93" cy="-4" r="2.2" fill="#e07b39"/>
      <circle cx="6.93" cy="4" r="2.2" fill="#e07b39"/>
      <circle cx="0" cy="8" r="2.2" fill="#e07b39"/>
      <circle cx="-6.93" cy="4" r="2.2" fill="#e07b39"/>
      <circle cx="-6.93" cy="-4" r="2.2" fill="#e07b39"/>
    </g>
  </svg>`,

  claude_desktop: `<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="20" cy="20" r="20" fill="#1a1a2e"/>
    <g transform="translate(20,20)">
      <circle cx="0" cy="-8" r="2.2" fill="#e07b39"/>
      <circle cx="6.93" cy="-4" r="2.2" fill="#e07b39"/>
      <circle cx="6.93" cy="4" r="2.2" fill="#e07b39"/>
      <circle cx="0" cy="8" r="2.2" fill="#e07b39"/>
      <circle cx="-6.93" cy="4" r="2.2" fill="#e07b39"/>
      <circle cx="-6.93" cy="-4" r="2.2" fill="#e07b39"/>
    </g>
    <rect x="12" y="30" width="16" height="2" rx="1" fill="#e07b39" opacity="0.6"/>
  </svg>`,

  codex: `<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="20" cy="20" r="20" fill="#1a1a2e"/>
    <path d="M27 14 A9 9 0 1 0 27 26" stroke="#06b6d4" stroke-width="3" stroke-linecap="round" fill="none"/>
    <line x1="14" y1="20" x2="26" y2="20" stroke="#06b6d4" stroke-width="2" stroke-linecap="round"/>
  </svg>`,

  bridge: `<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="20" cy="20" r="20" fill="#0f1729"/>
    <circle cx="14" cy="20" r="3.5" fill="#06b6d4"/>
    <circle cx="26" cy="20" r="3.5" fill="#06b6d4"/>
    <rect x="17" y="18.5" width="6" height="3" rx="1.5" fill="#06b6d4"/>
    <path d="M14 20 L14 14 M26 20 L26 14 M10 14 L30 14" stroke="#06b6d4" stroke-width="1.8" stroke-linecap="round"/>
  </svg>`,
};

// ── State ─────────────────────────────────────────────────────────────────────

let _state = { ok: false, providers: [], targets: [], proxy_running: false, port: null };
let _currentScreen = 'home';
let _currentTarget = null;
let _refreshTimer = null;
let _editingProvider = null;

// ── Pywebview bridge ───────────────────────────────────────────────────────────

async function api(method, ...args) {
  try {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api[method] === 'function') {
      return await window.pywebview.api[method](...args);
    }
  } catch (e) {
    console.error('api error', method, e);
  }
  return null;
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function toast(msg, type = 'info') {
  const container = document.getElementById('ab-toasts');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `ab-toast ab-toast--${type}`;
  el.textContent = msg;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add('ab-toast--visible'));
  setTimeout(() => {
    el.classList.remove('ab-toast--visible');
    setTimeout(() => el.remove(), 300);
  }, 3000);
}

// ── Navigation ────────────────────────────────────────────────────────────────

function go(screen, extra) {
  document.querySelectorAll('.ab-screen').forEach(s => s.hidden = true);
  const el = document.querySelector(`[data-screen="${screen}"]`);
  if (!el) return;
  el.hidden = false;
  _currentScreen = screen;

  if (screen === 'home') renderHome();
  else if (screen === 'target') { _currentTarget = extra; renderTarget(extra); }
  else if (screen === 'providers') renderProviders();
  else if (screen === 'add') { _editingProvider = extra || null; renderAdd(extra); }
}

// ── Render: Home ──────────────────────────────────────────────────────────────

function renderHome() {
  const provCount = _state.providers ? _state.providers.length : 0;
  const badge = document.getElementById('home-provider-count');
  if (badge) badge.textContent = provCount > 0 ? provCount : '';

  const container = document.getElementById('target-cards');
  if (!container) return;

  const targets = _state.targets || [];
  if (targets.length === 0) {
    container.innerHTML = '<div class="ab-empty">Carregando alvos…</div>';
    return;
  }

  container.innerHTML = targets.map(t => {
    let dotClass = 'ab-target-card__dot';
    let statusLabel = '';
    if (t.connected) { dotClass += ' ab-target-card__dot--connected'; statusLabel = 'Conectado'; }
    else if (t.installed) { dotClass += ' ab-target-card__dot--available'; statusLabel = 'Instalado'; }
    else { dotClass += ' ab-target-card__dot--unavailable'; statusLabel = 'Não instalado'; }

    const icon = ICONS[t.id] || ICONS.bridge;

    return `<button class="ab-target-card" data-target="${t.id}">
      <div class="ab-target-card__icon">${icon}</div>
      <div class="ab-target-card__body">
        <div class="ab-target-card__name">${t.name}</div>
        <div class="ab-target-card__desc">${t.desc || ''}</div>
      </div>
      <div class="ab-target-card__status">
        <span class="${dotClass}"></span>
        <span class="ab-target-card__status-label">${statusLabel}</span>
      </div>
    </button>`;
  }).join('');

  container.querySelectorAll('.ab-target-card').forEach(card => {
    card.addEventListener('click', () => go('target', card.dataset.target));
  });
}

// ── Render: Target detail ─────────────────────────────────────────────────────

function renderTarget(key) {
  const targets = _state.targets || [];
  const t = targets.find(x => x.id === key);
  if (!t) { go('home'); return; }

  const hasProvider = _state.providers && _state.providers.length > 0;

  // Icons
  const iconLeft = document.getElementById('target-icon-left');
  const iconRight = document.getElementById('target-icon-right');
  if (iconLeft) iconLeft.innerHTML = ICONS[t.id] || ICONS.bridge;
  if (iconRight) iconRight.innerHTML = ICONS.bridge;

  // Title / desc
  const titleEl = document.getElementById('target-title');
  const descEl = document.getElementById('target-desc');
  if (titleEl) titleEl.textContent = t.name;
  if (descEl) descEl.textContent = t.desc || '';

  // Connection line
  const connLine = document.getElementById('target-conn-line');
  if (connLine) {
    connLine.classList.toggle('ab-conn-bridge--active', t.connected);
  }

  // Status
  const statusEl = document.getElementById('target-conn-status');
  if (statusEl) {
    if (!t.installed) statusEl.textContent = 'Não instalado neste sistema';
    else if (t.connected) statusEl.textContent = 'Conectado via AI Bridge';
    else statusEl.textContent = 'Usando provedor original';
  }

  // Pill toggle
  const pillBridge = document.getElementById('pill-bridge');
  const pillOriginal = document.getElementById('pill-original');
  if (pillBridge && pillOriginal) {
    pillBridge.classList.toggle('ab-pill-btn--active', t.connected);
    pillOriginal.classList.toggle('ab-pill-btn--active', !t.connected);
  }

  // No provider warning
  const noProv = document.getElementById('target-no-provider');
  if (noProv) noProv.hidden = hasProvider;
}

// ── Render: Providers list ────────────────────────────────────────────────────

function renderProviders() {
  const container = document.getElementById('provider-list-screen');
  if (!container) return;

  const providers = _state.providers || [];
  if (providers.length === 0) {
    container.innerHTML = '<div class="ab-empty">Nenhum provedor configurado.</div>';
    return;
  }

  container.innerHTML = providers.map(p => {
    const modelCount = (p.models || []).length;
    return `<div class="ab-provider-item">
      <div class="ab-provider-item__info">
        <div class="ab-provider-item__name">${escHtml(p.name)}</div>
        <div class="ab-provider-item__sub">${escHtml(p.base_url || '')}${modelCount ? ` · ${modelCount} modelo${modelCount !== 1 ? 's' : ''}` : ''}</div>
      </div>
      <div class="ab-provider-item__actions">
        <button class="btn btn-ghost btn-sm" data-edit="${escHtml(p.name)}">Editar</button>
        <button class="btn btn-ghost btn-sm ab-btn-danger" data-remove="${escHtml(p.name)}">Remover</button>
      </div>
    </div>`;
  }).join('');

  container.querySelectorAll('[data-edit]').forEach(btn => {
    btn.addEventListener('click', () => go('add', btn.dataset.edit));
  });
  container.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const name = btn.dataset.remove;
      const res = await api('remove_provider', name);
      if (res && res.ok) {
        toast(`Provedor "${name}" removido.`);
        await refresh();
        renderProviders();
      } else {
        toast(res?.error || 'Erro ao remover.', 'error');
      }
    });
  });
}

// ── Render: Add/Edit provider ─────────────────────────────────────────────────

async function renderAdd(editName) {
  const titleEl = document.getElementById('add-screen-title');
  const saveLabel = document.getElementById('save-label');
  if (titleEl) titleEl.textContent = editName ? 'Editar Provedor' : 'Novo Provedor';
  if (saveLabel) saveLabel.textContent = editName ? 'Salvar alterações' : 'Salvar Provedor';

  // Reset form
  const form = document.getElementById('add-form');
  if (form) form.reset();
  const testResult = document.getElementById('test-result');
  if (testResult) { testResult.hidden = true; testResult.textContent = ''; }

  // Load presets
  const presetList = document.getElementById('preset-list');
  if (presetList) {
    const res = await api('get_presets');
    const presets = (res && res.presets) ? res.presets : [];
    presetList.innerHTML = presets.map(p =>
      `<button type="button" class="ab-preset-btn" data-preset="${escHtml(p.name)}">
        <span class="ab-preset-btn__name">${escHtml(p.name)}</span>
      </button>`
    ).join('');
    presetList.querySelectorAll('.ab-preset-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const pname = btn.dataset.preset;
        const pres = (res.presets || []).find(x => x.name === pname);
        if (!pres) return;
        const fName = document.getElementById('f-name');
        const fUrl = document.getElementById('f-url');
        const fModels = document.getElementById('f-models');
        if (fName && !fName.value) fName.value = pres.name;
        if (fUrl) fUrl.value = pres.base_url || '';
        if (fModels) fModels.value = (pres.models || []).map(m =>
          typeof m === 'string' ? m : `${m.id}|${m.name}`
        ).join('\n');
      });
    });
  }

  // Load existing provider data for editing
  if (editName) {
    const detail = await api('get_provider_detail', editName);
    if (detail && detail.ok) {
      const fName = document.getElementById('f-name');
      const fUrl = document.getElementById('f-url');
      const fKey = document.getElementById('f-key');
      const fModels = document.getElementById('f-models');
      if (fName) fName.value = detail.name || editName;
      if (fUrl) fUrl.value = detail.base_url || '';
      if (fKey) fKey.value = detail.api_key || '';
      if (fModels) fModels.value = (detail.models || []).map(m =>
        typeof m === 'string' ? m : `${m.id}|${m.name}`
      ).join('\n');
    }
  }
}

// ── State refresh ─────────────────────────────────────────────────────────────

async function refresh() {
  const res = await api('state');
  if (res) _state = res;
}

async function tickRefresh() {
  await refresh();
  if (_currentScreen === 'home') renderHome();
  else if (_currentScreen === 'target' && _currentTarget) renderTarget(_currentTarget);
}

function startAutoRefresh() {
  _refreshTimer = setInterval(tickRefresh, 3000);
}

// ── Utility ───────────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Wire up static controls ───────────────────────────────────────────────────

function wireControls() {
  // Window controls
  document.getElementById('btn-minimize')?.addEventListener('click', () => {
    window.pywebview?.api?.minimize?.() ?? window.pywebview?.minimize?.();
  });
  document.getElementById('btn-close')?.addEventListener('click', () => {
    window.pywebview?.api?.close_to_tray?.() ?? window.pywebview?.close_to_tray?.();
  });

  // Home: providers button
  document.getElementById('btn-providers')?.addEventListener('click', () => go('providers'));

  // Target back
  document.getElementById('btn-back-target')?.addEventListener('click', () => go('home'));

  // Providers back + add
  document.getElementById('btn-back-providers')?.addEventListener('click', () => go('home'));
  document.getElementById('btn-add-from-providers')?.addEventListener('click', () => go('add'));

  // Add/Edit back + cancel
  document.getElementById('btn-back-add')?.addEventListener('click', () =>
    go(_editingProvider ? 'providers' : 'providers'));
  document.getElementById('btn-cancel')?.addEventListener('click', () =>
    go('providers'));

  // Pill toggle (connect / disconnect)
  document.getElementById('pill-bridge')?.addEventListener('click', async () => {
    if (!_currentTarget) return;
    const t = (_state.targets || []).find(x => x.id === _currentTarget);
    if (t && t.connected) return; // already connected
    const hasProvider = _state.providers && _state.providers.length > 0;
    if (!hasProvider) { toast('Adicione um provedor primeiro.', 'error'); return; }
    const res = await api('connect_target', _currentTarget);
    if (res && res.ok) {
      toast('Conectado ao AI Bridge!', 'success');
      await refresh();
      renderTarget(_currentTarget);
    } else {
      toast(res?.error || 'Falha ao conectar.', 'error');
    }
  });

  document.getElementById('pill-original')?.addEventListener('click', async () => {
    if (!_currentTarget) return;
    const t = (_state.targets || []).find(x => x.id === _currentTarget);
    if (t && !t.connected) return; // already disconnected
    const res = await api('disconnect_target', _currentTarget);
    if (res && res.ok) {
      toast('Desconectado — usando provedor original.', 'info');
      await refresh();
      renderTarget(_currentTarget);
    } else {
      toast(res?.error || 'Falha ao desconectar.', 'error');
    }
  });

  // Go to providers from target screen
  document.getElementById('btn-go-providers-from-target')?.addEventListener('click', () => go('providers'));

  // Show/hide API key
  document.getElementById('btn-show-key')?.addEventListener('click', () => {
    const input = document.getElementById('f-key');
    if (!input) return;
    const isHidden = input.type === 'password';
    input.type = isHidden ? 'text' : 'password';
    document.getElementById('btn-show-key').textContent = isHidden ? 'Ocultar' : 'Mostrar';
  });

  // Test connection
  document.getElementById('btn-test')?.addEventListener('click', async () => {
    const url = document.getElementById('f-url')?.value?.trim();
    const key = document.getElementById('f-key')?.value?.trim();
    const btn = document.getElementById('btn-test');
    const resultEl = document.getElementById('test-result');
    if (!url || !key) { toast('Preencha URL e chave antes de testar.', 'error'); return; }
    if (btn) { btn.textContent = '…'; btn.disabled = true; }
    const res = await api('test_provider', url, key);
    if (btn) { btn.textContent = 'Testar'; btn.disabled = false; }
    if (resultEl) {
      resultEl.hidden = false;
      if (res && res.ok) {
        resultEl.className = 'ab-test-ok';
        resultEl.textContent = `✓ Conexão OK — ${res.models_count ?? '?'} modelo(s)`;
      } else {
        resultEl.className = 'ab-test-error';
        resultEl.textContent = `✗ ${res?.error || 'Falha na conexão'}`;
      }
    }
  });

  // Save provider form
  document.getElementById('add-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('f-name')?.value?.trim();
    const url = document.getElementById('f-url')?.value?.trim();
    const key = document.getElementById('f-key')?.value?.trim();
    const models = document.getElementById('f-models')?.value?.trim();
    if (!name || !url || !key) return;

    const saveBtn = document.getElementById('btn-save');
    if (saveBtn) saveBtn.disabled = true;

    const res = await api('add_provider', name, url, key, models);

    if (saveBtn) saveBtn.disabled = false;

    if (res && res.ok) {
      toast(`Provedor "${name}" salvo.`, 'success');
      await refresh();
      go('providers');
    } else {
      toast(res?.error || 'Erro ao salvar.', 'error');
    }
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function boot() {
  wireControls();
  await refresh();
  go('home');
  startAutoRefresh();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    // pywebview fires window.addEventListener('pywebviewready') when the API is ready
    window.addEventListener('pywebviewready', boot, { once: true });
    // Fallback for dev: if pywebview not present, boot after 300ms
    setTimeout(() => {
      if (!window.pywebview) boot();
    }, 300);
  });
} else {
  window.addEventListener('pywebviewready', boot, { once: true });
  setTimeout(() => { if (!window.pywebview) boot(); }, 300);
}
