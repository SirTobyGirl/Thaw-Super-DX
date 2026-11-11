"""THAW Super DX window: pick your THAW disc and each game to take levels from, choose levels, options, build.

    python -m thaw_sandbox            (or: python -m thaw_sandbox gui, ./thaw-super-dx.sh)

Tkinter only (ships with Python). Disc checks and the build run in worker threads; build log lines are shown in
the window. Last used discs, level choices and options are remembered in ~/.config/thaw-super-dx/gui.json.
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
GAME_NAMES = {"THUG2": "Underground 2", "THUG": "Underground", "THPS4": "Pro Skater 4"}
GREY, GOOD, BAD = "gray", "#2a7a2a", "#b02020"


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


def check_disc(path, game=None, work=cli.WORK, progress=lambda s: None):
    """-> (ok, message, source or None). game: the adapter module the row expects, None for THAW.
    A .chd is extracted here (once; the build reuses it)."""
    if not os.path.isfile(path):
        return False, "file not found", None
    if path.lower().endswith(".chd"):
        progress("extracting the CHD image (first time only, a few minutes)…")
        try:
            path = B.disc_image(path, work)
        except Exception as e:
            return False, f"could not extract ({e})", None
    if game is None:
        return ((True, "Tony Hawk's American Wasteland", None) if B.is_thaw(path) else
                (False, "not Tony Hawk's American Wasteland (NTSC-U, SLUS-21295)", None))
    if not game.detect(path):
        other = next((a.GAME for a in sources.ADAPTERS if a is not game and a.detect(path)), None)
        if B.is_thaw(path):
            other = "THAW"
        return False, f"not a {game.GAME} disc" + (f" (this is {other})" if other else ""), None
    try:
        src = game.Source(path, os.path.join(work, "cache"))
        src.levels()
    except Exception as e:
        return False, f"could not read the disc ({e})", None
    return True, game.GAME, src


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
    def __init__(self, app, parent, row, label, game, var_path, selected=None):
        self.app, self.game, self.path = app, game, var_path
        self.source, self.ok, self.msg = None, None, ""
        self.selected = set(selected) if selected is not None else None  # level codes; None = all
        self.status = tk.StringVar(value="")
        ttk.Label(parent, text=label, width=26).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(4, 0))
        e = ttk.Entry(parent, textvariable=var_path)
        e.grid(row=row, column=1, sticky="ew", pady=(4, 0))
        e.bind("<FocusOut>", lambda _e: self.changed())
        e.bind("<Return>", lambda _e: self.changed())
        ttk.Button(parent, text="Browse…", command=self.browse).grid(row=row, column=2, padx=(6, 0), pady=(4, 0))
        if game is not None:
            self.lv = ttk.Button(parent, text="Levels…", command=self.pick_levels, state="disabled")
            self.lv.grid(row=row, column=3, padx=(4, 0), pady=(4, 0))
            ttk.Button(parent, text="Clear", command=self.clear).grid(row=row, column=4, padx=(4, 0), pady=(4, 0))
        self.lbl = ttk.Label(parent, textvariable=self.status, foreground=GREY)
        self.lbl.grid(row=row + 1, column=1, columnspan=4, sticky="w")
        self.checked_path = None

    # ---- state ----
    def levels(self):
        return self.source.levels() if self.source else []

    def chosen(self):
        """[codes] to build, [] for nothing (empty row or no level ticked)."""
        if not self.path.get().strip() or not self.source:
            return []
        codes = [c for c, _ in self.levels()]
        return codes if self.selected is None else [c for c in codes if c in self.selected]

    def refresh(self):
        if self.ok is None:
            self.status.set(self.msg)
            self.lbl.configure(foreground=GREY)
            return
        text = ("✔ " if self.ok else "✖ ") + self.msg
        if self.ok and self.source:
            n, k = len(self.levels()), len(self.chosen())
            text += f": {k} of {n} levels chosen" if k != n else f": all {n} levels"
        self.status.set(text)
        self.lbl.configure(foreground=GOOD if self.ok else BAD)
        if self.game is not None:
            self.lv.configure(state="normal" if self.source else "disabled")

    # ---- actions ----
    def changed(self):
        p = self.path.get().strip()
        if p == self.checked_path:
            return
        self.checked_path, self.source = p, None
        if self.game is not None:
            self.lv.configure(state="disabled")
        if not p:
            self.ok, self.msg = None, ""
            self.refresh()
            return
        self.ok, self.msg = None, "checking…"
        self.refresh()
        q = self.app.q

        def work():
            res = check_disc(p, self.game, progress=lambda s: q.put(("progress", (self, s))))
            q.put(("check", (self, p, res)))
        threading.Thread(target=work, daemon=True).start()

    def checked(self, p, res):
        if p != self.path.get().strip():
            return  # the path changed while checking
        self.ok, self.msg, self.source = res
        if self.source and self.selected is not None:
            self.selected &= {c for c, _ in self.levels()}
        self.refresh()

    def browse(self):
        start = os.path.dirname(self.path.get()) or os.path.expanduser("~")
        p = filedialog.askopenfilename(title=f"Choose your {self.game.GAME if self.game else 'American Wasteland'} disc",
                                       initialdir=start, filetypes=DISC_TYPES)
        if p:
            self.path.set(p)
            self.selected = None
            self.changed()

    def clear(self):
        self.path.set("")
        self.selected = None
        self.changed()

    def pick_levels(self):
        if self.source:
            LevelDialog(self.app, self)


class LevelDialog:
    """Tick the levels to add from one disc."""

    def __init__(self, app, row):
        self.app, self.row = app, row
        t = self.top = tk.Toplevel(app.root)
        t.title(f"{GAME_NAMES.get(row.game.GAME, row.game.GAME)} ({row.game.GAME}) levels")
        t.transient(app.root)
        t.minsize(380, 300)
        f = ttk.Frame(t, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        ttk.Label(f, text="Tick the levels to add:").grid(row=0, column=0, sticky="w")
        # scrollable list
        box = ttk.Frame(f)
        box.grid(row=1, column=0, sticky="nsew", pady=6)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        canvas = tk.Canvas(box, highlightthickness=0, height=360)
        sb = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        for w in (canvas, inner):
            w.bind("<Button-4>", lambda _e: canvas.yview_scroll(-2, "units"))
            w.bind("<Button-5>", lambda _e: canvas.yview_scroll(2, "units"))
            w.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        newer = app.newer_versions(row)
        chosen = set(row.chosen())
        self.vars = {}
        for i, (code, name) in enumerate(row.levels()):
            v = tk.BooleanVar(value=code in chosen)
            self.vars[code] = v
            ttk.Checkbutton(inner, text=name, variable=v).grid(row=i, column=0, sticky="w", pady=1)
            if code in newer:
                ttk.Label(inner, text=f"the {newer[code]} version is used", foreground=GREY).grid(
                    row=i, column=1, sticky="w", padx=(12, 0))
        if newer:
            ttk.Label(f, text="A level remade by a newer game you chose is added once, from the newest game.",
                      foreground=GREY, wraplength=360).grid(row=2, column=0, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(b, text="Select all", command=lambda: self.set_all(True)).pack(side="left")
        ttk.Button(b, text="Select none", command=lambda: self.set_all(False)).pack(side="left", padx=(6, 0))
        ttk.Button(b, text="OK", command=self.ok).pack(side="right")
        ttk.Button(b, text="Cancel", command=t.destroy).pack(side="right", padx=(0, 6))
        t.bind("<Escape>", lambda _e: t.destroy())
        t.grab_set()

    def set_all(self, on):
        for v in self.vars.values():
            v.set(on)

    def ok(self):
        sel = {c for c, v in self.vars.items() if v.get()}
        self.row.selected = None if len(sel) == len(self.vars) else sel
        self.row.refresh()
        self.top.destroy()


class App:
    def __init__(self, root):
        self.root, self.q, self.busy = root, queue.Queue(), False
        root.title(TITLE)
        root.minsize(760, 640)
        st = _load_settings()
        f = ttk.Frame(root, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text=TITLE, font=("TkDefaultFont", 15, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(f, text="Adds levels from your other Tony Hawk discs to American Wasteland. "
                         "Your discs are only read; the result is a new image.",
                  wraplength=720, foreground=GREY).grid(row=1, column=0, sticky="w", pady=(0, 10))

        d = ttk.LabelFrame(f, text="Your discs", padding=10)
        d.grid(row=2, column=0, sticky="ew")
        d.columnconfigure(1, weight=1)
        self.thaw = tk.StringVar(value=st.get("thaw", ""))
        self.rows = [DiscRow(self, d, 0, "American Wasteland (required)", None, self.thaw)]
        self.src = {}
        for i, a in enumerate(sources.ADAPTERS):
            v = tk.StringVar(value=st.get("sources", {}).get(a.GAME, ""))
            self.src[a.GAME] = v
            self.rows.append(DiscRow(self, d, 2 + 2 * i, f"{GAME_NAMES.get(a.GAME, a.GAME)} ({a.GAME})", a, v,
                                     st.get("levels", {}).get(a.GAME)))
        ttk.Label(d, text="Leave a game empty to skip it. Levels… picks single levels (all by default).",
                  foreground=GREY, wraplength=700).grid(row=2 + 2 * len(sources.ADAPTERS), column=0, columnspan=5,
                                                        sticky="w", pady=(6, 0))

        g = ttk.LabelFrame(f, text="Levels from real places - EXPERIMENTAL (generated, needs internet)", padding=10)
        g.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        g.columnconfigure(1, weight=1)
        ttk.Label(g, text="Location").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.place = tk.StringVar()
        pe = ttk.Entry(g, textvariable=self.place)
        pe.grid(row=0, column=1, sticky="ew")
        pe.bind("<Return>", lambda _e: self.add_place())
        ttk.Label(g, text="Size").grid(row=0, column=2, padx=(8, 4))
        self.place_size = tk.StringVar(value="300 m")
        ttk.Combobox(g, textvariable=self.place_size, values=("200 m", "300 m", "400 m"), width=7,
                     state="readonly").grid(row=0, column=3)
        ttk.Label(g, text="Name").grid(row=0, column=4, padx=(8, 4))
        self.place_name = tk.StringVar()
        ttk.Entry(g, textvariable=self.place_name, width=14).grid(row=0, column=5)
        self.add_btn = ttk.Button(g, text="Add place", command=self.add_place)
        self.add_btn.grid(row=0, column=6, padx=(8, 0))
        self.places = [tuple(x) + (None,) * (4 - len(x)) for x in st.get("places", [])]  # (loc, size m, name, layout)
        self.place_list = tk.Listbox(g, height=3)
        self.place_list.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(6, 0))
        pb = ttk.Frame(g)
        pb.grid(row=1, column=6, sticky="n", padx=(8, 0), pady=(6, 0))
        ttk.Button(pb, text="Remove", command=self.remove_place).pack(fill="x")
        self.layout_btn = ttk.Button(pb, text="Skatepark layout…", command=self.edit_layout)
        self.layout_btn.pack(fill="x", pady=(4, 0))
        self.place_note = ttk.Label(g, foreground=GREY, wraplength=700, text=(
            "A plus code (9C6WQCGF+QP, or QCGF+QP Durham) or 'lat, lon'. Streets, buildings, steps, benches and hills "
            "come from OpenStreetMap and elevation data; textures from your American Wasteland disc."))
        self.place_note.grid(row=2, column=0, columnspan=7, sticky="w", pady=(4, 0))
        self.refresh_places()

        o = ttk.LabelFrame(f, text="Options", padding=10)
        o.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        o.columnconfigure(1, weight=1)
        self.shrink = tk.BooleanVar(value=st.get("shrink", False))
        ttk.Checkbutton(o, text="Shrink the image (free skate only)", variable=self.shrink,
                        command=self.options_changed).grid(row=0, column=0, columnspan=3, sticky="w")
        self.shrink_note = ttk.Label(o, foreground=GREY, wraplength=680)
        self.shrink_note.grid(row=1, column=0, columnspan=3, sticky="w", padx=(24, 0))
        self.unlock = tk.BooleanVar(value=st.get("unlock", True))
        self.unlock_box = ttk.Checkbutton(o, text="Unlock all levels", variable=self.unlock)
        self.unlock_box.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.unlock_note = ttk.Label(o, foreground=GREY, wraplength=680)
        self.unlock_note.grid(row=3, column=0, columnspan=3, sticky="w", padx=(24, 0))
        self.package = tk.BooleanVar(value=st.get("package", False))
        ttk.Checkbutton(o, text="Also make an emulator-ready folder (image + PCSX2 launcher + notes)",
                        variable=self.package).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(o, text="Save as", width=10).grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.out = tk.StringVar(value=st.get("out", os.path.expanduser("~/THAW Super DX.iso")))
        ttk.Entry(o, textvariable=self.out).grid(row=5, column=1, sticky="ew", pady=(10, 0))
        ttk.Button(o, text="Choose…", command=self.choose_out).grid(row=5, column=2, padx=(6, 0), pady=(10, 0))
        self.options_changed()

        b = ttk.Frame(f)
        b.grid(row=5, column=0, sticky="ew", pady=(12, 4))
        b.columnconfigure(1, weight=1)
        self.go = ttk.Button(b, text="Build", command=self.start)
        self.go.grid(row=0, column=0)
        self.bar = ttk.Progressbar(b, mode="determinate")
        self.bar.grid(row=0, column=1, sticky="ew", padx=10)
        self.state = tk.StringVar(value="Pick your discs, then Build.")
        ttk.Label(f, textvariable=self.state).grid(row=6, column=0, sticky="w")

        lf = ttk.Frame(f)
        lf.grid(row=7, column=0, sticky="nsew", pady=(6, 0))
        f.rowconfigure(7, weight=1)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.log = tk.Text(lf, height=8, wrap="word", state="disabled", font=("TkFixedFont", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

        for r in self.rows:
            r.changed()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    # ---- real places
    def refresh_places(self):
        self.place_list.delete(0, "end")
        for loc, size, name, lay in self.places:
            extra = ""
            if lay and os.path.exists(lay):
                try:
                    n = len(json.load(open(lay)).get("pieces", []))
                    extra = f"  -  skatepark layout: {n} pieces"
                except Exception:
                    extra = "  -  skatepark layout (unreadable)"
            self.place_list.insert("end", f"{name}  -  {loc}  ({size} m square){extra}")

    def add_place(self):
        loc = self.place.get().strip()
        if not loc or self.busy:
            return
        size = int(self.place_size.get().split()[0])
        name = self.place_name.get().strip()
        self.add_btn.configure(state="disabled")
        self.place_note.configure(text="Checking the location…", foreground=GREY)

        def work():
            from thaw_sandbox.mapgen import fetch, real_place
            try:
                cands = fetch.candidates(loc)
                self.q.put(("place", (loc, size, name or real_place(loc)[1], cands, None)))
            except Exception as e:
                self.q.put(("place", (loc, size, name, None, e)))
        threading.Thread(target=work, daemon=True).start()

    def on_place(self, x):
        loc, size, name, cands, err = x
        self.add_btn.configure(state="normal")
        if err:
            self.place_note.configure(text=f"✖ {err}", foreground=BAD)
            return
        if len(cands) > 1:
            pick = self.choose_place(cands)
            if pick is None:
                self.place_note.configure(text="Cancelled.", foreground=GREY)
                return
            cands = [cands[pick]]
        from thaw_sandbox.mapgen import fetch
        label, lat, lon = cands[0]
        if label != loc:  # a short code: keep the full code so the place is unambiguous
            loc = f"{fetch.encode(lat, lon)}"
        self.add_resolved(loc, size, name, lat, lon)

    def choose_place(self, cands):
        """Modal list of places a short plus code may mean -> index or None."""
        t = tk.Toplevel(self.root)
        t.title("Which place?")
        t.transient(self.root)
        ttk.Label(t, text="That short plus code fits several places. Which one?", padding=10).pack(anchor="w")
        lb = tk.Listbox(t, width=80, height=min(8, len(cands)))
        for label, lat, lon in cands:
            lb.insert("end", f"{label}   ({lat:.4f}, {lon:.4f})")
        lb.pack(padx=10, fill="both", expand=True)
        lb.selection_set(0)
        res = [None]

        def ok(_e=None):
            sel = lb.curselection()
            res[0] = sel[0] if sel else None
            t.destroy()
        b = ttk.Frame(t, padding=10)
        b.pack(fill="x")
        ttk.Button(b, text="OK", command=ok).pack(side="right")
        ttk.Button(b, text="Cancel", command=t.destroy).pack(side="right", padx=6)
        lb.bind("<Double-Button-1>", ok)
        t.grab_set()
        self.root.wait_window(t)
        return res[0]

    def add_resolved(self, loc, size, name, lat, lon):
        self.places.append((loc, size, name[:20], None))
        self.refresh_places()
        self.place.set("")
        self.place_name.set("")
        self.place_note.configure(text=f"✔ Added {name} ({lat:.5f}, {lon:.5f}).", foreground=GOOD)

    def edit_layout(self):
        sel = self.place_list.curselection()
        if not sel:
            self.place_note.configure(text="Select a place in the list first.", foreground=BAD)
            return
        i = sel[0]
        loc, size, name, lay = self.places[i]
        self.place_note.configure(text=f"Loading the map of {name}…", foreground=GREY)

        def work():
            from thaw_sandbox.mapgen import fetch
            try:
                lat, lon = fetch.resolve(loc)
                data, _ = fetch.fetch(lat, lon, size / 2, os.path.join(cli.WORK, "mapdata"))
                self.q.put(("editor", (i, data, lat, lon, None)))
            except Exception as e:
                self.q.put(("editor", (i, None, None, None, e)))
        threading.Thread(target=work, daemon=True).start()

    def on_editor(self, x):
        i, data, lat, lon, err = x
        if err:
            self.place_note.configure(text=f"✖ {err}", foreground=BAD)
            return
        from thaw_sandbox import park_editor as PE
        loc, size, name, lay = self.places[i]
        ctx = PE.context(data, lat, lon)
        layout = None
        if lay and os.path.exists(lay):
            layout = json.load(open(lay))
        if lay is None:
            os.makedirs(PE.PARKS_DIR, exist_ok=True)
            lay = os.path.join(PE.PARKS_DIR, "".join(c if c.isalnum() else "_" for c in name) + ".json")

        def saved(path, i=i):
            l_, s_, n_, _ = self.places[i]
            self.places[i] = (l_, s_, n_, path)
            self.refresh_places()
            _save_settings(self.settings())
        PE.ParkEditor(self.root, name, ctx, layout, lay, saved)
        self.place_note.configure(text=("Skatepark outline from OpenStreetMap." if ctx["outline"] else
                                        "No skatepark is mapped here: pieces are placed around the location."),
                                  foreground=GREY)

    def remove_place(self):
        for i in reversed(self.place_list.curselection()):
            del self.places[i]
        self.refresh_places()

    def options_changed(self):
        if self.shrink.get():
            self.shrink_note.configure(text="Boots straight to the level list. Removes story mode, classic mode, "
                                            "movies, cutscenes and the other extras; music stays. About 1.9 GB.")
            self.unlock_box.configure(state="disabled")
            self.unlock_note.configure(text="Always on when shrinking (story mode is gone, so levels can't be "
                                            "unlocked by playing).")
        else:
            self.shrink_note.configure(text="Off: the full game, booting as normal with story mode and everything "
                                            "else. The new levels are in High Score / Free Skate.")
            self.unlock_box.configure(state="normal")
            self.unlock_note.configure(text="Every level is open in free skate from the start. Off: a level opens "
                                            "once you have visited it (the added levels are open).")

    def newer_versions(self, row):
        """{code: newer game} for levels of row that a newer chosen disc also has."""
        out = {}
        for other in self.rows[1:]:
            if other is row or not other.source or not other.chosen():
                continue
            if other.source.GENERATION <= row.source.GENERATION:
                continue
            ids = {sources.identity(other.source, c) for c in other.chosen()}
            for code, _ in row.levels():
                if sources.identity(row.source, code) in ids:
                    out[code] = other.source.GAME
        return out

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
                "levels": {r.game.GAME: (sorted(r.selected) if r.selected is not None else None)
                           for r in self.rows[1:]},
                "shrink": self.shrink.get(), "unlock": self.unlock.get(), "package": self.package.get(),
                "out": self.out.get(), "places": [list(p) for p in self.places]}

    # ---- build ----
    def problems(self):
        thaw, out = self.thaw.get().strip(), self.out.get().strip()
        if not thaw:
            return "Choose your American Wasteland disc."
        busy = [r for r in self.rows if r.path.get().strip() and r.ok is None]
        if busy:
            return "Still checking a disc; try again in a moment."
        bad = [r for r in self.rows if r.path.get().strip() and r.ok is False]
        if bad:
            return f"{bad[0].msg}:\n{bad[0].path.get()}"
        if not any(r.chosen() for r in self.rows[1:]) and not self.places:
            return "Choose at least one game (and level) to take levels from, or add a real place."
        if not out:
            return "Choose where to save the new image."
        discs = {os.path.abspath(r.path.get().strip()) for r in self.rows if r.path.get().strip()}
        if os.path.abspath(out) in discs:
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
        wanted = [(r.path.get().strip(), r.chosen()) for r in self.rows[1:] if r.chosen()]
        pkg = os.path.splitext(out)[0] if self.package.get() else None
        self.busy, self.done_levels = True, 0
        self.total = sum(len(c) for _, c in wanted)
        self.go.configure(state="disabled")
        self.bar.configure(mode="determinate", maximum=self.total + 2, value=0)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.state.set("Building…")
        shrink = self.shrink.get()
        from thaw_sandbox.mapgen import real_place
        gen = [real_place(loc, size / 2, name, cli.WORK, lay if lay and os.path.exists(lay) else None)
               for loc, size, name, lay in self.places]
        self.total += len(gen)
        self.bar.configure(maximum=self.total + 2)
        args = (self.thaw.get().strip(), wanted, out, cli.WORK, shrink, pkg, False, True,
                self.unlock.get() or shrink, gen)
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
        row, p, res = x
        row.checked(p, res)

    def on_progress(self, x):
        row, s = x
        row.msg = s
        row.refresh()

    def on_log(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        s = line.strip()
        if s.startswith("copying THAW"):
            self.state.set("Copying American Wasteland…")
            self.bar.configure(value=1)
        elif s.endswith("converting ..."):
            self.done_levels += 1
            self.state.set(f"Level {self.done_levels} of {self.total}: {s[:-len(': converting ...')]}")
            self.bar.configure(value=1 + self.done_levels)
        elif s.startswith("shrinking"):
            self.state.set("Shrinking the image…")
        elif s.startswith("extracting") or s.startswith("downloading"):
            self.state.set(s[:1].upper() + s[1:])

    def finish(self):
        self.busy = False
        self.go.configure(state="normal")

    def on_done(self, x):
        out, added, pkg = x
        self.finish()
        self.bar.configure(value=self.bar.cget("maximum"))
        self.state.set(f"Done: {len(added)} levels added.")
        msg = f"{len(added)} levels added.\n\nNew image:\n{out}"
        if pkg:
            msg += f"\n\nEmulator-ready folder:\n{pkg}"
        messagebox.showinfo(TITLE, msg)

    def on_fail(self, e):
        self.finish()
        self.bar.configure(value=0)
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
