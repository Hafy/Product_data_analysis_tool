# utils/file_logger.py
"""
详细日志写文件，GUI 只显示关键事件（ERROR / WARNING）。
"""
from pathlib import Path
from datetime import datetime
import traceback


class FileLogger:
    """把详细 INFO/WARN/ERROR 写到文件，供排查 bug 用。"""

    def __init__(self, log_dir: Path = None, prefix: str = "rmt_ch"):
        if log_dir is None:
            log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = log_dir / f"{prefix}_{ts}.log"
        self._fh = open(self.log_path, 'w', encoding='utf-8')

    def info(self, msg):
        try:
            self._fh.write(f"[INFO ] {msg}\n")
            self._fh.flush()
        except Exception:
            pass

    def warning(self, msg):
        try:
            self._fh.write(f"[WARN ] {msg}\n")
            self._fh.flush()
        except Exception:
            pass

    def error(self, msg):
        try:
            self._fh.write(f"[ERROR] {msg}\n")
            self._fh.flush()
        except Exception:
            pass

    def exception(self):
        try:
            self._fh.write(traceback.format_exc() + "\n")
            self._fh.flush()
        except Exception:
            pass

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass