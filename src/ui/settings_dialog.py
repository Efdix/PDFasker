"""
API 配置对话框 —— 聊天 / 翻译 / 图片解析 三套 API 独立配置
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QFormLayout, QGroupBox, QMessageBox,
    QTabWidget, QWidget,
)
from PySide6.QtCore import Qt

from ..core.llm_client import PROVIDERS
from ..utils.config import load_config, save_config, get_api_config


class APIConfigTab(QWidget):
    """单个 API 配置标签页"""

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
        self.model.setPlaceholderText("deepseek-v4-flash")
        form.addRow("模型:", self.model)
        layout.addWidget(cfg)

        layout.addStretch()

    def _on_provider(self, name: str):
        info = PROVIDERS.get(name, {})
        self.provider_desc.setText(info.get("description", ""))
        self.base_url.setText(info.get("base_url", ""))
        self.model.clear()
        for m in info.get("models", []):
            self.model.addItem(m)
        if self.model.count() > 0:
            self.model.setCurrentIndex(0)

    def load(self, api_cfg: dict):
        p = api_cfg.get("provider", "DeepSeek")
        idx = self.provider_combo.findText(p)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.api_key.setText(api_cfg.get("api_key", ""))
        self.base_url.setText(api_cfg.get("base_url", ""))
        m = api_cfg.get("model", "")
        if m:
            idx = self.model.findText(m)
            if idx >= 0:
                self.model.setCurrentIndex(idx)
            else:
                self.model.setCurrentText(m)

    def get(self) -> dict:
        return {
            "provider": self.provider_combo.currentText(),
            "api_key": self.api_key.text().strip(),
            "base_url": self.base_url.text().strip(),
            "model": self.model.currentText().strip(),
        }


class SettingsDialog(QDialog):
    """三标签页 API 配置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 配置")
        self.setMinimumSize(520, 500)
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
        self._trans_tab = APIConfigTab("trans", "🌐 翻译 API — 英文段落翻译，可用便宜模型")
        self._image_tab = APIConfigTab("image", "🖼️ 图析 API — 解读图表（需多模态模型，如 GPT-4o / Gemini）")
        self._chat_tab = APIConfigTab("chat", "💬 聊天 API — 基于论文内容的问答对话，建议用最强模型")
        self.tabs.addTab(self._trans_tab, "🌐 翻译")
        self.tabs.addTab(self._image_tab, "🖼️ 图析")
        self.tabs.addTab(self._chat_tab, "💬 聊天")
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

    def _current_tab(self) -> APIConfigTab:
        idx = self.tabs.currentIndex()
        return [self._chat_tab, self._trans_tab, self._image_tab][idx]

    def _load(self):
        self._chat_tab.load(get_api_config(self._config, "chat_api"))
        self._trans_tab.load(get_api_config(self._config, "translation_api"))
        self._image_tab.load(get_api_config(self._config, "image_api"))

    def _test(self):
        tab = self._current_tab()
        cfg = tab.get()
        if not cfg["api_key"] or not cfg["base_url"]:
            QMessageBox.warning(self, "提示", "请填写 API Key 和 Base URL")
            return
        try:
            from ..core.llm_client import LLMClient
            c = LLMClient(cfg["api_key"], cfg["base_url"], cfg["model"] or "default")
            r = c.chat_sync([{"role": "user", "content": "回复'OK'即可"}])
            QMessageBox.information(self, "成功", f"连接成功！\n回复：{r[:100]}")
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))

    def _save(self):
        ck_api = self._chat_tab.get()
        tr_api = self._trans_tab.get()
        im_api = self._image_tab.get()
        for api, name in [(ck_api, "聊天"), (tr_api, "翻译"), (im_api, "图析")]:
            if not api["api_key"]:
                QMessageBox.warning(self, "提示", f"请填写{name} API 的 Key")
                return

        self._config["chat_api"] = ck_api
        self._config["translation_api"] = tr_api
        self._config["image_api"] = im_api
        save_config(self._config)
        self.accept()
