"""Classic mode for added levels (Super DX): the level's own THUG2 classic goals, rewritten for THAW's goal
scripts, and the classic level ladder.

THUG2 level goal scripts (<code>_Goals) call AddGoal_HighScore / ProScore / SickScore / HighCombo / Skate / Combo /
collect / gaps / SecretTape with classic_mode_goal. THAW still has all of those scripts, with these differences
(read from both games' scripts):
  * every THAW AddGoal_* needs zone = '<zone>' (goal ids become <zone>_classic_goal_<type><version>; THUG2's were
    <code>_classic_goal_...: the level's helper scripts name them, so those names are remapped)
  * view_goals_cameras must hold pos/Quat cameras (the view-goals menu reads them): THAW's stock
    goal_utilities_temp_goal_cam; THUG2's virtual_cam (world camera position + look-at point) becomes the goal's
    classic_intro_camera {LockTo = world pos Quat FOV}, shown before a run
  * score targets and their texts were globals of THUG2's goal_scores.qb: inlined as literals
  * THAW's AddGoal_collect wants goal_collect_objects; THUG2's generic list named objects that never existed
    (the levels count crates etc. from trigger scripts), so the same kind of list is passed
  * THAW's goal_collect_got_object also hides the object it runs on - from a trigger script that is the skater -
    so the level scripts call sdx_collect_got (THUG2's version of that script) instead
The level's Goals script is the template's (Z_JA_Goals, renamed with the zone); goals are added in classic mode.
"""
import math
import struct

from thaw_sandbox import convert_thug2 as C, lzss, qb_code as QC, qb_data as QD, qb_file as F, qb_tokens as T
from thaw_sandbox.qb_parser import qbcrc as H

GOAL_TYPES = ("HighScore", "ProScore", "SickScore", "HighCombo", "Skate", "Combo", "Collect", "Gaps", "SecretTape",
              "Counter")
ADDGOAL = {H(f"AddGoal_{t}"): t for t in GOAL_TYPES}
# THUG2 game objects that classic goals use; THAW ships the same models (same node Type and model path)
GOAL_OBJECT_TYPES = tuple(f"Letter_{c}" for c in "SKATE") + tuple(f"Combo_{c}" for c in "COMB") + ("Secret_Tape",)
SCORES_QB = "\\scripts\\game\\goal_scores.qb"
# unlock thresholds (goals beaten over all classic levels) for the 2nd, 3rd, ... level: THAW's own ladder, then +7
LADDER = (5, 12, 18, 25, 31, 40, 48)

COLLECT_GOT = """
Obj_ClearExceptions
PlaySound GapSound_11 vol = 100
GoalManager_SetGoalFlag name = <goal_id> <flag> 1
GoalManager_GetGoalParams name = <goal_id>
if not GoalManager_AllFlagsSet name = <goal_id>
    FormatText TextName = collect_text '%c of %n %t' c = <num_flags_set> t = <collect_type> n = <num_flags>
    create_panel_message text = <collect_text> style = Goal_Collect_text
endif
"""


def look_quat(pos, target):
    """THAW camera Quat (x, y, z; w >= 0 implied) at pos looking at target. Checked against Kyoto's own classic
    intro cameras: the view direction is +Z rotated by the conjugate of the stored quaternion."""
    d = [t - p for p, t in zip(pos, target)]
    n = math.sqrt(sum(x * x for x in d)) or 1.0
    d = [x / n for x in d]
    r = [d[2], 0.0, -d[0]]  # right = up x d, up = +Y
    rn = math.sqrt(sum(x * x for x in r))
    if rn < 1e-6:
        r, rn = [1.0, 0.0, 0.0], 1.0
    r = [x / rn for x in r]
    u = [d[1] * r[2] - d[2] * r[1], d[2] * r[0] - d[0] * r[2], d[0] * r[1] - d[1] * r[0]]
    m = [[r[0], u[0], d[0]], [r[1], u[1], d[1]], [r[2], u[2], d[2]]]  # columns: right, up, view
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s]
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = [0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s]
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = [(m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s]
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = [(m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s]
    x, y, z, w = q
    x, y, z = -x, -y, -z  # conjugate
    if w < 0:
        x, y, z = -x, -y, -z
    return x, y, z


def thug2_constants(scores_qb: bytes) -> dict:
    """{name crc: int or str} from THUG2's goal_scores.qb."""
    from thaw_sandbox import thug2_qb
    return {k: v for k, v in thug2_qb.parse(scores_qb).data.items() if isinstance(v, (int, str)) and
            not isinstance(v, bool)}


def _inline(value: bytes, consts) -> bytes:
    out = bytearray()
    for t in T.tokenize(value):
        c = consts.get(QC.name_of(value, t)) if t.id == 22 else None
        if isinstance(c, int):
            out += QC.integer(c)
        elif isinstance(c, str):
            out += QC.string(c)
        else:
            out += value[t.off:t.end]
    return bytes(out)


def _camera(value: bytes):
    """THUG2 view_goals_cameras = [{virtual_cam targetid = world targetOffset = vec positionOffset = vec ...}]
    -> (camera position, look-at point) or None (cameras named after level animations have no THAW form)."""
    toks = T.tokenize(value)
    if len(toks) < 3 or toks[0].id != 5:
        return None
    i = next((k for k, t in enumerate(toks) if t.id == 3), None)
    if i is None:
        return None
    f = {k: v for k, v in QC.fields(value, toks[i + 1:QC.matching(toks, i)]) if k}
    tgt, pos = f.get(H("targetOffset")), f.get(H("positionOffset"))
    if not tgt or not pos or tgt[0] != 0x1e or pos[0] != 0x1e:
        return None
    return struct.unpack_from("<3f", pos, 1), struct.unpack_from("<3f", tgt, 1)


def _intro_cam(cam) -> bytes:
    pos, tgt = cam
    return QC.build_struct([("LockTo", QC.name("world")), ("pos", QC.vector(*pos)),
                            ("Quat", QC.vector(*look_quat(pos, tgt))), ("FOV", QC.real(72.0))], eol=False)


def convert_goals(code: bytes, zone: str, consts: dict):
    """A THUG2 <code>_Goals script -> (THAW script code for <zone>_Goals, goal count). Only the classic goals are
    kept (the rest were for THUG2's story and net modes)."""
    toks = T.tokenize(code)
    goals = []
    for i, t in enumerate(toks):
        kind = ADDGOAL.get(QC.name_of(code, t)) if t.id == 22 else None
        if kind is None or i + 1 >= len(toks) or toks[i + 1].id != 3:
            continue
        j = QC.matching(toks, i + 1)
        if any(x.id in QC.JUMPS for x in toks[i + 2:j]):
            continue
        fs = QC.fields(code, toks[i + 2:j])
        if not any(k is None and v == QC.name("classic_mode_goal") for k, v in fs):
            continue
        goals.append((kind, fs))
    cams = [next((_camera(v) for k, v in fs if k == H("view_goals_cameras")), None) for _, fs in goals]
    first = next((c for c in cams if c), None)
    out = bytearray()
    for n, ((kind, fs), cam) in enumerate(zip(goals, cams)):
        keys = {k for k, _ in fs}
        ent = [("zone", QC.string(zone))]
        ent += [(k, _inline(v, consts)) for k, v in fs if k != H("view_goals_cameras")]
        ent.append(("view_goals_cameras", b"\x05" + QC.name("goal_utilities_temp_goal_cam") + b"\x06"))
        if kind == "Collect" and H("goal_collect_objects") not in keys:
            flags = next((v for k, v in fs if k == H("goal_flags")), None)
            names = [QC.name_of(flags, x) for x in T.tokenize(flags) if x.id == 22] if flags else []
            names = names or [H(f"got_{k}") for k in range(1, 6)]
            ent.append(("goal_collect_objects", b"\x05" + b"".join(QC.build_struct(
                [("id", QC.name(f"sdx_no_object_{k + 1}")), ("scr", QC.name("goal_collect_got_object")),
                 ("flag", QC.name(f))], eol=False) for k, f in enumerate(names)) + b"\x06"))
        if cam or (n == 0 and first):  # a goal without one reuses the previous goal's (classic_mode_menu)
            ent.append(("classic_intro_camera", _intro_cam(cam or first)))
        elif n == 0:
            ent.append(("classic_intro_camera", QC.name("goal_utilities_temp_goal_cam")))
        out += QC.EOL + QC.name(f"AddGoal_{kind}") + QC.build_struct(ent)
    if not goals:
        return None, 0
    return QC.if_block(QC.name("GameModeEquals") + QC.name("is_classic"), bytes(out)) + QC.EOL + QC.ENDSCRIPT, \
        len(goals)


def remap_table(code: str, zone: str) -> dict:
    """Name checksums to swap in the level's own scripts: THUG2 goal ids -> THAW's, and the collect callback."""
    out = {H("goal_collect_got_object"): H("sdx_collect_got")}
    for t in GOAL_TYPES:
        for v in ("",) + tuple(str(k) for k in range(2, 10)):
            out[H(f"{code}_classic_goal_{t}{v}")] = H(f"{zone}_classic_goal_{t}{v}")
    return out


def remap_code(code: bytes, table: dict) -> bytes:
    try:
        toks = T.tokenize(code)
    except ValueError:
        return code
    b = bytearray(code)
    for t in toks:
        if t.id == 22:
            new = table.get(struct.unpack_from("<I", b, t.off + 1)[0])
            if new is not None:
                struct.pack_into("<I", b, t.off + 1, new)
    return bytes(b)


def remap_items(items, table):
    """Swap names in every script of a qb item list (in place). -> scripts changed"""
    n = 0
    for it in items:
        if it.vtype != 7:
            continue
        code = lzss.unpack_body(it.value)[1]
        new = remap_code(code, table)
        if new != code:
            it.value = C.script_body(new)
            n += 1
    return n


# ---- the classic ladder (global scripts) -------------------------------------------------------------------------

def _get(items, name):
    return next(it for it in items if it.name == H(name))


def _append(item, block: bytes):
    """Add statements to the end of a script (before its endscript)."""
    code = lzss.unpack_body(item.value)[1]
    assert code.endswith(b"\x01\x24"), "script does not end with EOL endscript"
    item.value = C.script_body(code[:-2] + block + QC.EOL + QC.ENDSCRIPT)


def ladder_edits(levels, template="z_ja"):
    """levels: [(zone, display name)] in ladder order, put before THAW's own classic levels. The first one is
    open from the start; every later level (THAW's included) needs LADDER goals.
    -> edits for level_register.edit_files"""
    import copy

    def menu(items):
        arr = _get(items, "level_select_menu_classic_level_info").value
        tmpl = next(e for e in arr.items if any(k == H("Level") and getattr(v, "crc", 0) == H(f"load_{template}")
                                                for k, v in e.items))
        new = []
        for zone, display in levels:
            e = copy.deepcopy(tmpl)
            e.items = [(k, v) for k, v in e.items if k not in (H("required_goal_total"), H("collectors_edition_only"))]
            for i, (k, v) in enumerate(e.items):
                if k == H("text"):
                    e.items[i] = (k, type(v)(display))
                elif k == H("Level"):
                    e.items[i] = (k, QD.Name(H(f"load_{zone}")))
            new.append(e)
        for e in arr.items:
            e.items = [(k, v) for k, v in e.items if k != H("required_goal_total")]
        arr.items[:0] = new
        for n, e in enumerate(arr.items[1:]):
            need = LADDER[n] if n < len(LADDER) else LADDER[-1] + 7 * (n - len(LADDER) + 1)
            e.items.append((H("required_goal_total"), need))
        first = levels[0][0]
        _append(_get(items, "SetStartingLevelFlags"), QC.compile_block(
            f"SetFlag Level = load_{first} flag = LEVEL_VISITED\n"
            f"SetFlag Level = load_{first} flag = LEVEL_UNLOCKED_CLASSIC"))

    def collect(items):
        items.append(F.Item(7, H("sdx_collect_got"), C.script_body(QC.compile_script(COLLECT_GOT))))

    return (("gamemenu_levelselect.qb.ps2", menu), ("goal_collect.qb.ps2", collect))
