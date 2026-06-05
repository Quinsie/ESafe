# -*- coding: utf-8 -*-
"""
ESafe 한글(HWP) 보고서 생성기.

전국 위험지도의 'AI 브리핑 및 상황요약 보고서' 내용을 받아 한글 문서(.hwp)로 출력한다.
jkf87/hwp-mcp 의 win32com COM 자동화 방식을 차용했다(Windows + 한글 설치 필수).

설계 메모:
- HWP COM은 단일 인스턴스/STA 모델이라, 모든 작업을 전용 단일 워커 스레드에서 직렬로 처리한다.
  (FastAPI 워커 스레드에서 직접 COM을 호출하면 아파트먼트/동시성 문제가 생김)
- 사용자가 열어둔 한글 창을 닫지 않도록 Quit() 하지 않고, 숨김 자동화 인스턴스를 재사용한다.
- 보안 경고창은 SetMessageBoxMode + 보안 모듈 등록으로 회피한다.
"""
from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

# HWP 작업 전용 단일 워커(직렬화). COM 아파트먼트를 이 스레드에 고정한다.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hwp")
_state = {"hwp": None}

_DLL_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "hwp_mcp", "security_module",
                 "FilePathCheckerModuleExample.dll")
)

# 한국전기안전공사 공문 양식(서식 유지용). 이 양식을 열어 제목/본문만 채운다.
_TEMPLATE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "templates", "kesco_gongmun.hwp")
)


def is_available() -> bool:
    """win32com + HWPFrame.HwpObject 사용 가능 여부(빠른 판별용)."""
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


def build_report(payload: dict) -> bytes:
    """보고서 페이로드를 받아 .hwp 바이트를 반환한다(블로킹)."""
    return _executor.submit(_build_in_com, payload).result()


# ---------------------------------------------------------------------------
# COM 워커 (단일 스레드에서만 실행)
# ---------------------------------------------------------------------------
def _register_security(hwp):
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\HNC\HwpAutomation\Modules")
        winreg.SetValueEx(key, "FilePathCheckerModuleExample", 0, winreg.REG_SZ, _DLL_PATH)
        winreg.CloseKey(key)
    except Exception:
        pass
    for args in (("FilePathCheckerModuleExample", "FilePathCheckerModuleExample"),
                 ("FilePathCheckDLL", "FilePathCheckerModule")):
        try:
            hwp.RegisterModule(*args)
        except Exception:
            pass


def _ensure_hwp():
    if _state["hwp"] is not None:
        return _state["hwp"]
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
    _register_security(hwp)
    try:
        hwp.SetMessageBoxMode(0x00010000)  # 메시지박스 자동 확인
    except Exception:
        pass
    try:
        hwp.XHwpWindows.Item(0).Visible = False  # 숨김 자동화 인스턴스
    except Exception:
        pass
    _state["hwp"] = hwp
    return hwp


def _find(hwp, text) -> bool:
    """문서에서 text를 찾아 커서를 그 위치로 옮긴다."""
    pset = hwp.HParameterSet.HFindReplace
    hwp.HAction.GetDefault("RepeatFind", pset.HSet)
    pset.FindString = text
    pset.FindRegExp = 0
    pset.IgnoreMessage = 1
    pset.Direction = 0
    return bool(hwp.HAction.Execute("RepeatFind", pset.HSet))


def _save_as(hwp, path):
    """대화상자 없이 다른 이름으로 저장(FileSaveAs_S)."""
    pset = hwp.HParameterSet.HFileOpenSave
    hwp.HAction.GetDefault("FileSaveAs_S", pset.HSet)
    pset.filename = path
    pset.Format = "HWP"
    hwp.HAction.Execute("FileSaveAs_S", pset.HSet)


def _build_in_com(payload: dict) -> bytes:
    hwp = _ensure_hwp()
    out_path = None
    try:
        if not os.path.exists(_TEMPLATE_PATH):
            raise RuntimeError("공문 양식 파일을 찾을 수 없습니다: %s" % _TEMPLATE_PATH)
        # 양식을 열고 제목/본문만 채워 서식(두문·발신명의·직인·시행번호 등)을 보존한다.
        hwp.Open(_TEMPLATE_PATH, "HWP", "")
        _write_report(hwp, payload)

        fd, out_path = tempfile.mkstemp(suffix=".hwp", prefix="esafe_report_")
        os.close(fd)
        if os.path.exists(out_path):
            os.remove(out_path)
        _save_as(hwp, out_path)

        for _ in range(50):  # 저장 완료 대기(최대 5초)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                break
            time.sleep(0.1)
        with open(out_path, "rb") as f:
            data = f.read()
        return data
    finally:
        try:
            hwp.SetMessageBoxMode(0x00100000)  # 닫을 때 '저장 안 함' (양식 원본 오염 방지)
            hwp.Run("FileClose")
            hwp.SetMessageBoxMode(0x00010000)
        except Exception:
            pass
        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 문서 작성 헬퍼
# ---------------------------------------------------------------------------
def _text(hwp, s: str):
    hwp.HAction.GetDefault("InsertText", hwp.HParameterSet.HInsertText.HSet)
    hwp.HParameterSet.HInsertText.Text = s
    hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)


def _para(hwp):
    hwp.HAction.Run("BreakPara")


def _multiline(hwp, text: str):
    lines = str(text).replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if i > 0:
            _para(hwp)
        if line.strip():
            _text(hwp, line)


def _align(hwp, how: str):
    action = {
        "center": "ParagraphShapeAlignCenter",
        "left": "ParagraphShapeAlignLeft",
        "right": "ParagraphShapeAlignRight",
        "justify": "ParagraphShapeAlignJustify",
    }.get(how)
    if action:
        try:
            hwp.HAction.Run(action)
        except Exception:
            pass


def _font(hwp, name=None, size=None, bold=False):
    hwp.HAction.GetDefault("CharShape", hwp.HParameterSet.HCharShape.HSet)
    cs = hwp.HParameterSet.HCharShape
    if name:
        for attr in ("FaceNameHangul", "FaceNameLatin", "FaceNameHanja",
                     "FaceNameJapanese", "FaceNameOther", "FaceNameSymbol", "FaceNameUser"):
            try:
                setattr(cs, attr, name)
            except Exception:
                pass
    if size:
        cs.Height = int(size) * 100  # 10pt = 1000
    cs.Bold = bool(bold)
    cs.Italic = False
    cs.UnderlineType = 0
    hwp.HAction.Execute("CharShape", hwp.HParameterSet.HCharShape.HSet)


def _insert_table(hwp, rows: int, cols: int):
    # 매 호출마다 새 액션/파라미터셋을 생성한다. 공유 HParameterSet을 재사용하면
    # 두 번째 표 생성부터 COM 서버 예외(-2147417851)가 발생한다.
    act = hwp.CreateAction("TableCreate")
    pset = act.CreateSet()
    act.GetDefault(pset)
    pset.SetItem("Rows", rows)
    pset.SetItem("Cols", cols)
    pset.SetItem("WidthType", 0)    # 0: 단에 맞춤(열 너비 균등 분배)
    pset.SetItem("HeightType", 1)   # 1: 절대값
    pset.SetItem("WidthValue", 0)
    pset.SetItem("HeightValue", 1000)
    act.Execute(pset)


def _table(hwp, data, has_header=True, reposition=None):
    """2차원 리스트를 표로 삽입한다.

    reposition: 표 생성 전/후 커서를 둘 위치를 정하는 콜백. 없으면 문서 끝(MoveDocEnd).
    양식 본문에 표를 넣을 때는 '발신명의 바로 위'로 재위치하는 콜백을 넘긴다.
    """
    if not data:
        return
    rows = len(data)
    cols = max(len(r) for r in data)

    def _place():
        if reposition:
            reposition()
        else:
            hwp.Run("MoveDocEnd")

    _place()  # 이전 표 셀 안이 아닌 본문 위치에서 표 생성
    _insert_table(hwp, rows, cols)  # 커서가 첫 셀에 위치

    for row_idx, row in enumerate(data):
        for col_idx in range(cols):
            value = row[col_idx] if col_idx < len(row) else ""
            hwp.Run("TableSelCell")
            hwp.Run("Delete")
            bold = bool(has_header and row_idx == 0)
            if bold:
                _font(hwp, size=10, bold=True)
            _text(hwp, str(value))
            if bold:
                _font(hwp, size=10, bold=False)
            if col_idx < cols - 1:
                hwp.Run("TableRightCell")
        if row_idx < rows - 1:
            for _ in range(cols - 1):
                hwp.Run("TableLeftCell")
            hwp.Run("TableLowerCell")

    # 표 밖(표 아래 본문 문단)으로 커서 이동
    hwp.Run("TableSelCell")
    hwp.Run("Cancel")
    _place()


def _fmt_contribution(value):
    try:
        v = float(value)
        return ("+%.1f" % v) if v >= 0 else ("%.1f" % v)
    except (TypeError, ValueError):
        return "" if value is None else str(value)


_FONT = "함초롬바탕"


def _write_report(hwp, p: dict):
    """양식(kesco_gongmun.hwp)을 열어 제목과 본문만 채운다.

    두문·발신명의·직인·기안/검토/전결·시행번호·주소/연락처 등 서식은 양식이 제공하므로
    여기서는 '제목'과 '본문(발신명의 위 영역)'만 채운다.
    """
    region = p.get("region_name") or "관할 지역"
    generated_at = p.get("generated_at") or ""
    briefing = p.get("briefing_text") or ""
    factors = p.get("factors") or []
    stats = p.get("grade_distribution") or {}
    building_count = p.get("building_count")
    avg_score = p.get("avg_score")
    date_only = generated_at.split(" ")[0] if generated_at else ""

    # --- 제목 채우기(두문의 '제목' 칸) ---
    hwp.Run("MoveDocBegin")
    if _find(hwp, "제목"):
        hwp.Run("MoveLineEnd")
        _text(hwp, "   AI 기반 전기재해위험 상황요약 결과 통보")

    # --- 본문은 발신명의('광주전남본부장') 바로 위에 좌측정렬로 채운다 ---
    def _fresh_para():
        # 발신명의 위에 좌측정렬 빈 문단을 만들고 커서를 그 안에 둔다.
        # (발신명의 문단은 가운데정렬이라, 그 위에 별도 좌측정렬 문단을 새로 만든다)
        hwp.Run("MoveDocBegin")
        _find(hwp, "광주전남본부장")
        hwp.Run("MoveLineBegin")
        _para(hwp)
        hwp.Run("MoveUp")
        hwp.Run("MoveLineBegin")
        _align(hwp, "left")
        _font(hwp, _FONT, 11, bold=False)

    def L(t=""):
        if t:
            _text(hwp, t)
        _para(hwp)

    _fresh_para()
    L("1. 우리 공사의 전기재해 예방 업무에 협조하여 주신 데 깊이 감사드립니다.")
    L()
    L("2. %s을(를) 대상으로 AI 기반 위험원인 분석을 통해 산출한 전기재해위험 "
      "상황요약 결과를 다음과 같이 통보하오니, 관련 업무에 참고하시기 바랍니다." % region)
    L()
    L("3. 분석 개요")
    L("  가. 분석 기간: 최근 2주%s" % ((" (%s 기준)" % date_only) if date_only else ""))
    L("  나. 분석 대상: %s" % region)
    overview = []
    if building_count is not None:
        try:
            overview.append("대상 건물 %s개소" % format(int(building_count), ","))
        except (TypeError, ValueError):
            pass
    if avg_score is not None:
        overview.append("평균 위험점수 %s점" % avg_score)
    if overview:
        L("  다. 분석 규모: %s" % " / ".join(overview))
    L("  라. 주요 내용: AI 기반 전기재해위험 상황요약(위험원인 분석)")
    L()
    L("4. 분석 결과")
    for bl in str(briefing or "(분석 결과 내용이 없습니다.)").replace("\r\n", "\n").split("\n"):
        L(bl.strip())
    L()

    # 주요 위험요인 표
    if factors:
        L("[ 주요 위험요인 분석 ]")
        tdata = [["순위", "위험 요인", "기여도(위험도 가산점)"]]
        for i, f in enumerate(factors, 1):
            label = (f.get("label") or f.get("feature") or "") if isinstance(f, dict) else str(f)
            contrib = f.get("contribution") if isinstance(f, dict) else None
            tdata.append([str(i), label, _fmt_contribution(contrib)])
        _table(hwp, tdata, has_header=True, reposition=(lambda: None))
        _fresh_para()

    # 등급별 통계 표
    if stats:
        L("[ 등급별 건물 통계 ]")
        tdata = [["등급", "건물 수"]]
        for k, v in stats.items():
            tdata.append([str(k), str(v)])
        _table(hwp, tdata, has_header=True, reposition=(lambda: None))
        _fresh_para()

    # 활용 방안 / 붙임
    L("5. 본 분석 결과는 다음과 같이 활용하실 수 있습니다.")
    L("  가. 위험 등급별 우선 점검 대상 선별")
    L("  나. 분석 결과 기반 현장 점검 및 설비 보수 계획 수립")
    L("  다. 전기재해 예방 정책 수립 기초자료 활용")
    L()
    L("붙임  1. 전기재해위험 상황요약 보고서 1부.")
    L("        2. 주요 위험요인 분석 자료 1부.  끝.")
