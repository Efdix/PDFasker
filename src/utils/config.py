"""
配置管理 —— 所有数据存储在用户设定的图书馆目录下。

目录结构::

    {library_path}/
      ├── .pdfasker/
      │   ├── config.json        # API 配置
      │   ├── library.json       # PDF 图书列表
      │   ├── chats/             # 对话历史
      │   ├── states/            # 排版/翻译状态
      │   ├── para_cache/        # 段落解析缓存
      │   └── image_cache/       # 图片提取缓存
      └── *.pdf                  # 导入的 PDF 文件
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# ---- 常量 ----

_DEFAULT_LIBRARY = Path.home() / "Documents" / "PDFasker_Library"


def _default_api(provider: str = "DeepSeek", model: str = "deepseek-v4-flash") -> dict:
    """生成默认的 API 配置字典。"""
    return {
        "provider": provider,
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": model,
    }


DEFAULT_CONFIG: dict = {
    "chat_api": _default_api("DeepSeek", "deepseek-v4-flash"),
    "translation_api": _default_api("DeepSeek", "deepseek-v4-flash"),
    "image_api": _default_api("DeepSeek", "deepseek-v4-flash"),
    "review_api": _default_api("DeepSeek", "deepseek-v4-flash"),
    "format_api": _default_api("DeepSeek", "deepseek-v4-flash"),
    "max_tokens": 1_000_000,
    "library_path": str(_DEFAULT_LIBRARY),
    "zotero_data_dir": "",
}

# ---- 路径工具 ----

def _data_dir(library_path: str | None = None) -> Path:
    """获取数据目录（图书馆路径下的 .pdfasker/）。"""
    base = Path(library_path) if library_path else _DEFAULT_LIBRARY
    return base / ".pdfasker"


def _config_file() -> Path:
    """配置文件始终从默认路径读取，因为 config.json 里存着用户自定义的 library_path。"""
    d = _DEFAULT_LIBRARY / ".pdfasker"
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def _resolve_data_dir(config: dict) -> Path:
    """根据 config 中的 library_path 解析实际数据目录。"""
    lp = config.get("library_path", str(_DEFAULT_LIBRARY))
    d = Path(lp) / ".pdfasker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _doc_id(file_path: str) -> str:
    """基于文件路径生成短文档标识符（MD5 前 12 位）。"""
    return hashlib.md5(file_path.encode()).hexdigest()[:12]


# ========== 配置读写 ==========

def load_config() -> dict:
    """加载配置，兼容旧版本数据格式。"""
    cf = _config_file()
    if not cf.exists():
        return DEFAULT_CONFIG.copy()

    try:
        saved = json.loads(cf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        saved = {}

    config = DEFAULT_CONFIG.copy()

    # 兼容旧格式：单 API key → 多 API 配置
    if "api_key" in saved and "chat_api" not in saved:
        saved["chat_api"] = {
            "provider": saved.get("provider", "DeepSeek"),
            "api_key": saved.get("api_key", ""),
            "base_url": saved.get("base_url", "https://api.deepseek.com"),
            "model": saved.get("model", "deepseek-v4-flash"),
        }
        saved["translation_api"] = saved["chat_api"].copy()
        saved["image_api"] = saved["chat_api"].copy()

    # 兼容无 format_api 的旧版本
    if "format_api" not in saved:
        saved["format_api"] = saved.get("translation_api", _default_api()).copy()

    config.update(saved)
    return config


def save_config(config: dict) -> None:
    """保存配置到 JSON 文件。"""
    cf = _config_file()
    cf.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_api_config(config: dict, key: str) -> dict:
    """从配置中提取指定 API 的配置，缺失时返回默认值。"""
    return config.get(key, _default_api())


# ========== PDF 图书馆 ==========

def _library_file(config: dict | None = None) -> Path:
    if config is None:
        config = load_config()
    return _resolve_data_dir(config) / "library.json"


def load_library() -> list[dict]:
    """加载 PDF 图书馆列表。"""
    lf = _library_file()
    if lf.exists():
        try:
            return json.loads(lf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_library(library: list[dict]) -> None:
    """保存 PDF 图书馆列表。"""
    lf = _library_file()
    lf.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")


def add_pdf_to_library(pdf_info: dict) -> None:
    """添加或更新 PDF 条目到图书馆。若已存在同路径条目则更新。"""
    lib = load_library()
    for item in lib:
        if item.get("path") == pdf_info.get("path"):
            item.update(pdf_info)
            save_library(lib)
            return
    lib.append(pdf_info)
    save_library(lib)


def remove_pdf_from_library(pdf_path: str) -> None:
    """从图书馆中移除指定 PDF。"""
    lib = [item for item in load_library() if item.get("path") != pdf_path]
    save_library(lib)


def get_library_folders(library: list[dict]) -> list[str]:
    """获取所有已使用的文件夹名称（去重排序）。"""
    return sorted({item.get("folder", "") for item in library if item.get("folder")})


# ========== 对话历史 ==========

def _chats_dir(config: dict | None = None) -> Path:
    if config is None:
        config = load_config()
    d = _resolve_data_dir(config) / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_chat_history(file_path: str) -> list[dict]:
    """加载指定文档的对话历史。"""
    f = _chats_dir() / f"{_doc_id(file_path)}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_chat_history(file_path: str, messages: list[dict]) -> None:
    """保存对话历史到文件。"""
    f = _chats_dir() / f"{_doc_id(file_path)}.json"
    f.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_chat_history(file_path: str) -> None:
    """删除指定文档的对话历史文件。"""
    f = _chats_dir() / f"{_doc_id(file_path)}.json"
    if f.exists():
        f.unlink()


# ========== 图片缓存目录 ==========

def get_image_cache_dir() -> Path:
    """获取图片缓存目录路径。"""
    config = load_config()
    d = _resolve_data_dir(config) / "image_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ========== 排版 & 翻译状态持久化 ==========

def _states_dir(config: dict | None = None) -> Path:
    if config is None:
        config = load_config()
    d = _resolve_data_dir(config) / "states"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_doc_state(file_path: str) -> dict:
    """加载某篇文档的排版/翻译状态。"""
    f = _states_dir() / f"{_doc_id(file_path)}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_doc_state(file_path: str, state: dict) -> None:
    """保存某篇文档的排版/翻译状态。"""
    f = _states_dir() / f"{_doc_id(file_path)}.json"
    f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_doc_state(file_path: str) -> None:
    """删除某篇文档的排版/翻译状态文件。"""
    f = _states_dir() / f"{_doc_id(file_path)}.json"
    if f.exists():
        f.unlink()


# ========== 段落缓存 ==========

def _cache_dir() -> Path:
    config = load_config()
    d = _resolve_data_dir(config) / "para_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_paragraph_cache(file_path: str) -> tuple[list[dict], str] | None:
    """加载段落缓存；若 PDF 修改时间不匹配则返回 None。

    Returns:
        (paragraphs, full_text) 或 None 表示缓存失效。
    """
    f = _cache_dir() / f"{_doc_id(file_path)}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        cached_mtime = data.get("_mtime", 0)
        real_mtime = os.path.getmtime(file_path)
        if abs(cached_mtime - real_mtime) > 1.0:
            return None
        paras = data.get("paragraphs", [])
        # bbox 在 JSON 中存为 list，恢复为 tuple
        for p in paras:
            if "bbox" in p and isinstance(p["bbox"], list):
                p["bbox"] = tuple(p["bbox"])
        full_text = data.get("full_text", "")
        return (paras, full_text)
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def save_paragraph_cache(file_path: str, paragraphs: list[dict], full_text: str = "") -> None:
    """保存段落缓存，附带 PDF 最后修改时间戳。"""
    f = _cache_dir() / f"{_doc_id(file_path)}.json"
    clean: list[dict] = []
    for p in paragraphs:
        cp = dict(p)
        if "bbox" in cp and isinstance(cp["bbox"], tuple):
            cp["bbox"] = list(cp["bbox"])
        clean.append(cp)
    data = {
        "_mtime": os.path.getmtime(file_path),
        "paragraphs": clean,
        "full_text": full_text,
    }
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
