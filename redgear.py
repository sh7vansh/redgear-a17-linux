#!/usr/bin/env python3
"""Native Linux configuration of the Redgear A-17 (Sunplus SPCP19x)."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
LED_MODES = {"dpi": 1, "multicolour": 2, "rainbow": 3, "flow": 4,
             "waltz": 5, "seasons": 6, "off": 7}
SIDE_BUTTONS = {4: 'Side button 4', 5: 'Side button 5'}
# Exact three-byte constants from the vendor's action encoder at 0x59a374.
BUTTON_ACTIONS = {name: bytes.fromhex(code) for name, code in (
    ('left', '010100'), ('right', '010200'), ('middle', '010400'),
    ('back', '010800'), ('forward', '011000'), ('disabled', '000000'),
    ('dpi-cycle', '050000'), ('dpi-up', '070000'), ('dpi-down', '080000'),
    ('led-switch', '090000'), ('led-mode', '100000'), ('key-mode', '0F0000'),
    ('play-pause', '0300CD'), ('media-stop', '0300B7'),
    ('previous-track', '0300B6'), ('next-track', '0300B5'),
    ('volume-up', '0300E9'), ('volume-down', '0300EA'), ('mute', '0300E2'),
    ('browser-back', '030224'), ('browser-forward', '030225'),
    ('desktop', '020807'))}
SIDE_ACTIONS = ('back', 'forward', 'volume-up', 'volume-down', 'mute',
                'play-pause', 'next-track', 'previous-track', 'media-stop',
                'browser-back', 'browser-forward', 'desktop',
                'dpi-cycle', 'dpi-up', 'dpi-down', 'led-switch', 'led-mode',
                'key-mode', 'left', 'right', 'middle', 'disabled')
ACTION_LABELS = {action: action.replace('-', ' ').title() for action in SIDE_ACTIONS}
ACTION_LABELS.update({'dpi-cycle': 'Cycle DPI', 'dpi-up': 'DPI Up', 'dpi-down': 'DPI Down',
                      'led-switch': 'Switch Lighting', 'led-mode': 'Lighting Mode',
                      'key-mode': 'Key Mode', 'play-pause': 'Play / Pause',
                      'media-stop': 'Stop Playback', 'desktop': 'Show Desktop',
                      'left': 'Left Click', 'right': 'Right Click', 'middle': 'Middle Click'})


class ProtocolError(RuntimeError):
    pass


class MouseAccessError(PermissionError):
    pass


class SetupError(ProtocolError):
    pass


SUPPORTED_IDENTITY = bytes.fromhex('aa0cfd')
ACCESS_RULE = ('ACTION=="add|change", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1bcf", '
               'ATTRS{idProduct}=="08a0", TAG+="uaccess"\n')

ACCESS_RULE_PATH = Path('/etc/udev/rules.d/70-redgear-a17.rules')


def mouse_access_enabled():
    # A device ACL can survive rule removal until reconnection. Do not use that
    # stale grant as permission to configure the mouse after the user opts out.
    try:
        return ACCESS_RULE_PATH.read_text().strip() == ACCESS_RULE.strip()
    except (OSError, UnicodeError):
        return False


def require_mouse_access():
    if not mouse_access_enabled():
        raise MouseAccessError('Permissions required. Add permissions or run setup.')


def check_identity(identity):
    if identity[1:4] != SUPPORTED_IDENTITY:
        raise ProtocolError('This mouse revision is not supported. '
                            'Only the tested Redgear A-17 protocol is enabled.')


def read_settings(mouse):
    require_mouse_access()
    with mouse.session() as identity:
        check_identity(identity)
        data = mouse.read()
    validate(data)
    return identity, data


def devices():
    result = []
    for node in sorted(Path('/sys/class/hidraw').glob('hidraw*')):
        info = dict(line.split('=', 1) for line in
                    (node / 'device/uevent').read_text().splitlines() if '=' in line)
        if info.get('HID_ID') == '0003:00001BCF:000008A0':
            result.append('/dev/' + node.name)
    return result


class Mouse:
    def __init__(self, path=None, trace=False):
        candidates = devices()
        if path is not None and path not in candidates:
            raise ProtocolError('Specified device is not a USB 1bcf:08a0 mouse')
        if path is None:
            if not candidates:
                raise ProtocolError('No supported mouse found. Connect a Redgear A-17 and press Refresh.')
            if len(candidates) > 1:
                raise ProtocolError('More than one matching mouse is connected. '
                                    'Disconnect the extra mouse, or use --device in the terminal.')
            path = candidates[0]
        require_mouse_access()
        self.path, self.trace = path, trace
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
        except PermissionError as error:
            raise MouseAccessError('Mouse access is required.') from error
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(self.fd)
            raise ProtocolError('Mouse is busy. Close the other controller and press Refresh.') from error
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def exchange(self, command, *args):
        packet = bytes([4, command, *args]).ljust(8, b'\0')
        if len(packet) != 8:
            raise ValueError('Feature reports must contain eight bytes')
        if self.trace:
            print('TX', packet.hex(' '), file=sys.stderr)
        fcntl.ioctl(self.fd, 0xC0084806, packet)  # HIDIOCSFEATURE(8)
        time.sleep(0.015)
        # Retry GET only: resending a data-transfer command advances the cursor.
        for _ in range(8):
            response = bytearray([4, 0, 0, 0, 0, 0, 0, 0])
            n = fcntl.ioctl(self.fd, 0xC0084807, response, True)
            if self.trace:
                print('RX', response.hex(' '), file=sys.stderr)
            if n != 8 or response[0] != 4:
                raise ProtocolError(f'Invalid feature response: {n}, {response.hex()}')
            if response[7] == 0xcc:
                return bytes(response)
            if response[7] not in (0,):
                raise ProtocolError(f'Unexpected response: {response.hex()}')
            time.sleep(0.015)
        raise ProtocolError('Mouse did not acknowledge command')

    @contextlib.contextmanager
    def session(self):
        started = False
        try:
            response = self.exchange(1)
            started = True
            if response[1] != 0xa6:
                raise ProtocolError('Mouse handshake does not match the A-17 protocol')
            identity = self.exchange(3)
            if identity[1] != 0xaa:
                raise ProtocolError('Mouse identity response does not match')
            yield identity
        finally:
            if started:
                # Always release configuration mode, including on transfer failure.
                try:
                    self.exchange(8)
                finally:
                    self.exchange(2)

    def read(self, address=0, size=255):
        if not (0 <= address < 2048 and 0 < size <= 255 and address + size <= 2048):
            raise ValueError('Invalid memory read')
        self.exchange(4, address & 255, address >> 8, size >> 8, size & 255)
        result = bytearray()
        for _ in range((size + 5) // 6):
            result.extend(self.exchange(5)[1:7])
        return bytes(result[:size])

    def write(self, address, data):
        require_mouse_access()
        if not (0 <= address and 0 < len(data) <= 255 and address + len(data) <= 255):
            raise ValueError('Writes are restricted to the configuration region')
        size = len(data)
        self.exchange(6, address & 255, address >> 8, size >> 8, size & 255)
        for offset in range(0, size, 6):
            chunk = data[offset:offset + 6].ljust(6, b'\xff')
            response = self.exchange(7, *chunk)
            if response[1:7] != chunk:
                raise ProtocolError('Configuration transfer echo mismatch')


def validate(data):
    if len(data) != 255:
        raise ProtocolError('Incomplete configuration')
    # The connected mouse already has a stale main checksum. Preserve that block.
    for offset in (0x30, 0x32, 0x34):
        if data[offset] ^ data[offset + 1] != 255:
            raise ProtocolError(f'Configuration complement mismatch at {offset:#x}')
    if not (1 <= data[2] <= 7 and (data[0x30] & 15) < data[2]):
        raise ProtocolError('Unrecognized DPI slot layout')
    if (data[50] & 15) not in LED_MODES.values() or (data[50] & 0xf0) % 32:
        raise ProtocolError('This mouse has an unsupported lighting configuration.')


def describe(data):
    return {'dpi_slot': (data[0x30] & 15) + 1,
            'dpi_values': [DPI_VALUES.get(code, f'unknown code {code}')
                           for code in data[6:6 + data[2]]],
            'led_mode': next((k for k, v in LED_MODES.items() if v == data[0x32] & 15),
                             f'unknown ({data[0x32] & 15})'),
            'led_speed': 8 - ((data[0x32] >> 4) // 2),
            'configuration_bytes': len(data),
            'buttons': {str(i + 1): decode_action(data[64 + i * 3:67 + i * 3])
                        for i in range(7)},
            'main_checksum_valid': data[47] == ((sum(data[:47]) & 255) ^ 0x5a)}


DPI_VALUES = dict(enumerate((500, 800, 1000, 1200, 1600, 2000,
                            2400, 3200, 4000, 4800, 6400, 8000), 1))


def decode_action(code):
    return next((name for name, value in BUTTON_ACTIONS.items() if value == bytes(code)),
                'custom:' + bytes(code).hex())


def plan_update(original, dpi_slot=None, led=None, speed=None, buttons=None):
    validate(original)
    changed = bytearray(original)
    if dpi_slot is not None:
        if not 1 <= dpi_slot <= original[2]:
            raise ValueError(f'DPI slot must be between 1 and {original[2]}')
        changed[48] = (changed[48] & 0xf0) | (dpi_slot - 1)
        changed[49] = changed[48] ^ 255
    if led is not None:
        changed[50] = (changed[50] & 0xf0) | LED_MODES[led]
    if speed is not None:
        if not 1 <= speed <= 8:
            raise ValueError('Speed must be between 1 and 8')
        changed[50] = (changed[50] & 15) | ((8 - speed) << 5)
    changed[51] = changed[50] ^ 255
    if buttons:
        if original[118] != ((sum(original[64:118]) & 255) ^ 0x5a):
            raise ProtocolError('Button table checksum mismatch; refusing remapping')
        for button, action in buttons.items():
            if not isinstance(button, int) or button not in SIDE_BUTTONS:
                raise ValueError('Only side buttons 4 and 5 can be remapped')
            if action not in BUTTON_ACTIONS:
                raise ValueError(f'Unknown button action: {action}')
            offset = 64 + (button - 1) * 3
            changed[offset:offset + 3] = BUTTON_ACTIONS[action]
        if not any(changed[i:i + 3] == BUTTON_ACTIONS['left']
                   for i in range(64, 85, 3)):
            raise ValueError('Keep at least one button assigned to left click')
        changed[118] = (sum(changed[64:118]) & 255) ^ 0x5a
    regions = []
    for address, size in ((48, 6), (64, 60)):
        if changed[address:address + size] != original[address:address + size]:
            regions.append((address, bytes(changed[address:address + size])))
    return bytes(changed), regions


def update(mouse, dpi_slot=None, led=None, speed=None, buttons=None):
    require_mouse_access()
    with mouse.session() as identity:
        check_identity(identity)
        original = mouse.read()
        validate(original)
        changed, regions = plan_update(original, dpi_slot, led, speed, buttons)
        if changed == original:
            return describe(original)
        # Whole transfer packets preserve padding and the secondary mapping bank.
        for address, data in regions:
            require_mouse_access()
            mouse.write(address, data)
    time.sleep(0.1)
    with mouse.session():
        actual = mouse.read()
    if actual != bytes(changed):
        raise ProtocolError('Readback differs from requested settings.')
    return describe(actual)


def run_gui(device=None):
    import threading
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk, GLib

    app = Adw.Application(application_id='local.redgear.A17')

    def activate(application):
        existing = application.get_active_window()
        if existing:
            existing.present()
            return
        window = Adw.ApplicationWindow(application=application, title='Redgear A-17')
        window.set_default_size(560, 760)
        layout = Adw.ToolbarView()
        window.set_content(layout)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title='Redgear A-17', subtitle='Mouse settings'))
        refresh = Gtk.Button(label='Refresh')
        refresh.set_tooltip_text('Read the current settings from the mouse')
        header.pack_start(refresh)
        apply = Gtk.Button(label='Apply settings')
        apply.add_css_class('suggested-action')
        header.pack_end(apply)
        layout.add_top_bar(header)

        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        layout.set_content(scroll)
        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=480)
        scroll.set_child(clamp)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + side)(24)
        clamp.set_child(box)

        status = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status.set_halign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name('input-mouse-symbolic')
        icon.set_pixel_size(48)
        status.append(icon)
        title = Gtk.Label(label='Redgear A-17')
        title.add_css_class('title-1')
        status.append(title)
        progress = Gtk.Spinner()
        progress.set_halign(Gtk.Align.CENTER)
        status.append(progress)
        message = Gtk.Label(label='Connecting…', wrap=True, justify=Gtk.Justification.CENTER)
        message.set_selectable(True)
        message.add_css_class('dim-label')
        status.append(message)
        box.append(status)

        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.append(grid)
        pointer = Adw.PreferencesGroup(title='Pointer', description='Choose one of the mouse’s stored DPI presets.')
        grid.append(pointer)
        dpi = Adw.ComboRow(title='DPI preset', model=Gtk.StringList.new(['Reading mouse…']))
        pointer.add(dpi)
        lighting = Adw.PreferencesGroup(title='Lighting')
        grid.append(lighting)
        led = Adw.ComboRow(title='Effect', model=Gtk.StringList.new([x.capitalize() for x in LED_MODES]))
        lighting.add(led)
        speed = Adw.SpinRow.new_with_range(1, 8, 1)
        speed.set_title('Effect speed')
        speed.set_subtitle('1 is slowest, 8 is fastest')
        lighting.add(speed)
        side_buttons = Adw.PreferencesGroup(title='Side buttons', description='Assign navigation, media or mouse actions.')
        grid.append(side_buttons)
        button_controls = {}
        for number, label in SIDE_BUTTONS.items():
            row = Adw.ComboRow(title=label, model=Gtk.StringList.new(['Reading…']))
            row.set_enable_search(True)
            side_buttons.add(row)
            button_controls[number] = row

        permissions = Adw.PreferencesGroup(title='Mouse access',
            description='Administrator authentication is required to change permissions.')
        box.append(permissions)
        access_row = Adw.ActionRow(title='Configuration access')
        access_button = Gtk.Button(label='Add permissions', valign=Gtk.Align.CENTER)
        access_row.add_suffix(access_button)
        access_row.set_activatable_widget(access_button)
        permissions.add(access_row)
        removal_row = Adw.ActionRow(title='Remove access', subtitle='Reconnect the mouse after removal')
        remove_access = Gtk.Button(label='Remove permissions', valign=Gtk.Align.CENTER)
        remove_access.add_css_class('destructive-action')
        removal_row.add_suffix(remove_access)
        removal_row.set_activatable_widget(remove_access)
        permissions.add(removal_row)
        state = {'ready': False, 'busy': False, 'initial_load': True}

        def scroll_to_start():
            scroll.get_vadjustment().set_value(0)
            return False

        def sync_controls():
            allowed = mouse_access_enabled()
            if not allowed:
                if state['ready'] and not state['busy']:
                    message.set_text('Permissions required. Click Add permissions.')
                state['ready'] = False
            idle = not state['busy']
            refresh.set_sensitive(idle)
            apply.set_sensitive(idle and state['ready'] and allowed)
            grid.set_sensitive(idle and state['ready'] and allowed)
            access_button.set_sensitive(idle)
            remove_access.set_sensitive(idle and ACCESS_RULE_PATH.exists())
            return True

        def busy(value):
            state['busy'] = value
            progress.set_spinning(value)
            progress.set_visible(value)
            sync_controls()

        def finish(result, error, applying, removing=False):
            if not error and not removing and not mouse_access_enabled():
                error = MouseAccessError('Permissions required.')
            if error:
                if isinstance(error, MouseAccessError):
                    message.set_text('Permissions required. Click Add permissions.')
                else:
                    message.set_text(str(error))
                state['ready'] = False
            elif removing:
                state['ready'] = False
                message.set_text('Permissions removed. Unplug and reconnect the mouse.')
            else:
                settings = result
                dpi.set_model(Gtk.StringList.new([f'{v} DPI · preset {i + 1}'
                               for i, v in enumerate(settings['dpi_values'])]))
                dpi.set_selected(settings['dpi_slot'] - 1)
                led.set_selected(list(LED_MODES).index(settings['led_mode']))
                speed.set_value(settings['led_speed'])
                state['buttons'] = settings['buttons']
                state['choices'] = {}
                for number, dropdown in button_controls.items():
                    current = settings['buttons'][str(number)]
                    choices = list(SIDE_ACTIONS)
                    if current not in choices:
                        choices.append(current)
                    state['choices'][number] = choices
                    dropdown.set_model(Gtk.StringList.new([
                        ('Keep custom mapping (' + x[7:] + ')') if x.startswith('custom:')
                        else ACTION_LABELS[x] for x in choices]))
                    dropdown.set_selected(choices.index(current))
                state['ready'] = True
                message.set_text('Settings saved and verified.' if applying else 'Mouse connected.')
            busy(False)
            if state.pop('initial_load', False):
                GLib.timeout_add(300, scroll_to_start)
            return False

        def job(applying=False, enable_access=False, removing=False):
            if state['busy']:
                return
            if applying and (not state['ready'] or not mouse_access_enabled()):
                state['ready'] = False
                message.set_text('Permissions required. Click Add permissions.' if not mouse_access_enabled()
                                 else 'Press Refresh before applying settings.')
                sync_controls()
                return
            mappings = {}
            if applying:
                for number, dropdown in button_controls.items():
                    action = state['choices'][number][dropdown.get_selected()]
                    if action != state['buttons'][str(number)]:
                        mappings[number] = action
            requested = ((dpi.get_selected() + 1, list(LED_MODES)[led.get_selected()],
                          int(speed.get_value()), mappings) if applying else None)
            busy(True)
            message.set_text('Removing permissions…' if removing else
                             'Adding permissions…' if enable_access else
                             'Saving settings…' if applying else 'Reading settings…')

            def worker():
                result = error = None
                mouse = None
                try:
                    if removing:
                        setup(graphical=True, remove=True)
                    else:
                        if enable_access:
                            setup(graphical=True)
                        mouse = Mouse(device)
                        if applying:
                            result = update(mouse, *requested)
                        else:
                            _, data = read_settings(mouse)
                            result = describe(data)
                except Exception as exc:
                    error = exc
                finally:
                    if mouse:
                        try:
                            mouse.close()
                        except Exception as exc:
                            if error is None:
                                error = exc
                GLib.idle_add(finish, result, error, applying, removing)
            threading.Thread(target=worker, daemon=True).start()

        # A daemon must never exit midway through a write or leave config mode open.
        window.connect('close-request', lambda *_: state['busy'])
        refresh.connect('clicked', lambda *_: job())
        apply.connect('clicked', lambda *_: job(True))
        access_button.connect('clicked', lambda *_: job(enable_access=True))
        remove_access.connect('clicked', lambda *_: job(removing=True))
        permission_watch = GLib.timeout_add(750, sync_controls)
        window.connect('destroy', lambda *_: GLib.source_remove(permission_watch))
        window.set_focus(refresh)
        window.present()
        job()

    app.connect('activate', activate)
    app.run([])


def setup_instruction(action='setup'):
    import shlex
    appimage = os.environ.get('APPIMAGE')
    command = (shlex.quote(str(Path(appimage).resolve())) if appimage else
               f'{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))}')
    return 'Terminal alternative: ' + command + ' ' + action


def setup(graphical=False, remove=False):
    """Explicitly enable or remove configuration access; never run the app as root."""
    import subprocess
    import tempfile
    import shutil
    host_environment = os.environ.copy()
    for key in ('LD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH', 'GI_TYPELIB_PATH',
                'GSETTINGS_SCHEMA_DIR', 'GIO_MODULE_DIR'):
        host_environment.pop(key, None)
    try:
        with tempfile.TemporaryDirectory(prefix='redgear-access-') as folder:
            source = Path(folder) / '70-redgear-a17.rules'
            source.write_text(ACCESS_RULE)
            if graphical:
                pkexec = shutil.which('pkexec', path=host_environment.get('PATH'))
                if not pkexec:
                    command = 'remove-access' if remove else 'setup'
                    raise SetupError(f'Administrator authentication is unavailable. Run the app with {command} '
                                     'in a terminal instead.')
                helper = Path(folder) / 'mouse-access.sh'
                operation = ('/usr/bin/rm -f -- /etc/udev/rules.d/70-redgear-a17.rules\n' if remove else
                             '/usr/bin/install -m 0644 "$1" /etc/udev/rules.d/70-redgear-a17.rules\n')
                helper.write_text('#!/bin/sh\nset -eu\n'
                                  + operation +
                                  '/usr/bin/udevadm control --reload-rules\n'
                                  '/usr/bin/udevadm trigger --subsystem-match=hidraw --action=change\n')
                subprocess.run([pkexec, '/bin/sh', str(helper), str(source)],
                               check=True, env=host_environment)
            else:
                operation = (['sudo', 'rm', '-f', '--', '/etc/udev/rules.d/70-redgear-a17.rules'] if remove else
                             ['sudo', 'install', '-m', '0644', str(source),
                              '/etc/udev/rules.d/70-redgear-a17.rules'])
                subprocess.run(operation, check=True, env=host_environment)
                subprocess.run(['sudo', 'udevadm', 'control', '--reload-rules'], check=True, env=host_environment)
                subprocess.run(['sudo', 'udevadm', 'trigger', '--subsystem-match=hidraw',
                                '--action=change'], check=True, env=host_environment)
    except subprocess.CalledProcessError as error:
        command = 'remove-access' if remove else 'setup'
        raise SetupError(f'Mouse access change was cancelled or could not finish. '
                         f'Administrator authentication is required. Terminal command: {command}.') from error
    print('Access rule removed. Unplug and reconnect the mouse to end access granted by this rule.'
          if remove else 'Mouse access enabled. Reconnect the mouse if access is still denied.')


def main():
    p = argparse.ArgumentParser(description=__doc__, epilog=
        'Supported mouse: tested Redgear A-17 protocol (USB 1bcf:08a0, identity aa0cfd). '
        'AppImage build: x86_64 Linux with a bundled C runtime. '
        'Use setup once on a new machine to enable mouse access.')
    p.add_argument('--device')
    p.add_argument('--trace', action='store_true')
    sub = p.add_subparsers(dest='command')
    sub.add_parser('list')
    sub.add_parser('status')
    sub.add_parser('gui')
    sub.add_parser('setup', help='Install the mouse access rule (administrator authentication)')
    sub.add_parser('remove-access', help='Remove the mouse access rule; then reconnect the mouse')
    setting = sub.add_parser('set')
    setting.add_argument('--dpi-slot', type=int, choices=range(1, 8))
    setting.add_argument('--led', choices=LED_MODES)
    setting.add_argument('--speed', type=int, choices=range(1, 9))
    setting.add_argument('--button', metavar='N=ACTION', action='append', default=[],
                         help='Remap side button 4 or 5; repeat to change both')
    sub.add_parser('actions')
    dump = sub.add_parser('dump'); dump.add_argument('output', type=Path)
    args = p.parse_args()
    if args.command in ('setup', 'remove-access'):
        setup(remove=args.command == 'remove-access')
        return
    if args.command in (None, 'gui'):
        run_gui(args.device)
        return
    if args.command == 'list':
        print('\n'.join(devices()) or 'No compatible mouse connected')
        return
    if args.command == 'actions':
        print('\n'.join(BUTTON_ACTIONS))
        return
    mouse = Mouse(args.device, args.trace)
    try:
        if args.command == 'set':
            buttons = {}
            for mapping in args.button:
                number, sep, action = mapping.partition('=')
                if not sep or not number.isdigit() or action not in BUTTON_ACTIONS:
                    p.error('Use --button N=ACTION; list supported actions with "actions"')
                buttons[int(number)] = action
            if args.dpi_slot is None and args.led is None and args.speed is None and not buttons:
                p.error('set requires --dpi-slot, --led, --speed or --button')
            state = update(mouse, args.dpi_slot, args.led, args.speed, buttons)
            print(json.dumps({'settings': state}, indent=2))
            return
        identity, data = read_settings(mouse)
        if args.command == 'dump':
            args.output.write_bytes(data)
            print(f'Saved {len(data)} bytes to {args.output}')
        else:
            print(json.dumps({'device': mouse.path, 'identity': identity.hex(),
                              **describe(data)}, indent=2))
            validate(data)
    finally:
        mouse.close()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ProtocolError, ValueError) as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)
