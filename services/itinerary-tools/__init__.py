"""Itinerary tools: lightweight MCP service for geocoding and route planning.

Two tools, zero old-framework dependencies:
- geocode: place names → WGS-84 coordinates (with ambiguity detection)
- plan_route: origin+destination → road geometry (with three-tier fallback)
"""
