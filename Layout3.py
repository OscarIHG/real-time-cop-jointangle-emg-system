import tkinter              as tk
import matplotlib.pyplot    as plt
import matplotlib.animation as animation
import time            
from matplotlib.figure    import Figure
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
        self.State_MainLay = False
        
        # Delete button from window
        widgets_to_hide = [self.Imagenes, self.Info, self.Inte, self.ObjBotonIn]
        for widget in widgets_to_hide:
            widget.pack_forget()

        # Call function to create multiplots
        self.create_subplots(screen_width, screen_height)
                
        # Total frames
        self.iteration = 1000
        
        # Create animations
        self.aniEMG  = animation.FuncAnimation(
            self.fig,
            self.update_aniEMG,
            interval = 3,
            frames   = self.iteration,
            repeat   = True)
        self.aniFP   = animation.FuncAnimation(
            self.fig,
            self.update_aniFP,
            interval = 3,
            frames   = self.iteration,
            repeat   = True)
        
        # Inicializate Modules
        self.inicializateEMG()
        self.inicializateFP()
        
        # Star animations
        self.aniEMG._start()
        self.aniFP._start()
        self.master.after(20000, self.stop_animation)
    
    def create_subplots(self, screen_width, screen_height):
        # Create a figure and subplots
        self.fig, self.ax  = plt.subplots(nrows=2, ncols=2)
        
        # Plot some sample data on the subplots
        self.ax0, = self.ax[0,0].plot([], [])
        self.ax1, = self.ax[0,1].plot([], [], 'o', markersize=10)
        self.ax2, = self.ax[1,0].plot([], [])
        self.ax3, = self.ax[1,1].plot([], [])
        
        # Set initial config for EMG plot
        self.ax[0,0].set_ylim(0, 5)
        self.ax[0,0].set_xlabel("Tiempo")
        self.ax[0,0].set_ylabel("Valor del EMG")
        
        # Set initial config for FP plot
        self.ax[0,1].set_xlim(-27.94, 27.94)  # Adjust the X-axis limits to a specific range
        self.ax[0,1].set_ylim(-20.32, 20.32)  # Adjust the Y-axis limits to a specific range
        self.ax[0,1].set_title("Real Time Center of Pressure", loc='center', fontdict={'fontsize': 12})
        self.ax[0,1].set_xlabel("X Distance (centimeters)", fontdict={'fontsize': 10})
        self.ax[0,1].set_ylabel("Y Distance (centimeters)", fontdict={'fontsize': 10})
        self.ax[0,1].set_yticks([-20.32, 0, 20.32])
        self.ax[0,1].set_xticks([-27.94, 0, 27.94])
        self.ax[0,1].grid()
        
        # Embed the matplotlib figure in the Tkinter window
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.master)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side = tk.TOP, fill=tk.BOTH, expand=1)
        
        
    def update_aniEMG(self, frame):
        try:
            emg_data = acquisitionEMG(self.socket, self.fm)
            self.ax0.set_data(range(len(emg_data)), emg_data)
            self.ax[0,0].relim()  # Actualiza los límites del eje y
            self.ax[0,0].autoscale_view()  # Ajusta automáticamente los límites del eje x
            self.canvas.draw()
        except:
            if self.State_MainLay:
                self.aniEMG.event_source.stop()  # Detiene la animación
        return self.ax0,
    
    def update_aniFP(self, frame):
        try:
            self.ax1.set_data([copap[-1]], [-copml[-1]])
        except: 
            if self.State_MainLay:
                self.aniFP.event_source.stop()  # Detiene la animación
        return self.ax1,  # Return the 'scatter' object as a tuple
    
    def stop_animation(self):
        self.State_MainLay = True
        # Finalize EMG Module
        print('Socket bluetooth close')
        self.socket.send("2")
        time.sleep(1) 
        self.socket.close()
        print('EMG adquicision ends')
        
        # Finalize PF Module
        self.ch0.close()
        print('CH0 close')
        self.ch1.close()
        print('CH1 close')
        self.ch2.close()
        print('CH2 close')
        self.ch3.close()
        print('CH3 close')
        print('PF adquicision ends')
        
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
    
    def inicializateEMG(self):
        print('EMG adquisicion started')
            
        # Call fm, for gettin frequency of EMG
        self.socket, self.fm   = getfm(esp32_address)
        print('EMG Frequency: ', self.fm)
        
    def inicializateFP(self):
        self.ch0, self.ch1, self.ch2, self.ch3 = createCH()        
    
    
root = tk.Tk()
app  = App(root)
root.mainloop()