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
"""
Base Lookup Service for name server lookup to find the initiator to target port
mapping for available SAN contexts.
Vendor specific lookup classes are expected to implement the interfaces
defined in this class.

"""

from oslo_log import log as logging
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _
from cinder.volume import configuration as config
from cinder.zonemanager import fc_common
from cinder.zonemanager import fc_zone_manager


LOG = logging.getLogger(__name__)


class FCSanLookupService(fc_common.FCCommon):
    """Base Lookup Service.

    Base Lookup Service for name server lookup to find the initiator to
    target port mapping for available SAN contexts.

    """

    lookup_service = None

    def __init__(self, **kwargs):
        super(FCSanLookupService, self).__init__(**kwargs)

        opts = fc_zone_manager.zone_manager_opts
        self.configuration = config.Configuration(opts, 'fc-zone-manager')

    def get_device_mapping_from_network(self, initiator_list, target_list):
        """Get device mapping from FC network.

        Gets a filtered list of initiator ports and target ports for each SAN
        available.
        :param initiator_list: list of initiator port WWN
        :param target_list: list of target port WWN
        :returns: device wwn map in following format

        .. code-block:: python

            {
                <San name>: {
                    'initiator_port_wwn_list':
                    ('200000051E55A100', '200000051E55A121'..)
                    'target_port_wwn_list':
                    ('100000051E55A100', '100000051E55A121'..)
                }
            }

        :raises Exception: when a lookup service implementation is not
                 specified in cinder.conf:fc_san_lookup_service
        """
        # Initialize vendor specific implementation of  FCZoneDriver
        if (self.configuration.fc_san_lookup_service):
            lookup_service = self.configuration.fc_san_lookup_service
            LOG.debug("Lookup service to invoke: "
                      "%s", lookup_service)
            self.lookup_service = importutils.import_object(
                lookup_service, configuration=self.configuration)
        else:
            msg = _("Lookup service not configured. Config option for "
                    "fc_san_lookup_service needs to specify a concrete "
                    "implementation of the lookup service.")
            LOG.error(msg)
            raise exception.FCSanLookupServiceException(msg)
        try:
            device_map = self.lookup_service.get_device_mapping_from_network(
                initiator_list, target_list)
        except Exception as e:
            LOG.exception('Unable to get device mapping from network.')
            raise exception.FCSanLookupServiceException(e)
        return device_map
