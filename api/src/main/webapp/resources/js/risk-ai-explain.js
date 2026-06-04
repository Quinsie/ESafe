/*
 * risk-ai-explain.js - 건물 상세: AI 위험원인 설명 (기능 1, XAI+LLM).
 * 화면에 이미 로드된 항목별 위험 점수를 근거(factor)로 모아 LLM 사이드카에 보낸다.
 * 현재 AHP 가산모델에서는 항목 점수가 곧 기여도이므로 실제 데이터로 동작한다.
 * (팀원 CatBoost 모델 연결 후에는 사이드카가 SHAP 값으로 factor를 대체한다.)
 */
(function () {
    'use strict';

    var LLM_BASE = window.ESAFE_LLM_BASE || 'http://localhost:8800';

    var btn = document.getElementById('aiExplainBtn');
    var out = document.getElementById('aiExplainContent');
    if (!btn || !out) {
        return;
    }

    // 화면 점수 카드 id → 사람이 읽는 위험요소 이름
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

    function num(text) {
        var n = Number(String(text == null ? '' : text).replace(/[^0-9.\-]/g, ''));
        return isFinite(n) ? n : null;
    }

    // 점수>0 인 항목만 기여도 큰 순으로 상위 5개
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

    function setBusy(busy) {
        btn.disabled = busy;
        btn.textContent = busy ? '분석 중…' : 'AI 위험원인 설명';
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

        setBusy(true);
        out.textContent = 'AI가 위험 원인을 분석하는 중입니다… (로컬 모델은 수십 초 걸릴 수 있어요)';
        fetch(LLM_BASE + '/explain/building', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                address: addrEl ? (addrEl.textContent || '').trim() : null,
                predicted_score: score,
                grade: gradeEl ? (gradeEl.textContent || '').trim() : null,
                factors: collectFactors()
            })
        })
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.json();
            })
            .then(function (res) {
                out.innerHTML = String(res.text).replace(/\n/g, '<br>');
            })
            .catch(function (err) {
                out.innerHTML =
                    '<span style="color:#c0392b;">분석 실패: ' + err.message + '</span><br>'
                    + '<span style="font-size:12px;color:#7f8c8d;">LLM 사이드카(' + LLM_BASE
                    + ')와 Ollama가 실행 중인지 확인하세요.</span>';
            })
            .finally(function () {
                setBusy(false);
            });
    });

    // --- 기능 2: 유사 사고 사례 추천 (RAG) ---
    var simBtn = document.getElementById('aiSimilarBtn');
    var simOut = document.getElementById('aiSimilarContent');
    if (simBtn && simOut) {
        var esc = function (s) {
            return String(s == null ? '-' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        };
        var renderCases = function (res) {
            var html = '';
            if (res.summary) {
                html += '<div style="margin-bottom:12px;padding:10px;background:#f5f7fa;border-radius:6px;">'
                    + esc(res.summary) + '</div>';
            }
            (res.cases || []).forEach(function (c, i) {
                html += '<div style="margin-bottom:10px;padding-bottom:10px;'
                    + (i < res.cases.length - 1 ? 'border-bottom:1px solid #eee;' : '') + '">'
                    + '<div style="font-weight:600;">' + esc(c.title)
                    + ' <span style="color:#7f8c8d;font-weight:400;font-size:12px;">유사도 '
                    + Math.round((c.score || 0) * 100) + '%</span></div>'
                    + '<div style="font-size:13px;color:#555;line-height:1.6;">'
                    + '원인: ' + esc(c.cause) + '<br>'
                    + '대응: ' + esc(c.response) + '<br>'
                    + '피해: ' + esc(c.damage) + '<br>'
                    + '예방: ' + esc(c.prevention) + '</div></div>';
            });
            simOut.innerHTML = html || '유사 사례를 찾지 못했습니다.';
        };
        simBtn.addEventListener('click', function () {
            var gradeEl = document.getElementById('combinedGrade');
            simBtn.disabled = true;
            simBtn.textContent = '검색 중…';
            simOut.textContent = '유사한 과거 사고 사례를 검색하는 중입니다…';
            fetch(LLM_BASE + '/similar-cases', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    grade: gradeEl ? (gradeEl.textContent || '').trim() : null,
                    factors: collectFactors(),
                    top_k: 3
                })
            })
                .then(function (r) {
                    if (!r.ok) { throw new Error('HTTP ' + r.status); }
                    return r.json();
                })
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
    }
}());
