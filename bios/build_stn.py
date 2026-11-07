"""Build patched system BIOS (stn.bin) for ASUS P5A 1011.005 and put it into the image.

Patches (E000 = stn[0x0000..], F000 = stn[0x10000..]):
  1. E000:E425  'jmp short E443'  -> Symbios PCI-ID scan skipped, module 0800 always loaded
                (still gated by the setup item at F000:7105, value 0 = load)
  2. F000:7417  setup label 'SYMBIOS SCSI BIOS  : ' -> 'K6PLUS CPU Tweaks  : '
  3. F000:747F  value 'Auto    ' -> 'Enabled '
  4. E000:D7B5  K6-III name: call E000:F000 (CPUID model D -> 'AMD-K6(tm)-III+')
  5. E000:1C93 + E000:FFC4  ROM.by 4.23 multiplier/MHz rounding table
  6. F000:22B2  ROM.by 4.23: 'Y' default for Save & Exit
LHA header CRC16 of stn.bin is kept by 2 compensation bytes at E000:EFB0.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from lh5 import parse_modules, lh5_decode
from lh5enc import lh5_encode
from crc16 import crc16, fix_crc

HERE = os.path.dirname(os.path.abspath(__file__))
E, F = 0x0000, 0x10000


def patch(buf, off, old, new):
    old = bytes.fromhex(old) if isinstance(old, str) else old
    new = bytes.fromhex(new) if isinstance(new, str) else new
    assert len(old) == len(new), hex(off)
    assert buf[off:off + len(old)] == old, f"{off:#x}: {buf[off:off+len(old)].hex()} != {old.hex()}"
    buf[off:off + len(new)] = new


def build_raw(stn):
    s = bytearray(stn)
    # 1. loader: skip PCI vendor/device test
    patch(s, E + 0xE425, "32c9", "eb1c")
    assert s[E + 0xE443:E + 0xE446] == bytes.fromhex("be0008")
    # 2./3. setup texts
    patch(s, F + 0x7417, b"SYMBIOS SCSI BIOS  : ", b"K6PLUS CPU Tweaks  : ")
    patch(s, F + 0x747F, b"Auto    ", b"Enabled ")
    # 4. CPU name
    code = open(os.path.join(HERE, "cpuname.bin"), "rb").read()
    patch(s, E + 0xF000, b"\xff" * len(code), code)
    rel = (0xF000 - (0xD7B5 + 3)) & 0xFFFF
    patch(s, E + 0xD7B5, "be9bd8", bytes([0xE8, rel & 0xFF, rel >> 8]))
    assert s[E + 0xD7B8:E + 0xD7BA] == bytes.fromhex("eb31")
    # 5. rounding table (from ROM.by 4.23 modul.tmp)
    tbl = bytes.fromhex("f4f2a0cac8a0c2c0909d9b90908e807774906e6c805e5cd05250904d4b802c2a802220a00a088007059000")
    patch(s, E + 0xFFC4, b"\xff" * len(tbl), tbl)
    patch(s, E + 0x1C93, "951f", "c4ff")
    # 6. 'Y' default
    patch(s, F + 0x22B2, "b04eb459", "b059b44e")
    # CRC compensation
    s = bytearray(fix_crc(bytes(s), E + 0xEFB0, crc16(stn)))
    assert crc16(s) == crc16(stn)
    return bytes(s)


def main(img_in, img_out):
    img = bytearray(open(img_in, "rb").read())
    m = [x for x in parse_modules(img) if x["name"] == "stn.bin"][0]
    base = m["off"]; hs = img[base]
    stn = lh5_decode(m["data"], m["osize"])
    raw = build_raw(stn)
    ext = os.environ.get("LZH")
    if ext:                                   # stream from original LHA.EXE archive
        a = open(ext, "rb").read()
        assert a[2:7] == b"-lh5-"
        ahs = a[0]; acs = int.from_bytes(a[7:11], "little")
        assert a[0x14] in (0, 1)
        if a[0x14] == 1:                      # level-1: ext headers counted in csize
            p = 2 + ahs; ext_sz = int.from_bytes(a[p-2:p], "little"); skip = 0
            while ext_sz:
                skip += ext_sz; p += ext_sz; ext_sz = int.from_bytes(a[p-2:p], "little")
            comp = a[2 + ahs + skip: 2 + ahs + acs]
        else:
            comp = a[2 + ahs: 2 + ahs + acs]
        print("using LHA.EXE stream", len(comp))
    else:
        comp = lh5_encode(raw)
    assert lh5_decode(comp, len(raw)) == raw
    print(f"stn.bin: original csize {m['csize']:#x}, new {len(comp):#x} ({len(comp)-m['csize']:+d})")
    hdr = bytearray(img[base:base + 2 + hs])
    hdr[7:11] = len(comp).to_bytes(4, "little")
    hdr[1] = sum(hdr[2:2 + hs]) & 0xFF                       # LHA header checksum
    end_old = base + 2 + hs + m["csize"] + 2                  # incl. terminator + checksum byte
    mod = bytes(hdr) + comp + b"\x00"
    limit = 0x36000
    assert base + len(mod) + 1 <= limit, "no room"
    # clear old area to FF, write new module + bootblock checksum byte
    img[base:end_old] = b"\xff" * (end_old - base)
    img[base:base + len(mod)] = mod
    img[base + len(mod)] = sum(mod) & 0xFF
    open(img_out, "wb").write(img)
    open(os.path.join(HERE, "stn_patched.bin"), "wb").write(raw)
    print("written", img_out)


if __name__ == "__main__":
    main(*sys.argv[1:3])
