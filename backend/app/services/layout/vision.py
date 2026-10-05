import json
import logging
import uuid
from typing import Any
from ...config import load_config
from .models import LayoutBlock, BlockType

logger = logging.getLogger(__name__)

VISION_LAYOUT_PROMPT = """
You are an expert document layout and academic typography analysis engine.
Analyze this scanned document page image carefully.

Separate the text on this page into four semantic layout categories:
1. "body_text": The main narrative prose, headings, and continuous reading text in natural reading order. Do NOT include margin notes, footnotes, or running headers/footers here.
2. "marginalia": Any marginal references, biblical scripture citations (e.g. 'cf. John viii. 26'), dates, or commentary printed in the outer or side margins.
3. "footnotes": Scholarly footnotes or apparatus at the bottom of the page (usually numbered 1, 2, 3... or with symbols *, †).
4. "callouts": Text inside framed, shaded, or bordered cards, sidebars, or 'Did You Know?' boxes.

Return a JSON object strictly matching this schema:
{
  "body_paragraphs": ["first paragraph...", "second paragraph..."],
  "marginalia": ["margin note 1...", "margin note 2..."],
  "footnotes": ["footnote 1...", "footnote 2..."],
  "callouts": ["callout text..."]
}
"""


async def extract_layout_via_vision(
    image_bytes: bytes,
    page_number: int,
    provider: str = "gemini",
    model: str = "gemini-2.0-flash",
) -> list[LayoutBlock]:
    """
    Submit page image to multimodal LLM (Gemini / OpenAI) with structured output
    to extract semantic zones from degraded scans.
    """
    cfg = load_config()
    blocks: list[LayoutBlock] = []

    if provider == "gemini" or (provider == "auto" and cfg.gemini_api_key):
        if not cfg.gemini_api_key:
            raise ValueError("Gemini API key is not configured in settings.")

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=cfg.gemini_api_key)
            vision_model = model if model.startswith("gemini") else "gemini-2.0-flash"

            response = client.models.generate_content(
                model=vision_model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    VISION_LAYOUT_PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            raw_json = response.text or "{}"
            data = json.loads(raw_json)
        except Exception as e:
            logger.exception("Gemini Vision extraction failed: %s", e)
            raise RuntimeError(f"Vision extraction failed: {e}") from e

    elif provider == "openai" or (provider == "auto" and cfg.openai_api_key):
        if not cfg.openai_api_key:
            raise ValueError("OpenAI API key is not configured in settings.")

        try:
            import base64
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=cfg.openai_api_key)
            b64_img = base64.b64encode(image_bytes).decode("utf-8")
            openai_model = model if "gpt" in model else "gpt-4o-mini"

            response = await client.chat.completions.create(
                model=openai_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_LAYOUT_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                            },
                        ],
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw_json = response.choices[0].message.content or "{}"
            data = json.loads(raw_json)
        except Exception as e:
            logger.exception("OpenAI Vision extraction failed: %s", e)
            raise RuntimeError(f"OpenAI Vision extraction failed: {e}") from e
    else:
        raise ValueError("No vision LLM provider configured with a valid API key.")

    # Convert structured JSON data to LayoutBlock list
    order = 1

    # 1. Body paragraphs
    body_paras = data.get("body_paragraphs") or []
    if isinstance(body_paras, str):
        body_paras = [p.strip() for p in body_paras.split("\n\n") if p.strip()]

    # Estimate normalized vertical slicing for body paragraphs
    num_paras = max(1, len(body_paras))
    para_h = 0.70 / num_paras

    for i, p_text in enumerate(body_paras):
        if not p_text.strip():
            continue
        y0 = round(0.12 + (i * para_h), 4)
        y1 = round(min(0.85, y0 + para_h - 0.01), 4)
        blocks.append(
            LayoutBlock(
                id=f"blk_v_{page_number}_{uuid.uuid4().hex[:6]}",
                type="body",
                order=order,
                audio_muted=False,
                bbox=[0.24, y0, 0.92, y1],
                text=p_text.strip(),
                confidence=0.95,
            )
        )
        order += 1

    # 2. Callouts
    callouts = data.get("callouts") or []
    for c_text in callouts:
        if not c_text.strip():
            continue
        blocks.append(
            LayoutBlock(
                id=f"blk_v_{page_number}_{uuid.uuid4().hex[:6]}",
                type="callout",
                order=order,
                audio_muted=False,
                bbox=[0.20, 0.20, 0.80, 0.35],
                text=c_text.strip(),
                confidence=0.95,
            )
        )
        order += 1

    # 3. Marginalia
    marginalia = data.get("marginalia") or []
    first_body_id = blocks[0].id if blocks else None
    for i, m_text in enumerate(marginalia):
        if not m_text.strip():
            continue
        m_y0 = round(0.12 + (i * 0.15), 4)
        m_y1 = round(min(0.85, m_y0 + 0.12), 4)
        # Check even/odd page for outer margin placement
        is_even = (page_number % 2 == 0)
        m_bbox = [0.05, m_y0, 0.22, m_y1] if is_even else [0.78, m_y0, 0.95, m_y1]
        blocks.append(
            LayoutBlock(
                id=f"blk_v_{page_number}_{uuid.uuid4().hex[:6]}",
                type="marginalia",
                order=None,
                audio_muted=True,
                bbox=m_bbox,
                text=m_text.strip(),
                confidence=0.95,
                associated_para_id=first_body_id,
            )
        )

    # 4. Footnotes
    footnotes = data.get("footnotes") or []
    for i, fn_text in enumerate(footnotes):
        if not fn_text.strip():
            continue
        fn_y0 = round(0.85 + (i * 0.05), 4)
        fn_y1 = round(min(0.98, fn_y0 + 0.045), 4)
        blocks.append(
            LayoutBlock(
                id=f"blk_v_{page_number}_{uuid.uuid4().hex[:6]}",
                type="footnote",
                order=None,
                audio_muted=True,
                bbox=[0.24, fn_y0, 0.92, fn_y1],
                text=fn_text.strip(),
                confidence=0.95,
                associated_para_id=first_body_id,
            )
        )

    return blocks
