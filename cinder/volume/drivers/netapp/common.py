# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Alex Meade.  All Rights Reserved.
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
Unified driver for NetApp storage systems.

Supports multiple storage systems of different families and protocols.
"""

from oslo_log import log as logging
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _, _LI
from cinder.volume import driver
from cinder.volume.drivers.netapp import options
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)

DATAONTAP_PATH = 'cinder.volume.drivers.netapp.dataontap'
ESERIES_PATH = 'cinder.volume.drivers.netapp.eseries'

# Add new drivers here, no other code changes required.
NETAPP_UNIFIED_DRIVER_REGISTRY = {
    'ontap_cluster':
    {
        'iscsi': DATAONTAP_PATH + '.iscsi_cmode.NetAppCmodeISCSIDriver',
        'nfs': DATAONTAP_PATH + '.nfs_cmode.NetAppCmodeNfsDriver',
        'fc': DATAONTAP_PATH + '.fc_cmode.NetAppCmodeFibreChannelDriver'
    },
    'ontap_7mode':
    {
        'iscsi': DATAONTAP_PATH + '.iscsi_7mode.NetApp7modeISCSIDriver',
        'nfs': DATAONTAP_PATH + '.nfs_7mode.NetApp7modeNfsDriver',
        'fc': DATAONTAP_PATH + '.fc_7mode.NetApp7modeFibreChannelDriver'
    },
    'eseries':
    {
        'iscsi': ESERIES_PATH + '.iscsi_driver.NetAppEseriesISCSIDriver',
        'fc': ESERIES_PATH + '.fc_driver.NetAppEseriesFibreChannelDriver'
    }}


class NetAppDriver(driver.ProxyVD):
    """NetApp unified block storage driver.

       Acts as a factory to create NetApp storage drivers based on the
       storage family and protocol configured.
    """

    REQUIRED_FLAGS = ['netapp_storage_family', 'netapp_storage_protocol']

    def __new__(cls, *args, **kwargs):

        config = kwargs.get('configuration', None)
        if not config:
            raise exception.InvalidInput(
                reason=_('Required configuration not found'))

        config.append_config_values(options.netapp_proxy_opts)
        na_utils.check_flags(NetAppDriver.REQUIRED_FLAGS, config)

        app_version = na_utils.OpenStackInfo().info()
        LOG.info(_LI('OpenStack OS Version Info: %(info)s'),
                 {'info': app_version})
        kwargs['app_version'] = app_version

        return NetAppDriver.create_driver(config.netapp_storage_family,
                                          config.netapp_storage_protocol,
                                          *args, **kwargs)

    @staticmethod
    def create_driver(storage_family, storage_protocol, *args, **kwargs):
        """Creates an appropriate driver based on family and protocol."""

        storage_family = storage_family.lower()
        storage_protocol = storage_protocol.lower()

        fmt = {'storage_family': storage_family,
               'storage_protocol': storage_protocol}
        LOG.info(_LI('Requested unified config: %(storage_family)s and '
                     '%(storage_protocol)s.'), fmt)

        family_meta = NETAPP_UNIFIED_DRIVER_REGISTRY.get(storage_family)
        if family_meta is None:
            raise exception.InvalidInput(
                reason=_('Storage family %s is not supported.')
                % storage_family)

        driver_loc = family_meta.get(storage_protocol)
        if driver_loc is None:
            raise exception.InvalidInput(
                reason=_('Protocol %(storage_protocol)s is not supported '
                         'for storage family %(storage_family)s.') % fmt)

        kwargs = kwargs or {}
        kwargs['netapp_mode'] = 'proxy'
        driver = importutils.import_object(driver_loc, *args, **kwargs)
        LOG.info(_LI('NetApp driver of family %(storage_family)s and protocol '
                     '%(storage_protocol)s loaded.'), fmt)
        return driver
