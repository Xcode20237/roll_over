"use strict";
/**
 * visualisation.js — Onglet Visualisation temps réel
 *
 * Flux complet :
 *  socket "visu_image_brute" → remplace spinner par image brute
 *                              + overlay "traitement en cours"
 *  socket "visu_traitement"  → affiche steps, retire overlay, verdict
 *  Modal focus (clic image)  → toutes les steps en grand + métriques
 */

let _svc = "colorimetrique";
let _recette = null;
let _typeCourant = null;
let _sessionId = null;
let _sessionData = {};
let _urlCache = {};
let _modalDef = null;
let _modalAng = null;

// ── URL présignée (cache 5 min) ────────────────────────────────────
async function urlMinIO(chemin) {
    if (!chemin) return "";
    if (_urlCache[chemin]) return _urlCache[chemin];
    try {
        const r = await fetch(`/api/minio_url?chemin=${encodeURIComponent(chemin)}`);
        const d = await r.json();
        if (d.url) { _urlCache[chemin] = d.url; return d.url; }
    } catch { }
    return "";
}

// ── Sélection service ──────────────────────────────────────────────
function selectService(btn) {
    document.querySelectorAll(".visu-svc-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    _svc = btn.dataset.svc;
    _recette = null; _typeCourant = null; _sessionId = null; _sessionData = {};
    const titleLbl = document.getElementById("visu-service-title");
    if (titleLbl) titleLbl.textContent = "Exemple interface pour " + btn.textContent.trim();
    renderEmpty();
    fetch(`/api/visualisation/derniere?service=${_svc}`)
        .then(r => r.json()).then(d => { if (d && !d.vide) applyTraitement(d); })
        .catch(() => { });
}

// ── Lecture recette ────────────────────────────────────────────────
async function chargerRecette(type) {
    if (_typeCourant === type && _recette) return _recette;
    try {
        const r = await fetch(`/api/recette?service=${_svc}&type=${encodeURIComponent(type)}`);
        const d = await r.json();
        if (d.defauts) { _recette = d; _typeCourant = type; return _recette; }
    } catch { }
    return null;
}

// ── SocketIO ───────────────────────────────────────────────────────
socket.on("visu_image_brute", async payload => {
    updateLiveBadge(payload.service, null);
    if (payload.service !== _svc) return;

    const id = String(payload.id_bouteille || "?");
    const type = payload.type_bouteille;

    if (id !== _sessionId) {
        _sessionId = id; _sessionData = {};
        const rec = await chargerRecette(type);
        buildPlaceholders(rec, id, type);
    }

    if (payload.service === "fusion") {
        updateFusionProgress(payload);
        return;
    }

    const did = payload.id_defaut;
    const ang = String(payload.angle);
    if (!did || ang === "null") return;

    if (!_sessionData[did]) _sessionData[did] = {};
    _sessionData[did][ang] = {
        etat: "image", chemin_brute: payload.chemin_brute || "",
        steps: {}, verdict: null,
        angles_requis: payload.angles_requis || [],
        angles_recus: payload.angles_recus || [],
    };
    await updateCelluleBrute(did, ang, payload);
});

socket.on("visu_traitement", async payload => {
    updateLiveBadge(payload.service, payload.verdict_global);
    if (payload.service !== _svc) return;
    applyTraitement(payload);
});

socket.on("init", () => {
    fetch(`/api/visualisation/derniere?service=${_svc}`)
        .then(r => r.json()).then(d => { if (d && !d.vide) applyTraitement(d); })
        .catch(() => { });
});

// ── État vide ──────────────────────────────────────────────────────
function renderEmpty() {
    el("visu-info-empty")?.classList.remove("hidden");
    el("visu-info-content")?.classList.add("hidden");
    el("visu-body").innerHTML = "";
}

// ── Shorthand getElementById ───────────────────────────────────────
function el(id) { return document.getElementById(id); }

// ── Placeholders depuis recette ────────────────────────────────────
function buildPlaceholders(recette, idBtl, type) {
    showInfoBar(idBtl, type, null, null);
    const body = el("visu-body");
    body.innerHTML = "";

    if (_svc === "fusion") { body.appendChild(buildFusionBlock()); if (window.lucide) lucide.createIcons(); return; }
    if (_svc === "ia") { body.appendChild(buildIABlock()); if (window.lucide) lucide.createIcons(); return; }
    if (_svc === "check_position") { body.appendChild(buildCheckBlock()); if (window.lucide) lucide.createIcons(); return; }

    if (!recette?.defauts) {
        body.innerHTML = `<div class="visu-empty-msg">Recette non disponible pour ${type}</div>`;
        return;
    }

    // Création de la barre de navigation des défauts
    const navBar = document.createElement("div");
    navBar.className = "visu-defect-tabs-nav";
    
    // Conteneur global des contenus de défaut
    const contentArea = document.createElement("div");
    contentArea.className = "visu-defect-tabs-content";

    let firstKey = null;

    recette.defauts.forEach((def, index) => {
        // Tab bouton
        const btn = document.createElement("button");
        btn.className = "visu-defect-tab-btn";
        btn.id = `tab-btn-${def.id_defaut}`;
        btn.innerHTML = `<strong>${def.id_defaut}</strong>: ${def.label || "Défaut"}`;
        
        // Contenu du défaut
        const contentBlock = document.createElement("div");
        contentBlock.className = "visu-defect-tab-pane";
        contentBlock.id = `block-${def.id_defaut}`;
        
        // En-tête du défaut pour garder les méta-données et le verdict global du défaut
        contentBlock.innerHTML = `
          <div class="visu-defect-pane-header">
            <span class="visu-algo-badge">${def.algo || ""}</span>
            <span class="visu-defaut-meta">Étage ${def.etage} · ${def.angles_requis.length} angle(s)</span>
            <span class="verdict-badge badge-ok hidden" id="verdict-${def.id_defaut}">—</span>
          </div>
          <div class="visu-defect-content" id="grid-${def.id_defaut}"></div>
        `;

        const grid = contentBlock.querySelector('[id="grid-' + def.id_defaut + '"]');
        (def.angles_requis || []).forEach(ang => {
            grid.appendChild(buildRowGrid(def.id_defaut, def.etage, ang));
        });

        // Gestion de l'affichage / masquage
        if (index === 0) {
            btn.classList.add("active");
            firstKey = def.id_defaut;
        } else {
            contentBlock.style.display = "none";
        }

        btn.onclick = () => {
            document.querySelectorAll(".visu-defect-tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            document.querySelectorAll(".visu-defect-tab-pane").forEach(p => p.style.display = "none");
            contentBlock.style.display = "block";
        };

        navBar.appendChild(btn);
        contentArea.appendChild(contentBlock);
    });

    body.appendChild(navBar);
    body.appendChild(contentArea);
    
    if (window.lucide) lucide.createIcons();
}

function buildDefautBlock(def) {
    // Rendue obsolète par le système d'onglets, mais on garde pour compatibilité si appelé manuellement
    return document.createElement("div");
}

function buildRowGrid(did, etage, angle) {
    const container = document.createElement("div");
    container.className = "visu-angle-container";
    container.id = `pair-${did}-${angle}`;
    container.innerHTML = `
    <div class="visu-angle-anchor-badge">E${etage}-A${angle}</div>
    <div class="visu-row-grid">
      <!-- 1. Image Brute -->
      <div class="vrg-box">
        <div class="vrg-box-title">Image Brute</div>
        <div class="vrg-box-img visu-spinner-wrap" id="raw-${did}-${angle}">
          <div class="visu-spinner"></div>
        </div>
      </div>
      <!-- 2. Image Traitée (Finale) -->
      <div class="vrg-box">
        <div class="vrg-box-title" id="proc-lbl-${did}-${angle}">Traitement (En attente)</div>
        <div class="vrg-box-img visu-spinner-wrap" id="proc-${did}-${angle}">
          <div class="visu-spinner"></div>
        </div>
      </div>
      <!-- 3. Statut / Mesures -->
      <div class="vrg-box vrg-status-box">
        <div class="vrg-status-title" id="statut-lbl-${did}-${angle}">Analyse en cours...</div>
        <div class="vrg-box-content" id="metrics-${did}-${angle}">
          <div style="display:flex;justify-content:center"><div class="visu-spinner"></div></div>
        </div>
      </div>
    </div>
    `;
    return container;
}

// ── Mise à jour cellule brute ──────────────────────────────────────
async function updateCelluleBrute(did, ang, payload) {
    const wrap = el(`raw-${did}-${ang}`);
    if (!wrap) return;
    const url = await urlMinIO(payload.chemin_brute);
    if (!url) return;

    wrap.innerHTML = `
    <img src="${url}" alt="brute A${ang}"
         onclick="openVisuModal('${did}','${ang}')" style="cursor:pointer">
    <div class="visu-treatment-overlay" id="overlay-${did}-${ang}">
      <div class="visu-spinner visu-spinner-sm"></div>
      <span>Traitement...</span>
    </div>`;

    // Progression dans l'en-tête
    const meta = el(`block-${did}`)?.querySelector(".visu-defaut-meta");
    if (meta) {
        const rec = (payload.angles_recus || []).length;
        const req = (payload.angles_requis || []).length;
        meta.textContent = `Étage · ${rec}/${req} reçus`;
    }
}

// ── Application traitement complet ─────────────────────────────────
async function applyTraitement(payload) {
    const id = String(payload.id_bouteille || "?");
    const type = payload.type_bouteille;

    if (!_recette && type) await chargerRecette(type);
    if (_sessionId !== id) {
        _sessionId = id; _sessionData = {};
        buildPlaceholders(_recette, id, type);
    }
    showInfoBar(id, type, payload.verdict_global, payload.timestamp);

    if (payload.service === "fusion" || payload.chemin_fusion) { await renderFusionResult(payload); return; }
    if (payload.service === "ia" || payload.chemin_annote) { await renderIAResult(payload); return; }
    if (payload.service === "check_position") { await renderCheckResult(payload); return; }

    for (const def of (payload.defauts || [])) {
        const did = def.id_defaut;

        // Verdict badge bloc
        const badge = el(`verdict-${did}`);
        if (badge) {
            badge.textContent = def.verdict || "?";
            badge.className = "verdict-badge " + (def.verdict === "NG" ? "badge-ng" : "badge-ok");
            badge.classList.remove("hidden");
            el(`block-${did}`)?.classList.toggle("ng", def.verdict === "NG");
        }

        // Angles
        for (const [angStr, angData] of Object.entries(def.angles_visu || {})) {
            // Retirer overlay traitement
            el(`overlay-${did}-${angStr}`)?.remove();

            // Remplir Metrics
            const mWrap = el(`metrics-${did}-${angStr}`);
            const statLbl = el(`statut-lbl-${did}-${angStr}`);
            if (mWrap) {
                const isNg = def.verdict === "NG";
                if (statLbl) {
                    statLbl.textContent = def.verdict || "OK";
                    statLbl.style.color = isNg ? "var(--ng)" : "var(--ok)";
                }
                
                let h = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">`;
                if (def.mesure !== undefined && def.mesure !== null) {
                    h += `<div style="background:var(--surface-low);padding:8px;border-radius:4px;">
                            <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase">Mesure</div>
                            <div style="font-size:14px;font-family:var(--font-data);color:var(--text-primary)">
                                ${Number.isInteger(def.mesure) ? def.mesure : parseFloat(def.mesure).toFixed(3)}
                            </div>
                          </div>`;
                }
                if (def.tolerance) {
                    h += `<div style="background:var(--surface-low);padding:8px;border-radius:4px;">
                            <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase">Tolérance</div>
                            <div style="font-size:14px;font-family:var(--font-data);color:var(--text-primary)">
                                [${def.tolerance[0]}; ${def.tolerance[1]}]
                            </div>
                          </div>`;
                }
                h += `</div><div style="margin-top:12px;font-size:12px;color:var(--text-muted)">
                        <em>Cliquez sur une image pour voir le graphique d'intensité ou les différentes couches de traitement (Sobel, Gausien...)</em>
                      </div>`;
                mWrap.innerHTML = h;
            }

            // Image brute si pas encore affichée
            const rawWrap = el(`raw-${did}-${angStr}`);
            if (rawWrap && !rawWrap.querySelector("img") && angData.chemin_brute) {
                const url = await urlMinIO(angData.chemin_brute);
                if (url) rawWrap.innerHTML =
                    `<img src="${url}" style="cursor:pointer"
                onclick="openVisuModal('${did}','${angStr}')" alt="brute">`;
            }

            // Dernière step dans la case du milieu
            const steps = angData.steps || {};
            const stepKeys = Object.keys(steps);
            if (stepKeys.length) {
                const lastKey = stepKeys[stepKeys.length - 1];
                const procWrap = el(`proc-${did}-${angStr}`);
                const procLbl = el(`proc-lbl-${did}-${angStr}`);
                
                if (procWrap) {
                    const url = await urlMinIO(steps[lastKey]);
                    if (url) procWrap.innerHTML =
                        `<img src="${url}" style="cursor:pointer"
                  onclick="openVisuModal('${did}','${angStr}')" alt="${lastKey}">`;
                }
                if (procLbl) procLbl.textContent = lastKey.replace(/\d+_/, "").replace(/_/g, " ");
            }

            // Stocker dans _sessionData pour modal
            if (!_sessionData[did]) _sessionData[did] = {};
            _sessionData[did][angStr] = {
                etat: "traitee", chemin_brute: angData.chemin_brute || "",
                steps, verdict: def.verdict, mesure: def.mesure,
                reference: def.reference, tolerance: def.tolerance,
                ecart: def.ecart, details: def.details || {},
            };
        }
    }
}

// ── Fusion ─────────────────────────────────────────────────────────
function buildFusionBlock() {
    const b = document.createElement("div");
    b.className = "visu-defaut-block"; b.id = "block-fusion";
    b.innerHTML = `
    <div class="visu-defaut-header" style="background:rgba(59, 130, 246, 0.1); border-color:rgba(59, 130, 246, 0.3)">
      <span class="defaut-id-badge" style="background:#3B82F6">Fusion IA</span>
      <span class="visu-defaut-name">Panorama cylindrique déroulé</span>
      <span class="visu-defaut-meta" id="fusion-progress">En attente des images...</span>
      <span class="verdict-badge hidden" id="verdict-fusion">—</span>
    </div>
    <div class="visu-fusion-layout">
      <!-- Zone gauche : Groupes par étage -->
      <div class="fusion-left-pane" id="fusion-thumbs-pane">
         <div style="text-align:center;color:var(--text-muted);font-style:italic;margin-top:20px">En attente des sources...</div>
      </div>
      <!-- Zone droite : Panorama -->
      <div class="fusion-right-pane">
        <div class="fusion-panorama-title">Résultat Image Fusionnée</div>
        <div class="fusion-panorama-img visu-spinner-wrap" id="fusion-result-wrap">
          <div class="visu-spinner"></div>
        </div>
      </div>
    </div>`;
    return b;
}

function updateFusionProgress(payload) {
    const lbl = el("fusion-progress");
    if (lbl) lbl.textContent = `${payload.nb_images_recues || 0} / ${payload.nb_images_attendues || "?"} images reçues`;
    // For live thumb updates, we might need to parse floor/angle. We leave this logic to the main refresh for now or just append linearly.
}

async function renderFusionResult(payload) {
    if (!el("block-fusion")) el("visu-body").appendChild(buildFusionBlock());
    const b = el("verdict-fusion");
    if (b) { b.textContent = payload.verdict_global || "OK"; b.className = "verdict-badge " + (payload.verdict_global === "NG" ? "badge-ng" : "badge-ok"); b.classList.remove("hidden"); }
    
    if (payload.chemins_sources && payload.chemins_sources.length > 0) {
        const pane = el("fusion-thumbs-pane");
        if (pane) {
            pane.innerHTML = "";
            // Dictionary to group by etage
            const etages = {};
            payload.chemins_sources.forEach(chemin => {
                // Format attendu: bouteilles_Type/ID/ID_E<etage>_A<angle>_...
                const match = chemin.match(/_E(\d+)_A(\d+)_/);
                const e = match ? match[1] : "?";
                const a = match ? match[2] : "?";
                if (!etages[e]) etages[e] = [];
                etages[e].push({ angle: a, chemin });
            });

            for (const [e, imgs] of Object.entries(etages)) {
                const grp = document.createElement("div");
                grp.className = "fusion-etage-group";
                grp.innerHTML = `<div class="fusion-etage-badge">E${e}</div>`;
                for (const imgData of imgs) {
                    const box = document.createElement("div");
                    box.className = "fusion-thumb-box";
                    box.innerHTML = `<div class="fusion-angle-lbl">A${imgData.angle}</div><div class="visu-spinner visu-spinner-sm"></div>`;
                    grp.appendChild(box);
                    urlMinIO(imgData.chemin).then(url => {
                        if (url) box.innerHTML = `<div class="fusion-angle-lbl">A${imgData.angle}</div><img src="${url}">`;
                    });
                }
                pane.appendChild(grp);
            }
        }
    }

    if (payload.chemin_fusion) {
        const url = await urlMinIO(payload.chemin_fusion);
        const w = el("fusion-result-wrap");
        if (w && url) w.innerHTML = `<img src="${url}" alt="Panorama">`;
    }
    const lbl = el("fusion-progress");
    if (lbl) lbl.textContent = `${payload.nb_images || "?"} images — fusion terminée`;
}

// ── IA ─────────────────────────────────────────────────────────────
function buildIABlock() {
    const b = document.createElement("div");
    b.className = "visu-defaut-block"; b.id = "block-ia";
    b.innerHTML = `
    <div class="visu-defaut-header" style="background:rgba(59, 130, 246, 0.1); border-color:rgba(59, 130, 246, 0.3)">
      <span class="defaut-id-badge" style="background:#3B82F6">IA</span>
      <span class="visu-defaut-name">Analyse YOLO — Détection défauts surface</span>
      <span class="verdict-badge hidden" id="verdict-ia">—</span>
    </div>
    <div class="visu-ia-layout">
      <!-- Ligne du haut (Images) -->
      <div class="visu-ia-top-row">
        <div class="visu-ia-box">
          <div class="fusion-panorama-title">Image Brute (Cylindre déroulé)</div>
          <div class="visu-ia-box-empty visu-spinner-wrap" id="ia-brute-wrap"><div class="visu-spinner"></div></div>
        </div>
        <div class="visu-ia-box">
          <div class="fusion-panorama-title">Résultat Annoté (YOLO)</div>
          <div class="visu-ia-box-empty visu-spinner-wrap" id="ia-annote-wrap"><div class="visu-spinner"></div></div>
        </div>
      </div>
      <!-- Ligne du bas (Liste des défauts) -->
      <div class="visu-ia-bottom-row" id="ia-detections">
         <div style="text-align:center;color:var(--text-muted);font-style:italic;">Les défauts identifiés par le modèle s'afficheront ici</div>
      </div>
    </div>`;
    return b;
}

async function renderIAResult(payload) {
    if (!el("block-ia")) el("visu-body").appendChild(buildIABlock());
    const b = el("verdict-ia");
    if (b) { b.textContent = payload.verdict_global || "?"; b.className = "verdict-badge " + (payload.verdict_global === "NG" ? "badge-ng" : "badge-ok"); b.classList.remove("hidden"); }
    if (payload.chemin_brute) {
        const url = await urlMinIO(payload.chemin_brute);
        const w = el("ia-brute-wrap");
        if (w && url) w.innerHTML = `<img src="${url}" style="max-width:100%;max-height:100%;object-fit:contain">`;
    }
    if (payload.chemin_annote) {
        const url = await urlMinIO(payload.chemin_annote);
        const w = el("ia-annote-wrap");
        if (w && url) w.innerHTML = `<img src="${url}" style="max-width:100%;max-height:100%;object-fit:contain">`;
    }
    const dets = el("ia-detections");
    if (dets) {
        dets.innerHTML = `<div style="font-size:14px;font-weight:600;color:var(--text-primary);margin-bottom:16px;">Défauts identifiés par le modèle (${(payload.detections || []).length})</div><div style="display:flex;flex-wrap:wrap;gap:10px;" id="ia-det-container"></div>`;
        const c = el("ia-det-container");
        (payload.detections || []).forEach(d => {
            const p = document.createElement("div");
            p.className = "visu-ia-det-pill " + (d.status === "NG" ? "pill-ng" : "pill-ok");
            p.innerHTML = `<strong>${d.label}</strong><span>${d.status}</span><span>conf. ${(d.confidence || 0).toFixed(3)}</span><span>${d.defauts_nb || 0} instance(s)</span>`;
            c.appendChild(p);
        });
        if (!(payload.detections || []).length) {
            c.innerHTML = '<div style="color:var(--ok);font-size:13px;font-weight:500;">Aucun défaut détecté.</div>';
        }
    }
}

// ── Check Position ─────────────────────────────────────────────────
function buildCheckBlock() {
    const b = document.createElement("div");
    b.className = "visu-defect-details"; // Reusing accordion styles statically
    b.id = "block-check";
    b.innerHTML = `
    <div class="visu-defect-summary" style="cursor:default">
      <span class="defaut-id-badge">CP1.1</span>
      <span class="visu-defaut-name">Check Position — Symétrie Canny</span>
      <span class="verdict-badge hidden" id="verdict-check">—</span>
    </div>
    <div class="visu-defect-content" id="grid-check"></div>`;
    return b;
}

async function renderCheckResult(payload) {
    // Créer le bloc si absent
    if (!el("block-check")) el("visu-body").appendChild(buildCheckBlock());

    // Verdict badge
    const badge = el("verdict-check");
    if (badge) {
        badge.textContent = payload.verdict_global || "?";
        badge.className = "verdict-badge " + (payload.verdict_global === "NG" ? "badge-ng" : "badge-ok");
        badge.classList.remove("hidden");
        el("block-check")?.classList.toggle("ng", payload.verdict_global === "NG");
    }

    const grid = el("grid-check");
    if (!grid) return;
    grid.innerHTML = "";

    for (const def of (payload.defauts || [])) {
        for (const [angStr, angData] of Object.entries(def.angles_visu || {})) {
            // Append row grid structure
            // CP operates mostly per angle globally (E1-A1...)
            // Just guess floor=1 for now as we don't have it natively in payload check_pos
            grid.appendChild(buildRowGrid(def.id_defaut, 1, angStr));

            // Cellule image brute
            if (angData.chemin_brute) {
                urlMinIO(angData.chemin_brute).then(url => {
                    const w = el(`raw-${def.id_defaut}-${angStr}`);
                    if (w && url) w.innerHTML = `<img src="${url}" onclick="openVisuModal('${def.id_defaut}','${angStr}')" alt="brute">`;
                });
            }

            // Cellule traitement
            const steps = angData.steps || {};
            const stepKeys = Object.keys(steps);
            if (stepKeys.length) {
                const lastKey = stepKeys[stepKeys.length - 1];
                const lblStep = lastKey.replace(/\d+_/, "").replace(/_/g, " ");
                urlMinIO(steps[lastKey]).then(url => {
                    const w = el(`proc-${def.id_defaut}-${angStr}`);
                    if (w && url) w.innerHTML = `<img src="${url}" onclick="openVisuModal('${def.id_defaut}','${angStr}')" alt="${lblStep}">`;
                });
                const procLbl = el(`proc-lbl-${def.id_defaut}-${angStr}`);
                if (procLbl) procLbl.textContent = lblStep;
            }

            // Statut & Metrics
            const statLbl = el(`statut-lbl-${def.id_defaut}-${angStr}`);
            const mWrap = el(`metrics-${def.id_defaut}-${angStr}`);
            if (mWrap) {
                const isNg = def.verdict === "NG";
                if (statLbl) {
                    statLbl.textContent = def.verdict || "OK";
                    statLbl.style.color = isNg ? "var(--ng)" : "var(--ok)";
                }
                mWrap.innerHTML = `
                    <div style="background:var(--surface-low);padding:8px;border-radius:4px;margin-bottom:8px">
                        <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase">Écart</div>
                        <div style="font-size:14px;font-family:var(--font-data);color:var(--text-primary)">
                            ${def.ecart != null ? def.ecart.toFixed(4) : "N/A"}
                        </div>
                    </div>
                `;
            }

            // Stocker dans _sessionData pour la modal (métriques + steps)
            const did = def.id_defaut;
            if (!_sessionData[did]) _sessionData[did] = {};
            _sessionData[did][angStr] = {
                etat: "traitee",
                chemin_brute: angData.chemin_brute || "",
                steps,
                verdict: def.verdict,
                mesure: def.mesure,
                reference: def.reference,
                tolerance: def.tolerance,
                ecart: def.ecart,
                details: (def.details || []).reduce((acc, r) => Object.assign(acc, r.details || {}), {}),
            };
        }
    }

    if (!grid.children.length) {
        grid.innerHTML = `<div class="visu-empty-msg">Aucune image disponible</div>`;
    }
}

// ── Info bar ───────────────────────────────────────────────────────
function showInfoBar(id, type, verdict, ts) {
    el("visu-info-empty")?.classList.add("hidden");
    el("visu-info-content")?.classList.remove("hidden");
    if (el("visu-btl-id")) el("visu-btl-id").textContent = `#${id}`;
    if (el("visu-btl-type")) el("visu-btl-type").textContent = type || "—";
    if (el("visu-ts")) el("visu-ts").textContent = ts ? new Date(ts).toLocaleTimeString("fr-FR") : "—";
    const bd = el("visu-global-badge");
    if (bd && verdict) { bd.textContent = verdict; bd.className = "verdict-badge " + (verdict === "NG" ? "badge-ng" : "badge-ok"); }
}

// ── Live badge ─────────────────────────────────────────────────────
function updateLiveBadge(svc, verdict) {
    const txt = el("visu-live-text");
    const dot = el("visu-live-dot");
    const bdg = el("visu-live-badge");
    if (txt) txt.textContent = `${svc} · ${verdict || "…"}`;
    if (bdg) bdg.className = "visu-live-badge " + (verdict ? (verdict === "NG" ? "live-ng" : "live-ok") : "");
    if (dot) dot.className = "visu-live-dot " + (verdict ? (verdict === "NG" ? "dot-ng" : "dot-ok") : "");
}

// ── Modal focus ────────────────────────────────────────────────────
function openVisuModal(idDef, angle) {
    _modalDef = idDef; _modalAng = String(angle);
    el("visu-modal-overlay")?.classList.remove("hidden");

    const defData = _sessionData[idDef] || {};
    const angData = defData[_modalAng] || {};

    // Trouver ce défaut dans la recette courante (pour connaitre l'étage et les angles)
    const recDef = (_recette?.defauts || []).find(d => d.id_defaut === idDef) || {};
    const etage = recDef.etage || defData.etage || "?";
    const validAngles = recDef.angles_requis || [];

    el("vm-id-badge").textContent = idDef;
    el("vm-name").textContent = el(`block-${idDef}`)?.querySelector(".visu-defaut-name")?.textContent || idDef;
    const vb = el("vm-badge");
    const vd = angData.verdict || "?";
    vb.textContent = vd; vb.className = "verdict-badge " + (vd === "NG" ? "badge-ng" : "badge-ok");

    // Angles nav
    const nav = el("vm-angles-nav");
    nav.innerHTML = `<span class="vm-angles-label">Angle(s) :</span>`;
    
    // N'afficher QUE les angles de la recette si elle existe, sinon rabattement sur les clés
    const anglesToIterate = (validAngles.length > 0) 
        ? validAngles.map(String) 
        : Object.keys(defData).sort((a, b) => +a - +b);

    anglesToIterate.forEach(ang => {
        const pill = document.createElement("button");
        pill.className = "vm-angle-pill" + (ang === _modalAng ? " active" : "");
        pill.textContent = `E${etage}-A${ang}`;
        pill.dataset.ang = ang;
        pill.onclick = () => switchModalAngle(idDef, ang);
        nav.appendChild(pill);
    });

    renderModalImgs(idDef, _modalAng);
    renderModalMetrics(angData);
    if (window.lucide) lucide.createIcons();
}

function switchModalAngle(idDef, ang) {
    _modalAng = String(ang);
    document.querySelectorAll(".vm-angle-pill").forEach(p => {
        p.classList.toggle("active", p.dataset.ang === _modalAng);
    });
    const angData = (_sessionData[idDef] || {})[_modalAng] || {};
    renderModalImgs(idDef, _modalAng);
    renderModalMetrics(angData);
}

async function renderModalImgs(idDef, ang) {
    const grid = el("vm-imgs-grid");
    if (!grid) return;
    grid.innerHTML = "";
    const angData = (_sessionData[idDef] || {})[String(ang)] || {};

    if (angData.chemin_brute) grid.appendChild(makeModalCard("Image brute", angData.chemin_brute));
    for (const [k, v] of Object.entries(angData.steps || {})) grid.appendChild(makeModalCard(k, v));
    if (!grid.children.length) grid.innerHTML = `<div class="vm-no-imgs">Images non disponibles</div>`;
}

function makeModalCard(label, chemin) {
    const card = document.createElement("div");
    card.className = "vm-img-card";
    card.innerHTML = `
    <div class="vm-img-label">${label.replace(/\d+_/, "").replace(/_/g, " ")}</div>
    <div class="vm-img-wrap" id="mcard-${Math.random().toString(36).slice(2)}">
      <div class="visu-spinner visu-spinner-sm"></div>
    </div>`;
    const wrap = card.querySelector(".vm-img-wrap");
    urlMinIO(chemin).then(url => {
        if (url) wrap.innerHTML = `<img src="${url}" class="vm-img" alt="${label}">`;
    });
    return card;
}

function renderModalMetrics(angData) {
    const row = el("vm-metrics-row");
    if (!row) return;
    row.innerHTML = "";
    const items = [
        ["Mesure", angData.mesure],
        ["Référence", angData.reference],
        ["Tolérance", angData.tolerance ? `[${angData.tolerance[0]} ; ${angData.tolerance[1]}]` : null],
        ["Écart", angData.ecart],
    ];
    const det = angData.details || {};
    ["scale", "pct_lignes_ng", "ecart_type_px", "ratio", "ratio_ref",
        "angle_deg", "decentrage_px", "ecart_position_px"].forEach(k => {
            if (det[k] != null) items.push([k.replace(/_/g, " "), det[k]]);
        });
    items.filter(([, v]) => v != null).forEach(([lbl, val]) => {
        const box = document.createElement("div");
        box.className = "vm-metric-box";
        const fv = typeof val === "number"
            ? (Number.isInteger(val) ? val : parseFloat(val.toFixed(4))) : val;
        box.innerHTML = `<div class="vm-metric-val">${fv}</div><div class="vm-metric-lbl">${lbl}</div>`;
        row.appendChild(box);
    });
}

function closeVisuModal() {
    el("visu-modal-overlay")?.classList.add("hidden");
}

document.addEventListener("keydown", e => { if (e.key === "Escape") closeVisuModal(); });