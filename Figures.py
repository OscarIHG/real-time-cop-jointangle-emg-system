import pandas               as pd
import matplotlib.pyplot    as plt
from   matplotlib.animation import FuncAnimation

def createfigs():
    # Figure
    plt.style.use('dark_background')

    # Get on the interactive mode
    plt.ion()

    # Create a figure and an axis for the scatter plot
    fig1, ax1 = plt.subplots(figsize=(8.8, 6.4))
    fig2, ax2 = plt.subplots()

    # Scatter plot
    scatter, = ax1.plot([], [], 'o', markersize=10)
    linea,   = ax2.plot([], [])

    # Set axes limits  
    ax1.set_xlim(-27.94, 27.94)  # Adjust the X-axis limits to a specific range
    ax1.set_ylim(-20.32, 20.32)  # Adjust the Y-axis limits to a specific range
    ax2.set_ylim(0, 5)

    # Set the title of the plot
    ax1.set_title("Real Time Center of Pressure", loc='center', fontdict={'fontsize': 12})

    # Set labels for the X and Y axes
    ax1.set_xlabel("X Distance (centimeters)", fontdict={'fontsize': 10})
    ax1.set_ylabel("Y Distance (centimeters)", fontdict={'fontsize': 10})

    # Set tick locations for the Y and X axes
    ax1.set_yticks([-20.32, 0, 20.32])
    ax1.set_xticks([-27.94, 0, 27.94])

    # Set the aspect ratio to ensure correct scaling of the plot
    ratio = 16/22  # Ratio of width to height for the plot
    x_left, x_right = ax1.get_xlim()
    y_low, y_high = ax1.get_ylim()
    ax1.set_aspect(abs((x_right - x_left) / (y_low - y_high)) * ratio)

    # Add a grid to the plot
    ax1.grid()
    
    return fig1, fig2, ax1, ax2, scatter, linea


# Function that saves the Center of Pressure data obtained in X and Y formats as .csv and .txt.
def save_file():

    # Check if there are data to save
    if not copap or not copml:
        print("No data to save.")
        return

    # Create DataFrame
    data = {'COPX': copap, 'COPY': copml, 'Weight - KG': kg_total}
    df = pd.DataFrame(data)

    # Ask the user if they want to save the data
    while True:
        save_option = input("Do you want to save the data? (Yes/No): ").strip().lower()
        if save_option == 'yes' or save_option == 'y':
            break
        elif save_option == 'no' or save_option == 'n':
            return
        else:
            print("Invalid option. Please respond 'Yes' or 'No'.")

    # Ask the user in which format they want to save the data
    while True:
        format_option = input("In which format do you want to save the data? (CSV/TXT/Both): ").strip().lower()
        if format_option == 'csv':
            name_csv = input("CSV file name: ")
            name_csv += ".csv"
            df.to_csv(name_csv, index=False)
            print(f"Data saved in '{name_csv}'")
            break
        elif format_option == 'txt':
            name_txt = input("TXT file name: ")
            name_txt += ".txt"
            df.to_csv(name_txt, sep=' ', index=False)
            print(f"Data saved in '{name_txt}'")
            break
        elif format_option == 'both':
            name_csv = input("CSV file name: ")
            name_csv += ".csv"
            df.to_csv(name_csv, index=False)
            print(f"Data saved in '{name_csv}'")
            name_txt = input("TXT file name: ")
            name_txt += ".txt"
            df.to_csv(name_txt, sep=' ', index=False)
            print(f"Data saved in '{name_txt}'")
            break
        else:
            print("Invalid option. Please respond 'CSV', 'TXT', or 'Both'.")


