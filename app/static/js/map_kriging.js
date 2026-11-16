/**
 * PGA Kriging GIS - Controlador Front-end do Mapa e Interpolação Geoestatística
 * Camadas Base com Esri World Dark Gray Canvas (sem chave de API) e Controle de Camadas
 */

document.addEventListener('DOMContentLoaded', () => {
    // Obter Token CSRF da meta tag
    const getCsrfToken = () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    };

    // --- 1. INICIALIZAÇÃO DO MAPA LEAFLET & CUSTOM PANES ---
    // Centro geográfico aproximado da Região Norte do Brasil
    const defaultCenter = [-4.0, -56.0];
    const map = L.map('map', {
        center: defaultCenter,
        zoom: 5,
        zoomControl: true,
        attributionControl: true
    });

    // Custom Panes para assegurar a hierarquia estrita de z-index
    // tilePane padrão do Leaflet tem zIndex 200
    map.createPane('krigingPane');
    map.getPane('krigingPane').style.zIndex = 400; // Acima dos mapas base

    map.createPane('stationsPane');
    map.getPane('stationsPane').style.zIndex = 600; // Acima da interpolação e do mapa base

    // --- 2. CONFIGURAÇÃO DAS CAMADAS BASE (ZERO DEPENDÊNCIA DE API KEY) ---

    // Camada Base 1: Esri World Dark Gray Canvas (Base + Labels) - PADRÃO INICIAL
    const esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
        maxZoom: 16
    });

    const esriDarkRef = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
        attribution: '',
        maxZoom: 16
    });

    // Grupo com Base Escura + Fronteiras/Rótulos de Cidades e Estados
    const esriDarkGroup = L.layerGroup([esriDarkBase, esriDarkRef]).addTo(map);

    // Camada Base 2: Esri World Imagery (Satélite)
    const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri, Earthstar Geographics',
        maxZoom: 18
    });

    // Camada Base 3: OpenStreetMap Padrão
    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    });

    // --- 3. GRUPOS DE CAMADAS VETORIAIS (OVERLAYS) ---
    const stationsLayer = L.layerGroup([], { pane: 'stationsPane' }).addTo(map);
    const krigingLayerGroup = L.layerGroup([], { pane: 'krigingPane' }).addTo(map);

    // Dicionários para o Controle de Camadas
    const baseLayers = {
        "Escuro Técnico (Esri Dark Gray)": esriDarkGroup,
        "Satélite (Esri World Imagery)": esriSat,
        "OpenStreetMap Padrão": osm
    };

    const overlayLayers = {
        "Estações Sísmicas": stationsLayer,
        "Interpolação PGA (Krigagem)": krigingLayerGroup
    };

    // Controle de Camadas no canto superior direito
    const layerControl = L.control.layers(baseLayers, overlayLayers, {
        position: 'topright',
        collapsed: false
    }).addTo(map);

    L.control.scale({ metric: true, imperial: false, position: 'bottomright' }).addTo(map);

    // --- 4. LEGENDA DINÂMICA DE RISCO SÍSMICO NO MAPA ---
    const legendControl = L.control({ position: 'bottomright' });
    legendControl.onAdd = function () {
        const div = L.DomUtil.create('div', 'info legend');
        div.innerHTML = `
            <div class="font-bold mb-1 text-[11px] text-cyan-300 flex items-center gap-1">
                <i class="fa-solid fa-signal"></i> PGA (g) &bull; NBR 15421
            </div>
            <div><i style="background: #8b5cf6"></i> &gt; 0.40 g (Extremo)</div>
            <div><i style="background: #ef4444"></i> 0.20 - 0.40 g (Muito Alto)</div>
            <div><i style="background: #f97316"></i> 0.10 - 0.20 g (Alto)</div>
            <div><i style="background: #eab308"></i> 0.05 - 0.10 g (Moderado)</div>
            <div><i style="background: #06b6d4"></i> 0.02 - 0.05 g (Baixo)</div>
            <div><i style="background: #10b981"></i> &lt; 0.02 g (Muito Baixo)</div>
        `;
        return div;
    };
    legendControl.addTo(map);

    // --- 5. CONTROLE DE ABAS E PAINEL LATERAL ---
    const sidebar = document.getElementById('sidebar');
    const btnToggleSidebar = document.getElementById('btnToggleSidebar');

    btnToggleSidebar.addEventListener('click', () => {
        sidebar.classList.toggle('-ml-96');
        setTimeout(() => map.invalidateSize(), 310);
    });

    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => {
                b.classList.remove('text-cyan-400', 'bg-slate-800/80');
                b.classList.add('text-slate-400');
            });
            btn.classList.add('text-cyan-400', 'bg-slate-800/80');
            btn.classList.remove('text-slate-400');

            const targetId = btn.getAttribute('data-target');
            tabPanes.forEach(pane => {
                pane.classList.toggle('hidden', pane.id !== targetId);
            });
        });
    });

    // Controle do Slider de Resolução (Padrão 60 para escala continental)
    const rangeResolution = document.getElementById('rangeResolution');
    const labelResolutionVal = document.getElementById('labelResolutionVal');
    rangeResolution.addEventListener('input', (e) => {
        labelResolutionVal.textContent = `${e.target.value} x ${e.target.value}`;
    });

    // Helper de Alertas / Toast
    const alertBox = document.getElementById('alertBox');
    const showAlert = (message, type = 'error') => {
        alertBox.classList.remove('hidden', 'bg-rose-950/80', 'border-rose-700/60', 'text-rose-200', 'bg-emerald-950/80', 'border-emerald-700/60', 'text-emerald-200', 'bg-cyan-950/80', 'border-cyan-700/60', 'text-cyan-200');
        if (type === 'error') {
            alertBox.classList.add('bg-rose-950/80', 'border-rose-700/60', 'text-rose-200');
            alertBox.innerHTML = `<i class="fa-solid fa-triangle-exclamation mr-1.5"></i> ${message}`;
        } else if (type === 'info') {
            alertBox.classList.add('bg-cyan-950/80', 'border-cyan-700/60', 'text-cyan-200');
            alertBox.innerHTML = `<i class="fa-solid fa-info-circle mr-1.5"></i> ${message}`;
        } else {
            alertBox.classList.add('bg-emerald-950/80', 'border-emerald-700/60', 'text-emerald-200');
            alertBox.innerHTML = `<i class="fa-solid fa-circle-check mr-1.5"></i> ${message}`;
        }
    };
    const hideAlert = () => alertBox.classList.add('hidden');

    // --- 6. CARREGAMENTO E RENDERIZAÇÃO DAS ESTAÇÕES ---
    let stationsData = [];

    const loadStations = async (shouldFit = false) => {
        try {
            const res = await fetch('/api/estacoes');
            const data = await res.json();
            stationsData = data.features || [];

            // Atualizar badge no header
            document.getElementById('badgeStationCount').textContent = `${stationsData.length} Estações Ativas`;

            // Limpar camada no mapa
            stationsLayer.clearLayers();

            const tableBody = document.getElementById('tableStationsBody');
            tableBody.innerHTML = '';

            const bounds = L.latLngBounds();

            stationsData.forEach(feat => {
                const props = feat.properties;
                const coords = feat.geometry.coordinates; // [lon, lat]
                const latLng = [coords[1], coords[0]];
                bounds.extend(latLng);

                // Criar Ícone Customizado Sísmico
                const customIcon = L.divIcon({
                    className: 'seismic-marker',
                    html: `
                        <div class="seismic-pulse"></div>
                        <div class="seismic-core" title="${props.codigo_estacao} (${props.municipio_uf || ''})"></div>
                    `,
                    iconSize: [24, 24],
                    iconAnchor: [12, 12]
                });

                // Criar Marcador com Popup Completo (Município/UF, Profundidade, PGA)
                const marker = L.marker(latLng, { icon: customIcon, pane: 'stationsPane' });
                const munText = props.municipio_uf && props.municipio_uf !== "Não informado" ? props.municipio_uf : 'Não informado';
                const profText = props.profundidade_km !== undefined ? `${props.profundidade_km} km` : '10.0 km';

                marker.bindPopup(`
                    <div class="space-y-1.5 font-sans min-w-[210px]">
                        <div class="flex items-center justify-between border-b border-slate-700 pb-1">
                            <div>
                                <span class="font-bold text-cyan-400 font-mono text-xs">${props.codigo_estacao}</span>
                                <span class="block text-[10px] text-slate-300 font-medium">${munText}</span>
                            </div>
                            <span class="text-[9px] px-1 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">ID #${props.id}</span>
                        </div>
                        <div class="text-[11px] space-y-1 text-slate-200">
                            <div class="flex justify-between items-center bg-slate-900/60 px-1.5 py-0.5 rounded border border-slate-800">
                                <span>Aceleração PGA:</span>
                                <span class="font-mono text-emerald-400 font-bold">${props.pga_g} g</span>
                            </div>
                            <div class="flex justify-between items-center text-slate-400 text-[10px]">
                                <span>Profundidade:</span>
                                <span class="font-mono text-slate-200">${profText}</span>
                            </div>
                            <div class="flex justify-between items-center text-slate-400 text-[10px]">
                                <span>Coordenadas:</span>
                                <span class="font-mono text-slate-300">${props.latitude.toFixed(4)}, ${props.longitude.toFixed(4)}</span>
                            </div>
                        </div>
                        <button onclick="window.deleteStation(${props.id})" class="mt-2 w-full py-1 bg-rose-950/70 hover:bg-rose-900 text-rose-200 border border-rose-800/60 rounded text-[10px] transition-colors cursor-pointer flex items-center justify-center gap-1">
                            <i class="fa-solid fa-trash-can"></i> Excluir Estação
                        </button>
                    </div>
                `);
                stationsLayer.addLayer(marker);

                // Adicionar na Tabela
                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-900/80 transition-colors';
                tr.innerHTML = `
                    <td class="p-1.5">
                        <span class="text-cyan-300 font-medium block">${props.codigo_estacao}</span>
                        <span class="text-slate-400 text-[9px] block">${munText}</span>
                    </td>
                    <td class="p-1.5 text-emerald-400 font-bold">${props.pga_g} g</td>
                    <td class="p-1.5 text-right">
                        <button onclick="window.deleteStation(${props.id})" class="text-rose-400 hover:text-rose-300 p-1" title="Excluir">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </td>
                `;
                tableBody.appendChild(tr);
            });

            if (stationsData.length > 0 && bounds.isValid()) {
                window.lastBounds = bounds;
                if (shouldFit) {
                    map.fitBounds(bounds, { padding: [40, 40] });
                }
            }

        } catch (err) {
            console.error('Erro ao carregar estações:', err);
            showAlert('Falha ao conectar com o serviço PostGIS de estações.', 'error');
        }
    };

    // Função Global para Exclusão
    window.deleteStation = async (id) => {
        if (!confirm(`Deseja realmente remover a estação ID ${id}?`)) return;
        try {
            const res = await fetch(`/api/estacoes/${id}`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                }
            });
            const data = await res.json();
            if (res.ok) {
                showAlert(data.message || 'Estação removida.', 'success');
                loadStations();
            } else {
                showAlert(data.message || 'Erro ao remover estação.', 'error');
            }
        } catch (err) {
            showAlert('Erro de rede ao excluir estação.', 'error');
        }
    };

    // --- 7. CADASTRO DE ESTAÇÃO INDIVIDUAL ---
    const formAddStation = document.getElementById('formAddStation');
    formAddStation.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideAlert();

        const payload = {
            codigo_estacao: document.getElementById('inputStationCode').value,
            municipio_uf: document.getElementById('inputStationMun').value,
            latitude: parseFloat(document.getElementById('inputStationLat').value),
            longitude: parseFloat(document.getElementById('inputStationLon').value),
            pga_g: parseFloat(document.getElementById('inputStationPga').value),
            profundidade_km: parseFloat(document.getElementById('inputStationProf').value || 10.0)
        };

        try {
            const res = await fetch('/api/estacoes', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (res.ok) {
                showAlert(data.message || 'Estação cadastrada com sucesso!', 'success');
                formAddStation.reset();
                loadStations();
            } else {
                showAlert(data.message || 'Erro ao cadastrar estação.', 'error');
            }
        } catch (err) {
            showAlert('Erro de rede ao salvar estação.', 'error');
        }
    });

    // --- 8. INGESTÃO SEGURA VIA UPLOAD (.CSV / .GEOJSON) ---
    const dropZone = document.getElementById('dropZone');
    const inputFileUniversal = document.getElementById('inputFileUniversal');

    dropZone.addEventListener('click', () => inputFileUniversal.click());

    ['dragenter', 'dragover'].forEach(name => {
        dropZone.addEventListener(name, (e) => {
            e.preventDefault();
            dropZone.classList.add('border-cyan-500', 'bg-cyan-950/20');
        });
    });

    ['dragleave', 'drop'].forEach(name => {
        dropZone.addEventListener(name, (e) => {
            e.preventDefault();
            dropZone.classList.remove('border-cyan-500', 'bg-cyan-950/20');
        });
    });

    dropZone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files.length > 0) uploadUniversalFile(files[0]);
    });

    inputFileUniversal.addEventListener('change', (e) => {
        if (e.target.files.length > 0) uploadUniversalFile(e.target.files[0]);
    });

    const uploadUniversalFile = async (file) => {
        const name = file.name.toLowerCase();
        if (!name.endsWith('.csv') && !name.endsWith('.geojson') && !name.endsWith('.json')) {
            showAlert('Formato inválido. Selecione um arquivo .csv ou .geojson.', 'error');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            showAlert(`Processando arquivo '${file.name}'...`, 'info');
            const res = await fetch('/api/estacoes/upload', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                },
                body: formData
            });
            const data = await res.json();

            if (res.ok) {
                const det = data.detalhes || {};
                const rejeitados = det.rejeitados ? ` (${det.rejeitados} linhas rejeitadas)` : '';
                showAlert(`${data.message}${rejeitados}`, 'success');
                await loadStations(true);
            } else {
                showAlert(data.message || 'Erro no processamento do arquivo.', 'error');
            }
        } catch (err) {
            showAlert('Falha na transmissão do arquivo para o servidor.', 'error');
        } finally {
            inputFileUniversal.value = '';
        }
    };

    // --- 9. CARGA RÁPIDA: DATASET REGIÃO NORTE (20 ESTAÇÕES) ---
    const handleLoadNorte = async () => {
        try {
            showAlert('Carregando dataset oficial da Região Norte (20 estações)...', 'info');
            const res = await fetch('/api/estacoes/seed-norte', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                }
            });
            const data = await res.json();

            if (res.ok) {
                showAlert(`${data.message} Total de estações no PostGIS: ${data.total_banco}`, 'success');
                await loadStations(true);
            } else {
                showAlert(data.message || 'Falha ao carregar dataset Norte.', 'error');
            }
        } catch (err) {
            showAlert('Erro de conexão ao carregar dataset da Região Norte.', 'error');
        }
    };

    document.getElementById('btnQuickSeedNorte').addEventListener('click', handleLoadNorte);
    document.getElementById('btnSeedNorteSidebar').addEventListener('click', handleLoadNorte);
    document.getElementById('btnRefreshStations').addEventListener('click', () => loadStations(false));

    // --- 10. EXECUÇÃO DA KRIGAGEM ORDINÁRIA ---
    const btnRunKriging = document.getElementById('btnRunKriging');
    const mapLoading = document.getElementById('mapLoading');
    const metricsBox = document.getElementById('metricsBox');

    btnRunKriging.addEventListener('click', async () => {
        hideAlert();
        mapLoading.classList.remove('hidden');

        const modelo = document.getElementById('selectModel').value;
        const resolucao = parseInt(document.getElementById('rangeResolution').value, 10);

        try {
            const res = await fetch('/api/interpolar', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ modelo, resolucao })
            });

            const data = await res.json();

            if (!res.ok) {
                showAlert(data.message || 'Erro ao realizar interpolação.', 'error');
                return;
            }

            // Limpar camada de interpolação anterior
            krigingLayerGroup.clearLayers();

            // Renderizar Grade Interpolada GeoJSON dentro da pane krigingPane
            const gridGeoJson = L.geoJSON(data, {
                pane: 'krigingPane',
                style: (feature) => {
                    const props = feature.properties;
                    return {
                        fillColor: props.cor || '#10b981',
                        weight: 0.35,
                        opacity: 0.55,
                        color: '#0f172a',
                        fillOpacity: 0.72
                    };
                },
                onEachFeature: (feature, layer) => {
                    const p = feature.properties;
                    layer.bindPopup(`
                        <div class="space-y-1.5 font-sans min-w-[200px]">
                            <div class="font-bold text-slate-100 border-b border-slate-700 pb-1 flex items-center justify-between">
                                <span class="text-xs">Célula Interpolada</span>
                                <span class="px-1.5 py-0.5 rounded text-[9px] font-semibold" style="background: ${p.cor}22; color: ${p.cor}; border: 1px solid ${p.cor}">
                                    ${p.risco_sismico}
                                </span>
                            </div>
                            <div class="text-[11px] space-y-0.5 font-mono text-slate-300">
                                <div><strong>PGA Estimado:</strong> <span class="text-white font-bold">${p.pga_g} g</span></div>
                                <div><strong>Variância:</strong> <span class="text-slate-400">${p.variancia}</span></div>
                                <div><strong>Desvio Padrão:</strong> <span class="text-slate-400">${p.desvio_padrao} g</span></div>
                            </div>
                        </div>
                    `);

                    layer.on('mouseover', () => layer.setStyle({ fillOpacity: 0.9, weight: 1.5, color: '#38bdf8' }));
                    layer.on('mouseout', () => layer.setStyle({ fillOpacity: 0.72, weight: 0.35, color: '#0f172a' }));
                }
            });

            krigingLayerGroup.addLayer(gridGeoJson);

            // Se o overlay tiver sido desmarcado no controle, reativa para exibição imediata
            if (!map.hasLayer(krigingLayerGroup)) {
                map.addLayer(krigingLayerGroup);
            }

            // Atualizar Caixa de Métricas
            const meta = data.metadata || {};
            metricsBox.classList.remove('hidden');
            document.getElementById('metricUtm').textContent = `EPSG:${meta.utm_epsg} (${meta.utm_zona})`;
            document.getElementById('metricPgaMean').textContent = `${meta.pga_media} g`;
            document.getElementById('metricPgaMax').textContent = `${meta.pga_max} g`;
            document.getElementById('metricPgaMin').textContent = `${meta.pga_min} g`;
            document.getElementById('metricCells').textContent = `${meta.total_celulas} células`;

            showAlert(`Krigagem concluída com sucesso usando o modelo ${modelo.toUpperCase()} (${meta.total_celulas} células)!`, 'success');

            // Ajustar visualização para cobrir o grid
            map.fitBounds(gridGeoJson.getBounds(), { padding: [30, 30] });

        } catch (err) {
            console.error('Erro na interpolação:', err);
            showAlert('Erro de rede ou conexão com o servidor ao interpolar.', 'error');
        } finally {
            mapLoading.classList.add('hidden');
        }
    });

    // Zoom Extent Button
    document.getElementById('btnZoomExtent').addEventListener('click', () => {
        const layers = krigingLayerGroup.getLayers();
        if (layers.length > 0 && layers[0].getBounds) {
            map.fitBounds(layers[0].getBounds(), { padding: [30, 30] });
        } else if (window.lastBounds) {
            map.fitBounds(window.lastBounds, { padding: [40, 40] });
        }
    });

    // Carga inicial
    loadStations(true);
});
