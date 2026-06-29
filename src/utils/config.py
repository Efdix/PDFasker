"""
配置管理 —— API 配置（聊天/翻译/图析分离）、PDF 图书馆、对话历史
"""

import json
import hashlib
import os
from datetime import datetime
from pathlib import Path


CONFIG_DIR = Path.home() / ".pdfasker"
CONFIG_FILE = CONFIG_DIR / "config.json"
LIBRARY_FILE = CONFIG_DIR / "library.json"
CHATS_DIR = CONFIG_DIR / "chats"

# 一套 API 的默认值
def _default_api(provider="DeepSeek", model="deepseek-v4-flash"):
    return {"provider": provider, "api_key": "", "base_url": "https://api.deepseek.com", "model": model}

DEFAULT_CONFIG = {
    # 三套独立 API 配置
    "chat_api":        _default_api("DeepSeek", "deepseek-v4-flash"),
    "translation_api": _default_api("DeepSeek", "deepseek-v4-flash"),
    "image_api":       _default_api("DeepSeek", "deepseek-v4-flash"),
    "max_tokens": 1_000_000,
    "library_path": str(Path.home() / "Documents" / "PDFasker_Library"),
}


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CHATS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_config_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config = DEFAULT_CONFIG.copy()
            # 兼容旧格式：把顶层 api_key 等迁移到 chat_api
            if "api_key" in saved and "chat_api" not in saved:
                saved["chat_api"] = {
                    "provider": saved.get("provider", "DeepSeek"),
                    "api_key": saved.get("api_key", ""),
                    "base_url": saved.get("base_url", "https://api.deepseek.com"),
                    "model": saved.get("model", "deepseek-v4-flash"),
                }
                saved["translation_api"] = saved["chat_api"].copy()
                saved["image_api"] = saved["chat_api"].copy()
            config.update(saved)
            return config
        except (json.JSONDecodeError, OSError):
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_api_config(config: dict, key: str) -> dict:
    """安全获取某套 API 配置"""
    return config.get(key, _default_api())


# ========== PDF 图书馆 ==========

def load_library() -> list[dict]:
    ensure_config_dir()
    if LIBRARY_FILE.exists():
        try:
            with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_library(library: list[dict]):
    ensure_config_dir()
    with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)


def add_pdf_to_library(pdf_info: dict):
    library = load_library()
    for item in library:
        if item.get("path") == pdf_info.get("path"):
            item.update(pdf_info)
            save_library(library)
            return
    library.append(pdf_info)
    save_library(library)


def remove_pdf_from_library(pdf_path: str):
    library = [item for item in load_library() if item.get("path") != pdf_path]
    save_library(library)


def get_library_folders(library: list[dict]) -> list[str]:
    folders = {item.get("folder", "") for item in library if item.get("folder")}
    return sorted(folders)


# ========== 按文档隔离的聊天历史 ==========

def _doc_id(file_path: str) -> str:
    """用路径的 MD5 作为文档唯一标识"""
    return hashlib.md5(file_path.encode()).hexdigest()[:12]


def _chat_file(file_path: str) -> Path:
    return CHATS_DIR / f"{_doc_id(file_path)}.json"


def load_chat_history(file_path: str) -> list[dict]:
    """加载某 PDF 的对话历史"""
    f = _chat_file(file_path)
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_chat_history(file_path: str, messages: list[dict]):
    """保存某 PDF 的对话历史"""
    ensure_config_dir()
    with open(_chat_file(file_path), "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def delete_chat_history(file_path: str):
    """删除某 PDF 的对话历史"""
    f = _chat_file(file_path)
    if f.exists():
        f.unlink()
