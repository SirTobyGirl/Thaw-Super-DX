# Format notes: THAW (PS2) and the games before it

What this project learned about the PS2 files of Tony Hawk's American Wasteland (NTSC-U, SLUS-21295) and the
level formats of THUG2, THUG, THPS4 and THPS3, written for other modders. Everything here was checked against the
discs (round trips that reproduce the original bytes) or in PCSX2. The code that reads and writes each format is
named in brackets; its comments have more detail.

All values are little endian. **qbcrc**(s) = `~crc32(lower(s) with / -> \)`, Neversoft's checksum for names and
paths. `w0..w19` = 32-bit words of a record.

## Contents

- [Disc and archives](#disc-and-archives): ISO layout, DATAP.HED/WAD, lookup indexes, PAK/PAB, zone PAKs
- [Scripts (QB)](#scripts-qb): files, data values, compressed script bodies, tokens
- [Level data in THAW zones](#level-data-in-thaw-zones): textures, geometry, collision, nodes, rails, gaps,
  prefix tables
- [Registering a new level](#registering-a-new-level)
- [Older games](#older-games): THUG2, THUG, THPS4, THPS3 differences
- [Engine facts and limits](#engine-facts-and-limits): addresses and limits found while debugging

## Disc and archives

**Image.** UDF bridge (ISO9660 + UDF 1.02). Everything below the first file (system area, volume descriptors,
directories, UDF file entries: sectors 0..348) must stay where it is. Rebuilding the image with genisoimage made
the PS2 BIOS crash in loadelf. Images may grow past single-layer DVD size (2,295,104 sectors): PCSX2 opens them as
one linear single-layer disc and the game reads data beyond it (checked with a 6.9 GB image); only burning a disc
needs the shrunk size.
What works: change file extents only (ISO9660 records + UDF file entries + partition length + closing anchor),
e.g. grow DATAP.WAD over /MOVIES. [iso_build, iso_compact]

**DATAP.HED / DATAP.WAD.** HED = repeated `{s32 offset in 2048-byte sectors, u32 size, NUL-terminated path, pad
to 4}`, ended by offset -1; each WAD entry starts on a sector boundary. HED order does not matter (the shipped
disc already has entries appended out of order). [wad, disc]
THUG2, THUG, THPS4 and THPS3 use the same HED form with **byte** offsets (DATAP / SKATE4 / SKATE3.HED).

**DATAPD.HDP / DATAPF.HDP** are the lookup indexes the game actually uses to find files: D lists per directory
`qbcrc(dir)` + `qbcrc(file)`, F is a sorted list of `qbcrc(filename)`. New or moved files must be added to both.
The music WAD has the same trio (MUSICP.HED/.WAD, MUSICPD/PF.HDP); its HED offsets are sectors with 0x0F in the
top byte. [disc, music]

**PAK / PAB** (e.g. `pak/qb.pak.ps2` + `qb.pab.ps2`). PAK = index of 32-byte entries
`{u32 type, u32 offset, u32 size, u32 crc, 3 x u32 hashes/0, u32 flags}`, +160-byte NUL-padded path when
`flags & 0x20`; the last entry is a marker. Offsets are relative to the entry's own position in the combined
space (PAK then PAB): data in the PAB is at `offset - len(pak) + entry.pos`. qb.pab may grow. [pak]

**Zone PAKs** (`worlds/worldzones/z_xx/z_xx.pak.ps2`): the same entry table with the data inline (base 0). Entry
types are `qbcrc(extension)`: `.tex` `.geom` `.col` `.nqb` (node array) `.sqb` `.qb` `.mdl` `.mcol` `.stex` `.ska`
`.rnb` (rails, 0x91e1028d) `.gap` (0xff2d0e91) `.pfx`, plus the node prefix table (0xa7dea591). Data entries start
on 16-byte boundaries (0xCD padding). Path hashes are `qbcrc(path without the platform suffix)`. [zone]

## Scripts (QB)

**File.** `u32 0, u32 file size, 20 constant bytes (type-size table), records...`. Record (20 bytes) =
`[00 04 vt 00][name crc][file crc][value][next]` followed by its out-of-line data. vt: 1 int, 2 float, 3 string,
7 script, 10 struct, 12 array, 13 name. The record "file crc" is not checked (qbcrc of the path works). [qb_file]

**Data values.** Struct = `[00 00 01 00][ptr to first component]`; component (16 bytes) =
`[00 TT 00 00][name crc or 0 for a flag][value or ptr][next or 0]`, TT = (raw type << 1) | 1. Array =
`[00 01 ET 00][count][ptr]`; arrays of structs/arrays/vectors/strings point at a table of element pointers.
Vector `[00 01 00 00] 3 x f32`, pair 2 x f32, strings NUL-terminated and 4-aligned. Raw types: 1 int, 2 float,
3 string, 4 local string, 5 pair, 6 vector, 7 script, 10 struct, 12 array, 13 name. [qb_data]

**Script bodies** = `[u32 crc][u32 size A][u32 stored size B][stream]`, stored raw if A == B, else **LZSS**
(Okumura): flag byte, 8 items per flag LSB first, 1 = literal; match = `b1 | (b2 & 0xF0) << 4` ring position,
`(b2 & 0x0F) + 3` length; 4096-byte ring, write pointer starting at 4078, **pre-filled with spaces**. Flag bytes
can sit inside 4-byte hashes, so never search compressed data for names. The header crc is not checked.
Store bodies like the original compiler: compressed unless compression is not smaller. Raw-when-compressible and
all-literal streams crash the game; with a real encoder whole-body replacement works. [lzss]

**Tokens** follow THUG2's set (EOL 1, `{` 3, `}` 4, `[` 5, `]` 6, `=` 7, name 0x16 + u32, int 0x17 + i32,
float 0x1A + f32, string 0x1B + u32 length incl. NUL, vector 0x1E, pair 0x1F, begin 0x20, repeat 0x21, break 0x22,
endscript 0x24, endif 0x28, return 0x29, `<...>` 0x2C, arg 0x2D, not 0x39, switch/case 0x3C-0x3F, `:` 0x42) with
fast jumps: **fastif 0x47 / fastelse 0x48 / shortjump 0x49 + s16 offset** relative to the offset field
(fastif lands just past the fastelse or endif token, fastelse just past endif). THAW adds **0x4A**, a serialized
parameter block ending at `k - 2 + u32 size` (k = payload header, 2 mod 4). Every script on the disc tokenizes
to its end. `dbg.pak.ps2` holds plain-text .dbg files with `[LineNumbers]` and `[Checksums]` (hash -> name).
[qb_tokens; qb_code compiles text back to bytecode]

## Level data in THAW zones

**Textures (.tex, version 6).** Header `u16 6, u16 groups, u32 textures, u32 packet offset, u32 data offset`;
80-byte group records from 0x10 (`w12 = (VRAM hi << 16) | lo`: groups alternate between block windows
0x2BC0-0x35A0 and 0x35A0-0x3F80); 64-byte texture records: `w0 crc, w1 group, w3 upload flags, w4-5 GS TEX0,
w10/11 image offset/size, w12/13 palette offset/size, w14 packet offset`. Pixels are stored **pre-swizzled** in
the format they are uploaded as (e.g. 128x128 T4 as 64x32 CT32). The engine rebuilds the upload packets at load
from `w3`: per mip level L, bit `25 + L` = uploaded as CT32, `18 + L` = as CT16, none = native, so `w3` must describe
the stored data. Upload rules (from Kyoto's 783 textures): T4 <= 8 wide or 64x256 native; T4 square >= 32 or both
sides >= 128 as CT32 (w/2, h/4); other T4 as CT16 (w/2, h/2); T8 64x128 or < 16 wide native; other T8 as CT32
(w/2, h/2). Geometry refers to groups, so keep source groups (regrouping crashed). [thaw_tex, gsmem]

**Geometry (.geom).** `u32 K (0x10)`, at K a u32 root offset, then a tree of 0x50-byte nodes (offsets K-relative):
`w0-2` bounding-sphere centre, `w3` radius, `w4-6` half extents, `w7` flags (0x2 leaf, 0x100 on every THAW leaf,
0x400 vertex-colour animation with a list at w14), `w8` leaf: DMA/VIF chunk / node: first child, `w9` bits 16-25
VU slot count, `w10` next sibling, `w11` 1-based texture group index, `w14` relocation list offset or -1,
`w17` 1-based texture index in the group.
A leaf chunk is a DMA tag + VIF codes: register GIFtag + GS registers (TEX0, TEX1, ALPHA, TEST, CLAMP...), then per
batch a vertex GIFtag, V2_32 UVs (x 4096), V4_8 colours (128 = 1.0) or V3_8 normals, and **STMOD 1 + V4_16
positions = (p - leaf centre) * 16**, `w` = 0x8000 strip restart, 0x20 odd vertex (winding), then MSCAL.
Rules that must hold, or the renderer hangs or draws garbage:
- slot count = sum over batches of `cycle * vertices + 2 + registers` (it places the next leaf right after);
- every vertex GIFtag ends with EOP after STCYCL 2-4;
- vertex GIFtag word 1 bits 0-7 = VU1 microcode routine; selectors 0x3C/0x3E/0x48 must use **REGS ST, RGBAQ,
  XYZ2 (0x412) with PRIM fog (0x7C)** (THPS4's XYZF2 gives broken depth); THUG2 0x52/54/56/58 = THAW 0x4E/50/52/54;
- the TEX0/MIPTBP/TEX1 registers must match the texture dictionary (bound after writing). [geom, thps4_geom,
  mapgen/geom_writer]

**Collision (.col, version 10 + THAW block).** Header `8 x u32 {10, objects, verts, large faces, small faces,
float verts, fixed verts, 0}`; THAW inserts 48 bytes `{0, 0, grid columns, grid rows, bbox min xyz1, max xyz1}`;
64-byte objects `{crc, u16 flags, u16 verts, u16 faces, u8 small faces, u8 fixed verts, face offset, bbox,
vert offset, BSP offset, intensity offset, 0}`; float verts (12 B) or fixed verts (u16 x 3 = (p - bbox min) * 16);
1 intensity byte per vertex; faces: large `{u16 flags, u16 terrain, 3 x u16}`, small with u8 indices; one byte per
large face; BSP: u32 size, 8-byte nodes `(axis | int(point * 16) << 2), left child offset` (right follows),
leaves `{3, 0, u16 count, u32 first}` into a u16 face index list. Front face: (b - a) x (c - a) points out.
Face flags: 0x1 skatable, 0x2 not skatable, 0x4 wallride, 0x8 vert, 0x10 not collidable, 0x40 trigger,
0x80 camera collide (inverted in THPS3/THPS4), 0x1000 invisible. [col, mapgen/col_writer]

**Nodes (.nqb)** = `<zone>_NodeArray` plus `<zone>_NodeArray_SortedNames` / `_SortedIndices`: the engine finds nodes
by name with a **binary search**, so these must stay sorted after any rename (a stale order made sound emitters
read null structs: random freezes). [zone_rename, level_convert]

**Prefix table (0xa7dea591)**, one per node array: `u32 qbcrc(<zone>_NodeArray), u32 count, count x {prefix crc,
byte offset, index count}` sorted by crc, then u16 node indices. Scripts' `Kill/Create/Shatter prefix = "..."`
look prefixes up here; a stale table returns the wrong nodes. [prefix_table]

**Rails (.rnb).** THAW builds rails from this table, not from RailNodes: `u32 count, u32 1, count x 22 words
{v0 bbox min, v1 bbox max (node + linked node), v2 position, v3 0, flags, name crc, terrain crc, cluster crc,
next index, prev index}` sorted by name crc, padded to `8 + count * 0x60` (unpacked in place). Flags 0x200 has
next, 0x400 has prev, 0x10 climbing node. Terrain must be a TERRAIN_GRIND* type or grinding crashes. [rails]

**Gaps (.gap):** `u32 1, u32 qbcrc(zone), u16 count, count x {u32 score, u8 length, name}` sorted by score then
name. [gaps]

## Registering a new level

A level needs (all in qb.pak/qb.pab): `Level_<ZONE>` + `load_<ZONE>` (levels.qb), an entry in
`SkaterCareerParams.level_table` (else it never finishes loading), a level-select entry
(gamemenu_levelselect.qb), an unlock in `cheat_reallygivelevels` (cheats.qb), `SkateZones.<zone>`
(zone_links.qb), memory budgets for `<zone>` and `<zone>ped` (zone_sizes_ps2.qb), and the zone's internals renamed
from the template (path hashes, record names, Name values, name tokens). Free skate treats a level as unlocked
when its LEVEL_VISITED flag is set. [level_register, zone_rename, sandbox_patch]

## Older games

| | THUG2 | THUG | THPS4 | THPS3 |
|---|---|---|---|---|
| Archive | DATAP.HED/WAD (bytes) | same | SKATE4.HED/WAD; PRE archives (LZSS) | SKATE3.HED/WAD; PRE |
| Textures | .tex v5, linear | v5 | v4 (no leading word) in `pre/<code>scn.pre` | RenderWare PS2 rasters |
| Geometry | same tree as THAW | V2_16 UVs | V2_16 UVs, leaves name no texture, XYZF2 tags | RenderWare world (.bsp) |
| Collision | v10 (no THAW block) | v9 (no per-face byte block) | v8, 16-byte float verts | in the world's sectors |
| QB | plain token stream | older tokens | old if/else, line numbers | as THPS4 |

- **THUG2 .tex v5:** `version, groups, textures`; group `{crc, 0, 0, count}`; texture `{0, crc, log2 w, log2 h, psm,
  clut psm, flags}` padded to 16, palette, mips (`flags & 0xFF` = mips - 1). Flag bit 31 = header only: the
  pixels live in another group or another level's file (index all .tex files by crc). [thug2_tex, thug2_texrefs]
- **THUG2 geometry** names group/texture by checksum; THAW by 1-based index. Untextured leaves (microcode 0x44)
  freeze THAW: drop them. [geom]
- **THPS4/THUG geometry:** widen V2_16 UVs to V2_32 (exact). Leaves have no texture id: match TEX0 to the group's
  textures by **CLUT position**: palettes are uploaded downwards in file order, unused textures included,
  `CBP = top - (palette blocks of textures 0..i)`, T4 1 block, T8 CT16 2, T8 CT32 4, unpalettised 0.
  Clear vertex flag 0x4000, node w14, flag 0x400 and the 0xFF top byte of w7. [thps4_geom]
- **THPS4 node positions** have Z mirrored against the geometry (as do THPS3's). [sources/thps4]
- **Disney's Extreme Skate Adventure** (SLUS-20607) is the THPS4 engine with THPS4's formats; every level file is
  in PRE archives (`<code>scn.pre` geometry/textures/sky, `<code>col.pre`, `<code>.pre` nodes + scripts). One
  texture dictionary (Olliewood) has more groups than its header's group count: read until the texture count is
  reached. A few textures are direct colour (CT32/CT24/CT16): converted to 8-bit palettised. [sources/desa]
- **THPS4 QB:** 0x02 = newline + line number; random has no weights; old if/else/endif (0x25/0x26/0x28) must
  become fast ifs or loads hang. [thps4_qb]
- **PRE archives:** `u32 total, u32 version, u32 count`, entries `{size, compressed size, name length,
  [v3: name crc], name, data}` 4-aligned; compressed data uses the same LZSS as THAW scripts. [sources/thps4]
- **THPS3 (RenderWare 3.1):** chunks `{u32 type, u32 size, u32 0x310}`. World struct ends with a format word
  (0x01 tristrip, 0x08 prelit, 0x10 normals, 0x80 two UV sets); atomic sectors hold vertices, normals, prelit
  colours (255 = full), UVs and triangles `{u16 material, u16 a, b, c}` (front face as above).
  The material list struct is `{count, count x i32}`: -1 = a new Material chunk follows, otherwise the index of an
  earlier material to reuse (ignore it and later indices shift; Rio reuses 8).
  Neversoft chunk 0x294AF01 in each **sector** = `u32 6, u16 face flags per triangle, ..., sector checksum` (the
  name of the sector's `EnvironmentObject` node). In each **material**: byte 19 flags (0x02 collision-only mesh,
  0x08 transparent, 0x10 decal), byte 20 terrain (standard list), byte 37 GS ALPHA (0x00/0x0A/0x44 normal,
  0x48/0x68 additive, 0x42/0x62 subtractive, 0x64 fixed blend), byte 41 FIX, then the pass's Texture chunk.
  Trigger faces (0x40) run the `TriggerScript` of the node named like the sector (gaps, glass, bouncy objects);
  in THAW the collision object must carry that name and the node must exist, or the engine reads a null node.
  Texture rasters: T4/T8 with GS-ready palettes (raster format 0x4000 4-bit, 0x2000 8-bit, 0x0500 CT32, 0x0100
  CT16, 0x8000 mips), or **16/32-bit direct colour** (THPS2-era textures in Warehouse, Burnside, Roswell).
  Each level's `.qb` holds both its node array and its scripts. Sky worlds are separate (`Levels\<x>_Sky`).
  **Level objects** (`<code>.dff`): one clump per object, back to back; the clump's last chunk, Neversoft's
  `0x294AF01 {u32 1, u32 name crc}`, lies past the clump's size field (scan for the next clump header). Geometry
  struct (RW before 3.4) = `{format, triangles, vertices, morph targets, 3 x f32 surface properties}`, prelit
  colours, UVs, triangles `{u16 v2, v1, material, v3}`, morph target `{sphere, has verts, has normals, verts}`.
  Vertices are in the object's own space; the node of the same name (GameObject, BouncyObject) places it
  (Position with Z mirrored, Y rotation reversed).
  [rw, sources/thps3]

### Project 8 (PS2)

Project 8's PS2 version runs on THAW's engine: its areas are THAW-format zone PAKs whose textures (version 6),
geometry, collision (with the supersector block) and node files THAW reads as they are. Its DATAP.HED offsets are
**21-bit sector numbers, sign-extended**: entries past 2 GB of the WAD read negative; use `offset & 0x1FFFFF`.
The areas are pieces of one streamed city, so several have no restart node. The disc still carries THAW's level
list and a 2.5 MB leftover of THAW's Marseilles (`z_ms`). [sources/p8]

### Proving Ground (PS2)

Same engine and files as Project 8 (zone PAKs THAW reads as they are). Its node files use one QB value type THAW
does not have: **raw type 26**, an inline name checksum (e.g. a ped's `profile`); it is read as a name (13).
About half of each area's leaves store positions as **V4_32**: fixed point with 12 fraction bits, absolute (leaf
centre words are 0), where THAW's microcode expects V4_16 relative to the centre. The city areas also use a unit
about **12x** THAW's (collision 250-650 units across). Not supported yet. [sources/pg]

### THUG Pro custom levels (PC)

Downloads (e.g. thpsgoat.com) hold `<scene>.level.json` (hand-written JSON, trailing commas) and PRE archives
renamed `.prx`: `<scene>scn.prx` (`.scn.xbx` scene + `.tex.xbx` textures, plus a sky), `<scene>col.prx` (`.col.xbx`
= THUG2 collision version 10) and `<scene>_scripts.prx` (`<scene>.qb` = THUG2 nodes; script files may be empty).
- **Scene (.scn.xbx):** `3 x u32, u32 materials, materials, i32 sectors, sectors`. Material: checksum, name
  checksum, passes, alpha cutoff, sorted, draw order, single sided, no culling, z bias, grass, specular; per pass
  texture checksum, flags (0x10 decal, 0x40 transparent, 0x800 animated...), colour, blend mode (THUG2 list:
  1 add, 2 add fixed, 3 subtract, 4 sub fixed, 5 blend, 6 blend fixed ...), fixed alpha, addressing, filtering,
  optional wibble / animation blocks, 4 words of mip info. Sector: checksum, bone, flags (0x01 UVs, 0x02 colours,
  0x04 normals, 0x10 weights, 0x800000 billboard), meshes; mesh: bounds, material checksum, LODs; per LOD an index
  list, a **triangle strip** (u16), 14 bytes, u8 stride, u16 vertex count, u16 buffers, then vertices
  `{3 f32 position, [normal], [b g r a, 128 = 1.0], UV sets}` and a small trailer (vertex shaders, wibble flag,
  pixel shader block `{i32, i32 n, n bytes}`). Positions are in THUG2's frame (matching collision and nodes).
- **Textures (.tex.xbx):** `i32 version, i32 count`; per texture `checksum, width, height, levels, texel depth,
  palette depth, DXT version (1/2 = DXT1, 5), palette size`, palette, then each level `{u32 size, data}`.
  [xbx, sources/thugpro]

## Engine facts and limits

THAW SLUS_212.95 (PS2), addresses for Ghidra (r5900):

- Zone size: if any zone PAK on the disc is larger than ~10.6 MB, THAW's own big levels hang while loading (the game
  sizes something from the largest zone file). Kyoto (z_ja, 8.7 MB) is the largest shipped zone.
- 40 per-level career flag slots (SetFlag FUN_002fb540); levels past them share flags.
- Rail table loader FUN_0025a818 (allocates `count * 0x60` on the main heap; patched to unpack in place, [elf_patch]).
- Node lookup by name FUN_00252d38 -> FUN_00252bd0 (binary search); prefix lookup FUN_00250f38 -> FUN_00250d00;
  struct field getter FUN_002ae260 (a null struct here = a missing node).
- Renderer: load walker FUN_001cfb58, object render FUN_001d09e8, leaf emit FUN_001d1f58, group sequencer
  FUN_001c3930, "DMA HANG!" wait around 0x2a6958 (a frame that never ends: wrong slot count or missing EOP).
- `startup_loading_screen`'s movie check, `attract_mode_timer` (attract demo after ~40 s idle) and
  `create_xbox_online_menu` (an unused Xbox-only script that can host boot code) are useful hooks. [sandbox_patch]

Credits: formats were cross-checked against
[neversoft-multitool](https://github.com/slfx77/neversoft-multitool),
[io_thps_scene](https://github.com/denetii/io_thps_scene), [LegacyTHPS](https://github.com/DCxDemo/LegacyTHPS),
[QScript](https://github.com/cuckydev/QScript), [NeverScript](https://github.com/byxor/NeverScript) and
[WAD-Tool](https://github.com/DCxDemo/WAD-Tool).
