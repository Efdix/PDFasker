"""
API 配置对话框
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QFormLayout, QGroupBox, QMessageBox,
)
from PySide6.QtCore import Qt

from ..core.llm_client import PROVIDERS
from ..utils.config import load_config, save_config


class SettingsDialog(QDialog):
    """API 配置设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 配置")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._config = load_config()
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # 标题
        title = QLabel("⚙️  大模型 API 配置")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # 提供商选择
        provider_group = QGroupBox("API 提供商")
        provider_layout = QVBoxLayout(provider_group)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(list(PROVIDERS.keys()))
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        provider_layout.addWidget(self.provider_combo)

        self.provider_desc = QLabel()
        self.provider_desc.setObjectName("subtitleLabel")
        self.provider_desc.setWordWrap(True)
        provider_layout.addWidget(self.provider_desc)
        layout.addWidget(provider_group)

        # 详细配置
        config_group = QGroupBox("连接参数")
        form = QFormLayout(config_group)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("输入你的 API Key...")
        form.addRow("API Key:", self.api_key_input)

        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("https://api.deepseek.com")
        form.addRow("Base URL:", self.base_url_input)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setPlaceholderText("选择或输入模型名称...")
        form.addRow("模型:", self.model_combo)

        layout.addWidget(config_group)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self._test_connection)
        btn_layout.addWidget(test_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save_and_accept)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _load_values(self):
        """加载已保存的配置"""
        provider = self._config.get("provider", "DeepSeek")
        idx = self.provider_combo.findText(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        else:
            self.provider_combo.setCurrentIndex(0)

        self.api_key_input.setText(self._config.get("api_key", ""))
        self.base_url_input.setText(self._config.get("base_url", ""))
        model = self._config.get("model", "")
        if model:
            idx = self.model_combo.findText(model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentText(model)

    def _on_provider_changed(self, name: str):
        """切换提供商时更新预设"""
        info = PROVIDERS.get(name, {})
        self.provider_desc.setText(info.get("description", ""))
        self.base_url_input.setText(info.get("base_url", ""))

        self.model_combo.clear()
        models = info.get("models", [])
        if models:
            self.model_combo.addItems(models)
            self.model_combo.setCurrentIndex(0)

    def _get_current_config(self) -> dict:
        return {
            "provider": self.provider_combo.currentText(),
            "api_key": self.api_key_input.text().strip(),
            "base_url": self.base_url_input.text().strip(),
            "model": self.model_combo.currentText().strip(),
            "max_tokens": self._config.get("max_tokens", 120_000),
        }

    def _test_connection(self):
        """测试 API 连接"""
        config = self._get_current_config()
        if not config["api_key"]:
            QMessageBox.warning(self, "提示", "请先输入 API Key")
            return
        if not config["base_url"]:
            QMessageBox.warning(self, "提示", "请先输入 Base URL")
            return

        try:
            from ..core.llm_client import LLMClient
            client = LLMClient(
                api_key=config["api_key"],
                base_url=config["base_url"],
                model=config["model"] or "default",
            )
            reply = client.chat_sync([
                {"role": "user", "content": "你好，请回复'连接成功'即可。"}
            ])
            QMessageBox.information(self, "成功", f"连接成功！\n回复：{reply[:100]}")
        except Exception as e:
            QMessageBox.critical(self, "连接失败", f"无法连接：\n{str(e)}")

    def _save_and_accept(self):
        """保存并关闭"""
        config = self._get_current_config()
        if not config["api_key"]:
            QMessageBox.warning(self, "提示", "请输入 API Key")
            return
        if not config["base_url"]:
            QMessageBox.warning(self, "提示", "请输入 Base URL")
            return

        save_config(config)
        self.accept()

    def get_config(self) -> dict:
        return self._get_current_config()
