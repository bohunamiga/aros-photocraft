"""One place for the port's paths and pins.

Values come from, in order of precedence: environment variables, the ignored
`local.json` beside `upstreams.json` (or the file named by PHOTOCRAFT_LOCAL),
and the defaults below. Workstation paths have no defaults: a missing value is
reported with the variable that sets it, never guessed.
"""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Per-architecture build profile. `target_template` is ("rust-aros", name) for the
# template that ships with the rust-aros checkout, or ("repo", path) for one kept
# here. `pthread_cflags` must reproduce the SDK's libpthread.a objects exactly
# (checked at build time).
ARCHITECTURES = {
    "x86_64": {
        "triple": "x86_64-aros",
        "abi": "x86_64 ABIv11",
        "build_root": "build/v11",
        "cargo_home": "deps/v11/cargo-home",
        "target_template": ("rust-aros", "x86_64-aros.json.in"),
        "pthread_cflags": ["-O2", "-mcmodel=large", "-fno-omit-frame-pointer"],
        "rust_aros_commit": "49324c45b4dc89c7046eb3cb39097c59ce36e6f3",
        "aros_src_commit": "5376f09bc1ed0c36a12fbb096406013f8a046e89",
    },
    "aarch64": {
        "triple": "aarch64-aros",
        "abi": "aarch64 ABIv1",
        "build_root": "build/aarch64",
        "cargo_home": "deps/aarch64/cargo-home",
        "target_template": ("repo", "targets/aarch64-aros.json.in"),
        # The aarch64 toolchain keeps GCC's pre-10 -fcommon default; the SDK was
        # built with -fno-common (without it pthread.o differs in four globals).
        "pthread_cflags": ["-O2", "-mcmodel=large", "-fno-omit-frame-pointer", "-fno-common"],
        "rust_aros_commit": "1e26a71d4b7956f358d6540163bad1def6d91360",
        "aros_src_commit": "e2cb3acaace051317da486a5bfd574cda726540d",
    },
}

# key: (environment variable, default, description)
SETTINGS = {
    "arch": ("PHOTOCRAFT_ARCH", "x86_64", "target architecture: x86_64 (ABIv11) or aarch64"),
    "aros_gcc": ("PHOTOCRAFT_AROS_GCC", None, "AROS C compiler driver matching the SDK"),
    "aros_ar": ("PHOTOCRAFT_AROS_AR", None, "archiver from the same toolchain"),
    "aros_strip": ("PHOTOCRAFT_AROS_STRIP", None, "strip from the same toolchain (optional)"),
    "aros_sdk": ("PHOTOCRAFT_AROS_SDK", None, "SDK used as --sysroot"),
    "rust_aros": ("PHOTOCRAFT_RUST_AROS", None, "rust-aros Git checkout (target template, libc-aros)"),
    "rust_aros_commit": ("PHOTOCRAFT_RUST_AROS_COMMIT", None,
                         "rust-aros commit whose target template and libc-aros are used (profile default)"),
    "aros_src": ("PHOTOCRAFT_AROS_SRC", None, "AROS Git checkout; read-only source of the pthread link library"),
    "aros_src_commit": ("PHOTOCRAFT_AROS_SRC_COMMIT", None,
                        "commit whose compiler/pthread matches the SDK's libpthread.a (profile default)"),
    "egui_aros": ("PHOTOCRAFT_EGUI_AROS", None, "egui-aros Git checkout; its commit pinned in upstreams.json is built"),
    "toolchain": ("PHOTOCRAFT_TOOLCHAIN", None, "rustup name of the private AROS std toolchain"),
    "rustc_version": ("PHOTOCRAFT_RUSTC_VERSION", "rustc 1.100.0-nightly (0dfb098f3 2026-08-31)",
                      "exact `rustc --version` the toolchain must report"),
    "cargo_home": ("PHOTOCRAFT_CARGO_HOME", None, "private CARGO_HOME (relative: to the repository)"),
    "build_root": ("PHOTOCRAFT_BUILD_ROOT", None, "build outputs (relative: to the repository)"),
    "panic": ("PHOTOCRAFT_PANIC", "unwind", "native panic profile: unwind or abort"),
}


class ConfigError(Exception):
    pass


def _local():
    path = Path(os.environ.get("PHOTOCRAFT_LOCAL", REPO / "local.json"))
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ConfigError(f"{path}: {error}") from error
    unknown = set(data) - set(SETTINGS)
    if unknown:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)}")
    return data, path


def load(required=()):
    """Returns the resolved settings; raises ConfigError naming what is missing."""
    local, _ = _local()
    out = {}
    for key, (env, default, _) in SETTINGS.items():
        value = os.environ.get(env) or local.get(key) or default
        out[key] = value
    if out["arch"] not in ARCHITECTURES:
        raise ConfigError(f"arch must be one of {sorted(ARCHITECTURES)}, not {out['arch']!r}")
    profile = ARCHITECTURES[out["arch"]]
    # Derived from the profile; a local.json / environment value still wins.
    out["triple"] = profile["triple"]
    out["abi"] = profile["abi"]
    out["pthread_cflags"] = profile["pthread_cflags"]
    for key in ("rust_aros_commit", "aros_src_commit", "cargo_home", "build_root"):
        if not out[key]:
            out[key] = profile[key]
        if key in ("cargo_home", "build_root") and not os.path.isabs(out[key]):
            out[key] = str(REPO / out[key])
    missing = [key for key in required if not out.get(key)]
    if missing:
        lines = [f"  {k}: set {SETTINGS[k][0]} or \"{k}\" in local.json ({SETTINGS[k][2]})" for k in missing]
        raise ConfigError("missing configuration:\n" + "\n".join(lines))
    if out["panic"] not in ("unwind", "abort"):
        raise ConfigError("panic must be unwind or abort")
    return out


def describe():
    local, path = _local()
    arch = os.environ.get("PHOTOCRAFT_ARCH") or local.get("arch") or SETTINGS["arch"][1]
    profile = ARCHITECTURES.get(arch)
    rows = []
    for key, (env, default, text) in SETTINGS.items():
        if os.environ.get(env):
            source = "env"
        elif key in local:
            source = "local"
        elif default:
            source = "default"
        elif profile and key in profile:
            source = "profile"
        else:
            source = "unset"
        rows.append(f"{key:18} {source:8} {env}  ({text})")
    if profile:
        rows.append(f"{'triple':18} {'profile':8} -  ({profile['triple']}, {profile['abi']})")
    return f"local file: {path or 'none'}\n" + "\n".join(rows)
