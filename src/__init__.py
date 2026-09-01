"""MCP Guardian — a security interception layer for Model Context Protocol tools.

Packages:
    mcp_gateway   — the interception layer every MCP call routes through.
    crewai_layer  — CrewAI reasoning/inspection crew (static + runtime auditors).
    adk_layer     — Google ADK stateful enforcement and case management.
    a2a_bridge    — CrewAI verdict -> A2A message -> ADK pipeline hop.
    data          — test-data loaders (DVMCP, MCPTox, benign, custom).
    evaluation    — metrics, ablation, and reporting.
    dashboard     — Streamlit audit-trail viewer.
    demo_agent    — end-to-end demo of an agent using Guardian-wrapped tools.
"""
