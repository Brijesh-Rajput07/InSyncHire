"""Agent Service (M6) -- owns the LangGraph agent nodes (later milestones:
M9/M10 wire the live interview pipeline graph, M6 builds the AI Ranking
Agent's graph) and the GuardrailService: the 5-layer defense-in-depth
wrapper every agent call goes through (Section: GUARDRAILS ARCHITECTURE).

This milestone (M6) delivers the GuardrailService as a correct, fully
unit-tested, standalone component -- no live LLM calls, no LangGraph
graph, no tenant DB persistence yet. Interview Service and Job Service
call into this service (directly, or via a future HTTP/queue boundary)
whenever agents are needed (Section 3: "Agent Service ... Called by
Interview Service and Job Service when agents are needed").
"""