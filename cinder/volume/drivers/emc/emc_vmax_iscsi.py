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
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.emc import emc_vmax_common


LOG = logging.getLogger(__name__)

CINDER_CONF = '/etc/cinder/cinder.conf'


@interface.volumedriver
class EMCVMAXISCSIDriver(driver.ISCSIDriver):
    """EMC ISCSI Drivers for VMAX using SMI-S.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.1.0 - Multiple pools and thick/thin provisioning,
                performance enhancement.
        2.0.0 - Add driver requirement functions
        2.1.0 - Add consistency group functions
        2.1.1 - Fixed issue with mismatched config (bug #1442376)
        2.1.2 - Clean up failed clones (bug #1440154)
        2.1.3 - Fixed a problem with FAST support (bug #1435069)
        2.2.0 - Add manage/unmanage
        2.2.1 - Support for SE 8.0.3
        2.2.2 - Update Consistency Group
        2.2.3 - Pool aware scheduler(multi-pool) support
        2.2.4 - Create CG from CG snapshot
        2.3.0 - Name change for MV and SG for FAST (bug #1515181)
              - Fix for randomly choosing port group. (bug #1501919)
              - get_short_host_name needs to be called in find_device_number
                (bug #1520635)
              - Proper error handling for invalid SLOs (bug #1512795)
              - Extend Volume for VMAX3, SE8.1.0.3
              https://blueprints.launchpad.net/cinder/+spec/vmax3-extend-volume
              - Incorrect SG selected on an attach (#1515176)
              - Cleanup Zoning (bug #1501938)  NOTE: FC only
              - Last volume in SG fix
              - _remove_last_vol_and_delete_sg is not being called
                for VMAX3 (bug #1520549)
              - necessary updates for CG changes (#1534616)
              - Changing PercentSynced to CopyState (bug #1517103)
              - Getting iscsi ip from port in existing masking view
              - Replacement of EMCGetTargetEndpoints api (bug #1512791)
              - VMAX3 snapvx improvements (bug #1522821)
              - Operations and timeout issues (bug #1538214)
        2.4.0 - EMC VMAX - locking SG for concurrent threads (bug #1554634)
              - SnapVX licensing checks for VMAX3 (bug #1587017)
              - VMAX oversubscription Support (blueprint vmax-oversubscription)
              - QoS support (blueprint vmax-qos)
              - VMAX2/VMAX3 iscsi multipath support (iscsi only)
              https://blueprints.launchpad.net/cinder/+spec/vmax-iscsi-multipath

    """

    VERSION = "2.4.0"

    # ThirdPartySystems wiki
    CI_WIKI_NAME = "EMC_VMAX_CI"

    def __init__(self, *args, **kwargs):

        super(EMCVMAXISCSIDriver, self).__init__(*args, **kwargs)
        self.common = (
            emc_vmax_common.EMCVMAXCommon('iSCSI',
                                          self.VERSION,
                                          configuration=self.configuration))
        self.iscsi_ip_addresses = []

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a VMAX volume."""
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

    def create_export(self, context, volume, connector):
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
        Example return value:

        .. code-block:: json

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': '12345678-1234-4321-1234-123456789012',
                }
            }
        Example return value (multipath is enabled)::
            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqns': ['iqn.2010-10.org.openstack:volume-00001',
                                    'iqn.2010-10.org.openstack:volume-00002'],
                    'target_portals': ['127.0.0.1:3260', '127.0.1.1:3260'],
                    'target_luns': [1, 1],
                }
            }
        """
        device_info = self.common.initialize_connection(
            volume, connector)
        try:
            self.iscsi_ip_addresses = device_info['iscsi_ip_addresses']
            is_multipath = device_info['is_multipath']
        except KeyError as ex:
            exception_message = (_("Cannot get iSCSI ipaddresses or "
                                   "multipath flag. Exception is %(ex)s. ")
                                 % {'ex': ex})

            raise exception.VolumeBackendAPIException(data=exception_message)

        iscsi_properties = self.smis_get_iscsi_properties(
            volume, connector, is_multipath)

        LOG.info(_LI("Leaving initialize_connection: %s"), iscsi_properties)
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def _call_iscsiadm(self, iscsi_ip_address):
        """Calls iscsiadm with iscsi ip address"""
        try:
            (out, _err) = self._execute('iscsiadm', '-m', 'discovery',
                                        '-t', 'sendtargets', '-p',
                                        iscsi_ip_address,
                                        run_as_root=True)
            return out, _err, None
        except Exception as ex:
            return None, None, ex

    def smis_do_iscsi_discovery(self, volume):
        """Calls iscsiadm with each iscsi ip address in the list"""
        LOG.info(_LI("ISCSI provider_location not stored, using discovery."))
        targets = []
        if len(self.iscsi_ip_addresses) == 0:
            LOG.error(_LE("The list of iscsi_ip_addresses is empty"))
            return targets
        outList = []
        for iscsi_ip_address in self.iscsi_ip_addresses:
            out, _err, ex = self._call_iscsiadm(iscsi_ip_address)
            if out:
                outList.append(out)

        if len(outList) == 0:
            if ex:
                exception_message = (_("Unsuccessful iscsiadm. "
                                       "Exception is %(ex)s. ")
                                     % {'ex': ex})
            else:
                exception_message = (_("iscsiadm execution failed. "))
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.info(_LI(
            "smis_do_iscsi_discovery is: %(out)s."),
            {'out': out})
        for out in outList:
            for target in out.splitlines():
                targets.append(target)

        outTargets = self._parse_target_list(targets)
        return outTargets

    def _parse_target_list(self, targets):
        """Parse target list into usable format.

        :param targets: list of all targets
        :return: outTargets
        """
        outTargets = []
        for target in targets:
            results = target.split(" ")
            properties = {}
            properties['target_portal'] = results[0].split(",")[0]
            properties['target_iqn'] = results[1]
            outTargets.append(properties)
        return outTargets

    def smis_get_iscsi_properties(self, volume, connector, is_multipath):
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

        targets = self.smis_do_iscsi_discovery(volume)
        if len(targets) == 0:
            raise exception.InvalidVolume(_("Could not find iSCSI export "
                                          "for volume %(volumeName)s.")
                                          % {'volumeName': volume['name']})

        LOG.debug("ISCSI Discovery: Found %s", targets)

        device_info = self.common.find_device_number(
            volume, connector['host'])

        isError = False
        if device_info:
            try:
                lun_id = device_info['hostlunid']
            except KeyError:
                isError = True
        else:
            isError = True

        if isError:
            LOG.error(_LE("Unable to get the lun id"))
            exception_message = (_("Cannot find device number for volume "
                                 "%(volumeName)s.")
                                 % {'volumeName': volume['name']})
            raise exception.VolumeBackendAPIException(data=exception_message)

        properties = {'target_discovered': False,
                      'target_iqn': 'unknown',
                      'target_iqns': None,
                      'target_portal': 'unknown',
                      'target_portals': None,
                      'target_lun': 'unknown',
                      'target_luns': None,
                      'volume_id': volume['id']}

        if len(self.iscsi_ip_addresses) > 0:
            if len(self.iscsi_ip_addresses) > 1 and is_multipath:
                properties['target_iqns'] = [t['target_iqn'] for t in targets]
                properties['target_portals'] = (
                    [t['target_portal'] for t in targets])
                properties['target_luns'] = [lun_id] * len(targets)
            properties['target_discovered'] = True
            properties['target_iqn'] = [t['target_iqn'] for t in targets][0]
            properties['target_portal'] = (
                [t['target_portal'] for t in targets][0])
            properties['target_lun'] = lun_id
        else:
            LOG.error(_LE('Failed to find available iSCSI targets.'))

        LOG.info(_LI(
            "ISCSI properties: %(properties)s."), {'properties': properties})
        LOG.info(_LI(
            "ISCSI volume is: %(volume)s."), {'volume': volume})

        if 'provider_auth' in volume:
            auth = volume['provider_auth']
            LOG.info(_LI(
                "AUTH properties: %(authProps)s."), {'authProps': auth})

            if auth is not None:
                (auth_method, auth_username, auth_secret) = auth.split()

                properties['auth_method'] = auth_method
                properties['auth_username'] = auth_username
                properties['auth_password'] = auth_secret

                LOG.info(_LI("AUTH properties: %s."), properties)

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

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""
        return self.common.delete_consistencygroup(
            context, group, volumes)

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""
        return self.common.create_cgsnapshot(context, cgsnapshot, snapshots)

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""
        return self.common.delete_cgsnapshot(context, cgsnapshot, snapshots)

    def _check_for_iscsi_ip_address(self):
        """Check to see if iscsi_ip_address is set in cinder.conf

        :returns: boolean -- True if iscsi_ip_address id defined in config.
        """
        bExists = os.path.exists(CINDER_CONF)
        if bExists:
            if 'iscsi_ip_address' in open(CINDER_CONF).read():
                return True
        return False

    def manage_existing(self, volume, external_ref):
        """Manages an existing VMAX Volume (import to Cinder).

        Renames the Volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.
        """
        return self.common.manage_existing(volume, external_ref)

    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing VMAX volume to manage_existing.

        :param self: reference to class
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: size of the volume in GB
        """
        return self.common.manage_existing_get_size(volume, external_ref)

    def unmanage(self, volume):
        """Export VMAX volume from Cinder.

        Leave the volume intact on the backend array.
        """
        return self.common.unmanage(volume)

    def update_consistencygroup(self, context, group,
                                add_volumes, remove_volumes):
        """Updates LUNs in consistency group."""
        return self.common.update_consistencygroup(group, add_volumes,
                                                   remove_volumes)

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates the consistency group from source.

        Currently the source can only be a cgsnapshot.

        :param context: the context
        :param group: the consistency group object to be created
        :param volumes: volumes in the consistency group
        :param cgsnapshot: the source consistency group snapshot
        :param snapshots: snapshots of the source volumes
        :param source_cg: the dictionary of a consistency group as source.
        :param source_vols: a list of volume dictionaries in the source_cg.
        """
        return self.common.create_consistencygroup_from_src(
            context, group, volumes, cgsnapshot, snapshots, source_cg,
            source_vols)
