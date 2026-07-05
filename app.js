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

  renderFooter();
}

function renderAll() {
  renderOverview();
  renderTableSection();
  renderChart();
  renderToolUsage();
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
    const chip = document.createElement('div');
    chip.className = 'chip' + (visibleModels.has(model) ? ' active' : '');
    chip.style.setProperty('--chip-color', colorForModel(model));
    chip.innerHTML = `<span class="dot"></span>${model}`;
    chip.addEventListener('click', () => {
      if (visibleModels.has(model)) {
        visibleModels.delete(model);
      } else {
        visibleModels.add(model);
      }
      buildModelChips();
      renderAll();
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
      card.innerHTML = `<h3>${model}</h3><div class="empty">no sessions in range</div>`;
      container.appendChild(card);
      return;
    }

    const outputTokens = rows.map(r => r.main.output_tokens);
    const durations = rows.map(r => r.duration_active_ms);
    const userTurns = rows.map(r => r.main.user_turns);

    card.innerHTML = `
      <h3>${model}</h3>
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
  { key: 'main.tool_error_rate', label: 'Tool error rate (errors/calls)', section: 'main', get: r => {
      const calls = sumToolCalls(r.main.tool_calls);
      return calls > 0 ? r.main.tool_errors / calls : null;
    }, fmt: fmtPct, isRate: true },
  { key: 'subagent.messages', label: 'Subagent messages', section: 'subagent', get: r => r.subagent.messages },
  { key: 'subagent.output_tokens', label: 'Subagent output tokens', section: 'subagent', get: r => r.subagent.output_tokens },
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
  head.innerHTML = '<th>Metric</th>' + models.map(m => `<th>${m}<br><span style="font-weight:400;color:var(--muted)">n=${perModelRows[m].length}</span></th>`).join('');

  // body
  const body = document.getElementById('compareTableBody');
  body.innerHTML = '';

  let currentSection = null;
  TABLE_METRICS.forEach(metric => {
    if (metric.section !== currentSection) {
      currentSection = metric.section;
      const labelRow = document.createElement('tr');
      labelRow.className = 'section-label';
      const label = currentSection === 'main' ? 'Main (assistant + attributed user turns)' : 'Subagent (aggregated separately — never summed into main)';
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
      const vals = rows.map(metric.get).filter(v => v !== null && v !== undefined && !Number.isNaN(v));
      if (vals.length === 0) {
        cells += `<td class="empty-col">n/a</td>`;
        return;
      }
      const fmtFn = metric.fmt || fmtNum;
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
      if (logScale && val <= 0) return; // log scale can't plot zero/negative
      points.push({ model, ts, val, session_id: r.session_id, project: r.project });
    });
  });

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
    text.textContent = 'no sessions in range';
    svg.appendChild(text);
    return;
  }

  const tsExtent = [Math.min(...points.map(p => p.ts)), Math.max(...points.map(p => p.ts))];
  const valExtent = [Math.min(...points.map(p => p.val)), Math.max(...points.map(p => p.val))];

  const xScale = ts => {
    if (tsExtent[1] === tsExtent[0]) return margin.left + innerW / 2;
    return margin.left + ((ts - tsExtent[0]) / (tsExtent[1] - tsExtent[0])) * innerW;
  };

  const yScale = val => {
    if (logScale) {
      const lo = Math.log10(Math.max(valExtent[0], 1));
      const hi = Math.log10(Math.max(valExtent[1], 1));
      if (hi === lo) return margin.top + innerH / 2;
      return margin.top + innerH - ((Math.log10(Math.max(val, 1)) - lo) / (hi - lo)) * innerH;
    }
    if (valExtent[1] === valExtent[0]) return margin.top + innerH / 2;
    return margin.top + innerH - ((val - valExtent[0]) / (valExtent[1] - valExtent[0])) * innerH;
  };

  const ns = 'http://www.w3.org/2000/svg';
  function el(tag, attrs) {
    const e = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  }

  // gridlines + y-axis labels
  const yTickCount = 5;
  for (let i = 0; i <= yTickCount; i++) {
    let val;
    if (logScale) {
      const lo = Math.log10(Math.max(valExtent[0], 1));
      const hi = Math.log10(Math.max(valExtent[1], 1));
      val = Math.pow(10, lo + (hi - lo) * (i / yTickCount));
    } else {
      val = valExtent[0] + (valExtent[1] - valExtent[0]) * (i / yTickCount);
    }
    const y = yScale(val);
    svg.appendChild(el('line', { x1: margin.left, x2: margin.left + innerW, y1: y, y2: y, class: 'grid-line' }));
    const label = el('text', { x: margin.left - 8, y: y + 3, class: 'axis-label', 'text-anchor': 'end' });
    label.textContent = fmtNum(val);
    svg.appendChild(label);
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
  yAxisTitle.textContent = 'main output tokens' + (logScale ? ' (log)' : '');
  svg.appendChild(yAxisTitle);

  // points
  points.forEach(p => {
    const cx = xScale(p.ts);
    const cy = yScale(p.val);
    const circle = el('circle', {
      cx, cy, r: 3.5,
      fill: colorForModel(p.model).startsWith('var') ? getComputedColor(p.model) : p.model,
      opacity: 0.75,
      class: 'dot-point',
    });
    circle.addEventListener('mouseenter', (e) => {
      tooltip.style.display = 'block';
      tooltip.innerHTML = `
        <div class="tt-row"><span class="k">Model</span><span>${p.model}</span></div>
        <div class="tt-row"><span class="k">Session</span><span>${p.session_id.slice(0, 8)}…</span></div>
        <div class="tt-row"><span class="k">Project</span><span>${p.project}</span></div>
        <div class="tt-row"><span class="k">Output tokens</span><span>${fmtNum(p.val)}</span></div>
      `;
    });
    circle.addEventListener('mousemove', (e) => {
      tooltip.style.left = (e.clientX + 14) + 'px';
      tooltip.style.top = (e.clientY + 14) + 'px';
    });
    circle.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
    });
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
      panel.innerHTML = `<h3>${model}</h3><div class="empty">no sessions in range</div>`;
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
            <span class="bar-label${isOther ? ' is-other' : ''}">${name}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${pct}%;--bar-color:${getComputedColor(model)}"></div></div>
            <span class="bar-num">${count}</span>
          </div>
        `;
      });
    }

    panel.innerHTML = `<h3>${model}</h3><div class="bars">${barsHtml}</div>`;
    container.appendChild(panel);
  });
}

// ---------- go ----------

loadData();
