import re
from typing import Sequence
import pymupdf as fitz

from .geometry import normalize_bbox, bbox_area

CAPTION_PATTERN = re.compile(
    r"^(?:Figure|Fig\.|Table|Plate|Diagram|Illustration|Photo)\s+[\dA-Za-z\.\-]+",
    re.IGNORECASE,
)


def detect_vector_callouts(
    page: fitz.Page,
    width: float,
    height: float,
    min_area_ratio: float = 0.04,
) -> list[list[float]]:
    """
    Detect vector card boxes (shaded backgrounds, bordered cards, callouts)
    using page.get_drawings().
    Returns a list of normalized bounding boxes [x0, y0, x1, y1].
    """
    callouts: list[list[float]] = []
    page_area = width * height
    if page_area <= 0:
        return callouts

    try:
        drawings = page.get_drawings()
    except Exception:
        return callouts

    for d in drawings:
        rect = d.get("rect")
        if not rect:
            continue
        # PyMuPDF Rect: x0, y0, x1, y1
        r_area = rect.width * rect.height
        # Check if the shape has fill color or stroke border and has meaningful size
        has_fill = bool(d.get("fill"))
        has_color = bool(d.get("color"))
        is_card_sized = (r_area >= min_area_ratio * page_area) and (r_area < 0.90 * page_area)
        
        # Don't capture full page backgrounds or tiny decoration lines
        if is_card_sized and (has_fill or has_color):
            n_box = normalize_bbox([rect.x0, rect.y0, rect.x1, rect.y1], width, height)
            # Avoid duplicate or near-identical boxes
            if not any(
                abs(n_box[0] - ex[0]) < 0.02
                and abs(n_box[1] - ex[1]) < 0.02
                and abs(n_box[2] - ex[2]) < 0.02
                and abs(n_box[3] - ex[3]) < 0.02
                for ex in callouts
            ):
                callouts.append(n_box)

    return callouts


def detect_images_and_captions(
    page: fitz.Page,
    text_blocks: Sequence[dict],
    width: float,
    height: float,
) -> tuple[list[list[float]], set[int]]:
    """
    Detect raster image bounding boxes and bind nearby figure captions.
    Returns (image_bboxes, caption_block_indices).
    """
    image_boxes: list[list[float]] = []
    caption_indices: set[int] = set()

    try:
        img_info = page.get_image_info()
    except Exception:
        return image_boxes, caption_indices

    for img in img_info:
        bbox = img.get("bbox")
        if not bbox:
            continue
        n_img = normalize_bbox(bbox, width, height)
        if bbox_area(n_img) >= 0.02:  # Ignore tiny icon decorations
            image_boxes.append(n_img)

    # Check text blocks for figure caption patterns or vertical proximity to images
    for idx, b in enumerate(text_blocks):
        text = b.get("text", "").strip()
        n_box = b.get("bbox")
        if not text or not n_box:
            continue

        is_caption_text = bool(CAPTION_PATTERN.match(text))
        
        # Check if right below or above an image box (within ~0.06 normalized height)
        is_near_image = False
        for img_b in image_boxes:
            vert_dist = n_box[1] - img_b[3]
            if 0 <= vert_dist <= 0.06 and (
                (img_b[0] <= n_box[0] <= img_b[2]) or (img_b[0] <= n_box[2] <= img_b[2])
            ):
                is_near_image = True
                break

        if is_caption_text or (is_near_image and len(text) < 160):
            caption_indices.add(idx)

    return image_boxes, caption_indices
