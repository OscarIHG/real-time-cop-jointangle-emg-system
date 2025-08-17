import tkinter           as tk
import matplotlib.pyplot as plt
import time            
from matplotlib.figure    import Figure
from matplotlib.animation import FuncAnimation
from PIL                  import Image, ImageTk
from ThreadMain           import *
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Create class for APP
class App:
    def __init__(self,master):
        # Master is an object window
        self.master = master
        # Title of window
        self.master.title('Proyecto Modular')
        # Get size of window
        screen_width  = self.master.winfo_screenwidth()  
        screen_height = self.master.winfo_screenheight()
        size          = str(screen_width) + 'x' + str(screen_height)
        self.master.geometry(size)
        # Call function to create elements
        self.logoUDG(screen_width)
        self.logoCUCEI(screen_width)
        self.TrackingImage(screen_width)
        self.PressureImage(screen_width)
        self.EMGImage(screen_width)
        
        # Call function to put elements on the window
        self.Encabezado(screen_height,screen_width)
        self.ImagenesPortada(screen_height,screen_width)
        self.TextoPortada(screen_height, screen_width)
        self.BotonInicio(screen_height, screen_width)
        
    def BotonInicio(self, screen_height, screen_width):
        self.ObjBotonIn = tk.Button(self.master,text = "INICIAR",relief = tk.GROOVE,fg = "White",bg = "#00FF44",font=("Helvetica", int(screen_width/100)),command=lambda:self.BotonIniciarPresionado(screen_height,screen_width))
        self.ObjBotonIn.pack()
        
    def BotonIniciarPresionado(self, screen_height, screen_width):
        # Obtain global var for figures
        State_MainLay = True
        
        # Delete button from window
        widgets_to_hide = [self.Imagenes, self.Info, self.Inte, self.ObjBotonIn]
        for widget in widgets_to_hide:
            widget.pack_forget()

        # Call function to create multiplots
        self.create_subplots(screen_width, screen_height)
        i = 1
        while True:
            self.update_plots(i)
            i = .2+i
        
    
    def create_subplots(self, screen_width, screen_height):
        # Create a figure and subplots
        self.fig, self.ax  = plt.subplots(nrows=2, ncols=2)
        # Plot some sample data on the subplots
        self.ax0, = self.ax[0,0].plot([], [],'o')
        self.ax1, = self.ax[0,1].plot([], [], 'o', markersize=10)
        self.ax2, = self.ax[1,0].plot([], [])
        self.ax3, = self.ax[1,1].plot([], [])
        # Set initial config for EMG plot
        self.ax[0,0].set_ylim(0, 5)
        self.ax[0,0].set_xlabel("Tiempo")
        self.ax[0,0].set_ylabel("Valor del EMG")
        
        # Embed the matplotlib figure in the Tkinter window
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.master)
        self.canvas.get_tk_widget().pack(side = tk.TOP, fill=tk.BOTH, expand=1)
        self.canvas.draw()
        
        # Activate Interactive plot mood
        plt.ion()
        
    def update_plots(self, i):
        self.ax0.set_data(range(1), [i])
        self.canvas.draw()
        self.master.after(1, lambda: self.update_plots(i)) 
    
    # Element: IMGs for APP
    def logoUDG(self, screen_width):
        # Load IMG
        image = Image.open("Escudo_UdeG.svg")
        porc  = .07
        image = self.rsize(image, porc, screen_width)
        self.image01 = ImageTk.PhotoImage(image)
        
    def logoCUCEI(self, screen_width):
        image = Image.open("CUCEI.svg") 
        porc  = .07
        image = self.rsize(image, porc, screen_width)
        self.image02 = ImageTk.PhotoImage(image)
        
    def TrackingImage(self, screen_width):
        image = Image.open("BodyTracking.png")  # Cargar Imágenes
        porc  = .20
        image = self.rsize(image, porc, screen_width)
        self.image03 = ImageTk.PhotoImage(image)
        
    def PressureImage(self, screen_width):
        image = Image.open("Pressure.png")  # Cargar Imágenes
        porc  = .20
        image = self.rsize(image, porc, screen_width)
        self.image04 = ImageTk.PhotoImage(image)
        
    def EMGImage(self, screen_width):
        image = Image.open("EMG.png")  # Cargar la imagen
        porc  = .20
        image = self.rsize(image, porc, screen_width)
        self.image05 = ImageTk.PhotoImage(image)
    
    # Function to modify img
    def rsize(self,image, porc, screen_width):
        # Get size from the IMG
        widthIMG, heightIMG = image.size
        r = widthIMG/heightIMG
        # Get size for the IMG
        width, height = int(screen_width*porc*r), int(screen_width*porc)  # Ajustardimensiones
        # Resize the Image to fit in the canvas
        image = image.resize((width, height))
        # Return IMG to the class
        return image
    
    # Elements: Texts for APP
    def Encabezado(self, screen_height,screen_width):
        # Create Header
        self.FondoSuperior = tk.Canvas(bg = "#0066FF",height=screen_height*.11,width = screen_width,  master=self.master)
        # Put Images 01 & 02 on header
        self.FondoSuperior.create_image(10, 5, anchor=tk.NW, image=self.image01)
        self.FondoSuperior.create_image(screen_width-self.image02.width()-10, 5, anchor=tk.NW, image=self.image02)
        # Create higher text var
        texto = "Monitoreo en Tiempo Real del Centro de Presión, Ángulo Articular y EMG Abdominal para Diagnóstico de Patologías Posturales"
        # Center higher text
        x_texto = self.FondoSuperior.winfo_reqwidth()  // 2
        y_texto = self.FondoSuperior.winfo_reqheight() // 2
        # Put text on canvas
        self.FondoSuperior.create_text(x_texto, y_texto, text= texto, font=("Helvetica", int(screen_width/87)), fill="white")
        self.FondoSuperior.pack()

    def ImagenesPortada(self,screen_height,screen_width):
        # Create canvas for images 03,04 y 05
        self.Imagenes = tk.Canvas(height = int(screen_height * .30), width = screen_width,master=self.master)
        # Put Img 03, 04 & 05 on canvas
        self.Imagenes.create_image(int(screen_width * .1), 5, anchor = tk.NW, image = self.image03)
        self.Imagenes.create_image(int(screen_width * .4), 5, anchor = tk.NW, image = self.image04)
        self.Imagenes.create_image(int(screen_width * .7), 5, anchor = tk.NW, image = self.image05)
        self.Imagenes.pack()
        
    def TextoPortada(self, screen_height, screen_width):
        # Create text Info
        info  = "Universidad de Guadalajara\n Centro Universitario de Ciencias Exactas e Ingenierías\n División de Tecnologías para la Integración Ciber-Humana\n Ingeniería Biomédica"
        inte = "Integrantes:\nHernández Gómez Óscar Iván \t 215468521\tINBI\nQuintero Valdez José Rodrigo     \t 219747166\tINBI\nVelasco López José Carlos        \t 219747093\tINBI\n\nAsesores:\nÁlvarez Padilla Francisco Javier \t Departamento de Bioingeniería Traslacional\nDe la Torre Valdovinos Braniff \t Departamento de Bioingeniería Traslacional"
        # Put texts on canvas
        self.Info = tk.Label(self.master, width = screen_width, text = info,font=("Helvetica", int(screen_width/90)))
        self.Inte = tk.Label(self.master, text = inte,font=("Helvetica", int(screen_width/100)),justify="left",pady = int(screen_height*.05))
        self.Info.pack(fill = 'x')
        self.Inte.pack()
    
root = tk.Tk()
app  = App(root)
root.mainloop()