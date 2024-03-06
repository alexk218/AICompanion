import requests
import time
import serial
import json
from datetime import datetime

# Setup serial connection (adjust port name as per your setup, commonly /dev/ttyACM0 or /dev/ttyUSB0)
# ser = serial.Serial('COM3', 9600, timeout=1)
# ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)  # Adjust this line for your setup
# ser.flush()  # clear any data that might be in the buffer
schedules_file = 'medication_schedules.json'

USER_ID = "65c59de165c7d5f0fd7f60d0"  # alexkepekci@hotmail.com

# fetches medication schedules from database, prints schedule details and pill details
def fetch_medication_schedules():
    try:
        #response = requests.get(f'http://localhost:5000/api/getMedicationSchedules?userId={"65c59de165c7d5f0fd7f60d0"}')
        response = requests.get(f'http://192.168.2.34:5000/api/getMedicationSchedules?userId={"65c59de165c7d5f0fd7f60d0"}')
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

                print(schedule_info)
                print(f"Pill Details: {fetch_medication_details(schedule['pillName'])}")
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
        response = requests.get(f'http://192.168.2.34:5000/api/medicationDetails?name={medication_name}')
        if response.status_code == 200:
            details = response.json()
            return f"Color: {details['color']}"
        else:
            print(f"Failed to fetch details for {medication_name}")
            return None
    except Exception as e:
        print(f"Error fetching details for {medication_name}: {e}")
        return None

# at pill dispension time, send signal to begin navigation
def check_and_navigate():
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")  # Current time in HH:MM format
    current_day_str = now.strftime("%A").lower()  # Current day in lowercase (e.g., 'monday')

    schedules = read_schedules()
    for schedule in schedules:
        pill_time_str = schedule['pillTime']  # Expected in HH:MM format
        schedule_type = schedule.get('scheduleType', 'daily')
        compartment = schedule['pillCompartment']

        if schedule_type == 'daily' and current_time_str == pill_time_str:
            send_navigation_signal(compartment)
        elif schedule_type == 'custom':
            schedule_days = schedule.get('scheduleDays', [])
            if current_day_str in schedule_days and current_time_str == pill_time_str:
                send_navigation_signal(compartment)

def read_schedules():
    with open(schedules_file, 'r') as file:
        return json.load(file)

def send_navigation_signal(compartment):
    command = f"NAVIGATE,{compartment}\n"
    print(f"Sending command to Arduino: {command.strip()}")
   # ser.write(b'NAVIGATE')

while True:
    fetch_medication_schedules()
    check_and_navigate()
    time.sleep(30)  # poll every 30 secs