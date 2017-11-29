# Copyright (c) 2015 Infortrend Technology, Inc.
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
"""
Infortrend basic CLI factory.
"""

import abc
import os
import time

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import strutils
import six

from cinder import utils

LOG = logging.getLogger(__name__)

DEFAULT_RETRY_TIME = 5


def retry_cli(func):
    def inner(self, *args, **kwargs):
        total_retry_time = self.cli_retry_time

        if total_retry_time is None:
            total_retry_time = DEFAULT_RETRY_TIME

        retry_time = 0
        while retry_time < total_retry_time:
            rc, out = func(self, *args, **kwargs)
            retry_time += 1

            if rc == 0:
                break

            LOG.error(
                'Retry %(retry)s times: %(method)s Failed '
                '%(rc)s: %(reason)s', {
                    'retry': retry_time,
                    'method': self.__class__.__name__,
                    'rc': rc,
                    'reason': out})

            # show error log, not retrying
            if rc == 1:
                # RAID return fail
                break
            elif rc == 11:
                # rc == 11 means not exist
                break
            elif rc == 20:
                # rc == 20 means already exist
                break

        LOG.debug(
            'Method: %(method)s Return Code: %(rc)s '
            'Output: %(out)s', {
                'method': self.__class__.__name__, 'rc': rc, 'out': out})
        return rc, out
    return inner


def os_execute(fd, raidcmd_timeout, command_line):
    os.write(fd, command_line.encode('utf-8'))
    return os_read(fd, 8192, 'RAIDCmd:>', raidcmd_timeout)


def os_read(fd, buffer_size, cmd_pattern, raidcmd_timeout):
    content = ''
    start_time = int(time.time())
    while True:
        time.sleep(0.5)
        output = os.read(fd, buffer_size)
        if len(output) > 0:
            content += output.decode('utf-8')
        if content.find(cmd_pattern) >= 0:
            break
        if int(time.time()) - start_time > raidcmd_timeout:
            content = 'Raidcmd timeout: %s' % content
            LOG.error(
                'Raidcmd exceeds cli timeout [%(timeout)s]s.', {
                    'timeout': raidcmd_timeout})
            break
    return content


def strip_empty_in_list(list):
    result = []
    for entry in list:
        entry = entry.strip()
        if entry != "":
            result.append(entry)

    return result


def table_to_dict(table):
    tableHeader = table[0].split("  ")
    tableHeaderList = strip_empty_in_list(tableHeader)

    result = []

    for i in range(len(table) - 2):
        if table[i + 2].strip() == "":
            break

        resultEntry = {}
        tableEntry = table[i + 2].split("  ")
        tableEntryList = strip_empty_in_list(tableEntry)

        for key, value in zip(tableHeaderList, tableEntryList):
            resultEntry[key] = value

        result.append(resultEntry)
    return result


def content_lines_to_dict(content_lines):
    result = []
    resultEntry = {}

    for content_line in content_lines:

        if content_line.strip() == "":
            result.append(resultEntry)
            resultEntry = {}
            continue

        split_entry = content_line.strip().split(": ", 1)
        resultEntry[split_entry[0]] = split_entry[1]

    return result


@six.add_metaclass(abc.ABCMeta)
class BaseCommand(object):

    """The BaseCommand abstract class."""

    def __init__(self):
        super(BaseCommand, self).__init__()

    @abc.abstractmethod
    def execute(self, *args, **kwargs):
        pass


class ShellCommand(BaseCommand):

    """The Common ShellCommand."""

    def __init__(self, cli_conf):
        super(ShellCommand, self).__init__()
        self.cli_retry_time = cli_conf.get('cli_retry_time')

    @retry_cli
    def execute(self, *args, **kwargs):
        commands = ' '.join(args)
        result = None
        rc = 0
        try:
            result, err = utils.execute(commands, shell=True)
        except processutils.ProcessExecutionError as pe:
            rc = pe.exit_code
            result = pe.stdout
            result = result.replace('\n', '\\n')
            LOG.error(
                'Error on execute command. '
                'Error code: %(exit_code)d Error msg: %(result)s', {
                    'exit_code': pe.exit_code, 'result': result})
        return rc, result


class ExecuteCommand(BaseCommand):

    """The Cinder Filter Command."""

    def __init__(self, cli_conf):
        super(ExecuteCommand, self).__init__()
        self.cli_retry_time = cli_conf.get('cli_retry_time')

    @retry_cli
    def execute(self, *args, **kwargs):
        result = None
        rc = 0
        try:
            result, err = utils.execute(*args, **kwargs)
        except processutils.ProcessExecutionError as pe:
            rc = pe.exit_code
            result = pe.stdout
            result = result.replace('\n', '\\n')
            LOG.error(
                'Error on execute command. '
                'Error code: %(exit_code)d Error msg: %(result)s', {
                    'exit_code': pe.exit_code, 'result': result})
        return rc, result


class CLIBaseCommand(BaseCommand):

    """The CLIBaseCommand class."""

    def __init__(self, cli_conf):
        super(CLIBaseCommand, self).__init__()
        self.cli_retry_time = cli_conf.get('cli_retry_time')
        self.raidcmd_timeout = cli_conf.get('raidcmd_timeout')
        self.cli_cache = cli_conf.get('cli_cache')
        self.pid = cli_conf.get('pid')
        self.fd = cli_conf.get('fd')
        self.command = ""
        self.parameters = ()
        self.show_noinit = ""
        self.command_line = ""

    def _generate_command(self, parameters):
        """Generate execute Command. use java, execute, command, parameters."""
        self.parameters = parameters
        parameters_line = ' '.join(parameters)

        self.command_line = "{0} {1} {2}\n".format(
            self.command,
            parameters_line,
            self.show_noinit)

        return self.command_line

    def _parser(self, content=None):
        """The parser to parse command result.

        :param content: The parse Content
        :returns: parse result
        """
        content = content.replace("\r", "")
        content = content.replace("\\/-", "")
        content = content.strip()
        LOG.debug(content)

        if content is not None:
            content_lines = content.split("\n")
            rc, out = self._parse_return(content_lines)

            if rc != 0:
                return rc, out
            else:
                return rc, content_lines

        return -1, None

    @retry_cli
    def execute(self, *args, **kwargs):
        command_line = self._generate_command(args)
        LOG.debug('Executing: %(command)s', {
            'command': strutils.mask_password(command_line)})
        rc = 0
        result = None
        try:
            content = self._execute(command_line)
            rc, result = self._parser(content)
        except processutils.ProcessExecutionError as pe:
            rc = -2  # prevent confusing with cli real rc
            result = pe.stdout
            result = result.replace('\n', '\\n')
            LOG.error(
                'Error on execute %(command)s. '
                'Error code: %(exit_code)d Error msg: %(result)s', {
                    'command': strutils.mask_password(command_line),
                    'exit_code': pe.exit_code,
                    'result': result})
        return rc, result

    def _execute(self, command_line):
        return os_execute(
            self.fd, self.raidcmd_timeout, command_line)

    def _parse_return(self, content_lines):
        """Get the end of command line result."""
        rc = 0
        if 'Raidcmd timeout' in content_lines[0]:
            rc = -3
            return_cli_result = content_lines
        elif len(content_lines) < 4:
            rc = -4
            return_cli_result = 'Raidcmd output error: %s' % content_lines
        else:
            return_value = content_lines[-3].strip().split(' ', 1)[1]
            return_cli_result = content_lines[-4].strip().split(' ', 1)[1]
            rc = int(return_value, 16)

        return rc, return_cli_result


class ConnectRaid(CLIBaseCommand):

    """The Connect Raid Command."""

    def __init__(self, *args, **kwargs):
        super(ConnectRaid, self).__init__(*args, **kwargs)
        self.command = "connect"


class CheckConnection(CLIBaseCommand):

    """The Check Connection Command."""

    def __init__(self, *args, **kwargs):
        super(CheckConnection, self).__init__(*args, **kwargs)
        self.command = "lock"


class InitCache(CLIBaseCommand):
    """Refresh cacahe data for update volume status."""

    def __init__(self, *args, **kwargs):
        super(InitCache, self).__init__(*args, **kwargs)
        self.command = "utility init-cache"


class CreateLD(CLIBaseCommand):

    """The Create LD Command."""

    def __init__(self, *args, **kwargs):
        super(CreateLD, self).__init__(*args, **kwargs)
        self.command = "create ld"


class CreateLV(CLIBaseCommand):

    """The Create LV Command."""

    def __init__(self, *args, **kwargs):
        super(CreateLV, self).__init__(*args, **kwargs)
        self.command = "create lv"


class CreatePartition(CLIBaseCommand):

    """Create Partition.

    create part
        [LV-ID] [name] [size={partition-size}]
        [min={minimal-reserve-size}] [init={switch}]
        [tier={tier-level-list}]
    """

    def __init__(self, *args, **kwargs):
        super(CreatePartition, self).__init__(*args, **kwargs)
        self.command = "create part"


class DeletePartition(CLIBaseCommand):

    """Delete Partition.

    delete part [partition-ID] [-y]
    """

    def __init__(self, *args, **kwargs):
        super(DeletePartition, self).__init__(*args, **kwargs)
        self.command = "delete part"


class SetPartition(CLIBaseCommand):

    """Set Partition.

    set part
    [partition-ID] [name={partition-name}] [min={minimal-reserve-size}]
    set part expand [partition-ID] [size={expand-size}]
    set part purge [partition-ID] [number] [rule-type]
    set part reclaim [partition-ID]
    set part tier-resided [partition-ID] tier={tier-level-list}
    """

    def __init__(self, *args, **kwargs):
        super(SetPartition, self).__init__(*args, **kwargs)
        self.command = "set part"


class SetLV(CLIBaseCommand):

    """Set Logical Volume.

    set lv tier-migrate [LV-ID] [part={partition-IDs}]
    """

    def __init__(self, *args, **kwargs):
        super(SetLV, self).__init__(*args, **kwargs)
        self.command = "set lv"


class SetSnapshot(CLIBaseCommand):

    """Set Logical Volume.

    set lv tier-migrate [LV-ID] [part={partition-IDs}]
    """

    def __init__(self, *args, **kwargs):
        super(SetSnapshot, self).__init__(*args, **kwargs)
        self.command = "set si"


class CreateMap(CLIBaseCommand):

    """Map the Partition on the channel.

    create map
        [part] [partition-ID] [Channel-ID]
        [Target-ID] [LUN-ID] [assign={assign-to}]
    """

    def __init__(self, *args, **kwargs):
        super(CreateMap, self).__init__(*args, **kwargs)
        self.command = "create map"


class DeleteMap(CLIBaseCommand):

    """Unmap the Partition on the channel.

    delete map
        [part] [partition-ID] [Channel-ID]
        [Target-ID] [LUN-ID] [-y]
    """

    def __init__(self, *args, **kwargs):
        super(DeleteMap, self).__init__(*args, **kwargs)
        self.command = "delete map"


class CreateSnapshot(CLIBaseCommand):

    """Create partition's Snapshot.

    create si [part] [partition-ID]
    """

    def __init__(self, *args, **kwargs):
        super(CreateSnapshot, self).__init__(*args, **kwargs)
        self.command = "create si"


class DeleteSnapshot(CLIBaseCommand):

    """Delete partition's Snapshot.

    delete si [snapshot-image-ID] [-y]
    """

    def __init__(self, *args, **kwargs):
        super(DeleteSnapshot, self).__init__(*args, **kwargs)
        self.command = "delete si"


class CreateReplica(CLIBaseCommand):

    """Create partition or snapshot's replica.

    create replica
        [name] [part | si] [source-volume-ID]
        [part] [target-volume-ID] [type={replication-mode}]
        [priority={level}] [desc={description}]
        [incremental={switch}] [timeout={value}]
        [compression={switch}]
    """

    def __init__(self, *args, **kwargs):
        super(CreateReplica, self).__init__(*args, **kwargs)
        self.command = "create replica"


class DeleteReplica(CLIBaseCommand):

    """Delete and terminate specific replication job.

    delete replica [volume-pair-ID] [-y]
    """

    def __init__(self, *args, **kwargs):
        super(DeleteReplica, self).__init__(*args, **kwargs)
        self.command = "delete replica"


class CreateIQN(CLIBaseCommand):

    """Create host iqn for CHAP or lun filter.

    create iqn
        [IQN] [IQN-alias-name] [user={username}] [password={secret}]
        [target={name}] [target-password={secret}] [ip={ip-address}]
        [mask={netmask-ip}]
    """

    def __init__(self, *args, **kwargs):
        super(CreateIQN, self).__init__(*args, **kwargs)
        self.command = "create iqn"


class DeleteIQN(CLIBaseCommand):

    """Delete host iqn by name.

    delete iqn [name]
    """

    def __init__(self, *args, **kwargs):
        super(DeleteIQN, self).__init__(*args, **kwargs)
        self.command = "delete iqn"


class SetIOTimeout(CLIBaseCommand):

    """Set CLI IO timeout.

    utility set io-timeout [time]
    """

    def __init__(self, *args, **kwargs):
        super(SetIOTimeout, self).__init__(*args, **kwargs)
        self.command = "utility set io-timeout"


class ShowCommand(CLIBaseCommand):

    """Basic Show Command."""

    def __init__(self, *args, **kwargs):
        super(ShowCommand, self).__init__(*args, **kwargs)
        self.param_detail = "-l"
        self.default_type = "table"
        self.start_key = ""
        if self.cli_cache:
            self.show_noinit = "-noinit"

    def _parser(self, content=None):
        """Parse Table or Detail format into dict.

        # Table format

         ID   Name  LD-amount
        ----------------------
         123  LV-1  1

        # Result

        {
            'ID': '123',
            'Name': 'LV-1',
            'LD-amount': '1'
        }

        # Detail format

         ID: 5DE94FF775D81C30
         Name: LV-1
         LD-amount: 1

        # Result

        {
            'ID': '123',
            'Name': 'LV-1',
            'LD-amount': '1'
        }

        :param content: The parse Content.
        :returns: parse result
        """
        rc, out = super(ShowCommand, self)._parser(content)

        # Error.
        if rc != 0:
            return rc, out

        # No content.
        if len(out) < 6:
            return rc, []

        detect_type = self.detect_type()

        # Show detail content.
        if detect_type == "list":

            start_id = self.detect_detail_start_index(out)

            if start_id < 0:
                return rc, []

            result = content_lines_to_dict(out[start_id:-3])
        else:

            start_id = self.detect_table_start_index(out)

            if start_id < 0:
                return rc, []

            result = table_to_dict(out[start_id:-4])

        return rc, result

    def detect_type(self):
        if self.param_detail in self.parameters:
            detect_type = "list"
        else:
            detect_type = self.default_type
        return detect_type

    def detect_table_start_index(self, content):
        for i in range(1, len(content)):
            key = content[i].strip().split('  ')
            if self.start_key in key[0].strip():
                return i

        return -1

    def detect_detail_start_index(self, content):
        for i in range(1, len(content)):
            split_entry = content[i].strip().split(' ')
            if len(split_entry) >= 2 and ':' in split_entry[0]:
                return i

        return -1


class ShowLD(ShowCommand):

    """Show LD.

    show ld [index-list]
    """

    def __init__(self, *args, **kwargs):
        super(ShowLD, self).__init__(*args, **kwargs)
        self.command = "show ld"


class ShowLV(ShowCommand):

    """Show LV.

    show lv [lv={LV-IDs}] [-l]
    """

    def __init__(self, *args, **kwargs):
        super(ShowLV, self).__init__(*args, **kwargs)
        self.command = "show lv"
        self.start_key = "ID"
        self.show_noinit = ""

    def detect_table_start_index(self, content):
        if "tier" in self.parameters:
            self.start_key = "LV-Name"

        for i in range(1, len(content)):
            key = content[i].strip().split('  ')
            if self.start_key in key[0].strip():
                return i

        return -1


class ShowPartition(ShowCommand):

    """Show Partition.

    show part [part={partition-IDs} | lv={LV-IDs}] [-l]
    """

    def __init__(self, *args, **kwargs):
        super(ShowPartition, self).__init__(*args, **kwargs)
        self.command = "show part"
        self.start_key = "ID"
        self.show_noinit = ""


class ShowSnapshot(ShowCommand):

    """Show Snapshot.

    show si [si={snapshot-image-IDs} | part={partition-IDs} | lv={LV-IDs}] [-l]
    """

    def __init__(self, *args, **kwargs):
        super(ShowSnapshot, self).__init__(*args, **kwargs)
        self.command = "show si"
        self.start_key = "Index"


class ShowDevice(ShowCommand):

    """Show Device.

    show device
    """

    def __init__(self, *args, **kwargs):
        super(ShowDevice, self).__init__(*args, **kwargs)
        self.command = "show device"
        self.start_key = "Index"


class ShowChannel(ShowCommand):

    """Show Channel.

    show channel
    """

    def __init__(self, *args, **kwargs):
        super(ShowChannel, self).__init__(*args, **kwargs)
        self.command = "show channel"
        self.start_key = "Ch"


class ShowDisk(ShowCommand):

    """The Show Disk Command.

    show disk [disk-index-list | channel={ch}]
    """

    def __init__(self, *args, **kwargs):
        super(ShowDisk, self).__init__(*args, **kwargs)
        self.command = "show disk"


class ShowMap(ShowCommand):

    """Show Map.

    show map [part={partition-IDs} | channel={channel-IDs}] [-l]
    """

    def __init__(self, *args, **kwargs):
        super(ShowMap, self).__init__(*args, **kwargs)
        self.command = "show map"
        self.start_key = "Ch"


class ShowNet(ShowCommand):

    """Show IP network.

    show net [id={channel-IDs}] [-l]
    """

    def __init__(self, *args, **kwargs):
        super(ShowNet, self).__init__(*args, **kwargs)
        self.command = "show net"
        self.start_key = "ID"


class ShowLicense(ShowCommand):

    """Show License.

    show license
    """

    def __init__(self, *args, **kwargs):
        super(ShowLicense, self).__init__(*args, **kwargs)
        self.command = "show license"
        self.start_key = "License"

    def _parser(self, content=None):
        """Parse License format.

        # License format

         License  Amount(Partition/Subsystem)  Expired
        ------------------------------------------------
         EonPath  ---                          True

        # Result

        {
            'EonPath': {
                'Amount': '---',
                'Support': True
            }
        }

        :param content: The parse Content.
        :returns: parse result
        """
        rc, out = super(ShowLicense, self)._parser(content)

        if rc != 0:
            return rc, out

        if len(out) > 0:
            result = {}
            for entry in out:
                if entry['Expired'] == '---' or entry['Expired'] == 'Expired':
                    support = False
                else:
                    support = True
                result[entry['License']] = {
                    'Amount':
                        entry['Amount(Partition/Subsystem)'],
                    'Support': support
                }
            return rc, result

        return rc, []


class ShowReplica(ShowCommand):

    """Show information of all replication jobs or specific job.

    show replica [id={volume-pair-IDs}] [-l] id={volume-pair-IDs}
    """

    def __init__(self, *args, **kwargs):
        super(ShowReplica, self).__init__(*args, **kwargs)
        self.command = 'show replica'
        self.show_noinit = ""


class ShowWWN(ShowCommand):

    """Show Fibre network.

    show wwn
    """

    def __init__(self, *args, **kwargs):
        super(ShowWWN, self).__init__(*args, **kwargs)
        self.command = "show wwn"
        self.start_key = "CH"


class ShowIQN(ShowCommand):

    """Show iSCSI initiator IQN which is set by create iqn.

    show iqn
    """

    LIST_START_LINE = "List of initiator IQN(s):"

    def __init__(self, *args, **kwargs):
        super(ShowIQN, self).__init__(*args, **kwargs)
        self.command = "show iqn"
        self.default_type = "list"

    def detect_detail_start_index(self, content):
        for i in range(1, len(content)):
            if content[i].strip() == self.LIST_START_LINE:
                return i + 2

        return -1


class ShowHost(ShowCommand):

    """Show host settings.

    show host
    """

    def __init__(self, *args, **kwargs):
        super(ShowHost, self).__init__(*args, **kwargs)
        self.command = "show host"
        self.default_type = "list"

    def detect_detail_start_index(self, content):
        for i in range(1, len(content)):
            if ':' in content[i]:
                return i
        return -1
