# gui/main_window.py
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QToolBar, QStackedWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QFont
from utils.path_utils import get_resource_path
from gui.rmt_page import RmtPage
from gui.rmt_compare_page import RmtComparePage
from gui.profile_page import ProfilePage
from gui.profile_compare_page import ProfileComparePage
from gui.error_summary_page import ErrorSummaryPage
from gui.time_summary_page import TimeSummaryPage
from gui.rmt_ch_page import RmtChPage

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("产品部数据分析工具")
        self.setMinimumSize(900, 700)
        # 全局字体兜底
        self.setFont(QFont("Microsoft YaHei", 10))

        # 图标
        icon_path = get_resource_path("icons/Tigo.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ===== 顶部工具栏：一级下拉框 + 二级下拉框 + 单次按钮 =====
        toolbar_widget = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_widget)
        toolbar_layout.setContentsMargins(10, 6, 10, 6)
        toolbar_layout.setSpacing(8)

        # 一级下拉框
        self.stage_combo = QComboBox()
        self.stage_combo.addItems(["量产数据分析", "研发阶段数据分析"])
        self.stage_combo.setFixedWidth(160)
        self.stage_combo.setFont(QFont("Microsoft YaHei", 10))
        self.stage_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                border: 1px solid #dcdfe6;
                border-radius: 4px;
                background: white;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                border: 1px solid #dcdfe6;
                background: white;
                selection-background-color: #ecf5ff;
                selection-color: #409EFF;
            }
        """)
        self.stage_combo.currentIndexChanged.connect(self.on_stage_changed)

        label_stage = QLabel("分析阶段:")
        label_stage.setFont(QFont("Microsoft YaHei", 10))
        toolbar_layout.addWidget(label_stage)
        toolbar_layout.addWidget(self.stage_combo)
        toolbar_layout.addSpacing(12)

        # 二级下拉框
        self.func_combo = QComboBox()
        self.func_combo.setFixedWidth(200)
        self.func_combo.setFont(QFont("Microsoft YaHei", 10))
        self.func_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                border: 1px solid #dcdfe6;
                border-radius: 4px;
                background: white;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                border: 1px solid #dcdfe6;
                background: white;
                selection-background-color: #ecf5ff;
                selection-color: #409EFF;
            }
        """)
        self.func_combo.currentIndexChanged.connect(self.on_func_changed)

        label_func = QLabel("功能:")
        label_func.setFont(QFont("Microsoft YaHei", 10))
        toolbar_layout.addWidget(label_func)
        toolbar_layout.addWidget(self.func_combo)
        toolbar_layout.addSpacing(20)

        # 单次按钮
        self.btn_single_rmt = QPushButton("单次RMT")
        self.btn_single_rmt.clicked.connect(lambda: self.stacked.setCurrentIndex(5))
        self.btn_single_profile = QPushButton("单次PROFILE")
        self.btn_single_profile.clicked.connect(lambda: self.stacked.setCurrentIndex(6))

        for btn in (self.btn_single_rmt, self.btn_single_profile):
            btn.setFont(QFont("Microsoft YaHei", 10))
            #btn.setEnabled(False)   # ← 新增：禁用
            #btn.setToolTip("功能暂未开放")   # ← 可选：鼠标悬停提示
            btn.setStyleSheet("""
                QPushButton {
                    padding: 5px 14px;
                    border: 1px solid #409EFF;
                    border-radius: 4px;
                    color: #409EFF;
                    background: white;
                }
                QPushButton:hover { background: #ecf5ff; }
                QPushButton:pressed { background: #d9ecff; }
            """)
            toolbar_layout.addWidget(btn)

        toolbar_layout.addStretch()

        tb = QToolBar()
        tb.setFont(QFont("Microsoft YaHei", 10))
        tb.setMovable(False)
        tb.addWidget(toolbar_widget)
        self.addToolBar(Qt.TopToolBarArea, tb)

        # ---- QStackedWidget 容器 ----
        self.stacked = QStackedWidget()
        self.setCentralWidget(self.stacked)

        # ---- 索引0：欢迎页 ----
        welcome = QWidget()
        welcome.setAttribute(Qt.WA_StyledBackground, True)
        welcome.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(welcome)
        layout.setAlignment(Qt.AlignCenter)

        img_path = get_resource_path("icons/Kimtigo.png")
        if img_path.exists():
            pixmap = QPixmap(str(img_path))
            if pixmap.width() > 800 or pixmap.height() > 600:
                pixmap = pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img_label = QLabel()
            img_label.setPixmap(pixmap)
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setAttribute(Qt.WA_TranslucentBackground)
            img_label.setStyleSheet("background: transparent;")
            layout.addWidget(img_label)
        else:
            label = QLabel("欢迎使用产品部数据分析工具\n\n请从顶部选择操作")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-size: 20px; color: #555; padding: 100px;")
            layout.addWidget(label)

        self.stacked.addWidget(welcome)  # 索引0

        # ---- 量产页面（索引1、2） ----
        self.page_rmt_compare = RmtComparePage()
        self.page_profile_compare = ProfileComparePage()
        self.stacked.addWidget(self.page_rmt_compare)      # 索引1
        self.stacked.addWidget(self.page_profile_compare)  # 索引2

        # ---- 研发页面（索引3、4，占位） ----
        self.page_rd_rmt = self._make_placeholder("研发阶段 - 老化RMT（待实现）")
        self.page_rd_profile = self._make_placeholder("研发阶段 - 老化PROFILE（待实现）")
        self.stacked.addWidget(self.page_rd_rmt)      # 索引3
        self.stacked.addWidget(self.page_rd_profile)  # 索引4

        # ---- 单次页面（索引5、6） ----
        self.page_rmt = RmtPage()
        self.page_profile = ProfilePage()
        self.stacked.addWidget(self.page_rmt)      # 索引5
        self.stacked.addWidget(self.page_profile)  # 索引6

               # ---- 检错信息汇总（索引7、8） ----
        self.page_error_summary_prod = ErrorSummaryPage("量产")   # 索引7
        self.page_error_summary_rd = ErrorSummaryPage("研发")     # 索引8
        self.stacked.addWidget(self.page_error_summary_prod)
        self.stacked.addWidget(self.page_error_summary_rd)

        # ---- RMT结果分析（CH通道）：研发（索引9） ----
        self.page_rmt_ch = RmtChPage()                            # 索引9
        self.stacked.addWidget(self.page_rmt_ch)

        # ---- 测试时间收集：量产（索引10） ----
        self.page_time_summary_prod = TimeSummaryPage("量产")     # 索引10
        self.stacked.addWidget(self.page_time_summary_prod)

        # ---- 测试时间收集：研发（索引11） ----
        self.page_time_summary_rd = TimeSummaryPage("研发")       # 索引11
        self.stacked.addWidget(self.page_time_summary_rd)

        # ---- RMT结果分析（CH通道）：量产（索引12） ----
        self.page_rmt_ch_prod = RmtChPage()                       # 索引12
        self.stacked.addWidget(self.page_rmt_ch_prod)

        self.stacked.setCurrentIndex(0)

        # 初始化二级下拉框（默认量产）
        self._refresh_func_combo(0)
        self.on_func_changed(0)

        self.statusBar().showMessage("请选择分析阶段或单次功能")

    def _make_placeholder(self, text):
        """生成占位页面"""
        w = QWidget()
        layout = QVBoxLayout(w)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 18px; color: #999;")
        layout.addWidget(label)
        return w

    def _refresh_func_combo(self, stage_idx):
        self.func_combo.blockSignals(True)
        self.func_combo.clear()
        if stage_idx == 0:
            # 量产
            self.func_combo.addItems([
                "老化RMT",
                "老化PROFILE",
                "检错信息汇总",
                "RMT结果分析（CH通道）",
                "测试时间收集",
            ])
        else:
            # 研发
            self.func_combo.addItems([
                "检错信息汇总",
                "RMT结果分析（CH通道）",
                "测试时间收集",
            ])
        self.func_combo.setCurrentIndex(0)
        self.func_combo.blockSignals(False)

    def on_func_changed(self, idx):
        stage_idx = self.stage_combo.currentIndex()
        if stage_idx == 0:
            # 量产：0=老化RMT(1), 1=老化PROFILE(2), 2=检错汇总(7), 3=RMT-CH(12), 4=测试时间(10)
            if idx == 0:
                self.stacked.setCurrentIndex(1)
            elif idx == 1:
                self.stacked.setCurrentIndex(2)
            elif idx == 2:
                self.stacked.setCurrentIndex(7)
            elif idx == 3:
                self.stacked.setCurrentIndex(12)
            else:
                self.stacked.setCurrentIndex(10)
        else:
            # 研发：0=检错汇总(8), 1=RMT-CH(9), 2=测试时间(11)
            if idx == 0:
                self.stacked.setCurrentIndex(8)
            elif idx == 1:
                self.stacked.setCurrentIndex(9)
            else:
                self.stacked.setCurrentIndex(11)

    def on_stage_changed(self, idx):
        """一级下拉框切换：0=量产，1=研发"""
        if idx == 0:
            self.statusBar().showMessage("当前：量产数据分析")
        else:
            self.statusBar().showMessage("当前：研发阶段数据分析")
        self._refresh_func_combo(idx)
        self.on_func_changed(0)