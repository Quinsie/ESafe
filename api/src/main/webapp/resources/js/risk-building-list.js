/**
 * risk-building-list.js - 건물 목록 (검색 + SBGrid + 페이징)
 * 본부/사업소, 시도/구군 하드코딩 매핑 포함
 */
var pageIndex = 1;
var pageSize = 15;

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

var HQ_ORDER = ['서울본부','부산울산본부','대구경북본부','인천본부','광주전남본부',
                '대전세종충남본부','경기본부','경기북부본부','강원본부','충북본부',
                '전북본부','경남본부','제주본부'];

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

var REGION_ORDER = ['서울','부산','대구','인천','광주','대전','울산','세종',
                    '경기','강원','충북','충남','전북','전남','경북','경남','제주'];

$(function() {
    initHqCombo();
    initRegionCombo();
    searchList();

    // 본부 변경 → 사업소 콤보 갱신
    $('#searchHq').on('change', function() {
        updateBranchCombo();
    });

    // 시도 변경 → 구군 콤보 갱신
    $('#searchRegion').on('change', function() {
        updateDistrictCombo();
    });

    $('#btnSearch').on('click', function() {
        pageIndex = 1;
        searchList();
    });

    // 엔터키 검색
    $('#searchKeyword').on('keypress', function(e) {
        if (e.which === 13) { pageIndex = 1; searchList(); }
    });

    // 페이징 클릭
    $(document).on('click', '#pagingArea a', function() {
        pageIndex = parseInt($(this).data('page'));
        searchList();
    });
});

/** 본부 콤보박스 초기화 */
function initHqCombo() {
    var $sel = $('#searchHq');
    for (var i = 0; i < HQ_ORDER.length; i++) {
        $sel.append('<option value="' + HQ_ORDER[i] + '">' + HQ_ORDER[i] + '</option>');
    }
    updateBranchCombo();
}

/** 사업소 콤보박스 갱신 */
function updateBranchCombo() {
    var selHq = $('#searchHq').val();
    var $sel = $('#searchBranch');
    $sel.find('option:gt(0)').remove();

    if (selHq && HQ_BRANCH_MAP[selHq]) {
        var list = HQ_BRANCH_MAP[selHq];
        for (var i = 0; i < list.length; i++) {
            $sel.append('<option value="' + list[i] + '">' + list[i] + '</option>');
        }
    } else {
        // 전체: 모든 사업소 표시
        for (var j = 0; j < HQ_ORDER.length; j++) {
            var branches = HQ_BRANCH_MAP[HQ_ORDER[j]];
            for (var k = 0; k < branches.length; k++) {
                $sel.append('<option value="' + branches[k] + '">' + branches[k] + '</option>');
            }
        }
    }
}

/** 시도 콤보박스 초기화 */
function initRegionCombo() {
    var $sel = $('#searchRegion');
    for (var i = 0; i < REGION_ORDER.length; i++) {
        $sel.append('<option value="' + REGION_ORDER[i] + '">' + REGION_ORDER[i] + '</option>');
    }
    updateDistrictCombo();
}

/** 구군 콤보박스 갱신 */
function updateDistrictCombo() {
    var selRegion = $('#searchRegion').val();
    var $sel = $('#searchDistrict');
    $sel.find('option:gt(0)').remove();

    if (selRegion && REGION_DISTRICT_MAP[selRegion]) {
        var list = REGION_DISTRICT_MAP[selRegion];
        for (var i = 0; i < list.length; i++) {
            $sel.append('<option value="' + list[i] + '">' + list[i] + '</option>');
        }
    } else {
        // 전체: 모든 구군 표시
        for (var j = 0; j < REGION_ORDER.length; j++) {
            var districts = REGION_DISTRICT_MAP[REGION_ORDER[j]];
            if (districts) {
                for (var k = 0; k < districts.length; k++) {
                    $sel.append('<option value="' + districts[k] + '">' + districts[k] + '</option>');
                }
            }
        }
    }
}

/** 검색 실행 */
function searchList() {
    var selHq = $('#searchHq').val();
    var selBranch = $('#searchBranch').val();

    // 본부만 선택하고 사업소 미선택 시, 해당 본부의 모든 사업소를 branchNm 조건으로 전달
    var branchNm = '';
    if (selBranch) {
        branchNm = selBranch;
    }

    var params = {
        pageIndex: pageIndex,
        pageSize: pageSize,
        branchNm: branchNm,
        regionNm: $('#searchRegion').val(),
        districtNm: $('#searchDistrict').val(),
        riskCd: $('#searchGrade').val(),
        searchKeyword: $('#searchKeyword').val()
    };

    // 본부만 선택된 경우 (사업소 미선택) → 해당 본부 소속 사업소 목록 전달
    if (selHq && !selBranch && HQ_BRANCH_MAP[selHq]) {
        var branches = HQ_BRANCH_MAP[selHq];
        for (var i = 0; i < branches.length; i++) {
            params['branchNmList[' + i + ']'] = branches[i];
        }
    }

    RiskApp.callApi('selectCombinedList.do', params, function(res) {
        var totalCount = res.totalCount || 0;
        $('#totalCount').text(RiskApp.formatNumber(totalCount));

        // 순번 부여
        var list = res.data || [];
        var startNo = (pageIndex - 1) * pageSize + 1;
        for (var i = 0; i < list.length; i++) {
            list[i].rowNo = startNo + i;
            list[i].addr = normalizeJibunAddress(list[i].addr);
        }

        var columns = [
            { id: 'rowNo', title: 'No', width: 45 },
            { id: 'branchNm', title: '사업소', width: 90 },
            { id: 'regionNm', title: '지역', width: 50 },
            { id: 'districtNm', title: '구군', width: 60 },
            { id: 'a13', title: '용도지역지구', width: 120, align: 'left' },
            { id: 'addr', title: '주소', width: 180, align: 'left' },
            { id: 'totalScore', title: '기본점수', width: 55 },
            { id: 'riskCd', title: '정적등급', width: 50 },
            { id: 'weatherScore', title: '기상', width: 45 },
            { id: 'combinedScore', title: '종합점수', width: 55 },
            { id: 'combinedRiskCd', title: '종합등급', width: 50 }
        ];

        RiskApp.createGrid('sbGridBuilding', columns, list, {
            onRowClick: function(row) {
                if (row && row.bldgSeq) {
                    location.href = 'riskBuildingDetail.do?bldgSeq=' + row.bldgSeq;
                }
            }
        });

        // 페이징
        $('#pagingArea').html(RiskApp.renderPaging(totalCount, pageIndex, pageSize));
    });
}

function normalizeJibunAddress(addr) {
    if (!addr) {
        return addr;
    }
    var s = String(addr).trim().replace(/\s+/g, ' ');
    s = s.replace(/\s+\d+\s+(?:일반건축물|집합건축물)\s*$/, '');
    s = s.replace(/\s+\d+\s+\S+\s+([0-9]+(?:-[0-9]+)?)\s+[0-9]{1,4}\s*$/, ' $1');
    s = s.replace(/ ([0-9]+(?:-[0-9]+)?) [0-9]{4,}(?: \d+)?$/, ' $1');
    s = s.replace(/\s+\d+\s+\S+\s+([0-9]+(?:-[0-9]+)?)$/, ' $1');
    return s;
}
