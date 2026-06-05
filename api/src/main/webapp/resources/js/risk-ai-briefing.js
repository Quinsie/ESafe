/*
 * risk-ai-briefing.js - 전국 위험지도의 'AI 브리핑 및 상황요약 보고서' 칸 연동.
 * ESafe LLM 사이드카(FastAPI, 기본 :8800)를 호출해 브리핑 텍스트를 표출하고,
 * 같은 내용을 한글(HWP) 보고서로 내려받는다.
 *
 * [데모 모드] 시연 환경에서 LLM/Ollama/한글을 구동할 수 없을 때를 위해
 * DEMO_MODE 가 true 면 사이드카 호출 없이 미리 작성한 더미 결과를 보여준다.
 *   - 실제 LLM을 쓰려면: JSP에서 `window.ESAFE_DEMO_MODE = false;` 설정(또는 아래 기본값 변경).
 */
(function () {
    'use strict';

    var LLM_BASE = window.ESAFE_LLM_BASE || 'http://localhost:8800';
    var REGION_NAME = window.ESAFE_BRIEF_REGION || '광주전남본부직할 관할 지역';
    // 기본 true = 시연용 더미. 실제 LLM 연동 시 false.
    var DEMO_MODE = (typeof window.ESAFE_DEMO_MODE === 'boolean') ? window.ESAFE_DEMO_MODE : true;
    var SAMPLE_HWP = window.ESAFE_SAMPLE_HWP || '/resources/sample/esafe_situation_report.hwp';

    var contentEl = document.getElementById('nationwideBriefingContent');
    var btnEl = document.getElementById('nationwideBriefingBtn');
    var reportBtn = document.getElementById('nationwideReportBtn');
    if (!contentEl || !btnEl) {
        return;
    }

    var lastBriefingText = '';
    var GRADE_LABEL = { E: '위험(E)', D: '경고(D)', C: '주의(C)', B: '관심(B)', A: '안전(A)' };

    // ---------------------------------------------------------------
    // 데모용 더미 브리핑 (광주전남본부직할 기준, 실제 수치 반영)
    // ---------------------------------------------------------------
    var DEMO_BRIEFING_TEXT =
        "광주전남본부직할 관할 지역의 전기재해 종합 위험도는 평균 17.2점(100점 환산)으로 '주의' 수준입니다. "
        + "전체 217,241개 건물 중 위험(E) 165개소, 경고(D) 9,962개소가 우선 관리 대상으로 분류됩니다.\n"
        + "위험도를 끌어올린 주요 요인은 (1) 건물 노후도, (2) 설비 점검 부적합 이력, (3) 최근 2주간 과부하 패턴 반복입니다. "
        + "특히 곡성군·함평군 등 노후 주거밀집 구역과 산지·저지대 인접 구역에서 위험 등급 상향이 두드러집니다.\n"
        + "권고: 위험·경고 등급 건물 우선 현장점검, 노후 배전반·옥내배선 교체, 여름철 냉방 과부하 대비 회로 분산을 단계적으로 추진할 것을 제안합니다.";

    function demoBriefingHtml() {
        return ''
            + '<div style="line-height:1.75;">'
            + '<div style="margin-bottom:10px;">'
            + '<b>광주전남본부직할 관할 지역</b>의 전기재해 종합 위험도는 평균 <b>17.2점</b>(100점 환산)으로 '
            + '<span style="color:#e67e22;font-weight:600;">\'주의\'</span> 수준입니다. '
            + '전체 <b>217,241</b>개 건물 중 <span style="color:#c0392b;font-weight:600;">위험(E) 165개소</span>, '
            + '<span style="color:#e67e22;font-weight:600;">경고(D) 9,962개소</span>가 우선 관리 대상입니다.'
            + '</div>'
            + '<div style="margin:10px 0 6px;font-weight:600;color:#2c3e50;">주요 위험 요인 (기여도)</div>'
            + '<ul style="margin:0 0 10px 18px;padding:0;">'
            + '<li>건물 노후도 <b>+9.7</b> — 30년 이상 노후 건물의 옥내배선·배전반 절연 저하</li>'
            + '<li>설비 점검 부적합 <b>+7.3</b> — 점검 지적사항 미조치 및 장기 미점검 설비</li>'
            + '<li>과부하 패턴 반복 <b>+5.5</b> — 최근 2주간 분전반 과부하·발열 신호</li>'
            + '</ul>'
            + '<div style="margin:10px 0 6px;font-weight:600;color:#2c3e50;">주목 구역</div>'
            + '<div style="margin-bottom:10px;">곡성군·함평군 등 <b>노후 주거밀집 구역</b>과 산지·저지대 인접 구역에서 위험 등급 상향이 두드러집니다.</div>'
            + '<div style="margin:10px 0 6px;font-weight:600;color:#2c3e50;">권고 사항</div>'
            + '<ol style="margin:0 0 4px 18px;padding:0;">'
            + '<li>위험·경고 등급 건물 <b>우선 현장점검</b></li>'
            + '<li>노후 <b>배전반·옥내배선 교체</b></li>'
            + '<li>여름철 냉방 과부하 대비 <b>회로 분산</b></li>'
            + '</ol>'
            + '</div>';
    }

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
        contentEl.innerHTML = note + lastBriefingText.replace(/\n/g, '<br>');
    }

    function generate() {
        if (DEMO_MODE) {
            setBusy(true);
            contentEl.textContent = 'LLM이 상황을 요약하는 중입니다…';
            setTimeout(function () {
                lastBriefingText = DEMO_BRIEFING_TEXT;
                contentEl.innerHTML = demoBriefingHtml();
                setBusy(false);
            }, 1200);
            return;
        }
        realGenerate();
    }

    function realGenerate() {
        setBusy(true);
        contentEl.textContent = 'LLM이 상황을 요약하는 중입니다… (로컬 모델은 수십 초 걸릴 수 있어요)';
        fetch(LLM_BASE + '/briefing/region', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ region_name: REGION_NAME })
        })
            .then(function (r) { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); })
            .then(function (res) { render(res.text, res.used_mock); })
            .catch(function (err) {
                contentEl.innerHTML =
                    '<span style="color:#c0392b;">브리핑 생성 실패: ' + err.message + '</span><br>'
                    + '<span style="font-size:12px;color:#7f8c8d;">LLM 사이드카(' + LLM_BASE
                    + ')와 Ollama가 실행 중인지 확인하세요.</span>';
            })
            .finally(function () { setBusy(false); });
    }

    // ---------------------------------------------------------------
    // 한글(HWP) 보고서
    // ---------------------------------------------------------------
    function triggerDownload(href, filename) {
        var a = document.createElement('a');
        a.href = href;
        a.download = filename || 'esafe_risk_report.hwp';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    function generateReport() {
        if (DEMO_MODE) {
            setReportBusy(true);
            setTimeout(function () {
                // 미리 생성해 둔 샘플 .hwp 다운로드
                triggerDownload(SAMPLE_HWP, '전기재해위험_상황요약보고서.hwp');
                setReportBusy(false);
            }, 900);
            return;
        }
        realGenerateReport();
    }

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
        if (m && m[1]) { try { return decodeURIComponent(m[1]); } catch (e) { /* noop */ } }
        var m2 = /filename="?([^"]+)"?/i.exec(disposition);
        return (m2 && m2[1]) ? m2[1] : null;
    }

    function realGenerateReport() {
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
                if (!r.ok) { return r.text().then(function (t) { throw new Error('HTTP ' + r.status + ' ' + t); }); }
                var name = parseFilename(r.headers.get('Content-Disposition'));
                return r.blob().then(function (blob) {
                    var url = URL.createObjectURL(blob);
                    triggerDownload(url, name);
                    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
                });
            });
        }).catch(function (err) {
            contentEl.innerHTML =
                '<span style="color:#c0392b;">한글 보고서 생성 실패: ' + err.message + '</span><br>'
                + '<span style="font-size:12px;color:#7f8c8d;">사이드카(' + LLM_BASE
                + ')·Ollama·한글(HWP) 실행 여부를 확인하세요.</span>';
        }).finally(function () { setReportBusy(false); });
    }

    btnEl.addEventListener('click', generate);
    if (reportBtn) { reportBtn.addEventListener('click', generateReport); }
}());
