(function(global) {
    'use strict';

    var MAP_HEIGHT = 430;
    var DEFAULT_ALTITUDE = 2400;
    var MARKER_ALTITUDE = 40;
    var ADDRESS_API_URL = 'https://api.vworld.kr/req/address';

    function toNumber(value) {
        if (value === null || value === undefined || value === '') return NaN;
        var numberValue = Number(value);
        return isFinite(numberValue) ? numberValue : NaN;
    }

    function isValidLatLon(lat, lon) {
        if (!isFinite(lat) || !isFinite(lon)) return false;
        if (lat < -90 || lat > 90) return false;
        if (lon < -180 || lon > 180) return false;
        if (lat === 0 && lon === 0) return false;
        return true;
    }

    function isLikelyKorea(lat, lon) {
        return lat >= 33.0 && lat <= 39.9 && lon >= 124.0 && lon <= 132.5;
    }

    function isLikelyProjected5186(rawLon, rawLat) {
        return isFinite(rawLon) && isFinite(rawLat) &&
            rawLon >= 100000 && rawLon <= 400000 &&
            rawLat >= 100000 && rawLat <= 700000;
    }

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function setMapState(container) {
        if (container.className.indexOf('map-ready') === -1) {
            container.className += ' map-ready';
        }
    }

    function renderMessage(container, message) {
        container.innerHTML = '';
        container.textContent = message;
    }

    function emitResolvedLatLon(options, lat, lon, source, rawLat, rawLon) {
        if (!options || typeof options.onResolvedLatLon !== 'function') return;
        try {
            options.onResolvedLatLon({
                lat: lat,
                lon: lon,
                source: source || '',
                rawLat: rawLat,
                rawLon: rawLon
            });
        } catch (error) {
            console.error('onResolvedLatLon callback failed', error);
        }
    }

    function uniqueMapId() {
        return 'riskBuildingVworld3d_' + Date.now() + '_' + Math.floor(Math.random() * 100000);
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
        if (!isValidLatLon(latDeg, lonDeg) || !isLikelyKorea(latDeg, lonDeg)) {
            return null;
        }

        return { lat: latDeg, lon: lonDeg };
    }

    function geocodeByVworld(detail, fallbackLatLon, rawLat, rawLon) {
        var apiKey = String(global.RISK_VWORLD_API_KEY || '').trim();
        var address = detail && detail.addr ? String(detail.addr).trim() : '';
        if (!apiKey || !address || !global.fetch) {
            return Promise.resolve(fallbackLatLon);
        }

        var url = ADDRESS_API_URL
            + '?service=address'
            + '&request=getcoord'
            + '&crs=epsg:4326'
            + '&format=json'
            + '&type=PARCEL'
            + '&address=' + encodeURIComponent(address)
            + '&key=' + encodeURIComponent(apiKey);

        return global.fetch(url).then(function(response) {
            if (!response.ok) {
                throw new Error('VWorld geocode HTTP ' + response.status);
            }
            return response.json();
        }).then(function(json) {
            var response = json && json.response ? json.response : null;
            var point = response && response.result ? response.result.point : null;
            var lon = point ? toNumber(point.x) : NaN;
            var lat = point ? toNumber(point.y) : NaN;
            if (!isValidLatLon(lat, lon) || !isLikelyKorea(lat, lon)) {
                return fallbackLatLon;
            }

            return {
                lat: lat,
                lon: lon,
                source: 'geocoder',
                rawLat: rawLat,
                rawLon: rawLon
            };
        }).catch(function() {
            return fallbackLatLon;
        });
    }

    function createOverlayHtml(detail) {
        return ''
            + '<div style="font-weight:700;margin-bottom:4px;">' + escapeHtml(detail.a13 || 'Building') + '</div>'
            + '<div>' + escapeHtml(detail.addr || '-') + '</div>';
    }

    function createVworldCameraPosition(lon, lat, altitude) {
        if (!global.vw || typeof global.vw.CameraPosition !== 'function' ||
                typeof global.vw.CoordZ !== 'function' ||
                typeof global.vw.Direction !== 'function') {
            return null;
        }

        return new global.vw.CameraPosition(
            new global.vw.CoordZ(lon, lat, altitude),
            new global.vw.Direction(0, -90, 0)
        );
    }

    function createMarkerIconDataUri() {
        var svg = ''
            + '<svg xmlns="http://www.w3.org/2000/svg" width="54" height="72" viewBox="0 0 54 72">'
            + '<path d="M27 2C14.3 2 4 12.3 4 25c0 16.9 19.2 36.6 22.1 39.4a1.3 1.3 0 0 0 1.8 0C30.8 61.6 50 41.9 50 25 50 12.3 39.7 2 27 2z" fill="#df2f2f" stroke="#ffffff" stroke-width="3"/>'
            + '<circle cx="27" cy="25" r="9" fill="#ffffff"/>'
            + '<circle cx="27" cy="25" r="4.5" fill="#df2f2f"/>'
            + '</svg>';
        return 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg);
    }

    function decorateViewer(detail, lon, lat) {
        if (!global.ws3d || !global.ws3d.viewer || typeof global.Cesium === 'undefined') {
            return;
        }

        var viewer = global.ws3d.viewer;
        var Cesium = global.Cesium;
        var markerIcon = createMarkerIconDataUri();

        global.setTimeout(function() {
            try {
                var groundPosition = Cesium.Cartesian3.fromDegrees(lon, lat, MARKER_ALTITUDE);
                var labelPosition = Cesium.Cartesian3.fromDegrees(lon, lat, MARKER_ALTITUDE + 120);
                if (viewer.entities && typeof viewer.entities.removeAll === 'function') {
                    viewer.entities.removeAll();
                }
                if (viewer.entities && typeof viewer.entities.add === 'function') {
                    viewer.entities.add({
                        id: 'risk-building-marker',
                        position: groundPosition,
                        billboard: {
                            image: markerIcon,
                            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                            heightReference: Cesium.HeightReference.NONE,
                            disableDepthTestDistance: Number.POSITIVE_INFINITY,
                            scale: 0.9
                        },
                        point: {
                            pixelSize: 12,
                            color: Cesium.Color.RED,
                            outlineColor: Cesium.Color.WHITE,
                            outlineWidth: 3,
                            disableDepthTestDistance: Number.POSITIVE_INFINITY
                        },
                        label: {
                            text: String(detail.a13 || 'Building'),
                            font: '14px sans-serif',
                            fillColor: Cesium.Color.WHITE,
                            showBackground: true,
                            backgroundColor: Cesium.Color.fromCssColorString('#1f2d3dcc'),
                            pixelOffset: new Cesium.Cartesian2(0, -88),
                            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                            disableDepthTestDistance: Number.POSITIVE_INFINITY
                        }
                    });
                    viewer.entities.add({
                        id: 'risk-building-marker-anchor',
                        position: labelPosition,
                        polyline: {
                            positions: [groundPosition, labelPosition],
                            width: 2,
                            material: Cesium.Color.fromCssColorString('#df2f2f'),
                            clampToGround: false
                        }
                    });
                }

                if (viewer.camera && typeof viewer.camera.flyTo === 'function') {
                    viewer.camera.flyTo({
                        destination: Cesium.Cartesian3.fromDegrees(lon, lat, DEFAULT_ALTITUDE),
                        orientation: {
                            heading: 0,
                            pitch: Cesium.Math.toRadians(-50),
                            roll: 0
                        },
                        duration: 0
                    });
                }
            } catch (error) {
                console.error('VWorld 3D viewer decoration failed', error);
            }
        }, 400);
    }

    function renderMap(container, detail, lat, lon, options, source, rawLat, rawLon) {
        setMapState(container);
        container.innerHTML = '';
        container.style.position = 'relative';
        container.style.overflow = 'hidden';

        var mapId = uniqueMapId();
        var mapEl = document.createElement('div');
        mapEl.id = mapId;
        mapEl.style.width = '100%';
        mapEl.style.height = '100%';
        mapEl.style.minHeight = MAP_HEIGHT + 'px';
        container.appendChild(mapEl);

        var overlay = document.createElement('div');
        overlay.style.position = 'absolute';
        overlay.style.left = '12px';
        overlay.style.top = '12px';
        overlay.style.zIndex = '20';
        overlay.style.background = 'rgba(255,255,255,0.96)';
        overlay.style.border = '1px solid #d8e1ea';
        overlay.style.borderRadius = '8px';
        overlay.style.padding = '8px 10px';
        overlay.style.boxShadow = '0 4px 12px rgba(0,0,0,0.12)';
        overlay.style.fontSize = '12px';
        overlay.style.lineHeight = '1.45';
        overlay.style.color = '#223';
        overlay.style.maxWidth = '240px';
        overlay.innerHTML = createOverlayHtml(detail);
        container.appendChild(overlay);

        var map = new global.vw.Map();
        var cameraPosition = createVworldCameraPosition(lon, lat, DEFAULT_ALTITUDE);
        var options3d = {
            mapId: mapId,
            navigation: true,
            logo: true
        };

        map.setOption(options3d);
        if (typeof map.setMapId === 'function') {
            map.setMapId(mapId);
        }
        if (cameraPosition && typeof map.setInitPosition === 'function') {
            map.setInitPosition(cameraPosition);
        }
        if (typeof map.setLogoVisible === 'function') {
            map.setLogoVisible(true);
        }
        if (typeof map.setNavigationZoomVisible === 'function') {
            map.setNavigationZoomVisible(true);
        }
        map.start();

        decorateViewer(detail, lon, lat);
        emitResolvedLatLon(options, lat, lon, source, rawLat, rawLon);
    }

    global.RiskBuildingDetailMapAdapter = {
        render: function(container, detail, options) {
            if (!container) return;
            options = options || {};

            if (!global.vw || typeof global.vw.Map !== 'function') {
                renderMessage(container, 'VWorld 3D SDK load failed.');
                return;
            }

            var rawLat = toNumber(detail && detail.lat);
            var rawLon = toNumber(detail && detail.lon);

            if (isValidLatLon(rawLat, rawLon) && isLikelyKorea(rawLat, rawLon)) {
                renderMap(container, detail || {}, rawLat, rawLon, options, 'wgs84', rawLat, rawLon);
                return;
            }

            var fallbackLatLon = null;
            if (isFinite(rawLat) && isFinite(rawLon)) {
                var converted = epsg5186ToWgs84(rawLon, rawLat);
                if (converted) {
                    fallbackLatLon = {
                        lat: converted.lat,
                        lon: converted.lon,
                        source: 'converted',
                        rawLat: rawLat,
                        rawLon: rawLon
                    };
                }
            }

            geocodeByVworld(detail || {}, fallbackLatLon, rawLat, rawLon).then(function(resolved) {
                if (!resolved || !isValidLatLon(resolved.lat, resolved.lon) || !isLikelyKorea(resolved.lat, resolved.lon)) {
                    renderMessage(container, 'Map could not be rendered because location data is unavailable.');
                    return;
                }

                renderMap(
                    container,
                    detail || {},
                    resolved.lat,
                    resolved.lon,
                    options,
                    resolved.source || 'geocoder',
                    rawLat,
                    rawLon
                );
            });
        }
    };
}(window));
