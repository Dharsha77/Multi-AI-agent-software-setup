# multi_agent_installer_with_scheduler.py
import os
import platform
import subprocess
import requests
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import pyttsx3
import speech_recognition as sr
import json
from datetime import datetime, timedelta
import uuid
import time

SCHEDULE_STORE = Path.home() / ".multi_agent_installer_schedules.json"

# =============================
# Voice Engine
# =============================
engine = pyttsx3.init()
def speak(text: str):
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass  # fail silently for TTS so UI remains responsive

# =============================
# Software Database (demo subset)
# =============================
software_db = {
    "python": {
        "dependencies": [],
        "windows": {
            "url": "https://www.python.org/ftp/python/3.11.5/python-3.11.5-amd64.exe",
            "install_cmd": ["/quiet", "InstallAllUsers=1", "PrependPath=1"],
            "path_check": r"C:\Python311\python.exe"
        }
    },
    "anaconda": {
        "dependencies": ["python"],
        "windows": {
            "url": "https://repo.anaconda.com/archive/Anaconda3-2023.07-Windows-x86_64.exe",
            "install_cmd": ["/S", "/InstallationType=AllUsers", "/AddToPath=1"],
            "path_check": r"C:\ProgramData\Anaconda3\python.exe"
        }
    },
    "java": {
        "dependencies": [],
        "windows": {
            "url": "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.exe",
            "install_cmd": ["/s"],
            "path_check": r"C:\Program Files\Java\jdk-21\bin\java.exe"
        }
    }
}

# =============================
# Dependency Resolver
# =============================
def resolve_dependencies(software, resolved=None, seen=None):
    if resolved is None:
        resolved = []
    if seen is None:
        seen = set()
    if software in seen:
        return resolved
    seen.add(software)

    details = software_db.get(software)
    if not details:
        return resolved

    for dep in details.get("dependencies", []):
        resolve_dependencies(dep, resolved, seen)

    if software not in resolved:
        resolved.append(software)
    return resolved

# =============================
# Download Helper
# =============================
def download_file(url, dest, progress_var, log_area=None):
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0) or 0)
            downloaded = 0
            chunk_size = 8192
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        percent = int((downloaded / total) * 100)
                        progress_var.set(percent)
                        if log_area:
                            log_area.update_idletasks()
        return True, "Downloaded"
    except Exception as e:
        return False, str(e)

# =============================
# Installer Agent (Windows-focused demo)
# =============================
def install_software(software, log_area, status_label, progress_var):
    os_label = platform.system().lower()
    # For demo brevity we only look up windows entry in software_db:
    details = software_db[software].get("windows")
    path_check = details.get("path_check")

    # Already installed?
    if path_check and os.path.exists(os.path.expandvars(path_check)):
        status_label.config(text="Already Installed", foreground="green")
        log_area.insert(tk.END, f"{software} already installed.\n")
        return

    url = details.get("url")
    installer_path = os.path.join(str(Path.home()), f"{software}_installer.exe")

    status_label.config(text="Downloading...", foreground="blue")
    log_area.insert(tk.END, f"[{now_str()}] Downloading {software}...\n")
    success, msg = download_file(url, installer_path, progress_var, log_area)
    if not success:
        status_label.config(text="Download Failed", foreground="red")
        log_area.insert(tk.END, f"[{now_str()}] {software} download failed: {msg}\n")
        speak(f"{software} download failed")
        return

    status_label.config(text="Installing...", foreground="orange")
    log_area.insert(tk.END, f"[{now_str()}] Installing {software}...\n")
    try:
        subprocess.run([installer_path] + details["install_cmd"], check=True)
        status_label.config(text="Installed", foreground="green")
        log_area.insert(tk.END, f"[{now_str()}] {software} installed successfully.\n")
        speak(f"{software} installation completed")
    except Exception as e:
        status_label.config(text="Install Failed", foreground="red")
        log_area.insert(tk.END, f"[{now_str()}] {software} installation failed: {e}\n")
        speak(f"{software} installation failed")

# =============================
# Utility
# =============================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =============================
# Scheduler: in-app persistent scheduling
# =============================
_scheduled_timers = {}  # job_id -> threading.Timer
_scheduled_jobs = {}    # job_id -> job dict (stored to disk)

def load_schedules():
    global _scheduled_jobs
    if SCHEDULE_STORE.exists():
        try:
            with open(SCHEDULE_STORE, "r", encoding="utf-8") as f:
                _scheduled_jobs = json.load(f)
        except Exception:
            _scheduled_jobs = {}
    else:
        _scheduled_jobs = {}

def save_schedules():
    try:
        with open(SCHEDULE_STORE, "w", encoding="utf-8") as f:
            json.dump(_scheduled_jobs, f, indent=2)
    except Exception as e:
        print("Failed to save schedules:", e)

def schedule_job(command_text, run_at_dt, log_area, software_frames, persist=True):
    """
    schedule: command_text (string), run_at_dt (datetime)
    returns job_id on success
    """
    now = datetime.now()
    delay = (run_at_dt - now).total_seconds()
    if delay <= 0:
        raise ValueError("Scheduled time must be in the future")

    job_id = str(uuid.uuid4())
    job = {"id": job_id, "command": command_text, "run_at": run_at_dt.isoformat()}
    _scheduled_jobs[job_id] = job
    if persist:
        save_schedules()

    # Timer callback
    def _run_job():
        try:
            # Show in log area
            log_area.insert(tk.END, f"[{now_str()}] Running scheduled job: {command_text}\n")
            # Recreate main_agent behavior for scheduled run
            main_agent(command_text, log_area, software_frames)
        except Exception as e:
            log_area.insert(tk.END, f"[{now_str()}] Scheduled job error: {e}\n")
        finally:
            # Remove job from in-memory store and disk (job done)
            _scheduled_jobs.pop(job_id, None)
            save_schedules()
            _scheduled_timers.pop(job_id, None)
            # Update scheduled jobs UI (we'll call refresh)
            refresh_scheduled_listbox()

    t = threading.Timer(delay, _run_job)
    t.daemon = True
    t.start()
    _scheduled_timers[job_id] = {"timer": t, "run_at": run_at_dt, "command": command_text}
    refresh_scheduled_listbox()
    return job_id

def cancel_scheduled_job(job_id):
    info = _scheduled_timers.get(job_id)
    if info:
        try:
            info["timer"].cancel()
        except Exception:
            pass
    _scheduled_timers.pop(job_id, None)
    _scheduled_jobs.pop(job_id, None)
    save_schedules()
    refresh_scheduled_listbox()

def reschedule_pending_jobs(log_area, software_frames):
    # load saved and re-create timers for future jobs
    load_schedules()
    now = datetime.now()
    for job_id, job in list(_scheduled_jobs.items()):
        run_at = datetime.fromisoformat(job["run_at"])
        if run_at <= now:
            # job time already passed while app was closed -> run immediately in background
            try:
                threading.Thread(target=lambda: main_agent(job["command"], log_area, software_frames), daemon=True).start()
            except Exception as e:
                log_area.insert(tk.END, f"[{now_str()}] Error running pending job {job_id}: {e}\n")
            _scheduled_jobs.pop(job_id, None)
            save_schedules()
            continue
        # schedule timer
        if job_id not in _scheduled_timers:
            try:
                schedule_job(job["command"], run_at, log_area, software_frames, persist=False)
            except Exception as e:
                log_area.insert(tk.END, f"[{now_str()}] Error scheduling job {job_id}: {e}\n")

# =============================
# Main Agent: multi-software execution
# =============================
def main_agent(command_text, log_area, software_frames):
    command = command_text.lower()
    # find requested software names (simple substring matching)
    softwares_to_install = []
    for s in software_db.keys():
        if s in command:
            order = resolve_dependencies(s)
            for item in order:
                if item not in softwares_to_install:
                    softwares_to_install.append(item)

    if not softwares_to_install:
        log_area.insert(tk.END, f"[{now_str()}] No known software found in command: {command_text}\n")
        speak("No recognized software found in your command")
        return

    log_area.insert(tk.END, f"[{now_str()}] Installation order: {', '.join(softwares_to_install)}\n")
    speak(f"Installing in order: {', '.join(softwares_to_install)}")
    for software in softwares_to_install:
        if software not in software_frames:
            log_area.insert(tk.END, f"[{now_str()}] UI missing frame for {software}, skipping\n")
            continue
        frame = software_frames[software]
        status_label = frame["status"]
        progress_var = frame["progress"]
        # run installer in separate thread to keep UI responsive
        threading.Thread(target=install_software, args=(software, log_area, status_label, progress_var), daemon=True).start()

# =============================
# Voice Listener
# =============================
def listen_voice(log_area, software_frames):
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        log_area.insert(tk.END, f"[{now_str()}] Listening for voice command...\n")
        audio = recognizer.listen(source)
    try:
        cmd = recognizer.recognize_google(audio).lower()
        log_area.insert(tk.END, f"[{now_str()}] Voice command: {cmd}\n")
        threading.Thread(target=main_agent, args=(cmd, log_area, software_frames), daemon=True).start()
    except Exception as e:
        log_area.insert(tk.END, f"[{now_str()}] Could not understand voice: {e}\n")

# =============================
# GUI
# =============================
def refresh_scheduled_listbox():
    # refresh the Scheduled Jobs listbox content from _scheduled_timers
    listbox.delete(0, tk.END)
    # Combine timers and persisted jobs to show both scheduled and persisted items
    for job_id, info in _scheduled_timers.items():
        run_at = info["run_at"]
        cmd = info["command"]
        listbox.insert(tk.END, f"{job_id} | {run_at.strftime('%Y-%m-%d %H:%M')} | {cmd}")

def on_schedule_button():
    cmd_text = schedule_cmd_entry.get().strip()
    dt_text = schedule_time_entry.get().strip()
    if not cmd_text or not dt_text:
        messagebox.showerror("Input error", "Enter both command and date/time.")
        return
    try:
        run_at = datetime.strptime(dt_text, "%Y-%m-%d %H:%M")
    except ValueError:
        messagebox.showerror("Format error", "Date/time format must be YYYY-MM-DD HH:MM")
        return
    try:
        job_id = schedule_job(cmd_text, run_at, log_area, software_frames)
        messagebox.showinfo("Scheduled", f"Job scheduled: {job_id} at {run_at}")
        log_area.insert(tk.END, f"[{now_str()}] Scheduled job {job_id} at {run_at}\n")
    except Exception as e:
        messagebox.showerror("Scheduling error", str(e))

def on_cancel_job():
    sel = listbox.curselection()
    if not sel:
        messagebox.showwarning("Select", "Select a scheduled job to cancel")
        return
    selected = listbox.get(sel[0])
    job_id = selected.split("|")[0].strip()
    cancel_scheduled_job(job_id)
    log_area.insert(tk.END, f"[{now_str()}] Cancelled job {job_id}\n")

root = tk.Tk()
root.title("Multi-Agent AI Installer (Scheduler-enabled)")
root.geometry("900x600")

tk.Label(root, text="Multi-Agent AI Installer (Scheduler-enabled)", font=("Arial", 16, "bold")).pack(pady=10)

# Software Status Frames
software_frames = {}
status_container = ttk.Frame(root)
status_container.pack(fill="x", padx=10)
for s in software_db.keys():
    frame = ttk.Frame(status_container)
    frame.pack(fill="x", pady=3)
    tk.Label(frame, text=s.capitalize(), width=15, anchor="w").pack(side="left")
    status_label = tk.Label(frame, text="Pending", width=15, anchor="w")
    status_label.pack(side="left", padx=5)
    progress_var = tk.IntVar()
    progress = ttk.Progressbar(frame, variable=progress_var, maximum=100, length=300)
    progress.pack(side="left", padx=5)
    software_frames[s] = {"status": status_label, "progress": progress_var}

# Logs
log_area = scrolledtext.ScrolledText(root, height=12)
log_area.pack(fill="both", expand=True, padx=10, pady=10)

# Controls: voice, schedule, etc.
controls = ttk.Frame(root)
controls.pack(fill="x", padx=10, pady=5)

# Voice Command button
ttk.Button(controls, text="Voice Command", command=lambda: threading.Thread(target=listen_voice, args=(log_area, software_frames), daemon=True).start()).pack(side="left", padx=5)

# Text command input for immediate run
cmd_entry = ttk.Entry(controls, width=50)
cmd_entry.pack(side="left", padx=5)
cmd_entry.insert(0, "Install Python and Anaconda")

def on_run_text_command():
    cmd = cmd_entry.get().strip()
    if cmd:
        threading.Thread(target=main_agent, args=(cmd, log_area, software_frames), daemon=True).start()

ttk.Button(controls, text="Run Command Now", command=on_run_text_command).pack(side="left", padx=5)

# Scheduler controls
sched_frame = ttk.Labelframe(root, text="Schedule a command (persistent)")
sched_frame.pack(fill="x", padx=10, pady=8)

tk.Label(sched_frame, text="Command:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
schedule_cmd_entry = ttk.Entry(sched_frame, width=60)
schedule_cmd_entry.grid(row=0, column=1, padx=4, pady=4)
schedule_cmd_entry.insert(0, "Install Python and Anaconda")

tk.Label(sched_frame, text="Run at (YYYY-MM-DD HH:MM):").grid(row=1, column=0, sticky="w", padx=4, pady=4)
schedule_time_entry = ttk.Entry(sched_frame, width=30)
schedule_time_entry.grid(row=1, column=1, sticky="w", padx=4, pady=4)

ttk.Button(sched_frame, text="Schedule", command=on_schedule_button).grid(row=0, column=2, rowspan=2, padx=6)

# Scheduled jobs list + cancel
jobs_frame = ttk.Labelframe(root, text="Scheduled Jobs")
jobs_frame.pack(fill="both", padx=10, pady=6, expand=False)

listbox = tk.Listbox(jobs_frame, height=6)
listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)
scroll = ttk.Scrollbar(jobs_frame, orient="vertical", command=listbox.yview)
scroll.pack(side="left", fill="y")
listbox.config(yscrollcommand=scroll.set)

ttk.Button(jobs_frame, text="Cancel Selected Job", command=on_cancel_job).pack(side="left", padx=6, pady=6)

# Load persisted schedules and reschedule timers
load_schedules()
reschedule_pending_jobs(log_area, software_frames)
refresh_scheduled_listbox()

# Exit
ttk.Button(root, text="Exit", command=root.destroy).pack(pady=6)

root.mainloop()
So friends, this is our program so don't share to others. tomorrow we will HOD and discuss regarding our project status. ok
