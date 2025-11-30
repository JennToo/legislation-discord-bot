import os
import asyncio
import logging
import datetime
import re
import pathlib

import discord
import discord.app_commands
import aiohttp
import aiojobs

from . import bills

MESSAGE_SEND_COOLDOWN = 1
FULL_SCAN_INTERVAL = 15 * 60
MOTD = """
_In the distance, the sound of a wretched and horrible machine churns to life._

## Bills for the 2026 Session begin here

As a reminder, each server can maintain a list of bills-of-interest with the /mark and /unmark commands.

View the status of marked bills with /status

For marked bills, meetings notifications will be generated (assuming they are marked correctly in the website)

The polling interval for new/updated bills will remain low until the session gets closer.

For bot issues please contact @jenntoo
""".strip()
MOTD_VERSION = 1

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

        for server in config["servers"]:
            if server.get("motd", 0) >= MOTD_VERSION:
                continue
            if not server.get("dev_mode"):
                continue
            channel = client.get_channel(int(server["channel_id"]))
            await channel.send(MOTD)
            await asyncio.sleep(MESSAGE_SEND_COOLDOWN)
            server["motd"] = MOTD_VERSION
            bills.save_config(config)

        logger.info("Scraping bills")
        new_bills = await bills.get_bills(session)
        old_meetings = bills.load_meeting_database()
        logger.info("Scraping meetings")
        new_meetings = await bills.get_meetings(session)

        for server in config["servers"]:
            if not server["enabled"]:
                continue
            if not server.get("dev_mode"):
                continue
            if len(new_bills) < (len(old_bills) / 2):
                logger.info(
                    "Sanity check failure. Weird change, ignoring %s", new_bills
                )
                return
            old_server_meetings = old_meetings.get(server["server_id"], {})
            new_server_meetings = await bills.get_meetings_by_bill(new_meetings, server)
            for message in bills.render_all_meetings(
                old_server_meetings, new_server_meetings, server
            ) + bills.render_all_bills(old_bills, new_bills, server):
                logger.info("New message: %s", message)
                channel = client.get_channel(int(server["channel_id"]))
                await channel.send(message[:1950])
                await asyncio.sleep(MESSAGE_SEND_COOLDOWN)
            bills.save_bill_database(new_bills)
            old_meetings[server["server_id"]] = new_server_meetings

        bills.save_meeting_database(old_meetings)
    logger.info("Check done")


intents = discord.Intents.default()
intents.message_content = True
client = Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


@tree.command(name="status", description="Status of bills-of-interest")
async def status_command(interaction):
    config = bills.load_config()

    bill_db = bills.load_bill_database()
    meetings_db = bills.load_meeting_database()
    db_update = datetime.datetime.fromtimestamp(
        bills.BILL_DATABASE_FILE.stat().st_mtime, tz=datetime.timezone.utc
    )

    servers_by_id = {x["server_id"]: x for x in config["servers"]}
    server_config = servers_by_id.get(str(interaction.guild_id))
    if not server_config:
        summary = "(No bills or meetings can be included because the config for this server wasn't found)\n"
    else:
        summary = bills.render_bills_summary(bill_db, server_config)
        summary += bills.render_meetings_summary(meetings_db, server_config)

    message = f"{summary}_Last DB Update: <t:{int(db_update.timestamp())}>_"
    if len(message) > 2000:
        message = f"{message[:1950]}\n(Truncated, too long)"
    await interaction.response.send_message(message)


BILL_REGEX = re.compile(r"^(H|S)B\d+$")


@tree.command(name="mark", description="Mark a bill for following")
async def mark(interaction, bill: str):
    config = bills.load_config()
    servers_by_id = {x["server_id"]: x for x in config["servers"]}
    server_config = servers_by_id.get(str(interaction.guild_id))
    if not BILL_REGEX.match(bill):
        message = f"Invalid bill {bill}"
    elif not server_config:
        message = "Error: this server is not configured for the bot"
    else:
        if bill not in server_config["bills-of-interest"]:
            server_config["bills-of-interest"].append(bill)
        message = (
            f"Bill {bill} is now marked as a bill of interest for this server.\n"
            f"All tracked bills for this server: {', '.join(server_config['bills-of-interest'])}"
        )
        bills.save_config(config)
    await interaction.response.send_message(message)


@tree.command(name="unmark", description="Unmark a bill for following")
async def unmark(interaction, bill: str):
    config = bills.load_config()
    servers_by_id = {x["server_id"]: x for x in config["servers"]}
    server_config = servers_by_id.get(str(interaction.guild_id))
    if not BILL_REGEX.match(bill):
        message = f"Invalid bill ID {bill}"
    elif not server_config:
        message = "Error: this server is not configured for the bot"
    else:
        server_config["bills-of-interest"] = [
            x for x in server_config["bills-of-interest"] if x != bill
        ]
        message = (
            f"Bill {bill} is has been unmarked as a bill of interest for this server.\n"
            f"All tracked bills for this server: {', '.join(server_config['bills-of-interest'])}"
        )
        bills.save_config(config)
    await interaction.response.send_message(message)


def main():
    client.run(os.environ["LEGIBOT_TOKEN"])
