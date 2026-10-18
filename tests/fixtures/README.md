# Test fixtures

| File | Content | Origin |
|---|---|---|
| `grid-32x24.png` | 32x24 8-bit RGB; quadrants red (top left), green (top right), blue (bottom left), white (bottom right) | `make_fixtures.py` (deterministic; rerun to reproduce) |
| `white-320x160.png` | 320x160 8-bit RGB, all white: a canvas for the Type tool, where any dark pixel is text | `make_fixtures.py` |
| `layered-64x48.psd` | 64x48 RGB 8-bit PSD: white Background plus layer "red box", a #ff0000 rectangle at x 10, y 8, 20x16 | Written by PhotoCraft c450e755 with this port's patches (host build, MCP `doc_save`) through `tests/mcp-client`'s edit sequence |

SHA-256:

    442131d419b88bd2039f67e0a26199051c711706fad44a0f0d8aac35f0f3dd85  grid-32x24.png
    4ce949df5573db7c88641573d4c1a72b0b34327017ceddae4a80e5563b2bec37  layered-64x48.psd
    5f498b7c3629091dab62dbd8ac1c3ca1536706201c5ddbf033f215fe1b126cb4  white-320x160.png

`tests/check_png.py` verifies the flattened pixels of a PNG written from either fixture.
