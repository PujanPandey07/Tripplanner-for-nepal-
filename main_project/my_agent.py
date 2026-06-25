import os
import requests
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv

load_dotenv()

llm = ChatOllama(model="llama3.1:8b")

search_tool = DuckDuckGoSearchRun()

# set this in your env, don't hardcode it
WEATHERSTACK_KEY = os.getenv("WEATHERSTACK_API_KEY")


@tool
def weather(city: str) -> str:
    """Takes a city name and returns the current weather for that city."""
    if not WEATHERSTACK_KEY:
        return "Weather API key not configured."

    url = "http://api.weatherstack.com/current"
    params = {"access_key": WEATHERSTACK_KEY, "query": city}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return f"Could not fetch weather: {e}"

    if "error" in data:
        return f"Weather API error: {data['error'].get('info', 'unknown error')}"

    current = data.get("current", {})
    location = data.get("location", {})
    return (
        f"Weather in {location.get('name', city)}: "
        f"{current.get('temperature')}°C, {current.get('weather_descriptions', [''])[0]}"
    )


print(weather.invoke({"city": "New York"}))

agent = create_react_agent(
    llm,
    tools=[search_tool, weather],
    prompt="You are a helpful assistant. When you use a tool, trust and use its result directly "
    "as the current, accurate answer — do not refer to your training data or knowledge cutoff "
    "when a tool has already given you the answer."
)

response = agent.invoke(
    {"messages": [
        {"role": "user", "content": "What is the capital of France and what is the weather there?"}]}
)

print(response["messages"][-1].content)
