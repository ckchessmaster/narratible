import uuid
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
)
from .extractor import extract_block_text


def _extract_spatial_blocks(page: fitz.Page, width: float, height: float, page_number: int) -> list[dict]:
    """
    Extract text lines from PyMuPDF dict and cluster them into true spatial blocks.
    Unlike page.get_text("blocks"), this does NOT merge lines separated by horizontal gutters
    (such as marginalia sharing the same baseline with a body line).
    """
    page_dict = page.get_text("dict") or {}
    raw_lines: list[dict] = []

    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            txt = "".join(s.get("text", "") for s in l.get("spans", [])).strip()
            if not txt:
                continue
            l_bbox = l.get("bbox")
            if l_bbox and len(l_bbox) == 4:
                raw_lines.append({
                    "bbox": l_bbox,
                    "text": txt,
                })

    if not raw_lines:
        return []

    # Sort lines primarily top-to-bottom, secondarily left-to-right
    raw_lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))

    # Cluster lines into blocks:
    # Lines belong to the same block if they are vertically close and horizontally aligned.
    clusters: list[list[dict]] = []
    for line in raw_lines:
        bx0, by0, bx1, by1 = line["bbox"]
        line_h = max(8.0, by1 - by0)
        matched_cluster = None

        for cl in reversed(clusters):
            last_line = cl[-1]
            lx0, ly0, lx1, ly1 = last_line["bbox"]
            v_gap = by0 - ly1

            # Check if this line is directly below the last line in this cluster
            # (within 2.2 line heights) and shares significant horizontal column overlap
            h_overlap = min(bx1, lx1) - max(bx0, lx0)
            h_dist_left = abs(bx0 - lx0)

            if 0 <= v_gap <= (2.2 * line_h) and (h_overlap > 0 or h_dist_left < 20.0):
                matched_cluster = cl
                break

        if matched_cluster is not None:
            matched_cluster.append(line)
        else:
            clusters.append([line])

    # Convert clusters into blocks with combined bbox and text
    blocks: list[dict] = []
    for cl in clusters:
        cb_x0 = min(l["bbox"][0] for l in cl)
        cb_y0 = min(l["bbox"][1] for l in cl)
        cb_x1 = max(l["bbox"][2] for l in cl)
        cb_y1 = max(l["bbox"][3] for l in cl)
        combined_text = "\n".join(l["text"] for l in cl).strip()
        if not combined_text:
            continue

        n_box = normalize_bbox([cb_x0, cb_y0, cb_x1, cb_y1], width, height)
        blocks.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "bbox": n_box,
            "text": combined_text,
        })

    return blocks


def analyze_page_layout(page: fitz.Page, page_number: int) -> PageLayout:
    """
    Perform deep spatial classification on a PDF page:
    1. Extract vector callout containers and images.
    2. Classify raw text blocks into semantic types (body, marginalia, footnote,
       callout, figure_caption, header_footer).
    3. Sort body blocks via Recursive XY-Cut multi-column ordering.
    4. Bind marginalia/footnotes to nearest vertical body paragraph.
    5. Assign sequential narration order and audio muting flags.
    """
    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)

    if width <= 0 or height <= 0:
        return PageLayout(page_number=page_number, width=612.0, height=792.0, blocks=[])

    # 1. Extract true spatial blocks via line clustering
    initial_blocks = _extract_spatial_blocks(page, width, height, page_number)

    if not initial_blocks:
        return PageLayout(page_number=page_number, width=width, height=height, blocks=[])

    # 2. Detect vector containers (callouts) and image captions
    vector_containers = detect_vector_callouts(page, width, height)
    _, caption_indices = detect_images_and_captions(page, initial_blocks, width, height)

    # 3. Determine body column limits for Verso/Recto margins
    body_xmin, body_xmax = compute_body_column_bounds(initial_blocks)

    # 4. Classify each block
    classified: list[dict] = []
    for idx, b in enumerate(initial_blocks):
        n_box = b["bbox"]
        txt = b["text"]
        b_type: BlockType = "body"

        # Check vector callout container containment
        is_in_container = any(
            bbox_centroid_inside(c_box, n_box) for c_box in vector_containers
        )

        if idx in caption_indices:
            b_type = "figure_caption"
        elif is_header_footer(n_box, txt):
            b_type = "header_footer"
        elif is_in_container:
            b_type = "callout"
        elif is_footnote(n_box, txt):
            b_type = "footnote"
        elif is_marginalia(n_box, txt, page_number, body_xmin, body_xmax):
            b_type = "marginalia"
        else:
            b_type = "body"

        classified.append({**b, "type": b_type})

    # 5. Separate body & callouts from peripheral blocks
    body_and_callout = [b for b in classified if b["type"] in {"body", "callout"}]
    peripheral = [b for b in classified if b["type"] not in {"body", "callout"}]

    # 6. Apply Recursive XY-Cut on body and callout blocks for natural column flow
    sorted_body = recursive_xy_cut(body_and_callout, bbox_key="bbox")

    # 7. Assign sequential order numbers to body/callout blocks
    final_body_blocks: list[dict] = []
    current_order = 1
    for b in sorted_body:
        b_copy = dict(b)
        b_copy["order"] = current_order
        b_copy["audio_muted"] = False
        current_order += 1
        final_body_blocks.append(b_copy)

    # 8. Peripheral blocks: marginalia, footnote, header_footer, figure_caption
    final_peripheral_blocks: list[dict] = []
    for p in peripheral:
        p_copy = dict(p)
        p_copy["order"] = None
        p_copy["audio_muted"] = True  # Peripheral notes default to muted in audio

        # Bind marginalia and footnotes to nearest body paragraph by vertical centroid
        if p["type"] in {"marginalia", "footnote"} and final_body_blocks:
            nearest = min(
                final_body_blocks,
                key=lambda body_b: bbox_vertical_distance(p["bbox"], body_b["bbox"])
            )
            p_copy["associated_para_id"] = nearest["id"]
        else:
            p_copy["associated_para_id"] = None

        final_peripheral_blocks.append(p_copy)

    # 9. Combine all blocks
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
