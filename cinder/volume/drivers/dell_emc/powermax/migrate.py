# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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

import uuid

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.powermax import masking
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import utils

LOG = logging.getLogger(__name__)


class PowerMaxMigrate(object):
    """Upgrade class for Rest based PowerMax volume drivers.

    This upgrade class is for Dell EMC PowerMax volume drivers
    based on UniSphere Rest API.
    It supports VMAX 3 and VMAX All Flash and PowerMax arrays.

    """
    def __init__(self, prtcl, rest):
        self.rest = rest
        self.utils = utils.PowerMaxUtils()
        self.masking = masking.PowerMaxMasking(prtcl, self.rest)
        self.provision = provision.PowerMaxProvision(self.rest)

    def do_migrate_if_candidate(
            self, array, srp, device_id, volume, connector):
        """Check and migrate if the volume is a candidate

        If the volume is in the legacy (SMIS) masking view structure
        move it to staging storage group within a staging masking view.

        :param array: array serial number
        :param srp: the SRP
        :param device_id: the volume device id
        :param volume: the volume object
        :param connector: the connector object
        """
        mv_detail_list = list()

        masking_view_list, storage_group_list = (
            self._get_mvs_and_sgs_from_volume(
                array, device_id))

        for masking_view in masking_view_list:
            masking_view_dict = self.get_masking_view_component_dict(
                masking_view, srp)
            if masking_view_dict:
                mv_detail_list.append(masking_view_dict)

        if not mv_detail_list:
            return False

        if len(storage_group_list) != 1:
            LOG.warning("MIGRATE - The volume %(dev_id)s is not in one "
                        "storage group as is expected for migration. "
                        "The volume is in storage groups %(sg_list)s."
                        "Migration will not proceed.",
                        {'dev_id': device_id,
                         'sg_list': storage_group_list})
            return False
        else:
            source_storage_group_name = storage_group_list[0]

        # Get the host that OpenStack has volume exposed to (it should only
        # be one host).
        os_host_list = self.get_volume_host_list(volume, connector)
        if len(os_host_list) != 1:
            LOG.warning("MIGRATE - OpenStack has recorded that "
                        "%(dev_id)s is attached to hosts %(os_hosts)s "
                        "and not 1 host as is expected. "
                        "Migration will not proceed.",
                        {'dev_id': device_id,
                         'os_hosts': os_host_list})
            return False
        else:
            os_host_name = os_host_list[0]
        LOG.info("MIGRATE - Volume %(dev_id)s is a candidate for "
                 "migration. The OpenStack host is %(os_host_name)s."
                 "The volume is in storage group %(sg_name)s.",
                 {'dev_id': device_id,
                  'os_host_name': os_host_name,
                  'sg_name': source_storage_group_name})
        return self._perform_migration(
            array, device_id, mv_detail_list, source_storage_group_name,
            os_host_name)

    def _perform_migration(
            self, array, device_id, mv_detail_list, source_storage_group_name,
            os_host_name):
        """Perform steps so we can get the volume in a correct state.

        :param array: the storage array
        :param device_id: the device_id
        :param mv_detail_list: the masking view list
        :param source_storage_group_name: the source storage group
        :param os_host_name: the host the volume is exposed to
        :returns: boolean
        """
        extra_specs = {utils.INTERVAL: 3, utils.RETRIES: 200}
        stg_sg_name = self._create_stg_storage_group_with_vol(
            array, os_host_name, extra_specs)
        if not stg_sg_name:
            # Throw an exception here
            exception_message = _("MIGRATE - Unable to create staging "
                                  "storage group.")
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        LOG.info("MIGRATE - Staging storage group %(stg_sg_name)s has "
                 "been successfully created.", {'stg_sg_name': stg_sg_name})

        new_stg_mvs = self._create_stg_masking_views(
            array, mv_detail_list, stg_sg_name, extra_specs)
        LOG.info("MIGRATE - Staging masking views %(new_stg_mvs)s have "
                 "been successfully created.", {'new_stg_mvs': new_stg_mvs})

        if not new_stg_mvs:
            exception_message = _("MIGRATE - Unable to create staging "
                                  "masking views.")
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        # Move volume from old storage group to new staging storage group
        self.move_volume_from_legacy_to_staging(
            array, device_id, source_storage_group_name,
            stg_sg_name, extra_specs)

        LOG.info("MIGRATE - Device id %(device_id)s has been successfully "
                 "moved from %(src_sg)s to %(tgt_sg)s.",
                 {'device_id': device_id,
                  'src_sg': source_storage_group_name,
                  'tgt_sg': stg_sg_name})

        new_masking_view_list, new_storage_group_list = (
            self._get_mvs_and_sgs_from_volume(
                array, device_id))

        if len(new_storage_group_list) != 1:
            exception_message = (_(
                "MIGRATE - The current storage group list has %(list_len)d "
                "members. The list is %(sg_list)s. Will not proceed with "
                "cleanup. Please contact customer representative.") % {
                'list_len': len(new_storage_group_list),
                'sg_list': new_storage_group_list})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        else:
            current_storage_group_name = new_storage_group_list[0]
            if current_storage_group_name.lower() != stg_sg_name.lower():
                exception_message = (_(
                    "MIGRATE - The current storage group %(sg_1)s "
                    "does not match %(sg_2)s. Will not proceed with "
                    "cleanup. Please contact customer representative.") % {
                    'sg_1': current_storage_group_name,
                    'sg_2': stg_sg_name})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

        if not self._delete_staging_masking_views(
                array, new_masking_view_list, os_host_name):
            exception_message = _("MIGRATE - Unable to delete staging masking "
                                  "views. Please contact customer "
                                  "representative.")
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        final_masking_view_list, final_storage_group_list = (
            self._get_mvs_and_sgs_from_volume(
                array, device_id))
        if len(final_masking_view_list) != 1:
            exception_message = (_(
                "MIGRATE - The final masking view list has %(list_len)d "
                "entries and not 1 entry as is expected.  The list is "
                "%(mv_list)s. Please contact customer representative.") % {
                'list_len': len(final_masking_view_list),
                'sg_list': final_masking_view_list})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        return True

    def move_volume_from_legacy_to_staging(
            self, array, device_id, source_storage_group_name,
            stg_sg_name, extra_specs):
        """Move the volume from legacy SG to staging SG

        :param array: array serial number
        :param device_id: the device id of the volume
        :param source_storage_group_name: the source storage group
        :param stg_sg_name: the target staging storage group
        :param extra_specs: the extra specs
        """
        num_vol_in_sg = self.rest.get_num_vols_in_sg(
            array, source_storage_group_name)
        if num_vol_in_sg == 1:
            # Can't move last volume and leave masking view empty
            # so creating a holder volume
            temp_vol_size = '1'
            hold_vol_name = 'hold-' + str(uuid.uuid1())
            self.provision.create_volume_from_sg(
                array, hold_vol_name, source_storage_group_name,
                temp_vol_size, extra_specs)
            LOG.info("MIGRATE - Volume %(vol)s has been created because "
                     "there was only one volume remaining in storage group "
                     "%(src_sg)s and we are attempting a move it to staging "
                     "storage group %(tgt_sg)s.",
                     {'vol': hold_vol_name,
                      'src_sg': source_storage_group_name,
                      'tgt_sg': stg_sg_name})

        self.rest.move_volume_between_storage_groups(
            array, device_id, source_storage_group_name,
            stg_sg_name, extra_specs)

    def _delete_staging_masking_views(
            self, array, masking_view_list, os_host_name):
        """Delete the staging masking views

        Delete the staging masking views except the masking view
        exposed to the OpenStack compute

        :param array: array serial number
        :param masking_view_list: masking view namelist
        :param os_host_name: the host the volume is exposed to in OpenStack
        :returns: boolean
        """
        delete_mv_list = list()
        safe_to_delete = False
        for masking_view_name in masking_view_list:
            if os_host_name in masking_view_name:
                safe_to_delete = True
            else:
                delete_mv_list.append(masking_view_name)
        if safe_to_delete:
            for delete_mv in delete_mv_list:
                self.rest.delete_masking_view(array, delete_mv)
                LOG.info("MIGRATE - Masking view %(delete_mv)s has been "
                         "successfully deleted.",
                         {'delete_mv': delete_mv})
        return safe_to_delete

    def _create_stg_masking_views(
            self, array, mv_detail_list, stg_sg_name, extra_specs):
        """Create a staging masking views

        :param array: array serial number
        :param mv_detail_list: masking view detail list
        :param stg_sg_name: staging storage group name
        :param extra_specs: the extra specs
        :returns: masking view list
        """
        new_masking_view_list = list()
        for mv_detail in mv_detail_list:
            host_name = mv_detail.get('host')
            masking_view_name = mv_detail.get('mv_name')
            masking_view_components = self.rest.get_masking_view(
                array, masking_view_name)
            # Create a staging masking view
            random_uuid = uuid.uuid1()
            staging_mv_name = 'STG-' + host_name + '-' + str(
                random_uuid) + '-MV'
            if masking_view_components:
                self.rest.create_masking_view(
                    array, staging_mv_name, stg_sg_name,
                    masking_view_components.get('portGroupId'),
                    masking_view_components.get('hostId'), extra_specs)
                masking_view_dict = self.rest.get_masking_view(
                    array, staging_mv_name)
                if masking_view_dict:
                    new_masking_view_list.append(staging_mv_name)
                else:
                    LOG.warning("Failed to create staging masking view "
                                "%(mv_name)s. Migration cannot proceed.",
                                {'mv_name': masking_view_name})
                    return None
        return new_masking_view_list

    def _create_stg_storage_group_with_vol(self, array, os_host_name,
                                           extra_specs):
        """Create a staging storage group and add volume

        :param array: array serial number
        :param os_host_name: the openstack host name
        :param extra_specs: the extra specs
        :returns: storage group name
        """
        random_uuid = uuid.uuid1()
        # Create a staging SG
        stg_sg_name = 'STG-' + os_host_name + '-' + (
            str(random_uuid) + '-SG')
        temp_vol_name = 'tempvol-' + str(random_uuid)
        temp_vol_size = '1'

        _stg_storage_group = self.provision.create_storage_group(
            array, stg_sg_name,
            None, None, None, extra_specs)
        if _stg_storage_group:
            self.provision.create_volume_from_sg(
                array, temp_vol_name, stg_sg_name,
                temp_vol_size, extra_specs)
            return stg_sg_name
        else:
            return None

    def _get_mvs_and_sgs_from_volume(self, array, device_id):
        """Given a device Id get its storage groups and masking views.

        :param array: array serial number
        :param device_id: the volume device id
        :returns: masking view list, storage group list
        """
        final_masking_view_list = []
        storage_group_list = self.rest.get_storage_groups_from_volume(
            array, device_id)
        for sg in storage_group_list:
            masking_view_list = self.rest.get_masking_views_from_storage_group(
                array, sg)
            final_masking_view_list.extend(masking_view_list)
        return final_masking_view_list, storage_group_list

    def get_masking_view_component_dict(
            self, masking_view_name, srp):
        """Get components from input string.

        :param masking_view_name: the masking view name -- str
        :param srp: the srp -- str
        :returns: object components -- dict
        """
        regex_str_share = (
            r'^(?P<prefix>OS)-(?P<host>.+?)((?P<srp>' + srp + r')-'
            r'(?P<slo>.+?)-(?P<workload>.+?)|(?P<no_slo>No_SLO))'
            r'((?P<protocol>-I|-F)|)'
            r'(?P<CD>-CD|)(?P<RE>-RE|)'
            r'(?P<uuid>-[0-9A-Fa-f]{8}|)'
            r'-(?P<postfix>MV)$')

        object_dict = self.utils.get_object_components_and_correct_host(
            regex_str_share, masking_view_name)

        if object_dict:
            object_dict['mv_name'] = masking_view_name
        return object_dict

    def get_volume_host_list(self, volume, connector):
        """Get host list attachments from connector object

        :param volume: the volume object
        :param connector: the connector object
        :returns os_host_list
        """
        os_host_list = list()
        if connector is not None:
            attachment_list = volume.volume_attachment
            LOG.debug("Volume attachment list: %(atl)s. "
                      "Attachment type: %(at)s",
                      {'atl': attachment_list, 'at': type(attachment_list)})
            try:
                att_list = attachment_list.objects
            except AttributeError:
                att_list = attachment_list
            if att_list is not None:
                host_list = [att.connector['host'] for att in att_list if
                             att is not None and att.connector is not None]
        for host_name in host_list:
            os_host_list.append(self.utils.get_host_short_name(host_name))
        return os_host_list

    def cleanup_staging_objects(
            self, array, storage_group_names, extra_specs):
        """Delete the staging masking views and storage groups

        :param array: the array serial number
        :param storage_group_names: a list of storage group names
        :param extra_specs: the extra specs
        """
        def _do_cleanup(sg_name, device_id):
            masking_view_list = (
                self.rest.get_masking_views_from_storage_group(
                    array, sg_name))
            for masking_view in masking_view_list:
                if 'STG-' in masking_view:
                    self.rest.delete_masking_view(array, masking_view)
                    self.rest.remove_vol_from_sg(
                        array, sg_name, device_id,
                        extra_specs)
                    self.rest.delete_volume(array, device_id)
                    self.rest.delete_storage_group(array, sg_name)

        for storage_group_name in storage_group_names:
            if 'STG-' in storage_group_name:
                volume_list = self.rest.get_volumes_in_storage_group(
                    array, storage_group_name)
                if len(volume_list) == 1:
                    try:
                        _do_cleanup(storage_group_name, volume_list[0])
                    except Exception:
                        LOG.warning("MIGRATE - An attempt was made to "
                                    "cleanup after a legacy live migration, "
                                    "but it failed. You may choose to "
                                    "cleanup manually.")
