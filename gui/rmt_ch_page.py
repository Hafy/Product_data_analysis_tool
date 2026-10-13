# gui/rmt_ch_page.py
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QLabel, QProgressBar, QTextEdit, QMessageBox,
    QFileDialog,
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QTextCursor

from parsers.rmt_ch_parser import (
    parse_rmt_folder_for_ch, build_min_max_avg_rows,
    build_ch_sheet, compute_ch_stats, CH_NUMERIC_COLS,
    DISPLAY_COLS, SRC_COLS,
)
from utils.excel_helper import write_ch_analysis_to_excel
from utils.file_logger import FileLogger
import pandas as pd
import traceback
from utils.log_highlight import append_highlighted

class RmtChWorker(QThread):
    log_msg = Signal(str)          # 关键事件（GUI 显示）
    warn_msg = Signal(str)         # 警告（GUI 显示，黄色可自行 CSS）
    finished = Signal()
    error = Signal(str)

    def __init__(self, root_dir: Path, bios_version: str):
        super().__init__()
        self.root_dir = Path(root_dir)
        self.bios_version = bios_version
        self.has_error = False
        self.output_path = None
        self.log_path = None
        self.file_logger = None

    # ------------------ 工具 ------------------
    def _gui_info(self, msg):
        self.log_msg.emit(msg)

    def _gui_warn(self, level, msg):
        """level: 'warn' / 'error'"""
        if level == 'error':
            self.warn_msg.emit(f"❌ {msg}")
        else:
            self.warn_msg.emit(f"⚠️ {msg}")

    def _file_info(self, msg):
        """详细日志写文件"""
        if self.file_logger:
            self.file_logger.info(msg)

    def _find_rmt_root(self, stage_dir: Path):
        rmt = stage_dir / "RMT"
        if rmt.exists() and rmt.is_dir():
            return rmt
        return None

    def _detect_rmt_mode(self, rmt_root: Path):
        """
        返回 (mode, round_list)
        mode='multi'：RMT/1, RMT/2, RMT/3 结构（研发）
        mode='single'：RMT/*.log 直接是文件（量产）
        round_list: multi 时是 [1,2,3]，single 时是 [1]
        """
        if not rmt_root.exists() or not rmt_root.is_dir():
            return "single", []
        subdirs = [d for d in rmt_root.iterdir() if d.is_dir()]
        numeric = sorted([int(d.name) for d in subdirs if d.name.isdigit()])
        if numeric:
            return "multi", numeric
        # 否则是 single（直接是文件）
        return "single", [1]

    def _parse_rmt_rounds(self, rmt_root: Path, stage_label: str):
        """
        自动识别 single/multi，返回 [(round_idx, df), ...]
        """
        mode, rounds = self._detect_rmt_mode(rmt_root)
        self._gui_info(f"   🔧 {stage_label} RMT 模式: {mode}（轮次 {rounds}）")
        self._file_info(f"{stage_label} RMT mode={mode}, rounds={rounds}")

        results = []
        for i in rounds:
            if mode == "multi":
                sub = rmt_root / str(i)
                display_label = f"{stage_label} RMT/{i}"
            else:
                sub = rmt_root
                display_label = f"{stage_label} RMT"

            if not sub.exists() or not sub.is_dir():
                self._gui_info(f"   ⚠️ {display_label} 不存在，跳过")
                continue

            t0 = datetime.now()
            self._gui_info(f"   📂 解析 {display_label} ...")
            df = parse_rmt_folder_for_ch(
                sub, self.bios_version,
                log_callback=self.file_logger.info if self.file_logger else None,
                gui_warn=self._gui_warn,
            )
            elapsed = (datetime.now() - t0).total_seconds()
            if df.empty:
                self._gui_info(f"      ⚠️ 无有效数据（耗时 {elapsed:.1f}s）")
                continue
            self._gui_info(f"      ✅ {len(df)} 行（耗时 {elapsed:.1f}s）")
            results.append((i, df))
        return results

    # ------------------ 主流程 ------------------
    def run(self):
        self.file_logger = FileLogger(prefix="rmt_ch")
        self.log_path = self.file_logger.log_path
        self.file_logger.info(f"===== RMT-CH 分析开始 =====")
        self.file_logger.info(f"root_dir = {self.root_dir}")
        self.file_logger.info(f"bios_version = {self.bios_version}")

        try:
            t0_dir, end_dir = None, None
            for d in self.root_dir.iterdir():
                if not d.is_dir():
                    continue
                if "T0" in d.name:
                    t0_dir = d
                elif "结束" in d.name:
                    end_dir = d

            if t0_dir is None:
                self.has_error = True
                self.error.emit("未找到 T0时刻 目录")
                self.file_logger.error("未找到 T0时刻 目录")
                self.finished.emit()
                return

            self._gui_info(f"🔍 解析 T0时刻: {t0_dir.name}")
            t0_rmt = self._find_rmt_root(t0_dir)
            if t0_rmt is None:
                self.has_error = True
                self.error.emit(f"{t0_dir.name} 下未找到 RMT 目录")
                self.file_logger.error("T0 RMT 目录未找到")
                self.finished.emit()
                return
            t0_rounds = self._parse_rmt_rounds(t0_rmt, "T0时刻")

            end_rounds = []
            if end_dir is not None:
                self._gui_info(f"🔍 解析 结束时刻: {end_dir.name}")
                end_rmt = self._find_rmt_root(end_dir)
                if end_rmt is not None:
                    end_rounds = self._parse_rmt_rounds(end_rmt, "结束时刻")
                else:
                    self._gui_info(f"   ⚠️ {end_dir.name} 下未找到 RMT 目录")
            else:
                self._gui_info("ℹ️ 未找到 结束时刻 目录，只处理 T0时刻")

            if not t0_rounds and not end_rounds:
                self.has_error = True
                self.error.emit("没有任何有效 RMT 数据")
                self.file_logger.error("没有任何有效 RMT 数据")
                self.finished.emit()
                return

            dataframes = {}
            footnotes = {}
            header_sheets = set()
            bold_rows_map = {}
            diff_special = None

            # ① T0-1_RMT 等
            # 判断是 single 还是 multi
            t0_mode = "multi" if len(t0_rounds) > 1 else "single"
            for idx, df in t0_rounds:
                df_disp = df.drop(columns=['Skt', 'Ch'], errors='ignore')
                if t0_mode == "multi":
                    sheet_name = f"T0-{idx}_RMT"
                else:
                    sheet_name = "T0_RMT"
                dataframes[sheet_name] = build_min_max_avg_rows(df_disp, CH_NUMERIC_COLS)
                footnotes[sheet_name] = "说明：末尾三行为 Min / Max / Ave（绝对值）"
                header_sheets.add(sheet_name)

            # ② 结束时刻-1_RMT 等
            end_mode = "multi" if len(end_rounds) > 1 else "single"
            for idx, df in end_rounds:
                df_disp = df.drop(columns=['Skt', 'Ch'], errors='ignore')
                if end_mode == "multi":
                    sheet_name = f"结束时刻-{idx}_RMT"
                else:
                    sheet_name = "结束时刻_RMT"
                dataframes[sheet_name] = build_min_max_avg_rows(df_disp, CH_NUMERIC_COLS)
                footnotes[sheet_name] = "说明：末尾三行为 Min / Max / Ave（绝对值）"
                header_sheets.add(sheet_name)

            # ③ CH 汇总
            def build_stage_ch_sheets(rounds, stage_label):
                all_chs = set()
                for _, df in rounds:
                    if 'Ch' in df.columns:
                        all_chs.update(df['Ch'].dropna().unique().tolist())
                all_chs = sorted([c for c in all_chs if c is not None and c >= 0])

                for ch in all_chs:
                    pieces = []
                    for idx, df in rounds:
                        sub = build_ch_sheet(df, ch)
                        if sub.empty:
                            continue
                        pieces.append(sub)
                        pieces.append(pd.DataFrame([{col: None for col in sub.columns}]))
                    if pieces:
                        pieces = pieces[:-1]
                        merged = pd.concat(pieces, ignore_index=True)
                        with_stats = build_min_max_avg_rows(merged, CH_NUMERIC_COLS)
                        sheet_name = f"{stage_label}-CH{ch}"
                        dataframes[sheet_name] = with_stats
                        footnotes[sheet_name] = "说明：末尾三行为 Min / Max / Ave（绝对值）"
                        header_sheets.add(sheet_name)

            build_stage_ch_sheets(t0_rounds, "T0")
            build_stage_ch_sheets(end_rounds, "结束时刻")

            # ④ 差值对比
            diff_result = self._build_diff_sheet(t0_rounds, end_rounds)
            if diff_result is not None:
                diff_df, diff_bold_rows, diff_merges, diff_pink_cells = diff_result
                if diff_df is not None and not diff_df.empty:
                    dataframes["差值对比"] = diff_df
                    bold_rows_map["差值对比"] = diff_bold_rows
                    diff_special = {
                        "sheet_name": "差值对比",
                        "merges": diff_merges,
                        "pink_cells": diff_pink_cells,
                    }

            self._gui_info("💾 正在写入 Excel，请稍候...")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.root_dir.parent / f"{self.root_dir.name}_RMT-CH分析_{timestamp}.xlsx"
            self.output_path = output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)

            write_ch_analysis_to_excel(
                dataframes, output_path,
                footnotes=footnotes,
                header_sheets=header_sheets,
                bold_rows_map=bold_rows_map,
                diff_special=diff_special,
            )
            self._gui_info(f"✅ 分析结果已保存: {output_path}")
            self.file_logger.info(f"结果已保存: {output_path}")

        except Exception as e:
            self.has_error = True
            self._gui_info(f"❌ 异常: {e}")
            if self.file_logger:
                self.file_logger.exception()
            self.error.emit(str(e))
        finally:
            if self.file_logger:
                self.file_logger.close()
            self.finished.emit()

    # ================== 差值对比 sheet ==================
    def _build_diff_sheet(self, t0_rounds, end_rounds):
        """
        返回 (df, bold_rows, merges, pink_cells)
        - pink_cells: [(excel_row, excel_col), ...]  差值块里负数单元格的 Excel 坐标（1-based）
        """
        if not t0_rounds or not end_rounds:
            return None

        def stage_ch_stats(rounds):
            all_chs = set()
            for _, df in rounds:
                if 'Ch' in df.columns:
                    all_chs.update(df['Ch'].dropna().unique().tolist())
            all_chs = sorted([c for c in all_chs if c is not None and c >= 0])

            stats = {}
            for ch in all_chs:
                pieces = []
                for _, df in rounds:
                    sub = build_ch_sheet(df, ch)
                    if not sub.empty:
                        pieces.append(sub)
                if not pieces:
                    continue
                merged = pd.concat(pieces, ignore_index=True)
                stats[ch] = compute_ch_stats(merged, CH_NUMERIC_COLS)
            return stats

        t0_stats = stage_ch_stats(t0_rounds)
        end_stats = stage_ch_stats(end_rounds)

        all_chs = sorted(set(t0_stats.keys()) | set(end_stats.keys()))
        n = len(all_chs)
        if n == 0:
            return None

        display_cols = DISPLAY_COLS
        src_cols = SRC_COLS

        block_size = n + 2
        ROW_T0_MIN  = 1
        ROW_T0_MAX  = ROW_T0_MIN  + 1 * block_size
        ROW_T0_AVE  = ROW_T0_MIN  + 2 * block_size
        ROW_END_MIN = ROW_T0_MIN  + 3 * block_size
        ROW_END_MAX = ROW_T0_MIN  + 4 * block_size
        ROW_END_AVE = ROW_T0_MIN  + 5 * block_size
        ROW_DIF_MIN = ROW_T0_MIN  + 6 * block_size
        ROW_DIF_MAX = ROW_T0_MIN  + 7 * block_size
        ROW_DIF_AVE = ROW_T0_MIN  + 8 * block_size

        total_rows = ROW_DIF_AVE + n
        rows = [[None] * 10 for _ in range(total_rows)]

        def write_block_header(header_row, stage_label, metric_label):
            r = header_row - 1
            rows[r][0] = stage_label
            rows[r][1] = metric_label
            for i, dc in enumerate(display_cols):
                rows[r][2 + i] = dc

        def fill_block_data(header_row, stats, metric_key):
            for ch_idx, ch in enumerate(all_chs):
                rr = header_row + 1 + ch_idx
                row_idx = rr - 1
                rows[row_idx][1] = f'C{ch}'
                for i, sc in enumerate(src_cols):
                    v = stats.get(ch, {}).get(metric_key, {}).get(sc)
                    rows[row_idx][2 + i] = v

        # 差值块：结束 - T0，同时记录负数单元格 Excel 坐标（1-based）
        pink_cells = []
        def fill_diff_block_data(header_row, metric_key):
            for ch_idx, ch in enumerate(all_chs):
                rr = header_row + 1 + ch_idx      # Excel 行号（1-based）
                row_idx = rr - 1
                rows[row_idx][1] = f'C{ch}'
                for i, sc in enumerate(src_cols):
                    v_end = end_stats.get(ch, {}).get(metric_key, {}).get(sc)
                    v_t0  = t0_stats.get(ch, {}).get(metric_key, {}).get(sc)
                    if v_end is None or v_t0 is None:
                        rows[row_idx][2 + i] = None
                    else:
                        diff = v_end - v_t0
                        if metric_key == 'avg':
                            value = round(diff, 3)
                        else:
                            value = int(diff) if float(diff).is_integer() else round(diff, 3)
                        rows[row_idx][2 + i] = value
                        # 记录负数单元格（Excel 列号：C=3, D=4, ... J=10）
                        if isinstance(value, (int, float)) and value < 0:
                            pink_cells.append((rr, 3 + i))

        # T0
        write_block_header(ROW_T0_MIN, 'T0时刻\nRMT', 'Channel-min')
        fill_block_data(ROW_T0_MIN, t0_stats, 'min')
        write_block_header(ROW_T0_MAX, 'T0时刻\nRMT', 'Channel-max')
        fill_block_data(ROW_T0_MAX, t0_stats, 'max')
        write_block_header(ROW_T0_AVE, 'T0时刻\nRMT', 'Channel-Ave')
        fill_block_data(ROW_T0_AVE, t0_stats, 'avg')

        # 结束时刻
        write_block_header(ROW_END_MIN, '结束时刻RMT', 'Channel-min')
        fill_block_data(ROW_END_MIN, end_stats, 'min')
        write_block_header(ROW_END_MAX, '结束时刻RMT', 'Channel-max')
        fill_block_data(ROW_END_MAX, end_stats, 'max')
        write_block_header(ROW_END_AVE, '结束时刻RMT', 'Channel-Ave')
        fill_block_data(ROW_END_AVE, end_stats, 'avg')

        # 差值
        write_block_header(ROW_DIF_MIN, '差值', 'Channel-min')
        fill_diff_block_data(ROW_DIF_MIN, 'min')
        write_block_header(ROW_DIF_MAX, '差值', 'Channel-max')
        fill_diff_block_data(ROW_DIF_MAX, 'max')
        write_block_header(ROW_DIF_AVE, '差值', 'Channel-Ave')
        fill_diff_block_data(ROW_DIF_AVE, 'avg')

        bold_rows = {
            ROW_T0_MIN - 1,  ROW_T0_MAX - 1,  ROW_T0_AVE - 1,
            ROW_END_MIN - 1, ROW_END_MAX - 1, ROW_END_AVE - 1,
            ROW_DIF_MIN - 1, ROW_DIF_MAX - 1, ROW_DIF_AVE - 1,
        }

        merges = [
            (f"A{ROW_T0_MIN}",  f"A{ROW_T0_AVE + n}",  "T0时刻\nRMT", "C6EFCE"),
            (f"A{ROW_END_MIN}", f"A{ROW_END_AVE + n}", "结束时刻RMT", "FFEB9C"),
            (f"A{ROW_DIF_MIN}", f"A{ROW_DIF_AVE + n}", "差值",       "FFCC99"),
        ]

        return pd.DataFrame(rows), bold_rows, merges, pink_cells


class RmtChPage(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.task_running = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        dir_group = QGroupBox("选择研发ORT日志目录（含 T0时刻/结束时刻）")
        dir_layout = QHBoxLayout()
        self.dir_line = QLineEdit()
        self.dir_line.setPlaceholderText("请选择包含 T0时刻/结束时刻 的上层目录（如 ROMT268212 ORT log）")
        self.dir_btn = QPushButton("浏览...")
        self.dir_btn.clicked.connect(self.select_dir)
        dir_layout.addWidget(self.dir_line)
        dir_layout.addWidget(self.dir_btn)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(self.info_label)

        bios_group = QGroupBox("BIOS版本（可选）")
        bios_layout = QHBoxLayout()
        self.bios_input = QLineEdit()
        self.bios_input.setPlaceholderText("留空则默认使用 V25.06.00")
        bios_layout.addWidget(self.bios_input)
        bios_group.setLayout(bios_layout)
        layout.addWidget(bios_group)

        self.run_btn = QPushButton("🚀 开始RMT结果分析（CH通道）")
        self.run_btn.clicked.connect(self.start_task)
        self.run_btn.setStyleSheet("font-size: 14px; padding: 8px;")
        layout.addWidget(self.run_btn)

        self.progress_label = QLabel("就绪")
        self.progress_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFontFamily("Consolas")
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-size: 11px;")
        log_layout.addWidget(self.log_text)
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(lambda: self.log_text.clear())
        log_layout.addWidget(clear_btn, alignment=Qt.AlignRight)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

    def select_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择研发ORT日志目录")
        if dir_path:
            self.dir_line.setText(dir_path)
            p = Path(dir_path)
            has_t0 = any(d.is_dir() and "T0" in d.name for d in p.iterdir())
            has_end = any(d.is_dir() and "结束" in d.name for d in p.iterdir())
            if has_t0 and has_end:
                self.info_label.setText("✅ 检测到 T0时刻 和 结束时刻 目录")
                self.info_label.setStyleSheet("color: green; font-size: 12px;")
            elif has_t0:
                self.info_label.setText("⚠ 只检测到 T0时刻 目录（无结束时刻）")
                self.info_label.setStyleSheet("color: orange; font-size: 12px;")
            else:
                self.info_label.setText("❌ 未检测到 T0时刻 目录")
                self.info_label.setStyleSheet("color: red; font-size: 12px;")

    def start_task(self):
        if self.task_running:
            QMessageBox.warning(self, "提示", "任务正在运行，请等待完成")
            return
        folder = self.dir_line.text().strip()
        bios = self.bios_input.text().strip() or "V25.06.00"
        if not folder or not Path(folder).exists():
            QMessageBox.warning(self, "提示", "请选择有效的目录")
            return

        self.task_running = True
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.log_text.append("=" * 60)
        self.log_text.append(f"🚀 RMT结果分析（CH通道）开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log_text.append(f"📂 目录: {folder}")
        self.log_text.append(f"🔖 BIOS版本: {bios}")
        self.log_text.append("=" * 60)

        self.worker = RmtChWorker(Path(folder), bios)
        self.worker.log_msg.connect(self.append_log)
        self.worker.warn_msg.connect(self.append_warn)
        self.worker.finished.connect(self.task_finished)
        self.worker.error.connect(self.task_error)
        self.worker.start()

    def append_log(self, msg):
        append_highlighted(self.log_text, msg)

    def append_warn(self, msg):
        append_highlighted(self.log_text, msg)

    def task_finished(self):
        if not self.task_running:
            return
        self.task_running = False
        self.run_btn.setEnabled(True)
        self.progress_bar.setValue(100)

        if self.worker and self.worker.has_error:
            self.progress_label.setText("⚠️ 任务完成但存在错误")
            self.log_text.append("⚠️ 任务已完成但存在错误，请查看上方日志。")
        else:
            self.progress_label.setText("✅ 全部完成")
            self.log_text.append("=" * 60)
            append_highlighted(self.log_text, "🎉 RMT结果分析（CH通道）完成！")
            self.log_text.append("=" * 60)

            output_path = self.worker.output_path if (self.worker and self.worker.output_path) else "未知路径"
            log_path = self.worker.log_path if (self.worker and self.worker.log_path) else ""

            # Worker 已打印过"分析结果已保存"，这里只打详细日志
            if log_path:
                append_highlighted(self.log_text, f"📄 详细日志: {log_path}")

            QMessageBox.information(
                self, "完成",
                f"分析结果已导出到：\n{output_path}\n\n详细日志：\n{log_path}"
            )

    def task_error(self, msg):
        if not self.task_running:
            return
        self.run_btn.setEnabled(True)
        self.progress_label.setText("❌ 任务出错")
        self.log_text.append(f"❌ 错误: {msg}")
        QMessageBox.critical(self, "错误", f"分析失败:\n{msg}")