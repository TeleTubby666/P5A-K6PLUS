"""Run K6PLUS (EMUTEST build) in Unicorn with simulated K6 MSRs, PCI bus, BIOS ints."""
import struct, subprocess, sys, os
from unicorn import *
from unicorn.x86_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..")
ROMSEG = 0xC800
RET_SEG, RET_OFF = 0x0000, 0x0500     # return stub (hlt)


class PciDev:
    def __init__(self, vid, did, cls, hdr=0, bars=(), host=False):
        self.cfg = bytearray(256)
        struct.pack_into("<HH", self.cfg, 0, vid, did)
        struct.pack_into("<I", self.cfg, 8, cls << 8)
        self.cfg[0x0E] = hdr
        struct.pack_into("<H", self.cfg, 4, 0x0007)
        struct.pack_into("<H", self.cfg, 6, 0x0230)
        self.barsize = {}
        for i, (val, size) in enumerate(bars):
            struct.pack_into("<I", self.cfg, 0x10 + 4 * i, val)
            self.barsize[0x10 + 4 * i] = size
        self.cfg[0x87] = 0xA5          # canary for RMW check
        self.log = []
        self.host = host
        self.bad = []

    def rd(self, reg):
        return struct.unpack_from("<I", self.cfg, reg)[0]

    def wr(self, reg, val):
        self.log.append((reg, val))
        if reg in self.barsize:
            size = self.barsize[reg]
            if size:
                ro = self.rd(reg) & (0x1 if self.rd(reg) & 1 else 0xF)
                val = (val & ~(size - 1) & 0xFFFFFFFF) | ro
            else:
                val = 0
        if reg == 4:
            if self.host and not val & 0x2:
                self.bad.append("host bridge memory decode switched off")
            val = (val & 0xFFFF) | (self.rd(4) & 0xFFFF0000)  # status not writable here
        struct.pack_into("<I", self.cfg, reg, val & 0xFFFFFFFF)


def make_board(vga="agp", voodoo=None, m5229=True):
    devs = {
        (0, 0): PciDev(0x10B9, 0x1541, 0x060000, bars=[(0xD0000008, 128 << 20)], host=True),  # AGP aperture
        (0, 1): PciDev(0x10B9, 0x5243, 0x060400, hdr=1),
        (0, 7): PciDev(0x10B9, 0x1533, 0x060100),
        (0, 0x0B): PciDev(0x1000, 0x000F, 0x010000, bars=[(0xE001, 256), (0xE3000000, 0x100)]),  # SCSI
    }
    if vga == "agp":      # e.g. Riva TNT2: BAR0 MMIO 16M, BAR1 FB 32M prefetchable
        devs[(1, 0)] = PciDev(0x10DE, 0x0028, 0x030000,
                              bars=[(0xE2000000, 16 << 20), (0xE4000008, 32 << 20)])
    elif vga == "voodoo3":  # PCI Voodoo3: BAR0 MMIO 32M, BAR1 LFB 32M pf, BAR2 IO
        devs[(0, 0x09)] = PciDev(0x121A, 0x0005, 0x030000,
                                 bars=[(0xD0000000, 32 << 20), (0xD8000008, 32 << 20), (0xD001, 256)])
    elif vga == "nonpf":  # card with only non-prefetchable FB
        devs[(0, 0x09)] = PciDev(0x5333, 0x8A01, 0x030000, bars=[(0xE0000000, 64 << 20)])
    elif vga == "gf2":    # GeForce2 Ultra (AGP): BAR0 MMIO 16M, BAR1 FB 128M pf
        devs[(1, 0)] = PciDev(0x10DE, 0x0152, 0x030000,
                              bars=[(0xE8000000, 16 << 20), (0xE0000008, 128 << 20)])
    if m5229:
        d = PciDev(0x10B9, 0x5229, 0x01018A, bars=[(0x1F1, 8), (0x3F5, 4), (0x171, 8), (0x375, 4), (0xD001, 16)])
        d.cfg[0x53] = 0x00
        devs[(0, 0x0F)] = d
    devs[(0, 0x0D)] = PciDev(0x10B7, 0x9055, 0x020000, bars=[(0xD801, 128), (0xCE000000, 128)])    # 3Com NIC
    devs[(0, 0x0C)] = PciDev(0x1031, 0x5601, 0x040000, bars=[(0xCD800000, 4096)])                 # miro DC30
    if voodoo == "v2sli":
        devs[(0, 0x09)] = PciDev(0x121A, 0x0002, 0x040000, bars=[(0xDD000000, 16 << 20)])
        devs[(0, 0x0A)] = PciDev(0x121A, 0x0002, 0x040000, bars=[(0xDE000000, 16 << 20)])
    elif voodoo == "v1":
        devs[(0, 0x09)] = PciDev(0x121A, 0x0001, 0x040000, bars=[(0xDB000000, 16 << 20)])
    elif voodoo == "v2conf":   # another device inside the 64M block
        devs[(0, 0x09)] = PciDev(0x121A, 0x0002, 0x040000, bars=[(0xDD000000, 16 << 20)])
        devs[(0, 0x0A)] = PciDev(0x121A, 0x0002, 0x040000, bars=[(0xDE000000, 16 << 20)])
        devs[(0, 0x0E)] = PciDev(0x1102, 0x0002, 0x040100, bars=[(0xDF800000, 4096)])
    elif voodoo == "v2low":    # block would reach into RAM
        devs[(0, 0x09)] = PciDev(0x121A, 0x0002, 0x040000, bars=[(0x01000000, 16 << 20)])
    return devs


def build(cfgargs):
    out = os.path.join(HERE, "t.rom")
    subprocess.run(["nasm", "-f", "bin", "-DEMUTEST", "-o", out, os.path.join(SRC, "k6plus.asm")], check=True)
    subprocess.run([sys.executable, os.path.join(SRC, "k6cfg.py"), out] + cfgargs, check=True, stdout=subprocess.DEVNULL)
    return open(out, "rb").read()


def run(rom, cpu="k6-3+", mem_kb=131072, hole=False, whcr=0, efer=0x10, shift=False, vga="agp", e801=True,
        voodoo=None, m5229=True):
    mu = Uc(UC_ARCH_X86, UC_MODE_16)
    mu.mem_map(0, 0x100000)
    mu.mem_write(ROMSEG * 16, rom)
    mu.mem_write(RET_SEG * 16 + RET_OFF, b"\xf4")
    if shift:
        mu.mem_write(0x417, b"\x02")

    msr = {0xC0000080: efer, 0xC0000082: whcr, 0xC0000085: 0, 0xC0000086: 0}
    st = dict(msrlog=[], io=[], tty="", pci=make_board(vga, voodoo, m5229), cf8=0, bad=[])
    cpus = {  # (vendor, family, model, stepping)
        "k6-3+": ("AuthenticAMD", 5, 0xD, 0), "k6-2+": ("AuthenticAMD", 5, 0xD, 0),
        "k6-3": ("AuthenticAMD", 5, 9, 1), "k6-2cxt": ("AuthenticAMD", 5, 8, 0xC),
        "k6-2": ("AuthenticAMD", 5, 8, 0), "k6": ("AuthenticAMD", 5, 6, 2),
        "intel": ("GenuineIntel", 6, 5, 2), "k5": ("AuthenticAMD", 5, 1, 4)}
    vend, fam, mod, step = cpus[cpu]

    def hk_cpuid(uc, _):
        leaf = uc.reg_read(UC_X86_REG_EAX)
        if leaf == 0:
            b, d, c = struct.unpack("<III", vend.encode())
            uc.reg_write(UC_X86_REG_EAX, 1); uc.reg_write(UC_X86_REG_EBX, b)
            uc.reg_write(UC_X86_REG_EDX, d); uc.reg_write(UC_X86_REG_ECX, c)
        else:
            uc.reg_write(UC_X86_REG_EAX, fam << 8 | mod << 4 | step)
            uc.reg_write(UC_X86_REG_EBX, 0); uc.reg_write(UC_X86_REG_ECX, 0)
            uc.reg_write(UC_X86_REG_EDX, 0x008021BF)
        return 1

    def pci_access(port, size, val=None):
        addr = st["cf8"]
        if not addr & 0x80000000:
            return 0xFFFFFFFF
        bus, dev, fn, reg = addr >> 16 & 0xFF, addr >> 11 & 0x1F, addr >> 8 & 7, addr & 0xFC
        d = st["pci"].get((bus, dev)) if fn == 0 else None
        off = port - 0xCFC
        assert 0 <= off < 4 and off + size <= 4, (hex(port), size)
        mask = (1 << (8 * size)) - 1
        if val is None:
            return (d.rd(reg) >> (8 * off)) & mask if d else mask
        if d:
            cur = d.rd(reg)
            new = (cur & ~(mask << (8 * off))) | ((val & mask) << (8 * off))
            d.wr(reg, new if size < 4 else val)
        else:
            st["bad"].append(("write to absent PCI dev", hex(addr)))

    def hk_in(uc, port, size, _):
        if 0xCFC <= port <= 0xCFF:
            return pci_access(port, size)
        if port == 0xCF8:
            return st["cf8"]
        st["bad"].append(("IN", hex(port)))
        return 0xFFFFFFFF

    def hk_out(uc, port, size, value, _):
        st["io"].append((port, size, value))
        if port == 0xCF8:
            st["cf8"] = value
        elif 0xCFC <= port <= 0xCFF:
            pci_access(port, size, value)
        elif port == 0xFFF8:
            if not msr[0xC0000086] & 1:
                st["bad"].append("BVC write with EPMR I/O block disabled")
        else:
            st["bad"].append(("OUT", hex(port)))

    def hk_intr(uc, intno, _):
        ax = uc.reg_read(UC_X86_REG_AX)
        fl = uc.reg_read(UC_X86_REG_EFLAGS)
        if intno == 0x10:
            assert ax >> 8 == 0x0E
            st["tty"] += chr(ax & 0xFF)
        elif intno == 0x15:
            if ax == 0xE801 and e801:
                below = 14336 if hole else min(mem_kb - 1024, 15360)
                above = max(0, (mem_kb - 16384) // 64)
                for r, v in ((UC_X86_REG_AX, below), (UC_X86_REG_BX, above), (UC_X86_REG_CX, below), (UC_X86_REG_DX, above)):
                    uc.reg_write(r, v)
                uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1)
            elif ax >> 8 == 0x88:
                uc.reg_write(UC_X86_REG_AX, min(mem_kb - 1024, 0xFFFF)); uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1)
            else:
                uc.reg_write(UC_X86_REG_AX, 0x8600 | (ax & 0xFF)); uc.reg_write(UC_X86_REG_EFLAGS, fl | 1)
        elif intno == 0xF0:  # rdmsr
            ecx = uc.reg_read(UC_X86_REG_ECX)
            if ecx not in msr: st["bad"].append(("rdmsr", hex(ecx)))
            v = msr.get(ecx, 0)
            uc.reg_write(UC_X86_REG_EAX, v & 0xFFFFFFFF); uc.reg_write(UC_X86_REG_EDX, v >> 32)
        elif intno == 0xF1:  # wrmsr
            ecx = uc.reg_read(UC_X86_REG_ECX)
            v = uc.reg_read(UC_X86_REG_EDX) << 32 | uc.reg_read(UC_X86_REG_EAX)
            if ecx not in msr: st["bad"].append(("wrmsr", hex(ecx)))
            if ecx == 0xC0000080 and v & ~0xFF: st["bad"].append(("EFER reserved bits", hex(v)))
            msr[ecx] = v; st["msrlog"].append((hex(ecx), hex(v)))
        else:
            st["bad"].append(("int", hex(intno)))
            uc.emu_stop()

    mu.hook_add(UC_HOOK_INSN, hk_cpuid, None, 1, 0, UC_X86_INS_CPUID)
    mu.hook_add(UC_HOOK_INSN, hk_in, None, 1, 0, UC_X86_INS_IN)
    mu.hook_add(UC_HOOK_INSN, hk_out, None, 1, 0, UC_X86_INS_OUT)
    mu.hook_add(UC_HOOK_INTR, hk_intr)

    # Caller state: stack at 0000:7000, far return to RET stub
    regs0 = {UC_X86_REG_EAX: 0x11112222, UC_X86_REG_EBX: 0x33334444, UC_X86_REG_ECX: 0x55556666,
             UC_X86_REG_EDX: 0x77778888, UC_X86_REG_ESI: 0x9999AAAA, UC_X86_REG_EDI: 0xBBBBCCCC,
             UC_X86_REG_EBP: 0xDDDDEEEE, UC_X86_REG_DS: 0x1234, UC_X86_REG_ES: 0x2345}
    for r, v in regs0.items(): mu.reg_write(r, v)
    mu.reg_write(UC_X86_REG_SS, 0); mu.reg_write(UC_X86_REG_ESP, 0x7000)
    sp = 0x7000 - 4
    mu.mem_write(sp, struct.pack("<HH", RET_OFF, RET_SEG))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    mu.reg_write(UC_X86_REG_CS, ROMSEG)
    mu.emu_start(ROMSEG * 16 + 3, RET_SEG * 16 + RET_OFF, timeout=5_000_000)
    for r, v in regs0.items():
        if mu.reg_read(r) != v: st["bad"].append(("reg clobbered", r, hex(mu.reg_read(r))))
    if mu.reg_read(UC_X86_REG_ESP) != 0x7000: st["bad"].append(("ESP", hex(mu.reg_read(UC_X86_REG_ESP))))
    if not mu.reg_read(UC_X86_REG_EFLAGS) & 0x200: st["bad"].append("IF not restored")
    for d in st["pci"].values():
        st["bad"] += d.bad
    st["msr"] = msr
    return st
