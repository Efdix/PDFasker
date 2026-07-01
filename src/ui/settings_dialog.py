"""API 配置对话框 —— 两套 API 独立配置：文献阅读 + 综述写作 + 处理设置"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QFormLayout, QGroupBox, QMessageBox,
    QTabWidget, QWidget, QSpinBox, QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Qt

from ..core.llm_client import PROVIDERS
from ..utils.config import load_config, save_config


class APIConfigTab(QWidget):
    """单个 API 配置标签页。"""

    def __init__(self, tab_name: str, description: str, parent=None):
        super().__init__(parent)
        self._tab_name = tab_name
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        desc = QLabel(description)
        desc.setObjectName("subtitleLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        provider_group = QGroupBox("提供商")
        pg = QVBoxLayout(provider_group)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(list(PROVIDERS.keys()))
        self.provider_combo.currentTextChanged.connect(self._on_provider)
        pg.addWidget(self.provider_combo)
        self.provider_desc = QLabel()
        self.provider_desc.setObjectName("subtitleLabel")
        self.provider_desc.setWordWrap(True)
        pg.addWidget(self.provider_desc)
        layout.addWidget(provider_group)

        cfg = QGroupBox("连接参数")
        form = QFormLayout(cfg)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-...")
        form.addRow("API Key:", self.api_key)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://api.deepseek.com")
        form.addRow("Base URL:", self.base_url)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setPlaceholderText("选择或输入模型名")
        form.addRow("模型:", self.model)
        layout.addWidget(cfg)

        layout.addStretch()

    def _on_provider(self, name: str):
        info = PROVIDERS.get(name, {})
        self.provider_desc.setText(info.get("description", ""))
        self.base_url.setText(info.get("base_url", ""))
        self._populate_models()

    def load(self, api_cfg: dict):
        p = api_cfg.get("provider", "DeepSeek")
        idx = self.provider_combo.findText(p)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        else:
            self.provider_combo.setCurrentIndex(0)
        self.api_key.setText(api_cfg.get("api_key", ""))
        saved_url = api_cfg.get("base_url", "")
        if saved_url:
            self.base_url.setText(saved_url)
        self._populate_models()
        m = api_cfg.get("model", "")
        if m:
            idx = self.model.findText(m)
            if idx >= 0:
                self.model.setCurrentIndex(idx)
            else:
                self.model.setCurrentText(m)

    def _populate_models(self):
        name = self.provider_combo.currentText()
        info = PROVIDERS.get(name, {})
        self.provider_desc.setText(info.get("description", ""))
        models = info.get("models", [])
        self.model.clear()
        if models:
            self.model.addItems(models)
            self.model.setCurrentIndex(0)
        else:
            self.model.setCurrentText("")

    def get(self) -> dict:
        return {
            "provider": self.provider_combo.currentText(),
            "api_key": self.api_key.text().strip(),
            "base_url": self.base_url.text().strip(),
            "model": self.model.currentText().strip(),
        }


class ProcessingSettingsTab(QWidget):
    """Stage 1 处理设置标签页 —— 同步/异步模式 + 并发数。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        desc = QLabel(
            "控制 PDF 导入后逐页 AI 解析（Stage 1）的处理方式。\n"
            "跨页整合（Stage 2）不受此设置影响。"
        )
        desc.setObjectName("subtitleLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ---- 处理模式 ----
        mode_group = QGroupBox("处理模式")
        mode_layout = QVBoxLayout(mode_group)

        self._mode_group = QButtonGroup(self)
        self._sync_radio = QRadioButton("🔤 同步（逐页顺序）")
        self._sync_radio.setToolTip(
            "一页一页顺序处理。\n"
            "✅ 优点：稳定、不触发 API 限流、进度反馈精确\n"
            "❌ 缺点：速度较慢，总耗时 = 单页耗时 × 页数"
        )
        self._async_radio = QRadioButton("⚡ 异步（并发处理）")
        self._async_radio.setToolTip(
            "多页同时发送 API 请求。\n"
            "✅ 优点：速度更快（约 3-5 倍）\n"
            "❌ 缺点：可能触发 API 限流、部分接口不支持高并发"
        )
        self._mode_group.addButton(self._sync_radio, 0)
        self._mode_group.addButton(self._async_radio, 1)
        mode_layout.addWidget(self._sync_radio)
        mode_layout.addWidget(self._async_radio)
        layout.addWidget(mode_group)

        # ---- 并发数 ----
        concurrency_group = QGroupBox("并发设置（仅异步模式）")
        concurrency_layout = QFormLayout(concurrency_group)

        self._concurrency_spin = QSpinBox()
        self._concurrency_spin.setRange(1, 10)
        self._concurrency_spin.setValue(3)
        self._concurrency_spin.setToolTip(
            "同时发送 API 请求的页数。\n"
            "推荐 2-4：平衡速度与稳定性\n"
            "设为 1 的效果等同于同步模式"
        )
        self._concurrency_spin.setSuffix(" 页同时")
        concurrency_layout.addRow("并发页数：", self._concurrency_spin)

        # 当切换到同步模式时禁用并发设置
        self._sync_radio.toggled.connect(
            lambda checked: self._concurrency_spin.setEnabled(not checked)
        )
        layout.addWidget(concurrency_group)

        layout.addStretch()

    def load(self, config: dict):
        mode = config.get("stage1_mode", "async")
        if mode == "sync":
            self._sync_radio.setChecked(True)
        else:
            self._async_radio.setChecked(True)

        concurrency = config.get("stage1_concurrency", 3)
        self._concurrency_spin.setValue(max(1, min(10, concurrency)))

    def get(self) -> dict:
        return {
            "stage1_mode": "sync" if self._sync_radio.isChecked() else "async",
            "stage1_concurrency": self._concurrency_spin.value(),
        }


class SettingsDialog(QDialog):
    """API 配置对话框（两标签页：文献阅读 + 综述写作）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 配置")
        self.setMinimumSize(680, 600)
        self.setModal(True)
        self._config = load_config()
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("API 配置")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self._reading_tab = APIConfigTab(
            "reading",
            "📖 文献阅读 API — 用于 PDF 结构识别、段落翻译、图片解读、论文问答。\n建议使用支持视觉的多模态模型以获得最佳 PDF 结构识别效果。"
        )
        self._review_tab = APIConfigTab(
            "review",
            "📝 综述写作 API — 用于引文核查、综述内容优化。建议使用强推理模型。"
        )
        self._processing_tab = ProcessingSettingsTab()
        self.tabs.addTab(self._reading_tab, "📖 文献阅读")
        self.tabs.addTab(self._review_tab, "📝 综述写作")
        self.tabs.addTab(self._processing_tab, "⚙️ 处理设置")
        layout.addWidget(self.tabs)

        btn = QHBoxLayout()
        btn.addStretch()
        test = QPushButton("测试当前标签页连接")
        test.clicked.connect(self._test)
        btn.addWidget(test)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btn.addWidget(cancel)
        save = QPushButton("保存全部")
        save.setObjectName("primaryBtn")
        save.clicked.connect(self._save)
        btn.addWidget(save)
        layout.addLayout(btn)

    def _load(self):
        self._reading_tab.load(self._config.get("reading_api", {}))
        self._review_tab.load(self._config.get("review_api", {}))
        self._processing_tab.load(self._config)

    def _save(self):
        self._config["reading_api"] = self._reading_tab.get()
        self._config["review_api"] = self._review_tab.get()
        self._config.update(self._processing_tab.get())
        save_config(self._config)
        mode = self._config.get("stage1_mode", "async")
        conc = self._config.get("stage1_concurrency", 3)
        QMessageBox.information(
            self, "已保存",
            f"API 配置已保存。\n处理模式：{'同步（逐页顺序）' if mode == 'sync' else f'异步（{conc}页并发）'}"
        )
        self.accept()

    def _test(self):
        current = self.tabs.currentWidget()
        if not isinstance(current, APIConfigTab):
            return
        cfg = current.get()
        if not cfg.get("api_key"):
            QMessageBox.warning(self, "缺少 API Key", "请先填写 API Key。")
            return
        if not cfg.get("base_url"):
            QMessageBox.warning(self, "缺少 Base URL", "请先填写 Base URL。")
            return
        try:
            from ..core.llm_client import LLMClient
            client = LLMClient(cfg["api_key"], cfg["base_url"], cfg["model"])
            reply = client.chat_sync([{"role": "user", "content": "请回复：连接测试成功"}], timeout=15, max_tokens=50)
            QMessageBox.information(self, "测试成功", f"API 连接正常！\n回复：{reply[:200]}")
        except Exception as e:
            QMessageBox.critical(self, "测试失败", f"连接失败：{e}")
