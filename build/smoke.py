from pathlib import Path
import os
import tempfile
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gdk, Graphene

rule_folder = tempfile.TemporaryDirectory(prefix='redgear-permission-test-')
rule_path = Path(rule_folder.name) / '70-redgear-a17.rules'
source = Path(os.environ['APPDIR']) / 'usr/share/redgear-a17/redgear.py'
scope = {'__file__': str(source), '__name__': 'redgear_smoke'}
exec(compile(source.read_text().replace('/etc/udev/rules.d/70-redgear-a17.rules', str(rule_path)).replace("'local.redgear.A17'", "'local.redgear.A17.BuildTest'"),
             str(source), 'exec'), scope)
present = Gtk.ApplicationWindow.present
success = []
mode = os.environ.get('REDGEAR_SMOKE_MODE', 'normal')
access_enabled = []
access_removed = []
rule_path.write_text(scope['ACCESS_RULE'])
revoked_stage = [0]
write_attempts = []
if mode in ('revoked', 'external'):
    def setup(graphical=False, remove=False):
        if remove: rule_path.unlink()
        else: rule_path.write_text(scope['ACCESS_RULE'])
    scope['setup'] = setup
    def update(*args, **kwargs):
        write_attempts.append(True)
        raise AssertionError('Write attempted after permissions were removed')
    scope['update'] = update
if mode == 'removal':
    scope['setup'] = lambda graphical=False, remove=False: access_removed.append((graphical, remove))
if mode == 'permission':
    real_mouse = scope['Mouse']
    def mouse(*args, **kwargs):
        if not access_enabled:
            raise scope['MouseAccessError']('Mouse access is required.')
        return real_mouse(*args, **kwargs)
    scope['Mouse'] = mouse
    scope['setup'] = lambda graphical=False, remove=False: access_enabled.append(graphical)
elif mode == 'unsupported':
    import contextlib
    class UnsupportedMouse:
        @contextlib.contextmanager
        def session(self): yield bytes.fromhex('04aa0efd000000cc')
        def read(self): raise AssertionError('Unknown hardware must not be read')
        def close(self): pass
    scope['Mouse'] = lambda *args, **kwargs: UnsupportedMouse()

def inspect(window):
    defer_quit = False
    def walk(widget):
        yield widget
        child = widget.get_first_child()
        while child:
            yield from walk(child)
            child = child.get_next_sibling()
    try:
        widgets = list(walk(window.get_child()))
        labels = [w.get_text() for w in widgets if isinstance(w, Gtk.Label)]
        dropdowns = [w for w in widgets if isinstance(w, Gtk.DropDown)]
        buttons = {w.get_label(): w for w in widgets if isinstance(w, Gtk.Button)}
        if mode == 'external':
            if revoked_stage[0] == 0:
                assert buttons['Apply settings'].is_sensitive()
                rule_path.unlink()
                revoked_stage[0] = 1
            elif revoked_stage[0] == 1:
                assert not buttons['Apply settings'].is_sensitive(), 'External removal left Apply enabled'
                revoked_stage[0] = 2
                buttons['Apply settings'].emit('clicked')
            else:
                assert not write_attempts
                success.append(True)
                print('External rule removal disables Apply; forced click cannot write.', flush=True)
                return False
            defer_quit = True
            GLib.timeout_add(1500, inspect, window)
            return False
        if mode == 'revoked':
            stage = revoked_stage[0]
            if stage == 0:
                assert buttons['Apply settings'].is_sensitive()
                revoked_stage[0] = 1
                buttons['Remove permissions'].emit('clicked')
            elif stage == 1:
                assert not buttons['Apply settings'].is_sensitive()
                revoked_stage[0] = 2
                buttons['Refresh'].emit('clicked')
            elif stage == 2:
                assert not buttons['Apply settings'].is_sensitive(), 'Refresh re-enabled Apply after permission removal'
                assert all(not control.is_sensitive() for control in dropdowns)
                revoked_stage[0] = 3
                buttons['Apply settings'].emit('clicked')  # Even bypassing disabled UI must not write.
            elif stage == 3:
                assert not write_attempts, 'Apply reached the write path without permissions'
                revoked_stage[0] = 4
                buttons['Add permissions'].emit('clicked')
            else:
                assert buttons['Apply settings'].is_sensitive(), labels
                assert not write_attempts
                success.append(True)
                print('Remove → Refresh → forced Apply blocked; Add permissions restores controls.', flush=True)
                return False
            defer_quit = True
            GLib.timeout_add(1500, inspect, window)
            return False
        if mode == 'removal' and access_removed:
            assert access_removed == [(True, True)], access_removed
            assert any('Permissions removed.' in label and 'reconnect' in label for label in labels)
            assert not buttons['Apply settings'].is_sensitive()
            assert all(not control.is_sensitive() for control in dropdowns)
            success.append(True)
            print('Permission removal disables settings; authentication simulated.', flush=True)
            return False
        if mode == 'unsupported':
            assert any('revision is not supported' in label for label in labels), labels
            assert not buttons['Apply settings'].is_sensitive()
            assert all(not control.is_sensitive() for control in dropdowns)
            success.append(True)
            print('Unsupported mouse: clear message, no configuration read, controls disabled.', flush=True)
            return False
        if mode == 'permission' and not access_enabled:
            assert any('Permissions required.' in label for label in labels), labels
            assert buttons['Add permissions'].get_mapped()
            assert not buttons['Apply settings'].is_sensitive()
            assert all(not control.is_sensitive() for control in dropdowns)
            defer_quit = True
            buttons['Add permissions'].emit('clicked')
            GLib.timeout_add(2000, inspect, window)
            return False
        assert 'Mouse connected.' in labels, labels
        if mode == 'removal':
            assert buttons['Remove permissions'].is_sensitive()
            defer_quit = True
            buttons['Remove permissions'].emit('clicked')
            GLib.timeout_add(1500, inspect, window)
            return False
        assert len(dropdowns) == 4
        for dropdown in dropdowns[2:]:
            model = dropdown.get_model()
            names = [model.get_string(i) for i in range(model.get_n_items())]
            assert 'Volume Up' in names and 'Volume Down' in names
        # GTK 4.6 GI cannot marshal GskRenderNode reliably; use its C API for capture.
        import ctypes
        gtk = ctypes.CDLL(str(Path(os.environ['APPDIR']) / 'usr/lib/libgtk-4.so.1'))
        def function(name, restype, *argtypes):
            f = getattr(gtk, name); f.restype = restype; f.argtypes = list(argtypes); return f
        ptr = ctypes.c_void_p
        child = window.get_child()
        paintable = function('gtk_widget_paintable_new', ptr, ptr)(hash(child))
        snapshot = function('gtk_snapshot_new', ptr)()
        function('gdk_paintable_snapshot', None, ptr, ptr, ctypes.c_double, ctypes.c_double)(
            paintable, snapshot, child.get_width(), child.get_height())
        node = function('gtk_snapshot_free_to_node', ptr, ptr)(snapshot)
        renderer = function('gtk_native_get_renderer', ptr, ptr)(hash(window))
        texture = function('gsk_renderer_render_texture', ptr, ptr, ptr, ptr)(renderer, node, None)
        assert function('gdk_texture_save_to_png', ctypes.c_int, ptr, ctypes.c_char_p)(texture,
            os.fsencode(Path(__file__).resolve().parent / 'appimage-gui.png'))
        success.append(True)
        print('Bundled GTK GUI connected to the mouse; side controls and volume options verified.', flush=True)
        print('GTK version:', Gtk.get_major_version(), Gtk.get_minor_version(), flush=True)
        if mode == 'permission':
            assert access_enabled == [True]
            assert buttons['Apply settings'].is_sensitive()
            print('First-launch permission flow recovered and enabled controls.', flush=True)
    finally:
        if not defer_quit:
            window.get_application().quit()
    return False

def show(window):
    present(window)
    GLib.timeout_add(3000, inspect, window)

Gtk.ApplicationWindow.present = show
scope['run_gui']()
assert success == [True], success
