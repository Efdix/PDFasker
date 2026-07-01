"""PDF 解析器 —— 精简版：文本提取 + 页面渲染 + 图片提取。

保留纯工具性功能供 pdf_processor 使用。
所有智能解析（段落分割、结构识别、图表理解）已迁移至 pdf_processor.py
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import fitz  # PyMuPDF

if TYPE_CHECKING:
    pass


class PDFParser:
    """PDF 基础解析器 —— 提供文本提取、页面渲染、图片提取等底层能力。

    不再包含任何智能解析逻辑（列检测、段落合并、标题识别等），
    这些已全部交给 pdf_processor.py 中的视觉 LLM 管线处理。
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self._doc = fitz.open(file_path)
        self._full_text: str | None = None
        self._image_dir: str = ""
        self._images: list[dict] | None = None

    @property
    def page_count(self) -> int:
        return len(self._doc)

    @property
    def metadata(self) -> dict:
        return self._doc.metadata

    def get_toc(self) -> list[dict]:
        toc = self._doc.get_toc(simple=False)
        if not toc:
            return []
        result = []
        for item in toc:
            level, title, page = item[0], item[1], item[2]
            if title.strip():
                result.append({"level": level, "title": title.strip(), "page": page})
        return result

    def set_image_output_dir(self, directory: str) -> None:
        self._image_dir = directory
        os.makedirs(directory, exist_ok=True)

    def close(self) -> None:
        self._doc.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def render_page_to_base64(self, page_num: int, dpi: int = 150) -> str:
        import base64
        page = self._doc[page_num - 1]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def render_all_pages_to_base64(self, dpi: int = 150) -> list[str]:
        return [self.render_page_to_base64(i + 1, dpi) for i in range(len(self._doc))]

    @staticmethod
    def render_image_region(page, bbox: tuple, output_path: str, dpi: int = 200) -> None:
        x0, y0, x1, y1 = bbox
        clip = fitz.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, clip=clip)
        pix.save(output_path)

    def extract_text_by_page(self) -> dict[int, str]:
        result: dict[int, str] = {}
        for i, page in enumerate(self._doc, 1):
            text = page.get_text()
            if text.strip():
                result[i] = text.strip()
        return result

    def extract_full_text(self) -> str:
        if self._full_text is not None:
            return self._full_text
        parts = []
        for i, page in enumerate(self._doc, 1):
            text = page.get_text()
            if text.strip():
                parts.append(f"[第 {i} 页]\n{text.strip()}")
        self._full_text = "\n\n".join(parts)
        return self._full_text

    def get_page_text(self, page_num: int) -> str:
        if page_num < 1 or page_num > len(self._doc):
            return ""
        return self._doc[page_num - 1].get_text().strip()

    def extract_images(self) -> list[dict]:
        if self._images is not None:
            return self._images
        self._images = []
        for page_num, page in enumerate(self._doc, 1):
            image_list = page.get_images(full=True)
            for img_idx, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = self._doc.extract_image(xref)
                    orig_w = base_image["width"]
                    orig_h = base_image["height"]
                    img_rects = page.get_image_rects(xref)
                    bbox = (0, 0, 0, 0)
                    if img_rects:
                        r = img_rects[0]
                        bbox = (r.x0, r.y0, r.x1, r.y1)
                    img_path = ""
                    if self._image_dir:
                        img_filename = f"page{page_num}_img{img_idx}.png"
                        img_path = os.path.join(self._image_dir, img_filename)
                        if not os.path.exists(img_path):
                            self._extract_image_safe(xref, img_path, page, bbox)
                    self._images.append({
                        "page": page_num,
                        "index": img_idx,
                        "path": img_path,
                        "width": orig_w,
                        "height": orig_h,
                        "ext": "png",
                        "bbox": bbox,
                    })
                except Exception:
                    continue
        return self._images

    def _extract_image_safe(self, xref: int, output_path: str, page, bbox: tuple) -> None:
        try:
            pix = fitz.Pixmap(self._doc, xref)
            if pix.n > 4:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            pix.save(output_path)
            return
        except Exception:
            pass
        try:
            base_image = self._doc.extract_image(xref)
            image_bytes = base_image["image"]
            orig_ext = base_image.get("ext", "").lower()
            if orig_ext in ("png", "jpeg", "jpg", "bmp", "gif"):
                with open(output_path, "wb") as f:
                    f.write(image_bytes)
                from PySide6.QtGui import QPixmap
                test = QPixmap(output_path)
                if not test.isNull():
                    return
        except Exception:
            pass
        bbox_valid = (bbox[2] - bbox[0] > 1 and bbox[3] - bbox[1] > 1)
        if bbox_valid:
            try:
                self.render_image_region(page, bbox, output_path, dpi=200)
            except Exception:
                pass
