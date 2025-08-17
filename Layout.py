import tkinter 		     as tk
import matplotlib.pyplot as plt
from matplotlib.figure 				   import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL 							   import Image, ImageTk
from ThreadMain import *

def logoUDG(screen_width, screen_height):
    image = Image.open("Escudo_UdeG.svg")  # Cargar Imágenes
    width, height = int(screen_height * .08), int(screen_height * .10)  # Ajustardimensiones
    image = image.resize((width, height))
    return image
def logoCUCEI(screen_width, screen_height):
    image = Image.open("CUCEI.svg")  # Cargar Imágenes
    width, height = int(screen_height * .08), int(screen_height * .10)  # Ajustardimensiones
    image = image.resize((width, height))
    return image
def TrackingImage(screen_width, screen_height):
    image = Image.open("BodyTracking.png")  # Cargar Imágenes
    width, height = int(screen_width * .20), int(screen_height * .28)  # Ajustardimensiones
    image = image.resize((width, height))
    return image
def PressureImage(screen_width, screen_height):
    image = Image.open("Pressure.png")  # Cargar Imágenes
    width, height = int(screen_width * .20), int(screen_height * .28)  # Ajustardimensiones
    image = image.resize((width, height))
    return image
def EMGImage(screen_width, screen_height):
    image = Image.open("EMG.png")  # Cargar Imágenes
    width, height = int(screen_width * .20), int(screen_height * .28)  # Ajustardimensiones
    image = image.resize((width, height))
    return image

class App(tk.Tk):
    def __init__(self, master):
#         super().__init__()
        self.master = master
        #Se obtienen las dimensiones de la pantalla para ajustar la aplicación
        screen_width = self.master.winfo_screenwidth()
        screen_height = self.master.winfo_screenheight()
        size = str(screen_width) + "x" + str(screen_height)
        #Configuración Inicial
        self.master.title('Proyecto Modular')
        self.master.geometry(size)
        self.Encabezado(screen_height,screen_width)
        self.ImagenesPortada(screen_height,screen_width)
        self.TextoPortada(screen_height, screen_width)
        self.BotonInicio(screen_height, screen_width)
    def Encabezado(self, screen_height,screen_width):
        #Encabezado de la interfaz
        self.FondoSuperior = tk.Canvas(bg = "#0066FF",height=screen_height*.11,width = screen_width,  master=self.master)

        self.UDG = ImageTk.PhotoImage(logoUDG(screen_width,screen_height),  master=self.master)
        self.FondoSuperior.create_image(10, 5, anchor=tk.NW, image=self.UDG)

        self.CUCEI = ImageTk.PhotoImage(logoCUCEI(screen_width,screen_height),  master=self.master)
        self.FondoSuperior.create_image(screen_width-self.CUCEI.width()-10, 5, anchor=tk.NW, image=self.CUCEI)

        # Agregar texto centrado en el Canvas
        texto = "Monitoreo en Tiempo Real del Centro de Presión, Ángulo Articular y EMG Abdominal para Diagnóstico de Patologías Posturales"
        x_texto = self.FondoSuperior.winfo_reqwidth() // 2  # Centro horizontal
        y_texto = self.FondoSuperior.winfo_reqheight() // 2  # Centro vertical
        self.FondoSuperior.create_text(x_texto, y_texto, text= texto, font=("Helvetica", int(screen_width/90)), fill="white")

        self.FondoSuperior.pack()
        #Imagenes
    def ImagenesPortada(self,screen_height,screen_width):
        self.Imagenes = tk.Canvas(height = int(screen_height * .30), width = screen_width,master=self.master)
        self.BodyTrackingImage = ImageTk.PhotoImage(TrackingImage(screen_width,screen_height))
        self.PressureImagen = ImageTk.PhotoImage(PressureImage(screen_width, screen_height))
        self.EMGImagen = ImageTk.PhotoImage(EMGImage(screen_width, screen_height))

        self.Imagenes.create_image(int(screen_width*.1), 5, anchor = tk.NW, image = self.BodyTrackingImage)
        self.Imagenes.create_image(int(screen_width * .4), 5, anchor = tk.NW, image = self.PressureImagen)
        self.Imagenes.create_image(int(screen_width * .7), 5, anchor = tk.NW, image = self.EMGImagen)
        self.Imagenes.pack()
    def TextoPortada(self, screen_height, screen_width):
        self.Info = tk.Label(self.master, width = screen_width,text = "Universidad de Guadalajara\n Centro Universitario de Ciencias Exactas e Ingenierías\n División de Tecnologías para la Integración Ciber-Humana\n Ingeniería Biomédica",font=("Helvetica", int(screen_width/90)))
        self.Info.pack(fill = 'x')
        texto = "Integrantes:\nHernández Gómez Óscar Iván \t 215468521\tINBI\nQuintero Valdez José Rodrigo     \t 219747166\tINBI\nVelasco López José Carlos        \t 219747093\tINBI\n\nAsesores:\nÁlvarez Padilla Francisco Javier \t Departamento de Bioingeniería Traslacional\nDe la Torre Valdovinos Braniff \t Departamento de Bioingeniería Traslacional"
        self.Integrantes = tk.Label(self.master, text = texto,font=("Helvetica", int(screen_width/100)),justify="left",pady = int(screen_height*.05))
        self.Integrantes.pack()
    def BotonInicio(self, screen_height, screen_width):
        self.BotonIniciar = tk.Button(self.master,text = "INICIAR",relief = tk.GROOVE,fg = "White",bg = "#00FF44",font=("Helvetica", int(screen_width/100)),command=lambda:self.BotonIniciarPresionado(screen_height,screen_width))
        self.BotonIniciar.pack()
    def BotonIniciarPresionado(self, screen_height, screen_width):
        # Obtain global var for figures
        State_MainLay = True
        
        widgets_to_hide = [self.Imagenes, self.Info, self.Integrantes, self.BotonIniciar]
        for widget in widgets_to_hide:
            widget.pack_forget()
        self.create_subplots(screen_height, screen_width)
            
        # Inicializate threads
#         FP_acquisition.start()
        EMG_acquisition.start()
#         BD_acquisition.start()
        #Timer.start()
        i = 1
        # Make Plot
        while True:
#             self.ax[0,1].plot(i,i,'o')
#             i = i+1
            try:
                emg_data, State_MainLay = update_plot(State_MainLay)
            except:
                pass
            self.ax0.set_data(range(len(emg_data)), emg_data)
            self.ax[0,0].relim()  # Actualiza los límites del eje y
            self.ax[0,0].autoscale_view()  # Ajusta automáticamente los límites del eje x
            plt.pause(0.01)  # Actualiza el gráfico cada 10 ms
            self.canvas.draw()
#             app.update()
            print(State_MainLay)
            if State_MainLay == False:
                break

        # Waiting for the ending of threads
        EMG_acquisition.join()
#         FP_acquisition.join()
#         BD_acquisition.join()
        #Timer.join()
        
    def create_subplots(self, screen_height, screen_width):
        # Create a figure and subplots
        self.fig, self.ax  = plt.subplots(nrows=2, ncols=2)
        #= Figure(figsize=(canvas_width/100, canvas_height/100), tight_layout=True)
        #fig_canvas = FigureCanvasTkAgg(fig)
#         self.fig.suptitle("Main Figure Title", fontsize= 12)
#         self.emgax = self.fig.add_subplot(2, 2, 1)
#         fopax = self.fig.add_subplot(2, 2, 2)
#         bptax = self.fig.add_subplot(2, 2, 3)
#         angax = self.fig.add_subplot(2, 2, 4)
        # Plot some sample data on the subplots (replace this with your actual data)
        self.ax0, = self.ax[0,0].plot([], [])
        self.ax1, = self.ax[0,1].plot([], [], 'o', markersize=10)
        self.ax2, = self.ax[1,0].plot([], [])
        self.ax3, = self.ax[1,1].plot([], [])
        
        self.ax[0,0].set_ylim(0, 5)
        self.ax[0,0].set_xlabel("Tiempo")
        self.ax[0,0].set_ylabel("Valor del EMG")

#         emgax.set_title("Subplot 1")
#         fopax.set_title("Subplot 2")
#         bptax.set_title("Subplot 3")
#         angax.set_title("Subplot 4")

        # Embed the matplotlib figure in the Tkinter window
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.master)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(pady = int(screen_height*.05))
        plt.ion()
        #app.update()
        #subplot4.plot([1, 2, 3], [10, 11, 12])

def main():
    root = tk.Tk()
    app  = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()



