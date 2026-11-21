"""leadership-visit frontend document: graphics list -> map_json (成果本体).

Thin scenario wrapper over the renderer-neutral Image Canvas v2 builder
(``adapters.frontend_canvas``): the scenario contributes its document
identity (category) and keeps the component-facing API stable. The document
is built directly from the frozen ``image_graphics`` list — never from
rendered PNG/SVG output — so the frontend rendering and the PDF stay
pixel-consistent. The basemap is NOT embedded: the frontend loads the
registered image separately.
"""
from __future__ import annotations

from typing import Any

from ...adapters.frontend_canvas import build_canvas_document
from ...backend_registry import IMAGE_ITINERARY_PAGE
from ...errors import ProtocolError
from ...schema_registry import SchemaRegistry

CATEGORY = "leadership_visit"


class FrontendDocumentBuilder:
    """Deterministic map_json builder; consumes the same graphics as the renderer."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def build(self, scene: dict[str, Any], page: dict[str, Any], *,
              identifier: str, name: str) -> dict[str, Any]:
        """Build the frontend document for a frozen image RenderScene.

        ``scene`` carries image_graphics + resolved_layout + viewport; ``page``
        is the validated image page-request (basemap window, texts, legends).
        """
        if scene["renderer_id"] != IMAGE_ITINERARY_PAGE.renderer_id:
            raise ProtocolError("FRONTEND_MODE_UNSUPPORTED",
                                "the image itinerary document requires the image backend")
        return build_canvas_document(self.registry, scene, page,
                                     identifier=identifier, name=name, category=CATEGORY)

    def build_for_scene(self, scene: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
        """Convenience wrapper: identifier/name derived from the scene identity."""
        return self.build(scene, page, identifier=f"map-{scene['scene_id']}",
                          name=f"领导调研行程路线图 {scene['scene_id']}")
