import tkinter as tk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


def create_control_bar(master: tk.Widget):
    """Create the top control bar with length, start/stop and save options."""
    frame = tk.Frame(master)
    tk.Label(frame, text="Enter recording length in seconds:").pack(side=tk.LEFT, padx=5)
    length_entry = tk.Entry(frame, width=8)
    length_entry.pack(side=tk.LEFT)
    start_button = tk.Button(frame, text="Start")
    start_button.pack(side=tk.LEFT, padx=5)
    tk.Label(frame, text="Filename:").pack(side=tk.LEFT, padx=(20, 5))
    filename_entry = tk.Entry(frame, width=15)
    filename_entry.pack(side=tk.LEFT)
    save_button = tk.Button(frame, text="Save")
    save_button.pack(side=tk.LEFT, padx=5)
    frame.pack(fill="x", padx=10, pady=5)
    return length_entry, start_button, filename_entry, save_button


def create_subplots(master: tk.Widget):
    """Create a matplotlib figure embedded in Tkinter with four subplots."""
    fig, ax = plt.subplots(nrows=2, ncols=2)
    canvas = FigureCanvasTkAgg(fig, master=master)
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)
    return fig, ax, canvas


class App:
    """Main application window."""

    def __init__(self, master: tk.Tk):
        self.master = master
        self.master.title("Proyecto Modular")

        screen_width = master.winfo_screenwidth()
        screen_height = master.winfo_screenheight()
        master.geometry(f"{screen_width}x{screen_height}")

        # Controls
        (
            self.length_entry,
            self.start_button,
            self.filename_entry,
            self.save_button,
        ) = create_control_bar(master)
        self.start_button.config(command=self.toggle_start)
        self.save_button.config(command=self.save_figure)
        self.running = False

        # Subplots
        self.fig, self.ax, self.canvas = create_subplots(master)
        self.emg_line, = self.ax[0, 0].plot([], [])
        self.ax[0, 0].set_title("Abdominal EMG")
        self.ax[0, 0].set_xlim(0, 400)  # expand as sample count grows
        self.ax[0, 0].set_ylim(1, 5)

        self.cop_point, = self.ax[0, 1].plot([], [], "o")
        self.ax[0, 1].set_title("Center of Pressure")
        self.ax[0, 1].set_xlim(-20.32, 20.32)
        self.ax[0, 1].set_ylim(-27.94, 27.94)

        self.body_line, = self.ax[1, 0].plot([], [])
        self.ax[1, 0].set_title("Body-Tracking")
        self.ax[1, 0].set_xlim(0, 600)
        self.ax[1, 0].set_ylim(0, 400)

        self.joint_line, = self.ax[1, 1].plot([], [])
        self.ax[1, 1].set_title("Joint Angle")
        self.ax[1, 1].set_xlim(0, 35)
        self.ax[1, 1].set_ylim(40, -40)

    def toggle_start(self):
        """Toggle between start and stop states."""
        self.running = not self.running
        self.start_button.config(text="Stop" if self.running else "Start")

    def save_figure(self):
        """Save the current figure using the filename entry."""
        name = self.filename_entry.get() or "figure"
        self.fig.savefig(f"{name}.png")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
