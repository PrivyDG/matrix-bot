import json
import pytz
import requests
import urllib
import time
from datetime import datetime, timedelta
from matrixbot import utils
from dateutil import parser

def utcnow():
    now = datetime.utcnow()
    return now.replace(tzinfo=pytz.utc)


def set_property(settings, builder, setting):
    if setting in settings and not setting in builder:
        builder[setting] = settings[setting]


class WKBotsFeederPlugin:
    def __init__(self, bot, settings):
        self.name = "WKBotsFeederPlugin"
        self.logger = utils.get_logger()
        self.bot = bot
        self.settings = settings
        self.logger.info("WKBotsFeederPlugin loaded (%(name)s)" % settings)
        for builder_name, builder in self.settings["builders"].iteritems():
            if 'builder_name' not in builder:
                builder['builder_name'] = builder_name
            builder['last_buildjob'] = -1
            set_property(self.settings, builder, "last_buildjob_url_squema")
            set_property(self.settings, builder, "builds_url_squema")
            set_property(self.settings, builder, "only_failures")
            self.logger.info("WKBotsFeederPlugin loaded (%(name)s) builder: " % settings + json.dumps(builder, indent = 4))
        self.lasttime = time.time()
        self.period = self.settings.get('period', 60)

    def pretty_entry(self, builder):
        url = builder['last_buildjob_url_squema'] % {
            'builder_name': urllib.quote(builder['builder_name']),
            'last_buildjob': builder['last_buildjob'],
        }

        res = "%(builder_name)s " % builder
        res += "(<a href='%s'>" % url
        res += "%(last_buildjob)s </a>): " % builder
        if builder['failed']:
            res += "<font color='red'><strong>failed</strong></font>"
        else:
            res += "<font color='green'><strong>success</strong></font>"
        return res

    def async(self, handler):
        self.logger.debug("WKBotsFeederPlugin async")
        now = time.time()
        if now < self.lasttime + self.period:
            return  # Feeder is only updated each 'period' time
        self.lasttime = now

        res = []
        for builder_name, builder in self.settings["builders"].iteritems():
            self.logger.debug("WKBotsFeederPlugin async: Fetching %s ..." % builder_name)
            try:
                r = requests.get(builder['builds_url_squema'] % builder).json()
                failed = 'failed' in r['-2']['text']
                last_buildjob = r['-2']['number']
                last_comments = r['-2']['sourceStamp']['changes'][0]['comments']
                if builder['last_buildjob'] >= last_buildjob:
                    continue

                builder["failed"] = failed
                builder["last_buildjob"] = last_buildjob
                builder["last_comments"] = last_comments

                if builder['only_failures'] and not failed:
                    continue

                message = self.pretty_entry(builder)
                for room_id in self.settings["rooms"]:
                    room_id = self.bot.get_real_room_id(room_id)
                    self.bot.send_html(room_id, message, msgtype="m.notice")
            except Exception as e:
                self.logger.error("WKBotsFeederPlugin got error in builder %s: %s" % (builder_name,e))


    def command(self, sender, room_id, body, handler):
        self.logger.debug("WKBotsFeederPlugin command")
        return

    def help(self, sender, room_id, handler):
        self.logger.debug("WKBotsFeederPlugin help")
        return
