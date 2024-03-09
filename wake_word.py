import os
import proto
import pvporcupine
import pyaudio
import struct
# from gtts import gTTS
import speech_recognition as sr
import openai
from dotenv import load_dotenv
import pyttsx3
import requests
from flask import Flask, request, jsonify
import uuid
from datetime import datetime, timedelta
import pytz  # for timezone handling
from google.cloud import dialogflow
from google.oauth2 import service_account
import random

load_dotenv()  # Load environment variables

# initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=openai.api_key)

# initialize OpenWeatherAPI key
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
PORCUPINE_KEY = os.getenv("PORCUPINE_KEY")

# System prompt and conversation history
character_prompt = 'Answer precise and short with a hint of charming sarcasm, maximum of 2 sentences!'
history = [{'role': 'system', 'content': character_prompt}]

# Speech recognizer and microphone
recognizer = sr.Recognizer()
microphone = sr.Microphone()

# Initialize pyttsx3 engine
engine = pyttsx3.init()

# create a Flask app with an endpoint for Dialogflow webhook fulfillment
app = Flask(__name__)

service_account_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
credentials = service_account.Credentials.from_service_account_file(service_account_path)
session_client = dialogflow.SessionsClient(
    credentials=credentials)  # Explicitly set the credentials when initializing your client


# Flask Decorator. tells Flask to execute the following function whenever a web request matches the route (/webhook) & HTTP method (POST).
# this is used for testing in the Dialogflow console
@app.route('/webhook', methods=['POST'])
def webhook():
    # retrieve the JSON data sent to the Flask app's /webhook endpoint.
    # force=True tells Flask to ignore the content type of the request and attempt to parse the body as JSON regardless (even if 'Content-Type' header is not set to 'application/json')
    req = request.get_json(force=True)
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
        save_user_name(user_name)
        print(user_name)
        user_captured_response = [f"Got it! I'll remember that your name is {user_name}.",
                                  f"Alrighty {user_name}! Understood.",
                                  f"Sounds good, {user_name}!",
                                  f"{user_name}, {user_name}, {user_name}, I will never forget.",
                                  f"Oky doky {user_name}.",
                                  f"What a coincidence, {user_name} is my favourite name. Got it."]
        selected_response = random.choice(user_captured_response)
        print(selected_response)
        return jsonify({
            "fulfillmentMessages": [{
                "text": {
                    "text": [selected_response]
                }
            }]
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


# Saves user's name to a file
def save_user_name(name):
    with open("user_name.txt", "w") as file:
        file.write(name)


def load_user_name():
    try:
        with open("user_name.txt", "r") as file:
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
    print(f"Geocoding response: {geocoding_data}")

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
                    # processed_date_time = process_date_time(date_time)

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
                        weather_response = "Sorry, I don't have information for past weather."
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


def process_date_time(date_time):
    if isinstance(date_time, str):
        # Directly parse the ISO 8601 string
        return datetime.fromisoformat(date_time[:-6])  # Removes timezone for simplicity
    elif isinstance(date_time, proto.marshal.collections.maps.MapComposite):
        # Handle the structured format for relative dates
        amount = date_time.get('amount')
        unit = date_time.get('unit')
        # Assuming 'unit' is 'day' for simplicity; adjust logic as needed for other units
        if unit == 'day':
            return datetime.now() + timedelta(days=amount)
        # Add more conditions as necessary for other units like 'week', 'month', etc.
    # Add additional error handling or fallback as necessary
    return None


def format_current_weather(data, city):
    current_weather = data['current']
    weather_description = current_weather['weather'][0]['description']
    temperature = current_weather['temp']
    rounded_temp = round(temperature)
    return f"Currently in {city}, it's {weather_description} with a temperature of {rounded_temp}°C."


def format_future_weather(data, city, date_time):
    # Use datetime.strptime to handle date_time if it's a valid string
    try:
        date_requested = datetime.strptime(date_time, "%Y-%m-%d").date()
        today = datetime.now().date()
        delta_days = (date_requested - today).days
        if 0 <= delta_days <= 7:
            # Your existing logic to handle future dates
            return f"Forecast for {city} in {delta_days} days..."
        else:
            return "I can only provide weather forecasts for the next 7 days."
    except ValueError:
        return "Please specify the date in YYYY-MM-DD format."


def speak(text):
    """Use pyttsx3 to speak the text."""
    engine.say(text)
    engine.runAndWait()


# Generate confirmation message
def generate_confirmation():
    with open("confirmation_text.txt", "r") as file:
        lines = file.readlines()
        # select a random line from the file
        confirmation_message = random.choice(lines).strip()
        # Remove the number and period prefix if present (assuming format "1. Message")
        confirmation_message = confirmation_message.split('. ', 1)[-1]
        speak(confirmation_message)
        print("Confirmation message:", confirmation_message)


# listen and convert speech to text
def listen_and_respond(
        timeout=10):  # wait 10 seconds for the user to say something, otherwise start listening for wake word again
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
            return None


# generate response with OpenAI API and update conversation history
# this function is only called when you actually speak to it (not just Dialogflow console)
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
        city = parameters.get(
            "geo-city")  # extract geo-city from parameters dictionary and use Montreal as default (if not specified).
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
        if user_name:
            assistant_text = capturename_prompt(user_name, text, style)
        else:
            assistant_text = "I couldn't capture the name correctly."
    elif intent_display_name == "GreetingIntent":
        style = get_speaking_style()
        user_name = load_user_name()
        assistant_text = greetingintent_prompt(user_name, text, style)
    elif intent_display_name == "ChangeSpeakingStyle":
        save_speaking_style(text)
        assistant_text = changespeakingstyle_prompt(text)
        update_confirmation_message(text)
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
    creative_prompt = f"The user wants you to speak in the following manner: '{text}'. Generate five distinct one-word or two-word confirmation answers (such as 'yes', 'affirmative', etc) in the specified style, indicating that you are listening for their next prompt."
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


def main():
    porcupine = None
    pa = None
    audio_stream = None
    # generate_confirmation()

    # Attempting to dynamically select the microphone
    try:
        porcupine = pvporcupine.create(access_key=PORCUPINE_KEY, keywords=["bumblebee"])
        pa = pyaudio.PyAudio()

        # Select the default microphone as input device
        audio_stream = pa.open(rate=porcupine.sample_rate,
                               channels=1,
                               format=pyaudio.paInt16,
                               input=True,
                               frames_per_buffer=porcupine.frame_length,
                               input_device_index=None)  # Use default input device

        # Main loop for continuous interaction
        while True:
            print("Listening for wake word...")
            # Wake word detection loop
            while True:
                pcm = audio_stream.read(porcupine.frame_length)
                pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
                keyword_index = porcupine.process(pcm)

                if keyword_index >= 0:
                    # print("Wake word detected!")
                    generate_confirmation()  # Play confirmation
                    break
            # Loop for listening and responding to user input
            while True:
                user_text = listen_and_respond(timeout=10)
                if user_text:
                    response_text = generate_response(user_text)
                    if response_text:
                        speak(response_text)
                    else:
                        print("Could not generate a response. Listening for the next prompt...")
                else:
                    print("No user input detected. Listening for wake word...")
                    break

    finally:
        if audio_stream:
            audio_stream.close()
        if pa:
            pa.terminate()
        if porcupine:
            porcupine.delete()


'''
        # Main loop for continuous interaction
        while True:
            print("Listening for wake word...")
            # Wake word detection loop
            while True:
                pcm = audio_stream.read(porcupine.frame_length)
                pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
                keyword_index = porcupine.process(pcm)

                if keyword_index >= 0:
                    print("Wake word detected!")
                    generate_confirmation()  # Play confirmation
                    break
'''

if __name__ == "__main__":
    # app.run(debug=True)
    main()
    # speak(generate_response("talk to me like you are a gen Z teenager from now on"))
    # speak(generate_response("from now on, you must speak like an angry dictator"))
    # speak(generate_response("from now on you must speak like you are a depressed teenager"))
