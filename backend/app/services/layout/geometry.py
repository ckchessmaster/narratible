from typing import Sequence


def clamp(val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, val))


def normalize_bbox(
    bbox: Sequence[float], width: float, height: float
) -> list[float]:
    """Convert absolute page coordinates [x0, y0, x1, y1] to normalized [0.0, 1.0]."""
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 1.0, 1.0]
    x0, y0, x1, y1 = bbox
    return [
        round(clamp(min(x0, x1) / width), 4),
        round(clamp(min(y0, y1) / height), 4),
        round(clamp(max(x0, x1) / width), 4),
        round(clamp(max(y0, y1) / height), 4),
    ]


def denormalize_bbox(
    n_bbox: Sequence[float], width: float, height: float
) -> list[float]:
    """Convert normalized [0.0, 1.0] coordinates to absolute page coordinates [x0, y0, x1, y1]."""
    x0, y0, x1, y1 = n_bbox
    return [
        round(x0 * width, 2),
        round(y0 * height, 2),
        round(x1 * width, 2),
        round(y1 * height, 2),
    ]


def bbox_centroid(bbox: Sequence[float]) -> tuple[float, float]:
    """Return (center_x, center_y) of a bounding box."""
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def bbox_area(bbox: Sequence[float]) -> float:
    """Return width * height of a bounding box."""
    w = max(0.0, bbox[2] - bbox[0])
    h = max(0.0, bbox[3] - bbox[1])
    return w * h


def bbox_contains(outer: Sequence[float], inner: Sequence[float], tol: float = 0.01) -> bool:
    """Return True if outer box contains inner box within an optional tolerance."""
    return (
        outer[0] - tol <= inner[0]
        and outer[1] - tol <= inner[1]
        and outer[2] + tol >= inner[2]
        and outer[3] + tol >= inner[3]
    )


def bbox_centroid_inside(outer: Sequence[float], inner: Sequence[float]) -> bool:
    """Return True if the centroid of inner box falls inside outer box."""
    cx, cy = bbox_centroid(inner)
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def bbox_vertical_distance(b1: Sequence[float], b2: Sequence[float]) -> float:
    """Return the absolute vertical distance between the centroids of two boxes."""
    _, cy1 = bbox_centroid(b1)
    _, cy2 = bbox_centroid(b2)
    return abs(cy1 - cy2)


def recursive_xy_cut(
    items: list[dict],
    bbox_key: str = "bbox",
    min_gap: float = 0.008,
    spanning_threshold: float = 0.60,
) -> list[dict]:
    """
    Recursive XY-Cut layout decomposition.
    1. If a full-width spanning block (e.g. section title, banner) spans across the container,
       split horizontally above and below it.
    2. Otherwise, check for vertical gutters (columns). If gutters exist, split vertically
       into columns from left to right (depth-first).
    3. Within a single column, sort top-to-bottom.
    """
    if len(items) <= 1:
        return list(items)

    def _b(it):
        return it[bbox_key]

    # Calculate bounding container of the items in this branch
    c_x0 = min(_b(it)[0] for it in items)
    c_x1 = max(_b(it)[2] for it in items)
    c_width = max(0.001, c_x1 - c_x0)

    # 1. Check for full-width spanning blocks (e.g. title spanning >60% of container width)
    spanning_blocks = [
        it for it in items
        if ((_b(it)[2] - _b(it)[0]) / c_width) >= spanning_threshold
        and len(items) > 1
    ]

    if spanning_blocks:
        # Sort all items by y0 and partition horizontally around spanning blocks
        sorted_by_y = sorted(items, key=lambda it: _b(it)[1])
        h_splits = []
        current_max_y = _b(sorted_by_y[0])[3]
        current_group = [sorted_by_y[0]]

        for it in sorted_by_y[1:]:
            box = _b(it)
            # Only cut horizontally if a spanning block triggers or gap exists near spanning
            is_spanning = it in spanning_blocks or current_group[-1] in spanning_blocks
            if is_spanning and box[1] >= current_max_y + min_gap:
                h_splits.append(current_group)
                current_group = [it]
                current_max_y = box[3]
            else:
                current_group.append(it)
                if box[3] > current_max_y:
                    current_max_y = box[3]
        h_splits.append(current_group)

        if len(h_splits) > 1:
            result = []
            for band in h_splits:
                result.extend(
                    recursive_xy_cut(
                        band,
                        bbox_key=bbox_key,
                        min_gap=min_gap,
                        spanning_threshold=spanning_threshold,
                    )
                )
            return result

    # 2. Check for vertical gutters (columns)
    sorted_by_x = sorted(items, key=lambda it: _b(it)[0])
    v_splits = []
    current_max_x = _b(sorted_by_x[0])[2]
    current_col = [sorted_by_x[0]]

    for it in sorted_by_x[1:]:
        box = _b(it)
        if box[0] >= current_max_x + min_gap:
            # Found distinct vertical column gutter!
            v_splits.append(current_col)
            current_col = [it]
            current_max_x = box[2]
        else:
            current_col.append(it)
            if box[2] > current_max_x:
                current_max_x = box[2]
    v_splits.append(current_col)

    if len(v_splits) > 1:
        # Traverse columns depth-first: Left Column -> Right Column
        result = []
        for col in v_splits:
            result.extend(
                recursive_xy_cut(
                    col,
                    bbox_key=bbox_key,
                    min_gap=min_gap,
                    spanning_threshold=spanning_threshold,
                )
            )
        return result

    # 3. Base case (single column): Sort top-to-bottom (y0), then left-to-right (x0)
    return sorted(items, key=lambda it: (_b(it)[1], _b(it)[0]))
