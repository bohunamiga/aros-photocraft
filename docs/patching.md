---
type: guide
updated: 2026-10-16
---

# Source and patch workflow

## Registered source

`upstreams.json` maps `photocraft` (the build source) and `aros-ports` (origin of
the first two patches) to their URLs and full commits. `patches/photocraft/series`
lists the patches in order. The example manifest is illustrative only.

`scripts/pc.py` implements the procedure below: `fetch` (clone, or verify origin,
pin and clean state), `materialize` (new work copy only), `export` (work-copy
commits since the pin to numbered patches and `series`; refuses uncommitted
changes) and `verify` (rebuild the series in a new temporary directory whose path
contains spaces and compare its Git tree, contents and modes, with the work
copy's committed tree).

## Materialization procedure

1. Read and validate the active manifest and explicit series. Fetch the registered
   URL into a new `upstream/photocraft` checkout, detach at the exact full commit,
   verify its identity and clean state. Never edit that clean source.
2. Create a separate new `work/photocraft` from the pin and apply the ordered series.
   Stop on conflicts; record the pin, series order and patch content digests.
3. Before reusing work, check its expected inputs against the current manifest and
   patches. Reconstruct independently in a temporary directory and compare actual
   saved source contents and modes before claiming synchronization.
4. Never overwrite or reset an existing work copy as bootstrap behavior. Preserve
   staged, unstaged, untracked and valuable ignored files, branches, commits,
   stashes and reflogs. A clean status or stored digest does not preserve history
   or establish source equivalence. Refuse destructive recreation unless both are
   verified independently and recovery is retained outside the replaced copy.

Checked on 2026-10-16: `verify` reproduces the work copy's tree; `materialize`
from another working directory into a repository copy under a path with spaces
gives the same tree; `materialize` refuses an existing work copy.

## Saving changes

Save every external-source modification in `patches/photocraft/` as a numbered,
coherent patch. Use the full Git binary patch format for binary changes; a text-only
`Binary files differ` notice is insufficient. Save only the delta following earlier
patches and append its exact filename to `series`. Never overwrite existing patches
by calculating a number from file count.

Work-copy commits are the patches: write the metadata into the commit message, then
`export`. Each patch records title, repository, author, date, base commit, prerequisites,
problem, rationale, platform scope, upstream status (`candidate`, `local-only`,
`submitted`, or `accepted`), actual verification and a removal condition if temporary.
Submitted/accepted changes require the upstream link. Explicitly mark unrun tests.
Save patch, metadata and series atomically enough to retain recoverable edits if
interrupted; do not advance a claimed baseline after failure. Commit the preserved
patch before any separately authorized upstream submission. Work-copy commits or a
remote fork do not replace this repository's patch record.

## Reproduction and pin changes

Validate the complete series in a separate temporary reconstruction without changing
active copies. Compare contents, binary bytes and executable modes with the expected
saved tree. Test stale inputs, unsaved changes, stashes/branches/reflogs, amended
commits, successive patches and binary changes before relying on new tooling.
Preserve the previous series in Git history before updating the base. Retire accepted
patches only when the new pinned source contains them; retain their provenance in
history. A source reconstruction check proves neither a build nor runtime behavior.
