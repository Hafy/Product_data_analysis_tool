
import re
import pandas as pd
from pathlib import Path

# 列名必须与 Excel 模板表头完全一致（包括空格）
RMT_COLUMNS = [
    'BMC IP', 'BIOS Version', 'MPN', 'RCD', 'PMIC', 'Date Code',
    'SN', 'DIMM(Physical)', 'DIMM(Logical)',
    'RxDly-', 'RxDly+', 'RxVrf-', 'RxVrf+',
    'TxDly-', 'TxDly+', 'TxVrf-', 'TxVrf+'
]

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

    # ---------- 1. 解析 DIMM Info 块 ----------
    dimm_info_match = re.search(
        r'\[Display Dimm Info\] Start(.*?)\[Display Dimm Info\]\.\.\.End',
        content, re.DOTALL
    )
    if not dimm_info_match:
        log("⚠️ 未找到 [Display Dimm Info] 块")
        return pd.DataFrame(columns=RMT_COLUMNS)

    dimm_info_text = dimm_info_match.group(1)
    log("✅ 找到 DIMM Info 块，开始解析...")

    # 按 Socket 分割
    socket_blocks = re.split(r'\| Socket \d+ \|', dimm_info_text)
    physical_props = {}

    for socket_idx, block in enumerate(socket_blocks[1:], start=0):
        log(f"  📌 处理 Socket {socket_idx}")
        
        lines = [line.strip() for line in block.splitlines() if line.strip().startswith('|')]
        if not lines:
            log(f"      ⚠️ Socket {socket_idx} 无有效行")
            continue

        # 先找到 Physical 行，确定该 Socket 有多少个 DIMM
        physical_line = None
        for line in lines:
            if 'Physical' in line:
                physical_line = line
                break

        if not physical_line:
            log(f"      ⚠️ Socket {socket_idx} 未找到 Physical 行")
            continue

        # 从 Physical 行提取 DIMM 编号列表
        dimm_ids = re.findall(r'DIMM\s+(\d{3})', physical_line)
        num_dimms = len(dimm_ids)
        log(f"      Physical 行: {physical_line}")
        log(f"      Socket {socket_idx} 有 {num_dimms} 个 DIMM: {dimm_ids}")

        if num_dimms == 0:
            continue

        # 初始化 num_dimms 个 Channel 的字典
        channels = [{} for _ in range(num_dimms)]

        # 解析每一行，提取属性
        for line in lines:
            parts = [p.strip() for p in line.split('|')]
            parts = parts[1:-1]
            
            # 有效行应该有 (1 + num_dimms) 列（Slot + 每个DIMM一列）
            # 但物理行可能有更多列，我们只取前 num_dimms 个 DIMM
            if len(parts) < 1 + num_dimms:
                continue
            
            first_val = parts[1] if len(parts) > 1 else ""
            
            # ---- 跳过 DIMM 厂商行 ----
            if first_val.startswith('DIMM:'):
                continue
            
            # ---- 识别属性行 ----
            elif 'RCD' in first_val:
                for i in range(num_dimms):
                    val = parts[i+1].split(':')[-1].strip()
                    channels[i]['RCD'] = val
                log(f"      RCD 行: {[ch.get('RCD', '') for ch in channels]}")
                
            elif 'PMIC' in first_val:
                for i in range(num_dimms):
                    val = parts[i+1].split(':')[-1].strip()
                    channels[i]['PMIC'] = val
                log(f"      PMIC 行: {[ch.get('PMIC', '') for ch in channels]}")
                
            elif first_val.startswith('ww') and '20' in first_val:
                for i in range(num_dimms):
                    channels[i]['Date Code'] = parts[i+1].strip()
                log(f"      Date Code 行: {[ch.get('Date Code', '') for ch in channels]}")
                
            elif first_val.startswith('JTR') or ('JTR' in first_val and len(first_val) < 30):
                for i in range(num_dimms):
                    channels[i]['MPN'] = parts[i+1].strip()
                log(f"      MPN 行: {[ch.get('MPN', '') for ch in channels]}")
                
            elif re.match(r'^[0-9a-f]{16}$', first_val) or first_val.startswith('ff'):
                for i in range(num_dimms):
                    channels[i]['SN'] = parts[i+1].strip()
                log(f"      SN 行: {[ch.get('SN', '') for ch in channels]}")
            else:
                # 其他行跳过
                pass

        # 将解析到的 DIMM 属性存入 physical_props
        for i, dimm_num in enumerate(dimm_ids):
            if i < num_dimms:
                key = f"DIMM{dimm_num}"
                # ---- 新增检测逻辑 ----
                mpn = channels[i].get('MPN', '')
                rcd = channels[i].get('RCD', '')
                if ('NO DIMM' in mpn.upper()) or ('NO DIMM' in rcd.upper()) or (mpn == '' and rcd == ''):
                    #log(f"      ⚠ DIMM {dimm_num} 无内存（NO DIMM 或空属性），跳过")
                    continue  # 跳过该槽位，不加入 physical_props

                physical_props[key] = {
                    'Physical': key,
                    'MPN': channels[i].get('MPN', ''),
                    'RCD': channels[i].get('RCD', ''),
                    'PMIC': channels[i].get('PMIC', ''),
                    'Date Code': channels[i].get('Date Code', ''),
                    'SN': channels[i].get('SN', ''),
                }
                log(f"          → {key}: MPN={physical_props[key]['MPN']}, RCD={physical_props[key]['RCD']}, PMIC={physical_props[key]['PMIC']}, Date={physical_props[key]['Date Code']}, SN={physical_props[key]['SN']}")

    log(f"📦 总共解析出 {len(physical_props)} 个 Physical DIMM: {list(physical_props.keys())}")

    # ---------- 2. 解析 RMT 测试数据 ----------
    rmt_blocks = re.finditer(
        r'\+\+\+ SOC-DRAM Level DX Margin Test \+\+\+(.*?)(?=\+\+\+|\Z)',
        content, re.DOTALL
    )

    rows = []
    block_count = 0
    for block_match in rmt_blocks:
        block_count += 1
        block_text = block_match.group(1)
        dimm_match = re.search(r'DIMM(\d{3})\s+Rank:', block_text)
        if not dimm_match:
            log(f"  ⚠️ RMT块 {block_count} 未找到 DIMM 编号")
            continue

        dimm_num = dimm_match.group(1)
        key = f"DIMM{dimm_num}"
        if key not in physical_props:
            #log(f"   ⚠️RMT 块 {block_count} 匹配到 {key}, 但该DIMM 未安装， 跳过")
            continue
        props = physical_props.get(key, {})
        if not props:
            log(f"  ⚠️ 未在 DIMM Info 中找到 {key} 的属性，使用空值")
            props = {
                'Physical': key,
                'MPN': '',
                'RCD': '',
                'PMIC': '',
                'Date Code': '',
                'SN': ''
            }
        else:
            log(f"  ✅ RMT块 {block_count} 匹配到 {key}, 属性: MPN={props.get('MPN')}, RCD={props.get('RCD')}, PMIC={props.get('PMIC')}, Date={props.get('Date Code')}, SN={props.get('SN')}")

        data_pattern = re.compile(
            r'(S\d+\.C\d+\.SC\d+\.D\d+\.R\d+):\s+'
            r'([-]?\d+)\s+([-]?\d+)\s+([-]?\d+)\s+([-]?\d+)\s+'
            r'([-]?\d+)\s+([-]?\d+)\s+([-]?\d+)\s+([-]?\d+)'
        )
        data_lines = data_pattern.findall(block_text)
        #log(f"      RMT数据行数: {len(data_lines)}")

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
            log(f"          → {logical_id}: {vals}")

    #log(f"📊 总共提取 RMT 数据行数: {len(rows)}")

    if not rows:
        return pd.DataFrame(columns=RMT_COLUMNS)

    df = pd.DataFrame(rows, columns=RMT_COLUMNS)
    #log(f"✅ 最终 DataFrame 形状: {df.shape}")
    return df
