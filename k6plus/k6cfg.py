#!/usr/bin/env python3
"""k6cfg.py - configure K6PLUS.ROM and fix its checksum.

Examples:
  python3 k6cfg.py k6plus.rom                    # show config, fix checksum
  python3 k6cfg.py k6plus.rom --multi 5.5        # set multiplier 5.5x
  python3 k6cfg.py k6plus.rom --multi off --chipset --wc-vga
"""
import argparse, sys

CFG = 0x20
F_WO, F_DPE, F_L2, F_WC_PCI, F_WC_VGA, F_CHIPSET, F_NONPF, F_QUIET, F_WC_3DFX, F_CDDMA = (1 << i for i in range(10))
FLAGS = [("wo", F_WO, "write order"), ("dpe", F_DPE, "data prefetch"), ("l2", F_L2, "L2 cache on"),
         ("wc-pci", F_WC_PCI, "WC for PCI/AGP frame buffer"), ("wc-vga", F_WC_VGA, "WC for A0000-BFFFF"),
         ("chipset", F_CHIPSET, "ALi Aladdin V FB tweak"), ("nonpf", F_NONPF, "accept non-prefetchable BARs"),
         ("quiet", F_QUIET, "no screen output"),
         ("wc-3dfx", F_WC_3DFX, "WC for 3dfx Voodoo 1/Rush/Voodoo2 cards"),
         ("cddma", F_CDDMA, "ALi M5229 CD/DVD DMA enable (reg 53h bit 0)")]
# K6-2+/III+ BVC internal bus frequency codes (from K6INIT / lib866d)
MULTI = {"2.0": 4, "3.0": 5, "3.5": 7, "4.0": 2, "4.5": 0, "5.0": 1, "5.5": 3, "6.0": 6}
WA = {"leave": 0, "auto": 1, "force": 2}
WO = {0: "all regions (slow)", 1: "all except UC/WC (fast)", 2: "none (fastest)"}


def show(r):
    flags = r[CFG + 5] | r[CFG + 6] << 8
    print("Config:")
    for name, bit, desc in FLAGS:
        print(f"  {name:8s} {'on ' if flags & bit else 'off'}  {desc}")
    print(f"  wo-mode  {r[CFG+7]}    {WO.get(r[CFG+7], '?')}")
    print(f"  wa       {[k for k, v in WA.items() if v == r[CFG+8]][0]}")
    m = r[CFG + 9]
    print(f"  multi    {'unchanged' if m == 0xFF else r[CFG+10:CFG+13].decode() + 'x'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("-o", "--output", help="write to this file instead of in place")
    for name, _, desc in FLAGS:
        ap.add_argument(f"--{name}", dest=name.replace("-", "_"), action="store_true", default=None, help=f"enable: {desc}")
        ap.add_argument(f"--no-{name}", dest=name.replace("-", "_"), action="store_false", help=f"disable: {desc}")
    ap.add_argument("--wo-mode", type=int, choices=[0, 1, 2])
    ap.add_argument("--wa", choices=WA.keys(), help="leave=BIOS setting, auto=only if BIOS left it off, force")
    ap.add_argument("--multi", help="2.0 3.0 3.5 4.0 4.5 5.0 5.5 6.0 or 'off' (K6-2+/III+ only)")
    a = ap.parse_args()

    r = bytearray(open(a.rom, "rb").read())
    if r[:2] != b"\x55\xaa" or r[CFG:CFG + 4] != b"K6CF":
        sys.exit("not a K6PLUS ROM")
    if len(r) != r[2] * 512:
        sys.exit("size mismatch in ROM header")

    flags = r[CFG + 5] | r[CFG + 6] << 8
    for name, bit, _ in FLAGS:
        v = getattr(a, name.replace("-", "_"))
        if v is True: flags |= bit
        if v is False: flags &= ~bit
    r[CFG + 5], r[CFG + 6] = flags & 0xFF, flags >> 8
    if a.wo_mode is not None: r[CFG + 7] = a.wo_mode
    if a.wa: r[CFG + 8] = WA[a.wa]
    if a.multi:
        m = a.multi.lower()
        if m in ("off", "none"):
            r[CFG + 9] = 0xFF; r[CFG + 10:CFG + 13] = b"   "
        else:
            if len(m) == 1: m += ".0"
            if m not in MULTI: sys.exit(f"invalid multiplier {a.multi}; valid: {', '.join(MULTI)}")
            r[CFG + 9] = MULTI[m]; r[CFG + 10:CFG + 13] = m.encode()

    r[-1] = 0
    r[-1] = (-sum(r)) & 0xFF
    assert sum(r) & 0xFF == 0
    open(a.output or a.rom, "wb").write(r)
    show(r)
    print(f"Checksum OK ({len(r)} bytes) -> {a.output or a.rom}")


if __name__ == "__main__":
    main()
