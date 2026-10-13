# utils/excel_helper.py

from copy import copy
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils.dataframe import dataframe_to_rows
from pathlib import Path
import pandas as pd
from datetime import datetime


def write_single_dataframe_to_excel(df, template_path: Path, output_path: Path,
                                     red_cells: dict = None, footnotes: dict = None):
    from copy import copy
    from openpyxl.styles import Border, Side, Alignment

    wb = load_workbook(template_path)
    ws = wb.active

    # 读模板表头
    template_headers = []
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=col).value
        if v is None:
            break
        template_headers.append(str(v).strip())

    for c_idx, h in enumerate(template_headers, start=1):
        ws.cell(row=1, column=c_idx, value=h)

    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    if df is not None and not df.empty:
        for r_idx, (_, row) in enumerate(df.iterrows(), start=2):
            for c_idx, h in enumerate(template_headers, start=1):
                val = row[h] if h in df.columns else None
                try:
                    if pd.isna(val):
                        val = None
                except Exception:
                    pass
                ws.cell(row=r_idx, column=c_idx, value=val)

    # ===== 显式加边框 =====
    thin = Side(style='thin', color='A6A6A6')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center_wrap = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for r in range(1, ws.max_row + 1):
        is_header = (r == 1)
        for c in range(1, len(template_headers) + 1):
            cell = ws.cell(row=r, column=c)
            cell.alignment = center_wrap
            new_font = copy(cell.font)
            new_font.bold = bool(is_header)
            cell.font = new_font
            cell.border = border
        if is_header:
            ws.row_dimensions[r].height = 30
        else:
            ws.row_dimensions[r].height = None

    # 脚注
    if footnotes:
        note_row = (len(df) if df is not None and not df.empty else 0) + 2
        for sheet_note in footnotes.values():
            cell = ws.cell(row=note_row, column=1, value=sheet_note)
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            new_font = copy(cell.font)
            new_font.bold = False
            cell.font = new_font
            ws.row_dimensions[note_row].height = None
            note_row += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    wb.close()

def write_dataframes_to_excel(dataframes: dict, template_path: Path, output_path: Path,
                               red_cells: dict = None, footnotes: dict = None):
    """
    将多个 DataFrame 写入同一个 Excel 的不同 Sheet，保留模板样式。
    
    :param dataframes: {"sheet名": DataFrame}
    :param template_path: 模板文件路径（用于复制样式）
    :param output_path: 输出文件路径
    :param red_cells: {sheet_name: [(row_index, column_name), ...]} 需要标红的单元格（行索引从0开始）
    """
    # 加载模板
    wb = load_workbook(template_path)
    template_ws = wb.worksheets[0]

    for sheet_name, df in dataframes.items():
        # 复制模板sheet（样式会复制）
        new_ws = wb.copy_worksheet(template_ws)
        new_ws.title = sheet_name

        '''
        num_df_cols = len(df.columns)
        max_col = new_ws.max_column
        if max_col > num_df_cols:
            new_ws.delete_cols(num_df_cols + 1, max_col - num_df_cols)
        '''
        # ===== 新增：偏离百分比特殊处理，删除 Type 列 =====
        if sheet_name == "偏离百分比":
            # 找到 Type 列并删除
            for col_idx in range(new_ws.max_column, 0, -1):
                if new_ws.cell(row=1, column=col_idx).value == "Type":
                    new_ws.delete_cols(col_idx)
                    break

        # 删除原有数据行（保留表头）
        max_row = new_ws.max_row
        if max_row > 1:
            new_ws.delete_rows(2, max_row - 1)

        # ---- 新增：差值统计特殊处理 ----
        if sheet_name == "差值统计":
            num_df_cols = len(df.columns)
            max_col = new_ws.max_column
            if max_col > num_df_cols:
                new_ws.delete_cols(num_df_cols + 1, max_col - num_df_cols)
            for col_idx, col_name in enumerate(df.columns, start=1):
                new_ws.cell(row=1, column=col_idx, value=col_name)

        # 写入DataFrame数据
        for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=False), start=2):
            for c_idx, value in enumerate(row, start=1):
                new_ws.cell(row=r_idx, column=c_idx, value=value)

        # ===== 新增：写入备注（脚注） =====
        if footnotes and sheet_name in footnotes:
            note_row = len(df) + 2  # 数据最后一行下一行
            note_cell = new_ws.cell(row=note_row, column=1, value=footnotes[sheet_name])
            note_cell.font = Font(size=10, italic=True, color="666666")

        # 处理标红
        if red_cells and sheet_name in red_cells:
            # 先获取表头列名到列索引的映射
            header_row = new_ws[1]
            col_name_to_idx = {}
            for cell in header_row:
                if cell.value:
                    col_name_to_idx[cell.value] = cell.column

            for row_idx, col_name in red_cells[sheet_name]:
                if col_name in col_name_to_idx:
                    col_idx = col_name_to_idx[col_name]
                    # +2 因为数据从第2行开始（第1行是表头），row_idx从0开始
                    cell = new_ws.cell(row=row_idx + 2, column=col_idx)
                    cell.font = Font(color="FF0000")

    # 删除原始模板sheet
    wb.remove(template_ws)
    wb.save(output_path)

def _auto_fit_columns(ws, max_width=25, col_max_width=None):
    """根据每列内容自动设置列宽（中文按 2 字符宽度算）。
    col_max_width: {列名: 该列最大宽度}，用于特殊列收紧
    """
    from openpyxl.utils import get_column_letter

    if col_max_width is None:
        col_max_width = {}

    for col_cells in ws.columns:
        col_letter = get_column_letter(col_cells[0].column)
        # 取该列的表头名
        header_name = None
        for cell in col_cells:
            if cell.row == 1 and cell.value is not None:
                header_name = str(cell.value).strip()
                break

        max_len = 0
        for cell in col_cells:
            if cell.value is None:
                continue
            v = str(cell.value)
            for line in v.split('\n'):
                line_len = sum(2 if ord(c) > 127 else 1 for c in line)
                if line_len > max_len:
                    max_len = line_len

        col_upper = col_max_width.get(header_name, max_width)
        ws.column_dimensions[col_letter].width = min(max_len + 2, col_upper)


def write_ch_analysis_to_excel(dataframes: dict, output_path: Path,
                                footnotes: dict = None,
                                header_sheets: set = None,
                                bold_rows_map: dict = None,
                                diff_special: dict = None):
    """
    diff_special 结构：
    {
        "sheet_name": "差值对比",
        "merges": [(start_addr, end_addr, label, color), ...],
        "pink_cells": [(excel_row, excel_col), ...],   # 需要填粉红的单元格
    }
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, Border, Side, PatternFill

    if header_sheets is None:
        header_sheets = set()
    if bold_rows_map is None:
        bold_rows_map = {}

    wb = Workbook()
    wb.remove(wb.active)

    thin = Side(style='thin', color='CCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center_wrap = Alignment(horizontal='center', vertical='center', wrap_text=True)
    font_header = Font(bold=True)
    font_data   = Font(bold=False)
    fill_pink   = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

    # 列宽上限（让 BMC IP 之类的列别太宽）
    COL_MAX_WIDTH = {
        'BMC IP': 18,
        'BIOS Version': 14,
        'Skt': 5,
        'Ch': 5,
        'SN': 20,
        'DIMM(Physical)': 16,
        'DIMM(Logical)': 20,
    }

    for sheet_name, df in dataframes.items():
        ws = wb.create_sheet(title=str(sheet_name)[:31])
        if df is None or df.empty:
            continue

        use_columns_as_header = sheet_name in header_sheets
        last_data_row = 1

        if use_columns_as_header:
            cols = list(df.columns)
            n_cols = len(cols)
            for c_idx, col_name in enumerate(cols, start=1):
                cell = ws.cell(row=1, column=c_idx, value=str(col_name))
                cell.alignment = center_wrap
                cell.font = font_header
                cell.border = border
            ws.row_dimensions[1].height = None

            data_rows = df.shape[0]
            for r in range(data_rows):
                excel_r = 2 + r
                for c in range(n_cols):
                    v = df.iloc[r, c]
                    try:
                        if pd.isna(v):
                            v = None
                    except Exception:
                        pass
                    cell = ws.cell(row=excel_r, column=c + 1, value=v)
                    cell.alignment = center_wrap
                    cell.font = font_data
                    cell.border = border
                ws.row_dimensions[excel_r].height = None
            last_data_row = 2 + data_rows - 1
        else:
            n_cols = df.shape[1]
            n_rows = df.shape[0]
            bold_rows = bold_rows_map.get(sheet_name, set())
            for r in range(n_rows):
                excel_r = r + 1
                f = font_header if r in bold_rows else font_data
                for c in range(n_cols):
                    v = df.iloc[r, c]
                    try:
                        if pd.isna(v):
                            v = None
                    except Exception:
                        pass
                    cell = ws.cell(row=excel_r, column=c + 1, value=v)
                    cell.alignment = center_wrap
                    cell.font = f
                    cell.border = border
                ws.row_dimensions[excel_r].height = None
            last_data_row = n_rows

            # ---- 差值对比特殊处理 ----
            if diff_special and diff_special.get("sheet_name") == sheet_name:
                # ① A 列合并 + 填色
                for (start_addr, end_addr, label, color) in diff_special.get("merges", []):
                    try:
                        ws.merge_cells(f"{start_addr}:{end_addr}")
                    except Exception:
                        pass
                    cell = ws[start_addr]
                    cell.value = label
                    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")

                # ② 负数单元格填粉红
                for (excel_r, excel_c) in diff_special.get("pink_cells", []):
                    try:
                        ws.cell(row=excel_r, column=excel_c).fill = fill_pink
                    except Exception:
                        pass

        # 脚注
        if footnotes and sheet_name in footnotes:
            note_row = last_data_row + 2
            cell = ws.cell(row=note_row, column=1, value=footnotes[sheet_name])
            cell.font = Font(size=10, italic=True, color="666666", bold=False)
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            ws.row_dimensions[note_row].height = None

        # 自动列宽
        _auto_fit_columns(ws, col_max_width=COL_MAX_WIDTH)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    wb.close()


def write_time_summary_to_excel(headers, data_rows, merges, output_path: Path):
    """
    写入测试时间汇总表。

    :param headers:   [row1, row2, row3]，每行是 list，长度 = 总列数
    :param data_rows: [[IP, dt, dt, ...], ...]
    :param merges:    [{"range": "A1:A3", "value": "BMCip地址"}, ...]
    :param output_path: 输出路径
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "测试时间汇总"

    thin = Side(style='thin', color='999999')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center_wrap = Alignment(horizontal='center', vertical='center', wrap_text=True)
    font_header = Font(bold=True, size=10)
    font_data = Font(bold=False, size=10)

    # 淡蓝色填充表头
    fill_header = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")

    n_cols = len(headers[0])

    # ---- 写表头 3 行 ----
    for r_idx, row in enumerate(headers, start=1):
        for c_idx in range(n_cols):
            v = row[c_idx] if c_idx < len(row) else None
            cell = ws.cell(row=r_idx, column=c_idx + 1, value=v)
            cell.alignment = center_wrap
            cell.font = font_header
            cell.border = border
            cell.fill = fill_header
        ws.row_dimensions[r_idx].height = 20

    # ---- 合并单元格 ----
    for m in merges:
        rng = m["range"]
        try:
            ws.merge_cells(rng)
        except Exception:
            continue
        # 合并后写值（合并区域左上角）
        start_addr = rng.split(":")[0]
        ws[start_addr] = m["value"]
        ws[start_addr].alignment = center_wrap
        ws[start_addr].font = font_header
        ws[start_addr].fill = fill_header

    # ---- 写数据行（从第 4 行开始） ----
    # 日期时间格式
    dt_format = "yyyy-mm-dd hh:mm:ss"

    for r_off, row in enumerate(data_rows):
        excel_r = 4 + r_off
        for c_idx in range(n_cols):
            v = row[c_idx] if c_idx < len(row) else None
            cell = ws.cell(row=excel_r, column=c_idx + 1, value=v)
            cell.alignment = center_wrap
            cell.font = font_data
            cell.border = border
            # 日期时间列格式化
            if c_idx > 0 and isinstance(v, datetime):
                cell.number_format = dt_format
        ws.row_dimensions[excel_r].height = 18

    # ---- 自动列宽 ----
    for col_idx in range(1, n_cols + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        # 从第 1 行扫到数据最后一行
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx, values_only=False):
            for cell in row:
                if cell.value is None:
                    continue
                s = str(cell.value)
                # 日期时间按固定宽度算
                if isinstance(cell.value, datetime):
                    width = 18
                else:
                    width = sum(2 if ord(c) > 127 else 1 for c in s)
                if width > max_len:
                    max_len = width
        # 数据列（时间戳）至少 17 宽
        if col_idx > 1:
            max_len = max(max_len, 17)
        ws.column_dimensions[col_letter].width = min(max_len + 2, 30)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    wb.close()