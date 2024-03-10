import json
import os
from functools import reduce

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def process_plugin(plugin):
    return {
        "name":
        plugin["full_name"],
        "shorthand":
        plugin["full_name"].split("/")[1],
        "dependencies":
        reduce(lambda x, y: x + y, plugin.get("dependencies", ["None"])),
        "license":
        plugin["license"]["spdx_id"] if plugin["license"] else None,
        "description":
        plugin.get("description", None),
    }


database = json.load(open('database.json', 'r'))
plugins = json.load(open(f'{root}/json/plugins.json', 'r'))

filtered_plugins = [
    plugin for plugin in database.values() if plugin["stargazers_count"] > 250
]

crossref_plugins = list(map(process_plugin, filtered_plugins))

with open(f'{root}/json/crossref.json', 'w') as f:
    json.dump({"plugins": crossref_plugins}, f, indent=4)

print("Cross-referenced plugins written to crossref.json.")
