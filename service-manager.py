#!/usr/bin/env python3

import asyncio
import json
import subprocess
import threading
import urwid
from asyncio.subprocess import PIPE
from os import listdir
from os.path import isfile, join, expanduser

PALETTE = [
    ("substate_running", "dark green", ""),
    ("substate_dead", "", ""),
    ("substate_failed", "light red", ""),
    ("substate_error", "light red", ""),
    ("substate_changing", "yellow", ""),
    ("btn_start", "dark green", ""),
    ("btn_start_act", "", "dark green"),
    ("btn_stop", "light red", ""),
    ("btn_stop_act", "", "light red"),
    ("text", "", ""),
]

SERVICE_DIR = expanduser("~/.config/systemd/user/")

async def check_output(cmd):
    if type(cmd) == list:
        cmd = " ".join(cmd)
    p = await asyncio.create_subprocess_shell(cmd, stdin=PIPE, stdout=PIPE)
    out, err = await p.communicate()
    return out


class Service(urwid.Columns):

    SUBSTATE_CHANGING = "changing"

    def __init__(self, servicename, debug=False):
        self.name = "Unknown service"
        self.state = ""
        self.substate = Service.SUBSTATE_CHANGING
        self.servicename = servicename
        self.lastline = "__ no output __"
        super().__init__(widget_list=[], dividechars=1)
        if not debug:
            asyncio.ensure_future(self.__update_loop())

    async def __update_loop(self):
        while True:
            await self.__update_data()
            await asyncio.sleep(1)

    async def __update_data(self):
        status = await self.get_service_status()
        name = status["Description"]
        state = status["ActiveState"]
        substate = status["SubState"]
        lastline = status["lastline"]
        self.set_data(name, substate, lastline)

    def set_data(self, name, substate, lastline):
        ''' DEBUG '''
        self.name = name
        self.state = ""
        self.substate = substate
        self.lastline = lastline
        self.__update_contents()

    def __get_substate_widget(state, substate):
        text = "Unknown"
        color = "text"

        substate_map = {
            "running": ("Running", "substate_running"),
            "dead": ("Dead", "substate_dead"),
            "failed": ("Failed", "substate_failed"),
            # currently unused as journal doesn't
            # distinguish stderr from stdout
            "error": ("Error", "substate_error"),
            Service.SUBSTATE_CHANGING: ("......", "substate_changing"),
        }

        state_map = {
            "failed": ("Failed", "substate_failed"),
        }

        if substate in substate_map:
            text, color = substate_map[substate]
        elif state in state_map:
            text, color = state_map[state]

        text_widget = urwid.Text(text, align="left", wrap="clip")
        return urwid.AttrMap(text_widget, color)

    def __gen_contents(self):
        raw_contents = [
            (urwid.Text(self.name), ['weight', 1]),
            (Service.__get_substate_widget(self.state, self.substate),
                ['given', 4 + len("Running")]),
            #(urwid.Text(self.servicename), ['weight', 1]),
            (urwid.AttrMap(urwid.Button("Start", self.start), "btn_start"),
                ['given', 4 + len("Start")]),
            (urwid.AttrMap(urwid.Button("Stop", self.stop), "btn_stop"),
                ['given', 4 + len("Stop")]),
            (urwid.Text(self.lastline), ['weight', 4]),
        ]
        contents = [
            (widget, self.options(*option_args))
            for widget, option_args in raw_contents
        ]
        return contents

    def __update_contents(self):
        self.contents = self.__gen_contents()

    def debug_create(name, substate, servicename, lastline):
        s = Service(servicename, debug=True)
        s.set_data(name, substate, lastline)
        return s

    def start(self, button):
        self.substate = Service.SUBSTATE_CHANGING
        self.__update_contents()
        asyncio.ensure_future(self.start_async())

    async def start_async(self):
        await check_output([
            "systemctl", "--user", "start", self.servicename])
        await self.__update_data()

    def stop(self, button):
        self.substate = Service.SUBSTATE_CHANGING
        self.__update_contents()
        asyncio.ensure_future(self.stop_async())

    async def stop_async(self):
        await check_output([
            "systemctl", "--user", "stop", self.servicename])
        await self.__update_data()

    async def get_service_status(self):
        # get systemd info
        raw_status = await check_output([
            "systemctl", "--user", "show", self.servicename])
        status = {}
        for line in raw_status.decode().splitlines():
            k, _, v = line.partition("=")
            status[k] = v

        # get last line from journal
        journal = await check_output([
            "journalctl", "--user" "-u", self.servicename,
            "-n" , "1", "-o", "json"])
        if len(journal) > 0:
            journal = json.loads(journal)
            status["lastline"] = journal["MESSAGE"]
        else:
            status["lastline"] = "__ no output __"

        return status



class ServiceList(urwid.ListBox):

    def __init__(self, *args, **kwargs):
        kwargs["body"] = []
        super().__init__(*args, **kwargs)
        asyncio.ensure_future(self.__update_service_list())

    async def __update_service_list(self):
        # TODO aiofiles for non-blocking
        files = [f for f in listdir(SERVICE_DIR)
                    if isfile(join(SERVICE_DIR, f)) and f.endswith(".service")]
        files = [f.rpartition(".")[0] for f in files]
        files = set(files)
        files_len = len(files)

        services = set()

        # keep existing services
        for s in self.body:
            if s.filename in files:
                services.add(s)
                files.remove(s.filename)

        # add new services
        for f in files:
            s = Service(f)
            services.add(s)

        assert(len(services) == files_len)

        self.body.clear()
        self.body += services

if __name__ == '__main__':
    services = [
        Service.debug_create("shit", "running", "fileshit", "lineshit"),
        Service.debug_create("dead", "dead", "fileblar", "lineblar"),
        Service.debug_create("failed", "failed", "fileblar", "lineblar"),
        Service.debug_create("error", "error", "fileblar", "lineblar"),
        Service.debug_create("changing", Service.SUBSTATE_CHANGING, "fileblar", "lineblar"),
        Service("test-service"),
    ]
    service_list = ServiceList()

    aloop = asyncio.get_event_loop()
    ev_loop = urwid.AsyncioEventLoop(loop=aloop)
    loop = urwid.MainLoop(service_list, PALETTE, event_loop=ev_loop)
    loop.run()
