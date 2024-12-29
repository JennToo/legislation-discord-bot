#!/usr/bin/env python3
import json
import pathlib

db = pathlib.Path("bill-database.json")
current = json.loads(db.read_text())
new_one = {}
for full_key, full_value in current.items():
    new_value = {}
    for key, value in full_value.items():
        if key.endswith("Date") or key.endswith("Read"):
            parts = list(full_value[key].split("/"))
            value = "-".join([parts[2], parts[0], parts[1]])
        new_value[key[0].lower() + key[1:]] = value
    new_one[full_key] = new_value
db.write_text(json.dumps(new_one, indent=4))
