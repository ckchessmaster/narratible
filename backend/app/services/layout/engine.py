import uuid
from typing import Sequence
import pymupdf as fitz

from .models import PageLayout, LayoutBlock, BlockType
from .geometry import (
    normalize_bbox,
    bbox_centroid_inside,
    bbox_vertical_distance,
    recursive_xy_cut,
)
from .containers import detect_vector_callouts, detect_images_and_captions
from .margins import (
    is_header_footer,
    is_footnote,
    is_marginalia,
    compute_body_column_bounds,
    FOOTNOTE_PATTERN,
    MARGINALIA_PATTERN,
)
from .extractor import extract_block_text


def _cluster_body_columns(body_segments: list[dict], width: float, height: float) -> list[list[dict]]:
    """
    Cluster body lines into columns. For single-column text, merges all contiguous lines
    into a single unified reading column macrozone. For multi-column pages, detects vertical
    gutters and cleanly partitions lines into separate column flow containers.
    """
    if not body_segments:
        return []

    x_min = min(s["bbox"][0] for s in body_segments)
    x_max = max(s["bbox"][2] for s in body_segments)

    # Search for vertical gutters (empty vertical strips dividing columns)
    gutters = []
    x_step = 2.0
    x_probe = x_min + 35.0
    while x_probe < x_max - 35.0:
        crossers = [s for s in body_segments if s["bbox"][0] <= x_probe <= s["bbox"][2]]
        if not crossers:
            gutters.append(x_probe)
        x_probe += x_step

    if gutters:
        gutter_ranges = []
        cur_range = [gutters[0]]
        for g in gutters[1:]:
            if g - cur_range[-1] <= x_step * 1.5:
                cur_range.append(g)
            else:
                gutter_ranges.append((min(cur_range), max(cur_range)))
                cur_range = [g]
        if cur_range:
            gutter_ranges.append((min(cur_range), max(cur_range)))

        # A valid column dividing gutter must have significant width (>= 12 points)
        valid_gutters = [r for r in gutter_ranges if (r[1] - r[0]) >= 12.0]
        if valid_gutters:
            widest = max(valid_gutters, key=lambda r: r[1] - r[0])
            split_x = (widest[0] + widest[1]) / 2.0
            col1 = [s for s in body_segments if s["bbox"][2] <= split_x]
            col2 = [s for s in body_segments if s["bbox"][0] >= split_x]
            if col1 and col2:
                return [col1, col2]

    # Single column layout: All body segments belong to a single continuous column
    return [body_segments]


def _extract_atomic_segments(
    page: fitz.Page,
    width: float,
    height: float,
    page_number: int,
) -> tuple[list[dict], float, float]:
    """
    Extract atomic text segments from PyMuPDF dict by inspecting text spans.
    Unlike line-level or block-level extraction, this cleanly untangles composite
    lines where OCR engines merged margin citations (e.g., 'Luke i. 35') and adjacent
    body lines ('portion of the whole...') into the exact same line baseline.
    """
    page_dict = page.get_text("dict") or {}
    all_spans = []

    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                txt = s.get("text", "").strip()
                if txt:
                    all_spans.append(s)

    if not all_spans:
        return [], 0.15 * width, 0.85 * width

    # 1. Determine typographical scale (median body font size)
    mid_spans = [s for s in all_spans if 0.10 <= s["bbox"][1] / height <= 0.88]
    sizes = sorted(s["size"] for s in mid_spans) if mid_spans else [s["size"] for s in all_spans]
    body_size = sizes[len(sizes) // 2] if sizes else 10.0

    # 2. Determine dominant body column boundaries [col_x0, col_x1]
    # Filter out outer margin notes matching MARGINALIA_PATTERN so they don't skew the body column
    body_spans = [
        s for s in mid_spans
        if s["size"] >= 0.88 * body_size
        and not (
            (s["bbox"][2] / width <= 0.32 or s["bbox"][0] / width >= 0.68)
            and bool(MARGINALIA_PATTERN.match(s["text"].strip()))
        )
    ]
    if len(body_spans) >= 4:
        bx0s = sorted(s["bbox"][0] for s in body_spans)
        bx1s = sorted(s["bbox"][2] for s in body_spans)
        col_x0 = bx0s[int(len(bx0s) * 0.15)]
        col_x1 = bx1s[int(len(bx1s) * 0.85)]
    else:
        col_x0 = 0.15 * width
        col_x1 = 0.85 * width

    # 3. Extract atomic segments by splitting composite lines
    atomic_segments = []
    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            spans = [s for s in l.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue

            l_y0_norm = l["bbox"][1] / height
            l_y1_norm = l["bbox"][3] / height

            # Extreme top band: Running header
            if l_y1_norm <= 0.10 or (l_y0_norm <= 0.08 and l_y1_norm <= 0.12):
                atomic_segments.append({
                    "bbox": list(l["bbox"]),
                    "text": " ".join(s["text"].strip() for s in spans),
                    "size": sum(s["size"] for s in spans) / len(spans),
                    "type": "header_top",
                })
                continue

            # Extreme bottom band: Folio / page number
            if l_y0_norm >= 0.93:
                atomic_segments.append({
                    "bbox": list(l["bbox"]),
                    "text": " ".join(s["text"].strip() for s in spans),
                    "size": sum(s["size"] for s in spans) / len(spans),
                    "type": "header_bottom",
                })
                continue

            # Check if this line crosses left or right margin gutters
            has_left_margin = any(s["bbox"][2] <= col_x0 + 1.0 for s in spans) and (col_x0 > 0.10 * width)
            has_body_span = any(s["bbox"][0] >= col_x0 - 4.0 and s["bbox"][2] <= col_x1 + 4.0 for s in spans)
            has_right_margin = any(s["bbox"][0] >= col_x1 - 1.0 for s in spans) and (col_x1 < 0.90 * width)

            if has_left_margin and has_body_span:
                # Split composite line: left margin note vs body text
                m_spans = [s for s in spans if s["bbox"][2] <= col_x0 + 2.0]
                b_spans = [s for s in spans if s["bbox"][0] >= col_x0 - 3.0]
                if m_spans:
                    atomic_segments.append({
                        "bbox": [
                            min(s["bbox"][0] for s in m_spans),
                            min(s["bbox"][1] for s in m_spans),
                            max(s["bbox"][2] for s in m_spans),
                            max(s["bbox"][3] for s in m_spans),
                        ],
                        "text": " ".join(s["text"].strip() for s in m_spans),
                        "size": sum(s["size"] for s in m_spans) / len(m_spans),
                        "type": "marginalia_left",
                    })
                if b_spans:
                    atomic_segments.append({
                        "bbox": [
                            min(s["bbox"][0] for s in b_spans),
                            min(s["bbox"][1] for s in b_spans),
                            max(s["bbox"][2] for s in b_spans),
                            max(s["bbox"][3] for s in b_spans),
                        ],
                        "text": " ".join(s["text"].strip() for s in b_spans),
                        "size": sum(s["size"] for s in b_spans) / len(b_spans),
                        "type": "candidate_body",
                    })
            elif has_right_margin and has_body_span:
                # Split composite line: body text vs right margin note
                b_spans = [s for s in spans if s["bbox"][2] <= col_x1 + 3.0]
                m_spans = [s for s in spans if s["bbox"][0] >= col_x1 - 2.0]
                if b_spans:
                    atomic_segments.append({
                        "bbox": [
                            min(s["bbox"][0] for s in b_spans),
                            min(s["bbox"][1] for s in b_spans),
                            max(s["bbox"][2] for s in b_spans),
                            max(s["bbox"][3] for s in b_spans),
                        ],
                        "text": " ".join(s["text"].strip() for s in b_spans),
                        "size": sum(s["size"] for s in b_spans) / len(b_spans),
                        "type": "candidate_body",
                    })
                if m_spans:
                    atomic_segments.append({
                        "bbox": [
                            min(s["bbox"][0] for s in m_spans),
                            min(s["bbox"][1] for s in m_spans),
                            max(s["bbox"][2] for s in m_spans),
                            max(s["bbox"][3] for s in m_spans),
                        ],
                        "text": " ".join(s["text"].strip() for s in m_spans),
                        "size": sum(s["size"] for s in m_spans) / len(m_spans),
                        "type": "marginalia_right",
                    })
            else:
                # Standalone line
                avg_sz = sum(s["size"] for s in spans) / len(spans)
                txt = " ".join(s["text"].strip() for s in spans)
                txt_matches_marginalia = bool(MARGINALIA_PATTERN.match(txt))
                is_outer_left = l["bbox"][2] / width <= 0.32
                is_outer_right = l["bbox"][0] / width >= 0.68

                if (col_x0 > 0.10 * width and l["bbox"][2] <= col_x0 + 3.0) or (is_outer_left and txt_matches_marginalia):
                    t = "marginalia_left"
                elif (col_x1 < 0.90 * width and l["bbox"][0] >= col_x1 - 3.0) or (is_outer_right and txt_matches_marginalia):
                    t = "marginalia_right"
                else:
                    t = "candidate_body"
                atomic_segments.append({
                    "bbox": list(l["bbox"]),
                    "text": txt,
                    "size": avg_sz,
                    "type": t,
                })

    # 4. Footnote apparatus detection in lower region
    cand_body = [s for s in atomic_segments if s["type"] == "candidate_body"]
    cand_body.sort(key=lambda s: s["bbox"][1])
    footnote_start_y = 999999.0
    for s in cand_body:
        y0_norm = s["bbox"][1] / height
        is_fn_font = s["size"] <= 0.88 * body_size
        is_fn_text = bool(FOOTNOTE_PATTERN.match(s["text"]))
        # Must be in lower region (>= 0.65) and match marker
        if y0_norm >= 0.65 and is_fn_text and (is_fn_font or y0_norm >= 0.72):
            footnote_start_y = s["bbox"][1] - 2.0
            break

    final_segments = []
    for s in atomic_segments:
        if s["type"] in ("header_top", "header_bottom", "marginalia_left", "marginalia_right"):
            final_segments.append(s)
        elif s["bbox"][1] >= footnote_start_y:
            final_segments.append({**s, "type": "footnote"})
        else:
            final_segments.append({**s, "type": "body"})

    return final_segments, col_x0, col_x1


def analyze_page_layout(page: fitz.Page, page_number: int) -> PageLayout:
    """
    Perform deep spatial classification and macrozone aggregation on a PDF page:
    1. Untangles composite lines at the span level (separating margin notes from body lines).
    2. Identifies header, footer, left/right marginalia, body, and footnote apparatus.
    3. Consolidates peripheral zones into unified macrozones.
    4. Sorts body reading columns via XY-Cut and binds marginalia/apparatus.
    """
    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)

    if width <= 0 or height <= 0:
        return PageLayout(page_number=page_number, width=612.0, height=792.0, blocks=[])

    # 1. Extract atomic segments
    segments, col_x0, col_x1 = _extract_atomic_segments(page, width, height, page_number)
    if not segments:
        return PageLayout(page_number=page_number, width=width, height=height, blocks=[])

    # 2. Detect vector containers (callouts) and image captions
    vector_containers = detect_vector_callouts(page, width, height)

    classified_segments: list[dict] = []
    for s in segments:
        n_box = normalize_bbox(s["bbox"], width, height)
        s_type = s["type"]

        # Check vector callout container containment
        if s_type == "body":
            if any(bbox_centroid_inside(c_box, n_box) for c_box in vector_containers):
                s_type = "callout"

        classified_segments.append({**s, "type": s_type})

    # 3. Macrozone Groups
    groups = {
        "header_top": [],
        "header_bottom": [],
        "marginalia_left": [],
        "marginalia_right": [],
        "footnote": [],
        "callout": [],
        "body": [],
    }

    for s in classified_segments:
        groups[s["type"]].append(s)

    consolidated_peripheral: list[dict] = []

    # Running Header
    if groups["header_top"]:
        h_list = groups["header_top"]
        h_list.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
        hx0 = min(s["bbox"][0] for s in h_list)
        hy0 = min(s["bbox"][1] for s in h_list)
        hx1 = max(s["bbox"][2] for s in h_list)
        hy1 = max(s["bbox"][3] for s in h_list)
        htxt = " ".join(s["text"].strip() for s in h_list if s["text"].strip())
        consolidated_peripheral.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "type": "header_footer",
            "bbox": normalize_bbox([hx0, hy0, hx1, hy1], width, height),
            "text": htxt,
            "audio_muted": True,
            "order": None,
        })

    # Bottom Folio / Footer
    if groups["header_bottom"]:
        f_list = groups["header_bottom"]
        f_list.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
        fx0 = min(s["bbox"][0] for s in f_list)
        fy0 = min(s["bbox"][1] for s in f_list)
        fx1 = max(s["bbox"][2] for s in f_list)
        fy1 = max(s["bbox"][3] for s in f_list)
        ftxt = " ".join(s["text"].strip() for s in f_list if s["text"].strip())
        consolidated_peripheral.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "type": "header_footer",
            "bbox": normalize_bbox([fx0, fy0, fx1, fy1], width, height),
            "text": ftxt,
            "audio_muted": True,
            "order": None,
        })

    # Left Marginalia Macrozone
    if groups["marginalia_left"]:
        ml_list = groups["marginalia_left"]
        ml_list.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
        lx0 = min(s["bbox"][0] for s in ml_list)
        ly0 = min(s["bbox"][1] for s in ml_list)
        lx1 = max(s["bbox"][2] for s in ml_list)
        ly1 = max(s["bbox"][3] for s in ml_list)
        ltxt = "\n".join(s["text"].strip() for s in ml_list if s["text"].strip())
        consolidated_peripheral.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "type": "marginalia",
            "bbox": normalize_bbox([lx0, ly0, lx1, ly1], width, height),
            "text": ltxt,
            "audio_muted": True,
            "order": None,
        })

    # Right Marginalia Macrozone
    if groups["marginalia_right"]:
        mr_list = groups["marginalia_right"]
        mr_list.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
        rx0 = min(s["bbox"][0] for s in mr_list)
        ry0 = min(s["bbox"][1] for s in mr_list)
        rx1 = max(s["bbox"][2] for s in mr_list)
        ry1 = max(s["bbox"][3] for s in mr_list)
        rtxt = "\n".join(s["text"].strip() for s in mr_list if s["text"].strip())
        consolidated_peripheral.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "type": "marginalia",
            "bbox": normalize_bbox([rx0, ry0, rx1, ry1], width, height),
            "text": rtxt,
            "audio_muted": True,
            "order": None,
        })

    # Footnote Apparatus Macrozone
    if groups["footnote"]:
        fn_list = groups["footnote"]
        fn_list.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
        fx0 = min(s["bbox"][0] for s in fn_list)
        fy0 = min(s["bbox"][1] for s in fn_list)
        fx1 = max(s["bbox"][2] for s in fn_list)
        fy1 = max(s["bbox"][3] for s in fn_list)
        fntxt = "\n".join(s["text"].strip() for s in fn_list if s["text"].strip())
        consolidated_peripheral.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "type": "footnote",
            "bbox": normalize_bbox([fx0, fy0, fx1, fy1], width, height),
            "text": fntxt,
            "audio_muted": True,
            "order": None,
        })

    # Callouts
    for c in groups["callout"]:
        consolidated_peripheral.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "type": "callout",
            "bbox": normalize_bbox(c["bbox"], width, height),
            "text": c["text"],
            "order": None,
            "audio_muted": False,
        })

    # 4. Body Reading Blocks
    consolidated_body_blocks: list[dict] = []
    if groups["body"]:
        b_list = groups["body"]
        b_list.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))

        # Cluster body lines into unified columns (single column merges all into 1 macrozone)
        cols = _cluster_body_columns(b_list, width, height)
        for c_list in cols:
            cb_x0 = min(s["bbox"][0] for s in c_list)
            cb_y0 = min(s["bbox"][1] for s in c_list)
            cb_x1 = max(s["bbox"][2] for s in c_list)
            cb_y1 = max(s["bbox"][3] for s in c_list)
            cb_text = "\n".join(s["text"].strip() for s in c_list if s["text"].strip())
            consolidated_body_blocks.append({
                "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
                "type": "body",
                "bbox": normalize_bbox([cb_x0, cb_y0, cb_x1, cb_y1], width, height),
                "text": cb_text,
            })

    # Sort body blocks via recursive_xy_cut for natural reading order
    sorted_body = recursive_xy_cut(consolidated_body_blocks, bbox_key="bbox") if consolidated_body_blocks else []
    final_body_blocks: list[dict] = []
    current_order = 1
    for b in sorted_body:
        b_copy = dict(b)
        b_copy["order"] = current_order
        b_copy["audio_muted"] = False
        current_order += 1
        final_body_blocks.append(b_copy)

    # 5. Bind peripheral blocks to nearest vertical body paragraph
    final_peripheral_blocks: list[dict] = []
    for p in consolidated_peripheral:
        p_copy = dict(p)
        if p["type"] in {"marginalia", "footnote"} and final_body_blocks:
            nearest = min(
                final_body_blocks,
                key=lambda body_b: bbox_vertical_distance(p["bbox"], body_b["bbox"]),
            )
            p_copy["associated_para_id"] = nearest["id"]
        else:
            p_copy["associated_para_id"] = None
        final_peripheral_blocks.append(p_copy)

    # 6. Combine all blocks
    all_blocks = final_body_blocks + final_peripheral_blocks

    layout_blocks = [
        LayoutBlock(
            id=b["id"],
            type=b["type"],
            order=b.get("order"),
            audio_muted=b.get("audio_muted", False),
            bbox=b["bbox"],
            text=b["text"],
            confidence=1.0,
            associated_para_id=b.get("associated_para_id"),
        )
        for b in all_blocks
    ]

    return PageLayout(
        page_number=page_number,
        width=round(width, 2),
        height=round(height, 2),
        blocks=layout_blocks,
    )
