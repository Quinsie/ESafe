/**
 * risk-branch-summary.js - 사업소별 현황 (본부/사업소 필터)
 * 본부-사업소 매핑: 전국 사업소 일람표 기준
 */
var allData = [];

/** 본부 → 소속 사업소 매핑 */
var HQ_BRANCH_MAP = {
    '서울본부': ['서울본부직할','서울동부지사','서울서부지사','서울남부지사','서울북부지사'],
    '부산울산본부': ['부산울산본부직할','울산지사','부산동부지사'],
    '대구경북본부': ['대구경북본부직할','대구서부지사','구미칠곡지사','경북동부지사','경북서부지사','경북북부지사','경주지사'],
    '인천본부': ['인천본부직할','인천서부지사','부천김포지사'],
    '광주전남본부': ['광주전남본부직할','전남동부지사','전남서부지사','전남남부지사','여수지사'],
    '대전세종충남본부': ['대전세종충남본부직할','천안아산지사','충남중부지사','충남남부지사','서산태안지사','충남서부지사'],
    '경기본부': ['경기본부직할','경기중부지사','안산시흥지사','경기서부지사','평택안성지사','이천여주지사','용인지사'],
    '경기북부본부': ['경기북부본부직할','고양파주지사','경기북동부지사'],
    '강원본부': ['강원본부직할','강원동부지사','원주횡성지사','강원북부지사','강원남부지사'],
    '충북본부': ['충북본부직할','충주음성지사','제천단양지사','영동옥천지사'],
    '전북본부': ['전북본부직할','전북서부지사','익산지사','군산지사','남원순창지사'],
    '경남본부': ['경남본부직할','김해양산지사','경남서부지사','경남남부지사','경남북부지사','밀양창녕지사'],
    '제주본부': ['제주본부직할']
};

/** 사업소명 → 본부명 역매핑 (초기화 시 자동 생성) */
var BRANCH_TO_HQ = {};
(function() {
    for (var hq in HQ_BRANCH_MAP) {
        var branches = HQ_BRANCH_MAP[hq];
        for (var i = 0; i < branches.length; i++) {
            BRANCH_TO_HQ[branches[i]] = hq;
        }
    }
})();

/** 본부명 추출 (매핑 우선, 없으면 "본부" 키워드로 추출) */
function getHqName(branchNm) {
    if (!branchNm) return '';
    if (BRANCH_TO_HQ[branchNm]) return BRANCH_TO_HQ[branchNm];
    var idx = branchNm.indexOf('본부');
    if (idx >= 0) return branchNm.substring(0, idx + 2);
    return '기타';
}

$(function() {
    loadBranchData();

    $('#filterHq').on('change', function() {
        updateBranchCombo();
        filterAndRender();
    });

    $('#filterBranch').on('change', function() {
        filterAndRender();
    });

    $('#btnSearch').on('click', function() {
        filterAndRender();
    });

    $('#btnDownloadBranchExcelAll').on('click', function() {
        downloadBranchExcel(false);
    });

    $('#btnDownloadBranchExcelDanger').on('click', function() {
        downloadBranchExcel(true);
    });
});

/** 전체 데이터 로드 + 콤보박스 초기화 */
function loadBranchData() {
    RiskApp.callApi('selectBranchSummary.do', {}, function(res) {
        allData = res.data || [];
        initHqCombo();
        filterAndRender();
    });
}

/** 본부 콤보박스 초기화 */
function initHqCombo() {
    // DB에 존재하는 본부만 표시
    var hqSet = {};
    for (var i = 0; i < allData.length; i++) {
        var hq = getHqName(allData[i].branchNm);
        if (hq) hqSet[hq] = true;
    }

    var $sel = $('#filterHq');
    $sel.find('option:gt(0)').remove();

    // 일람표 순서대로 표시 (DB에 있는 것만)
    var hqOrder = ['서울본부','부산울산본부','대구경북본부','인천본부','광주전남본부',
                   '대전세종충남본부','경기본부','경기북부본부','강원본부','충북본부',
                   '전북본부','경남본부','제주본부'];
    for (var j = 0; j < hqOrder.length; j++) {
        if (hqSet[hqOrder[j]]) {
            $sel.append('<option value="' + hqOrder[j] + '">' + hqOrder[j] + '</option>');
        }
    }
    // 매핑에 없는 기타 본부
    for (var key in hqSet) {
        if (hqOrder.indexOf(key) < 0) {
            $sel.append('<option value="' + key + '">' + key + '</option>');
        }
    }

    updateBranchCombo();
}

/** 사업소 콤보박스 갱신 (선택된 본부 기준) */
function updateBranchCombo() {
    var selHq = $('#filterHq').val();
    var $sel = $('#filterBranch');
    $sel.find('option:gt(0)').remove();

    // DB에 존재하는 사업소만 표시
    var branchInDb = {};
    for (var i = 0; i < allData.length; i++) {
        var nm = allData[i].branchNm;
        if (nm) branchInDb[nm] = true;
    }

    if (selHq && HQ_BRANCH_MAP[selHq]) {
        // 일람표 순서대로 (DB에 있는 것만)
        var list = HQ_BRANCH_MAP[selHq];
        for (var j = 0; j < list.length; j++) {
            if (branchInDb[list[j]]) {
                $sel.append('<option value="' + list[j] + '">' + list[j] + '</option>');
            }
        }
    } else {
        // 전체 또는 기타: DB 데이터 기준
        var sorted = Object.keys(branchInDb).sort();
        for (var k = 0; k < sorted.length; k++) {
            if (!selHq || getHqName(sorted[k]) === selHq) {
                $sel.append('<option value="' + sorted[k] + '">' + sorted[k] + '</option>');
            }
        }
    }
}

/** 필터링 + 그리드 렌더링 */
function filterAndRender() {
    var selHq = $('#filterHq').val();
    var selBranch = $('#filterBranch').val();

    var filtered = [];
    for (var i = 0; i < allData.length; i++) {
        var nm = allData[i].branchNm || '';

        if (selBranch && nm !== selBranch) continue;
        if (!selBranch && selHq && getHqName(nm) !== selHq) continue;

        filtered.push(allData[i]);
    }

    $('#totalCount').text(filtered.length);

    var columns = [
        { id: 'branchNm', title: '사업소', width: 130, align: 'left' },
        { id: 'bldgCnt', title: '건물수', width: 60 },
        { id: 'avgTotalScore', title: '평균 기본점수', width: 85 },
        { id: 'avgWeatherScore', title: '평균 기상점수', width: 85 },
        { id: 'avgCombinedScore', title: '평균 종합점수', width: 85 },
        { id: 'gradeE', title: '심각(E)', width: 55 },
        { id: 'gradeD', title: '위험(D)', width: 55 },
        { id: 'gradeC', title: '경고(C)', width: 55 },
        { id: 'gradeB', title: '관심(B)', width: 55 },
        { id: 'gradeA', title: '안전(A)', width: 55 }
    ];
    RiskApp.createGrid('sbGridBranch', columns, filtered);
}

function downloadBranchExcel(dangerOnly) {
    var params = [];
    var branchNm = $('#filterBranch').val();
    var hqNm = $('#filterHq').val();

    if (branchNm) {
        params.push('branchNm=' + encodeURIComponent(branchNm));
    } else if (hqNm) {
        params.push('hqNm=' + encodeURIComponent(hqNm));
    }

    var qs = params.length ? ('?' + params.join('&')) : '';
    location.href = (dangerOnly ? 'downloadDangerBuildingExcel.do' : 'downloadBuildingExcel.do') + qs;
}
