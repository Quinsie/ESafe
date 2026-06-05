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


def _build_in_com(payload: dict) -> bytes:
    hwp = _ensure_hwp()
    out_path = None
    try:
        hwp.Run("FileNew")
        _write_report(hwp, payload)

        fd, out_path = tempfile.mkstemp(suffix=".hwp", prefix="esafe_report_")
        os.close(fd)
        if os.path.exists(out_path):
            os.remove(out_path)
        hwp.SaveAs(out_path, "HWP", "")

        for _ in range(50):  # 저장 완료 대기(최대 5초)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                break
            time.sleep(0.1)
        with open(out_path, "rb") as f:
            data = f.read()
        return data
    finally:
        try:
            hwp.Run("FileClose")  # SaveAs 이후라 저장 프롬프트 없음
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


def _table(hwp, data, has_header=True):
    """2차원 리스트를 표로 삽입한다. 삽입 후 커서는 표 아래로 빠진다."""
    if not data:
        return
    rows = len(data)
    cols = max(len(r) for r in data)
    hwp.Run("MoveDocEnd")  # 이전 표 셀 안이 아닌 문서 끝(본문)에서 표 생성
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

    # 표 밖(문서 끝, 표 아래 본문 문단)으로 커서 이동
    hwp.Run("TableSelCell")
    hwp.Run("Cancel")
    hwp.Run("MoveDocEnd")


def _fmt_contribution(value):
    try:
        v = float(value)
        return ("+%.1f" % v) if v >= 0 else ("%.1f" % v)
    except (TypeError, ValueError):
        return "" if value is None else str(value)


_FONT = "맑은 고딕"


def _write_report(hwp, p: dict):
    region = p.get("region_name") or "관할 지역"
    generated_at = p.get("generated_at") or ""
    briefing = p.get("briefing_text") or ""
    factors = p.get("factors") or []
    stats = p.get("grade_distribution") or {}
    building_count = p.get("building_count")
    avg_score = p.get("avg_score")
    model = p.get("model") or ""

    # 제목
    _align(hwp, "center")
    _font(hwp, _FONT, 18, bold=True)
    _text(hwp, "전기재해위험도 상황요약 보고서")
    _para(hwp)

    # 메타
    _align(hwp, "center")
    _font(hwp, _FONT, 10, bold=False)
    _text(hwp, "대상 지역: %s" % region)
    _para(hwp)
    if generated_at:
        _text(hwp, "생성일시: %s" % generated_at)
        _para(hwp)
    extra = []
    if building_count is not None:
        try:
            extra.append("대상 건물 %s건" % format(int(building_count), ","))
        except (TypeError, ValueError):
            pass
    if avg_score is not None:
        extra.append("평균 위험점수 %s" % avg_score)
    if extra:
        _text(hwp, " / ".join(extra))
        _para(hwp)
    _para(hwp)

    # 1. 브리핑 본문
    _align(hwp, "left")
    _font(hwp, _FONT, 13, bold=True)
    _text(hwp, "■ AI 상황요약 브리핑")
    _para(hwp)
    _font(hwp, _FONT, 11, bold=False)
    _multiline(hwp, briefing or "(브리핑 내용이 없습니다.)")
    _para(hwp)
    _para(hwp)

    # 2. 주요 위험요인 표
    if factors:
        _align(hwp, "left")
        _font(hwp, _FONT, 13, bold=True)
        _text(hwp, "■ 주요 위험요인")
        _para(hwp)
        _font(hwp, _FONT, 10, bold=False)
        table = [["순위", "위험요인", "기여도"]]
        for i, f in enumerate(factors, 1):
            label = (f.get("label") or f.get("feature") or "") if isinstance(f, dict) else str(f)
            contrib = f.get("contribution") if isinstance(f, dict) else None
            table.append([str(i), label, _fmt_contribution(contrib)])
        _table(hwp, table, has_header=True)
        _para(hwp)
        _para(hwp)

    # 3. 등급별 통계 표
    if stats:
        _align(hwp, "left")
        _font(hwp, _FONT, 13, bold=True)
        _text(hwp, "■ 등급별 건물 통계")
        _para(hwp)
        _font(hwp, _FONT, 10, bold=False)
        table = [["등급", "건물 수"]]
        for k, v in stats.items():
            table.append([str(k), str(v)])
        _table(hwp, table, has_header=True)
        _para(hwp)
        _para(hwp)

    # 푸터
    _align(hwp, "left")
    _font(hwp, _FONT, 9, bold=False)
    foot = "※ 본 보고서는 ESafe 전기재해위험지도 시스템이 자동 생성했습니다."
    if model:
        foot += " (LLM: %s)" % model
    _text(hwp, foot)
