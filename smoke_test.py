"""Verifica a ligacao ao Microsoft Foundry com o Agent Framework."""

import asyncio

from agent_framework import Agent
from agent_framework_foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    client = FoundryChatClient(credential=AzureCliCredential())
    agent = Agent(client, instructions="Responde numa frase curta.")
    result = await agent.run(
        "Diz olá e identifica-te como um agente de análise de futebol."
    )
    print(result)


asyncio.run(main())
