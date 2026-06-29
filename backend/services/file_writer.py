"""
Format-preserving output writers for PDF and DOCX.

PDF  — PyMuPDF redaction: find PII text → add redact annotation with placeholder
       text → apply_redactions() removes original and overlays the replacement.
DOCX — python-docx paragraph replacement: rebuild each paragraph's runs so the
       full text reflects the replacement while preserving paragraph-level style
       (alignment, spacing, indent) and table structure.

Both anonymise and re-identify paths are supported by swapping the lookup direction.
"""

from pathlib import Path
from typing import Dict


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def write_anonymized_pdf(input_path: Path, output_path: Path, mapping_table) -> None:
    """
    Produce an anonymized PDF from *input_path* by finding each PII string on every
    page and replacing it with the corresponding placeholder via redaction.
    """
    lookup = _build_lookup(mapping_table, reverse=False)
    _process_pdf(input_path, output_path, lookup)


def write_reidentified_pdf(input_path: Path, output_path: Path, mapping_table) -> None:
    """Replace placeholder tokens with original values in a PDF."""
    lookup = _build_lookup(mapping_table, reverse=True)
    _process_pdf(input_path, output_path, lookup)


def _build_lookup(mapping_table, reverse: bool) -> Dict[str, str]:
    """Build {find: replace} from a MappingTable, sorted longest-first."""
    if reverse:
        pairs = [(e.placeholder, e.original) for e in mapping_table.entries
                 if e.placeholder and e.original]
    else:
        pairs = [(e.original, e.placeholder) for e in mapping_table.entries
                 if e.original and e.placeholder]
    # Longest-match-first so "Jane Smith" wins over "Jane"
    pairs.sort(key=lambda x: -len(x[0]))
    return dict(pairs)


def _process_pdf(input_path: Path, output_path: Path, lookup: Dict[str, str]) -> None:
    import fitz  # PyMuPDF

    doc = fitz.open(str(input_path))

    if not lookup:
        doc.save(str(output_path))
        doc.close()
        return

    for page in doc:
        for find_text, replace_text in lookup.items():
            if not find_text:
                continue
            areas = page.search_for(find_text)
            for area in areas:
                page.add_redact_annot(
                    area,
                    text=replace_text,
                    fontsize=11,
                    fill=(1, 1, 1),       # white background
                    text_color=(0, 0, 0), # black text
                )
        page.apply_redactions()

    doc.save(str(output_path))
    doc.close()


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def write_anonymized_docx(input_path: Path, output_path: Path, mapping_table) -> None:
    """Produce an anonymized DOCX with PII replaced by placeholders."""
    lookup = _build_lookup(mapping_table, reverse=False)
    _process_docx(input_path, output_path, lookup)


def write_reidentified_docx(input_path: Path, output_path: Path, mapping_table) -> None:
    """Replace placeholder tokens with original values in a DOCX."""
    lookup = _build_lookup(mapping_table, reverse=True)
    _process_docx(input_path, output_path, lookup)


def _process_docx(input_path: Path, output_path: Path, lookup: Dict[str, str]) -> None:
    """
    Write a modified copy of the DOCX by operating at the ZIP/XML level.

    This preserves *every* part of the original archive (charts, embedded OLE
    objects, custom XML, themes, etc.) — python-docx's high-level Document.save()
    only writes the parts it understands and silently drops the rest, which makes
    complex Word documents unopenable after a round-trip.

    Text replacement is performed by iterating all <w:t> nodes inside each <w:p>
    element, concatenating their text, applying the replacement on the combined
    string, putting the result in the first <w:t>, and clearing the rest.  This
    correctly handles PII that Word has split across multiple runs for formatting
    reasons while keeping paragraph-level and run-level XML structure intact.
    """
    import shutil
    import zipfile
    from lxml import etree

    if not lookup:
        shutil.copy2(str(input_path), str(output_path))
        return

    sorted_pairs = sorted(lookup.items(), key=lambda x: -len(x[0]))

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
    P_TAG = f"{{{W}}}p"
    T_TAG = f"{{{W}}}t"

    def _replace_in_xml(data: bytes) -> bytes:
        try:
            tree = etree.fromstring(data)
        except etree.XMLSyntaxError:
            return data  # unparseable — return unchanged

        for p_elem in tree.iter(P_TAG):
            t_elems = [e for e in p_elem.iter(T_TAG)]
            if not t_elems:
                continue
            full_text = "".join(t.text or "" for t in t_elems)
            new_text = full_text
            for orig, repl in sorted_pairs:
                if orig in new_text:
                    new_text = new_text.replace(orig, repl)
            if new_text == full_text:
                continue
            # Concentrate all text in the first <w:t>; clear the rest
            t_elems[0].text = new_text
            if new_text.startswith(" ") or new_text.endswith(" "):
                t_elems[0].set(XML_SPACE, "preserve")
            for t in t_elems[1:]:
                t.text = ""

        return etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)

    # Parts whose content may contain document text that needs replacement
    def _is_text_part(name: str) -> bool:
        return (
            name == "word/document.xml"
            or (name.startswith("word/") and name.endswith(".xml") and (
                "/header" in name
                or "/footer" in name
                or "/footnote" in name
                or "/endnote" in name
            ))
        )

    with zipfile.ZipFile(str(input_path), "r") as zin:
        with zipfile.ZipFile(str(output_path), "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if _is_text_part(item.filename):
                    data = _replace_in_xml(data)
                zout.writestr(item, data)


# ---------------------------------------------------------------------------
# Image stripping
# ---------------------------------------------------------------------------

def strip_images_from_pdf(input_path: Path, output_path: Path, indices_to_remove: set) -> None:
    """
    Remove raster images at the given global indices from a PDF.

    Indices correspond to the sequential counter used by
    image_extractor._extract_pdf_images(): page 0 images first, then page 1, etc.
    Images are removed by adding a full-coverage redaction annotation and
    applying it with PDF_REDACT_IMAGE_REMOVE so the XObject is deleted from
    the page Resources dictionary.
    """
    import shutil
    if not indices_to_remove:
        shutil.copy2(str(input_path), str(output_path))
        return

    import fitz

    doc = fitz.open(str(input_path))

    # Build (page_idx, img_info) tuples in global sequential order
    global_idx = 0
    to_redact: Dict[int, list] = {}  # page_idx → [img_info, ...]
    for page_num, page in enumerate(doc):
        for img_info in page.get_images(full=True):
            if global_idx in indices_to_remove:
                to_redact.setdefault(page_num, []).append(img_info)
            global_idx += 1

    for page_num, img_list in to_redact.items():
        page = doc[page_num]
        for img_info in img_list:
            try:
                bbox = page.get_image_bbox(img_info)
                if not bbox.is_empty:
                    page.add_redact_annot(bbox, fill=(1, 1, 1))
            except Exception:
                pass
        # PDF_REDACT_IMAGE_REMOVE removes the image XObject from page Resources
        try:
            page.apply_redactions(p_flags=fitz.PDF_REDACT_IMAGE_REMOVE)
        except (TypeError, AttributeError):
            page.apply_redactions()

    doc.save(str(output_path), garbage=4)
    doc.close()


def strip_images_from_docx(input_path: Path, output_path: Path, indices_to_remove: set) -> None:
    """
    Remove images at the given global indices from a DOCX.

    Indices match those from image_extractor._extract_docx_images() (sorted
    word/media/ names).  Procedure:
      1. Identify which media files correspond to the indices.
      2. Find their relationship IDs from word/_rels/document.xml.rels.
      3. Remove <w:drawing> elements that reference those IDs.
      4. Rebuild the ZIP without the stripped media files and their rels.
    """
    import shutil
    if not indices_to_remove:
        shutil.copy2(str(input_path), str(output_path))
        return

    import zipfile
    from lxml import etree

    with zipfile.ZipFile(str(input_path), 'r') as zin:
        names = zin.namelist()
        media_files = sorted([
            n for n in names
            if n.startswith('word/media/') and not n.endswith('/')
        ])

        strip_files = {media_files[i] for i in indices_to_remove if i < len(media_files)}
        strip_basenames = {Path(f).name for f in strip_files}

        if not strip_files:
            shutil.copy2(str(input_path), str(output_path))
            return

        # Parse relationships — find and remove rIds for stripped media files
        rels_raw = zin.read('word/_rels/document.xml.rels')
        rels_tree = etree.fromstring(rels_raw)
        strip_rids: set = set()
        for rel in list(rels_tree):
            target = rel.get('Target', '')
            if Path(target).name in strip_basenames:
                strip_rids.add(rel.get('Id'))
                rels_tree.remove(rel)

        # Parse document XML — remove <w:drawing> elements referencing strip_rids
        doc_raw = zin.read('word/document.xml')
        doc_tree = etree.fromstring(doc_raw)
        if strip_rids:
            _remove_drawing_elements(doc_tree, strip_rids)

        rels_new = etree.tostring(
            rels_tree, xml_declaration=True, encoding='UTF-8', standalone=True
        )
        doc_new = etree.tostring(
            doc_tree, xml_declaration=True, encoding='UTF-8', standalone=True
        )

        # Rebuild ZIP: skip stripped media, replace modified XMLs, copy the rest
        with zipfile.ZipFile(str(output_path), 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in strip_files:
                    continue
                elif item.filename == 'word/_rels/document.xml.rels':
                    zout.writestr(item.filename, rels_new)
                elif item.filename == 'word/document.xml':
                    zout.writestr(item.filename, doc_new)
                else:
                    zout.writestr(item, zin.read(item.filename))


def _remove_drawing_elements(doc_tree, strip_rids: set) -> None:
    """Remove <w:drawing> elements whose a:blip r:embed attribute is in strip_rids."""
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

    drawing_tag = f'{{{W}}}drawing'
    blip_tag = f'{{{A}}}blip'
    r_embed = f'{{{R}}}embed'

    drawings_to_remove = []
    for drawing in doc_tree.iter(drawing_tag):
        for blip in drawing.iter(blip_tag):
            if blip.get(r_embed) in strip_rids:
                drawings_to_remove.append(drawing)
                break

    for drawing in drawings_to_remove:
        parent = drawing.getparent()
        if parent is not None:
            parent.remove(drawing)


