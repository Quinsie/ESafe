/**
 * risk-common.js - 공통 유틸리티
 * SBGrid 초기화 헬퍼 + AJAX 공통 + 등급 포맷
 */
var RiskApp = {
    /** .do API 호출 공통 */
    callApi: function(url, params, callback, options) {
        options = options || {};
        var method = (options.method || 'GET').toUpperCase();
        var csrf = this.getCsrf();

        $.ajax({
            url: url,
            type: method,
            data: params || {},
            dataType: 'json',
            beforeSend: function(xhr) {
                if (method !== 'GET' && csrf.token) {
                    xhr.setRequestHeader(csrf.headerName || 'X-CSRF-TOKEN', csrf.token);
                }
            },
            success: function(res) {
                if (res.resultCode === 'OK') {
                    callback(res);
                } else {
                    var msg = res.resultMsg || res.message || '알 수 없는 오류';
                    if (options.onFail) {
                        options.onFail(res, msg);
                    } else {
                        alert('API 오류: ' + msg);
                    }
                }
            },
            error: function(xhr) {
                alert('통신 오류: ' + xhr.status);
            }
        });
    },

    getCsrf: function() {
        return {
            token: $('#_csrfToken').val() || '',
            headerName: $('#_csrfHeader').val() || 'X-CSRF-TOKEN'
        };
    },

    /** 등급 뱃지 HTML */
    gradeBadge: function(grade) {
        var names = { A: '안전', B: '관심', C: '경고', D: '위험', E: '심각' };
        return '<span class="badge-grade badge-' + grade + '">' + grade + ' ' + (names[grade] || '') + '</span>';
    },

    /** 숫자 포맷 (천단위 콤마) */
    formatNumber: function(num) {
        if (num == null) return '-';
        return Number(num).toLocaleString();
    },

    /** 페이징 HTML 생성 */
    renderPaging: function(totalCount, pageIndex, pageSize, callback) {
        var totalPages = Math.ceil(totalCount / pageSize);
        if (totalPages <= 1) return '';

        var html = '';
        var startPage = Math.max(1, pageIndex - 5);
        var endPage = Math.min(totalPages, startPage + 9);

        if (pageIndex > 1) {
            html += '<a data-page="1">&laquo;</a>';
            html += '<a data-page="' + (pageIndex - 1) + '">&lsaquo;</a>';
        }
        for (var i = startPage; i <= endPage; i++) {
            if (i === pageIndex) {
                html += '<span class="active">' + i + '</span>';
            } else {
                html += '<a data-page="' + i + '">' + i + '</a>';
            }
        }
        if (pageIndex < totalPages) {
            html += '<a data-page="' + (pageIndex + 1) + '">&rsaquo;</a>';
            html += '<a data-page="' + totalPages + '">&raquo;</a>';
        }
        return html;
    },

    /**
     * SBGrid 초기화 (SBGrid 라이브러리 로드 여부 확인)
     * SBGrid 미설치 시 HTML 테이블 폴백
     */
    isSBGridLoaded: function() {
        return (typeof SBGrid !== 'undefined');
    },

    /**
     * SBGrid 또는 폴백 테이블 렌더링
     * @param {string} targetId - div ID
     * @param {Array} columns - [{id, title, width, align}]
     * @param {Array} data - row data array
     * @param {Object} options - {onRowClick: fn}
     * @returns {Object|null} SBGrid 인스턴스 or null
     */
    createGrid: function(targetId, columns, data, options) {
        options = options || {};

        if (this.isSBGridLoaded()) {
            // SBGrid 사용
            var grid = new SBGrid(targetId);
            var colInfos = [];
            for (var i = 0; i < columns.length; i++) {
                colInfos.push({
                    id: columns[i].id,
                    title: columns[i].title,
                    width: columns[i].width || 100,
                    align: columns[i].align || 'center'
                });
            }
            grid.setColumnInfo(colInfos);
            grid.setData(data);
            if (options.onRowClick) {
                grid.setEventHandler('onCellClick', options.onRowClick);
            }
            grid.render();
            return grid;
        } else {
            // 폴백: HTML 테이블
            this.renderFallbackTable(targetId, columns, data, options);
            return null;
        }
    },

    /** HTML 폴백 테이블 렌더링 */
    renderFallbackTable: function(targetId, columns, data, options) {
        var html = '<table class="fallback-table"><thead><tr>';
        for (var c = 0; c < columns.length; c++) {
            html += '<th style="width:' + (columns[c].width || 100) + 'px">' + columns[c].title + '</th>';
        }
        html += '</tr></thead><tbody>';

        if (!data || data.length === 0) {
            html += '<tr><td colspan="' + columns.length + '" style="text-align:center;padding:20px;color:#999;">데이터 없음</td></tr>';
        } else {
            for (var r = 0; r < data.length; r++) {
                var row = data[r];
                var clickAttr = '';
                if (options && options.onRowClick) {
                    clickAttr = ' style="cursor:pointer" data-row-idx="' + r + '"';
                }
                html += '<tr' + clickAttr + '>';
                for (var c2 = 0; c2 < columns.length; c2++) {
                    var val = row[columns[c2].id];
                    var align = columns[c2].align || 'center';
                    // 등급 컬럼이면 뱃지
                    if (columns[c2].id === 'combinedRiskCd' || columns[c2].id === 'riskCd' || columns[c2].id === 'totalGrade') {
                        val = RiskApp.gradeBadge(val);
                    }
                    var wrap = (align === 'left') ? 'white-space:normal;word-break:break-all;' : '';
                    html += '<td style="text-align:' + align + ';' + wrap + '">' + (val != null ? val : '-') + '</td>';
                }
                html += '</tr>';
            }
        }
        html += '</tbody></table>';

        $('#' + targetId).html(html);

        // 행 클릭 이벤트
        if (options && options.onRowClick) {
            $('#' + targetId + ' tbody tr').on('click', function() {
                var idx = $(this).data('row-idx');
                if (idx !== undefined) {
                    options.onRowClick(data[idx], idx);
                }
            });
        }
    },

    /** 현재 시간 표시 */
    initClock: function() {
        var updateTime = function() {
            var now = new Date();
            var str = now.getFullYear() + '-' +
                String(now.getMonth() + 1).padStart(2, '0') + '-' +
                String(now.getDate()).padStart(2, '0') + ' ' +
                String(now.getHours()).padStart(2, '0') + ':' +
                String(now.getMinutes()).padStart(2, '0');
            $('#currentTime').text(str);
        };
        updateTime();
        setInterval(updateTime, 60000);
    }
};

// 페이지 로드 시 공통 초기화
$(function() {
    RiskApp.initClock();

    // 현재 페이지 사이드바 active 처리
    var path = location.pathname;
    $('.menu-item').each(function() {
        if (path.indexOf($(this).attr('href')) > -1) {
            $(this).addClass('active');
        }
    });
});
