"""방송 화면 위에 항상 떠 있는 자막 오버레이 창 (tkinter).

- 화면 아래쪽 가운데에 반투명 검은 배경으로 표시
- 마우스로 끌어서 위치 이동 가능
- ESC 키 또는 ✕ 버튼으로 종료
- 10초 동안 새 자막이 없으면 내용이 지워짐
"""

import queue
import time
import tkinter as tk
import tkinter.font as tkfont

_FONT_CANDIDATES = [
    "Malgun Gothic",        # Windows 한국어
    "Apple SD Gothic Neo",  # macOS
    "AppleGothic",
    "Noto Sans CJK KR",     # Linux
    "NanumGothic",
]

_CLEAR_AFTER_SEC = 10.0


def _pick_font(root):
    available = set(tkfont.families(root))
    for name in _FONT_CANDIDATES:
        if name in available:
            return name
    return "TkDefaultFont"


class SubtitleOverlay:
    """(일본어, 한국어) 자막 쌍을 ui_queue에서 꺼내 화면에 보여준다."""

    def __init__(self, ui_queue, stop_event, font_scale=1.0, show_japanese=True):
        self.ui_queue = ui_queue
        self.stop_event = stop_event
        self.show_japanese = show_japanese
        self._last_update = time.monotonic()
        self._drag_offset = None

        self.root = tk.Tk()
        self.root.title("실시간 번역 자막")
        self.root.overrideredirect(True)          # 테두리 없는 창
        self.root.attributes("-topmost", True)    # 항상 위
        try:
            self.root.attributes("-alpha", 0.88)  # 반투명
        except tk.TclError:
            pass
        self.root.configure(bg="#101014")

        family = _pick_font(self.root)
        ja_size = max(10, int(14 * font_scale))
        ko_size = max(12, int(20 * font_scale))

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self._wrap = int(screen_w * 0.68)

        frame = tk.Frame(self.root, bg="#101014", padx=18, pady=10)
        frame.pack(fill="both", expand=True)

        top = tk.Frame(frame, bg="#101014")
        top.pack(fill="x")
        tk.Label(top, text="● 일본어 실시간 번역", bg="#101014", fg="#5a5f6e",
                 font=(family, max(8, int(9 * font_scale)))).pack(side="left")
        close = tk.Label(top, text="✕", bg="#101014", fg="#8a8f9e",
                         font=(family, max(9, int(10 * font_scale))), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self._close())

        self.ja_label = tk.Label(
            frame, text="", bg="#101014", fg="#9aa0b0",
            font=(family, ja_size), wraplength=self._wrap, justify="center")
        if self.show_japanese:
            self.ja_label.pack(fill="x", pady=(4, 0))

        self.ko_label = tk.Label(
            frame, text="방송 소리를 기다리는 중...", bg="#101014", fg="#ffffff",
            font=(family, ko_size, "bold"), wraplength=self._wrap, justify="center")
        self.ko_label.pack(fill="x", pady=(2, 2))

        # 마우스로 끌어서 이동
        for widget in (self.root, frame, self.ja_label, self.ko_label):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
        self.root.bind("<Escape>", lambda e: self._close())
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        # 처음 위치: 화면 아래쪽 가운데
        self.root.update_idletasks()
        x = (screen_w - self.root.winfo_reqwidth()) // 2
        y = screen_h - self.root.winfo_reqheight() - 80
        self.root.geometry(f"+{x}+{y}")
        self._user_moved = False
        self._screen_w = screen_w
        self._screen_h = screen_h

        # ESC 키가 바로 먹히도록 창에 키보드 포커스를 준다
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def _drag_start(self, event):
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _drag_move(self, event):
        if self._drag_offset:
            x = event.x_root - self._drag_offset[0]
            y = event.y_root - self._drag_offset[1]
            self.root.geometry(f"+{x}+{y}")
            self._user_moved = True

    def _close(self):
        self.stop_event.set()

    def _reposition(self):
        """자막 길이가 바뀌어도 아래쪽 가운데를 유지한다 (사용자가 옮겼으면 그대로 둠)."""
        if self._user_moved:
            return
        self.root.update_idletasks()
        x = (self._screen_w - self.root.winfo_reqwidth()) // 2
        y = self._screen_h - self.root.winfo_reqheight() - 80
        self.root.geometry(f"+{x}+{y}")

    def _show(self, ja_text, ko_text, partial=False):
        if self.show_japanese:
            self.ja_label.config(text=ja_text)
        # 말하는 중(partial)에는 살짝 어둡게 + ⋯ 표시, 확정되면 밝은 흰색
        if partial:
            self.ko_label.config(text=ko_text + " ⋯", fg="#c8cbd4")
        else:
            self.ko_label.config(text=ko_text, fg="#ffffff")
        self._last_update = time.monotonic()
        self._reposition()

    def _poll(self):
        if self.stop_event.is_set():
            self.root.destroy()
            return
        try:
            while True:
                ja, ko, partial = self.ui_queue.get_nowait()
                self._show(ja, ko, partial)
        except queue.Empty:
            pass

        # 한동안 조용하면 자막을 지운다
        if (time.monotonic() - self._last_update > _CLEAR_AFTER_SEC
                and self.ko_label.cget("text")):
            self.ja_label.config(text="")
            self.ko_label.config(text="")
            self._reposition()

        self.root.after(100, self._poll)

    def run(self):
        """메인 스레드에서 호출 — 창이 닫힐 때까지 블록된다."""
        self.root.after(100, self._poll)
        self.root.mainloop()
        self.stop_event.set()
