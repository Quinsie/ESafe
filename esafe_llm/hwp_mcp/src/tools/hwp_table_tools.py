"""
한글(HWP) 문서의 표 관련 기능을 제공하는 모듈
hwp_controller.py와 함께 사용됩니다.
"""

import json
import logging
import os
import time
from typing import List, Dict, Any, Optional

# Configure logging
logger = logging.getLogger("hwp-table-tools")

class HwpTableTools:
    """한글 문서의 표 관련 기능을 제공하는 클래스"""

    def __init__(self, hwp_controller=None):
        """
        초기화 함수
        
        Args:
            hwp_controller: HwpController 인스턴스
        """
        self.hwp_controller = hwp_controller

    def set_controller(self, hwp_controller):
        """
        HwpController 인스턴스 설정
        
        Args:
            hwp_controller: HwpController 인스턴스
        """
        self.hwp_controller = hwp_controller

    def insert_table(self, rows: int, cols: int) -> str:
        """
        현재 커서 위치에 표를 삽입합니다.
        
        Args:
            rows: 표의 행 수
            cols: 표의 열 수
            
        Returns:
            str: 결과 메시지
        """
        try:
            if not self.hwp_controller:
                return "Error: HWP Controller is not set"
            
            if self.hwp_controller.insert_table(rows, cols):
                logger.info(f"Successfully inserted {rows}x{cols} table")
                return f"Table inserted with {rows} rows and {cols} columns"
            else:
                return "Error: Failed to insert table"
        except Exception as e:
            logger.error(f"Error inserting table: {str(e)}", exc_info=True)
            return f"Error: {str(e)}"

    def set_cell_text(self, row: int, col: int, text: str) -> str:
        """
        표의 특정 셀에 텍스트를 입력합니다.
        
        Args:
            row: 셀의 행 번호 (1부터 시작)
            col: 셀의 열 번호 (1부터 시작)
            text: 입력할 텍스트
            
        Returns:
            str: 결과 메시지
        """
        try:
            if not self.hwp_controller:
                return "Error: HWP Controller is not set"
            
            # fill_table_cell 메서드를 사용하여 셀에 텍스트 입력
            if self.hwp_controller.fill_table_cell(row, col, text):
                logger.info(f"셀 텍스트 설정 완료: ({row}, {col})")
                return f"셀({row}, {col})에 텍스트 입력 완료"
            else:
                return f"셀({row}, {col})에 텍스트 입력 실패"
        except Exception as e:
            logger.error(f"셀 텍스트 설정 중 오류: {str(e)}", exc_info=True)
            return f"Error: {str(e)}"

    def merge_cells(self, start_row: int, start_col: int, end_row: int, end_col: int) -> str:
        """
        표의 특정 범위의 셀을 병합합니다.
        
        Args:
            start_row: 시작 행 번호 (1부터 시작)
            start_col: 시작 열 번호 (1부터 시작)
            end_row: 종료 행 번호 (1부터 시작)
            end_col: 종료 열 번호 (1부터 시작)
            
        Returns:
            str: 결과 메시지
        """
        try:
            if not self.hwp_controller:
                return "Error: HWP Controller is not set"
            
            # merge_table_cells 메서드를 사용하여 셀 병합
            if self.hwp_controller.merge_table_cells(start_row, start_col, end_row, end_col):
                logger.info(f"셀 병합 완료: ({start_row},{start_col}) - ({end_row},{end_col})")
                return f"셀 병합 완료 ({start_row},{start_col}) - ({end_row},{end_col})"
            else:
                return f"셀 병합 실패"
        except Exception as e:
            logger.error(f"셀 병합 중 오류: {str(e)}", exc_info=True)
            return f"Error: {str(e)}"

    def get_cell_text(self, row: int, col: int) -> str:
        """
        표의 특정 셀의 텍스트를 가져옵니다.
        
        Args:
            row: 셀의 행 번호 (1부터 시작)
            col: 셀의 열 번호 (1부터 시작)
            
        Returns:
            str: 셀의 텍스트 내용
        """
        try:
            if not self.hwp_controller:
                return "Error: HWP Controller is not set"
            
            # get_table_cell_text 메서드를 사용하여 셀 텍스트 가져오기
            text = self.hwp_controller.get_table_cell_text(row, col)
            logger.info(f"셀 텍스트 가져오기 완료: ({row}, {col})")
            return text
        except Exception as e:
            logger.error(f"셀 텍스트 가져오기 중 오류: {str(e)}", exc_info=True)
            return f"Error: {str(e)}"

    def create_table_with_data(self, rows: int, cols: int, data: str = None, has_header: bool = False) -> str:
        """
        현재 커서 위치에 표를 생성하고 데이터를 채웁니다.
        
        Args:
            rows: 표의 행 수
            cols: 표의 열 수
            data: 표에 채울 데이터 (JSON 형식의 2차원 배열 문자열, 예: '[["항목1", "항목2"], ["값1", "값2"]]')
            has_header: 첫 번째 행을 헤더로 처리할지 여부
            
        Returns:
            str: 결과 메시지
        """
        try:
            if not self.hwp_controller:
                return "Error: HWP Controller is not set"
            
            # 표 생성
            if not self.hwp_controller.insert_table(rows, cols):
                return "Error: Failed to create table"
            
            # 데이터가 제공된 경우 표 채우기
            if data:
                try:
                    # 입력 데이터 로깅
                    logger.info(f"Parsing data string: {data[:100]}...")
                    
                    # JSON 문자열을 파이썬 객체로 변환
                    data_array = json.loads(data)
                    
                    # 데이터 구조 유효성 검사
                    if not isinstance(data_array, list):
                        return f"표는 생성되었으나 데이터가 리스트 형식이 아닙니다. 받은 데이터 타입: {type(data_array)}"
                    
                    if len(data_array) == 0:
                        return f"표는 생성되었으나 데이터 리스트가 비어 있습니다."
                    
                    if not all(isinstance(row, list) for row in data_array):
                        return f"표는 생성되었으나 데이터가 2차원 배열 형식이 아닙니다."
                    
                    # 모든 문자열로 변환 (혼합 유형 데이터 처리)
                    str_data_array = [[str(cell) for cell in row] for row in data_array]
                    
                    logger.info(f"Converted data array: {str_data_array[:2]}...")
                    
                    # fill_table_with_data 메서드를 사용하여 데이터 채우기
                    if self.hwp_controller.fill_table_with_data(str_data_array, 1, 1, has_header):
                        return f"표 생성 및 데이터 입력 완료 ({rows}x{cols} 크기)"
                    else:
                        return f"표는 생성되었으나 데이터 입력에 실패했습니다."
                    
                except json.JSONDecodeError as e:
                    logger.error(f"JSON 파싱 오류: {str(e)}")
                    return f"표는 생성되었으나 JSON 데이터 파싱 오류: {str(e)}"
                except Exception as data_error:
                    logger.error(f"표 데이터 입력 중 오류: {str(data_error)}", exc_info=True)
                    return f"표는 생성되었으나 데이터 입력 중 오류 발생: {str(data_error)}"
            
            return f"표 생성 완료 ({rows}x{cols} 크기)"
        except Exception as e:
            logger.error(f"표 생성 중 오류: {str(e)}", exc_info=True)
            return f"Error: {str(e)}"

    def fill_table_with_data(self, data_list: List[List[str]], start_row: int = 1, start_col: int = 1, has_header: bool = False) -> str:
        """
        이미 존재하는 표에 데이터를 채웁니다.
        
        Args:
            data_list: 표에 채울 2차원 데이터 리스트
            start_row: 시작 행 번호 (1부터 시작)
            start_col: 시작 열 번호 (1부터 시작)
            has_header: 첫 번째 행을 헤더로 처리할지 여부
            
        Returns:
            str: 결과 메시지
        """
        try:
            if not self.hwp_controller:
                return "Error: HWP Controller is not set"
            
            if not data_list:
                return "Error: Data is required"
            
            logger.info(f"Filling table with data: {len(data_list)} rows, starting at ({start_row}, {start_col})")
            
            # 데이터 형식 검사 및 변환
            processed_data = []
            for row in data_list:
                if not isinstance(row, list):
                    logger.warning(f"행이 리스트 형식이 아님: {type(row)}")
                    row = [str(row)]
                processed_row = [str(cell) if cell is not None else "" for cell in row]
                processed_data.append(processed_row)
            
            # fill_table_with_data 메서드를 사용하여 데이터 채우기
            success = self.hwp_controller.fill_table_with_data(processed_data, start_row, start_col, has_header)
            
            if success:
                logger.info("표 데이터 입력 완료")
                return "표 데이터 입력 완료"
            else:
                logger.error("hwp_controller.fill_table_with_data 호출 실패")
                return "표 데이터 입력 실패"
        except Exception as e:
            logger.error(f"표 데이터 입력 중 오류: {str(e)}", exc_info=True)
            return f"Error: {str(e)}"

# 유틸리티 함수 - 문자열 데이터를 2차원 배열로 변환
def parse_table_data(data_str: str) -> List[List[str]]:
    """
    문자열 형태의 표 데이터를 2차원 리스트로 변환합니다.
    
    Args:
        data_str: JSON 형식의 2차원 배열 문자열
        
    Returns:
        List[List[str]]: 2차원 데이터 리스트
    """
    try:
        data = json.loads(data_str)
        
        # 데이터 구조 유효성 검사
        if not isinstance(data, list):
            logger.error(f"데이터가 리스트 형식이 아님: {type(data)}")
            return []
        
        # 모든 행이 리스트인지 확인하고 문자열로 변환
        result = []
        for row in data:
            if isinstance(row, list):
                result.append([str(cell) if cell is not None else "" for cell in row])
            else:
                # 리스트가 아닌 행은 단일 항목 리스트로 처리
                result.append([str(row)])
        
        return result
    except json.JSONDecodeError as e:
        logger.error(f"표 데이터 파싱 오류: {str(e)}")
        return [] 