import json
import os
from functools import reduce

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(f'{root}/database.json', 'r') as f:
    database = json.load(f)

with open(f'{root}/json/plugins.json', 'r') as f:
    plugins = json.load(f)


def process_plugin(plugin):
    return {
        "name":
        plugin["full_name"],
        "shorthand":
        plugin["full_name"].split("/")[1],
        "dependencies":
        reduce(lambda x, y: x + y, plugin.get("dependencies", ["None"])),
        "license":
        plugin["license"]["spdx_id"],
        "description":
        plugin.get("description") or "No Description",
    }


unique_crossref_plugins = [
    plugin for plugin in list(
        map(process_plugin, [
            plugin for plugin in database.values() if
            plugin["stargazers_count"] > 250 and plugin["license"] is not None
        ])) if plugin["shorthand"] not in (
            {plugin["shorthand"]
             for plugin in plugins["plugins"]})
]

print(
    f"Found {len(unique_crossref_plugins)} unique plugins to cross-reference.")

with open(f'{root}/json/crossref.json', 'w') as f:
    json.dump({"plugins": unique_crossref_plugins}, f, indent=4)

print(
    "Advanced cross-referenced plugins have been successfully inscribed into the mystical crossref.json."
)
