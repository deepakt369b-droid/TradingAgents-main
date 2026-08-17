/* ============================================================
   TradingAgents Desktop — Frontend Application Logic
   ============================================================ */

(function () {
  'use strict';

  // ---------- State ----------
  const state = {
    view: 'config',          // config | dashboard | results
    ws: null,                // WebSocket instance
    analysisRunning: false,
    startTime: null,
    timerInterval: null,
    selectedAnalysts: ['market', 'social', 'news', 'fundamentals'],
    selectedDepth: 1,
    agents: {},              // { name: status }
    reports: {},             // { section: content }
    messages: [],            // [{time, type, content}]
    stats: { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 },
    finalState: null,
    config: null,            // from /api/config
  };

  // ---------- DOM Refs ----------
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // Known-good model defaults, used when /api/config has no catalog entry
  // for a provider (e.g. custom-only providers like kimi) so a model select
  // is never left blank.
  const FALLBACK_MODELS = {
    openai: { deep: ['gpt-5.5', 'gpt-5.4', 'o3'], quick: ['gpt-5.4-mini', 'gpt-4.1-mini'] },
    google: { deep: ['gemini-3.5-pro', 'gemini-3.0-pro'], quick: ['gemini-3.5-flash', 'gemini-3.0-flash'] },
    anthropic: { deep: ['claude-opus-4', 'claude-sonnet-4'], quick: ['claude-sonnet-4', 'claude-haiku-3.5'] },
    deepseek: { deep: ['deepseek-r1', 'deepseek-chat'], quick: ['deepseek-chat'] },
    // Moonshot rotates model IDs frequently; these are the current non-sunset
    // IDs as of Aug 2026. Use OpenAI Compatible + a custom base_url for the
    // Kimi Code Plan endpoint (https://api.kimi.com/coding/v1).
    kimi: { deep: ['kimi-k3', 'kimi-k2.7-code'], quick: ['kimi-k2.6'] },
    nvidia: { deep: ['meta/llama-3.1-70b-instruct', 'nvidia/llama-3.1-nemotron-70b-instruct'], quick: ['meta/llama-3.1-8b-instruct'] },
    ollama: { deep: ['llama3.3:70b'], quick: ['llama3.3:8b'] },
    openrouter: { deep: ['anthropic/claude-3.5-sonnet', 'openai/gpt-4o'], quick: ['meta-llama/llama-3.1-8b-instruct'] },
    lm_studio: { deep: ['default'], quick: ['default'] },
  };

  // ---------- View Management ----------
  function switchView(viewName) {
    state.view = viewName;
    $$('.view').forEach(v => v.classList.remove('active'));
    const el = $(`#view-${viewName}`);
    if (el) el.classList.add('active');
  }

  // ---------- Toast Notifications ----------
  function showToast(message, type = 'info', duration = 6000) {
    const container = $('#toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
      <span>${message}</span>
      <button class="toast-dismiss" onclick="this.parentElement.remove()">✕</button>
    `;
    container.appendChild(toast);
    if (duration > 0) {
      setTimeout(() => toast.remove(), duration);
    }
  }

  // ---------- Initialization ----------
  async function init() {
    // Set default date to today
    const today = new Date().toISOString().split('T')[0];
    $('#analysis-date').value = today;

    // Load saved preferences from localStorage
    loadPreferences();

    // Bind events
    bindConfigEvents();

    // Load config from backend
    await loadConfig();

    // Check for updates
    checkForUpdates();
  }

  function loadPreferences() {
    try {
      const prefs = JSON.parse(localStorage.getItem('ta_prefs') || '{}');
      if (prefs.ticker) $('#ticker').value = prefs.ticker;
      if (prefs.provider) {
        $('#llm-provider').value = prefs.provider;
        toggleBaseUrlVisibility(prefs.provider);
      }
      if (prefs.baseUrl) $('#base-url').value = prefs.baseUrl;
      if (prefs.language) $('#output-language').value = prefs.language;
      if (prefs.quickSplit) {
        const cb = $('#split-quick-provider');
        if (cb) {
          cb.checked = true;
          $('#quick-provider-section').classList.remove('hidden');
        }
        if (prefs.quickProvider) $('#quick-llm-provider').value = prefs.quickProvider;
        if (prefs.quickBaseUrl) $('#quick-base-url').value = prefs.quickBaseUrl;
      }
      if (prefs.depth) {
        state.selectedDepth = prefs.depth;
        $$('.depth-option').forEach(d => {
          d.classList.toggle('selected', parseInt(d.dataset.depth) === prefs.depth);
        });
      }
      if (prefs.analysts) {
        state.selectedAnalysts = prefs.analysts;
        $$('.analyst-check').forEach(a => {
          const val = a.dataset.analyst;
          const checked = prefs.analysts.includes(val);
          a.classList.toggle('selected', checked);
          a.querySelector('input').checked = checked;
        });
      }
    } catch (e) { /* ignore */ }
  }

  function savePreferences() {
    try {
      localStorage.setItem('ta_prefs', JSON.stringify({
        ticker: $('#ticker').value,
        provider: $('#llm-provider').value,
        baseUrl: $('#base-url').value,
        language: $('#output-language').value,
        depth: state.selectedDepth,
        analysts: state.selectedAnalysts,
        quickSplit: isQuickProviderSplit(),
        quickProvider: $('#quick-llm-provider') ? $('#quick-llm-provider').value : null,
        quickBaseUrl: $('#quick-base-url') ? $('#quick-base-url').value : null,
      }));
    } catch (e) { /* ignore */ }
  }

  // ---------- Config Loading ----------
  async function loadConfig() {
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) throw new Error('Failed to load config');
      state.config = await resp.json();
      populateModels($('#llm-provider').value);
      toggleBaseUrlVisibility($('#llm-provider').value);
      if (isQuickProviderSplit() && $('#quick-llm-provider')) {
        populateQuickModels($('#quick-llm-provider').value);
        toggleBaseUrlVisibility($('#quick-llm-provider').value, '#quick-base-url-wrap', '#quick-base-url');
      }
    } catch (e) {
      console.warn('Could not load config:', e);
      // Set fallback models
      populateModelsFallback();
    }
  }

  function populateModels(provider) {
    // Deep-thinking select always follows the main provider dropdown. The
    // quick-thinking select follows it too UNLESS the user has opted into a
    // separate quick-thinking provider (see populateQuickModels).
    populateModelsForRole(provider, 'deep', $('#deep-model'));
    if (!isQuickProviderSplit()) {
      populateModelsForRole(provider, 'quick', $('#quick-model'));
    }

    // Update thinking config visibility
    updateThinkingConfig(provider, $('#thinking-config-wrap'), $('#thinking-config-label'), $('#thinking-config'));
  }

  function isQuickProviderSplit() {
    const cb = $('#split-quick-provider');
    return !!(cb && cb.checked);
  }

  function populateQuickModels(provider) {
    populateModelsForRole(provider, 'quick', $('#quick-model'));
  }

  function populateModelsForRole(provider, role, selectEl) {
    if (!selectEl) return;
    selectEl.innerHTML = '';

    let models = null;
    if (state.config && state.config.models && state.config.models[provider]) {
      models = state.config.models[provider];
    }
    const list = models && models[role];

    if (list && list.length) {
      list.forEach(m => {
        selectEl.innerHTML += `<option value="${m}">${m}</option>`;
      });
    } else {
      // Empty list (e.g. custom-only providers like kimi) falls back to
      // known-good defaults so the select is never left blank.
      const fallback = (FALLBACK_MODELS[provider] || { deep: ['default'], quick: ['default'] })[role];
      fallback.forEach(m => {
        selectEl.innerHTML += `<option value="${m}">${m}</option>`;
      });
    }
  }

  function populateModelsFallback() {
    // Used only when /api/config itself failed to load -- populate both
    // selects from the shared provider dropdown since no per-role split
    // can be offered without the config the split UI depends on.
    const provider = $('#llm-provider').value;
    populateModelsForRole(provider, 'deep', $('#deep-model'));
    populateModelsForRole(provider, 'quick', $('#quick-model'));
  }

  function updateThinkingConfig(provider, wrap, label, sel) {
    if (!wrap || !label || !sel) return;
    if (provider === 'google') {
      wrap.classList.remove('hidden');
      label.textContent = 'Thinking Level';
      sel.innerHTML = '<option value="">Default</option><option value="minimal">Minimal</option><option value="high">High</option>';
    } else if (provider === 'openai') {
      wrap.classList.remove('hidden');
      label.textContent = 'Reasoning Effort';
      sel.innerHTML = '<option value="">Default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>';
    } else if (provider === 'anthropic') {
      wrap.classList.remove('hidden');
      label.textContent = 'Effort Level';
      sel.innerHTML = '<option value="">Default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>';
    } else {
      wrap.classList.add('hidden');
    }
  }

  function toggleBaseUrlVisibility(provider, wrapSel, inputSel) {
    // Always show the endpoint field, prefilled with the provider's default
    // API base URL (from /api/config) and editable.
    wrapSel = wrapSel || '#base-url-wrap';
    inputSel = inputSel || '#base-url';
    const wrap = $(wrapSel);
    if (!wrap) return;
    wrap.classList.remove('hidden');
    if (!state.config || !state.config.base_urls) return;

    const input = $(inputSel);
    const newUrl = state.config.base_urls[provider];
    const current = input.value.trim();

    // If the field is empty or currently holds another provider's default
    // endpoint, switch it to the newly selected provider's default. This
    // prevents a stale OpenAI URL from being sent when the user switches to
    // Moonshot (or any other provider).
    const knownDefaults = new Set(Object.values(state.config.base_urls));
    if (!current || knownDefaults.has(current)) {
      input.value = newUrl || '';
    }
  }

  // ---------- Event Bindings ----------
  function bindConfigEvents() {
    // Provider change
    $('#llm-provider').addEventListener('change', (e) => {
      populateModels(e.target.value);
      toggleBaseUrlVisibility(e.target.value);
    });

    // Split quick-thinking onto its own provider
    const splitCb = $('#split-quick-provider');
    const quickSection = $('#quick-provider-section');
    if (splitCb && quickSection) {
      splitCb.addEventListener('change', () => {
        quickSection.classList.toggle('hidden', !splitCb.checked);
        if (splitCb.checked) {
          populateQuickModels($('#quick-llm-provider').value);
          toggleBaseUrlVisibility($('#quick-llm-provider').value, '#quick-base-url-wrap', '#quick-base-url');
          updateThinkingConfig(
            $('#quick-llm-provider').value,
            $('#quick-thinking-config-wrap'), $('#quick-thinking-config-label'), $('#quick-thinking-config')
          );
        } else {
          // Reverting to the shared provider: quick-model follows deep provider again.
          populateModels($('#llm-provider').value);
        }
      });
    }
    const quickProviderSelect = $('#quick-llm-provider');
    if (quickProviderSelect) {
      quickProviderSelect.addEventListener('change', (e) => {
        populateQuickModels(e.target.value);
        toggleBaseUrlVisibility(e.target.value, '#quick-base-url-wrap', '#quick-base-url');
        updateThinkingConfig(
          e.target.value,
          $('#quick-thinking-config-wrap'), $('#quick-thinking-config-label'), $('#quick-thinking-config')
        );
      });
    }

    // Execution platform dynamic fields
    const execPlatform = $('#exec-platform');
    if (execPlatform) {
      const updateExecFields = () => {
        const val = execPlatform.value;
        const alpacaFields = $('#exec-fields-alpaca');
        const ibkrFields = $('#exec-fields-ibkr');
        const ccxtFields = $('#exec-fields-ccxt');

        if (alpacaFields) alpacaFields.classList.toggle('hidden', val !== 'alpaca');
        if (ibkrFields) ibkrFields.classList.toggle('hidden', val !== 'ibkr');
        if (ccxtFields) ccxtFields.classList.toggle('hidden', val !== 'ccxt');
      };
      execPlatform.addEventListener('change', updateExecFields);
      updateExecFields();
    }

    // Save Production Gateway & Broker Config
    const btnSaveProdConfig = $('#btn-save-prod-config');
    if (btnSaveProdConfig) {
      btnSaveProdConfig.addEventListener('click', async () => {
        btnSaveProdConfig.textContent = 'Saving...';
        btnSaveProdConfig.disabled = true;

        try {
          const body = {
            cf_account_id: $('#cf-account-id').value.trim(),
            cf_gateway_id: $('#cf-gateway-id').value.trim(),
            cf_byok_alias: $('#cf-byok-alias').value.trim(),
            cf_gateway_url: $('#cf-gateway-url').value.trim(),
            cf_gateway_token: $('#cf-gateway-token').value.trim(),
            execution_platform: $('#exec-platform').value,
            alpaca_api_key: $('#alpaca-api-key').value.trim(),
            alpaca_secret_key: $('#alpaca-secret-key').value.trim(),
            ibkr_host: $('#ibkr-host').value.trim(),
            ibkr_port: $('#ibkr-port').value.trim(),
            ccxt_exchange: $('#ccxt-exchange').value,
            ccxt_api_key: $('#ccxt-api-key').value.trim(),
            ccxt_secret_key: $('#ccxt-secret-key').value.trim(),
            require_trade_approval: $('#require-trade-approval').checked,
            approval_timeout_minutes: $('#approval-timeout-minutes').value.trim(),
            execute_from_ui: $('#execute-from-ui').checked,
            telegram_enabled: $('#telegram-enabled').checked,
            telegram_bot_token: $('#telegram-bot-token').value.trim(),
            telegram_chat_id: $('#telegram-chat-id').value.trim(),
            telegram_allowed_chat_ids: $('#telegram-allowed-chat-ids').value.trim(),
            telegram_webhook_secret: $('#telegram-webhook-secret').value.trim(),
          };

          const resp = await fetch('/api/save-production-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });

          const data = await resp.json();
          if (resp.ok && data.success) {
            showToast('Gateway & Broker settings saved to runtime and .env!', 'success', 5000);
          } else {
            showToast(`Error saving settings: ${data.message || 'Unknown error'}`, 'error', 6000);
          }
        } catch (err) {
          showToast(`Save failed: ${err.message}`, 'error', 6000);
        } finally {
          btnSaveProdConfig.textContent = 'Save & Apply Settings';
          btnSaveProdConfig.disabled = false;
        }
      });
    }

    // Analyst checkboxes
    $$('.analyst-check').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        const cb = el.querySelector('input');
        cb.checked = !cb.checked;
        el.classList.toggle('selected', cb.checked);
        state.selectedAnalysts = Array.from($$('.analyst-check input:checked')).map(i => i.value);
      });
    });

    // Depth selection
    $$('.depth-option').forEach(el => {
      el.addEventListener('click', () => {
        $$('.depth-option').forEach(d => d.classList.remove('selected'));
        el.classList.add('selected');
        state.selectedDepth = parseInt(el.dataset.depth);
      });
    });

    // Launch button
    $('#btn-launch').addEventListener('click', launchAnalysis);

    // Cancel button
    $('#btn-cancel').addEventListener('click', cancelAnalysis);

    // Edit Config button
    $('#btn-edit-config').addEventListener('click', () => {
      if (state.analysisRunning) {
        cancelAnalysis();
      }
      switchView('config');
    });

    // Results buttons
    $('#btn-save-report').addEventListener('click', saveReport);
    $('#btn-new-analysis').addEventListener('click', () => {
      switchView('config');
    });

    // Fetch models and validate key
    $('#btn-fetch-models').addEventListener('click', fetchModels);

    // Save key to project config store
    const btnSaveKey = $('#btn-save-key');
    if (btnSaveKey) {
      btnSaveKey.addEventListener('click', saveApiKey);
    }

    // Trading view navigation
    const btnHeaderTrading = $('#btn-header-trading');
    if (btnHeaderTrading) btnHeaderTrading.addEventListener('click', openTradingView);
    const btnViewTrading = $('#btn-view-trading');
    if (btnViewTrading) btnViewTrading.addEventListener('click', openTradingView);
    const btnTradingBack = $('#btn-trading-back');
    if (btnTradingBack) {
      btnTradingBack.addEventListener('click', () => switchView(state.lastTicker ? 'results' : 'config'));
    }

    // Telegram test message
    const btnTelegramTest = $('#btn-telegram-test');
    if (btnTelegramTest) {
      btnTelegramTest.addEventListener('click', async () => {
        btnTelegramTest.disabled = true;
        btnTelegramTest.textContent = 'Sending...';
        try {
          const resp = await fetch('/api/telegram/test', { method: 'POST' });
          const data = await resp.json();
          showToast(data.message || (data.success ? 'Sent.' : 'Failed.'), data.success ? 'success' : 'error');
        } catch (e) {
          showToast(`Test failed: ${e.message}`, 'error');
        } finally {
          btnTelegramTest.disabled = false;
          btnTelegramTest.textContent = 'Send Test Message';
        }
      });
    }

    // Kill switch toggle
    const btnKillSwitch = $('#btn-toggle-kill-switch');
    if (btnKillSwitch) {
      btnKillSwitch.addEventListener('click', async () => {
        const active = btnKillSwitch.dataset.active === 'true';
        try {
          const resp = await fetch('/api/kill-switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active: !active }),
          });
          const data = await resp.json();
          renderKillSwitch(data.active);
          showToast(data.active ? '🛑 Kill switch activated.' : '✅ Kill switch cleared.', data.active ? 'warning' : 'success');
        } catch (e) {
          showToast(`Failed to toggle kill switch: ${e.message}`, 'error');
        }
      });
    }
  }

  // ---------- Trading View ----------
  function openTradingView() {
    switchView('trading');
    loadTradingView();
  }

  function renderKillSwitch(active) {
    const btn = $('#btn-toggle-kill-switch');
    if (!btn) return;
    btn.dataset.active = String(active);
    btn.textContent = active ? '🛑 Active -- click to resume' : '✅ Clear -- click to halt';
  }

  async function loadTradingView() {
    try {
      const statusResp = await fetch('/api/trading/status');
      const status = await statusResp.json();
      $('#trading-status-line').textContent =
        `Platform: ${status.platform} • ${status.live_trading_enabled ? 'LIVE' : 'paper/sandbox'} • ` +
        `Approval required: ${status.require_trade_approval ? 'yes' : 'no'}`;
      renderKillSwitch(status.kill_switch_active);
      renderPositions(status.positions, status.account, status.account_error);
    } catch (e) {
      $('#trading-status-line').textContent = 'Failed to load trading status.';
    }

    try {
      const approvalsResp = await fetch('/api/approvals');
      const approvals = await approvalsResp.json();
      renderApprovals(approvals.pending, '#pending-approvals-list', true);
      renderApprovals(approvals.recent, '#recent-approvals-list', false);
    } catch (e) {
      $('#pending-approvals-list').innerHTML = '<div class="report-placeholder">Failed to load approvals.</div>';
    }
  }

  function renderPositions(positions, account, accountError) {
    const container = $('#positions-list');
    if (accountError) {
      container.innerHTML = `<div class="report-placeholder">Could not fetch account/positions: ${escapeHtml(accountError)}</div>`;
      return;
    }
    let html = '';
    if (account) {
      html += `<div class="approval-row"><span>Cash</span><span>$${Number(account.cash).toFixed(2)}</span></div>`;
      html += `<div class="approval-row"><span>Portfolio Value</span><span>$${Number(account.portfolio_value).toFixed(2)}</span></div>`;
    }
    if (!positions || positions.length === 0) {
      html += '<div class="report-placeholder">No open positions.</div>';
    } else {
      positions.forEach(p => {
        html += `
          <div class="position-row">
            <span>${escapeHtml(p.symbol)}</span>
            <span>${Number(p.quantity).toFixed(4)} @ $${Number(p.average_entry_price).toFixed(2)}</span>
            <span>${Number(p.unrealized_pnl) >= 0 ? '+' : ''}${Number(p.unrealized_pnl).toFixed(2)}</span>
          </div>`;
      });
    }
    container.innerHTML = html;
  }

  function renderApprovals(rows, selector, actionable) {
    const container = $(selector);
    if (!rows || rows.length === 0) {
      container.innerHTML = '<div class="report-placeholder">Nothing here yet.</div>';
      return;
    }
    container.innerHTML = rows.map(row => `
      <div class="approval-row">
        <div class="approval-row-info">
          <strong>${escapeHtml(row.ticker)} ${escapeHtml((row.side || '').toUpperCase())} ${Number(row.quantity).toFixed(4)}</strong>
          <span class="field-hint">rating: ${escapeHtml(row.rating)} • platform: ${escapeHtml(row.platform)} • ref: $${Number(row.reference_price).toFixed(2)}</span>
        </div>
        ${actionable
          ? `<div class="approval-row-actions">
               <button class="btn-approve" data-id="${escapeHtml(row.approval_id)}" data-decision="approve">Approve</button>
               <button class="btn-reject" data-id="${escapeHtml(row.approval_id)}" data-decision="reject">Reject</button>
             </div>`
          : `<span class="badge-status ${escapeHtml(row.status)}">${escapeHtml(row.status)}</span>`
        }
      </div>
    `).join('');

    if (actionable) {
      container.querySelectorAll('button[data-decision]').forEach(btn => {
        btn.addEventListener('click', () => decideApproval(btn.dataset.id, btn.dataset.decision));
      });
    }
  }

  async function decideApproval(approvalId, decision) {
    try {
      const resp = await fetch(`/api/approvals/${encodeURIComponent(approvalId)}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      });
      const data = await resp.json();
      if (data.success) {
        showToast(decision === 'approve' ? 'Approved -- submitting shortly.' : 'Rejected.', 'success');
      } else {
        showToast(data.message || 'Decision failed.', 'error');
      }
      loadTradingView();
    } catch (e) {
      showToast(`Decision failed: ${e.message}`, 'error');
    }
  }

  async function saveApiKey() {
    const key = $('#api-key').value.trim();
    const provider = $('#llm-provider').value;
    const status = $('#key-status');
    const btn = $('#btn-save-key');

    if (!key) {
      showToast('Please enter an API key to save', 'warning');
      return;
    }

    btn.textContent = 'Saving...';
    btn.disabled = true;

    try {
      const resp = await fetch('/api/save-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, key }),
      });
      const data = await resp.json();
      if (resp.ok && data.success) {
        status.textContent = '✓';
        status.className = 'key-status valid';
        showToast(data.message || 'API key saved to project config', 'success');
      } else {
        status.textContent = '✗';
        status.className = 'key-status invalid';
        showToast(data.message || 'Failed to save API key', 'error');
      }
    } catch (e) {
      status.textContent = '?';
      status.className = 'key-status';
      showToast('Error connecting to backend', 'error');
    } finally {
      btn.textContent = 'Save Key';
      btn.disabled = false;
    }
  }

  async function fetchModels() {
    const key = $('#api-key').value.trim();
    const provider = $('#llm-provider').value;
    const baseUrl = $('#base-url').value.trim();
    const status = $('#key-status');
    const btn = $('#btn-fetch-models');

    btn.textContent = 'Fetching...';
    btn.disabled = true;
    status.textContent = '⟳';
    status.className = 'key-status checking';

    try {
      const resp = await fetch('/api/fetch-models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, key, base_url: baseUrl }),
      });
      const data = await resp.json();
      
      if (resp.ok && data.valid) {
        status.textContent = '✓';
        status.className = 'key-status valid';
        
        // Populate models
        if (data.models && data.models.length > 0) {
          const deepSelect = $('#deep-model');
          const quickSelect = $('#quick-model');
          deepSelect.innerHTML = '';
          quickSelect.innerHTML = '';
          
          data.models.forEach(m => {
            deepSelect.innerHTML += `<option value="${m}">${m}</option>`;
            quickSelect.innerHTML += `<option value="${m}">${m}</option>`;
          });
          showToast(`Successfully fetched ${data.models.length} models`, 'success');
        }
      } else {
        status.textContent = '✗';
        status.className = 'key-status invalid';
        showToast(data.message || 'Failed to validate key or fetch models', 'error');
      }
    } catch (e) {
      status.textContent = '?';
      status.className = 'key-status';
      showToast('Error connecting to backend', 'error');
    } finally {
      btn.textContent = 'Validate & Fetch Models';
      btn.disabled = false;
    }
  }

  async function validateApiKey() {
    const key = $('#api-key').value.trim();
    const provider = $('#llm-provider').value;
    const status = $('#key-status');

    if (!key) {
      status.textContent = '';
      status.className = 'key-status';
      return;
    }

    status.textContent = '⟳';
    status.className = 'key-status checking';

    try {
      const resp = await fetch('/api/validate-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, key }),
      });
      const data = await resp.json();
      if (data.valid) {
        status.textContent = '✓';
        status.className = 'key-status valid';
      } else {
        status.textContent = '✗';
        status.className = 'key-status invalid';
      }
    } catch (e) {
      status.textContent = '?';
      status.className = 'key-status';
    }
  }

  // ---------- Update Checker ----------
  async function checkForUpdates() {
    try {
      const resp = await fetch('/api/update-check');
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.update_available) {
        showToast(
          `Update available: <strong>${data.latest_version}</strong> → <a class="toast-link" href="${data.download_url}" target="_blank">Download</a>`,
          'info',
          0  // persistent
        );
      }
    } catch (e) { /* silent */ }
  }

  // ---------- Launch Analysis ----------
  function launchAnalysis() {
    // Validate
    const ticker = $('#ticker').value.trim();
    if (!ticker) {
      showToast('Please enter a ticker symbol', 'warning');
      return;
    }

    const date = $('#analysis-date').value;
    if (!date) {
      showToast('Please select an analysis date', 'warning');
      return;
    }

    if (state.selectedAnalysts.length === 0) {
      showToast('Please select at least one analyst', 'warning');
      return;
    }

    // Save preferences
    savePreferences();

    // Build request
    const provider = $('#llm-provider').value;
    const thinkingConfig = $('#thinking-config').value || null;
    const quickSplit = isQuickProviderSplit();

    const request = {
      ticker: ticker.toUpperCase(),
      date: date,
      provider: provider,
      base_url: $('#base-url').value.trim() || null,
      deep_model: $('#deep-model').value,
      quick_model: $('#quick-model').value,
      analysts: state.selectedAnalysts,
      depth: state.selectedDepth,
      language: $('#output-language').value,
      api_key: $('#api-key').value.trim() || null,
      thinking_config: thinkingConfig,
      // Per-role provider split (see "Use a different provider for Quick
      // Thinking"). null fields mean "same as the shared provider above" --
      // the server falls back to `provider`/`base_url` for either role.
      quick_provider: quickSplit ? $('#quick-llm-provider').value : null,
      quick_base_url: quickSplit ? ($('#quick-base-url').value.trim() || null) : null,
      quick_api_key: quickSplit ? ($('#quick-api-key').value.trim() || null) : null,
      quick_thinking_config: quickSplit ? ($('#quick-thinking-config').value || null) : null,
      // Trade execution: off unless the run's own toggle is checked. The
      // platform selected here also drives DEFAULT_CONFIG['execution_platform']
      // for this run via /ws/analysis's request handling.
      execute: $('#run-execute-toggle') ? $('#run-execute-toggle').checked : false,
      execution_platform: $('#run-exec-platform') ? $('#run-exec-platform').value : 'paper',
    };

    const tickerStr = ticker.toUpperCase();
    const isResume = (state.lastTicker === tickerStr && state.lastDate === date && Object.keys(state.reports).length > 0);

    if (!isResume) {
      // Reset state
      resetDashboardState();

      // Initialize agent grid
      initAgentGrid();
    } else {
      state.analysisRunning = true;
      $('#btn-cancel').classList.remove('hidden');
      $('#btn-edit-config').classList.remove('hidden');
    }

    state.lastTicker = tickerStr;
    state.lastDate = date;

    // Switch view
    switchView('dashboard');

    // Start timer
    state.startTime = Date.now();
    state.timerInterval = setInterval(updateTimer, 1000);

    // Connect WebSocket
    connectWebSocket(request);
  }

  function resetDashboardState() {
    state.analysisRunning = true;
    state.agents = {};
    state.reports = {};
    state.messages = [];
    state.stats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };
    state.finalState = null;
    $('#messages-feed').innerHTML = '';
    $('#report-content').innerHTML = '<div class="report-placeholder">Waiting for analysis reports...</div>';
    $('#btn-cancel').classList.remove('hidden');
    $('#btn-edit-config').classList.remove('hidden');
    updateStatsBar();
  }

  // ---------- Agent Grid ----------
  const TEAMS = {
    'Analyst Team': [],    // populated dynamically from selected analysts
    'Research Team': ['Bull Researcher', 'Bear Researcher', 'Research Manager'],
    'Trading Team': ['Trader'],
    'Risk Management': ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'],
    'Portfolio Management': ['Portfolio Manager'],
  };

  const ANALYST_NAMES = {
    market: 'Market Analyst',
    social: 'Sentiment Analyst',
    news: 'News Analyst',
    fundamentals: 'Fundamentals Analyst',
  };

  function initAgentGrid() {
    // Build analyst team from selections
    TEAMS['Analyst Team'] = state.selectedAnalysts.map(a => ANALYST_NAMES[a]);

    // Init status
    state.agents = {};
    Object.values(TEAMS).flat().forEach(agent => {
      state.agents[agent] = 'pending';
    });

    renderAgentGrid();
  }

  function renderAgentGrid() {
    const grid = $('#agent-grid');
    grid.innerHTML = '';

    let totalAgents = 0;
    let completedAgents = 0;

    Object.entries(TEAMS).forEach(([team, agents]) => {
      if (agents.length === 0) return;

      const teamLabel = document.createElement('div');
      teamLabel.className = 'agent-team-label';
      teamLabel.textContent = team;
      grid.appendChild(teamLabel);

      agents.forEach(agent => {
        const status = state.agents[agent] || 'pending';
        totalAgents++;
        if (status === 'completed') completedAgents++;

        const row = document.createElement('div');
        row.className = 'agent-row';
        row.id = `agent-${agent.replace(/\s+/g, '-').toLowerCase()}`;

        row.innerHTML = `
          <span class="agent-name">${agent}</span>
          <span class="agent-status ${status}">
            <span class="status-dot"></span>
            ${status === 'in_progress' ? 'analyzing' : status}
          </span>
        `;
        grid.appendChild(row);
      });
    });

    $('#stat-agents').textContent = `${completedAgents}/${totalAgents}`;
  }

  function updateAgentStatus(agent, status) {
    state.agents[agent] = status;
    const row = $(`#agent-${agent.replace(/\s+/g, '-').toLowerCase()}`);
    if (row) {
      const statusEl = row.querySelector('.agent-status');
      statusEl.className = `agent-status ${status}`;
      statusEl.innerHTML = `<span class="status-dot"></span>${status === 'in_progress' ? 'analyzing' : status}`;
    }

    // Update counter
    const total = Object.keys(state.agents).length;
    const completed = Object.values(state.agents).filter(s => s === 'completed').length;
    $('#stat-agents').textContent = `${completed}/${total}`;
  }

  // ---------- WebSocket ----------
  function connectWebSocket(request) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/analysis`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      addMessage('System', 'Connected to analysis server');
      state.ws.send(JSON.stringify(request));
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleWSMessage(msg);
      } catch (e) {
        console.warn('WS parse error:', e);
      }
    };

    state.ws.onerror = () => {
      showToast('Connection error. Please check the server.', 'error');
    };

    state.ws.onclose = (event) => {
      if (state.analysisRunning) {
        addMessage('System', 'Connection closed');
        state.analysisRunning = false;
        clearInterval(state.timerInterval);
      }
    };
  }

  function handleWSMessage(msg) {
    switch (msg.type) {
      case 'agent_status':
        updateAgentStatus(msg.agent, msg.status);
        break;

      case 'report_update':
        updateReport(msg.section, msg.content);
        break;

      case 'message':
        if (msg.content && msg.content.trim()) {
          addMessage(msg.msg_type || 'Agent', msg.content);
        }
        break;

      case 'tool_call':
        addMessage('Tool', `${msg.name}: ${truncate(JSON.stringify(msg.args), 100)}`);
        break;

      case 'stats':
        state.stats = { ...state.stats, ...msg };
        updateStatsBar();
        break;

      case 'complete':
        onAnalysisComplete(msg.final_state, msg.rating);
        break;

      case 'approval_pending':
        showExecutionOutcome('pending', `⏳ ${msg.ticker} ${msg.side.toUpperCase()} ${msg.quantity.toFixed(4)} -- awaiting your approval (Telegram or the Trading tab).`);
        break;

      case 'order_placed':
        showExecutionOutcome('placed', `✅ ${msg.ticker} ${msg.side.toUpperCase()} ${msg.quantity.toFixed(4)} -- ${msg.status} (${msg.message || ''})`);
        break;

      case 'error':
        showToast(msg.detail || 'Analysis error occurred', 'error');
        addMessage('Error', msg.detail);
        state.analysisRunning = false;
        clearInterval(state.timerInterval);
        $('#btn-cancel').classList.add('hidden');
        break;

      default:
        console.log('Unknown WS message type:', msg.type);
    }
  }

  // ---------- Reports ----------
  const SECTION_TITLES = {
    market_report: 'Market Analysis',
    sentiment_report: 'Social Sentiment',
    news_report: 'News Analysis',
    fundamentals_report: 'Fundamentals Analysis',
    investment_plan: 'Research Team Decision',
    trader_investment_plan: 'Trading Team Plan',
    final_trade_decision: 'Portfolio Management Decision',
  };

  function updateReport(section, content) {
    state.reports[section] = content;

    // Update report count
    const total = Object.keys(SECTION_TITLES).filter(s =>
      state.selectedAnalysts.some(a => {
        if (s === 'market_report') return a === 'market';
        if (s === 'sentiment_report') return a === 'social';
        if (s === 'news_report') return a === 'news';
        if (s === 'fundamentals_report') return a === 'fundamentals';
        return true;
      }) || ['investment_plan', 'trader_investment_plan', 'final_trade_decision'].includes(s)
    ).length;
    const filled = Object.keys(state.reports).length;
    $('#stat-reports').textContent = `${filled}/${total}`;
    $('#report-progress').textContent = `${filled} / ${total}`;

    // Render latest report
    renderLiveReport();
  }

  function renderLiveReport() {
    const container = $('#report-content');
    let html = '';

    Object.entries(state.reports).forEach(([section, content]) => {
      const title = SECTION_TITLES[section] || section;
      html += `<h2>${title}</h2>`;
      html += typeof marked !== 'undefined' ? marked.parse(content) : `<p>${content}</p>`;
    });

    container.innerHTML = html || '<div class="report-placeholder">Waiting for analysis reports...</div>';

    // Auto-scroll to bottom
    container.scrollTop = container.scrollHeight;
  }

  // ---------- Messages Feed ----------
  function addMessage(type, content) {
    const now = new Date();
    const time = now.toTimeString().slice(0, 8);
    const truncated = truncate(content, 200);

    state.messages.unshift({ time, type, content: truncated });
    if (state.messages.length > 100) state.messages.pop();

    const feed = $('#messages-feed');
    const typeClass = type.toLowerCase();
    const row = document.createElement('div');
    row.className = 'msg-row';
    row.innerHTML = `
      <span class="msg-time">${time}</span>
      <span class="msg-type ${typeClass}">${type}</span>
      <span class="msg-content">${escapeHtml(truncated)}</span>
    `;
    feed.insertBefore(row, feed.firstChild);

    // Keep max 50 visible rows
    while (feed.children.length > 50) {
      feed.removeChild(feed.lastChild);
    }
  }

  // ---------- Stats ----------
  function updateStatsBar() {
    $('#stat-llm').textContent = state.stats.llm_calls;
    $('#stat-tools').textContent = state.stats.tool_calls;

    if (state.stats.tokens_in > 0 || state.stats.tokens_out > 0) {
      $('#stat-tokens').textContent = `${formatTokens(state.stats.tokens_in)}↑ ${formatTokens(state.stats.tokens_out)}↓`;
    }
  }

  function updateTimer() {
    if (!state.startTime) return;
    const elapsed = Math.floor((Date.now() - state.startTime) / 1000);
    const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const ss = String(elapsed % 60).padStart(2, '0');
    $('#stat-elapsed').textContent = `${mm}:${ss}`;
  }

  // ---------- Analysis Complete ----------
  function onAnalysisComplete(finalState, rating) {
    state.analysisRunning = false;
    state.finalState = finalState;
    clearInterval(state.timerInterval);
    $('#btn-cancel').classList.add('hidden');
    $('#btn-edit-config').classList.add('hidden');

    // Mark all agents completed
    Object.keys(state.agents).forEach(a => updateAgentStatus(a, 'completed'));

    addMessage('System', '✅ Analysis complete');
    showToast('Analysis completed successfully!', 'success');

    // After a short delay, switch to results
    setTimeout(() => showResults(finalState, rating), 1500);
  }

  function showResults(finalState, rating) {
    // Set header
    const ticker = $('#ticker').value.trim().toUpperCase();
    const date = $('#analysis-date').value;
    $('#results-ticker-date').textContent = `${ticker} • ${date}`;

    // Extract decision. Prefer the pipeline's actual 5-tier rating
    // (agents/utils/rating.py, sent as msg.rating on the 'complete'
    // message) over guessing from report text -- see extractDecision's
    // docstring for why the text-guessing fallback exists at all.
    const decision = extractDecision(finalState, rating);
    const actionEl = $('#decision-action');
    actionEl.textContent = decision.label;
    actionEl.className = `decision-action ${decision.cssClass}`;
    $('#decision-summary').textContent = decision.summary;
    $('#execution-outcome').classList.add('hidden');
    $('#execution-outcome').textContent = '';

    // Build report accordion
    renderResultsReport();

    switchView('results');
  }

  function showExecutionOutcome(kind, text) {
    const el = $('#execution-outcome');
    if (!el) return;
    el.textContent = text;
    el.className = `execution-outcome ${kind}`;
    el.classList.remove('hidden');
  }

  // Maps the pipeline's 5-tier rating (agents/utils/rating.py:RATINGS_5_TIER)
  // onto the existing 3-way badge styling (.decision-action.buy/.hold/.sell).
  const RATING_CSS_CLASS = {
    Buy: 'buy', Overweight: 'buy',
    Hold: 'hold',
    Underweight: 'sell', Sell: 'sell',
  };

  function extractDecision(finalState, rating) {
    const fd = finalState?.final_trade_decision || finalState?.risk_debate_state?.judge_decision || '';
    const text = typeof fd === 'string' ? fd : JSON.stringify(fd);

    // Extract first paragraph as summary (unchanged regardless of rating source)
    const lines = text.split('\n').filter(l => l.trim().length > 20);
    const summary = lines[0] ? truncate(lines[0].replace(/^#+\s*/, ''), 300) : 'Analysis complete. See detailed report below.';

    if (rating && RATING_CSS_CLASS[rating]) {
      return { label: rating.toUpperCase(), cssClass: RATING_CSS_CLASS[rating], summary };
    }

    // Fallback only: the server should always send a rating on 'complete'.
    // This substring guess is a last resort for an older/mismatched server.
    let action = 'HOLD';
    const lower = text.toLowerCase();
    if (lower.includes('"buy"') || lower.includes('action: buy') || lower.includes('decision: buy')) {
      action = 'BUY';
    } else if (lower.includes('"sell"') || lower.includes('action: sell') || lower.includes('decision: sell')) {
      action = 'SELL';
    }
    return { label: action, cssClass: action.toLowerCase(), summary };
  }

  function renderResultsReport() {
    const container = $('#results-report');
    container.innerHTML = '';

    Object.entries(state.reports).forEach(([section, content]) => {
      const title = SECTION_TITLES[section] || section;
      const div = document.createElement('div');
      div.className = 'glass report-section';
      div.innerHTML = `
        <div class="report-section-header" onclick="this.parentElement.classList.toggle('open')">
          <span class="report-section-title">${title}</span>
          <span class="report-section-chevron">▼</span>
        </div>
        <div class="report-section-body">
          <div class="report-section-content">${typeof marked !== 'undefined' ? marked.parse(content) : content}</div>
        </div>
      `;
      container.appendChild(div);
    });
  }

  // ---------- Save Report ----------
  function saveReport() {
    let md = `# TradingAgents Analysis Report\n\n`;
    md += `**Ticker:** ${$('#ticker').value.trim().toUpperCase()}\n`;
    md += `**Date:** ${$('#analysis-date').value}\n\n---\n\n`;

    Object.entries(state.reports).forEach(([section, content]) => {
      const title = SECTION_TITLES[section] || section;
      md += `## ${title}\n\n${content}\n\n---\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `TradingAgents_${$('#ticker').value.trim()}_${$('#analysis-date').value}.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Report saved!', 'success');
  }

  // ---------- Cancel Analysis ----------
  function cancelAnalysis() {
    if (state.ws) {
      state.ws.close();
    }
    state.analysisRunning = false;
    clearInterval(state.timerInterval);
    $('#btn-cancel').classList.add('hidden');
    addMessage('System', 'Analysis cancelled by user');
    showToast('Analysis cancelled', 'warning');
  }

  // ---------- Utilities ----------
  function truncate(str, maxLen) {
    if (!str) return '';
    str = String(str);
    return str.length > maxLen ? str.slice(0, maxLen - 3) + '...' : str;
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function formatTokens(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
  }

  // ---------- Boot ----------
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
