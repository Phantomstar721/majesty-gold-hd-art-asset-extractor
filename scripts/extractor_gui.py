from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import queue
from pathlib import Path
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from extract_assets import (
    DEFAULT_OUT,
    ExtractionMode,
    MODE_LABELS,
    estimate_output_size,
    extract_mode,
    format_bytes,
    is_game_folder,
    resolve_game_path,
)


MODE_HELP = {
    ExtractionMode.ALL_RAW: (
        "Every recognized frame, support layer, and uncategorized art record. "
        "Palette-control and shadow pixels remain visible."
    ),
    ExtractionMode.RELEVANT_RAW: (
        "Useful sprites, menus, maps, cinematics, segues, and loading screens. "
        "Skips noisy support records but keeps raw shadow/control pixels."
    ),
    ExtractionMode.RELEVANT_ART: (
        "The useful sprite and presentation-art library, cleaned for browsing. "
        "Engine controls become transparent only on world sprites; profiles, "
        "icons, effects, menus, maps, and paintings keep their full palettes."
    ),
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
        self.root.minsize(690, 570)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False

        try:
            default_game = str(resolve_game_path(None))
        except (FileNotFoundError, OSError):
            default_game = ""

        self.game_var = tk.StringVar(value=default_game)
        self.output_var = tk.StringVar(value=str(DEFAULT_OUT))
        self.mode_var = tk.StringVar(value=ExtractionMode.RELEVANT_ART.value)
        self.size_var = tk.StringVar(value="Checking source files and free space…")
        self.status_var = tk.StringVar(value="Ready")

        self._build()
        self.mode_var.trace_add("write", lambda *_args: self.refresh_estimate())
        self.output_var.trace_add("write", lambda *_args: self.refresh_estimate())
        self.game_var.trace_add("write", lambda *_args: self.refresh_estimate())
        self.root.after(100, self._poll_messages)
        self.refresh_estimate()

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        ttk.Label(outer, text="Majesty Gold HD Art Extractor", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            outer,
            text="Build a private, organized PNG art library from your own game installation.",
        ).grid(row=1, column=0, sticky="w", pady=(2, 16))

        paths = ttk.LabelFrame(outer, text="Locations", padding=12)
        paths.grid(row=2, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        ttk.Label(paths, text="Game folder").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(paths, textvariable=self.game_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(paths, text="Browse…", command=self._choose_game).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(paths, text="Extract to").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(9, 0))
        ttk.Entry(paths, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", pady=(9, 0))
        ttk.Button(paths, text="Browse…", command=self._choose_output).grid(
            row=1, column=2, padx=(8, 0), pady=(9, 0)
        )

        modes = ttk.LabelFrame(outer, text="What should be extracted?", padding=12)
        modes.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        modes.columnconfigure(0, weight=1)
        for row, mode in enumerate(ExtractionMode):
            item = ttk.Frame(modes)
            item.grid(row=row, column=0, sticky="ew", pady=(0, 9 if row < 2 else 0))
            ttk.Radiobutton(
                item,
                text=MODE_LABELS[mode],
                value=mode.value,
                variable=self.mode_var,
            ).pack(anchor="w")
            ttk.Label(item, text=MODE_HELP[mode], wraplength=610, foreground="#555555").pack(
                anchor="w", padx=(24, 0), pady=(2, 0)
            )

        estimate = ttk.Frame(outer, padding=(2, 12, 2, 8))
        estimate.grid(row=4, column=0, sticky="ew")
        ttk.Label(estimate, textvariable=self.size_var).pack(anchor="w")

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=5, column=0, sticky="ew")
        ttk.Label(outer, textvariable=self.status_var).grid(row=6, column=0, sticky="w", pady=(5, 4))

        log_frame = ttk.Frame(outer)
        log_frame.grid(row=7, column=0, sticky="nsew")
        outer.rowconfigure(7, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=7, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(outer)
        actions.grid(row=8, column=0, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Close", command=self._close).pack(side="left", padx=(0, 8))
        self.extract_button = ttk.Button(actions, text="Extract", command=self._start_extract)
        self.extract_button.pack(side="left")

    def _choose_game(self) -> None:
        chosen = filedialog.askdirectory(title="Select the Majesty HD game folder", initialdir=self.game_var.get() or None)
        if chosen:
            self.game_var.set(chosen)

    def _choose_output(self) -> None:
        chosen = filedialog.askdirectory(title="Select the output folder", initialdir=self.output_var.get() or None)
        if chosen:
            self.output_var.set(chosen)

    def refresh_estimate(self) -> None:
        try:
            game = Path(self.game_var.get())
            output = Path(self.output_var.get())
            if not is_game_folder(game):
                self.size_var.set("Select a valid Majesty HD game folder to calculate space.")
                return
            estimate = estimate_output_size(game, self.mode_var.get())
            existing = output
            while not existing.exists() and existing != existing.parent:
                existing = existing.parent
            free = shutil.disk_usage(existing).free
            enough = "enough free space" if free >= estimate else "NOT enough free space"
            self.size_var.set(
                f"Estimated output: up to {format_bytes(estimate)}  •  "
                f"Free: {format_bytes(free)} ({enough})"
            )
        except (OSError, ValueError):
            self.size_var.set("Space estimate unavailable for the selected location.")

    def _start_extract(self) -> None:
        if self.running:
            return
        game = Path(self.game_var.get())
        output = Path(self.output_var.get())
        if not is_game_folder(game):
            messagebox.showerror("Game folder not found", "Select the Majesty HD folder containing Data\\maindata.cam.")
            return
        if not self.output_var.get().strip():
            messagebox.showerror("Output folder required", "Select where the extracted art should be written.")
            return
        if output.exists() and any(output.iterdir()):
            if not messagebox.askyesno(
                "Replace existing extraction?",
                f"The extractor will replace the contents of:\n\n{output}\n\nContinue?",
            ):
                return

        self.running = True
        self.extract_button.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Extracting…")
        self._append_log("\nStarting extraction…\n")
        mode = ExtractionMode(self.mode_var.get())
        threading.Thread(target=self._extract_worker, args=(game, output, mode), daemon=True).start()

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
                    self.status_var.set(f"Complete — {total} PNG files")
                    messagebox.showinfo("Extraction complete", f"Wrote {total} PNG files to:\n\n{output}")
                elif kind == "error":
                    self._finish()
                    self.status_var.set("Extraction failed")
                    messagebox.showerror("Extraction failed", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    def _finish(self) -> None:
        self.running = False
        self.progress.stop()
        self.extract_button.configure(state="normal")
        self.refresh_estimate()

    def _close(self) -> None:
        if self.running and not messagebox.askyesno(
            "Extraction is still running",
            "Closing now will interrupt the extraction and leave partial output. Close anyway?",
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
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    ExtractorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
