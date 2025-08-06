#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import json
import os
from pathlib import Path
from update_checker import ensure_inhibit_delay
import subprocess

CONFIG_PATH = Path.home() / '.config/mintupdater/config.json'
AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "mintupdater-shutdown.desktop"
SYSTEM_AUTOSTART = "/etc/xdg/autostart/mintupdater-shutdown.desktop"

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

def save_config(cfg):
    os.makedirs(CONFIG_PATH.parent, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f)

class ConfigWindow(Gtk.Window):
    def on_toggle_install_on_shutdown(self, widget):
        self.update_toggle_label()
        if widget.get_active():
            ensure_inhibit_delay()
        self.save_settings()

    def on_toggle_show_prompt(self, widget):
        self.save_settings()

    def update_autostart_label(self):
        if self.toggle_autostart.get_active():
            self.toggle_autostart.set_label("Autostart (Aktiviert)")
        else:
            self.toggle_autostart.set_label("Autostart (Deaktiviert)")

    def on_toggle_autostart(self, widget):
        if widget.get_active():
            if AUTOSTART_FILE.exists():
                AUTOSTART_FILE.unlink()
        else:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            try:
                with open(SYSTEM_AUTOSTART, 'r') as src:
                    lines = src.readlines()
            except FileNotFoundError:
                lines = [
                    "[Desktop Entry]\n",
                    "Type=Application\n",
                    "Name=UpdateChecker\n",
                    "Exec=/opt/mintupdater/update_checker.py\n",
                    "X-GNOME-Autostart-enabled=true\n",
                    "NoDisplay=false\n",
                ]
            with open(AUTOSTART_FILE, 'w') as dst:
                for line in lines:
                    if line.strip().lower().startswith("hidden="):
                        continue
                    dst.write(line)
                dst.write("Hidden=true\n")
        self.update_autostart_label()
        self.update_install_on_shutdown_sensitivity()

    def is_autostart_enabled(self):
        if not AUTOSTART_FILE.exists():
            return True
        with open(AUTOSTART_FILE, 'r') as f:
            for line in f:
                if line.strip().lower() == "hidden=true":
                    return False
        return True

    def is_daemon_running(self):
        result = subprocess.run(
            ["pgrep", "-f", "update_checker.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0

    def update_daemon_label(self):
        if self.toggle_daemon.get_active():
            self.toggle_daemon.set_label("Hintergrunddienst (Gestartet)")
        else:
            self.toggle_daemon.set_label("Hintergrunddienst (Gestoppt)")

    def on_toggle_daemon(self, widget):
        if widget.get_active():
            if not self.is_daemon_running():
                subprocess.Popen(['./update_checker.py'])
        else:
            subprocess.run(['pkill', '-f', 'update_checker.py'])
        self.update_daemon_label()
        self.update_install_on_shutdown_sensitivity()

    def on_set_inhibit_delay_clicked(self, button):
        if ensure_inhibit_delay():
            button.set_label("Verzögerung erfolgreich gesetzt")

    def update_install_on_shutdown_sensitivity(self):
        autostart_enabled = self.toggle_autostart.get_active()
        daemon_enabled = self.toggle_daemon.get_active()
        enabled = autostart_enabled or daemon_enabled
        self.toggle_install_on_shutdown.set_sensitive(enabled)
        self.check_show_prompt.set_sensitive(enabled)

    def __init__(self):
        Gtk.Window.__init__(self, title="Einstellungen für Update-Prüfer")
        self.set_border_width(10)
        self.set_default_size(400, 100)

        config = load_config()
        interval = config.get("interval_hours", 4)
        install_on_shutdown = config.get("install_on_shutdown", False)
        always_show_prompt = config.get("always_show_prompt", False)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        self.dropdown = Gtk.ComboBoxText()
        for label, hours in [("1 Stunde", 1), ("4 Stunden", 4), ("8 Stunden", 8), ("24 Stunden", 24)]:
            self.dropdown.append_text(label)
        self.dropdown.set_active(["1", "4", "8", "24"].index(str(interval)))
        self.dropdown.connect("changed", self.on_interval_changed)
        vbox.pack_start(Gtk.Label(label="Nach Updates suchen alle:"), False, False, 0)
        vbox.pack_start(self.dropdown, False, False, 0)

        delay_button = Gtk.Button(label="Verzögerung beim Herunterfahren setzen")
        delay_button.connect("clicked", self.on_set_inhibit_delay_clicked)
        vbox.pack_start(delay_button, False, False, 0)

        self.toggle_autostart = Gtk.ToggleButton(label="Autostart (Aktiviert)")
        self.toggle_autostart.set_active(self.is_autostart_enabled())
        self.update_autostart_label()
        self.toggle_autostart.connect("toggled", self.on_toggle_autostart)
        vbox.pack_start(self.toggle_autostart, False, False, 0)

        self.toggle_daemon = Gtk.ToggleButton(label="Hintergrunddienst")
        self.toggle_daemon.set_active(self.is_daemon_running())
        self.update_daemon_label()
        self.toggle_daemon.connect("toggled", self.on_toggle_daemon)
        vbox.pack_start(self.toggle_daemon, False, False, 0)

        shutdown_frame = Gtk.Frame(label="Updates beim Herunterfahren installieren")
        shutdown_frame.set_margin_top(10)

        shutdown_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        shutdown_box.set_border_width(10)

        self.toggle_install_on_shutdown = Gtk.ToggleButton(label="Beim Herunterfahren installieren (Aktiviert)")
        self.toggle_install_on_shutdown.set_active(install_on_shutdown)
        self.update_toggle_label()
        self.toggle_install_on_shutdown.connect("toggled", self.on_toggle_install_on_shutdown)
        shutdown_box.pack_start(self.toggle_install_on_shutdown, False, False, 0)

        self.check_show_prompt = Gtk.CheckButton(label="Trotzdem nach Updates fragen")
        self.check_show_prompt.set_active(always_show_prompt)
        self.check_show_prompt.connect("toggled", self.on_toggle_show_prompt)
        shutdown_box.pack_start(self.check_show_prompt, False, False, 0)

        shutdown_help = Gtk.Label(
            label="Diese Optionen funktionieren nur, wenn Autostart oder der Hintergrunddienst aktiviert ist."
        )
        shutdown_help.set_margin_top(5)
        shutdown_help.set_margin_bottom(10)
        shutdown_help.set_xalign(0)
        shutdown_box.pack_start(shutdown_help, False, False, 0)

        shutdown_frame.add(shutdown_box)
        vbox.pack_start(shutdown_frame, False, False, 0)

        self.update_install_on_shutdown_sensitivity()

    def on_interval_changed(self, widget):
        self.save_settings()

    def update_toggle_label(self):
        if self.toggle_install_on_shutdown.get_active():
            self.toggle_install_on_shutdown.set_label("Beim Herunterfahren installieren (Aktiviert)")
        else:
            self.toggle_install_on_shutdown.set_label("Beim Herunterfahren installieren (Deaktiviert)")

    def save_settings(self):
        choice = self.dropdown.get_active_text()
        hours = int(choice.split()[0])
        config = load_config()
        config['interval_hours'] = hours
        config['install_on_shutdown'] = self.toggle_install_on_shutdown.get_active()
        config['always_show_prompt'] = self.check_show_prompt.get_active()
        save_config(config)

win = ConfigWindow()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
