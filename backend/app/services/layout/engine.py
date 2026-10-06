import re
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
from .containers import detect_vector_callouts, detect_images_and_captions, CAPTION_PATTERN
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
    bw = x_max - x_min

    # Search for vertical gutters (empty vertical strips dividing columns)
    gutters = []
    x_step = 1.0
    min_col_w = min(40.0, 0.15 * bw)
    x_probe = x_min + min_col_w
    while x_probe < x_max - min_col_w:
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

        # A valid column dividing gutter must have width >= 6.0 points
        valid_gutters = [r for r in gutter_ranges if (r[1] - r[0]) >= 6.0]
        if valid_gutters:
            valid_gutters.sort(key=lambda r: r[0])
            splits = [(r[0] + r[1]) / 2.0 for r in valid_gutters]

            cols = [[] for _ in range(len(splits) + 1)]
            for s in body_segments:
                s_mid = (s["bbox"][0] + s["bbox"][2]) / 2.0
                assigned = False
                for idx, sp in enumerate(splits):
                    if s_mid < sp:
                        cols[idx].append(s)
                        assigned = True
                        break
                if not assigned:
                    cols[-1].append(s)

            non_empty_cols = [c for c in cols if c]
            if len(non_empty_cols) > 1:
                return non_empty_cols

    # Single column layout: All body segments belong to a single continuous column
    return [body_segments]


def analyze_page_layout(page: fitz.Page, page_number: int) -> PageLayout:
    """
    Perform deep spatial classification and macrozone aggregation on a PDF page:
    1. Untangles composite lines at span level (separating margin notes from body lines).
    2. Identifies images, vector callouts, and figure captions (muting them for narration).
    3. Multi-signal discrimination for running headers/footers vs top-of-page body text.
    4. Detects multi-column vertical gutters dynamically, producing separate column macrozones.
    5. Sorts body columns in natural reading order and binds peripheral notes to paragraphs.
    """
    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)

    if width <= 0 or height <= 0:
        return PageLayout(page_number=page_number, width=612.0, height=792.0, blocks=[])

    page_dict = page.get_text("dict") or {}
    page_area = width * height
    raw_imgs = page.get_image_info() or []
    img_boxes = []
    for img in raw_imgs:
        ib = img.get("bbox")
        if not ib:
            continue
        iw = ib[2] - ib[0]
        ih = ib[3] - ib[1]
        iarea = iw * ih
        # Filter full-page scan backgrounds (e.g. Internet Archive scanned books) and tiny noise
        if iarea >= 0.70 * page_area or (iw >= 0.85 * width and ih >= 0.85 * height) or iarea < 0.01 * page_area:
            continue
        img_boxes.append(ib)

    vector_containers = detect_vector_callouts(page, width, height)

    # Document metadata title if available
    doc_title = ""
    if hasattr(page, "parent") and page.parent:
        try:
            doc_title = (page.parent.metadata or {}).get("title") or ""
        except Exception:
            pass
    clean_doc_title = re.sub(r"[^a-zA-Z0-9]", "", doc_title).lower().replace("l", "i").replace("1", "i")

    # Pre-compute page-level body boundaries from substantial text lines
    wide_x0s, wide_x1s = [], []
    for b in page_dict.get("blocks", []):
        if b.get("type") == 0:
            for l in b.get("lines", []):
                lw = l["bbox"][2] - l["bbox"][0]
                if lw >= 0.35 * width:
                    wide_x0s.append(l["bbox"][0])
                    wide_x1s.append(l["bbox"][2])
    wide_x0s.sort()
    wide_x1s.sort()
    page_body_x0 = wide_x0s[len(wide_x0s) // 2] if wide_x0s else 0.15 * width
    page_body_x1 = wide_x1s[len(wide_x1s) // 2] if wide_x1s else 0.85 * width

    has_verified_left = any(
        MARGINALIA_PATTERN.match(" ".join(s["text"].strip() for s in l.get("spans", []) if s.get("text", "").strip()))
        for b in page_dict.get("blocks", []) if b.get("type") == 0
        for l in b.get("lines", [])
        if l["bbox"][2] / width <= 0.28
    )
    has_verified_right = any(
        MARGINALIA_PATTERN.match(" ".join(s["text"].strip() for s in l.get("spans", []) if s.get("text", "").strip()))
        for b in page_dict.get("blocks", []) if b.get("type") == 0
        for l in b.get("lines", [])
        if l["bbox"][0] / width >= 0.72
    )

    raw_segments: list[dict] = []

    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue

        b_txt = " ".join(
            s["text"].strip()
            for l in b.get("lines", [])
            for s in l.get("spans", [])
            if s.get("text", "").strip()
        )
        b_box = b.get("bbox", [0, 0, 0, 0])
        is_block_caption = bool(CAPTION_PATTERN.match(b_txt))

        # Check illustration proximity: immediately below an illustration (< 32 pt)
        is_block_under_img = any(
            0 <= (b_box[1] - ib[3]) <= 32.0 and max(b_box[0], ib[0]) < min(b_box[2], ib[2])
            for ib in img_boxes
        )
        # Check if block is inside an illustration box (like map or diagram labels)
        matched_img_idx = None
        for idx, ib in enumerate(img_boxes):
            if ib[0] - 2 <= b_box[0] and b_box[2] <= ib[2] + 2 and ib[1] - 2 <= b_box[1] and b_box[3] <= ib[3] + 2:
                matched_img_idx = idx
                break

        block_is_caption = is_block_caption or (
            is_block_under_img and len(b_txt) < 300 and not b_txt[:1].islower()
        )

        for l in b.get("lines", []):
            spans = [s for s in l.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue

            # Filter pure non-alphanumeric noise spans (floating punctuation, dust specks)
            clean_spans = []
            for s in spans:
                s_txt = s.get("text", "").strip()
                has_alnum = any(c.isalnum() for c in s_txt)
                is_tiny = (s["bbox"][2] - s["bbox"][0] < 5.0 and s["bbox"][3] - s["bbox"][1] < 5.0)
                is_edge_noise = not has_alnum and (s["bbox"][0] / width <= 0.12 or s["bbox"][2] / width >= 0.88 or s["bbox"][1] / height <= 0.05 or s["bbox"][3] / height >= 0.95)
                if (not has_alnum and is_tiny) or is_edge_noise:
                    continue
                clean_spans.append(s)

            if not clean_spans:
                continue
            spans = clean_spans

            # Split composite spans:
            # 1. Wide gutters (>= 10pt) for multi-column pages
            # 2. Outer margins with font size jump, boundary crossing, or marginalia pattern
            cur_spans = [spans[0]]
            for s in spans[1:]:
                prev_x1 = cur_spans[-1]["bbox"][2]
                curr_x0 = s["bbox"][0]
                prev_sz = cur_spans[-1]["size"]
                curr_sz = s["size"]
                s_txt = s["text"].strip()
                is_wide_gutter = (curr_x0 - prev_x1) >= 10.0

                crosses_left_bound = (prev_x1 < page_body_x0 - 0.5 and curr_x0 >= page_body_x0 - 2.0)
                crosses_right_bound = (prev_x1 <= page_body_x1 + 2.0 and curr_x0 > page_body_x1 + 0.5)

                in_left_margin = (prev_x1 < page_body_x0 - 1.0 or curr_x0 < page_body_x0 - 1.0)
                in_right_margin = (prev_x1 > page_body_x1 + 1.0 or curr_x0 > page_body_x1 + 1.0)

                sz_jump = (curr_sz >= 1.15 * prev_sz or curr_sz <= 0.85 * prev_sz)
                is_margin_split = (in_left_margin or in_right_margin) and (
                    crosses_left_bound
                    or crosses_right_bound
                    or sz_jump
                    or bool(MARGINALIA_PATTERN.match(s_txt))
                    or (curr_x0 - prev_x1 >= 4.0)
                )

                if is_wide_gutter or is_margin_split:
                    raw_segments.append({
                        "bbox": [
                            min(x["bbox"][0] for x in cur_spans),
                            min(x["bbox"][1] for x in cur_spans),
                            max(x["bbox"][2] for x in cur_spans),
                            max(x["bbox"][3] for x in cur_spans),
                        ],
                        "text": " ".join(x["text"].strip() for x in cur_spans if x["text"].strip()),
                        "size": sum(x["size"] for x in cur_spans) / len(cur_spans),
                        "is_block_caption": block_is_caption,
                        "matched_img_idx": matched_img_idx,
                    })
                    cur_spans = [s]
                else:
                    cur_spans.append(s)

            if cur_spans:
                raw_segments.append({
                    "bbox": [
                        min(x["bbox"][0] for x in cur_spans),
                        min(x["bbox"][1] for x in cur_spans),
                        max(x["bbox"][2] for x in cur_spans),
                        max(x["bbox"][3] for x in cur_spans),
                    ],
                    "text": " ".join(x["text"].strip() for x in cur_spans if x["text"].strip()),
                    "size": sum(x["size"] for x in cur_spans) / len(cur_spans),
                    "is_block_caption": block_is_caption,
                    "matched_img_idx": matched_img_idx,
                })

    if not raw_segments:
        return PageLayout(page_number=page_number, width=width, height=height, blocks=[])

    raw_segments.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))

    # Dominant typography size
    mid_spans = [s for s in raw_segments if 0.10 <= s["bbox"][1] / height <= 0.88]
    sizes = sorted(s["size"] for s in mid_spans) if mid_spans else [s["size"] for s in raw_segments]
    body_size = sizes[len(sizes) // 2] if sizes else 10.0

    # Dominant body boundaries from substantial lines
    substantial = [
        s for s in raw_segments
        if (s["bbox"][2] - s["bbox"][0]) >= 0.35 * width
        and len(s["text"].split()) >= 6
        and 0.10 <= s["bbox"][1] / height <= 0.88
    ]
    if substantial:
        body_xmin = min(s["bbox"][0] for s in substantial) / width
        body_xmax = max(s["bbox"][2] for s in substantial) / width
    else:
        body_xmin, body_xmax = 0.15, 0.85

    classified: list[dict] = []
    for s in raw_segments:
        x0, y0, x1, y1 = s["bbox"]
        txt = s["text"].strip()
        y0_norm = y0 / height
        y1_norm = y1 / height
        x0_norm = x0 / width
        x1_norm = x1 / width
        seg_w_norm = (x1 - x0) / width

        # 1. Figure Caption / image container
        if s.get("matched_img_idx") is not None:
            classified.append({**s, "type": "figure_caption", "img_group": s["matched_img_idx"]})
            continue

        if s.get("is_block_caption") or bool(CAPTION_PATTERN.match(txt)):
            classified.append({**s, "type": "figure_caption", "img_group": None})
            continue

        # Check vector callout container
        n_box = normalize_bbox(s["bbox"], width, height)
        is_in_vector_callout = any(bbox_centroid_inside(c_box, n_box) for c_box in vector_containers)
        if is_in_vector_callout:
            classified.append({**s, "type": "callout"})
            continue

        # 2. Bottom folio / footer
        if y0_norm >= 0.92 and (len(txt) <= 30 or not FOOTNOTE_PATTERN.match(txt)):
            classified.append({**s, "type": "header_bottom"})
            continue

        # 3. Running Header (extreme top band or top treatise title)
        clean_txt = re.sub(r"[^a-zA-Z0-9]", "", txt).lower().replace("l", "i").replace("1", "i")
        matches_doc_title = bool(
            clean_doc_title
            and len(clean_doc_title) >= 5
            and (
                clean_doc_title in clean_txt
                or (len(clean_txt) >= int(0.7 * len(clean_doc_title)) and clean_txt in clean_doc_title)
            )
        )

        # Strip common folio tokens like Roman numerals or digits to evaluate title casing
        tokens = txt.split()
        non_folio_tokens = [t for t in tokens if not re.match(r"^[ivxlcdm0-9!j\.\-]+$", t, re.I)]
        eval_txt = " ".join(non_folio_tokens) if non_folio_tokens else txt
        alpha_chars = [c for c in eval_txt if c.isalpha()]
        is_ocr_allcaps = bool(alpha_chars) and (sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) >= 0.85)

        is_top_band = y1_norm <= 0.12 or (y0_norm <= 0.08 and y1_norm <= 0.15)
        is_opening_title = (0.12 < y0_norm <= 0.35 and matches_doc_title and is_ocr_allcaps)

        if is_opening_title:
            classified.append({**s, "type": "heading"})
            continue

        if is_top_band:
            is_allcaps_title = is_ocr_allcaps and 1 <= len(tokens) <= 10
            is_folio = bool(re.match(r"^\[?[ivxlcdm0-9!j\s\.\-]+\]?$", txt, re.I)) and len(txt) <= 12

            next_segs = [
                ns for ns in raw_segments
                if (ns["bbox"][1] + ns["bbox"][3]) / 2.0 > (y0 + y1) / 2.0
                and max(x0, ns["bbox"][0]) < min(x1, ns["bbox"][2])
            ]
            has_gap = False
            if next_segs:
                min_next_y0 = min(ns["bbox"][1] for ns in next_segs)
                line_h = max(8.0, y1 - y0)
                vert_dist = max(0.0, min_next_y0 - y1)
                has_gap = (vert_dist >= 1.8 * line_h)

            is_short = len(txt) <= 60
            is_continuation = txt[:1].islower()

            if matches_doc_title or is_allcaps_title or is_folio or (y1_norm <= 0.09 and has_gap and is_short and not is_continuation):
                classified.append({**s, "type": "header_top"})
                continue

        # 4. Marginalia: outer page gutters with verified page context
        is_vert_margin_zone = (0.08 <= y0_norm and y1_norm <= 0.92)
        is_outside_left = is_vert_margin_zone and (x1_norm <= body_xmin + 0.02 and x1_norm <= 0.28)
        is_outside_right = is_vert_margin_zone and (x0_norm >= body_xmax - 0.02 and x0_norm >= 0.72)
        matches_marginalia = bool(MARGINALIA_PATTERN.match(txt))
        has_multi_words = len(txt.split()) >= 2 and any(c.isalpha() for c in txt)

        if is_outside_left:
            if has_verified_left or matches_marginalia or has_multi_words:
                classified.append({**s, "type": "marginalia_left"})
                continue
            else:
                # Stray gutter dust on page with no marginalia apparatus
                continue
        if is_outside_right:
            if has_verified_right or matches_marginalia or has_multi_words:
                classified.append({**s, "type": "marginalia_right"})
                continue
            else:
                # Stray gutter dust on page with no marginalia apparatus
                continue
        if is_vert_margin_zone and (x1_norm <= 0.28 or x0_norm >= 0.72) and matches_marginalia and seg_w_norm <= 0.25:
            t = "marginalia_left" if x1_norm <= 0.35 else "marginalia_right"
            classified.append({**s, "type": t})
            continue

        # 5. Footnote: must sit within the column width (NOT strictly in outer margins)
        if y0_norm >= 0.65 and bool(FOOTNOTE_PATTERN.match(txt)) and not is_outside_right and not is_outside_left:
            classified.append({**s, "type": "footnote"})
            continue

        classified.append({**s, "type": "candidate_body"})

    # Check footnote apparatus continuation at bottom (ONLY for small typography)
    fn_y0s = [s["bbox"][1] for s in classified if s["type"] == "footnote"]
    if fn_y0s:
        min_fn_y = min(fn_y0s) - 2.0
        for s in classified:
            if s["type"] == "candidate_body" and s["bbox"][1] >= min_fn_y and (s["bbox"][1] / height) >= 0.70:
                if s["size"] <= 0.92 * body_size:
                    s["type"] = "footnote"

    # Macrozone Groups
    groups = {
        "header_top": [],
        "header_bottom": [],
        "marginalia_left": [],
        "marginalia_right": [],
        "footnote": [],
        "callout": [],
        "figure_caption": [],
        "heading": [],
        "body": [],
    }

    for s in classified:
        t = s["type"]
        if t == "candidate_body":
            groups["body"].append(s)
        else:
            groups[t].append(s)

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

    # Left Marginalia
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

    # Right Marginalia
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

    # Footnote Apparatus
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

    # Figure Captions & diagram containers:
    # 1. Group segments inside illustrations by image index
    img_groups: dict[int, list[dict]] = {}
    other_captions: list[dict] = []
    for s in groups["figure_caption"]:
        g_idx = s.get("img_group")
        if g_idx is not None:
            if g_idx not in img_groups:
                img_groups[g_idx] = []
            img_groups[g_idx].append(s)
        else:
            other_captions.append(s)

    # Add 1 consolidated block per illustration containing internal labels (e.g. US map)
    for g_idx, g_segs in img_groups.items():
        gx0 = min(s["bbox"][0] for s in g_segs)
        gy0 = min(s["bbox"][1] for s in g_segs)
        gx1 = max(s["bbox"][2] for s in g_segs)
        gy1 = max(s["bbox"][3] for s in g_segs)
        gtxt = "\n".join(s["text"].strip() for s in g_segs if s["text"].strip())
        consolidated_peripheral.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "type": "figure_caption",
            "bbox": normalize_bbox([gx0, gy0, gx1, gy1], width, height),
            "text": gtxt,
            "audio_muted": True,
            "order": None,
        })

    # Other figure captions clustered by vertical proximity
    if other_captions:
        other_captions.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
        cap_clusters = []
        for c_seg in other_captions:
            if not cap_clusters:
                cap_clusters.append([c_seg])
            else:
                last_c = cap_clusters[-1][-1]
                v_dist = c_seg["bbox"][1] - last_c["bbox"][3]
                h_overlap = min(c_seg["bbox"][2], last_c["bbox"][2]) - max(c_seg["bbox"][0], last_c["bbox"][0])
                if 0 <= v_dist <= 25.0 and (h_overlap > -20.0):
                    cap_clusters[-1].append(c_seg)
                else:
                    cap_clusters.append([c_seg])

        for c_cl in cap_clusters:
            cx0 = min(s["bbox"][0] for s in c_cl)
            cy0 = min(s["bbox"][1] for s in c_cl)
            cx1 = max(s["bbox"][2] for s in c_cl)
            cy1 = max(s["bbox"][3] for s in c_cl)
            ctxt = "\n".join(s["text"].strip() for s in c_cl if s["text"].strip())
            consolidated_peripheral.append({
                "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
                "type": "figure_caption",
                "bbox": normalize_bbox([cx0, cy0, cx1, cy1], width, height),
                "text": ctxt,
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

    # Headings and Body Columns
    consolidated_body_blocks: list[dict] = []
    for h in groups["heading"]:
        consolidated_body_blocks.append({
            "id": f"blk_{page_number}_{uuid.uuid4().hex[:6]}",
            "type": "heading",
            "bbox": normalize_bbox(h["bbox"], width, height),
            "text": h["text"],
        })

    if groups["body"]:
        cols = _cluster_body_columns(groups["body"], width, height)
        for c_list in cols:
            c_list.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
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

    # Bind peripheral blocks to nearest vertical body paragraph
    final_peripheral_blocks: list[dict] = []
    for p in consolidated_peripheral:
        p_copy = dict(p)
        if p["type"] in {"marginalia", "footnote", "figure_caption"} and final_body_blocks:
            nearest = min(
                final_body_blocks,
                key=lambda body_b: bbox_vertical_distance(p["bbox"], body_b["bbox"]),
            )
            p_copy["associated_para_id"] = nearest["id"]
        else:
            p_copy["associated_para_id"] = None
        final_peripheral_blocks.append(p_copy)

    # Combine all blocks
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
