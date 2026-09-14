import os
import shutil
import requests
from datetime import datetime, timezone, timedelta
import tkinter as tk
from tkinter import messagebox, filedialog
from tkcalendar import DateEntry
from datetime import time
import tkinter.ttk as ttk

# Custom exceptions for API errors
class DojoNetworkError(Exception):
    pass

class DojoNotFoundError(Exception):
    pass

class DojoParseError(Exception):
    pass

# Global variables
all_challenges = {}
checked_challenges = set()
dojo = ""
current_timezone = None  # Track the timezone from "Now" button

# Path to the student-username list used in batch mode, or None if
# no file has been selected yet.
username_file_path = None

# Subfolder (next to this script) where batch mode writes per-student
# report files.
BATCH_REPORT_DIRNAME = "batch-report"

# Downloads the list of all challenges in a dojo
# Returns a dictionary listing the challenges within their respective modules
def get_dojo_challenges(dojo):
    try:
        response = requests.get(f"https://pwn.college/pwncollege_api/v1/dojos/{dojo}/modules")
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()
        if not data.get("success"):
            raise DojoNotFoundError(f"API request failed - dojo '{dojo}' may not exist or be accessible")
        modules = data.get("modules", [])
        challenges_dict = {}
        for module in modules:
            module_id = module["id"]
            challenges = [ch["id"] for ch in module["challenges"]]
            challenges_dict[module_id] = challenges
        return challenges_dict
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise DojoNotFoundError(f"Dojo '{dojo}' not found")
        else:
            raise DojoNetworkError(f"HTTP error {e.response.status_code}: {e}")
    except requests.exceptions.RequestException as e:
        raise DojoNetworkError(f"Network error: {e}")
    except ValueError as e:  # JSON decode error
        raise DojoParseError(f"Invalid response format from server")

# Downloads the list of challenges a student has solved within a dojo, with timestamps
# Returns a dict organizing solved challenges by module
def get_student_solves(username, dojo):
    try:
        response = requests.get(f"https://pwn.college/pwncollege_api/v1/dojos/{dojo}/solves?username={username}")
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()
        if not data.get("success"):
            raise DojoNotFoundError(f"API request failed - username '{username}' may not exist or be accessible")
        solves = data.get("solves", [])
        solves_dict = {}
        for solve in solves:
            module = solve["module_id"]
            challenge = solve["challenge_id"]
            timestamp_str = solve["timestamp"]
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            if module not in solves_dict:
                solves_dict[module] = {}
            solves_dict[module][challenge] = timestamp
        return solves_dict
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise DojoNotFoundError(f"User '{username}' not found or dojo '{dojo}' not accessible")
        else:
            raise DojoNetworkError(f"HTTP error {e.response.status_code}: {e}")
    except requests.exceptions.RequestException as e:
        raise DojoNetworkError(f"Network error: {e}")
    except ValueError as e:  # JSON decode error
        raise DojoParseError(f"Invalid response format from server")

# Helper function to get timezone display string
def get_timezone_display(deadline, abbreviated=False):
    #
    # Check if we have original timezone info and it matches the deadline offset.
    #
    # If the user entered an offset manually, we can't unambiguously determine the timezone,
    # but the typical expected use case is that the user won't change the default.
    #
    # We'd ideally like to provide both full and abbreviated timezone names (e.g.,
    # "Eastern Daylight Time" vs "EDT"), so the latter can be used in more repetitive displays
    # like the per-module breakdown in the grade report. But Python's datetime module doesn't
    # provide a reliable way to get both forms (some systems return one or the other).
    # So, we expect to have to fall back to just the UTC offset display in at least one of the
    # two cases - but this code at least gives us the best we can get, and ensures we don't
    # get the long-form display when the calling code specifically asks for an abbreviation.
    #
    if current_timezone:
        try:
            current_offset = current_timezone.utcoffset(datetime.now())
            if current_offset == deadline.utcoffset():
                # Use the original timezone to get the timezone's proper name
                temp_time = datetime.now(current_timezone)
                if abbreviated:
                    # Try to get abbreviated timezone name (EDT, PST, etc.)
                    tz_abbrev = temp_time.strftime('%Z')
                    if tz_abbrev and not tz_abbrev.startswith(('UTC', '+', '-')) and len(tz_abbrev) <= 5:
                        return f"{tz_abbrev} (UTC{deadline.utcoffset().total_seconds()/3600:+.0f})"
                else:
                    # Get full timezone name
                    tz_name = temp_time.strftime('%Z')
                    if tz_name and not tz_name.startswith(('UTC', '+', '-')):
                        return f"{tz_name} (UTC{deadline.utcoffset().total_seconds()/3600:+.0f})"
        except:
            pass

    # Fall back to just displaying UTC offset
    return f"(UTC{deadline.utcoffset().total_seconds()/3600:+.0f})"

# Generates a grading report for a student based on the given deadline and list of assigned
# challenges selected on the first tab
def generate_report(username, dojo, deadline):
    assert all_challenges, "No dojo selected; can't generate report."
    assert checked_challenges, "No challenges selected; can't generate report."

    # Download the list of challenges solved by the student within this dojo
    solves_dict = get_student_solves(username, dojo)

    report = []
    report.append(f"Username: {username}")
    report.append(f"Dojo: {dojo}")

    # Convert deadline to the specified timezone for display
    deadline_local = deadline.astimezone(deadline.tzinfo)
    tz_display = get_timezone_display(deadline)  # Full name for deadline
    tz_display_short = get_timezone_display(deadline, abbreviated=True)  # Short for solve times

    report.append(f"Deadline: {deadline_local.strftime('%Y-%m-%d %H:%M:%S')} {tz_display}")
    report.append(f"Graded at: {datetime.now(timezone.utc).astimezone(deadline.tzinfo).strftime('%Y-%m-%d %H:%M:%S')} {tz_display}")
    report.append("")

    #
    # Summary of what the student has completed (independent of deadline)
    #
    total_solves = sum(len(challenges) for challenges in solves_dict.values())
    report.append(f"Total solves: {total_solves}\n")

    # Get modules with solves in original order
    module_ids = [module for module in all_challenges.keys() if module in solves_dict]
    report.append(f"Modules with solves: {', '.join(module_ids)}\n")

    # Get challenges solved in original order (by module, then by challenge order within module)
    challenge_ids = []
    for module in all_challenges:
        if module in solves_dict:
            for challenge in all_challenges[module]:
                if challenge in solves_dict[module]:
                    challenge_ids.append(challenge)
    report.append(f"Challenges solved: {', '.join(challenge_ids)}")
    report.append("")

    overall_before_deadline = 0
    total_challenges = len(checked_challenges)

    #
    # Detailed breakdown by module
    #
    for module in all_challenges:
        # Check if any challenge in this module is assigned
        # (tracking challenges as "module:challenge", since different modules could have challenges with the same name)
        if any(f"{module}:{ch}" in checked_challenges for ch in all_challenges[module]):
            report.append(f"Module: {module}")

            challenges_solved = solves_dict.get(module, {})
            module_before_deadline = 0

            for challenge in all_challenges[module]:
                if f"{module}:{challenge}" in checked_challenges:
                    if challenge in challenges_solved:
                        timestamp = challenges_solved[challenge]
                        # Convert solve timestamp to the same timezone as deadline
                        timestamp_local = timestamp.astimezone(deadline.tzinfo)
                        formatted_timestamp = timestamp_local.strftime("%Y-%m-%d %H:%M:%S")
                        report.append(f"  {challenge}: Solved at {formatted_timestamp} {tz_display_short}")
                        if timestamp < deadline:
                            module_before_deadline += 1
                    else:
                        report.append(f"  {challenge}: Not solved")

            total_in_module = len([ch for ch in all_challenges[module] if f"{module}:{ch}" in checked_challenges])
            overall_before_deadline += module_before_deadline
            percentage = (module_before_deadline / total_in_module) * 100 if total_in_module > 0 else 0
            report.append(f"{module_before_deadline}/{total_in_module} solved before deadline ({percentage:.1f}%)")
            report.append("")

    overall_percentage = (overall_before_deadline / total_challenges) * 100 if total_challenges > 0 else 0
    report.append(f"Overall: {overall_before_deadline}/{total_challenges} solved before deadline ({overall_percentage:.1f}%)")

    return "\n".join(report)

# Implements the "Load Challenges" button
# (downloads the challenge list from pwn.college and populates the tree view)
def on_load_challenges_click():
    global dojo, all_challenges, checked_challenges

    dojo = dojo_entry.get()
    if not dojo:
        messagebox.showerror("Error", "Please enter a dojo name.")
        return

    # Show downloading message
    status_label.config(text="Downloading dojo...")
    root.update()  # Force GUI update

    try:
        # Download the list of challenges in this dojo
        all_challenges = get_dojo_challenges(dojo)
        if not all_challenges:
            status_label.config(text="")  # Clear status message
            messagebox.showerror("Error", f"Dojo '{dojo}' exists but has no challenges.")
            return

        # Clear previous
        for item in tree.get_children():
            tree.delete(item)
        checked_challenges.clear()

        # Populate tree view with the challenge list we downloaded
        for module, challenges in all_challenges.items():
            module_item = tree.insert('', 'end', module, text=f'[ ] {module}', tags=('module',), open=True)
            for ch in challenges:
                tree.insert(module_item, 'end', text=f'[ ] {ch}', tags=('challenge',))

        # Show the Select All and Deselect All buttons now that we have challenges
        select_all_button.grid()
        deselect_all_button.grid()

        # Clear status message
        status_label.config(text="")

    except DojoNotFoundError as e:
        status_label.config(text="")
        messagebox.showerror("Error", str(e))
    except DojoNetworkError as e:
        status_label.config(text="")
        messagebox.showerror("Error", f"Network error: {str(e)}")
    except DojoParseError as e:
        status_label.config(text="")
        messagebox.showerror("Error", f"Server response error: {str(e)}")

# Select all challenges in the dojo
def on_select_all_click():
    if not all_challenges:
        return

    # Find modules that aren't fully checked and toggle them
    for module_id in tree.get_children():
        module_text = tree.item(module_id, 'text')
        if not module_text.startswith('[x]'):
            toggle_check(module_id)

# Deselect all challenges in the dojo
def on_deselect_all_click():
    if not all_challenges:
        return

    # Find modules that have any selection and toggle them until they're unchecked
    for module_id in tree.get_children():
        module_text = tree.item(module_id, 'text')
        if module_text.startswith('[-]'):
            # Partially selected - toggle twice (first to select all, then to deselect all)
            toggle_check(module_id)
            toggle_check(module_id)
        elif module_text.startswith('[x]'):
            # Fully selected - toggle once to deselect
            toggle_check(module_id)

# Handle tree item clicks
def on_tree_click(event):
    item = tree.identify('item', event.x, event.y)
    if item:
        toggle_check(item)
        return "break"  # Prevent default treeview behavior

# Toggle the check state of a tree item (and its children if applicable)
def toggle_check(item):
    current_text = tree.item(item, 'text')
    name = current_text[4:]  # Extract name after '[ ] ' or '[x] ' or '[-] '
    if '[ ]' in current_text:
        new_text = current_text.replace('[ ]', '[x]')
        if 'module' in tree.item(item, 'tags'):
            # Check all children
            module_name = name
            for child in tree.get_children(item):
                child_text = tree.item(child, 'text')
                tree.item(child, text=child_text.replace('[ ]', '[x]'))
                child_name = child_text[4:]
                checked_challenges.add(f"{module_name}:{child_name}")
        else:
            # Get the module name from the parent
            parent = tree.parent(item)
            module_name = tree.item(parent, 'text')[4:]
            checked_challenges.add(f"{module_name}:{name}")
            tree.item(item, text=new_text)  # Update item first
            update_parent(item)
            return  # Exit early to avoid updating twice
    elif '[x]' in current_text:
        new_text = current_text.replace('[x]', '[ ]')
        if 'module' in tree.item(item, 'tags'):
            # Uncheck all children
            module_name = name
            for child in tree.get_children(item):
                child_text = tree.item(child, 'text')
                tree.item(child, text=child_text.replace('[x]', '[ ]'))
                child_name = child_text[4:]
                checked_challenges.discard(f"{module_name}:{child_name}")
        else:
            # Get the module name from the parent
            parent = tree.parent(item)
            module_name = tree.item(parent, 'text')[4:]
            checked_challenges.discard(f"{module_name}:{name}")
            tree.item(item, text=new_text)  # Update item first
            update_parent(item)
            return  # Exit early to avoid updating twice
    elif '[-]' in current_text:
        # Treat as select all (check all children)
        new_text = current_text.replace('[-]', '[x]')
        if 'module' in tree.item(item, 'tags'):
            # Check all children
            module_name = name
            for child in tree.get_children(item):
                child_text = tree.item(child, 'text')
                tree.item(child, text=child_text.replace('[ ]', '[x]').replace('[-]', '[x]'))
                child_name = child_text[4:]
                checked_challenges.add(f"{module_name}:{child_name}")
        else:
            # Challenges should never have children, so this should not happen
            assert False, "Challenge items should not have children"
    tree.item(item, text=new_text)

# Update a parent item's checkbox state in response to a change in one of its children
def update_parent(child):
    parent = tree.parent(child)
    if parent:
        children = tree.get_children(parent)
        checked_count = sum(1 for c in children if '[x]' in tree.item(c, 'text'))
        parent_text = tree.item(parent, 'text')

        # Extract parent name - all checkbox prefixes are exactly 4 characters
        # (namely: [ ] , [x] , [-])
        parent_name = parent_text[4:]

        # Update the parent item's text based on the children's checked state
        if checked_count == 0:
            new_parent_text = f'[ ] {parent_name}'
        elif checked_count == len(children):
            new_parent_text = f'[x] {parent_name}'
        else:
            new_parent_text = f'[-] {parent_name}'

        # Apply the new text to the parent's entry in the tree
        tree.item(parent, text=new_parent_text)

# Build a filesystem-safe .txt filename from a student username
def report_filename_for(username):
    allowed = []
    for ch in username:
        if ch.isalnum() or ch in "._-":
            allowed.append(ch)
        else:
            allowed.append("_")
    safe = "".join(allowed).strip("._")
    if not safe:
        safe = "unknown"
    return f"{safe}.txt"

# Absolute path of the batch-report output directory (next to this script)
def batch_report_dir():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, BATCH_REPORT_DIRNAME)

# True if path is a directory that contains at least one entry
def dir_is_nonempty(path):
    if not os.path.isdir(path):
        return False
    try:
        with os.scandir(path) as entries:
            for _ in entries:
                return True
        return False
    except OSError:
        return False

# mtime of the newest file directly in path (not recursive).
#
# If the directory has no files, fall back to path's own mtime.
def most_recent_file_mtime(path):
    latest = None
    try:
        names = os.listdir(path)
    except OSError:
        return os.path.getmtime(path)
    for name in names:
        entry = os.path.join(path, name)
        try:
            if os.path.isfile(entry):
                mtime = os.path.getmtime(entry)
                if latest is None or mtime > latest:
                    latest = mtime
        except OSError:
            continue
    if latest is None:
        return os.path.getmtime(path)
    return latest

# Path to rename batch-report to, using the newest file's mtime.
#
# Suffix format is YYYY-MM-DD-HHMM (local time), e.g.
# batch-report-2026-09-14-0137. If that name is already taken,
# append -2, -3, and so on.
def archived_batch_dir_path(path):
    stamp = datetime.fromtimestamp(
        most_recent_file_mtime(path)
    ).strftime("%Y-%m-%d-%H%M")
    parent = os.path.dirname(path)
    base = f"{BATCH_REPORT_DIRNAME}-{stamp}"
    candidate = os.path.join(parent, base)
    if not os.path.exists(candidate):
        return candidate
    n = 2
    while True:
        candidate = os.path.join(parent, f"{base}-{n}")
        if not os.path.exists(candidate):
            return candidate
        n += 1

# Delete all files and subdirectories inside path, leaving path itself
def erase_directory_contents(path):
    for name in os.listdir(path):
        entry = os.path.join(path, name)
        if os.path.isdir(entry) and not os.path.islink(entry):
            shutil.rmtree(entry)
        else:
            os.remove(entry)

# Ask how to handle a nonempty batch-report directory.
# Returns "erase", "merge", "rename", or "cancel".
def ask_nonempty_batch_dir():
    dialog = tk.Toplevel(root)
    # Hide until the layout has a real size. On Windows, calling
    # resizable(False) or geometry("+x+y") before that freezes the
    # window at the first widget's size and clips the buttons.
    dialog.withdraw()
    dialog.title("Batch report directory is not empty")
    dialog.transient(root)

    result = {"choice": "cancel"}

    def choose(choice):
        result["choice"] = choice
        dialog.destroy()

    container = tk.Frame(dialog, padx=12, pady=10)
    container.pack()

    tk.Label(
        container,
        text=f"Output directory '{BATCH_REPORT_DIRNAME}' is not empty (may "
              "contain reports from a previous run).",
    ).pack(anchor="w", pady=(0, 8))

    buttons = [
        ("Erase existing contents", "erase"),
        ("Merge (overwrite existing files with same names)",
         "merge"),
        ("Rename existing directory (add date suffix) "
         "then proceed", "rename"),
        ("Cancel", "cancel"),
    ]
    for label, choice in buttons:
        tk.Button(
            container, text=label,
            command=lambda c=choice: choose(c),
            anchor="w",
        ).pack(fill="x", pady=2)

    dialog.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
    dialog.bind("<Escape>", lambda e: choose("cancel"))

    dialog.update_idletasks()
    dw = max(dialog.winfo_reqwidth(),
             container.winfo_reqwidth())
    dh = max(dialog.winfo_reqheight(),
             container.winfo_reqheight())
    px = root.winfo_rootx()
    py = root.winfo_rooty()
    pw = root.winfo_width()
    ph = root.winfo_height()
    x = px + max((pw - dw) // 2, 0)
    y = py + max((ph - dh) // 2, 0)
    dialog.geometry(f"{dw}x{dh}+{x}+{y}")
    dialog.minsize(dw, dh)
    dialog.resizable(False, False)

    dialog.deiconify()
    dialog.lift()
    dialog.wait_visibility()
    dialog.grab_set()
    dialog.focus_set()
    dialog.wait_window()
    return result["choice"]

# Read student usernames from a text file (one per line).
#
# Blank lines and # comments are ignored, surrounding whitespace is
# stripped, and duplicates are dropped while preserving first-seen
# order.
def load_usernames_from_file(path):
    usernames = []
    seen = set()
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            name = line.strip()
            if not name or name.startswith("#") or name in seen:
                continue
            seen.add(name)
            usernames.append(name)
    return usernames

# Append a line to the report text box and scroll it into view
def append_report_progress(message):
    report_text.insert(tk.END, message + "\n")
    report_text.see(tk.END)
    root.update()

# Read the deadline fields from the GUI.
#
# Returns a timezone-aware datetime, or None if the values are
# invalid (an error dialog is shown in that case).
def parse_deadline_from_gui():
    try:
        date = date_entry.get_date()
        hour = int(hour_entry.get())
        minute = int(min_entry.get())
        second = int(sec_entry.get())
        offset_hours = int(offset_entry.get())
        tz = timezone(timedelta(hours=offset_hours))
        return datetime.combine(
            date, time(hour, minute, second)
        ).replace(tzinfo=tz)
    except ValueError:
        messagebox.showerror("Error", "Invalid input values.")
        return None

# Enable the widgets that match the selected report mode
def on_report_mode_change():
    if report_mode.get() == "single":
        username_entry.config(state=tk.NORMAL)
        select_file_button.config(state=tk.DISABLED)
    else:
        username_entry.config(state=tk.DISABLED)
        select_file_button.config(state=tk.NORMAL)

# Launch a file picker and remember the chosen username list
def on_select_username_file_click():
    global username_file_path
    path = filedialog.askopenfilename(
        title="Select username list",
        filetypes=[
            ("Text files", "*.txt"),
            ("All files", "*.*"),
        ])
    if not path:
        return
    username_file_path = path
    try:
        count = len(load_usernames_from_file(path))
        username_file_label.config(
            text=f"{os.path.basename(path)} ({count} student(s))")
    except OSError:
        username_file_label.config(text=os.path.basename(path))

# Generate one student's report into the GUI text box
def run_single_report(deadline):
    username = username_entry.get().strip()
    if not username:
        messagebox.showerror("Error", "Please enter a username.")
        return

    # Clear the text box to signal that generation is starting
    # N.B.: "1.0" here selects "line 1, character 0"
    report_text.delete("1.0", tk.END)

    report_status_label.config(text="Downloading user solves...")
    root.update()

    try:
        report = generate_report(username, dojo, deadline)
        report_text.insert(tk.END, report)
    except DojoNotFoundError as e:
        messagebox.showerror("Error", str(e))
    except DojoNetworkError as e:
        messagebox.showerror("Error", f"Network error: {str(e)}")
    except DojoParseError as e:
        messagebox.showerror(
            "Error", f"Server response error: {str(e)}")

# Generate one student's report and write it under output_dir.
# Returns True on success, False on failure (already logged).
def write_one_batch_report(username, deadline, output_dir):
    try:
        report = generate_report(username, dojo, deadline)
        filename = report_filename_for(username)
        out_path = os.path.join(output_dir, filename)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(report)
            if not report.endswith("\n"):
                handle.write("\n")

        # Include the overall score in the progress line so the
        # batch log is scannable without opening every file.
        last_line = report.strip().split("\n")[-1]
        if last_line.startswith("Overall:"):
            append_report_progress(
                f"{username}: done - {last_line} ({filename})")
        else:
            append_report_progress(
                f"{username}: done ({filename})")
        return True
    except (DojoNotFoundError, DojoNetworkError,
            DojoParseError) as e:
        append_report_progress(f"{username}: error - {e}")
        return False
    except OSError as e:
        append_report_progress(
            f"{username}: error writing file - {e}")
        return False

# Generate reports for every username in the selected file.
#
# Each student's report is written to batch-report/<username>.txt.
# The GUI text box shows per-student progress rather than the full
# report text.
def run_batch_reports(deadline):
    if not username_file_path:
        messagebox.showerror(
            "Error", "Please select a username file.")
        return

    try:
        usernames = load_usernames_from_file(username_file_path)
    except OSError as e:
        messagebox.showerror(
            "Error", f"Could not read username file: {e}")
        return

    if not usernames:
        messagebox.showerror(
            "Error",
            "The selected file contains no usernames.")
        return

    output_dir = batch_report_dir()
    preexisting_note = None
    if dir_is_nonempty(output_dir):
        choice = ask_nonempty_batch_dir()
        if choice == "cancel":
            return
        try:
            if choice == "erase":
                erase_directory_contents(output_dir)
                preexisting_note = (
                    "Erased existing contents of "
                    f"{BATCH_REPORT_DIRNAME}")
            elif choice == "rename":
                archived = archived_batch_dir_path(output_dir)
                os.rename(output_dir, archived)
                preexisting_note = (
                    f"Renamed existing {BATCH_REPORT_DIRNAME} "
                    f"to {os.path.basename(archived)}")
            elif choice == "merge":
                preexisting_note = (
                    f"Merging into existing "
                    f"{BATCH_REPORT_DIRNAME} (same names will "
                    f"be overwritten)")
        except OSError as e:
            messagebox.showerror(
                "Error",
                f"Could not prepare output directory: {e}")
            return

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        messagebox.showerror(
            "Error",
            f"Could not create output directory: {e}")
        return

    report_text.delete("1.0", tk.END)
    n = len(usernames)
    append_report_progress(
        f"Starting batch report for {n} student(s)...")
    append_report_progress(f"Output directory: {output_dir}")
    if preexisting_note:
        append_report_progress(preexisting_note)
    append_report_progress("")

    succeeded = 0
    failed = 0
    for i, username in enumerate(usernames, 1):
        report_status_label.config(
            text=f"Downloading solves for {username} ({i}/{n})...")
        root.update()
        if write_one_batch_report(username, deadline, output_dir):
            succeeded += 1
        else:
            failed += 1

    append_report_progress("")
    append_report_progress(
        f"Batch complete: {succeeded} succeeded, "
        f"{failed} failed.")

# Implements the "Generate Report" button
#
# Downloads completed challenges and compares them with the selected
# challenges and deadline. In single-student mode the report is shown
# in the GUI text box; in batch mode each student's report is written
# to a file under batch-report/. All selected challenges are weighted
# equally regardless of how they break down into modules.
def on_generate_report_click():
    deadline = parse_deadline_from_gui()
    if deadline is None:
        return
    if not dojo or not all_challenges:
        messagebox.showerror(
            "Error",
            "Please load a dojo on the first tab first.")
        return
    if not checked_challenges:
        messagebox.showerror(
            "Error",
            "Please select at least one challenge.")
        return

    generate_button.config(state=tk.DISABLED)
    single_radio.config(state=tk.DISABLED)
    batch_radio.config(state=tk.DISABLED)
    username_entry.config(state=tk.DISABLED)
    select_file_button.config(state=tk.DISABLED)
    try:
        if report_mode.get() == "batch":
            run_batch_reports(deadline)
        else:
            run_single_report(deadline)
    finally:
        generate_button.config(state=tk.NORMAL)
        single_radio.config(state=tk.NORMAL)
        batch_radio.config(state=tk.NORMAL)
        on_report_mode_change()
        report_status_label.config(text="")

# Implements the "Now" button (sets current time in the GUI deadline fields)
# Can also be called directly from other code that wishes to do this (e.g. on program startup)
def set_current_time():
    global current_timezone
    now = datetime.now()
    current_timezone = now.astimezone().tzinfo  # Store the original timezone

    date_entry.set_date(now.date())
    hour_entry.delete(0, tk.END)
    hour_entry.insert(0, str(now.hour))
    min_entry.delete(0, tk.END)
    min_entry.insert(0, str(now.minute))
    sec_entry.delete(0, tk.END)
    sec_entry.insert(0, str(now.second))

    # Set UTC offset to match local timezone
    local_offset_seconds = now.astimezone().utcoffset().total_seconds()
    local_offset_hours = int(local_offset_seconds / 3600)
    offset_entry.delete(0, tk.END)
    offset_entry.insert(0, str(local_offset_hours))

# GUI setup
root = tk.Tk()
root.title("PwnCollege Autograder")
root.resizable(True, True)

# Center the window on screen
window_width = 800
window_height = 600
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
x = (screen_width // 2) - (window_width // 2)
y = (screen_height // 2) - (window_height // 2)
root.geometry(f"{window_width}x{window_height}+{x}+{y}")

notebook = ttk.Notebook(root)
notebook.pack(fill='both', expand=True)

# Tab 1: Select Dojo and Assignments
tab1 = ttk.Frame(notebook)
notebook.add(tab1, text="Select Dojo and Assignments")

# Create input frame for dojo controls
dojo_frame = tk.Frame(tab1)
dojo_frame.pack(anchor="w", pady=5)

tk.Label(dojo_frame, text="Dojo:").grid(row=0, column=0, sticky="w")
dojo_entry = tk.Entry(dojo_frame)
dojo_entry.grid(row=0, column=1, sticky="w", padx=(5, 5))
dojo_entry.bind('<Return>', lambda e: on_load_challenges_click())
load_button = tk.Button(dojo_frame, text="Load Challenges", command=on_load_challenges_click)
load_button.grid(row=0, column=2, sticky="w")
select_all_button = tk.Button(dojo_frame, text="Select All", command=on_select_all_click)
select_all_button.grid(row=0, column=3, sticky="w", padx=(5, 0))
select_all_button.grid_remove()  # Hide initially
deselect_all_button = tk.Button(dojo_frame, text="Deselect All", command=on_deselect_all_click)
deselect_all_button.grid(row=0, column=4, sticky="w", padx=(5, 0))
deselect_all_button.grid_remove()  # Hide initially
status_label = tk.Label(dojo_frame, text="")  # displays download status when active
status_label.grid(row=0, column=5, sticky="w", padx=(5, 0))

# Create a frame for the tree and scrollbar
tree_frame = tk.Frame(tab1)
tree_frame.pack(fill='both', expand=True)

tree_scrollbar = tk.Scrollbar(tree_frame)
tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

tree = ttk.Treeview(tree_frame, show='tree', yscrollcommand=tree_scrollbar.set)
tree.pack(side=tk.LEFT, fill='both', expand=True)

tree_scrollbar.config(command=tree.yview)

# Hide +/- buttons to expand/contract the tree by customizing the layout
# (we couldn't support them properly without item selection toggling glitching out)
style = ttk.Style()
style.layout("Treeview.Item", [
    ('Treeitem.padding', {'sticky': 'nswe', 'children': [
        ('Treeitem.text', {'sticky': 'nswe'})
    ]})
])
tree.bind('<Button-1>', on_tree_click)
# Disable tree item opening/closing
tree.bind('<Double-1>', lambda e: "break")
tree.bind('<<TreeviewOpen>>', lambda e: "break")
tree.bind('<<TreeviewClose>>', lambda e: "break")

# Tab 2: Generate Report
tab2 = ttk.Frame(notebook)
notebook.add(tab2, text="Generate Report")

# Create input frame to keep inputs left-justified
input_frame = tk.Frame(tab2)
input_frame.pack(anchor="w")

# Mode selection: single student vs. batch from a username file.
# Nested so the radio rows don't have to share columns with the
# deadline widgets below.
mode_frame = tk.Frame(input_frame)
mode_frame.grid(row=0, column=0, columnspan=11, sticky="w",
                pady=(0, 5))

report_mode = tk.StringVar(value="single")

single_radio = tk.Radiobutton(
    mode_frame, text="Single student:",
    variable=report_mode, value="single",
    command=on_report_mode_change)
single_radio.grid(row=0, column=0, sticky="w")

username_entry = tk.Entry(mode_frame)
username_entry.grid(row=0, column=1, sticky="w", padx=(5, 0))
username_entry.bind('<Return>', lambda e: on_generate_report_click())

batch_radio = tk.Radiobutton(
    mode_frame, text="Batch from file:",
    variable=report_mode, value="batch",
    command=on_report_mode_change)
batch_radio.grid(row=1, column=0, sticky="w")

select_file_button = tk.Button(
    mode_frame, text="Select File...",
    command=on_select_username_file_click,
    state=tk.DISABLED)
select_file_button.grid(row=1, column=1, sticky="w", padx=(5, 0))

username_file_label = tk.Label(mode_frame, text="(no file selected)")
username_file_label.grid(row=1, column=2, sticky="w", padx=(5, 0))

tk.Label(input_frame, text="Deadline Date:").grid(row=1, column=0, sticky="w")
date_entry = DateEntry(input_frame, date_pattern='yyyy-mm-dd')
date_entry.grid(row=1, column=1, sticky="w")

tk.Label(input_frame, text="Hour (0-23):").grid(row=1, column=2, sticky="w")
hour_entry = tk.Entry(input_frame, width=3)
hour_entry.insert(0, "0")
hour_entry.grid(row=1, column=3, sticky="w")

tk.Label(input_frame, text="Minute (0-59):").grid(row=1, column=4, sticky="w")
min_entry = tk.Entry(input_frame, width=3)
min_entry.insert(0, "0")
min_entry.grid(row=1, column=5, sticky="w")

tk.Label(input_frame, text="Second (0-59):").grid(row=1, column=6, sticky="w")
sec_entry = tk.Entry(input_frame, width=3)
sec_entry.insert(0, "0")
sec_entry.grid(row=1, column=7, sticky="w")

tk.Label(input_frame, text="UTC Offset (hours):").grid(row=1, column=8, sticky="w")
offset_entry = tk.Entry(input_frame, width=4)
offset_entry.insert(0, "0")
offset_entry.grid(row=1, column=9, sticky="w")

now_button = tk.Button(input_frame, text="Now", command=set_current_time)
now_button.grid(row=1, column=10, sticky="w")

generate_button = tk.Button(
    input_frame, text="Generate Report",
    command=on_generate_report_click)
generate_button.grid(row=2, column=0, sticky="w")
# displays download status when active
report_status_label = tk.Label(input_frame, text="")
report_status_label.grid(row=2, column=1, columnspan=9, sticky="w",
                         padx=(5, 0))

# Text area
text_frame = tk.Frame(tab2)
text_frame.pack(fill='both', expand=True)

scrollbar = tk.Scrollbar(text_frame)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

report_text = tk.Text(text_frame, height=20, width=80, yscrollcommand=scrollbar.set)
report_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

scrollbar.config(command=report_text.yview)

tab2.rowconfigure(3, weight=1)
tab2.columnconfigure(0, weight=1)

# Initialize the time fields with current time
root.after(100, set_current_time)  # Call after GUI is fully constructed

root.mainloop()
