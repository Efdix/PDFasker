"""
共享布局辅助工具 —— 递归计算布局高度，供各 UI 面板的 heightForWidth 使用。
"""

from PySide6.QtWidgets import QHBoxLayout, QLayout


def calc_layout_height(layout: QLayout, inner_width: int) -> int:
    """递归计算布局在给定宽度下所需的高度。

    对 QVBoxLayout 累加子元素高度；对 QHBoxLayout 取最大子元素高度。
    自动处理嵌套的 widget-with-layout 情况。
    """
    if layout is None:
        return 0

    is_horizontal = isinstance(layout, QHBoxLayout)
    spacing = layout.spacing()
    total = 0
    max_h = 0
    count = layout.count()

    for i in range(count):
        item = layout.itemAt(i)
        if item is None:
            continue

        child_h = 0
        if widget := item.widget():
            if not widget.isVisible():
                continue
            if widget.hasHeightForWidth():
                child_h = widget.heightForWidth(inner_width)
            elif widget.layout():
                w_marg = widget.contentsMargins()
                w_inner = max(inner_width - w_marg.left() - w_marg.right(), 50)
                child_h = w_marg.top() + w_marg.bottom() + calc_layout_height(widget.layout(), w_inner)
            else:
                child_h = widget.sizeHint().height()
        elif sub := item.layout():
            sub_marg = sub.contentsMargins()
            sub_inner = max(inner_width - sub_marg.left() - sub_marg.right(), 50)
            child_h = sub_marg.top() + sub_marg.bottom() + calc_layout_height(sub, sub_inner)
        elif item.spacerItem():
            continue

        if is_horizontal:
            max_h = max(max_h, child_h)
        else:
            if child_h > 0:
                total += child_h
                if i < count - 1:
                    total += spacing

    return max_h if is_horizontal else total
