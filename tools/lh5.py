"""Minimal LH5 (LHA -lh5-) decoder + Award module lister/extractor."""
import sys, os

class BitReader:
    def __init__(self, data):
        self.d = data; self.pos = 0; self.buf = 0; self.n = 0
    def bits(self, k):
        while self.n < k:
            b = self.d[self.pos] if self.pos < len(self.d) else 0
            self.pos += 1
            self.buf = (self.buf << 8) | b; self.n += 8
        self.n -= k
        return (self.buf >> self.n) & ((1 << k) - 1)
    def peek(self, k):
        while self.n < k:
            b = self.d[self.pos] if self.pos < len(self.d) else 0
            self.pos += 1
            self.buf = (self.buf << 8) | b; self.n += 8
        return (self.buf >> (self.n - k)) & ((1 << k) - 1)

def make_decoder(lengths):
    # canonical huffman -> dict (len, code)->sym
    table = {}
    maxl = max(lengths) if lengths else 0
    code = 0
    for l in range(1, maxl + 1):
        for s, ln in enumerate(lengths):
            if ln == l:
                table[(l, code)] = s; code += 1
        code <<= 1
    return table, maxl

def decode_sym(br, dec):
    table, maxl = dec
    if isinstance(table, int):
        return table
    code = 0
    for l in range(1, maxl + 1):
        code = (code << 1) | br.bits(1)
        s = table.get((l, code))
        if s is not None:
            return s
    raise ValueError("bad code")

NC, NP, NT = 510, 14, 19

def read_pt_len(br, nn, nbit, special):
    n = br.bits(nbit)
    if n == 0:
        c = br.bits(nbit)
        return c  # constant
    lens = [0] * nn
    i = 0
    while i < n:
        c = br.bits(3)
        if c == 7:
            while br.bits(1): c += 1
        lens[i] = c; i += 1
        if i == special:
            z = br.bits(2)
            for _ in range(z): lens[i] = 0; i += 1
    return lens

def read_c_len(br, tdec):
    n = br.bits(9)
    if n == 0:
        return br.bits(9)
    lens = [0] * NC
    i = 0
    while i < n:
        c = decode_sym(br, tdec)
        if c <= 2:
            if c == 0: cnt = 1
            elif c == 1: cnt = br.bits(4) + 3
            else: cnt = br.bits(9) + 20
            for _ in range(cnt): lens[i] = 0; i += 1
        else:
            lens[i] = c - 2; i += 1
    return lens

def to_dec(x):
    if isinstance(x, int): return (x, 0)
    return make_decoder(x)

def lh5_decode(data, osize):
    br = BitReader(data)
    out = bytearray()
    blocksize = 0
    while len(out) < osize:
        if blocksize == 0:
            blocksize = br.bits(16)
            tdec = to_dec(read_pt_len(br, NT, 5, 3))
            cdec = to_dec(read_c_len(br, tdec))
            pdec = to_dec(read_pt_len(br, NP, 4, -1))
        blocksize -= 1
        c = decode_sym(br, cdec)
        if c < 256:
            out.append(c)
        else:
            ln = c - 256 + 3
            p = decode_sym(br, pdec)
            if p > 1:
                p = (1 << (p - 1)) + br.bits(p - 1)
            src = len(out) - p - 1
            for k in range(ln):
                out.append(out[src + k])
    return bytes(out[:osize])

def parse_modules(d):
    import re
    mods = []
    for m in re.finditer(rb'-lh[05]-', d):
        o = m.start() - 2
        hs = d[o]
        method = d[o+2:o+7]
        csize = int.from_bytes(d[o+7:o+11], 'little')
        osize = int.from_bytes(d[o+11:o+15], 'little')
        off_seg = d[o+15:o+19]
        nl = d[o+21]
        name = d[o+22:o+22+nl].decode('latin1')
        dstart = o + 2 + hs
        mods.append(dict(off=o, method=method, csize=csize, osize=osize,
                         name=name, data=d[dstart:dstart+csize], hdr=d[o:dstart],
                         typ=int.from_bytes(off_seg[2:4], 'little'),
                         loadoff=int.from_bytes(off_seg[0:2], 'little')))
    return mods

if __name__ == '__main__':
    src, outdir = sys.argv[1], sys.argv[2]
    d = open(src, 'rb').read()
    os.makedirs(outdir, exist_ok=True)
    for m in parse_modules(d):
        raw = lh5_decode(m['data'], m['osize']) if m['method'] == b'-lh5-' else m['data']
        open(os.path.join(outdir, m['name']), 'wb').write(raw)
        print(f"{m['off']:#07x} {m['name']:14s} csize={m['csize']:#07x} osize={m['osize']:#07x} type={m['typ']:#06x} hdrsum_ok? ")
