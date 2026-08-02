"""Windowed front end for the Majesty Gold HD art extractor.

Standard library only. tkinter ships with Python on Windows, so the tool stays
a download-and-run affair with no packaging step.

The palette is sampled from the game's own interface art rather than invented:
warm near-black stone (#181410 through #403830), aged gold filigree (#d8a058),
and parchment text. Ornaments are drawn with Canvas primitives so there are no
image files to ship.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import os
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import ffmpeg_support
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
    "window": "#12100c",
    "surface": "#1e1a14",
    "surface_alt": "#282016",
    "surface_selected": "#33291b",
    "border": "#4a4038",
    "border_lit": "#6b5a3c",
    "gold": "#d8a058",
    "gold_lit": "#eac278",
    "gold_dim": "#8a6f42",
    "gold_text": "#1a1206",
    "text": "#ece3d0",
    "muted": "#a89880",
    "faint": "#7a6c5a",
    "success": "#8fbf7a",
    "warning": "#e0b060",
    "error": "#d97a62",
    "input": "#0d0b08",
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


# Milestones the extractor prints, mapped to a share of the run. This is what
# turns the progress bar from a barber pole into something honest.
PROGRESS_STAGES = (
    ("Extracting game art records", 4),
    ("Extracting curated interface records", 34),
    ("Extracting maps, cinematics", 52),
    ("Auditing decoded TILE pixels", 78),
    ("Writing manifest", 92),
    ("Creating preview sheets", 96),
    ("Extraction stages finished", 99),
)


def enable_dpi_awareness() -> None:
    """Stop Windows from bitmap-scaling the window into a blur."""
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # per-monitor
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError, ImportError):
        pass


def pick_font(root: tk.Tk, candidates: tuple[str, ...], fallback: str) -> str:
    """First installed family from candidates.

    Named families are not guaranteed present, and tkinter silently substitutes
    something arbitrary when one is missing rather than telling you.
    """
    available = {name.lower() for name in tkfont.families(root)}
    for name in candidates:
        if name.lower() in available:
            return name
    return fallback


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
        self.root.geometry("1000x830")
        self.root.minsize(940, 780)
        self.root.configure(background=COLORS["window"])
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.mode_cards: dict[ExtractionMode, tuple[tk.Frame, list[tk.Widget]]] = {}
        self.mode_radios: dict[ExtractionMode, tk.Radiobutton] = {}

        self.ui_family = pick_font(root, ("Segoe UI", "Tahoma", "Verdana"), "TkDefaultFont")
        self.head_family = pick_font(
            root, ("Trajan Pro", "Georgia", "Palatino Linotype", "Book Antiqua", "Segoe UI Semibold"), self.ui_family
        )
        self.mono_family = pick_font(
            root, ("Cascadia Mono", "Consolas", "Lucida Console", "Courier New"), "TkFixedFont"
        )

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
        # Default on only when FFmpeg is already here, so the first run of a
        # fresh copy never proposes a download the user did not ask about.
        self.cinematics_var = tk.BooleanVar(value=ffmpeg_support.find_ffmpeg() is not None)
        self.cinematics_detail_var = tk.StringVar(value="")

        self._configure_styles()
        self._build()
        self.mode_var.trace_add("write", lambda *_args: self._mode_changed())
        self.output_var.trace_add("write", lambda *_args: self.refresh_estimate())
        self.game_var.trace_add("write", lambda *_args: self.refresh_estimate())
        self.root.after(100, self._poll_messages)
        self._mode_changed()

    # ---------------------------------------------------------------- styling

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
            insertcolor=COLORS["gold"],
            padding=(10, 8),
        )
        style.map(
            "Modern.TEntry",
            bordercolor=[("focus", COLORS["gold"])],
            lightcolor=[("focus", COLORS["gold"])],
            darkcolor=[("focus", COLORS["gold"])],
            fieldbackground=[("disabled", COLORS["surface"])],
            foreground=[("disabled", COLORS["faint"])],
        )
        style.configure(
            "Secondary.TButton",
            background=COLORS["surface_alt"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            borderwidth=1,
            padding=(14, 9),
            font=(self.ui_family, 9, "bold"),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", COLORS["surface_selected"]), ("disabled", COLORS["surface"])],
            bordercolor=[("active", COLORS["border_lit"])],
            foreground=[("disabled", COLORS["faint"])],
        )
        style.configure(
            "Primary.TButton",
            background=COLORS["gold"],
            foreground=COLORS["gold_text"],
            bordercolor=COLORS["gold_lit"],
            borderwidth=1,
            padding=(22, 11),
            font=(self.ui_family, 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["gold_lit"]), ("disabled", COLORS["gold_dim"])],
            foreground=[("disabled", COLORS["faint"])],
        )
        style.configure(
            "Gold.Horizontal.TProgressbar",
            troughcolor=COLORS["input"],
            background=COLORS["gold"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["gold_lit"],
            darkcolor=COLORS["gold_dim"],
            borderwidth=0,
            thickness=6,
        )
        style.configure(
            "Vertical.TScrollbar",
            troughcolor=COLORS["input"],
            background=COLORS["border"],
            bordercolor=COLORS["window"],
            borderwidth=0,
            arrowcolor=COLORS["muted"],
        )

    # ------------------------------------------------------------- ornaments

    def _filigree_rule(self, parent: tk.Widget, width: int = 760) -> tk.Canvas:
        """A gold divider with a centred diamond, echoing the game's panels."""
        height = 13
        canvas = tk.Canvas(
            parent,
            height=height,
            width=width,
            background=COLORS["window"],
            highlightthickness=0,
            borderwidth=0,
        )
        mid = height // 2

        def redraw(_event: tk.Event | None = None) -> None:
            canvas.delete("all")
            span = canvas.winfo_width() or width
            centre = span // 2
            gap = 20
            # A continuous rule either side of the diamond, with a small hook at
            # the inner end so it reads as a drawn ornament rather than a border.
            for direction in (-1, 1):
                inner = centre + direction * gap
                outer = 10 if direction < 0 else span - 10
                canvas.create_line(outer, mid, inner, mid, fill=COLORS["gold_dim"], width=1)
                canvas.create_line(
                    inner, mid, inner - direction * 9, mid, fill=COLORS["gold"], width=2
                )
                canvas.create_arc(
                    inner - direction * 9 - 5, mid - 5, inner - direction * 9 + 5, mid + 5,
                    start=90 if direction < 0 else 0, extent=90,
                    style="arc", outline=COLORS["gold_dim"],
                )
            canvas.create_polygon(
                centre, mid - 5, centre + 6, mid, centre, mid + 5, centre - 6, mid,
                fill=COLORS["surface_alt"], outline=COLORS["gold"],
            )
            canvas.create_polygon(
                centre, mid - 2, centre + 2, mid, centre, mid + 2, centre - 2, mid,
                fill=COLORS["gold_lit"], outline="",
            )

        canvas.bind("<Configure>", redraw)
        redraw()
        return canvas

    def _crest(self, parent: tk.Widget, size: int = 46) -> tk.Canvas:
        """A small shield mark for the header."""
        canvas = tk.Canvas(
            parent,
            width=size,
            height=size,
            background=COLORS["window"],
            highlightthickness=0,
            borderwidth=0,
        )
        pad = 4
        right = size - pad
        waist = size * 0.60
        canvas.create_polygon(
            pad, pad + 3, right, pad + 3, right, waist, size / 2, right, pad, waist,
            fill=COLORS["surface_alt"], outline=COLORS["gold"], width=2,
        )
        canvas.create_line(size / 2, pad + 7, size / 2, right - 7, fill=COLORS["gold_dim"])
        canvas.create_line(pad + 7, waist - 8, right - 7, waist - 8, fill=COLORS["gold_dim"])
        for cx, cy in ((size * 0.33, pad + 12), (size * 0.67, pad + 12)):
            canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=COLORS["gold"], outline="")
        canvas.create_polygon(
            size / 2, waist - 2, size / 2 + 5, waist + 6, size / 2, waist + 14, size / 2 - 5, waist + 6,
            fill="", outline=COLORS["gold_lit"],
        )
        return canvas

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        outer = tk.Frame(self.root, background=COLORS["window"], padx=30, pady=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(8, weight=1)  # spacer row absorbs vertical growth

        header = tk.Frame(outer, background=COLORS["window"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        self._crest(header).grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 14), pady=(2, 0))

        tk.Label(
            header,
            text="MAJESTY GOLD HD",
            background=COLORS["window"],
            foreground=COLORS["gold"],
            font=(self.ui_family, 9, "bold"),
        ).grid(row=0, column=1, sticky="w")
        tk.Label(
            header,
            text="Art Extractor",
            background=COLORS["window"],
            foreground=COLORS["text"],
            font=(self.head_family, 25),
        ).grid(row=1, column=1, sticky="w")
        tk.Label(
            header,
            text="Build an organized, source-verified art library from your own installation.",
            background=COLORS["window"],
            foreground=COLORS["muted"],
            font=(self.ui_family, 10),
        ).grid(row=2, column=1, sticky="w", pady=(3, 0))
        tk.Label(
            header,
            text="LOCAL ONLY  ·  GAME FILES ARE ONLY READ",
            background=COLORS["surface_alt"],
            foreground=COLORS["success"],
            font=(self.ui_family, 8, "bold"),
            padx=12,
            pady=7,
        ).grid(row=0, column=2, rowspan=2, sticky="ne")

        self._filigree_rule(outer).grid(row=1, column=0, sticky="ew", pady=(10, 12))

        paths = self._card(outer, pady=13)
        paths.grid(row=2, column=0, sticky="ew", pady=(0, 13))
        paths.columnconfigure(0, weight=1)
        paths.columnconfigure(1, weight=1)
        self._section_title(paths, "Locations", "The game is only read from; only the destination is written to.", 0)

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
            font=(self.ui_family, 8, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.game_status = tk.Label(
            game_group,
            textvariable=self.game_status_var,
            background=COLORS["surface"],
            foreground=COLORS["success"],
            font=(self.ui_family, 8),
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
            font=(self.ui_family, 8, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.output_entry = ttk.Entry(output_group, textvariable=self.output_var, style="Modern.TEntry")
        self.output_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.output_button = ttk.Button(
            output_group, text="Browse", style="Secondary.TButton", command=self._choose_output
        )
        self.output_button.grid(row=1, column=1, padx=(8, 0), pady=(5, 0))

        mode_header = tk.Frame(outer, background=COLORS["window"])
        mode_header.grid(row=3, column=0, sticky="ew", pady=(0, 9))
        tk.Label(
            mode_header,
            text="Choose an extraction",
            background=COLORS["window"],
            foreground=COLORS["text"],
            font=(self.head_family, 14),
        ).pack(side="left")
        tk.Label(
            mode_header,
            text="All three include menus, maps, loading art, segues, and playable cinematics.",
            background=COLORS["window"],
            foreground=COLORS["faint"],
            font=(self.ui_family, 9),
        ).pack(side="right")

        modes = tk.Frame(outer, background=COLORS["window"])
        modes.grid(row=4, column=0, sticky="ew", pady=(0, 13))
        for column in range(3):
            modes.columnconfigure(column, weight=1, uniform="mode")
        for column, mode in enumerate(
            (ExtractionMode.RELEVANT_ART, ExtractionMode.RELEVANT_RAW, ExtractionMode.ALL_RAW)
        ):
            self._build_mode_card(modes, mode, column)

        estimate = self._card(outer, padx=18, pady=11)
        estimate.grid(row=5, column=0, sticky="ew", pady=(0, 9))
        estimate.columnconfigure(1, weight=1)
        tk.Label(
            estimate,
            text="SPACE",
            background=COLORS["surface"],
            foreground=COLORS["gold"],
            font=(self.ui_family, 8, "bold"),
        ).grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 18))
        tk.Label(
            estimate,
            textvariable=self.size_title_var,
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=(self.ui_family, 11, "bold"),
        ).grid(row=0, column=1, sticky="w")
        self.size_detail = tk.Label(
            estimate,
            textvariable=self.size_detail_var,
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=(self.ui_family, 9),
        )
        self.size_detail.grid(row=1, column=1, sticky="w", pady=(2, 0))

        self._build_cinematics_card(outer)

        activity = tk.Frame(outer, background=COLORS["window"])
        activity.grid(row=7, column=0, sticky="ew")
        activity.columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            activity,
            textvariable=self.status_var,
            background=COLORS["window"],
            foreground=COLORS["muted"],
            font=(self.ui_family, 9),
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        self.details_button = tk.Button(
            activity,
            textvariable=self.details_button_var,
            command=self._toggle_details,
            background=COLORS["window"],
            foreground=COLORS["muted"],
            activebackground=COLORS["window"],
            activeforeground=COLORS["gold"],
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=(self.ui_family, 9, "underline"),
        )
        self.details_button.grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(
            activity, mode="determinate", maximum=100, style="Gold.Horizontal.TProgressbar"
        )
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))

        self._build_log_window()

        actions = tk.Frame(outer, background=COLORS["window"])
        actions.grid(row=9, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)
        self.open_button = ttk.Button(
            actions, text="Open output folder", style="Secondary.TButton", command=self._open_output
        )
        self.open_button.grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Close", style="Secondary.TButton", command=self._close).grid(
            row=0, column=1, padx=(0, 10)
        )
        self.extract_button = ttk.Button(
            actions, text="Extract art", style="Primary.TButton", command=self._start_extract
        )
        self.extract_button.grid(row=0, column=2)

    def _build_cinematics_card(self, outer: tk.Widget) -> None:
        """Opt-in for the one thing that cannot be done with the standard library.

        Cinematics, quest maps and segues are Bink video. Everything else here
        runs with nothing installed, so this stays a deliberate choice rather
        than a silent download.
        """
        card = self._card(outer, padx=18, pady=11)
        card.grid(row=6, column=0, sticky="ew", pady=(0, 9))
        card.columnconfigure(1, weight=1)

        self.cinematics_check = tk.Checkbutton(
            card,
            text="Include cinematics, quest maps and segues",
            variable=self.cinematics_var,
            command=self._cinematics_changed,
            background=COLORS["surface"],
            foreground=COLORS["text"],
            activebackground=COLORS["surface"],
            activeforeground=COLORS["gold_lit"],
            selectcolor=COLORS["input"],
            font=(self.ui_family, 10, "bold"),
            anchor="w",
            cursor="hand2",
        )
        self.cinematics_check.grid(row=0, column=0, columnspan=2, sticky="w")
        self.cinematics_detail = tk.Label(
            card,
            textvariable=self.cinematics_detail_var,
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=(self.ui_family, 9),
            justify="left",
            anchor="w",
        )
        self.cinematics_detail.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self._cinematics_changed()

    def _cinematics_changed(self) -> None:
        found = ffmpeg_support.find_ffmpeg()
        if not self.cinematics_var.get():
            self.cinematics_detail_var.set(
                "Left off, the extractor needs nothing installed at all. "
                "These records are Bink video and will be skipped."
            )
            self.cinematics_detail.configure(foreground=COLORS["muted"])
        elif found is not None:
            self.cinematics_detail_var.set(f"Using the FFmpeg already on this machine:  {found}")
            self.cinematics_detail.configure(foreground=COLORS["success"])
        else:
            self.cinematics_detail_var.set(
                f"FFmpeg is not on this machine. About {ffmpeg_support.FFMPEG_APPROX_MB} MB "
                "will be downloaded when you start, after you confirm."
            )
            self.cinematics_detail.configure(foreground=COLORS["warning"])
        self.refresh_estimate()

    def _build_log_window(self) -> None:
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("Extraction details")
        self.log_window.geometry("820x380")
        self.log_window.minsize(560, 260)
        self.log_window.configure(background=COLORS["window"])
        self.log_window.protocol("WM_DELETE_WINDOW", self._hide_details)
        self.log_window.withdraw()
        tk.Label(
            self.log_window,
            text="Extraction details",
            background=COLORS["window"],
            foreground=COLORS["text"],
            font=(self.head_family, 14),
        ).pack(anchor="w", padx=18, pady=(15, 8))
        frame = tk.Frame(
            self.log_window,
            background=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.log = tk.Text(
            frame,
            height=7,
            wrap="word",
            state="disabled",
            background=COLORS["input"],
            foreground=COLORS["muted"],
            insertbackground=COLORS["gold"],
            selectbackground=COLORS["surface_selected"],
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            font=(self.mono_family, 9),
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

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
            font=(self.head_family, 13),
        ).grid(row=row, column=0, sticky="w")
        tk.Label(
            parent,
            text=subtitle,
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=(self.ui_family, 9),
        ).grid(row=row, column=1, columnspan=2, sticky="w")

    def _build_mode_card(self, parent: tk.Widget, mode: ExtractionMode, column: int) -> None:
        content = MODE_CONTENT[mode]
        card = tk.Frame(
            parent,
            background=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=15,
            pady=12,
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
            activeforeground=COLORS["gold_lit"],
            selectcolor=COLORS["input"],
            font=(self.ui_family, 11, "bold"),
            cursor="hand2",
            anchor="w",
        )
        radio.grid(row=0, column=0, sticky="w")
        widgets.append(radio)
        self.mode_radios[mode] = radio
        badge = tk.Label(
            top,
            text=content["badge"],
            background=COLORS["surface_alt"],
            foreground=COLORS["gold"] if mode is ExtractionMode.RELEVANT_ART else COLORS["faint"],
            font=(self.ui_family, 7, "bold"),
            padx=7,
            pady=3,
            cursor="hand2",
        )
        badge.grid(row=0, column=1, sticky="e")
        widgets.append(badge)

        for row, (text, color, font_spec) in enumerate(
            (
                (content["summary"], COLORS["text"], (self.ui_family, 9, "bold")),
                (content["includes"], COLORS["gold"], (self.ui_family, 8)),
                (content["detail"], COLORS["muted"], (self.ui_family, 8)),
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
                font=font_spec,
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
            card.configure(
                background=background,
                highlightbackground=COLORS["gold"] if active else COLORS["border"],
            )
            for widget in widgets:
                if isinstance(widget, (tk.Frame, tk.Label, tk.Radiobutton)):
                    try:
                        widget.configure(background=background)
                    except tk.TclError:
                        pass
                if isinstance(widget, tk.Radiobutton):
                    widget.configure(activebackground=background)
        self.refresh_estimate()

    # --------------------------------------------------------------- actions

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
                "Everything in this folder will be deleted and rebuilt:\n\n"
                f"{output}\n\nContinue?",
            ):
                return

        # Settled before the worker starts so the download prompt happens on
        # the UI thread, where a dialog belongs.
        ffmpeg = self._resolve_ffmpeg()
        if ffmpeg is None and self.cinematics_var.get():
            if not messagebox.askyesno(
                "Continue without cinematics?",
                "Cinematics, quest maps and segues will be skipped.\n\n"
                "Everything else extracts normally. Continue?",
            ):
                return

        self.running = True
        self._set_inputs_enabled(False)
        self.progress.configure(value=0)
        self.status_var.set("Preparing…")
        self.status_label.configure(foreground=COLORS["gold"])
        self._append_log("\n— Starting extraction —\n")
        mode = ExtractionMode(self.mode_var.get())
        threading.Thread(
            target=self._extract_worker, args=(game, output, mode, ffmpeg), daemon=True
        ).start()

    def _resolve_ffmpeg(self) -> Path | None:
        if not self.cinematics_var.get():
            return None
        try:
            return ffmpeg_support.resolve_ffmpeg(
                allow_download=True,
                confirm=lambda message: messagebox.askyesno("Download FFmpeg?", message),
                progress=self._append_log,
            )
        except ffmpeg_support.FFmpegUnavailable as error:
            messagebox.showerror("FFmpeg could not be set up", str(error))
            return None

    def _set_inputs_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.extract_button.configure(state=state)
        self.game_entry.configure(state=state)
        self.output_entry.configure(state=state)
        self.game_button.configure(state=state)
        self.output_button.configure(state=state)
        # The cards guard themselves through self.running, but the radio
        # buttons are real widgets and would otherwise still accept clicks and
        # show a selection that does not match the run in progress.
        for radio in self.mode_radios.values():
            radio.configure(state=state)
        self.cinematics_check.configure(state=state)

    def _extract_worker(
        self, game: Path, output: Path, mode: ExtractionMode, ffmpeg: Path | None
    ) -> None:
        writer = QueueWriter(self.messages)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                total = extract_mode(game, output, mode, ffmpeg=ffmpeg)
            self.messages.put(("done", (total, output)))
        except Exception as exc:  # GUI boundary: report errors instead of disappearing.
            self.messages.put(("error", str(exc)))

    def _advance_progress(self, text: str) -> None:
        for marker, percent in PROGRESS_STAGES:
            if marker in text:
                if percent > self.progress["value"]:
                    self.progress.configure(value=percent)
                self.status_var.set(text.strip().rstrip(".") or "Working…")
                break

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                    self._advance_progress(str(payload))
                elif kind == "done":
                    total, output = payload
                    self._finish()
                    self.progress.configure(value=100)
                    self.status_var.set(f"Complete · {total:,} PNG files · source-pixel audit passed")
                    self.status_label.configure(foreground=COLORS["success"])
                    if messagebox.askyesno(
                        "Your art library is ready",
                        f"Created {total:,} PNG files and verified them against the source archives.\n\n"
                        f"{output}\n\nOpen the folder now?",
                    ):
                        self._open_path(Path(output))
                elif kind == "error":
                    self._finish()
                    self.progress.configure(value=0)
                    self.status_var.set("Extraction stopped · see the error for details")
                    self.status_label.configure(foreground=COLORS["error"])
                    messagebox.showerror("Extraction could not be completed", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    def _finish(self) -> None:
        self.running = False
        self._set_inputs_enabled(True)
        self.refresh_estimate()

    def _toggle_details(self) -> None:
        if self.log_window.state() == "withdrawn":
            self.log_window.deiconify()
            self.log_window.lift()
            self.log_window.focus_set()
            self.details_button_var.set("Hide technical details")
        else:
            self._hide_details()

    def _hide_details(self) -> None:
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
            os.startfile(path)  # noqa: S606  -- Windows-only tool, matching the game
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
    enable_dpi_awareness()
    root = tk.Tk()
    ExtractorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
