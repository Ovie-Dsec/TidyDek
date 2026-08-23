"""Main window shell (View layer).

Rules obeyed here:
- Renders ONLY what is in ViewModel snapshots; re-rendering is idempotent
  (a change-key short-circuits redundant widget churn).
- Zero business logic: every user intent delegates to the ViewModel.
- Never imports ``src.core`` directly (architecture test enforces this).
"""

from __future__ import annotations

import tkinter.filedialog as filedialog
from typing import Any, Mapping

import customtkinter as ctk

from src.viewmodels.app_viewmodel import AppViewModel


class MainWindow(ctk.CTk):
    """Reactive CustomTkinter shell bound to an :class:`AppViewModel`.

    ``taskbar`` is an optional duck-typed capability (start_indeterminate /
    clear) injected by the composition root, so this View never imports the
    integrations layer directly.
    """

    def __init__(self, view_model: AppViewModel, taskbar=None) -> None:
        super().__init__()
        self._vm = view_model
        self._taskbar = taskbar
        self._unsub = view_model.subscribe(self._on_state_changed)

        self.title("TidyDek")
        self.geometry("820x540")
        self.minsize(640, 420)

        self._root_var = ctk.StringVar(value="")
        self._status_var = ctk.StringVar(value="")
        self._index_by_name: dict[str, int] = {}
        self._rendered: tuple[Any, ...] | None = None

        # Phase 13: queue polling (UI thread only); taskbar via injection.
        self._poll_job: str | None = None
        self._taskbar_active = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        toolbar.grid_columnconfigure(1, weight=1)

        self._open_btn = ctk.CTkButton(
            toolbar, text="Open Folder...", width=130, command=self._choose_folder
        )
        self._open_btn.grid(row=0, column=0, padx=(0, 8))

        ctk.CTkEntry(toolbar, textvariable=self._root_var).grid(
            row=0, column=1, sticky="ew"
        )

        self._file_picker = ctk.CTkComboBox(
            self, values=[], command=self._on_pick_file, width=340, state="readonly"
        )
        self._file_picker.set("")
        self._file_picker.grid(row=1, column=0, sticky="ew", padx=12, pady=4)

        self._progress_bar = ctk.CTkProgressBar(self, mode="indeterminate")
        self._progress_bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 2))

        self._preview = ctk.CTkTextbox(self, wrap="none")
        self._preview.configure(state="disabled")
        self._preview.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)

        # Phase 19.2 FRE placeholder: occupies the preview cell until the
        # first successful scan dismisses it. Purely presentational.
        self._welcome_label = ctk.CTkLabel(
            self,
            text=("Welcome to TidyDek\n\n"
                  "Click \"Open Folder...\" above to scan and tidy a folder."),
            justify="center",
        )
        self._welcome_label.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        self._welcome_label.grid_remove()

        self._status_label = ctk.CTkLabel(
            self, textvariable=self._status_var, anchor="w"
        )
        self._status_label.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 10))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initial paint straight from the ViewModel snapshot.
        self._render(view_model.snapshot())

    # ---- reactions -------------------------------------------------------
    def _on_state_changed(
        self, snapshot: Mapping[str, Any], changed: tuple[str, ...]
    ) -> None:
        self._render(dict(snapshot))

    def _render(self, s: dict[str, Any]) -> None:
        key = (
            s["root"],
            s["status"],
            s["busy"],
            tuple(f["path"] for f in s["files"]),
            s["selected_index"],
            s["preview_text"],
            s.get("first_run", False),
        )
        if key == self._rendered:
            return
        self._rendered = key

        self._root_var.set(s["root"] or "")
        self._status_var.set(s["status"])
        self._open_btn.configure(state="disabled" if s["busy"] else "normal")

        counts: dict[str, int] = {}
        display: list[str] = []
        for i, f in enumerate(s["files"]):
            name = f["name"]
            seen = counts.get(name, 0)
            label = name if seen == 0 else f"{name} ({seen + 1})"
            counts[name] = seen + 1
            display.append(label)
            self._index_by_name[label] = i

        if tuple(display) != tuple(self._file_picker.cget("values")):
            self._file_picker.configure(values=display)

        desired = next(
            (
                label
                for label, idx in self._index_by_name.items()
                if idx == s["selected_index"]
            ),
            "",
        )
        if self._file_picker.get() != desired:
            self._file_picker.set(desired)

        self._preview.configure(state="normal")
        self._preview.delete("1.0", "end")
        self._preview.insert("1.0", s["preview_text"])
        self._preview.configure(state="disabled")

        # FRE visibility (Phase 19.2): welcome label replaces the preview
        # pane until the first successful scan completes.
        fre = bool(s.get("first_run"))
        if fre:
            self._preview.grid_remove()
            self._welcome_label.grid()
        else:
            self._welcome_label.grid_remove()
            self._preview.grid()

    # ---- intents -----------------------------------------------------------
    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Choose a folder")
        if folder and self._vm.open_folder(folder):
            self._ensure_polling()

    def attach_taskbar(self, taskbar) -> None:
        """Composition-root injection point for the taskbar capability."""
        self._taskbar = taskbar

    def _ensure_polling(self) -> None:
        """Start the 50ms queue-drain timer (idempotent)."""
        if self._poll_job is None:
            self._run_poll()

    def _run_poll(self) -> None:
        had_events = self._vm.drain_scan_progress()
        busy = bool(self._vm.snapshot().get("busy"))

        if busy and not self._taskbar_active:
            self._progress_bar.start()
            if self._taskbar is not None:
                self._taskbar.start_indeterminate()
            self._taskbar_active = True
        elif not busy and self._taskbar_active:
            self._progress_bar.stop()
            self._progress_bar.set(0)
            if self._taskbar is not None:
                self._taskbar.clear()
            self._taskbar_active = False

        if busy or had_events:
            self._poll_job = self.after(50, self._run_poll)
        else:
            self._poll_job = None

    def _on_pick_file(self, label: str) -> None:
        index = self._index_by_name.get(label)
        if index is not None:
            self._vm.preview_selected(index)

    def _on_close(self) -> None:
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        self._unsub()
        self.destroy()
