# utils/log_handler.py - 日志工具（可选）
import logging
from datetime import datetime
from pathlib import Path


class LogHandler:
    """日志处理器，同时输出到文件和回调函数"""
    
    def __init__(self, log_file: str = None):
        self.log_file = log_file
        self.callbacks = []
        
        # 如果指定了日志文件，创建目录
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 配置 logging
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file, encoding='utf-8'),
                ]
            )
            self.logger = logging.getLogger(__name__)
    
    def add_callback(self, callback):
        """添加回调函数（用于GUI显示）"""
        self.callbacks.append(callback)
    
    def info(self, msg):
        """INFO级别日志"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_msg = f"[{timestamp}] {msg}"
        
        # 写入文件
        if hasattr(self, 'logger'):
            self.logger.info(msg)
        
        # 调用所有回调（更新GUI）
        for cb in self.callbacks:
            try:
                cb(formatted_msg)
            except Exception as e:
                print(f"回调执行失败: {e}")
    
    def error(self, msg):
        """ERROR级别日志"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_msg = f"[{timestamp}] ❌ {msg}"
        
        if hasattr(self, 'logger'):
            self.logger.error(msg)
        
        for cb in self.callbacks:
            try:
                cb(formatted_msg)
            except Exception as e:
                print(f"回调执行失败: {e}")
    
    def warning(self, msg):
        """WARNING级别日志"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_msg = f"[{timestamp}] ⚠ {msg}"
        
        if hasattr(self, 'logger'):
            self.logger.warning(msg)
        
        for cb in self.callbacks:
            try:
                cb(formatted_msg)
            except Exception as e:
                print(f"回调执行失败: {e}")