"""Lecture compacte de l'arbre uiautomator (H02, H05, H06)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .models import Bounds, UiNode

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_bounds(raw: str) -> Bounds | None:
    m = _BOUNDS.fullmatch(raw.strip())
    if not m:
        return None
    left, top, right, bottom = map(int, m.groups())
    return Bounds(left=left, top=top, right=right, bottom=bottom)


def _flag(el: ET.Element, name: str) -> bool:
    return el.get(name) == "true"


def parse_uiautomator_xml(xml: str, max_nodes: int = 250) -> list[UiNode]:
    """Garde les nœuds porteurs de sens (texte, description, action possible) et visibles.

    Les conteneurs muets sont omis pour ne pas envoyer des milliers de nœuds au modèle.
    """
    start = xml.find("<hierarchy")
    if start < 0:
        return []
    end = xml.rfind("</hierarchy>")
    root = ET.fromstring(xml[start : end + len("</hierarchy>")] if end > 0 else xml[start:])
    nodes: list[UiNode] = []
    for el in root.iter("node"):
        bounds = parse_bounds(el.get("bounds", ""))
        if bounds is None or bounds.empty:
            continue
        text = (el.get("text") or "").strip()
        desc = (el.get("content-desc") or "").strip()
        cls = el.get("class") or ""
        clickable = _flag(el, "clickable")
        long_clickable = _flag(el, "long-clickable")
        scrollable = _flag(el, "scrollable")
        editable = "EditText" in cls
        checkable = _flag(el, "checkable")
        if not (text or desc or clickable or long_clickable or scrollable or editable or checkable):
            continue
        password = _flag(el, "password")
        nodes.append(
            UiNode(
                index=len(nodes),
                text="•••" if password and text else text[:300],
                desc=desc[:300],
                resource_id=el.get("resource-id") or "",
                cls=cls.rsplit(".", 1)[-1],
                package=el.get("package") or "",
                bounds=bounds,
                clickable=clickable,
                long_clickable=long_clickable,
                scrollable=scrollable,
                editable=editable,
                enabled=el.get("enabled", "true") == "true",
                checked=_flag(el, "checked") if checkable else None,
                selected=_flag(el, "selected"),
                focused=_flag(el, "focused"),
                password=password,
            )
        )
        if len(nodes) >= max_nodes:
            break
    return nodes


def render_for_model(nodes: list[UiNode]) -> str:
    """Une ligne par élément : index, rôle, libellé, états et centre en pixels écran."""
    lines = []
    for n in nodes:
        label = n.text or n.desc or n.resource_id.rsplit("/", 1)[-1]
        states = []
        if n.clickable:
            states.append("cliquable")
        if n.editable:
            states.append("champ")
        if n.scrollable:
            states.append("défilable")
        if n.checked is not None:
            states.append("coché" if n.checked else "non coché")
        if n.selected:
            states.append("sélectionné")
        if n.focused:
            states.append("focus")
        if not n.enabled:
            states.append("désactivé")
        cx, cy = n.bounds.center
        lines.append(f"[{n.index}] {n.cls} «{label}» ({', '.join(states) or '-'}) @({cx},{cy})")
    return "\n".join(lines)
