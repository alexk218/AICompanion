import requests
import time
import serial
import json
from datetime import datetime
import tkinter as tk
from PIL import Image, ImageTk, ImageEnhance, ImageFilter
import io
import os
import threading
from dotenv import load_dotenv
from itertools import cycle

load_dotenv()

# Setup serial connection (adjust port name as per your setup, commonly /dev/ttyACM0 or /dev/ttyUSB0)
ser = serial.Serial('/dev/serial0', 9600, timeout=1)  # Adjust this line for your setup
ser.flush()  # clear any data that might be in the buffer
schedules_file = 'medication_schedules.json'

USER_ID = os.getenv("USER_ID") # alexkepekci@hotmail.com on Cluster0


flag_path = "wake_flag.txt" 
desired_saturation_level = 1  # Start with normal saturation
current_saturation_level = 1


# GUI setup
os.environ['DISPLAY'] = ':0' # set DISPLAY environment variable to default display
root = tk.Tk()
root.attributes('-fullscreen', True)
root.title("MedMate")

background_image_path = '/home/capstone/projects/AICompanion/background.jpg'
screen_width = 1024
screen_height = 600
# screen_width = 1920
# screen_height = 1080

img_label = tk.Label(root)
img_label.pack(fill='both', expand=True)
# img_label.place(x=0, y=0, width=screen_width, height=screen_height - 100)  # Adjust size for the medication image


# text_label = tk.Label(root, text="Waiting...", font=('Arial', 12), bg='white')
text_label = tk.Label(root, font=('Arial', 30), bg='white')
# text_label.place(x=0, y=screen_height - 100, width=screen_width, height=100)  # Place text label at the bottom

# text_label.pack()
# img_label.pack(fill='both', expand=True)  # Make the label fill the entire window

def display_background_image():
    # Displays the background image.
    try:
        image = Image.open(background_image_path)
        image = image.resize((screen_width, screen_height))

        photo = ImageTk.PhotoImage(image, master=root)
        img_label.config(image=photo)
        img_label.image = photo  # Keep a reference
        text_label.pack_forget()  # Hide the text label when showing the background
    except Exception as e:
        print(f"Error loading background image: {e}")

display_background_image()

# fetches medication schedules from database, prints schedule details and pill details
def fetch_medication_schedules():
   try:
       response = requests.get(f'https://medmate-15e14a1b2dec.herokuapp.com/api/getMedicationSchedules?userId={USER_ID}')
       if response.status_code == 200:
           schedules = response.json()
           # process the schedules
           print("Fetched schedules:")
           # loop over all medication schedules
           for schedule in schedules:
               schedule_type = schedule.get('scheduleType', 'daily')  # Default to 'daily' if not provided
               schedule_days = ', '.join(schedule.get('scheduleDays', []))  # Join the days with a comma

               schedule_info = f"Pill Name: {schedule['pillName']}, Compartment: {schedule['pillCompartment']}, Quantity: {schedule['pillQuantity']}, Time to dispense: {schedule['pillTime']}, Schedule Type: {schedule_type}"

               if schedule_days:
                   schedule_info += f", Days: {schedule_days}"

               print(schedule_info,"-", fetch_medication_details(schedule['pillName']))

               # print(f"Pill Details: {fetch_medication_details(schedule['pillName'])}")
               # open 'medication_schedules.json' file in write mode
               with open(schedules_file, 'w') as file:
                   json.dump(schedules, file)  # write json data to the file
       else:
           print("Failed to fetch schedules")
   except Exception as e:
       print("Error:", e)

# fetches medication details associated with a medication in the schedule. returns details for that medication.
def fetch_medication_details(medication_name):
   try:
       response = requests.get(f'https://medmate-15e14a1b2dec.herokuapp.com/api/medicationDetails?name={medication_name}')
       if response.status_code == 200:
           details = response.json()
           return f"Color: {details['color']}"
       else:
           print(f"Failed to fetch details for {medication_name}")
           return None
   except Exception as e:
       print(f"Error fetching details for {medication_name}: {e}")
       return None

def fetch_medication_image(medication_name):
    try:
        # Adjust the URL to match the endpoint's expected URL pattern
        response = requests.get(f'https://medmate-15e14a1b2dec.herokuapp.com/medicationImage/{medication_name}')

        if response.status_code == 200:
            # The response content is binary data of the image
            image_data = response.content
            display_image(image_data)
        else:
            display_message(f"No image found for {medication_name}")
    except Exception as e:
        display_message(f"Error fetching image for {medication_name}: {e}")

def display_image(image_data):
    """Displays the medication image, replacing the background image."""
    try:
        image = Image.open(io.BytesIO(image_data))
        image = image.resize((screen_width - 100, screen_height - 100))
        photo = ImageTk.PhotoImage(image, master=root)
        img_label.config(image=photo)
        img_label.image = photo  # Keep a reference
        text_label.pack(side='bottom')  # Show the text label at the bottom
    except Exception as e:
        print(f"Error displaying medication image: {e}")

def display_message(message):
    text_label.config(text=message)

# at pill dispension time, send signal to begin navigation
def check_and_navigate():
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")  # Current time in HH:MM format
    current_day_str = now.strftime("%A").lower()  # Current day in lowercase (e.g., 'monday')
    print(current_time_str, current_day_str)

    schedules = read_schedules()
    for schedule in schedules:
        pill_time_str = schedule['pillTime']  # Expected in HH:MM format
        schedule_type = schedule.get('scheduleType', 'daily')
        compartment = schedule['pillCompartment']
        quantity = schedule['pillQuantity']
        pillName = schedule['pillName']

        pillColor = fetch_medication_details(pillName)

        if schedule_type == 'daily' and current_time_str == pill_time_str:
            write_dispensing_details(quantity, pillName, pill_time_str)
            send_navigation_signal(compartment, quantity)
            root.after(1000, fetch_medication_image(pillName))
            message = f"Currently dispensing {pillName}. {pillColor}"
            display_message(message)
           
        elif schedule_type == 'custom':
            schedule_days = schedule.get('scheduleDays', [])
            if current_day_str in schedule_days and current_time_str == pill_time_str:
                write_dispensing_details(quantity, pillName, pill_time_str)
                send_navigation_signal(compartment, quantity)
                root.after(1000, fetch_medication_image(pillName))
                message = f"Currently dispensing {pillName}. {pillColor}"
                display_message(message)

# write dispensing details to a file. fed into AI companion during pill dispensing times
def write_dispensing_details(quantity, pillName, pillTime):
    dispensing_details = {
        'quantity': quantity,
        'pillName': pillName,
        'pillTime': pillTime
    }
    with open('dispensing_details.json', 'w') as f:
        json.dump(dispensing_details, f)


def read_schedules():
   with open(schedules_file, 'r') as file:
       return json.load(file)

def send_navigation_signal(compartment, quantity):
    command = f"NAVIGATE,{compartment},{quantity}\n"
    print(f"Sending command to Arduino: {command.strip()}")
    ser.write(command.encode('utf-8'))

def periodically_fetch_medication_schedules():
    fetch_medication_schedules()
    # Schedule this function to run again after 15 seconds (15000 milliseconds)
    root.after(5000, periodically_fetch_medication_schedules)

def periodically_check_and_navigate():
    check_and_navigate()
    # Schedule this function to run again after 15 seconds (15000 milliseconds)
    root.after(5000, periodically_check_and_navigate)

def send_sig():
   print("connected to: " + ser.portstr)
   command_to_send = "NAVIGATE,1,1\n"
   ser.flush()
   ser.write(command_to_send.encode('utf-8'))
   print("Command sent successfully.")

def close(event):
    root.destroy()


def check_listening_flag():
    if os.path.exists(flag_path):
        with open(flag_path, "r") as f:
            if f.read().strip() == "detected":
                print("Listening, updating GUI...")
                initiate_smooth_transition(3.5)  # Example: Reduce saturation
                # reset_flag()
            else:
                print("Not listening, updating GUI...")
                initiate_smooth_transition(1)
    root.after(100, check_listening_flag)


def initiate_smooth_transition(final_saturation):
    global desired_saturation_level
    desired_saturation_level = final_saturation
    # The actual transition will be handled by another function that checks this variable

def update_image_saturation():
    global current_saturation_level, desired_saturation_level
    transition_speed = 1.5  # Control how fast the saturation changes per update

    # Calculate the difference between the current and desired saturation levels
    saturation_difference = desired_saturation_level - current_saturation_level

    # If the difference is significant enough, adjust the current saturation level towards the desired level
    if abs(saturation_difference) > transition_speed:
        current_saturation_level += transition_speed if saturation_difference > 0 else -transition_speed
    else:
        # If the difference is within the threshold, set the current saturation to the desired level directly
        current_saturation_level = desired_saturation_level
    
    # Adjust the image saturation using the current saturation level
    original_image = Image.open(background_image_path).resize((screen_width, screen_height))
    adjusted_image = adjust_saturation(original_image, current_saturation_level)
    photo = ImageTk.PhotoImage(adjusted_image, master=root)
    img_label.config(image=photo)
    img_label.image = photo

    # Re-schedule this function to run again after a short delay for continuous checks
    root.after(3, update_image_saturation)

def adjust_saturation(image, saturation_level):
    """
    Adjusts the saturation of an image.
    :param image: PIL.Image object
    :param saturation_level: Saturation multiplier where 1 is unchanged, <1 is less saturated, and >1 is more saturated
    :return: PIL.Image object with adjusted saturation
    """
    enhancer = ImageEnhance.Color(image)
    return enhancer.enhance(saturation_level)


# Bind the Escape key to the close function
root.bind('<Escape>', close)


# Initialize the periodic tasks
root.after(1000, periodically_fetch_medication_schedules)
root.after(1000, periodically_check_and_navigate)
root.after(5, check_listening_flag)  # Initial check, subsequent checks are scheduled by the function itself

# root.after(1000, send_sig)

update_image_saturation()  # Add this before root.mainloop()


# Start the Tkinter event loop; this should be the last line in your script
root.mainloop()





'''
def update_image_saturation():
    global current_saturation_level, desired_saturation_level, is_listening, original_image

    # Ensure the original_image is loaded outside of this function or make sure it's updated only once.
    original_image = Image.open(background_image_path).resize((screen_width, screen_height))

    # Adjust the image saturation using the current saturation level
    adjusted_image = adjust_saturation(original_image, current_saturation_level)

    # Apply a glow effect if the system is in the listening state
    if is_listening:
        adjusted_image = apply_glow_effect(adjusted_image, border_size=5, glow_color=(61, 90, 235), glow_intensity=100)
    
    # Calculate the difference between the current and desired saturation levels
    saturation_difference = desired_saturation_level - current_saturation_level

    # Adjust the current saturation level towards the desired level
    if abs(saturation_difference) > 0.05:
        current_saturation_level += (desired_saturation_level - current_saturation_level) * 0.1

    # Update the image on the GUI
    photo = ImageTk.PhotoImage(adjusted_image, master=root)
    img_label.config(image=photo)
    img_label.image = photo

    # Re-schedule this function for continuous checks
    root.after(5, update_image_saturation)
'''

'''
def apply_glow_effect(image, border_size=10, glow_color=(0, 255, 255), glow_intensity=5):
    """
    Applies a glowing border effect to the image.
    
    :param image: The original PIL image.
    :param border_size: Thickness of the glow effect.
    :param glow_color: Color of the glow as an RGB tuple.
    :param glow_intensity: Intensity of the glow effect.
    :return: Image with applied glow effect.
    """
    # Create a new image with a border
    new_size = (image.width + border_size * 2, image.height + border_size * 2)
    bordered_image = Image.new("RGB", new_size, glow_color)
    bordered_image.paste(image, (border_size, border_size))
    
    # Apply a blur to the border
    blurred_image = bordered_image.filter(ImageFilter.GaussianBlur(border_size / glow_intensity))
    
    return blurred_image
'''
'''
def pulse_brightness_effect():
    """
    Gradually adjusts the brightness of the background image to create a pulse effect.
    """
    global current_brightness_factor
    
    # Define a sequence of brightness factors to create the pulsing effect
    brightness_sequence = cycle([0.99, 1.0, 1.01, 1.0])

    def update_brightness():
        global current_brightness_factor
        try:
            # Get the next brightness factor from the sequence
            current_brightness_factor = next(brightness_sequence)
            
            # Adjust the image brightness
            enhancer = ImageEnhance.Brightness(original_image)
            adjusted_image = enhancer.enhance(current_brightness_factor)
            photo = ImageTk.PhotoImage(adjusted_image, master=root)
            img_label.config(image=photo)
            img_label.image = photo  # Keep a reference!

            # Schedule the next update
            root.after(30, update_brightness)
        
        except StopIteration:
            return

    # Start the pulsing effect
    update_brightness()

# Example usage
original_image = Image.open(background_image_path).resize((screen_width, screen_height))

pulse_brightness_effect()
'''








