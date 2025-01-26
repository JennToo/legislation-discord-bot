import os
import asyncio
import logging
import datetime

import discord
import discord.app_commands
import aiohttp
import aiojobs

from . import bills

ALLOWED_CHANNELS = [
    535528612502437889,  # Testing channel
    # 1181424039756050514,  # Trans North AL channel
    # 1193332824846127275,  # readfree
    # 1206065865485979689,  # LGBTQ+ Action Group
]
MESSAGE_SEND_COOLDOWN = 15
FULL_SCAN_INTERVAL = 15 * 60

logger = logging.getLogger("discord")


class Client(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.scheduler = None

    async def on_ready(self):
        await tree.sync()
        if self.scheduler is None:
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
        config = bills.load_config()
        old_bills = bills.load_bill_database()
        new_bills = await bills.get_bills(session)
        old_meetings = bills.load_meeting_database()
        new_meetings = await bills.get_meetings_by_bill(session, config)
        if len(new_bills) < (len(old_bills) / 2):
            logger.info("Sanity check failure. Weird change, ignoring %s", new_bills)
            return
        for message in bills.render_all_meetings(
            old_meetings, new_meetings, config
        ) + bills.render_all_bills(old_bills, new_bills, config):
            logger.info("New message: %s", message)
            for channel_id in ALLOWED_CHANNELS:
                channel = client.get_channel(channel_id)
                await channel.send(message)
            await asyncio.sleep(MESSAGE_SEND_COOLDOWN)
        bills.save_bill_database(new_bills)
        bills.save_meeting_database(new_meetings)
    logger.info("Check done")


intents = discord.Intents.default()
intents.message_content = True
client = Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


@tree.command(name="status", description="Status of bills-of-interest")
async def status_command(interaction):
    bill_db = bills.load_bill_database()
    summary = bills.render_bills_summary(bill_db)
    db_update = datetime.datetime.fromtimestamp(
        bills.BILL_DATABASE_FILE.stat().st_mtime, tz=datetime.timezone.utc
    )

    message = f"## Status of Bills of Interest\n{summary}_Last DB Update: {db_update.isoformat()}Z_"
    await interaction.response.send_message(message)


def main():
    client.run(os.environ["LEGIBOT_TOKEN"])
