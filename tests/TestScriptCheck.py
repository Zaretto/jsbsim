# TestScriptCheck.py
#
# Test the <check> elements of the script events: the pass and fail counts,
# the AND and OR logic, the halt on failure, and the tolerances file.
#
# Copyright (c) 2026 Richard Harrison
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>
#

import os
import xml.etree.ElementTree as et
from JSBSim_utils import JSBSimTestCase, CreateFDM, ExecuteUntil, RunTest


class TestScriptCheck(JSBSimTestCase):
    def setUp(self):
        JSBSimTestCase.setUp(self)
        self.script_path = self.sandbox.path_to_jsbsim_file('scripts', 'c1722.xml')

    def write_script(self, events, tolerances_src=None, name='check_script.xml'):
        """Write a copy of the base script with extra events under <run>.

        events is a list of (event attributes, condition, notify attributes,
        checks), checks being a list of check attribute dicts.
        """
        tree = et.parse(self.script_path)
        root = tree.getroot()
        run = root.find('run')
        for event_attrs, condition, notify_attrs, checks in events:
            event = et.SubElement(run, 'event', event_attrs)
            et.SubElement(event, 'condition').text = condition
            notify = et.SubElement(event, 'notify', notify_attrs)
            for check in checks:
                et.SubElement(notify, 'check', check)
        if tolerances_src is not None:
            et.SubElement(root, 'tolerances', {'src': tolerances_src})
        tree.write(name)
        return name

    def run_script(self, name, end_time=3.0):
        fdm = CreateFDM(self.sandbox)
        self.assertTrue(fdm.load_script(name))
        fdm.run_ic()
        ExecuteUntil(fdm, end_time)
        return fdm

    def test_counts_start_at_zero(self):
        fdm = CreateFDM(self.sandbox)
        fdm.load_script(self.script_path)
        fdm.run_ic()
        self.assertEqual(fdm['simulation/script/checks-passed'], 0)
        self.assertEqual(fdm['simulation/script/checks-failed'], 0)

    def test_pass_and_fail_are_counted(self):
        name = self.write_script([
            ({'name': 'at one second'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.0', 'tol_abs': '0.02'},
                {'property': 'simulation/sim-time-sec', 'value': '5.0', 'tol_abs': '0.1'},
                {'property': 'simulation/sim-time-sec', 'value': '1.0', 'tol_rel': '0.05'},
            ]),
        ])
        fdm = self.run_script(name)
        self.assertEqual(fdm['simulation/script/checks-passed'], 2)
        self.assertEqual(fdm['simulation/script/checks-failed'], 1)

    def test_missing_property_fails_the_check(self):
        name = self.write_script([
            ({'name': 'no such property'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'no/such/property', 'value': '0.0', 'tol_abs': '1.0'},
            ]),
        ])
        fdm = self.run_script(name)
        self.assertEqual(fdm['simulation/script/checks-passed'], 0)
        self.assertEqual(fdm['simulation/script/checks-failed'], 1)

    def test_one_shot_event_checks_once(self):
        name = self.write_script([
            ({'name': 'once'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.0', 'tol_abs': '0.02'},
            ]),
        ])
        fdm = self.run_script(name, end_time=3.0)
        self.assertEqual(fdm['simulation/script/checks-passed'], 1)

    def test_and_logic_halts_when_any_check_fails(self):
        name = self.write_script([
            ({'name': 'halt', 'halt_on_failure': 'true'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.0', 'tol_abs': '0.02'},
                {'property': 'simulation/sim-time-sec', 'value': '5.0', 'tol_abs': '0.1'},
            ]),
        ])
        fdm = self.run_script(name, end_time=3.0)
        # The script stopped at the event rather than running to the end.
        self.assertLess(fdm.get_sim_time(), 1.5)
        self.assertEqual(fdm['simulation/script/checks-failed'], 1)

    def test_or_logic_passes_when_any_check_passes(self):
        name = self.write_script([
            ({'name': 'either', 'halt_on_failure': 'true'}, 'simulation/sim-time-sec ge 1.0',
             {'logic': 'OR'}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.0', 'tol_abs': '0.02'},
                {'property': 'simulation/sim-time-sec', 'value': '5.0', 'tol_abs': '0.1'},
            ]),
        ])
        fdm = self.run_script(name, end_time=3.0)
        # One check failed, but with OR logic the event passed and did not halt.
        self.assertGreater(fdm.get_sim_time(), 2.9)
        self.assertEqual(fdm['simulation/script/checks-passed'], 1)
        self.assertEqual(fdm['simulation/script/checks-failed'], 1)

    def test_invalid_logic_rejects_the_script(self):
        name = self.write_script([
            ({'name': 'bad logic'}, 'simulation/sim-time-sec ge 1.0', {'logic': 'XOR'}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.0', 'tol_abs': '0.02'},
            ]),
        ])
        fdm = CreateFDM(self.sandbox)
        self.assertFalse(fdm.load_script(name))

    def test_default_tolerance_is_tight(self):
        # No tolerance on the check, no tolerances file: the default is 1e-6.
        name = self.write_script([
            ({'name': 'tight'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.3'},
            ]),
        ])
        fdm = self.run_script(name)
        self.assertEqual(fdm['simulation/script/checks-failed'], 1)

    def write_tolerances(self, path):
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            f.write('<?xml version="1.0"?>\n'
                    '<tolerances>\n'
                    '  <global-tolerances>\n'
                    '    <tolerance match="simulation/*" tol_abs="0.5"/>\n'
                    '    <default tol_abs="1e-9"/>\n'
                    '  </global-tolerances>\n'
                    '</tolerances>\n')

    def test_tolerances_file_in_the_root_is_the_default(self):
        # The FDM root directory is the sandbox, so tolerances.xml there applies
        # to checks that carry no tolerance of their own.
        self.write_tolerances(self.sandbox('tolerances.xml'))
        name = self.write_script([
            ({'name': 'from file'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.3'},
            ]),
        ])
        fdm = self.run_script(name)
        self.assertEqual(fdm['simulation/script/checks-passed'], 1)
        self.assertEqual(fdm['simulation/script/checks-failed'], 0)

    def test_tolerances_src_names_the_file(self):
        self.write_tolerances(self.sandbox('rules', 'my-tolerances.xml'))
        name = self.write_script([
            ({'name': 'from named file'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.3'},
            ]),
        ], tolerances_src=os.path.join('rules', 'my-tolerances.xml'))
        fdm = self.run_script(name)
        self.assertEqual(fdm['simulation/script/checks-passed'], 1)

    def test_explicit_tolerance_wins_over_the_file(self):
        self.write_tolerances(self.sandbox('tolerances.xml'))
        name = self.write_script([
            ({'name': 'explicit'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.3', 'tol_abs': '0.01'},
            ]),
        ])
        fdm = self.run_script(name)
        self.assertEqual(fdm['simulation/script/checks-failed'], 1)

    def test_missing_tolerances_file_rejects_the_script(self):
        name = self.write_script([
            ({'name': 'no file'}, 'simulation/sim-time-sec ge 1.0', {}, [
                {'property': 'simulation/sim-time-sec', 'value': '1.0', 'tol_abs': '0.02'},
            ]),
        ], tolerances_src='no-such-file.xml')
        fdm = CreateFDM(self.sandbox)
        self.assertFalse(fdm.load_script(name))


RunTest(TestScriptCheck)
