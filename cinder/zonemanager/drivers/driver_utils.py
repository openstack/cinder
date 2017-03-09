#    (c) Copyright 2014 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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

import re

from oslo_log import log

LOG = log.getLogger(__name__)


def get_friendly_zone_name(zoning_policy, initiator, target,
                           host_name, storage_system, zone_name_prefix,
                           supported_chars):
    """Utility function implementation of _get_friendly_zone_name.

    Get friendly zone name is used to form the zone name
    based on the details provided by the caller

    :param zoning_policy: determines the zoning policy is either
                          initiator-target or initiator
    :param initiator: initiator WWN
    :param target: target WWN
    :param host_name: Host name returned from Volume Driver
    :param storage_system: Storage name returned from Volume Driver
    :param zone_name_prefix: user defined zone prefix configured
                             in cinder.conf
    :param supported_chars: Supported character set of FC switch vendor.
                            Example: `abc123_-$`. These are defined in
                            the FC zone drivers.
    """
    if host_name is None:
        host_name = ''
    if storage_system is None:
        storage_system = ''
    if zoning_policy == 'initiator-target':
        host_name = host_name[:14]
        storage_system = storage_system[:14]
        if len(host_name) > 0 and len(storage_system) > 0:
            zone_name = (host_name + "_"
                         + initiator.replace(':', '') + "_"
                         + storage_system + "_"
                         + target.replace(':', ''))
        else:
            zone_name = (zone_name_prefix
                         + initiator.replace(':', '')
                         + target.replace(':', ''))
            LOG.info("Zone name created using prefix because either "
                     "host name or storage system is none.")
    else:
        host_name = host_name[:47]
        if len(host_name) > 0:
            zone_name = (host_name + "_"
                         + initiator.replace(':', ''))
        else:
            zone_name = (zone_name_prefix
                         + initiator.replace(':', ''))
            LOG.info("Zone name created using prefix because host "
                     "name is none.")

    LOG.info("Friendly zone name after forming: %(zonename)s",
             {'zonename': zone_name})
    zone_name = re.sub('[^%s]' % supported_chars, '', zone_name)
    return zone_name
