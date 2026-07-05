// Model Compare — Usage tab. Vanilla JS, zero dependencies.
// Descriptive only: never compute or display a "better/worse" ranking.

const DEFAULT_MODELS = ['Fable 5', 'Opus 4.8', 'Sonnet 5'];

const MODEL_COLOR_VAR = {
  'Fable 5': '--c-fable',
  'Opus 4.8': '--c-opus',
  'Sonnet 5': '--c-sonnet',
  'Sonnet 4.6': '--c-sonnet46',
  'Haiku 4.5': '--c-haiku',
};

function colorForModel(model) {
  const varName = MODEL_COLOR_VAR[model];
  if (varName) return `var(${varName})`;
  return 'var(--c-other)';
}

// ---------- stats helpers ----------

function median(values) {
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const n = sorted.length;
  const mid = Math.floor(n / 2);
  if (n % 2 === 1) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

function mean(values) {
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString('en-US');
  return (Math.round(n * 100) / 100).toLocaleString('en-US');
}

function fmtPct(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return (n * 100).toFixed(1) + '%';
}

function fmtDuration(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  const totalSec = Math.round(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

// Escape a data.json-derived string before interpolating into innerHTML.
// Static template strings we author ourselves do not need this.
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function parseTs(ts) {
  if (!ts) return null;
  const t = Date.parse(ts);
  return Number.isNaN(t) ? null : t;
}

// ---------- app state ----------

let DATA = null;
let visibleModels = new Set(DEFAULT_MODELS);

// ---------- load ----------

async function loadData() {
  let res;
  try {
    res = await fetch('./data.json');
  } catch (e) {
    showLoadError('Could not fetch data.json (network error). Run <code>python3 collect.py</code> first, then serve this directory over http.');
    return;
  }
  if (!res.ok) {
    showLoadError(`data.json returned HTTP ${res.status}. Run <code>python3 collect.py</code> first to generate it.`);
    return;
  }
  try {
    DATA = await res.json();
  } catch (e) {
    showLoadError('data.json is not valid JSON. Re-run <code>python3 collect.py</code>.');
    return;
  }
  if (!DATA || !Array.isArray(DATA.rows)) {
    showLoadError('data.json is missing a "rows" array. Re-run <code>python3 collect.py</code>.');
    return;
  }
  document.getElementById('mainContent').style.display = '';
  document.getElementById('siteNav').style.display = '';
  init();
}

function showLoadError(msg) {
  const el = document.getElementById('loadError');
  el.style.display = '';
  el.innerHTML = `<strong>Could not load data.</strong><br>${msg}<br><code>python3 collect.py &amp;&amp; python3 -m http.server 8850 --directory fable-tools/model-compare</code>`;
}

// ---------- init ----------

function init() {
  buildModelChips();
  populateCategoryOptions();
  renderAll();

  document.getElementById('lastXSelect').addEventListener('change', renderTableSection);
  document.getElementById('dateFrom').addEventListener('change', renderTableSection);
  document.getElementById('dateTo').addEventListener('change', renderTableSection);
  document.getElementById('categorySelect').addEventListener('change', renderTableSection);
  document.getElementById('logScaleToggle').addEventListener('change', renderChart);
  document.getElementById('heatmapNormToggle').addEventListener('change', (e) => {
    heatmapNormalization = e.target.checked ? 'col' : 'row';
    renderHeatmap();
  });

  renderFooter();
}

function renderAll() {
  renderSuggestedUse();
  renderOverview();
  renderShapeCards();
  renderToolMix();
  renderTableSection();
  renderHeatmap();
  renderChart();
  renderToolUsage();
  renderMessagePatterns();
}

function renderFooter() {
  const f = document.getElementById('footerStats');
  const d = DATA;
  f.textContent = `generated ${d.generated_at} · ${d.top_level_files_seen} top-level transcripts seen, ` +
    `${d.files_with_data} with data · ${d.files_nested_scanned} nested subagent files scanned · ` +
    `${d.lines_skipped} lines skipped · ${d.rows.length} (session, model) rows.`;
}

// ---------- model chips ----------

function allModelsSeen() {
  return DATA.models_seen && DATA.models_seen.length ? DATA.models_seen : uniqueModelsFromRows();
}

function uniqueModelsFromRows() {
  const s = new Set(DATA.rows.map(r => r.model));
  return Array.from(s);
}

function buildModelChips() {
  const container = document.getElementById('modelChips');
  container.innerHTML = '';
  const models = allModelsSeen();
  models.forEach(model => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip' + (visibleModels.has(model) ? ' active' : '');
    chip.setAttribute('aria-pressed', visibleModels.has(model) ? 'true' : 'false');
    chip.style.setProperty('--chip-color', colorForModel(model));
    chip.innerHTML = `<span class="dot"></span>${escapeHtml(model)}`;
    chip.dataset.model = model;
    chip.addEventListener('click', () => {
      if (visibleModels.has(model)) {
        visibleModels.delete(model);
      } else {
        visibleModels.add(model);
      }
      buildModelChips();
      renderAll();
      // Rebuild replaces the DOM node — restore keyboard focus to the same chip.
      const rebuilt = container.querySelector(`[data-model="${CSS.escape(model)}"]`);
      if (rebuilt) rebuilt.focus();
    });
    container.appendChild(chip);
  });
}

// ---------- overview cards ----------

function renderOverview() {
  const container = document.getElementById('overviewCards');
  container.innerHTML = '';
  const models = allModelsSeen().filter(m => visibleModels.has(m));

  models.forEach(model => {
    const rows = DATA.rows.filter(r => r.model === model);
    const card = document.createElement('div');
    card.className = 'card';
    card.style.setProperty('--card-color', colorForModel(model));

    if (rows.length === 0) {
      card.innerHTML = `<h3>${escapeHtml(model)}</h3><div class="empty">no sessions</div>`;
      container.appendChild(card);
      return;
    }

    const outputTokens = rows.map(r => r.main.output_tokens);
    const durations = rows.map(r => r.duration_active_ms);
    const userTurns = rows.map(r => r.main.user_turns);

    card.innerHTML = `
      <h3>${escapeHtml(model)}</h3>
      <div class="metric-row"><span class="k">Sessions</span><span class="v">${rows.length}</span></div>
      <div class="metric-row"><span class="k">Median output tokens</span><span class="v">${fmtNum(median(outputTokens))}</span></div>
      <div class="metric-row"><span class="k">Median active duration</span><span class="v">${fmtDuration(median(durations))}</span></div>
      <div class="metric-row"><span class="k">Median user turns</span><span class="v">${fmtNum(median(userTurns))}</span></div>
    `;
    container.appendChild(card);
  });
}

// ---------- comparison table ----------

function populateCategoryOptions() {
  const select = document.getElementById('categorySelect');
  const cats = new Set(DATA.rows.map(r => r.task_category));
  Array.from(cats).sort().forEach(cat => {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = cat;
    select.appendChild(opt);
  });
}

function getFilteredRowsForModel(model, opts) {
  let rows = DATA.rows.filter(r => r.model === model);

  if (opts.category && opts.category !== 'all') {
    rows = rows.filter(r => r.task_category === opts.category);
  }
  if (opts.fromTs !== null) {
    rows = rows.filter(r => {
      const ts = parseTs(r.start_ts);
      return ts !== null && ts >= opts.fromTs;
    });
  }
  if (opts.toTs !== null) {
    rows = rows.filter(r => {
      const ts = parseTs(r.start_ts);
      return ts !== null && ts <= opts.toTs;
    });
  }

  // sort by start_ts descending, then take last-X (= most recent X)
  rows = rows.slice().sort((a, b) => {
    const ta = parseTs(a.start_ts) || 0;
    const tb = parseTs(b.start_ts) || 0;
    return tb - ta;
  });

  if (opts.lastX !== 'all') {
    const n = parseInt(opts.lastX, 10);
    rows = rows.slice(0, n);
  }

  return rows;
}

const TABLE_METRICS = [
  { key: 'main.user_turns', label: 'User turns', section: 'main', get: r => r.main.user_turns },
  { key: 'main.assistant_messages', label: 'Assistant messages', section: 'main', get: r => r.main.assistant_messages },
  { key: 'main.output_tokens', label: 'Output tokens', section: 'main', get: r => r.main.output_tokens },
  { key: 'main.input_tokens', label: 'Fresh input tokens', section: 'main', get: r => r.main.input_tokens },
  { key: 'main.cache_read_tokens', label: 'Cache read tokens', section: 'main', get: r => r.main.cache_read_tokens },
  { key: 'main.cache_creation_tokens', label: 'Cache creation tokens', section: 'main', get: r => r.main.cache_creation_tokens },
  { key: 'duration_active_ms', label: 'Active duration', section: 'main', get: r => r.duration_active_ms, fmt: fmtDuration },
  { key: 'main.tool_calls_total', label: 'Tool calls (total)', section: 'main', get: r => sumToolCalls(r.main.tool_calls) },
  { key: 'main.tool_error_rate', label: 'Tool error rate (pooled)', section: 'main',
    // Pooled per cohort: sum of errors / sum of calls across the cohort's sessions.
    // NOT a median/mean of per-session ratios (those over-weight low-call sessions).
    pooled: rows => {
      const totalCalls = rows.reduce((a, r) => a + sumToolCalls(r.main.tool_calls), 0);
      const totalErrors = rows.reduce((a, r) => a + r.main.tool_errors, 0);
      return totalCalls > 0 ? totalErrors / totalCalls : null;
    }, fmt: fmtPct },
  { key: 'subagent.messages', label: 'Subagent messages', section: 'subagent', get: r => r.subagent.messages },
  { key: 'subagent.output_tokens', label: 'Subagent output tokens', section: 'subagent', get: r => r.subagent.output_tokens },
  { key: 'shape.msgs_per_turn', label: 'Assistant msgs / user turn', section: 'shape',
    get: r => r.main.user_turns ? r.main.assistant_messages / r.main.user_turns : NaN },
  { key: 'shape.tools_per_turn', label: 'Tool calls / user turn', section: 'shape',
    get: r => r.main.user_turns ? sumToolCalls(r.main.tool_calls) / r.main.user_turns : NaN },
  { key: 'shape.verbosity', label: 'Output tokens / assistant msg', section: 'shape',
    get: r => r.main.assistant_messages ? r.main.output_tokens / r.main.assistant_messages : NaN },
  { key: 'shape.subagent_output_share', label: 'Subagent output token share', section: 'shape',
    get: r => (r.main.output_tokens + r.subagent.output_tokens) ? r.subagent.output_tokens / (r.main.output_tokens + r.subagent.output_tokens) : NaN,
    fmt: fmtPct },
  { key: 'shape.cache_reuse', label: 'Cache reuse (context served from cache)', section: 'shape',
    get: r => (r.main.cache_read_tokens + r.main.input_tokens) ? r.main.cache_read_tokens / (r.main.cache_read_tokens + r.main.input_tokens) : NaN,
    fmt: fmtPct },
  { key: 'shape.subagent_active_rate', label: 'Subagent-active session rate', section: 'shape',
    // Cohort-level percentage (share of rows with subagent.messages > 0), not a per-row ratio —
    // computed once per cohort via the pooled path.
    pooled: rows => {
      if (!rows.length) return null;
      return rows.filter(r => r.subagent.messages > 0).length / rows.length;
    }, fmt: fmtPct, pooledCaption: 'share of sessions' },
];

function sumToolCalls(toolCallsMap) {
  if (!toolCallsMap) return 0;
  return Object.values(toolCallsMap).reduce((a, b) => a + b, 0);
}

function renderTableSection() {
  const lastX = document.getElementById('lastXSelect').value;
  const dateFrom = document.getElementById('dateFrom').value;
  const dateTo = document.getElementById('dateTo').value;
  const category = document.getElementById('categorySelect').value;

  const fromTs = dateFrom ? new Date(dateFrom + 'T00:00:00Z').getTime() : null;
  const toTs = dateTo ? new Date(dateTo + 'T23:59:59Z').getTime() : null;

  const models = allModelsSeen().filter(m => visibleModels.has(m));
  const opts = { lastX, fromTs, toTs, category };

  const perModelRows = {};
  models.forEach(model => {
    perModelRows[model] = getFilteredRowsForModel(model, opts);
  });

  // header
  const head = document.getElementById('compareTableHead');
  head.innerHTML = '<th>Metric</th>' + models.map(m => `<th>${escapeHtml(m)}<br><span style="font-weight:400;color:var(--muted)">n=${perModelRows[m].length}</span></th>`).join('');

  // body
  const body = document.getElementById('compareTableBody');
  body.innerHTML = '';

  let currentSection = null;
  TABLE_METRICS.forEach(metric => {
    if (metric.section !== currentSection) {
      currentSection = metric.section;
      const labelRow = document.createElement('tr');
      labelRow.className = 'section-label';
      let label;
      if (currentSection === 'main') label = 'Main (assistant + attributed user turns)';
      else if (currentSection === 'subagent') label = 'Subagent (aggregated separately — never summed into main)';
      else if (currentSection === 'shape') label = 'Shape (per-row ratios, median)';
      else label = currentSection;
      labelRow.innerHTML = `<td colspan="${models.length + 1}">${label}</td>`;
      body.appendChild(labelRow);
    }

    const tr = document.createElement('tr');
    let cells = `<td class="metric-name">${metric.label}</td>`;
    models.forEach(model => {
      const rows = perModelRows[model];
      if (rows.length === 0) {
        cells += `<td class="empty-col">no sessions in range</td>`;
        return;
      }
      const fmtFn = metric.fmt || fmtNum;
      if (metric.pooled) {
        const rate = metric.pooled(rows);
        if (rate === null || Number.isNaN(rate)) {
          cells += `<td class="empty-col">n/a</td>`;
        } else {
          const caption = metric.pooledCaption || 'Σerrors / Σcalls';
          cells += `<td class="metric-value"><span class="median">${fmtFn(rate)}</span><span class="mean">${caption}</span></td>`;
        }
        return;
      }
      const vals = rows.map(metric.get).filter(v => v !== null && v !== undefined && !Number.isNaN(v));
      if (vals.length === 0) {
        cells += `<td class="empty-col">n/a</td>`;
        return;
      }
      const med = median(vals);
      const avg = mean(vals);
      cells += `<td class="metric-value"><span class="median">${fmtFn(med)}</span><span class="mean">mean ${fmtFn(avg)}</span></td>`;
    });
    tr.innerHTML = cells;
    body.appendChild(tr);
  });
}

// ---------- tokens-over-time chart (inline SVG) ----------

function renderChart() {
  const svg = document.getElementById('chart');
  const tooltip = document.getElementById('tooltip');
  const logScale = document.getElementById('logScaleToggle').checked;

  const models = allModelsSeen().filter(m => visibleModels.has(m));
  const points = [];
  models.forEach(model => {
    DATA.rows.filter(r => r.model === model).forEach(r => {
      const ts = parseTs(r.start_ts);
      const val = r.main.output_tokens;
      if (ts === null) return;
      points.push({ model, ts, val, session_id: r.session_id, project: r.project });
    });
  });
  // Log can't plot 0 — such points are clamped to the y-floor (noted in the axis label).
  const zeroClamped = logScale ? points.filter(p => p.val <= 0).length : 0;

  const width = Math.max(900, document.querySelector('.chart-wrap').clientWidth - 32);
  const height = 380;
  const margin = { top: 16, right: 20, bottom: 40, left: 70 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', height);
  svg.innerHTML = '';

  if (points.length === 0) {
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', width / 2);
    text.setAttribute('y', height / 2);
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('class', 'axis-label');
    text.textContent = 'no sessions';
    svg.appendChild(text);
    return;
  }

  const tsExtent = [Math.min(...points.map(p => p.ts)), Math.max(...points.map(p => p.ts))];
  const valMax = Math.max(...points.map(p => p.val));
  // Linear scale is anchored at 0 so point height is proportional to token count.
  // Log scale floor: smallest positive value (zeros are clamped onto this floor).
  const positiveVals = points.map(p => p.val).filter(v => v > 0);
  const logFloor = positiveVals.length ? Math.min(...positiveVals) : 1;

  const xScale = ts => {
    if (tsExtent[1] === tsExtent[0]) return margin.left + innerW / 2;
    return margin.left + ((ts - tsExtent[0]) / (tsExtent[1] - tsExtent[0])) * innerW;
  };

  const yScale = val => {
    if (logScale) {
      const lo = Math.log10(Math.max(logFloor, 1));
      const hi = Math.log10(Math.max(valMax, 1));
      if (hi === lo) return margin.top + innerH / 2;
      const clamped = Math.max(val, logFloor); // zero/negative → floor
      return margin.top + innerH - ((Math.log10(Math.max(clamped, 1)) - lo) / (hi - lo)) * innerH;
    }
    if (valMax === 0) return margin.top + innerH / 2;
    return margin.top + innerH - (val / valMax) * innerH;
  };

  const ns = 'http://www.w3.org/2000/svg';
  function el(tag, attrs) {
    const e = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  }

  // gridlines + y-axis labels (skip a tick label if rounding made it identical to the previous one)
  const yTickCount = 5;
  let prevYLabel = null;
  for (let i = 0; i <= yTickCount; i++) {
    let val;
    if (logScale) {
      const lo = Math.log10(Math.max(logFloor, 1));
      const hi = Math.log10(Math.max(valMax, 1));
      val = Math.pow(10, lo + (hi - lo) * (i / yTickCount));
    } else {
      val = valMax * (i / yTickCount); // linear anchored at 0
    }
    const y = yScale(val);
    svg.appendChild(el('line', { x1: margin.left, x2: margin.left + innerW, y1: y, y2: y, class: 'grid-line' }));
    const labelText = fmtNum(val);
    if (labelText !== prevYLabel) {
      const label = el('text', { x: margin.left - 8, y: y + 3, class: 'axis-label', 'text-anchor': 'end' });
      label.textContent = labelText;
      svg.appendChild(label);
      prevYLabel = labelText;
    }
  }

  // x-axis labels (dates)
  const xTickCount = 6;
  for (let i = 0; i <= xTickCount; i++) {
    const ts = tsExtent[0] + (tsExtent[1] - tsExtent[0]) * (i / xTickCount);
    const x = xScale(ts);
    svg.appendChild(el('line', { x1: x, x2: x, y1: margin.top, y2: margin.top + innerH, class: 'grid-line' }));
    const label = el('text', { x: x, y: margin.top + innerH + 18, class: 'axis-label', 'text-anchor': 'middle' });
    const d = new Date(ts);
    label.textContent = `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
    svg.appendChild(label);
  }

  // axes lines
  svg.appendChild(el('line', { x1: margin.left, x2: margin.left, y1: margin.top, y2: margin.top + innerH, class: 'axis-line' }));
  svg.appendChild(el('line', { x1: margin.left, x2: margin.left + innerW, y1: margin.top + innerH, y2: margin.top + innerH, class: 'axis-line' }));

  const yAxisTitle = el('text', { x: 14, y: margin.top + innerH / 2, class: 'axis-label', transform: `rotate(-90 14 ${margin.top + innerH / 2})`, 'text-anchor': 'middle' });
  let yTitle = 'main output tokens';
  if (logScale) {
    yTitle += zeroClamped > 0 ? ` (log; ${zeroClamped} zero-token sessions at floor)` : ' (log)';
  }
  yAxisTitle.textContent = yTitle;
  svg.appendChild(yAxisTitle);

  const xAxisTitle = el('text', { x: margin.left + innerW / 2, y: height - 4, class: 'axis-label', 'text-anchor': 'middle' });
  xAxisTitle.textContent = 'session start date';
  svg.appendChild(xAxisTitle);

  // points — hoverable AND keyboard-focusable; native SVG <title> covers touch long-press
  points.forEach(p => {
    const cx = xScale(p.ts);
    const cy = yScale(p.val);
    const circle = el('circle', {
      cx, cy, r: 3.5,
      fill: colorForModel(p.model).startsWith('var') ? getComputedColor(p.model) : p.model,
      opacity: 0.75,
      class: 'dot-point',
      tabindex: 0,
      role: 'img',
      'aria-label': `${p.model}, ${fmtNum(p.val)} output tokens, project ${p.project}`,
    });
    const svgTitle = document.createElementNS(ns, 'title');
    svgTitle.textContent = `${p.model} — ${fmtNum(p.val)} output tokens (${p.project})`;
    circle.appendChild(svgTitle);
    const showTooltip = () => {
      tooltip.style.display = 'block';
      tooltip.innerHTML = `
        <div class="tt-row"><span class="k">Model</span><span>${escapeHtml(p.model)}</span></div>
        <div class="tt-row"><span class="k">Session</span><span>${escapeHtml(p.session_id.slice(0, 8))}…</span></div>
        <div class="tt-row"><span class="k">Project</span><span>${escapeHtml(p.project)}</span></div>
        <div class="tt-row"><span class="k">Output tokens</span><span>${fmtNum(p.val)}</span></div>
      `;
    };
    circle.addEventListener('mouseenter', showTooltip);
    circle.addEventListener('focus', () => {
      showTooltip();
      const r = circle.getBoundingClientRect();
      tooltip.style.left = (r.right + 10) + 'px';
      tooltip.style.top = (r.top + 10) + 'px';
    });
    circle.addEventListener('mousemove', (e) => {
      tooltip.style.left = (e.clientX + 14) + 'px';
      tooltip.style.top = (e.clientY + 14) + 'px';
    });
    circle.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
    circle.addEventListener('blur', () => { tooltip.style.display = 'none'; });
    svg.appendChild(circle);
  });

  // legend
  let legendX = margin.left;
  models.forEach(model => {
    const g = el('g', {});
    const dot = el('circle', { cx: legendX + 5, cy: 8, r: 4, fill: getComputedColor(model) });
    const label = el('text', { x: legendX + 14, y: 12, class: 'axis-label' });
    label.textContent = model;
    g.appendChild(dot);
    g.appendChild(label);
    svg.appendChild(g);
    legendX += 16 + model.length * 6.2 + 18;
  });
}

function getComputedColor(model) {
  const varName = MODEL_COLOR_VAR[model];
  const styles = getComputedStyle(document.documentElement);
  if (varName) return styles.getPropertyValue(varName).trim() || '#8b949e';
  return styles.getPropertyValue('--c-other').trim() || '#8b949e';
}

// ---------- tool usage ----------

function renderToolUsage() {
  const container = document.getElementById('toolGrid');
  container.innerHTML = '';
  const models = allModelsSeen().filter(m => visibleModels.has(m));

  models.forEach(model => {
    const rows = DATA.rows.filter(r => r.model === model);
    const panel = document.createElement('div');
    panel.className = 'tool-panel';
    panel.style.setProperty('--panel-color', colorForModel(model));

    if (rows.length === 0) {
      panel.innerHTML = `<h3>${escapeHtml(model)}</h3><div class="empty">no sessions</div>`;
      container.appendChild(panel);
      return;
    }

    const totals = {};
    rows.forEach(r => {
      Object.entries(r.main.tool_calls || {}).forEach(([name, count]) => {
        totals[name] = (totals[name] || 0) + count;
      });
    });

    const entries = Object.entries(totals).sort((a, b) => b[1] - a[1]);
    const top10 = entries.slice(0, 10);
    const rest = entries.slice(10);
    const otherTotal = rest.reduce((a, [, c]) => a + c, 0);

    const display = top10.slice();
    if (otherTotal > 0) display.push(['other', otherTotal]);

    const maxVal = Math.max(...display.map(([, c]) => c), 1);

    let barsHtml = '';
    if (display.length === 0) {
      barsHtml = '<div class="empty">no tool calls recorded</div>';
    } else {
      display.forEach(([name, count]) => {
        const pct = (count / maxVal) * 100;
        const isOther = name === 'other';
        barsHtml += `
          <div class="bar-row">
            <span class="bar-label${isOther ? ' is-other' : ''}">${escapeHtml(name)}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${pct}%;--bar-color:${getComputedColor(model)}"></div></div>
            <span class="bar-num">${count}</span>
          </div>
        `;
      });
    }

    panel.innerHTML = `<h3>${escapeHtml(model)}</h3><div class="bars">${barsHtml}</div>`;
    container.appendChild(panel);
  });
}

// ---------- v2 P0 metrics (render-only, pure functions of existing data.json fields) ----------

// A2. Tool mix classification. First match wins: named tools checked before mcp__* wildcards.
const TOOL_CLASS_RULES = [
  ['Read', 'explore'], ['Grep', 'explore'], ['Glob', 'explore'], ['LS', 'explore'],
  ['NotebookRead', 'explore'], ['ToolSearch', 'explore'], ['WebFetch', 'explore'], ['WebSearch', 'explore'],
  ['Edit', 'edit'], ['Write', 'edit'], ['MultiEdit', 'edit'], ['NotebookEdit', 'edit'], ['Artifact', 'edit'],
  ['Bash', 'execute'], ['BashOutput', 'execute'], ['KillBash', 'execute'], ['KillShell', 'execute'],
  ['Task', 'orchestrate'], ['Agent', 'orchestrate'], ['SendMessage', 'orchestrate'],
];
const TOOL_CLASS_WILDCARDS = [
  [/mcp__.*read.*/i, 'explore'], [/mcp__.*search.*/i, 'explore'], [/mcp__.*list.*/i, 'explore'], [/mcp__.*get.*/i, 'explore'], [/mcp__.*fetch.*/i, 'explore'],
  [/mcp__.*create.*/i, 'edit'], [/mcp__.*update.*/i, 'edit'], [/mcp__.*edit.*/i, 'edit'], [/mcp__.*write.*/i, 'edit'],
  [/.*ExitPlanMode.*/i, 'orchestrate'], [/mcp__.*spawn.*/i, 'orchestrate'],
];
const TOOL_CLASSES = ['explore', 'edit', 'execute', 'orchestrate', 'other'];
const TOOL_CLASS_LABEL = { explore: 'Explore', edit: 'Edit', execute: 'Execute', orchestrate: 'Orchestrate', other: 'Other' };

function classifyTool(name) {
  const exact = TOOL_CLASS_RULES.find(([n]) => n === name);
  if (exact) return exact[1];
  const wc = TOOL_CLASS_WILDCARDS.find(([re]) => re.test(name));
  if (wc) return wc[1];
  return 'other';
}

// A1. Interaction shape: per-row ratios with zero guard (user_turns == 0 excluded, count reported).
function computeShapeRatios(rows) {
  let excludedTurns = 0;
  const msgsPerTurn = [];
  const toolsPerTurn = [];
  rows.forEach(r => {
    const turns = r.main.user_turns;
    if (!turns) { excludedTurns++; return; }
    msgsPerTurn.push(r.main.assistant_messages / turns);
    toolsPerTurn.push(sumToolCalls(r.main.tool_calls) / turns);
  });
  // one-shot rate: share of rows (with user_turns != 0) where user_turns == 1
  const eligible = rows.filter(r => r.main.user_turns);
  const oneShotRate = eligible.length ? eligible.filter(r => r.main.user_turns === 1).length / eligible.length : null;
  return {
    msgsPerTurnMedian: median(msgsPerTurn),
    toolsPerTurnMedian: median(toolsPerTurn),
    oneShotRate,
    excludedTurns,
    n: rows.length,
  };
}

// A5. Verbosity: output tokens / assistant message, per row, median. Zero guard: assistant_messages == 0 excluded.
function computeVerbosity(rows) {
  let excluded = 0;
  const vals = [];
  rows.forEach(r => {
    if (!r.main.assistant_messages) { excluded++; return; }
    vals.push(r.main.output_tokens / r.main.assistant_messages);
  });
  return { median: median(vals), excluded };
}

// A3. Delegation propensity.
function computeDelegation(rows) {
  let excludedOutputShare = 0;
  const shares = [];
  rows.forEach(r => {
    const denom = r.main.output_tokens + r.subagent.output_tokens;
    if (!denom) { excludedOutputShare++; return; }
    shares.push(r.subagent.output_tokens / denom);
  });
  const activeCount = rows.filter(r => r.subagent.messages > 0).length;
  return {
    subagentOutputShareMedian: median(shares),
    excludedOutputShare,
    subagentActiveRate: rows.length ? activeCount / rows.length : null,
  };
}

// A4. Cache reuse (P1, included in table per spec §D item 6).
function computeCacheReuse(rows) {
  let excluded = 0;
  const vals = [];
  rows.forEach(r => {
    const denom = r.main.cache_read_tokens + r.main.input_tokens;
    if (!denom) { excluded++; return; }
    vals.push(r.main.cache_read_tokens / denom);
  });
  return { median: median(vals), excluded };
}

// A2. Tool mix: per-model % across 5 classes.
function computeToolMix(rows) {
  const totals = { explore: 0, edit: 0, execute: 0, orchestrate: 0, other: 0 };
  let grand = 0;
  rows.forEach(r => {
    Object.entries(r.main.tool_calls || {}).forEach(([name, count]) => {
      const cls = classifyTool(name);
      totals[cls] += count;
      grand += count;
    });
  });
  if (grand === 0) return null;
  const pct = {};
  TOOL_CLASSES.forEach(c => { pct[c] = (totals[c] / grand) * 100; });
  return { pct, totals, grand };
}

// A6. Category x model usage-share matrix.
function computeCategoryMatrix(models, allRows, normalization) {
  const categories = Array.from(new Set(allRows.map(r => r.task_category))).sort();
  const matrix = {}; // model -> category -> pct
  models.forEach(model => {
    const rows = allRows.filter(r => r.model === model);
    matrix[model] = {};
    if (normalization === 'row') {
      const total = rows.length;
      categories.forEach(cat => {
        const c = rows.filter(r => r.task_category === cat).length;
        matrix[model][cat] = total ? (c / total) * 100 : null;
      });
    }
  });
  if (normalization === 'col') {
    const modelSet = new Set(models);
    categories.forEach(cat => {
      // Denominator is the sum over VISIBLE models only, so the rendered columns
      // (which only show `models`) sum to 100% — rows from hidden models must not
      // silently inflate the denominator.
      const rowsInCat = allRows.filter(r => r.task_category === cat && modelSet.has(r.model));
      const total = rowsInCat.length;
      models.forEach(model => {
        const c = rowsInCat.filter(r => r.model === model).length;
        matrix[model][cat] = total ? (c / total) * 100 : null;
      });
    });
  }
  return { categories, matrix };
}

// A7 helpers: autonomy phrase bin, tool class phrase.
function autonomyPhrase(msgsPerTurnMedian) {
  if (msgsPerTurnMedian === null || Number.isNaN(msgsPerTurnMedian)) return null;
  if (msgsPerTurnMedian < 2) return 'a short exchange';
  if (msgsPerTurnMedian <= 5) return 'a few steps';
  return 'an extended run';
}

const TOOL_CLASS_PHRASE = {
  explore: 'toward reading and searching',
  edit: 'toward writing and editing',
  execute: 'toward running commands',
  orchestrate: 'toward delegating to subagents',
  other: 'toward mixed tooling',
};

function dominantToolClass(pct) {
  if (!pct) return null;
  let best = null;
  TOOL_CLASSES.forEach(c => {
    if (best === null || pct[c] > pct[best]) best = c;
  });
  return best;
}

// ---------- render: shape cards (A1 + A5) ----------

function renderShapeCards() {
  const container = document.getElementById('shapeCards');
  if (!container) return;
  container.innerHTML = '';
  const models = allModelsSeen().filter(m => visibleModels.has(m));

  models.forEach(model => {
    const rows = DATA.rows.filter(r => r.model === model);
    const card = document.createElement('div');
    card.className = 'card';
    card.style.setProperty('--card-color', colorForModel(model));

    if (rows.length === 0) {
      card.innerHTML = `<h3>${escapeHtml(model)}</h3><div class="empty">no sessions</div>`;
      container.appendChild(card);
      return;
    }

    const shape = computeShapeRatios(rows);
    const verbosity = computeVerbosity(rows);
    const delegation = computeDelegation(rows);

    const excludedNote = shape.excludedTurns > 0
      ? `<div class="metric-row"><span class="k">Rows excluded (0 user turns)</span><span class="v">${shape.excludedTurns}</span></div>`
      : '';

    card.innerHTML = `
      <h3>${escapeHtml(model)}</h3>
      <div class="metric-row"><span class="k">Assistant msgs / user turn (median)</span><span class="v">${fmtNum(shape.msgsPerTurnMedian)}</span></div>
      <div class="metric-row"><span class="k">Tool calls / user turn (median)</span><span class="v">${fmtNum(shape.toolsPerTurnMedian)}</span></div>
      <div class="metric-row"><span class="k">One-shot rate</span><span class="v">${fmtPct(shape.oneShotRate)}</span></div>
      <div class="metric-row"><span class="k">Output tokens / assistant msg (median)</span><span class="v">${fmtNum(verbosity.median)}</span></div>
      <div class="metric-row"><span class="k">Subagent-active session rate</span><span class="v">${fmtPct(delegation.subagentActiveRate)}</span></div>
      ${excludedNote}
    `;
    container.appendChild(card);
  });
}

// ---------- render: tool-mix fingerprint bars (A2) ----------

function renderToolMix() {
  const container = document.getElementById('toolMixBars');
  if (!container) return;
  container.innerHTML = '';
  const models = allModelsSeen().filter(m => visibleModels.has(m));

  models.forEach(model => {
    const rows = DATA.rows.filter(r => r.model === model);
    const row = document.createElement('div');
    row.className = 'tool-mix-row';

    const mix = computeToolMix(rows);
    const heading = document.createElement('h3');
    heading.textContent = model;
    row.appendChild(heading);

    const track = document.createElement('div');
    track.className = 'tool-mix-stack';

    const TOOL_CLASS_COLOR_VAR = {
      explore: '--c-opus', edit: '--c-fable', execute: '--good', orchestrate: '--c-sonnet', other: '--muted',
    };

    if (!mix) {
      // Zero total tool calls for this model: show all 5 classes as undefined ("—"),
      // not a single collapsed dash — the cohort has a defined class set, just no data.
      track.innerHTML = TOOL_CLASSES.map(cls => `<span class="empty">${TOOL_CLASS_LABEL[cls]}: —</span>`).join(' ');
    } else {
      TOOL_CLASSES.forEach(cls => {
        const pct = mix.pct[cls];
        if (pct <= 0) return;
        const seg = document.createElement('div');
        seg.className = 'tool-mix-seg';
        seg.style.width = pct + '%';
        seg.style.background = `var(${TOOL_CLASS_COLOR_VAR[cls]})`;
        seg.title = `${TOOL_CLASS_LABEL[cls]}: ${pct.toFixed(1)}%`;
        seg.textContent = pct >= 8 ? pct.toFixed(0) + '%' : '';
        track.appendChild(seg);
      });
    }
    row.appendChild(track);

    if (mix) {
      const legend = document.createElement('div');
      legend.className = 'tool-mix-legend';
      legend.innerHTML = TOOL_CLASSES.map(cls =>
        `<span><span class="sw" style="background:var(${TOOL_CLASS_COLOR_VAR[cls]})"></span>${TOOL_CLASS_LABEL[cls]} ${mix.pct[cls].toFixed(1)}%</span>`
      ).join('');
      row.appendChild(legend);
    } else {
      const legend = document.createElement('div');
      legend.className = 'tool-mix-legend';
      legend.innerHTML = TOOL_CLASSES.map(cls =>
        `<span><span class="sw" style="background:var(${TOOL_CLASS_COLOR_VAR[cls]})"></span>${TOOL_CLASS_LABEL[cls]} —</span>`
      ).join('');
      row.appendChild(legend);
    }

    container.appendChild(row);
  });
}

// ---------- render: category x model heatmap (A6) ----------

let heatmapNormalization = 'row';

function renderHeatmap() {
  const container = document.getElementById('heatmapSection');
  if (!container) return;
  const models = allModelsSeen().filter(m => visibleModels.has(m));
  const { categories, matrix } = computeCategoryMatrix(models, DATA.rows, heatmapNormalization);

  const head = document.getElementById('heatmapTableHead');
  const body = document.getElementById('heatmapTableBody');

  head.innerHTML = '<th>Model</th>' + categories.map(c => `<th>${escapeHtml(c)}</th>`).join('');
  body.innerHTML = '';

  models.forEach(model => {
    const tr = document.createElement('tr');
    let cells = `<td class="metric-name">${escapeHtml(model)}</td>`;
    categories.forEach(cat => {
      const pct = matrix[model][cat];
      if (pct === null || pct === undefined) {
        cells += `<td class="empty-col">—</td>`;
      } else {
        const alpha = Math.min(0.85, pct / 100 + 0.06);
        // Accent comes from the CSS token, not a pinned literal; above ~45% fill the
        // orange is mid-luminance, where light text fails contrast — switch to dark text.
        const darkText = alpha > 0.45 ? ' is-hot' : '';
        const mixPct = Math.round(alpha * 100);
        cells += `<td><div class="heatmap-cell${darkText}" style="background: color-mix(in srgb, var(--accent) ${mixPct}%, transparent)">${pct.toFixed(1)}%</div></td>`;
      }
    });
    tr.innerHTML = cells;
    body.appendChild(tr);
  });

}

// ---------- render: suggested-use panel (A7) — binding wording, verbatim template ----------

function renderSuggestedUse() {
  const container = document.getElementById('suggestedUseCards');
  if (!container) return;
  container.innerHTML = '';
  const models = allModelsSeen().filter(m => visibleModels.has(m));

  models.forEach(model => {
    const rows = DATA.rows.filter(r => r.model === model);
    const card = document.createElement('div');
    card.className = 'card suggested-use-card';
    card.style.setProperty('--card-color', colorForModel(model));

    if (rows.length === 0) {
      card.innerHTML = `<h3>${escapeHtml(model)}</h3><div class="empty">no sessions</div>`;
      container.appendChild(card);
      return;
    }

    const { categories, matrix } = computeCategoryMatrix([model], DATA.rows, 'row');
    const shares = categories
      .map(cat => ({ cat, pct: matrix[model][cat] }))
      .filter(c => c.pct !== null && c.pct > 0)
      .sort((a, b) => b.pct - a.pct);

    const mix = computeToolMix(rows);
    const domClass = dominantToolClass(mix ? mix.pct : null);
    const toolPhrase = domClass ? TOOL_CLASS_PHRASE[domClass] : 'toward mixed tooling';

    const shape = computeShapeRatios(rows);
    const autonomy = autonomyPhrase(shape.msgsPerTurnMedian);

    let catSentence;
    if (shares.length === 0) {
      catSentence = `In your usage, sessions on ${escapeHtml(model)} did not have a clear category breakdown.`;
    } else if (shares.length === 1) {
      catSentence = `In your usage, sessions on ${escapeHtml(model)} most often looked like ${escapeHtml(shares[0].cat)} (${shares[0].pct.toFixed(0)}%).`;
    } else {
      catSentence = `In your usage, sessions on ${escapeHtml(model)} most often looked like ${escapeHtml(shares[0].cat)} (${shares[0].pct.toFixed(0)}%) and ${escapeHtml(shares[1].cat)} (${shares[1].pct.toFixed(0)}%).`;
    }

    // Undefined ratio (e.g. all rows in this cohort have user_turns == 0) must render
    // as the dash convention used elsewhere on this page — never silently fall back to
    // the "a short exchange" bin, which would misrepresent an undefined value as data.
    const autonomyText = autonomy || '—';

    card.innerHTML = `
      <h3>${escapeHtml(model)}</h3>
      <p class="suggested-text">
        ${catSentence}
        These sessions leaned ${toolPhrase} and averaged ${autonomyText} per prompt.
        Based on ${rows.length} session(s).
      </p>
    `;
    container.appendChild(card);
  });
}

// ---------- v2 P1 metrics (COLLECT-tier; needs schema_version >= 2 fields) ----------

function hasV2Data() {
  return !!(DATA && DATA.schema_version >= 2);
}

// A9. stop_reason distribution: pooled counts across the cohort's rows,
// normalized to a %-of-total map. Pooled (not per-row median) — this is a
// distribution over lines, not a per-row ratio.
function computeStopReasonMix(rows) {
  const totals = {};
  let grand = 0;
  rows.forEach(r => {
    const sr = r.main.stop_reasons || {};
    Object.entries(sr).forEach(([key, count]) => {
      totals[key] = (totals[key] || 0) + count;
      grand += count;
    });
  });
  if (grand === 0) return null;
  const entries = Object.entries(totals)
    .map(([key, count]) => ({ key, count, pct: (count / grand) * 100 }))
    .sort((a, b) => b.count - a.count);
  return { entries, grand };
}

// A10. Thinking block frequency: thinking_messages / assistant_messages per
// row, median across cohort. Zero guard: assistant_messages == 0 excluded.
function computeThinkingFrequency(rows) {
  let excluded = 0;
  const vals = [];
  rows.forEach(r => {
    if (!r.main.assistant_messages) { excluded++; return; }
    if (r.main.thinking_messages === undefined) return; // v1 row, no field
    vals.push(r.main.thinking_messages / r.main.assistant_messages);
  });
  return { median: median(vals), excluded };
}

// A11. text_chars_per_text_block: text_chars / text_blocks per row, median.
// Zero guard: text_blocks == 0 excluded.
function computeTextCharsPerBlock(rows) {
  let excluded = 0;
  const vals = [];
  rows.forEach(r => {
    if (r.main.text_blocks === undefined) return; // v1 row, no field
    if (!r.main.text_blocks) { excluded++; return; }
    vals.push(r.main.text_chars / r.main.text_blocks);
  });
  return { median: median(vals), excluded };
}

// A8. Quick-follow-up cadence: quick_follow_ups / user_turns per row,
// median. "Cadence, not sentiment." Zero guard: user_turns == 0 excluded.
function computeFollowUpCadence(rows) {
  let excluded = 0;
  const quickRateVals = [];
  let totalShort = 0;
  let totalQuick = 0;
  rows.forEach(r => {
    if (r.main.quick_follow_ups === undefined) return; // v1 row
    if (!r.main.user_turns) { excluded++; return; }
    quickRateVals.push(r.main.quick_follow_ups / r.main.user_turns);
    totalQuick += r.main.quick_follow_ups;
    totalShort += r.main.short_quick_follow_ups || 0;
  });
  return {
    quickRateMedian: median(quickRateVals),
    excluded,
    totalQuick,
    totalShort,
  };
}

function renderMessagePatterns() {
  const section = document.getElementById('messagePatternsSection');
  const container = document.getElementById('messagePatternsCards');
  if (!section || !container) return;

  const navLink = document.getElementById('navMessagePatterns');
  if (!hasV2Data()) {
    section.style.display = 'none';
    if (navLink) navLink.style.display = 'none';
    return;
  }
  section.style.display = '';
  if (navLink) navLink.style.display = '';
  container.innerHTML = '';

  const models = allModelsSeen().filter(m => visibleModels.has(m));

  models.forEach(model => {
    const rows = DATA.rows.filter(r => r.model === model);
    const card = document.createElement('div');
    card.className = 'card';
    card.style.setProperty('--card-color', colorForModel(model));

    if (rows.length === 0) {
      card.innerHTML = `<h3>${escapeHtml(model)}</h3><div class="empty">no sessions</div>`;
      container.appendChild(card);
      return;
    }

    const stopMix = computeStopReasonMix(rows);
    const thinking = computeThinkingFrequency(rows);
    const textChars = computeTextCharsPerBlock(rows);
    const followUp = computeFollowUpCadence(rows);

    let stopReasonHtml = '<span class="empty">—</span>';
    if (stopMix) {
      stopReasonHtml = stopMix.entries
        .map(e => `<div class="bar-row"><span class="bar-label">${escapeHtml(e.key)}</span><div class="bar-track"><div class="bar-fill" style="width:${e.pct}%;--bar-color:${getComputedColor(model)}"></div></div><span class="bar-num">${e.pct.toFixed(1)}%</span></div>`)
        .join('');
    }

    card.innerHTML = `
      <h3>${escapeHtml(model)}</h3>
      <div class="metric-row"><span class="k">Thinking block frequency (median)</span><span class="v">${fmtPct(thinking.median)}</span></div>
      <div class="metric-row"><span class="k">Text chars / text block (median)</span><span class="v">${fmtNum(textChars.median)}</span></div>
      <div class="metric-row"><span class="k">Quick follow-up rate (median, cadence not sentiment)</span><span class="v">${fmtPct(followUp.quickRateMedian)}</span></div>
      <div class="metric-row"><span class="k">Quick follow-ups (short / total)</span><span class="v">${followUp.totalShort} / ${followUp.totalQuick}</span></div>
      <div class="sub-heading">stop_reason distribution (pooled)</div>
      <div class="bars">${stopReasonHtml}</div>
    `;
    container.appendChild(card);
  });
}

// ---------- go ----------

loadData();
