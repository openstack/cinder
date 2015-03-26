# Copyright (c) 2012 - 2015 EMC Corporation.
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
ISCSI Drivers for EMC VMAX arrays based on SMI-S.

"""
import os

from oslo_log import log as logging
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder.volume import driver
from cinder.volume.drivers.emc import emc_vmax_common


LOG = logging.getLogger(__name__)

CINDER_CONF = '/etc/cinder/cinder.conf'


class EMCVMAXISCSIDriver(driver.ISCSIDriver):
    """EMC ISCSI Drivers for VMAX using SMI-S.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Multiple pools and thick/thin provisioning,
                performance enhancement.
        2.0.0 - Add driver requirement functions
        2.1.0 - Add consistency group functions
    """

    VERSION = "2.1.0"

    def __init__(self, *args, **kwargs):

        super(EMCVMAXISCSIDriver, self).__init__(*args, **kwargs)
        self.common =\
            emc_vmax_common.EMCVMAXCommon('iSCSI',
                                          configuration=self.configuration)

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a EMC(VMAX/VNX) volume."""
        volpath = self.common.create_volume(volume)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        volpath = self.common.create_volume_from_snapshot(volume, snapshot)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        volpath = self.common.create_cloned_volume(volume, src_vref)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        ctxt = context.get_admin_context()
        volumename = snapshot['volume_name']
        index = volumename.index('-')
        volumeid = volumename[index + 1:]
        volume = self.db.volume_get(ctxt, volumeid)

        volpath = self.common.create_snapshot(snapshot, volume)

        model_update = {}
        snapshot['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = snapshot['provider_location']
        return model_update

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        ctxt = context.get_admin_context()
        volumename = snapshot['volume_name']
        index = volumename.index('-')
        volumeid = volumename[index + 1:]
        volume = self.db.volume_get(ctxt, volumeid)

        self.common.delete_snapshot(snapshot, volume)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        the format of the driver data is defined in smis_get_iscsi_properties.
        Example return value::
            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': '12345678-1234-4321-1234-123456789012',
                }
            }
        """
        self.common.initialize_connection(
            volume, connector)

        iscsi_properties = self.smis_get_iscsi_properties(
            volume, connector)

        LOG.info(_LI("Leaving initialize_connection: %s"), (iscsi_properties))
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def smis_do_iscsi_discovery(self, volume):
        LOG.info(_LI("ISCSI provider_location not stored, using discovery."))
        if not self._check_for_iscsi_ip_address():
            LOG.error(_LE(
                "You must set your iscsi_ip_address in cinder.conf."))

        (out, _err) = self._execute('iscsiadm', '-m', 'discovery',
                                    '-t', 'sendtargets', '-p',
                                    self.configuration.iscsi_ip_address,
                                    run_as_root=True)

        LOG.info(_LI(
            "smis_do_iscsi_discovery is: %(out)s."),
            {'out': out})
        targets = []
        for target in out.splitlines():
            targets.append(target)

        return targets

    def smis_get_iscsi_properties(self, volume, connector):
        """Gets iscsi configuration.

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in future
        The properties are:
        :target_discovered:    boolean indicating whether discovery was used
        :target_iqn:    the IQN of the iSCSI target
        :target_portal:    the portal of the iSCSI target
        :target_lun:    the lun of the iSCSI target
        :volume_id:    the UUID of the volume
        :auth_method:, :auth_username:, :auth_password:
            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.
        """
        properties = {}

        location = self.smis_do_iscsi_discovery(volume)
        if not location:
            raise exception.InvalidVolume(_("Could not find iSCSI export "
                                          " for volume %(volumeName)s.")
                                          % {'volumeName': volume['name']})

        LOG.debug("ISCSI Discovery: Found %s", (location))
        properties['target_discovered'] = True

        device_info = self.common.find_device_number(volume)

        if device_info is None or device_info['hostlunid'] is None:
            exception_message = (_("Cannot find device number for volume "
                                 "%(volumeName)s.")
                                 % {'volumeName': volume['name']})
            raise exception.VolumeBackendAPIException(data=exception_message)

        device_number = device_info['hostlunid']

        LOG.info(_LI(
            "location is: %(location)s"), {'location': location})

        for loc in location:
            results = loc.split(" ")
            properties['target_portal'] = results[0].split(",")[0]
            properties['target_iqn'] = results[1]

        properties['target_lun'] = device_number

        properties['volume_id'] = volume['id']

        LOG.info(_LI(
            "ISCSI properties: %(properties)s"), {'properties': properties})
        LOG.info(_LI(
            "ISCSI volume is: %(volume)s"), {'volume': volume})

        if 'provider_auth' in volume:
            auth = volume['provider_auth']
            LOG.info(_LI(
                "AUTH properties: %(authProps)s"), {'authProps': auth})

            if auth is not None:
                (auth_method, auth_username, auth_secret) = auth.split()

                properties['auth_method'] = auth_method
                properties['auth_username'] = auth_username
                properties['auth_password'] = auth_secret

                LOG.info(_LI("AUTH properties: %s."), (properties))

        return properties

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        self.common.terminate_connection(volume, connector)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        self.common.extend_volume(volume, new_size)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug("Updating volume stats")
        data = self.common.update_volume_stats()
        data['storage_protocol'] = 'iSCSI'
        data['driver_version'] = self.VERSION
        self._stats = data

    def migrate_volume(self, ctxt, volume, host):
        """Migrate a volume from one Volume Backend to another.

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param host: the host dict holding the relevant target information
        :returns: boolean -- Always returns True
        :returns: dict -- Empty dict {}
        """
        return self.common.migrate_volume(ctxt, volume, host)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Migrate volume to another host using retype.

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param new_type: the new volume type.
        :param diff: Unused parameter in common.retype
        :param host: the host dict holding the relevant target information
        :returns: boolean -- True if retype succeeded, False if error
        """
        return self.common.retype(ctxt, volume, new_type, diff, host)

    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
        self.common.create_consistencygroup(context, group)

    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""
        volumes = self.db.volume_get_all_by_group(context, group['id'])
        return self.common.delete_consistencygroup(
            context, group, volumes)

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a cgsnapshot."""
        return self.common.create_cgsnapshot(context, cgsnapshot, self.db)

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot."""
        return self.common.delete_cgsnapshot(context, cgsnapshot, self.db)

    def _check_for_iscsi_ip_address(self):
        """Check to see if iscsi_ip_address is set in cinder.conf

        :returns: boolean -- True if iscsi_ip_address id defined in config.
        """
        bExists = os.path.exists(CINDER_CONF)
        if bExists:
            if 'iscsi_ip_address' in open(CINDER_CONF).read():
                return True
        return False
