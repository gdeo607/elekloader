# SPDX-License-Identifier: GPL-2.0-or-later
"""The SDK alpha's render on a device whose DSP code goes in as a raw SHARC payload (`sharc_raw`): the
Digitakt II, through core-dt2 2.7 (gdeo607/Digi2Core).

A machine's render is the same SHARC assembly the Digitone II plays (docs/SDK.md, "render on the Digitone
II"): R4 = struct elek_voice, R8 = 32 floats, a C return. The builder assembles the mod's "sharc" sources
with the pinned Selache, and writes a stub for each machine: its dsp-inline voice routine, which core's
_sk_enter, sdk_dsp_voice and _sk_leave (core-dt2's sdk_dsp.s, sdk_dsp.c) run around the render. The stub
carries the machine's knob table for the DSP: each knob's slot (where core's ColdFire side keeps its value,
by the same rule as core-dt2's sdk.c) and its range. Each machine gets a core_dsp_voices row (its type ->
its stub) and a core_mf_selector row (the clone's sample selector, as STRING's)."""
import os
from pathlib import Path
import subprocess

from . import sharc_doj

SLOTS = 12
FREE_ORDER = (8, 9, 10, 11, 0, 1, 2, 3, 4, 5, 6, 7)


def slots(layout):
    """Each knob's slot (0-11), as core-dt2 2.7's sdk.c assigns them at boot: a knob on page 1 encoder e
    takes slot e, then page 2's knobs and the knobs on no page the free slots, page 2's first, in
    FREE_ORDER. -> [slot of knob 0, ...]."""
    n = len(layout['knobs'])
    slot_of, taken = [-1] * n, [False] * SLOTS

    def take(k, s):
        if 0 <= k < n and slot_of[k] < 0 and not taken[s]:
            slot_of[k], taken[s] = s, True

    def take_free(k):
        for s in FREE_ORDER:
            take(k, s)

    pages = layout['pages']
    for e, knob in (pages[0]['knobs'].items() if pages else ()):
        take(knob['id'], e)
    for e, knob in sorted(pages[1]['knobs'].items()) if len(pages) > 1 else ():
        take_free(knob['id'])
    for k in range(n):
        take_free(k)
    return slot_of


def stub_source(machines):
    """The stubs' assembly: machines = [(id, render label, [(min, max)], [slot])]."""
    lines = ['// The SDK alpha machines\' stubs (elekloader sdk_alpha_raw): each machine\'s dsp-inline voice routine.',
             '.SECTION/PM seg_pmco;', '.EXTERN _sk_odd;', '.EXTERN _sk_enter;', '.EXTERN _sk_leave;']
    lines += ['.EXTERN %s;' % label for label in sorted({m[1] for m in machines})]
    lines += ['.GLOBAL _sk%d;' % m[0] for m in machines]
    lines += ['.NOCOMPRESS;']
    for mid, label, _ranges, _slots in machines:
        lines += ['_sk%d:' % mid,
                  '    R1 = 1;', '    R1 = R0 AND R1;', '    IF NE JUMP _sk_odd;',
                  '    R1 = _sk%d_m;' % mid, '    CALL _sk_enter;',
                  '    R0 = PASS R0;', '    IF EQ JUMP _sk_leave;',
                  '    R4 = PASS R0;', '    R2 = I6;',
                  '    CJUMP %s (DB);' % label, '    DM(I7, M7) = R2;', '    DM(I7, M7) = _sk%d_back - 1;' % mid,
                  '_sk%d_back:' % mid, '    JUMP _sk_leave;']
    lines += ['.SECTION/DM seg_dmda;']
    for mid, _label, ranges, slot_of in machines:
        words = [mid, len(ranges)] + [s for s in slot_of] + [0] * (SLOTS - len(slot_of))
        words += [lo for lo, _hi in ranges] + [0] * (SLOTS - len(ranges))
        words += [hi for _lo, hi in ranges] + [0] * (SLOTS - len(ranges))
        # struct sdk_dsp_machine (sdk_dsp.c), in hex: selas reads `.VAR = -50;` as a symbol
        lines.append('.VAR _sk%d_m = 0x%x;' % (mid, words[0] & 0xffffffff))
        lines += ['.VAR = 0x%x;' % (w & 0xffffffff) for w in words[1:]]
    return '\n'.join(lines) + '\n'


def _assemble(tools, src, work):
    out = os.path.join(work, Path(src).stem + '.doj')
    r = subprocess.run([str(tools / 'selas'), '-proc', 'ADSP-21569', '-o', out, str(src)],
                       capture_output=True, text=True)
    if r.returncode:
        raise ValueError('selas %s:\n%s%s' % (Path(src).name, r.stdout, r.stderr))
    with open(out, 'rb') as fh:
        return sharc_doj.read(fh.read(), Path(src).name)


def raw_doc(sources, machines, work, selector):
    """The mod's `sharc_raw` payload: its assembly and the stubs as objects, and each machine's
    core_dsp_voices and core_mf_selector rows. machines = [(id, render label, [(min, max)], [slot])];
    selector = the stock sample selector the machines clone (an address in the DSP's code). Raises
    ValueError."""
    from .sharc import selache_tools
    tools = selache_tools()
    objects = [_assemble(tools, src, work) for src in sources]
    stubs = os.path.join(work, 'sdk_alpha_stubs.s')
    with open(stubs, 'w') as fh:
        fh.write(stub_source(machines))
    objects.append(_assemble(tools, stubs, work))
    defined = {s['name'] for ob in objects for s in ob['symbols'] if s.get('section') is not None and s.get('global')}
    for mid, label, _r, _s in machines:
        if label not in defined:
            raise ValueError('the SHARC assembly defines no global %s' % label)
    contribute = []
    for mid, _label, _r, _s in machines:
        contribute.append({'to': 'core_dsp_voices', 'parts': [['hex', '%02x' % mid + '00' * 7]],
                           'relocs': [[4, 'le32', 'sym:_sk%d' % mid, 0]]})
        contribute.append({'to': 'core_mf_selector', 'index': mid, 'parts': [['stock', '0x%x' % selector, 4]]})
    return {'objects': objects, 'contribute': contribute}
