import re
import pandas as pd
from pathlib import Path

RMT_COLUMNS = [
    'BMC IP', 'BIOS Version', 'MPN', 'RCD', 'PMIC', 'Date Code',
    'SN', 'DIMM(Physical)', 'DIMM(Logical)',
    'RxDly-', 'RxDly+', 'RxVrf-', 'RxVrf+',
    'TxDly-', 'TxDly+', 'TxVrf-', 'TxVrf+'
]

def is_uppercase_mpn(text: str) -> bool:
    """判断文本是否像全大写 MPN，例如 KTQDR5Q8E-HAR0A"""
    # 必须包含字母，且字母全部是大写，且没有小写字母
    has_letter = bool(re.search(r'[A-Za-z]', text))
    has_lower = bool(re.search(r'[a-z]', text))
    return has_letter and not has_lower


def parse_rmt_log(file_path: Path, bios_version: str, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    content = file_path.read_text(encoding='utf-8', errors='ignore')
    bmc_ip_raw = file_path.stem.split('_')[0] if '_' in file_path.stem else file_path.stem
    bmc_ip = bmc_ip_raw.replace('-', '.')
    log(f"📄 开始解析文件: {file_path.name}, BMC IP={bmc_ip}")

    dimm_info_match = re.search(
        r'\[Display Dimm Info\] Start(.*?)\[Display Dimm Info\]\.\.\.End',
        content, re.DOTALL
    )
    if not dimm_info_match:
        log("⚠️ 未找到 [Display Dimm Info] 块")
        return pd.DataFrame(columns=RMT_COLUMNS)

    dimm_info_text = dimm_info_match.group(1)
    socket_blocks = re.split(r'\| Socket \d+ \|', dimm_info_text)
    physical_props = {}

    for socket_idx, block in enumerate(socket_blocks[1:], start=0):
        log(f"  📌 处理 Socket {socket_idx}")

        raw_lines = [line.strip() for line in block.splitlines() if line.strip().startswith('|')]
        if not raw_lines:
            continue

        # 找 Physical 行
        physical_line = None
        for line in reversed(raw_lines):
            if 'Physical' in line:
                physical_line = line
                break

        if not physical_line:
            continue

        dimm_ids = re.findall(r'DIMM\s*(\d{3})', physical_line)
        num_dimms = len(dimm_ids)
        log(f"      Socket {socket_idx} 有 {num_dimms} 个 DIMM: {dimm_ids}")

        if num_dimms == 0:
            continue

        channels = [{} for _ in range(num_dimms)]
        
        mpn_line = None
        sn_line = None
        
        # 1. 找 SN 行（特征：包含 16~24 位十六进制）
        for line in raw_lines:
            parts = [p.strip() for p in line.split('|')][1:-1]
            if len(parts) < 2:
                continue
            
            if any(re.match(r'^[0-9a-fA-F]{16,24}$', cell) for cell in parts[1:num_dimms+1]):
                sn_line = line
                break

        # 2. 找 MPN 行（特征：全大写字母，且在 SN 行之上）
        if sn_line:
            sn_idx = raw_lines.index(sn_line)
            # 从 SN 行往上找
            for i in range(sn_idx - 1, -1, -1):
                prev_parts = [p.strip() for p in raw_lines[i].split('|')][1:-1]
                if len(prev_parts) < 2:
                    continue
                # 如果这行的数据部分包含全大写的 MPN 特征
                if any(is_uppercase_mpn(cell) for cell in prev_parts[1:num_dimms+1]):
                    mpn_line = raw_lines[i]
                    break

        # 解析 MPN
        if mpn_line:
            mpn_parts = [p.strip() for p in mpn_line.split('|')][1:-1]
            for i in range(num_dimms):
                if len(mpn_parts) > i + 1:
                    channels[i]['MPN'] = mpn_parts[i + 1].strip()
            log(f"      MPN 行: {[ch.get('MPN', '') for ch in channels]}")
        else:
            log(f"      ⚠️ Socket {socket_idx} 无法定位 MPN 行")

        # 解析 SN
        if sn_line:
            sn_parts = [p.strip() for p in sn_line.split('|')][1:-1]
            for i in range(num_dimms):
                if len(sn_parts) > i + 1:
                    channels[i]['SN'] = sn_parts[i + 1].strip()
            log(f"      SN 行: {[ch.get('SN', '') for ch in channels]}")
        else:
            log(f"      ⚠️ Socket {socket_idx} 无法定位 SN 行")

        # 解析 RCD / PMIC / Date Code
        for line in raw_lines:
            parts = [p.strip() for p in line.split('|')][1:-1]
            if len(parts) < 1 + num_dimms:
                continue

            first_val = parts[1] if len(parts) > 1 else ""
            first_val_upper = first_val.upper()

            if 'RCD' in first_val_upper:
                for i in range(num_dimms):
                    channels[i]['RCD'] = parts[i + 1].split(':')[-1].strip()
            elif 'PMIC' in first_val_upper:
                for i in range(num_dimms):
                    channels[i]['PMIC'] = parts[i + 1].split(':')[-1].strip()
            elif first_val.lower().startswith('ww') and '20' in first_val:
                for i in range(num_dimms):
                    channels[i]['Date Code'] = parts[i + 1].strip()

        # 组装 physical_props
        for i, dimm_num in enumerate(dimm_ids):
            if i < num_dimms:
                key = f"DIMM{dimm_num}"
                mpn = channels[i].get('MPN', '')
                rcd = channels[i].get('RCD', '')

                if ('NO DIMM' in mpn.upper()) or ('NO DIMM' in rcd.upper()) or (mpn == '' and rcd == ''):
                    continue

                physical_props[key] = {
                    'Physical': key,
                    'MPN': mpn,
                    'RCD': channels[i].get('RCD', ''),
                    'PMIC': channels[i].get('PMIC', ''),
                    'Date Code': channels[i].get('Date Code', ''),
                    'SN': channels[i].get('SN', ''),
                }
                log(f"          → {key}: MPN={physical_props[key]['MPN']}, SN={physical_props[key]['SN']}")

    # ---------- 解析 RMT 测试数据 ----------
    rmt_blocks = re.finditer(
        r'\+\+\+ SOC-DRAM Level DX Margin Test \+\+\+(.*?)(?=\+\+\+|\Z)',
        content, re.DOTALL
    )

    rows = []
    for block_match in rmt_blocks:
        block_text = block_match.group(1)
        dimm_match = re.search(r'DIMM(\d{3})\s+Rank:', block_text)
        if not dimm_match:
            continue

        dimm_num = dimm_match.group(1)
        key = f"DIMM{dimm_num}"
        if key not in physical_props:
            continue

        props = physical_props.get(key, {})
        
        data_pattern = re.compile(
            r'(S\d+\.C\d+\.SC\d+\.D\d+\.R\d+):\s+'
            r'([-]?\d+)\s+([-]?\d+)\s+([-]?\d+)\s+([-]?\d+)\s+'
            r'([-]?\d+)\s+([-]?\d+)\s+([-]?\d+)\s+([-]?\d+)'
        )
        data_lines = data_pattern.findall(block_text)

        for match in data_lines:
            logical_id = match[0]
            vals = list(map(int, match[1:]))
            row = {
                'BMC IP': bmc_ip,
                'BIOS Version': bios_version,
                'MPN': props.get('MPN', ''),
                'RCD': props.get('RCD', ''),
                'PMIC': props.get('PMIC', ''),
                'Date Code': props.get('Date Code', ''),
                'SN': props.get('SN', ''),
                'DIMM(Physical)': props.get('Physical', key),
                'DIMM(Logical)': logical_id,
                'RxDly-': vals[0],
                'RxDly+': vals[1],
                'RxVrf-': vals[2],
                'RxVrf+': vals[3],
                'TxDly-': vals[4],
                'TxDly+': vals[5],
                'TxVrf-': vals[6],
                'TxVrf+': vals[7],
            }
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=RMT_COLUMNS)

    return pd.DataFrame(rows, columns=RMT_COLUMNS)