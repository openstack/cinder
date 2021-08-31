#    Copyright (c) 2020 Open-E, Inc.
#    All Rights Reserved.
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

"""iSCSI volume driver for JovianDSS driver."""
import math
import string

from oslo_log import log as logging
from oslo_utils import units as o_units

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.open_e.jovian_common import exception as jexc
from cinder.volume.drivers.open_e.jovian_common import jdss_common as jcom
from cinder.volume.drivers.open_e.jovian_common import rest
from cinder.volume.drivers.open_e import options
from cinder.volume.drivers.san import san
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class JovianISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Open-E JovianDSS.

    Version history:

    .. code-block:: none

        1.0.0 - Open-E JovianDSS driver with basic functionality
        1.0.1 - Added certificate support
                Added revert to snapshot support
        1.0.2 - Added multi-attach support
                Added 16K block support
 """

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Open-E_JovianDSS_CI"
    VERSION = "1.0.2"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._stats = None
        self.jovian_iscsi_target_portal_port = "3260"
        self.jovian_target_prefix = 'iqn.2020-04.com.open-e.cinder:'
        self.jovian_chap_pass_len = 12
        self.jovian_sparse = False
        self.jovian_ignore_tpath = None
        self.jovian_hosts = None
        self._pool = 'Pool-0'
        self.ra = None

    @property
    def backend_name(self):
        """Return backend name."""
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.get('volume_backend_name',
                                                  'Open-EJovianDSS')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self.configuration.append_config_values(
            options.jdss_connection_opts)
        self.configuration.append_config_values(
            options.jdss_iscsi_opts)
        self.configuration.append_config_values(
            options.jdss_volume_opts)
        self.configuration.append_config_values(san.san_opts)

        self._pool = self.configuration.get('jovian_pool', 'Pool-0')
        self.jovian_iscsi_target_portal_port = self.configuration.get(
            'target_port', 3260)

        self.jovian_target_prefix = self.configuration.get(
            'target_prefix',
            'iqn.2020-04.com.open-e.cinder:')
        self.jovian_chap_pass_len = self.configuration.get(
            'chap_password_len', 12)
        self.block_size = (
            self.configuration.get('jovian_block_size', '64K'))
        self.jovian_sparse = (
            self.configuration.get('san_thin_provision', True))
        self.jovian_ignore_tpath = self.configuration.get(
            'jovian_ignore_tpath', None)
        self.jovian_hosts = self.configuration.get(
            'san_hosts', [])

        self.ra = rest.JovianRESTAPI(self.configuration)

        self.check_for_setup_error()

    def check_for_setup_error(self):
        """Check for setup error."""
        if len(self.jovian_hosts) == 0:
            msg = _("No hosts provided in configuration")
            raise exception.VolumeDriverException(msg)

        if not self.ra.is_pool_exists():
            msg = (_("Unable to identify pool %s") % self._pool)
            raise exception.VolumeDriverException(msg)

        valid_bsize = ['16K', '32K', '64K', '128K', '256K', '512K', '1M']
        if self.block_size not in valid_bsize:
            raise exception.InvalidConfigurationValue(
                value=self.block_size,
                option='jovian_block_size')

    def _get_target_name(self, volume_name):
        """Return iSCSI target name to access volume."""
        return '%s%s' % (self.jovian_target_prefix, volume_name)

    def _get_active_ifaces(self):
        """Return list of ip addreses for iSCSI connection"""

        return self.jovian_hosts

    def create_volume(self, volume):
        """Create a volume.

        :param volume: volume reference
        :return: model update dict for volume reference
        """
        vname = jcom.vname(volume.id)
        LOG.debug('creating volume %s.', vname)

        provider_location = self._get_provider_location(volume.id)
        provider_auth = self._get_provider_auth()

        try:
            self.ra.create_lun(vname,
                               volume.size * o_units.Gi,
                               sparse=self.jovian_sparse,
                               block_size=self.block_size)

        except jexc.JDSSException as jerr:
            LOG.error("Create volume error. Because %(err)s",
                      {"err": jerr})
            raise exception.VolumeBackendAPIException(
                _('Failed to create volume %s.') % volume.id) from jerr
        ret = {}
        if provider_auth is not None:
            ret['provider_auth'] = provider_auth

        ret['provider_location'] = provider_location

        return ret

    def _hide_object(self, vname):
        """Mark volume/snapshot as hidden

        :param vname: physical volume name
        """
        rename = {'name': jcom.hidden(vname)}
        try:
            self.ra.modify_lun(vname, rename)
        except jexc.JDSSException as jerr:
            emsg = _('Failure in hiding %(object)s, err: %(error)s,'
                     ' object has to be removed manually') % {'object': vname,
                                                              'error': jerr}
            LOG.warning(emsg)
            raise exception.VolumeBackendAPIException(emsg)

    def _clean_garbage_snapshots(self, vname, snapshots):
        """Delete physical snapshots that have no descendents"""
        garbage = []
        for snap in snapshots:
            if snap['clones'] == '':
                try:
                    self.ra.delete_snapshot(vname, snap['name'])
                except jexc.JDSSException as jerr:
                    args = {'obj': jcom.idname(vname), 'err': jerr}
                    msg = (_("Unable to clean garbage for "
                             "%(obj)s: %(err)s") % args)
                    raise exception.VolumeBackendAPIException(msg)
                garbage.append(snap)
        for snap in garbage:
            snapshots.remove(snap)

        return snapshots

    def _cascade_volume_delete(self, o_vname, o_snaps):
        """Delete or hides volume(if it is busy)

        Go over snapshots and deletes them if possible
        Calls for recursive volume deletion if volume do not have children
        """
        vsnaps = []
        deletable = True

        for snap in o_snaps:
            if jcom.is_snapshot(snap['name']):
                vsnaps += [(snap['name'],
                            jcom.full_name_volume(snap['clones']))]

        active_vsnaps = [vs for vs in vsnaps if jcom.is_hidden(vs[1]) is False]

        # If volume have clones or hidden snapshots it should be hidden
        if len(active_vsnaps) < len(o_snaps):
            deletable = False

        for vsnap in active_vsnaps:
            psnap = []
            try:
                psnap = self.ra.get_snapshots(vsnap[1])
            except jexc.JDSSException as jerr:
                msg = (_('Failure in acquiring snapshot for %s.') % vsnap[1])
                raise exception.VolumeBackendAPIException(msg) from jerr

            try:
                psnap = self._clean_garbage_snapshots(vsnap[1], psnap)
            except exception.VolumeBackendAPIException as err:
                msg = (_('Failure in cleaning garbage snapshots %s'
                         ' for volume %s, %s') % psnap, vsnap[1], err)
                raise exception.VolumeBackendAPIException(msg) from err
            if len(psnap) > 0:
                deletable = False
                self._hide_object(vsnap[1])
            else:
                try:
                    self.ra.delete_snapshot(o_vname,
                                            vsnap[0],
                                            recursively_children=True,
                                            recursively_dependents=True,
                                            force_umount=True)
                except jexc.JDSSException as jerr:
                    LOG.warning('Failure during deletion of physical '
                                'snapshot %s, err: %s', vsnap[0], jerr)
                    msg = (_('Failure during deletion of virtual snapshot '
                             '%s') % vsnap[1])
                    raise exception.VolumeBackendAPIException(msg)

        if deletable:
            self._gc_delete(o_vname)
        else:
            self._hide_object(o_vname)

    def delete_volume(self, volume, cascade=False):
        """Delete volume

        :param volume: volume reference
        :param cascade: remove snapshots of a volume as well
        """
        vname = jcom.vname(volume.id)

        LOG.debug('deleating volume %s', vname)

        snapshots = None
        try:
            snapshots = self.ra.get_snapshots(vname)
        except jexc.JDSSResourceNotFoundException:
            LOG.debug('volume %s dne, it was already '
                      'deleted', vname)
            return
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(jerr)

        snapshots = self._clean_garbage_snapshots(vname, snapshots)

        if cascade:
            self._cascade_volume_delete(vname, snapshots)
        else:
            if len(snapshots) > 0:
                self._hide_object(vname)
            else:
                self._gc_delete(vname)

    def _gc_delete(self, vname):
        """Delete volume and its hidden parents

        Deletes volume by going recursively to the first active
        parent and cals recursive deletion on storage side
        """
        vol = None
        try:
            vol = self.ra.get_lun(vname)
        except jexc.JDSSResourceNotFoundException:
            LOG.debug('volume %s does not exist, it was already '
                      'deleted.', vname)
            return
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(jerr)

        if vol['is_clone']:
            self._delete_back_recursively(jcom.origin_volume(vol['origin']),
                                          jcom.origin_snapshot(vol['origin']))
        else:
            try:
                self.ra.delete_lun(vname, force_umount=True)
            except jexc.JDSSRESTException as jerr:
                LOG.debug(
                    "Unable to delete physical volume %(volume)s "
                    "with error %(err)s.", {
                        "volume": vname,
                        "err": jerr})
                raise exception.VolumeIsBusy(jerr)

    def _delete_back_recursively(self, opvname, opsname):
        """Deletes snapshot by removing its oldest removable parent

        Checks if source volume for this snapshot is hidden:
        If it is hidden and have no other descenents, it calls itself on its
            source snapshot if such exists, or deletes it
        If it is not hidden, trigers delete for snapshot

        :param opvname: origin physical volume name
        :param opsname: origin physical snapshot name
        """

        if jcom.is_hidden(opvname):
            # Resource is hidden
            snaps = []
            try:
                snaps = self.ra.get_snapshots(opvname)
            except jexc.JDSSResourceNotFoundException:
                LOG.debug('Unable to get physical snapshots related to'
                          ' physical volume %s, volume do not exist',
                          opvname)
                return
            except jexc.JDSSException as jerr:
                raise exception.VolumeBackendAPIException(jerr)

            snaps = self._clean_garbage_snapshots(opvname, snaps)

            if len(snaps) > 1:
                # opvname has active snapshots and cant be deleted
                # that is why we delete branch related to opsname
                try:
                    self.ra.delete_snapshot(opvname,
                                            opsname,
                                            recursively_children=True,
                                            recursively_dependents=True,
                                            force_umount=True)
                except jexc.JDSSException as jerr:
                    raise exception.VolumeBackendAPIException(jerr)
            else:
                vol = None
                try:
                    vol = self.ra.get_lun(opvname)

                except jexc.JDSSResourceNotFoundException:
                    LOG.debug('volume %s does not exist, it was already '
                              'deleted.', opvname)
                    return
                except jexc.JDSSException as jerr:
                    raise exception.VolumeBackendAPIException(jerr)

                if vol['is_clone']:
                    self._delete_back_recursively(
                        jcom.origin_volume(vol['origin']),
                        jcom.origin_snapshot(vol['origin']))
                else:
                    try:
                        self.ra.delete_lun(opvname,
                                           recursively_children=True,
                                           recursively_dependents=True,
                                           force_umount=True)
                    except jexc.JDSSResourceNotFoundException:
                        LOG.debug('volume %s does not exist, it was already '
                                  'deleted.', opvname)
                        return
                    except jexc.JDSSException as jerr:
                        raise exception.VolumeBackendAPIException(jerr)
        else:
            # Resource is active
            try:
                self.ra.delete_snapshot(opvname,
                                        opsname,
                                        recursively_children=True,
                                        recursively_dependents=True,
                                        force_umount=True)
            except jexc.JDSSException as jerr:
                raise exception.VolumeBackendAPIException(jerr) from jerr

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.debug("Extend volume %s", volume.id)

        try:
            self.ra.extend_lun(jcom.vname(volume.id),
                               new_size * o_units.Gi)
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(
                (_('Failed to extend volume %s.'), volume.id)) from jerr

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot.

        Note: the revert process should not change the volume's
        current size, that means if the driver shrank
        the volume during the process, it should extend the
        volume internally.
        """
        vname = jcom.vname(volume.id)
        sname = jcom.sname(snapshot.id)
        LOG.debug('reverting %(vname)s to %(sname)s', {
            "vname": vname,
            "sname": sname})

        vsize = None
        try:
            vsize = self.ra.get_lun(vname).get('volsize')
        except jexc.JDSSResourceNotFoundException as jerr:
            raise exception.VolumeNotFound(volume_id=volume.id) from jerr
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(jerr) from jerr

        if vsize is None:
            raise exception.VolumeDriverException(
                _("unable to identify volume size"))

        try:
            self.ra.rollback_volume_to_snapshot(vname, sname)
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(jerr.message) from jerr

        try:
            rvsize = self.ra.get_lun(vname).get('volsize')
            if rvsize != vsize:
                self.ra.extend_lun(vname, vsize)
        except jexc.JDSSResourceNotFoundException as jerr:
            raise exception.VolumeNotFound(volume_id=volume.id) from jerr
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(jerr) from jerr

    def _clone_object(self, oname, coname):
        """Creates a clone of specified object

        :param: oname: name of an object to clone
        :param: coname: name of a new clone
        """
        LOG.debug('cloning %(oname)s to %(coname)s', {
            "oname": oname,
            "coname": coname})

        try:
            self.ra.create_snapshot(oname, coname)
        except jexc.JDSSSnapshotExistsException:
            try:
                self.ra.delete_snapshot(oname, coname)
            except jexc.JDSSSnapshotIsBusyException as jerrisbusy:
                raise exception.Duplicate() from jerrisbusy
            except jexc.JDSSException as jerr:
                raise exception.VolumeBackendAPIException(
                    (_("Unable to create volume %s.") % coname)) from jerr
        except jexc.JDSSResourceNotFoundException as jerrnotfound:
            if jcom.is_volume(oname):
                raise exception.VolumeNotFound(
                    volume_id=jcom.idname(oname)) from jerrnotfound
            raise exception.SnapshotNotFound(
                snapshot_id=jcom.idname(oname)) from jerrnotfound

        except jexc.JDSSException as jerr:
            args = {'snapshot': coname,
                    'object': oname,
                    'err': jerr}
            msg = (_('Failed to create tmp snapshot %(snapshot)s '
                     'for object %(object)s: %(err)s') % args)
            raise exception.VolumeBackendAPIException(msg)

        try:
            self.ra.create_volume_from_snapshot(
                coname,
                coname,
                oname,
                sparse=self.jovian_sparse)
        except jexc.JDSSResourceExistsException as jerr:
            raise exception.Duplicate() from jerr
        except jexc.JDSSException as jerr:
            try:
                self.ra.delete_snapshot(oname,
                                        coname,
                                        recursively_children=True,
                                        recursively_dependents=True,
                                        force_umount=True)
            except jexc.JDSSException as jerrd:
                LOG.warning("Because of %s physical snapshot %s of volume"
                            " %s have to be removed manually",
                            jerrd,
                            coname,
                            oname)

            raise exception.VolumeBackendAPIException(
                _("Unable to create volume %(vol)s because of %(err)s.") % {
                    'vol': coname, 'err': jerr}) from jerr

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        cvname = jcom.vname(volume.id)

        vname = jcom.vname(src_vref.id)

        LOG.debug('cloned volume %(id)s to %(id_clone)s', {
            "id": src_vref.id,
            "id_clone": volume.id})

        self._clone_object(vname, cvname)

        clone_size = 0

        try:
            clone_size = int(self.ra.get_lun(cvname)['volsize'])
        except jexc.JDSSException as jerr:

            self._delete_back_recursively(vname, cvname)
            raise exception.VolumeBackendAPIException(
                _("Fail in cloning volume %(vol)s to %(clone)s.") % {
                    'vol': src_vref.id, 'clone': volume.id}) from jerr

        try:
            if int(clone_size) < o_units.Gi * int(volume.size):
                self.extend_volume(volume, int(volume.size))

        except exception.VolumeBackendAPIException:
            # If volume can't be set to a proper size make sure to clean it
            # before failing
            try:
                self._delete_back_recursively(cvname, cvname)
            except exception.VolumeBackendAPIException as err:
                LOG.warning("Because of %s physical snapshot %s of volume"
                            " %s have to be removed manually",
                            err,
                            cvname,
                            vname)
            raise

        provider_location = self._get_provider_location(volume.id)
        provider_auth = self._get_provider_auth()

        ret = {}
        if provider_auth:
            ret['provider_auth'] = provider_auth

        ret['provider_location'] = provider_location

        return ret

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        If volume_type extra specs includes 'replication: <is> True'
        the driver needs to create a volume replica (secondary),
        and setup replication between the newly created volume and
        the secondary volume.
        """
        LOG.debug('create volume %(vol)s from snapshot %(snap)s', {
            'vol': volume.id,
            'snap': snapshot.id})

        cvname = jcom.vname(volume.id)
        sname = jcom.sname(snapshot.id)

        self._clone_object(sname, cvname)

        clone_size = 0

        try:
            clone_size = int(self.ra.get_lun(cvname)['volsize'])
        except jexc.JDSSException as jerr:

            self._delete_back_recursively(sname, cvname)
            raise exception.VolumeBackendAPIException(
                _("Fail in cloning snapshot %(snap)s to %(clone)s.") % {
                    'snap': snapshot.id, 'clone': volume.id}) from jerr

        try:
            if clone_size < o_units.Gi * int(volume.size):
                self.extend_volume(volume, int(volume.size))
        except exception.VolumeBackendAPIException:
            # If volume can't be set to a proper size make sure to clean it
            # before failing
            try:
                self._delete_back_recursively(cvname, cvname)
            except exception.VolumeBackendAPIException as err:
                msg = ("Hidden snapshot %s of volume %s "
                       "have to be removed manualy, "
                       "as automatic removal failed: %s")
                LOG.warning(msg, cvname, sname, err)
            raise

        provider_location = self._get_provider_location(volume.id)
        provider_auth = self._get_provider_auth()

        ret = {}
        if provider_auth is not None:
            ret['provider_auth'] = provider_auth

        ret['provider_location'] = provider_location

        return ret

    def create_snapshot(self, snapshot):
        """Create snapshot of existing volume.

        :param snapshot: snapshot reference
        """
        LOG.debug('create snapshot %(snap)s for volume %(vol)s', {
            'snap': snapshot.id,
            'vol': snapshot.volume_id})

        vname = jcom.vname(snapshot.volume_id)
        sname = jcom.sname(snapshot.id)

        self._clone_object(vname, sname)

        try:
            self.ra.make_readonly_lun(sname)
        except jexc.JDSSException as err:
            # Name of snapshot should be the same as a name of volume
            # that is going to be created from it
            self._delete_back_recursively(vname, sname)
            raise exception.VolumeBackendAPIException(err)

    def delete_snapshot(self, snapshot):
        """Delete snapshot of existing volume.

        :param snapshot: snapshot reference
        """
        sname = jcom.sname(snapshot.id)

        LOG.debug('deleating snapshot %s.', sname)

        snapshots = None
        try:
            snapshots = self.ra.get_snapshots(sname)
        except jexc.JDSSResourceNotFoundException:
            LOG.debug('physical volume %s dne, it was already '
                      'deleted.', sname)
            return
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(jerr)

        snapshots = self._clean_garbage_snapshots(sname, snapshots)

        if len(snapshots) > 0:
            self._hide_object(sname)
        else:
            self._gc_delete(sname)

    def _get_provider_auth(self):
        """Get provider authentication for the volume.

        :return: string of auth method and credentials
        """
        chap_user = volume_utils.generate_password(
            length=8,
            symbolgroups=(string.ascii_lowercase +
                          string.ascii_uppercase))

        chap_password = volume_utils.generate_password(
            length=self.jovian_chap_pass_len,
            symbolgroups=(string.ascii_lowercase +
                          string.ascii_uppercase + string.digits))

        return 'CHAP %(user)s %(passwd)s' % {
            'user': chap_user, 'passwd': chap_password}

    def _get_provider_location(self, volume_name):
        """Return volume iscsiadm-formatted provider location string."""
        return '%(host)s:%(port)s,1 %(name)s 0' % {
            'host': self.ra.get_active_host(),
            'port': self.jovian_iscsi_target_portal_port,
            'name': self._get_target_name(volume_name)}

    def create_export(self, _ctx, volume, connector):
        """Create new export for zvol.

        :param volume: reference of volume to be exported
        :return: iscsiadm-formatted provider location string
        """
        LOG.debug("create export for volume: %s.", volume.id)

        self._ensure_target_volume(volume)

        return {'provider_location': self._get_provider_location(volume.id)}

    def ensure_export(self, _ctx, volume):
        """Recreate parts of export if necessary.

        :param volume: reference of volume to be exported
        """
        LOG.debug("ensure export for volume: %s.", volume.id)
        self._ensure_target_volume(volume)

    def remove_export(self, _ctx, volume):
        """Destroy all resources created to export zvol.

        :param volume: reference of volume to be unexported
        """
        LOG.debug("remove_export for volume: %s.", volume.id)

        self._remove_target_volume(volume)

    def _update_volume_stats(self):
        """Retrieve stats info."""
        LOG.debug('Updating volume stats')

        pool_stats = self.ra.get_pool_stats()
        total_capacity = math.floor(int(pool_stats["size"]) / o_units.Gi)
        free_capacity = math.floor(int(pool_stats["available"]) / o_units.Gi)

        reserved_percentage = (
            self.configuration.get('reserved_percentage', 0))

        if total_capacity is None:
            total_capacity = 'unknown'
        if free_capacity is None:
            free_capacity = 'unknown'

        location_info = '%(driver)s:%(host)s:%(volume)s' % {
            'driver': self.__class__.__name__,
            'host': self.ra.get_active_host()[0],
            'volume': self._pool
        }

        self._stats = {
            'vendor_name': 'Open-E',
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': total_capacity,
            'free_capacity_gb': free_capacity,
            'reserved_percentage': int(reserved_percentage),
            'volume_backend_name': self.backend_name,
            'QoS_support': False,
            'location_info': location_info,
            'multiattach': True
        }

        LOG.debug('Total capacity: %d, '
                  'Free %d.',
                  self._stats['total_capacity_gb'],
                  self._stats['free_capacity_gb'])

    def _create_target(self, target_name, use_chap=True):
        """Creates target and handles exceptions

        Tryes to create target.
        :param target_name: name of target
        :param use_chap: flag for using chap
        """
        try:
            self.ra.create_target(target_name,
                                  use_chap=use_chap)

        except jexc.JDSSResourceExistsException as jerrex:
            raise exception.Duplicate() from jerrex
        except jexc.JDSSException as jerr:

            msg = (_('Unable to create target %(target)s '
                     'because of %(error)s.') % {'target': target_name,
                                                 'error': jerr})
            raise exception.VolumeBackendAPIException(msg)

    def _attach_target_volume(self, target_name, vname):
        """Attach target to volume and handles exceptions

        Tryes to set attach volume to specific target.
        In case of failure will remve target.
        :param target_name: name of target
        :param use_chap: flag for using chap
        """
        try:
            self.ra.attach_target_vol(target_name, vname)
        except jexc.JDSSException as jerr:
            msg = ('Unable to attach volume to target {target} '
                   'because of {error}.')
            emsg = msg.format(target=target_name, error=jerr)
            LOG.debug(msg, {"target": target_name, "error": jerr})
            try:
                self.ra.delete_target(target_name)
            except jexc.JDSSException:
                pass
            raise exception.VolumeBackendAPIException(_(emsg))

    def _set_target_credentials(self, target_name, cred):
        """Set CHAP configuration for target and handle exceptions

        Tryes to set CHAP credentials for specific target.
        In case of failure will remve target.
        :param target_name: name of target
        :param cred: CHAP user name and password
        """
        try:
            self.ra.create_target_user(target_name, cred)

        except jexc.JDSSException as jerr:
            try:
                self.ra.delete_target(target_name)
            except jexc.JDSSException:
                pass

            err_msg = (('Unable to create user %(user)s '
                        'for target %(target)s '
                        'because of %(error)s.') % {
                            'target': target_name,
                            'user': cred['name'],
                            'error': jerr})

            LOG.debug(err_msg)

            raise exception.VolumeBackendAPIException(_(err_msg))

    def _create_target_volume(self, volume):
        """Creates target and attach volume to it

        :param volume: volume id
        :return:
        """
        LOG.debug("create target and attach volume %s to it", volume.id)

        target_name = self.jovian_target_prefix + volume.id
        vname = jcom.vname(volume.id)

        auth = volume.provider_auth

        if not auth:
            msg = _("Volume %s is missing provider_auth") % volume.id
            raise exception.VolumeDriverException(msg)

        (__, auth_username, auth_secret) = auth.split()
        chap_cred = {"name": auth_username,
                     "password": auth_secret}

        # Create target
        self._create_target(target_name, True)

        # Attach volume
        self._attach_target_volume(target_name, vname)

        # Set credentials
        self._set_target_credentials(target_name, chap_cred)

    def _ensure_target_volume(self, volume):
        """Checks if target configured properly and volume is attached to it

        param: volume: volume structure
        """
        LOG.debug("ensure volume %s assigned to a proper target", volume.id)

        target_name = self.jovian_target_prefix + volume.id

        auth = volume.provider_auth

        if not auth:
            msg = _("volume %s is missing provider_auth") % volume.id
            raise exception.VolumeDriverException(msg)

        (__, auth_username, auth_secret) = auth.split()
        chap_cred = {"name": auth_username,
                     "password": auth_secret}

        if not self.ra.is_target(target_name):
            self._create_target_volume(volume)
            return

        vname = jcom.vname(volume.id)
        if not self.ra.is_target_lun(target_name, vname):
            self._attach_target_volume(target_name, vname)

        try:
            users = self.ra.get_target_user(target_name)
            if len(users) == 1:
                if users[0]['name'] == chap_cred['name']:
                    return
                self.ra.delete_target_user(
                    target_name,
                    users[0]['name'])
            for user in users:
                self.ra.delete_target_user(
                    target_name,
                    user['name'])
            self._set_target_credentials(target_name, chap_cred)

        except jexc.JDSSException as jerr:
            self.ra.delete_target(target_name)
            raise exception.VolumeBackendAPIException(jerr)

    def _remove_target_volume(self, volume):
        """_remove_target_volume

        Ensure that volume is not attached to target and target do not exists.
        """
        target_name = self.jovian_target_prefix + volume.id
        LOG.debug("remove export")
        LOG.debug("detach volume:%(vol)s from target:%(targ)s.", {
            'vol': volume,
            'targ': target_name})

        try:
            self.ra.detach_target_vol(target_name, jcom.vname(volume.id))
        except jexc.JDSSResourceNotFoundException as jerrrnf:
            LOG.debug('failed to remove resource %(t)s because of %(err)s', {
                't': target_name,
                'err': jerrrnf.args[0]})
        except jexc.JDSSException as jerr:
            LOG.debug('failed to Terminate_connection for target %(targ)s '
                      'because of: %(err)s', {
                          'targ': target_name,
                          'err': jerr.args[0]})
            raise exception.VolumeBackendAPIException(jerr)

        LOG.debug("delete target: %s", target_name)

        try:
            self.ra.delete_target(target_name)
        except jexc.JDSSResourceNotFoundException as jerrrnf:
            LOG.debug('failed to remove resource %(target)s because '
                      'of %(err)s', {'target': target_name,
                                     'err': jerrrnf.args[0]})

        except jexc.JDSSException as jerr:
            LOG.debug('Failed to Terminate_connection for target %(targ)s '
                      'because of: %(err)s ', {
                          'targ': target_name,
                          'err': jerr.args[0]})

            raise exception.VolumeBackendAPIException(jerr)

    def _get_iscsi_properties(self, volume, connector):
        """Return dict according to cinder/driver.py implementation.

        :param volume:
        :return:
        """
        tname = self.jovian_target_prefix + volume.id
        iface_info = []
        multipath = connector.get('multipath', False)
        if multipath:
            iface_info = self._get_active_ifaces()
            if not iface_info:
                raise exception.InvalidConfigurationValue(
                    _('No available interfaces '
                      'or config excludes them'))

        iscsi_properties = dict()

        if multipath:
            iscsi_properties['target_iqns'] = []
            iscsi_properties['target_portals'] = []
            iscsi_properties['target_luns'] = []
            LOG.debug('tpaths %s.', iface_info)
            for iface in iface_info:
                iscsi_properties['target_iqns'].append(
                    self.jovian_target_prefix +
                    volume.id)
                iscsi_properties['target_portals'].append(
                    iface +
                    ":" +
                    str(self.jovian_iscsi_target_portal_port))
                iscsi_properties['target_luns'].append(0)
        else:
            iscsi_properties['target_iqn'] = tname
            iscsi_properties['target_portal'] = (
                self.ra.get_active_host() +
                ":" +
                str(self.jovian_iscsi_target_portal_port))

        iscsi_properties['target_discovered'] = False

        auth = volume.provider_auth
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            iscsi_properties['auth_method'] = auth_method
            iscsi_properties['auth_username'] = auth_username
            iscsi_properties['auth_password'] = auth_secret

        iscsi_properties['target_lun'] = 0
        return iscsi_properties

    def initialize_connection(self, volume, connector):
        """Initialize the connection and returns connection info.

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
                    'volume_id': '12345678-1234-1234-1234-123456789012',
                }
            }
        """
        iscsi_properties = self._get_iscsi_properties(volume, connector)

        LOG.debug("initialize_connection for %(volume)s %(ip)s.",
                  {'volume': volume.id,
                   'ip': connector['ip']})

        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties,
        }

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """terminate_connection

        """

        LOG.debug("terminate connection for %(volume)s ",
                  {'volume': volume.id})
