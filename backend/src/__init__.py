"""MCP Guardian - a security interception layer for Model Context Protocol tools.

Packages:
    mcp_gateway - the interception layer every MCP call routes through.
    crewai_layer - CrewAI reasoning/inspection crew (static + runtime auditors).
    adk_layer - Google ADK stateful enforcement and case management.
    a2a_bridge - CrewAI verdict -> A2A message -> ADK pipeline hop.
    data - test-data loaders (DVMCP, MCPTox, benign, custom).
    evaluation - metrics, ablation, and reporting.
    dashboard - Streamlit audit-trail viewer.
    demo_agent - end-to-end demo of an agent using Guardian-wrapped tools.
"""

import os as _os

# The A2A library emits a dozen internal spans per message (event queues, request handlers). They add cost and no
# information; the hop itself is traced by the pipeline. Must be set before the library is first imported.
_os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")
# Put the prompt and reply on ADK's model-call span (the behaviour judge), so Langfuse can show input and output.
# Credentials are masked by the tracing exporter before anything leaves the process.
_os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
_os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "SPAN_ONLY")
