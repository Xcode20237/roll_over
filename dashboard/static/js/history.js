/* history.js — Logique de la page historique */
"use strict";

let currentPage = 1;
let totalResults = 0;
const PAGE_SIZE = 50;

function doSearch(page) {
  currentPage = page || 1;
  const params = new URLSearchParams({
    id: document.getElementById("s-id")?.value || "",
    type: document.getElementById("s-type")?.value || "",
    verdict: document.getElementById("s-verdict")?.value || "",
    defaut: document.getElementById("s-defaut")?.value || "",
    debut: document.getElementById("s-debut")?.value || "",
    fin: document.getElementById("s-fin")?.value || "",
    limite: PAGE_SIZE,
    offset: (currentPage - 1) * PAGE_SIZE,
  });

  fetch(`/api/historique?${params}`)
    .then(r => r.json())
    .then(data => {
      totalResults = data.total || 0;
      renderResults(data.resultats || []);
      renderPagination();
      document.getElementById("results-count").textContent =
        `${totalResults} résultat(s)`;
    })
    .catch(e => console.error("Erreur recherche:", e));
}

function clearSearch() {
  ["s-id", "s-type", "s-debut", "s-fin"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  ["s-verdict", "s-defaut"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  document.getElementById("history-tbody").innerHTML =
    `<tr><td colspan="7" class="empty-msg">Lancez une recherche pour afficher les résultats.</td></tr>`;
  document.getElementById("results-count").textContent = "—";
  document.getElementById("pagination").innerHTML = "";
  totalResults = 0;
}

function renderResults(rows) {
  const tbody = document.getElementById("history-tbody");
  tbody.innerHTML = "";

  if (rows.length === 0) {
    tbody.innerHTML =
      `<tr><td colspan="7" class="empty-msg">Aucun résultat trouvé.</td></tr>`;
    return;
  }

  rows.forEach(row => {
    const verdict = row.verdict || "?";
    const services = Array.isArray(row.services_evalues)
      ? row.services_evalues.join(", ")
      : (row.services_evalues || "");
    const tr = document.createElement("tr");
    tr.className = verdict === "NG" ? "row-ng" : "";
    tr.innerHTML = `
      <td>${row.timestamp_display || ""}</td>
      <td style="font-weight:700">${row.id_bouteille}</td>
      <td>${row.type_bouteille || "?"}</td>
      <td><span class="verdict-badge badge-${verdict.toLowerCase()}">${verdict}</span></td>
      <td style="font-size:12px">${services}</td>
      <td style="color:var(--ng);font-size:12px">${row.raison_ng || ""}</td>
      <td>
        <button class="btn-detail"
          onclick="openDetailDB(${row.id})">Détail</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function openDetailDB(verdict_id) {
  fetch(`/api/verdict/${verdict_id}`)
    .then(r => r.json())
    .then(data => {
      if (data.erreur) { alert(data.erreur); return; }

      // details_json a la structure :
      // { colorimetrique: { status, defauts: [...] },
      //   gradient:       { status, defauts: [...] },
      //   geometrique:    { status, defauts: [...] } }
      //
      // On aplatit tous les défauts de tous les services en un seul tableau
      // pour que openModal() puisse les afficher normalement.
      const defauts = extraireDefautsDepuisDetails(data.details_json);

      const payload = {
        id_bouteille: data.id_bouteille,
        type_bouteille: data.type_bouteille,
        verdict: data.verdict,
        verdict_global: data.verdict,
        timestamp_display: data.timestamp_display,
        raison_ng: data.raison_ng || null,
        duree_s: null,
        defauts: defauts,
      };
      openModal(payload);
    })
    .catch(e => console.error("Erreur détail:", e));
}

/**
 * Extrait et aplatit tous les défauts depuis details_json.
 * Structure attendue :
 *   { colorimetrique: { status, defauts: [...] }, gradient: {...}, ... }
 * Retourne un tableau plat de défauts, chacun avec son id_defaut,
 * label, verdict, mesure, reference, tolerance, ecart, rois.
 */
function extraireDefautsDepuisDetails(details_json) {
  if (!details_json || typeof details_json !== "object") return [];

  const result = [];

  Object.entries(details_json).forEach(([service, svc_data]) => {
    if (!svc_data || typeof svc_data !== "object") return;

    const defauts = svc_data.defauts;
    if (!Array.isArray(defauts)) return;

    defauts.forEach(d => {
      // Copie du défaut en ajoutant le service d'origine pour le modal
      result.push({ ...d, _service: service });
    });
  });

  return result;
}

function renderPagination() {
  const pag = document.getElementById("pagination");
  const pages = Math.ceil(totalResults / PAGE_SIZE);
  pag.innerHTML = "";
  if (pages <= 1) return;

  const addBtn = (label, page, isActive) => {
    const btn = document.createElement("button");
    btn.className = "page-btn" + (isActive ? " active" : "");
    btn.textContent = label;
    if (!isActive) btn.onclick = () => doSearch(page);
    pag.appendChild(btn);
  };

  if (currentPage > 1) addBtn("← Préc.", currentPage - 1, false);

  const start = Math.max(1, currentPage - 2);
  const end = Math.min(pages, currentPage + 2);
  for (let p = start; p <= end; p++) addBtn(p, p, p === currentPage);

  if (currentPage < pages) addBtn("Suiv. →", currentPage + 1, false);
}

function exportCSV() {
  const params = new URLSearchParams({
    id: document.getElementById("s-id")?.value || "",
    type: document.getElementById("s-type")?.value || "",
    verdict: document.getElementById("s-verdict")?.value || "",
    defaut: document.getElementById("s-defaut")?.value || "",
    debut: document.getElementById("s-debut")?.value || "",
    fin: document.getElementById("s-fin")?.value || "",
  });
  window.location.href = `/api/export/csv?${params}`;
}

// Lancer la recherche auto sur le dernier jour au démarrage
document.addEventListener("DOMContentLoaded", () => {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const fmt = d => d.toISOString().slice(0, 16);
  const debut = document.getElementById("s-debut");
  if (debut) debut.value = fmt(today);
  doSearch(1);
});