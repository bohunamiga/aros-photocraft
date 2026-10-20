# Photocraft for AROS

A port of [PhotoCraft](https://github.com/storytold/photocraft), an image editor
written in Rust, to AROS x86_64 ABIv11, with mainline v1 retained as a secondary
target.

The repository holds the source pins, the patch series and the build and test
tooling, not a source checkout. The pinned source is PhotoCraft
`c450e755` (0.7.0), the base the AROS ports recipe uses, starting from that
recipe's patch and native Intuition shell
([aros-development-team/ports](https://github.com/aros-development-team/ports/tree/master/graphics/photocraft),
imported unchanged as the first two patches).

Status: the GUI and `photocraft-cli` (with the MCP server over stdio) build for
x86_64 ABIv11 and have been run on an ABIv11 guest; the TCP control bridge does
not build for AROS yet. Mainline v1 is not built. Details and the exact tested
scope: [development](docs/development.md). Patch handling:
[patching](docs/patching.md).

[upstreams.json](upstreams.json) identifies the sources;
[patches/photocraft/series](patches/photocraft/series) the changes to PhotoCraft;
`patches/crates`, `patches/libc-aros` and `patches/aros-pthread` the changes to
dependencies. Generated checkouts and outputs are ignored.
