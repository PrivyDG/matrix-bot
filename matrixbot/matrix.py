# -*- coding:utf-8 -*-
#
# Author: Pablo Saavedra
# Maintainer: Pablo Saavedra
# Contact: saavedra.pablo at gmail.com

from matrix_client.api import MatrixHttpApi, MatrixRequestError
from matrix_client.client import MatrixClient

# import pprint
import time

from . import utils
from . import ldap as bot_ldap


class MatrixBot():
    def __init__(self, settings):
        self.sync_token = None

        self.logger = utils.get_logger()

        self.settings = settings
        self.period = settings["DEFAULT"]["period"]
        self.uri = settings["matrix"]["uri"]
        self.username = settings["matrix"]["username"].lower()
        self.password = settings["matrix"]["password"]
        self.room_ids = settings["matrix"]["rooms"]
        self.domain = self.settings["matrix"]["domain"]

        self.subscriptions_room_ids = settings["subscriptions"]["rooms"]
        self.revokations_rooms_ids = settings["revokations"]["rooms"]

        self.client = MatrixClient(self.uri)
        self.token = self.client.login_with_password(username=self.username,
                                                     password=self.password)
        self.api = MatrixHttpApi(self.uri, token=self.token)

        self.rooms = []
        self.room_aliases = {}

    def get_user_id(self, username=None):
        if not username:
            username = self.username
        return "@%s:%s" % (username, self.domain)

    def normalize_user_id(self, user_id):
        if not user_id.startswith("@"):
            user_id = "@" + user_id
            self.logger.debug("Adding missing '@' to the username: %s" % user_id)
        if user_id.count(":") == 0:
            user_id = "%s:%s" % (user_id, self.domain)
        return user_id

    def do_command(self, action, sender, room_id, body, attempts=3):
        def add_or_remove_user(users, username, append):
            username = self.normalize_user_id(username)
            if append and username not in users["in"]:
                users["in"].append(username)
            if not append and username not in users["out"]:
                users["out"].append(username)

        ldap_settings = self.settings["ldap"]
        body_arg_list = body.split()[2:]
        dry_mode = False
        if len(body_arg_list) > 0 and body_arg_list[0] == "dryrun":
            dry_mode = True
            body_arg_list = body.split()[3:]
        append = True
        users = {
            "in": [],
            "out": []
        }
        for body_arg in body_arg_list:
            if body_arg == ("but"):
                append = False
            elif body_arg.startswith("+"):
                group_name = body_arg[1:]
                groups_members = bot_ldap.get_ldap_groups_members(ldap_settings)
                if group_name in groups_members.keys():
                    for group_member in groups_members[group_name]:
                        add_or_remove_user(users, group_member, append)
            else:
                add_or_remove_user(users, body_arg, append)

        selected_users = filter(lambda x: x not in users["out"], users["in"])
        if dry_mode:
            self.send_private_message(sender,
                                      "Simulated '%s' action in room '%s' over: %s" % (action, room_id,
                                                                  " ".join(selected_users)))
        else:
            if len(selected_users) > 0:
                for user in selected_users:
                    self.logger.debug(" do_command (%s,%s,%s,dry_mode=%s)" % (action, room_id,
                                                                              user, dry_mode))
                    self.call_api(action, attempts, room_id, user)
            else:
                self.send_private_message(sender,
                                          "No users found")

    def invite_subscriptions(self):
        for room_id in self.subscriptions_room_ids:
            body = "bender: invite " + self.settings["subscriptions"][room_id]
            self.do_command("invite_user", room_id, body, attempts=1)

    def kick_revokations(self):
        for room_id in self.revokations_rooms_ids:
            body = "bender: kick " + self.settings["revokations"][room_id]
            self.do_command("kick_user", room_id, body, attempts=1)

    def call_api(self, action, max_attempts, *args):
        method = getattr(self.api, action)
        attempts = max_attempts
        while attempts > 0:
            try:
                response = method(*args)
                self.logger.info("Call %s action with: %s" % (action, args))
                return response
            except MatrixRequestError, e:
                self.logger.error("Fail (%s/%s) in call %s action with: %s - %s" % (attempts, max_attempts, action, args, e))
                attempts -= 1
                time.sleep(5)

    def send_message(self, room_id, message):
        return self.call_api("send_message", 3,
                             room_id, message)

    def send_private_message(self, user_id, message):
        room_id = self.get_private_room_with(user_id)
        return self.call_api("send_message", 3,
                             room_id, message)

    def leave_empty_rooms(self):
        self.logger.debug("leave_empty_rooms")
        rooms = self.get_rooms()
        for room_id in rooms:
            res = self.call_api("get_room_members", 1,
                                room_id)
            try:
                members_list = res.get('chunk', [])
            except Exception, e:
                members_list = []
                self.logger.debug("Error getting the list of members in room %s: %s" % (room_id, e))

            if len(members_list) > 2:
                self.logger.debug("Room %s is not a 1-to-1 room" % room_id)
                continue # We are looking for a 1-to-1 room
            for r in res.get('chunk', []):
                if 'user_id' in r and 'membership' in r: 
                    if r['membership'] == 'leave':
                        self.call_api("kick_user", 1, room_id, self.get_user_id())
                        self.call_api("forget", 1, room_id)
        return room_id

    def get_private_room_with(self, user_id):
        self.leave_empty_rooms()
        self.logger.debug("get_private_room_with")

        rooms = self.get_rooms()
        for room_id in rooms:
            res = self.call_api("get_room_members", 3,
                                room_id)
            me = False
            him = False
            try:
                members_list = res.get('chunk', [])
            except Exception, e:
                members_list = []
                self.logger.debug("Error getting the list of members in room %s: %s" % (room_id, e))

            if len(members_list) != 2:
                self.logger.debug("Room %s is not a 1-to-1 room" % room_id)
                continue # We are looking for a 1-to-1 room
            for r in res.get('chunk', []):
        
                self.logger.debug("r")
                self.logger.debug(r)
                if 'state_key' in r and 'membership' in r: 
                    self.logger.debug(r['state_key'])
                    self.logger.debug(r['membership'])
                    if r['state_key'] == user_id and r['membership'] == 'invite':
                        him = True
                    if r['state_key'] == user_id and r['membership'] == 'join':
                        him = True
                    if r['state_key'] == self.get_user_id() and r['membership'] == 'join':
                        me = True                   
                    if me and him:
                        self.logger.debug("me and him")
                        return room_id

        # No room found
        room_id = self.call_api("create_room", 3,
                                None, False,
                                [user_id])['room_id']
        return room_id


    def is_command(self, body, command="command_name"):
        res = False
        if body.lower().strip().startswith("%s:" % self.username.lower()):
            command_list = body.split()[1:]
            if len(command_list) == 0:
                if command == "help":
                    res = True
            else:
                if command_list[0] == command:
                    res = True
        self.logger.debug("is_%s: %s" % (command, res))
        return res

    def join_rooms(self, silent=True):
        for room_id in self.room_ids:
            try:
                room = self.client.join_room(room_id)
                room_id = room.room_id  # Ensure we are using the actual id not the alias
                if not silent:
                    self.send_message(room_id, "Mornings!")
            except MatrixRequestError, e:
                self.logger.error("Join action in room %s failed: %s" %
                                  (room_id, e))

        new_subscriptions_room_ids = []
        for room_id in self.subscriptions_room_ids:
            try:
                old_room_id = room_id
                room_id = room_id + ':' + self.domain
                room = self.client.join_room(room_id)
                new_room_id = room.room_id  # Ensure we are using the actual id not the alias
                new_subscriptions_room_ids.append(new_room_id)
                self.settings["subscriptions"][new_room_id] = self.settings["subscriptions"][old_room_id]
            except MatrixRequestError, e:
                self.logger.error("Join action for subscribe users in room %s failed: %s" %
                                  (room_id, e))
        self.subscriptions_room_ids = new_subscriptions_room_ids

        new_revokations_room_ids = []
        for room_id in self.revokations_rooms_ids:
            try:
                old_room_id = room_id
                room_id = room_id + ':' + self.domain
                room = self.client.join_room(room_id)
                new_room_id = room.room_id  # Ensure we are using the actual id not the alias
                new_revokations_room_ids.append(new_room_id)
                self.settings["revokations"][new_room_id] = self.settings["revokations"][old_room_id]
            except MatrixRequestError, e:
                self.logger.error("Join action for revoke users in room %s failed: %s" %
                                  (room_id, e))
        self.revokations_rooms_ids = new_revokations_room_ids

    def do_list_groups(self, sender):
        self.logger.debug("do_list_groups")
        vars_ = {}
        vars_["groups"] = ', '.join(self.settings["ldap"]["groups"])
        try:
            msg_help = '''Groups:

%(groups)s
''' % vars_
            self.send_private_message(sender, msg_help)
        except MatrixRequestError, e:
            self.logger.warning(e)

    def do_list_rooms(self, sender):
        self.logger.debug("do_list_rooms")
        msg_list = "Room list:\n"
        rooms = self.get_rooms()
        for room_id in rooms:

            aliases = self.get_room_aliases(room_id)
            if len(aliases) < 1:
                continue # We are looking for rooms with alias
 
            res = self.call_api("get_room_members", 3, room_id)
            members_list = res.get('chunk', [])

            if len(members_list) <= 2:
                continue # We are looking for many to many rooms
 
            try:
                name = self.api.get_room_name(room_id)['name']
            except Exception, e:
                self.logger.debug("Error getting the room name %s: %s" % (room_id, e))
                name = "No named"
            msg_list += "* %s - %s\n" % (name, " ".join(aliases))
        try:
            self.send_private_message(sender, msg_list)
        except MatrixRequestError, e:
            self.logger.warning(e)

    def do_list(self, sender, body):
        self.logger.debug("do_list")
        ldap_settings = self.settings["ldap"]
        body_arg_list = body.split()[2:]
        msg_list = ""

        if len(body_arg_list) == 0:
            msg_list = "groups:"
            groups = bot_ldap.get_groups(ldap_settings)
            for g in groups:
                msg_list += " %s" % g
            try:
                self.send_private_message(sender, msg_list)
            except MatrixRequestError, e:
                self.logger.warning(e)
            return

        groups_members = bot_ldap.get_ldap_groups_members(ldap_settings)
        for body_arg in body_arg_list:
            if body_arg.startswith("+"):
                group_name = body_arg[1:]
                if group_name in groups_members.keys():
                    msg_list = "group %s members:" % group_name
                    for group_member in groups_members[group_name]:
                        user_id = self.normalize_user_id(group_member)
                        msg_list += " %s" % user_id
                else:
                    msg_list = "group %s not found" % group_name
            else:
                user_id = self.normalize_user_id(body_arg)
                msg_list = "user: %s" % (user_id)
            try:
                self.send_private_message(sender, msg_list)
            except MatrixRequestError, e:
                self.logger.warning(e)

    def do_help(self, sender, body):
        vars_ = self.settings["matrix"].copy()
        vars_["aliases"] = "\n".join(map(lambda x: "%s: " % vars_["username"] + "%s ==> %s" % x,
                                     utils.get_aliases(self.settings).items()))
        try:
            self.logger.debug("do_help")
            msg_help = '''Examples:
%(username)s: help
%(username)s: help extra
%(username)s: invite [dryrun] (@user|+group) ... [ but (@user|+group) ]
%(username)s: kick [dryrun] (@user|+group) ... [ but (@user|+group) ]
%(username)s: list [+group]
%(username)s: list_rooms
%(username)s: list_groups
''' % vars_
            if body.find("extra") >= 0:
                msg_help += '''
Available command aliases:

%(aliases)s
''' % vars_
            self.send_private_message(sender, msg_help)
        except MatrixRequestError, e:
            self.logger.warning(e)

    def _set_rooms(self, response_dict):
        new_room_list = []
        for rooms_types in response_dict['rooms'].keys():
            for room_id in response_dict['rooms'][rooms_types].keys():
                new_room_list.append(room_id)
                
                self._set_room_aliases(room_id, response_dict['rooms'][rooms_types][room_id])
        self.rooms = new_room_list

    def _set_room_aliases(self, room_id, room_dict):
        try:
            aliases = []
            for e in room_dict['state']['events']:
                if e['type'] == 'm.room.aliases':        
                    aliases = e['content']['aliases']
            self.room_aliases[room_id] = aliases
        except Exception:
            pass

    def get_rooms(self):
        return self.rooms

    def get_room_aliases(self, room_id):
        return self.room_aliases[room_id] if room_id in self.room_aliases else []

    def sync(self, ignore=False, timeout_ms=30000):
        response = self.api.sync(self.sync_token, timeout_ms, full_state='true')
        self._set_rooms(response)
        self.sync_token = response["next_batch"]
        self.logger.info("!!! sync_token: %s" % (self.sync_token))
        self.logger.debug("Sync response: %s" % (response))
        if not ignore:
            self.sync_invitations(response['rooms']['invite'])
            self.sync_joins(response['rooms']['join'])
        time.sleep(self.period)

    def sync_invitations(self, invite_events):
        for room_id, invite_state in invite_events.items():
            self.logger.info("+++ (invite) %s" % (room_id))
            for event in invite_state["invite_state"]["events"]:
                if event["type"] == 'm.room.member' and \
                        "membership" in event and \
                        event["membership"] == 'invite' and \
                        "sender" in event and \
                        event["sender"].endswith(self.domain):
                    self.call_api("join_room", 3, room_id)

    def sync_joins(self, join_events):
        for room_id, sync_room in join_events.items():
            self.logger.info(">>> (join) %s" % (room_id))
            for event in sync_room["timeline"]["events"]:
                if event["type"] == 'm.room.message' and \
                        "content" in event and \
                        "msgtype" in event["content"] and \
                        event["content"]["msgtype"] == 'm.text':
                    sender = event["sender"]
                    body = event["content"]["body"]
                    body = utils.get_command_alias(body, self.settings)
                    if body.lower().strip().startswith("%s:" % self.username):
                        if self.is_command(body, "invite"):
                            self.do_command("invite_user", sender, room_id, body)
                        elif self.is_command(body, "kick"):
                            self.do_command("kick_user", sender, room_id, body)
                        elif self.is_command(body, "list"):
                            self.do_list(sender, body)
                        elif self.is_command(body, "list_rooms"):
                            self.do_list_rooms(sender)
                        elif self.is_command(body, "list_groups"):
                            self.do_list_groups(sender)
                        elif self.is_command(body, "help"):
                            self.do_help(sender, body)
                        else:
                            self.do_help(sender, room_id, body)
