"""
配置管理 —— 所有数据存储在用户设定的图书馆目录下
目录结构：
  {library_path}/
    ├── .pdfasker/
    │   ├── config.json      # API 配置
    │   ├── library.json     # PDF 图书列表
    │   └── chats/           # 对话历史
    └── *.pdf                # 导入的 PDF 文件
"""

import json
import hashlib
import os
from pathlib import Path

# 默认图书馆路径
_DEFAULT_LIBRARY = Path.home() / "Documents" / "PDFasker_Library"


def _data_dir(library_path: str = None) -> Path:
    """数据目录：图书馆路径下的 .pdfasker/"""
    base = Path(library_path) if library_path else _DEFAULT_LIBRARY
    return base / ".pdfasker"


def _config_file() -> Path:
    """配置文件路径（固定用默认路径找，因为首次还没有 library_path）"""
    # 始终从默认路径读取 config，里面存着用户设定的 library_path
    d = _DEFAULT_LIBRARY / ".pdfasker"
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def _resolve_data_dir(config: dict) -> Path:
    """根据 config 中的 library_path 解析实际数据目录"""
    lp = config.get("library_path", str(_DEFAULT_LIBRARY))
    d = Path(lp) / ".pdfasker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_api(provider="DeepSeek", model="deepseek-v4-flash"):
    return {"provider": provider, "api_key": "", "base_url": "https://api.deepseek.com", "model": model}


DEFAULT_CONFIG = {
    "chat_api":        _default_api("DeepSeek", "deepseek-v4-flash"),
    "translation_api": _default_api("DeepSeek", "deepseek-v4-flash"),
    "image_api":       _default_api("DeepSeek", "deepseek-v4-flash"),
    "review_api":      _default_api("DeepSeek", "deepseek-v4-flash"),
    "format_api":      _default_api("DeepSeek", "deepseek-v4-flash"),
    "max_tokens": 1_000_000,
    "library_path": str(_DEFAULT_LIBRARY),
    "zotero_data_dir": "",   # Zotero 数据目录（用户手动设置）
}


# ========== 配置读写 ==========

def load_config() -> dict:
    cf = _config_file()
    if cf.exists():
        try:
            saved = json.loads(cf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = {}
        config = DEFAULT_CONFIG.copy()
        # 兼容旧格式
        if "api_key" in saved and "chat_api" not in saved:
            saved["chat_api"] = {
                "provider": saved.get("provider", "DeepSeek"),
                "api_key": saved.get("api_key", ""),
                "base_url": saved.get("base_url", "https://api.deepseek.com"),
                "model": saved.get("model", "deepseek-v4-flash"),
            }
            saved["translation_api"] = saved["chat_api"].copy()
            saved["image_api"] = saved["chat_api"].copy()
        # 兼容无 format_api
        if "format_api" not in saved:
            saved["format_api"] = saved.get("translation_api", _default_api()).copy()
        config.update(saved)
        return config
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    cf = _config_file()
    cf.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_api_config(config: dict, key: str) -> dict:
    return config.get(key, _default_api())


# ========== PDF 图书馆 ==========

def _library_file(config: dict = None) -> Path:
    if config is None:
        config = load_config()
    return _resolve_data_dir(config) / "library.json"


def load_library() -> list[dict]:
    lf = _library_file()
    if lf.exists():
        try:
            return json.loads(lf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_library(library: list[dict]):
    lf = _library_file()
    lf.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")


def add_pdf_to_library(pdf_info: dict):
    lib = load_library()
    for item in lib:
        if item.get("path") == pdf_info.get("path"):
            item.update(pdf_info)
            save_library(lib)
            return
    lib.append(pdf_info)
    save_library(lib)


def remove_pdf_from_library(pdf_path: str):
    lib = [item for item in load_library() if item.get("path") != pdf_path]
    save_library(lib)


def get_library_folders(library: list[dict]) -> list[str]:
    return sorted({item.get("folder", "") for item in library if item.get("folder")})


# ========== 对话历史 ==========

def _chats_dir(config: dict = None) -> Path:
    if config is None:
        config = load_config()
    d = _resolve_data_dir(config) / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _doc_id(file_path: str) -> str:
    return hashlib.md5(file_path.encode()).hexdigest()[:12]


def load_chat_history(file_path: str) -> list[dict]:
    f = _chats_dir() / f"{_doc_id(file_path)}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_chat_history(file_path: str, messages: list[dict]):
    f = _chats_dir() / f"{_doc_id(file_path)}.json"
    f.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_chat_history(file_path: str):
    f = _chats_dir() / f"{_doc_id(file_path)}.json"
    if f.exists():
        f.unlink()


# ========== 图片临时目录（也在图书馆下）==========

def get_image_cache_dir() -> Path:
    config = load_config()
    d = _resolve_data_dir(config) / "image_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ========== 排版 & 翻译状态持久化（按文档隔离）==========

def _states_dir(config: dict = None) -> Path:
    if config is None:
        config = load_config()
    d = _resolve_data_dir(config) / "states"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_doc_state(file_path: str) -> dict:
    """加载某篇文档的排版/翻译状态"""
    f = _states_dir() / f"{_doc_id(file_path)}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_doc_state(file_path: str, state: dict):
    """保存某篇文档的排版/翻译状态"""
    f = _states_dir() / f"{_doc_id(file_path)}.json"
    f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_doc_state(file_path: str):
    """删除某篇文档的排版/翻译状态"""
    f = _states_dir() / f"{_doc_id(file_path)}.json"
    if f.exists():
        f.unlink()


# ========== 段落缓存（避免重复解析） ==========

def _cache_dir() -> Path:
    config = load_config()
    d = _resolve_data_dir(config) / "para_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_paragraph_cache(file_path: str) -> list[dict] | None:
    """加载段落缓存，若 PDF 修改时间不匹配则返回 None。
    返回 (paragraphs, full_text) 元组，失败返回 None。"""
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
        for p in paras:
            if "bbox" in p and isinstance(p["bbox"], list):
                p["bbox"] = tuple(p["bbox"])
        full_text = data.get("full_text", "")
        return (paras, full_text)
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def save_paragraph_cache(file_path: str, paragraphs: list[dict], full_text: str = ""):
    f = _cache_dir() / f"{_doc_id(file_path)}.json"
    clean = []
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
