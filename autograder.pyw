import csv
import io
import os
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

# Path to the student CSV used in batch mode, or None if no file
# has been selected yet.
student_csv_path = None

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

# Make a human-readable filename stem safe for Windows/Linux.
#
# Commas and spaces are kept so names like "Lastname, Firstname -
# Assignment" stay readable. Characters that are illegal in
# Windows filenames are replaced with underscores.
def sanitize_filename_stem(stem):
    forbidden = '<>:"/\\|?*'
    chars = []
    for ch in stem:
        if ch in forbidden or ord(ch) < 32:
            chars.append("_")
        else:
            chars.append(ch)
    safe = "".join(chars).strip(" .")
    if not safe:
        safe = "unknown"
    return safe

# Filename for one student's batch report.
#
# Default: "Lastname, Firstname.txt". If assignment_name is
# provided: "Lastname, Firstname - Assignment Name.txt".
# disambiguator, if given, is inserted after the person's name.
def report_filename_for_student(student, assignment_name,
                                disambiguator=""):
    display = f"{student['last']}, {student['first']}"
    if disambiguator:
        display = f"{display} ({disambiguator})"
    assignment_name = assignment_name.strip()
    if assignment_name:
        stem = f"{display} - {assignment_name}"
    else:
        stem = display
    return sanitize_filename_stem(stem) + ".txt"

# Pick a report filename that has not already been used this batch.
#
# On a collision (two students with the same display name), the
# pwn.college username is appended to keep both files.
def allocate_report_filename(student, assignment_name, used):
    filename = report_filename_for_student(
        student, assignment_name)
    if filename in used:
        filename = report_filename_for_student(
            student, assignment_name,
            disambiguator=student["username"])
        n = 2
        while filename in used:
            filename = report_filename_for_student(
                student, assignment_name,
                disambiguator=f"{student['username']}-{n}")
            n += 1
    used.add(filename)
    return filename

# Basename of a per-run batch output folder.
#
# With an assignment: <assignment>-<timestamp>
# Without:            <timestamp>
# Timestamp is local time YYYY-MM-DD-HHMMSS.
def batch_report_dirname(assignment_name, now=None):
    if now is None:
        now = datetime.now()
    stamp = now.strftime("%Y-%m-%d-%H%M%S")
    assignment_name = assignment_name.strip()
    if assignment_name:
        safe = sanitize_filename_stem(assignment_name)
        return f"{safe}-{stamp}"
    return stamp

# If path already exists, return path-2, path-3, ...; else path.
def disambiguate_path(path):
    if not os.path.exists(path):
        return path
    n = 2
    while True:
        candidate = f"{path}-{n}"
        if not os.path.exists(candidate):
            return candidate
        n += 1

# Unique per-run batch output directory next to this script.
def allocate_batch_report_dir(assignment_name=""):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base = batch_report_dirname(assignment_name)
    return disambiguate_path(os.path.join(script_dir, base))

# Decode CSV bytes from Excel's common save formats.
#
# "CSV UTF-8" writes UTF-8 with a BOM; plain "CSV" on Windows
# Excel uses the ANSI code page (cp1252) and no BOM. A UTF-16
# BOM (Excel "Unicode Text") is also recognized.
def decode_csv_bytes(raw):
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")

# Read students from a CSV with columns: last, first, username.
#
# Blank lines and # comments are ignored. A header row is skipped
# if the first two fields look like last/first column names.
# Duplicate usernames are dropped, keeping the first occurrence.
# Extra columns beyond the first three are ignored.
def load_students_from_csv(path):
    students = []
    seen = set()
    first_data = True
    with open(path, "rb") as handle:
        text = decode_csv_bytes(handle.read())
    reader = csv.reader(io.StringIO(text, newline=""))
    for row_num, row in enumerate(reader, 1):
        if not row or all(not c.strip() for c in row):
            continue
        if row[0].lstrip().startswith("#"):
            continue
        if len(row) < 3:
            raise ValueError(
                f"Line {row_num}: expected 3 columns "
                f"(last, first, username), "
                f"found {len(row)}")
        last = row[0].strip()
        first = row[1].strip()
        username = row[2].strip()
        if first_data:
            first_data = False
            if (last.lower() in (
                    "last", "lastname", "last name")
                    and first.lower() in (
                        "first", "firstname",
                        "first name")):
                continue
        if not last or not first or not username:
            raise ValueError(
                f"Line {row_num}: last name, first name, "
                f"and username are all required")
        if username in seen:
            continue
        seen.add(username)
        students.append({
            "last": last,
            "first": first,
            "username": username,
        })
    return students

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
        assignment_entry.config(state=tk.DISABLED)
    else:
        username_entry.config(state=tk.DISABLED)
        select_file_button.config(state=tk.NORMAL)
        assignment_entry.config(state=tk.NORMAL)

# Launch a file picker and remember the chosen student CSV
def on_select_student_csv_click():
    global student_csv_path
    path = filedialog.askopenfilename(
        title="Select student CSV",
        filetypes=[
            ("CSV files", "*.csv"),
            ("Text files", "*.txt"),
            ("All files", "*.*"),
        ])
    if not path:
        return
    student_csv_path = path
    try:
        count = len(load_students_from_csv(path))
        student_file_label.config(
            text=f"{os.path.basename(path)} ({count} student(s))")
    except (OSError, ValueError, csv.Error) as e:
        student_file_label.config(text=os.path.basename(path))
        messagebox.showerror(
            "Error", f"Could not read student CSV: {e}")

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

# Append a multi-line per-student summary to the batch log.
#
# processed/total is how far the batch has gotten after this
# student (1-based). filename is included on success only.
def append_student_batch_progress(student, processed, total,
                                  status_line, filename=None):
    display = f"{student['last']}, {student['first']}"
    username = student["username"]
    pct = (processed / total) * 100 if total else 0.0
    append_report_progress(f"{display} ({username})")
    append_report_progress(f"  {status_line}")
    if filename:
        append_report_progress(f"  Report written to '{filename}'")
    append_report_progress(
        f"  {processed}/{total} students processed "
        f"({pct:.1f}%)")
    append_report_progress("")

# Generate one student's report and write it under output_dir.
# Returns True on success, False on failure (already logged).
def write_one_batch_report(student, deadline, output_dir,
                           filename, processed, total):
    username = student["username"]
    try:
        report = generate_report(username, dojo, deadline)
        out_path = os.path.join(output_dir, filename)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(report)
            if not report.endswith("\n"):
                handle.write("\n")

        last_line = report.strip().split("\n")[-1]
        if last_line.startswith("Overall:"):
            status = f"Grading successful. {last_line}"
        else:
            status = "done"
        append_student_batch_progress(
            student, processed, total, status, filename)
        return True
    except (DojoNotFoundError, DojoNetworkError,
            DojoParseError) as e:
        append_student_batch_progress(
            student, processed, total, f"Error: {e}")
        return False
    except OSError as e:
        append_student_batch_progress(
            student, processed, total,
            f"error writing file - {e}")
        return False

# Generate reports for every student in the selected CSV.
#
# Each run writes into a new folder next to this script named
# from the assignment (if given) and the current timestamp.
# Per-student files are "Lastname, Firstname - Assignment.txt"
# (or without the assignment suffix if that field is blank).
# The GUI text box shows per-student progress rather than the
# full report text.
def run_batch_reports(deadline):
    if not student_csv_path:
        messagebox.showerror(
            "Error", "Please select a student CSV file.")
        return

    try:
        students = load_students_from_csv(student_csv_path)
    except (OSError, ValueError, csv.Error) as e:
        messagebox.showerror(
            "Error", f"Could not read student CSV: {e}")
        return

    if not students:
        messagebox.showerror(
            "Error",
            "The selected file contains no students.")
        return

    assignment_name = assignment_entry.get().strip()
    output_dir = allocate_batch_report_dir(assignment_name)
    try:
        os.makedirs(output_dir)
    except OSError as e:
        messagebox.showerror(
            "Error",
            f"Could not create output directory: {e}")
        return

    report_text.delete("1.0", tk.END)
    n = len(students)
    append_report_progress(
        f"Starting batch report for {n} student(s)...")
    append_report_progress(f"Output directory: {output_dir}")
    if assignment_name:
        append_report_progress(
            f"Assignment: {assignment_name}")
    append_report_progress("")

    succeeded = 0
    failed = 0
    used_filenames = set()
    for i, student in enumerate(students, 1):
        username = student["username"]
        report_status_label.config(
            text=f"Downloading solves for {username} "
                 f"({i}/{n})...")
        root.update()
        filename = allocate_report_filename(
            student, assignment_name, used_filenames)
        if write_one_batch_report(
                student, deadline, output_dir, filename,
                i, n):
            succeeded += 1
        else:
            failed += 1

    append_report_progress(
        f"Batch complete: {succeeded} succeeded, "
        f"{failed} failed.")

# Implements the "Generate Report" button
#
# Downloads completed challenges and compares them with the selected
# challenges and deadline. In single-student mode the report is shown
# in the GUI text box; in batch mode each student's report is written
# to a timestamped folder next to this script. All selected
# challenges are weighted equally regardless of how they break down
# into modules.
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
    assignment_entry.config(state=tk.DISABLED)
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

# Mode selection: single student vs. batch from a student CSV.
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
    mode_frame, text="Batch from CSV:",
    variable=report_mode, value="batch",
    command=on_report_mode_change)
batch_radio.grid(row=1, column=0, sticky="w")

select_file_button = tk.Button(
    mode_frame, text="Select File...",
    command=on_select_student_csv_click,
    state=tk.DISABLED)
select_file_button.grid(row=1, column=1, sticky="w", padx=(5, 0))

student_file_label = tk.Label(mode_frame, text="(no file selected)")
student_file_label.grid(row=1, column=2, sticky="w", padx=(5, 0))

assignment_label = tk.Label(mode_frame, text="Assignment:")
assignment_label.grid(row=1, column=3, sticky="w", padx=(15, 0))
assignment_entry = tk.Entry(mode_frame, width=24)
assignment_entry.grid(row=1, column=4, sticky="w", padx=(5, 0))
assignment_entry.config(state=tk.DISABLED)

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
