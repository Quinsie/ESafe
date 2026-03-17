# -*- coding: utf-8 -*-
"""
전기안전 위험도 통합분석 시스템 - Streamlit UI
"""

import streamlit as st
import pandas as pd
import geopandas as gpd
from pathlib import Path
from datetime import datetime
import sys
import os

# 현재 경로를 시스템 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from building_multi_risk_analyzer import BuildingMultiRiskAnalyzer
from weather_risk_multiplier import WeatherRiskMultiplier

# 페이지 설정
st.set_page_config(
    page_title="전기안전 위험도 통합분석",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 기본 경로
BASE_PATH = Path(__file__).parent

# 세션 상태 초기화
if 'analyzer' not in st.session_state:
    st.session_state.analyzer = BuildingMultiRiskAnalyzer(str(BASE_PATH))
if 'weather_multiplier' not in st.session_state:
    st.session_state.weather_multiplier = WeatherRiskMultiplier(str(BASE_PATH))
if 'last_result' not in st.session_state:
    st.session_state.last_result = None


def get_headquarters_list():
    """본부 목록 반환"""
    return [
        '서울본부', '부산울산본부', '대구경북본부', '인천본부',
        '광주전남본부', '대전세종충남본부', '경기본부', '경기북부본부',
        '강원본부', '충북본부', '전북본부', '경남본부', '제주본부'
    ]


def get_branches_by_hq(hq_name: str) -> list:
    """본부별 사업소 목록 반환"""
    analyzer = st.session_state.analyzer
    branches = []
    for branch_name in analyzer.branch_mapping.keys():
        if analyzer.branch_to_hq.get(branch_name) == hq_name:
            branches.append(branch_name)
    return sorted(branches)


def get_region_list():
    """광역지자체 목록 반환"""
    return ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
            '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']


def find_result_files(base_path: Path) -> list:
    """분석 결과 파일 목록 조회"""
    results = []

    # 사업소별 분석결과
    branch_path = base_path / "사업소별 분석결과"
    if branch_path.exists():
        for shp in branch_path.rglob("*.shp"):
            stat = shp.stat()
            results.append({
                'path': shp,
                'name': shp.name,
                'folder': str(shp.parent.relative_to(base_path)),
                'date': datetime.fromtimestamp(stat.st_mtime),
                'size': stat.st_size
            })

    # 지역별 분석결과
    region_path = base_path / "지역별 분석결과"
    if region_path.exists():
        for shp in region_path.rglob("*.shp"):
            stat = shp.stat()
            results.append({
                'path': shp,
                'name': shp.name,
                'folder': str(shp.parent.relative_to(base_path)),
                'date': datetime.fromtimestamp(stat.st_mtime),
                'size': stat.st_size
            })

    # 분석결과 폴더
    result_path = base_path / "분석결과"
    if result_path.exists():
        for shp in result_path.rglob("*.shp"):
            stat = shp.stat()
            results.append({
                'path': shp,
                'name': shp.name,
                'folder': str(shp.parent.relative_to(base_path)),
                'date': datetime.fromtimestamp(stat.st_mtime),
                'size': stat.st_size
            })

    # 날짜 기준 정렬
    results.sort(key=lambda x: x['date'], reverse=True)
    return results


def load_weather_alerts():
    """기상특보 현황 로드"""
    multiplier = st.session_state.weather_multiplier
    weather_df = multiplier.load_weather_alerts()
    return weather_df


def display_individual_risk_analysis(gdf):
    """개별 위험요소 분석 결과 표시"""

    st.subheader("📋 개별 위험요소 분석")

    col1, col2 = st.columns(2)

    # 1. 노후위험도
    with col1:
        st.markdown("**1. 노후위험도**")
        if '노후등급' in gdf.columns:
            age_counts = gdf['노후등급'].value_counts()
            st.bar_chart(age_counts)
            avg_age = gdf['건물연령'].mean() if '건물연령' in gdf.columns else 0
            st.caption(f"평균 건물연령: {avg_age:.1f}년")

    # 2. 홍수위험도
    with col2:
        st.markdown("**2. 홍수위험도**")
        if '홍수등급' in gdf.columns:
            flood_counts = gdf['홍수등급'].value_counts()
            st.bar_chart(flood_counts)
            flood_buildings = len(gdf[gdf['겹침비율'] > 0]) if '겹침비율' in gdf.columns else 0
            st.caption(f"홍수위험지역 교차 건물: {flood_buildings:,}개")

    col3, col4 = st.columns(2)

    # 3. 산사태위험도
    with col3:
        st.markdown("**3. 산사태근접위험도**")
        if '산사태등급' in gdf.columns:
            landslide_counts = gdf['산사태등급'].value_counts()
            st.bar_chart(landslide_counts)
            if '산사태거리' in gdf.columns:
                valid = gdf[gdf['산사태거리'] < 99999]['산사태거리']
                if len(valid) > 0:
                    st.caption(f"평균 거리: {valid.mean():.1f}m / 최소: {valid.min():.1f}m")

    # 4. 용도지역지구 위험도
    with col4:
        st.markdown("**4. 용도지역지구 위험도**")
        if '용도점수' in gdf.columns and '용도코드' in gdf.columns:
            matched = (gdf['용도코드'] != '').sum()
            unmatched = len(gdf) - matched

            match_df = pd.DataFrame({
                '구분': ['매칭', '미매칭'],
                '건물수': [matched, unmatched]
            }).set_index('구분')
            st.bar_chart(match_df)

            if matched > 0:
                avg_score = gdf[gdf['용도코드'] != '']['용도점수'].mean()
                st.caption(f"평균 용도지역 점수: {avg_score:.2f}점")

    # 5. 전기화재이력 위험도
    st.markdown("**5. 전기화재이력 위험도**")
    if '전기화재' in gdf.columns:
        col5a, col5b, col5c = st.columns(3)

        fire_10m = (gdf['전기화재'] == 2).sum()
        fire_50m = (gdf['전기화재'] == 1).sum()
        fire_none = (gdf['전기화재'] == 0).sum()

        col5a.metric("10m 이내 (1.5배)", f"{fire_10m:,}개")
        col5b.metric("50m 이내 (1.2배)", f"{fire_50m:,}개")
        col5c.metric("범위 밖 (1.0배)", f"{fire_none:,}개")

        if '화재배수' in gdf.columns:
            avg_mult = gdf['화재배수'].mean()
            st.caption(f"평균 화재배수: {avg_mult:.3f}배")

    # 6. 기상특보 배수 (기상배수 적용된 경우)
    if '기상배수' in gdf.columns:
        st.markdown("**6. 기상특보 배수**")

        col6a, col6b, col6c = st.columns(3)

        weather_applied = (gdf['기상배수'] > 1.0).sum()
        weather_none = (gdf['기상배수'] == 1.0).sum()
        avg_weather = gdf['기상배수'].mean()

        col6a.metric("배수 적용 건물", f"{weather_applied:,}개")
        col6b.metric("미적용 건물", f"{weather_none:,}개")
        col6c.metric("평균 기상배수", f"{avg_weather:.2f}배")

        # 적용된 특보 목록
        if '적용특보' in gdf.columns:
            applied_alerts = gdf[gdf['적용특보'] != '']['적용특보'].value_counts()
            if len(applied_alerts) > 0:
                st.markdown("**적용된 기상특보:**")
                for alert, count in applied_alerts.head(5).items():
                    st.write(f"- {alert}: {count:,}개 건물")

        # 기상위험점수
        if '기상위험점수' in gdf.columns:
            col_ws1, col_ws2 = st.columns(2)
            with col_ws1:
                st.caption(f"평균 기상위험점수: {gdf['기상위험점수'].mean():.2f}점")
            with col_ws2:
                st.caption(f"최고 기상위험점수: {gdf['기상위험점수'].max():.1f}점")


def display_summary_analysis(gdf):
    """요소별 위험도 현황 및 최종 종합 분석 표시"""

    st.subheader("📊 요소별 위험도 현황")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**위험요소별 평균 점수**")
        scores = {}
        if '노후점수' in gdf.columns:
            scores['노후'] = gdf['노후점수'].mean()
        if '홍수점수' in gdf.columns:
            scores['홍수'] = gdf['홍수점수'].mean()
        if '산사태점수' in gdf.columns:
            scores['산사태'] = gdf['산사태점수'].mean()
        if '용도점수' in gdf.columns:
            scores['용도지역'] = gdf['용도점수'].mean()

        if scores:
            score_df = pd.DataFrame({
                '위험요소': list(scores.keys()),
                '평균점수': list(scores.values())
            }).set_index('위험요소')
            st.bar_chart(score_df)

    with col2:
        st.markdown("**위험요소별 고위험 건물 수**")
        high_risk = {}
        if '노후점수' in gdf.columns:
            high_risk['노후(5+)'] = (gdf['노후점수'] >= 5).sum()
        if '홍수점수' in gdf.columns:
            high_risk['홍수(3+)'] = (gdf['홍수점수'] >= 3).sum()
        if '산사태점수' in gdf.columns:
            high_risk['산사태(3+)'] = (gdf['산사태점수'] >= 3).sum()
        if '용도점수' in gdf.columns:
            high_risk['용도지역(3+)'] = (gdf['용도점수'] >= 3).sum()

        if high_risk:
            risk_df = pd.DataFrame({
                '위험요소': list(high_risk.keys()),
                '건물수': list(high_risk.values())
            }).set_index('위험요소')
            st.bar_chart(risk_df)

    # 최종 종합 위험도 분석
    st.subheader("🎯 최종 종합 위험도 분석")
    st.caption("(노후+홍수+산사태+용도지역) × 전기화재배수")

    if '종합등급' in gdf.columns:
        col_g1, col_g2 = st.columns([2, 1])

        with col_g1:
            grade_counts = gdf['종합등급'].value_counts()
            st.bar_chart(grade_counts)

        with col_g2:
            st.markdown("**등급별 건물 수**")
            for grade in ['안전', '관심', '주의', '경고', '위험']:
                if grade in grade_counts.index:
                    count = grade_counts[grade]
                    pct = 100 * count / len(gdf)
                    st.write(f"{grade}: {count:,}개 ({pct:.1f}%)")

    # 고위험 건물 상세
    if '위험코드' in gdf.columns:
        d_count = (gdf['위험코드'] == 'D').sum()
        e_count = (gdf['위험코드'] == 'E').sum()

        col_de1, col_de2, col_de3 = st.columns(3)
        col_de1.metric("D등급 (경고)", f"{d_count:,}개", f"{100*d_count/len(gdf):.1f}%")
        col_de2.metric("E등급 (위험)", f"{e_count:,}개", f"{100*e_count/len(gdf):.1f}%")
        col_de3.metric("D+E 합계", f"{d_count+e_count:,}개", f"{100*(d_count+e_count)/len(gdf):.1f}%")

    # 점수 비교
    if '기본점수' in gdf.columns and '종합점수' in gdf.columns:
        st.markdown("**점수 비교**")
        col_sc1, col_sc2, col_sc3 = st.columns(3)
        col_sc1.metric("평균 기본점수", f"{gdf['기본점수'].mean():.2f}점")
        col_sc2.metric("평균 종합점수", f"{gdf['종합점수'].mean():.2f}점")
        col_sc3.metric("최고 종합점수", f"{gdf['종합점수'].max():.1f}점")

    # 기상위험점수 비교 (기상배수 적용된 경우)
    if '기상위험점수' in gdf.columns and '종합점수' in gdf.columns:
        st.markdown("**기상특보 적용 점수 비교**")
        col_ws1, col_ws2, col_ws3 = st.columns(3)
        col_ws1.metric("평균 종합점수", f"{gdf['종합점수'].mean():.2f}점")
        col_ws2.metric("평균 기상위험점수", f"{gdf['기상위험점수'].mean():.2f}점")

        # 증가율 계산
        if gdf['종합점수'].mean() > 0:
            increase_rate = (gdf['기상위험점수'].mean() / gdf['종합점수'].mean() - 1) * 100
            col_ws3.metric("위험도 증가율", f"{increase_rate:.1f}%")


# ============================================================================
# 사이드바
# ============================================================================
with st.sidebar:
    st.title("🏢 전기안전 위험도 분석")
    st.markdown("---")

    menu = st.radio(
        "메뉴 선택",
        ["🔍 건물위험분석", "🌧️ 기상특보 배수", "📊 결과조회"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.caption(f"📁 {BASE_PATH.name}")
    st.caption(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# ============================================================================
# 메인 컨텐츠
# ============================================================================

# -----------------------------------------------------------------------------
# 탭 1: 건물위험분석
# -----------------------------------------------------------------------------
if menu == "🔍 건물위험분석":
    st.header("🔍 건물 통합 위험분석")
    st.markdown("**(노후+홍수+산사태+용도지역) × 전기화재배수**")
    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📍 분석 대상 선택")

        search_type = st.radio(
            "검색 유형",
            ["사업소", "광역지자체"],
            horizontal=True
        )

        if search_type == "사업소":
            hq = st.selectbox("본부 선택", get_headquarters_list())
            branches = get_branches_by_hq(hq)

            if branches:
                branch_options = ["전체 (본부 전체)"] + branches
                selected_branch = st.selectbox("사업소 선택", branch_options)

                if selected_branch == "전체 (본부 전체)":
                    search_query = hq
                else:
                    search_query = selected_branch
            else:
                st.warning(f"{hq}에 등록된 사업소가 없습니다.")
                search_query = hq
        else:
            region = st.selectbox("광역지자체 선택", get_region_list())
            search_query = region

    with col2:
        st.subheader("⚙️ 분석 조건")

        col2a, col2b = st.columns(2)
        with col2a:
            min_age = st.number_input("최소 건물연령", min_value=0, max_value=100, value=0)
        with col2b:
            max_age = st.number_input("최대 건물연령", min_value=0, max_value=200, value=100)

        st.markdown("**분석 항목**")
        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            include_flood = st.checkbox("홍수위험", value=True)
            include_landuse = st.checkbox("용도지역", value=True)
        with col_opt2:
            include_landslide = st.checkbox("산사태위험", value=True)
            include_fire = st.checkbox("전기화재이력", value=True)

    st.markdown("---")

    # 분석 실행 버튼
    if st.button("🔍 분석 시작", type="primary", use_container_width=True):

        with st.spinner(f"'{search_query}' 분석 중..."):
            try:
                analyzer = st.session_state.analyzer

                # 사업소명인 경우 해당 지역 정보 추출
                if search_type == "사업소":
                    branch_info = analyzer.get_branch_info(search_query)
                    if branch_info:
                        districts_by_region = branch_info
                    else:
                        st.error(f"'{search_query}' 사업소 정보를 찾을 수 없습니다.")
                        st.stop()
                else:
                    # 광역지자체
                    districts_by_region = {search_query: None}

                # 분석 실행
                all_results = []
                progress_bar = st.progress(0)
                status_text = st.empty()

                total_regions = len(districts_by_region)
                region_idx = 0

                for region, districts in districts_by_region.items():
                    if districts is None:
                        status_text.text(f"분석 중: {region} 전체...")
                        result = analyzer.analyze_region(
                            region, None,
                            min_age if min_age > 0 else None,
                            max_age if max_age < 100 else None,
                            include_flood, include_landslide
                        )
                        if result is not None and len(result) > 0:
                            all_results.append(result)
                    else:
                        for district in districts:
                            status_text.text(f"분석 중: {region} {district}...")
                            result = analyzer.analyze_region(
                                region, district,
                                min_age if min_age > 0 else None,
                                max_age if max_age < 100 else None,
                                include_flood, include_landslide
                            )
                            if result is not None and len(result) > 0:
                                all_results.append(result)

                    region_idx += 1
                    progress_bar.progress(region_idx / total_regions)

                if all_results:
                    # 결과 병합
                    combined_gdf = gpd.GeoDataFrame(
                        pd.concat(all_results, ignore_index=True),
                        crs=all_results[0].crs
                    )

                    # 저장
                    output_path = analyzer.save_results(
                        combined_gdf,
                        region_name=search_query,
                        min_age=min_age if min_age > 0 else None,
                        search_query=search_query
                    )

                    status_text.empty()
                    progress_bar.empty()

                    st.success(f"분석 완료: {len(combined_gdf):,}개 건물")
                    st.info(f"📁 저장 위치: {output_path}")

                    # 세션에 결과 저장
                    st.session_state.last_result = combined_gdf

                    # 기본 요약
                    st.subheader("📈 분석 결과 요약")
                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                    col_s1.metric("총 건물 수", f"{len(combined_gdf):,}개")
                    col_s2.metric("평균 건물연령", f"{combined_gdf['건물연령'].mean():.1f}년")
                    col_s3.metric("평균 종합점수", f"{combined_gdf['종합점수'].mean():.2f}점")

                    high_risk = len(combined_gdf[combined_gdf['위험코드'].isin(['D', 'E'])])
                    col_s4.metric("고위험 (D+E)", f"{high_risk:,}개")

                    st.markdown("---")

                    # 개별 위험요소 분석
                    display_individual_risk_analysis(combined_gdf)

                    st.markdown("---")

                    # 요소별 현황 및 최종 종합 분석
                    display_summary_analysis(combined_gdf)

                else:
                    st.warning("분석 결과가 없습니다.")

            except Exception as e:
                st.error(f"분석 중 오류 발생: {e}")
                import traceback
                st.code(traceback.format_exc())


# -----------------------------------------------------------------------------
# 탭 2: 기상특보 배수
# -----------------------------------------------------------------------------
elif menu == "🌧️ 기상특보 배수":
    st.header("🌧️ 기상특보 기반 위험도 배수 적용")
    st.markdown("---")

    # 현재 기상특보 현황
    st.subheader("📡 현재 기상특보 현황")

    col_w1, col_w2 = st.columns([3, 1])

    with col_w2:
        if st.button("🔄 새로고침"):
            st.rerun()

    weather_df = load_weather_alerts()

    if weather_df.empty:
        st.warning("기상특보 데이터가 없습니다.")
        st.info("'기상특보' 폴더에 '기상특보현황_YYYYMMDD.csv' 파일을 추가해주세요.")
    else:
        st.success(f"기상특보 {len(weather_df)}건 로드됨")

        # 특보 현황 표시
        display_cols = ['특보종류', '특보수준', '특보구역명']
        available_cols = [c for c in display_cols if c in weather_df.columns]
        if available_cols:
            st.dataframe(weather_df[available_cols], use_container_width=True, height=200)

    st.markdown("---")

    # 배수 적용 대상 선택
    st.subheader("📁 배수 적용 대상")

    result_files = find_result_files(BASE_PATH)

    if not result_files:
        st.warning("분석 결과 파일이 없습니다. 먼저 '건물위험분석'을 실행해주세요.")
    else:
        # 파일 선택
        file_options = [f"{r['name']} ({r['folder']})" for r in result_files[:20]]
        selected_file_idx = st.selectbox(
            "분석 결과 파일 선택",
            range(len(file_options)),
            format_func=lambda x: file_options[x]
        )

        selected_file = result_files[selected_file_idx]

        col_info1, col_info2 = st.columns(2)
        with col_info1:
            st.caption(f"📅 생성일: {selected_file['date'].strftime('%Y-%m-%d %H:%M')}")
        with col_info2:
            st.caption(f"📦 크기: {selected_file['size'] / 1024:.1f} KB")

        st.markdown("---")

        # 배수 적용 버튼
        if st.button("⚡ 기상특보 배수 적용", type="primary", use_container_width=True):
            if weather_df.empty:
                st.error("기상특보 데이터가 없어 배수를 적용할 수 없습니다.")
            else:
                with st.spinner("배수 적용 중..."):
                    try:
                        multiplier = st.session_state.weather_multiplier

                        # 데이터 로드
                        try:
                            gdf = gpd.read_file(selected_file['path'], encoding='cp949')
                        except:
                            gdf = gpd.read_file(selected_file['path'], encoding='utf-8')

                        # 배수 적용
                        result_gdf = multiplier.apply_weather_multiplier(gdf, weather_df)

                        # 저장
                        output_name = selected_file['path'].stem + "_기상배수.shp"
                        output_path = selected_file['path'].parent / output_name
                        multiplier.save_results(result_gdf, output_path)

                        st.success("배수 적용 완료!")
                        st.info(f"📁 저장 위치: {output_path}")

                        # 결과 요약
                        st.subheader("📊 배수 적용 결과")

                        col_r1, col_r2, col_r3 = st.columns(3)
                        col_r1.metric("총 건물 수", f"{len(result_gdf):,}개")

                        applied_count = (result_gdf['기상배수'] > 1.0).sum()
                        col_r2.metric("배수 적용 건물", f"{applied_count:,}개")

                        avg_mult = result_gdf['기상배수'].mean()
                        col_r3.metric("평균 배수", f"{avg_mult:.2f}배")

                        # 적용된 특보 목록
                        if '적용특보' in result_gdf.columns:
                            applied_alerts = result_gdf[result_gdf['적용특보'] != '']['적용특보'].unique()
                            if len(applied_alerts) > 0:
                                st.markdown("**적용된 기상특보:**")
                                for alert in applied_alerts:
                                    st.write(f"- {alert}")

                    except Exception as e:
                        st.error(f"배수 적용 중 오류: {e}")
                        import traceback
                        st.code(traceback.format_exc())

    # 배수표 안내
    with st.expander("📋 기상특보 배수표"):
        multiplier_data = {
            '특보종류': ['호우', '태풍', '강풍', '한파', '폭염', '건조', '대설', '폭풍해일'],
            '예비': [1.5, 1.5, 1.2, 1.2, 1.2, 1.2, 1.0, 1.0],
            '주의': [1.5, 1.5, 1.2, 1.2, 1.2, 1.2, 1.0, 1.0],
            '경보': [2.0, 2.0, 1.8, 1.8, 1.8, 1.8, 1.5, 1.5]
        }
        st.caption("※ 예비 = 주의와 동일한 배율 적용")
        st.dataframe(pd.DataFrame(multiplier_data), use_container_width=True)


# -----------------------------------------------------------------------------
# 탭 3: 결과조회
# -----------------------------------------------------------------------------
elif menu == "📊 결과조회":
    st.header("📊 분석 결과 조회")
    st.markdown("---")

    result_files = find_result_files(BASE_PATH)

    if not result_files:
        st.warning("분석 결과 파일이 없습니다.")
    else:
        st.success(f"총 {len(result_files)}개 파일 발견")

        # 파일 목록 표시
        file_df = pd.DataFrame([
            {
                '파일명': r['name'],
                '폴더': r['folder'],
                '생성일': r['date'].strftime('%Y-%m-%d %H:%M'),
                '크기(KB)': f"{r['size']/1024:.1f}"
            }
            for r in result_files[:50]
        ])

        st.dataframe(file_df, use_container_width=True, height=250)

        st.markdown("---")

        # 파일 선택 및 상세 보기
        st.subheader("📄 상세 보기")

        file_options = [f"{r['name']}" for r in result_files[:20]]
        selected_idx = st.selectbox("파일 선택", range(len(file_options)), format_func=lambda x: file_options[x])

        selected = result_files[selected_idx]

        col_act1, col_act2, col_act3 = st.columns(3)

        with col_act1:
            view_stats = st.button("📊 통계 보기", use_container_width=True)

        with col_act2:
            view_detail = st.button("📋 상세 분석", use_container_width=True)

        with col_act3:
            download_csv = st.button("📥 CSV 다운로드", use_container_width=True)

        # 통계 보기
        if view_stats:
            try:
                try:
                    gdf = gpd.read_file(selected['path'], encoding='cp949')
                except:
                    gdf = gpd.read_file(selected['path'], encoding='utf-8')

                st.markdown("---")
                st.markdown("### 기본 통계")

                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                col_s1.metric("건물 수", f"{len(gdf):,}개")

                if '건물연령' in gdf.columns:
                    col_s2.metric("평균 연령", f"{gdf['건물연령'].mean():.1f}년")

                if '종합점수' in gdf.columns:
                    col_s3.metric("평균 종합점수", f"{gdf['종합점수'].mean():.2f}점")

                if '위험코드' in gdf.columns:
                    high = (gdf['위험코드'].isin(['D', 'E'])).sum()
                    col_s4.metric("고위험 (D+E)", f"{high:,}개")

                # 등급 분포
                if '종합등급' in gdf.columns:
                    st.markdown("**종합등급 분포**")
                    grade_counts = gdf['종합등급'].value_counts()
                    st.bar_chart(grade_counts)

            except Exception as e:
                st.error(f"파일 로드 오류: {e}")

        # 상세 분석
        if view_detail:
            try:
                try:
                    gdf = gpd.read_file(selected['path'], encoding='cp949')
                except:
                    gdf = gpd.read_file(selected['path'], encoding='utf-8')

                st.markdown("---")

                # 개별 위험요소 분석
                display_individual_risk_analysis(gdf)

                st.markdown("---")

                # 요소별 현황 및 최종 종합 분석
                display_summary_analysis(gdf)

            except Exception as e:
                st.error(f"파일 로드 오류: {e}")

        # CSV 다운로드
        if download_csv:
            try:
                try:
                    gdf = gpd.read_file(selected['path'], encoding='cp949')
                except:
                    gdf = gpd.read_file(selected['path'], encoding='utf-8')

                cols = [c for c in gdf.columns if c != 'geometry']
                csv_data = gdf[cols].to_csv(index=False, encoding='utf-8-sig')

                st.download_button(
                    label="💾 CSV 파일 다운로드",
                    data=csv_data,
                    file_name=selected['path'].stem + ".csv",
                    mime="text/csv",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"CSV 변환 오류: {e}")

        # 컬럼 목록
        with st.expander("📋 컬럼 목록 보기"):
            try:
                try:
                    gdf = gpd.read_file(selected['path'], encoding='cp949')
                except:
                    gdf = gpd.read_file(selected['path'], encoding='utf-8')

                st.write(", ".join([c for c in gdf.columns if c != 'geometry']))
            except:
                st.error("파일을 읽을 수 없습니다.")


# ============================================================================
# 푸터
# ============================================================================
st.markdown("---")
st.caption("전기안전 위험도 통합분석 시스템 v1.0 | Powered by Streamlit")
