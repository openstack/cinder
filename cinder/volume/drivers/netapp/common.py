# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2012 OpenStack Foundation
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
Unified driver for NetApp storage systems.

Supports call to multiple storage systems of different families and protocols.
"""

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.netapp.options import netapp_proxy_opts


LOG = logging.getLogger(__name__)


#NOTE(singn): Holds family:{protocol:driver} registration information.
#Plug in new families and protocols to support new drivers.
#No other code modification required.
netapp_unified_plugin_registry =\
    {'ontap_cluster':
     {
         'iscsi':
         'cinder.volume.drivers.netapp.iscsi.NetAppDirectCmodeISCSIDriver',
         'nfs': 'cinder.volume.drivers.netapp.nfs.NetAppDirectCmodeNfsDriver'
     },
     'ontap_7mode':
     {
         'iscsi':
         'cinder.volume.drivers.netapp.iscsi.NetAppDirect7modeISCSIDriver',
         'nfs':
         'cinder.volume.drivers.netapp.nfs.NetAppDirect7modeNfsDriver'
     },
     'eseries':
     {
         'iscsi':
         'cinder.volume.drivers.netapp.eseries.iscsi.Driver'
     },
     }

#NOTE(singn): Holds family:protocol information.
#Protocol represents the default protocol driver option
#in case no protocol is specified by the user in configuration.
netapp_family_default =\
    {
        'ontap_cluster': 'nfs',
        'ontap_7mode': 'nfs',
        'eseries': 'iscsi'
    }


class NetAppDriver(object):
    """"NetApp unified block storage driver.

       Acts as a mediator to NetApp storage drivers.
       Proxies requests based on the storage family and protocol configured.
       Override the proxy driver method by adding method in this driver.
    """

    def __init__(self, *args, **kwargs):
        super(NetAppDriver, self).__init__()
        self.configuration = kwargs.get('configuration', None)
        if self.configuration:
            self.configuration.append_config_values(netapp_proxy_opts)
        else:
            raise exception.InvalidInput(
                reason=_("Required configuration not found"))
        self.driver = NetAppDriverFactory.create_driver(
            self.configuration.netapp_storage_family,
            self.configuration.netapp_storage_protocol,
            *args, **kwargs)

    def __setattr__(self, name, value):
        """Sets the attribute."""
        if getattr(self, 'driver', None):
            self.driver.__setattr__(name, value)
            return
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        """"Gets the attribute."""
        drv = object.__getattribute__(self, 'driver')
        return getattr(drv, name)


class NetAppDriverFactory(object):
    """Factory to instantiate appropriate NetApp driver."""

    @staticmethod
    def create_driver(
            storage_family, storage_protocol, *args, **kwargs):
        """"Creates an appropriate driver based on family and protocol."""
        fmt = {'storage_family': storage_family,
               'storage_protocol': storage_protocol}
        LOG.info(_('Requested unified config: %(storage_family)s and '
                   '%(storage_protocol)s') % fmt)
        storage_family = storage_family.lower()
        family_meta = netapp_unified_plugin_registry.get(storage_family)
        if family_meta is None:
            raise exception.InvalidInput(
                reason=_('Storage family %s is not supported')
                % storage_family)
        if storage_protocol is None:
            storage_protocol = netapp_family_default.get(storage_family)
            fmt['storage_protocol'] = storage_protocol
        if storage_protocol is None:
            raise exception.InvalidInput(
                reason=_('No default storage protocol found'
                         ' for storage family %(storage_family)s')
                % fmt)
        storage_protocol = storage_protocol.lower()
        driver_loc = family_meta.get(storage_protocol)
        if driver_loc is None:
            raise exception.InvalidInput(
                reason=_('Protocol %(storage_protocol)s is not supported'
                         ' for storage family %(storage_family)s')
                % fmt)
        NetAppDriverFactory.check_netapp_driver(driver_loc)
        kwargs = kwargs or {}
        kwargs['netapp_mode'] = 'proxy'
        driver = importutils.import_object(driver_loc, *args, **kwargs)
        LOG.info(_('NetApp driver of family %(storage_family)s and protocol'
                   ' %(storage_protocol)s loaded') % fmt)
        return driver

    @staticmethod
    def check_netapp_driver(location):
        """Checks if the driver requested is a netapp driver."""
        if location.find(".netapp.") == -1:
            raise exception.InvalidInput(
                reason=_("Only loading netapp drivers supported."))


class Deprecated(driver.VolumeDriver):
    """Deprecated driver for NetApp.

        This driver is used for mapping deprecated
        drivers to itself in manager. It prevents cinder
        from getting errored out in case of upgrade scenarios
        and also suggests further steps.
    """

    def __init__(self, *args, **kwargs):
        self._log_deprecated_warn()

    def _log_deprecated_warn(self):
        """Logs appropriate warning and suggestion."""

        link = "https://communities.netapp.com/groups/openstack"
        msg = _("The configured NetApp driver is deprecated."
                " Please refer the link to resolve the issue '%s'.")
        LOG.warn(msg % link)

    def check_for_setup_error(self):
        pass

    def ensure_export(self, context, volume):
        pass

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service. If 'refresh' is
           True, run the update first.
        """
        self._log_deprecated_warn()
        return None
