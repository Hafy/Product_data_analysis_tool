# gui/time_summary_page.py
"""
测试时间收集 —— GUI 页面。
"""
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QLabel, QProgressBar, QTextEdit, QMessageBox,
    QFileDialog,
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QTextCursor, QTextCharFormat

from parsers.time_summary_parser import (
    collect_test_times, build_headers, build_data_rows,
)
from utils.excel_helper import write_time_summary_to_excel
from utils.file_logger import FileLogger
import traceback
from utils.log_highlight import append_highlighted


class TimeSummaryWorker(QThread):
    log_msg = Signal(str)       # 关键事件（GUI）
    warn_msg = Signal(str)      # 警告（GUI，黄色）
    finished = Signal()
    error = Signal(str)

    def __init__(self, root_dir: Path):
        super().__init__()
        self.root_dir = Path(root_dir)
        self.has_error = False
        self.output_path = None
        self.log_path = None
        self.file_logger = None

    # ---------- 日志封装 ----------
    def _gui_info(self, msg):
        self.log_msg.emit(msg)

    def _gui_warn(self, level, msg):
        if level == 'error':
            self.warn_msg.emit(f"❌ {msg}")
        else:
            self.warn_msg.emit(f"⚠️ {msg}")

    def _file_info(self, msg):
        if self.file_logger:
            self.file_logger.info(msg)

    # ---------- 主流程 ----------
    def run(self):
        self.file_logger = FileLogger(prefix="time_summary")
        self.log_path = self.file_logger.log_path
        self._file_info(f"===== 测试时间收集开始 =====")
        self._file_info(f"root_dir = {self.root_dir}")

        try:
            # ---- 1. 收集数据 ----
            self._gui_info("🔍 扫描目录结构...")
            info = collect_test_times(self.root_dir)

            self._file_info(f"mode = {info['mode']}")
            self._file_info(f"loops = {info['loops']}")
            self._file_info(f"t0_rmt_count = {info['t0_rmt_count']}")
            self._file_info(f"end_rmt_count = {info['end_rmt_count']}")
            self._file_info(f"has_end = {info['has_end']}")
            self._file_info(f"共 {len(info['data'])} 台服务器")

            if not info["data"]:
                self.has_error = True
                self.error.emit("未收集到任何服务器的时间数据")
                self.finished.emit()
                return

            self._gui_info(f"📊 共发现 {len(info['data'])} 台服务器")
            self._gui_info(f"📊 T0 时刻 RMT 次数: {info['t0_rmt_count']}")
            self._gui_info(f"📊 老化 loop 数: {len(info['loops'])} (loop {info['loops']})")
            if info["has_end"]:
                self._gui_info(f"📊 结束时刻 RMT 次数: {info['end_rmt_count']}")

            # ---- 2. 构造表头和数据 ----
            headers, merges = build_headers(info)
            data_rows = build_data_rows(info)

            self._file_info(f"headers 列数 = {len(headers[0])}")
            self._file_info(f"data_rows 行数 = {len(data_rows)}")
            self._file_info(f"merges 数 = {len(merges)}")

            # ---- 3. 写入 Excel ----
            self._gui_info("💾 正在写入 Excel，请稍候...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.root_dir.parent / f"{self.root_dir.name}_测试时间汇总_{timestamp}.xlsx"
            self.output_path = output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)

            write_time_summary_to_excel(
                headers, data_rows, merges, output_path,
            )
            self._gui_info(f"✅ 结果已保存: {output_path}")
            self._file_info(f"结果已保存: {output_path}")

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


class TimeSummaryPage(QWidget):
    def __init__(self, stage_name: str = ""):
        super().__init__()
        self.stage_name = stage_name   # "量产" / "研发"
        self.worker = None
        self.task_running = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

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

        self.run_btn = QPushButton("🚀 开始收集测试时间")
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
        dir_path = QFileDialog.getExistingDirectory(self, f"选择{self.stage_name}ORT日志目录")
        if dir_path:
            self.dir_line.setText(dir_path)
            p = Path(dir_path)
            # 简单检测
            has_t0 = any(d.is_dir() and "T0" in d.name for d in p.iterdir())
            has_end = any(d.is_dir() and "结束" in d.name for d in p.iterdir())
            # 统计 loop 数
            loop_count = sum(1 for d in p.iterdir()
                             if d.is_dir() and "轮" in d.name and "老化" in d.name)
            parts = []
            if has_t0:
                parts.append("✅ T0时刻")
            else:
                parts.append("❌ T0时刻")
            if has_end:
                parts.append("✅ 结束时刻")
            else:
                parts.append("⚠ 无结束时刻")
            parts.append(f"loop 数: {loop_count}")
            self.info_label.setText(" | ".join(parts))
            if has_t0:
                self.info_label.setStyleSheet("color: green; font-size: 12px;")
            else:
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
        append_highlighted(self.log_text, f"🚀 测试时间收集开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        append_highlighted(self.log_text, f"📂 目录: {folder}")
        append_highlighted(self.log_text, "=" * 60)

        self.worker = TimeSummaryWorker(Path(folder))
        self.worker.log_msg.connect(self.append_log)
        self.worker.warn_msg.connect(self.append_warn)
        self.worker.finished.connect(self.task_finished)
        self.worker.error.connect(self.task_error)
        self.worker.start()

    def append_log(self, msg):
        append_highlighted(self.log_text, msg)

    def append_warn(self, msg):
        # 警告类：用 append_highlighted 显式格式，但强制黄/红
        from PySide6.QtGui import QTextCharFormat, QColor
        color = "#ff7b7b" if "❌" in msg else "#ffcc66"
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self.log_text.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(msg, fmt)
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)

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
            append_highlighted(self.log_text, "🎉 测试时间收集完成！")
            append_highlighted(self.log_text, "=" * 60)

            output_path = self.worker.output_path if (self.worker and self.worker.output_path) else "未知路径"
            log_path = self.worker.log_path if (self.worker and self.worker.log_path) else ""

            if log_path:
                append_highlighted(self.log_text, f"📄 详细日志: {log_path}")

            QMessageBox.information(
                self, "完成",
                f"测试时间汇总已导出到：\n{output_path}\n\n详细日志：\n{log_path}"
            )

    def task_error(self, msg):
        if not self.task_running:
            return
        self.run_btn.setEnabled(True)
        self.progress_label.setText("❌ 任务出错")
        append_highlighted(self.log_text, f"❌ 错误: {msg}")
        QMessageBox.critical(self, "错误", f"收集失败:\n{msg}")