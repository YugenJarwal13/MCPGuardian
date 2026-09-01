"""Phase 0.3 — ADK 'hello world'.

NOTE: ADK's runner/session API has moved between releases. Treat this as a
target shape, not a copy-paste guarantee — cross-check against the version that
``pip show google-adk`` reports (see google.github.io/adk-docs). The goal of
this step is only to confirm an ADK Agent responds end-to-end.
"""
import asyncio

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner


def build_agent() -> Agent:
    return Agent(
        name="sanity_checker",
        model="gemini-2.5-flash",  # swap for your configured provider's model
        instruction="Reply with the single word 'ready'.",
    )


async def main() -> None:
    agent = build_agent()
    runner = InMemoryRunner(agent=agent)
    # The exact run-turn API differs across ADK versions. As of recent releases:
    #   session = await runner.session_service.create_session(app_name=..., user_id=...)
    #   async for event in runner.run_async(user_id=..., session_id=..., new_message=...):
    #       print(event)
    # Consult the installed version's quickstart and fill in the run loop.
    print("ADK agent constructed:", runner.agent.name)


if __name__ == "__main__":
    asyncio.run(main())
