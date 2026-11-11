"""Skatepark layout editor (Tk): place ramps on the real skatepark's outline, top-down, to scale.

The outline, nearby buildings and paths come from the place's OpenStreetMap data. Pieces are stored in metres
around the park centre (see mapgen/park.py); the layout is saved as JSON and used when the place is built.
Controls: Add buttons; click a piece to select; drag to move; Q / E or the mouse wheel rotate (15 degrees, with
Shift 5); Delete removes; the side panel edits position, angle and sizes.
"""
import json
import math
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from thaw_sandbox.mapgen import park as PK

COLOURS = {"quarter_pipe": "#c98b4a", "bank": "#d8b46a", "box": "#8f8f8f", "rail": "#3d6fb6", "stairs": "#a0785a",
           "pyramid": "#c9a35a", "mini_ramp": "#b77a3e", "bowl": "#6b9fc9"}
PARKS_DIR = os.path.expanduser("~/.config/thaw-super-dx/parks")


class ParkEditor:
    def __init__(self, master, title, context, layout=None, path=None, on_save=None):
        """context: {"outline": [(e, n)] or None, "buildings": [[(e, n)]], "paths": [[(e, n)]]} in metres around
        the park centre."""
        self.ctx, self.on_save, self.path = context, on_save, path
        self.layout = layout or {"name": title, "pieces": []}
        self.sel = None
        t = self.top = tk.Toplevel(master)
        t.title(f"Skatepark layout - {title}")
        t.geometry("1100x760")
        bar = ttk.Frame(t, padding=6)
        bar.pack(side="left", fill="y")
        ttk.Label(bar, text="Add", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        for typ, label in PK.LABELS.items():
            ttk.Button(bar, text=label, command=lambda k=typ: self.add(k)).pack(fill="x", pady=1)
        ttk.Separator(bar).pack(fill="x", pady=8)
        ttk.Button(bar, text="Save", command=self.save).pack(fill="x", pady=1)
        ttk.Button(bar, text="Save as…", command=lambda: self.save(ask=True)).pack(fill="x", pady=1)
        ttk.Button(bar, text="Open…", command=self.open).pack(fill="x", pady=1)
        ttk.Button(bar, text="Clear all", command=self.clear).pack(fill="x", pady=1)
        ttk.Label(bar, text="Drag to move\nQ / E or wheel: rotate\n(Shift: 5°)\nDelete: remove", foreground="gray",
                  justify="left").pack(anchor="w", pady=(12, 0))
        self.side = ttk.Frame(t, padding=8, width=230)
        self.side.pack(side="right", fill="y")
        self.side.pack_propagate(False)
        self.cv = tk.Canvas(t, background="#e9e6df", highlightthickness=0)
        self.cv.pack(side="left", fill="both", expand=True)
        self.status = tk.StringVar()
        ttk.Label(t, textvariable=self.status).place(relx=0.0, rely=1.0, anchor="sw", x=200, y=-4)
        self.cv.bind("<Configure>", lambda _e: self.fit())
        self.cv.bind("<Button-1>", self.press)
        self.cv.bind("<B1-Motion>", self.drag)
        self.cv.bind("<MouseWheel>", lambda e: self.rotate(-15 if e.delta > 0 else 15, e))
        self.cv.bind("<Button-4>", lambda e: self.rotate(-15, e))
        self.cv.bind("<Button-5>", lambda e: self.rotate(15, e))
        for k, a in (("q", -15), ("e", 15), ("Q", -5), ("E", 5)):
            t.bind(f"<KeyPress-{k}>", lambda e, a=a: self.rotate(a))
        t.bind("<Delete>", lambda _e: self.delete())
        t.bind("<BackSpace>", lambda _e: self.delete())
        self.fields = {}
        self.show_props()

    # ---- view
    def fit(self):
        pts = list(self.ctx.get("outline") or [(-30, -30), (30, 30)])
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(10, self.cv.winfo_width()), max(10, self.cv.winfo_height())
        span = max(max(xs) - min(xs), max(ys) - min(ys)) + 20
        self.scale = min(w, h) / span
        self.cx, self.cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self.draw()

    def P(self, e, n):
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        return w / 2 + (e - self.cx) * self.scale, h / 2 - (n - self.cy) * self.scale

    def M(self, x, y):
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        return (x - w / 2) / self.scale + self.cx, -(y - h / 2) / self.scale + self.cy

    def draw(self):
        cv = self.cv
        cv.delete("all")
        lo = self.M(0, cv.winfo_height())
        hi = self.M(cv.winfo_width(), 0)
        g = 5
        for e in range(int(lo[0] // g) * g, int(hi[0]) + g, g):
            cv.create_line(*self.P(e, lo[1]), *self.P(e, hi[1]), fill="#d9d5cc")
        for n in range(int(lo[1] // g) * g, int(hi[1]) + g, g):
            cv.create_line(*self.P(lo[0], n), *self.P(hi[0], n), fill="#d9d5cc")
        for path in self.ctx.get("paths", []):
            if len(path) > 1:
                cv.create_line(*[c for p in path for c in self.P(*p)], fill="#b8b2a6", width=max(2, 2 * self.scale))
        for b in self.ctx.get("buildings", []):
            cv.create_polygon(*[c for p in b for c in self.P(*p)], fill="#b59a86", outline="#7d6656")
        if self.ctx.get("outline"):
            cv.create_polygon(*[c for p in self.ctx["outline"] for c in self.P(*p)], fill="#cfd8c4",
                              outline="#4d7a3a", width=2)
        for i, p in enumerate(self.layout["pieces"]):
            fp = PK.footprint(p)
            cv.create_polygon(*[c for q in fp for c in self.P(*q)], fill=COLOURS[p["type"]],
                              outline="#d02020" if i == self.sel else "#333", width=3 if i == self.sel else 1,
                              tags=(f"p{i}",))
            a = math.radians(p.get("rot", 0))
            L = 1.5
            x0, y0 = self.P(p["x"], p["y"])
            x1, y1 = self.P(p["x"] + math.sin(a) * L, p["y"] + math.cos(a) * L)
            cv.create_line(x0, y0, x1, y1, arrow="last", width=2, fill="#222")
        x, y = 30, 40
        cv.create_line(x, y + 18, x, y - 12, arrow="last", width=2)
        cv.create_text(x, y + 28, text="N")
        bar = 10 * self.scale
        cv.create_line(20, cv.winfo_height() - 30, 20 + bar, cv.winfo_height() - 30, width=3)
        cv.create_text(20 + bar / 2, cv.winfo_height() - 18, text="10 m")
        n = len(self.layout["pieces"])
        self.status.set(f"{n} piece{'s' if n != 1 else ''}" + ("" if self.ctx.get("outline") else
                        "  -  no skatepark mapped here: pieces go around the location"))

    # ---- editing
    def add(self, typ):
        e, n = self.cx, self.cy
        p = {"type": typ, "x": round(e, 2), "y": round(n, 2), "rot": 0.0, **PK.PIECES[typ]}
        self.layout["pieces"].append(p)
        self.sel = len(self.layout["pieces"]) - 1
        self.draw()
        self.show_props()

    def press(self, ev):
        self.top.focus_set()
        hit = None
        for item in reversed(self.cv.find_overlapping(ev.x - 2, ev.y - 2, ev.x + 2, ev.y + 2)):
            tags = [t for t in self.cv.gettags(item) if t.startswith("p")]
            if tags:
                hit = int(tags[0][1:])
                break
        self.sel = hit
        if hit is not None:
            p = self.layout["pieces"][hit]
            m = self.M(ev.x, ev.y)
            self.grab = (m[0] - p["x"], m[1] - p["y"])
        self.draw()
        self.show_props()

    def drag(self, ev):
        if self.sel is None:
            return
        p = self.layout["pieces"][self.sel]
        m = self.M(ev.x, ev.y)
        p["x"], p["y"] = round(m[0] - self.grab[0], 2), round(m[1] - self.grab[1], 2)
        self.draw()
        self.show_props()

    def rotate(self, deg, ev=None):
        if self.sel is None:
            return
        if ev is not None and ev.state & 1:
            deg = 5 if deg > 0 else -5
        p = self.layout["pieces"][self.sel]
        p["rot"] = (p.get("rot", 0) + deg) % 360
        self.draw()
        self.show_props()

    def delete(self):
        if self.sel is None:
            return
        del self.layout["pieces"][self.sel]
        self.sel = None
        self.draw()
        self.show_props()

    def clear(self):
        if self.layout["pieces"] and messagebox.askyesno("Skatepark layout", "Remove every piece?", parent=self.top):
            self.layout["pieces"] = []
            self.sel = None
            self.draw()
            self.show_props()

    def show_props(self):
        for w in self.side.winfo_children():
            w.destroy()
        self.fields = {}
        if self.sel is None:
            ttk.Label(self.side, text="Select a piece to edit it, or add one.", wraplength=200,
                      foreground="gray").pack(anchor="w")
            return
        p = self.layout["pieces"][self.sel]
        ttk.Label(self.side, text=PK.LABELS[p["type"]], font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        names = {"x": "East (m)", "y": "North (m)", "rot": "Facing (° from N)"}
        for k in ["x", "y", "rot"] + list(PK.PIECES[p["type"]]):
            f = ttk.Frame(self.side)
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=names.get(k, k.capitalize() + (" (m)" if k != "steps" else "")), width=17).pack(
                side="left")
            v = tk.StringVar(value=f"{p.get(k, PK.PIECES[p['type']].get(k, 0)):g}")
            e = ttk.Entry(f, textvariable=v, width=8)
            e.pack(side="left")
            e.bind("<Return>", lambda _e: self.apply())
            e.bind("<FocusOut>", lambda _e: self.apply())
            self.fields[k] = v
        ttk.Button(self.side, text="Delete piece", command=self.delete).pack(anchor="w", pady=(10, 0))

    def apply(self):
        if self.sel is None:
            return
        p = self.layout["pieces"][self.sel]
        for k, v in self.fields.items():
            try:
                x = float(v.get())
            except ValueError:
                continue
            p[k] = int(max(1, x)) if k == "steps" else (x % 360 if k == "rot" else
                                                         (x if k in ("x", "y") else max(0.1, x)))
        self.draw()

    # ---- files
    def save(self, ask=False):
        self.apply()
        path = self.path
        if ask or not path:
            os.makedirs(PARKS_DIR, exist_ok=True)
            path = filedialog.asksaveasfilename(parent=self.top, initialdir=PARKS_DIR, defaultextension=".json",
                                                initialfile=(self.layout.get("name") or "park") + ".json",
                                                filetypes=[("Skatepark layout", "*.json")])
            if not path:
                return
        with open(path, "w") as f:
            json.dump(self.layout, f, indent=1)
        self.path = path
        if self.on_save:
            self.on_save(path)
        self.status.set(f"Saved {os.path.basename(path)}")

    def open(self):
        path = filedialog.askopenfilename(parent=self.top, initialdir=PARKS_DIR,
                                          filetypes=[("Skatepark layout", "*.json")])
        if path:
            with open(path) as f:
                self.layout = json.load(f)
            self.path, self.sel = path, None
            self.draw()
            self.show_props()


def context(osm_data, lat0, lon0, reach=90.0):
    """Editor context from a place's OSM data: the skatepark outline and nearby buildings/paths, in metres around
    the park centre (or the location when no skatepark is mapped)."""
    from thaw_sandbox.mapgen import osm as O
    found = O.find_park(osm_data, lat0, lon0)
    c = found[1] if found else (0.0, 0.0)
    kx = 111320 * math.cos(math.radians(lat0))
    rel = lambda g: ((g["lon"] - lon0) * kx - c[0], (g["lat"] - lat0) * 111320 - c[1])
    out = {"outline": [(e - c[0], n - c[1]) for e, n in found[0]] if found else None, "buildings": [], "paths": []}
    for w in osm_data["elements"]:
        if w["type"] != "way" or "geometry" not in w:
            continue
        pts = [rel(g) for g in w["geometry"]]
        if not any(abs(p[0]) < reach and abs(p[1]) < reach for p in pts):
            continue
        t = w.get("tags", {})
        if "building" in t:
            out["buildings"].append(pts)
        elif "highway" in t:
            out["paths"].append(pts)
    return out
