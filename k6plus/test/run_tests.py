import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emutest import build, run, make_board

fails = 0
def check(name, cond, info=""):
    global fails
    print(f"  [{'OK ' if cond else 'FAIL'}] {name} {info}")
    fails += not cond

def case(title, st):
    print(f"\n== {title}\n  screen: {st['tty'].strip()!r}\n  msr writes: {st['msrlog']}")
    check("no unexpected accesses / clobbered registers", not st["bad"], st["bad"])

def wc_mask(size_mb):
    i = 0
    while (128 << i) < size_mb * 1024: i += 1
    return ((0x7FFF << i) & 0x7FFF) << 2

rom = build([])                                   # defaults
st = run(rom)
case("K6-III+, 128MB, AGP TNT2, defaults", st)
check("WHCR = 128MB", st["msr"][0xC0000082] == 0x08000000, hex(st["msr"][0xC0000082]))
check("EFER = WO1|DPE, L2 on", st["msr"][0xC0000080] == 0x06, hex(st["msr"][0xC0000080]))
exp = 0xE4000000 | wc_mask(32) | 2
check("UWCCR lo = TNT2 FB 32MB WC", st["msr"][0xC0000085] == exp, f"{st['msr'][0xC0000085]:#x} vs {exp:#x}")
check("multiplier untouched", 0xFFF8 not in [p for p, _, _ in st["io"]])
tnt = st["pci"][(1, 0)]
check("TNT2 BARs restored", tnt.rd(0x10) == 0xE2000000 and tnt.rd(0x14) == 0xE4000008)
check("TNT2 command restored", tnt.rd(4) & 0xFFFF == 7)

st = run(rom, hole=True)
case("K6-III+, 128MB with 15-16M hole", st)
check("WHCR = 128MB + hole bit", st["msr"][0xC0000082] == 0x08010000, hex(st["msr"][0xC0000082]))

st = run(rom, whcr=0x04000000)
case("BIOS already set WHCR (wa=auto)", st)
check("WHCR untouched", st["msr"][0xC0000082] == 0x04000000)

st = run(build(["--wa", "force"]), whcr=0x04000000, mem_kb=262144)
case("wa=force, 256MB", st)
check("WHCR = 256MB", st["msr"][0xC0000082] == 0x10000000, hex(st["msr"][0xC0000082]))

st = run(build(["--multi", "5.5"]))
case("multiplier 5.5", st)
outs = [(p, v) for p, _, v in st["io"] if p == 0xFFF8]
check("BVC = 0x1260", outs == [(0xFFF8, 0x1260)], outs)
check("EPMR enabled then disabled", [v for m, v in st["msrlog"] if m == "0xc0000086"] == ["0xfff1", "0xfff0"])

st = run(build(["--multi", "6"]))
outs = [v for p, _, v in st["io"] if p == 0xFFF8]
case("multiplier 6.0", st)
check("BVC = 0x12C0", outs == [0x12C0], outs)

st = run(build(["--chipset"]))
case("ALi chipset tweak", st)
nb, agp = st["pci"][(0, 0)], st["pci"][(0, 1)]
for n, d in (("M1541", nb), ("M5243", agp)):
    v = d.rd(0x84)
    check(f"{n} 84h=E404 (16MB cap) 86h=05, 87h preserved", v == 0xA505E404, hex(v))

st = run(build(["--wc-vga", "--chipset"]))
case("VGA WC + chipset", st)
exp_lo = 0xA0000 | wc_mask(0.125) | 2
check("UWCCR lo = A0000/128K", st["msr"][0xC0000085] & 0xFFFFFFFF == exp_lo, hex(st["msr"][0xC0000085]))
check("UWCCR hi = TNT2 FB", st["msr"][0xC0000085] >> 32 == 0xE4000000 | wc_mask(32) | 2)
check("86h has VGA bit", st["pci"][(0, 0)].rd(0x84) >> 16 & 0xFF == 0x07)

st = run(rom, vga="voodoo3")
case("PCI Voodoo3", st)
check("UWCCR = D8000000 32MB", st["msr"][0xC0000085] == 0xD8000000 | wc_mask(32) | 2, hex(st["msr"][0xC0000085]))

st = run(rom, vga="nonpf")
case("card without prefetchable BAR (default)", st)
check("UWCCR not written", all(m != "0xc0000085" for m, _ in st["msrlog"]))
st = run(build(["--nonpf"]), vga="nonpf")
case("same with --nonpf", st)
check("UWCCR = E0000000 64MB", st["msr"][0xC0000085] == 0xE0000000 | wc_mask(64) | 2, hex(st["msr"][0xC0000085]))

st = run(rom, cpu="k6-2")
case("old K6-2 (pre-CXT)", st)
check("old WHCR layout 128MB", st["msr"][0xC0000082] == (32 << 1), hex(st["msr"][0xC0000082]))
check("no EFER/UWCCR", all(m == "0xc0000082" for m, _ in st["msrlog"]))

st = run(rom, cpu="k6-2cxt")
case("K6-2 CXT", st)
check("EFER without L2 touch", st["msr"][0xC0000080] == 0x16, hex(st["msr"][0xC0000080]))

st = run(build(["--multi", "5.5"]), cpu="k6-3")
case("K6-III (non-plus) with multi set", st)
check("no BVC write", not any(p == 0xFFF8 for p, _, _ in st["io"]))

st = run(rom, cpu="intel", m5229=False)
case("Intel CPU", st)
check("silent, nothing written", not st["msrlog"] and not st["tty"])

st = run(rom, cpu="k5", m5229=False)
case("K5", st)
check("silent", not st["msrlog"] and not st["tty"])

st = run(rom, shift=True)
case("SHIFT held", st)
check("nothing written", not st["msrlog"] and "skipped" in st["tty"])

st = run(rom, e801=False, mem_kb=65536)
case("no E801 -> INT15/88", st)
check("WHCR = 64MB", st["msr"][0xC0000082] == 0x04000000, hex(st["msr"][0xC0000082]))

st = run(build(["--quiet"]))
case("quiet", st)
check("no output", st["tty"] == "")

# ---------------- new: 3dfx + CD-DMA ----------------
rom = build([])
st = run(rom, vga="gf2", voodoo="v2sli", mem_kb=524288)
case("P5A-like: GF2 Ultra + Voodoo2 SLI, 512MB", st)
lo, hi = st["msr"][0xC0000085] & 0xFFFFFFFF, st["msr"][0xC0000085] >> 32
check("slot0 = GF2 E0000000/128M", lo == 0xE0000000 | wc_mask(128) | 2, hex(lo))
check("slot1 = Voodoo2 block DC000000/64M", hi == 0xDC000000 | wc_mask(64) | 2, hex(hi))
check("M5229 reg 53h bit0 set", st["pci"][(0, 0x0F)].cfg[0x53] & 1 == 1)
check("only byte 53h written on M5229", all(r == 0x50 for r, _ in st["pci"][(0, 0x0F)].log))
for k in ((0, 9), (0, 10), (0, 0x0D), (0, 0x0C), (0, 0)):
    d = st["pci"][k]
    check(f"BARs/command restored {k}", d.rd(0x10) == make_board("gf2", "v2sli")[k].rd(0x10) and d.rd(4) & 0xFFFF == 7)
check("screen line", "WC=DC000000/64M" in st["tty"] and "CD-DMA" in st["tty"], st["tty"].strip())

st = run(rom, vga="gf2", voodoo="v1", mem_kb=524288)
case("Voodoo 1 single", st)
check("slot1 = DB000000/16M", st["msr"][0xC0000085] >> 32 == 0xDB000000 | wc_mask(16) | 2, hex(st["msr"][0xC0000085] >> 32))

st = run(rom, vga="gf2", voodoo="v2conf", mem_kb=524288)
case("Voodoo2 SLI with other device inside block", st)
check("slot1 not used", st["msr"][0xC0000085] >> 32 == 0, hex(st["msr"][0xC0000085]))
check("conflict shown", "WC3D=conflict" in st["tty"])

st = run(rom, vga="gf2", voodoo="v2low", mem_kb=524288)
case("Voodoo2 block below top of RAM", st)
check("slot1 not used", st["msr"][0xC0000085] >> 32 == 0)

st = run(rom, vga="nonpf", voodoo="v2sli", mem_kb=524288)
case("no WC-able VGA, Voodoo2 SLI gets slot 0", st)
check("slot0 = DC000000/64M", st["msr"][0xC0000085] & 0xFFFFFFFF == 0xDC000000 | wc_mask(64) | 2)

st = run(build(["--chipset"]), vga="nonpf", voodoo="v2sli", mem_kb=524288)
case("chipset tweak must not target Voodoo region", st)
check("M1541 84h untouched", st["pci"][(0, 0)].rd(0x84) == 0xA5000000, hex(st["pci"][(0, 0)].rd(0x84)))

st = run(build(["--no-wc-3dfx", "--no-cddma"]), vga="gf2", voodoo="v2sli", mem_kb=524288)
case("both new features off", st)
check("slot1 unused", st["msr"][0xC0000085] >> 32 == 0)
check("53h untouched", st["pci"][(0, 0x0F)].cfg[0x53] == 0)

st = run(rom, vga="gf2", m5229=False)
case("no M5229", st)
check("no CD-DMA text", "CD-DMA" not in st["tty"])

st = run(rom, cpu="intel", vga="gf2", voodoo="v2sli")
case("Intel CPU: only CD-DMA", st)
check("no MSR access", not st["msrlog"])
check("53h set", st["pci"][(0, 0x0F)].cfg[0x53] & 1 == 1)
check("line shows only CD-DMA", st["tty"].strip() == "K6PLUS: CD-DMA", repr(st["tty"]))

st = run(build(["--chipset"]), vga="gf2", voodoo="v2sli", mem_kb=524288)
case("P5A config: GF2 + V2 SLI + chipset", st)
for k in ((0, 0), (0, 1)):
    v = st["pci"][k].rd(0x84)
    check(f"{k} 84h = E004 (E0000000, 16MB), 86h=05", v == 0xA505E004, hex(v))
check("WC still 128M", st["msr"][0xC0000085] & 0xFFFFFFFF == 0xE0000000 | wc_mask(128) | 2)
print(repr(st["tty"].strip()))

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
