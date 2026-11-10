"""THAW Super DX window: pick your THAW disc, pick each game to take levels from, shrink or not, build.

    python -m thaw_sandbox            (or: python -m thaw_sandbox gui)

Tkinter only (ships with Python). The build runs in a worker thread; its log lines are shown in the window.
Last used paths are remembered in ~/.config/thaw-super-dx/gui.json.
"""
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from thaw_sandbox import build as B, cli, sources

TITLE = "THAW Super DX"
SETTINGS = os.path.expanduser("~/.config/thaw-super-dx/gui.json")
DISC_TYPES = [("PS2 disc images", "*.iso *.ISO *.chd *.CHD"), ("All files", "*")]
ISO_TYPES = [("ISO image", "*.iso"), ("All files", "*")]


def _load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(d):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w") as f:
            json.dump(d, f, indent=1)
    except Exception:
        pass


def check_disc(path, game=None, work=cli.WORK):
    """-> (ok, message). game: adapter module the row expects, None for THAW."""
    if not os.path.isfile(path):
        return False, "file not found"
    if path.lower().endswith(".chd"):
        return True, "CHD: checked when the build extracts it"
    if game is None:
        return (True, "Tony Hawk's American Wasteland") if B.is_thaw(path) else \
            (False, "not Tony Hawk's American Wasteland (NTSC-U, SLUS-21295)")
    if not game.detect(path):
        other = next((a.GAME for a in sources.ADAPTERS if a is not game and a.detect(path)), None)
        if B.is_thaw(path):
            other = "THAW"
        return False, f"not a {game.GAME} disc" + (f" (this is {other})" if other else "")
    try:
        n = len(game.Source(path, os.path.join(work, "cache")).levels())
    except Exception as e:
        return False, f"could not read the disc ({e})"
    return True, f"{game.GAME}: {n} levels"


class _Writer:
    """stdout replacement for the worker thread: lines go to the window."""

    def __init__(self, q):
        self.q, self.buf = q, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.q.put(("log", line))

    def flush(self):
        pass


class DiscRow:
    def __init__(self, parent, row, label, game, var_path, on_change):
        self.game, self.path = game, var_path
        self.status = tk.StringVar(value="")
        ttk.Label(parent, text=label, width=24).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        e = ttk.Entry(parent, textvariable=var_path)
        e.grid(row=row, column=1, sticky="ew", pady=3)
        e.bind("<FocusOut>", lambda _e: on_change(self))
        e.bind("<Return>", lambda _e: on_change(self))
        ttk.Button(parent, text="Browse…", command=self.browse).grid(row=row, column=2, padx=(6, 0))
        if game is not None:
            ttk.Button(parent, text="Clear", command=self.clear).grid(row=row, column=3, padx=(4, 0))
        self.lbl = ttk.Label(parent, textvariable=self.status, foreground="gray")
        self.lbl.grid(row=row + 1, column=1, columnspan=3, sticky="w")
        self.on_change = on_change
        self.ok = None

    def browse(self):
        start = os.path.dirname(self.path.get()) or os.path.expanduser("~")
        p = filedialog.askopenfilename(title=f"Choose your {self.game.GAME if self.game else 'THAW'} disc",
                                       initialdir=start, filetypes=DISC_TYPES)
        if p:
            self.path.set(p)
            self.on_change(self)

    def clear(self):
        self.path.set("")
        self.on_change(self)

    def show(self, ok, msg):
        self.ok = ok
        self.status.set(("✔ " if ok else "✖ ") + msg if msg else "")
        self.lbl.configure(foreground="#2a7a2a" if ok else ("#b02020" if ok is False else "gray"))


class App:
    def __init__(self, root):
        self.root, self.q, self.busy = root, queue.Queue(), False
        root.title(TITLE)
        root.minsize(720, 560)
        st = _load_settings()
        f = ttk.Frame(root, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text=TITLE, font=("TkDefaultFont", 15, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(f, text="Adds levels from your other Tony Hawk discs to American Wasteland's free skate. "
                         "Your discs are only read; the result is a new image.",
                  wraplength=680, foreground="gray").grid(row=1, column=0, sticky="w", pady=(0, 10))

        d = ttk.LabelFrame(f, text="Your discs", padding=10)
        d.grid(row=2, column=0, sticky="ew")
        d.columnconfigure(1, weight=1)
        self.thaw = tk.StringVar(value=st.get("thaw", ""))
        self.rows = [DiscRow(d, 0, "American Wasteland (required)", None, self.thaw, self.check)]
        self.src = {}
        names = {"THUG2": "Underground 2", "THUG": "Underground", "THPS4": "Pro Skater 4"}
        for i, a in enumerate(sources.ADAPTERS):
            v = tk.StringVar(value=st.get("sources", {}).get(a.GAME, ""))
            self.src[a.GAME] = v
            self.rows.append(DiscRow(d, 2 + 2 * i, f"{names.get(a.GAME, a.GAME)} ({a.GAME})", a, v, self.check))
        ttk.Label(d, text="Leave a game empty to skip it. When two games have the same level, only the newest "
                          "version is added.", foreground="gray", wraplength=660).grid(
            row=2 + 2 * len(sources.ADAPTERS), column=0, columnspan=4, sticky="w", pady=(6, 0))

        o = ttk.LabelFrame(f, text="Options", padding=10)
        o.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        o.columnconfigure(1, weight=1)
        self.shrink = tk.BooleanVar(value=st.get("shrink", True))
        ttk.Checkbutton(o, text="Shrink the image", variable=self.shrink).grid(row=0, column=0, columnspan=4,
                                                                                sticky="w")
        ttk.Label(o, text="Removes story mode, classic mode, create-a-skater, movies and cutscenes "
                          "(about 1.9 GB instead of 4 GB). THAW's own levels stay.",
                  foreground="gray", wraplength=660).grid(row=1, column=0, columnspan=4, sticky="w",
                                                          padx=(24, 0))
        self.package = tk.BooleanVar(value=st.get("package", False))
        ttk.Checkbutton(o, text="Also make an emulator-ready folder (image + PCSX2 launcher + notes)",
                        variable=self.package).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(o, text="Save as", width=10).grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.out = tk.StringVar(value=st.get("out", os.path.expanduser("~/THAW Super DX.iso")))
        ttk.Entry(o, textvariable=self.out).grid(row=3, column=1, sticky="ew", pady=(10, 0))
        ttk.Button(o, text="Choose…", command=self.choose_out).grid(row=3, column=2, padx=(6, 0), pady=(10, 0))

        b = ttk.Frame(f)
        b.grid(row=4, column=0, sticky="ew", pady=(12, 4))
        b.columnconfigure(1, weight=1)
        self.go = ttk.Button(b, text="Build", command=self.start)
        self.go.grid(row=0, column=0)
        self.bar = ttk.Progressbar(b, mode="determinate")
        self.bar.grid(row=0, column=1, sticky="ew", padx=10)
        self.state = tk.StringVar(value="Pick your discs, then Build.")
        ttk.Label(f, textvariable=self.state).grid(row=5, column=0, sticky="w")

        lf = ttk.Frame(f)
        lf.grid(row=6, column=0, sticky="nsew", pady=(6, 0))
        f.rowconfigure(6, weight=1)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.log = tk.Text(lf, height=10, wrap="word", state="disabled", font=("TkFixedFont", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

        for r in self.rows:
            if r.path.get():
                self.check(r)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    # ---- disc checks (in a thread: reading a disc's level list can take a moment) ----
    def check(self, row):
        p = row.path.get().strip()
        if not p:
            row.show(None, "")
            return
        row.show(None, "checking…")
        threading.Thread(target=lambda: self.q.put(("check", (row, *check_disc(p, row.game)))),
                         daemon=True).start()

    def choose_out(self):
        cur = self.out.get()
        p = filedialog.asksaveasfilename(title="Save the new image as", defaultextension=".iso",
                                         initialdir=os.path.dirname(cur) or os.path.expanduser("~"),
                                         initialfile=os.path.basename(cur) or "THAW Super DX.iso",
                                         filetypes=ISO_TYPES)
        if p:
            self.out.set(p)

    def settings(self):
        return {"thaw": self.thaw.get(), "sources": {k: v.get() for k, v in self.src.items()},
                "shrink": self.shrink.get(), "package": self.package.get(), "out": self.out.get()}

    # ---- build ----
    def problems(self):
        thaw, out = self.thaw.get().strip(), self.out.get().strip()
        chosen = [v.get().strip() for v in self.src.values() if v.get().strip()]
        if not thaw:
            return "Choose your American Wasteland disc."
        if not chosen:
            return "Choose at least one game to take levels from."
        bad = [r for r in self.rows if r.path.get().strip() and r.ok is False]
        if bad:
            return f"{bad[0].status.get()[2:]}: {bad[0].path.get()}"
        if not out:
            return "Choose where to save the new image."
        absd = {os.path.abspath(p) for p in chosen + [thaw]}
        if os.path.abspath(out) in absd:
            return "The new image must not overwrite one of your discs."
        if not os.path.isdir(os.path.dirname(os.path.abspath(out))):
            return "The folder to save into does not exist."
        return None

    def start(self):
        if self.busy:
            return
        p = self.problems()
        if p:
            messagebox.showerror(TITLE, p)
            return
        out = self.out.get().strip()
        if os.path.exists(out) and not messagebox.askyesno(TITLE, f"{out} exists. Replace it?"):
            return
        _save_settings(self.settings())
        wanted = [(v.get().strip(), None) for v in self.src.values() if v.get().strip()]
        pkg = os.path.splitext(out)[0] if self.package.get() else None
        self.busy, self.done_levels, self.total = True, 0, None
        self.go.configure(state="disabled")
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.state.set("Building…")
        args = (self.thaw.get().strip(), wanted, out, cli.WORK, self.shrink.get(), pkg)
        threading.Thread(target=self.worker, args=args, daemon=True).start()

    def worker(self, *args):
        old = sys.stdout
        sys.stdout = _Writer(self.q)
        try:
            added = cli.run_build(*args)
            self.q.put(("done", (args[2], added, args[5])))
        except Exception as e:
            self.q.put(("fail", e))
        finally:
            sys.stdout = old

    def poll(self):
        try:
            while True:
                kind, x = self.q.get_nowait()
                getattr(self, "on_" + kind)(x)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def on_check(self, x):
        row, ok, msg = x
        row.show(ok, msg)

    def on_log(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        s = line.strip()
        if s.startswith("copying THAW"):
            self.state.set("Copying American Wasteland…")
        elif s.endswith("converting ..."):
            self.done_levels += 1
            self.state.set(f"Level {self.done_levels}: {s[:-len(': converting ...')]}")
        elif s.startswith("shrinking"):
            self.state.set("Shrinking the image…")
        elif s.startswith("extracting"):
            self.state.set(s)

    def finish(self):
        self.busy = False
        self.bar.stop()
        self.bar.configure(mode="determinate", value=0)
        self.go.configure(state="normal")

    def on_done(self, x):
        out, added, pkg = x
        self.finish()
        self.bar.configure(value=100)
        self.state.set(f"Done: {len(added)} levels added.")
        msg = f"{len(added)} levels added.\n\nNew image:\n{out}"
        if pkg:
            msg += f"\n\nEmulator-ready folder:\n{pkg}"
        messagebox.showinfo(TITLE, msg)

    def on_fail(self, e):
        self.finish()
        self.state.set("Build failed.")
        self.on_log(f"error: {e}")
        messagebox.showerror(TITLE, f"The build failed:\n\n{e}")

    def close(self):
        if self.busy and not messagebox.askyesno(TITLE, "A build is running. Stop it and quit?"):
            return
        _save_settings(self.settings())
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
