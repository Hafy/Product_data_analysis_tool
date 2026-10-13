# utils/path_utils.py
import sys
import re
from pathlib import Path
from typing import List


def get_resource_path(relative_path: str) -> Path:
    """
    获取资源文件的绝对路径。
    开发环境：返回项目目录下的路径
    打包环境：返回 EXE 解压后的临时目录下的路径
    """
    if getattr(sys, 'frozen', False):
        # 打包后的 EXE 环境
        base_path = Path(sys._MEIPASS)
    else:
        # 开发环境
        base_path = Path(__file__).parent.parent
    
    return base_path / relative_path

def find_named_folders(root_dir: Path, suffix: str) -> List[Path]:
    """
    扫描根目录下所有匹配后缀的文件夹，按数字排序。
    
    :param root_dir: 根目录路径
    :param suffix: 文件夹后缀，如 '.RMT' 或 '.profile'（不区分大小写）
    :return: 按数字升序排列的文件夹列表
    """
    root = Path(root_dir)
    folders = []
    escaped_suffix = re.escape(suffix)
    pattern = re.compile(rf'(\d+){escaped_suffix}', re.IGNORECASE)
    
    for item in root.iterdir():
        if item.is_dir() and item.name.lower().endswith(suffix.lower()):
            match = pattern.search(item.name)
            if match:
                num = int(match.group(1))
                folders.append((num, item))
    
    # 按数字排序
    folders.sort(key=lambda x: x[0])
    return [folder for _, folder in folders]