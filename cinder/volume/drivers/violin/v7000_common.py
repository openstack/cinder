# Copyright 2015 Violin Memory, Inc.
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
Violin Memory 7000 Series All-Flash Array Common Driver for OpenStack Cinder

Provides common (ie., non-protocol specific) management functions for
V7000 series flash arrays.

Backend array communication is handled via VMEM's python library
called 'vmemclient'.

NOTE: this driver file requires the use of synchronization points for
certain types of backend operations, and as a result may not work
properly in an active-active HA configuration.  See OpenStack Cinder
driver documentation for more information.
"""

import math
import re
import six
import socket
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import units

from cinder import context
from cinder.db.sqlalchemy import api
from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume import configuration
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)

try:
    import vmemclient
except ImportError:
    vmemclient = None
else:
    LOG.info("Running with vmemclient version: %s",
             vmemclient.__version__)


CONCERTO_SUPPORTED_VERSION_PATTERNS = ['Version 7.[0-9].?[0-9]?']
CONCERTO_DEFAULT_PRIORITY = 'medium'
CONCERTO_DEFAULT_SRA_POLICY = 'preserveAll'
CONCERTO_DEFAULT_SRA_ENABLE_EXPANSION = True
CONCERTO_DEFAULT_SRA_EXPANSION_THRESHOLD = 50
CONCERTO_DEFAULT_SRA_EXPANSION_INCREMENT = '1024MB'
CONCERTO_DEFAULT_SRA_EXPANSION_MAX_SIZE = None
CONCERTO_DEFAULT_SRA_ENABLE_SHRINK = False
CONCERTO_DEFAULT_POLICY_MAX_SNAPSHOTS = 1000
CONCERTO_DEFAULT_POLICY_RETENTION_MODE = 'All'
CONCERTO_LUN_TYPE_THICK = 'THICK'
LUN_ALLOC_SZ = 10

violin_opts = [
    cfg.IntOpt('violin_request_timeout',
               default=300,
               help='Global backend request timeout, in seconds.'),
    cfg.ListOpt('violin_dedup_only_pools',
                default=[],
                help='Storage pools to be used to setup dedup luns only.'
                     '(Comma separated list)'),
    cfg.ListOpt('violin_dedup_capable_pools',
                default=[],
                help='Storage pools capable of dedup and other luns.'
                     '(Comma separated list)'),
    cfg.StrOpt('violin_pool_allocation_method',
               default='random',
               choices=['random', 'largest', 'smallest'],
               help='Method of choosing a storage pool for a lun.'),
    cfg.ListOpt('violin_iscsi_target_ips',
                default=[],
                help='Target iSCSI addresses to use.'
                     '(Comma separated list)'),
]

CONF = cfg.CONF
CONF.register_opts(violin_opts, group=configuration.SHARED_CONF_GROUP)


class V7000Common(object):
    """Contains common code for the Violin V7000 drivers."""

    def __init__(self, config):
        self.vmem_mg = None
        self.container = ""
        self.config = config

    def do_setup(self, context):
        """Any initialization the driver does while starting."""
        if not self.config.san_ip:
            raise exception.InvalidInput(
                reason=_('Gateway VIP is not set'))

        if vmemclient:
            self.vmem_mg = vmemclient.open(self.config.san_ip,
                                           self.config.san_login,
                                           self.config.san_password,
                                           keepalive=True)

        if self.vmem_mg is None:
            msg = _('Failed to connect to array')
            raise exception.VolumeBackendAPIException(data=msg)

        if self.vmem_mg.utility.is_external_head:
            # With an external storage pool configuration is a must
            if (self.config.violin_dedup_only_pools == [] and
                    self.config.violin_dedup_capable_pools == []):

                LOG.warning("Storage pools not configured.")
                raise exception.InvalidInput(
                    reason=_('Storage pool configuration is '
                             'mandatory for external head'))

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        if vmemclient is None:
            msg = _('vmemclient python library not found')
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info("CONCERTO version: %s", self.vmem_mg.version)

        if not self._is_supported_vmos_version(self.vmem_mg.version):
            msg = _('CONCERTO version is not supported')
            raise exception.ViolinInvalidBackendConfig(reason=msg)

    @utils.synchronized('vmem-lun')
    def _create_lun(self, volume):
        """Creates a new lun.

        :param volume:  volume object provided by the Manager
        """
        spec_dict = {}
        selected_pool = {}

        size_mb = volume['size'] * units.Ki
        full_size_mb = size_mb

        LOG.debug("Creating LUN %(name)s, %(size)s MB.",
                  {'name': volume['name'], 'size': size_mb})

        spec_dict = self._process_extra_specs(volume)

        try:
            selected_pool = self._get_storage_pool(
                volume,
                size_mb,
                spec_dict['pool_type'],
                "create_lun")

        except exception.ViolinResourceNotFound:
            raise
        except Exception:
            msg = _('No suitable storage pool found')
            LOG.exception(msg)
            raise exception.ViolinBackendErr(message=msg)

        try:
            # Note: In the following create_lun command for setting up a dedup
            # or thin lun the size_mb parameter is ignored and 10% of the
            # full_size_mb specified is the size actually allocated to
            # the lun. full_size_mb is the size the lun is allowed to
            # grow. On the other hand, if it is a thick lun, the
            # full_size_mb is ignored and size_mb is the actual
            # allocated size of the lun.

            self._send_cmd(self.vmem_mg.lun.create_lun,
                           "Create resource successfully.",
                           volume['id'],
                           spec_dict['size_mb'],
                           selected_pool['dedup'],
                           selected_pool['thin'],
                           full_size_mb,
                           storage_pool_id=selected_pool['storage_pool_id'])

        except exception.ViolinBackendErrExists:
            LOG.debug("Lun %s already exists, continuing.", volume['id'])

        except Exception:
            LOG.exception("Lun create for %s failed!", volume['id'])
            raise

    @utils.synchronized('vmem-lun')
    def _delete_lun(self, volume):
        """Deletes a lun.

        :param volume:  volume object provided by the Manager
        """
        success_msgs = ['Delete resource successfully', '']

        LOG.debug("Deleting lun %s.", volume['id'])

        # If the LUN has ever had a snapshot, it has an SRA and
        # policy that must be deleted first.
        self._delete_lun_snapshot_bookkeeping(volume['id'])

        try:
            self._send_cmd(self.vmem_mg.lun.delete_lun,
                           success_msgs, volume['id'])

        except vmemclient.core.error.NoMatchingObjectIdError:
            LOG.debug("Lun %s already deleted, continuing.", volume['id'])

        except exception.ViolinBackendErrExists:
            LOG.exception("Lun %s has dependent snapshots, "
                          "skipping lun deletion.", volume['id'])
            raise exception.VolumeIsBusy(volume_name=volume['id'])

        except Exception:
            LOG.exception("Lun delete for %s failed!", volume['id'])
            raise

    def _extend_lun(self, volume, new_size):
        """Extend an existing volume's size.

        :param volume:  volume object provided by the Manager
        :param new_size:  new size in GB to be applied
        """
        v = self.vmem_mg

        typeid = volume['volume_type_id']

        if typeid and not self.vmem_mg.utility.is_external_head:
            spec_value = self._get_volume_type_extra_spec(volume, "dedup")
            if spec_value and spec_value.lower() == "true":
                # A Dedup lun's size cannot be modified in Concerto.
                msg = _('Dedup luns cannot be extended')
                raise exception.VolumeDriverException(message=msg)

        size_mb = volume['size'] * units.Ki
        new_size_mb = new_size * units.Ki

        # Concerto lun extend requires number of MB to increase size by,
        # not the final size value.
        #
        delta_mb = new_size_mb - size_mb

        LOG.debug("Extending lun %(id)s, from %(size)s to %(new_size)s MB.",
                  {'id': volume['id'], 'size': size_mb,
                   'new_size': new_size_mb})

        try:
            self._send_cmd(v.lun.extend_lun,
                           "Expand resource successfully",
                           volume['id'], delta_mb)

        except Exception:
            LOG.exception("LUN extend failed!")
            raise

    def _create_lun_snapshot(self, snapshot):
        """Create a new cinder snapshot on a volume.

        This maps onto a Concerto 'timemark', but we must always first
        ensure that a snapshot resource area (SRA) exists, and that a
        snapshot policy exists.

        :param snapshot:  cinder snapshot object provided by the Manager

        :raises:
            VolumeBackendAPIException: If SRA could not be created, or
                snapshot policy could not be created
            RequestRetryTimeout: If backend could not complete the request
                within the allotted timeout.
            ViolinBackendErr: If backend reports an error during the
                create snapshot phase.
        """

        cinder_volume_id = snapshot['volume_id']
        cinder_snapshot_id = snapshot['id']

        LOG.debug("Creating LUN snapshot %(snap_id)s on volume "
                  "%(vol_id)s %(dpy_name)s.",
                  {'snap_id': cinder_snapshot_id,
                   'vol_id': cinder_volume_id,
                   'dpy_name': snapshot['display_name']})

        self._ensure_snapshot_resource_area(cinder_volume_id)

        self._ensure_snapshot_policy(cinder_volume_id)

        try:
            self._send_cmd(
                self.vmem_mg.snapshot.create_lun_snapshot,
                "Create TimeMark successfully",
                lun=cinder_volume_id,
                comment=self._compress_snapshot_id(cinder_snapshot_id),
                priority=CONCERTO_DEFAULT_PRIORITY,
                enable_notification=False)
        except Exception:
            LOG.exception("Lun create snapshot for "
                          "volume %(vol)s snapshot %(snap)s failed!",
                          {'vol': cinder_volume_id,
                           'snap': cinder_snapshot_id})
            raise

    def _delete_lun_snapshot(self, snapshot):
        """Delete the specified cinder snapshot.

        :param snapshot:  cinder snapshot object provided by the Manager

        :raises:
            RequestRetryTimeout: If backend could not complete the request
                within the allotted timeout.
            ViolinBackendErr: If backend reports an error during the
                delete snapshot phase.
        """
        LOG.debug("Deleting snapshot %(snap_id)s on volume "
                  "%(vol_id)s %(dpy_name)s",
                  {'snap_id': snapshot['id'],
                   'vol_id': snapshot['volume_id'],
                   'dpy_name': snapshot['display_name']})

        return self._wait_run_delete_lun_snapshot(snapshot)

    def _create_volume_from_snapshot(self, snapshot, volume):
        """Create a new cinder volume from a given snapshot of a lun

        This maps onto a Concerto 'copy  snapshot to lun'. Concerto
        creates the lun and then copies the snapshot into it.

        :param snapshot:  cinder snapshot object provided by the Manager
        :param volume:  cinder volume to be created
        """
        cinder_volume_id = volume['id']
        cinder_snapshot_id = snapshot['id']
        size_mb = volume['size'] * units.Ki
        result = None
        spec_dict = {}

        LOG.debug("Copying snapshot %(snap_id)s onto volume %(vol_id)s "
                  "%(dpy_name)s",
                  {'snap_id': cinder_snapshot_id,
                   'vol_id': cinder_volume_id,
                   'dpy_name': snapshot['display_name']})

        source_lun_info = self.vmem_mg.lun.get_lun_info(snapshot['volume_id'])
        self._validate_lun_type_for_copy(source_lun_info['subType'])

        spec_dict = self._process_extra_specs(volume)
        try:
            selected_pool = self._get_storage_pool(volume,
                                                   size_mb,
                                                   spec_dict['pool_type'],
                                                   "create_lun")

        except exception.ViolinResourceNotFound:
            raise
        except Exception:
            msg = _('No suitable storage pool found')
            LOG.exception(msg)
            raise exception.ViolinBackendErr(message=msg)

        try:
            result = self.vmem_mg.lun.copy_snapshot_to_new_lun(
                source_lun=snapshot['volume_id'],
                source_snapshot_comment=self._compress_snapshot_id(
                    cinder_snapshot_id),
                destination=cinder_volume_id,
                storage_pool_id=selected_pool['storage_pool_id'])

            if not result['success']:
                self._check_error_code(result)

        except Exception:
            LOG.exception("Copy snapshot to volume for "
                          "snapshot %(snap)s volume %(vol)s failed!",
                          {'snap': cinder_snapshot_id,
                           'vol': cinder_volume_id})
            raise

        # get the destination lun info and extract virtualdeviceid
        info = self.vmem_mg.lun.get_lun_info(object_id=result['object_id'])

        self._wait_for_lun_or_snap_copy(
            snapshot['volume_id'], dest_vdev_id=info['virtualDeviceID'])

    def _create_lun_from_lun(self, src_vol, dest_vol):
        """Copy the contents of a lun to a new lun (i.e., full clone).

        :param src_vol:  cinder volume to clone
        :param dest_vol:  cinder volume to be created
        """
        size_mb = dest_vol['size'] * units.Ki
        src_vol_mb = src_vol['size'] * units.Ki
        result = None
        spec_dict = {}

        LOG.debug("Copying lun %(src_vol_id)s onto lun %(dest_vol_id)s.",
                  {'src_vol_id': src_vol['id'],
                   'dest_vol_id': dest_vol['id']})

        try:
            source_lun_info = self.vmem_mg.lun.get_lun_info(src_vol['id'])
            self._validate_lun_type_for_copy(source_lun_info['subType'])

            # in order to do a full clone the source lun must have a
            # snapshot resource
            self._ensure_snapshot_resource_area(src_vol['id'])

            spec_dict = self._process_extra_specs(dest_vol)
            selected_pool = self._get_storage_pool(dest_vol,
                                                   size_mb,
                                                   spec_dict['pool_type'],
                                                   None)

            result = self.vmem_mg.lun.copy_lun_to_new_lun(
                source=src_vol['id'], destination=dest_vol['id'],
                storage_pool_id=selected_pool['storage_pool_id'])

            if not result['success']:
                self._check_error_code(result)

        except Exception:
            LOG.exception("Create new lun from lun for source "
                          "%(src)s => destination %(dest)s failed!",
                          {'src': src_vol['id'], 'dest': dest_vol['id']})
            raise

        self._wait_for_lun_or_snap_copy(
            src_vol['id'], dest_obj_id=result['object_id'])

        # extend the copied lun if requested size is larger then original
        if size_mb > src_vol_mb:
            # dest_vol size has to be set to reflect what it is currently
            dest_vol_size = dest_vol['size']
            dest_vol['size'] = src_vol['size']
            self._extend_lun(dest_vol, dest_vol_size)
            dest_vol['size'] = dest_vol_size

    def _send_cmd(self, request_func, success_msgs, *args, **kwargs):
        """Run an XG request function, and retry as needed.

        The request will be retried until it returns a success
        message, a failure message, or the global request timeout is
        hit.

        This wrapper is meant to deal with backend requests that can
        fail for any variety of reasons, for instance, when the system
        is already busy handling other LUN requests. If there is no
        space left, or other "fatal" errors are returned (see
        _fatal_error_code() for a list of all known error conditions).

        :param request_func:  XG api method to call
        :param success_msgs:  Success messages expected from the backend
        :param *args:  argument array to be passed to the request_func
        :param **kwargs:  argument dictionary to be passed to request_func
        :returns: the response dict from the last XG call
        """
        resp = {}
        start = time.time()
        done = False

        if isinstance(success_msgs, six.string_types):
            success_msgs = [success_msgs]

        while not done:
            if time.time() - start >= self.config.violin_request_timeout:
                raise exception.ViolinRequestRetryTimeout(
                    timeout=self.config.violin_request_timeout)

            resp = request_func(*args, **kwargs)

            if not resp['msg']:
                # XG requests will return None for a message if no message
                # string is passed in the raw response
                resp['msg'] = ''

            for msg in success_msgs:
                if resp['success'] and msg in resp['msg']:
                    done = True
                    break

            if not resp['success']:
                self._check_error_code(resp)
                done = True
                break

        return resp

    def _send_cmd_and_verify(self, request_func, verify_func,
                             request_success_msgs='', rargs=None, vargs=None):
        """Run an XG request function, retry if needed, and verify success.

        If the verification fails, then retry the request/verify cycle
        until both functions are successful, the request function
        returns a failure message, or the global request timeout is
        hit.

        This wrapper is meant to deal with backend requests that can
        fail for any variety of reasons, for instance, when the system
        is already busy handling other LUN requests.  It is also smart
        enough to give up if clustering is down (eg no HA available),
        there is no space left, or other "fatal" errors are returned
        (see _fatal_error_code() for a list of all known error
        conditions).

        :param request_func:  XG api method to call
        :param verify_func:  function call to verify request was completed
        :param request_success_msg:  Success message expected for request_func
        :param *rargs:  argument array to be passed to request_func
        :param *vargs:  argument array to be passed to verify_func
        :returns: the response dict from the last XG call
        """
        resp = {}
        start = time.time()
        request_needed = True
        verify_needed = True

        if isinstance(request_success_msgs, six.string_types):
            request_success_msgs = [request_success_msgs]

        rargs = rargs if rargs else []
        vargs = vargs if vargs else []

        while request_needed or verify_needed:
            if time.time() - start >= self.config.violin_request_timeout:
                raise exception.ViolinRequestRetryTimeout(
                    timeout=self.config.violin_request_timeout)

            if request_needed:
                resp = request_func(*rargs)

                if not resp['msg']:
                    # XG requests will return None for a message if no message
                    # string is passed in the raw response
                    resp['msg'] = ''

                for msg in request_success_msgs:
                    if resp['success'] and msg in resp['msg']:
                        request_needed = False
                        break

                if not resp['success']:
                    self._check_error_code(resp)
                    request_needed = False

            elif verify_needed:
                success = verify_func(*vargs)
                if success:
                    # XG verify func was completed
                    verify_needed = False

        return resp

    def _ensure_snapshot_resource_area(self, volume_id):
        """Make sure concerto snapshot resource area exists on volume.

        :param volume_id:  Cinder volume ID corresponding to the backend LUN

        :raises:
            VolumeBackendAPIException: if cinder volume does not exist
               on backnd, or SRA could not be created.
        """
        ctxt = context.get_admin_context()
        volume = api.volume_get(ctxt, volume_id)
        spec_dict = {}

        if not volume:
            msg = (_("Failed to ensure snapshot resource area, could not "
                   "locate volume for id %s") % volume_id)
            raise exception.VolumeBackendAPIException(data=msg)

        if not self.vmem_mg.snapshot.lun_has_a_snapshot_resource(
           lun=volume_id):
            # Per Concerto documentation, the SRA size should be computed
            # as follows
            #  Size-of-original-LUN        Reserve for SRA
            #   < 500MB                    100%
            #   500MB to 2G                50%
            #   >= 2G                      20%
            # Note: cinder volume.size is in GB, vmemclient wants MB.
            lun_size_mb = volume['size'] * units.Ki
            if lun_size_mb < 500:
                snap_size_mb = lun_size_mb
            elif lun_size_mb < 2000:
                snap_size_mb = 0.5 * lun_size_mb
            else:
                snap_size_mb = 0.2 * lun_size_mb

            snap_size_mb = int(math.ceil(snap_size_mb))

            spec_dict = self._process_extra_specs(volume)

            try:
                selected_pool = self._get_storage_pool(
                    volume,
                    snap_size_mb,
                    spec_dict['pool_type'],
                    None)

                LOG.debug("Creating SRA of %(ssmb)sMB for lun of %(lsmb)sMB "
                          "on %(vol_id)s",
                          {'ssmb': snap_size_mb,
                           'lsmb': lun_size_mb,
                           'vol_id': volume_id})

            except exception.ViolinResourceNotFound:
                raise
            except Exception:
                msg = _('No suitable storage pool found')
                LOG.exception(msg)
                raise exception.ViolinBackendErr(message=msg)

            res = self.vmem_mg.snapshot.create_snapshot_resource(
                lun=volume_id,
                size=snap_size_mb,
                enable_notification=False,
                policy=CONCERTO_DEFAULT_SRA_POLICY,
                enable_expansion=CONCERTO_DEFAULT_SRA_ENABLE_EXPANSION,
                expansion_threshold=CONCERTO_DEFAULT_SRA_EXPANSION_THRESHOLD,
                expansion_increment=CONCERTO_DEFAULT_SRA_EXPANSION_INCREMENT,
                expansion_max_size=CONCERTO_DEFAULT_SRA_EXPANSION_MAX_SIZE,
                enable_shrink=CONCERTO_DEFAULT_SRA_ENABLE_SHRINK,
                storage_pool_id=selected_pool['storage_pool_id'])

            if (not res['success']):
                msg = (_("Failed to create snapshot resource area on "
                       "volume %(vol)s: %(res)s.") %
                       {'vol': volume_id, 'res': res['msg']})
                raise exception.VolumeBackendAPIException(data=msg)

    def _ensure_snapshot_policy(self, volume_id):
        """Ensure concerto snapshot policy exists on cinder volume.

        A snapshot policy is required by concerto in order to create snapshots.

        :param volume_id:  Cinder volume ID corresponding to the backend LUN

        :raises:
            VolumeBackendAPIException: when snapshot policy cannot be created.
        """
        if not self.vmem_mg.snapshot.lun_has_a_snapshot_policy(
                lun=volume_id):

            res = self.vmem_mg.snapshot.create_snapshot_policy(
                lun=volume_id,
                max_snapshots=CONCERTO_DEFAULT_POLICY_MAX_SNAPSHOTS,
                enable_replication=False,
                enable_snapshot_schedule=False,
                enable_cdp=False,
                retention_mode=CONCERTO_DEFAULT_POLICY_RETENTION_MODE)

            if not res['success']:
                msg = (_(
                    "Failed to create snapshot policy on "
                    "volume %(vol)s: %(res)s.") %
                    {'vol': volume_id, 'res': res['msg']})
                raise exception.VolumeBackendAPIException(data=msg)

    def _delete_lun_snapshot_bookkeeping(self, volume_id):
        """Clear residual snapshot support resources from LUN.

        :raises:
            VolumeBackendAPIException: If snapshots still exist on the LUN.
        """

        # Make absolutely sure there are no snapshots present
        try:
            snaps = self.vmem_mg.snapshot.get_snapshots(volume_id)
            if len(snaps) > 0:
                msg = (_("Cannot delete LUN %s while snapshots exist.") %
                       volume_id)
                raise exception.VolumeBackendAPIException(data=msg)
        except vmemclient.core.error.NoMatchingObjectIdError:
            pass
        except vmemclient.core.error.MissingParameterError:
            pass

        try:
            res = self.vmem_mg.snapshot.delete_snapshot_policy(
                lun=volume_id)
            if not res['success']:
                if 'TimeMark is disabled' in res['msg']:
                    LOG.debug("Verified no snapshot policy is on volume %s.",
                              volume_id)
                else:
                    msg = (_("Unable to delete snapshot policy on "
                             "volume %s.") % volume_id)
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                LOG.debug("Deleted snapshot policy on volume "
                          "%(vol)s, result %(res)s.",
                          {'vol': volume_id, 'res': res})
        except vmemclient.core.error.NoMatchingObjectIdError:
            LOG.debug("Verified no snapshot policy present on volume %s.",
                      volume_id)
            pass

        try:
            res = self.vmem_mg.snapshot.delete_snapshot_resource(
                lun=volume_id)
            LOG.debug("Deleted snapshot resource area on "
                      "volume %(vol)s, result %(res)s.",
                      {'vol': volume_id, 'res': res})
        except vmemclient.core.error.NoMatchingObjectIdError:
            LOG.debug("Verified no snapshot resource area present on "
                      "volume %s.", volume_id)
            pass

    def _compress_snapshot_id(self, cinder_snap_id):
        """Compress cinder snapshot ID so it fits in backend.

           Compresses to fit in 32-chars.
        """
        return ''.join(six.text_type(cinder_snap_id).split('-'))

    def _get_snapshot_from_lun_snapshots(
            self, cinder_volume_id, cinder_snap_id):
        """Locate backend snapshot dict associated with cinder snapshot id.

        :returns: Cinder snapshot dictionary if found, None otherwise.
        """

        try:
            snaps = self.vmem_mg.snapshot.get_snapshots(cinder_volume_id)
        except vmemclient.core.error.NoMatchingObjectIdError:
            return None

        key = self._compress_snapshot_id(cinder_snap_id)

        for s in snaps:
            if s['comment'] == key:
                # Remap return dict to its uncompressed form
                s['comment'] = cinder_snap_id
                return s

    def _wait_for_lun_or_snap_copy(self, src_vol_id, dest_vdev_id=None,
                                   dest_obj_id=None):
        """Poll to see when a lun or snap copy to a lun is complete.

        :param src_vol_id:  cinder volume ID of source volume
        :param dest_vdev_id:  virtual device ID of destination, for snap copy
        :param dest_obj_id:  lun object ID of destination, for lun copy
        :returns: True if successful, False otherwise
        """
        wait_id = None
        wait_func = None

        if dest_vdev_id:
            wait_id = dest_vdev_id
            wait_func = self.vmem_mg.snapshot.get_snapshot_copy_status
        elif dest_obj_id:
            wait_id = dest_obj_id
            wait_func = self.vmem_mg.lun.get_lun_copy_status
        else:
            return False

        def _loop_func():
            LOG.debug("Entering _wait_for_lun_or_snap_copy loop: "
                      "vdev=%s, objid=%s", dest_vdev_id, dest_obj_id)

            target_id, mb_copied, percent = wait_func(src_vol_id)

            if target_id is None:
                # pre-copy transient result
                LOG.debug("lun or snap copy prepping.")
                pass
            elif target_id != wait_id:
                # the copy is complete, another lun is being copied
                LOG.debug("lun or snap copy complete.")
                raise loopingcall.LoopingCallDone(retvalue=True)
            elif mb_copied is not None:
                # copy is in progress
                LOG.debug("MB copied: %(copied)d, percent done: %(percent)d.",
                          {'copied': mb_copied, 'percent': percent})
                pass
            elif percent == 0:
                # copy has just started
                LOG.debug("lun or snap copy started.")
                pass
            elif percent == 100:
                # copy is complete
                LOG.debug("lun or snap copy complete.")
                raise loopingcall.LoopingCallDone(retvalue=True)
            else:
                # unexpected case
                LOG.debug("unexpected case (%(id)s, %(bytes)s, %(percent)s)",
                          {'id': target_id,
                           'bytes': mb_copied,
                           'percent': six.text_type(percent)})
                raise loopingcall.LoopingCallDone(retvalue=False)

        timer = loopingcall.FixedIntervalLoopingCall(_loop_func)
        success = timer.start(interval=1).wait()

        return success

    def _is_supported_vmos_version(self, version_string):
        """Check a version string for compatibility with OpenStack.

        Compare a version string against the global regex of versions
        compatible with OpenStack.

        :param version_string:  array's gateway version string
        :returns: True if supported, false if not
        """
        for pattern in CONCERTO_SUPPORTED_VERSION_PATTERNS:
            if re.match(pattern, version_string):
                return True
        return False

    def _check_error_code(self, response):
        """Raise an exception when backend returns certain errors.

        Error codes returned from the backend have to be examined
        individually. Not all of them are fatal. For example, lun attach
        failing becase the client is already attached is not a fatal error.

        :param response: a response dict result from the vmemclient request
        """
        if "Error: 0x9001003c" in response['msg']:
            # This error indicates a duplicate attempt to attach lun,
            # non-fatal error
            pass
        elif "Error: 0x9002002b" in response['msg']:
            # lun unexport failed - lun is not exported to any clients,
            # non-fatal error
            pass
        elif "Error: 0x09010023" in response['msg']:
            # lun delete failed - dependent snapshot copy in progress,
            # fatal error
            raise exception.ViolinBackendErr(message=response['msg'])
        elif "Error: 0x09010048" in response['msg']:
            # lun delete failed - dependent snapshots still exist,
            # fatal error
            raise exception.ViolinBackendErr(message=response['msg'])
        elif "Error: 0x90010022" in response['msg']:
            # lun create failed - lun with same name already exists,
            # fatal error
            raise exception.ViolinBackendErrExists()
        elif "Error: 0x90010089" in response['msg']:
            # lun export failed - lun is still being created as copy,
            # fatal error
            raise exception.ViolinBackendErr(message=response['msg'])
        else:
            # assume any other error is fatal
            raise exception.ViolinBackendErr(message=response['msg'])

    def _get_volume_type_extra_spec(self, volume, spec_key):
        """Parse data stored in a volume_type's extra_specs table.

        :param volume:  volume object containing volume_type to query
        :param spec_key:  the metadata key to search for
        :returns: string value associated with spec_key
        """
        spec_value = None
        ctxt = context.get_admin_context()
        typeid = volume['volume_type_id']
        if typeid:
            volume_type = volume_types.get_volume_type(ctxt, typeid)
            volume_specs = volume_type.get('extra_specs')
            for key, val in volume_specs.items():

                # Strip the prefix "capabilities"
                if ':' in key:
                    scope = key.split(':')
                    key = scope[1]
                if key == spec_key:
                    spec_value = val
                    break

        return spec_value

    def _get_violin_extra_spec(self, volume, spec_key):
        """Parse volume_type's extra_specs table for a violin-specific key.

        :param volume:  volume object containing volume_type to query
        :param spec_key:  the metadata key to search for
        :returns: string value associated with spec_key
        """
        spec_value = None
        ctxt = context.get_admin_context()
        typeid = volume['volume_type_id']
        if typeid:
            volume_type = volume_types.get_volume_type(ctxt, typeid)
            volume_specs = volume_type.get('extra_specs')
            for key, val in volume_specs.items():

                # Strip the prefix "violin"
                if ':' in key:
                    scope = key.split(':')
                    key = scope[1]
                    if scope[0] == "violin" and key == spec_key:
                        spec_value = val
                        break
        return spec_value

    def _get_storage_pool(self, volume, size_in_mb, pool_type, usage):
        # User-specified pool takes precedence over others

        pool = None
        typeid = volume.get('volume_type_id')
        if typeid:
            # Extract the storage_pool name if one is specified
            pool = self._get_violin_extra_spec(volume, "storage_pool")

        # Select a storage pool
        selected_pool = self.vmem_mg.pool.select_storage_pool(
            size_in_mb,
            pool_type,
            pool,
            self.config.violin_dedup_only_pools,
            self.config.violin_dedup_capable_pools,
            self.config.violin_pool_allocation_method,
            usage)
        if selected_pool is None:
            # Backend has not provided a suitable storage pool
            msg = _("Backend does not have a suitable storage pool.")
            raise exception.ViolinResourceNotFound(message=msg)

        LOG.debug("Storage pool returned is %s",
                  selected_pool['storage_pool'])

        return selected_pool

    def _process_extra_specs(self, volume):
        spec_dict = {}
        thin_lun = False
        thick_lun = False
        dedup = False
        size_mb = volume['size'] * units.Ki
        full_size_mb = size_mb

        if self.config.san_thin_provision:
            thin_lun = True
            # Set the actual allocation size for thin lun
            # default here is 10%
            size_mb = int(math.ceil(float(size_mb) / LUN_ALLOC_SZ))

        typeid = volume.get('volume_type_id')
        if typeid:
            # extra_specs with thin specified overrides san_thin_provision
            spec_value = self._get_volume_type_extra_spec(volume, "thin")
            if not thin_lun and spec_value and spec_value.lower() == "true":
                thin_lun = True
                # Set the actual allocation size for thin lun
                # default here is 10%
                size_mb = int(math.ceil(float(size_mb) / LUN_ALLOC_SZ))

            # Set thick lun before checking for dedup,
            # since dedup is always thin
            if not thin_lun:
                thick_lun = True

            spec_value = self._get_volume_type_extra_spec(volume, "dedup")
            if spec_value and spec_value.lower() == "true":
                dedup = True
                # A dedup lun is always a thin lun
                thin_lun = True
                thick_lun = False
                # Set the actual allocation size for thin lun
                # default here is 10%. The actual allocation may
                # different, depending on other factors
                size_mb = int(math.ceil(float(full_size_mb) / LUN_ALLOC_SZ))

        if dedup:
            spec_dict['pool_type'] = "dedup"
        elif thin_lun:
            spec_dict['pool_type'] = "thin"
        else:
            spec_dict['pool_type'] = "thick"
            thick_lun = True

        spec_dict['size_mb'] = size_mb
        spec_dict['thick'] = thick_lun
        spec_dict['thin'] = thin_lun
        spec_dict['dedup'] = dedup

        return spec_dict

    def _get_volume_stats(self, san_ip):
        """Gathers array stats and converts them to GB values."""
        free_gb = 0
        total_gb = 0

        owner = socket.getfqdn(san_ip)
        # Store DNS lookups to prevent asking the same question repeatedly
        owner_lookup = {san_ip: owner}
        pools = self.vmem_mg.pool.get_storage_pools(
            verify=True,
            include_full_info=True,
        )

        for short_info, full_info in pools:
            mod = ''
            pool_free_mb = 0
            pool_total_mb = 0
            for dev in full_info.get('physicaldevices', []):
                if dev['owner'] not in owner_lookup:
                    owner_lookup[dev['owner']] = socket.getfqdn(dev['owner'])
                if owner_lookup[dev['owner']] == owner:
                    pool_free_mb += dev['availsize_mb']
                    pool_total_mb += dev['size_mb']
                elif not mod:
                    mod = ' *'
            LOG.debug('pool %(pool)s: %(avail)s / %(total)s MB free %(mod)s',
                      {'pool': short_info['name'], 'avail': pool_free_mb,
                       'total': pool_total_mb, 'mod': mod})
            free_gb += int(pool_free_mb / units.Ki)
            total_gb += int(pool_total_mb / units.Ki)

        data = {
            'vendor_name': 'Violin Memory, Inc.',
            'reserved_percentage': self.config.reserved_percentage,
            'QoS_support': False,
            'free_capacity_gb': free_gb,
            'total_capacity_gb': total_gb,
            'consistencygroup_support': False,
        }

        return data

    def _wait_run_delete_lun_snapshot(self, snapshot):
        """Run and wait for LUN snapshot to complete.

        :param snapshot -- cinder snapshot object provided by the Manager
        """
        cinder_volume_id = snapshot['volume_id']
        cinder_snapshot_id = snapshot['id']

        comment = self._compress_snapshot_id(cinder_snapshot_id)
        oid = self.vmem_mg.snapshot.snapshot_comment_to_object_id(
            cinder_volume_id, comment)

        def _loop_func():
            LOG.debug("Entering _wait_run_delete_lun_snapshot loop: "
                      "vol=%(vol)s, snap_id=%(snap_id)s, oid=%(oid)s",
                      {'vol': cinder_volume_id,
                       'oid': oid,
                       'snap_id': cinder_snapshot_id})

            try:
                ans = self.vmem_mg.snapshot.delete_lun_snapshot(
                    snapshot_object_id=oid)
            except Exception:
                msg = (_("Failed to delete snapshot "
                         "%(snap)s of volume %(vol)s") %
                       {'snap': cinder_snapshot_id, 'vol': cinder_volume_id})
                raise exception.ViolinBackendErr(msg)

            if ans['success']:
                LOG.debug("Delete snapshot %(snap_id)s of %(vol)s: "
                          "success", {'vol': cinder_volume_id,
                                      'snap_id': cinder_snapshot_id})
                raise loopingcall.LoopingCallDone(retvalue=True)
            else:
                LOG.warning("Delete snapshot %(snap)s of %(vol)s "
                            "encountered temporary error: %(msg)s",
                            {'snap': cinder_snapshot_id,
                             'vol': cinder_volume_id,
                             'msg': ans['msg']})

        timer = loopingcall.FixedIntervalLoopingCall(_loop_func)
        success = timer.start(interval=1).wait()

        return success

    def _validate_lun_type_for_copy(self, lun_type):
        """Make sure volume type is thick.

        :param lun_type:  Cinder volume type

        :raises:
            VolumeBackendAPIException: if volume type is not thick,
               copying the lun is not possible.
        """
        if lun_type != CONCERTO_LUN_TYPE_THICK:
            msg = _('Lun copy currently only supported for thick luns')
            LOG.error(msg)
            raise exception.ViolinBackendErr(message=msg)
