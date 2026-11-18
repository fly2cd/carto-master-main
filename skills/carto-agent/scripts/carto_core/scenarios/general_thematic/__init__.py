"""general-thematic scenario package (raster + vector geometry variants).

Keep this ``__init__`` import-light: the registry loads ``manifest`` at import time, and
importing the heavy strategy modules (dispatch/raster/vector) here would cycle back into
``scenario_registry`` while it is still building ``_COMPONENTS``. ``component()`` imports
the dispatch module lazily on first use.
"""