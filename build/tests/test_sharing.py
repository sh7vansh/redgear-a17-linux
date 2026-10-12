import contextlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

source = Path(__file__).resolve().parents[2] / 'redgear.py'
spec = importlib.util.spec_from_file_location('redgear_sharing', source)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
# Synthetic configuration; no personal device snapshots are needed.
fixture = bytearray(255)
fixture[2] = 6
fixture[6:12] = bytes((1, 3, 6, 7, 9, 10))
fixture[48:54] = bytes.fromhex('02fd43bc00ff')
fixture[64:85] = b''.join(r.BUTTON_ACTIONS[action] for action in
                        ('left', 'middle', 'right', 'volume-down', 'volume-up', 'dpi-cycle', 'dpi-cycle'))
fixture[118] = (sum(fixture[64:118]) & 255) ^ 0x5a
fixture = bytes(fixture)


class SharingTests(unittest.TestCase):
    def setUp(self):
        self.rule_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.rule_directory.cleanup)
        rule = Path(self.rule_directory.name) / '70-redgear-a17.rules'
        rule.write_text(r.ACCESS_RULE)
        self.rule_patch = patch.object(r, 'ACCESS_RULE_PATH', rule)
        self.rule_patch.start()
        self.addCleanup(self.rule_patch.stop)

    def test_removed_rule_blocks_existing_device_grant_and_writes(self):
        r.ACCESS_RULE_PATH.unlink()
        with patch.object(r, 'devices', return_value=['/dev/hidraw9']), \
             patch.object(r.os, 'open') as open_device, self.assertRaises(r.MouseAccessError):
            r.Mouse()
        open_device.assert_not_called()
        from unittest.mock import Mock
        mouse = Mock()
        for operation in (lambda: r.read_settings(mouse),
                          lambda: r.update(mouse, buttons={4: 'back'}),
                          lambda: r.Mouse.write(mouse, 48, bytes(6))):
            with self.assertRaises(r.MouseAccessError): operation()
        mouse.session.assert_not_called()
        mouse.write.assert_not_called()

    def test_rule_removed_during_read_blocks_write(self):
        class Mouse:
            writes = 0
            @contextlib.contextmanager
            def session(self): yield bytes.fromhex('04aa0cfd000000cc')
            def read(self):
                r.ACCESS_RULE_PATH.unlink()
                return fixture
            def write(self, *args): self.writes += 1
        mouse = Mouse()
        with self.assertRaises(r.MouseAccessError):
            r.update(mouse, buttons={4: 'back'})
        self.assertEqual(mouse.writes, 0)

    def test_only_matching_rule_enables_configuration(self):
        self.assertTrue(r.mouse_access_enabled())
        r.ACCESS_RULE_PATH.write_text('')
        self.assertFalse(r.mouse_access_enabled())
        r.ACCESS_RULE_PATH.write_text(r.ACCESS_RULE)
        self.assertTrue(r.mouse_access_enabled())

    def test_no_mouse_and_multiple_mice_have_clear_errors(self):
        for devices, message in (([], 'No supported mouse'),
                                 (['/dev/hidraw0', '/dev/hidraw1'], 'More than one')):
            with patch.object(r, 'devices', return_value=devices), self.assertRaisesRegex(r.ProtocolError, message):
                r.Mouse()

    def test_permission_error_identifies_device_access(self):
        with patch.object(r, 'devices', return_value=['/dev/hidraw9']), \
             patch.object(r.os, 'open', side_effect=PermissionError), \
             self.assertRaises(r.MouseAccessError):
            r.Mouse()

    def test_unknown_revision_never_reads_configuration(self):
        class Mouse:
            reads = 0
            @contextlib.contextmanager
            def session(self): yield bytes.fromhex('04aa0efd000000cc')
            def read(self): self.reads += 1; return fixture
        mouse = Mouse()
        with self.assertRaisesRegex(r.ProtocolError, 'revision is not supported'):
            r.read_settings(mouse)
        with self.assertRaises(r.ProtocolError):
            r.update(mouse, buttons={4: 'back'})
        self.assertEqual(mouse.reads, 0)

    def test_unknown_lighting_is_refused_before_gui(self):
        data = bytearray(fixture)
        data[50], data[51] = 0x48, 0xb7
        with self.assertRaisesRegex(r.ProtocolError, 'lighting configuration'):
            r.validate(data)

    def test_graphical_setup_uses_recipient_path_and_host_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            recipient = Path(directory) / 'Alex Documents/Mouse $tools 100%/Redgear A17.AppImage'
            data = Path(directory) / 'recipient-data'
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                self.assertNotIn('LD_LIBRARY_PATH', kwargs['env'])
                self.assertNotIn('PYTHONHOME', kwargs['env'])
                self.assertEqual(args[:2], ['/usr/bin/pkexec', '/bin/sh'])
                rule = Path(args[3]).read_text()
                self.assertIn('1bcf', rule)
                self.assertIn('08a0', rule)
                self.assertIn('TAG+="uaccess"', rule)
                self.assertNotIn('0666', rule)
                self.assertIn('udevadm trigger', Path(args[2]).read_text())
            env = {'APPIMAGE': str(recipient), 'XDG_DATA_HOME': str(data),
                   'LD_LIBRARY_PATH': '/bundle/lib', 'PYTHONHOME': '/bundle/usr'}
            with patch.dict(os.environ, env), patch('shutil.which', return_value='/usr/bin/pkexec'), \
                 patch('subprocess.run', side_effect=run):
                r.setup(graphical=True)
            self.assertEqual(len(calls), 1)
            self.assertFalse(data.exists(), 'Access setup must not install a launcher')

    def test_authentication_cancellation_creates_no_shortcut(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'data'
            with patch.dict(os.environ, {'XDG_DATA_HOME': str(data)}), \
                 patch('shutil.which', return_value='/usr/bin/pkexec'), \
                 patch('subprocess.run', side_effect=subprocess.CalledProcessError(126, 'pkexec')), \
                 self.assertRaises(r.SetupError):
                r.setup(graphical=True)
            self.assertFalse(data.exists())

    def test_graphical_removal_only_deletes_our_rule(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertEqual(args[:2], ['/usr/bin/pkexec', '/bin/sh'])
            helper = Path(args[2]).read_text()
            self.assertIn('/usr/bin/rm -f -- /etc/udev/rules.d/70-redgear-a17.rules\n', helper)
            self.assertNotIn('/usr/bin/install', helper)
            self.assertNotIn('*', helper)
            self.assertIn('/usr/bin/udevadm control --reload-rules', helper)
            self.assertNotIn('LD_LIBRARY_PATH', kwargs['env'])
        with patch('shutil.which', return_value='/usr/bin/pkexec'), \
             patch('subprocess.run', side_effect=run):
            r.setup(graphical=True, remove=True)
        self.assertEqual(len(calls), 1)

    def test_terminal_removal_and_cancel(self):
        with patch('subprocess.run') as run:
            r.setup(remove=True)
        self.assertEqual([c.args[0] for c in run.call_args_list], [
            ['sudo', 'rm', '-f', '--', '/etc/udev/rules.d/70-redgear-a17.rules'],
            ['sudo', 'udevadm', 'control', '--reload-rules'],
            ['sudo', 'udevadm', 'trigger', '--subsystem-match=hidraw', '--action=change']])
        with patch('shutil.which', return_value='/usr/bin/pkexec'), \
             patch('subprocess.run', side_effect=subprocess.CalledProcessError(126, 'pkexec')), \
             self.assertRaisesRegex(r.SetupError, 'remove-access'):
            r.setup(graphical=True, remove=True)

    def test_missing_authentication_tool_gives_removal_fallback(self):
        with patch('shutil.which', return_value=None), patch('subprocess.run') as run, \
             self.assertRaisesRegex(r.SetupError, 'remove-access'):
            r.setup(graphical=True, remove=True)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
