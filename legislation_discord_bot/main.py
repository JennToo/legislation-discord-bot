import os
import asyncio
import logging

import discord
import aiohttp
import aiojobs

from . import bills

ALLOWED_CHANNELS = [
    # 535528612502437889,  # Testing channel
    1181424039756050514,  # Trans North AL channel
    1193332824846127275,  # readfree
]
MESSAGE_SEND_COOLDOWN = 15
FULL_SCAN_INTERVAL = 15 * 60

intents = discord.Intents.default()
intents.message_content = True
logger = logging.getLogger("discord")


class Client(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.scheduler = None

    async def on_ready(self):
        self.scheduler = aiojobs.Scheduler()
        await self.scheduler.spawn(check_forever(self))


async def check_forever(client):
    while True:
        try:
            await check_for_updates(client)
        except Exception:
            logging.exception("Ignoring exception")
        await asyncio.sleep(FULL_SCAN_INTERVAL)


async def check_for_updates(client):
    logger.info("Checking for updates")
    async with aiohttp.ClientSession() as session:
        old_bills = bills.load_bill_database()
        new_bills = await bills.get_bills(session)
        if len(new_bills) < (len(old_bills) / 2):
            logger.info("Sanity check failure. Weird change, ignoring %s", new_bills)
            return
        for message in bills.render_all_bills(old_bills, new_bills):
            logger.info("New message: %s", message)
            for channel_id in ALLOWED_CHANNELS:
                channel = client.get_channel(channel_id)
                await channel.send(message)
                await asyncio.sleep(MESSAGE_SEND_COOLDOWN)
        bills.save_bill_database(new_bills)
    logger.info("Check done")


def main():
    client = Client(intents=intents)
    client.run(os.environ["LEGIBOT_TOKEN"])
