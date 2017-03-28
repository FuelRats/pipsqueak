"""
Rudimentary bloom filter implementation, along with some pure Python hash functions.
"""
import functools
import itertools
from binascii import crc32

# Note that the hash algorithms presented here are NOT secure for any sort of cryptographic use.  They're optimized
# for speed first, for this BloomFilter implementation where hash collisions are not critical

# Fowler-Noll-Vo hash functions (FNV-1 and FNV-1a) implementations
# See:
#   https://en.wikipedia.org/wiki/Fowler%E2%80%93Noll%E2%80%93Vo_hash_function
#   http://www.isthe.com/chongo/tech/comp/fnv/index.html#public_domain
def _fnv1_impl(bits, prime, basis, data):
    mask = (2**bits)-1
    result = basis
    for octet in data:
        result = ((result * prime) ^ octet) & mask
    return result

def _fnv1a_impl(bits, prime, basis, data):
    mask = (2**bits)-1
    result = basis
    for octet in data:
        result = ((result ^ octet) * prime) & mask
    return result

fnv_primes = {
    32: 2**24 +2**8 + 0x93,
    64: 2**40 + 2**8 + 0xb3,
    128: 2**88 + 2**8 + 0x3b,
    256: 2**168 + 2**8 + 0x63,
    512: 2**344 + 2**8 + 0x57,
    1024: 2**680 + 2**8 + 0x8d
}
fnv_basis = dict((k, _fnv1_impl(k, v, 0, b"chongo <Landon Curt Noll> /\\../\\")) for k, v in fnv_primes.items())


def _f(k):
    return functools.partial(_fnv1_impl, k, fnv_primes[k], fnv_basis[k])
fnv1_32 = _f(32)
fnv1_64 = _f(64)
fnv1_128 = _f(128)
fnv1_256 = _f(256)
fnv1_512 = _f(512)
fnv1_1024 = _f(1024)


def _f(k):
    return functools.partial(_fnv1a_impl, k, fnv_primes[k], fnv_basis[k])
fnv1a_32 = _f(32)
fnv1a_64 = _f(64)
fnv1a_128 = _f(128)
fnv1a_256 = _f(256)
fnv1a_512 = _f(512)
fnv1a_1024 = _f(1024)

def jenkins_32(data):
    mask = (2**32) - 1
    result = 0
    for octet in data:
        result += octet
        result &= mask
        result += ((result << 10) & mask)
        result &= mask
        result ^= (result >> 6)
    result += ((result << 3) & mask)
    result &= mask
    result ^= (result >> 11)
    result += ((result << 11) & mask)
    result &= mask
    return result


class BloomFilter:
    """Bloom filter implementation"""


    NBITS = list(sum(1 if octet & 1 << n else 0 for n in range(8)) for octet in range(256))
    DEFAULT_FUNCTIONS = [fnv1a_32, jenkins_32]

    @staticmethod
    def _round_up(value, increment):
        return value + increment - ((value % increment) or increment)

    def __init__(self, bits, functions=None, data=None):
        """
        Creates a new BloomFilter that is 'size' bits wide.

        :param bits: Size in bits.  ('m')
        :param functions: List of hash functions.  These should accept bytes input and return an integer.
        :param data: Initial data as a bytes, bytearray or buffer.  Set to all zeroes if omitted.  Note that only the
            first (bits/8) bytes of this structure will be copied.
        """
        self.bits = bits
        if functions is None:
            functions = self.DEFAULT_FUNCTIONS
        self.functions = tuple(functions)

        self.data = bytearray(self._round_up(bits, 8) // 8)  # Quick round-up-to-nearest
        self._setbits = 0
        if data is not None:
            self.read(data)

    def read(self, data):
        """
        Copies data into self and updates the number of set bits.
        """
        for ix, octet in enumerate(data):
            self.data[ix] = octet
        self.count_bits()

    def count_bits(self):
        bits = 0
        for octet in self.data:
            bits += self.NBITS[octet]
        self._setbits = bits
        return bits

    @staticmethod
    def coerce(item):
        """
        Ensures item is bytes or bytes-like.
        :param item: Original item
        :return: Coerced item
        """
        if isinstance(item, str):
            return item.encode()
        return item

    def hashes(self, item):
        """
        Yields hash function results, in the format of (byte, 1<<bit)
        :param item: Item to be hashed.
        """
        item = self.coerce(item)
        for function in self.functions:
            byte, bit = divmod(function(item) % self.bits, 8)
            yield byte, 1 << bit

    def add(self, item):
        """
        Adds a new item to the bloom filter.
        :param item: Item to examine.  bytes or str
        :return: The number of bits set that weren't previously
        """
        rv = 0
        for byte, mask in self.hashes(item):
            if not self.data[byte] & mask:
                rv += 1
            self.data[byte] |= mask
        self._setbits += rv
        return rv

    def update(self, it):
        """
        Adds all items from the iterable.
        """
        rv = 0
        for item in it:
            rv += self.add(item)

    def has(self, item):
        """
        Returns True if the item is in the bloom filter.
        :param item: Item to examine.  bytes or str
        """
        for byte, mask in self.hashes(item):
            if not self.data[byte] & mask:
                return False
        return True

    def __contains__(self, item):
        return self.has(item)

    @property
    def setbits(self):
        """Returns the number of bits that are set to 1."""
        return self._setbits

    def false_positive_chance(self):
        """Returns approximate chance of false positive based on current utilization."""
        return (1 - ((self.bits - self.setbits) / self.bits)) ** len(self.functions)

    @classmethod
    def suggest_size(cls, rate, count, hashes=2, rounding=8):
        """
        Determines the number of bits required to have a false positive rate of 'rate' assuming 'count' items will be
        added and 'hashes' hash functions will be used.

        :param self:
        :param rate: Acceptable false positive rate (0..1)
        :param count: Anticipated number of items
        :param hashes: # of hash functions
        :param rounding: If non-None, the returned size is rounded up to the nearest multiple of this.
        :return:
        """
        if not (count > 0 and hashes > 0):
            raise ValueError("count and hashes must be positive")
        r = rate
        k = hashes
        n = count
        # This is a long and complicated formula I do not pretend to understand but it works when tested against
        # the other formula, which I do understand.
        bits = int((1 / (1 - (1 - r**(1/k))**(1/(k*n)))))
        if rounding:
            bits = cls._round_up(bits, rounding)
        return bits

    @classmethod
    def suggest_size_and_hashes(cls, rate, count, max_hashes=20, rounding=8):
        """
        Returns the lowest number of bits required to meet the accepted false positive rate and the number of hashes
        required.

        Note that this isn't a super-elegant implementation and relies on trial and error to come up with an answer.
        Extreme values may take awhile

        :param rate: Acceptable false positive rate (0..1)
        :param count: Anticipated number of items
        :param max_hashes: Maximum number of hashes, None = no limit
        :param rounding: If non-None, the returned size is rounded up to the nearest multiple of this.
        :return: bits, hashes
        """
        hashes = 0
        last = None
        while not max_hashes or hashes < max_hashes:
            hashes += 1
            bits = cls.suggest_size(rate, count, hashes, rounding)
            if last is not None and last < bits:
                return last, hashes - 1
            last = bits

    @classmethod
    def extend_hashes(cls, n, functions=None):
        """
        Extends the list of hash functions to a set size by adding duplicate copies that each use a unique salt.
        Or trims the list if n is smaller than the number of functions.
        :param n: Desired expansion size
        :param functions: Functions to expand.
        :return: Expanded list of functions.
        """
        if functions is None:
            functions = cls.DEFAULT_FUNCTIONS
        result = list(functions)
        if len(result) > n:
            return result[:n]

        it = iter(itertools.cycle(functions))
        for salt in range(n - len(result)):
            function = next(it)
            salt = str(function(str(salt).encode())).encode()
            result.append(lambda data, _salt=salt, _fn=function: _fn(_salt + data))
        return result

    @property
    def k(self):
        """k is the standard term used to describe the number of hash functions in a bloom filter."""
        return len(self.functions)

    @property
    def m(self):
        """m is the standard term used to describe the number of bits in a bloom filter."""
        return self.bits
