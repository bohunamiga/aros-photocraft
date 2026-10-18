#!/usr/bin/env python3
"""Stage a guest acceptance payload for one pool run.

    stage.py BUILD_OUTPUT TOOL_OUTPUT NEW_PAYLOAD_DIR --prefix RUN --ctools CTOOLS_OUTPUT

BUILD_OUTPUT is a `pc.py build` output holding PhotoCraft and photocraft-cli;
TOOL_OUTPUT one holding photocraft-mcp-check (`pc.py build --tool mcp-check`).
The payload is extracted in the guest to RAM:pc (`C:UnZip >RAM:<RUN>-unzip.log
POOLINPUT:payload.zip -d RAM:pc`). Then:

    Execute RAM:pc/run-a     scripted checks; every result is a new RESULTS:<RUN>-* file
    Execute RAM:pc/run-gui   interactive session (driven from the host), then its exit
    Execute RAM:pc/run-g1    open a PSD copy, edit and Save over it (driven from the host)
    Execute RAM:pc/run-g2    the same file delete-protected: the Save must fail, file unchanged
    Execute RAM:pc/run-g3    Type tool on a white canvas, paste of an ISO 8859-1 clip (cliptext), Save As PNG
    Execute RAM:pc/run-z     reopen what the interactive sessions saved, final receipt
    Execute RAM:pc/run-p     with --package: unpack the release archive into a path with spaces
    Execute RAM:pc/run-s     last: the CLI at the Shell's default stack (may crash the guest)

Scripts are bytes: some file names are ISO 8859-1 (`caf\xe9.png`, as AROS writes them) and some
UTF-8 (as PhotoCraft writes a JSON or UTF-8 name).

`<RUN>-start.txt` and `<RUN>-done.txt` carry the run UUID and the build id; a
result without both receipts, or with another UUID, does not count. Executables
keep mode 0755 on the host and get `Protect +e` on the RAM: copy.
"""
import argparse
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = ["grid-32x24.png", "layered-64x48.psd", "white-320x160.png"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


LATIN1 = "caf\xe9".encode("latin-1")  # how AROS writes "café"
UTF8 = "za\u017c\u00f3\u0142\u0107".encode("utf-8")  # "zażółć" as UTF-8 bytes


def script(text):
    """A Shell script as bytes, with the two non-ASCII names put in byte for byte."""
    return text.encode("ascii").replace(b"@LATIN1@", LATIN1).replace(b"@UTF8@", UTF8)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("build", type=Path)
    p.add_argument("tool", type=Path)
    p.add_argument("dest", type=Path)
    p.add_argument("--prefix", required=True)
    p.add_argument("--ctools", type=Path, required=True, help="a `pc.py ctools` output (links_test, taskstack)")
    p.add_argument("--extra", type=Path, action="append", default=[], help="another executable for RAM:pc (diagnostics)")
    p.add_argument("--package", type=Path, help="a release ZIP from package.py, staged as RAM:pc/release.zip")
    a = p.parse_args()
    if not re.fullmatch(r"[a-z0-9]{2,12}", a.prefix):
        p.error("prefix: 2-12 lower-case letters or digits (it starts every guest result name)")
    manifest = json.loads((a.build / "manifest.json").read_text())
    tool_manifest = json.loads((a.tool / "manifest.json").read_text())
    if manifest.get("status") != "built-not-run" or tool_manifest.get("status") != "built-not-run":
        p.error("both outputs must come from finished builds")
    a.dest.mkdir()  # refuses an existing directory
    binaries = {}
    for source, name in [(a.build / "PhotoCraft", "PhotoCraft"), (a.build / "photocraft-cli", "photocraft-cli"),
                         (a.tool / "photocraft-mcp-check", "photocraft-mcp-check"),
                         (a.ctools / "links_test", "links_test"), (a.ctools / "taskstack", "taskstack"),
                         (a.ctools / "cliptext", "cliptext")] + [(x, x.name) for x in a.extra]:
        shutil.copyfile(source, a.dest / name)
        (a.dest / name).chmod(0o755)
        binaries[name] = sha(a.dest / name)
    (a.dest / "fixtures").mkdir()
    for name in FIXTURES:
        shutil.copyfile(REPO / "tests" / "fixtures" / name, a.dest / "fixtures" / name)
    if a.package:
        shutil.copyfile(a.package, a.dest / "release.zip")
    run = str(uuid.uuid4())
    r = f"RESULTS:{a.prefix}"
    protect = "\n".join(f"Protect RAM:pc/{n} +e" for n in binaries)
    (a.dest / "run-a").write_bytes(script(f"""FailAt 30
Stack >{r}-stack-default.txt
Stack 4000000
{protect}
Echo "START {run} {manifest['build_id']}" >{r}-start.txt
List RAM:pc >{r}-list.txt
RAM:pc/photocraft-cli --version >{r}-cli-version.txt
Echo $RC >{r}-cli-version.rc
RAM:pc/photocraft-cli info RAM:pc/fixtures/grid-32x24.png >{r}-cli-info.txt
Echo $RC >{r}-cli-info.rc
MakeDir "RAM:pc/out dir"
RAM:pc/photocraft-cli convert RAM:pc/fixtures/layered-64x48.psd "RAM:pc/out dir/conv.png" >{r}-cli-convert.txt
Echo $RC >{r}-cli-convert.rc
Copy "RAM:pc/out dir/conv.png" {r}-conv.png
MakeDir "RAM:pc/mcp work"
MakeDir RAM:pcoutside
Copy RAM:pc/fixtures/grid-32x24.png RAM:pcoutside/secret.png
MakeLink "RAM:pc/mcp work/escape-link" RAM:pcoutside
Echo $RC >{r}-makelink.rc
Copy RAM:pc/fixtures/grid-32x24.png "RAM:pc/mcp work/locked.png"
Protect "RAM:pc/mcp work/locked.png" -d
List "RAM:pc/mcp work" >{r}-mcpwork-before.txt
MakeDir "RAM:pc/links test"
RAM:pc/links_test "RAM:pc/links test" >{r}-links.txt
Echo $RC >{r}-links.rc
RAM:pc/photocraft-mcp-check RAM:pc/photocraft-cli "RAM:pc/mcp work" {r}-mcp.txt {r}-mcp-transcript.txt
Echo $RC >{r}-mcp.rc
Copy "RAM:pc/mcp work/mcp-out.png" {r}-mcp-out.png
Copy "RAM:pc/mcp work/mcp-out.psd" {r}-mcp-out.psd
List RAM:pcoutside >{r}-outside-after.txt
Protect "RAM:pc/mcp work/locked.png" +d
List "RAM:pc/mcp work" >{r}-mcpwork-after.txt
RAM:pc/photocraft-cli convert RAM:pc/fixtures/grid-32x24.png "RAM:pc/out dir/conv.png" >{r}-cli-overwrite.txt
Echo $RC >{r}-cli-overwrite.rc
Copy "RAM:pc/out dir/conv.png" {r}-conv2.png
Copy RAM:pc/fixtures/grid-32x24.png "RAM:pc/out dir/locked.png"
Protect "RAM:pc/out dir/locked.png" -d
RAM:pc/photocraft-cli convert RAM:pc/fixtures/layered-64x48.psd "RAM:pc/out dir/locked.png" >{r}-cli-locked.txt
Echo $RC >{r}-cli-locked.rc
Protect "RAM:pc/out dir/locked.png" +d
Copy "RAM:pc/out dir/locked.png" {r}-locked-after.png
RAM:pc/photocraft-cli convert RAM:pc/fixtures/grid-32x24.png POOLINPUT:readonly.png >{r}-cli-readonly.txt
Echo $RC >{r}-cli-readonly.rc
RAM:pc/photocraft-cli convert RAM:pc/fixtures/grid-32x24.png "RAM:pc/out dir/@UTF8@.png" >{r}-cli-utf8.txt
Echo $RC >{r}-cli-utf8.rc
RAM:pc/photocraft-cli info "RAM:pc/out dir/@UTF8@.png" >{r}-cli-utf8-info.txt
Echo $RC >{r}-cli-utf8-info.rc
Copy RAM:pc/fixtures/grid-32x24.png "RAM:pc/out dir/@LATIN1@.png"
RAM:pc/photocraft-cli info "RAM:pc/out dir/@LATIN1@.png" >{r}-cli-latin1-info.txt
Echo $RC >{r}-cli-latin1-info.rc
List "RAM:pc/out dir" >{r}-outdir-a.txt
Set PHOTOCRAFT_CONFIG_DIR RAM:pc/data
Set PHOTOCRAFT_INLINE_JOBS 1
Set PHOTOCRAFT_LOG {r}-gui1.log
RAM:pc/PhotoCraft --screenshot RAM:pc/gui1.png --screenshot-frames 15 RAM:pc/fixtures/layered-64x48.psd
Echo $RC >{r}-gui1.rc
Copy RAM:pc/gui1.png {r}-gui1.png
Unset PHOTOCRAFT_INLINE_JOBS
Echo "A-DONE {run}" >{r}-a-done.txt
"""))
    (a.dest / "run-gui").write_bytes(script(f"""Stack 4000000
Set PHOTOCRAFT_CONFIG_DIR RAM:pc/data
Set PHOTOCRAFT_LOG {r}-gui2.log
Set RUST_LOG debug
RAM:pc/PhotoCraft RAM:pc/fixtures/grid-32x24.png
Echo $RC >{r}-gui2.rc
Status >{r}-gui2-status.txt
"""))
    gui = f"""Stack 4000000
Set PHOTOCRAFT_CONFIG_DIR RAM:pc/data
"""
    (a.dest / "run-g1").write_bytes(script(gui + f"""Copy RAM:pc/fixtures/layered-64x48.psd "RAM:pc/out dir/edit me.psd"
Copy "RAM:pc/out dir/edit me.psd" {r}-g1-before.psd
Set PHOTOCRAFT_LOG {r}-g1.log
RAM:pc/PhotoCraft "RAM:pc/out dir/edit me.psd"
Echo $RC >{r}-g1.rc
Copy "RAM:pc/out dir/edit me.psd" {r}-g1-saved.psd
List "RAM:pc/out dir" >{r}-g1-outdir.txt
"""))
    (a.dest / "run-g2").write_bytes(script(gui + f"""Protect "RAM:pc/out dir/edit me.psd" -d
Set PHOTOCRAFT_LOG {r}-g2.log
RAM:pc/PhotoCraft "RAM:pc/out dir/edit me.psd"
Echo $RC >{r}-g2.rc
Protect "RAM:pc/out dir/edit me.psd" +d
Copy "RAM:pc/out dir/edit me.psd" {r}-g2-after.psd
List "RAM:pc/out dir" >{r}-g2-outdir.txt
"""))
    (a.dest / "run-g3").write_bytes(script(gui + f"""List FONTS:TrueType >{r}-g3-fonts.txt
RAM:pc/cliptext "@LATIN1@ clip 42" >{r}-g3-cliptext.txt
Echo $RC >{r}-g3-cliptext.rc
Set PHOTOCRAFT_LOG {r}-g3.log
Set RUST_LOG debug
RAM:pc/PhotoCraft RAM:pc/fixtures/white-320x160.png
Echo $RC >{r}-g3.rc
Unset RUST_LOG
Copy "RAM:pc/out dir/type.png" {r}-type.png
List "RAM:pc/out dir" >{r}-g3-outdir.txt
"""))
    (a.dest / "run-p").write_bytes(script(f"""Stack 4000000
MakeDir "RAM:PC test"
UnZip >{r}-p-unzip.txt RAM:pc/release.zip -d "RAM:PC test"
Echo $RC >{r}-p-unzip.rc
List "RAM:PC test" >{r}-p-list-top.txt
List "RAM:PC test/PhotoCraft" >{r}-p-list.txt
"RAM:PC test/PhotoCraft/photocraft-cli" --version >{r}-p-cli-version.txt
Echo $RC >{r}-p-cli-version.rc
"""))
    (a.dest / "run-s").write_bytes(script(f"""Stack 40960
Stack >{r}-s-stack.txt
RAM:pc/photocraft-cli --version >{r}-s-cli-version.txt
Echo $RC >{r}-s-cli-version.rc
RAM:pc/photocraft-cli info RAM:pc/fixtures/grid-32x24.png >{r}-s-cli-info.txt
Echo $RC >{r}-s-cli-info.rc
Echo "S-DONE {run}" >{r}-s-done.txt
Stack 4000000
"""))
    (a.dest / "run-z").write_text(f"""Stack 4000000
List "RAM:pc/out dir" >{r}-outdir.txt
Copy "RAM:pc/out dir/edited 1.png" {r}-edited.png
Copy "RAM:pc/out dir/edited 1.psd" {r}-edited.psd
Set PHOTOCRAFT_CONFIG_DIR RAM:pc/data
Set PHOTOCRAFT_INLINE_JOBS 1
Set PHOTOCRAFT_LOG {r}-gui3.log
RAM:pc/PhotoCraft --screenshot RAM:pc/gui3.png --screenshot-frames 15 "RAM:pc/out dir/edited 1.psd"
Echo $RC >{r}-gui3.rc
Copy RAM:pc/gui3.png {r}-gui3.png
Set PHOTOCRAFT_LOG {r}-gui4.log
RAM:pc/PhotoCraft --screenshot RAM:pc/gui4.png --screenshot-frames 15 "RAM:pc/out dir/edit me.psd"
Echo $RC >{r}-gui4.rc
Copy RAM:pc/gui4.png {r}-gui4.png
Echo "DONE {run} {manifest['build_id']}" >{r}-done.txt
""")
    record = {"prefix": a.prefix, "run_uuid": run, "build": str(a.build), "build_id": manifest["build_id"],
              "tool_build_id": tool_manifest["build_id"], "binaries": binaries,
              "fixtures": {n: sha(a.dest / "fixtures" / n) for n in FIXTURES},
              "package": {"name": a.package.name, "sha256": sha(a.dest / "release.zip")} if a.package else None}
    (a.dest / "stage.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
