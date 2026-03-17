/**
 * risk-dashboard.js - 대시보드 (차트)
 */
$(function() {
    loadGradeStats();
    loadHqSummary();
    loadWeatherAlertCount();
});

/** 등급별 통계 → 요약 카드 + 도넛 차트 */
function loadGradeStats() {
    RiskApp.callApi('selectGradeStats.do', {}, function(res) {
        var data = res.data || [];
        var total = 0, danger = 0, warning = 0;
        var labels = [], counts = [], colors = [];
        var gradeOrder = ['A', 'B', 'C', 'D', 'E'];
        var colorMap = { A: '#27ae60', B: '#3498db', C: '#f39c12', D: '#e67e22', E: '#e74c3c' };
        var nameMap = { A: '안전', B: '관심', C: '주의', D: '경고', E: '위험' };

        // "적용 후" (기상점수 반영) 데이터만 필터링
        var afterData = [];
        for (var i = 0; i < data.length; i++) {
            if (data[i].totalGrade === 'AFTER' || data[i].totalGrade === '적용 후') {
                afterData.push(data[i]);
            }
        }
        if (afterData.length === 0) {
            for (var j = 0; j < data.length; j++) {
                if (data[j].totalGrade === 'BEFORE' || data[j].totalGrade === '적용 전') {
                    afterData.push(data[j]);
                }
            }
        }

        // A~E 고정 집계로 렌더링 (응답 누락/순서 영향 제거)
        var countByGrade = { A: 0, B: 0, C: 0, D: 0, E: 0 };
        for (var k = 0; k < afterData.length; k++) {
            var g = (afterData[k].riskCd || '').toUpperCase();
            if (countByGrade.hasOwnProperty(g)) {
                countByGrade[g] += (Number(afterData[k].bldgCnt) || 0);
            }
        }

        for (var gi = 0; gi < gradeOrder.length; gi++) {
            var grade = gradeOrder[gi];
            var cnt = countByGrade[grade];
            total += cnt;
            if (grade === 'D' || grade === 'E') danger += cnt;
            if (grade === 'C') warning += cnt;
            labels.push(grade + ' ' + nameMap[grade]);
            counts.push(cnt);
            colors.push(colorMap[grade]);
        }

        $('#totalCount').text(RiskApp.formatNumber(total));
        $('#dangerCount').text(RiskApp.formatNumber(danger));
        $('#warningCount').text(RiskApp.formatNumber(warning));

        if (typeof Chart !== 'undefined') {
            new Chart(document.getElementById('gradeChart'), {
                type: 'doughnut',
                data: { labels: labels, datasets: [{ data: counts, backgroundColor: colors }] },
                options: { responsive: true, plugins: { legend: { position: 'right' } } }
            });
        }
    });
}

/** 본부별 요약 → 바 차트 */
function loadHqSummary() {
    RiskApp.callApi('selectHqSummary.do', {}, function(res) {
        var data = res.data || [];
        var labels = [], dangerVals = [], totalVals = [];
        for (var i = 0; i < data.length; i++) {
            labels.push(data[i].branchNm || '');
            dangerVals.push(Number(data[i].dangerCnt) || 0);
            totalVals.push(Number(data[i].bldgCnt) || 0);
        }

        if (typeof Chart !== 'undefined') {
            new Chart(document.getElementById('hqChart'), {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        { label: '위험(D+E)', data: dangerVals, backgroundColor: '#e74c3c' },
                        { label: '전체 건물', data: totalVals, backgroundColor: '#3498db' }
                    ]
                },
                options: { responsive: true, indexAxis: 'y', plugins: { legend: { display: true } } }
            });
        }
    });
}

/** 당일 특보 건수 */
function loadWeatherAlertCount() {
    RiskApp.callApi('selectWeatherAlertToday.do', {}, function(res) {
        $('#alertCount').text(res.totalCount || 0);
    });
}
