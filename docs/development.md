---
type: guide
updated: 2026-10-16
---

# Development

## Current capabilities

A pinned PhotoCraft source plus an explicit patch series builds the GUI
(`PhotoCraft`) and the command line (`photocraft-cli`, including the MCP server
over stdio) for **x86_64 AROS ABIv11** with a private Rust std toolchain. Both
have been started on an ABIv11 guest (older AROS One 1.3 installation); see
"What has been run" below for the exact scope. Mainline ABIv1 is not built.

## Targets

| Architecture / ABI | Priority | Compile | Link | Runtime |
|---|---|---|---|---|
| x86_64 / ABIv11, older SDK (AROS One 1.3) | Primary | yes | yes | GUI, CLI and stdio MCP checks pass (see below) |
| x86_64 / ABIv11, 2026.09 SDK | Primary, separate profile | not run | not run | not run |
| x86_64 / mainline v1 | Secondary | not run | not run | not run |

## Requirements

- An x86_64 ABIv11 GCC 10.5 cross toolchain and the matching SDK. The C glue,
  the patched pthread objects and the Rust link must all use the same SDK:
  ABIv1 and ABIv11 pass `SysBase` differently, and a mismatch crashes inside the
  first system call instead of failing to build.
- A private Rust std toolchain for AROS registered with rustup, reporting
  exactly `rustc 1.100.0-nightly (0dfb098f3 2026-08-31)`, built with the
  rust-aros std patch tooling (the profile used here includes its process,
  socket-boundary and entropy fixes).
- A rust-aros checkout (target template `x86_64-aros.json.in` and
  `std-groundwork/libc-aros`, at the commit named in `scripts/pcconfig.py`).
- A deadwood2/AROS checkout containing the commit named in
  `scripts/pcconfig.py` (its `compiler/pthread` source is read, never changed).
- Python 3.11+, Git, `patch`, and network access once for `cargo fetch`.

## Configuration

`scripts/pcconfig.py` is the one place for paths. Each setting comes from an
environment variable, else the ignored `local.json` (copy
`local.example.json`), else a default. `python3 scripts/pc.py config` shows
where each value comes from; a missing value is reported with the variable that
sets it.

## Build

```sh
python3 scripts/pc.py fetch          # clone/verify upstream/photocraft and upstream/aros-ports at their pins
python3 scripts/pc.py materialize    # work/photocraft = pin + patches/photocraft/series; never overwrites
CARGO_HOME=deps/v11/cargo-home cargo +TOOLCHAIN fetch --manifest-path work/photocraft/Cargo.toml   # once, online
python3 scripts/pc.py build --no-default-features --features photocraft-cli/mcp
python3 scripts/pc.py build --tool mcp-check     # the MCP acceptance client, same profile
```

Each build writes `build/v11/out/<time>-<id>/` with the binaries and
`manifest.json`: work-copy commit and dirtiness, upstream pins, crate and
libc-aros patch digests, the pthread objects, toolchain identity, the cargo
command, binary SHA-256 and a check that no symbol is left undefined. Builds use
the committed work-copy tree unless `--worktree` is given (recorded as such).
Ambient `RUSTFLAGS`, `CARGO_TARGET_DIR` and similar overrides are refused.

What the build adds around the pinned source:

- `patches/crates/`: rayon-core 1.13.0 (`terminate_global_thread_pool`) and
  parking_lot_core 0.9.12 (realtime condvar deadlines on AROS), checked against
  the Cargo.lock checksums and the recorded patched-tree hashes.
- `patches/libc-aros/`: a `memchr` declaration for rust-aros libc-aros.
- `patches/aros-pthread/`: the pthread link library's detach fix. The unpatched
  `compiler/pthread` is first rebuilt and compared with the SDK's
  `libpthread.a`, object for object; then the two patched objects go first on
  the link line (the GCC driver searches the SDK's `lib/` before any `-L`).
- `--cfg getrandom_backend="custom"`, served by the `photocraft-aros-entropy`
  crate.
- The unwind panic profile (`-Cpanic=unwind -Cforce-unwind-tables=yes`) by
  default; `PHOTOCRAFT_PANIC=abort` selects abort.

Never strip the binaries fully; `x86_64-aros-strip --strip-debug` is safe.

## Features

`photocraft-cli` features: `mcp` (stdio MCP server; Tokio without networking),
`bridge` (TCP control bridge; needs Tokio networking), `sandbox` (cap-std file
roots). Upstream defaults stay `mcp + bridge + sandbox`. AROS builds use `mcp`
only: Tokio's `net` (mio, socket2) and cap-std's rustix do not compile for
AROS. Without `sandbox`, automation roots are checked, not confined: paths
through soft or hard links are refused, a link created during an operation is
not caught, a directory that cannot be listed is an error, and the CLI says so
on stderr when it grants roots.

`photocraft-cli serve --port` (the headless JSON control server on loopback TCP)
uses std networking, not Tokio, and is compiled into the AROS CLI; it carries
upstream's authentication deadline (`64520f64`) but has not been run on AROS.
Stored smart-filter parameters are checked against the requesting session's
automation roots when a document re-renders (upstream `b630d7cb`, backported;
this base has neither Displace `mapPath` re-reads nor `layer.smartFilter.transfer`,
so those parts do not apply).

Saving replaces a file by writing a temporary file beside it and renaming it
over the old one. AROS's C library performs that rename as DeleteFile then
Rename, so the two steps are not atomic. If the rename fails after the delete,
the temporary file (`.<name>.<pid>-<n>.pcsave.tmp`) is kept and the error names
it. A delete-protected file cannot be replaced; the save fails and the file is
unchanged.

MCP input lines are limited to 1 MiB (upstream's bounded reader, backported);
a longer line ends the session before any of it is processed. On AROS the
server reads standard input on a thread that is stopped and joined when the
session ends. The console can be waited on with a timeout; PIPE: cannot, and a
PIPE: read cannot be taken back. A session that ends while the client keeps
standard input open (a failed handshake, an overlong line) therefore keeps the
process until the client closes standard input; the server says so on stderr.
A client should close standard input when it is done or sees an error.

## Release package

```sh
python3 scripts/package.py build/v11/out/<build>      # into dist/
```

`packaging/release.json` names the release, the archive files, the Workbench
stack and the build profile a release must have. `package.py` refuses a build
from a dirty work copy, with other features, with binaries that differ from
its manifest, or whose patch series is not the repository's; it never replaces
a file already in `dist/`. It writes the binary archive (the drawer with both
programs, the Workbench icon made by `scripts/icons.py` from PhotoCraft's own
app icon, `packaging/README.md`, `SOURCE.txt` and the licenses, including every
Rust package the build linked, from `linked_packages` in the build manifest),
the source archive (`git archive` of HEAD), the release notes and
`SHA256SUMS`. Entries are dated with the HEAD commit and sorted, so the same
inputs give the same archive.

`scripts/accept.py ARCHIVE TOOL_OUT NEW_DIR --prefix RUN` stages the acceptance
run of a release archive: the archive is unpacked in the guest into a path with
spaces and every program the run starts comes from there (CLI, an ISO 8859-1
name, MCP smoke test, the CLI at the Shell's default stack, the editor started
from its icon, save and reopen). The unpacked files are copied back to the
results so their hashes can be compared with the archive's.

`photocraft-cli` runs its command on a thread with an 8 MiB stack on AROS, so
it works at a Shell's default stack and under any MCP client. The editor needs
4,000,000 bytes: its Workbench icon carries that; from a Shell, `Stack 4000000`.

## Guest testing

`scripts/stage.py BUILD_OUT TOOL_OUT NEW_DIR --prefix RUN --ctools CTOOLS [--package ZIP]`
writes a payload for one guest run: the binaries, `tests/fixtures`, and Shell
scripts `run-a` (scripted CLI, MCP, save-preservation, file-name and screenshot
checks), `run-gui`, `run-g1`, `run-g2` and `run-g3` (interactive sessions:
editing, Save over a file, a failing Save on a delete-protected file, the Type
tool), `run-z` (reopen the saved work), `run-p` (unpack a release archive into a
path with spaces) and `run-s` (the CLI at the Shell's default stack). Results are new `RESULTS:<RUN>-*` files with
start and done receipts carrying the run UUID and build id. Use the test
environment's reservation workflow and collect results only while the machine
is stopped. `tests/check_png.py` checks the pixels of PNGs written from the
fixtures. `tests/guest/stroke.py` drags the pointer with the position in every
event, which painting through QMP needs. `tests/guest/taskstack.c` prints a
waiting task's candidate return addresses for diagnosing a process that does
not end.

The GUI writes its log to the file named by `PHOTOCRAFT_LOG`
(`RUST_LOG=debug` adds a task list at exit); the AROS Shell cannot redirect a
command's error output.

## What has been run

On 2026-10-16, ABIv11 guest with the older AROS One 1.3 installation, QEMU TCG,
1024x768: CLI `--version`, `info` and `convert` (PSD to PNG, pixels checked);
the MCP acceptance client (33 checks: handshake, tools/list, edit, save,
reopen, preview, tool errors, malformed and fragmented input, two requests in
flight, link refusal, end of input, three restarts); GUI start, open, new
layer, brush stroke, undo/redo, Save As PSD and PNG through the ASL requester,
resize, text clipboard to the system, reopen of the saved PSD with its layers,
and normal exit after interactive sessions.

Not run: the TCP control bridge, image clipboard, file drops, fonts and the
Type tool, large documents, memory measurements, other ABIv11 installations,
mainline v1.
