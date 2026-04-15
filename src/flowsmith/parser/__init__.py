"""Blue Prism XML parser — .bprelease → RawProcess."""

from flowsmith.parser.process import parse_process

# VBO metadata keys in params_map (parser-injected, reserved)
VBO_OBJECT_KEY = "_vbo_object"
VBO_ACTION_KEY = "_vbo_action"

__all__ = ["parse_process", "VBO_OBJECT_KEY", "VBO_ACTION_KEY"]
