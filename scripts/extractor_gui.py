from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import os
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from extract_assets import (
    DEFAULT_OUT,
    ExtractionMode,
    estimate_output_size,
    extract_mode,
    format_bytes,
    is_game_folder,
    resolve_game_path,
)


COLORS = {
    "window": "#0b1020",
    "surface": "#141b2d",
    "surface_alt": "#192338",
    "surface_selected": "#1d2a43",
    "border": "#2b3851",
    "text": "#f4f7fb",
    "muted": "#a8b3c7",
    "faint": "#75839c",
    "accent": "#d7a84a",
    "accent_hover": "#e4bb65",
    "accent_text": "#17120a",
    "success": "#62d6a5",
    "warning": "#f3bd63",
    "error": "#ff7b83",
    "input": "#0e1526",
}


MODE_CONTENT = {
    ExtractionMode.RELEVANT_ART: {
        "title": "Clean relevant art",
        "badge": "RECOMMENDED",
        "summary": "The complete, presentation-ready art library.",
        "includes": "Sprites · profiles · icons · effects · menus · maps · segues · loading art · audible MP4 cinematics",
        "detail": (
            "Only documented world-sprite controls are removed. Profiles, icons, "
            "effects, and UI art keep full palettes. TILE PNGs are source-audited."
        ),
    },
    ExtractionMode.RELEVANT_RAW: {
        "title": "Relevant art — raw",
        "badge": "CURATED SOURCE",
        "summary": "The useful library with game-control colors intact.",
        "includes": "Same curated art and MP4s as clean mode · plus original BIK videos",
        "detail": (
            "Keeps sprite shadow, blend, and transition pixels visible. Filters out "
            "noisy support sets and unrelated archive records."
        ),
    },
    ExtractionMode.ALL_RAW: {
        "title": "Everything — raw",
        "badge": "ARCHIVAL",
        "summary": "Every recognized art record and animation frame.",
        "includes": "All curated art · every sprite frame · support layers · uncategorized records · MP4 and BIK video",
        "detail": (
            "Largest and slowest. No relevance filtering or cleanup; includes "
            "near-duplicate frames and engine-only layers."
        ),
    },
}


class QueueWriter:
    def __init__(self, messages: queue.Queue[tuple[str, object]]) -> None:
        self.messages = messages

    def write(self, value: str) -> int:
        if value:
            self.messages.put(("log", value))
        return len(value)

    def flush(self) -> None:
        pass


class ExtractorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Majesty Gold HD Art Extractor")
        self.root.geometry("980x720")
        self.root.minsize(940, 680)
        self.root.configure(background=COLORS["window"])
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.details_visible = False
        self.mode_cards: dict[ExtractionMode, tuple[tk.Frame, list[tk.Widget]]] = {}

        try:
            default_game = str(resolve_game_path(None))
        except (FileNotFoundError, OSError, SystemExit):
            default_game = ""

        self.game_var = tk.StringVar(value=default_game)
        self.output_var = tk.StringVar(value=str(DEFAULT_OUT))
        self.mode_var = tk.StringVar(value=ExtractionMode.RELEVANT_ART.value)
        self.size_title_var = tk.StringVar(value="Calculating output size…")
        self.size_detail_var = tk.StringVar(value="Checking the selected drive")
        self.game_status_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready to extract")
        self.details_button_var = tk.StringVar(value="Show technical details")

        self._configure_styles()
        self._build()
        self.mode_var.trace_add("write", lambda *_args: self._mode_changed())
        self.output_var.trace_add("write", lambda *_args: self.refresh_estimate())
        self.game_var.trace_add("write", lambda *_args: self.refresh_estimate())
        self.root.after(100, self._poll_messages)
        self._mode_changed()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Modern.TEntry",
            fieldbackground=COLORS["input"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            insertcolor=COLORS["text"],
            padding=(10, 8),
        )
        style.map(
            "Modern.TEntry",
            bordercolor=[("focus", COLORS["accent"])],
            lightcolor=[("focus", COLORS["accent"])],
            darkcolor=[("focus", COLORS["accent"])],
        )
        style.configure(
            "Secondary.TButton",
            background=COLORS["surface_alt"],
            foreground=COLORS["text"],
            borderwidth=0,
            padding=(14, 9),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", COLORS["border"]), ("disabled", COLORS["surface"])],
            foreground=[("disabled", COLORS["faint"])],
        )
        style.configure(
            "Primary.TButton",
            background=COLORS["accent"],
            foreground=COLORS["accent_text"],
            borderwidth=0,
            padding=(20, 11),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["accent_hover"]), ("disabled", COLORS["border"])],
            foreground=[("disabled", COLORS["faint"])],
        )
        style.configure(
            "Gold.Horizontal.TProgressbar",
            troughcolor=COLORS["input"],
            background=COLORS["accent"],
            borderwidth=0,
            thickness=5,
        )
        style.configure(
            "Vertical.TScrollbar",
            troughcolor=COLORS["input"],
            background=COLORS["border"],
            borderwidth=0,
            arrowcolor=COLORS["muted"],
        )

    def _build(self) -> None:
        outer = tk.Frame(self.root, background=COLORS["window"], padx=28, pady=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)

        header = tk.Frame(outer, background=COLORS["window"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="MAJESTY GOLD HD",
            background=COLORS["window"],
            foreground=COLORS["accent"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="Art Extractor",
            background=COLORS["window"],
            foreground=COLORS["text"],
            font=("Segoe UI Semibold", 24),
        ).grid(row=1, column=0, sticky="w")
        tk.Label(
            header,
            text="Build an organized, source-verified art library from your local game installation.",
            background=COLORS["window"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 10),
        ).grid(row=2, column=0, sticky="w", pady=(3, 0))
        badge = tk.Label(
            header,
            text="LOCAL ONLY  ·  GAME FILES STAY UNCHANGED",
            background=COLORS["surface_alt"],
            foreground=COLORS["success"],
            font=("Segoe UI", 8, "bold"),
            padx=12,
            pady=7,
        )
        badge.grid(row=0, column=1, rowspan=2, sticky="ne")

        paths = self._card(outer, pady=12)
        paths.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        paths.columnconfigure(0, weight=1)
        paths.columnconfigure(1, weight=1)
        self._section_title(paths, "Locations", "The game is read-only; only the destination is written.", 0)

        location_grid = tk.Frame(paths, background=COLORS["surface"])
        location_grid.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(11, 0))
        location_grid.columnconfigure(0, weight=1, uniform="location")
        location_grid.columnconfigure(1, weight=1, uniform="location")

        game_group = tk.Frame(location_grid, background=COLORS["surface"])
        game_group.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        game_group.columnconfigure(0, weight=1)
        tk.Label(
            game_group,
            text="GAME INSTALLATION",
            background=COLORS["surface"],
            foreground=COLORS["faint"],
            font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.game_status = tk.Label(
            game_group,
            textvariable=self.game_status_var,
            background=COLORS["surface"],
            foreground=COLORS["success"],
            font=("Segoe UI", 8),
        )
        self.game_status.grid(row=0, column=1, sticky="e")
        self.game_entry = ttk.Entry(game_group, textvariable=self.game_var, style="Modern.TEntry")
        self.game_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.game_button = ttk.Button(game_group, text="Browse", style="Secondary.TButton", command=self._choose_game)
        self.game_button.grid(row=1, column=1, padx=(8, 0), pady=(5, 0))

        output_group = tk.Frame(location_grid, background=COLORS["surface"])
        output_group.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        output_group.columnconfigure(0, weight=1)
        tk.Label(
            output_group,
            text="SAVE ART TO",
            background=COLORS["surface"],
            foreground=COLORS["faint"],
            font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.output_entry = ttk.Entry(output_group, textvariable=self.output_var, style="Modern.TEntry")
        self.output_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.output_button = ttk.Button(output_group, text="Browse", style="Secondary.TButton", command=self._choose_output)
        self.output_button.grid(row=1, column=1, padx=(8, 0), pady=(5, 0))

        mode_header = tk.Frame(outer, background=COLORS["window"])
        mode_header.grid(row=2, column=0, sticky="ew", pady=(0, 9))
        tk.Label(
            mode_header,
            text="Choose an extraction",
            background=COLORS["window"],
            foreground=COLORS["text"],
            font=("Segoe UI Semibold", 13),
        ).pack(side="left")
        tk.Label(
            mode_header,
            text="All three include menus, maps, loading art, segues, and playable cinematics.",
            background=COLORS["window"],
            foreground=COLORS["faint"],
            font=("Segoe UI", 9),
        ).pack(side="right")

        modes = tk.Frame(outer, background=COLORS["window"])
        modes.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        for column in range(3):
            modes.columnconfigure(column, weight=1, uniform="mode")
        for column, mode in enumerate(
            (ExtractionMode.RELEVANT_ART, ExtractionMode.RELEVANT_RAW, ExtractionMode.ALL_RAW)
        ):
            self._build_mode_card(modes, mode, column)

        estimate = self._card(outer, padx=18, pady=10)
        estimate.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        estimate.columnconfigure(1, weight=1)
        tk.Label(
            estimate,
            text="SPACE",
            background=COLORS["surface"],
            foreground=COLORS["accent"],
            font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 18))
        tk.Label(
            estimate,
            textvariable=self.size_title_var,
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=("Segoe UI Semibold", 11),
        ).grid(row=0, column=1, sticky="w")
        self.size_detail = tk.Label(
            estimate,
            textvariable=self.size_detail_var,
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        self.size_detail.grid(row=1, column=1, sticky="w", pady=(2, 0))

        activity = tk.Frame(outer, background=COLORS["window"])
        activity.grid(row=5, column=0, sticky="ew")
        activity.columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            activity,
            textvariable=self.status_var,
            background=COLORS["window"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        self.details_button = tk.Button(
            activity,
            textvariable=self.details_button_var,
            command=self._toggle_details,
            background=COLORS["window"],
            foreground=COLORS["muted"],
            activebackground=COLORS["window"],
            activeforeground=COLORS["text"],
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Segoe UI", 9, "underline"),
        )
        self.details_button.grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(activity, mode="indeterminate", style="Gold.Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))

        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("Extraction details")
        self.log_window.geometry("780x360")
        self.log_window.minsize(560, 260)
        self.log_window.configure(background=COLORS["window"])
        self.log_window.protocol("WM_DELETE_WINDOW", self._hide_details)
        self.log_window.withdraw()
        tk.Label(
            self.log_window,
            text="Extraction details",
            background=COLORS["window"],
            foreground=COLORS["text"],
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w", padx=18, pady=(15, 8))
        self.log_frame = tk.Frame(
            self.log_window,
            background=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        self.log_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.log_frame.rowconfigure(0, weight=1)
        self.log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(
            self.log_frame,
            height=7,
            wrap="word",
            state="disabled",
            background=COLORS["input"],
            foreground=COLORS["muted"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["border"],
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            font=("Cascadia Mono", 9),
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        actions = tk.Frame(outer, background=COLORS["window"])
        actions.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        self.open_button = ttk.Button(
            actions,
            text="Open output folder",
            style="Secondary.TButton",
            command=self._open_output,
        )
        self.open_button.grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Close", style="Secondary.TButton", command=self._close).grid(
            row=0, column=1, padx=(0, 10)
        )
        self.extract_button = ttk.Button(
            actions,
            text="Extract art",
            style="Primary.TButton",
            command=self._start_extract,
        )
        self.extract_button.grid(row=0, column=2)

    def _card(self, parent: tk.Widget, *, padx: int = 18, pady: int = 16) -> tk.Frame:
        return tk.Frame(
            parent,
            background=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=padx,
            pady=pady,
        )

    def _section_title(self, parent: tk.Widget, title: str, subtitle: str, row: int) -> None:
        tk.Label(
            parent,
            text=title,
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=("Segoe UI Semibold", 12),
        ).grid(row=row, column=0, sticky="w")
        tk.Label(
            parent,
            text=subtitle,
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        ).grid(row=row, column=1, columnspan=2, sticky="w")

    def _build_mode_card(self, parent: tk.Widget, mode: ExtractionMode, column: int) -> None:
        content = MODE_CONTENT[mode]
        card = tk.Frame(
            parent,
            background=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=15,
            pady=11,
            cursor="hand2",
        )
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0 if column == 2 else 5))
        card.columnconfigure(0, weight=1)
        widgets: list[tk.Widget] = []

        top = tk.Frame(card, background=COLORS["surface"], cursor="hand2")
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        widgets.append(top)
        radio = tk.Radiobutton(
            top,
            text=content["title"],
            variable=self.mode_var,
            value=mode.value,
            command=self._mode_changed,
            background=COLORS["surface"],
            foreground=COLORS["text"],
            activebackground=COLORS["surface"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["surface_alt"],
            font=("Segoe UI Semibold", 11),
            cursor="hand2",
            anchor="w",
        )
        radio.grid(row=0, column=0, sticky="w")
        widgets.append(radio)
        badge = tk.Label(
            top,
            text=content["badge"],
            background=COLORS["surface_alt"],
            foreground=COLORS["accent"] if mode is ExtractionMode.RELEVANT_ART else COLORS["faint"],
            font=("Segoe UI", 7, "bold"),
            padx=7,
            pady=3,
            cursor="hand2",
        )
        badge.grid(row=0, column=1, sticky="e")
        widgets.append(badge)

        for row, (text, color, font) in enumerate(
            (
                (content["summary"], COLORS["text"], ("Segoe UI", 9, "bold")),
                (content["includes"], COLORS["accent"], ("Segoe UI", 8)),
                (content["detail"], COLORS["muted"], ("Segoe UI", 8)),
            ),
            start=1,
        ):
            label = tk.Label(
                card,
                text=text,
                background=COLORS["surface"],
                foreground=color,
                justify="left",
                anchor="nw",
                wraplength=250,
                font=font,
                cursor="hand2",
            )
            label.grid(row=row, column=0, sticky="ew", pady=(6 if row == 1 else 4, 0))
            widgets.append(label)

        def select(_event: tk.Event | None = None) -> None:
            if not self.running:
                self.mode_var.set(mode.value)

        card.bind("<Button-1>", select)
        for widget in widgets:
            widget.bind("<Button-1>", select)
        self.mode_cards[mode] = (card, widgets)

    def _mode_changed(self) -> None:
        selected = ExtractionMode(self.mode_var.get())
        for mode, (card, widgets) in self.mode_cards.items():
            active = mode is selected
            background = COLORS["surface_selected"] if active else COLORS["surface"]
            card.configure(background=background, highlightbackground=COLORS["accent"] if active else COLORS["border"])
            for widget in widgets:
                if isinstance(widget, (tk.Frame, tk.Label, tk.Radiobutton)):
                    try:
                        widget.configure(background=background)
                    except tk.TclError:
                        pass
                if isinstance(widget, tk.Radiobutton):
                    widget.configure(activebackground=background)
        self.refresh_estimate()

    def _choose_game(self) -> None:
        chosen = filedialog.askdirectory(
            title="Select the Majesty HD game folder",
            initialdir=self.game_var.get() or None,
        )
        if chosen:
            self.game_var.set(chosen)

    def _choose_output(self) -> None:
        chosen = filedialog.askdirectory(
            title="Choose where the extracted art library will be created",
            initialdir=self.output_var.get() or None,
        )
        if chosen:
            self.output_var.set(chosen)

    def refresh_estimate(self) -> None:
        try:
            game = Path(self.game_var.get())
            output = Path(self.output_var.get())
            if not is_game_folder(game):
                self.game_status_var.set("Majesty installation not detected")
                self.game_status.configure(foreground=COLORS["error"])
                self.size_title_var.set("Choose a valid game installation")
                self.size_detail_var.set("Expected a folder containing Data\\maindata.cam")
                self.size_detail.configure(foreground=COLORS["muted"])
                return
            self.game_status_var.set("Detected · ready")
            self.game_status.configure(foreground=COLORS["success"])
            estimate = estimate_output_size(game, self.mode_var.get())
            existing = output
            while not existing.exists() and existing != existing.parent:
                existing = existing.parent
            free = shutil.disk_usage(existing).free
            enough = free >= estimate
            self.size_title_var.set(f"Up to {format_bytes(estimate)} estimated")
            self.size_detail_var.set(
                f"{format_bytes(free)} free on the destination drive  ·  "
                f"{'Enough space available' if enough else 'More free space is required'}"
            )
            self.size_detail.configure(foreground=COLORS["success"] if enough else COLORS["error"])
        except (OSError, ValueError):
            self.size_title_var.set("Space estimate unavailable")
            self.size_detail_var.set("Check that the destination path is accessible")
            self.size_detail.configure(foreground=COLORS["warning"])

    def _start_extract(self) -> None:
        if self.running:
            return
        game = Path(self.game_var.get())
        output_text = self.output_var.get().strip()
        if not is_game_folder(game):
            messagebox.showerror(
                "Game installation not found",
                "Choose the Majesty HD folder containing Data\\maindata.cam.",
            )
            return
        if not output_text:
            messagebox.showerror("Destination required", "Choose where the extracted art library should be written.")
            return
        output = Path(output_text)
        if output.exists() and any(output.iterdir()):
            if not messagebox.askyesno(
                "Replace the existing extraction?",
                f"The current contents of this extraction folder will be replaced:\n\n{output}\n\nContinue?",
            ):
                return

        self.running = True
        self._set_inputs_enabled(False)
        self.progress.start(11)
        self.status_var.set("Extracting and source-verifying your art library…")
        self.status_label.configure(foreground=COLORS["accent"])
        self._append_log("\n— Starting extraction —\n")
        mode = ExtractionMode(self.mode_var.get())
        threading.Thread(target=self._extract_worker, args=(game, output, mode), daemon=True).start()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.extract_button.configure(state=state)
        self.game_entry.configure(state=state)
        self.output_entry.configure(state=state)
        self.game_button.configure(state=state)
        self.output_button.configure(state=state)

    def _extract_worker(self, game: Path, output: Path, mode: ExtractionMode) -> None:
        writer = QueueWriter(self.messages)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                total = extract_mode(game, output, mode)
            self.messages.put(("done", (total, output)))
        except Exception as exc:  # GUI boundary: report errors instead of disappearing.
            self.messages.put(("error", str(exc)))

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "done":
                    total, output = payload
                    self._finish()
                    self.status_var.set(f"Complete · {total:,} PNG files · source-pixel audit passed")
                    self.status_label.configure(foreground=COLORS["success"])
                    if messagebox.askyesno(
                        "Your art library is ready",
                        f"Created {total:,} PNG files and verified them against the source archives.\n\n{output}\n\nOpen the folder now?",
                    ):
                        self._open_path(Path(output))
                elif kind == "error":
                    self._finish()
                    self.status_var.set("Extraction stopped · see the error for details")
                    self.status_label.configure(foreground=COLORS["error"])
                    messagebox.showerror("Extraction could not be completed", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    def _finish(self) -> None:
        self.running = False
        self.progress.stop()
        self._set_inputs_enabled(True)
        self.refresh_estimate()

    def _toggle_details(self) -> None:
        if self.log_window.state() == "withdrawn":
            self.details_visible = True
            self.log_window.deiconify()
            self.log_window.lift()
            self.log_window.focus_set()
            self.details_button_var.set("Hide technical details")
        else:
            self._hide_details()

    def _hide_details(self) -> None:
        self.details_visible = False
        self.log_window.withdraw()
        self.details_button_var.set("Show technical details")

    def _open_output(self) -> None:
        output = Path(self.output_var.get())
        if not output.exists():
            messagebox.showinfo("Output folder not created yet", "Run an extraction first, or choose an existing folder.")
            return
        self._open_path(output)

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc))

    def _close(self) -> None:
        if self.running and not messagebox.askyesno(
            "Extraction is still running",
            "Closing now will interrupt extraction and may leave a partial output folder. Close anyway?",
        ):
            return
        self.root.destroy()

    def _append_log(self, value: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", value)
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> int:
    root = tk.Tk()
    ExtractorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
