import asyncio
import pathlib
import json
import logging
from copy import deepcopy

import aiohttp
import arrow

SESSION_YEAR = "2025"
SESSION_TYPE = "2025 Regular Session"
INTRODUCED_BILL_LINK_TEMPLATE = (
    "https://www.legislature.state.al.us/pdf/SearchableInstruments/2025RS/{}-int.pdf"
)
CONFIG = pathlib.Path("./config.json")


async def graphql(session, query):
    async with session.post(
        "https://alison.legislature.state.al.us/graphql",
        json=query,
    ) as result:
        result.raise_for_status()
        result_json = await result.json()
    return result_json


async def get_meetings(session):
    result_json = await graphql(session, BASE_QUERY_MEETING)
    return result_json["data"]["meetings"]["data"]


async def get_meetings_by_bill(all_meetings, config):
    meetings = {}
    for meeting_detail in all_meetings:
        for agenda_item in meeting_detail["agendaItems"]:
            if agenda_item["instrumentNbr"] in config["bills-of-interest"]:
                data = deepcopy(agenda_item)
                for field in AGENDA_ITEM_COPY_ITEMS:
                    data[field] = meeting_detail[field]
                meetings[agenda_item["instrumentNbr"]] = data
    return meetings


async def get_bills(session):
    bills = {}
    offset = 0
    while True:
        query = deepcopy(BASE_QUERY)
        query["variables"]["limit"] = PAGE_SIZE
        query["variables"]["offset"] = offset

        result_json = await graphql(session, query)

        for bill in result_json["data"]["instrumentOverviews"]["data"]:
            bills[bill["instrumentNbr"]] = bill

        offset += len(result_json["data"]["instrumentOverviews"]["data"])
        if (
            offset > result_json["data"]["instrumentOverviews"]["count"]
            or len(result_json["data"]["instrumentOverviews"]["data"]) < PAGE_SIZE
        ):
            break
        await asyncio.sleep(SCRAPE_PAGE_INTERVAL)

    return bills


def render_new_bill(bill, config):
    message = render_new_obj(
        bill, "Bill", RELEVANT_BILL_FIELDS, bill["instrumentNbr"], config
    )
    message.append(
        "[Link to initial Bill Text]("
        + INTRODUCED_BILL_LINK_TEMPLATE.format(bill["instrumentNbr"])
        + ") (Note: Bill text may take some time before available)"
    )
    return "\n".join(message)


def render_new_meeting(meeting, config):
    message = render_new_obj(
        meeting, "Meeting", RELEVANT_MEETING_FIELDS, meeting["instrumentNbr"], config
    )
    return "\n".join(message)


def render_new_obj(obj, name, fields, id_, config):
    message = [f"# New {name}"]
    if id_ in config["bills-of-interest"]:
        message = [f"# \u26a0 New {name} for Bill of Interest \u26a0"]
    for field, display_name in fields.items():
        value = obj.get(field, "UNKNOWN")
        if field == "startDate":
            value = discord_date(value)
        message.append(f" - **{display_name}**: {value}")
    return message


def maybe_render_changed_bill(old_bill, new_bill, config):
    return maybe_render_changed_obj(
        old_bill,
        new_bill,
        "Bill",
        RELEVANT_BILL_FIELDS,
        old_bill["instrumentNbr"],
        config,
    )


def maybe_render_changed_meeting(old_meeting, new_meeting, config):
    return maybe_render_changed_obj(
        old_meeting,
        new_meeting,
        "Meeting",
        RELEVANT_MEETING_FIELDS,
        old_meeting["instrumentNbr"],
        config,
    )


def maybe_render_changed_obj(old_obj, new_obj, name, fields, id_, config):
    message = [f"## Changed {name}"]
    if id_ in config["bills-of-interest"]:
        message = [f"# \u26a0 Changed {name} of Interest \u26a0"]
    message.append(f" - **Bill**: {id_} - {new_obj.get('shortTitle')}")

    found_change = False
    for field, display_name in fields.items():
        old_value = old_obj[field]
        new_value = new_obj[field]
        if old_value != new_value:
            if field == "startDate":
                old_value = discord_date(old_value)
                new_value = discord_date(new_value)
            message.append(f" - **Previous {display_name}**: {old_value}")
            message.append(f" - **New {display_name}**: {new_value}")
            found_change = True

    return found_change, "\n".join(message)


def render_all_bills(old_bills, new_bills, config):
    result = []
    for bill_number in new_bills:
        if bill_number not in old_bills:
            result.append(render_new_bill(new_bills[bill_number], config))
        else:
            changed, rendering = maybe_render_changed_bill(
                old_bills[bill_number], new_bills[bill_number], config
            )
            if changed:
                result.append(rendering)
    return result


def render_all_meetings(old_meetings, new_meetings, config):
    result = []
    for bill_number in new_meetings:
        if bill_number not in old_meetings:
            result.append(render_new_meeting(new_meetings[bill_number], config))
        else:
            changed, rendering = maybe_render_changed_meeting(
                old_meetings[bill_number], new_meetings[bill_number], config
            )
            if changed:
                result.append(rendering)
    return result


def render_bills_summary(bills, config):
    result = "## Status\n"
    for bill_id in config["bills-of-interest"]:
        bill = bills[bill_id]
        result += f"**{bill_id}**: ({bill['sponsor']}) {bill['shortTitle'][:40]}\n"
        result += f"- S:{bill['currentStatus']}\n"
        result += f"- Com:{bill['assignedCommittee']}\n"
        result += "\n"
    result = (
        result.replace("House of Origin", "HoO")
        .replace("Second", "2nd")
        .replace("Committee", "Com")
        .replace("(House)", "(H)")
        .replace("(Senate)", "(S)")
    )
    return result


def render_meetings_summary(meetings, config):
    result = "## Meetings\n"
    found_any = False
    for bill_id in config["bills-of-interest"]:
        if bill_id not in meetings:
            continue
        found_any = True
        meeting = meetings[bill_id]
        result += (
            f"**{bill_id}**: ({meeting['sponsor']}) {meeting['shortTitle'][:50]}\n"
        )
        result += f"- **C:** {meeting['committee']}\n"
        result += f"- **Loc:** {meeting['location']}\n"
        result += f"- **Time:** {discord_date(meeting['startDate'])}\n"
        result += f"- **PubHear:** {meeting['hasPublicHearing']}\n"
        result += "\n"
    if not found_any:
        result += "No meetings for relevant bills found\n"
    return result


def discord_date(iso_str):
    try:
        return f"<t:{int(arrow.get(iso_str).timestamp())}>"
    except arrow.parser.ParserError:
        return iso_str


def load_bill_database():
    return json.loads(BILL_DATABASE_FILE.read_text())


def save_bill_database(bills):
    BILL_DATABASE_FILE.write_text(json.dumps(bills, indent=4))


def load_meeting_database():
    return json.loads(MEETING_DATABASE_FILE.read_text())


def save_meeting_database(meetings):
    MEETING_DATABASE_FILE.write_text(json.dumps(meetings, indent=4))


def load_config():
    return json.loads(CONFIG.read_text())


def save_config(config):
    return CONFIG.write_text(json.dumps(config, indent=4))


def dump_all():
    async def run():
        async with aiohttp.ClientSession() as session:
            config = load_config()
            old_meetings = load_meeting_database()
            new_meetings = await get_meetings_by_bill(session, config)
            for message in render_all_meetings(old_meetings, new_meetings, config):
                print(message)
                print("---")
            save_meeting_database(new_meetings)
            old_bills = load_bill_database()
            new_bills = await get_bills(session)
            for message in render_all_bills(old_bills, new_bills, config):
                print(message)
                print("---")
            save_bill_database(new_bills)

    asyncio.run(run())


BILL_DATABASE_FILE = pathlib.Path("bill-database.json")
MEETING_DATABASE_FILE = pathlib.Path("meeting-database.json")
PAGE_SIZE = 25
SCRAPE_PAGE_INTERVAL = 5
RELEVANT_BILL_FIELDS = {
    "instrumentNbr": "Bill",
    "sponsor": "Sponsor",
    "assignedCommittee": "Committee",
    "prefiledDate": "Prefiled Date",
    "firstReadDate": "First Read",
    "currentStatus": "Status",
    "subject": "Subject",
    "shortTitle": "Title",
}
AGENDA_ITEM_COPY_ITEMS = {"committee", "body", "title", "location", "startDate"}
RELEVANT_MEETING_FIELDS = {
    "instrumentNbr": "Bill",
    "shortTitle": "Title",
    "sponsor": "Sponsor",
    "committee": "Committee",
    "body": "Body",
    "hasPublicHearing": "Public Hearing Requested",
    "title": "Meeting",
    "location": "Location",
    "startDate": "Date",
}
BASE_QUERY = {
    "operationName": "bills",
    "query": """query bills($googleId: ID, $category: String, $instrumentType: InstrumentType, $sessionAbbreviation: String, $order: Order = [
"sessionAbbreviation", 
"DESC"], $offset: Int, $limit: Int, $where: InstrumentOverviewWhere! = {}, $search: String) {
  instrumentOverviews(
    googleId: $googleId
    category: $category
    where: [{sessionAbbreviation: {eq: $sessionAbbreviation}, instrumentType: {eq: $instrumentType}}, $where]
    order: $order
    limit: $limit
    offset: $offset
    search: $search
  ) {
    data {
      ...billModalDataFragment
      id
      sessionYear
      instrumentNbr
      sponsor
      sessionType
      body
      subject
      shortTitle
      assignedCommittee
      allCommittees
      prefiledDate
      firstReadDate
      currentStatus
      lastAction
      actSummary
      viewEnacted
      companionInstrumentNbr
      effectiveDateCertain
      effectiveDateOther
      instrumentType
      __typename
    }
    count
    __typename
  }
}
fragment billModalDataFragment on InstrumentOverview {
  id
  instrumentType
  sessionAbbreviation
  sessionType
  instrumentNbr
  actSummary
  effectiveDateCertain
  effectiveDateOther
  __typename
}""",
    "variables": {
        "instrumentType": "B",
        "limit": 15,
        "offset": 0,
        "sessionAbbreviation": "2025RS",
        "where": {},
    },
}
BASE_QUERY_MEETING = {
    "operationName": "meetings",
    "query": """
query meetings($body: OrganizationBody, $managedInLinx: Boolean, $autoScroll: Boolean!) {
  meetings(
    where: {body: {eq: $body}, startDate: {gteToday: true}, managedInLinx: {eq: $managedInLinx}}
  ) {
    data {
      id
      startDate
      startTime
      location
      title
      description
      body
      hasPublicHearing
      hasLiveStream
      committee
      agendaUrl
      agendaItems @skip(if: $autoScroll) {
        id
        sessionType
        sessionYear
        instrumentNbr
        shortTitle
        matter
        recommendation
        hasPublicHearing
        sponsor
        __typename
      }
      __typename
    }
    count
    __typename
  }
}
    """,
    "variables": {"autoScroll": False},
}

if __name__ == "__main__":
    dump_all()
