# -*- coding: utf-8 -*-
"""
기상청 API - 당일 기상특보 현황 CSV 저장
실행: PYTHONIOENCODING=utf-8 /c/Users/user/AppData/Local/Programs/Python/Python313/python.exe -X utf8 "save_weather_warnings_csv.py"
"""

import sys
import io
import os
import csv
from datetime import datetime, timedelta

# Windows 환경 UTF-8 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WRN_TYPE_MAP = {
    'T': '태풍', 'H': '호우', 'V': '풍랑', 'S': '대설', 'D': '건조',
    'W': '강풍', 'C': '한파', 'O': '폭염', 'Y': '황사', 'F': '안개'
}
LVL_MAP = {'1': '예비', '2': '주의', '3': '경보'}
CMD_MAP = {'1': '발표', '2': '대치', '3': '해제', '4': '대치해제', '5': '연장', '6': '변경', '7': '변경해제'}
ACTIVE_CMDS = {'1', '2', '5', '6'}
DEFAULT_KMA_AUTH_KEY = "FtRxuKuhQneUcbirodJ3ng"


def load_zone_mappings() -> dict:
    """특보구역 코드 -> (이름/광역) 매핑 로드 (로컬 파일 전용)"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = []

    env_path = os.getenv("RISK_ALERT_ZONE_FILE", "").strip()
    if env_path:
        candidates.append(env_path)

    # 로컬 단독 실행용 기본 파일명
    candidates.append(os.path.join(base_dir, '기상특보구역표.csv'))
    candidates.append(os.path.join(base_dir, 'alert-zones.csv'))

    for path in candidates:
        norm = os.path.normpath(path)
        if not os.path.exists(norm):
            continue

        for enc in ('utf-8-sig', 'cp949'):
            try:
                mapping = {}
                with open(norm, 'r', encoding=enc) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        code = (
                            row.get('특보구역코드')
                            or row.get('ZONE_CD')
                            or row.get('zone_cd')
                            or row.get('코드')
                            or ''
                        ).strip().upper()
                        if not code:
                            continue

                        name = (
                            row.get('특보구역이름')
                            or row.get('ZONE_NM')
                            or row.get('zone_nm')
                            or row.get('특보구역명')
                            or row.get('구역명')
                            or ''
                        ).strip()
                        region = (
                            row.get('광역행정구역')
                            or row.get('PARENT_REGION')
                            or row.get('parent_region')
                            or row.get('상위구역명')
                            or row.get('광역')
                            or ''
                        ).strip()

                        mapping[code] = {'name': name, 'region': region}
                print(f"특보구역 매핑 로드: {norm} ({len(mapping)}건, {enc})")
                return mapping
            except UnicodeDecodeError:
                continue

        print(f"경고: 매핑 파일 인코딩을 읽을 수 없습니다: {norm}")

    print("경고: 기상특보구역표.csv(또는 alert-zones.csv)를 찾지 못했습니다. 구역코드만 사용합니다.")
    return {}


def get_current_warnings(auth_key: str) -> list:
    """wrn_met_data 이력에서 현재 발효중인 특보를 계산"""
    now = datetime.now()
    tmfc2 = now.strftime('%Y%m%d%H%M')
    tmfc1 = (now - timedelta(days=120)).strftime('%Y%m%d%H%M')

    url = 'https://apihub-pub.kma.go.kr/api/typ01/url/wrn_met_data.php'
    params = {
        'reg': 0,
        'wrn': 'A',
        'tmfc1': tmfc1,
        'tmfc2': tmfc2,
        'disp': 0,
        'help': 0,
        'authKey': auth_key
    }

    try:
        response = requests.get(url, params=params, timeout=30, verify=False)
        if response.status_code != 200:
            print(f"API 오류: HTTP {response.status_code}")
            return []
        response.encoding = 'euc-kr'

        zone_map = load_zone_mappings()
        latest_by_key = {}

        lines = response.text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('#') or not line:
                continue

            fields = [f.strip().rstrip('=') for f in line.split(',')]
            if len(fields) < 11:
                continue

            tm_fc = fields[0]
            tm_ef = fields[1]
            tm_in = fields[2]
            reg_id = fields[4]
            wrn_code = fields[5]
            lvl_code = fields[6]
            cmd_code = fields[7]
            cnt = fields[9]

            if not reg_id or not wrn_code:
                continue
            if cnt and cnt != '4':
                continue

            key = (reg_id, wrn_code)
            candidate = {
                'tm_fc': tm_fc,
                'tm_ef': tm_ef,
                'tm_in': tm_in,
                'reg_id': reg_id,
                'wrn_code': wrn_code,
                'lvl_code': lvl_code,
                'cmd_code': cmd_code
            }
            current = latest_by_key.get(key)
            if current is None:
                latest_by_key[key] = candidate
                continue

            current_key = (current.get('tm_in', ''), current.get('tm_fc', ''), current.get('tm_ef', ''))
            candidate_key = (tm_in, tm_fc, tm_ef)
            if candidate_key > current_key:
                latest_by_key[key] = candidate

        results = []
        for item in latest_by_key.values():
            cmd_code = item['cmd_code']
            if cmd_code not in ACTIVE_CMDS:
                continue

            reg_id = item['reg_id']
            zone = zone_map.get((reg_id or '').strip().upper(), {})
            record = {
                '상위구역코드': '',
                '상위구역명': zone.get('region', ''),
                '특보구역코드': reg_id,
                '특보구역명': zone.get('name', reg_id),
                '발표시각': item['tm_fc'],
                '발효시각': item['tm_ef'],
                '특보종류': WRN_TYPE_MAP.get(item['wrn_code'], item['wrn_code']),
                '특보수준': LVL_MAP.get(item['lvl_code'], item['lvl_code']),
                '특보명령': CMD_MAP.get(item['cmd_code'], item['cmd_code']),
                '해제예고': ''
            }
            results.append(record)

        return results
    except Exception as e:
        print(f"API 요청 오류: {e}")
        return []


def save_to_csv(data: list, filepath: str):
    """특보 데이터를 CSV로 저장"""
    if not data:
        print("저장할 데이터가 없습니다.")
        return False

    fieldnames = ['특보종류', '특보수준', '특보명령', '특보구역명', '특보구역코드',
                  '상위구역명', '발표시각', '발효시각', '해제예고']

    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()

        # 특보종류, 특보수준 순으로 정렬
        sorted_data = sorted(data, key=lambda x: (x['특보종류'], x['특보수준'], x['특보구역명']))
        writer.writerows(sorted_data)

    return True


def save_summary_csv(data: list, filepath: str):
    """특보 요약 정보를 CSV로 저장"""
    if not data:
        return False

    # 집계
    type_level_count = {}
    region_warnings = {}

    for record in data:
        wrn_type = record['특보종류']
        wrn_level = record['특보수준']
        region = record['특보구역명']

        if wrn_type not in type_level_count:
            type_level_count[wrn_type] = {'경보': 0, '주의': 0, '예비': 0}
        if wrn_level in type_level_count[wrn_type]:
            type_level_count[wrn_type][wrn_level] += 1

        if region not in region_warnings:
            region_warnings[region] = []
        region_warnings[region].append(f"{wrn_type} {wrn_level}")

    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)

        # 1. 헤더
        writer.writerow([f"기상특보 종합현황 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"])
        writer.writerow([])

        # 2. 전체 현황 요약
        writer.writerow(['[전체 현황 요약]'])
        writer.writerow(['특보종류', '경보', '주의', '예비', '합계'])

        type_order = ['한파', '대설', '강풍', '풍랑', '건조', '호우', '폭염', '태풍', '황사', '안개']
        total = {'경보': 0, '주의': 0, '예비': 0}

        for wrn_type in type_order:
            if wrn_type in type_level_count:
                counts = type_level_count[wrn_type]
                row_total = sum(counts.values())
                if row_total > 0:
                    writer.writerow([wrn_type, counts['경보'], counts['주의'], counts['예비'], row_total])
                    for lvl in ['경보', '주의', '예비']:
                        total[lvl] += counts[lvl]

        # 기타 특보
        for wrn_type in type_level_count:
            if wrn_type not in type_order:
                counts = type_level_count[wrn_type]
                row_total = sum(counts.values())
                if row_total > 0:
                    writer.writerow([wrn_type, counts['경보'], counts['주의'], counts['예비'], row_total])
                    for lvl in ['경보', '주의', '예비']:
                        total[lvl] += counts[lvl]

        writer.writerow(['합계', total['경보'], total['주의'], total['예비'], sum(total.values())])
        writer.writerow([])

        # 3. 경보 발효 지역
        warnings_only = [r for r in data if r['특보수준'] == '경보']
        if warnings_only:
            writer.writerow(['[경보 발효 지역]'])
            writer.writerow(['특보종류', '지역수', '지역목록'])

            summary = {}
            for r in warnings_only:
                key = r['특보종류']
                if key not in summary:
                    summary[key] = []
                summary[key].append(r['특보구역명'])

            for wrn_type in type_order + [t for t in summary if t not in type_order]:
                if wrn_type in summary:
                    regions = summary[wrn_type]
                    writer.writerow([f"{wrn_type} 경보", len(regions), ', '.join(regions)])
            writer.writerow([])

        # 4. 복수 특보 발효 지역
        multi = {k: v for k, v in region_warnings.items() if len(v) >= 2}
        if multi:
            writer.writerow(['[복수 특보 발효 지역]'])
            writer.writerow(['지역명', '특보수', '특보목록'])
            sorted_multi = sorted(multi.items(), key=lambda x: -len(x[1]))
            for region, warnings in sorted_multi:
                writer.writerow([region, len(warnings), ', '.join(warnings)])
            writer.writerow([])

        # 5. 최종 요약
        active_types = [t for t in type_order if t in type_level_count] + \
                       [t for t in type_level_count if t not in type_order]
        writer.writerow(['[최종 요약]'])
        writer.writerow([f"총 {len(data)}건 특보 발효중"])
        writer.writerow([f"경보 {total['경보']}건 / 주의 {total['주의']}건 / 예비 {total['예비']}건"])
        writer.writerow([f"발효 특보: {', '.join(active_types)}"])

    return True


def print_summary(data: list):
    """특보 현황 요약 출력"""
    if not data:
        print("\n" + "=" * 70)
        print("  현재 발효중인 기상특보가 없습니다.")
        print("=" * 70)
        return

    # 특보종류별, 수준별 집계
    summary = {}
    type_level_count = {}
    region_warnings = {}  # 지역별 특보 개수

    for record in data:
        wrn_type = record['특보종류']
        wrn_level = record['특보수준']
        region = record['특보구역명']
        key = f"{wrn_type} {wrn_level}"

        if key not in summary:
            summary[key] = []
        summary[key].append(region)

        # 종류-수준별 카운트
        if wrn_type not in type_level_count:
            type_level_count[wrn_type] = {'경보': 0, '주의': 0, '예비': 0}
        if wrn_level in type_level_count[wrn_type]:
            type_level_count[wrn_type][wrn_level] += 1

        # 지역별 특보 개수
        if region not in region_warnings:
            region_warnings[region] = []
        region_warnings[region].append(f"{wrn_type}{wrn_level[0]}")

    type_order = ['한파', '대설', '강풍', '풍랑', '건조', '호우', '폭염', '태풍', '황사', '안개']
    level_order = ['경보', '주의', '예비']

    # =========================================================================
    # 1. 헤더
    # =========================================================================
    print("\n" + "=" * 70)
    print(f"            기상특보 종합현황 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print("=" * 70)

    # =========================================================================
    # 2. 전체 요약 표
    # =========================================================================
    print("\n[전체 현황 요약]")
    print("-" * 50)
    print(f"  {'특보종류':^8} | {'경보':^6} | {'주의':^6} | {'예비':^6} | {'합계':^6}")
    print("-" * 50)

    total_by_level = {'경보': 0, '주의': 0, '예비': 0}
    active_types = []

    for wrn_type in type_order:
        if wrn_type in type_level_count:
            counts = type_level_count[wrn_type]
            row_total = sum(counts.values())
            if row_total > 0:
                active_types.append(wrn_type)
                경보 = counts['경보'] if counts['경보'] > 0 else '-'
                주의 = counts['주의'] if counts['주의'] > 0 else '-'
                예비 = counts['예비'] if counts['예비'] > 0 else '-'
                print(f"  {wrn_type:^8} | {경보:^6} | {주의:^6} | {예비:^6} | {row_total:^6}")
                for lvl in level_order:
                    total_by_level[lvl] += counts[lvl]

    # 기타 특보
    for wrn_type in type_level_count:
        if wrn_type not in type_order:
            counts = type_level_count[wrn_type]
            row_total = sum(counts.values())
            if row_total > 0:
                active_types.append(wrn_type)
                경보 = counts['경보'] if counts['경보'] > 0 else '-'
                주의 = counts['주의'] if counts['주의'] > 0 else '-'
                예비 = counts['예비'] if counts['예비'] > 0 else '-'
                print(f"  {wrn_type:^8} | {경보:^6} | {주의:^6} | {예비:^6} | {row_total:^6}")
                for lvl in level_order:
                    total_by_level[lvl] += counts[lvl]

    print("-" * 50)
    grand_total = sum(total_by_level.values())
    print(f"  {'합계':^8} | {total_by_level['경보']:^6} | {total_by_level['주의']:^6} | {total_by_level['예비']:^6} | {grand_total:^6}")
    print("-" * 50)

    # =========================================================================
    # 3. 경보 발효 지역 (위험도 높음)
    # =========================================================================
    warnings_only = [r for r in data if r['특보수준'] == '경보']
    if warnings_only:
        print("\n[경보 발효 지역] ★ 주의 필요")
        print("-" * 70)

        for wrn_type in type_order + [t for t in type_level_count if t not in type_order]:
            key = f"{wrn_type} 경보"
            if key in summary:
                regions = summary[key]
                print(f"  ● {wrn_type} 경보 ({len(regions)}개): ", end="")
                if len(regions) <= 8:
                    print(", ".join(regions))
                else:
                    print(", ".join(regions[:8]) + f" 외 {len(regions)-8}개")

    # =========================================================================
    # 4. 복수 특보 발효 지역
    # =========================================================================
    multi_warning_regions = {k: v for k, v in region_warnings.items() if len(v) >= 2}
    if multi_warning_regions:
        print("\n[복수 특보 발효 지역]")
        print("-" * 70)
        # 특보 개수 순으로 정렬
        sorted_regions = sorted(multi_warning_regions.items(), key=lambda x: -len(x[1]))
        for region, warnings in sorted_regions[:15]:  # 상위 15개
            print(f"  ● {region}: {', '.join(warnings)}")
        if len(sorted_regions) > 15:
            print(f"  ... 외 {len(sorted_regions)-15}개 지역")

    # =========================================================================
    # 5. 특보별 상세 (주의보 포함)
    # =========================================================================
    print("\n[특보별 상세 현황]")
    print("-" * 70)

    for wrn_type in type_order:
        for wrn_level in level_order:
            key = f"{wrn_type} {wrn_level}"
            if key in summary:
                regions = summary[key]
                level_mark = "★" if wrn_level == "경보" else "●" if wrn_level == "주의" else "○"
                print(f"\n{level_mark} {key} - {len(regions)}개 지역")
                # 6개씩 출력
                for i in range(0, len(regions), 6):
                    chunk = regions[i:i+6]
                    print("    " + ", ".join(chunk))

    # 기타 특보
    for key in sorted(summary.keys()):
        wrn_type = key.split()[0]
        if wrn_type not in type_order:
            regions = summary[key]
            wrn_level = key.split()[1] if len(key.split()) > 1 else ""
            level_mark = "★" if wrn_level == "경보" else "●" if wrn_level == "주의" else "○"
            print(f"\n{level_mark} {key} - {len(regions)}개 지역")
            for i in range(0, len(regions), 6):
                chunk = regions[i:i+6]
                print("    " + ", ".join(chunk))

    # =========================================================================
    # 6. 최종 요약
    # =========================================================================
    print("\n" + "=" * 70)
    print(f"  총 {len(data)}건 특보 발효중 | 경보 {total_by_level['경보']}건 | 주의 {total_by_level['주의']}건 | 예비 {total_by_level['예비']}건")
    print(f"  발효 특보: {', '.join(active_types)}")
    print("=" * 70)


def main():
    # API 인증키 (환경변수 필수)
    auth_key = os.getenv("KMA_AUTH_KEY", DEFAULT_KMA_AUTH_KEY).strip()
    if not auth_key:
        print("환경변수 KMA_AUTH_KEY가 설정되지 않았습니다.")
        return 1

    # 저장 경로
    today = datetime.now().strftime('%Y%m%d')
    output_dir = os.path.dirname(os.path.abspath(__file__))
    detail_file = os.path.join(output_dir, f"기상특보현황_{today}.csv")
    summary_file = os.path.join(output_dir, f"기상특보요약_{today}.csv")

    print("기상특보 현황을 조회합니다...")

    # 현재 특보 조회
    warnings = get_current_warnings(auth_key)

    if warnings:
        # 요약 출력
        print_summary(warnings)

        # CSV 저장 (상세)
        if save_to_csv(warnings, detail_file):
            print(f"\n상세 저장: {detail_file}")

        # CSV 저장 (요약)
        if save_summary_csv(warnings, summary_file):
            print(f"요약 저장: {summary_file}")
    else:
        print("특보 데이터를 가져오지 못했습니다.")
    return 0


if __name__ == "__main__":
    code = main()
    print()
    if not (sys.stdin and sys.stdin.isatty()):
        sys.exit(code)
    if code == 0:
        try:
            input("Enter 키를 누르면 종료됩니다...")
        except EOFError:
            pass
    sys.exit(code)
