"""
PDF 解析器 —— 使用 PyMuPDF (fitz) 提取文本、图片
"""

import io
import os
import fitz  # PyMuPDF


class PDFParser:
    """PDF 文件解析器，提取文本块、图片及元信息"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._doc = fitz.open(file_path)
        self._full_text: str | None = None
        self._blocks: list[dict] | None = None
        self._images: list[dict] | None = None
        self._image_dir: str = ""

    @property
    def page_count(self) -> int:
        return len(self._doc)

    @property
    def metadata(self) -> dict:
        return self._doc.metadata

    def set_image_output_dir(self, directory: str):
        """设置图片导出目录"""
        self._image_dir = directory
        os.makedirs(directory, exist_ok=True)

    # ========== 文本提取 ==========

    def extract_full_text(self) -> str:
        """提取全部文本（用于发送给 AI）"""
        if self._full_text is not None:
            return self._full_text
        parts = []
        for i, page in enumerate(self._doc, 1):
            text = page.get_text()
            if text.strip():
                parts.append(f"[第 {i} 页]\n{text.strip()}")
        self._full_text = "\n\n".join(parts)
        return self._full_text

    def extract_blocks(self) -> list[dict]:
        """
        按块提取文本 —— 比 get_text() 更结构化。
        每块包含: page, type (text/image), text, bbox, font_size
        """
        if self._blocks is not None:
            return self._blocks

        self._blocks = []
        for page_num, page in enumerate(self._doc, 1):
            # 获取页面尺寸
            page_rect = page.rect
            page_width = page_rect.width

            # 用 "dict" 模式获取结构化数据
            blocks_data = page.get_text("dict")["blocks"]

            for block in blocks_data:
                if block["type"] == 0:  # 文本块
                    for line in block.get("lines", []):
                        text_parts = []
                        max_font = 0
                        for span in line.get("spans", []):
                            text_parts.append(span["text"])
                            max_font = max(max_font, span.get("size", 10))
                        full_text = "".join(text_parts).strip()
                        if full_text:
                            bbox = line["bbox"]
                            self._blocks.append({
                                "page": page_num,
                                "type": "text",
                                "text": full_text,
                                "bbox": bbox,
                                "font_size": max_font,
                                "x": bbox[0],
                                "y": bbox[1],
                            })
                elif block["type"] == 1:  # 图片块
                    bbox = block["bbox"]
                    self._blocks.append({
                        "page": page_num,
                        "type": "image_placeholder",
                        "text": "[图片]",
                        "bbox": bbox,
                        "font_size": 0,
                        "x": bbox[0],
                        "y": bbox[1],
                    })

        return self._blocks

    def extract_structured_paragraphs(self) -> list[dict]:
        """
        智能分段：基于文本块位置和字体信息。
        后续对过长段落做句子级切分，方便阅读。
        """
        import re
        blocks = self.extract_blocks()
        images = {img["page"]: img for img in self.extract_images()}

        raw_paras = []  # [{text, is_heading, page, image_path}]
        current_lines = []
        current_page = 1
        last_y = -999
        last_font = 10

        for block in blocks:
            if block["type"] == "image_placeholder":
                if current_lines:
                    raw_paras.append({
                        "text": "\n".join(current_lines),
                        "is_heading": self._is_heading(" ".join(current_lines), last_font),
                        "page": current_page, "image_path": "",
                    })
                    current_lines = []
                img = images.get(block["page"])
                raw_paras.append({
                    "text": "", "is_heading": False,
                    "page": block["page"],
                    "image_path": img["path"] if img else "",
                })
                last_y = -999
                continue

            page, y, fs, text = block["page"], block["y"], block["font_size"], block["text"]

            if page != current_page:
                if current_lines:
                    raw_paras.append({
                        "text": "\n".join(current_lines),
                        "is_heading": self._is_heading(" ".join(current_lines), last_font),
                        "page": current_page, "image_path": "",
                    })
                    current_lines = []
                current_page = page; last_y = -999

            gap = y - last_y if last_y > 0 else 0
            if gap > fs * 2.5 and current_lines:
                raw_paras.append({
                    "text": "\n".join(current_lines),
                    "is_heading": self._is_heading(" ".join(current_lines), last_font),
                    "page": page, "image_path": "",
                })
                current_lines = []

            current_lines.append(text)
            last_y = y
            last_font = max(last_font, fs)

        if current_lines:
            raw_paras.append({
                "text": "\n".join(current_lines),
                "is_heading": self._is_heading(" ".join(current_lines), last_font),
                "page": current_page, "image_path": "",
            })

        # 后处理：对过长的段落做句子级切分
        result = []
        for para in raw_paras:
            if para["image_path"] or para["is_heading"] or len(para["text"]) < 300:
                result.append(para)
            else:
                # 在句子边界处切分（英文用 . ! ? 后跟空格+大写，中文用。！？）
                sentences = re.split(
                    r'(?<=[.!?])\s+(?=[A-Z])|(?<=[。！？])\s*',
                    para["text"]
                )
                buffer = ""
                for s in sentences:
                    s = s.strip()
                    if not s: continue
                    if len(buffer) + len(s) < 400:
                        buffer = (buffer + " " + s).strip() if buffer else s
                    else:
                        if buffer:
                            result.append({**para, "text": buffer})
                        buffer = s
                if buffer:
                    result.append({**para, "text": buffer})

        return result

    def _is_heading(self, text: str, font_size: float) -> bool:
        """判断文本是否是章节标题"""
        if not text:
            return False
        # 字号明显大于正文（正文一般 9-11pt）
        if font_size > 13:
            return True
        # 全大写且短
        if len(text) < 100 and text.isupper():
            return True
        # 编号开头
        if len(text) < 120 and (
            text[0].isdigit() or text.startswith(("I", "II", "III", "IV", "V"))
        ):
            return True
        return False

    # ========== 图片提取 ==========

    def extract_images(self) -> list[dict]:
        """提取 PDF 中所有图片，保存到文件"""
        if self._images is not None:
            return self._images

        self._images = []
        for page_num, page in enumerate(self._doc, 1):
            image_list = page.get_images(full=True)
            for img_idx, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = self._doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    ext = base_image["ext"]

                    # 保存图片
                    if self._image_dir:
                        img_filename = f"page{page_num}_img{img_idx}.{ext}"
                        img_path = os.path.join(self._image_dir, img_filename)
                        with open(img_path, "wb") as f:
                            f.write(image_bytes)
                    else:
                        img_path = ""

                    self._images.append({
                        "page": page_num,
                        "index": img_idx,
                        "path": img_path,
                        "width": base_image["width"],
                        "height": base_image["height"],
                        "ext": ext,
                    })
                except Exception:
                    continue

        return self._images

    def close(self):
        self._doc.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
