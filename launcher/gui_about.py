"""
GUI关于页面模块

功能：
1. 作为左侧导航的"关于"菜单对应内容页
2. 显示系统版本信息（仅本机信息，不加载任何远程内容）
"""
import tkinter as tk

from launcher.gui_theme import COLORS
from launcher.version import CURRENT_VERSION


def render_about_page(app):
    """
    在右侧内容区渲染"关于"页面

    Args:
        app: LauncherApp实例
    """
    content = app._content_frame

    inner = tk.Frame(content, bg=COLORS["card_bg"])
    inner.pack(fill=tk.BOTH, expand=True)

    # 标题
    tk.Label(inner, text="关于", font=("微软雅黑", 14, "bold"),
             fg=COLORS["text"], bg=COLORS["card_bg"]).pack(
        anchor=tk.W, padx=20, pady=(16, 4))

    # 系统名称和版本
    tk.Label(inner, text="闲鱼管理系统",
             font=("微软雅黑", 12),
             fg=COLORS["text"], bg=COLORS["card_bg"]).pack(
        anchor=tk.W, padx=20)
    tk.Label(inner, text=f"当前版本: v{CURRENT_VERSION}",
             font=("微软雅黑", 10),
             fg=COLORS["text_secondary"], bg=COLORS["card_bg"]).pack(
        anchor=tk.W, padx=20, pady=(0, 8))
