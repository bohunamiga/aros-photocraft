#!/usr/bin/env python3
"""Drag a pointer path in a pool guest with the position in every button batch.

Usage: stroke.py X0 Y0 X1 Y1 [STEPS]

vmctl's drag sends a single move and a button event without a position; a
painting tool needs intermediate motion while the button is held, and the
testbench found that button events without a position can land elsewhere.
Each step here carries the absolute position, and the press and release
carry it too. Requires the pool environment exported by `vm.sh env`.
"""
import os
import sys
import time

sys.path.insert(0, os.environ.get("AROS_TOOLS", os.path.expanduser("~/Work/AROS/tools")))
import vmctl  # noqa: E402


def main():
    args = [int(a) for a in sys.argv[1:]]
    if len(args) not in (4, 5):
        raise SystemExit(__doc__)
    x0, y0, x1, y1 = args[:4]
    steps = args[4] if len(args) == 5 else 16
    with vmctl.VM() as vm:
        ax, bx, ay, by = vm.calibration()

        def pos(x, y):
            gx, gy = int(round((x - bx) / ax)), int(round((y - by) / ay))
            return [{"type": "abs", "data": {"axis": "x", "value": gx * vmctl.ABS_MAX // vm.w}},
                    {"type": "abs", "data": {"axis": "y", "value": gy * vmctl.ABS_MAX // vm.h}}]

        vm._cmd("input-send-event", events=pos(x0, y0))
        time.sleep(0.2)
        vm._cmd("input-send-event", events=pos(x0, y0) + [{"type": "btn", "data": {"down": True, "button": "left"}}])
        time.sleep(0.15)
        for i in range(1, steps + 1):
            x = x0 + (x1 - x0) * i // steps
            y = y0 + (y1 - y0) * i // steps
            vm._cmd("input-send-event", events=pos(x, y))
            time.sleep(0.08)
        vm._cmd("input-send-event", events=pos(x1, y1) + [{"type": "btn", "data": {"down": False, "button": "left"}}])
        time.sleep(0.3)


if __name__ == "__main__":
    main()
