/**
 * risk-region-summary.js - 지역별 현황 (시도/구군 필터)
 * 시도-구군 매핑: 전국 사업소 일람표 기준
 */
var regionData = [];
var districtData = [];

/** 시도 → 구군 매핑 */
var REGION_DISTRICT_MAP = {
    '서울': ['마포구','은평구','서대문구','용산구','종로구','중구','동대문구','성동구','광진구','강동구',
             '송파구','영등포구','구로구','금천구','강서구','양천구','동작구','강남구','관악구','서초구',
             '도봉구','강북구','성북구','노원구','중랑구'],
    '부산': ['동구','서구','중구','북구','사상구','부산진구','강서구','영도구','사하구',
             '남구','수영구','금정구','해운대구','기장군','연제구','동래구'],
    '울산': ['중구','남구','동구','북구','울주군'],
    '대구': ['중구','동구','수성구','북구','서구','남구','달서구','달성군','군위군'],
    '인천': ['동구','중구','미추홀구','연수구','남동구','부평구','옹진군','서구','계양구','강화군'],
    '광주': ['동구','서구','남구','북구','광산구'],
    '대전': ['동구','중구','서구','유성구','대덕구'],
    '세종': ['세종시'],
    '경기': ['수원시','화성시','오산시','성남시','하남시','광주시','안산시','시흥시','안양시','군포시',
             '의왕시','과천시','광명시','평택시','안성시','이천시','여주시','용인시',
             '의정부시','동두천시','양주시','포천시','연천군','고양시','파주시','구리시','남양주시','양평군','가평군'],
    '강원': ['춘천시','화천군','철원군','홍천군','양구군','강릉시','동해시','삼척시','평창군','정선군',
             '원주시','횡성군','영월군','속초시','고성군','양양군','인제군','태백시'],
    '충북': ['청주시','보은군','괴산군','진천군','증평군','충주시','음성군','제천시','단양군','영동군','옥천군'],
    '충남': ['천안시','아산시','예산군','당진시','홍성군','논산시','공주시','계룡시','부여군',
             '서산시','태안군','보령시','청양군','서천군','금산군'],
    '전북': ['전주시','완주군','임실군','진안군','김제시','장수군','무주군','정읍시','고창군','부안군',
             '익산시','군산시','남원시','순창군'],
    '전남': ['나주시','함평군','화순군','담양군','장성군','영광군','곡성군',
             '순천시','광양시','보성군','구례군','고흥군',
             '목포시','무안군','신안군','영암군',
             '강진군','장흥군','해남군','진도군','완도군','여수시'],
    '경북': ['경산시','영천시','청도군','고령군','구미시','칠곡군','포항시','영덕군','울릉군','울진군',
             '김천시','상주시','성주군','문경시','안동시','의성군','청송군','영양군','영주시','봉화군','예천군','경주시'],
    '경남': ['창원시','함안군','의령군','김해시','양산시','진주시','사천시','남해군','하동군','산청군',
             '통영시','거제시','고성군','거창군','함양군','합천군','밀양시','창녕군'],
    '제주': ['제주시','서귀포시']
};

/** 시도 표시 순서 */
var REGION_ORDER = ['서울','부산','대구','인천','광주','대전','울산','세종',
                    '경기','강원','충북','충남','전북','전남','경북','경남','제주'];

$(function() {
    loadAllData();

    $('#filterRegion').on('change', function() {
        updateDistrictCombo();
        filterAndRender();
    });

    $('#filterDistrict').on('change', function() {
        filterAndRender();
    });

    $('#btnSearch').on('click', function() {
        filterAndRender();
    });

    $('#btnDownloadRegionExcel').on('click', function() {
        downloadDangerExcel();
    });
});

/** 시도별 + 구군별 데이터 동시 로드 */
function loadAllData() {
    var loaded = 0;
    var checkReady = function() {
        loaded++;
        if (loaded >= 2) {
            initRegionCombo();
            filterAndRender();
        }
    };

    RiskApp.callApi('selectRegionSummary.do', {}, function(res) {
        regionData = res.data || [];
        checkReady();
    });

    RiskApp.callApi('selectRegionDistrictSummary.do', {}, function(res) {
        districtData = res.data || [];
        checkReady();
    });
}

/** 시도 콤보박스 초기화 (DB에 있는 시도만, 정렬 순서는 하드코딩) */
function initRegionCombo() {
    var regionInDb = {};
    for (var i = 0; i < regionData.length; i++) {
        var nm = regionData[i].regionNm;
        if (nm) regionInDb[nm] = true;
    }

    var $sel = $('#filterRegion');
    $sel.find('option:gt(0)').remove();

    for (var j = 0; j < REGION_ORDER.length; j++) {
        var r = REGION_ORDER[j];
        if (regionInDb[r]) {
            $sel.append('<option value="' + r + '">' + r + '</option>');
        }
    }
    // 매핑에 없는 기타 시도
    for (var key in regionInDb) {
        if (REGION_ORDER.indexOf(key) < 0) {
            $sel.append('<option value="' + key + '">' + key + '</option>');
        }
    }

    updateDistrictCombo();
}

/** 구군 콤보박스 갱신 (선택된 시도 기준, 일람표 순서) */
function updateDistrictCombo() {
    var selRegion = $('#filterRegion').val();
    var $sel = $('#filterDistrict');
    $sel.find('option:gt(0)').remove();

    // DB에 존재하는 구군
    var distInDb = {};
    for (var i = 0; i < districtData.length; i++) {
        var d = districtData[i];
        if (!selRegion || d.regionNm === selRegion) {
            if (d.districtNm) distInDb[d.districtNm] = true;
        }
    }

    if (selRegion && REGION_DISTRICT_MAP[selRegion]) {
        // 일람표 순서대로 (DB에 있는 것만)
        var list = REGION_DISTRICT_MAP[selRegion];
        for (var j = 0; j < list.length; j++) {
            if (distInDb[list[j]]) {
                $sel.append('<option value="' + list[j] + '">' + list[j] + '</option>');
            }
        }
    } else {
        // 전체: DB 기준
        var sorted = Object.keys(distInDb).sort();
        for (var k = 0; k < sorted.length; k++) {
            $sel.append('<option value="' + sorted[k] + '">' + sorted[k] + '</option>');
        }
    }
}

/** 필터링 + 그리드 렌더링 */
function filterAndRender() {
    var selRegion = $('#filterRegion').val();
    var selDistrict = $('#filterDistrict').val();

    // 시도별 요약 필터
    var filteredRegion = [];
    for (var i = 0; i < regionData.length; i++) {
        if (selRegion && regionData[i].regionNm !== selRegion) continue;
        filteredRegion.push(regionData[i]);
    }

    var regionCols = [
        { id: 'regionNm', title: '시도', width: 80 },
        { id: 'bldgCnt', title: '건물수', width: 65 },
        { id: 'avgTotalScore', title: '평균 기본점수', width: 85 },
        { id: 'avgWeatherScore', title: '평균 기상점수', width: 85 },
        { id: 'avgCombinedScore', title: '평균 종합점수', width: 85 },
        { id: 'gradeE', title: '심각(E)', width: 55 },
        { id: 'gradeD', title: '위험(D)', width: 55 },
        { id: 'gradeC', title: '경고(C)', width: 55 },
        { id: 'gradeB', title: '관심(B)', width: 55 },
        { id: 'gradeA', title: '안전(A)', width: 55 }
    ];
    RiskApp.createGrid('sbGridRegion', regionCols, filteredRegion);

    // 구군별 상세 필터
    var filteredDistrict = [];
    for (var j = 0; j < districtData.length; j++) {
        var d = districtData[j];
        if (selRegion && d.regionNm !== selRegion) continue;
        if (selDistrict && d.districtNm !== selDistrict) continue;
        filteredDistrict.push(d);
    }

    $('#totalCount').text(filteredDistrict.length);

    var distCols = [
        { id: 'regionNm', title: '시도', width: 70 },
        { id: 'districtNm', title: '구군', width: 75 },
        { id: 'bldgCnt', title: '건물수', width: 60 },
        { id: 'avgCombinedScore', title: '평균 종합점수', width: 85 },
        { id: 'gradeE', title: '심각(E)', width: 55 },
        { id: 'gradeD', title: '위험(D)', width: 55 },
        { id: 'gradeC', title: '경고(C)', width: 55 },
        { id: 'gradeB', title: '관심(B)', width: 55 },
        { id: 'gradeA', title: '안전(A)', width: 55 }
    ];
    RiskApp.createGrid('sbGridDistrict', distCols, filteredDistrict);
}

function downloadDangerExcel() {
    var params = [];
    var regionNm = $('#filterRegion').val();
    var districtNm = $('#filterDistrict').val();

    if (regionNm) params.push('regionNm=' + encodeURIComponent(regionNm));
    if (districtNm) params.push('districtNm=' + encodeURIComponent(districtNm));

    var qs = params.length ? ('?' + params.join('&')) : '';
    location.href = 'downloadDangerBuildingExcel.do' + qs;
}
