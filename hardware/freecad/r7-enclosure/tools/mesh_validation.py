"""Current mesh topology checker, extracted unchanged from the verified fit audit.

Only triangle reading, vector math and mesh validation functions are retained.
No old enclosure revision or native CAD document is required.
"""
from __future__ import annotations
from collections import Counter
import math,struct

def read_stl(path):
    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * count:
            triangles = []
            for offset in range(84, len(data), 50):
                coordinates = struct.unpack_from("<9f", data, offset + 12)
                triangles.append(tuple(tuple(coordinates[i:i + 3]) for i in (0, 3, 6)))
            return "binary", triangles
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Neither ASCII STL nor binary STL with a matching triangle count") from exc
    triangles, current = [], None
    for number, line in enumerate(text.splitlines(), 1):
        words = line.split()
        if not words:
            continue
        keyword = words[0].lower()
        if keyword == "facet":
            if current is not None:
                raise ValueError(f"Nested facet on line {number}")
            current = []
        elif keyword == "vertex":
            if current is None or len(words) != 4:
                raise ValueError(f"Invalid vertex on line {number}")
            current.append(tuple(float(value) for value in words[1:]))
        elif keyword == "endfacet":
            if current is None or len(current) != 3:
                raise ValueError(f"Facet must have three vertices, line {number}")
            triangles.append(tuple(current))
            current = None
        elif keyword not in {"solid", "endsolid", "outer", "endloop"}:
            raise ValueError(f"Unexpected ASCII STL content on line {number}")
    if current is not None:
        raise ValueError("Unterminated ASCII STL facet")
    return "ascii", triangles


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def validate_mesh(path):
    report = {"file": path.name, "ok": False}
    try:
        kind, triangles = read_stl(path)
        if not triangles:
            raise ValueError("Mesh has no triangles")
        if any(not math.isfinite(v) for tri in triangles for point in tri for v in point):
            raise ValueError("Mesh contains a non-finite coordinate")
        minimum = [min(point[i] for tri in triangles for point in tri) for i in range(3)]
        maximum = [max(point[i] for tri in triangles for point in tri) for i in range(3)]
        origin = [(a + b) / 2 for a, b in zip(minimum, maximum)]
        parents = list(range(len(triangles)))
        sizes = [1] * len(triangles)

        def root(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def join(a, b):
            a, b = root(a), root(b)
            if a != b:
                if sizes[a] < sizes[b]:
                    a, b = b, a
                parents[b] = a
                sizes[a] += sizes[b]

        vertices, edges, volumes = {}, {}, []
        degenerate = 0
        for index, triangle in enumerate(triangles):
            ids = []
            for point in triangle:
                key = tuple(round(value, 5) for value in point)
                if key not in vertices:
                    vertices[key] = len(vertices)
                ids.append(vertices[key])
            a, b, c = triangle
            normal = cross(subtract(b, a), subtract(c, a))
            if len(set(ids)) != 3 or dot(normal, normal) <= 1e-24:
                degenerate += 1
            for u, v in zip(ids, ids[1:] + ids[:1]):
                edge = (min(u, v), max(u, v))
                owners = edges.setdefault(edge, [])
                if owners:
                    join(index, owners[0][0])
                owners.append((index, 1 if u < v else -1))
            a, b, c = (subtract(point, origin) for point in triangle)
            volumes.append(dot(a, cross(b, c)) / 6)

        incidence = Counter(len(owners) for owners in edges.values())
        nonmanifold = sum(count for degree, count in incidence.items() if degree != 2)
        winding_errors = sum(len(owners) == 2 and owners[0][1] == owners[1][1]
                             for owners in edges.values())
        component_sizes = sorted(Counter(root(i) for i in range(len(triangles))).values(), reverse=True)
        signed_volume = math.fsum(volumes)
        if not math.isfinite(signed_volume):
            raise ValueError("Volume calculation is not finite")
        volume = abs(signed_volume)
        report.update({
            "bytes": path.stat().st_size,
            "format": kind,
            "triangles": len(triangles),
            "unique_vertices_after_rounding": len(vertices),
            "bbox_mm": {"min": minimum, "max": maximum,
                        "size": [b - a for a, b in zip(minimum, maximum)]},
            "undirected_edges": len(edges),
            "edge_incidence_histogram": dict(sorted(incidence.items())),
            "nonmanifold_edges": nonmanifold,
            "boundary_edges": incidence.get(1, 0),
            "inconsistent_winding_edges": winding_errors,
            "degenerate_triangles": degenerate,
            "connected_components": len(component_sizes),
            "component_triangle_counts": component_sizes,
            "signed_volume_mm3": signed_volume,
            "absolute_volume_mm3": volume,
        })
        failures = []
        if nonmanifold:
            failures.append("Some undirected edges do not belong to exactly two triangles")
        if len(component_sizes) != 1:
            failures.append("Expected one connected component")
        if degenerate:
            failures.append("Degenerate triangles found")
        if winding_errors:
            failures.append("Adjacent triangle winding is inconsistent")
        if not math.isfinite(volume) or volume <= 0:
            failures.append("Absolute enclosed volume is not positive and finite")
        report["ok"] = not failures
        report["failures"] = failures
    except (OSError, ValueError, ArithmeticError, struct.error) as exc:
        report["error"] = str(exc)
    return report
