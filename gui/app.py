import tkinter as tk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image, ImageTk


def load_image(path: str, width_ratio: float, screen_width: int, master: tk.Widget | None = None) -> ImageTk.PhotoImage:
    """Load an image from *path* and resize it using *width_ratio* of the screen width.

    Parameters
    ----------
    path: str
        Location of the image file.
    width_ratio: float
        Percentage of the screen width the image should take (0-1).
    screen_width: int
        Width of the screen in pixels.
    master: tk.Widget | None
        Tkinter master widget for the resulting PhotoImage.

    Returns
    -------
    ImageTk.PhotoImage
        The resized image ready to be used in Tkinter widgets.
    """
    image = Image.open(path)
    width = int(screen_width * width_ratio)
    original_width, original_height = image.size
    height = int(width * original_height / original_width)
    image = image.resize((width, height))
    return ImageTk.PhotoImage(image, master=master)


def create_header(master: tk.Widget, screen_width: int, screen_height: int):
    """Create the header canvas with logos and title."""
    canvas = tk.Canvas(master=master, bg="#0066FF", height=screen_height * 0.11, width=screen_width)
    udg_logo = load_image("Escudo_UdeG.svg", 0.07, screen_width, master)
    cucei_logo = load_image("CUCEI.svg", 0.07, screen_width, master)
    canvas.create_image(10, 5, anchor=tk.NW, image=udg_logo)
    canvas.create_image(screen_width - cucei_logo.width() - 10, 5, anchor=tk.NW, image=cucei_logo)

    text = (
        "Monitoreo en Tiempo Real del Centro de Presión, Ángulo Articular y EMG Abdominal para Diagnóstico de Patologías Posturales"
    )
    x_text = canvas.winfo_reqwidth() // 2
    y_text = canvas.winfo_reqheight() // 2
    canvas.create_text(x_text, y_text, text=text, font=("Helvetica", int(screen_width / 90)), fill="white")
    canvas.pack()
    return canvas, udg_logo, cucei_logo


def create_intro_images(master: tk.Widget, screen_height: int, screen_width: int):
    """Create canvas with introductory images."""
    canvas = tk.Canvas(master=master, height=int(screen_height * 0.30), width=screen_width)
    tracking = load_image("BodyTracking.png", 0.20, screen_width, master)
    pressure = load_image("Pressure.png", 0.20, screen_width, master)
    emg = load_image("EMG.png", 0.20, screen_width, master)
    canvas.create_image(int(screen_width * 0.1), 5, anchor=tk.NW, image=tracking)
    canvas.create_image(int(screen_width * 0.4), 5, anchor=tk.NW, image=pressure)
    canvas.create_image(int(screen_width * 0.7), 5, anchor=tk.NW, image=emg)
    canvas.pack()
    return canvas, tracking, pressure, emg


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

        # Header and logos
        self.header, self.udg_logo, self.cucei_logo = create_header(master, screen_width, screen_height)

        # Introductory images and labels
        self.images_canvas, self.img_tracking, self.img_pressure, self.img_emg = create_intro_images(
            master, screen_height, screen_width
        )

        info_text = (
            "Universidad de Guadalajara\n Centro Universitario de Ciencias Exactas e Ingenierías\n"
            " División de Tecnologías para la Integración Ciber-Humana\n Ingeniería Biomédica"
        )
        self.info = tk.Label(master, width=screen_width, text=info_text, font=("Helvetica", int(screen_width / 90)))
        self.info.pack(fill="x")

        members_text = (
            "Integrantes:\nHernández Gómez Óscar Iván\t215468521\tINBI\n"
            "Quintero Valdez José Rodrigo\t219747166\tINBI\n"
            "Velasco López José Carlos\t219747093\tINBI\n\n"
            "Asesores:\nÁlvarez Padilla Francisco Javier\tDepartamento de Bioingeniería Traslacional\n"
            "De la Torre Valdovinos Braniff\tDepartamento de Bioingeniería Traslacional"
        )
        self.members = tk.Label(
            master,
            text=members_text,
            font=("Helvetica", int(screen_width / 100)),
            justify="left",
            pady=int(screen_height * 0.05),
        )
        self.members.pack()

        self.start_button = tk.Button(
            master,
            text="INICIAR",
            relief=tk.GROOVE,
            fg="White",
            bg="#00FF44",
            font=("Helvetica", int(screen_width / 100)),
            command=lambda: self.start(screen_width, screen_height),
        )
        self.start_button.pack()

    def start(self, screen_width: int, screen_height: int):
        """Handle start button: hide intro widgets and show subplots."""
        for widget in (self.images_canvas, self.info, self.members, self.start_button):
            widget.pack_forget()

        self.fig, self.ax, self.canvas = create_subplots(self.master)
        self.emg_line, = self.ax[0, 0].plot([], [])
        self.ax[0, 0].set_ylim(0, 5)
        self.ax[0, 0].set_xlabel("Tiempo")
        self.ax[0, 0].set_ylabel("Valor del EMG")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
