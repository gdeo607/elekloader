# SPDX-License-Identifier: GPL-2.0-or-later
"""A Selache object file (.doj, ELF32 little-endian) as a raw SHARC object: the layout elekloader.sharc's
`_object` reads in a `sharc_raw` payload (digikit's .dko.json layout): sections (text, data, bss), symbols
and the code's address relocations.

Code's 16-bit parcels are big-endian in a .doj and little-endian in the raw object (as the DSP section loads
them). Selache's relocation types in code: 11, a 24-bit address (`sharc.abs24`: a jump's or call's target) and 12, a
32-bit one (`sharc.abs32`: an immediate load of a symbol); r_offset counts 16-bit parcels from the section's
start, as a text symbol's value does. A relocation in a data section (a `.VAR` holding an address) is refused:
the raw linker places no data relocation."""
import struct

RELOC_TYPES = {11: 'sharc.abs24', 12: 'sharc.abs32'}
SHT_SYMTAB, SHT_RELA, SHT_NOBITS, SHT_PROGBITS = 2, 4, 8, 1
SHF_EXECINSTR = 4


class DojError(ValueError):
    pass


def read(raw, name):
    """The object in `raw` (bytes of a .doj) as {name, sections, symbols, relocs}. Raises DojError."""
    if raw[:4] != b'\x7fELF' or raw[4] != 1 or raw[5] != 1:
        raise DojError('%s: not a 32-bit little-endian ELF object' % name)
    shoff, = struct.unpack_from('<I', raw, 32)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', raw, 46)
    heads = [struct.unpack_from('<10I', raw, shoff + shentsize * i) for i in range(shnum)]

    def text(table, at):
        start = heads[table][4] + at
        return raw[start:raw.index(b'\0', start)].decode()

    names = [text(shstrndx, h[0]) for h in heads]
    sections, kept = [], {}
    for i, (h, nm) in enumerate(zip(heads, names)):
        kind = h[1]
        if kind not in (SHT_PROGBITS, SHT_NOBITS) or not h[5] or nm.startswith('.'):
            continue                            # tables, notes, debug and empty sections
        align = max(1, h[8])
        if kind == SHT_NOBITS:
            sc = {'name': nm, 'kind': 'bss', 'align': align, 'size': h[5]}
        else:
            body = raw[h[4]:h[4] + h[5]]
            code = bool(h[2] & SHF_EXECINSTR)
            if code:                            # .doj parcels are big-endian; the raw object's little-endian
                if len(body) % 2:
                    raise DojError('%s: %s is not whole 16-bit parcels' % (name, nm))
                body = b''.join(body[i:i + 2][::-1] for i in range(0, len(body), 2))
            sc = {'name': nm, 'kind': 'text' if code else 'data', 'align': align, 'hex': body.hex()}
        sections.append(sc)
        kept[i] = sc
    symbols, by_index = [], {}
    for h in heads:
        if h[1] != SHT_SYMTAB:
            continue
        for k, at in enumerate(range(h[4], h[4] + h[5], 16)):
            nmo, value, _size, info, _other, shndx = struct.unpack_from('<IIIBBH', raw, at)
            sym = text(h[6], nmo) if nmo else ''
            by_index[k] = sym
            if not sym or info & 0xf in (3, 4):             # sections and files
                continue
            if shndx == 0:
                symbols.append({'name': sym, 'section': None, 'global': True})      # an import
            elif shndx in kept:
                symbols.append({'name': sym, 'section': kept[shndx]['name'], 'value': value,
                                'global': info >> 4 != 0})
    relocs = []
    for h, nm in zip(heads, names):
        if h[1] != SHT_RELA or h[7] not in kept:
            continue
        sc = kept[h[7]]
        for at in range(h[4], h[4] + h[5], 12):
            off, info, addend = struct.unpack_from('<IIi', raw, at)
            kind = RELOC_TYPES.get(info & 0xff)
            if sc['kind'] != 'text':
                raise DojError('%s: %s holds an address (a relocation in data); keep addresses out of '
                               '.VAR data, load them in code' % (name, sc['name']))
            if kind is None:
                raise DojError('%s: relocation type %d in %s' % (name, info & 0xff, sc['name']))
            relocs.append({'section': sc['name'], 'offset': off, 'type': kind, 'symbol': by_index[info >> 8],
                           'addend': addend})
    return {'name': name, 'sections': sections, 'symbols': symbols, 'relocs': relocs}
