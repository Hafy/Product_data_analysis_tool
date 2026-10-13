# utils/log_highlight.py
"""
GUI 日志：加时间戳 + 高亮关键行。
用 QTextCharFormat 显式设置格式，避免 QTextEdit.append 的格式继承问题。
"""
from datetime import datetime
import re
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor

COLOR_SUCCESS = "#66ff99"   # 浅绿（数据已保存）
COLOR_PATH    = "#66ccff"   # 浅蓝（正在写入）
COLOR_DEFAULT = "#d4d4d4"   # 默认（浅灰，与 QTextEdit 样式一致）


def append_highlighted(qtextedit, msg, cursor_to_end=True):
    ts = datetime.now().strftime("[%H:%M:%S] ")
    if re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', msg):
        full_msg = msg
    else:
        full_msg = ts + msg

    # 决定颜色 + 加粗
    if ("数据已保存" in msg) or ("结果已保存" in msg):
        color = COLOR_SUCCESS
        bold = True
    elif "正在写入" in msg:
        color = COLOR_PATH
        bold = True
    else:
        color = COLOR_DEFAULT
        bold = False

    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    fmt.setFontWeight(700 if bold else 400)

    cursor = qtextedit.textCursor()
    cursor.movePosition(QTextCursor.End)

    # 如果已有内容，先换行（模拟 append 行为）
    if not qtextedit.document().isEmpty():
        cursor.insertBlock()

    cursor.insertText(full_msg, fmt)

    if cursor_to_end:
        cursor.movePosition(QTextCursor.End)
        qtextedit.setTextCursor(cursor)