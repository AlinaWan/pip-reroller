# -*- coding: utf-8 -*-
"""
app.py
"""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import Entry, Label, StringVar

from pynput import keyboard
from ahk import AHK
import cv2
import numpy as np

from app.capture import ScreenCapture
from app.config import ENABLE_LOGGING, ENABLE_DISCORD_RPC
from app.constants import RANKS, RANK_ORDER, RANK_TK_HEX
from app.theme import bg, label_fg, entry_bg, entry_fg, btn_bg, btn_fg
from app.utils import Tooltip
from app.processor import ImageProcessor

class PipRerollerApp:
    """
    Main Tkinter application for the Pip Reroller macro.

    This class manages the graphical user interface (GUI), user input,
    configuration settings, and background worker threads for
    continuous image processing and reroll automation.

    It handles:

    - GUI layout and input widgets for user configuration.
    - Thread-safe communication with background image processing and reroll threads.
    - Event handling for keyboard and window actions.
    - Logging of detected objects and application events (optional).

    :ivar root: The main Tkinter root window instance.
    :vartype root: tkinter.Tk

    :ivar game_area: Bounding box defining the screen region for pip detection.
    :vartype game_area: tuple or None

    :ivar chisel_button_pos: Screen coordinates of the chisel button.
    :vartype chisel_button_pos: tuple or None

    :ivar buy_button_pos: Screen coordinates of the buy button.
    :vartype buy_button_pos: tuple or None

    :ivar preview_active: Whether the preview mode is active.
    :vartype preview_active: bool

    :ivar running: Whether the reroll process is currently running.
    :vartype running: bool

    :ivar tolerance: Color tolerance used for pip detection.
    :vartype tolerance: int

    :ivar stop_at_ss: Minimum number of SS-rank pips required to stop rerolling.
    :vartype stop_at_ss: int

    :ivar click_delay_ms: Delay in milliseconds between simulated clicks.
    :vartype click_delay_ms: int

    :ivar post_reroll_delay_ms: Delay in milliseconds after each reroll before next action.
    :vartype post_reroll_delay_ms: int

    :ivar object_tolerance: Pixel tolerance for merging detected objects.
    :vartype object_tolerance: int

    :ivar image_poll_delay_ms: Interval in milliseconds between image processing polls.
    :vartype image_poll_delay_ms: int

    :ivar min_quality: Minimum pip rank quality to accept (e.g., "F", "SS").
    :vartype min_quality: str

    :ivar min_objects: Minimum number of pips of minimum quality required to stop rerolling.
    :vartype min_objects: int

    :ivar game_window_title: Title of the game window to capture.
    :vartype game_window_title: tkinter.StringVar

    :ivar rank_counts: Current counts of detected pips by rank, updated by background thread.
    :vartype rank_counts: dict

    :ivar status_var: Text variable for status label in the GUI.
    :vartype status_var: tkinter.StringVar

    :ivar message_var: Text variable for message label in the GUI.
    :vartype message_var: tkinter.StringVar

    :ivar status_color: Color hex code for status label.
    :vartype status_color: str

    :ivar log_buffer: Buffer holding log entries before dumping to file.
    :vartype log_buffer: list

    :ivar log_button: Button widget to manually dump logs when logging is enabled.
    :vartype log_button: tkinter.Button or None

    :ivar last_detected_objs: Cache of last detected objects to prevent attribute errors.
    :vartype last_detected_objs: list

    :ivar image_processor_thread: Background thread for image processing.
    :vartype image_processor_thread: threading.Thread or None

    :ivar reroll_loop_thread: Background thread managing reroll automation.
    :vartype reroll_loop_thread: threading.Thread or None

    :ivar preview_thread: Background thread for preview mode.
    :vartype preview_thread: threading.Thread or None

    :ivar stop_reroll_event: Event to signal stopping the reroll automation.
    :vartype stop_reroll_event: threading.Event

    :ivar listener: Keyboard listener for hotkey handling.
    :vartype listener: pynput.keyboard.Listener

    :ivar ahk: AutoHotkey interface for sending inputs to the game.
    :vartype ahk: ahk.AHK

    :meth __init__: Initializes the GUI, variables, threads, and event bindings.
    """
    def __init__(self, root):
        """
        Initialize the Pip Reroller application.
    
        Sets up the main window, GUI components, configuration variables,
        threading constructs, and event listeners. Also initializes optional
        logging mechanisms if enabled.
    
        :param root: The main Tkinter window instance on which the application UI is built.
        :type root: tkinter.Tk
        :rtype: None
        """
        self.root = root
        self.root.title("Auto Chiseler by Riri")
        self.root.geometry("440x550") # Increased height for new input field
        self.root.configure(bg=bg)
        self.root.attributes("-topmost", True) # Keep GUI on top

        # Configuration variables
        self.game_area = None
        self.chisel_button_pos = None
        self.buy_button_pos = None
        self.preview_active = False
        self.running = False

        self.tolerance = 10
        self.stop_at_ss = 0
        self.click_delay_ms = 50
        self.post_reroll_delay_ms = 500
        self.object_tolerance = 10
        self.image_poll_delay_ms = 10 # How often the image processor polls

        self.min_quality = "F"
        self.min_objects = 1
        self.game_window_title = StringVar(value="Roblox")

        # GUI state variables
        self.rank_counts = {rank: 0 for rank, _, _ in RANKS} # Updated by ImageProcessor via GUI callback
        self.status_var = StringVar(value="Status: Suspended")
        self.message_var = StringVar(value="")
        self.status_color = "#ff5555"

        # [DEBUG] Enable/disable logging
        self.log_buffer = []
        self.log_button = None
        self.last_detected_objs = [] # Prevent attribute errors if the reroll loop runs before detections

        # Thread management
        self.image_processor_thread = None
        self.reroll_loop_thread = None
        self.preview_thread = None
        self.stop_reroll_event = threading.Event() # Event for reroll loop to stop

        # --- GUI Elements ---
        pad_y = 5

        def make_label(text):
            """
            Create a styled Tkinter Label with predefined foreground and background colors.
            
            :param str text: The text to display on the label.
            
            :returns: A Tkinter Label widget configured with preset colors.
            :rtype: tkinter.Label
            """
            return tk.Label(root, text=text, fg=label_fg, bg=bg)

        # Input fields
        frame_delay = tk.Frame(root, bg=bg)
        frame_delay.pack(pady=(10, 0))
        delay_label = make_label("Click Delay (ms):")
        delay_label.pack(in_=frame_delay, side="left")
        Tooltip(delay_label, "Delay in milliseconds between simulated clicks.\nIncrease if the game lags or misses clicks.")
        self.click_delay_entry = Entry(frame_delay, bg=entry_bg, fg=entry_fg, insertbackground='white', width=6)
        self.click_delay_entry.pack(side="left", padx=(10, 0))
        self.click_delay_entry.insert(0, str(self.click_delay_ms))
        self.click_delay_entry.bind('<KeyRelease>', self.update_click_delay)

        frame_reroll_delay = tk.Frame(root, bg=bg)
        frame_reroll_delay.pack(pady=(10, 0))
        post_reroll_delay_label = make_label("Post Reroll Delay (ms):")
        post_reroll_delay_label.pack(in_=frame_reroll_delay, side="left")
        Tooltip(post_reroll_delay_label, "Delay in milliseconds between rerolls.\nSetting this value too low might reroll or delete\nthe charm underneath the one you're rerolling.")
        self.post_reroll_delay_entry = Entry(frame_reroll_delay, bg=entry_bg, fg=entry_fg, insertbackground='white', width=6)
        self.post_reroll_delay_entry.pack(side="left", padx=(10, 0))
        self.post_reroll_delay_entry.insert(0, str(self.post_reroll_delay_ms))
        self.post_reroll_delay_entry.bind('<KeyRelease>', self.update_post_reroll_delay)

        frame_poll_delay = tk.Frame(root, bg=bg)
        frame_poll_delay.pack(pady=(10, 0))
        poll_label = make_label("Image Poll Delay (ms):")
        poll_label.pack(in_=frame_poll_delay, side="left")
        Tooltip(poll_label, "How often to check for pips (in milliseconds).\nLower values update faster but use more CPU.\nDecrease if the macro accidentally rerolls on a suspend condition.")
        self.image_poll_delay_entry = Entry(frame_poll_delay, bg=entry_bg, fg=entry_fg, insertbackground='white', width=6)
        self.image_poll_delay_entry.pack(side="left", padx=(10, 0))
        self.image_poll_delay_entry.insert(0, str(self.image_poll_delay_ms))
        self.image_poll_delay_entry.bind('<KeyRelease>', self.update_image_poll_delay)

        frame_tol = tk.Frame(root, bg=bg)
        frame_tol.pack(pady=(10, 0))
        tol_label = make_label("Color Tolerance:")
        tol_label.pack(in_=frame_tol, side="left")
        Tooltip(tol_label, "How close a color must be to count as a match.\nIncrease if detection is unreliable.")
        self.tolerance_entry = Entry(frame_tol, bg=entry_bg, fg=entry_fg, insertbackground='white', width=6)
        self.tolerance_entry.pack(side="left", padx=(10, 0))
        self.tolerance_entry.insert(0, str(self.tolerance))
        self.tolerance_entry.bind('<KeyRelease>', self.update_tolerance)

        frame_obj_tol = tk.Frame(root, bg=bg)
        frame_obj_tol.pack(pady=(10, 0))
        obj_tol_label = make_label("Object Tolerance (px):")
        obj_tol_label.pack(in_=frame_obj_tol, side="left")
        Tooltip(obj_tol_label, "How close detected objects must be (in pixels) to be merged as one pip.\nIncrease if pips are split into multiple boxes.")
        self.object_tolerance_entry = Entry(frame_obj_tol, bg=entry_bg, fg=entry_fg, insertbackground='white', width=6)
        self.object_tolerance_entry.pack(side="left", padx=(10, 0))
        self.object_tolerance_entry.insert(0, str(self.object_tolerance))
        self.object_tolerance_entry.bind('<KeyRelease>', self.update_object_tolerance)

        frame_stop = tk.Frame(root, bg=bg)
        frame_stop.pack(pady=(10, 0))
        ss_label = tk.Label(frame_stop, text="Minimum SS:", fg=label_fg, bg=bg)
        ss_label.pack(side="left")
        Tooltip(ss_label, "Minimum number of SS-rank pips required to stop rerolling.")
        self.stop_at_entry = Entry(frame_stop, bg=entry_bg, fg=entry_fg, insertbackground='white', width=6)
        self.stop_at_entry.pack(side="left", padx=5)
        self.stop_at_entry.insert(0, str(self.stop_at_ss))
        self.stop_at_entry.bind('<KeyRelease>', self.update_stop_at)

        frame_minobjs = tk.Frame(root, bg=bg)
        frame_minobjs.pack(pady=(13, 0))
        minobjs_label = Label(frame_minobjs, text="Minimum Objects:", fg=label_fg, bg=bg)
        minobjs_label.pack(side="left")
        Tooltip(minobjs_label, "Minimum number of pips (of the selected quality or higher) required to stop rerolling.")
        self.min_objects_entry = Entry(frame_minobjs, bg=entry_bg, fg=entry_fg, insertbackground='white', width=6)
        self.min_objects_entry.pack(side="left", padx=(10,0))
        self.min_objects_entry.insert(0, str(self.min_objects))
        self.min_objects_entry.bind('<KeyRelease>', self.update_min_objects)

        # Minimum Quality row
        frame_quality = tk.Frame(root, bg=bg)
        frame_quality.pack(pady=(20, 0))
        min_quality_label = Label(
            frame_quality,
            text="Minimum Quality",
            fg=label_fg,
            bg=bg,
            font=("Arial", 12, "bold")
        )
        min_quality_label.pack()
        Tooltip(
            min_quality_label,
            "Select the lowest pip rank that you are willing to accept.\n"
            "Only pips of this quality or higher are considered for the stop condition."
        )

        self.quality_buttons = {}
        frame_buttons = tk.Frame(frame_quality, bg=bg)
        frame_buttons.pack(pady=(5, 0))
        for rank, _, _ in RANKS:
            btn = tk.Button(
                frame_buttons,
                text=rank,
                width=4,
                font=("Arial", 11, "bold"),
                relief="sunken" if rank == self.min_quality else "raised",
                bg=RANK_TK_HEX[rank] if rank == self.min_quality else "#333333",
                fg="#222222" if rank == self.min_quality else "#ffffff",
                activebackground=RANK_TK_HEX[rank],
                activeforeground="#222222",
                command=lambda r=rank: self.select_quality(r),
            )
            btn.pack(side="left", padx=3)
            self.quality_buttons[rank] = btn

        # Debugging: Rank counts row
        frame_rank_counts = tk.Frame(root, bg=bg)
        frame_rank_counts.pack(pady=(10, 0))
        # Top row: labels with rank names
        self.rank_labels = []
        for rank in RANK_TK_HEX:
            l = tk.Label(frame_rank_counts, text=rank, fg=RANK_TK_HEX[rank], bg=bg, font=("Arial", 11, "bold"))
            l.pack(side="left", padx=7)
            self.rank_labels.append(l)
        # Bottom row: StringVars with counts per rank
        frame_rank_counts2 = tk.Frame(root, bg=bg)
        frame_rank_counts2.pack()
        self.rank_count_vars = {}
        self.rank_count_labels = {}
        for rank in RANK_TK_HEX:
            v = StringVar(value="0")
            l = tk.Label(frame_rank_counts2, textvariable=v, fg=RANK_TK_HEX[rank], bg=bg, font=("Arial", 11))
            l.pack(side="left", padx=7)
            self.rank_count_vars[rank] = v
            self.rank_count_labels[rank] = l

        # Action Buttons
        btn_frame = tk.Frame(root, bg=bg)
        btn_frame.pack(pady=15)
        btn_opts = dict(bg=btn_bg, fg=btn_fg, width=18)
        tk.Button(btn_frame, text="Select Area", command=self.start_area_selection, **btn_opts).grid(row=0, column=0, padx=5, pady=pad_y)
        tk.Button(btn_frame, text="Set Chisel Button", command=self.start_chisel_button_selection, **btn_opts).grid(row=0, column=1, padx=5, pady=pad_y)
        tk.Button(btn_frame, text="Set Buy Button", command=self.start_buy_button_selection, **btn_opts).grid(row=1, column=0, padx=5, pady=pad_y)
        tk.Button(btn_frame, text="Start Preview", command=self.start_preview, **btn_opts).grid(row=1, column=1, padx=5, pady=pad_y)

        self.status_label = tk.Label(root, textvariable=self.status_var, fg=self.status_color,
                                     bg=bg, font=("Arial", 12, "bold"))
        self.status_label.pack(pady=(10, 0))

        self.message_label = tk.Label(root, textvariable=self.message_var,
                                      fg="#ff6666", bg=bg, font=("Arial", 10))
        self.message_label.pack()

        hotkey_label = tk.Label(root, text="Toggle Running: F5", fg="#888888", bg=bg, font=("Arial", 9))
        hotkey_label.pack(pady=(10, 5))

        # Keyboard listener
        self.listener = keyboard.Listener(on_press=self.on_key_press)
        self.listener.start()

        # AHK instance (default path to AutoHotkey.exe)
        print("App started")
        try:
            # Running from compiled executable
            # Nuitka inserts the __compiled__ global when building
            if "__compiled__" in globals():
                base_dir = os.path.dirname(os.path.abspath(__file__))
                ahk_path = os.path.abspath(os.path.join(base_dir, '..', 'assets', 'AutoHotkey.exe'))
                print("Resolved AHK path:", ahk_path)
                print("Exists:", os.path.exists(ahk_path))
                self.ahk = AHK(executable_path=ahk_path)
                print("AHK initialized successfully")
            else:
                # Running from source (assumes ahk[binary] installed or manually handled)
                self.ahk = AHK()
                print("AHK initialized in source mode")
        except Exception as e:
            print("Failed to initialize AHK:", e)

        # Ensure threads are cleanly stopped on app close
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        if ENABLE_LOGGING:
            def log_event(self, objects, rank_counts, settings, decision):
                """
                Logs a detection event with details about detected objects, counts, settings, and decisions.
            
                Each log entry includes a timestamp in UTC, the number of detected objects,
                their ranks and screen locations, the current rank counts, relevant settings,
                and the decision made by the application. Entries are appended to the internal
                log buffer.
            
                :param list[dict] objects: List of detected objects, each containing keys like 'rank' and 'rect' (bounding box).
                :param dict rank_counts: Dictionary mapping pip ranks to their counts at the time of logging.
                :param dict settings: Dictionary of current application settings relevant to the detection.
                :param str decision: Description of the decision or event that triggered the log entry.
                :rtype: None
                """
                import datetime
                if not objects:
                    return
                now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                total_objs = len(objects)
                obj_str = "; ".join(
                    f"{o['rank']}@({o['rect'][0]},{o['rect'][1]},{o['rect'][2]},{o['rect'][3]})"
                    for o in objects
                )
                counts_str = ", ".join(f"{rank}:{rank_counts[rank]}" for rank in rank_counts)
                settings_str = ", ".join(f"{k}={v}" for k, v in settings.items())
                log_line = (
                    f"{now} | Objects Detected: {total_objs} | Object Locations: {obj_str} | Counts: {counts_str} | "
                    f"Settings: {settings_str} | Decision: {decision}"
                )
                self.log_buffer.append(log_line)
        
            def dump_logs(self):
                """
                Writes all buffered log entries to a timestamped text file and clears the buffer.
            
                If no logs are present, updates the GUI message variable to indicate there are no logs to write.
                After successfully writing the logs, updates the message variable with the filename.
            
                The log file is saved in the current working directory with a name including the current date and time.
            
                :rtype: None
                """
                import datetime
                if not self.log_buffer:
                    self.message_var.set("No logs to write.")
                    return
                filename = f"auto_chiseler_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                with open(filename, "w", encoding="utf-8") as f:
                    for line in self.log_buffer:
                        f.write(line + "\n")
                self.message_var.set(f"Logs written to {filename}")
                self.log_buffer.clear()

            self.log_count_label = tk.Label(
                root, text="Logs ready to dump: 0", 
                bg=bg, fg="#ffcc00", font=("Arial", 9, "bold")
            )
            self.log_count_label.place(relx=1.0, y=5, anchor='ne')  # top right
        
            def update_log_count_label():
                """
                Periodically updates the GUI label displaying the number of logs currently buffered.
            
                This function schedules itself to run every 1000 milliseconds (1 second)
                to refresh the label text, reflecting the latest count of logs waiting to be written.
            
                :rtype: None
                """
                # Update label text with current number of logs in buffer
                count = len(self.log_buffer)
                self.log_count_label.config(text=f"Logs ready to dump: {count}")
        
                # Schedule to run again after 1000 ms (1 second)
                root.after(1000, update_log_count_label)
        
            # Start the periodic update loop
            update_log_count_label()
        
            # Attach methods to the instance
            self.log_event = log_event.__get__(self)
            self.dump_logs = dump_logs.__get__(self)
        
            # Show the log button
            self.log_button = tk.Button(
                root, text="DEBUG: Dump Logs", command=self.dump_logs,
                bg=bg, fg="#ffcc00", font=("Arial", 9, "bold")
            )
            self.log_button.place(x=5, y=5)
        else:
            self.log_event = lambda *a, **k: None

    def _on_closing(self):
        """
        Handle graceful shutdown when the application window is closed.
    
        This method stops background threads such as the image processor and keyboard listener,
        waits briefly for the image processor thread to finish, signals the main reroll loop to stop,
        and finally destroys the main Tkinter window.
    
        :rtype: None
        """
        self.stop_running_async() # Ensure main reroll loop stops
        if self.image_processor_thread and self.image_processor_thread.is_alive():
            self.image_processor_thread.stop() # Tell image processor to stop and cleanup
            self.image_processor_thread.join(timeout=1.0) # Wait for it to finish
        self.listener.stop() # Stop keyboard listener
        self.root.destroy()

    def select_quality(self, rank):
        """
        Update the selected minimum pip quality in the GUI.
        
        Adjusts the internal `min_quality` state and visually updates the quality selection buttons,
        highlighting the selected rank and resetting the others to default appearance.
        
        :param str rank: The rank string to select as the minimum quality (e.g., "F", "SS").
        :rtype: None
        """
        self.min_quality = rank
        for r, btn in self.quality_buttons.items():
            if r == rank:
                btn.config(relief="sunken", bg=RANK_TK_HEX[r], fg="#222222")
            else:
                btn.config(relief="raised", bg="#333333", fg="#ffffff")

    def update_tolerance(self, event=None):
        """
        Update the color tolerance value based on user input from the GUI.
        
        Reads the value from the tolerance entry widget, validates that it is an integer between 0 and 255,
        and updates the internal `tolerance` attribute accordingly. Invalid inputs are ignored.
        
        :param event: The event object from the GUI, not used in processing.
        :type event: tkinter.Event, optional
        :rtype: None
        """
        try:
            val = int(self.tolerance_entry.get())
            if 0 <= val <= 255:
                self.tolerance = val
        except ValueError:
            pass

    def update_stop_at(self, event=None):
        """
        Update the minimum SS-rank pip count required to stop rerolling based on GUI input.
        
        Reads the value from the stop_at entry widget, validates that it is a non-negative integer,
        and updates the internal `stop_at_ss` attribute accordingly. Invalid inputs are ignored.
        
        :param event: The event object from the GUI, not used in processing.
        :type event: tkinter.Event, optional
        :rtype: None
        """
        try:
            val = int(self.stop_at_entry.get())
            if val >= 0:
                self.stop_at_ss = val
        except ValueError:
            pass

    def update_min_objects(self, event=None):
        """
        Update the minimum number of objects required to stop rerolling from GUI input.
        
        Reads the value from the ``min_objects_entry`` widget, validates that it is an integer
        greater than or equal to 1, and updates the internal ``min_objects`` attribute.
        Invalid inputs are ignored.
        
        :param event: Event object from the GUI callback, not used.
        :type event: tkinter.Event, optional
        :rtype: None
        """
        try:
            val = int(self.min_objects_entry.get())
            if val >= 1:
                self.min_objects = val
        except ValueError:
            pass

    def update_click_delay(self, event=None):
        """
        Update the click delay (in milliseconds) from GUI input.
        
        Reads the value from the `click_delay_entry` widget, validates that it is a non-negative integer,
        and updates the internal `click_delay_ms` attribute.
        Invalid inputs are ignored.
        
        :param event: Event object from the GUI callback, not used.
        :type event: tkinter.Event, optional
        :rtype: None
        """
        try:
            val = int(self.click_delay_entry.get())
            if val >= 0:
                self.click_delay_ms = val
        except ValueError:
            pass

    def update_post_reroll_delay(self, event=None):
        """
        Update the post-reroll delay (in milliseconds) from GUI input.
        
        Reads the value from the `post_reroll_delay_entry` widget, validates that it is a non-negative integer,
        and updates the internal `post_reroll_delay_ms` attribute.
        Invalid inputs are ignored.
        
        :param event: Event object from the GUI callback, not used.
        :type event: tkinter.Event, optional
        :rtype: None
        """
        try:
            val = int(self.post_reroll_delay_entry.get())
            if val >= 0:
                self.post_reroll_delay_ms = val
        except ValueError:
            pass

    def update_image_poll_delay(self, event=None):
        """
        Update the image polling delay (in milliseconds) from GUI input.
        
        Reads the value from the ``image_poll_delay_entry`` widget, validates that it is a non-negative integer,
        and updates the internal ``image_poll_delay_ms`` attribute.
        Invalid inputs are ignored.
        
        :param event: Event object from the GUI callback, not used.
        :type event: tkinter.Event, optional
        :rtype: None
        """
        try:
            val = int(self.image_poll_delay_entry.get())
            if val >= 0:
                self.image_poll_delay_ms = val
        except ValueError:
            pass

    def update_object_tolerance(self, event=None):
        """
        Update the object merging tolerance (in pixels) from GUI input.
    
        Reads the value from the `object_tolerance_entry` widget, validates that it is a non-negative integer,
        and updates the internal `object_tolerance` attribute.
        Invalid inputs are ignored.
    
        :param event: Event object from the GUI callback, not used.
        :type event: tkinter.Event, optional
        :rtype: None
        """
        try:
            val = int(self.object_tolerance_entry.get())
            if val >= 0:
                self.object_tolerance = val
        except ValueError:
            pass

    def start_area_selection(self):
        """
        Initiate the screen area selection process for pip detection.
    
        Minimizes the main application window and creates a transparent, fullscreen overlay
        window with a crosshair cursor. This overlay captures mouse events to allow the user
        to drag and select a rectangular area of the screen for detection.
    
        :rtype: None
        """
        self.root.iconify() # Minimize main window
        self.selection_overlay = tk.Toplevel() # Create a transparent overlay window
        self.selection_overlay.attributes('-fullscreen', True, '-alpha', 0.2, '-topmost', True)
        self.selection_overlay.configure(bg='blue', cursor='crosshair')
        self.selection_rect = tk.Frame(self.selection_overlay, bg='red', highlightthickness=1,
                                     highlightbackground='white')
        self.selection_overlay.bind('<Button-1>', self.on_drag_start)
        self.selection_overlay.bind('<B1-Motion>', self.on_drag_motion)
        self.selection_overlay.bind('<ButtonRelease-1>', self.on_drag_end)

    def on_drag_start(self, event):
        """
        Handle the beginning of a mouse drag event during area selection.
        
        Records the initial cursor position in screen coordinates and places a minimal
        selection rectangle at the drag start location.
        
        :param event: The mouse button press event triggering the drag start.
        :type event: tkinter.Event
        :rtype: None
        """
        self.drag_start = (event.x_root, event.y_root)
        self.selection_rect.place(x=event.x, y=event.y, width=1, height=1)

    def on_drag_motion(self, event):
        """
        Handle mouse movement while dragging to select an area.
        
        Updates the size and position of the selection rectangle based on
        the current cursor position relative to the drag start point.
        
        :param event: The mouse motion event during the drag.
        :type event: tkinter.Event
        :rtype: None
        """
        x1, y1 = self.drag_start
        x2, y2 = event.x_root, event.y_root
        x, y = self.selection_overlay.winfo_rootx(), self.selection_overlay.winfo_rooty()
        self.selection_rect.place(x=min(x1, x2) - x, y=min(y1, y2) - y,
                                  width=abs(x1 - x2), height=abs(y1 - y2))

    def on_drag_end(self, event):
        """
        Handle the end of the drag event to finalize the selected screen area.
        
        Calculates the bounding box from the drag start and end coordinates,
        stores it in ``game_area``, destroys the overlay window, restores the main window,
        and updates the GUI message to confirm the selection.
        
        :param event: The mouse button release event signaling the end of the drag.
        :type event: tkinter.Event
        :rtype: None
        """
        x1, y1 = self.drag_start
        x2, y2 = event.x_root, event.y_root
        self.game_area = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        self.selection_overlay.destroy()
        self.root.deiconify() # Restore main window
        self.message_var.set("Game area set.")

    def start_chisel_button_selection(self):
        """
        Initiate the selection process for the 'Chisel' button position.
    
        Minimizes the main window and launches an overlay allowing the user to
        click and set the screen coordinates for the chisel button.
    
        :rtype: None
        """
        self._start_button_selection("chisel")

    def start_buy_button_selection(self):
        """
        Initiate the selection process for the 'Buy' button position.
    
        Minimizes the main window and launches an overlay allowing the user to
        click and set the screen coordinates for the buy button.
    
        :rtype: None
        """
        self._start_button_selection("buy")

    def _start_button_selection(self, button_type):
        """
        Helper method to create a fullscreen overlay for button position selection.
        
        The overlay is semi-transparent with a crosshair cursor and prompts the user
        to click to set either the "chisel" or "buy" button position, depending on the argument.
        
        :param button_type: The type of button to select, expected values are "chisel" or "buy".
        :type button_type: str
        :rtype: None
        """
        self.root.iconify()
        overlay = tk.Toplevel()
        overlay.attributes('-fullscreen', True, '-alpha', 0.3, '-topmost', True)
        overlay.configure(bg='purple' if button_type == "chisel" else 'darkgreen', cursor='crosshair')

        text = ("Click to set CHISEL BUTTON" if button_type == "chisel"
                else "Click to set BUY BUTTON")

        label = Label(overlay, text=text, font=("Arial", 20, "bold"),
                      bg=overlay['bg'], fg='white')
        label.pack(pady=100)

        overlay.bind('<Button-1>', lambda e: self.set_button_position(e, button_type, overlay))

    def set_button_position(self, event, button_type, overlay):
        """
        Set the screen coordinates for the specified button based on user click.
        
        Stores the (x_root, y_root) screen coordinates for the given button type,
        destroys the selection overlay, restores the main window, and updates the GUI message.
        
        :param event: The mouse click event containing the cursor position.
        :type event: tkinter.Event
        :param button_type: The button type being set, either "chisel" or "buy".
        :type button_type: str
        :param overlay: The overlay window used for selection, which will be destroyed.
        :type overlay: tkinter.Toplevel
        :rtype: None
        """
        pos = (event.x_root, event.y_root)
        if button_type == "chisel":
            self.chisel_button_pos = pos
        else:
            self.buy_button_pos = pos
        overlay.destroy()
        self.root.deiconify()
        self.message_var.set(f"{button_type.capitalize()} button set at {pos}")

    def on_key_press(self, key):
        """
        Handle keyboard key presses, toggling reroller on/off when F5 is pressed.
        
        If the F5 key is detected, starts the rerolling loop if it is not running,
        otherwise stops the running loop.
        
        :param key: The key event to handle.
        :type key: pynput.keyboard.Key
        :rtype: None
        """
        if key == keyboard.Key.f5:
            if not self.running:
                self.start_running_async()
            else:
                self.stop_running_async()

    def start_running_async(self):
        """
        Starts the reroller automation asynchronously.
    
        Validates that required settings (game area, chisel and buy button positions)
        are set, activates the target game window, clears stop signals, and
        launches background threads for image processing and the reroll loop.
    
        If any validation fails or the game window cannot be found, sets an appropriate
        error message in the GUI and aborts starting.
    
        :rtype: None
        """
        # --- Input validation ---
        if self.game_area is None:
            self.message_var.set("Please select area first.")
            return
        if self.chisel_button_pos is None:
            self.message_var.set("Please set Chisel Button first.")
            return
        if self.buy_button_pos is None:
            self.message_var.set("Please set Buy Button first.")
            return
        
        # --- Activate the game window (Crucial for reliable clicks) ---
        target_title = self.game_window_title.get()
        if not target_title:
            self.message_var.set("Please enter a Game Window Title.") # This logic is here if we ever decide to extend support for bootstrappers that might not have the same window title
            return

        if not self.ahk.win_exists(target_title):
            self.message_var.set(f"Error: Game window '{target_title}' not found. Please ensure it's open.")
            return
        
        self.ahk.win_activate(target_title)
        time.sleep(0.1) # Give the OS a moment to switch focus

        self.message_var.set("Game window activated. Starting reroll.")
        self.running = True
        self.update_status(True)
        
        # Call before starting any threads
        # This avoids very rare conditions where a race condition can happen where the thread could start immediately,
        # check the stop event, and mistakenly exit if it was still set from the last run.
        # We call it here in case the reroll loop starts without clearing the event first
        self.stop_reroll_event.clear() # Clear any previous stop signal for the reroll loop

        # Start the Image Processor thread if not already running
        if self.image_processor_thread is None or not self.image_processor_thread.is_alive():
            self.image_processor_thread = ImageProcessor(self)
            self.image_processor_thread.stop_event.clear() # Clear any previous stop signal
            self.image_processor_thread.start()
        
        # Start the Reroll Loop thread if not already running
        if self.reroll_loop_thread is None or not self.reroll_loop_thread.is_alive():
            self.reroll_loop_thread = threading.Thread(target=self.reroll_loop, daemon=True)
            self.reroll_loop_thread.start()

    def stop_running_async(self):
        """
        Signals all active automation threads to stop and updates GUI status.
    
        Sets the internal running flag to False, updates the GUI status label,
        sets the stop event for the reroll loop thread, and signals the image
        processor thread to stop if it is active.
    
        :rtype: None
        """
        self.running = False
        self.update_status(False)
        self.stop_reroll_event.set() # Signal the reroll loop to stop
        if self.image_processor_thread and self.image_processor_thread.is_alive():
            self.image_processor_thread.stop() # Signal the image processor to stop

    def update_status(self, running):
        """
        Update the status label in the GUI.
        
        Changes the status text and color based on whether the reroller is running.
        
        :param running: True if running, False if suspended.
        :type running: bool
        :rtype: None
        """
        if running:
            self.status_var.set("Status: Running")
            self.status_label.config(fg="#55ff55")
        else:
            self.status_var.set("Status: Suspended")
            self.status_label.config(fg="#ff5555")

    def update_rank_counts_gui(self, detected_objs):
        """
        Update the rank count display in the GUI.
    
        Called from the ImageProcessor thread via root.after() to safely update GUI elements.
        Updates internal counts and refreshes the Tkinter StringVars to reflect detected pip counts.
    
        :param detected_objs: List of detected pip objects with 'rank' keys.
        :type detected_objs: list
        :rtype: None
        """
        self.last_detected_objs = detected_objs # Store latest detected objects for logging
        # Reset counts for all ranks
        for rank in self.rank_count_vars:
            self.rank_counts[rank] = 0
        # Count detected objects by rank
        for obj in detected_objs:
            self.rank_counts[obj['rank']] += 1

        # Update Tkinter StringVars to refresh GUI labels
        for rank in self.rank_count_vars:
            self.rank_count_vars[rank].set(str(self.rank_counts[rank]))

    def start_preview(self):
        """
        Toggle the real-time bounding box preview window.
    
        Starts a background thread to capture and display pip detections live.
        If the preview is already active, stops it.
    
        :rtype: None
        """
        if self.game_area is None:
            self.message_var.set("Please select area first to start preview.")
            return
    
        if self.preview_active:
            self.preview_active = False
            # Do not call join() or destroyWindow here; let the thread clean up
            self.preview_thread = None
            return
    
        self.preview_active = True
        self.preview_thread = threading.Thread(target=self.preview_loop, daemon=True)
        self.preview_thread.start()

    def preview_loop(self):
        """
        Background loop for live preview of pip detection.
    
        Continuously captures screenshots of the game area, detects pips,
        draws bounding boxes with labels, and displays them in an OpenCV window.
        Runs until preview is deactivated.
    
        :rtype: None
        """
        preview_capturer = ScreenCapture()
        cv2.namedWindow("BBox Preview", cv2.WINDOW_AUTOSIZE)
        cv2.setWindowProperty("BBox Preview", cv2.WND_PROP_TOPMOST, 1)
    
        while self.preview_active:
            if self.game_area is None:
                time.sleep(0.05)
                continue
    
            frame = preview_capturer.capture(bbox=self.game_area)
            if frame is None:
                time.sleep(0.05)
                continue
    
            detected_objs = self.detect_and_classify(frame)
            # Update GUI rank counts safely on the main thread
            self.root.after(0, lambda objs=detected_objs: self.update_rank_counts_gui(objs))
    
            debug_frame = frame.copy()
            for obj in detected_objs:
                x, y, w, h = obj['rect']
                color = obj['cv2color']
                cv2.rectangle(debug_frame, (x, y), (x+w, y+h), color, 2)
                cv2.putText(debug_frame, obj['rank'], (x+2, y+18), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
            cv2.imshow("BBox Preview", debug_frame)
            # Use a very short waitKey and check preview_active frequently
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.preview_active = False
                break
            time.sleep(0.01)  # Small sleep to reduce CPU usage
    
        cv2.destroyAllWindows()
        preview_capturer.close()

    def detect_and_classify(self, frame):
        """
        Detect and classify pip objects within an image frame.
    
        Processes the input frame by applying color masks for each rank,
        performs morphological operations to clean the mask,
        detects contours, filters by area, merges close rectangles,
        and returns a sorted list of detected pip objects with their rank and bounding box.
    
        :param frame: The image frame to process (BGR color).
        :type frame: numpy.ndarray
        :returns: List of detected objects, each a dict with keys 'rank', 'rect', and 'cv2color'.
        :rtype: list of dict
        """
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        detected = []
        for rank, bgr, _ in RANKS:
            mask = self.rank_mask(frame, np.array(bgr), self.tolerance)
            # Apply morphological closing to connect nearby pixels and fill small gaps
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            # Filter contours by area to remove noise and get bounding rectangles
            rects = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > 1]
            # Merge overlapping or close rectangles
            merged_rects = self.merge_rectangles(rects, self.object_tolerance)
            for rect in merged_rects:
                detected.append({
                    "rank": rank,
                    "rect": rect,
                    "cv2color": bgr
                })
        # Sort detected objects by rank order (highest rank first)
        detected.sort(key=lambda o: -RANK_ORDER[o['rank']])
        return detected

    def rank_mask(self, frame, color_bgr, tolerance):
        """
        Create a binary mask of pixels within color tolerance of a target BGR color.
    
        Computes a mask where pixels in the frame are within the specified tolerance
        of the target color, across all BGR channels.
    
        :param frame: The image frame (BGR).
        :type frame: numpy.ndarray
        :param color_bgr: Target BGR color as a NumPy array.
        :type color_bgr: numpy.ndarray
        :param tolerance: Maximum allowed absolute difference per channel.
        :type tolerance: int
        :returns: Binary mask image with 255 where pixels match, 0 elsewhere.
        :rtype: numpy.ndarray
        """
        # Calculate absolute difference between frame pixels and target color
        diff = np.abs(frame.astype(np.int16) - color_bgr)
        # Create mask where all color channels are within tolerance
        mask = np.all(diff <= tolerance, axis=2).astype(np.uint8) * 255
        return mask

    def merge_rectangles(self, rects, max_distance):
        """
        Merge rectangles that are close to each other into combined bounding boxes.
    
        Useful for merging fragmented detections of the same object by expanding bounding boxes
        that are within the specified max_distance of each other.
    
        :param rects: List of rectangles as (x, y, w, h) tuples.
        :type rects: list of tuples
        :param max_distance: Maximum distance between rectangles to consider merging.
        :type max_distance: float
        :returns: List of merged rectangles as (x, y, w, h) tuples.
        :rtype: list of tuples
        """
        merged = []
        used = [False] * len(rects)

        def rect_distance(r1, r2):
            """
            Calculate the shortest Euclidean distance between the edges of two rectangles.
        
            Each rectangle is defined as (x, y, width, height). The distance is zero if the rectangles overlap
            or touch. Otherwise, it returns the straight-line distance between the closest edges.
        
            :param r1: First rectangle (x, y, w, h).
            :type r1: tuple
            :param r2: Second rectangle (x, y, w, h).
            :type r2: tuple
            :returns: Euclidean distance between closest points of the rectangles.
            :rtype: float
            """
            x1, y1, w1, h1 = r1
            x2, y2, w2, h2 = r2

            # Determine horizontal distance
            left = x2 + w2 < x1
            right = x1 + w1 < x2
            dx = 0
            if right:
                dx = x2 - (x1 + w1)
            elif left:
                dx = x1 - (x2 + w2)

            # Determine vertical distance
            above = y2 + h2 < y1
            below = y1 + h1 < y2
            dy = 0
            if below:
                dy = y2 - (y1 + h1)
            elif above:
                dy = y1 - (y2 + h2)
            
            # Return hypotenuse (closest distance)
            return np.hypot(dx, dy)

        for i, r in enumerate(rects):
            if used[i]:
                continue # Skip if already merged

            x, y, w, h = r
            # Initialize merged_rect with current rectangle's bounds (min_x, min_y, max_x, max_y)
            merged_rect = [x, y, x + w, y + h]
            used[i] = True

            # Iterate through remaining rectangles to find merge candidates
            for j in range(i + 1, len(rects)):
                if used[j]:
                    continue
                dist = rect_distance(r, rects[j])
                if dist <= max_distance:
                    # If close enough, expand merged_rect to include rects[j]
                    rx, ry, rw, rh = rects[j]
                    merged_rect[0] = min(merged_rect[0], rx)
                    merged_rect[1] = min(merged_rect[1], ry)
                    merged_rect[2] = max(merged_rect[2], rx + rw)
                    merged_rect[3] = max(merged_rect[3], ry + rh)
                    used[j] = True # Mark as used

            # Add the final merged rectangle (convert back to x, y, w, h format)
            merged.append((merged_rect[0], merged_rect[1],
                           merged_rect[2] - merged_rect[0],
                           merged_rect[3] - merged_rect[1]))
        return merged

    def click_at(self, x, y):
        """Simulates a mouse click at the specified screen coordinates using AutoHotkey (AHK).
    
        Moves the mouse instantly to (x, y) and performs a left-click (down and up).
        
        :param x: The x-coordinate on the screen.
        :type x: int
        :param y: The y-coordinate on the screen.
        :type y: int
        """
        self.ahk.mouse_move(x, y, speed=0)  # Instant move
        # Moving the cursor again when it is inside the client area
        # makes Roblox consider it inside the game client
        # Otherwise it might not register the click properly
        self.ahk.mouse_move(0, -1, relative=True, speed=0)  # Nudge up 1px
        self.ahk.click()

    def reroll_loop(self):
        """
        Main automation loop for performing the reroll clicks with responsiveness to stop signals.
    
        This loop continuously performs the following steps until a stop event is signaled:
        - Checks for a stop event to exit early.
        - Logs detected objects if logging is enabled.
        - Clicks the 'Chisel' button and waits a configured delay.
        - Checks for stop event again to allow immediate cancellation.
        - Clicks the 'Buy' button and waits a configured delay.
        - Checks for stop event again.
        - Waits a post-reroll delay to prevent game state glitches.
        - Updates the GUI message with the current detected pip counts.
        - Waits briefly to throttle the loop and let image processing catch up.
    
        The function uses thread-safe event waits to react quickly to stop signals from other threads.

        :rtype: None
        """
        if ENABLE_DISCORD_RPC:
            import app.discord_rpc as discord_rpc
            discord_rpc.init()

        ss_count = 0
        filtered_count = 0

        while not self.stop_reroll_event.is_set():   
            # Brief pause before the next iteration, to prevent clicking too fast
            # and allow the image processor to catch up if needed
            # Also to prevent the reroller from rerolling if a stop condition is already met
            time.sleep(0.01) # This is a general loop delay, not a click delay
            # Check if image processor has signaled a stop.
            # We wait with a short timeout to allow responsiveness.
            # If stop_reroll_event is set by ImageProcessor, this will immediately unblock.
            if self.stop_reroll_event.wait(timeout=0.01): # Wait for 10ms
                break # Exit the loop if stop is signaled

            # --- LOGGING: Only log if objects detected and logging is enabled ---
            min_rank_idx = RANK_ORDER[self.min_quality]
            detected_objs = getattr(self, "last_detected_objs", [])
            filtered_objs = [obj for obj in detected_objs if RANK_ORDER[obj["rank"]] >= min_rank_idx]
            if ENABLE_LOGGING and detected_objs:
                self.log_event(
                    detected_objs,
                    self.image_processor_thread.get_current_rank_counts(),
                    {
                        "min_quality": self.min_quality,
                        "min_objects": self.min_objects,
                        "stop_at_ss": self.stop_at_ss,
                        "tolerance": self.tolerance,
                        "object_tolerance": self.object_tolerance,
                        "click_delay_ms": self.click_delay_ms,
                        "post_reroll_delay": self.post_reroll_delay_ms,
                        "image_poll_delay_ms": self.image_poll_delay_ms,
                        "game_area": self.game_area,
                        "chisel_button_pos": self.chisel_button_pos,
                        "buy_button_pos": self.buy_button_pos,
                    },
                    decision="Rolling"
                )

            # If not stopped, perform the reroll clicks
            self.click_at(*self.chisel_button_pos)
            time.sleep(self.click_delay_ms / 1000) # Delay after first click
            
            # Re-check stop condition after the first click for immediate reaction
            if self.stop_reroll_event.wait(timeout=0.01):
                break

            self.click_at(*self.buy_button_pos)
            time.sleep(self.click_delay_ms / 1000) # Delay after second click
            
            # Re-check stop condition after the second click
            if self.stop_reroll_event.wait(timeout=0.01):
                break

            # Post-click safety delay
            # Prevents inventory shift issue where the charm below moves up temporarily.
            # This delay gives the game time to fully update/return the charm slot.
            time.sleep(self.post_reroll_delay_ms / 1000)

            current_counts = self.image_processor_thread.get_current_rank_counts()
            ss_count = current_counts.get("SS", 0)
            filtered_count = sum(
                count for rank, count in current_counts.items()
                if RANK_ORDER[rank] >= min_rank_idx
            )

            # Update message on the main thread
            self.root.after(0, lambda: self.message_var.set(
                f"Detected: {filtered_count} ≥{self.min_quality}" +
                (f", {ss_count} SS" if self.stop_at_ss > 0 else "") +
                ". Rolling..."
            ))

            # Update Discord RPC live status
            if ENABLE_DISCORD_RPC:
                discord_rpc.update(
                    min_quality=self.min_quality,
                    min_objects=self.min_objects,
                    ss_count=ss_count,
                    stop_at_ss=self.stop_at_ss,
                    rolling=True
                )

        current_counts = self.image_processor_thread.get_current_rank_counts()
        ss_count = current_counts.get("SS", 0)

        if ENABLE_DISCORD_RPC:
            # Determine if we stopped due to satisfying a condition
            stopped_from_condition = (
                (self.min_objects > 0 and filtered_count >= self.min_objects) or
                (self.stop_at_ss > 0 and ss_count >= self.stop_at_ss)
            )

            discord_rpc.update(
                min_quality=self.min_quality,
                min_objects=self.min_objects,
                ss_count=ss_count,
                stop_at_ss=self.stop_at_ss,
                rolling=False,
                stopped_from_condition=stopped_from_condition
            )