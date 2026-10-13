# gui/error_summary_page.py
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QLabel, QProgressBar, QTextEdit, QMessageBox,
    QFileDialog,
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QTextCursor, QTextCharFormat

from parsers.error_summary_parser import collect_all_errors
from utils.path_utils import get_resource_path
from utils.excel_helper import write_single_dataframe_to_excel
import pandas as pd
import traceback
from utils.log_highlight import append_highlighted

class ErrorSummaryWorker(QThread):
    log_msg = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, root_dir: Path, stage_label: str = ""):
        super().__init__()
        self.root_dir = Path(root_dir)
        self.stage_label = stage_label  # "量产" / "研发"，仅用于日志
        self.has_error = False
        self.output_path = None
        self.total_errors = 0

    def run(self):
        try:
            self.log_msg.emit(f"🔍 开始扫描: {self.root_dir}")
            df = collect_all_errors(self.root_dir, log_callback=self.log_msg.emit)

            if df.empty:
                self.log_msg.emit("ℹ️ 未发现任何错误记录，将生成仅含表头的汇总文件")

            template_path = get_resource_path("templates/error_summary_template.xlsx")
            if not template_path.exists():
                self.has_error = True
                self.error.emit(f"模板文件不存在: {template_path}")
                self.finished.emit()
                return

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.root_dir.parent / f"{self.root_dir.name}_检错汇总_{timestamp}.xlsx"
            self.output_path = output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)

            write_single_dataframe_to_excel(df, template_path, output_path)
            self.total_errors = len(df)
            self.log_msg.emit(f"✅ 汇总结果已保存: {output_path}")

        except Exception as e:
            self.has_error = True
            self.log_msg.emit(f"❌ 异常: {traceback.format_exc()}")
            self.error.emit(str(e))
        self.finished.emit()


class ErrorSummaryPage(QWidget):
    def __init__(self, stage_name: str = ""):
        super().__init__()
        self.stage_name = stage_name  # "量产" / "研发"
        self.worker = None
        self.task_running = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 目录选择
        dir_group = QGroupBox(f"选择{self.stage_name}ORT日志目录")
        dir_layout = QHBoxLayout()
        self.dir_line = QLineEdit()
        self.dir_line.setPlaceholderText("请选择包含 T0时刻 文件夹的上层目录（如 ROMT268212 ORT log）")
        self.dir_btn = QPushButton("浏览...")
        self.dir_btn.clicked.connect(self.select_dir)
        dir_layout.addWidget(self.dir_line)
        dir_layout.addWidget(self.dir_btn)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(self.info_label)

        # 执行按钮
        self.run_btn = QPushButton("🚀 开始检错信息汇总")
        self.run_btn.clicked.connect(self.start_task)
        self.run_btn.setStyleSheet("font-size: 14px; padding: 8px;")
        layout.addWidget(self.run_btn)

        # 进度
        self.progress_label = QLabel("就绪")
        self.progress_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        # 日志
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
        dir_path = QFileDialog.getExistingDirectory(self, "选择ORT日志上层目录")
        if dir_path:
            self.dir_line.setText(dir_path)
            # 简单检测一下是否包含 T0时刻
            p = Path(dir_path)
            has_t0 = any(d.is_dir() and "T0" in d.name for d in p.iterdir())
            if has_t0:
                self.info_label.setText("✅ 检测到 T0时刻 目录")
                self.info_label.setStyleSheet("color: green; font-size: 12px;")
            else:
                self.info_label.setText("⚠ 未检测到 T0时刻 目录，请确认选择正确")
                self.info_label.setStyleSheet("color: orange; font-size: 12px;")

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
        self.log_text.setCurrentCharFormat(QTextCharFormat())
        append_highlighted(self.log_text, "=" * 60)
        append_highlighted(self.log_text, f"🚀 检错信息汇总开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        append_highlighted(self.log_text, f"📂 目录: {folder}")
        append_highlighted(self.log_text, "=" * 60)

        self.worker = ErrorSummaryWorker(Path(folder), self.stage_name)
        self.worker.log_msg.connect(self.append_log)
        self.worker.finished.connect(self.task_finished)
        self.worker.error.connect(self.task_error)
        self.worker.start()

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
            append_highlighted(self.log_text, "⚠️ 任务已完成但存在错误，请查看上方日志。")
        else:
            self.progress_label.setText("✅ 全部完成")
            append_highlighted(self.log_text, "=" * 60)
            append_highlighted(self.log_text, "🎉 检错信息汇总完成！")
            append_highlighted(self.log_text, "=" * 60)

            output_path = self.worker.output_path if (self.worker and self.worker.output_path) else "未知路径"
            total = self.worker.total_errors if self.worker else 0

            QMessageBox.information(
                self, "完成",
                f"检错信息汇总已导出到：\n{output_path}\n\n共 {total} 条错误记录"
            )

    def task_error(self, msg):
        if not self.task_running:
            return
        self.run_btn.setEnabled(True)
        self.progress_label.setText("❌ 任务出错")
        append_highlighted(self.log_text, f"❌ 错误: {msg}")
        QMessageBox.critical(self, "错误", f"汇总失败:\n{msg}")