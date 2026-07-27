"""Agentic ride chatbot: LangGraph graph + Groq LLM over a dummy ride backend.

Graph shape:
 

Tool-level human-in-the-loop:
    `get_ride_estimates` is read-only and runs immediately (no prompt to see
    prices). `book_ride` is the only state-changing action, so it pauses at
    `interrupt()` for an explicit yes/no. The interrupt node has NO side effects
    (it only reads the quote to display), so a resume re-running it is safe; the
    actual booking happens once in the separate `execute_booking` node.

"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from ride_service import RideService, quote_to_dict

logger = logging.getLogger(__name__)

load_dotenv()

if not os.getenv("GROQ_API_KEY"):
    raise RuntimeError(
        "GROQ_API_KEY is not set. Add it to a .env file in this directory as "
        "`GROQ_API_KEY=key`"
    )

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are a uber ride-booking assistant. Your ONLY job is helping the user book a "
    "ride. Decline anything unrelated.\n"
    "Supported vehicles: bike, tuk (tuk-tuk), car.\n"
    "Flow:\n"
    "1. Get the pickup and dropoff. Ask for whatever is missing — never invent a "
    "location.\n"
    "2. Call get_ride_estimates. Present each option's price, ETA and whether it "
    "is available, in clear terms.\n"
    "3. Only after the user picks an option AND confirms, call book_ride with that "
    "option's quote_id. A separate approval step will double-check before booking.\n"
    "Call at most one tool per turn."
    "Keep this in mind: If the user chat with you in sinhala language, you should answer in sinhala"
)


# tool schemas 


class GetRideEstimates(BaseModel):
    """Get price, ETA and availability for a ride between two places."""

    pickup: str = Field(description="Where the rider starts from.")
    dropoff: str = Field(description="Where the rider wants to go.")
    vehicle_type: Optional[str] = Field(
        default=None, description="bike, tuk, or car. Omit to compare all options."
    )


class BookRide(BaseModel):
    """Book a ride for a quote the user has chosen and confirmed."""

    quote_id: str = Field(description="quote_id of the chosen option from a prior estimate.")


class RideState(TypedDict):
    messages: Annotated[list, add_messages]
    approved: Optional[bool]


#helpers 

def _latest_tool_calls(messages: list) -> tuple[AIMessage, list[dict]]:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            return msg, msg.tool_calls
    raise ValueError("expected a pending tool call but found none")


# graph factory


def build_app(service: RideService, *, checkpointer=None):
    """Compile the ride graph. A checkpointer is required for interrupt(); an
    in-memory one is used by default for local development."""
    llm = ChatGroq(model=MODEL, temperature=0)
    llm_with_tools = llm.bind_tools([GetRideEstimates, BookRide])

    def _run_call(call: dict) -> dict:
        name, args = call["name"], call["args"]
        if name == "GetRideEstimates":
            quotes = service.get_estimates(
                args["pickup"], args["dropoff"], args.get("vehicle_type")
            )
            return {"options": [quote_to_dict(q) for q in quotes]}
        if name == "BookRide":
            return service.book(args["quote_id"])
        raise ValueError(f"unknown tool {name!r}")

    def _answer_calls(messages: list) -> list[ToolMessage]:
        """Execute every pending tool call and return one ToolMessage each.
        Answering all of them keeps the model's tool protocol consistent."""
        _, calls = _latest_tool_calls(messages)
        results = []
        for call in calls:
            try:
                payload = _run_call(call)
            except ValueError as exc:
                payload = {"error": str(exc)}
            results.append(ToolMessage(content=json.dumps(payload), tool_call_id=call["id"]))
        return results

    # nodes

    def agent(state: RideState) -> dict:
        response = llm_with_tools.invoke(
            [{"role": "system", "content": SYSTEM_PROMPT}, *state["messages"]]
        )
        return {"messages": [response]}

    def safe_tools(state: RideState) -> dict:
        return {"messages": _answer_calls(state["messages"])}

    def approval(state: RideState) -> dict:
        """Pause for booking approval. No side effects — safe to re-run on resume."""
        _, calls = _latest_tool_calls(state["messages"])
        book_call = next(c for c in calls if c["name"] == "BookRide")
        quote = service.get_quote(book_call["args"]["quote_id"])
        detail = quote_to_dict(quote) if quote else {"quote_id": book_call["args"]["quote_id"]}
        decision = interrupt(
            {
                "type": "book_confirmation",
                "quote": detail,
                "question": "Confirm this booking? Reply 'yes' to book or 'no' to cancel.",
            }
        )
        approved = str(decision).strip().lower() in {"yes", "y", "confirm", "ok", "book"}
        return {"approved": approved}

    def execute_booking(state: RideState) -> dict:
        # Reached only after approval; runs once. Side effects allowed here.
        return {"messages": _answer_calls(state["messages"])}

    def cancel_booking(state: RideState) -> dict:
        _, calls = _latest_tool_calls(state["messages"])
        results = []
        for call in calls:
            if call["name"] == "BookRide":
                payload = {"status": "cancelled_by_user"}
            else:  # any non-booking call is harmless; run it normally
                try:
                    payload = _run_call(call)
                except ValueError as exc:
                    payload = {"error": str(exc)}
            results.append(ToolMessage(content=json.dumps(payload), tool_call_id=call["id"]))
        return {"messages": results}

    # routing

    def route_after_agent(state: RideState) -> str:
        last = state["messages"][-1]
        if not (isinstance(last, AIMessage) and last.tool_calls):
            return END
        if any(c["name"] == "BookRide" for c in last.tool_calls):
            return "approval"
        return "safe_tools"

    def route_after_approval(state: RideState) -> str:
        return "execute_booking" if state.get("approved") else "cancel_booking"

    # wiring 

    graph = StateGraph(RideState)
    graph.add_node("agent", agent)
    graph.add_node("safe_tools", safe_tools)
    graph.add_node("approval", approval)
    graph.add_node("execute_booking", execute_booking)
    graph.add_node("cancel_booking", cancel_booking)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["safe_tools", "approval", END])
    graph.add_conditional_edges(
        "approval", route_after_approval, ["execute_booking", "cancel_booking"]
    )
    graph.add_edge("safe_tools", "agent")
    graph.add_edge("execute_booking", "agent")
    graph.add_edge("cancel_booking", "agent")

    return graph.compile(checkpointer=checkpointer or MemorySaver())


# console REPL


def run_turn(app, user_text: str, config: dict) -> None:
    """One user turn; resolves any booking-approval interrupt via console input."""
    payload: object = {"messages": [HumanMessage(content=user_text)]}

    while True:
        interrupted = False
        for chunk in app.stream(payload, config, stream_mode="updates"):
            if "__interrupt__" in chunk:
                interrupted = True
                value = chunk["__interrupt__"][0].value
                q = value["quote"]
                price = f"{q.get('price')} {q.get('currency')}" if q.get("price") else "n/a"
                print(f"\n[confirm] {q.get('vehicle_type')} — {price}. {value['question']}")
                payload = Command(resume=input("> "))
                break
        if not interrupted:
            break

    final = app.get_state(config).values["messages"][-1]
    if isinstance(final, AIMessage) and final.content:
        print(f"\nassistant: {final.content}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    app = build_app(RideService())
    config = {"configurable": {"thread_id": "demo-session"}}

    print("Ride assistant ready. Try: 'I want to go from Bambalapitiya to Nugegoda by tuk'")
    print("Type 'quit' to exit.")
    while True:
        try:
            user = input("\nyou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in {"quit", "exit"}:
            break
        if user:
            run_turn(app, user, config)