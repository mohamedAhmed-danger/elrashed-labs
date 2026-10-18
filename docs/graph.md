# 🧠 `graph/` — Agent Orchestration

The `graph/` package is the **decision and orchestration layer** of the laboratory conversational agent.

It receives the current `AgentState`, determines the user's intent, routes the request to the appropriate workflow, and returns the updated state and response.

---

## 🔄 Flow

```text
Incoming Message
       │
       ▼
 intent_node
       │
       ▼
 route_intent()
       │
 ┌─────┼──────────┬───────────┐
 ▼     ▼          ▼           ▼
Booking Inquiry  Complaint   Direct
  │      │          │           │
  ▼      ▼          ▼           ▼
 RAG    RAG     Complaint     Direct
  │      │       Node          Node
  ▼      ▼          │           │
Booking Inquiry     │           │
 Node    Node       │           │
  └──────┴──────────┴───────────┘
             │
             ▼
            END
```

`labresults` follows a separate deterministic path through `result_node` without requiring an LLM call.

---

## 🧩 Main Components

| Component                 | Responsibility                                          |
| ------------------------- | ------------------------------------------------------- |
| `graph.py`                | Defines the LangGraph workflow and conditional routing. |
| `state.py`                | Defines the shared `AgentState`.                        |
| `response.py`             | Defines the final agent response structure.             |
| `nodes/intent_node.py`    | Classifies the user's intent.                           |
| `nodes/rag_node.py`       | Retrieves relevant laboratory knowledge.                |
| `nodes/inquiry_node.py`   | Handles laboratory information requests.                |
| `nodes/booking_node.py`   | Handles home-visit booking.                             |
| `nodes/complaint_node.py` | Handles customer complaints.                            |
| `nodes/direct_node.py`    | Handles general conversation.                           |
| `nodes/result_node.py`    | Handles laboratory result retrieval.                    |
| `tools/`                  | Provides agent-triggered actions.                       |
| `prompts/`                | Contains node-specific LLM prompts.                     |

---

## 🧠 AgentState

`AgentState` is the shared state passed between graph nodes.

It contains the main areas of:

```text
Platform Context
Conversation State
Intent / Routing
RAG Context
Booking State
Complaint State
Usage Metrics
```

Nodes return **partial state updates**, which LangGraph merges into the current state.

---

## 🔎 RAG

RAG is used by workflows that require laboratory knowledge.

```text
User Query
    │
    ▼
Query Refinement
    │
    ▼
Hybrid Retrieval
    │
    ▼
RAG Context
    │
    ▼
Domain Node
```

The retrieval layer is shared by domain workflows that require laboratory data.

---

## 💾 Side Effects

The graph orchestrates domain actions, while dedicated tools and services handle external operations.

```text
Graph Node
    │
    ▼
   Tool
    │
    ▼
 Service
    │
    ▼
Database / External System
```

Examples include:

* Saving home-visit bookings.
* Saving complaints.
* Generating booking-related data.

---

## 📤 Output

The graph produces an updated `AgentState` containing the final response and workflow-specific results.

Common outputs include:

```text
response
booking_saved
booking_reference
booking_data
complaint_saved
usage metrics
```

---

## 🔗 Entry Point

The graph is executed from:

```python
services/message_processor.py::run_agent()
```

`run_agent()` is responsible for:

1. Building the initial state.
2. Invoking the compiled graph.
3. Aggregating usage metrics.
4. Persisting the chat exchange.
5. Handling post-graph booking notifications.

---

## 📐 Responsibility Boundary

```text
graph/
    Decision + Orchestration

nodes/
    Intent-specific processing

tools/
    Agent-triggered actions

services/
    Business logic + external operations

rag/
    Knowledge retrieval

message_processor/
    Application entry point + post-processing
```

> **Core principle:** `graph/` decides **what should happen next**, while tools and services handle **how external actions are performed**.
