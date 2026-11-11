"""Node array for a generated level: player start points and rail nodes (THAW form, as in Kyoto's nodes)."""
from thaw_sandbox import qb_data as QD
from thaw_sandbox.qb_parser import qbcrc as H


def _n(s):
    return QD.Name(H(s))


def build(scene, zone_name):
    """-> list of node structs (the <zone>_NodeArray items)."""
    nodes = []
    for i, (pos, heading) in enumerate(scene.starts or [((0.0, 0.0, 0.0), 0.0)]):
        nodes.append(QD.Struct([
            (H("name"), _n(f"{zone_name}_start{i}")),
            (H("pos"), tuple(float(x) for x in pos)),
            (H("Angles"), (0.0, float(heading), 0.0)),
            (H("Class"), _n("restart")),
            (H("type"), _n("Player1")),
            (0, _n("CreatedAtStart")),
            (H("RestartName"), f"Start {i + 1}"),
            (H("restart_types"), QD.Array(13, [_n("Player1")])),
        ]))
    for r, rail in enumerate(scene.rails):
        base = len(nodes)
        for j, p in enumerate(rail.points):
            items = [(H("name"), _n(f"{zone_name}_rail{r}_{j}")),
                     (H("pos"), tuple(float(x) for x in p)),
                     (H("Angles"), (0.0, 0.0, 0.0)),
                     (H("Class"), _n("ClimbingNode" if rail.climb else "RailNode")),
                     (H("type"), _n("Generic")),
                     (0, _n("CreatedAtStart"))]
            if not rail.climb:
                items.append((H("TerrainType"), _n(rail.terrain)))
            if j + 1 < len(rail.points):
                items.append((H("links"), QD.Array(1, [base + j + 1])))
            nodes.append(QD.Struct(items))
    return nodes
