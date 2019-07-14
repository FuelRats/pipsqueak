"""
System name autocorrection

Copyright (c) 2017 The Fuel Rats Mischief,
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""
import re
import collections
import functools


class CorrectionResult:
    # Table of lookalikes
    digits = "001258"
    letters = "doizsb"
    lookalikes = {'L': dict(zip(digits, letters)), 'D': dict(zip(letters, digits))}

    # Allowed characters for each pattern.  Matches regex syntax within a [group]
    allowed = {'L': 'a-z', 'D': '0-9'}

    # Create the regular expression we use to match systems
    pattern = (r'\w+\s+(?P<l>LL-L\s+L)(?P<d>D+(?:-D+)?'
               r')\b')  # L and D will be replaced from lookalikes and allowed.
    for search, characters in allowed.items():
        pattern = pattern.replace(search, "[" + characters + "".join(lookalikes[search].keys()) + "]")
    regex = re.compile("(?i)" + pattern)

    def __init__(self, input):
        def fn(match):
            old = match.group(0)
            new = self._subfn(match)
            if old != new:
                self.corrections[old] = new
            return new

        self.input = input
        self.corrections = collections.OrderedDict()
        self.matched = 0
        self.fixed = 0
        self.output = self.regex.sub(self._subfn, input)

    def _subfn(self, match):
        """Performs corrections on patterns"""
        self.matched += 1
        old = match.group(0)
        new = None
        offset = match.start(0)  # Offset to all other patterns
        for key, value in match.groupdict().items():
            table = self.lookalikes.get(key[0].upper())
            if table is None:
                continue
            start = match.start(key)
            if start == -1:
                continue
            start -= offset
            for pos, ch in enumerate(value.lower(), start=start):
                if ch in table:
                    if new is None:
                        new = list(old)
                    new[pos] = table[ch].upper()
        if new:
            new = "".join(new)
            self.corrections[old] = new
            self.fixed += 1
            return new
        return old

    def __str__(self):
        return self.output

    def __repr__(self):
        return "<{0.__class__.__name__}(matched={0.matched}, fixed={0.fixed}, input={0.input!r}, corrections={0.corrections!r})>".format(self)


@functools.lru_cache(typed=True)
def correct(input):
    return CorrectionResult(input)


pattern = CorrectionResult.pattern
regex = CorrectionResult.regex

if __name__ == '__main__':
    print(repr(correct("Should trigger correction: Imaginary Sector CX-5 DS-9 Blah blah")))
    print(repr(correct("Should not trigger correction: Blah Blah Sector DE-F A2-33")))
