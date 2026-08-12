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

    // Detect CLIs on load
    detectCLIs();
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
      if (prefs.cli_paths) {
        state.cliPaths = prefs.cli_paths;
      } else {
        state.cliPaths = {};
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
        cli_paths: state.cliPaths || {},
      }));
    } catch (e) { /* ignore */ }
  }

  // ---------- CLI Detection ----------
  async function detectCLIs() {
    try {
      const resp = await fetch('/api/find-clis');
      if (!resp.ok) throw new Error('Failed to fetch CLIs');
      const data = await resp.json();
      
      const grid = $('#cli-grid');
      grid.innerHTML = '';
      
      const tools = ["claude", "codex", "kimi", "freebuff", "gemini", "kimchi", "opencode"];
      tools.forEach(tool => {
        // Use saved path if it exists, otherwise use detected path
        const path = (state.cliPaths && state.cliPaths[tool]) || data[tool];
        const isFound = !!path;
        
        const item = document.createElement('div');
        item.className = 'cli-item';
        item.innerHTML = `
          <div class="cli-item-header">
            <label class="cli-checkbox-label" style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
              <input type="checkbox" class="cli-enable-checkbox" data-tool="${tool}" ${isFound ? 'checked' : ''}>
              <span class="cli-name">${tool}</span>
            </label>
            <span class="cli-status ${isFound ? 'found' : 'missing'}">${isFound ? 'Found' : 'Not Installed'}</span>
          </div>
          <input type="text" class="cli-input" data-tool="${tool}" value="${path || ''}" placeholder="Path (e.g. C:/bin/${tool}.exe)">
        `;
        
        // Listen to input changes to update state
        const input = item.querySelector('.cli-input');
        input.addEventListener('change', (e) => {
          if (!state.cliPaths) state.cliPaths = {};
          state.cliPaths[tool] = e.target.value.trim();
          savePreferences();
          
          // Update status indicator visually
          const status = item.querySelector('.cli-status');
          if (e.target.value.trim()) {
            status.className = 'cli-status found';
            status.textContent = 'Found';
          } else {
            status.className = 'cli-status missing';
            status.textContent = 'Not Installed';
          }
        });
        
        grid.appendChild(item);
      });
      
    } catch (e) {
      console.warn('Could not detect CLIs:', e);
    }
  }

  // ---------- Config Loading ----------
  async function loadConfig() {
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) throw new Error('Failed to load config');
      state.config = await resp.json();
      populateModels($('#llm-provider').value);
    } catch (e) {
      console.warn('Could not load config:', e);
      // Set fallback models
      populateModelsFallback();
    }
  }

  function populateModels(provider) {
    const deepSelect = $('#deep-model');
    const quickSelect = $('#quick-model');
    deepSelect.innerHTML = '';
    quickSelect.innerHTML = '';

    let models = null;
    if (state.config && state.config.models && state.config.models[provider]) {
      models = state.config.models[provider];
    }

    if (models) {
      (models.deep || []).forEach(m => {
        deepSelect.innerHTML += `<option value="${m}">${m}</option>`;
      });
      (models.quick || []).forEach(m => {
        quickSelect.innerHTML += `<option value="${m}">${m}</option>`;
      });
    } else {
      populateModelsFallback();
    }

    // Update thinking config visibility
    updateThinkingConfig(provider);
  }

  function populateModelsFallback() {
    const defaults = {
      openai: { deep: ['gpt-5.5', 'gpt-5.4', 'o3'], quick: ['gpt-5.4-mini', 'gpt-4.1-mini'] },
      google: { deep: ['gemini-3.5-pro', 'gemini-3.0-pro'], quick: ['gemini-3.5-flash', 'gemini-3.0-flash'] },
      anthropic: { deep: ['claude-opus-4', 'claude-sonnet-4'], quick: ['claude-sonnet-4', 'claude-haiku-3.5'] },
      deepseek: { deep: ['deepseek-r1', 'deepseek-chat'], quick: ['deepseek-chat'] },
      nvidia: { deep: ['meta/llama-3.1-70b-instruct', 'nvidia/llama-3.1-nemotron-70b-instruct'], quick: ['meta/llama-3.1-8b-instruct'] },
      ollama: { deep: ['llama3.3:70b'], quick: ['llama3.3:8b'] },
      openrouter: { deep: ['anthropic/claude-3.5-sonnet', 'openai/gpt-4o'], quick: ['meta-llama/llama-3.1-8b-instruct'] },
      lm_studio: { deep: ['default'], quick: ['default'] },
    };

    const provider = $('#llm-provider').value;
    const models = defaults[provider] || { deep: ['default'], quick: ['default'] };
    const deepSelect = $('#deep-model');
    const quickSelect = $('#quick-model');
    deepSelect.innerHTML = '';
    quickSelect.innerHTML = '';
    models.deep.forEach(m => { deepSelect.innerHTML += `<option value="${m}">${m}</option>`; });
    models.quick.forEach(m => { quickSelect.innerHTML += `<option value="${m}">${m}</option>`; });
  }

  function updateThinkingConfig(provider) {
    const wrap = $('#thinking-config-wrap');
    const label = $('#thinking-config-label');
    const sel = $('#thinking-config');

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

  function toggleBaseUrlVisibility(provider) {
    const wrap = $('#base-url-wrap');
    if (provider === 'openai_compatible' || provider === 'lm_studio' || provider === 'openrouter' || provider === 'nvidia') {
      wrap.classList.remove('hidden');
      if (provider === 'nvidia' && !$('#base-url').value.trim()) {
        $('#base-url').value = 'https://integrate.api.nvidia.com/v1';
      }
    } else {
      wrap.classList.add('hidden');
    }
  }

  // ---------- Event Bindings ----------
  function bindConfigEvents() {
    // Provider change
    $('#llm-provider').addEventListener('change', (e) => {
      populateModels(e.target.value);
      toggleBaseUrlVisibility(e.target.value);
    });

    // Detect CLIs button
    const btnDetectClis = $('#btn-detect-clis');
    if (btnDetectClis) {
      btnDetectClis.addEventListener('click', async () => {
        // Clear saved overrides when auto-detecting manually
        state.cliPaths = {};
        savePreferences();
        btnDetectClis.textContent = 'Detecting...';
        await detectCLIs();
        btnDetectClis.textContent = 'Auto-Detect';
        showToast('CLI detection complete', 'success', 3000);
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
            execution_platform: $('#exec-platform').value,
            alpaca_api_key: $('#alpaca-api-key').value.trim(),
            alpaca_secret_key: $('#alpaca-secret-key').value.trim(),
            ibkr_host: $('#ibkr-host').value.trim(),
            ibkr_port: $('#ibkr-port').value.trim(),
            ccxt_exchange: $('#ccxt-exchange').value,
            ccxt_api_key: $('#ccxt-api-key').value.trim(),
            ccxt_secret_key: $('#ccxt-secret-key').value.trim(),
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
      cli_options: {},
    };

    $$('.cli-enable-checkbox').forEach(cb => {
      if (cb.checked) {
        const tool = cb.dataset.tool;
        const path = cb.closest('.cli-item').querySelector('.cli-input').value.trim();
        request.cli_options[tool] = path || true;
      }
    });

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
        onAnalysisComplete(msg.final_state);
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
  function onAnalysisComplete(finalState) {
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
    setTimeout(() => showResults(finalState), 1500);
  }

  function showResults(finalState) {
    // Set header
    const ticker = $('#ticker').value.trim().toUpperCase();
    const date = $('#analysis-date').value;
    $('#results-ticker-date').textContent = `${ticker} • ${date}`;

    // Extract decision
    const decision = extractDecision(finalState);
    const actionEl = $('#decision-action');
    actionEl.textContent = decision.action;
    actionEl.className = `decision-action ${decision.action.toLowerCase()}`;
    $('#decision-summary').textContent = decision.summary;

    // Build report accordion
    renderResultsReport();

    switchView('results');
  }

  function extractDecision(finalState) {
    // Try to parse the final trade decision for action
    const fd = finalState?.final_trade_decision || finalState?.risk_debate_state?.judge_decision || '';
    const text = typeof fd === 'string' ? fd : JSON.stringify(fd);

    let action = 'HOLD';
    const lower = text.toLowerCase();
    if (lower.includes('"buy"') || lower.includes('action: buy') || lower.includes('decision: buy')) {
      action = 'BUY';
    } else if (lower.includes('"sell"') || lower.includes('action: sell') || lower.includes('decision: sell')) {
      action = 'SELL';
    }

    // Extract first paragraph as summary
    const lines = text.split('\n').filter(l => l.trim().length > 20);
    const summary = lines[0] ? truncate(lines[0].replace(/^#+\s*/, ''), 300) : 'Analysis complete. See detailed report below.';

    return { action, summary };
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
