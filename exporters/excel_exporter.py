from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from pathlib import Path
import pandas as pd


def write_dataframe_to_template(df: pd.DataFrame, template_path: Path, output_path: Path, start_row: int = 2):
    """
    将DataFrame写入Excel模板，根据模板表头自动匹配列位置
    如果 Type 列为 'Diff'，则整行标红
    """
    if df.empty:
        print("警告：DataFrame为空，不生成Excel。")
        return

    wb = load_workbook(template_path)
    ws = wb.active

    # 读取模板表头（第一行）
    template_headers = []
    for col in range(1, ws.max_column + 1):
        cell_value = ws.cell(row=1, column=col).value
        if cell_value is not None:
            template_headers.append(str(cell_value).strip())
        else:
            break

    print(f"模板表头: {template_headers}")

    # 按模板表头顺序，从df中提取对应列的数据
    rows_data = []
    diff_rows = []  # 记录哪些行是 Diff 行（用于标红）
    for idx, (_, row) in enumerate(df.iterrows()):
        row_data = []
        for header in template_headers:
            if header in df.columns:
                row_data.append(row[header])
            else:
                row_data.append(None)
        rows_data.append(row_data)
        # 检查当前行是否是 Diff 行
        if 'Type' in df.columns and row.get('Type') == 'Diff':
            diff_rows.append(idx)  # 记录在 rows_data 中的索引

    # 写入数据
    for r_idx, row_data in enumerate(rows_data, start=start_row):
        for c_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=value)
            # 如果当前行是 Diff 行，标红
            if r_idx - start_row in diff_rows:
                cell.font = Font(color="FF0000")  # 红色字体
                #color="FF0000"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    wb.close()
