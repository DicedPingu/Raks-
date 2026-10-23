"""Tiny pure-Python QR code generator (byte mode, ECC level M, versions 1-10).

Written for Raks following the public QR Code specification (ISO/IEC 18004).
MIT licensed as part of this project.
"""

ECC_PER_BLOCK_M = [10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
NUM_BLOCKS_M = [1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
FORMAT_BITS_M = 0


def _raw_modules(ver):
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        r -= (25 * n - 10) * n - 55
        if ver >= 7:
            r -= 36
    return r


def _data_capacity(ver):
    return _raw_modules(ver) // 8 - ECC_PER_BLOCK_M[ver - 1] * NUM_BLOCKS_M[ver - 1]


def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 2)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _encode_data(data: bytes, ver):
    bits = [0, 1, 0, 0]
    cc_bits = 8 if ver < 10 else 16
    bits += [(len(data) >> i) & 1 for i in range(cc_bits - 1, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    cap = _data_capacity(ver) * 8
    bits += [0] * min(4, cap - len(bits))
    bits += [0] * (-len(bits) % 8)
    out = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(out) < _data_capacity(ver):
        out.append(pad)
        pad ^= 0xEC ^ 0x11
    return out


def _interleave(data, ver):
    nb = NUM_BLOCKS_M[ver - 1]
    ecc_len = ECC_PER_BLOCK_M[ver - 1]
    raw = _raw_modules(ver) // 8
    short = nb - raw % nb
    short_len = raw // nb
    div = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(nb):
        dlen = short_len - ecc_len + (0 if i < short else 1)
        dat = data[k:k + dlen]
        k += dlen
        ecc = _rs_remainder(dat, div)
        if i < short:
            dat = dat + [0]
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecc_len or j >= short:
                out.append(blk[i])
    return out


class _Matrix:
    def __init__(self, ver):
        self.ver = ver
        self.size = ver * 4 + 17
        n = self.size
        self.m = [[False] * n for _ in range(n)]
        self.f = [[False] * n for _ in range(n)]
        self._function_patterns()

    def _set(self, x, y, v):
        self.m[y][x] = bool(v)
        self.f[y][x] = True

    def _function_patterns(self):
        n = self.size
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self._set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self._align_positions()
        k = len(pos)
        for i in range(k):
            for j in range(k):
                if (i == 0 and j == 0) or (i == 0 and j == k - 1) or (i == k - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(pos[i] + dx, pos[j] + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        self._version_bits()

    def _align_positions(self):
        ver = self.ver
        if ver == 1:
            return []
        k = ver // 7 + 2
        step = (ver * 4 + k * 2 + 1) // (k * 2 - 2) * 2
        return [6] + [self.size - 7 - (k - 2 - i) * step for i in range(k - 1)]

    def _version_bits(self):
        ver = self.ver
        if ver < 7:
            return
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = ver << 12 | rem
        for i in range(18):
            b = (bits >> i) & 1
            a = self.size - 11 + i % 3
            c = i // 3
            self._set(a, c, b)
            self._set(c, a, b)

    def draw_format(self, mask):
        n = self.size
        data = FORMAT_BITS_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412

        def bit(i):
            return (bits >> i) & 1
        for i in range(6):
            self._set(8, i, bit(i))
        self._set(8, 7, bit(6))
        self._set(8, 8, bit(7))
        self._set(7, 8, bit(8))
        for i in range(9, 15):
            self._set(14 - i, 8, bit(i))
        for i in range(8):
            self._set(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, bit(i))
        self._set(8, n - 8, True)

    def draw_codewords(self, data):
        n = self.size
        i = 0
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.f[y][x] and i < len(data) * 8:
                        self.m[y][x] = bool((data[i >> 3] >> (7 - (i & 7))) & 1)
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        n = self.size
        for y in range(n):
            for x in range(n):
                if self.f[y][x]:
                    continue
                if mask == 0:
                    inv = (x + y) % 2 == 0
                elif mask == 1:
                    inv = y % 2 == 0
                elif mask == 2:
                    inv = x % 3 == 0
                elif mask == 3:
                    inv = (x + y) % 3 == 0
                elif mask == 4:
                    inv = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    inv = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    inv = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    inv = ((x + y) % 2 + x * y % 3) % 2 == 0
                if inv:
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        n, m = self.size, self.m
        score = 0
        for grid in (m, [list(c) for c in zip(*m)]):
            for row in grid:
                run = 1
                for i in range(1, n):
                    if row[i] == row[i - 1]:
                        run += 1
                    else:
                        if run >= 5:
                            score += run - 2
                        run = 1
                if run >= 5:
                    score += run - 2
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(r) for r in m)
        score += abs(dark * 20 - n * n * 10) // (n * n) * 10
        return score


def make_qr(text: str):
    """Return the QR code as a list of rows of booleans (True = dark), no quiet zone."""
    data = text.encode("utf-8")
    ver = None
    for v in range(1, 11):
        need = 4 + (8 if v < 10 else 16) + 8 * len(data)
        if need <= _data_capacity(v) * 8:
            ver = v
            break
    if ver is None:
        raise ValueError("text too long for QR versions 1-10 (max ~213 bytes)")
    codewords = _interleave(_encode_data(data, ver), ver)
    mat = _Matrix(ver)
    mat.draw_codewords(codewords)
    best, best_score = 0, None
    for mask in range(8):
        mat.apply_mask(mask)
        mat.draw_format(mask)
        s = mat.penalty()
        mat.apply_mask(mask)
        if best_score is None or s < best_score:
            best, best_score = mask, s
    mat.apply_mask(best)
    mat.draw_format(best)
    return mat.m


def to_ascii(matrix, border=2, color=True):
    """Render with half-block characters; black-on-white so it scans on dark terminals."""
    n = len(matrix)
    size = n + 2 * border

    def dark(x, y):
        x -= border
        y -= border
        return 0 <= x < n and 0 <= y < n and matrix[y][x]
    on, off = ("\x1b[30;47m", "\x1b[0m") if color else ("", "")
    chars = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}
    lines = []
    for y in range(0, size, 2):
        row = "".join(chars[(dark(x, y), dark(x, y + 1))] for x in range(size))
        lines.append(on + row + off)
    return "\n".join(lines)


def to_svg(matrix, border=2):
    n = len(matrix)
    size = n + 2 * border
    rects = "".join("M%d %dh1v1h-1z" % (x + border, y + border)
                    for y, row in enumerate(matrix) for x, v in enumerate(row) if v)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
            '<rect width="100%%" height="100%%" fill="#fff"/><path d="%s" fill="#000"/></svg>'
            % (size, size, rects))
