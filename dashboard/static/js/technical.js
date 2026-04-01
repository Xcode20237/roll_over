/* technical.js — Logique spécifique à la vue technique */
"use strict";

let chartNgEvol  = null;
let chartDefauts = null;
let chartTypes   = null;
let allVerdicts  = [];

// ── Tableaux verdicts ─────────────────────────────────────────────
function renderVerdictsTable(verdicts) {
  allVerdicts = verdicts || [];
  filterVerdicts();
}

function filterVerdicts() {
  const filterType    = document.getElementById("filter-type")?.value    || "";
  const filterVerdict = document.getElementById("filter-verdict")?.value || "";
  const tbody = document.getElementById("verdicts-tbody");
  if (!tbody) return;

  let filtered = allVerdicts;
  if (filterType)    filtered = filtered.filter(v => v.type_bouteille === filterType);
  if (filterVerdict) filtered = filtered.filter(v =>
    (v.verdict || v.verdict_global) === filterVerdict);

  tbody.innerHTML = "";
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-msg">Aucun résultat</td></tr>`;
    return;
  }

  filtered.forEach(v => {
    const verdict = v.verdict || v.verdict_global || "?";
    const ngDefs  = getNgDefauts(v);
    const tr = document.createElement("tr");
    tr.className = verdict === "NG" ? "row-ng" : "";
    tr.onclick   = () => openModal(v);
    tr.innerHTML = `
      <td>${v.timestamp_display || ""}</td>
      <td style="font-weight:700">${v.id_bouteille}</td>
      <td>${v.type_bouteille || "?"}</td>
      <td><span class="verdict-badge badge-${verdict.toLowerCase()}">${verdict}</span></td>
      <td style="color:var(--ng);font-size:12px">${ngDefs}</td>
      <td>${v.duree_s ? v.duree_s + "s" : "—"}</td>
      <td><button class="btn-detail" onclick="event.stopPropagation();openModal(${JSON.stringify(v).replace(/"/g,'&quot;')})">Détail</button></td>
    `;
    tbody.appendChild(tr);
  });

  // Mettre à jour le filtre type
  updateTypeFilter(allVerdicts);
}

function updateTypeFilter(verdicts) {
  const sel = document.getElementById("filter-type");
  if (!sel) return;
  const current = sel.value;
  const types = [...new Set(verdicts.map(v => v.type_bouteille).filter(Boolean))];
  sel.innerHTML = `<option value="">Tous types</option>`;
  types.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    if (t === current) opt.selected = true;
    sel.appendChild(opt);
  });
}

// ── KPI ───────────────────────────────────────────────────────────
function updateKPI(stats) {
  setText("kpi-total",   stats.total);
  setText("kpi-ok",      stats.ok + " (" + stats.taux_ok + "%)");
  setText("kpi-ng",      stats.ng + " (" + stats.taux_ng + "%)");
  setText("kpi-cadence", stats.cadence + "/min");
  setText("kpi-tps",     stats.tps_moyen + "s");
}

// ── Graphiques ────────────────────────────────────────────────────
function initCharts() {
  const ngEvolCtx  = document.getElementById("chart-ng-evolution");
  const defautsCtx = document.getElementById("chart-ng-defauts");
  const typesCtx   = document.getElementById("chart-par-type");

  // Thème sombre partagé
  const gridColor  = "rgba(255,255,255,0.05)";
  const tickColor  = "#4a5568";
  const baseScaleOpts = {
    grid : { color: gridColor },
    ticks: { color: tickColor, font: { family: "'JetBrains Mono', monospace", size: 10 } }
  };

  Chart.defaults.color = "#4a5568";

  if (ngEvolCtx && !chartNgEvol) {
    chartNgEvol = new Chart(ngEvolCtx.getContext("2d"), {
      type: "line",
      data: { labels: [], datasets: [{
        label: "Taux NG (%)",
        data          : [],
        borderColor   : "#ff6b6b",
        backgroundColor: "rgba(255,107,107,0.08)",
        fill: true, tension: 0.4, pointRadius: 2,
        borderWidth: 1.5,
      }]},
      options: {
        responsive: true, animation: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { ...baseScaleOpts, min: 0, max: 100 },
          x: { ...baseScaleOpts, grid: { display: false } }
        }
      }
    });
  }

  if (defautsCtx && !chartDefauts) {
    chartDefauts = new Chart(defautsCtx.getContext("2d"), {
      type: "bar",
      data: { labels: [], datasets: [{
        data           : [],
        backgroundColor: "rgba(255,107,107,0.25)",
        borderColor    : "#ff6b6b",
        borderWidth    : 1,
      }]},
      options: {
        responsive: true, animation: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { ...baseScaleOpts, beginAtZero: true, ticks: { ...baseScaleOpts.ticks, stepSize: 1 } },
          x: { ...baseScaleOpts, grid: { display: false } }
        }
      }
    });
  }

  if (typesCtx && !chartTypes) {
    chartTypes = new Chart(typesCtx.getContext("2d"), {
      type: "doughnut",
      data: { labels: [], datasets: [{
        data: [],
        backgroundColor: ["#75ff9e","#75aaff","#ffb778","#c084fc","#ff6b6b"],
        borderWidth    : 0,
      }]},
      options: {
        responsive: true, animation: false,
        plugins: { legend: {
          position: "bottom",
          labels: { color: "#8892a4", font: { size: 11, family: "'Inter', sans-serif" }, padding: 10 }
        }}
      }
    });
  }
}

function updateCharts(stats) {
  // Évolution NG
  if (chartNgEvol && stats.historique_taux) {
    const hist = stats.historique_taux;
    chartNgEvol.data.labels   = hist.map(h => h.heure);
    chartNgEvol.data.datasets[0].data = hist.map(h => h.taux_ng);
    chartNgEvol.update("none");
  }

  // NG par défaut
  if (chartDefauts && stats.par_defaut) {
    const entries = Object.entries(stats.par_defaut)
      .sort((a,b) => b[1].ng - a[1].ng);
    chartDefauts.data.labels = entries.map(([k,v]) => k);
    chartDefauts.data.datasets[0].data = entries.map(([k,v]) => v.ng);
    chartDefauts.update("none");
  }

  // Par type
  if (chartTypes && stats.par_type) {
    const entries = Object.entries(stats.par_type);
    chartTypes.data.labels = entries.map(([k]) => k);
    chartTypes.data.datasets[0].data = entries.map(([k,v]) => v.total);
    chartTypes.update("none");
  }
}

// ── Config alertes ────────────────────────────────────────────────
function saveConfigAlertes() {
  const cfg = {
    ng_seuil_pct: parseFloat(document.getElementById("cfg-ng-pct")?.value || 10),
    ng_fenetre  : parseInt(document.getElementById("cfg-window")?.value   || 20),
    son_actif   : document.getElementById("cfg-son")?.checked ?? true,
  };
  socket.emit("update_config_alertes", cfg);
}

function loadConfigAlertes(cfg) {
  if (!cfg) return;
  const pct = document.getElementById("cfg-ng-pct");
  const win = document.getElementById("cfg-window");
  const son = document.getElementById("cfg-son");
  if (pct) pct.value   = cfg.ng_seuil_pct;
  if (win) win.value   = cfg.ng_fenetre;
  if (son) son.checked = cfg.son_actif;
}

// ── SocketIO events ───────────────────────────────────────────────
socket.on("init", data => {
  if (data.verdicts) renderVerdictsTable(data.verdicts);
  if (data.stats)  { updateKPI(data.stats); updateCharts(data.stats); }
  if (data.config_alertes) loadConfigAlertes(data.config_alertes);
});

socket.on("verdicts_update", v => renderVerdictsTable(v));
socket.on("stats_update",    s => { updateKPI(s); updateCharts(s); });

socket.on("verdict_final", payload => {
  const verdict = payload.verdict || payload.verdict_global || "?";
  const box = document.getElementById("verdict-live-box");
  if (box) {
    box.className = `verdict-live-box verdict-${verdict.toLowerCase()}`;
    const s = document.getElementById("verdict-live-status");
    if (s) s.textContent = verdict === "OK" ? "✅ OK" : "❌ NG";
  }
});

// ── Init ─────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initCharts();
});
