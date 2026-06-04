/*
 * risk-ai-briefing.js - 전국 위험지도의 'AI 브리핑 및 상황요약 보고서' 칸 연동.
 * ESafe LLM 사이드카(FastAPI, 기본 :8800)를 호출해 브리핑 텍스트를 표출하고,
 * 같은 내용을 한글(HWP) 보고서로 내려받는다.
 * 모델 미연결 상태에서는 사이드카가 mock SHAP으로 채워 동작을 보여준다.
 */
(function () {
    'use strict';

    var LLM_BASE = window.ESAFE_LLM_BASE || 'http://localhost:8800';
    var REGION_NAME = window.ESAFE_BRIEF_REGION || '광주전남본부직할 관할 지역';

    var contentEl = document.getElementById('nationwideBriefingContent');
    var btnEl = document.getElementById('nationwideBriefingBtn');
    var reportBtn = document.getElementById('nationwideReportBtn');
    if (!contentEl || !btnEl) {
        return;
    }

    // 마지막으로 생성된 브리핑 본문(보고서 생성 시 재사용). 없으면 서버가 새로 생성한다.
    var lastBriefingText = '';

    var GRADE_LABEL = { E: '위험(E)', D: '경고(D)', C: '주의(C)', B: '관심(B)', A: '안전(A)' };

    function setBusy(busy) {
        btnEl.disabled = busy;
        btnEl.textContent = busy ? '브리핑 생성 중…' : 'AI 브리핑 생성';
    }

    function setReportBusy(busy) {
        if (!reportBtn) { return; }
        reportBtn.disabled = busy;
        reportBtn.textContent = busy ? '보고서 생성 중…' : '한글 보고서(HWP)';
    }

    function render(text, usedMock) {
        lastBriefingText = String(text || '');
        var note = usedMock
            ? '<div style="font-size:11px;color:#e67e22;margin-bottom:6px;">※ 모델 미연결 — 예시(mock) 데이터 기반 브리핑입니다.</div>'
            : '';
        var html = lastBriefingText.replace(/\n/g, '<br>');
        contentEl.innerHTML = note + html;
    }

    function generate() {
        setBusy(true);
        contentEl.textContent = 'LLM이 상황을 요약하는 중입니다… (로컬 모델은 수십 초 걸릴 수 있어요)';
        fetch(LLM_BASE + '/briefing/region', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ region_name: REGION_NAME })
        })
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.json();
            })
            .then(function (res) {
                render(res.text, res.used_mock);
            })
            .catch(function (err) {
                contentEl.innerHTML =
                    '<span style="color:#c0392b;">브리핑 생성 실패: ' + err.message + '</span><br>'
                    + '<span style="font-size:12px;color:#7f8c8d;">LLM 사이드카(' + LLM_BASE
                    + ')와 Ollama가 실행 중인지 확인하세요.</span>';
            })
            .finally(function () {
                setBusy(false);
            });
    }

    // 등급별 건물 통계(AFTER 기준)를 Tomcat에서 가져와 {라벨: 건수}로 변환. 실패하면 null.
    function fetchGradeStats() {
        return fetch('selectGradeStats.do', { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (res) {
                if (!res || !res.data) { return null; }
                var dist = {};
                ['E', 'D', 'C', 'B', 'A'].forEach(function (cd) {
                    for (var i = 0; i < res.data.length; i++) {
                        var row = res.data[i];
                        if (row && row.totalGrade === 'AFTER' && String(row.riskCd) === cd) {
                            dist[GRADE_LABEL[cd]] = row.bldgCnt;
                            break;
                        }
                    }
                });
                return Object.keys(dist).length ? dist : null;
            })
            .catch(function () { return null; });
    }

    function parseFilename(disposition) {
        if (!disposition) { return null; }
        var m = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
        if (m && m[1]) {
            try { return decodeURIComponent(m[1]); } catch (e) { /* noop */ }
        }
        var m2 = /filename="?([^"]+)"?/i.exec(disposition);
        return (m2 && m2[1]) ? m2[1] : null;
    }

    function triggerDownload(blob, filename) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename || 'esafe_risk_report.hwp';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }

    function generateReport() {
        setReportBusy(true);
        fetchGradeStats().then(function (gradeDist) {
            var payload = {
                region_name: REGION_NAME,
                briefing_text: lastBriefingText || null,
                grade_distribution: gradeDist || null
            };
            return fetch(LLM_BASE + '/briefing/report', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function (r) {
                if (!r.ok) {
                    return r.text().then(function (t) { throw new Error('HTTP ' + r.status + ' ' + t); });
                }
                var name = parseFilename(r.headers.get('Content-Disposition'));
                return r.blob().then(function (blob) { triggerDownload(blob, name); });
            });
        }).catch(function (err) {
            contentEl.innerHTML =
                '<span style="color:#c0392b;">한글 보고서 생성 실패: ' + err.message + '</span><br>'
                + '<span style="font-size:12px;color:#7f8c8d;">사이드카(' + LLM_BASE
                + ')·Ollama·한글(HWP) 실행 여부를 확인하세요.</span>';
        }).finally(function () {
            setReportBusy(false);
        });
    }

    btnEl.addEventListener('click', generate);
    if (reportBtn) {
        reportBtn.addEventListener('click', generateReport);
    }
}());
