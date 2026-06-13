"""
EPUB generator for narratible.
Produces a valid EPUB 3 file from chapter data and project metadata.
"""
import uuid
import zipfile
import logging
from pathlib import Path
from html import escape
from typing import Optional

logger = logging.getLogger(__name__)


# ── Templates ──────────────────────────────────────────────────────────────────

CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:schemas:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

OPF_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{book_id}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>en</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    {cover_item}
    {chapter_items}
  </manifest>
  <spine toc="ncx">
    {chapter_refs}
  </spine>
</package>"""

NCX_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{book_id}"/>
  </head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>
    {nav_points}
  </navMap>
</ncx>"""

NAV_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><meta charset="UTF-8"/><title>Table of Contents</title></head>
<body>
  <nav epub:type="toc">
    <h1>Table of Contents</h1>
    <ol>
      {toc_items}
    </ol>
  </nav>
</body>
</html>"""

CHAPTER_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><meta charset="UTF-8"/><title>{title}</title></head>
<body>
  <h1>{title}</h1>
  {paragraphs}
</body>
</html>"""


def _paragraphs_html(text: str) -> str:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    return "\n  ".join(f"<p>{escape(p)}</p>" for p in paras)


def build_epub(
    output_path: Path,
    title: str,
    author: str,
    chapters: list[dict],
    cover_image_path: Optional[Path] = None,
) -> Path:
    """
    Build an EPUB file at output_path.
    chapters: list of {"title": str, "text": str}
    Returns the path to the written EPUB file.
    """
    from datetime import datetime, timezone

    book_id = str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as epub:
        # mimetype must be first and uncompressed
        epub.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        epub.writestr("META-INF/container.xml", CONTAINER_XML)

        # Cover image
        cover_item = ""
        if cover_image_path and cover_image_path.exists():
            suffix = cover_image_path.suffix.lower()
            media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
            epub.write(cover_image_path, f"OEBPS/images/cover{suffix}")
            cover_item = f'<item id="cover-image" href="images/cover{suffix}" media-type="{media_type}" properties="cover-image"/>'

        # Chapter HTML files
        chapter_items = []
        chapter_refs = []
        nav_points = []
        toc_items = []

        for i, ch in enumerate(chapters):
            ch_id = f"chapter{i + 1:03d}"
            ch_file = f"{ch_id}.xhtml"
            ch_title = escape(ch.get("title", f"Chapter {i + 1}"))
            ch_html = CHAPTER_TEMPLATE.format(
                title=ch_title,
                paragraphs=_paragraphs_html(ch.get("text", "")),
            )
            epub.writestr(f"OEBPS/{ch_file}", ch_html)
            chapter_items.append(f'<item id="{ch_id}" href="{ch_file}" media-type="application/xhtml+xml"/>')
            chapter_refs.append(f'<itemref idref="{ch_id}"/>')
            nav_points.append(
                f'<navPoint id="{ch_id}" playOrder="{i + 1}">'
                f'<navLabel><text>{ch_title}</text></navLabel>'
                f'<content src="{ch_file}"/></navPoint>'
            )
            toc_items.append(f'<li><a href="{ch_file}">{ch_title}</a></li>')

        # nav.xhtml
        epub.writestr(
            "OEBPS/nav.xhtml",
            NAV_TEMPLATE.format(toc_items="\n      ".join(toc_items)),
        )

        # toc.ncx
        epub.writestr(
            "OEBPS/toc.ncx",
            NCX_TEMPLATE.format(
                book_id=book_id,
                title=escape(title),
                nav_points="\n    ".join(nav_points),
            ),
        )

        # content.opf
        epub.writestr(
            "OEBPS/content.opf",
            OPF_TEMPLATE.format(
                book_id=book_id,
                title=escape(title),
                author=escape(author),
                modified=modified,
                cover_item=cover_item,
                chapter_items="\n    ".join(chapter_items),
                chapter_refs="\n    ".join(chapter_refs),
            ),
        )

    logger.info(f"EPUB written to {output_path}")
    return output_path
