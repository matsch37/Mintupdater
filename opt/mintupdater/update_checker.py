#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

import subprocess
import threading
import time
import json
import os
import sys
from pathlib import Path
import dbus
import dbus.mainloop.glib
from datetime import datetime

inhibitor_fd = None  # Global file descriptor for shutdown inhibit


# Connect D-Bus with the GLib Mainloop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)


# Path to the configuration file in the user's home directory
CONFIG_PATH = Path.home() / '.config/mintupdater/config.json'

# Default configuration if no config is found
DEFAULT_CONFIG = {
    "interval_hours": 4,           # Interval for automatic update checks in hours
    "install_on_shutdown": False   # Flag to decide whether updates should be installed automatically at shutdown
}

def load_config():
    """
    Loads the configuration file if it exists.
    If not, it saves the default configuration and returns it.
    """
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    else:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def save_config(config):
    """
    Saves the given configuration to the JSON file.
    Creates the directory if it doesn't exist.
    """
    os.makedirs(CONFIG_PATH.parent, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f)

def check_updates():
    """
    Checks if system updates are available using mintupdate-cli.
    Executes 'mintupdate-cli check' and then 'mintupdate-cli list' to see if updates are available.
    """
    try:
        # Perform check (updates the internal list of mintupdate)
        subprocess.run(
            ['mintupdate-cli', 'check'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Retrieve the list of available updates
        result = subprocess.run(
            ['mintupdate-cli', 'list'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        lines = result.stdout.strip().split('\n')
        return len(lines) > 1  # If output data exists, there are updates
    except Exception as e:
        print("Update check failed:", e)
        return False

def check_spices():
    """
    Checks if there are Cinnamon Spice updates (Applets, Desklets, Extensions, Themes).
    Executes 'cinnamon-spice-updater --list-simple [type]' for each type.
    Returns True if updates are found, otherwise False.
    """
    spice_types = ['applet', 'desklet', 'extension', 'theme']

    try:
        for spice in spice_types:
            result = subprocess.run(
                ['cinnamon-spice-updater', '--list-simple', spice],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )

            lines = result.stdout.strip().split('\n')
            if lines and any(line.strip() for line in lines):
                return True  # Updates found for this spice type

        return False  # No updates for any type
    except Exception as e:
        print("Spice update check failed:", e)
        return False

def check_flatpak_updates():
    """
    Checks if there are any Flatpak updates available.
    First performs an Appstream update, then simulates the update.
    """
    try:
        subprocess.run(['flatpak', 'update', '--appstream'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = subprocess.run(
            ['flatpak', 'update', '--noninteractive'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )
        # Only count meaningful lines (not empty ones)
        lines = result.stdout.strip().split('\n')

        # If there are more than 2 meaningful lines, updates are available
        return len(lines) > 2
    except Exception:
        return False

def get_inhibit_delay():
    """
    Reads InhibitDelayMaxUSec via busctl and returns the delay in minutes.
    """
    try:
        result = subprocess.run(
            ['busctl', 'get-property', 'org.freedesktop.login1', '/org/freedesktop/login1',
             'org.freedesktop.login1.Manager', 'InhibitDelayMaxUSec'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        # Output format: "t 600000000"
        output = result.stdout.strip()
        _, microseconds_str = output.split()
        microseconds = int(microseconds_str)
        seconds = microseconds // 1_000_000
        return seconds
    except Exception as e:
        print("Error reading InhibitDelayMaxUSec with busctl:", e)
        return 0


def install_updates():
    """
    Installs updates with elevated privileges.
    Runs 'apt update', 'apt upgrade -y', and 'flatpak update -y'.
    Executes 'mintupdate-cli upgrade -y' for Mint Updates.
    """
    subprocess.run([
    'pkexec', 'bash', '-c',
    "apt update && apt upgrade -y && flatpak update -y && mintupdate-cli upgrade -y && apt autoremove -y"
    ])    
    subprocess.run([
    'cinnamon-spice-updater', '--update-all'
    ])

class UpdateChecker:
    """
    A class that periodically checks for updates and prompts the user when updates are available.
    Uses GTK dialogs for user interaction.
    """
    def __init__(self):
        self.config = load_config()
        self.running = True
        self.schedule_initial_check()

    def schedule_initial_check(self):
        # Starts the first update check with a 2-minute delay in a background thread
        threading.Thread(target=self._delayed_start, daemon=True).start()

    def _delayed_start(self):
        time.sleep(20)  # Wait for 2 minutes
        self.check_and_prompt()
        self._schedule_next_check()

    def _schedule_next_check(self):
        # Periodically performs update checks according to the configured interval
        interval = self.config.get('interval_hours', 4) * 3600
        while self.running:
            time.sleep(interval)
            self.check_and_prompt()

    def check_and_prompt(self):
        # Checks for updates and shows a dialog if available (in the GTK Main Thread)
        config = load_config()
        always_show = config.get('always_show_prompt', False)
        install_on_shutdown = config.get('install_on_shutdown', False)
        if not install_on_shutdown or always_show:
            if check_updates() or check_flatpak_updates() or check_spices():
                GLib.idle_add(self.show_prompt)

    def show_prompt(self):
        # Shows a dialog asking the user whether to install updates
        dialog = Gtk.MessageDialog(
            parent=None,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Updates Available"
        )
        dialog.format_secondary_text("What would you like to do?")
        dialog.add_button("Ask Again Later", Gtk.ResponseType.CANCEL)
        dialog.add_button("Install Now", Gtk.ResponseType.OK)
        dialog.add_button("Always install on Shutdown", Gtk.ResponseType.NO)

        def on_response(dlg, response):
            if response == Gtk.ResponseType.OK:
                # Show a 'please wait' dialog while installing updates
                wait_dialog = Gtk.MessageDialog(
                    parent=None,
                    flags=Gtk.DialogFlags.MODAL,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.NONE,
                    text="Please wait, Updates being installed..."
                )
                wait_dialog.set_title("System Update")
                wait_dialog.show_all()

                def do_updates():
                    install_updates()
                    GLib.idle_add(wait_dialog.destroy)
                threading.Thread(target=do_updates, daemon=True).start()
            elif response == Gtk.ResponseType.NO:
                if not ensure_inhibit_delay():
                   print("Delay not sufficient. The script will exit.")
                   inhibitor_fd.close()
                   return  # or sys.exit(1)
                # Set the flag for installing updates on shutdown, without deleting it
                config = load_config()
                config['install_on_shutdown'] = True
                save_config(config)
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.show_all()

def handle_prepare_for_shutdown(starting):
    """
    Triggered on shutdown signal.
    Installs updates before shutdown if configured.
    Delays the shutdown until updates are installed.
    """
    if not starting:
        return
    
    config = load_config()

    def shutdown_flow():
        print("[DEBUG] handle_prepare_for_shutdown called")
        # Show a 'please wait' dialog while searching for updates
        wait_dialog = Gtk.MessageDialog(
            parent=None,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Please wait. Searching for Updates..."
        )
        wait_dialog.set_title("System Update")
        wait_dialog.show_all()

        def do_update_checks():
            try:
                updates_available = check_updates() or check_flatpak_updates() or check_spices()
            except Exception as e:
                print("[ERROR] Exception during update checks:", e)
                updates_available = False
            def after_checks():
                wait_dialog.destroy()
                if config.get("install_on_shutdown", False):
                    print("Auto-installing updates on shutdown...")
                    if updates_available and suf_inhibit_delay():
                        print("[DEBUG] Updates found, installing...")
                        show_wait_dialog_and_install()
                    else:
                        print("No updates to install.")
                        inhibitor_fd.close()
                        Gtk.main_quit()
                    return

                # If no updates are available, proceed with normal shutdown
                if not updates_available:
                    print("[DEBUG] No updates available, proceeding with shutdown.")
                    inhibitor_fd.close()
                    Gtk.main_quit()
                    return

                # Updates available and no auto-install flag, ask the user
                response, main_window = show_shutdown_prompt()
                if response == Gtk.ResponseType.OK and suf_inhibit_delay():
                    print("[DEBUG] User chose to update and shutdown.")
                    show_wait_dialog_and_install(main_window)
                    return
                elif response == Gtk.ResponseType.NO:
                    print("[DEBUG] User chose to shutdown without updates.")
                    inhibitor_fd.close()
                    Gtk.main_quit()
                else:
                    print("Shutdown canceled by user.")
                    inhibitor_fd.close()
                    Gtk.main_quit()
            GLib.idle_add(after_checks)
        threading.Thread(target=do_update_checks, daemon=True).start()

    def show_wait_dialog_and_install(main_window=None):
        def _show_dialog():
            wait_dialog = Gtk.MessageDialog(
                transient_for=main_window,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.NONE,
                text="Please wait, updates are being installed.\nDo not power off the computer."
            )
            wait_dialog.set_title("System Update")
            wait_dialog.show_all()

            def do_updates():
                print("[DEBUG] Installing updates in background thread...")
                install_updates()
                GLib.idle_add(wait_dialog.destroy)
                GLib.idle_add(lambda: inhibitor_fd.close())
                GLib.idle_add(Gtk.main_quit)
            threading.Thread(target=do_updates, daemon=True).start()
        GLib.idle_add(_show_dialog)

    # Always run shutdown_flow in the main thread
    GLib.idle_add(shutdown_flow)

def show_shutdown_prompt():
    """
    Displays a dialog when the system is shutting down, asking the user if they want to install updates before shutdown.
    """
    main_window = Gtk.Window()
    dialog = Gtk.MessageDialog(
       parent=main_window,
       flags=0,
       message_type=Gtk.MessageType.QUESTION,
       buttons=Gtk.ButtonsType.NONE,
       text="Updates Available at Shutdown"
    )
    dialog.format_secondary_text("Do you want to install updates before shutdown?")
    dialog.add_button("Update and Shutdown", Gtk.ResponseType.OK)
    dialog.add_button("Shutdown without Updates", Gtk.ResponseType.NO)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    response = dialog.run()
    dialog.destroy()
    return response, main_window

def inhibit_shutdown():
    """
    Sets a systemd inhibitor to delay the shutdown process while the script installs updates.
    Returns a file descriptor reference which needs to be kept open to keep the inhibition active.
    """
    bus = dbus.SystemBus()
    proxy = bus.get_object("org.freedesktop.login1", "/org/freedesktop/login1")
    iface = dbus.Interface(proxy, "org.freedesktop.login1.Manager")
    fd_raw = iface.Inhibit(
        "shutdown",
        "Mintupdater",
        "Updates pending",
        "delay"
    )
    fd_int = fd_raw.take()  # Convert dbus.UnixFd to an int file descriptor
    fd = os.fdopen(fd_int, 'w')
    return fd  # Must be kept open to prevent shutdown from proceeding

def ensure_inhibit_delay(min_required_seconds=36000):
    """
    Ensures that the 'InhibitDelayMaxSec' property is at least the specified value.
    If the current delay is too short, shows a dialog to ask the user to increase the delay.
    Returns True if the requirement is met, False otherwise.
    """
    try:
        # Read the current delay via busctl
        result = subprocess.run(
            ['busctl', 'get-property', 'org.freedesktop.login1', '/org/freedesktop/login1',
             'org.freedesktop.login1.Manager', 'InhibitDelayMaxUSec'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        _, microseconds_str = result.stdout.strip().split()
        delay_seconds = int(int(microseconds_str) / 1_000_000)

        if delay_seconds >= min_required_seconds:
            return True

        # If the delay is too short, inform the user and prompt to increase it
        dialog = Gtk.MessageDialog(
            parent=None,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Your system currently allows only a shutdown delay of {delay_seconds/60} minutes.\n"
                 "Updates cannot be installed at shutdown."
        )
        dialog.add_button("OK", Gtk.ResponseType.CANCEL)
        dialog.add_button("Increase Delay", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return False

        # Proceed to adjust the configuration if the user agrees
        config_path = "/etc/systemd/logind.conf"
        target_line = "InhibitDelayMaxSec="
        updated = False
        inserted = False
        in_login_section = False
        new_lines = []

        with open(config_path, "r") as f:
            lines = f.readlines()

        for idx, line in enumerate(lines):
            stripped = line.strip()

            if stripped.startswith("[Login]"):
                in_login_section = True
                new_lines.append(line)
                continue

            if in_login_section and stripped.startswith(target_line) and not stripped.startswith("#"):
                new_lines.append(f"{target_line}{min_required_seconds}\n")
                updated = True
                continue

            if in_login_section and not inserted:
                if (stripped.startswith("[") and stripped != "[Login]") or idx == len(lines) - 1:
                    new_lines.append(f"{target_line}{min_required_seconds}\n")
                    inserted = True

            new_lines.append(line)

        # If the [Login] section is missing entirely, add it
        if not updated and not inserted:
            new_lines.append("\n[Login]\n")
            new_lines.append(f"{target_line}{min_required_seconds}\n")

        # Write the modified lines to a temporary file
        temp_file = "/tmp/logind.conf.modified"
        with open(temp_file, "w") as f:
            f.writelines(new_lines)

        display = os.environ.get("DISPLAY", "")
        xauth = os.environ.get("XAUTHORITY", os.path.expanduser("~/.Xauthority"))
        command = (
            f'cp "{temp_file}" "{config_path}" && systemctl restart systemd-logind'
        )

        subprocess.run([
            'pkexec', 'env',
            f'DISPLAY={display}',
            f'XAUTHORITY={xauth}',
            'sh', '-c', command
        ], check=True)

        # Inform the user that the delay was successfully increased
        info = Gtk.MessageDialog(
            parent=None,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=f"Shutdown delay successfully increased to {min_required_seconds} seconds."
        )
        info.run()
        info.destroy()
        return True

    except Exception as e:
        err = Gtk.MessageDialog(
            parent=None,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error while increasing the delay."
        )
        err.format_secondary_text(str(e))
        err.run()
        err.destroy()
        return False

def suf_inhibit_delay(min_required_seconds=36000):
    """
    Ensures that the 'InhibitDelayMaxSec' property is at least the specified value.
    If the current delay is too short, shows a dialog to ask the user to increase the delay.
    Returns True if the requirement is met, False otherwise.
    """
    try:
        # Read the current delay via busctl
        result = subprocess.run(
            ['busctl', 'get-property', 'org.freedesktop.login1', '/org/freedesktop/login1',
             'org.freedesktop.login1.Manager', 'InhibitDelayMaxUSec'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        _, microseconds_str = result.stdout.strip().split()
        delay_seconds = int(int(microseconds_str) / 1_000_000)

        # Check if the delay is sufficient
        if delay_seconds >= min_required_seconds:
            return True

        # If the delay is too short, notify the user
        dialog = Gtk.MessageDialog(
            parent=None,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Your system currently allows only a shutdown delay of {delay_seconds/60} minutes.\n"
                 "Updates cannot be installed at shutdown.\n Please adjust in the Control Panel."
        )
        dialog.add_button("OK", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        return False

    except Exception as e:
        err = Gtk.MessageDialog(
            parent=None,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error while increasing the delay."
        )
        err.format_secondary_text(str(e))
        err.run()
        err.destroy()
        return False

def main():
    """
    Main function:
    - Sets the shutdown inhibit to delay shutdown for updates
    - Starts the GTK event loop in the background
    - Starts the UpdateChecker to periodically check for updates
    - Registers a D-Bus signal receiver to handle shutdown events
    - Waits indefinitely (or until KeyboardInterrupt)
    """
    global inhibitor_fd
    try:
        inhibitor_fd = inhibit_shutdown()
        print("Shutdown inhibited.")
    except Exception as e:
        print("Error setting shutdown inhibit:", e)
        sys.exit(1)

    # Initialize the update checker
    app = UpdateChecker()

    # Activate D-Bus signal receiver to handle shutdown signals
    bus = dbus.SystemBus()
    bus.add_signal_receiver(handle_prepare_for_shutdown, signal_name="PrepareForShutdown",
                            dbus_interface="org.freedesktop.login1.Manager", path="/org/freedesktop/login1")

    # Start the GTK main loop in the main thread (only once!)
    Gtk.main()

if __name__ == "__main__":
    main()
