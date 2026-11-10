# SPDX-License-Identifier: GPL-2.0-or-later
"""The SDK alpha's render on the Digitakt II (sdk_alpha_raw, sharc_doj): the knobs' slots (core-dt2 2.7's rule),
the stubs' source, and, with SELACHE, the stubs and examples/sdk-sine's sine-dn2.s read as raw SHARC objects."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elekloader import sharc   # noqa: E402
from elekloader.sdk import sdk_alpha_raw, sharc_doj   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def layout(n, *pages):
    return {'knobs': [{'id': k} for k in range(n)],
            'pages': [{'knobs': {e: {'id': k} for e, k in page.items()}} for page in pages]}


class Slots(unittest.TestCase):
    def test_page_one_is_positional_then_page_two_then_the_rest(self):
        self.assertEqual(sdk_alpha_raw.slots(layout(1, {0: 0})), [0])
        self.assertEqual(sdk_alpha_raw.slots(layout(2, {0: 0}, {0: 1, 7: 0})), [0, 8])
        # a knob on no page takes page 2's slots first, then page 1's free ones
        self.assertEqual(sdk_alpha_raw.slots(layout(3, {3: 0})), [3, 8, 9])
        self.assertEqual(sdk_alpha_raw.slots(layout(12, {e: e for e in range(8)})), list(range(12)))
        self.assertEqual(sdk_alpha_raw.slots(layout(12, {}, {})), [8, 9, 10, 11, 0, 1, 2, 3, 4, 5, 6, 7])

    def test_the_stub_data_is_hex(self):
        text = sdk_alpha_raw.stub_source([(18, 'sine_render.', [(-50, 50)], [0])])
        self.assertIn('_sk18:', text)
        self.assertIn('CJUMP sine_render. (DB);', text)
        self.assertIn('.VAR = 0xffffffce;', text)          # min -50: selas reads `.VAR = -50;` as a symbol
        self.assertNotIn('= -', text)


@unittest.skipUnless(os.environ.get('SELACHE'), 'needs SELACHE (a clean Selache checkout, built)')
class Objects(unittest.TestCase):
    def assemble(self, src, work):
        from elekloader.sdk.sharc import selache_tools
        out = os.path.join(work, 'x.doj')
        subprocess.run([str(selache_tools() / 'selas'), '-proc', 'ADSP-21569', '-o', out, str(src)], check=True)
        with open(out, 'rb') as fh:
            return sharc_doj.read(fh.read(), Path(src).name)

    def test_sine_and_the_stubs_are_raw_objects(self):
        with tempfile.TemporaryDirectory() as work:
            sine = self.assemble(ROOT / 'examples/sdk-sine/sine-dn2.s', work)
            stub = Path(work) / 'stubs.s'
            stub.write_text(sdk_alpha_raw.stub_source([(18, 'sine_render.', [(-50, 50)], [0])]))
            stubs = self.assemble(stub, work)
        for ob in (sine, stubs):
            sharc._object(ob, 'test')                      # the linker reads it
        self.assertEqual({s['name'] for s in sine['symbols'] if s['global'] and s['section']}, {'sine_render.'})
        self.assertEqual({r['symbol'] for r in stubs['relocs']},
                         {'_sk_odd', '_sk_enter', '_sk_leave', 'sine_render.', '_sk18_m', '_sk18_back'})
        data = bytes.fromhex(next(s for s in stubs['sections'] if s['kind'] == 'data')['hex'])
        words = [int.from_bytes(data[i:i + 4], 'little', signed=True) for i in range(0, len(data), 4)]
        self.assertEqual(words[:3], [18, 1, 0])           # id, knob count, FINE's slot
        self.assertEqual((words[14], words[26]), (-50, 50))


if __name__ == '__main__':
    unittest.main()
