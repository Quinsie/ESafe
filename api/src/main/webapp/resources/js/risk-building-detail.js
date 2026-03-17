/**
 * risk-building-detail.js - building detail + radar + facility history
 */
$(function() {
    if (typeof bldgSeq === 'undefined') return;

    RiskApp.callApi('selectCombinedDetail.do', { bldgSeq: bldgSeq }, function(res) {
        var d = res.data;
        if (!d) {
            alert('건물 정보를 찾을 수 없습니다.');
            return;
        }

        $('#buildingName').text(d.a13 || '(건물명 없음)');
        $('#branchNm').text(d.branchNm || '-');
        $('#addr').text(d.addr || '-');
        $('#regionNm').text(d.regionNm || '-');
        $('#districtNm').text(d.districtNm || '-');

        $('#ageScore').text(d.ageScore != null ? d.ageScore : '-');
        $('#floodScore').text(d.floodScore != null ? d.floodScore : '-');
        $('#landslideScore').text(d.landslideScore != null ? d.landslideScore : '-');
        $('#fireScore').text(d.fireScore != null ? d.fireScore : '-');
        $('#landUseScore').text(d.landUseScore != null ? d.landUseScore : '-');
        $('#facilityRiskScore').text(d.facilityRiskScore != null ? d.facilityRiskScore : '0');
        $('#weatherScore').text(d.weatherScore != null ? d.weatherScore : '-');
        $('#wildfireScore').text(d.wildfireScore != null ? d.wildfireScore : '-');
        $('#combinedScore').text(d.combinedScore != null ? d.combinedScore : '-');
        $('#combinedGrade').html(RiskApp.gradeBadge(d.combinedRiskCd || d.riskCd || 'A'));

        var facilityHistory = normalizeFacilityHistory(res.facilityHistory || []);
        setupFacilityTypeFilter(facilityHistory);
        renderFacilityHistory(facilityHistory, getSelectedFacilityType());
        renderRadarChart(d);
        renderBuildingInsightArea(d, facilityHistory);
    });

    $(document).on('click', '#facilityHistoryBody tr.facility-row', function() {
        var histSeq = $(this).data('histSeq');
        var facilityType = normalizeFacilityType($(this).data('facilityType'));
        if (!histSeq) return;

        var target = isGeneralType(facilityType) ? 'riskFacilityGeneralDetail.do' : 'riskFacilitySelfDetail.do';
        var nextUrl = target + '?histSeq=' + encodeURIComponent(histSeq) + '&bldgSeq=' + encodeURIComponent(bldgSeq);
        location.href = nextUrl;
    });

    function setupFacilityTypeFilter(list) {
        var $filter = $('#facilityTypeFilter');
        if (!$filter.length) return;
        $filter.off('change').on('change', function() {
            renderFacilityHistory(list, getSelectedFacilityType());
        });
    }

    function getSelectedFacilityType() {
        var $filter = $('#facilityTypeFilter');
        var selected = $filter.length ? ($filter.val() || 'GENERAL') : 'GENERAL';
        return normalizeFacilityType(selected);
    }

    function renderFacilityHistory(list, selectedType) {
        var type = normalizeFacilityType(selectedType);
        renderFacilityHistoryHead(type);

        var $body = $('#facilityHistoryBody');
        if (!$body.length) return;

        var filtered = [];
        for (var j = 0; j < (list || []).length; j++) {
            var candidate = list[j] || {};
            if (normalizeFacilityType(candidate.facilityType) === type) {
                filtered.push(candidate);
            }
        }

        var emptyColspan = isGeneralType(type) ? 11 : 7;
        if (filtered.length === 0) {
            $body.html('<tr><td colspan="' + emptyColspan + '">데이터가 없습니다.</td></tr>');
            return;
        }

        var rows = [];
        for (var i = 0; i < filtered.length; i++) {
            var item = filtered[i] || {};
            var histSeqAttr = item.histSeq != null ? ' data-hist-seq="' + safeAttr(item.histSeq) + '"' : '';
            var typeAttr = ' data-facility-type="' + safeAttr(item.facilityType || type) + '"';

            if (isGeneralType(type)) {
                rows.push(
                    '<tr class="facility-row"' + histSeqAttr + typeAttr + '>' +
                        '<td>' + safe(item.branchNm) + '</td>' +
                        '<td class="facility-col-address">' + safe(item.addr) + '</td>' +
                        '<td>' + safe(item.kepcoCustNo) + '</td>' +
                        '<td>' + safe(item.resultText) + '</td>' +
                        '<td>' + safe(formatOralNotice(item.oralNoticeYn)) + '</td>' +
                        '<td>' + safe(item.failDetail) + '</td>' +
                        '<td>' + safe(item.lineNo) + '</td>' +
                        '<td>' + safe(item.capacity) + '</td>' +
                        '<td>' + safe(item.checkCycle) + '</td>' +
                        '<td>' + safe(item.contractType) + '</td>' +
                        '<td>' + safe(item.checkDt) + '</td>' +
                    '</tr>'
                );
                continue;
            }

            rows.push(
                '<tr class="facility-row"' + histSeqAttr + typeAttr + '>' +
                    '<td>' + safe(item.branchNm) + '</td>' +
                    '<td class="facility-col-address">' + safe(item.addr) + '</td>' +
                    '<td>' + safe(item.kepcoCustNo) + '</td>' +
                    '<td>' + safe(item.resultText) + '</td>' +
                    '<td>' + safe(item.defectCnt) + '</td>' +
                    '<td>' + safe(item.motorType) + '</td>' +
                    '<td>' + safe(item.checkDt) + '</td>' +
                '</tr>'
            );
        }

        $body.html(rows.join(''));
    }

    function renderFacilityHistoryHead(type) {
        var $head = $('#facilityHistoryHead');
        if (!$head.length) return;

        if (isGeneralType(type)) {
            $head.html(
                '<tr>' +
                    '<th>사업소(지사)</th>' +
                    '<th class="facility-col-address">주소(지번주소)</th>' +
                    '<th>한전고객번호</th>' +
                    '<th>결과</th>' +
                    '<th>구두통보</th>' +
                    '<th>부적합 내역</th>' +
                    '<th>선식번호</th>' +
                    '<th>용량</th>' +
                    '<th>주기</th>' +
                    '<th>계약종별</th>' +
                    '<th>점검일</th>' +
                '</tr>'
            );
            return;
        }

        $head.html(
            '<tr>' +
                '<th>사업소(지사)</th>' +
                '<th class="facility-col-address">주소(지번주소)</th>' +
                '<th>고객번호</th>' +
                '<th>결과</th>' +
                '<th>지적건수</th>' +
                '<th>원동기종류</th>' +
                '<th>검사일</th>' +
            '</tr>'
        );
    }

    function renderRadarChart(d) {
        if (typeof Chart === 'undefined') return;

        var labels = ['건물연령', '침수', '산사태', '화재', '용도지구', '설비점검', '기상', '산불'];
        var values = [
            Number(d.ageScore) || 0,
            Number(d.floodScore) || 0,
            Number(d.landslideScore) || 0,
            Number(d.fireScore) || 0,
            Number(d.landUseScore) || 0,
            Number(d.facilityRiskScore) || 0,
            Number(d.weatherScore) || 0,
            Number(d.wildfireScore) || 0
        ];
        var plotted = [];
        for (var i = 0; i < values.length; i++) {
            plotted.push(Math.min(Math.max(values[i], 0), 10));
        }

        new Chart(document.getElementById('radarChart'), {
            type: 'radar',
            data: {
                labels: labels,
                datasets: [{
                    label: '위험점수',
                    data: plotted,
                    backgroundColor: 'rgba(231, 76, 60, 0.2)',
                    borderColor: '#e74c3c',
                    borderWidth: 2,
                    pointBackgroundColor: '#e74c3c',
                    pointRadius: 4
                }]
            },
            options: {
                responsive: true,
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 10,
                        ticks: { stepSize: 2, display: false },
                        pointLabels: { font: { size: 13, weight: 'bold' } },
                        grid: { color: 'rgba(0,0,0,0.08)' },
                        angleLines: { color: 'rgba(0,0,0,0.08)' }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                var idx = ctx.dataIndex;
                                return labels[idx] + ': ' + plotted[idx] + '점 (최대 10)';
                            }
                        }
                    }
                }
            }
        });
    }

    function renderBuildingInsightArea(d, facilityHistory) {
        var $map = $('#buildingMapPlaceholder');
        var $age = $('#insightBuildingAge');
        var $structure = $('#insightStructureName');
        var $mainUse = $('#insightMainUseName');
        var $count = $('#insightFacilityCount');
        var $landUse = $('#insightLandUseZone');
        var $latLon = $('#insightLatLon');
        var $recentFireDate = $('#insightRecentFireDate');
        var $landslideDistance = $('#insightLandslideDistance');

        if ($age.length) {
            if (d.buildAge != null && d.buildAge !== '') {
                var ageText = String(d.buildAge) + '년';
                if (d.buildYear != null && d.buildYear !== '') {
                    ageText += ' (건축년도 ' + d.buildYear + ')';
                }
                $age.text(ageText);
            } else if (d.ageGrade || d.ageScore != null) {
                $age.text((d.ageGrade || '-') + (d.ageScore != null ? ' (' + d.ageScore + '점)' : ''));
            } else {
                $age.text('-');
            }
        }

        if ($structure.length) $structure.text(d.structureName || d.a17 || '-');
        if ($mainUse.length) $mainUse.text(d.mainUseName || d.a19 || '-');

        var uniqueCust = {};
        for (var i = 0; i < facilityHistory.length; i++) {
            var item = facilityHistory[i] || {};
            var custNo = normalizeCustomerNo(item.kepcoCustNo);
            if (custNo) {
                uniqueCust[custNo] = true;
            }
        }
        var facilityCount = Object.keys(uniqueCust).length;

        if ($count.length) $count.text(String(facilityCount));
        if ($landUse.length) $landUse.text(d.a13 || '-');
        if ($latLon.length) $latLon.text(formatLatLonInitial(d.lat, d.lon));
        if ($recentFireDate.length) $recentFireDate.text(formatRecentFireDate(d.prevFireOccurDate));
        if ($landslideDistance.length) $landslideDistance.text(formatLandslideDistance(d.landslideDistance));

        if (!$map.length) return;

        $map.attr('data-lat', d.lat != null ? d.lat : '');
        $map.attr('data-lon', d.lon != null ? d.lon : '');
        $map.text('지도 컴포넌트 연결 전 Placeholder');

        // Future extension hook: external map adapter can render without touching this file.
        if (window.RiskBuildingDetailMapAdapter &&
            typeof window.RiskBuildingDetailMapAdapter.render === 'function') {
            try {
                window.RiskBuildingDetailMapAdapter.render($map.get(0), d, {
                    onResolvedLatLon: function(info) {
                        if (!$latLon.length) return;
                        $latLon.text(formatResolvedLatLon(info));
                    }
                });
            } catch (e) {
                console.error('RiskBuildingDetailMapAdapter.render failed', e);
            }
        }
    }

    function safe(v) {
        if (v === null || v === undefined || v === '') return '-';
        return String(v)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function safeAttr(v) {
        if (v === null || v === undefined) return '';
        return String(v)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function normalizeFacilityHistory(list) {
        var normalized = [];
        for (var i = 0; i < list.length; i++) {
            var item = list[i] || {};
            item.facilityType = normalizeFacilityType(item.facilityType);
            normalized.push(item);
        }
        return normalized;
    }

    function normalizeFacilityType(type) {
        var v = String(type || '').trim();
        var u = v.toUpperCase();
        if (v.indexOf('일반') > -1 || u === 'GENERAL') return 'GENERAL';
        if (v.indexOf('자가') > -1 || u === 'SELF') return 'SELF';
        return 'GENERAL';
    }

    function isGeneralType(type) {
        return normalizeFacilityType(type) === 'GENERAL';
    }

    function formatOralNotice(yn) {
        if (yn === 'Y') return '예';
        if (yn === 'N') return '아니오';
        return '-';
    }

    function normalizeCustomerNo(v) {
        if (v === null || v === undefined) return '';
        var s = String(v).trim();
        if (!s) return '';
        return s.replace(/\.0$/, '');
    }

    function formatLatLonInitial(lat, lon) {
        var latNum = Number(lat);
        var lonNum = Number(lon);
        if (!isFinite(latNum) || !isFinite(lonNum)) return '-';

        if (isValidLatLon(latNum, lonNum) && isLikelyKorea(latNum, lonNum)) {
            return '위도 ' + latNum.toFixed(6) + ', 경도 ' + lonNum.toFixed(6) + ' (원본)';
        }

        return '원본좌표 X ' + lonNum.toFixed(3) + ', Y ' + latNum.toFixed(3);
    }

    function formatResolvedLatLon(info) {
        if (!info) return '-';
        var lat = Number(info.lat);
        var lon = Number(info.lon);
        if (!isFinite(lat) || !isFinite(lon)) return '-';

        var source = String(info.source || '').toLowerCase();
        var label = '';
        if (source === 'geocoder') label = ' (주소기준)';
        else if (source === 'wgs84') label = ' (좌표직접)';
        else if (source === 'converted') label = ' (좌표변환)';

        return '위도 ' + lat.toFixed(6) + ', 경도 ' + lon.toFixed(6) + label;
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

    function formatRecentFireDate(v) {
        if (v === null || v === undefined || v === '') return '-';
        var tokens = String(v).split('|');
        var latestToken = '';
        var latestSortable = '';

        for (var i = 0; i < tokens.length; i++) {
            var raw = String(tokens[i] || '').trim();
            if (!raw) continue;

            var normalized = raw.replace(/\./g, '-').replace(/\//g, '-');
            var sortable = '';
            if (/^\d{8}$/.test(normalized)) {
                sortable = normalized;
                normalized = normalized.slice(0, 4) + '-' + normalized.slice(4, 6) + '-' + normalized.slice(6, 8);
            } else {
                var m = normalized.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
                if (m) {
                    sortable = m[1] + ('0' + m[2]).slice(-2) + ('0' + m[3]).slice(-2);
                    normalized = m[1] + '-' + ('0' + m[2]).slice(-2) + '-' + ('0' + m[3]).slice(-2);
                }
            }

            if (sortable && (!latestSortable || sortable > latestSortable)) {
                latestSortable = sortable;
                latestToken = normalized;
            } else if (!latestToken) {
                latestToken = normalized;
            }
        }

        return latestToken || '-';
    }

    function formatLandslideDistance(v) {
        if (v === null || v === undefined || v === '') return '-';
        var n = Number(v);
        if (!isFinite(n)) return '-';
        if (n >= 99999) return '500m 이상';
        if (n < 0) return '-';
        if (n < 100) return n.toFixed(1) + 'm';
        return Math.round(n) + 'm';
    }
});
