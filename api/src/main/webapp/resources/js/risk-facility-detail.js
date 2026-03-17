/**
 * risk-facility-detail.js - facility history detail page (general/self)
 */
$(function() {
    var $root = $('#facilityDetailRoot');
    if (!$root.length) return;

    var histSeq = String($root.data('histSeq') || '').trim();
    var facilityType = normalizeFacilityType(String($root.data('facilityType') || '').trim() || 'GENERAL');
    var bldgSeq = String($root.data('bldgSeq') || '').trim();

    $('#btnBackToBuilding').on('click', function() {
        if (/^\d+$/.test(bldgSeq)) {
            location.href = 'riskBuildingDetail.do?bldgSeq=' + encodeURIComponent(bldgSeq);
            return;
        }
        history.back();
    });

    if (!/^\d+$/.test(histSeq)) {
        renderError('설비 이력 식별값(histSeq)이 올바르지 않습니다.');
        return;
    }

    RiskApp.callApi('selectFacilityHistoryDetail.do', {
        facilityType: facilityType,
        histSeq: histSeq
    }, function(res) {
        var d = res.data || {};
        renderSummary(d);
        renderRawTable(d.rawJson);
    });

    function renderSummary(d) {
        var customerNoLabel = isGeneralType(facilityType) ? '한전고객번호' : '고객번호';
        var labels = [
            ['facilityType', '설비 구분'],
            ['branchNm', '사업소(지사)'],
            ['addr', '주소(지번주소)'],
            ['kepcoCustNo', customerNoLabel],
            ['resultText', '결과'],
            ['oralNoticeYn', '구두통보'],
            ['failDetail', '부적합/불합격 내역'],
            ['lineNo', '선식번호'],
            ['capacity', '용량'],
            ['checkCycle', '주기'],
            ['contractType', '계약종별'],
            ['defectCnt', '지적건수'],
            ['motorType', '원동기종류'],
            ['checkDt', '점검/검사일']
        ];

        var html = [];
        for (var i = 0; i < labels.length; i++) {
            var key = labels[i][0];
            var name = labels[i][1];
            var value = d[key];
            if (value === null || value === undefined || String(value).trim() === '') {
                continue;
            }
            if (key === 'oralNoticeYn') {
                value = formatYn(value);
            }
            if (key === 'facilityType') {
                value = facilityTypeLabel(value);
            }
            html.push(
                '<div class="facility-detail-item">' +
                    '<span class="facility-detail-label">' + esc(name) + '</span>' +
                    '<span class="facility-detail-value">' + esc(value) + '</span>' +
                '</div>'
            );
        }

        if (html.length === 0) {
            html.push('<div class="facility-detail-item"><span class="facility-detail-value">표시할 데이터가 없습니다.</span></div>');
        }

        $('#facilityDetailSummary').html(html.join(''));
    }

    function renderRawTable(rawJsonText) {
        var $tbody = $('#facilityRawTable tbody');
        if (!$tbody.length) return;

        var parsed = {};
        if (rawJsonText !== null && rawJsonText !== undefined && String(rawJsonText).trim() !== '') {
            try {
                parsed = JSON.parse(String(rawJsonText));
            } catch (e) {
                $tbody.html('<tr><td colspan="2">원본 JSON 파싱 실패</td></tr>');
                return;
            }
        }

        var keys = Object.keys(parsed);
        if (keys.length === 0) {
            $tbody.html('<tr><td colspan="2">원본 샘플 컬럼 데이터가 없습니다.</td></tr>');
            return;
        }

        var rows = [];
        for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            var v = parsed[k];
            rows.push('<tr><td>' + esc(k) + '</td><td>' + esc(v) + '</td></tr>');
        }
        $tbody.html(rows.join(''));
    }

    function renderError(msg) {
        $('#facilityDetailSummary').html(
            '<div class="facility-detail-item"><span class="facility-detail-value">' + esc(msg) + '</span></div>'
        );
        $('#facilityRawTable tbody').html('<tr><td colspan="2">' + esc(msg) + '</td></tr>');
    }

    function formatYn(v) {
        if (String(v).toUpperCase() === 'Y') return '예';
        if (String(v).toUpperCase() === 'N') return '아니오';
        return v;
    }

    function normalizeFacilityType(v) {
        var s = String(v || '').trim();
        var u = s.toUpperCase();
        if (s.indexOf('일반') > -1 || u === 'GENERAL') return 'GENERAL';
        if (s.indexOf('자가') > -1 || u === 'SELF') return 'SELF';
        return 'GENERAL';
    }

    function facilityTypeLabel(v) {
        return normalizeFacilityType(v) === 'GENERAL' ? '일반용' : '자가용';
    }

    function isGeneralType(v) {
        return normalizeFacilityType(v) === 'GENERAL';
    }

    function esc(v) {
        if (v === null || v === undefined || v === '') return '-';
        return String(v)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
});
