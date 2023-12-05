import os
import asyncio

import discord
import aiohttp

from . import bills

ALLOWED_CHANNELS = [
    535528612502437889,  # Testing channel
    1181424039756050514, # Trans North AL channel
]
MESSAGE_SEND_COOLDOWN = 15

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")

    await check_for_updates()


async def check_for_updates():
    async with aiohttp.ClientSession() as session:
        old_bills = bills.load_bill_database()
        new_bills = await bills.get_bills(session)
        for message in bills.render_all_bills(old_bills, new_bills):
            print(message)
            for channel_id in ALLOWED_CHANNELS:
                channel = client.get_channel(channel_id)
                await channel.send(message)
                await asyncio.sleep(MESSAGE_SEND_COOLDOWN)
        bills.save_bill_database(new_bills)


def main():
    client.run(os.environ["LEGIBOT_TOKEN"])
