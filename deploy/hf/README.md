---
title: MCP Guardian
emoji: 🛡️
colorFrom: orange
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: Guards AI agents against poisoned MCP tools
---

# MCP Guardian

A security gateway that sits between an AI agent and the MCP tool servers it uses, inspecting tool
descriptions and responses with CrewAI inspectors, a Google ADK behaviour layer and an A2A case manager.

This Space serves the web app: an overview with the benchmark results, an animated live demo on the DVMCP
lab, and a page that checks any public MCP server. Source and full report:
https://github.com/YugenJarwal13/MCPGuardian
