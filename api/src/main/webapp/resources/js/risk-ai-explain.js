/*
 * risk-ai-explain.js - 건물 상세: AI 위험원인 설명(기능1) + 유사 사고 사례 추천(기능2, RAG).
 * 화면에 이미 로드된 항목별 위험 점수를 근거(factor)로 모아 LLM 사이드카에 보낸다.
 *
 * [데모 모드] 시연 환경에서 LLM/Ollama를 구동할 수 없을 때를 위해 DEMO_MODE 가 true 면
 * 사이드카 호출 없이 화면의 실제 점수 + 내장 사례 코퍼스로 그럴싸한 결과를 즉시 보여준다.
 *   - 실제 LLM을 쓰려면: JSP에서 `window.ESAFE_DEMO_MODE = false;` 설정(또는 아래 기본값 변경).
 */
(function () {
    'use strict';

    var LLM_BASE = window.ESAFE_LLM_BASE || 'http://localhost:8800';
    var DEMO_MODE = (typeof window.ESAFE_DEMO_MODE === 'boolean') ? window.ESAFE_DEMO_MODE : true;

    var btn = document.getElementById('aiExplainBtn');
    var out = document.getElementById('aiExplainContent');
    if (!btn || !out) {
        return;
    }

    var COMPONENTS = [
        { id: 'ageScore', label: '건물 연령' },
        { id: 'floodScore', label: '침수 위험' },
        { id: 'landslideScore', label: '산사태 근접' },
        { id: 'fireScore', label: '전기화재 이력' },
        { id: 'landUseScore', label: '용도지구' },
        { id: 'facilityRiskScore', label: '설비점검 현황' },
        { id: 'weatherScore', label: '기상특보' },
        { id: 'wildfireScore', label: '산불 위험' }
    ];

    // 위험요소별 설명 스니펫(데모 설명 생성용)
    var FACTOR_DESC = {
        ageScore: '건축 경과연수가 길어 옥내배선·배전반의 절연 성능이 저하되어 합선·누전 위험이 큽니다.',
        floodScore: '침수위험지역에 위치해 호우 시 분전반 침수·합선 위험이 있습니다.',
        landslideScore: '산사태위험지·급경사지에 근접해 지반 거동 시 전기 인입설비 손상이 우려됩니다.',
        fireScore: '인근 전기화재 이력이 있어 재발 위험을 가중합니다.',
        landUseScore: '용도지구 특성상 전기수요가 높아 용량 부족 시 과부하 위험이 있습니다.',
        facilityRiskScore: '설비 점검에서 부적합·지적사항이 확인되어 즉시 조치가 필요합니다.',
        weatherScore: '최근 기상특보 영향으로 단기 위험도가 상승했습니다.',
        wildfireScore: '산불위험이 높은 지역으로 외부 인입설비의 연소확대가 우려됩니다.'
    };

    // 위험요소 → 사례 태그 키워드(RAG 매칭용)
    var FACTOR_KEYWORDS = {
        ageScore: ['노후', '건물연령', '옥내배선', '노후건물', '노후설비', '배전반', '노후배전설비'],
        facilityRiskScore: ['미점검', '설비점검', '자가용설비', '절연열화', '수전설비'],
        floodScore: ['침수', '홍수', '집중호우', '합선'],
        landslideScore: ['산사태', '지반붕괴', '급경사지', '단선'],
        fireScore: ['합선', '누전', '전선노후', '피복손상', '절연파괴'],
        landUseScore: ['용도변경', '용도지구', '전기용량부족', '용도지역공업'],
        weatherScore: ['과부하', '여름철', '냉방부하', '발열', '분전반'],
        wildfireScore: ['산불', '연소확대', '산지인접', '인입설비']
    };

    // 내장 사례 코퍼스(cases_seed.json 발췌 — 데모 RAG용)
    var CASES = [
        { id: 'case-001', title: '노후 아파트 배전반 절연파괴 화재', cause: '노후 배전반 절연 파괴', response: '긴급 차단 후 배전반 설비 교체', damage: '부분 정전, 인명피해 없음', prevention: '정기 절연저항 측정 및 노후 배전반 교체', tags: ['노후설비', '배전반', '절연파괴', '아파트'] },
        { id: 'case-002', title: '여름철 냉방 과부하로 인한 분전반 발열 화재', cause: '여름철 냉방부하 급증에 따른 분전반 과부하 및 발열', response: '부하 분산 및 차단기 용량 재산정', damage: '점포 1개소 소실, 인명피해 없음', prevention: '여름철 부하 점검 및 차단기 용량 적정화', tags: ['과부하', '여름철', '냉방부하', '분전반', '발열'] },
        { id: 'case-003', title: '공장 노후 전선 피복 손상에 의한 누전 화재', cause: '노후 전선 피복 손상으로 인한 누전', response: '누전차단기 동작 후 전선 전면 교체', damage: '생산라인 일부 정지, 인명피해 없음', prevention: '정기 누전 점검 및 노후 배선 교체', tags: ['누전', '전선노후', '피복손상', '공장', '용도지역공업'] },
        { id: 'case-004', title: '침수 지역 분전반 침수 후 합선 화재', cause: '집중호우 침수로 분전반 침수 후 합선', response: '전원 차단 및 침수 설비 건조·교체', damage: '주택 1동 전기설비 손상', prevention: '침수위험지역 전기설비 상향 설치 및 방수', tags: ['침수', '홍수', '합선', '분전반', '집중호우'] },
        { id: 'case-005', title: '미점검 자가용 설비 절연열화 화재', cause: '장기 미점검에 따른 자가용 수전설비 절연 열화', response: '정전 점검 후 절연 보강 및 부품 교체', damage: '건물 정전, 인명피해 없음', prevention: '법정 점검주기 준수 및 지적사항 즉시 조치', tags: ['미점검', '자가용설비', '절연열화', '수전설비', '설비점검'] },
        { id: 'case-006', title: '전통시장 문어발 콘센트 과부하 화재', cause: '다수 콘센트 문어발 연결에 의한 과부하', response: '전용회로 분리 및 멀티탭 교체', damage: '점포 3개소 소실', prevention: '전용회로 증설 및 과부하 경보 설치', tags: ['과부하', '문어발', '콘센트', '전통시장', '상가'] },
        { id: 'case-007', title: '고령 건물 옥내배선 노후 합선 화재', cause: '30년 이상 노후 건물 옥내배선 절연 노후로 합선', response: '옥내배선 전면 교체', damage: '주택 일부 소실, 경상 1명', prevention: '노후 건물 옥내배선 정기 진단 및 교체', tags: ['노후건물', '옥내배선', '합선', '건물연령'] },
        { id: 'case-008', title: '산지 인접 건물 산불 연소확대 전기설비 손상', cause: '인근 산불 연소확대로 외부 전기인입설비 손상 후 발화', response: '전원 차단 및 방화선 구축', damage: '외부 인입설비 소실', prevention: '산지 인접 건물 방화 이격거리 확보', tags: ['산불', '연소확대', '산지인접', '인입설비'] },
        { id: 'case-009', title: '산사태 인접 건물 지반붕괴로 인입선 단선 화재', cause: '산사태로 지반이 붕괴되며 전기 인입선 단선 및 스파크', response: '긴급 단전 및 인입설비 재시공', damage: '인입설비 손상, 인명피해 없음', prevention: '산사태위험지역 전기설비 보호 및 우회 인입', tags: ['산사태', '지반붕괴', '단선', '인입선', '급경사지'] },
        { id: 'case-010', title: '산업단지 변압기 과열 화재', cause: '산업용 전력사용량 증가로 변압기 과열', response: '변압기 용량 증설 및 냉각 보강', damage: '설비 가동 중단, 인명피해 없음', prevention: '전력수요 예측 기반 변압기 용량 관리', tags: ['변압기', '과열', '산업용전력', '산업단지', '전력증가'] },
        { id: 'case-011', title: '노후 배전설비 밀집지역 동시 다발 정전·화재', cause: '노후 배전설비 비율이 높은 지역의 설비 동시 열화', response: '구역 단위 설비 일제 점검 및 순차 교체', damage: '지역 부분 정전, 소규모 화재 2건', prevention: '노후 배전설비 밀집지역 우선 정비', tags: ['노후배전설비', '주거밀집', '정전', '지역단위'] },
        { id: 'case-012', title: '용도변경 건물 전기용량 부족 과부하 화재', cause: '주거→상업 용도변경 후 전기용량 부족에 따른 과부하', response: '수전용량 증설 및 회로 재설계', damage: '1개 층 소실', prevention: '용도변경 시 전기설비 용량 재검토', tags: ['용도변경', '용도지구', '전기용량부족', '과부하'] }
    ];

    function num(text) {
        var n = Number(String(text == null ? '' : text).replace(/[^0-9.\-]/g, ''));
        return isFinite(n) ? n : null;
    }

    function collectFactors() {
        var factors = [];
        COMPONENTS.forEach(function (c) {
            var el = document.getElementById(c.id);
            if (!el) { return; }
            var v = num(el.textContent);
            if (v != null && v > 0) {
                factors.push({ feature: c.id, label: c.label, contribution: v });
            }
        });
        factors.sort(function (a, b) { return b.contribution - a.contribution; });
        return factors.slice(0, 5);
    }

    function esc(s) {
        return String(s == null ? '-' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function setBusy(busy) {
        btn.disabled = busy;
        btn.textContent = busy ? '분석 중…' : 'AI 위험원인 설명';
    }

    // ---------- 데모: 위험원인 설명 생성 ----------
    function demoExplainHtml(score, grade, factors) {
        var g = grade || '';
        var advice;
        if (g.indexOf('위험') >= 0 || score >= 40) {
            advice = '고위험 건물로 분류됩니다. 우선 현장점검과 노후 설비 교체를 시급히 시행할 것을 권고합니다.';
        } else if (g.indexOf('경고') >= 0 || score >= 30) {
            advice = '경고 수준입니다. 단기 내 정밀 점검과 점검 지적사항 조치를 권고합니다.';
        } else {
            advice = '정기 점검주기를 준수하고 위 요인을 지속 모니터링하시기 바랍니다.';
        }
        var top = factors.slice(0, 3);
        var items = top.map(function (f) {
            var d = FACTOR_DESC[f.feature] || '해당 항목의 위험 신호가 관측됩니다.';
            return '<li><b>' + esc(f.label) + '</b> (' + f.contribution + '점) — ' + esc(d) + '</li>';
        }).join('');
        var topNames = top.map(function (f) { return f.label; }).join(', ');
        return ''
            + '<div style="line-height:1.75;">'
            + '<div style="margin-bottom:10px;">이 건물의 종합 위험점수는 <b>' + (score == null ? '-' : score) + '점</b>'
            + (grade ? ', \'<b>' + esc(grade) + '</b>\' 등급' : '') + '입니다. '
            + '분석 결과 위험도에 가장 크게 기여한 요인은 <b>' + esc(topNames || '해당 없음') + '</b>입니다.</div>'
            + (items ? '<div style="margin:8px 0 4px;font-weight:600;color:#2c3e50;">위험 원인 (근거)</div><ul style="margin:0 0 10px 18px;padding:0;">' + items + '</ul>' : '')
            + '<div style="margin:8px 0 4px;font-weight:600;color:#2c3e50;">종합 의견</div>'
            + '<div>' + esc(advice) + '</div>'
            + '</div>';
    }

    btn.addEventListener('click', function () {
        var scoreEl = document.getElementById('combinedScore');
        var gradeEl = document.getElementById('combinedGrade');
        var addrEl = document.getElementById('addr');
        var score = scoreEl ? num(scoreEl.textContent) : null;
        if (score == null) {
            out.textContent = '종합 점수를 불러온 뒤 다시 시도하세요.';
            return;
        }
        var grade = gradeEl ? (gradeEl.textContent || '').trim() : null;
        var factors = collectFactors();

        if (DEMO_MODE) {
            setBusy(true);
            out.textContent = 'AI가 위험 원인을 분석하는 중입니다…';
            setTimeout(function () {
                out.innerHTML = demoExplainHtml(score, grade, factors);
                setBusy(false);
            }, 1100);
            return;
        }

        setBusy(true);
        out.textContent = 'AI가 위험 원인을 분석하는 중입니다… (로컬 모델은 수십 초 걸릴 수 있어요)';
        fetch(LLM_BASE + '/explain/building', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                address: addrEl ? (addrEl.textContent || '').trim() : null,
                predicted_score: score, grade: grade, factors: factors
            })
        })
            .then(function (r) { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); })
            .then(function (res) { out.innerHTML = String(res.text).replace(/\n/g, '<br>'); })
            .catch(function (err) {
                out.innerHTML =
                    '<span style="color:#c0392b;">분석 실패: ' + err.message + '</span><br>'
                    + '<span style="font-size:12px;color:#7f8c8d;">LLM 사이드카(' + LLM_BASE
                    + ')와 Ollama가 실행 중인지 확인하세요.</span>';
            })
            .finally(function () { setBusy(false); });
    });

    // ---------- 기능 2: 유사 사고 사례 추천 (RAG) ----------
    var simBtn = document.getElementById('aiSimilarBtn');
    var simOut = document.getElementById('aiSimilarContent');
    if (!simBtn || !simOut) { return; }

    function renderCases(res) {
        var html = '';
        if (res.summary) {
            html += '<div style="margin-bottom:12px;padding:10px;background:#f5f7fa;border-radius:6px;line-height:1.7;">'
                + esc(res.summary) + '</div>';
        }
        (res.cases || []).forEach(function (c, i) {
            html += '<div style="margin-bottom:10px;padding-bottom:10px;'
                + (i < res.cases.length - 1 ? 'border-bottom:1px solid #eee;' : '') + '">'
                + '<div style="font-weight:600;">' + esc(c.title)
                + ' <span style="color:#7f8c8d;font-weight:400;font-size:12px;">유사도 '
                + Math.round((c.score || 0) * 100) + '%</span></div>'
                + '<div style="font-size:13px;color:#555;line-height:1.6;">'
                + '원인: ' + esc(c.cause) + '<br>대응: ' + esc(c.response) + '<br>'
                + '피해: ' + esc(c.damage) + '<br>예방: ' + esc(c.prevention) + '</div></div>';
        });
        simOut.innerHTML = html || '유사 사례를 찾지 못했습니다.';
    }

    // 데모: 화면 위험요인 → 사례 태그 매칭으로 top_k 사례 랭킹(RAG 흉내)
    function demoSimilar(factors, topK) {
        var ranked = CASES.map(function (c) {
            var score = 0;
            factors.forEach(function (f, idx) {
                var kws = FACTOR_KEYWORDS[f.feature] || [];
                var hit = c.tags.some(function (t) { return kws.indexOf(t) >= 0; });
                if (hit) { score += (factors.length - idx); } // 상위 요인일수록 가중
            });
            return { c: c, score: score };
        });
        ranked.sort(function (a, b) { return b.score - a.score; });
        // 매칭이 전혀 없으면 노후/과부하/지역 대표 사례로 폴백
        if (ranked[0].score === 0) {
            var fb = ['case-007', 'case-002', 'case-011'];
            ranked = fb.map(function (id, i) {
                return { c: CASES.filter(function (x) { return x.id === id; })[0], score: 3 - i };
            });
        }
        var top = ranked.slice(0, topK || 3);
        var simBase = [0.72, 0.64, 0.57, 0.51];
        var cases = top.map(function (r, i) {
            var c = r.c;
            return {
                title: c.title, cause: c.cause, response: c.response,
                damage: c.damage, prevention: c.prevention,
                score: simBase[i] != null ? simBase[i] : 0.5
            };
        });
        var topCase = cases[0];
        var domFactor = factors.length ? factors[0].label : '노후·과부하 요인';
        var summary = "현재 건물은 '" + topCase.title + "' 사례와 가장 유사합니다(유사도 "
            + Math.round(topCase.score * 100) + '%). 두 경우 모두 ' + domFactor
            + ' 등이 핵심 위험으로 작용했습니다. 해당 사례의 대응(' + topCase.response
            + ')을 참고해 ' + topCase.prevention + '을(를) 우선 검토하시기 바랍니다.';
        return { summary: summary, cases: cases };
    }

    simBtn.addEventListener('click', function () {
        var gradeEl = document.getElementById('combinedGrade');
        var factors = collectFactors();
        simBtn.disabled = true;
        simBtn.textContent = '검색 중…';
        simOut.textContent = '유사한 과거 사고 사례를 검색하는 중입니다…';

        if (DEMO_MODE) {
            setTimeout(function () {
                renderCases(demoSimilar(factors, 3));
                simBtn.disabled = false;
                simBtn.textContent = '유사 사례 검색';
            }, 1100);
            return;
        }

        fetch(LLM_BASE + '/similar-cases', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                grade: gradeEl ? (gradeEl.textContent || '').trim() : null,
                factors: factors, top_k: 3
            })
        })
            .then(function (r) { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); })
            .then(renderCases)
            .catch(function (err) {
                simOut.innerHTML =
                    '<span style="color:#c0392b;">검색 실패: ' + err.message + '</span><br>'
                    + '<span style="font-size:12px;color:#7f8c8d;">LLM 사이드카와 Ollama 실행 여부를 확인하세요.</span>';
            })
            .finally(function () {
                simBtn.disabled = false;
                simBtn.textContent = '유사 사례 검색';
            });
    });
}());
