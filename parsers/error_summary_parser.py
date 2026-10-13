# parsers/error_summary_parser.py
import re
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd
from openpyxl import load_workbook

# 汇总表头（与"报错信息汇总模板.xlsx"一致）
SUMMARY_COLUMNS = [
    '序号', 'SN', '规格', '原始Log槽位', '实物槽位', '不良地址',
    'faultmode', '机台解析faultMode', '失效模式', '总报错次数',
    '报错算法', '报错温度', '报错Loop',
    'twr-trtp-trp-trcd-tras-delay-vdd-vddq-vpp',
    '机台号', 'LOG', '报错阶段'
]


def find_error_xlsx_files(root_dir: Path) -> List[Dict]:
    """
    扫描 ORT log 目录，找出所有检错 xlsx 文件，并计算"报错阶段"。

    返回: [{"file": Path, "stage": "第1轮老化+检错\\posttest1\\EXT"}, ...]
    """
    root = Path(root_dir)
    results = []

    if not root.exists() or not root.is_dir():
        return results

    # 遍历一级子目录（T0时刻、第N轮老化+检错、结束时刻等）
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue

        sub_name = sub.name

        # ---- 情况A：T0时刻 / 结束时刻，下面有 pretest 目录 ----
        pretest = sub / "pretest"
        if pretest.exists() and pretest.is_dir():
            for sub_sub in pretest.iterdir():
                if sub_sub.is_dir():
                    for xlsx in sub_sub.glob("*.xlsx"):
                        if xlsx.name.startswith("~$"):
                            continue
                        stage = f"{sub_name}\\pretest\\{sub_sub.name}"
                        results.append({"file": xlsx, "stage": stage})
            continue

        # ---- 情况B：第N轮老化+检错，下面有 posttest1/posttest2... ----
        post_dirs = [d for d in sub.iterdir() if d.is_dir() and d.name.lower().startswith("posttest")]
        if post_dirs:
            for post in sorted(post_dirs, key=lambda p: p.name):
                for sub_sub in post.iterdir():
                    if sub_sub.is_dir():
                        for xlsx in sub_sub.glob("*.xlsx"):
                            if xlsx.name.startswith("~$"):
                                continue
                            stage = f"{sub_name}\\{post.name}\\{sub_sub.name}"
                            results.append({"file": xlsx, "stage": stage})

    return results


def read_error_xlsx(file_path: Path) -> pd.DataFrame:
    """
    读取单个检错 xlsx，返回带原始表头的 DataFrame。
    如果只有表头没有数据，返回空 DataFrame。
    """
    try:
        # 用 openpyxl 读取，保留合并单元格/复杂文本
        wb = load_workbook(file_path, data_only=True)
        ws = wb.active

        # 读表头
        headers = []
        for col in range(1, ws.max_column + 1):
            v = ws.cell(row=1, column=col).value
            headers.append(str(v).strip() if v is not None else f"col{col}")

        # 读数据行
        rows = []
        for r in range(2, ws.max_row + 1):
            row_vals = []
            has_value = False
            for c in range(1, ws.max_column + 1):
                v = ws.cell(row=r, column=c).value
                row_vals.append(v)
                if v is not None and str(v).strip() != "":
                    has_value = True
            if has_value:
                rows.append(row_vals)

        wb.close()

        if not rows:
            return pd.DataFrame(columns=headers)

        return pd.DataFrame(rows, columns=headers)

    except Exception as e:
        print(f"读取 {file_path} 失败: {e}")
        return pd.DataFrame()


def collect_all_errors(root_dir: Path, log_callback=None) -> pd.DataFrame:
    """
    扫描 root_dir 下所有检错 xlsx，合并为一个 DataFrame。
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    files_info = find_error_xlsx_files(root_dir)
    log(f"📁 共发现 {len(files_info)} 个检错 xlsx 文件")

    all_rows = []
    for info in files_info:
        f = info["file"]
        stage = info["stage"]
        log(f"   📄 读取: {stage}\\{f.name}")
        df = read_error_xlsx(f)
        if df.empty:
            log(f"      ⚠️ 无数据（无错误）")
            continue
        # 添加"报错阶段"列
        df["报错阶段"] = stage
        all_rows.append(df)
        log(f"      ✅ 发现 {len(df)} 条错误记录")

    if not all_rows:
        log("ℹ️ 所有检错文件均无错误记录")
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    merged = pd.concat(all_rows, ignore_index=True)

    # 重新生成序号（可选，按原样保留也行；这里重新编号更规整）
    if "序号" in merged.columns:
        merged["序号"] = range(1, len(merged) + 1)

    # 保证列顺序与模板一致（多余的列丢弃，缺少的补空）
    for col in SUMMARY_COLUMNS:
        if col not in merged.columns:
            merged[col] = None
    merged = merged[SUMMARY_COLUMNS]

    log(f"📊 汇总完成，共 {len(merged)} 条错误记录")
    return merged