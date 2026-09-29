"""Phase 0.3 / 11.2.5 — ADK 'hello world', verified against google-adk 2.9.0.

Known-good API shape for this version:
    LlmAgent(name, model, instruction)           # model: str (Gemini) or BaseLlm
    Runner(app_name, agent, session_service)
    await session_service.create_session(app_name=, user_id=, session_id=)
    async for ev in runner.run_async(user_id=, session_id=, new_message=Content)
        ev.is_final_response(), ev.content.parts[i].text

Runs offline by default with a tiny scripted BaseLlm; pass --real to use the
provider configured in .env (LLM_PROVIDER) via src.adk_layer.adk_runtime.
"""
import asyncio
import sys

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


class EchoLlm(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ready")]))


async def main(real: bool) -> None:
    if real:
        from dotenv import load_dotenv

        from src.adk_layer.adk_runtime import adk_model

        load_dotenv()
        model = adk_model()
    else:
        model = EchoLlm(model="echo")
    agent = LlmAgent(name="sanity_checker", model=model,
                     instruction="Reply with the single word 'ready'.")
    service = InMemorySessionService()
    runner = Runner(app_name="toy", agent=agent, session_service=service)
    session = await service.create_session(app_name="toy", user_id="u", session_id="s1")
    msg = types.Content(role="user", parts=[types.Part(text="are you there?")])
    async for ev in runner.run_async(user_id="u", session_id=session.id, new_message=msg):
        if ev.is_final_response():
            print("ADK agent replied:", ev.content.parts[0].text)


if __name__ == "__main__":
    asyncio.run(main(real="--real" in sys.argv))
