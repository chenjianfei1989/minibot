"""交互式界面辅助工具，包括 Vim 编辑器和方向键选择器。"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any, Callable, Sequence


def edit_in_vim(initial_content: str) -> str | None:
    """用 ``$EDITOR``（默认 ``vim``）打开 *initial_content*。

    返回编辑后的文本。用户未保存即退出时返回 ``None``，通过检查文件是否被修改来判断。
    """
    editor = os.environ.get("EDITOR", "vim")
    with tempfile.NamedTemporaryFile(
        suffix=".md", mode="w", delete=False, encoding="utf-8",
    ) as tmp:
        tmp.write(initial_content)
        tmp_path = tmp.name

    original_mtime = os.path.getmtime(tmp_path)
    try:
        subprocess.run([editor, tmp_path], check=True)
        if os.path.getmtime(tmp_path) == original_mtime:
            return None
        with open(tmp_path, encoding="utf-8") as f:
            return f.read()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def interactive_select(
    items: Sequence[Any],
    *,
    render_fn: Callable[[Any, int, int], str],
    on_toggle: Callable[[Any], Any],
) -> None:
    """使用 prompt_toolkit 实现的方向键交互选择器。

    *render_fn(item, index, cursor)* 返回每项的显示文本。
    按下回车时调用 *on_toggle(item)*，该回调可以是异步函数。
    按 ``q`` 或 ``Esc`` 退出。
    """
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    if not items:
        return

    cursor = [0]

    def _get_text() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for idx, item in enumerate(items):
            line = render_fn(item, idx, cursor[0])
            style = "bold" if idx == cursor[0] else ""
            fragments.append((style, line + "\n"))
        fragments.append(("class:hint", "\n↑↓ navigate  Enter toggle  q/Esc exit"))
        return fragments

    control = FormattedTextControl(_get_text)
    kb = KeyBindings()

    @kb.add("up")
    def _up(event: Any) -> None:
        cursor[0] = max(0, cursor[0] - 1)

    @kb.add("down")
    def _down(event: Any) -> None:
        cursor[0] = min(len(items) - 1, cursor[0] + 1)

    @kb.add("enter")
    async def _enter(event: Any) -> None:
        result = on_toggle(items[cursor[0]])
        if hasattr(result, "__await__"):
            await result
        # 通过使当前显示失效来自动触发刷新。

    @kb.add("q")
    @kb.add("escape")
    def _quit(event: Any) -> None:
        event.app.exit()

    app: Application[None] = Application(
        layout=Layout(Window(control)),
        key_bindings=kb,
        full_screen=False,
    )
    await app.run_async()


async def interactive_choice(
    items: Sequence[Any],
    *,
    render_fn: Callable[[Any, int, int], str],
) -> Any | None:
    """使用方向键选择项目，按回车返回所选项。

    *render_fn(item, index, cursor)* 返回每项的显示文本。
    按 ``q`` 或 ``Esc`` 退出并返回 ``None``。
    """
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    if not items:
        return None

    cursor = [0]

    def _get_text() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for idx, item in enumerate(items):
            line = render_fn(item, idx, cursor[0])
            style = "bold" if idx == cursor[0] else ""
            fragments.append((style, line + "\n"))
        fragments.append(("class:hint", "\n↑↓ navigate  Enter select  q/Esc exit"))
        return fragments

    control = FormattedTextControl(_get_text)
    kb = KeyBindings()

    @kb.add("up")
    def _up(event: Any) -> None:
        cursor[0] = max(0, cursor[0] - 1)

    @kb.add("down")
    def _down(event: Any) -> None:
        cursor[0] = min(len(items) - 1, cursor[0] + 1)

    @kb.add("enter")
    def _enter(event: Any) -> None:
        event.app.exit(result=items[cursor[0]])

    @kb.add("q")
    @kb.add("escape")
    def _quit(event: Any) -> None:
        event.app.exit(result=None)

    app: Application[Any] = Application(
        layout=Layout(Window(control)),
        key_bindings=kb,
        full_screen=False,
    )
    return await app.run_async()


async def interactive_pick_option_or_custom(
    prompt: str,
    options: Sequence[dict[str, str]],
    *,
    allow_free_text: bool = True,
) -> dict[str, str] | None:
    """供 askuserquestion 使用的方向键选择器。

    返回下列值之一。
    - ``{"kind": "option", "label": ..., "value": ...}``
    - ``{"kind": "custom_prompt"}``
    - 取消时返回 ``None``。
    """
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    entries = [
        {"kind": "option", "label": str(item.get("label") or ""), "value": str(item.get("value") or "")}
        for item in options
        if str(item.get("label") or "").strip() and str(item.get("value") or "").strip()
    ]
    if allow_free_text:
        entries.append({"kind": "custom", "label": "Custom answer...", "value": ""})
    if not entries:
        return {"kind": "custom_prompt"} if allow_free_text else None

    cursor = [0]

    def _get_text() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        if prompt:
            fragments.append(("bold", prompt + "\n\n"))
        for idx, item in enumerate(entries):
            arrow = "▸ " if idx == cursor[0] else "  "
            style = "bold" if idx == cursor[0] else ""
            fragments.append((style, f"{arrow}{item['label']}\n"))
        hint = "\n↑↓ navigate  Enter submit"
        if allow_free_text:
            hint += "  Tab custom answer"
        hint += "  q/Esc exit"
        fragments.append(("class:hint", hint))
        return fragments

    control = FormattedTextControl(_get_text)
    kb = KeyBindings()

    @kb.add("up")
    def _up(event: Any) -> None:
        cursor[0] = max(0, cursor[0] - 1)

    @kb.add("down")
    def _down(event: Any) -> None:
        cursor[0] = min(len(entries) - 1, cursor[0] + 1)

    @kb.add("enter")
    def _enter(event: Any) -> None:
        chosen = entries[cursor[0]]
        if chosen["kind"] == "custom":
            event.app.exit(result={"kind": "custom_prompt"})
            return
        event.app.exit(result={"kind": "option", "label": chosen["label"], "value": chosen["value"]})

    if allow_free_text:
        @kb.add("tab")
        def _tab(event: Any) -> None:
            if entries[cursor[0]]["kind"] == "custom":
                event.app.exit(result={"kind": "custom_prompt"})

    @kb.add("q")
    @kb.add("escape")
    def _quit(event: Any) -> None:
        event.app.exit(result=None)

    app: Application[Any] = Application(
        layout=Layout(Window(control)),
        key_bindings=kb,
        full_screen=False,
    )
    return await app.run_async()
