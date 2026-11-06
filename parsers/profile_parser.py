import pandas as pd
import re
from pathlib import Path

PROFILE_COLUMNS = ['BMC IP', 'Type', 'Skt', 'Ch', 'SN', 'DIMM(Physical)',
                   'Vdd', 'Vddq', 'Vpp', 'tWR', 'tRCD', 'tRP', 'tRAS', 'tRFC', 'tDelay']


def parse_profile_log(file_path: Path, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.splitlines()
    except Exception as e:
        log(f"❌ 读取文件失败: {e}")
        return pd.DataFrame(columns=PROFILE_COLUMNS)

    ip_raw = file_path.stem.split('_')[0] if '_' in file_path.stem else file_path.stem
    bmc_ip = ip_raw.replace('-', '.')
    log(f"📄 开始解析PROFILE文件: {file_path.name}, BMC IP={bmc_ip}")

    # ---------- 1. 提取 DIMM Info 映射 ----------
    dimm_map = {}
    dimm_match = re.search(r'\[Display Dimm Info\] Start(.*?)\[Display Dimm Info\]\.\.\.End', content, re.DOTALL)
    if dimm_match:
        dimm_text = dimm_match.group(1)
        socket_blocks = re.split(r'\| Socket \d+ \|', dimm_text)
        for socket_idx, block in enumerate(socket_blocks[1:], start=0):
            lines_block = [line.strip() for line in block.splitlines() if line.strip().startswith('|')]
            
            # 找 Physical 行
            physical_line = None
            for line in reversed(lines_block):
                if 'Physical' in line:
                    physical_line = line
                    break
                    
            if not physical_line:
                continue
                
            sn_values = [None] * 8
            physical_values = [None] * 8
            
            # 找 SN 行
            sn_line = None
            for line in lines_block:
                parts = [p.strip() for p in line.split('|')][1:-1]
                if len(parts) < 2:
                    continue
                if any(re.match(r'^[0-9a-fA-F]{16,24}$', cell) for cell in parts[1:9]):
                    sn_line = line
                    break
            
            if sn_line:
                sn_parts = [p.strip() for p in sn_line.split('|')][1:-1]
                if len(sn_parts) >= 8:
                    for ch in range(8):
                        sn_values[ch] = sn_parts[1+ch].strip()
                        
            phys_parts = [p.strip() for p in physical_line.split('|')][1:-1]
            if len(phys_parts) >= 8:
                for ch in range(8):
                    cell_val = phys_parts[1+ch].strip()
                    m = re.search(r'DIMM\s*(\d{3})', cell_val)
                    if m:
                        physical_values[ch] = f"DIMM{m.group(1)}"

            for ch in range(8):
                sn = sn_values[ch]
                phy = physical_values[ch]
                if sn and phy:
                    dimm_map[(socket_idx, ch)] = (sn, phy)

    # ---------- 2. 提取 OriginTimeCfg ----------
    origin_lines = []
    in_origin = False
    for i, line in enumerate(lines):
        if 'Print OriginTimeCfg' in line:
            in_origin = True
            continue
        if in_origin and 'Current Timing Setting:' in line:
            for j in range(i+1, len(lines)):
                nxt = lines[j].strip()
                if not nxt or 'Print' in nxt:
                    break
                origin_lines.append(nxt)
            break

    if not origin_lines:
        log("⚠️ 未找到 Origin 数据")
        return pd.DataFrame(columns=PROFILE_COLUMNS)

    origin_data = {}
    for line in origin_lines:
        parts = line.split()
        if any(c.isalpha() for c in parts) and not all(p.lstrip('-').isdigit() for p in parts):
            continue
        if len(parts) < 11:
            continue
        try:
            skt, ch = int(parts[0]), int(parts[1])
            vals = list(map(int, parts[2:11]))
            origin_data[(skt, ch)] = vals
        except ValueError:
            continue

    # ---------- 3. 提取最后一个 TimeMarginResult ----------
    result_indices = [i for i, line in enumerate(lines) if 'Print TimeMarginResult' in line]
    if not result_indices:
        log("⚠️ 未找到 TimeMarginResult")
        return pd.DataFrame(columns=PROFILE_COLUMNS)

    result_lines = []
    for j in range(result_indices[-1] + 1, len(lines)):
        nxt = lines[j].strip()
        if not nxt or 'Profile Test' in nxt or 'Print' in nxt:
            break
        result_lines.append(nxt)

    result_data = {}
    for line in result_lines:
        parts = line.split()
        if any(c.isalpha() for c in parts) and not all(p.lstrip('-').isdigit() for p in parts):
            continue
        if len(parts) < 11:
            continue
        try:
            skt, ch = int(parts[0]), int(parts[1])
            vals = list(map(int, parts[2:11]))
            result_data[(skt, ch)] = vals
        except ValueError:
            continue

    # ---------- 4. 生成 Origin 和 Result 行 ----------
    param_names = ['Vdd', 'Vddq', 'Vpp', 'tWR', 'tRCD', 'tRP', 'tRAS', 'tRFC', 'tDelay']
    rows = []

    for (skt, ch), origin_vals in origin_data.items():
        if (skt, ch) not in result_data:
            continue

        result_vals = result_data[(skt, ch)]
        sn, physical = dimm_map.get((skt, ch), (None, None))

        row_origin = {
            'BMC IP': bmc_ip,
            'Type': 'Origin',
            'Skt': skt,
            'Ch': ch,
            'SN': sn,
            'DIMM(Physical)': physical,
        }
        for i, name in enumerate(param_names):
            row_origin[name] = origin_vals[i]
        rows.append(row_origin)

        row_result = {
            'BMC IP': bmc_ip,
            'Type': 'Result',
            'Skt': skt,
            'Ch': ch,
            'SN': sn,
            'DIMM(Physical)': physical,
        }
        for i, name in enumerate(param_names):
            row_result[name] = result_vals[i]
        rows.append(row_result)

    if not rows:
        return pd.DataFrame(columns=PROFILE_COLUMNS)

    return pd.DataFrame(rows, columns=PROFILE_COLUMNS)