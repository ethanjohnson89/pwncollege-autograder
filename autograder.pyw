import requests
from datetime import datetime, timezone, timedelta
import tkinter as tk
from tkinter import messagebox
from tkcalendar import DateEntry
from datetime import time

def get_student_solves(username, dojo):
    response = requests.get(f"https://pwn.college/pwncollege_api/v1/dojos/{dojo}/solves?username={username}")
    data = response.json()
    if not data.get("success"):
        return {}
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

def get_all_challenges(dojo):
    response = requests.get(f"https://pwn.college/pwncollege_api/v1/dojos/{dojo}/modules")
    data = response.json()
    if not data.get("success"):
        return {}
    modules = data.get("modules", [])
    challenges_dict = {}
    for module in modules:
        module_id = module["id"]
        challenges = [ch["id"] for ch in module["challenges"]]
        challenges_dict[module_id] = challenges
    return challenges_dict

def generate_report(username, dojo, deadline):
    solves_dict = get_student_solves(username, dojo)
    all_challenges = get_all_challenges(dojo)
    if not all_challenges:
        return "Failed to retrieve challenges."
    
    report = []
    report.append(f"Username: {username}")
    report.append(f"Dojo: {dojo}")
    report.append(f"Deadline: {deadline.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    report.append("")
    
    total_solves = sum(len(challenges) for challenges in solves_dict.values())
    report.append(f"Total solves: {total_solves}")
    module_ids = list(solves_dict.keys())
    report.append(f"Unique module IDs solved: {', '.join(module_ids)}")
    challenge_ids = set()
    for challenges in solves_dict.values():
        challenge_ids.update(challenges.keys())
    report.append(f"Unique challenge IDs solved: {', '.join(challenge_ids)}")
    report.append("")
    report.append("Challenges:")
    
    overall_before_deadline = 0
    total_challenges = sum(len(ch) for ch in all_challenges.values())
    
    for module in all_challenges:
        report.append(f"Module: {module}")
        challenges_solved = solves_dict.get(module, {})
        module_before_deadline = 0
        for challenge in all_challenges[module]:
            if challenge in challenges_solved:
                timestamp = challenges_solved[challenge]
                formatted_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                report.append(f"  {challenge}: Solved at {formatted_timestamp}")
                if timestamp < deadline:
                    module_before_deadline += 1
            else:
                report.append(f"  {challenge}: Not solved")
        total_in_module = len(all_challenges[module])
        overall_before_deadline += module_before_deadline
        percentage = (module_before_deadline / total_in_module) * 100 if total_in_module > 0 else 0
        report.append(f"{module_before_deadline}/{total_in_module} solved before deadline ({percentage:.1f}%)")
        report.append("")
    
    overall_percentage = (overall_before_deadline / total_challenges) * 100 if total_challenges > 0 else 0
    report.append(f"Overall: {overall_before_deadline}/{total_challenges} solved before deadline ({overall_percentage:.1f}%)")
    
    return "\n".join(report)

def on_generate():
    username = username_entry.get()
    dojo = dojo_entry.get()
    try:
        date = date_entry.get_date()
        hour = int(hour_entry.get())
        minute = int(min_entry.get())
        second = int(sec_entry.get())
        offset_hours = int(offset_entry.get())
        tz = timezone(timedelta(hours=offset_hours))
        deadline = datetime.combine(date, time(hour, minute, second)).replace(tzinfo=tz)
    except ValueError:
        messagebox.showerror("Error", "Invalid input values.")
        return
    if not username or not dojo:
        messagebox.showerror("Error", "Please fill in username and dojo.")
        return
    report = generate_report(username, dojo, deadline)
    report_text.delete(1.0, tk.END)
    report_text.insert(tk.END, report)

# GUI setup
root = tk.Tk()
root.title("PwnCollege Autograder")
root.resizable(True, True)

# Create input frame to keep inputs left-justified
input_frame = tk.Frame(root)
input_frame.grid(row=0, column=0, sticky="nw")

tk.Label(input_frame, text="Username:").grid(row=0, column=0, sticky="w")
username_entry = tk.Entry(input_frame)
username_entry.grid(row=0, column=1, sticky="w")

tk.Label(input_frame, text="Dojo:").grid(row=1, column=0, sticky="w")
dojo_entry = tk.Entry(input_frame)
dojo_entry.grid(row=1, column=1, sticky="w")

tk.Label(input_frame, text="Deadline Date:").grid(row=2, column=0, sticky="w")
date_entry = DateEntry(input_frame, date_pattern='yyyy-mm-dd')
date_entry.grid(row=2, column=1, sticky="w")

tk.Label(input_frame, text="Hour (0-23):").grid(row=2, column=2, sticky="w")
hour_entry = tk.Entry(input_frame, width=3)
hour_entry.insert(0, "0")
hour_entry.grid(row=2, column=3, sticky="w")

tk.Label(input_frame, text="Minute (0-59):").grid(row=2, column=4, sticky="w")
min_entry = tk.Entry(input_frame, width=3)
min_entry.insert(0, "0")
min_entry.grid(row=2, column=5, sticky="w")

tk.Label(input_frame, text="Second (0-59):").grid(row=2, column=6, sticky="w")
sec_entry = tk.Entry(input_frame, width=3)
sec_entry.insert(0, "0")
sec_entry.grid(row=2, column=7, sticky="w")

tk.Label(input_frame, text="UTC Offset (hours):").grid(row=2, column=8, sticky="w")
offset_entry = tk.Entry(input_frame, width=4)
offset_entry.insert(0, "0")
offset_entry.grid(row=2, column=9, sticky="w")

generate_button = tk.Button(input_frame, text="Generate Report", command=on_generate)
generate_button.grid(row=3, column=0, columnspan=10, sticky="w")

# Create a frame for the text area and scrollbar
text_frame = tk.Frame(root)
text_frame.grid(row=1, column=0, sticky='nsew')

scrollbar = tk.Scrollbar(text_frame)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

report_text = tk.Text(text_frame, height=20, width=80, yscrollcommand=scrollbar.set)
report_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

scrollbar.config(command=report_text.yview)

root.rowconfigure(1, weight=1)
root.columnconfigure(0, weight=1)

root.mainloop()
