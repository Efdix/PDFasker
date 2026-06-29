# PDFasker — AI 论文解读助手

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.11-green.svg)](https://pypi.org/project/PySide6/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一款基于大语言模型的 **Windows 桌面应用**，帮助你快速阅读和理解科研论文 PDF。

> 左侧浏览论文原文，右侧向 AI 提问，获取即时解答。

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📄 **PDF 解析** | 基于 PyMuPDF，快速提取论文全文，保留页码 |
| 🤖 **多模型支持** | 内置 DeepSeek、MiniMax 预设，支持所有 OpenAI 兼容接口 |
| 💬 **侧边栏聊天** | 左侧读论文、右侧聊天的沉浸式布局 |
| 🔄 **流式输出** | AI 回复实时逐字显示，无需等待 |
| 📚 **上下文管理** | 自动管理长文本，智能截断适配模型窗口 |
| 🎨 **现代暗色主题** | Catppuccin 风格暗色界面，护眼舒适 |
| 💾 **配置持久化** | API Key 等配置加密存储于本地 |

---

## 📸 界面预览

```
┌──────────────────────────────────────────────────────┐
│  菜单栏: 文件 | 设置 | 帮助                           │
├────────────────────┬─────────────────────────────────┤
│  📄 PDF 阅读器      │  💬 对话                  [清空] │
│  [打开 PDF]         │─────────────────────────────────│
│                    │                                 │
│  ┌──────────────┐  │  👤 你                          │
│  │              │  │  这篇论文的主要贡献是什么？        │
│  │  论文原文     │  │                                 │
│  │  (可滚动)    │  │  🤖 AI                          │
│  │              │  │  这篇论文的主要贡献包括...         │
│  │              │  │                                 │
│  │              │  │  ─────────────────────           │
│  └──────────────┘  │                                 │
│                    │  ┌─────────────────────────┐     │
│  共 12 页          │  │ 输入问题...    [发送 ✈]  │     │
│                    │  └─────────────────────────┘     │
├────────────────────┴─────────────────────────────────┤
│  状态栏: 模型: deepseek-chat | API: DeepSeek          │
└──────────────────────────────────────────────────────┘
```

---

## 🔧 环境搭建（重要！）

### 前置要求

- **Windows 10/11**
- **Miniconda / Anaconda**（用于创建隔离环境）
- **Git**（用于克隆项目）

### 第一步：克隆项目

```bash
git clone <your-repo-url> PDFasker
cd PDFasker
```

### 第二步：创建 Conda 环境

> ⚠️ **务必创建独立环境，不要装在 base 环境！**

```bash
# 创建名为 PDFasker 的独立 conda 环境（Python 3.11）
conda create -n PDFasker python=3.11 -y

# 激活环境
conda activate PDFasker
```

### 第三步：安装依赖

```bash
# 在 PDFasker 环境中安装所有依赖包
pip install -r requirements.txt
```

**依赖包清单**（`requirements.txt`）：

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| `PySide6` | ≥ 6.5 | Qt 桌面 GUI 框架 |
| `openai` | ≥ 1.0 | OpenAI 兼容 API 客户端 |
| `PyMuPDF` | ≥ 1.23 | PDF 文本提取 |
| `python-dotenv` | ≥ 1.0 | 环境变量管理 |

### 第四步：获取 API Key

#### DeepSeek（推荐）
1. 访问 [platform.deepseek.com](https://platform.deepseek.com/)
2. 注册并获取 API Key
3. 费用：约 ¥1/百万 tokens

#### MiniMax
1. 访问 [platform.minimaxi.com](https://platform.minimaxi.com/)
2. 注册并获取 API Key

### 第五步：启动应用

```bash
# 确保在 PDFasker 环境中
conda activate PDFasker
python main.py
```

---

## 📖 使用指南

### 1. 配置 API

首次启动后：
- 点击菜单栏 **设置 → API 配置**（或按 `Ctrl+,`）
- 选择提供商（DeepSeek / MiniMax / 自定义）
- 填入 API Key、Base URL、模型名称
- 点击 **测试连接** 验证
- 点击 **保存**

### 2. 加载论文

- 点击 **打开 PDF** 按钮（或按 `Ctrl+O`）
- 选择你的 PDF 论文文件
- 左侧将显示提取的文本内容

### 3. 开始提问

- 在右侧输入框输入问题
- 按 `Ctrl+Enter` 或点击 **发送** 按钮
- AI 将基于论文原文回答

### 推荐提问方式

| 类型 | 示例问题 |
|------|----------|
| 论文概览 | "请用中文总结这篇论文的核心贡献" |
| 方法理解 | "请详细解释第三章的方法论" |
| 结果分析 | "实验结果表明了什么？有哪些局限性？" |
| 术语解释 | "什么是 [术语]？在这篇论文中是如何使用的？" |
| 对比分析 | "这篇论文和之前的工作有什么不同？" |

---

## 🏗️ 项目结构

```
PDFasker/
├── main.py                  # 应用入口
├── requirements.txt         # Python 依赖清单
├── .gitignore               # Git 忽略规则
├── README.md                # 本文档
├── assets/                  # 静态资源（图标等）
└── src/
    ├── __init__.py
    ├── app.py               # 主窗口（整合所有 UI）
    ├── core/
    │   ├── __init__.py
    │   ├── llm_client.py    # LLM API 客户端
    │   ├── pdf_parser.py    # PDF 文本解析器
    │   └── context_manager.py # 上下文/Token 管理
    ├── ui/
    │   ├── __init__.py
    │   ├── chat_panel.py    # 聊天面板
    │   ├── pdf_viewer.py    # PDF 查看面板
    │   ├── settings_dialog.py # API 设置对话框
    │   └── styles.py        # QSS 全局样式
    └── utils/
        ├── __init__.py
        └── config.py        # 配置持久化
```

---

## ❓ 常见问题

### Q: 支持哪些大模型？
**A:** 所有 OpenAI 兼容接口的模型，包括但不限于：
- **DeepSeek** (deepseek-chat, deepseek-reasoner)
- **MiniMax** (MiniMax-Text-01, abab6.5s-chat)
- **通义千问** (qwen-turbo, qwen-plus)
- **智谱 GLM** (glm-4, glm-4-flash)
- **Moonshot/Kimi** (moonshot-v1)
- 任何兼容 `/v1/chat/completions` 的 API

### Q: API Key 安全吗？
**A:** API Key 存储在 `%USERPROFILE%\.pdfasker\config.json`，不上传到任何服务器。建议不要在公共电脑上使用。

### Q: 支持多长的论文？
**A:** 目前上下文窗口设为 120K tokens（适配 DeepSeek）。大多数 30 页以内的论文可完整处理。更长的论文会自动截断保留首尾。

### Q: 如何切换到另一台电脑使用？
**A:** 
```bash
# 在新电脑上
git clone <repo-url>
cd PDFasker
conda create -n PDFasker python=3.11 -y
conda activate PDFasker
pip install -r requirements.txt
python main.py
# 重新输入你的 API Key
```

---

## 🔨 打包为独立 .exe（可选）

如果希望在没有 Python 环境的电脑上运行：

```bash
conda activate PDFasker
pip install pyinstaller
pyinstaller --onefile --windowed --name PDFasker main.py
```

生成的 `dist/PDFasker.exe` 可独立运行。

---

## 📄 许可证

MIT License

---

## 🙏 致谢

- [PySide6](https://wiki.qt.io/Qt_for_Python) - Qt for Python
- [PyMuPDF](https://pymupdf.readthedocs.io/) - PDF 解析库
- [OpenAI Python SDK](https://github.com/openai/openai-python) - API 客户端
- [Catppuccin](https://github.com/catppuccin/catppuccin) - 配色灵感
