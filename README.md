# PDFasker — AI 论文解读助手

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.11-green.svg)](https://pypi.org/project/PySide6/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

基于大语言模型的 **Windows 桌面应用**，将科研论文 PDF 智能分段为可交互的段落卡片，支持中英对照翻译、图片 AI 解读、综述写作辅助。

---

## ✨ 功能

### 论文阅读

| 功能 | 说明 |
|------|------|
| 📄 **列感知分段** | 自动检测双栏/多栏布局，按阅读顺序将论文拆分为段落卡片 |
| 🏷️ **标题 & 元信息识别** | 自动识别章节标题（高亮）和作者/DOI/版权等元信息（淡化） |
| 🌐 **中英对照翻译** | 英文段落一键翻译为中文，逐段对照阅读 |
| 📝 **AI 排版** | 修复 PDF 提取造成的断行、断词，还原连贯段落 |
| 🔗 **段落合并** | 勾选多张卡片，AI 自动合并断裂的跨页段落 |
| 🖼️ **图片提取 & 解读** | 自动提取论文插图，AI 分析图表内容并支持追问 |
| 🔍 **全文搜索** | `Ctrl+F` 搜索论文内容，高亮定位匹配段落 |

### 综述写作

| 功能 | 说明 |
|------|------|
| 📝 **综述编辑器** | 编写文献综述，AI 辅助核查引用准确性 |
| 📚 **Zotero 集成** | 读取 Zotero 文献库，自动匹配引文与原文 |
| ✅ **引文核查** | 逐条检查综述中的引文是否准确反映原文观点，给出改写建议 |

### 通用

| 功能 | 说明 |
|------|------|
| 🤖 **多模型支持** | DeepSeek V4、Mimo 及所有 OpenAI 兼容接口，五套 API 独立配置 |
| 💬 **流式对话** | AI 回复实时逐字显示，上下文自动管理（1M token 窗口） |
| 📚 **论文库** | 拖拽导入 PDF，文件夹分类管理，对话和排版状态按文档持久化 |
| 🎨 **暗色主题** | Catppuccin 风格，护眼舒适 |

---

## 🔧 环境搭建

### 前置要求

- Windows 10/11
- Miniconda / Anaconda
- Git

### 安装

```bash
git clone <repo-url> PDFasker
cd PDFasker
conda create -n PDFasker python=3.11 -y
conda activate PDFasker
pip install -r requirements.txt
```

### 获取 API Key

**DeepSeek V4（推荐）**：访问 [platform.deepseek.com](https://platform.deepseek.com/)，获取 Key。模型选 `deepseek-v4-flash`（快）或 `deepseek-v4-pro`（强），Base URL 为 `https://api.deepseek.com`。

### 启动

```bash
conda activate PDFasker
python main.py
```

首次启动后在 **设置 → API 配置** 中填入 API Key 即可使用。

---

## 📖 使用指南

### 论文阅读

1. 左侧 **论文库** 拖拽或导入 PDF
2. 点击论文，自动分段为段落卡片
3. 阅读卡片，点击 **翻译** 查看中文对照
4. 图片卡片点击 **AI 解读** 分析图表
5. 右侧聊天面板输入问题，`Ctrl+Enter` 发送

### 段落操作

- **勾选多张卡片** → 工具栏出现「合并选中」「删除选中」
- **右键菜单** → 全选 / 复制 / 拆分段落
- **自动翻译 / 排版** → 工具栏开关，开启后滚动即自动处理

### 综述写作

1. 切换到「📝 综述写作」标签页
2. 设置 Zotero 数据目录路径
3. 编写综述 → 点击「核查引文」
4. AI 逐条对比原文，标记「引用恰当 / 建议补充 / 需核实」

---

## 📁 数据存储

所有数据存储在图书馆目录下的 `.pdfasker/` 文件夹：

```
你的图书馆目录/
├── .pdfasker/
│   ├── config.json       # API 配置
│   ├── library.json      # PDF 论文列表
│   ├── chats/            # 对话历史（按文档 MD5 隔离）
│   ├── states/           # 排版/翻译状态持久化
│   └── image_cache/      # PDF 图片提取缓存
└── *.pdf                 # 导入的论文文件
```

---

## 🏗️ 项目结构

```
PDFasker/
├── main.py
├── requirements.txt
├── README.md
├── assets/
└── src/
    ├── app.py                    # 主窗口
    ├── core/
    │   ├── pdf_parser.py         # PDF 解析器 v2（列感知智能分段）
    │   ├── llm_client.py         # LLM API 客户端
    │   ├── context_manager.py    # 上下文/Token 管理
    │   ├── zotero_parser.py      # Zotero 文献库解析
    │   └── review_checker.py     # 综述引文核查引擎
    ├── ui/
    │   ├── pdf_viewer.py         # 论文阅读面板（段落卡片/图片/翻译）
    │   ├── pdf_list_panel.py     # 论文库侧边栏
    │   ├── chat_panel.py         # 聊天面板
    │   ├── review_panel.py       # 综述写作面板
    │   ├── settings_dialog.py    # API 设置对话框
    │   └── styles.py             # QSS 全局样式
    └── utils/
        └── config.py             # 配置/状态持久化
```

---

## ❓ 常见问题

**支持哪些模型？** 所有 OpenAI 兼容接口：DeepSeek V4、Mimo、通义千问、智谱 GLM、Moonshot 等。五套 API（聊天/翻译/图析/综述/排版）可独立配置不同模型。

**支持多长的论文？** DeepSeek V4 支持 1M token 上下文，几百页论文可一次性处理。

**段落分得太碎/合得太粗？** 可在段落卡片右键「拆分」或勾选多张「合并选中」让 AI 重新整理。

---

## 📄 许可证

MIT License
