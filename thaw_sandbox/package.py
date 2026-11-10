"""Emulator-ready output folder next to a built image.

    package(iso, out_dir)

out_dir/
  <name>.iso            the image (reflink/hard link when possible, else a copy)
  play-linux.sh         starts PCSX2 on it straight into the game (flatpak net.pcsx2.PCSX2, pcsx2-qt on PATH,
                        or a PCSX2 *.AppImage placed in this folder)
  README.txt            Linux and Android steps

Nothing third-party is bundled: the emulator and the PS2 BIOS stay the user's own. The image keeps THAW's serial
(SLUS-21295) and boot ELF, so PCSX2 / AetherSX2 / NetherSX2 apply their built-in THAW fixes (game database)
automatically.
"""
import os
import shutil
import subprocess

LAUNCHER = r"""#!/bin/sh
# Start THAW Super DX in PCSX2 (skips the BIOS screen). Any PCSX2 1.7+/2.x works; its own settings and BIOS are used.
here="$(cd "$(dirname "$0")" && pwd)"
iso="$here/{iso}"
app="$(ls "$here"/*.AppImage 2>/dev/null | head -n1)"
if [ -n "$app" ]; then exec "$app" -batch -fastboot -- "$iso"; fi
if command -v pcsx2-qt >/dev/null 2>&1; then exec pcsx2-qt -batch -fastboot -- "$iso"; fi
if command -v flatpak >/dev/null 2>&1 && flatpak info net.pcsx2.PCSX2 >/dev/null 2>&1; then
  exec flatpak run --filesystem="$here" net.pcsx2.PCSX2 -batch -fastboot -- "$iso"
fi
echo "PCSX2 not found: install it (e.g. flatpak install flathub net.pcsx2.PCSX2) or put a PCSX2 AppImage here." >&2
exit 1
"""

README = """THAW Super DX
=============

{iso} is a Tony Hawk's American Wasteland (NTSC-U) image built from your own discs.
It boots straight to the level list (free skate, Tony Hawk, every level unlocked).
Added levels: {levels}

Linux (PCSX2)
  1. Install PCSX2 (flatpak install flathub net.pcsx2.PCSX2), or put a PCSX2 AppImage in this folder.
  2. Run PCSX2 once and set it up with your own PS2 BIOS.
  3. Run ./play-linux.sh

Android (AetherSX2 / NetherSX2)
  1. Copy {iso} to the device (e.g. the folder your emulator scans for games).
  2. Start it from the game list. The emulator's built-in fixes for THAW (SLUS-21295) apply automatically.
  3. Recommended: renderer Vulkan; if loading screens are missing, keep "Preload Frame Data" on.

Do not share this image: it contains the games you own.
"""


def _place(src, dst):
    if os.path.exists(dst):
        os.remove(dst)
    if subprocess.run(["cp", "--reflink=auto", src, dst]).returncode != 0:
        shutil.copyfile(src, dst)


def package(iso, out_dir, levels=()):
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.basename(iso)
    target = os.path.join(out_dir, name)
    if os.path.abspath(target) != os.path.abspath(iso):
        _place(iso, target)
    sh = os.path.join(out_dir, "play-linux.sh")
    with open(sh, "w") as f:
        f.write(LAUNCHER.replace("{iso}", name))
    os.chmod(sh, 0o755)
    with open(os.path.join(out_dir, "README.txt"), "w") as f:
        f.write(README.format(iso=name, levels=", ".join(levels) or "none"))
    return out_dir
