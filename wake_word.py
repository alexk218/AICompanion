import os
import pvporcupine
import pyaudio
import struct
from gtts import gTTS
import speech_recognition as sr
import openai
from dotenv import load_dotenv
import time
import requests
import uuid
from datetime import datetime
import pytz
from google.cloud import dialogflow
from google.oauth2 import service_account
import random
from flask import Flask, request, jsonify
import json
import subprocess

load_dotenv()

# initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=openai.api_key)

# initialize OpenWeatherAPI and Porcupine key
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
PORCUPINE_KEY = os.getenv("PORCUPINE_KEY")
KEYWORD_FILE_PATH = os.getenv("KEYWORD_FILE_PATH")

# file for saving user's name
user_name_file = 'user_name.txt'

# System prompt and conversation history
character_prompt = 'Answer precise and short with a hint of charming sarcasm, maximum of 2 sentences!'
history = [{'role': 'system', 'content': character_prompt}]

# Speech recognizer and microphone
recognizer = sr.Recognizer()
microphone = sr.Microphone()

# create a Flask application
app = Flask(__name__)

service_account_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
credentials = service_account.Credentials.from_service_account_file(service_account_path)
session_client = dialogflow.SessionsClient(
   credentials=credentials)  # Explicitly set the credentials when initializing your client


@app.route('/webhook', methods=['POST'])
def webhook():
   # retrieve the JSON data sent to the Flask app's /webhook endpoint.
   # force=True tells Flask to ignore the content type of the request and attempt to parse the body as JSON regardless (even if 'Content-Type' header is not set to 'application/json')
   req = request.get_json(force=True)
   session = req.get('session')  # Extract session ID from the request
   intent_name = req.get('queryResult').get('intent').get(
       'displayName')  # extract name of the intent identified by Dialogflow from the JSON request.


   parameters = req.get('queryResult').get('parameters',
                                           {})  # Extract parameters. If doesn't exist, default to an empty dictionary.
   date_time = parameters.get('date-time')  # This can be None if not provided
   city = parameters.get('geo-city')
   # When city is not provided, geo-city might not be in parameters or could be an empty list
   if not city:
       city = 'Montreal'  # Default city
   else:
       city = city[0] if isinstance(city, list) else city  # Extract city from list if necessary


   person_param = parameters.get('person', {})
   if isinstance(person_param, list):
       # If it's a list, concatenate the name parts.
       user_name = ' '.join([name_part.get('name', '') for name_part in person_param])
       print("isList", user_name)
   else:
       user_name = person_param.get('name')
       print("isNotList", user_name)


   if intent_name == 'WeatherQuery':
       weather_response = get_weather(city, date_time)
       # converts the weather_response string to a JSON response expected by Dialogflow.
       return jsonify({
           "fulfillmentMessages": [{
               "text": {
                   "text": [weather_response]
               }
           }]
       })


   if intent_name == 'RobotNameQuery':
       return jsonify({})  # Respond with the robot's name. Dialogflow handles the responses for this intent


   if intent_name == 'CaptureName' and user_name:
       # save_user_name(user_name)
       print(user_name)
       user_captured_response = [f"Got it! I'll remember that your name is {user_name}.",
                                 f"Alrighty {user_name}! Understood.",
                                 f"Sounds good, {user_name}!",
                                 f"{user_name}, {user_name}, {user_name}, I will never forget.",
                                 f"Oky doky {user_name}.",
                                 f"What a coincidence, {user_name} is my favourite name. Got it."]
       selected_response = random.choice(user_captured_response)
       # print(selected_response)
       output_contexts = [{
           "name": f"{session}/contexts/awaiting_name_confirmation",
           "lifespanCount": 1,
           "parameters": {"person": user_name}
       }]
       confirm_response = f"Are you sure you want me to call you {user_name} from now on?"
       return jsonify({
           "fulfillmentMessages": [{
               "text": {
                   "text": [confirm_response]
               }
           }],
           "outputContexts": output_contexts  # Make sure to include this in your response
       })
   if intent_name in ['ConfirmYes', 'ConfirmYesSpeakingStyle']:
       # Extract username from the awaiting_name_confirmation context parameters
       for context in req.get('queryResult', {}).get('outputContexts', []):
           if context.get('name').endswith('awaiting_name_confirmation'):
               user_name = context.get('parameters', {}).get('person')
               save_user_name(user_name)  # Save the username
               response_message = f"Got it! I'll remember that your name is {user_name}."
               # Clear the awaiting_name_confirmation context by setting its lifespan to 0
               output_contexts = [{
                   "name": f"{session}/contexts/awaiting_name_confirmation",
                   "lifespanCount": 0
               }]
               break
       else:
           response_message = "Sorry, I couldn't find the name to save."
           output_contexts = []


       return jsonify({
           "fulfillmentMessages": [{
               "text": {"text": [response_message]}
           }],
           "outputContexts": output_contexts
       })

   if intent_name == 'GreetingIntent':
       user_name = load_user_name() or "there"  # Use a default name if not found
       print("user_name:", user_name)
       greeting_response = [f"Hello {user_name}, how can I help you today?",
                            f"Howdy, {user_name}!",
                            f"Hey there {user_name}!",
                            f"Hi {user_name}, what's up?",
                            f"What do you want {user_name}."]
       selected_response = random.choice(greeting_response)
       print(selected_response)
       return jsonify({
           "fulfillmentMessages": [{
               "text": {
                   "text": [selected_response]
               }
           }]
       })


   return jsonify({"fulfillmentText": "Sorry, I couldn't understand that."})


# API STUFF
def get_weather(city='Montreal', date_time=None):
   # Use geocoding to get latitude and longitude for the city (This is an additional step for One Call API)
   GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/direct"
   geocoding_params = {
       "q": city,
       "limit": 1,
       "appid": OPENWEATHER_API_KEY,
   }
   geocoding_response = requests.get(GEOCODING_URL, params=geocoding_params)
   geocoding_data = geocoding_response.json()
   print(f"Geocoding response: {json.dumps(geocoding_data, ensure_ascii=False).encode('utf-8')}")
  # print(f"Geocoding response: {geocoding_data}")


   if geocoding_response.status_code == 200 and geocoding_data:
       lat = geocoding_data[0]['lat']
       lon = geocoding_data[0]['lon']
       if lat is None or lon is None:
           return f"I couldn't find the specific location you're asking about. Can you specify a city?"


       # Now, use lat and lon for the One Call API
       URL = "https://api.openweathermap.org/data/3.0/onecall"
       params = {
           "lat": lat,
           "lon": lon,
           # "exclude": "minutely,hourly,daily,alerts",
           "exclude": "minutely, hourly, alerts",
           "units": "metric",
           "appid": OPENWEATHER_API_KEY,
       }
       response = requests.get(URL, params=params)
       data = response.json()


       if response.status_code == 200:
           print("date_time: ", date_time)
           if not date_time:
               # Handle current weather (if an exact time isn't specified)
               current_weather = data['current']
               weather_description = current_weather['weather'][0]['description']
               temperature = current_weather['temp']
               rounded_temp = round(temperature)
               weather_response = f"Currently in {city}, it's {weather_description} with a temperature of {rounded_temp}°C."


           else:
               try:
                   # parses a string representing a date in the format YYYY-MM-DD by slicing the first 10 chars from the date_time string
                   # ex: date_time:  2024-03-06T12:00:00-05:00  => date_requested:  2024-03-06
                   date_requested = datetime.strptime(date_time[:10], "%Y-%m-%d").date()
                   today = datetime.now(pytz.timezone('America/New_York')).date()


                   print("date_requested: ", date_requested)
                   print("today: ", today)


                   delta_days = (date_requested - today).days
                   print("delta_days:", delta_days)


                   if delta_days < 0:
                       # If user asks for past dates.
                       # Define a list of possible responses for past dates
                       past_date_responses = [
                           "Weather forecasts for past dates are not available, sorry.",
                           "I can't look back in time, unfortunately.",
                           "Sorry, I don't have information for past weather."
                       ]
                       # Select a random response
                       weather_response = random.choice(past_date_responses)
                   elif delta_days == 1:
                       date_text = "Tomorrow"
                       # Fetch future weather from daily forecast
                       future_weather = data['daily'][delta_days]
                       print(
                           future_weather)  # this shows all the weather data fetched. maybe use this to show more stuff? 'summary', 'min', 'max'?
                       weather_description = future_weather['weather'][0]['description']
                       temp_day = future_weather['temp']['day']
                       rounded_temp = round(temp_day)
                       weather_response = f"{date_text}, the weather in {city} will be {weather_description} with a daytime temperature of {rounded_temp}°C."
                   elif 2 <= delta_days <= 7:
                       # for future dates, return the weekday name
                       date_text = date_requested.strftime("%A")
                       future_weather = data['daily'][delta_days]
                       weather_description = future_weather['weather'][0]['description']
                       temp_day = future_weather['temp']['day']
                       rounded_temp = round(temp_day)
                       weather_response = f"On {date_text}, the weather in {city} will be {weather_description} with a daytime temperature of {rounded_temp}°C."
                   else:
                       # Handle dates beyond the 7-day forecast limit
                       weather_response = "I can only provide weather forecasts for the next 7 days."
               except ValueError:
                   weather_response = "Please specify the date in YYYY-MM-DD format."
       else:
           weather_response = "I'm sorry, I couldn't fetch the weather for you right now."
   else:
       weather_response = "I couldn't find the specific location you're asking about. Can you specify a city?"


   return weather_response

# Saves user's name to a file
def save_user_name(name):
   with open(user_name_file, "w") as file:
       file.write(name)

def load_user_name():
   try:
       with open(user_name_file, "r") as file:
           return file.read().strip()
   except FileNotFoundError:
       return None  # Return None if the file doesn't exist


def save_speaking_style(speaking_style):
   with open("speaking_style.txt", "w") as file:
       file.write(speaking_style)

def get_speaking_style():
   try:
       with open("speaking_style.txt", "r") as file:
           return file.read().strip()
   except FileNotFoundError:
       return None  # Return None if the file doesn't exist

'''
# listen and convert speech to text
def listen_and_respond(timeout=10):  # wait 10s for user to say something, otherwise start listening for wake word
   while True:
       with microphone as source:
           print("Please say something...")
           recognizer.adjust_for_ambient_noise(source, duration=1)  # adjust for ambient noise
           # tells the recognizer to listen to the ambient noise for half a second to calibrate.
           try:
               audio = recognizer.listen(source, timeout=timeout)
               text = recognizer.recognize_google(audio)
               print("You said: " + text)
               return text
           except sr.WaitTimeoutError:
               print("No speech detected within the timeout period.")
               return None
           except sr.UnknownValueError:
               print("Google Speech Recognition could not understand audio")
           except sr.RequestError as e:
               print("Could not request results from Google Speech Recognition service; {0}".format(e))
'''

def listen_and_respond(timeout=10):
    while True:
        with microphone as source:
            print("Please say something...")
            recognizer.adjust_for_ambient_noise(source, duration=1)  # adjust for ambient noise
            # tells the recognizer to listen to the ambient noise for half a second to calibrate.
            try:
                audio = recognizer.listen(source, timeout=timeout)
                try:
                    text = recognizer.recognize_google(audio)
                    print("You said: " + text)
                    return text
                except sr.UnknownValueError:
                    print("Google Speech Recognition could not understand audio")
                    # Instead of returning None immediately, break to allow the loop to continue
            except sr.WaitTimeoutError:
                print("No speech detected within the timeout period.")
                return None
            except sr.RequestError as e:
                print("Could not request results from Google Speech Recognition service; {0}".format(e))
                # Consider whether to return None or break based on your error handling preferences

        
# generate response with OpenAI API and update conversation history
def generate_response(text):
   global history
   history.append({'role': 'user', 'content': text})


   project_id = "aicompanion-krwc"
   # generate a random UUID (Universally Unique Identifier) for the session betw the user and Dialogflow.
   # ensures each session is distinct, so Dialogflow maintains the context of the conversation.
   session_id = str(uuid.uuid4())


   # Call Dialogflow API to detect intent based on user query ('text')
   dialogflow_result = detect_intent_text(project_id, session_id, text, "en")


   # Correctly access intent display name and parameters from dialogflow_result
   intent_display_name = dialogflow_result["intent"]["display_name"]
   parameters = dialogflow_result["parameters"]


   # Check the detected intent and act accordingly
   if intent_display_name == "WeatherQuery":
       style = get_speaking_style()
       city = parameters.get("geo-city")  # extract geo-city from parameters dictionary and use Montreal as default (if not specified).
       if not city:
           city = "Montreal"
       date_time = parameters.get("date-time", None)
       weather_response = get_weather(city, date_time)
       # construct a creative prompt for GPT-3.5 turbo
       assistant_text = weatherquery_prompt(city, date_time, weather_response, style)
       # assistant_text = weather_response
   elif intent_display_name == "RobotNameQuery":
       style = get_speaking_style()
       assistant_text = robotnamequery_prompt(style)
       # assistant_text = dialogflow_result.get("fulfillment_text", "I'm not sure how to respond to that.")
   elif intent_display_name == "CaptureName":
       style = get_speaking_style()
       user_name = load_user_name()
       fulfillment_text = dialogflow_result.get("fulfillment_text", "I'm not sure how to respond to that.")
       print(fulfillment_text)
       if confirm_and_change_user_name(fulfillment_text, user_name, project_id, session_id):
           user_name = load_user_name()
           assistant_text = capturename_prompt(user_name, text, style)
       else:
           assistant_text = "Will not change user name."
   elif intent_display_name == "GreetingIntent":
       style = get_speaking_style()
       user_name = load_user_name()
       assistant_text = greetingintent_prompt(user_name, text, style)
   elif intent_display_name == "ChangeSpeakingStyle":
       if confirm_and_change_style(text, project_id, session_id):
           save_speaking_style(text)
           assistant_text = changespeakingstyle_prompt(text)  # Here 'text' is explicitly passed, ensuring scope
           update_confirmation_message(text)
       else:
           assistant_text = "Will not change speaking style."
   else:
       # If not one of the specified intents, use OpenAI's GPT-3.5 Turbo.
       style = get_speaking_style()
       prompt = f"The user wants you to speak in the following manner: {style}. They just said {text}. Give them an appropriate response, answering in the style they specified. KEEP IT BRIEF, MAXIMUM 2 SENTENCES!"
       print(prompt)
       response = client.chat.completions.create(
           model="gpt-3.5-turbo",
           temperature=1,
           # messages=history[-10:]
           messages=[{"role": "system", "content": prompt}]
       )
       if response.choices:
           # extracts response text from the OpenAI completion object.
           # after making a request to the API, you receive a response obj which has a list of choices (completions).
           # each choice represents a possible response based on the input provided.
           # [0] selects the first choice from the list.
           assistant_text = response.choices[0].message.content
       else:
           assistant_text = "Not sure how to respond to that."


   # print the response and append it to the conversation history
   print(f"Assistant: {assistant_text.strip()}")
   # appends a new dictionary to the 'history' list.
   # the dictionary contains 2 key-value pairs (assistant role & content of the message)
   history.append({'role': 'assistant', 'content': assistant_text.strip()})


   return assistant_text.strip()


def confirm_and_change_user_name(fulfillment_text, user_name, project_id, session_id):
   speak(fulfillment_text)
   listening_flag()
   confirmation_response = listen_and_respond(timeout=10)
   reset_flag()
   confirmation_intent_result = detect_intent_text(project_id, session_id, confirmation_response, "en")
   if confirmation_intent_result["intent"]["display_name"] in ["ConfirmYes", "ConfirmYesSpeakingStyle"]:
       print("yes confirmed")
       return True
   else:
       print("no confirmed")
       return False

def confirm_and_change_style(text, project_id, session_id):
   speak('Are you sure you want me to change my speaking style?')
   listening_flag()
   confirmation_response = listen_and_respond(timeout=10)
   reset_flag()
   confirmation_intent_result = detect_intent_text(project_id, session_id, confirmation_response, "en")
   if confirmation_intent_result["intent"]["display_name"] == "ConfirmYesSpeakingStyle":
       print("yes confirmed")
       return True
   else:
       print("no confirmed")
       return False


def weatherquery_prompt(city, date_time, weather_response, style):
   creative_prompt = f"The user wants you to speak in the following manner: '{style}'. They asked about the weather in {city}{f' on {date_time}' if date_time else ''}. Here's what you found: {weather_response}. Now, generate a creative answer in that style. KEEP IT BRIEF, MAXIMUM 2 SENTENCES."
   print("prompt:", creative_prompt)


   response = client.chat.completions.create(
       model="gpt-3.5-turbo",
       temperature=0.7,  # Adjust based on desired creativity
       messages=[{"role": "system", "content": creative_prompt}]
   )
   if response.choices:
       assistant_text = response.choices[0].message.content
   else:
       assistant_text = "I'm sorry, I couldn't generate a response right now."
   return assistant_text


def robotnamequery_prompt(style):
   creative_prompt = f"The user wants you to speak in the following manner: '{style}'. They just asked for your name. Your name is Medmate. Tell them your name. MAX 1 SENTENCE, KEEP IT BRIEF!"
   print("prompt:", creative_prompt)
   response = client.chat.completions.create(
       model="gpt-3.5-turbo",
       temperature=1,
       messages=[{"role": "system", "content": creative_prompt}]
   )
   if response.choices:
       assistant_text = response.choices[0].message.content
   else:
       assistant_text = f"My name is Medmate!"
   return assistant_text




def capturename_prompt(user_name, text, style):
   save_user_name(user_name)
   creative_prompt = f"The user wants you to speak in the following manner: '{style}'. They just gave you their name, {user_name}, and they said '{text}'. Generate a short (MAX 1 SENTENCE) response to this."
   print("prompt:", creative_prompt)
   # Use the GPT-3.5 API call here with the crafted prompt
   response = client.chat.completions.create(
       model="gpt-3.5-turbo",
       temperature=1,
       messages=[{"role": "system", "content": creative_prompt}]
   )
   if response.choices:
       assistant_text = response.choices[0].message.content
   else:
       assistant_text = f"Nice to meet you, {user_name}! I'm looking forward to our conversations."
   return assistant_text




def greetingintent_prompt(user_name, text, style):
   creative_prompt = f"The user wants you to speak in the following manner: /'{style}'. The user just said /'{text}' to you. Their name is {user_name}. Give them a brief greeting (MAX 1 SENTENCE)."
   print("prompt:", creative_prompt)
   response = client.chat.completions.create(
       model="gpt-3.5-turbo",
       temperature=1,
       messages=[{"role": "system", "content": creative_prompt}]
   )
   if response.choices:
       assistant_text = response.choices[0].message.content
   else:
       assistant_text = f"Hey there, {user_name}!"
   return assistant_text



def changespeakingstyle_prompt(text):
   creative_prompt = f"The user just said '{text}' to you. This is how they want you to speak. Give them a response that they'll enjoy and find humorous. KEEP IT BRIEF! MAX 2 SENTENCES."
   print("prompt:", creative_prompt)
   response = client.chat.completions.create(
       model="gpt-3.5-turbo",
       temperature=1,
       messages=[{"role": "system", "content": creative_prompt}]
   )
   if response.choices:
       assistant_text = response.choices[0].message.content
   else:
       assistant_text = f"Sorry, I encountered an error."
   return assistant_text

def update_confirmation_message(text):
   creative_prompt = f"The user wants you to speak in the following manner: '{text}'. Generate five distinct one-word or two-word confirmation answers (such as 'yes', 'affirmative', etc) in the specified style, indicating that you are listening for their next prompt. Confirmations must be gender-neutral."
   print("prompt:", creative_prompt)
   response = client.chat.completions.create(
       model="gpt-3.5-turbo",
       temperature=1,
       # n=5, # request 5 completions
       messages=[{"role": "system", "content": creative_prompt}]
   )
   if response.choices:
       with open("confirmation_text.txt", "w") as file:
           for choice in response.choices:
               file.write(choice.message.content.strip() + "\n")
               print(choice.message.content.strip())

def save_user_name(name):
    print("saving name:", name)
    with open("user_name.txt", "w") as file:
        file.write(name)

def detect_intent_text(project_id, session_id, text, language_code):
   session = session_client.session_path(project_id, session_id)
   text_input = dialogflow.TextInput(text=text, language_code=language_code)
   query_input = dialogflow.QueryInput(text=text_input)
   response = session_client.detect_intent(session=session, query_input=query_input)

   print("Detected intent:", response.query_result.intent.display_name)
   print("Fulfillment text:", response.query_result.fulfillment_text)

   parameters = response.query_result.parameters

   return {
       "intent": {
           "display_name": response.query_result.intent.display_name
       },
       "fulfillment_text": response.query_result.fulfillment_text,
       "parameters": parameters
   }


def speak(text):
    tts = gTTS(text=text, lang='en', tld='co.uk')
    tts.save("response.mp3")
    os.system("mpg321 response.mp3")
    
# Generate confirmation message at the start
'''
def generate_confirmation():
    tts = gTTS(text="Yes?", lang='en', tld='co.uk')
    tts.save("confirmation.mp3")
   #os.system("mpg321 confirmation.mp3")
'''
    
def generate_confirmation():
    with open("confirmation_text.txt", "r") as file:
        lines = file.readlines()
    
    # Select a random line from the file
    confirmation_message = random.choice(lines).strip()
    # Remove the number and period prefix if present (assuming format "1. Message")
    confirmation_message = confirmation_message.split('. ', 1)[-1]
    
    # Generate the speech from the selected message
    tts = gTTS(text=confirmation_message, lang='en', tld='co.uk')
    tts.save("confirmation.mp3")
    

    print("Confirmation message:", confirmation_message)

def find_device_by_index_name(target_device_name):
    pa = pyaudio.PyAudio()
    device_index = None
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if target_device_name in info['name']:
            device_index = i
            break
    pa.terminate()
    return device_index

def wait_for_device(device_name, timeout=60):
    start_time = time.time()
    while True:
        device_index = find_device_by_index_name(device_name)
        if device_index is not None:
            print(f"Device '{device_name}' found at index {device_index}. Proceeding...")
            return device_index
        elif time.time() - start_time > timeout:
            print(f"Timeout reached. Device '{device_name}' not found.")
            return None
        print("Waiting for device to become available...")
        time.sleep(2)  # Wait for 2 seconds before checking again

# writes to file so that display will be updated. raspberry.py periodically checks this file
def listening_flag():
    # Set the flag to "detected"
    with open("wake_flag.txt", "w") as f:
        f.write("detected")
    print("Flag set.")

def reset_flag():
    with open("wake_flag.txt", "w") as f:
        f.write("")
    print("Flag reset.")

def main():
    porcupine = None
    pa = None
    audio_stream = None
    generate_confirmation()
    
    # Wait for the "pulse" device to become available before initializing Porcupine and PyAudio
    target_device_name = "pulse"
    device_index = wait_for_device(target_device_name, timeout=60)  # Wait up to 60 seconds for the device
    if device_index is None:
        print("Audio input device not available. Exiting...")
        return

    try:
        porcupine = pvporcupine.create(
            access_key=PORCUPINE_KEY,
            keyword_paths=[KEYWORD_FILE_PATH] 
          #  keywords=["bumblebee"]
        )
        pa = pyaudio.PyAudio()
        audio_stream = pa.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length,
            input_device_index=device_index
        )

        while True:  # Main loop for continuous interaction
            print("Listening for wake word...")
            reset_flag()
            while True:  # Wake word detection loop
                pcm = audio_stream.read(porcupine.frame_length)
                pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
                keyword_index = porcupine.process(pcm)

                if keyword_index >= 0:
                    listening_flag() # write to file. used for feedback on display.
                    print("Wake word detected!")
                    os.system("mpg321 confirmation.mp3")  # Play confirmation sound
                    break  # Break out of the wake word loop

            # After breaking out of the wake word loop, enter a loop for listening and responding to user input
            while True:
                listening_flag()
                user_text = listen_and_respond(timeout=10)  # Listen for user input with a timeout
                if user_text is None:
                    reset_flag()
                    generate_confirmation()
                    break # go back to listening for wake word
                else:
                    reset_flag() # resets the flag. used for feedback on display.
                    response_text = generate_response(user_text)  # Generate and speak the response based on user input
                    if response_text:
                        speak(response_text)  # Speak out the response
                    else:
                        listening_flag()
                        print("Could not generate a response. Listening for the next prompt...")


    finally:
        if audio_stream is not None:
            audio_stream.close()
        if pa is not None:
            pa.terminate()
        if porcupine is not None:
            porcupine.delete()

if __name__ == "__main__":
   main()
    #generate_confirmation()
   #speak("hello")
