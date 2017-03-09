# Copyright (c) 2016 Reduxio Systems
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""Reduxio CLI intrface class for Reduxio Cinder Driver."""
import datetime
import json

import eventlet
from oslo_log import log as logging
import paramiko
import six

from cinder import exception
from cinder.i18n import _
from cinder import utils


CONNECTION_RETRY_NUM = 5

VOLUMES = "volumes"
HOSTS = "hosts"
HG_DIR = "hostgroups"
NEW_COMMAND = "new"
UPDATE_COMMAND = "update"
LS_COMMAND = "ls"
DELETE_COMMAND = "delete"
LIST_ASSIGN_CMD = "list-assignments"
CLI_DATE_FORMAT = "%m-%Y-%d %H:%M:%S"
CONNECT_LOCK_NAME = "reduxio_cli_Lock"
CLI_CONNECTION_RETRY_SLEEP = 5
CLI_SSH_CMD_TIMEOUT = 20
CLI_CONNECT_TIMEOUT = 50

LOG = logging.getLogger(__name__)


class RdxApiCmd(object):
    """A Builder class for Reduxio CLI Command."""

    def __init__(self, cmd_prefix, argument=None, flags=None,
                 boolean_flags=None, force=None):
        """Initialize a command object."""
        if isinstance(cmd_prefix, list):
            cmd_prefix = map(lambda x: x.strip(), cmd_prefix)
            self.cmd = " ".join(cmd_prefix)
        else:
            self.cmd = cmd_prefix

        self.arg = None
        self.flags = {}
        self.booleanFlags = {}

        if argument is not None:
            self.set_argument(argument)

        if flags is not None:
            if isinstance(flags, list):
                for flag in flags:
                    self.add_flag(flag[0], flag[1])
            else:
                for key in flags:
                    self.add_flag(key, flags[key])

        if boolean_flags is not None:
            for flag in boolean_flags:
                self.add_boolean_flag(flag)

        if force:
            self.force_command()

    def set_argument(self, value):
        """Set a command argument."""
        self.arg = value

    def add_flag(self, name, value):
        """Set a flag and its value."""
        if value is not None:
            self.flags[name.strip()] = value

    def add_boolean_flag(self, name):
        """Set a boolean flag."""
        if name is not None:
            self.booleanFlags[name.strip()] = True

    def build(self):
        """Return the command line which represents the command object."""
        argument_str = "" if self.arg is None else self.arg
        flags_str = ""

        for key in sorted(self.flags):
            flags_str += (" -%(flag)s \"%(value)s\"" %
                          {"flag": key, "value": self.flags[key]})

        for booleanFlag in sorted(self.booleanFlags):
            flags_str += " -%s" % booleanFlag

        return ("%(cmd)s %(arg)s%(flag)s" %
                {"cmd": self.cmd, "arg": argument_str, "flag": flags_str})

    def force_command(self):
        """Add a force flag."""
        self.add_boolean_flag("force")

    def set_json_output(self):
        """Add a json output flag."""
        self.add_flag("output", "json")

    def __str__(self):
        """Override toString."""
        return self.build()

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        """Compare commands based on their str command representations."""
        if isinstance(other, self.__class__):
            return six.text_type(self).strip() == six.text_type(other).strip()
        else:
            return False


class ReduxioAPI(object):
    def __init__(self, host, user, password):
        """Get credentials and connects to Reduxio CLI."""
        self.host = host
        self.user = user
        self.password = password
        self.ssh = None  # type: paramiko.SSHClient
        self._connect()

    def _reconnect_if_needed(self):
        if not self.connected:
            self._connect()

    def _connect(self):
        self.connected = False
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.ssh.connect(self.host, username=self.user,
                             password=self.password,
                             timeout=CLI_CONNECT_TIMEOUT)
            self.connected = True
        except paramiko.ssh_exception.AuthenticationException:
            raise exception.RdxAPIConnectionException(_(
                "Authentication Error. Check login credentials"))
        except Exception:
            LOG.exception("Exception in connecting to Reduxio CLI")
            raise exception.RdxAPIConnectionException(_(
                "Failed to create ssh connection to Reduxio."
                " Please check network connection or Reduxio hostname/IP."))

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def _run_cmd(self, cmd):
        """Run the command and returns a dictionary of the response.

        On failure, the function retries the command. After retry threshold
        the function throws an error.
        """
        cmd.set_json_output()
        LOG.info("Running cmd: %s", cmd)
        success = False
        for x in range(1, CONNECTION_RETRY_NUM):
            try:
                self._reconnect_if_needed()
                stdin, stdout, stderr = self.ssh.exec_command(  # nosec
                    # command input from authorized users on command line
                    command=six.text_type(cmd), timeout=CLI_SSH_CMD_TIMEOUT)
                success = True
                break
            except Exception:
                LOG.exception("Error in running Reduxio CLI command")
                LOG.error(
                    "retrying(%(cur)s/%(overall)s)",
                    {'cur': x, 'overall': CONNECTION_RETRY_NUM}
                )
                self.connected = False
                eventlet.sleep(CLI_CONNECTION_RETRY_SLEEP)

        if not success:
            raise exception.RdxAPIConnectionException(_(
                "Failed to connect to Redxuio CLI."
                " Check your username, password or Reduxio Hostname/IP"))

        str_out = stdout.read()
        # Python 2.7/3.4 compatibility with the decode method
        if hasattr(str_out, "decode"):
            data = json.loads(str_out.decode("utf8"))
        else:
            data = json.loads(str_out)

        if stdout.channel.recv_exit_status() != 0:
            LOG.error("Failed running cli command: %s", data["msg"])
            raise exception.RdxAPICommandException(data["msg"])

        LOG.debug("Command output is: %s", str_out)

        return data["data"]

    @staticmethod
    def _utc_to_cli_date(utc_date):
        if utc_date is None:
            return None
        date = datetime.datetime.fromtimestamp(utc_date)
        return date.strftime(CLI_DATE_FORMAT)

    # Volumes

    def create_volume(self, name, size, description=None, historypolicy=None,
                      blocksize=None):
        """Create a new volume."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, NEW_COMMAND])

        cmd.set_argument(name)
        cmd.add_flag("size", size)
        cmd.add_flag("description", description)
        cmd.add_flag("policy", historypolicy)
        cmd.add_flag("blocksize", blocksize)

        self._run_cmd(cmd)

    def list_volumes(self):
        """List all volumes."""
        return self._run_cmd(RdxApiCmd(cmd_prefix=[VOLUMES, LS_COMMAND]))[
            "volumes"]

    def list_clones(self, name):
        """List all clones of a volume."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "list-clones"])

        cmd.set_argument(name)

        return self._run_cmd(cmd)

    def find_volume_by_name(self, name):
        """Get a single volume by its name."""
        cmd = RdxApiCmd(cmd_prefix=[LS_COMMAND, VOLUMES + "/" + name])

        return self._run_cmd(cmd)["volumes"][0]

    def find_volume_by_wwid(self, wwid):
        """Get a single volume by its WWN."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "find-by-wwid"])

        cmd.set_argument(wwid)

        return self._run_cmd(cmd)

    def delete_volume(self, name):
        """Delete a volume."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, DELETE_COMMAND])

        cmd.set_argument(name)
        cmd.force_command()

        return self._run_cmd(cmd)

    def update_volume(self, name, new_name=None, description=None, size=None,
                      history_policy=None):
        """Update volume's properties. None value keeps the current value."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, UPDATE_COMMAND])

        cmd.set_argument(name)
        cmd.add_flag("size", size)
        cmd.add_flag("new-name", new_name)
        cmd.add_flag("policy", history_policy)
        cmd.add_flag("size", size)
        cmd.add_flag("description", description)

        self._run_cmd(cmd)

    def revert_volume(self, name, utc_date=None, bookmark_name=None):
        """Revert a volume to a specific date or by a bookmark."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "revert"])

        cmd.set_argument(name)
        cmd.add_flag("timestamp", ReduxioAPI._utc_to_cli_date(utc_date))
        cmd.add_flag("bookmark", bookmark_name)
        cmd.force_command()

        return self._run_cmd(cmd)

    def clone_volume(self, parent_name, clone_name, utc_date=None,
                     str_date=None, bookmark_name=None, description=None):
        """Clone a volume our of an existing volume."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "clone"])

        cmd.set_argument(parent_name)
        cmd.add_flag("name", clone_name)
        if str_date is not None:
            cmd.add_flag("timestamp", str_date)
        else:
            cmd.add_flag("timestamp", ReduxioAPI._utc_to_cli_date(utc_date))
        cmd.add_flag("bookmark", bookmark_name)
        cmd.add_flag("description", description)

        self._run_cmd(cmd)

    def list_vol_bookmarks(self, vol):
        """List all bookmarks of a volume."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "list-bookmarks"])

        cmd.set_argument(vol)

        return self._run_cmd(cmd)

    def add_vol_bookmark(self, vol, bm_name, utc_date=None, str_date=None,
                         bm_type=None):
        """Create a new bookmark for a given volume."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "bookmark"])

        cmd.set_argument(vol)
        cmd.add_flag("name", bm_name)
        if str_date is not None:
            cmd.add_flag("timestamp", str_date)
        else:
            cmd.add_flag("timestamp", ReduxioAPI._utc_to_cli_date(utc_date))
        cmd.add_flag("type", bm_type)

        return self._run_cmd(cmd)

    def delete_vol_bookmark(self, vol, bm_name):
        """Delete a volume's bookmark."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "delete-bookmark"])

        cmd.set_argument(vol)
        cmd.add_flag("name", bm_name)

        return self._run_cmd(cmd)

    # Hosts

    def list_hosts(self):
        """List all hosts."""
        return self._run_cmd(RdxApiCmd(cmd_prefix=[HOSTS, LS_COMMAND]))[
            "hosts"]

    def create_host(self, name, iscsi_name, description=None, user_chap=None,
                    pwd_chap=None):
        """Create a new host."""
        cmd = RdxApiCmd(cmd_prefix=[HOSTS, NEW_COMMAND])

        cmd.set_argument(name)
        cmd.add_flag("iscsi-name", iscsi_name)
        cmd.add_flag("description", description)
        cmd.add_flag("user-chap", user_chap)
        cmd.add_flag("pwd-chap", pwd_chap)

        return self._run_cmd(cmd)

    def delete_host(self, name):
        """Delete an existing host."""
        cmd = RdxApiCmd(cmd_prefix=[HOSTS, DELETE_COMMAND])

        cmd.set_argument(name)
        cmd.force_command()

        return self._run_cmd(cmd)

    def update_host(self, name, new_name=None, description=None,
                    user_chap=None, pwd_chap=None):
        """Update host's attributes."""
        cmd = RdxApiCmd(cmd_prefix=[HOSTS, UPDATE_COMMAND])

        cmd.set_argument(name)
        cmd.add_flag("new-name", new_name)
        cmd.add_flag("user-chap", user_chap)
        cmd.add_flag("pwd-chap", pwd_chap)
        cmd.add_flag("description", description)

        return self._run_cmd(cmd)

    # HostGroups

    def list_hostgroups(self):
        """List all hostgroups."""
        return self._run_cmd(RdxApiCmd(cmd_prefix=[HG_DIR, LS_COMMAND]))[
            "hostgroups"]

    def create_hostgroup(self, name, description=None):
        """Create a new hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[HG_DIR, NEW_COMMAND])

        cmd.set_argument(name)
        cmd.add_flag("description", description)

        return self._run_cmd(cmd)

    def delete_hostgroup(self, name):
        """Delete an existing hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[HG_DIR, DELETE_COMMAND])

        cmd.set_argument(name)
        cmd.force_command()

        return self._run_cmd(cmd)

    def update_hostgroup(self, name, new_name=None, description=None):
        """Update an existing hostgroup's attributes."""
        cmd = RdxApiCmd(cmd_prefix=[HG_DIR, UPDATE_COMMAND])

        cmd.set_argument(name)
        cmd.add_flag("new-name", new_name)
        cmd.add_flag("description", description)

        return self._run_cmd(cmd)

    def list_hosts_in_hostgroup(self, name):
        """List all hosts that are part of the given hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[HG_DIR, "list-hosts"])
        cmd.set_argument(name)

        return self._run_cmd(cmd)

    def add_host_to_hostgroup(self, name, host_name):
        """Join a host to a hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[HG_DIR, "add-host"])
        cmd.set_argument(name)
        cmd.add_flag("host", host_name)

        return self._run_cmd(cmd)

    def remove_host_from_hostgroup(self, name, host_name):
        """Remove a host from a hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[HG_DIR, "remove-host"])
        cmd.set_argument(name)
        cmd.add_flag("host", host_name)

        return self._run_cmd(cmd)

    def add_hg_bookmark(self, hg_name, bm_name, utc_date=None, str_date=None,
                        bm_type=None):
        """Bookmark all volumes that are assigned to the hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[HG_DIR, "add-bookmark"])

        cmd.set_argument(hg_name)
        cmd.add_flag("name", bm_name)
        if str_date is not None:
            cmd.add_flag("timestamp", str_date)
        else:
            cmd.add_flag("timestamp", ReduxioAPI._utc_to_cli_date(utc_date))
        cmd.add_flag("type", bm_type)

        return self._run_cmd(cmd)

    # Assignments

    def assign(self, vol_name, host_name=None, hostgroup_name=None, lun=None):
        """Create an assignment between a volume to host/hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "assign"])

        cmd.set_argument(vol_name)
        cmd.add_flag("host", host_name)
        cmd.add_flag("group", hostgroup_name)
        cmd.add_flag("lun", lun)

        return self._run_cmd(cmd)

    def unassign(self, vol_name, host_name=None, hostgroup_name=None):
        """Unassign a volume from a host/hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, "unassign"])

        cmd.set_argument(vol_name)
        cmd.add_flag("host", host_name)
        cmd.add_flag("group", hostgroup_name)

        return self._run_cmd(cmd)

    def list_assignments(self, vol=None, host=None, hg=None):
        """List all assignments for a given volume/host/hostgroup."""
        cmd = RdxApiCmd(cmd_prefix=[VOLUMES, LIST_ASSIGN_CMD])
        if vol is not None:
            cmd.set_argument(vol)
        elif host is not None:
            cmd = RdxApiCmd(cmd_prefix=[HOSTS, LIST_ASSIGN_CMD])
            cmd.set_argument(host)
        elif host is not None:
            cmd = RdxApiCmd(cmd_prefix=[HG_DIR, LIST_ASSIGN_CMD])
            cmd.set_argument(hg)

        return self._run_cmd(cmd)

    def get_single_assignment(self, vol, host, raise_on_non_exists=True):
        """Get a single assignment details between a host and a volume."""
        for assign in self.list_assignments(vol=vol):
            if assign["host"] == host:
                return assign
        if raise_on_non_exists:
            raise exception.RdxAPICommandException(_(
                "No such assignment vol:%(vol)s, host:%(host)s") %
                {'vol': vol, 'host': host}
            )
        else:
            return None

    # Settings

    def get_settings(self):
        """List all Reduxio settings."""
        cli_hash = self._run_cmd(
            RdxApiCmd(cmd_prefix=["settings", LS_COMMAND]))
        return self._translate_settings_to_hash(cli_hash)

    @staticmethod
    def _translate_settings_to_hash(cli_hash):
        new_hash = {}
        for key, value in cli_hash.items():
            if key == "directories":
                continue
            if key == "email_recipient_list":
                continue

            new_hash[key] = {}
            for inter_hash in value:
                if "Name" in inter_hash:
                    new_hash[key][inter_hash["Name"]] = inter_hash["value"]
                else:
                    new_hash[key][inter_hash["name"]] = inter_hash["value"]
        return new_hash

    # Statistics

    def get_savings_ratio(self):
        """Get current savings ratio."""
        return self._run_cmd(RdxApiCmd(cmd_prefix=["system", "status"]))[0][
            "savings-ratio"]

    def get_current_space_usage(self):
        """Get current space usage."""
        cmd = RdxApiCmd(cmd_prefix=["statistics", "space-usage"])
        return self._run_cmd(cmd)[0]
