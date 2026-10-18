from langgraph.graph import END, StateGraph

from graph.nodes.booking_node import booking_node
from graph.nodes.complaint_node import complaint_node
from graph.nodes.direct_node import direct_node
from graph.nodes.inquiry_node import inquiry_node
from graph.nodes.intent_node import intent_node
from graph.nodes.rag_node import rag_node
from graph.nodes.result_node import result_node
from graph.state import AgentState

import utils.trace_logger as trace_logger


__agent_graph = None


def route_intent(state: AgentState) -> str:
    """Return the current intent string used for graph routing."""

    intent = state.get("intent") or "direct"

    # تحويل الـ Enum لـ string صريح لو كان Enum object
    if hasattr(intent, "value"):
        intent_str = str(intent.value)
    else:
        intent_str = str(intent)

    trace_logger.step(
        "ROUTING",
        f"GRAPH CONDITIONAL ROUTING -> {intent_str.upper()}",
        input_data={"intent": intent_str},
        output_data={"target_branch": intent_str},
    )

    return intent_str


def build_graph():
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("intent", intent_node)
    graph.add_node("rag", rag_node)
    graph.add_node("booking", booking_node)
    graph.add_node("complaint", complaint_node)
    graph.add_node("inquiry", inquiry_node)
    graph.add_node("direct", direct_node)
    graph.add_node("labresults", result_node)

    # Entry point
    graph.set_entry_point("intent")

    # Intent → Workflow (تم تغيير المفتاح من 'booking' لـ 'visit' ليتطابق مع الـ Enum)
    graph.add_conditional_edges(
        "intent",
        route_intent,
        {
            "visit": "rag",            # 👈 تعديل المفتاح لـ visit
            "inquiry": "rag",
            "complaint": "complaint",
            "direct": "direct",
            "labresults": "labresults",
        },
    )

    # RAG → Workflow
    graph.add_conditional_edges(
        "rag",
        route_intent,
        {
            "visit": "booking",        # 👈 تعديل المفتاح لـ visit
            "inquiry": "inquiry",
        },
    )

    # Workflows → End
    graph.add_edge("booking", END)
    graph.add_edge("complaint", END)
    graph.add_edge("inquiry", END)
    graph.add_edge("direct", END)
    graph.add_edge("labresults", END)

    return graph.compile()


def get_agent_graph():
    global __agent_graph

    if __agent_graph is None:
        __agent_graph = build_graph()

    return __agent_graph