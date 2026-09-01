"""Phase 0.2 — CrewAI 'hello world'.

Proves the CrewAI environment + .env LLM credentials are wired correctly.
Run: ``python scratch/toy_crewai.py`` and confirm the output contains 'ready'.
This is a throwaway sanity check, not part of ``src/``.
"""
from crewai import Agent, Task, Crew

toy_agent = Agent(
    role="Sanity Checker",
    goal="Confirm the CrewAI environment is correctly configured.",
    backstory="You exist only to prove the pipeline works.",
)
toy_task = Task(
    description="Reply with the single word 'ready'.",
    expected_output="The word 'ready'.",
    agent=toy_agent,
)

if __name__ == "__main__":
    result = Crew(agents=[toy_agent], tasks=[toy_task]).kickoff()
    print(result)
