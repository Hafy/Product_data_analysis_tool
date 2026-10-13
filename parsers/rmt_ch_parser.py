# parsers/rmt_ch_parser.py
import re
from pathlib import Path
from typing import List, Dict
import pandas as pd

from parsers.rmt_parser import parse_rmt_log

# RMT 数值列（与 rmt_parser 一致）
CH_NUMERIC_COLS = [
    'RxDly-', 'RxDly+', 'RxVrf-', 'RxVrf+',
    'TxDly-', 'TxDly+', 'TxVrf-', 'TxVrf+'
]

# 差值对比显示名 → 数据列名
DISPLAY_TO_SRC = {
    'RxDqs-': 'RxDly-',
    'RxDqs+': 'RxDly+',
    'RxV-':   'RxVrf-',
    'RxV+':   'RxVrf+',
    'TxDq-':  'TxDly-',
    'TxDq+':  'TxDly+',
    'TxV-':   'TxVrf-',
    'TxV+':   'TxVrf+',
}
DISPLAY_COLS = list(DISPLAY_TO_SRC.keys())
SRC_COLS = list(DISPLAY_TO_SRC.values())


def _extract_sk_ch(logical_id) -> tuple:
    m = re.match(r'S(\d+)\.C(\d+)', str(logical_id))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _ip_sort_key(file_path: Path):
    """按 IP 数字排序：'192-168-10-91_...' → (192,168,10,91)"""
    stem = file_path.stem
    ip_part = stem.split('_')[0] if '_' in stem else stem
    parts = ip_part.replace('-', '.').split('.')
    nums = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    return tuple(nums)


def parse_rmt_folder_for_ch(folder: Path, bios_version: str,
                             log_callback=None, gui_warn=None) -> pd.DataFrame:
    """
    log_callback: 详细日志（写文件）用
    gui_warn:     重要事件（显示到 GUI）用，格式 gui_warn(level, msg)
                  level: 'warn' / 'error'
    """
    def log_detail(msg):
        if log_callback:
            log_callback(msg)

    def warn_gui(msg):
        if gui_warn:
            gui_warn('warn', msg)

    def error_gui(msg):
        if gui_warn:
            gui_warn('error', msg)

    all_dfs = []
    files = [f for f in folder.iterdir() if f.is_file() and not f.name.startswith('~$')]
    files = sorted(files, key=_ip_sort_key)

    if not files:
        log_detail(f"   ⚠️ 目录为空: {folder}")
        return pd.DataFrame()

    for f in files:
        try:
            df = parse_rmt_log(f, bios_version, log_callback=log_detail)
            if df.empty:
                warn_gui(f"⚠️ 文件无有效数据: {f.name}")
                continue
            skt_ch = df['DIMM(Logical)'].apply(_extract_sk_ch)
            df['Skt'] = [t[0] for t in skt_ch]
            df['Ch']  = [t[1] for t in skt_ch]
            all_dfs.append(df)
        except Exception as e:
            error_gui(f"❌ 解析失败 {f.name}: {e}")
            log_detail(f"   ❌ 解析失败 {f.name}: {e}")

    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)


def build_min_max_avg_rows(df: pd.DataFrame, numeric_cols: List[str],
                            first_col_name: str = 'BMC IP') -> pd.DataFrame:
    """
    在 df 末尾追加三行：Min / Max / Ave。
    ⚠️ 统计时先取 abs（绝对值），结果都是非负数。
    """
    if df.empty:
        return df

    rows = []
    for label, mode in [('Min', 'min'), ('Max', 'max'), ('Ave', 'mean')]:
        row = {}
        for col in df.columns:
            if col in numeric_cols:
                vals = pd.to_numeric(df[col], errors='coerce').abs()   # ← abs
                if mode == 'min':
                    row[col] = vals.min()
                elif mode == 'max':
                    row[col] = vals.max()
                else:
                    m = vals.mean()
                    row[col] = round(m, 3) if pd.notna(m) else None
            elif col == first_col_name:
                row[col] = label
            else:
                row[col] = None
        rows.append(row)

    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)


def build_ch_sheet(df: pd.DataFrame, ch: int) -> pd.DataFrame:
    sub = df[df['Ch'] == ch].copy()
    if sub.empty:
        return pd.DataFrame()
    return sub.reset_index(drop=True)


def compute_ch_stats(df_ch: pd.DataFrame, numeric_cols: List[str]) -> Dict[str, Dict[str, float]]:
    """
    对某个 CH 的数据计算 Min/Max/Average。
    ⚠️ 统计前先取 abs。
    """
    result = {}
    for key, mode in [('min', 'min'), ('max', 'max'), ('avg', 'mean')]:
        d = {}
        for col in numeric_cols:
            if col not in df_ch.columns:
                d[col] = None
                continue
            vals = pd.to_numeric(df_ch[col], errors='coerce').abs()   # ← abs
            if mode == 'min':
                d[col] = vals.min()
            elif mode == 'max':
                d[col] = vals.max()
            else:
                m = vals.mean()
                d[col] = round(m, 3) if pd.notna(m) else None
        result[key] = d
    return result