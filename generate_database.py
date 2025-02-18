#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# File Name: generate_data.py

__orgname__ = "PlugNPlay"
__docformat__ = "numpy"
__version__ = "0.0.2"
import asyncio
import functools
import itertools as it
import json
import logging
import os

# stack and queue
import queue
import random
import time
from collections import Counter, defaultdict
from typing import Any, Callable, List

import requests
import tqdm
from icecream import ic
from joblib import Parallel, delayed
from rich.logging import RichHandler
from tqdm.contrib.logging import logging_redirect_tqdm

from models import BaseRequestResponse
import joblib.externals.loky
joblib.externals.loky.process_executor._MAX_MEMORY_LEAK_SIZE = int(3e10)

root = logging.getLogger()
if root.handlers:
    for h in root.handlers:
        root.removeHandler(h)()

FORMAT = "%(message)s"
logging.basicConfig(
    level="INFO", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)


def get_or_create_eventloop() -> Any:
    """
    Gets the current asyncio event loop. Asyncio only
    opens an event loop when called in the main thread,

    Returns
    -------
    the current or created asyncio event loop
    """
    try:
        return asyncio.get_event_loop()
    except RuntimeError as ex:
        if "There is no current event loop in thread" in str(ex):
            logging.info("Creating event loop")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return asyncio.get_event_loop()


def key_mapper(key):
    """
    helper for working with annoying dicts and lists of dicts
    runs a function over external iterable on a specific dict key

    Examples:
    --------

    >>> d = {'a':1, 'b':2}
    >>> d2 = {'a':0, 'b':2}
    >>> l = [0,2,3,4,5,6,7]
    >>> a_mapper = key_mapper('a')
    >>> b_mapper = key_mapper('b')
    >>> equals_l = b_mapper(lambda x,y: x == y, l)
    >>> equals_l(d)
    >>> # 0
    >>> equals_l(d2)
    >>> # 1

    Parameters
    ----------
    key : key to map a function over



    Returns
    -------
    cond_mapper : function which takes in a function which asserts a condition over an iterable, and returns a function which runs the supplied function over the supplied iterable and the input

    """

    def cond_mapper(fn, iterable):
        """

        Parameters
        ----------
        fn : a callable, which takes in 2 positional args, the first of which is supplied later on, and the second of which comes from the supplied iterable

        iterable : list of parameters to supply to fn


        Returns
        -------
        output : a function which takes in a dict, indexes it with previously supplied key, and compares that index to a previously supplied iterable

        """

        def output(d: dict):
            logging.info(ic.format(d))
            return sum(fn(d[key], x) if key in d.keys() else 0 for x in iterable)

        return output

    return cond_mapper


class ClientKeySwitcher:
    def __init__(self):
        self.client_keys = [
            {"id_env_var": "CLIENT_ID", "secret_env_var": "SECRET_ID"},
            {"id_env_var": "CLIENT_ID2", "secret_env_var": "SECRET_ID2"},
            {"id_env_var": "CLIENT_ID3", "secret_env_var": "SECRET_ID3"},
            {"id_env_var": "CLIENT_ID4", "secret_env_var": "SECRET_ID4"},
        ]

        self.current_index = random.randint(0, len(self.client_keys) - 1)
        self.client_id, self.client_secret = self.get_key()

    def get_key(self):
        current_keys = self.client_keys[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.client_keys)
        client_id = os.environ.get(current_keys["id_env_var"])
        client_secret = os.environ.get(current_keys["secret_env_var"])
        logging.critical(ic.format(f"Switching API Key -> Using Keys: {current_keys}"))
        return client_id, client_secret

    def switch_api_key(self):
        self.client_id, self.client_secret = self.get_key()


class GenerateData(ClientKeySwitcher):
    """

    Attributes
    ----------
    batch_size : batch size for asyncrhonous API calls.
    use_batches : whether or not batches are used
    user : the user
    user_fmt : formatted version of the user
    base_url : url for users starpage
    client_id : client id
    client_secret : secret
    wanted_fields : fields we care about
    unwanted_config : fields we dont care about
    ignore_list : i am confused about this one
    extract_jobs : jobs to extract plugin data
    html_jobs : jobs to extract html data
    """

    def __init__(self, user: str = "budswa", batch_size: int = -1) -> None:
        """

        Parameters
        ----------
        user : str, the username

        batch_size : int, batch size for asyncio, if < 1 do not use batches at all (saves a couple of requests, uses way more memory, batch size only really needed if github limits our concurrent api requests)

        """
        super().__init__()
        ic.configureOutput(prefix="")
        self.batch_size = batch_size
        self.use_batches = self.batch_size > 0
        self.user = user
        self.user_fmt = ic.format(self.user)
        self.base_url = "https://api.github.com/users/{}/starred?per-page=1&per_page=100&page=".format(
            self.user
        )

        if not self.client_id or not self.client_secret:
            logging.info(ic.format("Client id and secret not set, using defaults"))

        # perhaps export to a `constants` module
        self.wanted_fields = [
            "archived",
            "clone_url",
            "commits_url",
            "contents_url",
            "created_at",
            "default_branch",
            "description",
            "fork",
            "forks_count",
            "full_name",
            "language",
            "license",
            "open_issues_count",
            "owner",
            "private",
            "stargazers_count",
            "subscribers_count",
            "topics",
            "updated_at",
        ]
        # this is not accurate but it will be good enough for now.
        self.unwanted_config = [
            "nvchad",
            "ide", 
            "astrocommunity",
            "lvim",
            "dotfiles",
            "dotfile",
            "dots",
            "nvim-dotfiles",
            "nvim-qt",
            "nvim-config",
            "vim-config",
            "config-nvim",
        ]
        self.ignore_list = []
        self.extract_jobs: list[tuple[dict, bool]] = []
        self.filetree_jobs: list[tuple[str]] = []

    def async_helper(self, fn: Callable[[tuple], Any], iterable: List) -> List:
        """
        Helper for simple async usages. Complicated stuff should be done normally

        Parameters
        ----------
        fn : Callable[[tuple], Any], function to run asynchronously

        iterable : list, list of parameters for fn


        Returns
        -------
        list of fn(iterable_item)

        """

        async def run_jobs():
            loop = get_or_create_eventloop()
            results = []
            if self.use_batches:
                with logging_redirect_tqdm():
                    for i in tqdm.tqdm(
                        range(0, len(iterable) + self.batch_size, self.batch_size),
                        desc=fn.__name__,
                    ):
                        results += await asyncio.gather(
                            *[
                                loop.run_in_executor(
                                    None,
                                    functools.partial(fn, *j),
                                )
                                for j in iterable[i : i + self.batch_size]
                            ]
                        )
            else:
                results += await asyncio.gather(
                    *[
                        loop.run_in_executor(
                            None,
                            functools.partial(fn, *j),
                        )
                        for j in iterable
                    ]
                )

            return results

        return asyncio.run(run_jobs())

    def load_stars_by_page(self, page: int, n_tries: int = 0) -> BaseRequestResponse:
        """

        Parameters
        ----------
        page : int


        Returns
        -------
        BaseRequestResponse

        """
        logging.debug(
            "Querying github stars for {}, {}".format(self.user_fmt, ic.format(page))
        )
        response = requests.get(
            self.base_url + str(page), auth=(self.client_id, self.client_secret)
        )

        if response.status_code != 200:
            time.sleep(random.random() * 3 + n_tries)

            logging.critical("Bad request {}".format(ic.format(response.status_code)))
            if response.status_code == 403 and n_tries <= 10:
                logging.info("Retrying!")
                self.switch_api_key()
                n_tries += 1

        out = BaseRequestResponse(
            responses=response.json(),
        )
        if len(out.responses) == 0:
            logging.warning(
                "No stars for {}, {} found!".format(self.user_fmt, ic.format(page))
            )
        return out

    async def get_pages(self) -> BaseRequestResponse:
        """
        gets all starpages for a user, works by grabbing 10 pages at a time, when all pages are empty, stops making more pages

        Returns
        -------
        response: BaseRequestResponse


        """
        loop = get_or_create_eventloop()
        results = []
        finished = False
        start = 0
        batch_size = 10
        while not finished:
            tmp = await asyncio.gather(
                *[
                    loop.run_in_executor(
                        None,
                        functools.partial(self.load_stars_by_page, start + i),
                    )
                    for i in range(1, batch_size + 1)
                ]
            )
            tmp = BaseRequestResponse(
                responses=list(it.chain(*[t.responses for t in tmp]))
            )
            if len(tmp.responses) == 0:
                finished = True
            results += tmp.responses
            start += batch_size
        response = BaseRequestResponse(responses=results)
        return response

    def extract_data(
        self, plugin_dict: dict, is_plugin: bool, n_retries: int = 0
    ) -> dict:
        """
        extracts commit data from a plugin or dotfile

        Parameters
        ----------
        plugin_dict : dict, dict describing dotfile or plugin

        is_plugin : bool, is it a plugin? or a dotfile?


        Returns
        -------
        dict containing the plugin name, plugin data, and whether it is a plugin or dotfile('type')

        """
        plugin_data = defaultdict()
        plugin_name = ""

        for field in plugin_dict.keys():
            if field == "full_name":
                plugin_name = plugin_dict[field]
            if field in self.wanted_fields:
                plugin_data[field] = plugin_dict[field]

        if "commits_url" in plugin_dict:
            time.sleep(random.random() * 3 + n_retries)
            commit_req = requests.get(
                plugin_dict["commits_url"][:-6],
                auth=(self.client_id, self.client_secret),
            )

            if commit_req.status_code == 200:
                commit = commit_req.json()[-1]
                plugin_data["commit"] = commit["sha"]
            else:
                logging.critical(
                    "Bad request {}".format(ic.format(commit_req.status_code))
                )
                if commit_req.status_code == 403 and n_retries <= 10:
                    logging.info("Retrying!")
                    self.switch_api_key()
                    self.extract_data(plugin_dict, is_plugin, n_retries + 1)

            del plugin_data["commits_url"]

        plugin_data = {k: v for k, v in plugin_data.items()}

        out = {"name": plugin_name, "data": plugin_data}
        out["type"] = "plugin" if is_plugin else "dotfile"
        ic.configureOutput(prefix="Parsed: ")
        logging.debug(ic.format(out["name"]))

        return out

    def get_filetree(self, d: dict, n_retries: int = 0, url=None) -> dict:
        """
        makes a single html/tree request, results are aggregated and parsed in the main thread

        Parameters
        ----------
        d : dict


        Returns
        -------
        response :

        """

        # repo = d["contents_url"]
        if url is None:
            url = f"https://api.github.com/repos/{d['full_name']}/contents"

        logging.info(ic.format("repo -> ", url))
        # tree_url = ("https://api.github.com/repos/{}/contents".format(repo))
        #
        files = []
        time.sleep(random.random() * 3 + n_retries)
        response = requests.get(
            url,
            auth=(self.client_id, self.client_secret),
        )

        while url:
            if response.status_code != 200:
                logging.critical(
                    "Bad request {}".format(ic.format(response.status_code))
                )
                if response.status_code == 403 and n_retries < 10:
                    logging.info("Retrying...")
                    self.switch_api_key()

                    self.get_filetree(d, n_retries + 1, url)
            data = response.json()

            # have to check isntance
            if isinstance(data, list):
                for item in data:
                    files.append(item["name"])
            url = response.links.get("next", {}).get("url")
        return files

    def debug_print(self, x, y):
        if x is not None:
            return x.lower() == "lua"
        else:
            return False

    def make_jobs(self, base: BaseRequestResponse) -> None:
        """
        Given a response list, generate jobs(read: sets of parameters) for extract_data to run asynchronously
        Iterates through the response list, and for each one, creates a plugin or dotfile job. For some edge cases,
        it creates a list of jobs to parse some html relating to the plugin or dotfile, and uses the result of that to create more jobs

        Parameters
        ----------
        base : BaseRequestResponse


        """
        logging.info("Generating jobs!")
        name_mapper = key_mapper("name")  # uses d['name']
        fullname_mapper = key_mapper("full_name")  # uses d['full_name']
        description_mapper = key_mapper("description")  # uses d['description']
        language_mapper = key_mapper("language")
        archive_mapper = key_mapper("archived")
        # checks if d['full_name'] ends with .nvim, -nvim, .vim
        # check if d['name'] starts with '.'

        fixed_plugin_conds = []
        fixed_dotfile_conds = []

        both_conditions = [
            language_mapper(
                # lambda x, y: x.lower() == "lua", ["lua"]
                lambda x, y: self.debug_print(x, y),
                ["lua"],
            ),
            # sourcery skip: swap-if-expression
            archive_mapper(lambda x, _: 1 if not x else 0, ["_"]),
        ]

        optional_plugin_conds = [
            fullname_mapper(
                lambda x, y: x.lower().endswith(y.lower()),
                [".nvim", "-nvim", ".vim"],
            ),
        ]
        optional_dotfile_conds = [
            name_mapper(lambda x, y: x.lower().startswith(y.lower()), "."),
            fullname_mapper(
                lambda x, y: y.lower() in x.lower(), self.unwanted_config
            ),  # checks if any of the unwanted config names are in d['full_name']
            description_mapper(
                lambda x, y: y.lower() in x.lower() if x is not None else 0,
                self.unwanted_config,
            ),  # check if any of the unwanted config names are in d['description']
        ]
        cases = {
            # mappings for conditions based on conditions
            (1, 0): "plugin_count",
            (0, 1): "dotfile_count",
        }

        def custom_case(x):
            if all(cn(x) for cn in both_conditions):
                is_plugin = sum(cn(x) for cn in fixed_plugin_conds)
                optional_plugin = sum(cn(x) for cn in optional_plugin_conds)
                optional_dotfile = sum(cn(x) for cn in optional_dotfile_conds)
                return (
                    (0, 1)
                    if optional_dotfile > 0
                    else (1, 0)
                    if is_plugin + optional_plugin > 1
                    else (0, 1)
                )
                # return (1, 0) if is_plugin + optional_plugin > 1 else (0, 1)

            else:
                return (0, 0)

        def make_jobtype(response):
            plugin_data = response.dict()
            case = custom_case(plugin_data)
            if case in cases:
                return (
                    (plugin_data, bool(case[0])) if case == (1, 0) else (plugin_data,)
                )
            else:
                return (0, 0, 0)

        initial_jobs = Parallel(-1)(
            delayed(make_jobtype)(response) for response in base.responses
        )  # gets all the jobtypes, in parallel over all cores

        self.filetree_jobs.extend([j for j in initial_jobs if len(j) == 1])
        self.extract_jobs.extend([j for j in initial_jobs if len(j) == 2])

        type_counts = Counter(
            ["plugin" if not x[-1] else "dotfile" for x in self.extract_jobs]
        )
        # __import__("pdb").set_trace()

        filetrees = self.async_helper(
            lambda x: (x, self.get_filetree(x)), self.filetree_jobs
        )
        filetrees = [x for x in filetrees if x[-1] is not None]
        for res in filetrees:
            tree = res[-1]

            # Secondary level filter
            if "lua" in tree:
                secondary = True
                # Teriary level filter

                for x in self.unwanted_config:
                    unwanted_lower = x.lower()
                    name = res[0].get("name").lower()
                    description = (res[0].get("description") or "").lower()
                    description = description.lower() if description is not None else ""
                    if unwanted_lower in name or unwanted_lower in description:
                        self.extract_jobs.append((res[0], False))
                        type_counts.update(["dotfile"])
                        logging.info("Adding dotfile: {}".format(res[0]["name"]))
                        secondary = False
                        break

                if secondary:
                    # Quaternary level filter
                    if any(
                        "init" in item
                        and (item.endswith("lua") or item.endswith("vim"))
                        for item in tree
                    ):
                        self.extract_jobs.append((res[0], False))
                        type_counts.update(["dotfile"])
                        logging.info("Adding dotfile: {}".format(res[0]["name"]))
                    else:
                        self.extract_jobs.append((res[0], True))
                        type_counts.update(["plugin"])
                        logging.info("Adding plugin: {}".format(res[0]["name"]))

        logging.info(ic.format(type_counts))
        ic.configureOutput("Created: ")
        logging.info(ic.format(len(self.extract_jobs)))

    async def run_jobs(self):
        """
        Runs jobs

        Returns
        -------
        results : list of star pages

        """
        loop = get_or_create_eventloop()
        results = []
        with logging_redirect_tqdm():
            for i in tqdm.tqdm(
                range(0, len(self.extract_jobs) + self.batch_size, self.batch_size)
            ):
                results += await asyncio.gather(
                    *[
                        loop.run_in_executor(
                            None,
                            functools.partial(self.extract_data, *j),
                        )
                        for j in self.extract_jobs[i : i + self.batch_size]
                    ]
                )
        return results

    @staticmethod
    def sort_results(results: List[dict]) -> dict[str, List[dict]]:
        """
        sorts results by plugin or not

        Parameters
        ----------
        results : list[dict]


        Returns
        -------
        dict[str, list[dict]]

        """
        results = sorted(results, key=lambda x: x["type"])
        grouped = {k: list(g) for k, g in it.groupby(results, lambda x: x["type"])}
        ic.configureOutput("Group Counts: ")
        logging.info(ic.format(len(grouped["plugin"])))
        logging.info(ic.format(len(grouped["dotfile"])))
        for k in grouped.keys():
            for item in grouped[k]:
                item.pop("type")
        return grouped

    @staticmethod
    def write_results(results: dict[str, list[dict]]) -> None:
        """
        Writes sorted results to database

        Parameters
        ----------
        results : dict[str, list[dict]]

        """
        logging.info("writing plugins")
        plugin_dict = {}
        for item in results["plugin"]:
            plugin_dict[item["name"]] = item["data"]
        with open("database.json", "+w") as f:
            f.write(json.dumps(plugin_dict, sort_keys=True, indent=4))

        logging.info("writing dots")
        dotfile_dict = {}
        for item in results["dotfile"]:
            dotfile_dict[item["name"]] = item["data"]
        with open("dotfiles.json", "+w") as f:
            f.write(json.dumps(dotfile_dict, sort_keys=True, indent=4))

    def __call__(self, *args: Any, write_results: bool = True, **kwds: Any) -> Any:
        """

         Parameters
         ----------
          *args: Any

         write_results : bool

          **kwds: Any


         Returns
         -------
        dict[str, list[dict]]

        """
        loop = get_or_create_eventloop()
        logging.info("Getting stars for {}".format(self.user_fmt))
        base = asyncio.run(self.get_pages())
        self.make_jobs(base)
        ic.configureOutput(prefix="")
        logging.info(
            "Running {} jobs!".format(
                ic.format(len(self.filetree_jobs) + len(self.extract_jobs))
            )
        )
        results = self.async_helper(self.extract_data, self.extract_jobs)
        results_grouped = self.sort_results(results)
        if write_results:
            self.write_results(results_grouped)
        return results_grouped


def main() -> None:
    """Main Function"""
    dg = GenerateData(batch_size=30)
    dc = dg()
    return dc


if __name__ == "__main__":
    __import__("dotenv").load_dotenv(".env")
    main()
