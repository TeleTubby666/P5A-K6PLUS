"""Minimal LH5 encoder (single or multiple blocks, canonical Huffman, LZ77 8K window)."""
import heapq

NC, NP, NT = 510, 14, 19
MAXLEN = 256
WIN = 8192


class BitWriter:
    def __init__(self):
        self.out = bytearray(); self.acc = 0; self.n = 0
    def put(self, val, k):
        for i in range(k - 1, -1, -1):
            self.acc = (self.acc << 1) | ((val >> i) & 1); self.n += 1
            if self.n == 8:
                self.out.append(self.acc); self.acc = 0; self.n = 0
    def flush(self):
        if self.n:
            self.out.append(self.acc << (8 - self.n)); self.acc = 0; self.n = 0
        return bytes(self.out)


def huff_lengths(freq, maxbits=16):
    syms = [(f, s) for s, f in enumerate(freq) if f]
    lens = [0] * len(freq)
    if not syms:
        return lens
    if len(syms) == 1:
        lens[syms[0][1]] = 1
        return lens
    f2 = list(freq)
    while True:
        heap = [(f, i, [s]) for i, (f, s) in enumerate((f2[s], s) for s in range(len(f2)) if f2[s])]
        heapq.heapify(heap)
        cnt = len(heap)
        L = [0] * len(freq)
        while len(heap) > 1:
            a = heapq.heappop(heap); b = heapq.heappop(heap)
            for s in a[2] + b[2]: L[s] += 1
            cnt += 1
            heapq.heappush(heap, (a[0] + b[0], cnt, a[2] + b[2]))
        if max(L) <= maxbits:
            return L
        f2 = [(x + 1) // 2 if x else 0 for x in f2]   # flatten and retry


def canon_codes(lens):
    codes = [0] * len(lens); code = 0
    for l in range(1, max(lens) + 1):
        for s, ln in enumerate(lens):
            if ln == l:
                codes[s] = code; code += 1
        code <<= 1
    return codes


def lz77(data):
    """Greedy + 1-step lazy matching with hash chains. Returns list of (lit) or (len, dist0)."""
    n = len(data); toks = []; head = {}; prev = [-1] * n
    def insert(i):
        if i + 2 < n:
            k = data[i:i + 3]; prev[i] = head.get(k, -1); head[k] = i
    def best(i):
        bl, bd = 0, 0
        if i + 2 >= n: return 0, 0
        j = head.get(data[i:i + 3], -1); tries = 0
        while j >= 0 and i - j <= WIN - 1 and tries < 512:
            l = 0; m = min(MAXLEN, n - i)
            while l < m and data[j + l] == data[i + l]: l += 1
            if l > bl: bl, bd = l, i - j - 1
            if l == m: break
            j = prev[j]; tries += 1
        return bl, bd
    i = 0
    while i < n:
        l, d = best(i)
        if l >= 3 and i + 1 < n:
            insert(i)
            l2, d2 = best(i + 1)
            if l2 > l + 1:
                toks.append(data[i]); i += 1
                continue
            for k in range(1, l): insert(i + k)
            toks.append((l, d)); i += l
        else:
            insert(i); toks.append(data[i]); i += 1
    return toks


def pcode(d):
    if d == 0: return 0, 0, 0
    if d == 1: return 1, 0, 0
    p = d.bit_length()
    return p, d - (1 << (p - 1)), p - 1


def write_pt(bw, lens, nn, nbit, special):
    n = nn
    while n > 0 and lens[n - 1] == 0: n -= 1
    if n == 0 or sum(1 for x in lens if x) == 1 and False:
        pass
    bw.put(n, nbit)
    i = 0
    while i < n:
        c = lens[i]
        if c <= 6: bw.put(c, 3)
        else:
            bw.put(7, 3)
            for _ in range(c - 7): bw.put(1, 1)
            bw.put(0, 1)
        i += 1
        if i == special:
            z = 0
            while z < 3 and i + z < n and lens[i + z] == 0: z += 1
            bw.put(z, 2); i += z


def encode_block(bw, toks):
    cf = [0] * NC; pf = [0] * NP
    for t in toks:
        if isinstance(t, int): cf[t] += 1
        else:
            cf[256 + t[0] - 3] += 1; pf[pcode(t[1])[0]] += 1
    bw.put(len(toks), 16)
    used_c = [s for s in range(NC) if cf[s]]
    # ---- C table ----
    if len(used_c) == 1:
        # constant C: T table constant too
        bw.put(0, 5); bw.put(0, 5)
        bw.put(0, 9); bw.put(used_c[0], 9)
        clen = None
    else:
        clen = huff_lengths(cf)
        n = NC
        while n > 0 and clen[n - 1] == 0: n -= 1
        # build T symbols
        tsyms = []; i = 0
        while i < n:
            if clen[i] == 0:
                z = 0
                while i + z < n and clen[i + z] == 0: z += 1
                i += z
                while z > 0:
                    if z <= 2:
                        tsyms.append((0, 0, 0)); z -= 1
                    elif z <= 18:
                        tsyms.append((1, z - 3, 4)); z = 0
                    elif z == 19:
                        tsyms.append((0, 0, 0)); tsyms.append((1, 15, 4)); z = 0
                    else:
                        k = min(z, 20 + 511); tsyms.append((2, k - 20, 9)); z -= k
            else:
                tsyms.append((clen[i] + 2, 0, 0)); i += 1
        tf = [0] * NT
        for s, _, _ in tsyms: tf[s] += 1
        used_t = [s for s in range(NT) if tf[s]]
        if len(used_t) == 1:
            bw.put(0, 5); bw.put(used_t[0], 5)
            tlen = None
        else:
            tlen = huff_lengths(tf); write_pt(bw, tlen, NT, 5, 3)
            tcode = canon_codes(tlen)
        bw.put(n, 9)
        for s, extra, eb in tsyms:
            if tlen is not None: bw.put(tcode[s], tlen[s])
            if eb: bw.put(extra, eb)
        ccode = canon_codes(clen)
    # ---- P table ----
    used_p = [s for s in range(NP) if pf[s]]
    if len(used_p) <= 1:
        bw.put(0, 4); bw.put(used_p[0] if used_p else 0, 4)
        plen = None
    else:
        plen = huff_lengths(pf); write_pt(bw, plen, NP, 4, -1); pcodes = canon_codes(plen)
    # ---- symbols ----
    for t in toks:
        if isinstance(t, int):
            if clen is not None: bw.put(ccode[t], clen[t])
        else:
            c = 256 + t[0] - 3
            if clen is not None: bw.put(ccode[c], clen[c])
            p, ex, eb = pcode(t[1])
            if plen is not None: bw.put(pcodes[p], plen[p])
            if eb: bw.put(ex, eb)


def lh5_encode(data, blocksize=16384):
    toks = lz77(data); bw = BitWriter()
    for i in range(0, len(toks), blocksize):
        encode_block(bw, toks[i:i + blocksize])
    return bw.flush()
