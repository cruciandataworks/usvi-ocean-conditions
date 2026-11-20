/* USVI Ocean Conditions - reads the JSON files written by pipeline/step6_export.py */
(async function () {
  const C = { ink: '#0E2A3B', coral: '#C8553D', coralL: '#E8836B', sea: '#2F7F86', seaL: '#8CC2C4', sand: '#D9CBB0', line: '#EFE9DE', muted: '#6B7C89', faint: '#9AA7B1' };
  const GAUGE_COLORS = { '9751639': C.ink, '9751381': C.sea, '9751364': C.coral, '9751401': '#C9A227' };
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const TZ = 'America/St_Thomas';
  const HOUR = 3600e3, DAY = 24 * HOUR;
  const MONTH_START = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];  // day of year

  const [S, tides] = await Promise.all(['summary', 'tides'].map((f) => fetch(`data/${f}.json`).then((r) => r.json()).catch(() => null)));
  if (!S) { document.getElementById('updated').textContent = 'Data files are missing - run the pipeline first.'; return; }

  const nf = (v, d = 2) => v == null ? '–' : Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  const sign = (v, d = 2) => v == null ? '–' : (v > 0 ? '+' : v < 0 ? '−' : '') + nf(Math.abs(v), d);
  const cm = (m) => Math.round(m * 100);
  const local = (iso, opts = {}) => new Date(iso).toLocaleString('en-US', { timeZone: TZ, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', ...opts });
  const dateOnly = (iso) => new Date(iso.length === 10 ? iso + 'T12:00:00Z' : iso).toLocaleDateString('en-US', { timeZone: TZ, month: 'short', day: 'numeric', year: 'numeric' });
  const age = (h) => h == null ? '–' : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} days`;
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  const gauges = S.gauges;
  const byId = Object.fromEntries(gauges.map((g) => [g.id, g]));
  const tideById = Object.fromEntries((tides || []).map((t) => [t.id, t]));
  const region = S.coral_latest.find((c) => c.id === 'usvi');
  let gid = '9751364';   // Christiansted Harbor first: this is a St. Croix company
  let tideDays = 3;

  document.getElementById('updated').textContent = `Checked ${local(S.meta.checked_at)} AST · tide gauges every 6 minutes, coral heat stress daily`;
  document.getElementById('built').textContent = `Pipeline last ran ${local(S.meta.checked_at, { year: 'numeric' })} AST. Verified tide data through ${dateOnly(S.meta.verified_through)}.`;

  /* ---------- Alerts ---------- */
  function renderAlerts() {
    const card = (a) => `<div class="alert ${a.severity}"><span class="sev">${a.severity === 'high' ? 'Alert' : a.severity === 'medium' ? 'Watch' : 'Notice'}</span>
      <div><b>${esc(a.title)}</b><p>${esc(a.message)}</p></div></div>`;
    const main = S.alerts.filter((a) => a.severity !== 'low'), low = S.alerts.filter((a) => a.severity === 'low');
    let html = main.map(card).join('');
    if (!main.length) html += `<div class="alert"><span class="sev">All clear</span><div><b>No active ocean alerts</b><p>No flooding, bleaching heat stress or failing collectors in the latest run.</p></div></div>`;
    if (low.length) html += `<details class="alert-more"><summary>${low.length} data feed notice${low.length > 1 ? 's' : ''} (sensors that have stopped reporting)</summary><div class="alerts">${low.map(card).join('')}</div></details>`;
    document.getElementById('alerts').innerHTML = html;
  }

  /* ---------- Gauge selector + KPIs ---------- */
  const seg = document.getElementById('gaugeSeg');
  seg.innerHTML = gauges.map((g) => `<button role="radio" data-g="${g.id}" aria-checked="${g.id === gid}">${esc(g.name.replace(' Harbor', ''))}</button>`).join('');
  seg.addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    gid = b.dataset.g;
    seg.querySelectorAll('button').forEach((x) => x.setAttribute('aria-checked', x.dataset.g === gid));
    renderGauge();
  });

  function renderKpis() {
    const g = byId[gid];
    const room = g.minor_flood - g.max_24h;
    const fillPct = Math.max(0, Math.min(100, 100 * (g.max_24h + 0.5) / (g.minor_flood + 0.5)));
    const tempStale = g.water_temp_time && (Date.parse(S.meta.checked_at) - Date.parse(g.water_temp_time)) > 2 * DAY;
    const k = [
      ['Water level now', `${sign(g.level)}<small>m</small>`,
        `NOAA predicted ${sign(g.predicted)} m for this hour · reading at ${local(g.time, { month: undefined, day: undefined })} AST`],
      ['Above the tide tables', `${sign(g.residual, 2)}<small>m</small>`,
        `The sea is running ${Math.abs(cm(g.residual))} cm ${g.residual >= 0 ? 'higher' : 'lower'} than predicted - wind, swell, warm water and sea level rise all add up`],
      ['Room before minor flooding', `${nf(room)}<small>m</small>`,
        `Highest in 24 h: ${sign(g.max_24h)} m · minor flood level ${nf(g.minor_flood)} m (${g.flood_source.startsWith('NOAA published') ? 'NOAA' : 'NOAA rule'})`, fillPct, room < 0.15],
      ['Water temperature', tempStale ? '–' : `${nf(g.water_temp, 1)}<small>°C</small>`,
        tempStale ? `Sensor silent since ${dateOnly(g.water_temp_time)}` : `At the gauge, ${local(g.water_temp_time, { month: undefined, day: undefined })} AST`],
      ['Coral heat stress (territory)', `${nf(region.dhw, 1)}<small>DHW</small>`,
        `${esc(region.label)} on ${dateOnly(region.date)} · sea surface ${nf(region.sst, 1)} °C, ${sign(region.ssta, 1)} °C above normal`, Math.min(100, region.dhw / 20 * 100), region.level >= 3],
    ];
    document.getElementById('kpis').innerHTML = k.map(([l, v, note, bar, hot], i) =>
      `<div class="kpi${hot && i === 4 ? ' flag' : ''}"><p class="l">${l}</p><p class="v">${v}</p>${bar != null ? `<div class="bar2"><i class="${hot ? 'hot' : ''}" style="width:${bar.toFixed(0)}%"></i></div>` : ''}<p class="note">${note}</p></div>`).join('');
    document.getElementById('applied').textContent = `${g.name}, ${g.island} · NOAA station ${g.id}`;
  }

  /* ---------- Charts ---------- */
  Chart.defaults.font.family = "'Satoshi', system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.animation.duration = 300;
  Chart.defaults.color = C.muted;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.tooltip.backgroundColor = C.ink;
  Chart.defaults.plugins.tooltip.padding = 10;
  const grid = { color: C.line, drawTicks: false };
  const charts = {};
  const make = (id, cfg) => {
    if (charts[id]) { charts[id].data = cfg.data; charts[id].options = cfg.options; charts[id].update('none'); return; }
    charts[id] = new Chart(document.getElementById(id), cfg);
  };
  // draws dashed horizontal reference lines and an optional "now" marker
  const refLines = {
    id: 'refLines',
    afterDatasetsDraw(chart, _a, o) {
      const { ctx, chartArea: a, scales: { x, y } } = chart;
      ctx.save();
      (o.lines || []).forEach((l) => {
        const py = y.getPixelForValue(l.y); if (py < a.top || py > a.bottom) return;
        ctx.strokeStyle = l.color; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.3;
        ctx.beginPath(); ctx.moveTo(a.left, py); ctx.lineTo(a.right, py); ctx.stroke();
        ctx.setLineDash([]); ctx.font = "500 11px 'Satoshi', sans-serif"; ctx.textAlign = 'left';
        const w = ctx.measureText(l.label).width, lx = l.right ? a.right - w - 8 : a.left + 6;
        ctx.fillStyle = 'rgba(255,253,248,.92)'; ctx.fillRect(lx - 3, py - 16, w + 6, 13);
        ctx.fillStyle = l.color; ctx.fillText(l.label, lx, py - 6);
      });
      if (o.now != null) {
        const px = x.getPixelForValue(o.now);
        ctx.fillStyle = 'rgba(14,42,59,.05)'; ctx.fillRect(px, a.top, a.right - px, a.bottom - a.top);
        ctx.strokeStyle = C.ink; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
        ctx.fillStyle = C.ink; ctx.font = "700 11px 'Satoshi', sans-serif"; ctx.textAlign = 'left';
        ctx.fillText('Now · forecast →', px + 6, a.bottom - 8);
      }
      ctx.restore();
    },
  };
  Chart.register(refLines);
  const dayTick = (v) => new Date(v).toLocaleDateString('en-US', { timeZone: TZ, month: 'short', day: 'numeric' });

  function renderTide() {
    const g = byId[gid], t = tideById[gid];
    document.getElementById('tideTitle').textContent = `Water level at ${g.name}`;
    if (!t) return;
    const now = Date.parse(g.time), from = now - tideDays * DAY, to = now + 3 * DAY;
    const obs = [], pred = [];
    t.t.forEach((iso, i) => {
      const x = Date.parse(iso); if (x < from || x > to) return;
      if (t.obs[i] != null) obs.push({ x, y: t.obs[i] });
      if (t.pred[i] != null) pred.push({ x, y: t.pred[i] });
    });
    make('cTide', {
      type: 'line',
      data: { datasets: [
        { label: 'Observed (preliminary)', data: obs, borderColor: C.sea, backgroundColor: C.sea, borderWidth: 1.8, pointRadius: 0, tension: 0 },
        { label: 'NOAA prediction', data: pred, borderColor: C.faint, backgroundColor: C.faint, borderDash: [4, 3], borderWidth: 1.5, pointRadius: 0, tension: 0.3 },
      ] },
      options: {
        maintainAspectRatio: false, parsing: false, normalized: true,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        scales: {
          x: { type: 'linear', min: from, max: to, grid, ticks: { stepSize: DAY, callback: dayTick, maxRotation: 0, autoSkipPadding: 12 } },
          y: { grid, suggestedMin: -0.4, suggestedMax: Math.max(0.6, g.minor_flood + 0.08), ticks: { callback: (v) => `${v.toFixed(1)} m` } },
        },
        plugins: {
          legend: { position: 'top', align: 'end' },
          tooltip: { callbacks: { title: (it) => local(new Date(it[0].parsed.x).toISOString()) + ' AST', label: (it) => `${it.dataset.label}: ${sign(it.parsed.y)} m` } },
          refLines: { now, lines: [
            { y: g.minor_flood, color: C.coral, label: `Minor flood level ${nf(g.minor_flood)} m`, right: true },
            { y: 0, color: C.muted, label: 'MHHW (average daily high tide)', right: true }] },
        },
      },
    });
    const recent = obs.filter((p) => p.x > now - DAY);
    const peak = recent.reduce((m, p) => (p.y > m.y ? p : m), { y: -9 });
    document.getElementById('tideNote').innerHTML = `<b>${g.name}:</b> highest water in the last 24 hours was ${sign(peak.y)} m at ${local(new Date(peak.x).toISOString())} AST, ${Math.round(100 * (g.minor_flood - peak.y))} cm below the minor flood level. Readings run ${Math.abs(cm(g.residual))} cm ${g.residual >= 0 ? 'above' : 'below'} the prediction right now.`;
  }
  document.getElementById('tideToggle').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    tideDays = +b.dataset.d;
    document.querySelectorAll('#tideToggle button').forEach((x) => x.setAttribute('aria-pressed', x === b));
    renderTide();
  });

  function renderCoral() {
    const style = { 2005: [C.sand, 1.5], 2023: [C.seaL, 1.8], 2024: [C.sea, 1.8], 2026: [C.coral, 2.8] };
    make('cCoral', {
      type: 'line',
      data: { datasets: S.coral_years.map((y) => ({
        label: String(y.year), data: y.doy.map((d, i) => ({ x: d, y: y.dhw[i] })),
        borderColor: style[y.year][0], backgroundColor: style[y.year][0], borderWidth: style[y.year][1], pointRadius: 0, tension: 0.2,
      })) },
      options: {
        maintainAspectRatio: false, parsing: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        scales: {
          x: { type: 'linear', min: 1, max: 366, grid,
            afterBuildTicks: (ax) => { ax.ticks = MONTH_START.map((v) => ({ value: v })); },
            ticks: { callback: (v) => MON[MONTH_START.indexOf(v)] ?? '', maxRotation: 0, autoSkip: true } },
          y: { grid, min: 0, suggestedMax: 24, ticks: { stepSize: 4 }, title: { display: true, text: 'Degree heating weeks', color: C.muted } },
        },
        plugins: {
          legend: { position: 'bottom' },
          tooltip: { callbacks: { title: (it) => { const d = new Date(Date.UTC(2026, 0, it[0].parsed.x)); return `${MON[d.getUTCMonth()]} ${d.getUTCDate()}`; }, label: (it) => `${it.dataset.label}: ${nf(it.parsed.y, 1)} DHW` } },
          refLines: { lines: [{ y: 4, color: C.coralL, label: 'Bleaching likely (4)' }, { y: 8, color: C.coral, label: 'Severe bleaching likely (8)' }] },
        },
      },
    });
    const ann = Object.fromEntries(S.coral_annual.map((a) => [a.year, a]));
    const top = [...S.coral_annual].sort((a, b) => b.max_dhw - a.max_dhw).slice(0, 3);
    document.getElementById('coralNote').textContent = `Highest peaks since 1985: ${top.map((a) => `${a.year} (${nf(a.max_dhw, 1)})`).join(', ')}. Days at Alert Level 2 or higher: 2023 ${ann[2023]?.days_a2 ?? 0}, 2024 ${ann[2024]?.days_a2 ?? 0}, ${region.date.slice(0, 4)} so far ${ann[+region.date.slice(0, 4)]?.days_a2 ?? 0}.`;

    const reefs = S.coral_latest;
    document.getElementById('coralSub').textContent = `NOAA Coral Reef Watch, ${dateOnly(region.date)}`;
    document.getElementById('reefs').innerHTML = `<li aria-hidden="true" style="display:block"><div class="scale"><span>0</span><span>4</span><span>8</span><span>12</span><span>16</span><span>20+ DHW</span></div></li>` +
      reefs.map((r) => `<li class="${r.kind === 'coral_region' ? 'region' : ''}"><span class="nm">${esc(r.kind === 'coral_region' ? 'Virgin Islands (regional)' : r.name)}<small>${esc(r.short || r.label)}</small></span>
        <span class="val">${nf(r.dhw, 1)}</span><span class="meter" role="img" aria-label="${nf(r.dhw, 1)} degree heating weeks"><i style="left:${Math.min(100, r.dhw / 20 * 100).toFixed(1)}%"></i></span></li>`).join('');
  }

  function renderSea() {
    const ids = [...new Set(S.sea_level.map((r) => r.id))];
    make('cSea', {
      type: 'line',
      data: { datasets: ids.map((id) => ({
        label: byId[id]?.name || id,
        data: S.sea_level.filter((r) => r.id === id && r.complete).map((r) => ({ x: r.year, y: r.msl })),
        borderColor: GAUGE_COLORS[id], backgroundColor: GAUGE_COLORS[id], borderWidth: 1.8, pointRadius: 2.5, tension: 0.2,
      })) },
      options: {
        maintainAspectRatio: false, parsing: false,
        scales: { x: { type: 'linear', grid, ticks: { stepSize: 2, callback: (v) => String(v) } }, y: { grid, suggestedMin: 0, ticks: { callback: (v) => `${(v * 100).toFixed(0)} cm` } } },
        plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { title: (it) => String(it[0].parsed.x), label: (it) => `${it.dataset.label}: ${sign(it.parsed.y * 100, 0)} cm` } },
          refLines: { lines: [{ y: 0, color: C.muted, label: '1983–2001 mean sea level' }] } },
      },
    });
    const complete = S.sea_level.filter((r) => r.complete);
    const lo = Math.min(...complete.map((r) => r.msl)), hi = Math.max(...complete.map((r) => r.msl));
    document.getElementById('seaNote').textContent = `Every complete year at every gauge sits ${cm(lo)} to ${cm(hi)} cm above the 1983–2001 baseline. Years with less than 90% of hours recorded are left out. The flood levels on this page are measured from MHHW of the same baseline, so today's sea starts closer to them.`;
  }

  function renderTemp() {
    make('cTemp', {
      type: 'line',
      data: { datasets: S.water_temp.map((w) => ({
        label: byId[w.id]?.name || w.id, data: w.d.map((d, i) => ({ x: Date.parse(d + 'T12:00:00Z'), y: w.temp[i] })),
        borderColor: GAUGE_COLORS[w.id], backgroundColor: GAUGE_COLORS[w.id], borderWidth: 1.5, pointRadius: 0, tension: 0.2,
      })) },
      options: {
        maintainAspectRatio: false, parsing: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        scales: { x: { type: 'linear', grid, ticks: { maxTicksLimit: 7, callback: (v) => new Date(v).toLocaleDateString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' }), maxRotation: 0 } },
          y: { grid, ticks: { callback: (v) => `${v}°` } } },
        plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { title: (it) => dateOnly(new Date(it[0].parsed.x).toISOString()), label: (it) => `${it.dataset.label}: ${nf(it.parsed.y, 1)} °C` } } },
      },
    });
    const silent = S.freshness.filter((f) => f.feed === 'water_temp' && f.stale);
    document.getElementById('tempNote').textContent = silent.length
      ? `${silent.map((f) => f.name).join(', ')}: thermometer silent since ${silent.map((f) => dateOnly(f.latest)).join(', ')} - the line simply stops. Values outside 15–40 °C are dropped as sensor errors.`
      : 'Values outside 15–40 °C are dropped as sensor errors.';
  }

  function renderBuoy() {
    const b = S.buoy;
    const off = (Date.parse(S.meta.checked_at) - Date.parse(b.last_waves)) / DAY;
    document.getElementById('buoyStatus').innerHTML = off > 2
      ? `<span class="dot"></span><div><b>Offline for ${Math.round(off)} days</b><p>Last report ${local(b.last_waves, { year: 'numeric' })} AST: waves ${nf(b.last_wave_m, 1)} m, water ${nf(b.last_temp_c, 1)} °C. The pipeline still asks every run; this card turns green when data returns.</p></div>`
      : `<span class="dot ok"></span><div><b>Reporting</b><p>Last report ${local(b.last_waves)} AST: waves ${nf(b.last_wave_m, 1)} m, water ${nf(b.last_temp_c, 1)} °C.</p></div>`;
    const m = S.buoy_monthly;
    const peak = m.reduce((a, r) => (r.max_wave > a.max_wave ? r : a));
    const [py, pm] = peak.month.split('-');
    document.getElementById('buoyFacts').innerHTML = `<div><b>${dateOnly(b.first_waves).replace(/^\w+ \d+, /, '')}</b><span>first report (${dateOnly(b.first_waves)})</span></div>
      <div><b>${(b.wave_rows / 1000).toFixed(0)}k</b><span>hourly wave readings that passed quality control</span></div>
      <div><b>${nf(peak.max_wave, 1)} m</b><span>highest hour on record, ${MON[+pm - 1]} ${py}</span></div>`;
    make('cBuoy', {
      type: 'line',
      data: { labels: m.map((r) => r.month), datasets: [
        { label: 'Monthly mean', data: m.map((r) => r.mean_wave), borderColor: C.sea, backgroundColor: C.sea, borderWidth: 1.6, pointRadius: 0, tension: 0.2 },
        { label: 'Highest hour', data: m.map((r) => r.max_wave), borderColor: C.coralL, backgroundColor: C.coralL, borderWidth: 1.2, pointRadius: 0, tension: 0.2 },
      ] },
      options: {
        maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0, callback(v) { return this.getLabelForValue(v).slice(0, 4); } } },
          y: { grid, beginAtZero: true, ticks: { callback: (v) => `${v} m` } } },
        plugins: { legend: { position: 'top', align: 'end' }, tooltip: { callbacks: { label: (it) => `${it.dataset.label}: ${nf(it.parsed.y, 1)} m` } } },
      },
    });
  }

  function renderFeeds() {
    // one row per feed when every station is on time; stale stations get their own row
    const order = ['tide_6min', 'water_temp', 'tide_verified', 'coral_daily', 'buoy_waves', 'buoy_ocean'];
    const when = (f) => f.feed === 'coral_daily' ? dateOnly(f.latest.slice(0, 10))
      : f.latest.slice(0, 4) === S.meta.checked_at.slice(0, 4) && !f.stale ? local(f.latest) : dateOnly(f.latest);
    const short = (n) => n.replace(/ \(NDBC.*\)/, '').replace(' (regional)', ' (region)');
    const rows = [];
    order.forEach((feed) => {
      const fs = S.freshness.filter((f) => f.feed === feed); if (!fs.length) return;
      const ok = fs.filter((f) => !f.stale), bad = fs.filter((f) => f.stale);
      if (ok.length) {
        const oldest = ok.reduce((a, b) => (b.age_h > a.age_h ? b : a));
        rows.push({ dataset: oldest.dataset, where: ok.length === 1 ? short(ok[0].name) : `${ok.length} ${feed.startsWith('coral') ? 'reef areas' : 'gauges'}`, f: oldest });
      }
      bad.forEach((f) => rows.push({ dataset: f.dataset, where: short(f.name), f }));
    });
    document.querySelector('#tFeeds tbody').innerHTML = rows.map(({ dataset, where, f }) => `<tr><td>${esc(dataset)}</td><td>${esc(where)}</td>
      <td class="n">${when(f)}</td><td class="n">${age(f.age_h)}</td>
      <td>${f.stale ? '<span class="tag warn">Stale</span>' : '<span class="tag good">On time</span>'}</td></tr>`).join('');
    const failing = S.health.filter((h) => h.fails > 0);
    document.getElementById('healthNote').textContent = (failing.length
      ? `${failing.length} collector(s) failed on the latest run: ${failing.map((h) => `${h.source}:${h.feed} (${h.fails} in a row)`).join(', ')}. An alert opens after 4 failures in a row. `
      : `All ${S.health.length} collectors succeeded on the latest run. `) +
      `"On time" means the newest value is younger than the feed's normal update interval (age shown is the oldest station in the row). Verified tides are allowed 100 days because NOAA reviews them by hand.`;
  }

  function renderFinding() {
    const tempOff = S.freshness.find((f) => f.feed === 'water_temp' && f.stale);
    const lo = Math.min(...gauges.map((g) => g.residual)), hi = Math.max(...gauges.map((g) => g.residual));
    const yr = +region.date.slice(0, 4);
    const rank = [...S.coral_annual].sort((a, b) => b.max_dhw - a.max_dhw).findIndex((a) => a.year === yr) + 1;
    const ord = ['', 'highest', 'second-highest', 'third-highest', 'fourth-highest', 'fifth-highest'][rank] || `number ${rank}`;
    document.getElementById('howFinding').innerHTML = `<b>Found along the way:</b> the VI1 wave buoy has sent nothing since ${dateOnly(S.buoy.last_waves)}${tempOff ? `, the ${tempOff.name} thermometer stopped on ${dateOnly(tempOff.latest)}` : ''}, and NOAA's hand-verified record ends ${dateOnly(S.meta.verified_through)}. Right now all four gauges read ${cm(lo)}–${cm(hi)} cm above their tide predictions, and the reefs' peak heat stress in ${yr} is the ${ord} since satellite records began in 1985.`;
  }

  function renderGauge() { renderKpis(); renderTide(); }
  renderAlerts(); renderGauge(); renderCoral(); renderSea(); renderTemp(); renderBuoy(); renderFeeds(); renderFinding();
})();
