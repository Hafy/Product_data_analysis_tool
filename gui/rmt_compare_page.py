# gui/rmt_compare_page.py
import sys
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QLabel, QProgressBar, QTextEdit, QMessageBox,
    QFileDialog,
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QTextCursor, QIcon, QFont

from parsers.rmt_parser import parse_rmt_log
from exporters.excel_exporter import write_dataframe_to_template
from utils.path_utils import get_resource_path, find_named_folders   # ← 关键
from utils.excel_helper import write_dataframes_to_excel
import pandas as pd
import traceback
from utils.log_highlight import append_highlighted

class RmtCompareWorker(QThread):
    progress = Signal(int, int, str)
    log_msg = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, folder1, folder2, bios_version, folder):
        super().__init__()
        self.folder1 = Path(folder1)
        self.folder2 = Path(folder2)
        self.bios_version = bios_version
        self.folder = Path(folder)  # 用户选择的目录
        self.has_error = False
        self.output_path = None

    def run(self):
        try:
            # ===== 日志使用实际文件夹名 =====
            self.log_msg.emit(f"🔍 解析第一次 RMT ({self.folder1.name})...")
            df1 = self._parse_folder(self.folder1, "第一次")
            self.log_msg.emit(f"🔍 解析第二次 RMT ({self.folder2.name})...")
            df2 = self._parse_folder(self.folder2, "第二次")

            if df1.empty or df2.empty:
                self.has_error = True
                self.error.emit("某次测试无有效数据")
                return

            numeric_cols = ['RxDly-', 'RxDly+', 'RxVrf-', 'RxVrf+',
                            'TxDly-', 'TxDly+', 'TxVrf-', 'TxVrf+']

            mean1 = df1[numeric_cols].mean()
            std1 = df1[numeric_cols].std()
            mean2 = df2[numeric_cols].mean()
            diff = mean2 - mean1

            diff_df = pd.DataFrame([diff[numeric_cols]])

            red_cells = []
            for col in numeric_cols:
                if abs(diff[col]) > std1[col]:
                    red_cells.append((0, col))

            df1 = self._append_stats(df1, numeric_cols, f"第一次({self.folder1.name})")
            df2 = self._append_stats(df2, numeric_cols, f"第二次({self.folder2.name})")

            dataframes = {
                "第一次RMT": df1,
                "第二次RMT": df2,
                "差值统计": diff_df
            }

            footnotes = {
                "差值统计": "说明：差值 = 老化后平均值 - 老化前平均值，|差值| > 老化前标准差则标红"
            }
            template_path = get_resource_path("templates/rmt_template.xlsx")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # ===== 老化模式输出路径 =====
            # 用户选择：C:\xxx\rot_1205（内含 2.RMT、4.RMT）
            # 输出到：  C:\xxx\rot_1205_RMT_时间戳.xlsx
            parent_dir = self.folder.parent
            output_path = parent_dir / f"{self.folder.name}_RMT_{timestamp}.xlsx"
            self.output_path = output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)

            write_dataframes_to_excel(dataframes, template_path, output_path,
                                      red_cells={"差值统计": red_cells}, footnotes=footnotes)
            self.log_msg.emit(f"✅ 对比结果已保存: {output_path}")

        except Exception as e:
            self.has_error = True
            self.error.emit(str(e))
        self.finished.emit()

    def _parse_folder(self, folder, label):
        all_dfs = []
        files = [f for f in folder.iterdir() if f.is_file()]
        total = len(files)
        for i, file in enumerate(files, 1):
            ip_raw = file.stem.split('_')[0] if '_' in file.stem else file.stem
            ip = ip_raw.replace('-', '.')
            self.progress.emit(i, total, ip)
            self.log_msg.emit(f"   {label} [{i}/{total}] {file.name}")
            df = parse_rmt_log(file, self.bios_version, log_callback=self.log_msg.emit)
            if not df.empty:
                all_dfs.append(df)
        if all_dfs:
            return pd.concat(all_dfs, ignore_index=True)
        return pd.DataFrame()

    def _append_stats(self, df, numeric_cols, label):
        """在 DataFrame 末尾追加两行：标准差、平均值"""
        if df.empty:
            return df
        first_col = df.columns[0]
        std_dict = {}
        mean_dict = {}
        for col in df.columns:
            if col in numeric_cols:
                std_dict[col] = df[col].std()
                mean_dict[col] = df[col].mean()
            else:
                if col == first_col:
                    std_dict[col] = f"{label}标准差"
                    mean_dict[col] = f"{label}平均值"
                else:
                    std_dict[col] = None
                    mean_dict[col] = None
        std_df = pd.DataFrame([std_dict])
        mean_df = pd.DataFrame([mean_dict])
        df = pd.concat([df, std_df, mean_df], ignore_index=True)
        return df


class RmtComparePage(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.task_running = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 目录选择
        dir_group = QGroupBox("选择老化对比目录")
        dir_layout = QHBoxLayout()
        self.dir_line = QLineEdit()
        self.dir_line.setPlaceholderText("请选择包含 2.RMT 的上层目录（如 ROMT266720 ORT测试）")
        self.dir_btn = QPushButton("浏览...")
        self.dir_btn.clicked.connect(self.select_dir)
        dir_layout.addWidget(self.dir_line)
        dir_layout.addWidget(self.dir_btn)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(self.info_label)

        # BIOS版本
        bios_group = QGroupBox("BIOS版本")
        bios_layout = QHBoxLayout()
        self.bios_input = QLineEdit()
        self.bios_input.setPlaceholderText("请输入BIOS版本号（留空则默认使用 V25.06.00）")
        bios_layout.addWidget(self.bios_input)
        bios_group.setLayout(bios_layout)
        layout.addWidget(bios_group)

        # 执行按钮
        self.run_btn = QPushButton("🚀 开始老化RMT对比")
        self.run_btn.clicked.connect(self.start_task)
        self.run_btn.setStyleSheet("font-size: 14px; padding: 8px;")
        layout.addWidget(self.run_btn)

        # 进度
        progress_layout = QHBoxLayout()
        self.progress_label = QLabel("就绪")
        self.progress_label.setStyleSheet("font-size: 12px;")
        progress_layout.addWidget(self.progress_label)
        progress_layout.addStretch()
        layout.addLayout(progress_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        # 日志窗口
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
        dir_path = QFileDialog.getExistingDirectory(self, "选择上层目录")
        if dir_path:
            self.dir_line.setText(dir_path)
            rmt_folders = find_named_folders(dir_path, '.RMT')
            if len(rmt_folders) >= 2:
                names = [f.name for f in rmt_folders]
                self.info_label.setText(f"✅ 找到 {len(rmt_folders)} 个 RMT 文件夹: {', '.join(names)}")
                self.info_label.setStyleSheet("color: green; font-size: 12px;")
            elif len(rmt_folders) == 1:
                self.info_label.setText(f"⚠ 只找到 1 个 RMT 文件夹: {rmt_folders[0].name}，需要至少 2 个")
                self.info_label.setStyleSheet("color: orange; font-size: 12px;")
            else:
                self.info_label.setText("❌ 未找到任何 .RMT 文件夹")
                self.info_label.setStyleSheet("color: red; font-size: 12px;")

    def start_task(self):
        if self.task_running:
            QMessageBox.warning(self, "提示", "任务正在运行，请等待完成")
            return

        folder = self.dir_line.text().strip()
        bios = self.bios_input.text().strip()
        if not bios:
            bios = "V25.06.00"

        if not folder or not Path(folder).exists():
            QMessageBox.warning(self, "提示", "请选择有效的目录")
            return

        rmt_folders = find_named_folders(folder, '.RMT')
        if len(rmt_folders) < 2:
            QMessageBox.warning(self, "提示", f"需要至少 2 个 RMT 文件夹，当前只找到 {len(rmt_folders)} 个")
            return

        folder1 = rmt_folders[0]
        folder2 = rmt_folders[-1]

        if len(rmt_folders) > 2:
            self.log_text.append(f"⚠ 找到 {len(rmt_folders)} 个 RMT 文件夹，将使用第一个和最后一个进行对比")
            self.log_text.append(f"   📁 第一次: {folder1.name}")
            self.log_text.append(f"   📁 第二次: {folder2.name}")

        self.task_running = True
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.log_text.append("=" * 60)
        self.log_text.append(f"🚀 老化RMT对比任务开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log_text.append(f"📂 目录: {folder}")
        self.log_text.append(f"🔖 BIOS版本: {bios}")
        self.log_text.append("=" * 60)
        self.log_text.append(f"✅ 找到第一次测试: {folder1.name}")
        self.log_text.append(f"✅ 找到第二次测试: {folder2.name}")

        self.worker = RmtCompareWorker(folder1, folder2, bios, folder)
        self.worker.progress.connect(self.update_progress)
        self.worker.log_msg.connect(self.append_log)
        self.worker.finished.connect(self.task_finished)
        self.worker.error.connect(self.task_error)
        self.worker.start()

    def update_progress(self, current, total, ip):
        self.progress_label.setText(f"🔄 正在处理: {ip}  ({current}/{total})")
        self.progress_bar.setValue(int(current / total * 100))

    def append_log(self, msg):
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
            append_highlighted(self.log_text, "🎉 老化RMT对比完成！")
            self.log_text.append("=" * 60)

            output_path = self.worker.output_path if (self.worker and self.worker.output_path) else "未知路径"
            append_highlighted(self.log_text, f"✅ 对比结果已保存: {output_path}")

            QMessageBox.information(self, "完成", f"老化RMT对比结果已导出到：\n{output_path}")
    def task_error(self, msg):
        if not self.task_running:
            return
        self.run_btn.setEnabled(True)
        self.progress_label.setText("❌ 任务出错")
        self.log_text.append(f"❌ 错误: {msg}")
        QMessageBox.critical(self, "错误", f"解析失败:\n{msg}")