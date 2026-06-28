import json
import difflib
import os

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_SCRIPT_DIR, "..", ".env"))


# ---------------------------------------------------------------------------
# LOAD THE DATASET ONCE
# ---------------------------------------------------------------------------
_DATA_PATH = os.path.join(_SCRIPT_DIR, "nepal_destinations_seed.json")

with open(_DATA_PATH, "r", encoding="utf-8") as f:
    nepal_data = json.load(f)

destinations = nepal_data["destinations"]
trekkings = nepal_data["trekking_destinations"]


# ---------------------------------------------------------------------------
# SHARED HELPER -- used by both trekking_info and budget_calculator so the
# matching behavior is defined in exactly one place, not duplicated.
# ---------------------------------------------------------------------------
def fuzzy_find(query: str, records: list, name_key: str = "name", cutoff: float = 0.6):
    """Find a record in `records` whose [name_key] best matches `query`.
    3-pass strategy: exact match -> substring match -> fuzzy match.
    Returns (matched_record_or_None, note_or_None)."""

    q = query.lower().strip()

    # Pass 1: exact, case-insensitive
    for r in records:
        if r[name_key].lower() == q:
            return r, None

    # Pass 2: substring, either direction (handles "Annapurna Circuit" ->
    # "Annapurna Circuit Trek")
    for r in records:
        real = r[name_key].lower()
        if q in real or real in q:
            return r, f"Matched '{query}' to closest entry '{r[name_key]}'."

    # Pass 3: fuzzy, character-similarity based (handles typos)
    all_names = [r[name_key] for r in records]
    close = difflib.get_close_matches(query, all_names, n=1, cutoff=cutoff)
    if close:
        matched = next(r for r in records if r[name_key] == close[0])
        return matched, f"Matched '{query}' to closest entry '{matched[name_key]}'."

    return None, None


# ---------------------------------------------------------------------------
# TOOL 1: destination_info
# ---------------------------------------------------------------------------
@tool
def destination_info(city: str) -> dict:
    """Look up details about a specific city or town destination in Nepal
    from the dataset. Use this when the user asks about a place to visit
    (not a trek) -- covers accommodation cost bands, food/transport costs,
    activities with prices, nearby day-trip extensions, and which treks
    are accessible from there. Pass the destination name exactly as the
    user wrote it, e.g. 'Pokhara' or 'Kathmandu'."""

    for dest in destinations:
        if dest["name"].lower() == city.lower():
            return {"found": True, "data": dest}

    available = [d["name"] for d in destinations]
    return {
        "found": False,
        "reason": f"No destination named '{city}' in dataset.",
        "available_destinations": available,
    }


# ---------------------------------------------------------------------------
# TOOL 2: trekking_info  (uses the shared fuzzy_find helper)
# ---------------------------------------------------------------------------
@tool
def trekking_info(trek_name: str) -> dict:
    """Look up details about a specific trekking destination in Nepal
    from the dataset. Use this when the user asks about a trek -- covers
    difficulty, duration, altitude, and which towns are used as starting
    points. Pass the trek name exactly as the user wrote it, e.g. 'Everest Base Camp'.
    Dataset entries usually end in the word 'Trek', e.g. 'Annapurna Circuit Trek'."""

    match, note = fuzzy_find(trek_name, trekkings)

    if match is None:
        available = [t["name"] for t in trekkings]
        return {
            "found": False,
            "reason": f"No trekking destination named '{trek_name}' in dataset.",
            "available_treks": available,
        }

    result = {"found": True, "data": match}
    if note:
        result["note"] = note
    return result


# ---------------------------------------------------------------------------
# TOOL 3: budget_calculator
# ---------------------------------------------------------------------------
@tool
def budget_calculator(
    destination: str,
    days: int,
    tier: str,
    activities: list[str] = None,
    trek: str = None,
) -> dict:
    """Calculate an estimated trip budget range in NPR for a given destination.
    `tier` must be one of: 'budget', 'mid_range', 'luxury'.
    `activities` is an optional list of activity names to include (fuzzy matched
    against the destination's activity list). `trek` is an optional trek name if
    the user wants to add a multi-day trek's cost band on top of the destination stay.
    Always use this tool for any budget/cost total request instead of calculating
    yourself -- it returns exact figures from the dataset."""

    activities = activities or []

    valid_tiers = ["budget", "mid_range", "luxury"]
    if tier not in valid_tiers:
        return {
            "found": False,
            "reason": f"Invalid tier '{tier}'. Must be one of {valid_tiers}.",
        }

    dest, dest_note = fuzzy_find(destination, destinations)
    if dest is None:
        return {
            "found": False,
            "reason": f"No destination named '{destination}' in dataset.",
            "available_destinations": [d["name"] for d in destinations],
        }

    # accommodation: per-night cost * nights
    acc = dest["accommodation"][tier]
    accommodation_min = acc["min_npr"] * days
    accommodation_max = acc["max_npr"] * days

    # food and local transport: per-day cost * days
    food_min = dest["food_per_day_npr"]["min"] * days
    food_max = dest["food_per_day_npr"]["max"] * days

    transport_min = dest["local_transport_per_day_npr"]["min"] * days
    transport_max = dest["local_transport_per_day_npr"]["max"] * days

    # activities: one-time costs, only for requested ones, fuzzy matched
    activity_breakdown = []
    activities_min_total = 0
    activities_max_total = 0
    unmatched_activities = []

    for requested in activities:
        match, note = fuzzy_find(requested, dest["activities"])
        if match is None:
            unmatched_activities.append(requested)
            continue
        activities_min_total += match["cost_min_npr"]
        activities_max_total += match["cost_max_npr"]
        entry = {
            "name": match["name"],
            "cost_min_npr": match["cost_min_npr"],
            "cost_max_npr": match["cost_max_npr"],
        }
        if note:
            entry["note"] = note
        activity_breakdown.append(entry)

    # trek: optional, already a trip-total cost band (not multiplied by days)
    trek_breakdown = None
    trek_min = 0
    trek_max = 0
    if trek:
        matched_trek, trek_note = fuzzy_find(trek, trekkings)
        if matched_trek is None:
            return {
                "found": False,
                "reason": f"No trekking destination named '{trek}' in dataset.",
                "available_treks": [t["name"] for t in trekkings],
            }
        band = matched_trek["cost_band_npr"]
        if tier == "luxury" and "luxury_min" in band:
            trek_min, trek_max = band["luxury_min"], band["luxury_max"]
        else:
            trek_min, trek_max = band["budget_min"], band["budget_max"]

        trek_breakdown = {
            "name": matched_trek["name"],
            "cost_min_npr": trek_min,
            "cost_max_npr": trek_max,
        }
        if trek_note:
            trek_breakdown["note"] = trek_note

    grand_min = accommodation_min + food_min + \
        transport_min + activities_min_total + trek_min
    grand_max = accommodation_max + food_max + \
        transport_max + activities_max_total + trek_max

    result = {
        "found": True,
        "destination": dest["name"],
        "tier": tier,
        "days": days,
        "breakdown": {
            "accommodation": {"min_npr": accommodation_min, "max_npr": accommodation_max},
            "food": {"min_npr": food_min, "max_npr": food_max},
            "local_transport": {"min_npr": transport_min, "max_npr": transport_max},
            "activities": activity_breakdown,
            "trek": trek_breakdown,
        },
        "grand_total": {"min_npr": grand_min, "max_npr": grand_max},
    }

    if unmatched_activities:
        result["unmatched_activities"] = unmatched_activities
    if dest_note:
        result["destination_match_note"] = dest_note

    return result


# ---------------------------------------------------------------------------
# TOOL 4: web_search
# ---------------------------------------------------------------------------
@tool
def web_search(query: str) -> dict:
    """Search the web for current information NOT covered by the Nepal dataset --
    use this for things like current weather, recent trail/road closures, visa
    requirements, flight prices/availability, festival dates, or exchange rates.
    Do NOT use this for destination or trek details already covered by
    destination_info or trekking_info -- prefer those whenever the dataset has
    the answer."""

    try:
        from langchain_community.tools import DuckDuckGoSearchRun
        searcher = DuckDuckGoSearchRun()
        raw_result = searcher.invoke(query)

        if not raw_result or not raw_result.strip():
            return {
                "found": False,
                "reason": f"No web search results found for '{query}'.",
            }

        return {"found": True, "query": query, "result": raw_result}

    except Exception as e:
        return {
            "found": False,
            "reason": f"Web search failed due to an error: {e}",
        }


# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a Nepal trip-planning assistant. You have access to tools
backed by a curated dataset of Nepal destinations and treks. Follow these rules strictly:

1. ALWAYS prefer dataset tools (destination_info, trekking_info, budget_calculator) over
   your own general knowledge. If a tool returns found: true, use ONLY the data it
   returned -- do not add extra facts, prices, or recommendations from your own knowledge
   unless the user asks about something the dataset clearly does not cover (e.g. visa
   rules, weather, flights).

2. When asked about treks "near" or "accessible from" a specific destination, you MUST
   use the accessible_treks list returned by destination_info as your source of truth.
   Do NOT call trekking_info on a trek you recalled from your own knowledge unless it
   appears in that destination's accessible_treks list.

3. If a tool returns found: false, do not guess or invent an answer. Either retry with
   a name from the tool's suggested list, or tell the user clearly that this isn't in
   the dataset.

4. For costs and budgets, use only the exact numbers returned by tools, especially
   budget_calculator. Never estimate, round, or invent your own cost figures. Always
   call budget_calculator for any request involving a total trip cost -- never sum
   numbers yourself.

5. If the user's request needs information no dataset tool can provide (e.g. current
   weather, flight availability, visa requirements, recent trail conditions), say so
   explicitly rather than guessing.

6. Do not state or imply that a destination/trek is geographically connected, nearby,
   or "on the way" to another place unless that exact relationship is explicitly present
   in the tool data (e.g. listed in accessible_treks, nearby_extensions, or the trek's own
   region/starting_point fields). If asked whether two places connect and the dataset
   doesn't confirm it, say the dataset doesn't provide that information rather than
   reasoning about it from general geography.

7. If a budget_calculator result includes unmatched_activities, you must clearly tell
   the user which activities could not be priced and were excluded from the total.

8. If web_search returns results that are vague, generic, or don't contain a specific
   answer to the user's question (e.g. search-result snippets about a topic rather than
   the actual fact), do not simply say you have no information. Instead, briefly
   summarize what the search results do suggest, clearly flag that it's not a confirmed
   current fact, and recommend the user verify with an official source (e.g. a weather
   site, the trekking agency, or local authorities) for anything safety-relevant like
   trail conditions.

9. Before calling budget_calculator, restate the days, tier, destination, and trek back
   to the user-stated values in your reasoning to confirm they match.

10. Treat every distinct sub-question in a multi-part request as something you must
   address with a tool call if a relevant tool exists -- do not skip a sub-question by
   replacing it with a generic disclaimer. If the user asks about weather, trail
   conditions, or similar live information, you must call web_search for that part of
   the question, even if you are also calling other tools for other parts of the same
   request.
11. For general knowledge questions that have nothing to do with your specific dataset
   (e.g. Nepali culture, language, history, geography, currency, general travel
   etiquette, or any question that isn't about a specific destination, trek, or
   budget covered by your tools), answer directly and confidently from your own
   knowledge. You don't need to call a tool or add a disclaimer for these --
   only stay cautious and tool-grounded for the specific destinations, treks, and
   costs your dataset actually covers.
"""


# ---------------------------------------------------------------------------
# BUILD THE GRAPH ONCE AT IMPORT TIME
# (cheap to keep around in memory, wasteful to rebuild on every message)
# ---------------------------------------------------------------------------
ALL_TOOLS = [destination_info, trekking_info, budget_calculator, web_search]

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0,
)
llm_with_tools = llm.bind_tools(ALL_TOOLS)


def agent_node(state: MessagesState):
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


tool_node = ToolNode(ALL_TOOLS)


def should_continue(state: MessagesState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END


_graph_builder = StateGraph(MessagesState)
_graph_builder.add_node("agent", agent_node)
_graph_builder.add_node("tools", tool_node)
_graph_builder.set_entry_point("agent")
_graph_builder.add_conditional_edges(
    "agent", should_continue, {"tools": "tools", END: END}
)
_graph_builder.add_edge("tools", "agent")

_CHECKPOINT_DB_PATH = os.path.join(_SCRIPT_DIR, "checkpoints.db")


# ---------------------------------------------------------------------------
# THE SINGLE ENTRY POINT DJANGO (OR ANYTHING ELSE) CALLS
# ---------------------------------------------------------------------------
def run_agent(thread_id: str, user_message: str) -> str:
    """Send one message through the agent for a given conversation thread.
    Opens a fresh checkpointer connection per call -- safe for Django's
    request-per-call model. History persists to checkpoints.db, keyed by
    thread_id, so passing the same thread_id across calls continues the
    same conversation."""

    with SqliteSaver.from_conn_string(_CHECKPOINT_DB_PATH) as memory:
        app = _graph_builder.compile(checkpointer=memory)

        thread_config = {"configurable": {"thread_id": thread_id}}

        # only inject the system prompt on a brand-new conversation thread
        existing_state = app.get_state(thread_config)
        messages = []
        if not existing_state.values.get("messages"):
            messages.append(SystemMessage(content=SYSTEM_PROMPT))
        messages.append(HumanMessage(content=user_message))

        result = app.invoke({"messages": messages}, config=thread_config)
        return _extract_text(result["messages"][-1].content)


def _extract_text(content) -> str:
    """Gemini sometimes returns content as a plain string, and sometimes as
    a list of content blocks (e.g. [{'type': 'text', 'text': '...', 'extras': {...}}]).
    This normalizes either shape down to clean, displayable text only."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        return "\n".join(text_parts).strip()

    return str(content)
