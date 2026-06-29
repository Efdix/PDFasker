"""
配置管理 —— 使用 JSON 文件持久化 API 配置和 PDF 图书馆
"""

import json
import os
from pathlib import Path


CONFIG_DIR = Path.home() / ".pdfasker"
CONFIG_FILE = CONFIG_DIR / "config.json"
LIBRARY_FILE = CONFIG_DIR / "library.json"

DEFAULT_CONFIG = {
    "provider": "DeepSeek",
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "max_tokens": 1_000_000,
    "library_path": str(Path.home() / "Documents" / "PDFasker_Library"),
}


def ensure_config_dir():
    """确保配置目录存在"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """加载配置，如果不存在则返回默认值"""
    ensure_config_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config = DEFAULT_CONFIG.copy()
            config.update(saved)
            return config
        except (json.JSONDecodeError, OSError):
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    """保存配置到文件"""
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ========== PDF 图书馆管理 ==========

def load_library() -> list[dict]:
    """加载 PDF 图书馆（文件列表和文件夹结构）"""
    ensure_config_dir()
    if LIBRARY_FILE.exists():
        try:
            with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_library(library: list[dict]):
    """保存 PDF 图书馆"""
    ensure_config_dir()
    with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)


def add_pdf_to_library(pdf_info: dict):
    """添加一个 PDF 到图书馆"""
    library = load_library()
    # 避免重复
    for item in library:
        if item.get("path") == pdf_info.get("path"):
            item.update(pdf_info)
            save_library(library)
            return
    library.append(pdf_info)
    save_library(library)


def remove_pdf_from_library(pdf_path: str):
    """从图书馆移除 PDF"""
    library = load_library()
    library = [item for item in library if item.get("path") != pdf_path]
    save_library(library)


def get_library_folders(library: list[dict]) -> list[str]:
    """获取所有不重复的文件夹名"""
    folders = set()
    for item in library:
        folder = item.get("folder", "")
        if folder:
            folders.add(folder)
    return sorted(folders)
