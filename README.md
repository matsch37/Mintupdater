# Linux Mint Update Helper Program

_________ this is a early test version. Use at your own risk. Either install yourself or download and install the miupd_eng.deb

This program is a lightweight update helper for **Linux Mint**. I created it because I wasn’t satisfied with the two options available for updating Linux Mint:

- **Manual updates**, which can be burdensome, especially for less experienced users.
- **Automatic updates**, which can be disruptive, such as restarting your browser (e.g., Firefox) mid-workflow.

This program aims to provide a middle ground.

## What it does:

- **Checks for updates** at user-defined intervals (1, 4, 8, or 24 hours).
- **Notifies the user** when updates are available, with options to:
    - **Ask later**
    - **Update now**
    - **Always update at shutdown**

- When the user clicks the **shutdown button**, the program rechecks for updates and presents a prompt with the options:
    - **Shutdown and update**
    - **Shutdown without updating**

## Features:

- A **control panel** to configure the program's behavior:
    - Set the interval for update checks
    - Set a delay time for shutdown (e.g., 10 hours) to allow updates to run safely
    - Enable or disable **autostart** of the program
    - **Start/stop** the tool
    - Enable or disable **auto-update on shutdown**
    - Show **update reminders** even when auto-update on shutdown is enabled

This tool offers a flexible and user-friendly approach to updating your system without the inconvenience of full manual updates or disruptive automatic processes.
<img width="472" height="394" alt="conrol panel" src="https://github.com/user-attachments/assets/5764b1c7-b8ce-4733-9dea-40a3cc0c04f7" />
