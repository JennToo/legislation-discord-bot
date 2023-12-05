import asyncio
import pathlib
import json

import aiohttp

SESSION_YEAR = "2024"
SESSION_TYPE = "2024 Regular Session"
INTRODUCED_BILL_LINK_TEMPLATE = (
    "https://www.legislature.state.al.us/pdf/SearchableInstruments/2024RS/{}-int.pdf"
)


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

        for bill in result_json["data"]["allInstrumentOverviews"]:
            bills[bill["InstrumentNbr"]] = bill

        if len(result_json["data"]["allInstrumentOverviews"]) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        await asyncio.sleep(SCRAPE_PAGE_INTERVAL)

    return bills


def render_new_bill(bill):
    message = ["# New Bill"]
    for field, display_name in RELEVEANT_FIELDS.items():
        message.append(f" - **{display_name}**: {bill.get(field, 'UNKNOWN')}")
    message.append(
        "[Link to initial Bill Text]("
        + INTRODUCED_BILL_LINK_TEMPLATE.format(bill["InstrumentNbr"])
        + ") (Note: Bill text may take some time before available)"
    )
    return "\n".join(message)


def maybe_render_changed_bill(old_bill, new_bill):
    message = ["# Changed Bill"]
    message.append(f" - **Bill**: {old_bill['InstrumentNbr']}")

    found_change = False
    for field, display_name in RELEVEANT_FIELDS.items():
        old_value = old_bill[field]
        new_value = new_bill[field]
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
            changed, rendering = maybe_render_changed_bill(old_bills[bill_number], new_bills[bill_number])
            if changed:
                result.append(rendering)
    return result

def load_bill_database():
    return json.loads(BILL_DATABASE_FILE.read_text())


def save_bill_database(bills):
    BILL_DATABASE_FILE.write_text(json.dumps(bills, indent=4))


def dump_all():
    async def run():
        async with aiohttp.ClientSession() as session:
            old_bills = load_bill_database()
            new_bills = await get_bills(session)
            for message in render_all_bills(old_bills, new_bills):
                print(message)
                print("---")

    asyncio.run(run())


BILL_DATABASE_FILE = pathlib.Path("bill-database.json")
PAGE_SIZE = 25
SCRAPE_PAGE_INTERVAL = 5
RELEVEANT_FIELDS = {
    "InstrumentNbr": "Bill",
    "InstrumentSponsor": "Sponsor",
    "AssignedCommittee": "Committee",
    "PrefiledDate": "Prefiled Date",
    "FirstRead": "First Read",
    "CurrentStatus": "Status",
    "Subject": "Subject",
    "ShortTitle": "Title",
}
RAW_QUERY = '{allInstrumentOverviews(instrumentType:"B", instrumentNbr:"", body:"", sessionYear:"SESSION_YEAR", sessionType:"SESSION_TYPE", assignedCommittee:"", status:"", currentStatus:"", subject:"", instrumentSponsor:"", companionInstrumentNbr:"", effectiveDateCertain:"", effectiveDateOther:"", firstReadSecondBody:"", secondReadSecondBody:"", direction:"ASC"orderBy:"InstrumentNbr"limit:"PAGE_SIZE"offset:"OFFSET"  search:"" customFilters: {}companionReport:"", ){ ID,SessionYear,InstrumentNbr,InstrumentSponsor,SessionType,Body,Subject,ShortTitle,AssignedCommittee,PrefiledDate,FirstRead,CurrentStatus,LastAction,ActSummary,ViewEnacted,CompanionInstrumentNbr,EffectiveDateCertain,EffectiveDateOther,InstrumentType }}'
