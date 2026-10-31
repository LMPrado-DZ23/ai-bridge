/* AI Bridge – app.js */
'use strict';

// ── Icons ─────────────────────────────────────────────────────────────────────

const ICONS = {
  claude_code:    `<img src="assets/icons/claude-mark.png" class="ab-brand-mark ab-brand-mark--claude" alt="Claude Code">`,
  claude_desktop: `<img src="assets/icons/claude-mark.png" class="ab-brand-mark ab-brand-mark--claude" alt="Claude Desktop">`,
  codex:          `<img src="assets/icons/codex-mark.png" class="ab-brand-mark ab-brand-mark--codex" alt="Codex">`,
  bridge:         `<img src="assets/icons/bridge-mark.svg" class="ab-brand-mark ab-brand-mark--bridge" alt="AI Bridge">`,
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
    if (t.connected && t.id === 'claude_desktop') { dotClass += ' ab-target-card__dot--available'; statusLabel = 'Conectado via AI Bridge'; }
    else if (t.connected) { dotClass += ' ab-target-card__dot--connected'; statusLabel = 'Conectado'; }
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
    connLine.classList.toggle('ab-conn-bridge--active', t.mode === 'bridge' || (t.mode == null && t.connected));
  }

  // Status
  const statusEl = document.getElementById('target-conn-status');
  if (statusEl) {
    if (!t.installed) statusEl.textContent = 'Não instalado neste sistema';
    else if (t.id === 'claude_desktop' && t.mode === 'bridge') {
      const available = (_state.models || []).slice(0, 3).map(m => m.label).join(' · ');
      statusEl.textContent = available
        ? 'AI Bridge configurado · modelos disponíveis: ' + available
        : 'AI Bridge configurado, mas nenhum modelo está disponível.';
    }
    else if (t.id === 'claude_desktop' && t.mode === 'external') statusEl.textContent = 'Outro gateway está ativo. Escolha AI Bridge ou Provedor padrão.';
    else if (t.connected && t.id === 'codex') statusEl.textContent = 'Conectado via AI Bridge · modelo padrão: ' + (_state.active_model_label || 'não selecionado');
    else if (t.connected) statusEl.textContent = 'Conectado via AI Bridge';
    else statusEl.textContent = 'Usando provedor original';
  }

  // Pill toggle
  const pillBridge = document.getElementById('pill-bridge');
  const pillOriginal = document.getElementById('pill-original');
  if (pillBridge && pillOriginal) {
    const bridgeActive = t.mode ? t.mode === 'bridge' : !!t.connected;
    const originalActive = t.mode ? t.mode === 'original' : !t.connected;
    pillBridge.classList.toggle('ab-pill-btn--active', bridgeActive);
    pillOriginal.classList.toggle('ab-pill-btn--active', originalActive);
  }

  // Codex default model selection. This changes only the default model, not login/auth.
  const modelWrap = document.getElementById('target-model-select-wrap');
  const modelSelect = document.getElementById('target-model-select');
  if (modelWrap) modelWrap.hidden = t.id !== 'codex';
  if (modelSelect && t.id === 'codex') {
    const models = _state.models || [];
    modelSelect.innerHTML = models.length
      ? models.map(m => '<option value="' + escHtml(m.value) + '">' + escHtml(m.label) + '</option>').join('')
      : '<option value="">Nenhum modelo configurado</option>';
    modelSelect.value = _state.active_model || (models[0]?.value || '');
    modelSelect.disabled = models.length === 0;
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
    const auth = p.auth || { kind: 'api_key' };
    const authLabel = auth.kind === 'oauth'
      ? `OAuth · ${escHtml(auth.source || '')}${auth.connected ? ' ✓' : ' — sem sessão'}`
      : 'API key';
    const loginBtn = (auth.kind === 'oauth' && !auth.connected)
      ? `<button class="btn btn-ghost btn-sm" data-login="${escHtml(p.name)}">Entrar</button>` : '';
    const reauthBtn = (auth.kind === 'oauth' && auth.connected)
      ? `<button class="btn btn-ghost btn-sm" data-reauth="${escHtml(p.name)}">Reautenticar</button>` : '';
    return `<div class="ab-provider-item">
      <div class="ab-provider-item__info">
        <div class="ab-provider-item__name">${escHtml(p.name)}</div>
        <div class="ab-provider-item__sub">${escHtml(p.base_url || '')}${modelCount ? ` · ${modelCount} modelo${modelCount !== 1 ? 's' : ''}` : ''} · ${authLabel}</div>
      </div>
      <div class="ab-provider-item__actions">
        ${loginBtn}
        ${reauthBtn}
        <button class="btn btn-ghost btn-sm" data-edit="${escHtml(p.name)}">Editar</button>
        <button class="btn btn-ghost btn-sm ab-btn-danger" data-remove="${escHtml(p.name)}">Remover</button>
      </div>
    </div>`;
  }).join('');

  container.querySelectorAll('[data-login]').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      const res = await api('get_oauth_login_url', btn.dataset.login);
      btn.disabled = false;
      if (res && res.ok) toast('Login aberto no navegador. Conclua e volte ao AI Bridge.', 'success');
      else toast(res?.error || 'Não foi possível iniciar o login.', 'error');
    });
  });

  container.querySelectorAll('[data-reauth]').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      const res = await api('reauth_oauth', btn.dataset.reauth);
      btn.disabled = false;
      if (res && res.ok && res.renewed) toast('Sessão renovada.', 'success');
      else if (res && res.ok && res.url) toast('Sessão expirada — login aberto no navegador.', 'info');
      else toast(res?.error || 'Falha ao reautenticar.', 'error');
      await refresh();
      renderProviders();
    });
  });

  container.querySelectorAll('[data-edit]').forEach(btn => {
    btn.addEventListener('click', () => go('add', btn.dataset.edit));
  });
  container.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.dataset.remove;
      const item = btn.closest('.ab-provider-item');
      if (!item) return;
      const existing = item.querySelector('.ab-confirm');
      if (existing) { existing.remove(); return; }
      const confirm = document.createElement('div');
      confirm.className = 'ab-confirm';
      confirm.innerHTML = `<span class="ab-confirm__msg">Remover "${escHtml(name)}"?</span>
        <button class="ab-confirm__yes btn btn-ghost btn-sm ab-btn-danger" type="button">Remover</button>
        <button class="ab-confirm__no btn btn-ghost btn-sm" type="button">Cancelar</button>`;
      item.appendChild(confirm);
      confirm.querySelector('.ab-confirm__no').addEventListener('click', () => confirm.remove());
      confirm.querySelector('.ab-confirm__yes').addEventListener('click', async () => {
        confirm.remove();
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
  });
}

// ── Render: Add/Edit provider ─────────────────────────────────────────────────

async function renderAdd(editName) {
  const titleEl = document.getElementById('add-screen-title');
  const saveLabel = document.getElementById('save-label');
  if (titleEl) titleEl.textContent = editName ? 'Editar Provedor' : 'Novo Provedor';
  if (saveLabel) saveLabel.classList.add('hidden');

  // Reset form
  const form = document.getElementById('add-form');
  if (form) form.reset();
  const testResult = document.getElementById('test-result');
  if (testResult) { testResult.hidden = true; testResult.textContent = ''; }
  syncAuthUi(null);

  // Catálogo de provedores (menu "Escolha o provedor")
  const catalogEl = document.getElementById('provider-catalog');
  if (catalogEl) {
    const res = await api('get_catalog');
    const entries = (res && res.catalog) ? res.catalog : [];
    const groups = [
      ['oauth', 'Assinaturas (OAuth)'],
      ['api_key', 'API key'],
      ['custom', 'Personalizado'],
    ];
    const badge = (entry) => entry.kind === 'oauth'
      ? (entry.source || 'oauth')
      : entry.kind === 'custom' ? 'custom' : 'api key';
    const render = (filter = '') => {
      const q = filter.trim().toLowerCase();
      catalogEl.innerHTML = groups.map(([kind, title]) => {
        const items = entries.filter(e => e.kind === kind && (
          !q || `${e.label} ${e.description} ${e.source || ''}`.toLowerCase().includes(q)
        ));
        if (!items.length) return '';
        return `<div class="ab-catalog__group">${title}</div>` + items.map(e =>
          `<button type="button" class="ab-catalog__item" data-entry="${escHtml(e.id)}">
             <span class="ab-catalog__label">${escHtml(e.label)}</span>
             <span class="ab-catalog__badge ab-catalog__badge--${e.kind}">${escHtml(badge(e))}</span>
             <span class="ab-catalog__desc">${escHtml(e.description || '')}</span>
           </button>`).join('');
      }).join('');
      catalogEl.querySelectorAll('[data-entry]').forEach(btn => {
        btn.addEventListener('click', () => applyCatalogEntry(entries.find(e => e.id === btn.dataset.entry)));
      });
    };
    render();
    const search = document.getElementById('catalog-search');
    if (search) search.oninput = () => render(search.value);
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
      if (fKey) {
        fKey.value = '';
        if (detail.has_key) {
          fKey.placeholder = '••••••••';
          if (saveLabel) saveLabel.classList.remove('hidden');
        }
      }
      if (fModels) fModels.value = detail.models_raw || (detail.models || []).map(m =>
        typeof m === 'string' ? m : `${m.id}|${m.label || m.name || m.id}`
      ).join('\n');
      const fProtocol = document.getElementById('f-protocol');
      if (fProtocol) fProtocol.value = detail.protocol || '';
      const fEnvKey = document.getElementById('f-env-key');
      if (fEnvKey) fEnvKey.value = detail.env_key || '';
      syncAuthUi({ ...(detail.auth || { kind: 'api_key' }), status: detail.auth_status });
    }
  }
}

// ── OAuth helpers ────────────────────────────────────────────────────────────

function currentAuth() {
  const kind = document.getElementById('f-auth-kind')?.value || 'api_key';
  if (kind !== 'oauth') return null;
  return { kind: 'oauth', source: document.getElementById('f-oauth-source')?.value || 'codex' };
}

function syncAuthUi(auth) {
  const kind = (auth && auth.kind === 'oauth') ? 'oauth' : 'api_key';
  const kindSel = document.getElementById('f-auth-kind');
  if (kindSel) kindSel.value = kind;
  if (auth && auth.source) {
    const srcSel = document.getElementById('f-oauth-source');
    if (srcSel) srcSel.value = auth.source;
  }
  document.getElementById('f-key-row')?.classList.toggle('hidden', kind === 'oauth');
  document.getElementById('f-oauth-row')?.classList.toggle('hidden', kind !== 'oauth');
  const statusEl = document.getElementById('oauth-status');
  if (statusEl) {
    const st = auth && auth.status;
    if (kind !== 'oauth') statusEl.textContent = '';
    else if (st && st.connected) statusEl.textContent = `Sessão encontrada (${st.source})${st.expired ? ' — expirada, será renovada' : ''}`;
    else statusEl.textContent = 'Sem sessão — use “Entrar com…” ou faça login na CLI.';
  }
}

function applyCatalogEntry(entry) {
  if (!entry) return;
  if (entry.kind === 'oauth') syncAuthUi({ kind: 'oauth', source: entry.source });
  else syncAuthUi({ kind: 'api_key' });
  const name = document.getElementById('f-name');
  const url = document.getElementById('f-url');
  const models = document.getElementById('f-models');
  const protocol = document.getElementById('f-protocol');
  if (name) name.value = entry.kind === 'custom' ? '' : entry.label;
  if (url) url.value = entry.base_url || '';
  if (models) models.value = entry.models || '';
  if (protocol) protocol.value = entry.protocol || '';
  const envKey = document.getElementById('f-env-key');
  if (envKey) envKey.value = entry.env_key || '';
  _discoveredModels = [];
  renderModelPicker();
  const status = document.getElementById('models-status');
  if (status) status.textContent = '';
  if (name) name.focus();
}

let _discoveredModels = [];

function renderModelPicker() {
  const box = document.getElementById('model-picker');
  if (!box) return;
  const onlyFree = document.getElementById('only-free')?.checked;
  const models = _discoveredModels.filter(m => !onlyFree || m.free);
  if (!_discoveredModels.length) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  box.classList.remove('hidden');
  box.innerHTML = models.length
    ? models.map(m => `<label class="ab-catalog__item">
        <input type="checkbox" data-model="${escHtml(m.id)}" checked />
        <span class="ab-catalog__label">${escHtml(m.id)}</span>
        ${m.free ? '<span class="ab-catalog__badge ab-catalog__badge--custom">grátis</span>' : ''}
      </label>`).join('')
    : '<div class="ab-label-hint px-1 py-2">Nenhum modelo para este filtro.</div>';
}

function selectedModelLines() {
  const boxes = [...document.querySelectorAll('#model-picker input[data-model]:checked')];
  if (!boxes.length) return '';
  const byId = new Map(_discoveredModels.map(m => [m.id, m]));
  return boxes.map(box => {
    const model = byId.get(box.dataset.model);
    const label = model && model.label && model.label !== model.id ? `|${model.label}` : '';
    return `${box.dataset.model}${label}`;
  }).join('\n');
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
  // Explicit size controls remain usable even when Windows hides the border of a frameless window.
  const resizeBy = (delta) => {
    const api = window.pywebview?.api;
    if (!api?.resize_window) return;
    const width = Math.max(520, Math.min(1600, Math.round(window.innerWidth + delta)));
    const height = Math.max(500, Math.min(1200, Math.round(window.innerHeight + delta)));
    api.resize_window(width, height).catch(() => toast('Não foi possível redimensionar a janela.', 'error'));
  };
  document.getElementById('btn-smaller')?.addEventListener('click', () => resizeBy(-80));
  document.getElementById('btn-larger')?.addEventListener('click', () => resizeBy(80));

  // Frameless windows do not expose a native resize border; use this corner grip.
  const resizeGrip = document.getElementById('ab-resize-grip');
  if (resizeGrip) {
    let drag = null;
    let resizeTimer = null;
    let lastSize = '';
    const sendSize = (width, height) => {
      const size = `${width}x${height}`;
      if (size === lastSize || !window.pywebview?.api?.resize_window) return;
      lastSize = size;
      window.pywebview.api.resize_window(width, height).catch(() => { lastSize = ''; });
    };
    resizeGrip.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      drag = { x: event.screenX, y: event.screenY, width: window.innerWidth, height: window.innerHeight };
      resizeGrip.setPointerCapture(event.pointerId);
    });
    resizeGrip.addEventListener('pointermove', (event) => {
      if (!drag) return;
      event.preventDefault();
      const width = Math.max(520, Math.round(drag.width + event.screenX - drag.x));
      const height = Math.max(500, Math.round(drag.height + event.screenY - drag.y));
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => sendSize(width, height), 80);
    });
    const stopResize = (event) => {
      if (!drag) return;
      const width = Math.max(520, Math.round(drag.width + event.screenX - drag.x));
      const height = Math.max(500, Math.round(drag.height + event.screenY - drag.y));
      clearTimeout(resizeTimer);
      drag = null;
      sendSize(width, height);
    };
    resizeGrip.addEventListener('pointerup', stopResize);
    resizeGrip.addEventListener('pointercancel', stopResize);
  }

  // Window controls
  document.getElementById('btn-minimize')?.addEventListener('click', () => {
    window.pywebview?.api?.minimize();
  });

  // Hide to the system tray; the tray icon keeps "Mostrar" and "Sair".
  document.getElementById('btn-tray')?.addEventListener('click', () => {
    const api = window.pywebview?.api;
    if (api?.hide_window) api.hide_window();
    else toast('Bandeja do sistema indisponível.', 'error');
  });
  document.getElementById('btn-close')?.addEventListener('click', () => {
    const api = window.pywebview?.api;
    if (api?.quit) api.quit();
    else if (api?.close) api.close();
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

  // One-click mode switch. The backend performs a graceful restart when the
  // desktop client must reload its configuration; no second confirmation dialog.
  let _modeSwitchPending = false;
  async function activateClientMode(mode) {
    if (!_currentTarget || _modeSwitchPending) return;
    if (mode === 'bridge' && (!_state.providers || !_state.providers.length)) {
      toast('Adicione e salve um provedor antes de usar o AI Bridge.', 'error');
      return;
    }
    _modeSwitchPending = true;
    const bridgeButton = document.getElementById('pill-bridge');
    const originalButton = document.getElementById('pill-original');
    if (bridgeButton) bridgeButton.disabled = true;
    if (originalButton) originalButton.disabled = true;
    try {
      const res = await api('activate_target', _currentTarget, mode);
      if (res?.ok) {
        toast(res.message || (mode === 'bridge' ? 'Modo AI Bridge aplicado.' : 'Modo original restaurado.'), 'success');
        await refresh();
        renderTarget(_currentTarget);
      } else {
        toast(res?.error || 'Não foi possível alternar o modo.', 'error');
        await refresh();
        renderTarget(_currentTarget);
      }
    } catch (error) {
      toast('Falha ao alternar o modo: ' + (error?.message || error), 'error');
      await refresh();
      renderTarget(_currentTarget);
    } finally {
      _modeSwitchPending = false;
      if (bridgeButton) bridgeButton.disabled = false;
      if (originalButton) originalButton.disabled = false;
    }
  }

  document.getElementById('pill-bridge')?.addEventListener('click', () => activateClientMode('bridge'));
  document.getElementById('pill-original')?.addEventListener('click', () => activateClientMode('original'));
  document.getElementById('target-model-select')?.addEventListener('change', async (event) => {
    const result = await api('set_active_model', event.target.value);
    if (result?.ok) {
      await refresh();
      renderTarget(_currentTarget);
      toast('Modelo padrão atualizado. Novas sessões do Codex usarão este modelo.', 'success');
    } else {
      toast(result?.error || 'Não foi possível alterar o modelo padrão.', 'error');
    }
  });

  // Go to providers from target screen
  document.getElementById('btn-go-providers-from-target')?.addEventListener('click', () => go('providers'));

  // Auth mode (API key vs OAuth)
  document.getElementById('f-auth-kind')?.addEventListener('change', (e) => {
    syncAuthUi({ kind: e.target.value, source: document.getElementById('f-oauth-source')?.value });
  });

  // Start the bridge's own OAuth login (saves the provider first when it is new)
  document.getElementById('btn-oauth-login')?.addEventListener('click', async () => {
    const name = document.getElementById('f-name')?.value?.trim();
    const source = document.getElementById('f-oauth-source')?.value || 'codex';
    if (!name) { toast('Informe o nome do provedor antes de entrar.', 'error'); return; }
    let providerName = _editingProvider;
    if (!providerName) {
      const url = document.getElementById('f-url')?.value?.trim() || '';
      const models = document.getElementById('f-models')?.value?.trim() || '';
      const protocol = document.getElementById('f-protocol')?.value || '';
      const saved = await api('add_provider', name, url, '', models, { kind: 'oauth', source }, protocol || null);
      if (!saved || !saved.ok) { toast(saved?.error || 'Salve o provedor antes de entrar.', 'error'); return; }
      providerName = name;
    }
    const res = await api('get_oauth_login_url', providerName);
    const statusEl = document.getElementById('oauth-status');
    if (res && res.ok) {
      if (statusEl) statusEl.textContent = 'Login aberto no navegador — conclua para liberar o provedor.';
      toast('Login aberto no navegador.', 'success');
    } else {
      toast(res?.error || 'Não foi possível iniciar o login OAuth.', 'error');
    }
  });

  // Show/hide API key
  document.getElementById('btn-show-key')?.addEventListener('click', () => {
    const input = document.getElementById('f-key');
    if (!input) return;
    const isHidden = input.type === 'password';
    input.type = isHidden ? 'text' : 'password';
    document.getElementById('icon-eye')?.classList.toggle('hidden', isHidden);
    document.getElementById('icon-eye-off')?.classList.toggle('hidden', !isHidden);
  });

  // Buscar modelos direto na API do provedor
  document.getElementById('btn-fetch-models')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-fetch-models');
    const status = document.getElementById('models-status');
    const name = document.getElementById('f-name')?.value?.trim() || '';
    const url = document.getElementById('f-url')?.value?.trim() || '';
    const key = document.getElementById('f-key')?.value?.trim() || '';
    const envKey = document.getElementById('f-env-key')?.value?.trim() || '';
    const auth = currentAuth();
    if (!url && !_editingProvider) { toast('Informe a URL base para buscar os modelos.', 'error'); return; }
    if (btn) { btn.disabled = true; btn.textContent = 'Buscando…'; }
    const res = await api('fetch_models', _editingProvider || name, url, key, envKey, auth);
    if (btn) { btn.disabled = false; btn.textContent = 'Buscar modelos disponíveis'; }
    if (!res || !res.ok) {
      if (status) status.textContent = res?.error || '';
      toast(res?.error || 'Falha ao buscar modelos.', 'error');
      return;
    }
    _discoveredModels = res.models || [];
    if (status) status.textContent = `${res.total} modelos · ${res.free_count} gratuitos`;
    renderModelPicker();
  });

  document.getElementById('only-free')?.addEventListener('change', renderModelPicker);
  document.getElementById('btn-select-all')?.addEventListener('click', () => {
    document.querySelectorAll('#model-picker input[data-model]').forEach(box => { box.checked = true; });
  });
  document.getElementById('btn-clear-models')?.addEventListener('click', () => {
    document.querySelectorAll('#model-picker input[data-model]').forEach(box => { box.checked = false; });
  });

  // Importar provedores/modelos do perfil do DeepSeek Harness
  document.getElementById('btn-import-dsh')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-import-dsh');
    if (btn) btn.disabled = true;
    const res = await api('import_dsh_providers');
    if (btn) btn.disabled = false;
    if (res && res.ok) {
      const names = res.imported || [];
      if (names.length) {
        toast(`${names.length} provedor(es) importado(s) do DeepSeek Harness: ${names.join(', ')}.`, 'success');
        await refresh();
        go('providers');
      } else {
        const why = (res.skipped || []).map(s => `${s.name} (${s.reason})`).join(', ');
        toast(why ? `Nada novo para importar — ${why}.` : 'Nenhum provedor novo no DSH.', 'info');
      }
    } else {
      toast(res?.error || 'Falha ao importar do DeepSeek Harness.', 'error');
    }
  });

  // Test connection
  document.getElementById('btn-test')?.addEventListener('click', async () => {
    const url = document.getElementById('f-url')?.value?.trim();
    const key = document.getElementById('f-key')?.value?.trim();
    const auth = currentAuth();
    const btn = document.getElementById('btn-test');
    const resultEl = document.getElementById('test-result');
    const importBtn = document.getElementById('btn-import-models');
    if (!auth && !url) { toast('Preencha a URL antes de testar.', 'error'); return; }
    if (!auth && !key && !_editingProvider) { toast('Preencha a chave antes de testar.', 'error'); return; }
    if (auth && !_editingProvider) { toast('Salve o provedor OAuth antes de testar.', 'error'); return; }
    if (btn) { btn.textContent = 'Testando…'; btn.disabled = true; }
    if (importBtn) importBtn.hidden = true;
    const res = await api('test_provider', url || '', key || '', _editingProvider || null);
    if (btn) { btn.textContent = 'Testar conexão'; btn.disabled = false; }
    if (resultEl) {
      resultEl.hidden = false;
      if (res && res.ok) {
        resultEl.className = 'ab-test-ok';
        resultEl.textContent = res.oauth
          ? `✓ ${res.message || 'Sessão OAuth válida'} (${res.protocol})`
          : `✓ Conexão OK — ${res.models_count ?? (res.models || []).length} modelo(s)`;
        if (importBtn && (res.models || []).length) {
          importBtn.hidden = false;
          importBtn.onclick = () => {
            const modelsField = document.getElementById('f-models');
            const current = new Set((modelsField?.value || '').split(/\\r?\\n/).map(x => x.trim()).filter(Boolean));
            (res.models || []).forEach(id => current.add(id));
            if (modelsField) modelsField.value = Array.from(current).join('\\n');
            importBtn.hidden = true;
            toast(`${(res.models || []).length} modelos importados. Revise a lista antes de salvar.`, 'success');
          };
        }
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
    const typedModels = document.getElementById('f-models')?.value?.trim() || '';
    const models = selectedModelLines() || typedModels;
    const auth = currentAuth();

    if (!name) return;
    if (!auth && !url) { toast('Preencha a URL do provedor.', 'error'); return; }
    if (!auth && !key && !_editingProvider) { toast('Preencha a chave API.', 'error'); return; }

    const saveBtn = document.getElementById('btn-save');
    if (saveBtn) saveBtn.disabled = true;

    const protocol = document.getElementById('f-protocol')?.value || '';
    const envKey = document.getElementById('f-env-key')?.value?.trim();
    const res = await api('add_provider', name, url || '', key || '', models, auth, protocol || null, envKey || null);

    if (saveBtn) saveBtn.disabled = false;

    if (res && res.ok) {
      const restartTargets = res.restart_required_targets || [];
      const suffix = auth ? ' OAuth configurado — use “Entrar com…” se ainda não houver sessão.' : '';
      if (restartTargets.length) {
        toast(`Provedor "${name}" salvo.${suffix} Reinicie ${restartTargets.join(' e ')} para atualizar o seletor de modelos.`, 'success');
      } else {
        toast(`Provedor "${name}" salvo.${suffix}`, 'success');
      }
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


