/**
 * risk-weather.js - 기상특보 현황
 */
(function() {
    var activeWeatherMapKind = 'wrn';
    var landslideMapState = {
        map: null,
        baseLayer: null,
        overlayLayer: null,
        target: null
    };
    var weatherMapMetaByKind = {
        wrn: {
            title: '종합 특보',
            description: '전국 기상 특보 상황을 한눈에 볼 수 있는 종합 지도입니다.',
            alt: '종합 특보 현황 지도',
            wrn: 'W,R,C,D,O,N,V,T,S,Y,H,F'
        },
        gk2a: {
            title: '실시간 위성',
            description: 'GK2A 가시영상 기준으로 현재 구름 분포를 확인할 수 있습니다.',
            alt: '위성지도',
            wrn: ''
        },
        wildfire: {
            title: '산불위험도',
            description: '기상청 산불위험도를 단계별로 확인할 수 있는 지도입니다.',
            alt: '산불위험지도',
            wrn: ''
        },
        landslide: {
            title: '산사태위험도',
            description: '광주광역시, 전라남도, 정읍시 산사태 위험등급을 한 화면에서 확인할 수 있습니다.',
            alt: '산사태위험지도',
            wrn: ''
        }
    };
    var weatherScoreFilterData = {
        hqList: [],
        branchList: [],
        branchByHq: {},
        regionList: [],
        districtMap: {}
    };
    $(function() {
        // Initial load: active map + today's alert/score tables
        initWeatherMapTabs();
        loadWeatherMaps([activeWeatherMapKind], { forceRefresh: false });
        loadAlertToday();
        initWeatherScoreFilters(function() {
            loadWeatherScore();
        });

        $('#btnRefresh').on('click', function() {
            var $btn = $(this);
            $btn.prop('disabled', true).text('갱신 중...');
            RiskApp.callApi('refreshWeatherData.do', {}, function(res) {
                alert(res.message || '갱신 완료');
                $btn.prop('disabled', false).text('수동 갱신');

                // Manual refresh must sync DB-backed data and all map images immediately.
                loadAlertToday();
                loadWeatherScore();
                loadWeatherMaps([activeWeatherMapKind], { forceRefresh: true });
            }, {
                method: 'POST',
                onFail: function(res, msg) {
                    alert('수동 갱신 실패: ' + msg);
                    $btn.prop('disabled', false).text('수동 갱신');
                }
            });
        });
    });

    function initWeatherMapTabs() {
        updateWeatherMapMeta(activeWeatherMapKind);
        $('#weatherMapTabs').off('click', 'button').on('click', 'button', function() {
            var mapKind = String($(this).data('mapKind') || '').toLowerCase();
            if (!mapKind || mapKind === activeWeatherMapKind) {
                return;
            }
            activeWeatherMapKind = mapKind;
            $('#weatherMapTabs button').removeClass('is-active');
            $(this).addClass('is-active');
            updateWeatherMapMeta(mapKind);
            loadWeatherMaps([mapKind], { forceRefresh: false });
        });
    }

    function updateWeatherMapMeta(mapKind) {
        var meta = weatherMapMetaByKind[mapKind] || weatherMapMetaByKind.wrn;
        var $img = $('#weatherMapPrimary');
        if ($img.length) {
            $img.attr('alt', meta.alt || '기상 지도');
            $img.attr('data-map-kind', mapKind);
            $img.attr('data-wrn', meta.wrn || '');
        }
        $('#weatherMapLayerDescription').text(meta.description || '');
    }

    function initWeatherScoreFilters(onReady) {
        loadWeatherScoreFilterOptions(function() {
            renderWeatherScoreFilterCombos();
            bindWeatherScoreFilterEvents();
            if (typeof onReady === 'function') {
                onReady();
            }
        });
    }

    function loadWeatherScoreFilterOptions(done) {
        var pending = 4;
        var hqSet = {};
        var branchSet = {};
        var branchByHq = {};
        var regionSet = {};
        var districtMap = {};

        function finishOne() {
            pending--;
            if (pending > 0) {
                return;
            }
            weatherScoreFilterData.hqList = Object.keys(hqSet).sort();
            var allBranches = Object.keys(branchSet);
            weatherScoreFilterData.branchList = allBranches.filter(function(branchName) {
                // Remove HQ-self option from branch combo (e.g. "광주전남본부" in "광주전남본부").
                return !hqSet[branchName];
            }).sort();
            weatherScoreFilterData.branchByHq = {};
            for (var hqName in branchByHq) {
                if (!branchByHq.hasOwnProperty(hqName)) continue;
                weatherScoreFilterData.branchByHq[hqName] = Object.keys(branchByHq[hqName]).filter(function(branchName) {
                    return branchName !== hqName;
                }).sort();
            }
            weatherScoreFilterData.regionList = Object.keys(regionSet).sort();
            weatherScoreFilterData.districtMap = districtMap;
            done();
        }

        RiskApp.callApi('selectHqSummary.do', {}, function(res) {
            var data = res.data || [];
            for (var i = 0; i < data.length; i++) {
                var hq = (data[i].branchNm || '').trim();
                if (hq) {
                    hqSet[hq] = true;
                }
            }
            finishOne();
        }, { onFail: function() { finishOne(); } });

        RiskApp.callApi('selectBranchSummary.do', {}, function(res) {
            var data = res.data || [];
            for (var i = 0; i < data.length; i++) {
                var branch = (data[i].branchNm || '').trim();
                if (branch) {
                    branchSet[branch] = true;
                }
            }
            finishOne();
        }, { onFail: function() { finishOne(); } });

        RiskApp.callApi('selectBranchHqMap.do', {}, function(res) {
            var data = res.data || [];
            for (var i = 0; i < data.length; i++) {
                var hq = (data[i].hqNm || '').trim();
                var branch = (data[i].branchNm || '').trim();
                if (!hq || !branch) {
                    continue;
                }
                hqSet[hq] = true;
                branchSet[branch] = true;
                if (!branchByHq[hq]) {
                    branchByHq[hq] = {};
                }
                branchByHq[hq][branch] = true;
            }
            finishOne();
        }, { onFail: function() { finishOne(); } });

        RiskApp.callApi('selectRegionDistrictSummary.do', {}, function(res) {
            var data = res.data || [];
            for (var i = 0; i < data.length; i++) {
                var region = (data[i].regionNm || '').trim();
                var district = (data[i].districtNm || '').trim();
                if (!region) {
                    continue;
                }
                regionSet[region] = true;
                if (!districtMap[region]) {
                    districtMap[region] = {};
                }
                if (district) {
                    districtMap[region][district] = true;
                }
            }
            finishOne();
        }, { onFail: function() { finishOne(); } });
    }

    function renderWeatherScoreFilterCombos() {
        setSelectOptions($('#weatherSearchHq'), weatherScoreFilterData.hqList);
        updateBranchComboByHq();
        setSelectOptions($('#weatherSearchRegion'), weatherScoreFilterData.regionList);
        updateDistrictComboByRegion();
    }

    function bindWeatherScoreFilterEvents() {
        $('#weatherSearchHq').off('change').on('change', function() {
            updateBranchComboByHq();
        });
        $('#weatherSearchRegion').off('change').on('change', function() {
            updateDistrictComboByRegion();
        });
        $('#btnWeatherScoreSearch').off('click').on('click', function() {
            loadWeatherScore();
        });
    }

    function updateBranchComboByHq() {
        var selectedHq = ($('#weatherSearchHq').val() || '').trim();
        var branches = weatherScoreFilterData.branchList;
        if (selectedHq && weatherScoreFilterData.branchByHq[selectedHq]) {
            branches = weatherScoreFilterData.branchByHq[selectedHq];
        }
        setSelectOptions($('#weatherSearchBranch'), branches);
    }

    function setSelectOptions($select, options) {
        if (!$select || !$select.length) {
            return;
        }
        $select.find('option:gt(0)').remove();
        for (var i = 0; i < options.length; i++) {
            var value = options[i];
            $select.append('<option value="' + escapeHtml(value) + '">' + escapeHtml(value) + '</option>');
        }
    }

    function updateDistrictComboByRegion() {
        var $district = $('#weatherSearchDistrict');
        if (!$district.length) {
            return;
        }
        var selectedRegion = ($('#weatherSearchRegion').val() || '').trim();
        var districts = [];
        if (selectedRegion) {
            var regionMap = weatherScoreFilterData.districtMap[selectedRegion] || {};
            districts = Object.keys(regionMap).sort();
        } else {
            var allSet = {};
            var map = weatherScoreFilterData.districtMap;
            for (var region in map) {
                if (!map.hasOwnProperty(region)) continue;
                var districtsByRegion = map[region];
                for (var district in districtsByRegion) {
                    if (districtsByRegion.hasOwnProperty(district)) {
                        allSet[district] = true;
                    }
                }
            }
            districts = Object.keys(allSet).sort();
        }
        setSelectOptions($district, districts);
    }

    function buildWeatherScoreParams() {
        return {
            hqNm: ($('#weatherSearchHq').val() || '').trim(),
            branchNm: ($('#weatherSearchBranch').val() || '').trim(),
            regionNm: ($('#weatherSearchRegion').val() || '').trim(),
            districtNm: ($('#weatherSearchDistrict').val() || '').trim()
        };
    }

    function escapeHtml(text) {
        return String(text || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatDt(raw) {
        if (!raw || raw.length < 12) return raw || '-';
        return raw.substring(0, 4) + '-' + raw.substring(4, 6) + '-' + raw.substring(6, 8)
             + ' ' + raw.substring(8, 10) + ':' + raw.substring(10, 12);
    }

    function formatNow(dt) {
        var yyyy = dt.getFullYear();
        var mm = String(dt.getMonth() + 1).padStart(2, '0');
        var dd = String(dt.getDate()).padStart(2, '0');
        var hh = String(dt.getHours()).padStart(2, '0');
        var mi = String(dt.getMinutes()).padStart(2, '0');
        return yyyy + '-' + mm + '-' + dd + ' ' + hh + ':' + mi;
    }

    function formatWildfireGrade(rawGrade) {
        var grade = String(rawGrade || '').trim().toUpperCase();
        if (grade === 'DETECTED') return '산불탐지';
        if (grade === 'SEVERE') return '심각';
        if (grade === 'WARNING') return '경계';
        if (grade === 'CAUTION') return '주의';
        if (grade === 'INTEREST') return '관심';
        if (grade === 'NONE' || grade === '') return '없음';
        return rawGrade || '없음';
    }

    function loadWeatherMaps(mapKinds, options) {
        var kindSet = null;
        var forceRefresh = options && options.forceRefresh === true;
        if ($.isArray(mapKinds) && mapKinds.length > 0) {
            kindSet = {};
            for (var i = 0; i < mapKinds.length; i++) {
                kindSet[String(mapKinds[i] || '').toLowerCase()] = true;
            }
        }

        var now = new Date();
        var $updated = $('#weatherMapUpdatedAt');
        if ($updated.length) {
            $updated.text('마지막 갱신: ' + formatNow(now));
        }

        $('.weather-map-image').each(function() {
            var $img = $(this);
            var mapKind = String($img.attr('data-map-kind') || 'wrn').toLowerCase();
            if (kindSet && !kindSet[mapKind]) {
                return;
            }

            var wrn = String($img.attr('data-wrn') || '').toUpperCase();
            var $frame = $img.closest('.weather-map-frame');
            var $state = $frame.find('.weather-map-state');
            $frame.removeClass('map-ready');
            $state.text('불러오는 중...');
            loadSingleWeatherMap($img, mapKind, wrn, $frame, $state, forceRefresh);
        });
    }

    function loadSingleWeatherMap($img, mapKind, wrn, $frame, $state, forceRefresh) {
        var requestUrl = buildMapUrl(mapKind, wrn, forceRefresh);
        if (!requestUrl) {
            $frame.removeClass('map-ready');
            $state.text('지도를 불러오지 못했습니다.');
            return;
        }
        if (mapKind === 'landslide') {
            loadLandslideOverlayMap($frame, $state, forceRefresh);
            return;
        }
        hideLandslideOverlayMap($frame);
        var failSafeTimer = setTimeout(function() {
            if (!$frame.hasClass('map-ready')) {
                $frame.removeClass('map-ready');
                $state.text('지도를 불러오지 못했습니다.');
            }
        }, 12000);

        $.ajax({
            url: requestUrl,
            method: 'GET',
            dataType: 'text',
            cache: false,
            timeout: 10000,
            success: function(raw, _status, xhr) {
                var base64 = normalizeBase64Payload(raw);
                bindMapImageHandlers($img, $frame, $state);

                if (base64) {
                    var mime = normalizeMimeType(xhr.getResponseHeader('Content-Type'));
                    if (setImageFromBase64($img, base64, mime)) {
                        // Keep a fallback ready state for cases where load event is delayed.
                        $frame.addClass('map-ready');
                        clearTimeout(failSafeTimer);
                        return;
                    }
                    return;
                }

                if (looksLikeHtml(raw)) {
                    $frame.removeClass('map-ready');
                    $state.text('세션이 만료되었습니다. 다시 로그인해 주세요.');
                    clearTimeout(failSafeTimer);
                    return;
                }

                // Fallback path if upstream starts returning a binary image body.
                revokeImageObjectUrl($img);
                $img.attr('src', requestUrl);
            },
            error: function() {
                $frame.removeClass('map-ready');
                $state.text('지도를 불러오지 못했습니다.');
                clearTimeout(failSafeTimer);
            },
            complete: function() {
                clearTimeout(failSafeTimer);
            }
        });
    }

    function bindMapImageHandlers($img, $frame, $state) {
        $img.off('load.weatherMap error.weatherMap');
        $img.on('load.weatherMap', function() {
            $frame.addClass('map-ready');
        });
        $img.on('error.weatherMap', function() {
            $frame.removeClass('map-ready');
            $state.text('지도를 불러오지 못했습니다.');
        });
    }

    function normalizeBase64Payload(raw) {
        if (raw == null) {
            return '';
        }
        var text = String(raw).trim();
        if (text.length > 1 && text.charAt(0) === '"' && text.charAt(text.length - 1) === '"') {
            text = text.substring(1, text.length - 1);
        }
        text = text.replace(/\s+/g, '');
        if (/^(iVBOR|R0lGOD|\/9j\/)/.test(text)) {
            return text;
        }
        return '';
    }

    function normalizeMimeType(rawContentType) {
        var ct = (rawContentType || '').split(';')[0].trim().toLowerCase();
        if (ct.indexOf('image/') === 0) {
            return ct;
        }
        return 'image/png';
    }

    function looksLikeHtml(raw) {
        if (raw == null) return false;
        var text = String(raw).trim().toLowerCase();
        return text.indexOf('<!doctype html') === 0 || text.indexOf('<html') === 0;
    }

    function buildMapUrl(mapKind, wrn, forceRefresh) {
        var nonce = '&_=' + Date.now();
        var force = forceRefresh ? '&force=1' : '';
        if (mapKind === 'gk2a') {
            return 'weatherSatelliteMapImage.do?' + nonce.substring(1) + force;
        }
        if (mapKind === 'wildfire') {
            return 'weatherWildfireMapImage.do?' + nonce.substring(1) + force;
        }
        if (mapKind === 'landslide') {
            return 'weatherLandslideMapImage.do?' + nonce.substring(1) + '&force=1';
        }
        return 'weatherWarningMapImage.do?wrn='
            + encodeURIComponent(wrn || 'W,R,C,D,O,N,V,T,S,Y,H,F')
            + force
            + nonce;
    }

    function buildLandslideOverlayUrl(forceRefresh) {
        return 'weatherLandslideOverlayImage.do?_=' + Date.now() + (forceRefresh ? '&force=1' : '');
    }

    function buildLandslideOverlayMetaUrl() {
        return 'weatherLandslideOverlayMeta.do?_=' + Date.now();
    }

    function hideLandslideOverlayMap($frame) {
        $frame.removeClass('is-landslide-map');
    }

    function ensureLandslideMapElements($frame) {
        var $canvas = $frame.find('.weather-landslide-map-canvas');
        if (!$canvas.length) {
            $canvas = $('<div class="weather-landslide-map-canvas" aria-label="산사태위험도 확대 지도"></div>');
            $frame.append($canvas);
        }

        if (!$frame.find('.weather-landslide-map-legend').length) {
            $frame.append(
                '<div class="weather-landslide-map-legend">' +
                    '<strong>산사태 위험등급</strong>' +
                    '<span><i style="background:#ff0000"></i>1등급</span>' +
                    '<span><i style="background:#ffc900"></i>2등급</span>' +
                    '<span><i style="background:#b6ff8e"></i>3등급</span>' +
                    '<span><i style="background:#30c2ff"></i>4등급</span>' +
                    '<span><i style="background:#0000ff"></i>5등급</span>' +
                '</div>'
            );
        }

        return $canvas.get(0);
    }

    function loadLandslideOverlayMap($frame, $state, forceRefresh) {
        if (!window.ol || !ol.Map || !ol.layer || !ol.source || !ol.proj) {
            $frame.removeClass('is-landslide-map map-ready');
            $state.text('지도 라이브러리를 불러오지 못했습니다.');
            return;
        }

        $frame.addClass('is-landslide-map');
        $frame.removeClass('map-ready');
        $state.text('산사태 지도를 불러오는 중...');
        var target = ensureLandslideMapElements($frame);

        $.ajax({
            url: buildLandslideOverlayMetaUrl(),
            method: 'GET',
            dataType: 'json',
            cache: false,
            timeout: 10000,
            success: function(meta) {
                try {
                    renderLandslideOverlayMap(target, normalizeLandslideOverlayMeta(meta), buildLandslideOverlayUrl(forceRefresh));
                    $frame.addClass('map-ready');
                } catch (e) {
                    $frame.removeClass('map-ready');
                    $state.text('산사태 지도를 불러오지 못했습니다.');
                }
            },
            error: function() {
                $frame.removeClass('map-ready');
                $state.text('산사태 지도를 불러오지 못했습니다.');
            }
        });
    }

    function normalizeLandslideOverlayMeta(rawMeta) {
        if (rawMeta && typeof rawMeta === 'object') {
            return rawMeta;
        }
        if (typeof rawMeta === 'string') {
            var text = rawMeta.trim();
            if (/^[A-Za-z0-9+/=]+$/.test(text)) {
                text = atob(text);
            }
            return JSON.parse(text);
        }
        throw new Error('Invalid landslide overlay meta response');
    }

    function renderLandslideOverlayMap(target, meta, overlayUrl) {
        var west = Number(meta && meta.west);
        var south = Number(meta && meta.south);
        var east = Number(meta && meta.east);
        var north = Number(meta && meta.north);
        if (!isFinite(west) || !isFinite(south) || !isFinite(east) || !isFinite(north)) {
            throw new Error('Invalid landslide overlay bounds');
        }

        var extent = ol.proj.transformExtent([west, south, east, north], 'EPSG:4326', 'EPSG:3857');
        var overlayLayer = new ol.layer.Image({
            opacity: 0.78,
            source: new ol.source.ImageStatic({
                url: overlayUrl,
                imageExtent: extent,
                projection: 'EPSG:3857',
                crossOrigin: 'anonymous'
            })
        });

        if (!landslideMapState.map || landslideMapState.target !== target) {
            var baseLayer = new ol.layer.Tile({
                source: new ol.source.XYZ({
                    url: 'https://xdworld.vworld.kr/2d/Base/service/{z}/{x}/{y}.png',
                    crossOrigin: 'anonymous'
                })
            });
            landslideMapState.baseLayer = baseLayer;
            landslideMapState.map = new ol.Map({
                target: target,
                layers: [baseLayer, overlayLayer],
                view: new ol.View({
                    center: ol.proj.fromLonLat([(west + east) / 2, (south + north) / 2]),
                    zoom: 8,
                    minZoom: 6,
                    maxZoom: 15
                }),
                controls: ol.control.defaults({ attribution: true, rotate: false }),
                interactions: ol.interaction.defaults({
                    altShiftDragRotate: false,
                    pinchRotate: false
                })
            });
            landslideMapState.target = target;
        } else {
            if (landslideMapState.overlayLayer) {
                landslideMapState.map.removeLayer(landslideMapState.overlayLayer);
            }
            landslideMapState.map.addLayer(overlayLayer);
        }

        landslideMapState.overlayLayer = overlayLayer;
        landslideMapState.map.getView().fit(extent, {
            padding: [28, 28, 28, 28],
            duration: 250,
            nearest: true
        });
        setTimeout(function() {
            landslideMapState.map.updateSize();
        }, 0);
    }

    function setImageFromBase64($img, base64, mime) {
        try {
            var binary = atob(base64);
            var len = binary.length;
            var bytes = new Uint8Array(len);
            for (var i = 0; i < len; i++) {
                bytes[i] = binary.charCodeAt(i);
            }
            var blob = new Blob([bytes], { type: mime || 'image/png' });
            var objectUrl = URL.createObjectURL(blob);
            revokeImageObjectUrl($img);
            $img.data('objectUrl', objectUrl);
            $img.attr('src', objectUrl);
            return true;
        } catch (e) {
            // Fallback to data URL only if Blob conversion fails.
            try {
                revokeImageObjectUrl($img);
                $img.attr('src', 'data:' + (mime || 'image/png') + ';base64,' + base64);
                return true;
            } catch (ignore) {
                return false;
            }
        }
    }

    function revokeImageObjectUrl($img) {
        var oldUrl = $img.data('objectUrl');
        if (oldUrl) {
            try {
                URL.revokeObjectURL(oldUrl);
            } catch (ignore) {}
            $img.removeData('objectUrl');
        }
    }

    function loadAlertToday() {
        RiskApp.callApi('selectWeatherAlertToday.do', {}, function(res) {
            var data = res.data || [];
            for (var i = 0; i < data.length; i++) {
                data[i].issueDtFmt = formatDt(data[i].issueDt);
                data[i].effectDtFmt = formatDt(data[i].effectDt);
            }
            var columns = [
                { id: 'alertType', title: '특보종류', width: 70 },
                { id: 'alertLevel', title: '수준', width: 55 },
                { id: 'alertCmd', title: '명령', width: 50 },
                { id: 'regionNm', title: '특보구역', width: 130, align: 'left' },
                { id: 'parentRegion', title: '상위구역', width: 90 },
                { id: 'issueDtFmt', title: '발표시각', width: 120 },
                { id: 'effectDtFmt', title: '발효시각', width: 120 }
            ];
            RiskApp.createGrid('sbGridAlert', columns, data);
        });
    }

    function loadWeatherScore() {
        RiskApp.callApi('selectWeatherRiskScore.do', buildWeatherScoreParams(), function(res) {
            var data = res.data || [];
            for (var i = 0; i < data.length; i++) {
                data[i].wildfireTmFmt = formatDt(data[i].wildfireTm);
                data[i].wildfireGradeKo = formatWildfireGrade(data[i].wildfireGrade);
            }
            var columns = [
                { id: 'regionNm', title: '지역', width: 80 },
                { id: 'districtNm', title: '시군구', width: 80 },
                { id: 'weatherScore', title: '기상점수', width: 70 },
                { id: 'wildfireScore', title: '산불점수', width: 70 },
                { id: 'wildfireGradeKo', title: '산불등급', width: 80 },
                { id: 'wildfireTmFmt', title: '산불기준시각', width: 120 },
                { id: 'appliedAlerts', title: '적용 특보', width: 250, align: 'left' }
            ];
            RiskApp.createGrid('sbGridScore', columns, data);
        });
    }
})();
