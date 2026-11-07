"""LHA CRC16 and a 2-byte compensation helper."""


def crc16(data, crc=0):
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def fix_crc(data, off, target):
    """Choose data[off], data[off+1] so that crc16(data) == target."""
    pre = crc16(data[:off])
    suffix = data[off + 2:]
    # crc after suffix is affine in the state s before it: f(s) = L(s) ^ K
    K = crc16(suffix, 0)
    basis = [crc16(suffix, 1 << i) ^ K for i in range(16)]
    def f(s):
        r = K
        for i in range(16):
            if s >> i & 1: r ^= basis[i]
        return r
    for x in range(256):
        s1 = crc16(bytes([x]), pre)
        for y in range(256):
            if f(crc16(bytes([y]), s1)) == target:
                d = bytearray(data); d[off] = x; d[off + 1] = y
                assert crc16(d) == target
                return bytes(d)
    raise RuntimeError("no CRC solution")
