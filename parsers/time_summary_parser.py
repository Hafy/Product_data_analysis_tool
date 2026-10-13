# parsers/time_summary_parser.py
"""
测试时间收集解析器。

扫描 ORT log 目录，收集每台服务器在每个测试子目录的测试时间，
按 BMC IP 对齐，返回表头信息（3 行）+ 数据行 + 合并信息。
"""
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Set

from openpyxl import load_workbook


# ============ 时间戳解析 ============

def parse_timestamp_from_filename(file_path: Path) -> Optional[datetime]:
    """
    从文件名提取时间戳，返回 datetime。
    文件名：'192-168-10-91_2026-08-24_151845.xlsx'
    或：   '192.168.10.91_2026-08-24_151845.log'
    """
    stem = file_path.stem
    # 按第一个 '_' 分割
    parts = stem.split('_', 1)
    if len(parts) < 2:
        return None
    ts_part = parts[1]  # '2026-08-24_151845'
    # 再按 '_' 分割：日期 和 时间
    ts_parts = ts_part.split('_')
    if len(ts_parts) < 2:
        return None
    date_str = ts_parts[0]   # '2026-08-24'
    time_str = ts_parts[1]   # '151845'
    # 时间可能是 6 位 HHMMSS 或 4 位 HHMM
    try:
        if len(time_str) == 6:
            hh, mm, ss = int(time_str[0:2]), int(time_str[2:4]), int(time_str[4:6])
        elif len(time_str) == 4:
            hh, mm, ss = int(time_str[0:2]), int(time_str[2:4]), 0
        else:
            return None
    except ValueError:
        return None
    # 日期可能含 '-' 或 '.'
    date_clean = date_str.replace('.', '-')
    try:
        y, m, d = [int(x) for x in date_clean.split('-')]
        return datetime(y, m, d, hh, mm, ss)
    except Exception:
        return None


def parse_ip_from_filename(file_path: Path) -> Optional[str]:
    """
    从文件名提取 BMC IP，归一化为点分格式。
    '192-168-10-91_2026-08-24_151845.xlsx' → '192.168.10.91'
    """
    stem = file_path.stem
    parts = stem.split('_', 1)
    if len(parts) < 2:
        return None
    ip_raw = parts[0]
    return ip_raw.replace('-', '.')


def _ip_sort_key(ip: str):
    """'192.168.10.11' → (192, 168, 10, 11)"""
    nums = []
    for p in ip.split('.'):
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    return tuple(nums)


# ============ 目录扫描 ============

def find_stage_dirs(root_dir: Path) -> Dict:
    """
    识别 root_dir 下的关键目录：
    {
        "t0": Path or None,             # '1.T0时刻' 或含 'T0' 的目录
        "end": Path or None,            # '结束时刻'
        "loops": [(loop_num, Path), ...],  # [(1, Path('2.第1轮...')), ...]
    }
    """
    root = Path(root_dir)
    result = {"t0": None, "end": None, "loops": []}

    for d in root.iterdir():
        if not d.is_dir():
            continue
        name = d.name

        # T0 时刻
        if result["t0"] is None and "T0" in name:
            result["t0"] = d
            continue

        # 结束时刻
        if result["end"] is None and "结束" in name:
            result["end"] = d
            continue

        # 第N轮老化+检错
        m = re.search(r'第\s*(\d+)\s*轮', name)
        if m and "老化" in name:
            try:
                num = int(m.group(1))
                result["loops"].append((num, d))
            except ValueError:
                pass

    result["loops"].sort(key=lambda x: x[0])
    return result


# ============ 扫描某个目录，得到 {IP: datetime} ============

def scan_dir_for_ip_time(folder: Path) -> Dict[str, datetime]:
    """
    扫描 folder 下所有文件，返回 {BMC_IP: datetime}。
    只保留可解析的文件。
    """
    result = {}
    if not folder.exists() or not folder.is_dir():
        return result

    for f in folder.iterdir():
        if not f.is_file():
            continue
        if f.name.startswith('~$'):
            continue
        ip = parse_ip_from_filename(f)
        ts = parse_timestamp_from_filename(f)
        if ip is None or ts is None:
            continue
        # 同一 IP 多个文件时，保留最早的时间（或最后一次，看需求；这里保留最早）
        if ip not in result or ts < result[ip]:
            result[ip] = ts
    return result

def scan_bi_folder(bi_path: Path) -> Dict[str, datetime]:
    """
    兼容 BI1/EXT/* 和 BI1/* 两种结构。
    如果 BI1/EXT/ 存在，读 EXT；否则读 BI1 本身。
    """
    ext_dir = bi_path / "EXT"
    if ext_dir.exists() and ext_dir.is_dir():
        return scan_dir_for_ip_time(ext_dir)
    return scan_dir_for_ip_time(bi_path)

# ============ 主流程：收集所有时间 ============

def collect_test_times(root_dir: Path) -> Dict:
    """
    扫描 root_dir，返回：
    {
        "mode": "single" | "multi",     # 量产=single，研发=multi
        "loops": [1, 2, 3, ...],        # 实际 loop 编号
        "t0_rmt_count": 1 或 3,         # T0 时刻 RMT 次数
        "end_rmt_count": 1 或 3,        # 结束时刻 RMT 次数
        "data": {
            ip: {
                "t0_pretest_ext": datetime or None,
                "t0_pretest_smt": datetime or None,
                "t0_profile": datetime or None,
                "t0_rmt": [datetime or None, ...],       # 长度 = t0_rmt_count
                "loop": {                                # 按 loop 编号
                    1: {
                        "bi1": datetime or None,
                        "posttest1_ext": datetime or None,
                        "posttest1_smt": datetime or None,
                        "bi2": datetime or None,
                        "posttest2_ext": datetime or None,
                        "posttest2_smt": datetime or None,
                    },
                    ...
                },
                "end_profile": datetime or None,
                "end_rmt": [datetime or None, ...],      # 长度 = end_rmt_count
            },
            ...
        }
    }
    """
    root = Path(root_dir)
    stages = find_stage_dirs(root)

    t0_dir = stages["t0"]
    end_dir = stages["end"]
    loop_dirs = stages["loops"]   # [(1, Path), (2, Path), ...]

    if t0_dir is None:
        raise RuntimeError("未找到 T0时刻 目录")

    # ---- 判断 RMT 模式 ----
    def detect_rmt_mode(stage_dir: Path) -> Tuple[str, int]:
        """
        返回 (mode, count)
        mode='multi' 表示 stage_dir/RMT/1, /2, /3 结构
        mode='single' 表示 stage_dir/RMT/*.log 直接是文件
        """
        rmt_root = stage_dir / "RMT"
        if not rmt_root.exists() or not rmt_root.is_dir():
            return "single", 0
        # 看是否有 1/2/3 数字子目录
        subdirs = [d for d in rmt_root.iterdir() if d.is_dir()]
        numeric = [d for d in subdirs if d.name.isdigit()]
        if numeric:
            # 按数字排序，计数
            nums = sorted([int(d.name) for d in numeric])
            return "multi", len(nums)
        return "single", 1

    t0_rmt_mode, t0_rmt_count = detect_rmt_mode(t0_dir)
    end_rmt_mode, end_rmt_count = (detect_rmt_mode(end_dir) if end_dir else ("single", 0))

    # ---- 收集 T0 时刻 ----
    t0_data = {
        "pretest_ext": scan_dir_for_ip_time(t0_dir / "pretest" / "EXT"),
        "pretest_smt": scan_dir_for_ip_time(t0_dir / "pretest" / "SMT"),
        "profile":     scan_dir_for_ip_time(t0_dir / "profile"),
        "rmt":         [],   # list of dict, 每个 dict 是一次 RMT 的 {ip: dt}
    }
    for i in range(1, t0_rmt_count + 1):
        if t0_rmt_mode == "multi":
            rmt_dir = t0_dir / "RMT" / str(i)
        else:
            rmt_dir = t0_dir / "RMT"
        t0_data["rmt"].append(scan_dir_for_ip_time(rmt_dir))

    # ---- 收集 结束时刻 ----
    end_data = {"profile": {}, "rmt": []}
    if end_dir is not None:
        end_data["profile"] = scan_dir_for_ip_time(end_dir / "profile")
        for i in range(1, end_rmt_count + 1):
            if end_rmt_mode == "multi":
                rmt_dir = end_dir / "RMT" / str(i)
            else:
                rmt_dir = end_dir / "RMT"
            end_data["rmt"].append(scan_dir_for_ip_time(rmt_dir))

    # ---- 收集每个 loop ----
    loop_data = {}   # {loop_num: {bi1: {...}, posttest1_ext: {...}, ...}}
    for num, loop_path in loop_dirs:
        loop_data[num] = {
            "bi1":           scan_bi_folder(loop_path / "BI1"),
            "posttest1_ext": scan_dir_for_ip_time(loop_path / "posttest1" / "EXT"),
            "posttest1_smt": scan_dir_for_ip_time(loop_path / "posttest1" / "SMT"),
            "bi2":           scan_bi_folder(loop_path / "BI2"),
            "posttest2_ext": scan_dir_for_ip_time(loop_path / "posttest2" / "EXT"),
            "posttest2_smt": scan_dir_for_ip_time(loop_path / "posttest2" / "SMT"),
        }

    # ---- 合并所有 IP ----
    all_ips: Set[str] = set()
    for d in [t0_data["pretest_ext"], t0_data["pretest_smt"],
              t0_data["profile"], end_data["profile"]]:
        all_ips.update(d.keys())
    for d in t0_data["rmt"]:
        all_ips.update(d.keys())
    for d in end_data["rmt"]:
        all_ips.update(d.keys())
    for num, d in loop_data.items():
        for sub_d in d.values():
            all_ips.update(sub_d.keys())

    # ---- 组装每台服务器的数据 ----
    data = {}
    for ip in sorted(all_ips, key=_ip_sort_key):
        entry = {
            "t0_pretest_ext": t0_data["pretest_ext"].get(ip),
            "t0_pretest_smt": t0_data["pretest_smt"].get(ip),
            "t0_profile":     t0_data["profile"].get(ip),
            "t0_rmt":         [d.get(ip) for d in t0_data["rmt"]],
            "loop":           {},
            "end_profile":    end_data["profile"].get(ip),
            "end_rmt":        [d.get(ip) for d in end_data["rmt"]],
        }
        for num, d in loop_data.items():
            entry["loop"][num] = {
                "bi1":           d["bi1"].get(ip),
                "posttest1_ext": d["posttest1_ext"].get(ip),
                "posttest1_smt": d["posttest1_smt"].get(ip),
                "bi2":           d["bi2"].get(ip),
                "posttest2_ext": d["posttest2_ext"].get(ip),
                "posttest2_smt": d["posttest2_smt"].get(ip),
            }
        data[ip] = entry

    return {
        "mode": t0_rmt_mode if t0_rmt_mode == "multi" else "single",
        "loops": [num for num, _ in loop_dirs],
        "t0_rmt_count": t0_rmt_count,
        "end_rmt_count": end_rmt_count,
        "data": data,
        "has_end": end_dir is not None,
    }


# ============ 构造表头（3 行 + 合并信息） ============
def build_headers(info: Dict) -> Tuple[List[List], List[Dict]]:
    """
    构造表头 3 行 + 合并信息。

    合并规则：
    - A1:A3 纵向合并（BMCip地址）
    - T0时刻/loopN/结束时刻 大标题：行1 横向跨列
    - pretest / posttest1 / posttest2：行2 横向跨 2 列
    - RMT（研发）：行2 横向跨 N 列，行3 填 1..N
    - RMT（量产）：行2 纵向合并到行3
    - profile / BI1 / BI2：行2 纵向合并到行3
    """
    loops = info["loops"]
    t0_rmt_count = info["t0_rmt_count"]
    end_rmt_count = info["end_rmt_count"]
    has_end = info["has_end"]

    # 总列数
    total_cols = 1
    t0_cols = 2 + 1 + t0_rmt_count
    total_cols += t0_cols
    loop_cols_per = 6
    total_cols += len(loops) * loop_cols_per
    end_cols = (1 + end_rmt_count) if has_end else 0
    total_cols += end_cols

    row1 = [None] * total_cols
    row2 = [None] * total_cols
    row3 = [None] * total_cols
    merges = []

    # ---- A 列：BMCip地址（纵向） ----
    row1[0] = "BMCip地址"
    merges.append({"range": "A1:A3", "value": "BMCip地址"})

    col = 1

    # ---- T0 时刻 ----
    t0_start = col
    row1[t0_start] = "T0时刻"
    merges.append({
        "range": f"{_col_letter(t0_start+1)}1:{_col_letter(t0_start+t0_cols)}1",
        "value": "T0时刻",
    })

    # pretest（行2 横向跨 2 列）
    row2[t0_start] = "pretest"
    merges.append({
        "range": f"{_col_letter(t0_start+1)}2:{_col_letter(t0_start+2)}2",
        "value": "pretest",
    })
    row3[t0_start] = "EXT"
    row3[t0_start + 1] = "SMT"

    # profile（行2 纵向合并到行3）
    prof_col = t0_start + 2
    row2[prof_col] = "profile"
    merges.append({
        "range": f"{_col_letter(prof_col+1)}2:{_col_letter(prof_col+1)}3",
        "value": "profile",
    })

    # RMT
    rmt_col = t0_start + 3
    row2[rmt_col] = "RMT"
    if t0_rmt_count > 1:
        # 研发：横向跨 N 列，行3 填 1..N
        merges.append({
            "range": f"{_col_letter(rmt_col+1)}2:{_col_letter(rmt_col+t0_rmt_count)}2",
            "value": "RMT",
        })
        for i in range(t0_rmt_count):
            row3[rmt_col + i] = str(i + 1)
    else:
        # 量产：纵向合并
        merges.append({
            "range": f"{_col_letter(rmt_col+1)}2:{_col_letter(rmt_col+1)}3",
            "value": "RMT",
        })

    col = t0_start + t0_cols

    # ---- 每个 loop ----
    for loop_num in loops:
        loop_start = col
        row1[loop_start] = f"loop{loop_num}"
        merges.append({
            "range": f"{_col_letter(loop_start+1)}1:{_col_letter(loop_start+loop_cols_per)}1",
            "value": f"loop{loop_num}",
        })

        # BI1（纵向合并）
        bi1_col = loop_start
        row2[bi1_col] = "BI1"
        merges.append({
            "range": f"{_col_letter(bi1_col+1)}2:{_col_letter(bi1_col+1)}3",
            "value": "BI1",
        })

        # posttest1（横向跨 2 列）
        pt1_col = loop_start + 1
        row2[pt1_col] = "posttest1"
        merges.append({
            "range": f"{_col_letter(pt1_col+1)}2:{_col_letter(pt1_col+2)}2",
            "value": "posttest1",
        })
        row3[pt1_col] = "EXT"
        row3[pt1_col + 1] = "SMT"

        # BI2（纵向合并）
        bi2_col = loop_start + 3
        row2[bi2_col] = "BI2"
        merges.append({
            "range": f"{_col_letter(bi2_col+1)}2:{_col_letter(bi2_col+1)}3",
            "value": "BI2",
        })

        # posttest2（横向跨 2 列）
        pt2_col = loop_start + 4
        row2[pt2_col] = "posttest2"
        merges.append({
            "range": f"{_col_letter(pt2_col+1)}2:{_col_letter(pt2_col+2)}2",
            "value": "posttest2",
        })
        row3[pt2_col] = "EXT"
        row3[pt2_col + 1] = "SMT"

        col += loop_cols_per

    # ---- 结束时刻 ----
    if has_end:
        end_start = col
        row1[end_start] = "结束时刻"
        merges.append({
            "range": f"{_col_letter(end_start+1)}1:{_col_letter(end_start+end_cols)}1",
            "value": "结束时刻",
        })

        # profile（纵向合并）
        prof_col = end_start
        row2[prof_col] = "profile"
        merges.append({
            "range": f"{_col_letter(prof_col+1)}2:{_col_letter(prof_col+1)}3",
            "value": "profile",
        })

        # RMT
        rmt_col = end_start + 1
        row2[rmt_col] = "RMT"
        if end_rmt_count > 1:
            merges.append({
                "range": f"{_col_letter(rmt_col+1)}2:{_col_letter(rmt_col+end_rmt_count)}2",
                "value": "RMT",
            })
            for i in range(end_rmt_count):
                row3[rmt_col + i] = str(i + 1)
        else:
            merges.append({
                "range": f"{_col_letter(rmt_col+1)}2:{_col_letter(rmt_col+1)}3",
                "value": "RMT",
            })

    return [row1, row2, row3], merges


def build_data_rows(info: Dict) -> List[List]:
    """
    根据 collect_test_times 的结果，构造数据行。
    每行：[IP, dt, dt, ..., dt]
    """
    loops = info["loops"]
    t0_rmt_count = info["t0_rmt_count"]
    end_rmt_count = info["end_rmt_count"]
    has_end = info["has_end"]
    data = info["data"]

    rows = []
    for ip in sorted(data.keys(), key=_ip_sort_key):
        entry = data[ip]
        row = [ip]
        # T0
        row.append(entry["t0_pretest_ext"])
        row.append(entry["t0_pretest_smt"])
        row.append(entry["t0_profile"])
        for i in range(t0_rmt_count):
            row.append(entry["t0_rmt"][i] if i < len(entry["t0_rmt"]) else None)
        # loops
        for loop_num in loops:
            loop_entry = entry["loop"].get(loop_num, {})
            row.append(loop_entry.get("bi1"))
            row.append(loop_entry.get("posttest1_ext"))
            row.append(loop_entry.get("posttest1_smt"))
            row.append(loop_entry.get("bi2"))
            row.append(loop_entry.get("posttest2_ext"))
            row.append(loop_entry.get("posttest2_smt"))
        # 结束时刻
        if has_end:
            row.append(entry["end_profile"])
            for i in range(end_rmt_count):
                row.append(entry["end_rmt"][i] if i < len(entry["end_rmt"]) else None)
        rows.append(row)
    return rows


# ============ 工具函数 ============

def _col_letter(col_idx_1based: int) -> str:
    """列号转字母，1→A，2→B，...，27→AA"""
    result = ""
    n = col_idx_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result