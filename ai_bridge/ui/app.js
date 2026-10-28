'use strict';

/* ─── Utility ─────────────────────────────────────────────────────────────── */

function $(id) { return document.getElementById(id); }
function $q(sel, ctx) { return (ctx || document).querySelector(sel); }

const PROVIDER_ICONS = {
  deepseek:  '🐋', openai: '🤖', groq: '⚡', gemini: '✦',
  mistral:   '🌬️', openrouter: '🔀', together: '🤝', ollama: '🦙',
  anthropic: '🔷', claude: '🔷', cohere: '🌀', default: '🔮',
};

function providerIcon(name) {
  const key = name.toLowerCase().split(/[\s_/-]/)[0];
  return PROVIDER_ICONS[key] || PROVIDER_ICONS.default;
}

/* ─── Toasts ──────────────────────────────────────────────────────────────── */

function toast(msg, type = 'info') {
  const icons = { success: '✓', error: '✕', info: 'ℹ' };
  const el = document.createElement('div');
  el.className = `ab-toast ab-toast--${type}`;
  el.innerHTML = `<span class="ab-toast-icon">${icons[type] || 'ℹ'}</span><span>${msg}</span>`;
  $('ab-toasts').appendChild(el);
  setTimeout(() => {
    el.classList.add('ab-toast--out');
    setTimeout(() => el.remove(), 220);
  }, 3200);
}

/* ─── Screen routing ──────────────────────────────────────────────────────── */

let _screen = 'home';

function go(screen) {
  document.querySelectorAll('.ab-screen').forEach(s => {
    s.hidden = (s.dataset.screen !== screen);
  });
  _screen = screen;
}

/* ─── API bridge ──────────────────────────────────────────────────────────── */

async function api(method, ...args) {
  if (!window.pywebview) throw new Error('pywebview unavailable');
  return window.pywebview.api[method](...args);
}

/* ─── State & render ──────────────────────────────────────────────────────── */

let state = { providers: [], targets: [], connected: false, port: null, proxy_running: false, model_count: 0 };
let _editingProvider = null;

async function refresh() {
  try {
    const r = await api('state');
    if (!r.ok) { toast(r.error, 'error'); return; }
    state = r;
    renderHome();
  } catch(e) {
    toast(String(e), 'error');
  }
}

function renderHome() {
  // Provider list
  const list = $('provider-list');
  if (!state.providers || !state.providers.length) {
    list.innerHTML = `
      <div class="ab-empty">
        <div class="ab-empty-icon">🔌</div>
        <p>Nenhum provedor cadastrado.<br>Clique em <b>+ Adicionar</b> para começar.</p>
      </div>`;
  } else {
    list.innerHTML = state.providers.map(p => `
      <div class="ab-provider-card">
        <div class="ab-provider-icon">${providerIcon(p.name)}</div>
        <div class="ab-provider-info">
          <div class="ab-provider-name">${escHtml(p.name)}</div>
          <div class="ab-provider-meta">${escHtml(p.base_url)}</div>
          <div class="ab-provider-models">${p.models.length} modelo${p.models.length !== 1 ? 's' : ''}</div>
        </div>
        <div class="ab-provider-btns">
          <button class="btn btn-ghost btn-sm btn-icon" data-edit="${escHtml(p.name)}" title="Editar">✎</button>
          <button class="btn btn-danger btn-sm btn-icon" data-remove="${escHtml(p.name)}" title="Remover">✕</button>
        </div>
      </div>`).join('');

    // Edit / Remove buttons
    list.querySelectorAll('[data-edit]').forEach(btn => {
      btn.addEventListener('click', () => editProvider(btn.dataset.edit));
    });
    list.querySelectorAll('[data-remove]').forEach(btn => {
      btn.addEventListener('click', () => removeProvider(btn.dataset.remove));
    });
  }

  // Targets list
  const targetList = $('target-list');
  const hint = $('proxy-hint');
  const hasProviders = state.providers && state.providers.length > 0;

  if (!state.targets || !state.targets.length) {
    targetList.innerHTML = '';
  } else {
    targetList.innerHTML = state.targets.map(t => {
      const isOn = t.connected;
      const notInstalled = !t.installed;
      let badgeHtml = '';
      if (notInstalled) {
        badgeHtml = `<span class="ab-target-badge ab-target-badge--na">Não instalado</span>`;
      } else if (isOn) {
        badgeHtml = `<span class="ab-target-badge ab-target-badge--on">Conectado</span>`;
      }
      const disableCon = !hasProviders || notInstalled;
      return `
        <div class="ab-target-card${isOn ? ' ab-target-card--on' : ''}">
          <div class="ab-target-icon">${escHtml(t.icon)}</div>
          <div class="ab-target-info">
            <div class="ab-target-name">${escHtml(t.name)} ${badgeHtml}</div>
            <div class="ab-target-desc">${escHtml(t.desc)}</div>
          </div>
          ${isOn
            ? `<button class="btn btn-ghost btn-sm ab-target-btn" data-action="disconnect" data-id="${escHtml(t.id)}">Desconectar</button>`
            : `<button class="btn btn-primary btn-sm ab-target-btn" data-action="connect" data-id="${escHtml(t.id)}"${disableCon ? ' disabled' : ''}>Conectar</button>`
          }
        </div>`;
    }).join('');

    targetList.querySelectorAll('.ab-target-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.action === 'connect') connectTarget(btn.dataset.id, btn);
        else disconnectTarget(btn.dataset.id, btn);
      });
    });
  }

  hint.innerHTML = state.proxy_running && state.port
    ? `Proxy ativo · <span class="tag tag-port">:${state.port}</span>`
    : '';
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* ─── Provider edit ───────────────────────────────────────────────────────── */

async function editProvider(name) {
  try {
    const r = await api('get_provider_detail', name);
    if (!r.ok) { toast(r.error, 'error'); return; }

    _editingProvider = name;
    $('add-form').reset();
    $('test-result').hidden = true;

    $('f-name').value    = r.name;
    $('f-name').readOnly = true;
    $('f-url').value     = r.base_url;
    $('f-models').value  = r.models_raw;
    $('f-key').value     = '';
    $('f-key').placeholder = 'Deixe em branco para manter a chave atual';
    $('f-key').required  = false;

    $('add-screen-title').textContent = 'Editar Provedor';
    $('save-label').textContent = 'Salvar Alterações';

    loadPresets();
    go('add');
  } catch(e) {
    toast(String(e), 'error');
  }
}

/* ─── Provider remove ─────────────────────────────────────────────────────── */

async function removeProvider(name) {
  if (!confirm(`Remover o provedor "${name}"?`)) return;
  try {
    const r = await api('remove_provider', name);
    if (!r.ok) { toast(r.error, 'error'); return; }
    toast(`Provedor "${name}" removido`, 'success');
    await refresh();
  } catch(e) {
    toast(String(e), 'error');
  }
}

/* ─── Connect / Disconnect targets ───────────────────────────────────────── */

async function connectTarget(id, btn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<div class="ab-spin"></div>';
  try {
    const r = await api('connect_target', id);
    if (!r.ok) { toast(r.error, 'error'); }
    else {
      const t = (state.targets || []).find(x => x.id === id);
      const name = t ? t.name : id;
      toast(`${name} conectado na porta ${r.port} 🎉`, 'success');
      await refresh();
    }
  } catch(e) {
    toast(String(e), 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

async function disconnectTarget(id, btn) {
  btn.disabled = true;
  try {
    const r = await api('disconnect_target', id);
    if (!r.ok) { toast(r.error, 'error'); }
    else {
      const t = (state.targets || []).find(x => x.id === id);
      const name = t ? t.name : id;
      toast(`${name} desconectado`, 'info');
      await refresh();
    }
  } catch(e) {
    toast(String(e), 'error');
  } finally {
    btn.disabled = false;
  }
}

/* ─── Add Provider screen ─────────────────────────────────────────────────── */

let presets = [];

async function loadPresets() {
  try {
    const r = await api('get_presets');
    if (!r.ok) return;
    presets = r.presets;
    const list = $('preset-list');
    list.innerHTML = presets.map((p, i) => `
      <div class="ab-preset-item" data-idx="${i}">
        <span>${providerIcon(p.name)}</span>
        ${escHtml(p.name)}
      </div>`).join('');
    list.querySelectorAll('.ab-preset-item').forEach(el => {
      el.addEventListener('click', () => applyPreset(Number(el.dataset.idx)));
    });
  } catch {}
}

function applyPreset(idx) {
  const p = presets[idx];
  if (!p) return;
  if (!_editingProvider) $('f-name').value = p.name;
  $('f-url').value    = p.base_url;
  $('f-models').value = p.models;
  $('f-key').value    = '';
  $('f-key').focus();
  $('test-result').hidden = true;
}

function resetAddForm() {
  $('add-form').reset();
  $('test-result').hidden = true;
  $('save-label').textContent = 'Salvar Provedor';
  $('add-screen-title').textContent = 'Novo Provedor';
  $('f-name').readOnly  = false;
  $('f-key').placeholder = 'sk-…';
  $('f-key').required   = true;
  _editingProvider = null;
}

/* ─── Test connection ─────────────────────────────────────────────────────── */

async function testConnection() {
  const url = $('f-url').value.trim();
  const key = $('f-key').value.trim();
  if (!url || !key) { toast('Preencha a URL e a chave antes de testar', 'error'); return; }

  const btn = $('btn-test');
  btn.disabled = true;
  btn.innerHTML = '<div class="ab-spin"></div>';

  try {
    const r = await api('test_provider', url, key);
    const box = $('test-result');
    box.hidden = false;
    if (r.ok) {
      box.className = 'ab-models-found';
      const models = r.models || [];
      box.textContent = models.length
        ? `✓ ${models.length} modelo(s) encontrado(s) — campo preenchido automaticamente`
        : '✓ Conexão OK (nenhum modelo listado)';
      if (models.length) {
        const current = $('f-models').value.trim();
        if (!current) {
          $('f-models').value = models.join('\n');
        } else {
          if (confirm(`Substituir modelos existentes pelos ${models.length} encontrados na API?`)) {
            $('f-models').value = models.join('\n');
          }
        }
      }
      toast('Conexão bem-sucedida!', 'success');
    } else {
      box.className = 'ab-hint';
      box.style.color = 'var(--error)';
      box.textContent = '✕ ' + r.error;
    }
  } catch(e) {
    toast(String(e), 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Testar';
  }
}

/* ─── Save provider ───────────────────────────────────────────────────────── */

async function saveProvider(e) {
  e.preventDefault();
  const name   = $('f-name').value.trim();
  const url    = $('f-url').value.trim();
  const key    = $('f-key').value.trim();
  const models = $('f-models').value;

  const btn = $('btn-save');
  btn.disabled = true;
  $('save-label').textContent = 'Salvando…';

  try {
    const r = await api('add_provider', name, url, key, models);
    if (!r.ok) { toast(r.error, 'error'); return; }
    toast(`Provedor "${name}" salvo!`, 'success');
    resetAddForm();
    go('home');
    await refresh();
  } catch(e) {
    toast(String(e), 'error');
  } finally {
    btn.disabled = false;
    $('save-label').textContent = 'Salvar Provedor';
  }
}

/* ─── Init ────────────────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  // Title bar
  $('btn-minimize').addEventListener('click', () => api('minimize').catch(() => {}));
  $('btn-close').addEventListener('click',    () => api('close').catch(() => {}));

  // Home
  $('btn-add-provider').addEventListener('click', () => { resetAddForm(); loadPresets(); go('add'); });

  // Add screen
  $('btn-back').addEventListener('click',    () => go('home'));
  $('btn-cancel').addEventListener('click',  () => { resetAddForm(); go('home'); });
  $('btn-test').addEventListener('click',    testConnection);
  $('add-form').addEventListener('submit',   saveProvider);
  $('btn-show-key').addEventListener('click', () => {
    const inp = $('f-key');
    inp.type = inp.type === 'password' ? 'text' : 'password';
    $('btn-show-key').textContent = inp.type === 'password' ? 'Mostrar' : 'Ocultar';
  });

  // Initial load
  if (window.pywebview) {
    window.addEventListener('pywebviewready', () => refresh());
    // Fallback: if event already fired
    setTimeout(() => { if (state.providers === undefined || !state.providers) refresh(); }, 800);
  }
});
