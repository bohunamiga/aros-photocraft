#!/usr/bin/env python3
"""Stage the acceptance run of a release archive: the archive itself, not the build outputs.

    accept.py ARCHIVE TOOL_OUTPUT NEW_PAYLOAD_DIR --prefix RUN

ARCHIVE is the release ZIP from package.py (as delivered in dist/); TOOL_OUTPUT a `pc.py build
--tool mcp-check` output. The payload is extracted in the guest to RAM:pc, as for stage.py.
Every PhotoCraft program the run starts comes from the archive unpacked into "RAM:PC accept":

    Execute RAM:pc/run-x     unpack, copy the unpacked files to RESULTS: (hashed on the host),
                             CLI version/info/convert, an ISO 8859-1 name, MCP (--quick: handshake,
                             tools, edits, saves, refusals, end of input); last, the CLI again at the
                             Shell's default stack
    (Workbench)              open "RAM:PC accept/PhotoCraft", start PhotoCraft from its icon,
                             open "RAM:PC accept/out dir/accept.psd", paint, Save, quit
    Execute RAM:pc/run-y     reopen the saved PSD from the unpacked program, process list, receipt

Results are new RESULTS:<RUN>-* files; <RUN>-start.txt and <RUN>-done.txt carry the run UUID and
the archive's SHA-256.
"""
import argparse
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = ["grid-32x24.png", "layered-64x48.psd"]
LATIN1 = "caf\xe9".encode("latin-1")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def script(text):
    return text.encode("ascii").replace(b"@LATIN1@", LATIN1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("archive", type=Path)
    p.add_argument("tool", type=Path)
    p.add_argument("dest", type=Path)
    p.add_argument("--prefix", required=True)
    a = p.parse_args()
    if not re.fullmatch(r"[a-z0-9]{2,12}", a.prefix):
        p.error("prefix: 2-12 lower-case letters or digits")
    tool = json.loads((a.tool / "manifest.json").read_text())
    if tool.get("status") != "built-not-run":
        p.error("the tool output must come from a finished build")
    a.dest.mkdir()
    shutil.copyfile(a.archive, a.dest / "release.zip")
    shutil.copyfile(a.tool / "photocraft-mcp-check", a.dest / "photocraft-mcp-check")
    (a.dest / "photocraft-mcp-check").chmod(0o755)
    (a.dest / "fixtures").mkdir()
    for name in FIXTURES:
        shutil.copyfile(REPO / "tests" / "fixtures" / name, a.dest / "fixtures" / name)
    run, archive_sha = str(uuid.uuid4()), sha(a.archive)
    r, d = f"RESULTS:{a.prefix}", '"RAM:PC accept/PhotoCraft'
    cli = f'{d}/photocraft-cli"'
    (a.dest / "run-x").write_bytes(script(f"""FailAt 30
Echo "START {run} {archive_sha}" >{r}-start.txt
Stack >{r}-stack-default.txt
Stack 4000000
Protect RAM:pc/photocraft-mcp-check +e
MakeDir "RAM:PC accept"
C:UnZip >{r}-unzip.txt RAM:pc/release.zip -d "RAM:PC accept"
Echo $RC >{r}-unzip.rc
List "RAM:PC accept" ALL >{r}-list.txt
Copy {d}/PhotoCraft" {r}-x-PhotoCraft
Copy {cli} {r}-x-photocraft-cli
Copy {d}/PhotoCraft.info" {r}-x-PhotoCraft.info
Copy "RAM:PC accept/PhotoCraft.info" {r}-x-drawer.info
MakeDir "RAM:PC accept/out dir"
Copy RAM:pc/fixtures/layered-64x48.psd "RAM:PC accept/out dir/accept.psd"
{cli} --version >{r}-cli-version.txt
Echo $RC >{r}-cli-version.rc
{cli} info RAM:pc/fixtures/grid-32x24.png >{r}-cli-info.txt
Echo $RC >{r}-cli-info.rc
{cli} convert RAM:pc/fixtures/layered-64x48.psd "RAM:PC accept/out dir/conv.png" >{r}-cli-convert.txt
Echo $RC >{r}-cli-convert.rc
Copy "RAM:PC accept/out dir/conv.png" {r}-conv.png
Copy RAM:pc/fixtures/grid-32x24.png "RAM:PC accept/out dir/@LATIN1@.png"
{cli} info "RAM:PC accept/out dir/@LATIN1@.png" >{r}-cli-latin1.txt
Echo $RC >{r}-cli-latin1.rc
{d}/PhotoCraft" "RAM:PC accept/out dir/@LATIN1@.png" >{r}-gui-latin1.txt
Echo $RC >{r}-gui-latin1.rc
MakeDir "RAM:PC accept/mcp work"
Copy RAM:pc/fixtures/grid-32x24.png "RAM:PC accept/mcp work/locked.png"
Protect "RAM:PC accept/mcp work/locked.png" -d
MakeDir RAM:pcaoutside
Copy RAM:pc/fixtures/grid-32x24.png RAM:pcaoutside/secret.png
MakeLink "RAM:PC accept/mcp work/escape-link" RAM:pcaoutside
RAM:pc/photocraft-mcp-check --quick {cli} "RAM:PC accept/mcp work" {r}-mcp.txt {r}-mcp-transcript.txt
Echo $RC >{r}-mcp.rc
Protect "RAM:PC accept/mcp work/locked.png" +d
List "RAM:PC accept/mcp work" >{r}-mcpwork.txt
List RAM:pcaoutside >{r}-outside.txt
Copy "RAM:PC accept/mcp work/mcp-out.png" {r}-mcp-out.png
Stack 40960
Stack >{r}-stack-low.txt
{cli} info RAM:pc/fixtures/grid-32x24.png >{r}-low-info.txt
Echo $RC >{r}-low-info.rc
{cli} convert RAM:pc/fixtures/layered-64x48.psd "RAM:PC accept/out dir/low.png" >{r}-low-convert.txt
Echo $RC >{r}-low-convert.rc
Copy "RAM:PC accept/out dir/low.png" {r}-low.png
Stack 4000000
Echo "X-DONE {run}" >{r}-x-done.txt
"""))
    (a.dest / "run-y").write_bytes(script(f"""Stack 4000000
List "RAM:PC accept/out dir" >{r}-outdir.txt
Copy "RAM:PC accept/out dir/accept.psd" {r}-accept.psd
{d}/PhotoCraft" --screenshot RAM:pc/y.png --screenshot-frames 15 "RAM:PC accept/out dir/accept.psd"
Echo $RC >{r}-reopen.rc
Copy RAM:pc/y.png {r}-reopen.png
List {d}" >{r}-drawer-after.txt
Status >{r}-status.txt
Echo "DONE {run} {archive_sha}" >{r}-done.txt
"""))
    record = {"prefix": a.prefix, "run_uuid": run, "archive": {"name": a.archive.name, "sha256": archive_sha},
              "tool": {"build_id": tool["build_id"], "sha256": sha(a.dest / "photocraft-mcp-check")},
              "fixtures": {n: sha(a.dest / "fixtures" / n) for n in FIXTURES}}
    (a.dest / "accept.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
