# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 IBM, Inc.
# Copyright (c) 2012 OpenStack LLC.
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
#
# Authors:
#   Ronen Kat <ronenkat@il.ibm.com>
#   Avishay Traeger <avishay@il.ibm.com>

"""
Tests for the IBM Storwize V7000 and SVC volume driver.
"""

import random

from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder import test
from cinder import utils
from cinder.volume import storwize_svc

LOG = logging.getLogger(__name__)


class StorwizeSVCManagementSimulator:
    def __init__(self, pool_name):
        self._flags = {"storwize_svc_volpool_name": pool_name}
        self._volumes_list = {}
        self._hosts_list = {}
        self._mappings_list = {}
        self._fcmappings_list = {}
        self._next_cmd_error = {}
        self._errors = {
            "CMMVC5701E": ("", "CMMVC5701E No object ID was specified."),
            "CMMVC6035E": ("", "CMMVC6035E The action failed as the " +
                               "object already exists."),
            "CMMVC5753E": ("", "CMMVC5753E The specified object does not " +
                               "exist or is not a suitable candidate."),
            "CMMVC5707E": ("", "CMMVC5707E Required parameters are missing."),
            "CMMVC6581E": ("", "CMMVC6581E The command has failed because " +
                               "the maximum number of allowed iSCSI " +
                               "qualified names (IQNs) has been reached, " +
                               "or the IQN is already assigned or is not " +
                               "valid."),
            "CMMVC5708E": ("", "CMMVC5708E The [XXX] parameter is missing " +
                               "its associated arguments."),
            "CMMVC5754E": ("", "CMMVC5754E The specified object does not " +
                               "exist, or the name supplied does not meet " +
                               "the naming rules."),
            "CMMVC6071E": ("", "CMMVC6071E The VDisk-to-host mapping was " +
                               "not created because the VDisk is already " +
                               "mapped to a host."),
            "CMMVC5879E": ("", "CMMVC5879E The VDisk-to-host mapping was " +
                               "not created because a VDisk is already " +
                               "mapped to this host with this SCSI LUN."),
            "CMMVC5840E": ("", "CMMVC5840E The virtual disk (VDisk) was " +
                               "not deleted because it is mapped to a " +
                               "host or because it is part of a FlashCopy " +
                               "or Remote Copy mapping, or is involved in " +
                               "an image mode migrate."),
            "CMMVC6070E": ("", "CMMVC6070E An invalid or duplicated " +
                               "parameter, unaccompanied argument, or " +
                               "incorrect argument sequence has been " +
                               "detected. Ensure that the input is as per " +
                               "the help."),
            "CMMVC6527E": ("", "CMMVC6527E The name that you have entered " +
                               "is not valid. The name can contain letters, " +
                               "numbers, spaces, periods, dashes, and " +
                               "underscores. The name must begin with a " +
                               "letter or an underscore. The name must not " +
                               "begin or end with a space."),
            "CMMVC5871E": ("", "CMMVC5871E The action failed because one or " +
                               "more of the configured port names is in a " +
                               "mapping."),
            "CMMVC5924E": ("", "CMMVC5924E The FlashCopy mapping was not " +
                               "created because the source and target " +
                               "virtual disks (VDisks) are different sizes."),
            "CMMVC6303E": ("", "CMMVC6303E The create failed because the " +
                               "source and target VDisks are the same."),
        }

    # Find an unused ID
    def _find_unused_id(self, d):
        ids = []
        for k, v in d.iteritems():
            ids.append(int(v["id"]))
        ids.sort()
        for index, n in enumerate(ids):
            if n > index:
                return str(index)
        return str(len(ids))

    # Check if name is valid
    def _is_invalid_name(self, name):
        if (name[0] == " ") or (name[-1] == " "):
            return True
        for c in name:
            if ((not c.isalnum()) and (c != " ") and (c != ".")
                    and (c != "-") and (c != "_")):
                return True
        return False

    # Check if name is valid
    def _strip_quotes(self, str):
        if ((str[0] == '\"' and str[-1] == '\"') or
                (str[0] == '\'' and str[-1] == '\'')):
            return str[1:-1]
        return str

    # Generic function for printing information
    def _print_info_cmd(self, arg_list, rows):
        for arg in arg_list:
            if arg == "-nohdr":
                del rows[0]

        delimeter = " "
        try:
            arg_index = arg_list.index("-delim")
            delimeter = arg_list[arg_index + 1]
        except ValueError:
            pass
        except IndexError:
            return self._errors["CMMVC5707E"]

        for index in range(len(rows)):
            rows[index] = delimeter.join(rows[index])
        return ("%s" % "\n".join(rows), "")

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lsmdiskgrp(self, arg_list):
        rows = [None] * 2
        rows[0] = ["id", "name", "status", "mdisk_count",
                   "vdisk_count capacity", "extent_size", "free_capacity",
                   "virtual_capacity", "used_capacity", "real_capacity",
                   "overallocation", "warning", "easy_tier",
                   "easy_tier_status"]
        rows[1] = ["0", self._flags["storwize_svc_volpool_name"], "online",
                   "1", str(len(self._volumes_list)), "3.25TB", "256",
                   "3.21TB", "1.54TB", "264.97MB", "35.58GB", "47", "80",
                   "auto", "inactive"]
        return self._print_info_cmd(arg_list, rows)

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lsnodecanister(self, arg_list):
        rows = [None] * 3
        rows[0] = ["id", "name", "UPS_serial_number", "WWNN", "status",
                   "IO_group_id", "IO_group_name", "config_node",
                   "UPS_unique_id", "hardware", "iscsi_name", "iscsi_alias",
                   "panel_name", "enclosure_id", "canister_id",
                   "enclosure_serial_number"]
        rows[1] = ["5", "node1", "", "123456789ABCDEF0", "online", "0",
                   "io_grp0",
                   "yes", "123456789ABCDEF0", "100",
                   "iqn.1982-01.com.ibm:1234.sim.node1", "", "01-1", "1", "1",
                   "0123ABC"]
        rows[2] = ["6", "node2", "", "123456789ABCDEF1", "online", "0",
                   "io_grp0",
                   "no", "123456789ABCDEF1", "100",
                   "iqn.1982-01.com.ibm:1234.sim.node2", "", "01-2", "1", "2",
                   "0123ABC"]
        return self._print_info_cmd(arg_list, rows)

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lsportip(self, arg_list):
        if (("lsportip" in self._next_cmd_error) and
                (self._next_cmd_error["lsportip"] == "ip_no_config")):
            self._next_cmd_error["lsportip"] = None
            ip_addr1 = ""
            ip_addr2 = ""
            gw = ""
        else:
            ip_addr1 = "1.234.56.78"
            ip_addr2 = "1.234.56.79"
            gw = "1.234.56.1"

        rows = [None] * 17
        rows[0] = ["id", "node_id", "node_name", "IP_address", "mask",
                   "gateway", "IP_address_6", "prefix_6", "gateway_6", "MAC",
                   "duplex", "state", "speed", "failover"]
        rows[1] = ["1", "5", "node1", ip_addr1, "255.255.255.0",
                   gw, "", "", "", "01:23:45:67:89:00", "Full",
                   "online", "1Gb/s", "no"]
        rows[2] = ["1", "5", "node1", "", "", "", "", "", "",
                   "01:23:45:67:89:00", "Full", "online", "1Gb/s", "yes"]
        rows[3] = ["2", "5", "node1", "", "", "", "", "", "",
                   "01:23:45:67:89:01", "Full", "unconfigured", "1Gb/s", "no"]
        rows[4] = ["2", "5", "node1", "", "", "", "", "", "",
                   "01:23:45:67:89:01", "Full", "unconfigured", "1Gb/s", "yes"]
        rows[5] = ["3", "5", "node1", "", "", "", "", "", "", "", "",
                   "unconfigured", "", "no"]
        rows[6] = ["3", "5", "node1", "", "", "", "", "", "", "", "",
                   "unconfigured", "", "yes"]
        rows[7] = ["4", "5", "node1", "", "", "", "", "", "", "", "",
                   "unconfigured", "", "no"]
        rows[8] = ["4", "5", "node1", "", "", "", "", "", "", "", "",
                   "unconfigured", "", "yes"]
        rows[9] = ["1", "6", "node2", ip_addr2, "255.255.255.0",
                   gw, "", "", "", "01:23:45:67:89:02", "Full",
                   "online", "1Gb/s", "no"]
        rows[10] = ["1", "6", "node2", "", "", "", "", "", "",
                    "01:23:45:67:89:02", "Full", "online", "1Gb/s", "yes"]
        rows[11] = ["2", "6", "node2", "", "", "", "", "", "",
                    "01:23:45:67:89:03", "Full", "unconfigured", "1Gb/s", "no"]
        rows[12] = ["2", "6", "node2", "", "", "", "", "", "",
                    "01:23:45:67:89:03", "Full", "unconfigured", "1Gb/s",
                    "yes"]
        rows[13] = ["3", "6", "node2", "", "", "", "", "", "", "", "",
                    "unconfigured", "", "no"]
        rows[14] = ["3", "6", "node2", "", "", "", "", "", "", "", "",
                    "unconfigured", "", "yes"]
        rows[15] = ["4", "6", "node2", "", "", "", "", "", "", "", "",
                    "unconfigured", "", "no"]
        rows[16] = ["4", "6", "node2", "", "", "", "", "", "", "", "",
                    "unconfigured", "", "yes"]

        return self._print_info_cmd(arg_list, rows)

    # Create a vdisk
    def _cmd_mkvdisk(self, arg_list):
        # We only save the id/uid, name, and size - all else will be made up
        volume_info = {}
        volume_info["id"] = self._find_unused_id(self._volumes_list)
        volume_info["uid"] = ("ABCDEF" * 3) + ("0" * 14) + volume_info["id"]
        try:
            arg_index = arg_list.index("-name") + 1
            volume_info["name"] = self._strip_quotes(arg_list[arg_index])
        except ValueError:
            volume_info["name"] = "vdisk" + str(len(self._volumes_list))
        except IndexError:
            return self._errors["CMMVC5707E"]

        # Assume size and unit are given, store it in bytes
        capacity = int(arg_list[arg_list.index("-size") + 1])
        unit = arg_list[arg_list.index("-unit") + 1]

        if unit == "b":
            volume_info["capacity"] = capacity
        elif unit == "kb":
            volume_info["capacity"] = capacity * pow(1024, 1)
        elif unit == "mb":
            volume_info["capacity"] = capacity * pow(1024, 2)
        elif unit == "gb":
            volume_info["capacity"] = capacity * pow(1024, 3)
        elif unit == "tb":
            volume_info["capacity"] = capacity * pow(1024, 4)
        elif unit == "pb":
            volume_info["capacity"] = capacity * pow(1024, 5)

        if volume_info["name"] in self._volumes_list:
            return self._errors["CMMVC6035E"]
        else:
            self._volumes_list[volume_info["name"]] = volume_info
            return ("Virtual Disk, id [%s], successfully created" %
                    (volume_info["id"]), "")

    # Delete a vdisk
    def _cmd_rmvdisk(self, arg_list):
        if len(arg_list) == 1:
            return self._errors["CMMVC5701E"]
        elif len(arg_list) == 2:
            force = 0
            vol_name = arg_list[1]
        elif len(arg_list) == 3:
            if (arg_list[1] == "-force"):
                force = 1
            else:
                return self._errors["CMMVC6070E"]
            vol_name = arg_list[2]
        else:
            return self._errors["CMMVC6070E"]

        vol_name = self._strip_quotes(vol_name)

        if not vol_name in self._volumes_list:
            return self._errors["CMMVC5753E"]

        if force == 0:
            for k, mapping in self._mappings_list.iteritems():
                if mapping["vol"] == vol_name:
                    return self._errors["CMMVC5840E"]
            for k, fcmap in self._fcmappings_list.iteritems():
                if ((fcmap["source"] == vol_name) or
                        (fcmap["target"] == vol_name)):
                    return self._errors["CMMVC5840E"]

        del self._volumes_list[vol_name]
        return ("", "")

    def _generic_parse_ls_args(self, arg_list):
        index = 1
        ret_vals = {
            "no_hdr": 0,
            "delim": "",
            "obj_name": "",
            "filter": "",
        }

        while index < len(arg_list):
            try:
                if arg_list[index] == "-delim":
                    ret_vals["delim"] = arg_list[index + 1]
                    index += 2
                elif arg_list[index] == "-nohdr":
                    ret_vals["no_hdr"] = 1
                    index += 1
                elif arg_list[index] == "-filtervalue":
                    ret_vals["filter"] = arg_list[index + 1].split("=")[1]
                    index += 2
                else:
                    ret_vals["obj_name"] = arg_list[index]
                    index += 1
            except IndexError:
                return self._errors["CMMVC5708E"]

        return ret_vals

    def _get_fcmap_info(self, vol_name):
        ret_vals = {
            "fc_id": "",
            "fc_name": "",
            "fc_map_count": "0",
        }
        for k, fcmap in self._fcmappings_list.iteritems():
            if ((fcmap["source"] == vol_name) or
                    (fcmap["target"] == vol_name)):
                ret_vals["fc_id"] = fcmap["id"]
                ret_vals["fc_name"] = fcmap["name"]
                ret_vals["fc_map_count"] = "1"
        return ret_vals

    # List information about vdisks
    def _cmd_lsvdisk(self, arg_list):
        arg_dict = self._generic_parse_ls_args(arg_list)

        if arg_dict["obj_name"] == "":
            rows = []
            rows.append(["id", "name", "IO_group_id", "IO_group_name",
                         "status", "mdisk_grp_id", "mdisk_grp_name",
                         "capacity", "type", "FC_id", "FC_name", "RC_id",
                         "RC_name", "vdisk_UID", "fc_map_count", "copy_count",
                         "fast_write_state", "se_copy_count", "RC_change"])

            for k, vol in self._volumes_list.iteritems():
                if ((arg_dict["filter"] == "") or
                        (arg_dict["filter"] == vol["name"])):
                    fcmap_info = self._get_fcmap_info(vol["name"])

                    rows.append([str(vol["id"]), vol["name"], "0", "io_grp0",
                                "online", "0",
                                self._flags["storwize_svc_volpool_name"],
                                str(vol["capacity"]), "striped",
                                fcmap_info["fc_id"], fcmap_info["fc_name"],
                                "", "", vol["uid"],
                                fcmap_info["fc_map_count"], "1", "empty",
                                "1", "no"])

            return self._print_info_cmd(arg_list, rows)

        else:
            if arg_dict["obj_name"] not in self._volumes_list:
                return self._errors["CMMVC5754E"]
            vol = self._volumes_list[arg_dict["obj_name"]]
            fcmap_info = self._get_fcmap_info(vol["name"])
            rows = []
            rows.append(["id", str(vol["id"])])
            rows.append(["name", vol["name"]])
            rows.append(["IO_group_id", "0"])
            rows.append(["IO_group_name", "io_grp0"])
            rows.append(["status", "online"])
            rows.append(["mdisk_grp_id", "0"])
            rows.append(["mdisk_grp_name",
                    self._flags["storwize_svc_volpool_name"]])
            rows.append(["capacity", str(vol["capacity"])])
            rows.append(["type", "striped"])
            rows.append(["formatted", "no"])
            rows.append(["mdisk_id", ""])
            rows.append(["mdisk_name", ""])
            rows.append(["FC_id", fcmap_info["fc_id"]])
            rows.append(["FC_name", fcmap_info["fc_name"]])
            rows.append(["RC_id", ""])
            rows.append(["RC_name", ""])
            rows.append(["vdisk_UID", vol["uid"]])
            rows.append(["throttling", "0"])
            rows.append(["preferred_node_id", "2"])
            rows.append(["fast_write_state", "empty"])
            rows.append(["cache", "readwrite"])
            rows.append(["udid", ""])
            rows.append(["fc_map_count", fcmap_info["fc_map_count"]])
            rows.append(["sync_rate", "50"])
            rows.append(["copy_count", "1"])
            rows.append(["se_copy_count", "0"])
            rows.append(["mirror_write_priority", "latency"])
            rows.append(["RC_change", "no"])

            if arg_dict["no_hdr"] == 1:
                for index in range(len(rows)):
                    rows[index] = " ".join(rows[index][1:])

            if arg_dict["delim"] != "":
                for index in range(len(rows)):
                    rows[index] = arg_dict["delim"].join(rows[index])

            return ("%s" % "\n".join(rows), "")

    # Make a host
    def _cmd_mkhost(self, arg_list):
        try:
            arg_index = arg_list.index("-name") + 1
            host_name = self._strip_quotes(arg_list[arg_index])
        except ValueError:
            host_name = "host" + str(self._num_host())
        except IndexError:
            return self._errors["CMMVC5707E"]

        try:
            arg_index = arg_list.index("-iscsiname") + 1
            iscsi_name = self._strip_quotes(arg_list[arg_index])
        except ValueError:
            return self._errors["CMMVC5707E"]
        except IndexError:
            return self._errors["CMMVC5708E"].replace("XXX", "-iscsiname")

        if self._is_invalid_name(host_name):
            return self._errors["CMMVC6527E"]

        if host_name in self._hosts_list:
            return self._errors["CMMVC6035E"]

        for k, v in self._hosts_list.iteritems():
            if v["iscsi_name"] == iscsi_name:
                return self._errors["CMMVC6581E"]

        host_info = {}
        host_info["host_name"] = host_name
        host_info["iscsi_name"] = iscsi_name
        host_info["id"] = self._find_unused_id(self._hosts_list)

        self._hosts_list[host_name] = host_info
        return ("Host, id [%s], successfully created" %
                (host_info["id"]), "")

    # Remove a host
    def _cmd_rmhost(self, arg_list):
        if len(arg_list) == 1:
            return self._errors["CMMVC5701E"]

        host_name = self._strip_quotes(arg_list[1])
        if host_name not in self._hosts_list:
            return self._errors["CMMVC5753E"]

        for k, v in self._mappings_list.iteritems():
            if (v["host"] == host_name):
                return self._errors["CMMVC5871E"]

        del self._hosts_list[host_name]
        return ("", "")

    # List information about hosts
    def _cmd_lshost(self, arg_list):
        arg_dict = self._generic_parse_ls_args(arg_list)

        if arg_dict["obj_name"] == "":
            rows = []
            rows.append(["id", "name", "port_count", "iogrp_count", "status"])

            for k, host in self._hosts_list.iteritems():
                if ((arg_dict["filter"] == "") or
                        (arg_dict["filter"] == host["host_name"])):
                    rows.append([host["id"], host["host_name"], "1", "4",
                                "offline"])
            return self._print_info_cmd(arg_list, rows)
        else:
            if arg_dict["obj_name"] not in self._hosts_list:
                return self._errors["CMMVC5754E"]
            host = self._hosts_list[arg_dict["obj_name"]]
            rows = []
            rows.append(["id", host["id"]])
            rows.append(["name", host["host_name"]])
            rows.append(["port_count", "1"])
            rows.append(["type", "generic"])
            rows.append(["mask", "1111"])
            rows.append(["iogrp_count", "4"])
            rows.append(["status", "offline"])
            rows.append(["iscsi_name", host["iscsi_name"]])
            rows.append(["node_logged_in_count", "0"])
            rows.append(["state", "offline"])

            if arg_dict["no_hdr"] == 1:
                for index in range(len(rows)):
                    rows[index] = " ".join(rows[index][1:])

            if arg_dict["delim"] != "":
                for index in range(len(rows)):
                    rows[index] = arg_dict["delim"].join(rows[index])

            return ("%s" % "\n".join(rows), "")

    # Create a vdisk-host mapping
    def _cmd_mkvdiskhostmap(self, arg_list):
        mapping_info = {}
        mapping_info["id"] = self._find_unused_id(self._mappings_list)
        try:
            arg_index = arg_list.index("-host") + 1
            mapping_info["host"] = self._strip_quotes(arg_list[arg_index])
        except (ValueError, IndexError):
            return self._errors["CMMVC5707E"]

        try:
            arg_index = arg_list.index("-scsi") + 1
            mapping_info["lun"] = self._strip_quotes(arg_list[arg_index])
        except (ValueError, IndexError):
            return self._errors["CMMVC5707E"]

        mapping_info["vol"] = self._strip_quotes(arg_list[-1])

        if not mapping_info["vol"] in self._volumes_list:
            return self._errors["CMMVC5753E"]

        if not mapping_info["host"] in self._hosts_list:
            return self._errors["CMMVC5754E"]

        if mapping_info["vol"] in self._mappings_list:
            return self._errors["CMMVC6071E"]

        for k, v in self._mappings_list.iteritems():
            if ((v["host"] == mapping_info["host"]) and
                    (v["lun"] == mapping_info["lun"])):
                return self._errors["CMMVC5879E"]

        self._mappings_list[mapping_info["vol"]] = mapping_info
        return ("Virtual Disk to Host map, id [%s], successfully created"
                % (mapping_info["id"]), "")

    # Delete a vdisk-host mapping
    def _cmd_rmvdiskhostmap(self, arg_list):
        try:
            host = self._strip_quotes(arg_list[arg_list.index("-host") + 1])
        except (ValueError, IndexError):
            return self._errors["CMMVC5707E"]

        vol = self._strip_quotes(arg_list[-1])

        if not vol in self._mappings_list:
            return self._errors["CMMVC5753E"]

        if self._mappings_list[vol]["host"] != host:
            return self._errors["CMMVC5753E"]

        del self._mappings_list[vol]
        return ("", "")

    # List information about vdisk-host mappings
    def _cmd_lshostvdiskmap(self, arg_list):
        index = 1
        no_hdr = 0
        delimeter = ""
        host_name = ""
        while index < len(arg_list):
            try:
                if arg_list[index] == "-delim":
                    delimeter = arg_list[index + 1]
                    index += 2
                elif arg_list[index] == "-nohdr":
                    no_hdr = 1
                    index += 1
                else:
                    host_name = arg_list[index]
                    index += 1
            except IndexError:
                return self._errors["CMMVC5708E"]

        if host_name not in self._hosts_list:
            return self._errors["CMMVC5754E"]

        rows = []
        rows.append(["id", "name", "SCSI_id", "vdisk_id", "vdisk_name",
                     "vdisk_UID"])

        for k, mapping in self._mappings_list.iteritems():
            if (host_name == "") or (mapping["host"] == host_name):
                volume = self._volumes_list[mapping["vol"]]
                rows.append([mapping["id"], mapping["host"],
                            mapping["lun"], volume["id"],
                            volume["name"], volume["uid"]])

        return self._print_info_cmd(arg_list, rows)

    # Create a FlashCopy mapping
    def _cmd_mkfcmap(self, arg_list):
        source = ""
        target = ""

        try:
            arg_index = arg_list.index("-source") + 1
            source = self._strip_quotes(arg_list[arg_index])
        except (ValueError, IndexError):
            return self._errors["CMMVC5707E"]
        if not source in self._volumes_list:
            return self._errors["CMMVC5754E"]

        try:
            arg_index = arg_list.index("-target") + 1
            target = self._strip_quotes(arg_list[arg_index])
        except (ValueError, IndexError):
            return self._errors["CMMVC5707E"]
        if not target in self._volumes_list:
            return self._errors["CMMVC5754E"]

        if source == target:
            return self._errors["CMMVC6303E"]

        if (self._volumes_list[source]["capacity"] !=
                self._volumes_list[target]["capacity"]):
            return ("", "%s != %s" % (self._volumes_list[source]["capacity"],
                    self._volumes_list[target]["capacity"]))

        fcmap_info = {}
        fcmap_info["source"] = source
        fcmap_info["target"] = target
        fcmap_info["id"] = self._find_unused_id(self._fcmappings_list)
        fcmap_info["name"] = "fcmap" + fcmap_info["id"]
        fcmap_info["status"] = "idle_or_copied"
        fcmap_info["progress"] = "0"
        self._fcmappings_list[target] = fcmap_info

        return("FlashCopy Mapping, id [" + fcmap_info["id"] +
               "], successfully created", "")

    # Same function used for both prestartfcmap and startfcmap
    def _cmd_gen_startfcmap(self, arg_list, mode):
        if len(arg_list) == 1:
            return self._errors["CMMVC5701E"]
        elif len(arg_list) > 2:
            return self._errors["CMMVC6070E"]
        id_num = arg_list[1]

        for k, fcmap in self._fcmappings_list.iteritems():
            if fcmap["id"] == id_num:
                if mode == "pre":
                    fcmap["status"] = "preparing"
                else:
                    fcmap["status"] = "copying"
                fcmap["progress"] = "0"
                return ("", "")
        return self._errors["CMMVC5753E"]

    def _cmd_lsfcmap(self, arg_list):
        rows = []
        rows.append(["id", "name", "source_vdisk_id", "source_vdisk_name",
                     "target_vdisk_id", "target_vdisk_name", "group_id",
                     "group_name", "status", "progress", "copy_rate",
                     "clean_progress", "incremental", "partner_FC_id",
                     "partner_FC_name", "restoring", "start_time",
                     "rc_controlled"])

        # Assume we always get a filtervalue argument
        arg_index = arg_list.index("-filtervalue")
        filter_key = arg_list[arg_index + 1].split("=")[0]
        filter_value = arg_list[arg_index + 1].split("=")[1]
        to_delete = []
        for k, v in self._fcmappings_list.iteritems():
            if str(v[filter_key]) == filter_value:
                source = self._volumes_list[v["source"]]
                target = self._volumes_list[v["target"]]
                rows.append([v["id"], v["name"], source["id"],
                            source["name"], target["id"], target["name"], "",
                            "", v["status"], v["progress"], "50", "100",
                            "off", "", "", "no", "", "no"])
                if v["status"] == "preparing":
                    v["status"] = "prepared"
                elif (v["status"] == "copying") and (v["progress"] == "0"):
                    v["progress"] = "50"
                elif (v["status"] == "copying") and (v["progress"] == "50"):
                    to_delete.append(k)

        for d in to_delete:
            del self._fcmappings_list[k]

        return self._print_info_cmd(arg_list, rows)

    # The main function to run commands on the management simulator
    def execute_command(self, cmd, check_exit_code=True):
        arg_list = cmd.split()

        if arg_list[0] == "lsmdiskgrp":
            out, err = self._cmd_lsmdiskgrp(arg_list)
        elif arg_list[0] == "lsnodecanister":
            out, err = self._cmd_lsnodecanister(arg_list)
        elif arg_list[0] == "lsportip":
            out, err = self._cmd_lsportip(arg_list)
        elif arg_list[0] == "mkvdisk":
            out, err = self._cmd_mkvdisk(arg_list)
        elif arg_list[0] == "rmvdisk":
            out, err = self._cmd_rmvdisk(arg_list)
        elif arg_list[0] == "lsvdisk":
            out, err = self._cmd_lsvdisk(arg_list)
        elif arg_list[0] == "mkhost":
            out, err = self._cmd_mkhost(arg_list)
        elif arg_list[0] == "rmhost":
            out, err = self._cmd_rmhost(arg_list)
        elif arg_list[0] == "lshost":
            out, err = self._cmd_lshost(arg_list)
        elif arg_list[0] == "mkvdiskhostmap":
            out, err = self._cmd_mkvdiskhostmap(arg_list)
        elif arg_list[0] == "rmvdiskhostmap":
            out, err = self._cmd_rmvdiskhostmap(arg_list)
        elif arg_list[0] == "lshostvdiskmap":
            out, err = self._cmd_lshostvdiskmap(arg_list)
        elif arg_list[0] == "mkfcmap":
            out, err = self._cmd_mkfcmap(arg_list)
        elif arg_list[0] == "prestartfcmap":
            out, err = self._cmd_gen_startfcmap(arg_list, "pre")
        elif arg_list[0] == "startfcmap":
            out, err = self._cmd_gen_startfcmap(arg_list, "start")
        elif arg_list[0] == "lsfcmap":
            out, err = self._cmd_lsfcmap(arg_list)
        else:
            out, err = ("", "ERROR: Unsupported command")

        if (check_exit_code) and (len(err) != 0):
            raise exception.ProcessExecutionError(exit_code=1,
                                                  stdout=out,
                                                  stderr=err,
                                                  cmd=' '.join(cmd))

        return (out, err)

    # After calling this function, the next call to the specified command will
    # result in in the error specified
    def error_injection(self, cmd, error):
        self._next_cmd_error[cmd] = error


class StorwizeSVCFakeDriver(storwize_svc.StorwizeSVCDriver):
    def __init__(self, *args, **kwargs):
        super(StorwizeSVCFakeDriver, self).__init__(*args, **kwargs)

    def set_fake_storage(self, fake):
        self.fake_storage = fake

    def _run_ssh(self, cmd, check_exit_code=True):
        try:
            LOG.debug(_('Run CLI command: %s') % cmd)
            ret = self.fake_storage.execute_command(cmd, check_exit_code)
            (stdout, stderr) = ret
            LOG.debug(_('CLI output:\n stdout: %(out)s\n stderr: %(err)s') %
                        {'out': stdout, 'err': stderr})

        except exception.ProcessExecutionError as e:
            with excutils.save_and_reraise_exception():
                LOG.debug(_('CLI Exception output:\n stdout: %(out)s\n '
                            'stderr: %(err)s') % {'out': e.stdout,
                            'err': e.stderr})

        return ret


class StorwizeSVCDriverTestCase(test.TestCase):
    def setUp(self):
        super(StorwizeSVCDriverTestCase, self).setUp()
        self.USESIM = 1
        if self.USESIM == 1:
            self.sim = StorwizeSVCManagementSimulator("volpool")
            driver = StorwizeSVCFakeDriver()
            driver.set_fake_storage(self.sim)
            storwize_svc.FLAGS.san_ip = "hostname"
            storwize_svc.FLAGS.san_login = "user"
            storwize_svc.FLAGS.san_password = "pass"
            storwize_svc.FLAGS.storwize_svc_volpool_name = "volpool"
            storwize_svc.FLAGS.storwize_svc_flashcopy_timeout = "20"
        else:
            driver = storwize_svc.StorwizeSVCDriver()
            storwize_svc.FLAGS.san_ip = "-1.-1.-1.-1"
            storwize_svc.FLAGS.san_login = "user"
            storwize_svc.FLAGS.san_password = "password"
            storwize_svc.FLAGS.storwize_svc_volpool_name = "pool"

        self.driver = driver
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()

    def test_storwize_svc_volume_non_space_efficient(self):
        storwize_svc.FLAGS.storwize_svc_vol_rsize = "-1"
        volume = {}
        volume["name"] = "test1_volume%s" % random.randint(10000, 99999)
        volume["size"] = 10
        volume["id"] = 1
        self.driver.create_volume(volume)
        # Make sure that the volume has been created
        is_volume_defined = self.driver._is_volume_defined(volume["name"])
        self.assertEqual(is_volume_defined, True)

        self.driver.delete_volume(volume)

    def test_storwize_svc_connectivity(self):
        # Make sure we detect if the pool doesn't exist
        orig_pool = getattr(storwize_svc.FLAGS, "storwize_svc_volpool_name")
        no_exist_pool = "i-dont-exist-%s" % random.randint(10000, 99999)
        storwize_svc.FLAGS.storwize_svc_volpool_name = no_exist_pool
        self.assertRaises(exception.InvalidInput,
                self.driver.check_for_setup_error)
        storwize_svc.FLAGS.storwize_svc_volpool_name = orig_pool

        # Check the case where the user didn't configure IP addresses
        if self.USESIM == 1:
            self.sim.error_injection("lsportip", "ip_no_config")
            self.assertRaises(exception.VolumeBackendAPIException,
                    self.driver.check_for_setup_error)

        # Finally, check with good parameters
        self.driver.check_for_setup_error()

    def test_storwize_svc_flashcopy(self):
        volume1 = {}
        volume1["name"] = "test_volume%s" % random.randint(10000, 99999)
        volume1["size"] = 10
        volume1["id"] = 10
        self.driver.create_volume(volume1)

        snapshot = {}
        snapshot["name"] = "snap_volume%s" % random.randint(10000, 99999)
        snapshot["volume_name"] = volume1["name"]
        self.driver.create_snapshot(snapshot)

        is_volume_defined = self.driver._is_volume_defined(snapshot["name"])
        self.assertEqual(is_volume_defined, True)

        self.driver._delete_snapshot(snapshot, True)
        self.driver._delete_volume(volume1, True)

    def test_storwize_svc_volumes(self):
        # Create a first volume
        volume = {}
        volume["name"] = "test1_volume%s" % random.randint(10000, 99999)
        volume["size"] = 10
        volume["id"] = 1
        self.driver.create_volume(volume)

        # Make sure that the volume has been created
        is_volume_defined = self.driver._is_volume_defined(volume["name"])
        self.assertEqual(is_volume_defined, True)

        # Make sure volume attributes are as they should be
        attributes = self.driver._get_volume_attributes(volume["name"])
        attr_size = float(attributes["capacity"]) / 1073741824  # bytes to GB
        self.assertEqual(attr_size, float(volume["size"]))
        pool = getattr(storwize_svc.FLAGS, "storwize_svc_volpool_name")
        self.assertEqual(attributes["mdisk_grp_name"], pool)
        vtype = getattr(storwize_svc.FLAGS, "storwize_svc_vol_vtype")
        self.assertEqual(attributes["type"], vtype)

        # Try to create the volume again (should fail)
        self.assertRaises(exception.ProcessExecutionError,
                self.driver.create_volume, volume)

        # Try to delete a volume that doesn't exist (should not fail)
        vol_no_exist = {"name": "i_dont_exist"}
        self.driver.delete_volume(vol_no_exist)

        # Delete the volume
        self.driver.delete_volume(volume)

    def test_storwize_svc_host_maps(self):
        # Create two volumes to be used in mappings
        volume1 = {}
        volume1["name"] = "test1_volume%s" % random.randint(10000, 99999)
        volume1["size"] = 2
        volume1["id"] = 1
        self.driver.create_volume(volume1)
        volume2 = {}
        volume2["name"] = "test2_volume%s" % random.randint(10000, 99999)
        volume2["size"] = 2
        volume2["id"] = 1
        self.driver.create_volume(volume2)

        # Make sure that the volumes have been created
        is_volume_defined = self.driver._is_volume_defined(volume1["name"])
        self.assertEqual(is_volume_defined, True)
        is_volume_defined = self.driver._is_volume_defined(volume2["name"])
        self.assertEqual(is_volume_defined, True)

        # Initialize connection from the first volume to a host
        # Add some characters to the initiator name that should be converted
        # when used for the host name
        conn = {}
        conn["initiator"] = "test:init:%s" % random.randint(10000, 99999)
        conn["ip"] = "10.10.10.10"  # Bogus ip for testing
        self.driver.initialize_connection(volume1, conn)

        # Initialize connection from the second volume to the host
        self.driver.initialize_connection(volume2, conn)

        # Try to delete the 1st volume (should fail because it is mapped)
        self.assertRaises(exception.ProcessExecutionError,
                self.driver.delete_volume, volume1)

        # Try to remove connection from host that doesn't exist (should fail)
        conn_no_exist = {"initiator": "i_dont_exist"}
        self.assertRaises(exception.VolumeBackendAPIException,
                self.driver.terminate_connection, volume1, conn_no_exist)

        # Try to remove connection from volume that isn't mapped (should print
        # message but NOT fail)
        vol_no_exist = {"name": "i_dont_exist"}
        self.driver.terminate_connection(vol_no_exist, conn)

        # Remove the mapping from the 1st volume and delete it
        self.driver.terminate_connection(volume1, conn)
        self.driver.delete_volume(volume1)
        vol_def = self.driver._is_volume_defined(volume1["name"])
        self.assertEqual(vol_def, False)

        # Make sure our host still exists
        host_name = self.driver._get_host_from_iscsiname(conn["initiator"])
        host_def = self.driver._is_host_defined(host_name)
        self.assertEquals(host_def, True)

        # Remove the mapping from the 2nd volume and delete it. The host should
        # be automatically removed because there are no more mappings.
        self.driver.terminate_connection(volume2, conn)
        self.driver.delete_volume(volume2)
        vol_def = self.driver._is_volume_defined(volume2["name"])
        self.assertEqual(vol_def, False)

        # Check if our host still exists (it should not)
        ret = self.driver._get_host_from_iscsiname(conn["initiator"])
        self.assertEquals(ret, None)
        ret = self.driver._is_host_defined(host_name)
        self.assertEquals(ret, False)
