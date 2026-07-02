"""写作教练 —— 知识库管理 + 风格分析 + 引用感知改写 + 遗漏文献检测。

Phase 1: 知识库 CRUD + 参考论文/期刊范文管理
Phase 2: LLM 风格指南生成
Phase 3: Zotero 引用感知改写 + S2 遗漏文献检测
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm_client import LLMClient


# ============================================================
# 数据结构
# ============================================================

@dataclass
class WritingProfile:
    """写作知识库配置。"""

    name: str = ""                         # 知识库名称
    writing_type: str = "综述"              # 写作类型 key
    created_at: str = ""
    updated_at: str = ""
    personal_papers: list[dict] = field(default_factory=list)    # [{filename, original_path, text}]
    journal_papers: list[dict] = field(default_factory=list)     # 同上
    style_guide: dict | None = None        # Phase 2: LLM 生成的风格指南

    @property
    def personal_count(self) -> int:
        return len(self.personal_papers)

    @property
    def journal_count(self) -> int:
        return len(self.journal_papers)

    @property
    def total_papers(self) -> int:
        return self.personal_count + self.journal_count

    @property
    def has_style_guide(self) -> bool:
        return self.style_guide is not None and bool(self.style_guide)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "writing_type": self.writing_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "personal_papers": [
                {"filename": p["filename"], "original_path": p.get("original_path", ""), "text": p["text"]}
                for p in self.personal_papers
            ],
            "journal_papers": [
                {"filename": p["filename"], "original_path": p.get("original_path", ""), "text": p["text"]}
                for p in self.journal_papers
            ],
            "style_guide": self.style_guide,
        }

    @staticmethod
    def from_dict(d: dict) -> "WritingProfile":
        return WritingProfile(
            name=d.get("name", ""),
            writing_type=d.get("writing_type", "综述"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            personal_papers=d.get("personal_papers", []),
            journal_papers=d.get("journal_papers", []),
            style_guide=d.get("style_guide"),
        )


# ============================================================
# 写作教练
# ============================================================

class WritingCoach:
    """写作教练 —— 管理知识库、生成风格指南、辅助写作。"""

    def __init__(self) -> None:
        self._kb_dir = self._resolve_kb_dir()
        self._current_profile: WritingProfile | None = None
        self._profiles: dict[str, WritingProfile] = {}
        self._load_profiles()

    # ---- 路径 ----

    @staticmethod
    def _resolve_kb_dir() -> Path:
        from ..utils.config import load_config, _resolve_data_dir
        config = load_config()
        d = _resolve_data_dir(config) / "writing_kb"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _profile_dir(self, name: str) -> Path:
        return self._kb_dir / name

    def _profile_config_path(self, name: str) -> Path:
        return self._profile_dir(name) / "config.json"

    def _papers_dir(self, name: str, paper_type: str) -> Path:
        """paper_type: 'personal' | 'journal'"""
        d = self._profile_dir(name) / f"{paper_type}_papers"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- 加载 ----

    def _load_profiles(self) -> None:
        """扫描 knowledge base 目录，加载所有 profile。"""
        self._profiles.clear()
        if not self._kb_dir.exists():
            return
        for entry in self._kb_dir.iterdir():
            if entry.is_dir():
                cfg_path = entry / "config.json"
                if cfg_path.exists():
                    try:
                        data = json.loads(cfg_path.read_text(encoding="utf-8"))
                        profile = WritingProfile.from_dict(data)
                        self._profiles[profile.name] = profile
                    except (json.JSONDecodeError, OSError):
                        pass

    def _save_profile(self, profile: WritingProfile) -> None:
        """保存 profile 配置到磁盘。"""
        d = self._profile_dir(profile.name)
        d.mkdir(parents=True, exist_ok=True)
        cfg_path = d / "config.json"
        cfg_path.write_text(
            json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 公共 API: 知识库管理 ----

    @property
    def profile_names(self) -> list[str]:
        return sorted(self._profiles.keys())

    @property
    def current_profile(self) -> WritingProfile | None:
        return self._current_profile

    def create_profile(self, name: str, writing_type: str = "综述") -> WritingProfile:
        """创建新的写作知识库。"""
        from datetime import datetime

        if name in self._profiles:
            raise ValueError(f"知识库 '{name}' 已存在")

        now = datetime.now().isoformat()
        profile = WritingProfile(
            name=name,
            writing_type=writing_type,
            created_at=now,
            updated_at=now,
        )
        self._profiles[name] = profile
        self._save_profile(profile)
        self._current_profile = profile
        return profile

    def switch_profile(self, name: str) -> WritingProfile:
        """切换到指定知识库。"""
        if name not in self._profiles:
            raise ValueError(f"知识库 '{name}' 不存在")
        self._current_profile = self._profiles[name]
        return self._current_profile

    def delete_profile(self, name: str) -> None:
        """删除知识库及其所有数据。"""
        if name not in self._profiles:
            return
        d = self._profile_dir(name)
        if d.exists():
            shutil.rmtree(str(d))
        self._profiles.pop(name, None)
        if self._current_profile and self._current_profile.name == name:
            self._current_profile = None

    # ---- 公共 API: 论文管理 ----

    def add_personal_paper(self, pdf_path: str) -> dict | None:
        """添加一篇个人参考论文到当前知识库。

        Returns:
            {"filename": str, "text": str} 或 None（失败时）
        """
        return self._add_paper(pdf_path, "personal")

    def add_journal_paper(self, pdf_path: str) -> dict | None:
        """添加一篇目标期刊范文到当前知识库。"""
        return self._add_paper(pdf_path, "journal")

    def remove_personal_paper(self, filename: str) -> None:
        """移除一篇个人参考论文。"""
        self._remove_paper(filename, "personal")

    def remove_journal_paper(self, filename: str) -> None:
        """移除一篇期刊范文。"""
        self._remove_paper(filename, "journal")

    def clear_personal_papers(self) -> None:
        """清空所有个人参考论文。"""
        if self._current_profile:
            self._current_profile.personal_papers.clear()
            self._save_profile(self._current_profile)

    def clear_journal_papers(self) -> None:
        """清空所有期刊范文。"""
        if self._current_profile:
            self._current_profile.journal_papers.clear()
            self._save_profile(self._current_profile)

    # ---- 内部: 论文添加/移除 ----

    def _add_paper(self, pdf_path: str, paper_type: str) -> dict | None:
        """添加论文到知识库（通用）。"""
        if not self._current_profile:
            return None
        if not os.path.isfile(pdf_path):
            return None

        import fitz

        try:
            doc = fitz.open(pdf_path)
            text_parts = []
            for page in doc:
                t = page.get_text()
                if t.strip():
                    text_parts.append(t.strip())
            doc.close()
            full_text = "\n\n".join(text_parts)
        except Exception:
            return None

        if not full_text.strip():
            return None

        filename = os.path.basename(pdf_path)
        # 存文本到 papers 目录（供检索）
        papers_dir = self._papers_dir(self._current_profile.name, paper_type)
        txt_path = papers_dir / (filename + ".txt")
        txt_path.write_text(full_text, encoding="utf-8")

        paper_entry = {
            "filename": filename,
            "original_path": pdf_path,
            "text": full_text,
        }

        target_list = (
            self._current_profile.personal_papers if paper_type == "personal"
            else self._current_profile.journal_papers
        )
        # 去重（同文件名替换）
        target_list[:] = [p for p in target_list if p["filename"] != filename]
        target_list.append(paper_entry)

        from datetime import datetime
        self._current_profile.updated_at = datetime.now().isoformat()
        self._save_profile(self._current_profile)

        return paper_entry

    def _remove_paper(self, filename: str, paper_type: str) -> None:
        if not self._current_profile:
            return
        target_list = (
            self._current_profile.personal_papers if paper_type == "personal"
            else self._current_profile.journal_papers
        )
        target_list[:] = [p for p in target_list if p["filename"] != filename]

        # 删除文本文件
        papers_dir = self._papers_dir(self._current_profile.name, paper_type)
        txt_path = papers_dir / (filename + ".txt")
        if txt_path.exists():
            txt_path.unlink()

        from datetime import datetime
        self._current_profile.updated_at = datetime.now().isoformat()
        self._save_profile(self._current_profile)

    # ---- 公共 API: 获取拼接文本 ----

    def get_all_paper_texts(self) -> str:
        """获取当前知识库中所有论文的拼接文本（供风格分析用）。"""
        if not self._current_profile:
            return ""
        parts = []
        for p in self._current_profile.personal_papers:
            parts.append(f"--- 个人论文: {p['filename']} ---\n{p.get('text', '')}")
        for p in self._current_profile.journal_papers:
            parts.append(f"--- 期刊范文: {p['filename']} ---\n{p.get('text', '')}")
        return "\n\n".join(parts)

    def build_writing_system_prompt(self, writing_type: str = "综述") -> str:
        """构建完整的写作 system prompt（硬编码原则 + 风格指南）。"""
        from .writing_prompts import get_writing_type_config

        cfg = get_writing_type_config(writing_type)
        prompt = cfg["system_prompt"]

        # 附加风格指南
        if self._current_profile and self._current_profile.has_style_guide:
            guide = self._current_profile.style_guide
            guide_text = self._format_style_guide(guide)
            if guide_text:
                prompt += "\n\n---\n以下是你需要遵循的具体格式和风格规范（基于真实论文分析）：\n\n" + guide_text

        return prompt

    @staticmethod
    def _format_style_guide(guide: dict) -> str:
        """将风格指南 dict 格式化为 prompt 可用的文字。"""
        parts = []
        if guide.get("citation_style"):
            parts.append(f"【引用格式】\n{guide['citation_style']}")
        if guide.get("structure_template"):
            parts.append(f"【结构模板】\n{guide['structure_template']}")
        if guide.get("terminology_preferences"):
            parts.append(f"【术语偏好】\n{guide['terminology_preferences']}")
        if guide.get("sentence_templates"):
            if isinstance(guide["sentence_templates"], list):
                parts.append("【句式模板】\n" + "\n".join(f"· {s}" for s in guide["sentence_templates"]))
            else:
                parts.append(f"【句式模板】\n{guide['sentence_templates']}")
        if guide.get("general_notes"):
            parts.append(f"【其他注意事项】\n{guide['general_notes']}")
        return "\n\n".join(parts)

    # ---- Phase 2: 风格指南生成 ----

    STYLE_ANALYSIS_PROMPT = """你是一位学术写作风格分析专家。请分析以下论文的写作风格，提炼出可操作的写作规范。

## 分析要点

1. **引用格式**: 文中引用是 [1] 编号制还是 (Author, Year)？参考文献列表格式？
2. **结构模板**: 论文/综述的典型章节结构是什么？每个章节有没有特定的开头/结尾套路？
3. **术语偏好**: 有哪些高频术语或固定搭配？有没有明显的用词偏好（如 nervous system vs neural system）？
4. **句式模板**: 摘录 5-10 个常见句式模板（如开头句、过渡句、总结句）
5. **图表描述惯例**: 图表标题格式（Figure 1. vs Fig. 1.）？正文中如何引用图表？
6. **段落组织**: 段落长度偏好？主题句位置？段落间过渡方式？

## 输出格式

请严格返回 JSON（不要加 Markdown 标记）：

{
  "citation_style": "引用格式描述",
  "structure_template": "结构模板描述",
  "terminology_preferences": "术语偏好描述",
  "sentence_templates": ["句式1", "句式2", "..."],
  "figure_conventions": "图表惯例描述",
  "paragraph_patterns": "段落组织模式描述",
  "general_notes": "其他值得注意的风格特征"
}

以下是需要分析的论文文本：
{paper_texts}"""

    def generate_style_guide(self, parse_client: "LLMClient") -> dict | None:
        """生成风格指南 —— 读取知识库中所有论文文本，发给 LLM 分析。

        Returns:
            风格指南 dict，失败返回 None。
        """
        if not self._current_profile:
            return None
        if self._current_profile.total_papers == 0:
            return None

        all_text = self.get_all_paper_texts()
        if not all_text.strip():
            return None

        # 截断过长的文本（保留前 30000 字符 + 后 5000）
        max_chars = 35000
        if len(all_text) > max_chars:
            all_text = (
                all_text[:25000]
                + "\n\n...(中间内容已省略)...\n\n"
                + all_text[-10000:]
            )

        prompt = self.STYLE_ANALYSIS_PROMPT.format(paper_texts=all_text)
        messages = [
            {"role": "system", "content": "你是学术写作风格分析专家。只返回 JSON，不要加解释。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = parse_client.chat_sync(messages, timeout=180.0, max_tokens=4000)
            guide = self._parse_style_guide_response(response)
            if guide:
                self._current_profile.style_guide = guide
                from datetime import datetime
                self._current_profile.updated_at = datetime.now().isoformat()
                self._save_profile(self._current_profile)
                return guide
        except Exception:
            pass

        return None

    @staticmethod
    def _parse_style_guide_response(raw: str) -> dict | None:
        """解析 LLM 返回的风格指南 JSON。"""
        import json as _json
        import re

        if not raw or not raw.strip():
            return None

        text = raw.strip()

        # 尝试 1: 直接解析
        try:
            return _json.loads(text)
        except (_json.JSONDecodeError, TypeError):
            pass

        # 尝试 2: 提取 ```json ... ```
        for pattern in [r'```json\s*\n?(.*?)\n?```', r'```\s*\n?(.*?)\n?```']:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                try:
                    return _json.loads(m.group(1).strip())
                except (_json.JSONDecodeError, TypeError):
                    pass

        # 尝试 3: 提取 { ... }
        first = text.find('{')
        last = text.rfind('}')
        if first >= 0 and last > first:
            try:
                return _json.loads(text[first:last + 1])
            except (_json.JSONDecodeError, TypeError):
                pass

        return None

    # ================================================================
    # Phase 3: 引用感知改写 + 遗漏文献检测
    # ================================================================

    POLISH_PROMPT = """你是学术写作润色专家。请润色以下文字，保持原意不变。

{style_context}
要求：
1. 提升学术表达的清晰度和流畅度
2. 修正语法错误和不当用词
3. 保持原有的引用标记不变
4. 输出润色后的完整文字，不要加解释"""

    CITE_REWRITE_PROMPT = """你是学术综述写作专家。请根据引文的原始文献内容，改写以下文字。

{style_context}

【待改写的文字】
{selected_text}

【引文原始内容】
{citation_texts}

要求：
1. 确保改写后的表述准确反映引文原文的发现
2. 如果原文不支持当前表述，请指出并提供更准确的版本
3. 保持综述应有的概括性风格，不要逐字照抄原文
4. 保持引文标记不变
5. 输出改写后的文字"""

    MISSING_LIT_PROMPT = """你是学术文献检索专家。分析以下综述草稿和已引用文献，找出可能遗漏的重要文献。

【综述草稿】
{draft_text}

【已引用文献】
{cited_papers}

请分析：
1. 这篇综述覆盖了哪些研究子方向？
2. 有哪些明显遗漏的研究方向或领域？（横向遗漏）
3. 在已覆盖的方向中，有没有近年（2023-2024）可能遗漏的新文献？（纵向遗漏）
4. 对每个遗漏方向，给出 3-5 个英文搜索关键词

请严格返回 JSON：
{{
  "covered_domains": [{{"domain": "方向名", "paper_count": 数字, "latest_year": 年份}}],
  "horizontal_gaps": [{{"domain": "遗漏方向", "reason": "原因", "search_queries": ["关键词1", "关键词2"]}}],
  "vertical_gaps": [{{"domain": "已有方向", "reason": "原因", "search_queries": ["关键词1"]}}]
}}"""

    def polish_text(self, write_client: "LLMClient", selected_text: str,
                    writing_type: str = "综述") -> str:
        """润色选中文字。"""
        if not selected_text.strip():
            return ""
        system_prompt = self.build_writing_system_prompt(writing_type)
        style_context = f"风格规范：\n{system_prompt}" if system_prompt else ""
        prompt = self.POLISH_PROMPT.format(
            style_context=style_context,
        )
        messages = [
            {"role": "system", "content": system_prompt or "你是学术写作润色专家。"},
            {"role": "user", "content": prompt + "\n\n待润色文字：\n" + selected_text},
        ]
        try:
            return write_client.chat_sync(messages, timeout=120.0)
        except Exception as e:
            return f"润色失败：{e}"

    def rewrite_with_citations(
        self, write_client: "LLMClient", selected_text: str,
        zotero_lib, writing_type: str = "综述",
    ) -> str:
        """基于 Zotero 引文原文改写选中文字。

        解析选中文字中的引用标记 [1][2,3] → 查 Zotero → 提取原文 → 改写。
        """
        if not selected_text.strip():
            return ""

        import re
        # 解析引用标记
        cite_pattern = re.compile(r'\[(\d+(?:[,，\s]*\d+)*)\]')
        cited_nums = set()
        for m in cite_pattern.finditer(selected_text):
            for num in re.split(r'[,，\s]+', m.group(1)):
                if num.strip().isdigit():
                    cited_nums.add(int(num.strip()))

        if not cited_nums:
            return "未在选中文字中检测到引用标记（如 [1]、[2,3]）"

        # 从 Zotero 获取引用文献
        zotero_items = []
        if zotero_lib and hasattr(zotero_lib, '_items'):
            for i, item in enumerate(zotero_lib._items):
                if (i + 1) in cited_nums:
                    zotero_items.append((i + 1, item))

        if not zotero_items:
            return f"在 Zotero 库中未找到编号 {sorted(cited_nums)} 对应的文献"

        # 提取原文
        import fitz
        citation_texts = []
        for num, item in zotero_items:
            title = item.title or "未知标题"
            text = ""
            if item.pdf_path and os.path.isfile(item.pdf_path):
                try:
                    doc = fitz.open(item.pdf_path)
                    # 只取摘要和首段（控制在 3000 字内）
                    parts = []
                    for page in doc:
                        parts.append(page.get_text())
                        if len("\n".join(parts)) > 3000:
                            break
                    text = "\n".join(parts)[:3000]
                    doc.close()
                except Exception:
                    text = f"[无法读取 PDF: {item.pdf_path}]"
            else:
                # 尝试从 Zotero 摘要中获取
                text = getattr(item, 'abstract', '') or "（无 PDF 全文，仅标题可用）"

            citation_texts.append(f"--- 引文 [{num}] {title} ---\n{text}")

        system_prompt = self.build_writing_system_prompt(writing_type)
        style_context = f"风格规范：\n{system_prompt}" if system_prompt else ""

        prompt = self.CITE_REWRITE_PROMPT.format(
            style_context=style_context,
            selected_text=selected_text,
            citation_texts="\n\n".join(citation_texts),
        )
        messages = [
            {"role": "system", "content": system_prompt or "你是学术综述写作专家。"},
            {"role": "user", "content": prompt},
        ]
        try:
            return write_client.chat_sync(messages, timeout=180.0)
        except Exception as e:
            return f"改写失败：{e}"

    def detect_missing_literature(
        self, write_client: "LLMClient", draft_text: str,
        zotero_lib,
    ) -> dict | None:
        """Step 1 of 遗漏文献检测：LLM 分析草稿 → 输出遗漏方向和搜索关键词。

        Returns:
            {"covered_domains": [...], "horizontal_gaps": [...], "vertical_gaps": [...]}
        """
        if not draft_text.strip():
            return None

        # 构建已引用文献列表
        cited_parts = []
        if zotero_lib and hasattr(zotero_lib, '_items'):
            # 从草稿中提取引用编号
            import re
            cite_pattern = re.compile(r'\[(\d+(?:[,，\s]*\d+)*)\]')
            cited_nums = set()
            for m in cite_pattern.finditer(draft_text):
                for num in re.split(r'[,，\s]+', m.group(1)):
                    if num.strip().isdigit():
                        cited_nums.add(int(num.strip()))

            for i, item in enumerate(zotero_lib._items):
                if (i + 1) in cited_nums:
                    authors = ", ".join(item.authors[:2]) if item.authors else "?"
                    year = item.year or "?"
                    title = item.title or "?"
                    cited_parts.append(f"[{i+1}] {authors} ({year}) - {title[:120]}")

        cited_text = "\n".join(cited_parts) if cited_parts else "（未检测到引用或 Zotero 未连接）"

        prompt = self.MISSING_LIT_PROMPT.format(
            draft_text=draft_text[:8000],
            cited_papers=cited_text[:3000],
        )
        messages = [
            {"role": "system", "content": "你是学术文献检索专家。只返回 JSON，不要加解释。"},
            {"role": "user", "content": prompt},
        ]
        try:
            response = write_client.chat_sync(messages, timeout=120.0, max_tokens=3000)
            # 解析
            import json as _json
            import re
            text = response.strip()
            for pattern in [r'```json\s*(.*?)```', r'```\s*(.*?)```']:
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    text = m.group(1).strip()
                    break
            first = text.find('{')
            last = text.rfind('}')
            if first >= 0 and last > first:
                return _json.loads(text[first:last + 1])
            return _json.loads(text)
        except Exception:
            return None

    def search_semantic_scholar(self, queries: list[str], limit: int = 10) -> list[dict]:
        """Step 2 of 遗漏文献检测：用搜索关键词调用 S2 API。

        返回论文列表 [{title, authors, year, citationCount, doi, url}, ...]。
        """
        import urllib.request
        import urllib.parse
        import json as _json

        all_papers = []
        seen_titles = set()

        for query in queries[:8]:  # 最多 8 个查询
            try:
                params = urllib.parse.urlencode({"query": query, "limit": limit})
                url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}&fields=title,authors,year,citationCount,externalIds,url"
                req = urllib.request.Request(url, headers={"User-Agent": "PDFasker/2.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = _json.loads(resp.read().decode())
                    for paper in data.get("data", []):
                        title = paper.get("title", "")
                        if title.lower() in seen_titles:
                            continue
                        seen_titles.add(title.lower())
                        authors_list = paper.get("authors", [])
                        author_names = ", ".join(
                            a.get("name", "") for a in authors_list[:3]
                        )
                        doi = ""
                        ext_ids = paper.get("externalIds", {}) or {}
                        doi = ext_ids.get("DOI", "")
                        all_papers.append({
                            "title": title,
                            "authors": author_names,
                            "year": paper.get("year", ""),
                            "citationCount": paper.get("citationCount", 0),
                            "doi": doi,
                            "url": paper.get("url", ""),
                            "source": f"S2搜索: {query[:40]}",
                        })
            except Exception:
                continue

        # 按引用数降序
        all_papers.sort(key=lambda p: p.get("citationCount", 0), reverse=True)
        return all_papers

    def search_s2_recommendations(
        self, positive_dois: list[str], limit: int = 20,
    ) -> list[dict]:
        """Step 2b of 遗漏文献检测：用 S2 推荐 API 基于已知文献推荐。

        positive_dois: 已引用文献的 DOI 列表。
        """
        import urllib.request
        import json as _json

        # 先用 DOI 获取 paperId
        paper_ids = []
        for doi in positive_dois[:20]:
            try:
                url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=paperId"
                req = urllib.request.Request(url, headers={"User-Agent": "PDFasker/2.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = _json.loads(resp.read().decode())
                    pid = data.get("paperId", "")
                    if pid:
                        paper_ids.append(pid)
            except Exception:
                continue

        if not paper_ids:
            return []

        # 调用推荐 API
        try:
            body = _json.dumps({
                "positivePaperIds": paper_ids[:20],
                "limit": limit,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.semanticscholar.org/recommendations/v1/papers",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "PDFasker/2.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = _json.loads(resp.read().decode())
                papers = []
                seen = set()
                for paper in data.get("recommendedPapers", [])[:limit]:
                    title = paper.get("title", "")
                    if title.lower() in seen:
                        continue
                    seen.add(title.lower())
                    authors = ", ".join(
                        a.get("name", "") for a in (paper.get("authors") or [])[:3]
                    )
                    ext_ids = paper.get("externalIds", {}) or {}
                    papers.append({
                        "title": title,
                        "authors": authors,
                        "year": paper.get("year", ""),
                        "citationCount": paper.get("citationCount", 0),
                        "doi": ext_ids.get("DOI", ""),
                        "url": paper.get("url", ""),
                        "source": "S2推荐",
                    })
                papers.sort(key=lambda p: p.get("citationCount", 0), reverse=True)
                return papers
        except Exception:
            return []
