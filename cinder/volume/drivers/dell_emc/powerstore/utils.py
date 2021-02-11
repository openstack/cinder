# Copyright (c) 2020 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Utilities for Dell EMC PowerStore Cinder driver."""

import functools
import re

from oslo_log import log as logging
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume.drivers.dell_emc.powerstore import driver
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)
CHAP_DEFAULT_USERNAME = "PowerStore_iSCSI_CHAP_Username"
CHAP_DEFAULT_SECRET_LENGTH = 60


def bytes_to_gib(size_in_bytes):
    """Convert size in bytes to GiB.

    :param size_in_bytes: size in bytes
    :return: size in GiB
    """

    return size_in_bytes // units.Gi


def gib_to_bytes(size_in_gb):
    """Convert size in GiB to bytes.

    :param size_in_gb: size in GiB
    :return: size in bytes
    """

    return size_in_gb * units.Gi


def extract_fc_wwpns(connector):
    """Convert connector FC ports to appropriate format with colons.

    :param connector: connection properties
    :return: FC ports in appropriate format with colons
    """

    if "wwnns" not in connector or "wwpns" not in connector:
        msg = _("Host %s does not have FC initiators.") % connector["host"]
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)
    return [":".join(re.findall("..", wwpn)) for wwpn in connector["wwpns"]]


def fc_wwn_to_string(wwn):
    """Convert FC WWN to string without colons.

    :param wwn: FC WWN
    :return: FC WWN without colons
    """

    return wwn.replace(":", "")


def iscsi_portal_with_port(address):
    """Add default port 3260 to iSCSI portal

    :param address: iSCSI portal without port
    :return: iSCSI portal with default port 3260
    """

    return "%(address)s:3260" % {"address": address}


def powerstore_host_name(connector, protocol):
    """Generate PowerStore host name for connector.

    :param connector: connection properties
    :param protocol: storage protocol (FC or iSCSI)
    :return: unique host name
    """

    return ("%(host)s-%(protocol)s" %
            {"host": connector["host"],
             "protocol": protocol, })


def filter_hosts_by_initiators(hosts, initiators):
    """Filter hosts by given list of initiators.

    :param hosts: list of PowerStore host objects
    :param initiators: list of initiators
    :return: PowerStore hosts list
    """

    hosts_names_found = set()
    for host in hosts:
        for initiator in host["host_initiators"]:
            if initiator["port_name"] in initiators:
                hosts_names_found.add(host["name"])
    return list(filter(lambda host: host["name"] in hosts_names_found, hosts))


def is_multiattached_to_host(volume_attachment, host_name):
    """Check if volume is attached to multiple instances on one host.

    When multiattach is enabled, a volume could be attached to two or more
    instances which are hosted on one nova host.
    Because PowerStore cannot recognize the volume is attached to two or more
    instances, we should keep the volume attached to the nova host until
    the volume is detached from the last instance.

    :param volume_attachment: list of VolumeAttachment objects
    :param host_name: OpenStack host name
    :return: multiattach flag
    """

    if not volume_attachment:
        return False

    attachments = [
        attachment for attachment in volume_attachment
        if (attachment.attach_status == fields.VolumeAttachStatus.ATTACHED and
            attachment.attached_host == host_name)
    ]
    return len(attachments) > 1


def get_chap_credentials():
    """Generate CHAP credentials.

    :return: CHAP username and secret
    """

    return {
        "chap_single_username": CHAP_DEFAULT_USERNAME,
        "chap_single_password": volume_utils.generate_password(
            CHAP_DEFAULT_SECRET_LENGTH
        )
    }


def get_protection_policy_from_volume(volume):
    """Get PowerStore Protection policy name from volume type.

    :param volume: OpenStack Volume object
    :return: Protection policy name
    """

    return volume.volume_type.extra_specs.get(driver.POWERSTORE_PP_KEY)


def is_group_a_cg_snapshot_type(func):
    """Check if group is a consistent snapshot group.

    Fallback to generic volume group implementation if consistent group
    snapshot is not enabled.
    """

    @functools.wraps(func)
    def inner(self, *args, **kwargs):
        if not volume_utils.is_group_a_cg_snapshot_type(args[0]):
            raise NotImplementedError
        return func(self, *args, **kwargs)
    return inner
