/* ═══════════════════════════════════════════════════════════════════
   app.js — Logique commune à toutes les pages
   ═══════════════════════════════════════════════════════════════════ */

"use strict";

// ── Connexion SocketIO ────────────────────────────────────────────
const socket = io({ transports: ["websocket", "polling"] });

// ── Traductions FR/EN ─────────────────────────────────────────────
const I18N = {
  fr: {
    total: "Total", taux_ok: "Taux OK", taux_ng: "Taux NG",
    cadence: "Cadence", tps_moyen: "Tps moyen",
    verdict_live: "Verdict en direct", en_cours: "Bouteille en cours",
    services: "État des services", derniers_verdicts: "Derniers verdicts",
    en_attente: "En attente d'une bouteille...",
    pipeline: "Pipeline", statistiques: "Statistiques du jour",
    evolution_ng: "Évolution taux NG (%)", ng_par_defaut: "NG par défaut",
    par_type: "Par type de bouteille", verdicts_recents: "Verdicts récents",
    config_alertes: "Configuration alertes", seuil_ng: "Seuil NG (%)",
    fenetre: "Fenêtre (bouteilles)", son_alerte: "Son d'alerte",
    sauvegarder: "Sauvegarder", filtrer: "Filtrer",
    colorimetrique: "Colorimétrique", gradient: "Gradient",
    geometrique: "Géométrique", decision: "Décision Finale",
    tous_types: "Tous types",
    recherche: "Recherche dans l'historique",
    id_bouteille: "ID Bouteille", type: "Type", verdict: "Verdict",
    defaut: "Défaut", date_debut: "Date début", date_fin: "Date fin",
    rechercher: "Rechercher", effacer: "Effacer",
    resultats: "Résultats", exporter_csv: "Exporter CSV",
    date_heure: "Date / Heure", services: "Services évalués",
    raison: "Raison NG", lancer_recherche: "Lancez une recherche...",
    heure: "Heure", id: "ID", duree: "Durée",
    defauts: "Défauts NG",
  },
  en: {
    total: "Total", taux_ok: "OK Rate", taux_ng: "NG Rate",
    cadence: "Throughput", tps_moyen: "Avg time",
    verdict_live: "Live Verdict", en_cours: "Active Bottle",
    services: "Services Status", derniers_verdicts: "Latest Verdicts",
    en_attente: "Waiting for a bottle...",
    pipeline: "Pipeline", statistiques: "Today's Statistics",
    evolution_ng: "NG Rate over time (%)", ng_par_defaut: "NG by defect",
    par_type: "By bottle type", verdicts_recents: "Recent Verdicts",
    config_alertes: "Alert Settings", seuil_ng: "NG threshold (%)",
    fenetre: "Window (bottles)", son_alerte: "Alert sound",
    sauvegarder: "Save", filtrer: "Filter",
    colorimetrique: "Colorimetric", gradient: "Gradient",
    geometrique: "Geometric", decision: "Final Decision",
    tous_types: "All types",
    recherche: "Search history",
    id_bouteille: "Bottle ID", type: "Type", verdict: "Verdict",
    defaut: "Defect", date_debut: "Start date", date_fin: "End date",
    rechercher: "Search", effacer: "Clear",
    resultats: "Results", exporter_csv: "Export CSV",
    date_heure: "Date / Time", services: "Evaluated services",
    raison: "NG reason", lancer_recherche: "Run a search...",
    heure: "Time", id: "ID", duree: "Duration",
    defauts: "NG Defects",
  }
};

let currentLang = "fr";

function toggleLang() {
  currentLang = currentLang === "fr" ? "en" : "fr";
  document.getElementById("lang-btn").textContent =
    currentLang === "fr" ? "EN" : "FR";
  applyI18n();
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (I18N[currentLang][key]) el.textContent = I18N[currentLang][key];
  });
}

// ── Horloge ───────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById("nav-clock");
  if (el) el.textContent = new Date().toLocaleTimeString("fr-FR");
}
setInterval(updateClock, 1000);
updateClock();

// ── Indicateur MQTT ───────────────────────────────────────────────
socket.on("connect", () => setMqttDot("connecte"));
socket.on("disconnect", () => setMqttDot("deconnecte"));
socket.on("mqtt_status", d => setMqttDot(d.connecte ? "connecte" : "deconnecte"));

function setMqttDot(statut) {
  const dot = document.getElementById("mqtt-dot");
  const lbl = document.getElementById("mqtt-label");
  if (!dot) return;
  dot.querySelector(".dot").className = `dot dot-${statut}`;
  if (lbl) lbl.textContent = "MQTT";
}

// ── Alertes ───────────────────────────────────────────────────────
let currentAlertId = null;

socket.on("alertes_update", alertes => renderAlertes(alertes));

function renderAlertes(alertes) {
  const bar = document.getElementById("alert-bar");
  const msg = document.getElementById("alert-bar-msg");
  if (!bar || !alertes || alertes.length === 0) {
    if (bar) bar.classList.add("hidden");
    return;
  }
  const alerte = alertes[0];
  currentAlertId = alerte.id;
  msg.textContent = `⚠️ [${alerte.timestamp}] ${alerte.message}`;
  bar.classList.remove("hidden");

  if (typeof playAlertSound === "function") playAlertSound();
  else _playAlert();
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("alert-ack-btn");
  if (btn) btn.onclick = () => {
    if (currentAlertId !== null) {
      socket.emit("acquitter_alerte", { id: currentAlertId });
    }
  };
});

function _playAlert() {
  try {
    const audio = document.getElementById("alert-sound");
    if (audio) audio.play().catch(() => { });
  } catch (e) { }
}

// ── Services ──────────────────────────────────────────────────────
const SERVICE_LABELS = {
  orchestrateur  : "Orchestrateur",
  colorimetrique : "Colorimétrique",
  gradient       : "Gradient",
  geometrique    : "Géométrique",
  ia             : "IA",
  decision       : "Décision",
  check_position : "Check Position",
};
const SERVICE_ICONS = {
  orchestrateur  : "🔀",
  colorimetrique : "🎨",
  gradient       : "🌊",
  geometrique    : "📐",
  ia             : "🤖",
  decision       : "⚖️",
  check_position : "🎯",
};

function renderServicesGrid(services) {
  const grid = document.getElementById("services-grid");
  if (!grid) return;
  grid.innerHTML = "";
  const ordre = ["orchestrateur", "check_position", "colorimetrique", "gradient", "geometrique", "ia", "decision"];
  ordre.forEach(nom => {
    const s = services[nom] || { statut: "inconnu" };
    const div = document.createElement("div");
    div.className = `svc-card ${s.statut}`;
    const lat = s.latence_moy_ms ? `${Math.round(s.latence_moy_ms)}ms` : "—";
    div.innerHTML = `
      <div class="svc-dot ${s.statut}"></div>
      <span class="svc-name">${SERVICE_ICONS[nom] || ""} ${SERVICE_LABELS[nom] || nom}</span>
      <span class="svc-lat">${lat}</span>
    `;
    grid.appendChild(div);
  });
}

function updatePipelineNodes(services) {
  Object.entries(services).forEach(([nom, data]) => {
    const node = document.getElementById(`pipe-${nom}`);
    const sText = document.getElementById(`pipe-status-${nom}`);
    const sLat = document.getElementById(`pipe-lat-${nom}`);
    if (node) {
      node.classList.remove("connecte", "deconnecte", "inconnu");
      node.classList.add(data.statut || "inconnu");
    }
    if (sText) sText.textContent = data.statut === "connecte" ? "🟢 Actif" :
      data.statut === "deconnecte" ? "🔴 Hors ligne" : "⚪ Inconnu";
    if (sLat && data.latence_moy_ms)
      sLat.textContent = `${Math.round(data.latence_moy_ms)}ms`;
  });
}

// ── Bouteille active ──────────────────────────────────────────────
let _activeTimer = null;

function renderBouteilleActive(b, containerId) {
  const box = document.getElementById(containerId);
  if (!box) return;

  if (_activeTimer) { clearInterval(_activeTimer); _activeTimer = null; }

  if (!b) {
    box.innerHTML = `<div class="active-idle-msg">
      ${I18N[currentLang]["en_attente"]}</div>`;
    return;
  }

  const debut = b.timestamp;
  function buildContent() {
    const duree = ((Date.now() / 1000) - debut).toFixed(1);
    const rows = Object.entries(b.services).map(([svc, statut]) => {
      const icon = statut === "recu" ? "✅" : statut === "en_attente" ? "⏳" : "—";
      const fill = statut === "recu" ? "100%" : "30%";
      const color = statut === "recu" ? "var(--ok)" : "var(--primary)";
      return `
        <div class="svc-progress-row">
          <span class="svc-progress-name">${SERVICE_ICONS[svc] || ""} ${SERVICE_LABELS[svc] || svc}</span>
          <div class="svc-progress-bar">
            <div class="svc-progress-fill" style="width:${fill};background:${color}"></div>
          </div>
          <span class="svc-status-badge">${icon}</span>
        </div>`;
    }).join("");
    return `
      <div class="active-bottle-content">
        <div class="active-bottle-header">
          <span class="active-btl-id">${b.id}</span>
          <span class="active-btl-type">${b.type}</span>
          <span class="active-btl-timer">${duree}s</span>
        </div>
        <div class="services-progress">${rows}</div>
      </div>`;
  }
  box.innerHTML = buildContent();
  _activeTimer = setInterval(() => { box.innerHTML = buildContent(); }, 500);
}

// ── Verdicts list (opérateur) ─────────────────────────────────────
function renderVerdictsList(verdicts, containerId) {
  const list = document.getElementById(containerId);
  if (!list) return;
  list.innerHTML = "";
  if (!verdicts || verdicts.length === 0) {
    list.innerHTML = `<div class="empty-msg">${I18N[currentLang]["en_attente"]}</div>`;
    return;
  }
  verdicts.forEach(v => {
    const verdict = v.verdict || v.verdict_global || "?";
    const ng_defauts = getNgDefauts(v);
    const row = document.createElement("div");
    row.className = "verdict-row";
    row.onclick = () => openModal(v);
    row.innerHTML = `
      <span class="verdict-badge badge-${verdict.toLowerCase()}">${verdict}</span>
      <span class="verdict-id">${v.id_bouteille}</span>
      <span class="verdict-type">${v.type_bouteille || "?"}</span>
      ${ng_defauts ? `<span class="verdict-defaut">${ng_defauts}</span>` : ""}
      <span class="verdict-time">${v.timestamp_display || ""}</span>
    `;
    list.appendChild(row);
  });
}

// ── Verdict live (opérateur) ──────────────────────────────────────
function updateVerdictLive(payload) {
  const box = document.getElementById("verdict-live-box");
  const status = document.getElementById("verdict-live-status");
  const id_el = document.getElementById("verdict-live-id");
  const type_el = document.getElementById("verdict-live-type");
  if (!box) return;

  const verdict = payload.verdict || payload.verdict_global || "?";
  box.className = `verdict-live-box verdict-${verdict.toLowerCase()}`;
  status.textContent = verdict === "OK" ? "✅ OK" : "❌ NG";
  if (id_el) id_el.textContent = payload.id_bouteille || "";
  if (type_el) type_el.textContent = payload.type_bouteille || "";

  // Flash animation
  box.style.transform = "scale(1.04)";
  setTimeout(() => { box.style.transform = "scale(1)"; }, 250);
}

// ── Stats (opérateur) ─────────────────────────────────────────────
function updateStatsBar(stats) {
  setText("stat-total", stats.total);
  setText("stat-taux-ok", stats.taux_ok + "%");
  setText("stat-taux-ng", stats.taux_ng + "%");
  setText("stat-cadence", stats.cadence + "/min");
  setText("stat-tps", stats.tps_moyen + "s");
}

// ── Utilitaires ───────────────────────────────────────────────────
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

/**
 * Extrait et aplatit tous les défauts depuis le payload.
 * Le payload final MQTT a la structure :
 *   { details: { colorimetrique: { status, defauts:[...] }, gradient: {...} } }
 * Retourne un tableau plat de défauts.
 */
function extraireDefautsDepuisDetails(details_json) {
  if (!details_json || typeof details_json !== "object") return [];
  const result = [];
  Object.entries(details_json).forEach(([service, svc_data]) => {
    if (!svc_data || typeof svc_data !== "object") return;
    const defauts = svc_data.defauts;
    if (!Array.isArray(defauts)) return;
    defauts.forEach(d => result.push({ ...d, _service: service }));
  });
  return result;
}

/**
 * Retourne les id_defaut NG sous forme de chaîne lisible.
 * Supporte les deux structures :
 *   - payload.defauts (tableau plat — après extraction)
 *   - payload.details (dict par service — payload MQTT brut)
 */
function getNgDefauts(payload) {
  const defauts = payload.defauts ||
    extraireDefautsDepuisDetails(payload.details) || [];
  return defauts
    .filter(d => d.verdict === "NG")
    .map(d => d.id_defaut)
    .join(", ");
}

// ── Modal détail ──────────────────────────────────────────────────
function openModal(payload) {
  const overlay = document.getElementById("modal-overlay");
  const title = document.getElementById("modal-title");
  const body = document.getElementById("modal-body");
  if (!overlay) return;

  // Normaliser le payload : s'assurer que payload.defauts est un tableau plat
  // Le payload MQTT brut a payload.details (dict par service)
  // Le payload BDD reconstruit a déjà payload.defauts (tableau plat)
  const payloadNorm = Object.assign({}, payload);
  if (!Array.isArray(payloadNorm.defauts) || payloadNorm.defauts.length === 0) {
    payloadNorm.defauts = extraireDefautsDepuisDetails(
      payload.details || payload.details_json || {}
    );
  }

  const verdict = payloadNorm.verdict || payloadNorm.verdict_global || "?";
  title.innerHTML = `
    <span class="modal-verdict-big ${verdict.toLowerCase()}">${verdict}</span>
    &nbsp; ${payloadNorm.id_bouteille} — ${payloadNorm.type_bouteille || "?"}
  `;
  body.innerHTML = buildModalBody(payloadNorm);
  overlay.classList.remove("hidden");
}

function closeModal() {
  const overlay = document.getElementById("modal-overlay");
  if (overlay) overlay.classList.add("hidden");
}

function buildModalBody(payload) {
  const defauts = payload.defauts || [];
  if (defauts.length === 0) {
    return `<p style="color:var(--text-muted)">Aucun détail disponible.</p>`;
  }

  // Grouper par service (colorimetrique / gradient / geometrique)
  const services = {};
  defauts.forEach(d => {
    const svc = detectService(d.id_defaut);
    if (!services[svc]) services[svc] = [];
    services[svc].push(d);
  });

  let html = `
    <div class="modal-verdict-header">
      <div>
        <div class="modal-meta">
          <strong>ID :</strong> ${payload.id_bouteille} &nbsp;|&nbsp;
          <strong>Type :</strong> ${payload.type_bouteille || "?"} &nbsp;|&nbsp;
          <strong>Durée :</strong> ${payload.duree_s ? payload.duree_s + "s" : "—"} &nbsp;|&nbsp;
          <strong>Heure :</strong> ${payload.timestamp_display || ""}
        </div>
      </div>
    </div>
  `;

  Object.entries(services).forEach(([svc, defs]) => {
    const svcOk = defs.every(d => d.verdict === "OK");
    html += `
      <div class="service-block">
        <div class="service-block-header">
          <span class="service-block-name">${SERVICE_ICONS[svc] || ""} ${SERVICE_LABELS[svc] || svc}</span>
          <span class="verdict-badge badge-${svcOk ? "ok" : "ng"}">${svcOk ? "OK" : "NG"}</span>
        </div>
        <div class="service-block-body">
          ${defs.map(d => buildDefautRow(d)).join("")}
        </div>
      </div>`;
  });
  return html;
}

function buildDefautRow(d) {
  const verdict = d.verdict || "?";
  const ecart = d.ecart != null ? d.ecart : "—";
  const ecartClass = ecart > 0 ? "ecart-pos" : ecart < 0 ? "ecart-neg" : "";
  const tol = d.tolerance ? `[${d.tolerance[0]} – ${d.tolerance[1]}]` : "—";
  return `
    <div class="defaut-row">
      <span class="defaut-id">${d.id_defaut}</span>
      <span class="defaut-label">${d.label || ""}</span>
      <span class="verdict-badge badge-${verdict.toLowerCase()}">${verdict}</span>
      <span class="defaut-mesure">M: ${d.mesure != null ? d.mesure : "—"}</span>
      <span class="defaut-ref">Ref: ${d.reference != null ? d.reference : "—"}</span>
      <span class="defaut-tol">Tol: ${tol}</span>
      <span class="defaut-ecart ${ecartClass}">Δ ${ecart}</span>
    </div>`;
}

function detectService(id_defaut) {
  const col  = ["D3.1", "D3.2", "D3.3", "D2.4", "D4.1", "D4.4"];
  const grd  = ["D2.1", "D2.2"];
  const geo  = ["D1.4", "D1.5", "D4.2"];
  const chk  = ["CP1.1"];
  if (col.includes(id_defaut))  return "colorimetrique";
  if (grd.includes(id_defaut))  return "gradient";
  if (geo.includes(id_defaut))  return "geometrique";
  if (chk.includes(id_defaut))  return "check_position";
  return "ia";
}

// ── Init page opérateur ───────────────────────────────────────────
socket.on("init", data => {
  if (data.bouteille_active)
    renderBouteilleActive(data.bouteille_active, "active-bottle-box");
  if (data.verdicts)
    renderVerdictsList(data.verdicts, "verdicts-list");
  if (data.services) {
    renderServicesGrid(data.services);
    updatePipelineNodes(data.services);
  }
  if (data.stats)
    updateStatsBar(data.stats);
  if (data.alertes)
    renderAlertes(data.alertes);
});

socket.on("bouteille_active", b => {
  renderBouteilleActive(b, "active-bottle-box");
  renderBouteilleActive(b, "active-bottle-tech");
});

socket.on("verdict_final", payload => {
  updateVerdictLive(payload);
});

socket.on("verdicts_update", verdicts => {
  renderVerdictsList(verdicts, "verdicts-list");
});

socket.on("services_update", services => {
  renderServicesGrid(services);
  updatePipelineNodes(services);
});

socket.on("stats_update", stats => {
  updateStatsBar(stats);
});

// ── Check Position ────────────────────────────────────────────────
function renderCheckPosition(data) {
  if (!data) return;
  const panel = document.getElementById("check-position-panel");
  if (!panel) return;

  const verdict = data.verdict;
  const ecart   = data.ecart_px != null ? parseFloat(data.ecart_px) : 0;
  const id_btl  = data.id_bouteille || "—";
  const ts      = data.timestamp   || "";

  if (verdict === null || verdict === undefined) {
    panel.className = "check-panel check-panel-idle";
    panel.innerHTML = `<span class="check-icon">🎯</span>
      <span class="check-label">Check Position</span>
      <span class="check-status check-idle">En attente...</span>`;
    return;
  }

  const isOk = verdict === "OK";
  panel.className = `check-panel ${isOk ? "check-panel-ok" : "check-panel-ng"}`;
  panel.innerHTML = `
    <span class="check-icon">🎯</span>
    <span class="check-label">Check Position</span>
    <span class="check-status">${isOk ? "✅ OK" : "❌ NG — Mauvais positionnement"}</span>
    <span class="check-ecart">Écart : ${ecart >= 0 ? "+" : ""}${ecart.toFixed(1)} px</span>
    <span class="check-meta">${id_btl}  ·  ${ts}</span>
  `;

  // Animation flash rouge si NG
  if (!isOk) {
    panel.style.animation = "none";
    void panel.offsetHeight;
    panel.style.animation = "check-ng-flash 0.6s ease 3";
  }
}

socket.on("check_position_update", data => renderCheckPosition(data));

// ── Init ──────────────────────────────────────────────────────────
socket.on("init", data => {
  if (data.bouteille_active)
    renderBouteilleActive(data.bouteille_active, "active-bottle-box");
  if (data.verdicts)
    renderVerdictsList(data.verdicts, "verdicts-list");
  if (data.services) {
    renderServicesGrid(data.services);
    updatePipelineNodes(data.services);
  }
  if (data.stats)
    updateStatsBar(data.stats);
  if (data.alertes)
    renderAlertes(data.alertes);
  if (data.check_position)
    renderCheckPosition(data.check_position);
});