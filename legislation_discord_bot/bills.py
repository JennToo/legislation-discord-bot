import asyncio
import pathlib
import json

import aiohttp

SESSION_YEAR = "2024"
SESSION_TYPE = "2024 Regular Session"
INTRODUCED_BILL_LINK_TEMPLATE = (
    "https://www.legislature.state.al.us/pdf/SearchableInstruments/2024RS/{}-int.pdf"
)
CONFIG = json.loads(pathlib.Path("./config.json").read_text())


async def graphql(session, query):
    async with session.post(
        "https://gql.api.alison.legislature.state.al.us/graphql",
        json={
            "query": query,
            "operationName": "",
            "variables": [],
        },
        headers={
            "Authorization": "Bearer undefined",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": "https://alison.legislature.state.al.us",
            "Referer": "https://alison.legislature.state.al.us/",
        },
    ) as result:
        result.raise_for_status()
        result_json = await result.json()
    return result_json


async def get_meetings_by_bill(session):
    result_json = await graphql(session, RAW_QUERY_MEETING)

    meetings = {}
    for meeting_detail in result_json["data"]["hearingsMeetingsDetails"]:
        if meeting_detail["InstrumentNbr"] in CONFIG["bills-of-interest"]:
            meetings[meeting_detail["InstrumentNbr"]] = meeting_detail
    return meetings


async def get_bills(session):
    bills = {}
    offset = 0
    while True:
        query = RAW_QUERY
        for key, value in {
            "PAGE_SIZE": str(PAGE_SIZE),
            "OFFSET": str(offset),
            "SESSION_TYPE": SESSION_TYPE,
            "SESSION_YEAR": SESSION_YEAR,
        }.items():
            query = query.replace(key, value)

        result_json = await graphql(session, query)

        for bill in result_json["data"]["allInstrumentOverviews"]:
            bills[bill["InstrumentNbr"]] = bill

        if len(result_json["data"]["allInstrumentOverviews"]) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
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
PAGE_SIZE = 25
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
RAW_QUERY = '{allInstrumentOverviews(instrumentType:"B", instrumentNbr:"", body:"", sessionYear:"SESSION_YEAR", sessionType:"SESSION_TYPE", assignedCommittee:"", status:"", currentStatus:"", subject:"", instrumentSponsor:"", companionInstrumentNbr:"", effectiveDateCertain:"", effectiveDateOther:"", firstReadSecondBody:"", secondReadSecondBody:"", direction:"ASC"orderBy:"InstrumentNbr"limit:"PAGE_SIZE"offset:"OFFSET"  search:"" customFilters: {}companionReport:"", ){ ID,SessionYear,InstrumentNbr,InstrumentSponsor,SessionType,Body,Subject,ShortTitle,AssignedCommittee,PrefiledDate,FirstRead,CurrentStatus,LastAction,ActSummary,ViewEnacted,CompanionInstrumentNbr,EffectiveDateCertain,EffectiveDateOther,InstrumentType }}'
RAW_QUERY_MEETING = '{hearingsMeetingsDetails(eventType:"meeting", body:"", keyword:"", toDate:"3000-02-10", fromDate:"2024-02-10", sortTime:"", direction:"ASC", orderBy:"SortTime", ){EventDt,EventTm,Location,EventTitle,EventDesc,Body,DeadlineDt,PublicHearing,LiveStream,Committee,AgendaUrl,SortTime,OidMeeting, Sponsor, InstrumentNbr, ShortTitle, OidInstrument, SessionType, SessionYear}}'
