from typing import Literal, Optional
from pydantic import BaseModel, Field

BlockType = Literal[
    "body",
    "heading",
    "marginalia",
    "footnote",
    "callout",
    "figure_caption",
    "header_footer",
]


class LayoutBlock(BaseModel):
    id: str
    type: BlockType = "body"
    format: Literal["prose", "verse"] = "prose"
    order: Optional[int] = None
    audio_muted: bool = False
    bbox: list[float]  # Normalized coordinates [x0, y0, x1, y1] where 0.0 <= val <= 1.0
    text: str = ""
    confidence: float = 1.0
    associated_para_id: Optional[str] = None  # id of the body paragraph this note aligns with


class PageLayout(BaseModel):
    page_number: int
    width: float
    height: float
    blocks: list[LayoutBlock] = Field(default_factory=list)


class LayoutUpdateRequest(BaseModel):
    blocks: list[LayoutBlock]
    reextract_text: bool = True


class LayoutPropagateRequest(BaseModel):
    mode: Literal["single", "alternating"] = "alternating"
    template_page: Optional[int] = None
    template_even_page: Optional[int] = None
    template_odd_page: Optional[int] = None
    target_start_page: int
    target_end_page: int
    reextract_all: bool = True
