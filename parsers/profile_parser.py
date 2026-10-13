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

    # ---------- 1. 提取 DIMM Info 映射 (Skt, Ch) -> (SN, DIMM Physical) ----------
    # ---------- 1. 提取 DIMM Info 映射 (Skt, Ch) -> (SN, DIMM Physical) ----------
    dimm_map = {}
    dimm_match = re.search(r'\[Display Dimm Info\] Start(.*?)\[Display Dimm Info\]\.\.\.End', content, re.DOTALL)
    if dimm_match:
        dimm_text = dimm_match.group(1)
        socket_blocks = re.split(r'\| Socket \d+ \|', dimm_text)
        for socket_idx, block in enumerate(socket_blocks[1:], start=0):
            lines_block = [line.strip() for line in block.splitlines() if line.strip().startswith('|')]
            if not lines_block:
                continue
            sn_values = [None] * 8
            physical_values = [None] * 8
            for line in lines_block:
                parts = [p.strip() for p in line.split('|')]
                parts = parts[1:-1]   # 去掉首尾空
                if len(parts) <9:
                    continue

                # 处理SN行：单元格内是16位hex SN (ff开头)
                has_sn_line = False
                for cell in parts:
                    if re.match(r'^[0-9a-fA-F]{16}$', cell) or cell.startswith("ff"):
                        has_sn_line = True
                        break
                if has_sn_line:
                    # parts[1] ~ parts[8] 对应 ch0~ch7
                    for ch in range(8):
                        cell_val = parts[1+ch].strip()
                        if re.match(r'^[0-9a-fA-F]{16}$', cell_val) or cell_val.startswith("ff"):
                            sn_values[ch] = cell_val
                    continue

                # 处理Physical行
                if "Physical" in line:
                    for ch in range(8):
                        cell_val = parts[1+ch].strip()
                        m = re.search(r'DIMM\s*(\d{3})', cell_val)
                        if m:
                            physical_values[ch] = f"DIMM{m.group(1)}"
                    continue

            # 组装map：socket_idx + ch → (sn, physical)
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

    if not result_lines:
        log("⚠️ 未找到 Result 数据")
        return pd.DataFrame(columns=PROFILE_COLUMNS)

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

    # ---------- 4. 生成 Origin 和 Result 行（加入 SN 和 DIMM Physical） ----------
    param_names = ['Vdd', 'Vddq', 'Vpp', 'tWR', 'tRCD', 'tRP', 'tRAS', 'tRFC', 'tDelay']
    rows = []

    for (skt, ch), origin_vals in origin_data.items():
        if (skt, ch) not in result_data:
            log(f"⚠️ Skt={skt}, Ch={ch} 在 Result 中不存在，跳过")
            continue

        result_vals = result_data[(skt, ch)]
        sn, physical = dimm_map.get((skt, ch), (None, None))

        # Origin 行
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

        # Result 行
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

        log(f"✅ Skt={skt}, Ch={ch}: SN={sn}, DIMM={physical}, Origin={origin_vals}, Result={result_vals}")

    if not rows:
        log("⚠️ 没有生成任何数据")
        return pd.DataFrame(columns=PROFILE_COLUMNS)

    df = pd.DataFrame(rows, columns=PROFILE_COLUMNS)
    return df