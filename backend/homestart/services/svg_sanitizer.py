"""Removes scripts, event handlers and external references from uploaded SVG files.

SVG is XML that browsers can execute, so uploaded icons are rebuilt from an allowlist
of drawing elements and attributes instead of trying to strip known-bad parts.
"""

import re
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

ALLOWED_ELEMENTS = {
    "svg", "g", "defs", "symbol", "use", "title", "desc",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask", "pattern",
    "filter", "feGaussianBlur", "feOffset", "feBlend", "feColorMatrix", "feComposite",
    "feFlood", "feMerge", "feMergeNode", "feMorphology", "feDropShadow",
}

ALLOWED_ATTRIBUTES = {
    "id", "class", "style", "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2",
    "cx", "cy", "r", "rx", "ry", "d", "points", "transform", "fill", "fill-opacity", "fill-rule",
    "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity", "clip-path", "clip-rule",
    "mask", "filter", "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
    "spreadMethod", "fx", "fy", "preserveAspectRatio", "font-family", "font-size", "font-weight",
    "text-anchor", "dominant-baseline", "letter-spacing", "dx", "dy", "patternUnits",
    "patternContentUnits", "patternTransform", "clipPathUnits", "maskUnits", "maskContentUnits",
    "visibility", "display", "color", "in", "in2", "stdDeviation", "result", "mode", "values",
    "type", "operator", "k1", "k2", "k3", "k4", "flood-color", "flood-opacity", "radius",
    "filterUnits", "primitiveUnits", "version", "href",
}

# url(...) is only allowed when it points inside the same document, e.g. url(#gradient).
_EXTERNAL_URL = re.compile(r"url\(\s*['\"]?\s*(?!#)", re.IGNORECASE)
_DANGEROUS_CSS = re.compile(r"expression\s*\(|javascript:|@import|behavior\s*:", re.IGNORECASE)


class SvgError(ValueError):
    pass


def _local_name(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return ns, name
    return None, tag


def _clean_value(value: str) -> str | None:
    if _EXTERNAL_URL.search(value) or _DANGEROUS_CSS.search(value):
        return None
    return value


def _clean_element(source: ET.Element) -> ET.Element | None:
    ns, name = _local_name(source.tag)
    if ns not in (None, SVG_NS) or name not in ALLOWED_ELEMENTS:
        return None

    target = ET.Element(name)
    for raw_attr, value in source.attrib.items():
        attr_ns, attr = _local_name(raw_attr)
        if attr_ns not in (None, XLINK_NS) or attr not in ALLOWED_ATTRIBUTES:
            continue
        if attr == "href":
            if not value.strip().startswith("#"):
                continue
            target.set("href", value.strip())
            continue
        cleaned = _clean_value(value)
        if cleaned is not None:
            target.set(attr, cleaned)

    if name in ("title", "desc", "text", "tspan") and source.text:
        target.text = source.text
    for child in source:
        cleaned_child = _clean_element(child)
        if cleaned_child is not None:
            target.append(cleaned_child)
        if child.tail and name in ("text", "tspan"):
            (cleaned_child if cleaned_child is not None else target).tail = child.tail
    return target


def sanitize_svg(data: bytes) -> bytes:
    try:
        root = SafeET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception as exc:  # defusedxml raises several unrelated exception types
        raise SvgError("The file is not a valid SVG image") from exc

    if _local_name(root.tag)[1] != "svg":
        raise SvgError("The file is not a valid SVG image")

    cleaned = _clean_element(root)
    if cleaned is None:
        raise SvgError("The file is not a valid SVG image")
    cleaned.set("xmlns", SVG_NS)
    return ET.tostring(cleaned, encoding="utf-8", xml_declaration=False)
