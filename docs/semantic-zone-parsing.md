PLAN: Intelligent Layout Engine, Semantic Block Zoning & Academic PDF Parsing
1. Objective & Scope
Enhance Narratible's document ingestion layer to parse complex documents (multi-column textbooks, academic scans with alternating margin notes, footers, callout boxes, and figures) without sentence corruption or audio interleaving.
Primary Objectives:
Spatial Document Object Model (DOM): Move from flat text extraction to semantic block classification (body, marginalia, footnote, callout, figure_caption, header_footer).
Verso/Recto & Multi-Column Resilience: Automatically isolate alternating outer margins (even vs. odd pages), multi-column text gutters (Recursive XY-Cut), and bottom footnote blocks.
Multimodal Vision Fallback: Provide on-demand Gemini 2.0 Flash / OpenAI vision extraction for degraded historical scans where local OCR coordinates fail.
Interactive Visual Zoning UI: Add an interactive SVG/Canvas overlay in the Source Inspector allowing users to visualize, draw, re-order, and re-tag layout bounding boxes.
Template & Propagation Engine: Enable single-click layout cloning and alternating even/odd template propagation across multi-page ranges.
2. Semantic Block Model & Audio/EPUB Mapping
Every page is partitioned into typed bounding blocks. Each block carries distinct export instructions for TTS vs. EPUB:
Block Type
Semantic Purpose
EPUB Export Target
Audiobook (TTS) Engine
body
Primary narrative prose
Standard flowing <p> / <div>
Spoken in sequential reading order
marginalia
Scripture refs, dates, section citations
<aside epub:type="marginalia">
Muted by default (prevents audio line interruptions)
footnote
Numbered apparatus / scholarly notes
<aside epub:type="footnote"> (linked)
Muted by default
callout
Shaded cards, "Did You Know?", case studies
<aside class="callout">
Deferred to section end or narrated
figure_caption
Image captions, table labels
<figcaption> attached to image
Skipped entirely
header_footer
Running titles, folio numbers, book title
Omitted / CSS paged media rules
Skipped entirely

3. Extraction Architecture: Multi-Tier Layout Pipeline



                                [ Input PDF Page ]
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
        [ Digital PDF with Vector/Text ]            [ Legacy Raster Scan ]
                    │                                       │
      1. PyMuPDF `page.get_drawings()`                      │
         (Detect shaded callout boxes)                      │
                    │                                       │
      2. PyMuPDF `page.get_image_info()`                    │
         (Isolate figures & bind captions)                  │
                    │                                       │
      3. Geometry & Recursive XY-Cut                        │
         (Header/Footer stripping, gutter detection)        │
                    │                                       │
      4. Verso/Recto Margin Classifier                      ▼
         (Alternating outer edge filtering)       [ Multimodal Vision Fallback ]
                    │                             (Gemini 2.0 Flash / OpenAI)
                    ▼                             (Structured JSON output)
         [ Classified Block Tree ]                          │
                    │                                       │
                    └───────────────────┬───────────────────┘
                                        ▼
                      [ Normalized Layout Blocks JSON ]
                                        │
                           (Source Inspector UI)
                     [ User Verification & Override ]


Layer 1: Vector Drawing Detection (Callout Boxes)
Query page.get_drawings() in PyMuPDF (fitz).
Detect filled or stroked rectangular paths with area $> 5\%$ of page dimensions.
Any text block whose centroid falls within a detected vector container is classified as callout.
Layer 2: Image & Caption Binding
Query page.get_image_info() for raster image bounding boxes.
Detect nearby text blocks within 30 vertical points matching caption heuristics (^(Figure|Fig\.|Table|Plate)\s+\d+ or font size $< \text{median body font}$).
Tag as figure_caption and bind to the corresponding image asset.
Layer 3: Dynamic Verso/Recto & Margin Classifier
Textbooks and academic editions (e.g., Tertullian Against Praxeas) alternate margins across even and odd pages:
Header / Footer Bands: Strip blocks where $y_1 \le 0.08 \times \text{height}$ or $y_0 \ge 0.92 \times \text{height}$ (unless starting with a footnote indicator).
Body Core Bounding Box: Calculate horizontal text mass histogram across non-header blocks to find the dominant body column boundaries $[X_{\min}, X_{\max}]$.
Alternating Outer Margins:
Even Pages (Verso): Outer margin is on the left ($x_1 < X_{\min} - 15\text{pt}$).
Odd Pages (Recto): Outer margin is on the right ($x_0 > X_{\max} + 15\text{pt}$).
Blocks detected in the active outer margin are classified as marginalia and excluded from sequential audio linearization.
Layer 4: Recursive XY-Cut (R-XY-Cut) Multi-Column Sorting
For pages with multiple internal columns, construct a projection histogram of word bounding boxes along the horizontal axis.
Identify whitespace valleys (gutters) of width $\ge 12\text{pt}$.
Split the page horizontally at full-width headers or diagrams, then vertically into column nodes. Traverse depth-first to produce natural reading flow (Left Column $\to$ Right Column).
Layer 5: Multimodal Vision Fallback Pipeline
For scanned documents with broken character streams or missing font structures:
Target page image is fetched via existing lazy renderer: /api/projects/{id}/pages/{page_num}.webp.
Image is submitted to Gemini 2.0 Flash with a structured output schema:
JSON
{
  "body_text": "Main narrative prose in reading order...",
  "callouts": ["Case study text..."],
  "marginalia": ["cf. John viii. 26", "cf. John xii. 49"],
  "footnotes": ["1 For structus = instructus..."]
}


Vision output populates the page's block list, eliminating interleaved OCR noise.
4. Frontend: Visual Layout Inspector & Zoning Canvas
Integrate an interactive layout overlay into the existing dockable Source Inspector drawer.



┌─────────────────────────────────────────────────────────────────────────────┐
│ SOURCE INSPECTOR: Page 44                   [ Mode: Blocks ▾ ]  [ ✕ Close ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ Tools: [ ↖ Select ] [ ⛶ Draw Box ] [ ✂ Split ] [ 🗑 Delete ]               │
│ Tag:   (•) Body    ( ) Margin    ( ) Footnote    ( ) Callout    ( ) Skip    │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─ [Gray] Header (Ignored) ──────────────────────────────────────────────┐ │
│  │ 44          TERTULLIAN AGAINST PRAXEAS                             [8  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│  ┌─ [Purple] Margin (Muted) ─┐ ┌─ [Blue] Body (Order: 1) ────────────────┐ │
│  │ ① cf. John viii. 26       │ │ ② commanded by the Father, these He      │ │
│  │   cf. John xii. 49        │ │   also speaks; and it was "not His       │ │
│  │   cf. John vi. 38         │ │   own will, but" the Father's that       │ │
│  │                           │ │   He accomplished...                     │ │
│  └───────────────────────────┘ └──────────────────────────────────────────┘ │
│  ┌─ [Amber] Footnote (Muted) ─────────────────────────────────────────────┐ │
│  │ ③ 1 For structus = instructus, cf. Hoppe, pp. 138 f.                   │ │
│  │   2 With this passage d'Alès, p. 86...                                 │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ [ ⚡ AI Vision Reparse ]  [ Re-extract Text ]         [ Layout Templates ▾ ] │
└─────────────────────────────────────────────────────────────────────────────┘


Visual Features:
Color-Coded Semantic Overlays:
Blue: body
Purple: marginalia
Amber: footnote
Green: callout
Slate Gray: header_footer / skip
Reading Order Badges: Circular numeric badges (①, ②, ③) showing explicit narration order.
Bi-Directional Hover Linking: Hovering a paragraph block in the Chapter Studio pulses the corresponding bounding box in the Inspector; clicking a box scrolls the editor to that paragraph.
Zoning Toolkit:
Draw Tool: Click and drag rectangular boxes directly over the WebP page image.
Transform Handles: Resize corner anchors and move boxes.
Tag Selector: Switch block role via dropdown or hotkeys (1: Body, 2: Margin, 3: Footnote, 4: Skip).
Reading Order Re-sequencing: Drag badges or use up/down order controls.
Re-extract Text Trigger: Calls backend to run bounded extraction (page.get_text(clip=Rect)) strictly inside the user's defined boxes.
5. Layout Template & Propagation System
To prevent repetitive manual zoning across hundreds of pages, provide batch propagation tools in the [ Layout Templates ▾ ] menu:
Copy from Previous Page (Ctrl + Shift + V): Clones normalized bounding boxes from page $N-1$ directly onto page $N$.
Verso/Recto Alternating Propagation:
User tunes Page 44 (Even) and Page 45 (Odd).
Opens Apply Alternating Template:
Range: Pages 46 to 120
Even pages receive Page 44's geometry.
Odd pages receive Page 45's geometry.
Named Project Presets: Save current layout configuration as a reusable preset (e.g., "Academic Two-Column + Bottom Footnotes" or "Patristic Outer Margin References").
6. Data Contracts & API Specifications
Normalized Coordinate Standard
To remain responsive across different display sizes and zoom levels, all bounding boxes are serialized as normalized floats ($0.0 \to 1.0$) relative to total page dimensions:

$$\text{bbox} = [x_0, y_0, x_1, y_1] \quad \text{where } x, y \in [0.0, 1.0]$$
Endpoint 1: Fetch Page Layout



HTTP
GET /api/projects/{project_id}/pages/{page_number}/layout


Response (200 OK):



JSON
{
  "page_number": 44,
  "width": 612.0,
  "height": 792.0,
  "blocks": [
    {
      "id": "blk_44_01",
      "type": "header_footer",
      "order": null,
      "audio_muted": true,
      "bbox": [0.10, 0.04, 0.90, 0.07],
      "text": "44 TERTULLIAN AGAINST PRAXEAS [8"
    },
    {
      "id": "blk_44_02",
      "type": "marginalia",
      "order": null,
      "audio_muted": true,
      "bbox": [0.08, 0.12, 0.22, 0.45],
      "text": "cf. John viii. 26\ncf. John xii. 49"
    },
    {
      "id": "blk_44_03",
      "type": "body",
      "order": 1,
      "audio_muted": false,
      "bbox": [0.24, 0.12, 0.92, 0.82],
      "text": "commanded by the Father, these He also speaks..."
    },
    {
      "id": "blk_44_04",
      "type": "footnote",
      "order": 2,
      "audio_muted": true,
      "bbox": [0.24, 0.84, 0.92, 0.94],
      "text": "1 For structus = instructus, cf. Hoppe, pp. 138 f."
    }
  ]
}


Endpoint 2: Save Modified Layout & Re-Extract



HTTP
POST /api/projects/{project_id}/pages/{page_number}/layout


Request Payload:



JSON
{
  "blocks": [
    {
      "id": "blk_custom_01",
      "type": "body",
      "order": 1,
      "audio_muted": false,
      "bbox": [0.24, 0.12, 0.92, 0.82]
    }
  ],
  "reextract_text": true
}


Endpoint 3: Batch Propagate Layout Template



HTTP
POST /api/projects/{project_id}/layout/propagate


Request Payload:



JSON
{
  "template_even_page": 44,
  "template_odd_page": 45,
  "target_start_page": 46,
  "target_end_page": 120,
  "reextract_all": true
}


Endpoint 4: Trigger Multimodal Vision Extraction



HTTP
POST /api/projects/{project_id}/pages/{page_number}/vision-extract


Request Payload:



JSON
{
  "provider": "gemini",
  "model": "gemini-2.0-flash",
  "prompt_preset": "academic_marginalia"
}


7. Step-by-Step Implementation Checklist
Phase 1: Spatial Block Extraction & Geometry Engine (Backend)
[ ] Create backend/app/services/layout/ module.
[ ] Implement vector container detection using page.get_drawings() for callout card extraction.
[ ] Implement image and caption binding using page.get_image_info().
[ ] Implement Recursive XY-Cut algorithm for multi-column page partitioning.
[ ] Implement Verso/Recto margin classifier to separate outer edge marginalia on alternating pages.
[ ] Build clipping extractor: given an arbitrary normalized bounding box, extract text via PyMuPDF page.get_text("text", clip=fitz.Rect(...)).
Phase 2: Layout Endpoints & Data Model (Backend)
[ ] Define Pydantic models: LayoutBlock, PageLayoutResponse, LayoutUpdateRequest, LayoutPropagateRequest.
[ ] Implement GET /api/projects/{project_id}/pages/{page_number}/layout.
[ ] Implement POST /api/projects/{project_id}/pages/{page_number}/layout with text re-extraction pipeline.
[ ] Implement POST /api/projects/{project_id}/layout/propagate supporting even/odd alternating templates.
[ ] Update project document schema to persist block geometry alongside chapter text.
Phase 3: Vision Fallback Integration (Backend)
[ ] Implement VisionLayoutService using existing Gemini/OpenAI API configuration.
[ ] Create structured JSON response schemas for body, marginalia, footnotes, and callouts.
[ ] Implement POST /api/projects/{project_id}/pages/{page_number}/vision-extract to convert page image into classified blocks.
Phase 4: Visual Inspector & Zoning Overlay (Frontend)
[ ] Add [ View: Original | Blocks ] toggle in <SourceInspectorDrawer/>.
[ ] Build SVG/Canvas overlay component displaying normalized bounding boxes over the rendered WebP page.
[ ] Implement color styling per semantic type (Blue=Body, Purple=Margin, Amber=Footnote, Green=Callout, Gray=Skip).
[ ] Add circular reading order sequence badges (①, ②, ③).
[ ] Implement bi-directional hover/focus linking between editor paragraphs and Inspector boxes.
Phase 5: Interactive Bounding Box Editor & Tools (Frontend)
[ ] Implement drawing canvas: click-and-drag box creation with bounding box transform handles.
[ ] Add floating toolbar: Select, Draw Box, Delete, Block Type dropdown, Order controls.
[ ] Add [ Re-extract Page Text ] action button connected to the update endpoint.
[ ] Add [ ⚡ AI Vision Extract ] trigger with loading state and confirmation diff.
Phase 6: Template Propagation UI (Frontend)
[ ] Add [ Layout Templates ▾ ] dropdown in the Source Inspector header.
[ ] Implement "Copy from Previous Page" shortcut (Ctrl + Shift + V).
[ ] Build "Propagate Layout to Range" modal with options for:
Single template to all pages.
Alternating Even/Odd templates across page ranges.
[ ] Add progress indicator for batch re-extraction across multi-page ranges.
Phase 7: Verification & Regression Testing
[ ] Test on 2-column scanned academic text (Tertullian Against Praxeas): confirm zero margin citations or footnotes leak into sequential TTS audio.
[ ] Test on digital STEM textbook: confirm shaded vector callout boxes and figure captions are isolated.
[ ] Verify template propagation correctly applies alternating margin offsets across 50+ pages.
[ ] Validate EPUB compile: confirm footnotes render as linked <aside> tags and marginalia is preserved visually while remaining muted in TTS audiobooks.
