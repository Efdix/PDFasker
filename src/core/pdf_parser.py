"""
PDF 解析器 —— 使用 PyMuPDF (fitz) 提取文本
"""

import fitz  # PyMuPDF


class PDFParser:
    """PDF 文件解析器，提取文本内容及元信息"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._doc = fitz.open(file_path)
        self._full_text: str | None = None
        self._pages: list[dict] | None = None

    @property
    def page_count(self) -> int:
        return len(self._doc)

    @property
    def metadata(self) -> dict:
        """返回 PDF 元数据（标题、作者等）"""
        return self._doc.metadata

    def extract_full_text(self) -> str:
        """提取全部文本，带页码标记"""
        if self._full_text is not None:
            return self._full_text

        parts = []
        for i, page in enumerate(self._doc, 1):
            text = page.get_text()
            if text.strip():
                parts.append(f"[第 {i} 页]\n{text.strip()}")
        self._full_text = "\n\n".join(parts)
        return self._full_text

    def extract_pages(self) -> list[dict]:
        """逐页提取，返回 [{'page': int, 'text': str}, ...]"""
        if self._pages is not None:
            return self._pages

        self._pages = []
        for i, page in enumerate(self._doc, 1):
            text = page.get_text().strip()
            if text:
                self._pages.append({"page": i, "text": text})
        return self._pages

    def get_text_preview(self, max_chars: int = 2000) -> str:
        """获取文本预览（前 N 个字符）"""
        full = self.extract_full_text()
        if len(full) <= max_chars:
            return full
        return full[:max_chars] + f"\n\n...（共 {len(full)} 字符，已截断预览）"

    def close(self):
        self._doc.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
