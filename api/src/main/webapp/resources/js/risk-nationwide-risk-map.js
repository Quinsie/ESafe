(function(global, $) {
    'use strict';

    var BRANCH_NAME = '\uAD11\uC8FC\uC804\uB0A8\uBCF8\uBD80\uC9C1\uD560';
    var DISTRICT_URL = 'selectRiskMapDistrictLayer.do';
    var BUILDING_URL = 'selectRiskMapBuildingLayer.do';
    var BUILDING_POLYGON_URL = 'selectRiskMapBuildingPolygonLayer.do';
    var ZOOM_BUILDING = 14;
    var ZOOM_POLYGON = 16;
    var BUILDING_POINT_MAX_ROWS = 20000;
    var BUILDING_POLYGON_MAX_ROWS = 1500;
    var DEFAULT_CENTER = [126.8514, 35.1601];
    var DEFAULT_ZOOM = 8;
    var MIN_ZOOM = 7;
    var MAX_ZOOM = 19;
    var REQUEST_DEBOUNCE_MS = 220;

    var RISK_META = {
        A: { label: '\uC548\uC804', color: '#1e934c', fill: 'rgba(30, 147, 76, 0.72)' },
        B: { label: '\uAD00\uC2EC', color: '#215fd1', fill: 'rgba(33, 95, 209, 0.72)' },
        C: { label: '\uC8FC\uC758', color: '#d8b300', fill: 'rgba(216, 179, 0, 0.74)' },
        D: { label: '\uACBD\uACE0', color: '#ea7a19', fill: 'rgba(234, 122, 25, 0.75)' },
        E: { label: '\uC704\uD5D8', color: '#cf2f22', fill: 'rgba(207, 47, 34, 0.76)' }
    };

    var state = {
        map: null,
        mapEngine: 'openlayers',
        mapTarget: null,
        districtSource: null,
        buildingSource: null,
        polygonSource: null,
        popupOverlay: null,
        popupElement: null,
        popupContentElement: null,
        statusElement: null,
        districtRows: [],
        activeRiskCodes: ['A', 'B', 'C', 'D', 'E'],
        pointRequest: null,
        polygonRequest: null,
        requestTimer: null,
        requestToken: 0,
        hovered: false,
        globalWheelBound: false,
        styleCache: {
            district: {},
            building: {},
            polygon: {}
        }
    };

    function toNumber(value) {
        if (value === null || value === undefined || value === '') {
            return NaN;
        }
        var numberValue = Number(value);
        return isFinite(numberValue) ? numberValue : NaN;
    }

    function isValidLatLon(lat, lon) {
        return isFinite(lat) && isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
    }

    function isLikelyProjected5186(x, y) {
        return isFinite(x) && isFinite(y) && x >= 100000 && x <= 400000 && y >= 100000 && y <= 700000;
    }

    function toRadians(value) {
        return value * Math.PI / 180.0;
    }

    function toDegrees(value) {
        return value * 180.0 / Math.PI;
    }

    function meridionalArc(a, e2, lat) {
        return a * (
            (1 - e2 / 4 - 3 * Math.pow(e2, 2) / 64 - 5 * Math.pow(e2, 3) / 256) * lat
            - (3 * e2 / 8 + 3 * Math.pow(e2, 2) / 32 + 45 * Math.pow(e2, 3) / 1024) * Math.sin(2 * lat)
            + (15 * Math.pow(e2, 2) / 256 + 45 * Math.pow(e2, 3) / 1024) * Math.sin(4 * lat)
            - (35 * Math.pow(e2, 3) / 3072) * Math.sin(6 * lat)
        );
    }

    function epsg5186ToWgs84(x, y) {
        if (!isLikelyProjected5186(x, y)) {
            return null;
        }

        var a = 6378137.0;
        var f = 1.0 / 298.257222101;
        var e2 = 2 * f - f * f;
        var ep2 = e2 / (1 - e2);
        var lat0 = toRadians(38.0);
        var lon0 = toRadians(127.0);
        var k0 = 1.0;
        var falseEasting = 200000.0;
        var falseNorthing = 600000.0;
        var m0 = meridionalArc(a, e2, lat0);
        var m = m0 + (y - falseNorthing) / k0;
        var mu = m / (a * (1 - e2 / 4.0 - 3 * Math.pow(e2, 2) / 64.0 - 5 * Math.pow(e2, 3) / 256.0));

        var e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
        var j1 = 3 * e1 / 2 - 27 * Math.pow(e1, 3) / 32;
        var j2 = 21 * Math.pow(e1, 2) / 16 - 55 * Math.pow(e1, 4) / 32;
        var j3 = 151 * Math.pow(e1, 3) / 96;
        var j4 = 1097 * Math.pow(e1, 4) / 512;

        var fp = mu
            + j1 * Math.sin(2 * mu)
            + j2 * Math.sin(4 * mu)
            + j3 * Math.sin(6 * mu)
            + j4 * Math.sin(8 * mu);

        var sinFp = Math.sin(fp);
        var cosFp = Math.cos(fp);
        var tanFp = Math.tan(fp);
        var c1 = ep2 * cosFp * cosFp;
        var t1 = tanFp * tanFp;
        var n1 = a / Math.sqrt(1 - e2 * sinFp * sinFp);
        var r1 = a * (1 - e2) / Math.pow(1 - e2 * sinFp * sinFp, 1.5);
        var d = (x - falseEasting) / (n1 * k0);

        var lat = fp - (n1 * tanFp / r1) * (
            d * d / 2
            - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * Math.pow(d, 4) / 24
            + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * Math.pow(d, 6) / 720
        );
        var lon = lon0 + (
            d
            - (1 + 2 * t1 + c1) * Math.pow(d, 3) / 6
            + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * Math.pow(d, 5) / 120
        ) / cosFp;

        var lonDeg = toDegrees(lon);
        var latDeg = toDegrees(lat);
        return isValidLatLon(latDeg, lonDeg) ? { lat: latDeg, lon: lonDeg } : null;
    }

    function wgs84ToEpsg5186(lon, lat) {
        if (!isValidLatLon(lat, lon)) {
            return null;
        }

        var a = 6378137.0;
        var f = 1.0 / 298.257222101;
        var e2 = 2 * f - f * f;
        var ep2 = e2 / (1 - e2);
        var latRad = toRadians(lat);
        var lonRad = toRadians(lon);
        var lat0 = toRadians(38.0);
        var lon0 = toRadians(127.0);
        var k0 = 1.0;
        var falseEasting = 200000.0;
        var falseNorthing = 600000.0;

        var sinLat = Math.sin(latRad);
        var cosLat = Math.cos(latRad);
        var tanLat = Math.tan(latRad);
        var n = a / Math.sqrt(1 - e2 * sinLat * sinLat);
        var t = tanLat * tanLat;
        var c = ep2 * cosLat * cosLat;
        var aTerm = (lonRad - lon0) * cosLat;
        var m = meridionalArc(a, e2, latRad);
        var m0 = meridionalArc(a, e2, lat0);

        var x = falseEasting + k0 * n * (
            aTerm
            + (1 - t + c) * Math.pow(aTerm, 3) / 6
            + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * Math.pow(aTerm, 5) / 120
        );
        var y = falseNorthing + k0 * (
            m - m0
            + n * tanLat * (
                Math.pow(aTerm, 2) / 2
                + (5 - t + 9 * c + 4 * c * c) * Math.pow(aTerm, 4) / 24
                + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * Math.pow(aTerm, 6) / 720
            )
        );

        return { x: x, y: y };
    }

    function escapeHtml(value) {
        if (value === null || value === undefined) {
            return '';
        }
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function getRiskMeta(riskCd) {
        return RISK_META[riskCd] || { label: riskCd || '-', color: '#7d8794', fill: 'rgba(125, 135, 148, 0.68)' };
    }

    function getSelectedRiskCodes() {
        return $('#nationwideGradeFilter input[type="checkbox"]:checked').map(function() {
            return String(this.value || '').toUpperCase();
        }).get();
    }

    function isRiskVisible(riskCd) {
        return state.activeRiskCodes.indexOf(String(riskCd || '').toUpperCase()) >= 0;
    }

    function describeActiveGrades() {
        if (!state.activeRiskCodes.length) {
            return '\uC5C6\uC74C';
        }
        return state.activeRiskCodes.map(function(riskCd) {
            return getRiskMeta(riskCd).label;
        }).join(', ');
    }

    function getMode() {
        var zoom = state.map ? state.map.getView().getZoom() : DEFAULT_ZOOM;
        if (zoom >= ZOOM_POLYGON) {
            return 'polygon';
        }
        if (zoom >= ZOOM_BUILDING) {
            return 'point';
        }
        return 'district';
    }

    function getDistrictStyle(riskCd) {
        var cacheKey = riskCd || 'default';
        if (!state.styleCache.district[cacheKey]) {
            var meta = getRiskMeta(riskCd);
            state.styleCache.district[cacheKey] = new ol.style.Style({
                image: new ol.style.Circle({
                    radius: 9.6,
                    fill: new ol.style.Fill({ color: meta.fill }),
                    stroke: new ol.style.Stroke({ color: '#111111', width: 2.8 })
                }),
                text: new ol.style.Text({
                    font: '600 11px "Malgun Gothic", sans-serif',
                    fill: new ol.style.Fill({ color: '#17202a' }),
                    stroke: new ol.style.Stroke({ color: 'rgba(255,255,255,0.9)', width: 3 }),
                    offsetY: 20
                })
            });
        }
        return state.styleCache.district[cacheKey];
    }

    function getBuildingStyle(riskCd) {
        var cacheKey = riskCd || 'default';
        if (!state.styleCache.building[cacheKey]) {
            var meta = getRiskMeta(riskCd);
            state.styleCache.building[cacheKey] = new ol.style.Style({
                image: new ol.style.Circle({
                    radius: 5.2,
                    fill: new ol.style.Fill({ color: meta.color }),
                    stroke: new ol.style.Stroke({ color: '#111111', width: 2.2 })
                })
            });
        }
        return state.styleCache.building[cacheKey];
    }

    function getPolygonStyle(riskCd) {
        var cacheKey = riskCd || 'default';
        if (!state.styleCache.polygon[cacheKey]) {
            var meta = getRiskMeta(riskCd);
            state.styleCache.polygon[cacheKey] = new ol.style.Style({
                fill: new ol.style.Fill({ color: meta.fill }),
                stroke: new ol.style.Stroke({ color: '#111111', width: 2.4 })
            });
        }
        return state.styleCache.polygon[cacheKey];
    }

    function setStatus(message) {
        if (state.statusElement) {
            state.statusElement.textContent = message;
        }
    }

    function clampZoom(zoom) {
        var view = state.map ? state.map.getView() : null;
        if (!view) {
            return zoom;
        }
        var minZoom = typeof view.getMinZoom === 'function' ? view.getMinZoom() : MIN_ZOOM;
        var maxZoom = typeof view.getMaxZoom === 'function' ? view.getMaxZoom() : MAX_ZOOM;
        return Math.max(minZoom, Math.min(maxZoom, zoom));
    }

    function handleManualWheelZoom(event) {
        if (!state.map || !state.mapTarget) {
            return;
        }
        var rect = state.mapTarget.getBoundingClientRect();
        var clientX = typeof event.clientX === 'number' ? event.clientX : -1;
        var clientY = typeof event.clientY === 'number' ? event.clientY : -1;
        var inside = state.hovered
            || (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom);
        if (!inside) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        if (typeof event.stopImmediatePropagation === 'function') {
            event.stopImmediatePropagation();
        }

        var view = state.map.getView();
        var currentZoom = view.getZoom();
        if (!isFinite(currentZoom)) {
            currentZoom = DEFAULT_ZOOM;
        }

        var delta = event.deltaY > 0 ? -0.75 : 0.75;
        var nextZoom = clampZoom(currentZoom + delta);
        view.setZoom(nextZoom);
    }

    function changeZoom(step) {
        if (!state.map) {
            return;
        }
        var view = state.map.getView();
        var currentZoom = view.getZoom();
        if (!isFinite(currentZoom)) {
            currentZoom = DEFAULT_ZOOM;
        }
        view.setZoom(clampZoom(currentZoom + step));
    }

    function createZoomControls(target) {
        var control = document.createElement('div');
        control.className = 'nationwide-map-zoom';

        var plusButton = document.createElement('button');
        plusButton.type = 'button';
        plusButton.className = 'zoom-in';
        plusButton.textContent = '+';

        var minusButton = document.createElement('button');
        minusButton.type = 'button';
        minusButton.className = 'zoom-out';
        minusButton.textContent = '-';

        plusButton.addEventListener('click', function() {
            changeZoom(1);
        });
        minusButton.addEventListener('click', function() {
            changeZoom(-1);
        });

        control.appendChild(plusButton);
        control.appendChild(minusButton);
        target.appendChild(control);
    }

    function bindManualWheelZoom(target) {
        state.mapTarget = target;
        target.addEventListener('mouseenter', function() {
            state.hovered = true;
            target.focus();
        });
        target.addEventListener('mouseleave', function() {
            state.hovered = false;
        });
        if (!state.globalWheelBound) {
            document.addEventListener('wheel', handleManualWheelZoom, {
                passive: false,
                capture: true
            });
            document.addEventListener('mousewheel', handleManualWheelZoom, {
                passive: false,
                capture: true
            });
            state.globalWheelBound = true;
        }
    }

    function buildViewportBbox() {
        var extent = state.map.getView().calculateExtent(state.map.getSize());
        var corners3857 = [
            [extent[0], extent[1]],
            [extent[0], extent[3]],
            [extent[2], extent[1]],
            [extent[2], extent[3]]
        ];
        var projected = [];
        for (var i = 0; i < corners3857.length; i += 1) {
            var lonLat = ol.proj.transform(corners3857[i], 'EPSG:3857', 'EPSG:4326');
            var converted = wgs84ToEpsg5186(lonLat[0], lonLat[1]);
            if (converted) {
                projected.push(converted);
            }
        }
        if (!projected.length) {
            return null;
        }
        var xs = projected.map(function(item) { return item.x; });
        var ys = projected.map(function(item) { return item.y; });
        return {
            minLon: Math.min.apply(null, xs),
            minLat: Math.min.apply(null, ys),
            maxLon: Math.max.apply(null, xs),
            maxLat: Math.max.apply(null, ys)
        };
    }

    function createDistrictFeature(row) {
        var projected = epsg5186ToWgs84(toNumber(row.centerLon), toNumber(row.centerLat));
        if (!projected) {
            return null;
        }
        var feature = new ol.Feature({
            geometry: new ol.geom.Point(ol.proj.fromLonLat([projected.lon, projected.lat]))
        });
        feature.setProperties({
            layerType: 'district',
            row: row
        });
        return feature;
    }

    function createBuildingFeature(row) {
        var projected = epsg5186ToWgs84(toNumber(row.lon), toNumber(row.lat));
        if (!projected) {
            return null;
        }
        var feature = new ol.Feature({
            geometry: new ol.geom.Point(ol.proj.fromLonLat([projected.lon, projected.lat]))
        });
        feature.setProperties({
            layerType: 'building',
            row: row
        });
        return feature;
    }

    function createPolygonFeature(row) {
        var rings = row && row.rings;
        if (!Array.isArray(rings) || !rings.length) {
            return null;
        }
        var coordinates = [];
        for (var i = 0; i < rings.length; i += 1) {
            var ring = rings[i];
            if (!Array.isArray(ring) || ring.length < 4) {
                continue;
            }
            var ringCoordinates = [];
            for (var j = 0; j < ring.length; j += 1) {
                var point = ring[j];
                if (!Array.isArray(point) || point.length < 2) {
                    continue;
                }
                var converted = epsg5186ToWgs84(toNumber(point[0]), toNumber(point[1]));
                if (converted) {
                    ringCoordinates.push(ol.proj.fromLonLat([converted.lon, converted.lat]));
                }
            }
            if (ringCoordinates.length >= 4) {
                coordinates.push(ringCoordinates);
            }
        }
        if (!coordinates.length) {
            return null;
        }
        var feature = new ol.Feature({
            geometry: new ol.geom.Polygon(coordinates)
        });
        feature.setProperties({
            layerType: 'polygon',
            row: row
        });
        return feature;
    }

    function renderDistrictFeatures() {
        state.districtSource.clear();
        if (getMode() !== 'district') {
            return 0;
        }
        var visibleRows = state.districtRows.filter(function(row) {
            return isRiskVisible(row.riskCd);
        });
        visibleRows.forEach(function(row) {
            var feature = createDistrictFeature(row);
            if (feature) {
                state.districtSource.addFeature(feature);
            }
        });
        return visibleRows.length;
    }

    function clearBuildingLayers() {
        state.buildingSource.clear();
        state.polygonSource.clear();
    }

    function abortPendingRequests() {
        if (state.pointRequest && typeof state.pointRequest.abort === 'function') {
            state.pointRequest.abort();
        }
        if (state.polygonRequest && typeof state.polygonRequest.abort === 'function') {
            state.polygonRequest.abort();
        }
        state.pointRequest = null;
        state.polygonRequest = null;
    }

    function buildRiskParams(bbox, maxRows) {
        return {
            branchNm: BRANCH_NAME,
            minLon: bbox.minLon,
            minLat: bbox.minLat,
            maxLon: bbox.maxLon,
            maxLat: bbox.maxLat,
            maxRows: maxRows,
            riskCdList: state.activeRiskCodes
        };
    }

    function updateStatusForDistrict(count) {
        setStatus(
            '\uAD6C\uC5ED \uB808\uC774\uC5B4 ' + count + '\uAC1C'
            + ' | \uD45C\uC2DC \uB4F1\uAE09: ' + describeActiveGrades()
            + ' | \uD655\uB300 \uC90C ' + ZOOM_BUILDING + '+\uC5D0\uC11C \uAC74\uBB3C \uB808\uC774\uC5B4 \uD45C\uC2DC'
        );
    }

    function updateStatusForBuilding(mode, response) {
        var subject = mode === 'polygon'
            ? '\uAC74\uBB3C \uD3F4\uB9AC\uACE4'
            : '\uAC74\uBB3C \uD3EC\uC778\uD2B8';
        var summary = subject + ' ' + (response.visibleCount || 0) + '\uAC1C';
        if (response.totalCount !== undefined && response.totalCount !== null) {
            summary += ' / \uC804\uCCB4 ' + response.totalCount + '\uAC1C';
        }
        if (response.truncated) {
            summary += ' (' + (response.maxRows || 0) + '\uAC1C \uC0C1\uD55C)';
        }
        summary += ' | \uD45C\uC2DC \uB4F1\uAE09: ' + describeActiveGrades();
        setStatus(summary);
    }

    function renderBuildingRows(rows, mode) {
        clearBuildingLayers();
        var count = 0;
        rows.forEach(function(row) {
            var feature = mode === 'polygon' ? createPolygonFeature(row) : createBuildingFeature(row);
            if (!feature) {
                return;
            }
            if (mode === 'polygon') {
                state.polygonSource.addFeature(feature);
            } else {
                state.buildingSource.addFeature(feature);
            }
            count += 1;
        });
        return count;
    }

    function requestBuildingLayer(mode) {
        if (!state.activeRiskCodes.length) {
            clearBuildingLayers();
            setStatus('\uD45C\uC2DC\uD560 \uB4F1\uAE09\uC744 \uC120\uD0DD\uD558\uC138\uC694.');
            return;
        }

        var bbox = buildViewportBbox();
        if (!bbox) {
            clearBuildingLayers();
            setStatus('\uC9C0\uB3C4 \uBC94\uC704\uB97C \uACC4\uC0B0\uD558\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4.');
            return;
        }

        abortPendingRequests();
        var requestToken = ++state.requestToken;
        var url = mode === 'polygon' ? BUILDING_POLYGON_URL : BUILDING_URL;
        var maxRows = mode === 'polygon' ? BUILDING_POLYGON_MAX_ROWS : BUILDING_POINT_MAX_ROWS;

        setStatus(
            (mode === 'polygon' ? '\uAC74\uBB3C \uD3F4\uB9AC\uACE4' : '\uAC74\uBB3C \uD3EC\uC778\uD2B8')
            + ' \uB85C\uB529 \uC911...'
        );

        var request = $.ajax({
            url: url,
            method: 'GET',
            dataType: 'json',
            traditional: true,
            data: buildRiskParams(bbox, maxRows)
        });

        if (mode === 'polygon') {
            state.polygonRequest = request;
        } else {
            state.pointRequest = request;
        }

        request.done(function(response) {
            if (requestToken !== state.requestToken) {
                return;
            }
            var rows = response && $.isArray(response.data) ? response.data : [];
            renderBuildingRows(rows, mode);
            updateStatusForBuilding(mode, response || {});
        }).fail(function(xhr, textStatus) {
            if (textStatus === 'abort') {
                return;
            }
            clearBuildingLayers();
            setStatus('\uAC74\uBB3C \uB808\uC774\uC5B4 \uC870\uD68C\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.');
        }).always(function() {
            if (mode === 'polygon') {
                state.polygonRequest = null;
            } else {
                state.pointRequest = null;
            }
        });
    }

    function refreshLayers(forceDistrictFetch) {
        state.activeRiskCodes = getSelectedRiskCodes();
        clearPopup();

        if (!state.activeRiskCodes.length) {
            state.districtSource.clear();
            clearBuildingLayers();
            setStatus('\uD45C\uC2DC\uD560 \uB4F1\uAE09\uC744 \uC120\uD0DD\uD558\uC138\uC694.');
            return;
        }

        var mode = getMode();
        var districtCount = renderDistrictFeatures();
        if (mode === 'district') {
            clearBuildingLayers();
            updateStatusForDistrict(districtCount);
            return;
        }

        state.districtSource.clear();
        requestBuildingLayer(mode);

        if (forceDistrictFetch || !state.districtRows.length) {
            loadDistrictLayer(false);
        }
    }

    function scheduleRefresh(forceDistrictFetch) {
        if (state.requestTimer) {
            global.clearTimeout(state.requestTimer);
        }
        state.requestTimer = global.setTimeout(function() {
            refreshLayers(forceDistrictFetch);
        }, REQUEST_DEBOUNCE_MS);
    }

    function loadDistrictLayer(refreshAfterLoad) {
        setStatus('\uAD6C\uC5ED \uB808\uC774\uC5B4 \uB85C\uB529 \uC911...');
        $.ajax({
            url: DISTRICT_URL,
            method: 'GET',
            dataType: 'json',
            data: { branchNm: BRANCH_NAME }
        }).done(function(response) {
            state.districtRows = response && $.isArray(response.data) ? response.data : [];
            if (refreshAfterLoad !== false) {
                refreshLayers(false);
            }
        }).fail(function() {
            state.districtRows = [];
            state.districtSource.clear();
            setStatus('\uAD6C\uC5ED \uB808\uC774\uC5B4 \uC870\uD68C\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.');
        });
    }

    function buildDistrictPopup(row) {
        var meta = getRiskMeta(row.riskCd);
        return ''
            + '<div style="font-weight:700;font-size:13px;margin-bottom:6px;">' + escapeHtml(row.districtNm || row.regionNm || '-') + '</div>'
            + '<div style="margin-bottom:4px;">\uB4F1\uAE09: <strong style="color:' + meta.color + ';">' + escapeHtml(meta.label) + '</strong></div>'
            + '<div style="margin-bottom:4px;">\uD3C9\uADE0 \uC885\uD569\uC810\uC218: <strong>' + escapeHtml(row.avgScore || '-') + '</strong></div>'
            + '<div>\uAC74\uBB3C \uC218: <strong>' + escapeHtml(row.bldgCnt || '-') + '</strong></div>';
    }

    function buildBuildingPopup(row) {
        var meta = getRiskMeta(row.riskCd);
        var detailUrl = 'riskBuildingDetail.do?bldgSeq=' + encodeURIComponent(row.bldgSeq || '');
        return ''
            + '<div style="font-weight:700;font-size:13px;margin-bottom:6px;">' + escapeHtml(row.bldgNm || '\uAC74\uBB3C') + '</div>'
            + '<div style="margin-bottom:4px;">' + escapeHtml(row.addr || '-') + '</div>'
            + '<div style="margin-bottom:4px;">\uB4F1\uAE09: <strong style="color:' + meta.color + ';">' + escapeHtml(meta.label) + '</strong></div>'
            + '<div style="margin-bottom:8px;">\uC885\uD569\uC810\uC218: <strong>' + escapeHtml(row.totalScore || row.combinedScore || '-') + '</strong></div>'
            + '<a href="' + detailUrl + '" style="color:#1c5db6;font-weight:700;text-decoration:none;">\uAC74\uBB3C \uC0C1\uC138 \uBCF4\uAE30</a>';
    }

    function clearPopup() {
        if (state.popupOverlay) {
            state.popupOverlay.setPosition(undefined);
        }
    }

    function initPopup(mapContainer) {
        var popup = document.createElement('div');
        popup.style.position = 'absolute';
        popup.style.minWidth = '220px';
        popup.style.maxWidth = '280px';
        popup.style.padding = '10px 12px';
        popup.style.background = 'rgba(255,255,255,0.97)';
        popup.style.border = '1px solid #c7d2df';
        popup.style.borderRadius = '8px';
        popup.style.boxShadow = '0 10px 28px rgba(14, 24, 38, 0.18)';
        popup.style.fontSize = '12px';
        popup.style.lineHeight = '1.55';
        popup.style.color = '#1f2b37';

        var closer = document.createElement('button');
        closer.type = 'button';
        closer.textContent = 'x';
        closer.style.position = 'absolute';
        closer.style.top = '6px';
        closer.style.right = '8px';
        closer.style.border = 'none';
        closer.style.background = 'transparent';
        closer.style.cursor = 'pointer';
        closer.style.color = '#51606f';
        popup.appendChild(closer);

        var content = document.createElement('div');
        content.style.paddingRight = '14px';
        popup.appendChild(content);
        mapContainer.appendChild(popup);

        closer.addEventListener('click', function() {
            clearPopup();
        });

        state.popupElement = popup;
        state.popupContentElement = content;
        state.popupOverlay = new ol.Overlay({
            element: popup,
            positioning: 'bottom-center',
            stopEvent: true,
            offset: [0, -12]
        });
        state.map.addOverlay(state.popupOverlay);
    }

    function showFeaturePopup(feature, coordinate) {
        var row = feature.get('row') || {};
        var layerType = feature.get('layerType');
        if (layerType === 'district') {
            state.popupContentElement.innerHTML = buildDistrictPopup(row);
        } else {
            state.popupContentElement.innerHTML = buildBuildingPopup(row);
        }
        state.popupOverlay.setPosition(coordinate);
    }

    function initMap() {
        var target = document.getElementById('nationwideMapCanvas');
        state.statusElement = document.getElementById('nationwideMapStatus');
        if (!target || typeof ol === 'undefined') {
            setStatus('\uC9C0\uB3C4 \uC5D4\uC9C4\uC744 \uBD88\uB7EC\uC624\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4.');
            return;
        }
        target.setAttribute('tabindex', '0');

        state.districtSource = new ol.source.Vector();
        state.buildingSource = new ol.source.Vector();
        state.polygonSource = new ol.source.Vector();

        var districtLayer = new ol.layer.Vector({
            source: state.districtSource,
            style: function(feature) {
                var row = feature.get('row') || {};
                var style = getDistrictStyle(row.riskCd);
                style.getText().setText(String(row.districtNm || row.regionNm || ''));
                return style;
            }
        });

        var buildingLayer = new ol.layer.Vector({
            source: state.buildingSource,
            style: function(feature) {
                var row = feature.get('row') || {};
                return getBuildingStyle(row.riskCd);
            }
        });

        var polygonLayer = new ol.layer.Vector({
            source: state.polygonSource,
            style: function(feature) {
                var row = feature.get('row') || {};
                return getPolygonStyle(row.riskCd);
            }
        });

        var interactions = ol.interaction.defaults({
            altShiftDragRotate: false,
            pinchRotate: false,
            mouseWheelZoom: false
        });

        var view = new ol.View({
            center: ol.proj.fromLonLat(DEFAULT_CENTER),
            zoom: DEFAULT_ZOOM,
            minZoom: MIN_ZOOM,
            maxZoom: MAX_ZOOM
        });
        var controls = ol.control.defaults({ attribution: true, rotate: false });
        var baseLayer = new ol.layer.Tile({
            source: new ol.source.XYZ({
                url: 'https://xdworld.vworld.kr/2d/Base/service/{z}/{x}/{y}.png',
                crossOrigin: 'anonymous'
            })
        });
        state.map = new ol.Map({
            target: target,
            layers: [baseLayer, districtLayer, polygonLayer, buildingLayer],
            view: view,
            controls: controls,
            interactions: interactions,
            keyboardEventTarget: document
        });
        state.mapEngine = 'openlayers';

        var mapSourceMeta = document.getElementById('nationwideMapSource');
        if (mapSourceMeta) {
            mapSourceMeta.textContent = '\uC9C0\uB3C4 \uC5D4\uC9C4: OpenLayers + VWorld Tiles';
        }

        initPopup(target);
        createZoomControls(target);
        bindManualWheelZoom(target);

        state.map.on('moveend', function() {
            scheduleRefresh(false);
        });

        state.map.on('singleclick', function(evt) {
            var feature = state.map.forEachFeatureAtPixel(evt.pixel, function(hitFeature) {
                return hitFeature;
            });
            if (!feature) {
                clearPopup();
                return;
            }
            showFeaturePopup(feature, evt.coordinate);
        });

        state.map.on('pointermove', function(evt) {
            var hit = state.map.hasFeatureAtPixel(evt.pixel);
            state.map.getTargetElement().style.cursor = hit ? 'pointer' : '';
        });
    }

    function bindEvents() {
        $('#nationwideMapRefreshBtn').on('click', function() {
            loadDistrictLayer(true);
        });

        $('#nationwideGradeFilter').on('change', 'input[type="checkbox"]', function() {
            scheduleRefresh(false);
        });
    }

    $(function() {
        initMap();
        bindEvents();
        loadDistrictLayer(true);
    });
}(window, window.jQuery));
