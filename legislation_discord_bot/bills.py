import asyncio
import pathlib
import json
import logging
from copy import deepcopy

import aiohttp

SESSION_YEAR = "2025"
SESSION_TYPE = "2025 Regular Session"
INTRODUCED_BILL_LINK_TEMPLATE = (
    "https://www.legislature.state.al.us/pdf/SearchableInstruments/2025RS/{}-int.pdf"
)
CONFIG = json.loads(pathlib.Path("./config.json").read_text())


async def graphql(session, query):
    async with session.post(
        "https://alison.legislature.state.al.us/graphql",
        json=query,
    ) as result:
        result.raise_for_status()
        result_json = await result.json()
    return result_json


async def get_meetings_by_bill(session):
    result_json = await graphql(session, BASE_QUERY_MEETING)

    meetings = {}
    for meeting_detail in result_json["data"]["meetings"]["data"]:
        for agenda_item in meeting_detail["agendaItems"]:
            if agenda_item in CONFIG["bills-of-interest"]:
                meetings[agenda_item] = meeting_detail
    return meetings


async def get_bills(session):
    bills = {}
    offset = 0
    while True:
        query = deepcopy(BASE_QUERY)
        query["variables"]["limit"] = PAGE_SIZE
        query["variables"]["offset"] = offset

        result_json = await graphql(session, query)

        for bill in result_json["data"]["data"]:
            bills[bill["InstrumentNbr"]] = bill

        if len(result_json["data"]["data"]) < PAGE_SIZE:
            break
        offset += len(result_json["data"]["data"])
        await asyncio.sleep(SCRAPE_PAGE_INTERVAL)

    return bills


def render_new_bill(bill):
    message = render_new_obj(bill, "Bill", RELEVANT_BILL_FIELDS, bill["InstrumentNbr"])
    message.append(
        "[Link to initial Bill Text]("
        + INTRODUCED_BILL_LINK_TEMPLATE.format(bill["InstrumentNbr"])
        + ") (Note: Bill text may take some time before available)"
    )
    return "\n".join(message)


def render_new_meeting(meeting):
    message = render_new_obj(
        meeting, "Meeting", RELEVANT_MEETING_FIELDS, meeting["InstrumentNbr"]
    )
    return "\n".join(message)


def render_new_obj(obj, name, fields, id_):
    message = [f"# New {name}"]
    if id_ in CONFIG["bills-of-interest"]:
        message = [f"# \u26a0 New {name} for Bill of Interest \u26a0"]
    for field, display_name in fields.items():
        message.append(f" - **{display_name}**: {obj.get(field, 'UNKNOWN')}")
    return message


def maybe_render_changed_bill(old_bill, new_bill):
    return maybe_render_changed_obj(
        old_bill, new_bill, "Bill", RELEVANT_BILL_FIELDS, old_bill["InstrumentNbr"]
    )


def maybe_render_changed_meeting(old_meeting, new_meeting):
    return maybe_render_changed_obj(
        old_meeting,
        new_meeting,
        "Meeting",
        RELEVANT_MEETING_FIELDS,
        old_meeting["InstrumentNbr"],
    )


def maybe_render_changed_obj(old_obj, new_obj, name, fields, id_):
    message = [f"## Changed {name}"]
    if id_ in CONFIG["bills-of-interest"]:
        message = [f"# \u26a0 Changed {name} of Interest \u26a0"]
    message.append(f" - **Bill**: {id_} - {new_obj.get('ShortTitle')}")

    found_change = False
    for field, display_name in fields.items():
        old_value = old_obj[field]
        new_value = new_obj[field]
        if old_value != new_value:
            message.append(f" - **Previous {display_name}**: {old_value}")
            message.append(f" - **New {display_name}**: {new_value}")
            found_change = True

    return found_change, "\n".join(message)


def render_all_bills(old_bills, new_bills):
    result = []
    for bill_number in new_bills:
        if bill_number not in old_bills:
            result.append(render_new_bill(new_bills[bill_number]))
        else:
            changed, rendering = maybe_render_changed_bill(
                old_bills[bill_number], new_bills[bill_number]
            )
            if changed:
                result.append(rendering)
    return result


def render_all_meetings(old_meetings, new_meetings):
    result = []
    for bill_number in new_meetings:
        if bill_number not in old_meetings:
            result.append(render_new_meeting(new_meetings[bill_number]))
        else:
            changed, rendering = maybe_render_changed_meeting(
                old_meetings[bill_number], new_meetings[bill_number]
            )
            if changed:
                result.append(rendering)
    return result


def load_bill_database():
    return json.loads(BILL_DATABASE_FILE.read_text())


def save_bill_database(bills):
    BILL_DATABASE_FILE.write_text(json.dumps(bills, indent=4))


def load_meeting_database():
    return json.loads(MEETING_DATABASE_FILE.read_text())


def save_meeting_database(meetings):
    MEETING_DATABASE_FILE.write_text(json.dumps(meetings, indent=4))


def dump_all():
    async def run():
        async with aiohttp.ClientSession() as session:
            old_meetings = load_meeting_database()
            new_meetings = await get_meetings_by_bill(session)
            for message in render_all_meetings(old_meetings, new_meetings):
                print(message)
                print("---")
            save_meeting_database(new_meetings)
            old_bills = load_bill_database()
            new_bills = await get_bills(session)
            for message in render_all_bills(old_bills, new_bills):
                print(message)
                print("---")
            save_bill_database(new_bills)

    asyncio.run(run())


BILL_DATABASE_FILE = pathlib.Path("bill-database.json")
MEETING_DATABASE_FILE = pathlib.Path("meeting-database.json")
PAGE_SIZE = 2000
SCRAPE_PAGE_INTERVAL = 5
RELEVANT_BILL_FIELDS = {
    "InstrumentNbr": "Bill",
    "InstrumentSponsor": "Sponsor",
    "AssignedCommittee": "Committee",
    "PrefiledDate": "Prefiled Date",
    "FirstRead": "First Read",
    "CurrentStatus": "Status",
    "Subject": "Subject",
    "ShortTitle": "Title",
}
RELEVANT_MEETING_FIELDS = {
    "InstrumentNbr": "Bill",
    "ShortTitle": "Title",
    "Sponsor": "Sponsor",
    "Committee": "Committee",
    "Body": "Body",
    "PublicHearing": "Public Hearing Requested",
    "EventTitle": "Meeting",
    "Location": "Location",
    "EventDt": "Date",
    "EventTm": "Time",
}
BASE_QUERY = {
    "operationName": "bills",
    "query": "query bills($googleId: String, $category: String, $sessionYear: String, $sessionType: String, $direction: String, $orderBy: String, $offset: Int, $limit: Int, $filters: InstrumentOverviewInput! = {}, $search: String, $instrumentType: String) {\n  data: allInstrumentOverviews(\n    googleId: $googleId\n    category: $category\n    instrumentType: $instrumentType\n    sessionYear: $sessionYear\n    sessionType: $sessionType\n    direction: $direction\n    orderBy: $orderBy\n    limit: $limit\n    offset: $offset\n    customFilters: $filters\n    search: $search\n  ) {\n    ...billModalDataFragment\n    ID\n    SessionYear\n    InstrumentNbr\n    InstrumentSponsor\n    SessionType\n    Body\n    Subject\n    ShortTitle\n    AssignedCommittee\n    PrefiledDate\n    FirstRead\n    CurrentStatus\n    LastAction\n    ActSummary\n    ViewEnacted\n    CompanionInstrumentNbr\n    EffectiveDateCertain\n    EffectiveDateOther\n    InstrumentType\n    __typename\n  }\n  count: allInstrumentOverviewsCount(\n    googleId: $googleId\n    category: $category\n    instrumentType: $instrumentType\n    sessionYear: $sessionYear\n    sessionType: $sessionType\n    customFilters: $filters\n    search: $search\n  )\n}\nfragment billModalDataFragment on InstrumentOverviews {\n  ID\n  InstrumentType\n  SessionType\n  SessionYear\n  InstrumentNbr\n  ActSummary\n  __typename\n}",
    "variables": {
        "direction": "DESC",
        "filters": {},
        "instrumentType": "B",
        "limit": 15,
        "offset": 0,
        "orderBy": "SessionYear",
        "sessionType": "2025 Regular Session",
    },
}
BASE_QUERY_MEETING = {
    "operationName": "meetings",
    "query": "query meetings($body: OrganizationBody, $managedInLinx: Boolean, $autoScroll: Boolean!) {\n  meetings(\n    where: {body: {eq: $body}, startDate: {gteToday: true}, managedInLinx: {eq: $managedInLinx}}\n  ) {\n    data {\n      id\n      startDate\n      startTime\n      location\n      title\n      description\n      body\n      hasPublicHearing\n      hasLiveStream\n      committee\n      agendaUrl\n      agendaItems @skip(if: $autoScroll) {\n        id\n        sessionType\n        sessionYear\n        instrumentNumber\n        shortTitle\n        matter\n        recommendation\n        hasPublicHearing\n        sponsor\n        __typename\n      }\n      __typename\n    }\n    count\n    __typename\n  }\n}",
    "variables": {"autoScroll": False},
}

if __name__ == "__main__":
    dump_all()
