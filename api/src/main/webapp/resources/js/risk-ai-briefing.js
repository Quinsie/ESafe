/*
 * risk-ai-briefing.js - 전국 위험지도의 'AI 브리핑 및 상황요약 보고서' 칸 연동.
 * ESafe LLM 사이드카(FastAPI, 기본 :8800)를 호출해 브리핑 텍스트를 표출한다.
 * 모델 미연결 상태에서는 사이드카가 mock SHAP으로 채워 동작을 보여준다.
 */
(function () {
    'use strict';

    var LLM_BASE = window.ESAFE_LLM_BASE || 'http://localhost:8800';
    var REGION_NAME = window.ESAFE_BRIEF_REGION || '광주전남본부직할 관할 지역';

    var contentEl = document.getElementById('nationwideBriefingContent');
    var btnEl = document.getElementById('nationwideBriefingBtn');
    if (!contentEl || !btnEl) {
        return;
    }

    function setBusy(busy) {
        btnEl.disabled = busy;
        btnEl.textContent = busy ? '브리핑 생성 중…' : 'AI 브리핑 생성';
    }

    function render(text, usedMock) {
        var note = usedMock
            ? '<div style="font-size:11px;color:#e67e22;margin-bottom:6px;">※ 모델 미연결 — 예시(mock) 데이터 기반 브리핑입니다.</div>'
            : '';
        // 줄바꿈을 <br>로
        var html = String(text).replace(/\n/g, '<br>');
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

    btnEl.addEventListener('click', generate);
}());
