# gui/profile_page.py
import sys
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QLabel, QProgressBar, QTextEdit, QMessageBox,
    QFileDialog,
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QTextCursor, QIcon

from parsers.profile_parser import parse_profile_log
from exporters.excel_exporter import write_dataframe_to_template
from utils.path_utils import get_resource_path
import pandas as pd
import traceback
from utils.log_highlight import append_highlighted

class ProfileWorker(QThread):
    progress = Signal(int, int, str)
    log_msg = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = Path(folder_path)
        self.has_error = False
        self.output_path = None  # 保存输出路径供界面显示

    def run(self):
        try:
            self.log_msg.emit("🔍 开始扫描PROFILE目录...")
            files = [f for f in self.folder_path.iterdir() if f.is_file()]
            if not files:
                self.has_error = True
                self.error.emit("未找到任何PROFILE日志文件")
                self.finished.emit()
                return

            total = len(files)
            self.log_msg.emit(f"📁 共发现 {total} 个日志文件")
            all_dfs = []
            success_count = 0

            for idx, file in enumerate(files, 1):
                ip_raw = file.stem.split('_')[0] if '_' in file.stem else file.stem
                ip = ip_raw.replace('-', '.')
                self.progress.emit(idx, total, ip)
                self.log_msg.emit(f"⏳ [{idx}/{total}] 正在解析: {file.name}")
                try:
                    df = parse_profile_log(file, log_callback=self.log_msg.emit)
                    if not df.empty:
                        all_dfs.append(df)
                        success_count += 1
                    else:
                        self.log_msg.emit(f"   ⚠️ 未提取到有效数据")
                except Exception as e:
                    self.log_msg.emit(f"   ❌ 解析失败: {str(e)}")

            self.log_msg.emit(f"📊 解析完成: {success_count}/{total} 个文件有效")

            if not all_dfs:
                self.has_error = True
                self.error.emit("没有解析到任何有效PROFILE数据")
                self.finished.emit()
                return

            final_df = pd.concat(all_dfs, ignore_index=True)
            self.log_msg.emit(f"📊 合并后总行数: {len(final_df)}")

            template_path = get_resource_path("templates/profile_template.xlsx")
            if not template_path.exists():
                self.has_error = True
                self.error.emit(f"模板文件不存在: {template_path}")
                self.finished.emit()
                return

            # ===== 单次模式输出路径 =====
            # 用户选择：C:\xxx\rot_1205\3.profile
            # 输出到：  C:\xxx\rot_1205\results\rot_1205_PROFILE_时间戳.xlsx
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            parent_of_selected = self.folder_path.parent          # C:\xxx\rot_1205
            results_dir = parent_of_selected / "results"          # C:\xxx\rot_1205\results
            upper_dir_name = parent_of_selected.name              # rot_1205
            output_path = results_dir / f"{upper_dir_name}_PROFILE_{timestamp}.xlsx"
            self.output_path = output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)

            self.log_msg.emit(f"💾 正在写入Excel: {output_path}")
            write_dataframe_to_template(final_df, template_path, output_path)
            self.log_msg.emit(f"✅ 数据已保存: {output_path}")

        except Exception as e:
            self.has_error = True
            self.log_msg.emit(f"❌ 发生异常: {traceback.format_exc()}")
            self.error.emit(str(e))

        self.finished.emit()


class ProfilePage(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.task_running = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 目录选择
        dir_group = QGroupBox("选择PROFILE日志目录")
        dir_layout = QHBoxLayout()
        self.dir_line = QLineEdit()
        self.dir_line.setPlaceholderText("请选择包含PROFILE日志的文件夹（如 3.profile）")
        self.dir_btn = QPushButton("浏览...")
        self.dir_btn.clicked.connect(self.select_dir)
        dir_layout.addWidget(self.dir_line)
        dir_layout.addWidget(self.dir_btn)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        # 执行按钮
        self.run_btn = QPushButton("🚀 开始PROFILE解析")
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
        dir_path = QFileDialog.getExistingDirectory(self, "选择PROFILE日志目录")
        if dir_path:
            self.dir_line.setText(dir_path)

    def start_task(self):
        if self.task_running:
            QMessageBox.warning(self, "提示", "任务正在运行，请等待完成")
            return

        folder = self.dir_line.text().strip()
        if not folder or not Path(folder).exists():
            QMessageBox.warning(self, "提示", "请选择有效的目录")
            return

        self.task_running = True
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.log_text.append("=" * 60)
        self.log_text.append(f"🚀 PROFILE解析任务开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log_text.append(f"📂 目录: {folder}")
        self.log_text.append("=" * 60)

        self.worker = ProfileWorker(folder)
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
            append_highlighted(self.log_text, "🎉 PROFILE解析任务完成！")
            self.log_text.append("=" * 60)

            output_path = self.worker.output_path if (self.worker and self.worker.output_path) else "未知路径"
            append_highlighted(self.log_text, f"✅ 数据已保存: {output_path}")

            QMessageBox.information(self, "完成", f"PROFILE数据已成功导出到：\n{output_path}")

    def task_error(self, msg):
        if not self.task_running:
            return
        self.run_btn.setEnabled(True)
        self.progress_label.setText("❌ 任务出错")
        self.log_text.append(f"❌ 错误: {msg}")
        QMessageBox.critical(self, "错误", f"解析失败:\n{msg}")