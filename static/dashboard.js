// Configuration
const WS_URL = `ws://${window.location.host}/ws`;
let socket;
let reconnectTimer;

// DOM Elements
const wsStatus = document.getElementById('ws-status');
const wsDot = document.getElementById('ws-dot');
const acqGrid = document.getElementById('acq-grid');
const mainImg = document.getElementById('main-img');
const mainImgPlaceholder = document.getElementById('main-img-placeholder');
const mainImgInfo = document.getElementById('main-img-info');

// Global state
let currentImages = {}; // id_bouteille -> list of images

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    initEmptyGrids();
});

// ---------------------------------------------------------------------------
// WEBSOCKET MANAGEMENT
// ---------------------------------------------------------------------------
function connectWebSocket() {
    socket = new WebSocket(WS_URL);

    socket.onopen = () => {
        console.log('Connecté au serveur WebSocket');
        wsStatus.textContent = 'Connecté (Live)';
        wsDot.classList.add('connected');
        clearTimeout(reconnectTimer);
    };

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleEvent(data);
        } catch (e) {
            console.error("Erreur parsing WS message:", e);
        }
    };

    socket.onclose = () => {
        console.log('Déconnecté du serveur WebSocket');
        wsStatus.textContent = 'Déconnecté - Reconnexion...';
        wsDot.classList.remove('connected');
        reconnectTimer = setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Erreur WebSocket:', err);
        socket.close();
    };
}

// ---------------------------------------------------------------------------
// EVENT ROUTING
// ---------------------------------------------------------------------------
function handleEvent(event) {
    const { type, data } = event;
    
    // Update Bottle Meta if available
    if (data.id_bouteille) {
        document.getElementById('meta-id').textContent = data.id_bouteille;
        if (data.type_bouteille) {
            document.getElementById('meta-type').textContent = data.type_bouteille;
        }
        
        // Reset grids if new bottle
        if (!currentImages[data.id_bouteille]) {
            resetAllDisplays();
            currentImages[data.id_bouteille] = true;
            document.getElementById('global-verdict').textContent = 'ANALYSE...';
            document.getElementById('global-verdict-box').className = 'verdict-box';
        }
    }

    switch (type) {
        case 'acquisition':
            handleAcquisition(data);
            break;
        case 'fusion_input':
            updateStatus('fusion', 'Prétraitement...');
            break;
        case 'fusion_done':
            handleFusionDone(data);
            break;
        case 'input_bouchon':
            handleServiceInput('bouchon', data);
            break;
        case 'result_bouchon':
            handleServiceResult('bouchon', data);
            break;
        case 'input_niveau':
            handleServiceInput('niveau', data);
            break;
        case 'result_niveau':
            handleServiceResult('niveau', data);
            break;
        case 'input_deformation':
            handleServiceInput('deformation', data);
            break;
        case 'result_deformation':
            handleServiceResult('deformation', data);
            break;
        case 'verdict_final':
            handleFinalVerdict(data);
            break;
        case 'status_orchestrateur':
            handleOrchestratorStatus(data);
            break;
    }
}

// ---------------------------------------------------------------------------
// HANDLERS
// ---------------------------------------------------------------------------

// 1. ACQUISITION
function handleAcquisition(data) {
    updateStatus('acq', 'Acquisition active');
    
    // Build image URL
    const imgUrl = `/api/image/${data.bucket}/${encodeURIComponent(data.chemin_minio)}`;
    
    // Display in main panel
    setMainImage(imgUrl, data.etage, data.angle);
    
    // Add to grid
    addThumbToGrid('acq-grid', imgUrl, `E${data.etage} A${data.angle}`, data.etage, data.angle);
}

// 2. FUSION
function handleFusionDone(data) {
    updateStatus('fusion', 'Panorama prêt');
    
    // Fallback in case payload uses data.chemin_image_fusionnee instead of data.chemin_panorama
    // and contains the bucket name in the path like "/images-production/..."
    let imgUrl = "";
    if (data.chemin_image_fusionnee) {
        // Example: "/images-production/bouteilles_Type_A/TEST/fusion_ia/deroule.jpg"
        const parts = data.chemin_image_fusionnee.split('/').filter(p => p);
        const bucket = parts.shift(); // extract bucket
        const minioPath = parts.join('/');
        imgUrl = `/api/image/${bucket}/${encodeURIComponent(minioPath)}`;
    } else {
        imgUrl = `/api/image/${data.bucket}/${encodeURIComponent(data.chemin_panorama)}`;
    }
    
    const panoImg = document.getElementById('pano-img');
    const placeholder = document.getElementById('pano-placeholder');
    
    panoImg.src = imgUrl;
    panoImg.style.display = 'block';
    placeholder.style.display = 'none';
}

// 3. SERVICE INPUTS (Images received before processing)
function handleServiceInput(serviceName, data) {
    updateStatus(serviceName, 'Image reçue');
    const imgUrl = `/api/image/${data.bucket}/${encodeURIComponent(data.chemin_minio)}`;
    
    const container = document.getElementById(`img-${serviceName}-container`);
    
    // Remove empty state if present
    const emptyState = container.querySelector('.empty-state');
    if (emptyState) {
        container.innerHTML = ''; // clear container
    }
    
    // Add image box
    const imgBox = document.createElement('div');
    imgBox.className = 'service-img-box';
    imgBox.innerHTML = `<img src="${imgUrl}" alt="Input ${serviceName}" onclick="setMainImage('${imgUrl}', ${data.etage}, ${data.angle})" style="cursor:pointer" title="Étage: ${data.etage}, Angle: ${data.angle}">`;
    container.appendChild(imgBox);
}

// 4. SERVICE RESULTS (Bouchon, Niveau, Deformation)
function handleServiceResult(serviceName, data) {
    updateStatus(serviceName, 'Analyse terminée');
    
    // Status visual
    const resBadge = document.getElementById(`res-${serviceName}`);
    resBadge.textContent = data.status;
    resBadge.className = `service-result ${data.status.toLowerCase()}`;
    
    // Details
    const detailsBox = document.getElementById(`details-${serviceName}`);
    detailsBox.innerHTML = `<strong>Status:</strong> ${data.status}<br/>`;
    
    if (data.details) {
        let detailsHtml = '';
        for (const [key, val] of Object.entries(data.details)) {
           detailsHtml += `<div>${key}: ${val.status || ''} ${val.value ? '('+val.value+')' : ''}</div>`; 
        }
        detailsBox.innerHTML += detailsHtml;
    }
}

// 4. VERDICT FINAL
function handleFinalVerdict(data) {
    const verdictBox = document.getElementById('global-verdict-box');
    const verdictValue = document.getElementById('global-verdict');
    
    verdictValue.textContent = data.status;
    
    if (data.status === 'OK') {
        verdictBox.className = 'verdict-box ok';
    } else {
        verdictBox.className = 'verdict-box ng';
    }
    
    // Update reasons if NG
    if (data.status === 'NG' && data.details && data.details.algorithmes_echoues) {
        let reasons = '<div style="color:var(--danger-red);font-size:12px;margin-top:10px;">Échecs: ';
        reasons += data.details.algorithmes_echoues.join(', ');
        reasons += '</div>';
        verdictBox.innerHTML += reasons;
    }
}

// 5. STATUS ORCHESTRATEUR
function handleOrchestratorStatus(data) {
    const el = document.getElementById('orchestrator-status');
    el.textContent = `En ligne (${data.mode_actif})`;
    el.className = 'service-status active';
}

// ---------------------------------------------------------------------------
// UI HELPERS
// ---------------------------------------------------------------------------
function updateStatus(service, text) {
    const el = document.getElementById(`status-${service}`);
    if (el) {
        el.textContent = text;
        el.className = 'service-status active';
        
        // Remove active class after 3s to show activity ping
        setTimeout(() => {
            el.className = 'service-status';
        }, 3000);
    }
}

function setMainImage(url, etage, angle) {
    mainImg.src = url;
    mainImg.style.display = 'block';
    mainImgPlaceholder.style.display = 'none';
    
    document.getElementById('main-img-e').textContent = etage || '?';
    document.getElementById('main-img-a').textContent = angle || '?';
    mainImgInfo.style.display = 'flex';
}

function initEmptyGrids() {
    // 16 slots placeholders for ACQ grid
    acqGrid.innerHTML = '';
    for (let i = 0; i < 16; i++) {
        const slot = document.createElement('div');
        slot.className = 'thumb-slot';
        slot.innerHTML = `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--border-color);font-size:10px;">-</div>`;
        acqGrid.appendChild(slot);
    }
}

function addThumbToGrid(gridId, imgUrl, badgeText, etage, angle) {
    const grid = document.getElementById(gridId);
    
    // Calcule index (0-15): etage 1 (0-7), etage 2 (8-15)
    // Assume angle is 1-8
    let idx = (etage - 1) * 8 + (angle - 1);
    if (idx < 0 || idx > 15) idx = 0;
    
    const slots = grid.querySelectorAll('.thumb-slot');
    if (slots[idx]) {
        slots[idx].innerHTML = `
            <span class="thumb-badge">${badgeText}</span>
            <img src="${imgUrl}" alt="thumb">
        `;
        
        // Clic pour afficher en grand
        slots[idx].onclick = () => {
            document.querySelectorAll('.thumb-slot').forEach(s => s.classList.remove('active'));
            slots[idx].classList.add('active');
            setMainImage(imgUrl, etage, angle);
        };
    }
}

function resetAllDisplays() {
    initEmptyGrids();
    
    mainImg.style.display = 'none';
    mainImgPlaceholder.style.display = 'block';
    mainImgInfo.style.display = 'none';
    
    document.getElementById('pano-img').style.display = 'none';
    document.getElementById('pano-placeholder').style.display = 'block';
    
    ['bouchon', 'niveau', 'deformation'].forEach(s => {
        const badge = document.getElementById(`res-${s}`);
        if(badge) {
            badge.textContent = 'WAIT';
            badge.className = 'service-result';
        }
        const details = document.getElementById(`details-${s}`);
        if(details) {
            details.innerHTML = 'Attente de fin d\'analyse...';
        }
        const imgContainer = document.getElementById(`img-${s}-container`);
        if(imgContainer) {
            imgContainer.innerHTML = '<div class="service-img-box"><span class="empty-state">Attente image...</span></div>';
        }
    });
}
