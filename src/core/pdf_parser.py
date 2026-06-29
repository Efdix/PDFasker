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
        智能分段。先按块+间距分逻辑段，再句子级切分，同时识别元信息。
        """
        import re
        blocks = self.extract_blocks()
        images = {img["page"]: img for img in self.extract_images()}

        raw_paras = []
        current_lines = []
        current_fonts = []  # 当前段落各行的字号
        current_page = 1
        last_y = -999

        for block in blocks:
            if block["type"] == "image_placeholder":
                if current_lines:
                    raw_paras.append({
                        "text": "\n".join(current_lines),
                        "is_heading": self._is_heading(" ".join(current_lines), current_fonts),
                        "is_meta": self._is_metadata(" ".join(current_lines)),
                        "page": current_page, "image_path": "",
                    })
                    current_lines = []; current_fonts = []
                img = images.get(block["page"])
                raw_paras.append({
                    "text": "", "is_heading": False, "is_meta": False,
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
                        "is_heading": self._is_heading(" ".join(current_lines), current_fonts),
                        "is_meta": self._is_metadata(" ".join(current_lines)),
                        "page": current_page, "image_path": "",
                    })
                    current_lines = []; current_fonts = []
                current_page = page; last_y = -999

            gap = y - last_y if last_y > 0 else 0
            if gap > fs * 2.5 and current_lines:
                raw_paras.append({
                    "text": "\n".join(current_lines),
                    "is_heading": self._is_heading(" ".join(current_lines), current_fonts),
                    "is_meta": self._is_metadata(" ".join(current_lines)),
                    "page": page, "image_path": "",
                })
                current_lines = []; current_fonts = []

            current_lines.append(text)
            current_fonts.append(fs)
            last_y = y

        if current_lines:
            raw_paras.append({
                "text": "\n".join(current_lines),
                "is_heading": self._is_heading(" ".join(current_lines), current_fonts),
                "is_meta": self._is_metadata(" ".join(current_lines)),
                "page": current_page, "image_path": "",
            })

        # 后处理：句子级切分（阈值 200 字/段）
        result = []
        for para in raw_paras:
            if para["image_path"] or para["is_heading"] or para["is_meta"] or len(para["text"]) < 200:
                result.append(para)
            else:
                sentences = re.split(
                    r'(?<=[.!?])\s+(?=[A-Z])|(?<=[。！？])\s*',
                    para["text"]
                )
                buffer = ""
                for s in sentences:
                    s = s.strip()
                    if not s: continue
                    if len(buffer) + len(s) < 200:
                        buffer = (buffer + " " + s).strip() if buffer else s
                    else:
                        if buffer:
                            result.append({**para, "text": buffer, "is_heading": False})
                        buffer = s
                if buffer:
                    result.append({**para, "text": buffer, "is_heading": False})

        return result

    def _is_heading(self, text: str, fonts: list[float]) -> bool:
        """用段落内第一行字号 + 内容特征判断""" 
        if not text or not fonts: return False
        first_font = fonts[0]
        if first_font > 13: return True
        if len(text) < 80 and first_font > 11: return True
        if len(text) < 100 and text.strip().isupper(): return True
        if len(text) < 120 and (text.strip()[0].isdigit() or text.strip().startswith(("I", "II", "III", "IV", "V"))):
            return True
        return False

    def _is_metadata(self, text: str) -> bool:
        """识别作者、单位、DOI、日期、版权等元信息"""
        import re
        t = text.strip()
        if len(t) > 500: return False  # 太长不是元信息
        # 作者列表模式：名字, 名字, ... 或 名姓上标数字
        if re.search(r'^[\w\-\s,;．·•\d†‡*⊛⍟]+$', t) and len(t) < 300 and t.count(',') >= 2:
            return True
        # 邮箱
        if re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', t): return True
        # DOI
        if re.search(r'10\.\d{4,}/', t): return True
        # 日期/投稿信息
        if re.match(r'^(Received|Accepted|Published|Submitted|Date|Posted)', t, re.IGNORECASE): return True
        # 版权/会议信息
        if re.search(r'(©|Copyright|All rights reserved|IEEE|ACM|Proceedings|Conference|Workshop|Symposium)', t): return True
        # 作者标注：纯数字+逗号列表（上标机构编号）
        if re.match(r'^[\d,\s]+$', t) and len(t) < 50: return True
        # 通讯作者标注
        if re.search(r'(corresponding author|email:|E-mail:|✉)', t, re.IGNORECASE): return True
        # "Keywords", "Index Terms" 等标签行
        if re.match(r'^(Keywords|Index Terms|Key words|MSC|PACS|JEL)', t, re.IGNORECASE) and len(t) < 200: return True
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
