# Copyright 2014 Violin Memory, Inc.
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
Violin Memory 6000 Series All-Flash Array Common Driver for Openstack Cinder

Provides common (ie., non-protocol specific) management functions for
V6000 series flash arrays.

Backend array communication is handled via VMEM's python library
called 'vmemclient'.

NOTE: this driver file requires the use of synchronization points for
certain types of backend operations, and as a result may not work
properly in an active-active HA configuration.  See OpenStack Cinder
driver documentation for more information.
"""

import re
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _, _LE, _LW, _LI
from cinder.openstack.common import loopingcall
from cinder import utils

LOG = logging.getLogger(__name__)

vmemclient = importutils.try_import("vmemclient")
if vmemclient:
    LOG.info(_LI("Running with vmemclient version: %s."),
             vmemclient.__version__)

# version vmos versions V6.3.0.4 or newer
VMOS_SUPPORTED_VERSION_PATTERNS = ['V6.3.0.[4-9]', 'V6.3.[1-9].?[0-9]?']

violin_opts = [
    cfg.StrOpt('gateway_mga',
               default=None,
               help='IP address or hostname of mg-a'),
    cfg.StrOpt('gateway_mgb',
               default=None,
               help='IP address or hostname of mg-b'),
    cfg.BoolOpt('use_igroups',
                default=False,
                help='Use igroups to manage targets and initiators'),
    cfg.IntOpt('request_timeout',
               default=300,
               help='Global backend request timeout, in seconds'),
]

CONF = cfg.CONF
CONF.register_opts(violin_opts)


class V6000Common(object):
    """Contains common code for the Violin V6000 drivers.

    Version history:
        1.0 - Initial driver
    """

    VERSION = '1.0'

    def __init__(self, config):
        self.vip = None
        self.mga = None
        self.mgb = None
        self.container = ""
        self.config = config

    def do_setup(self, context):
        """Any initialization the driver does while starting."""
        if not self.config.san_ip:
            raise exception.InvalidInput(
                reason=_('Gateway VIP option \'san_ip\' is not set'))
        if not self.config.gateway_mga:
            raise exception.InvalidInput(
                reason=_('Gateway MG-A IP option \'gateway_mga\' is not set'))
        if not self.config.gateway_mgb:
            raise exception.InvalidInput(
                reason=_('Gateway MG-B IP option \'gateway_mgb\' is not set'))
        if self.config.request_timeout <= 0:
            raise exception.InvalidInput(
                reason=_('Global timeout option \'request_timeout\' must be '
                         'greater than 0'))

        self.vip = vmemclient.open(self.config.san_ip,
                                   self.config.san_login,
                                   self.config.san_password, keepalive=True)
        self.mga = vmemclient.open(self.config.gateway_mga,
                                   self.config.san_login,
                                   self.config.san_password, keepalive=True)
        self.mgb = vmemclient.open(self.config.gateway_mgb,
                                   self.config.san_login,
                                   self.config.san_password, keepalive=True)

        ret_dict = self.vip.basic.get_node_values(
            "/vshare/state/local/container/*")
        if ret_dict:
            self.container = ret_dict.items()[0][1]

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""

        if len(self.container) == 0:
            msg = _('container is missing')
            raise exception.ViolinInvalidBackendConfig(reason=msg)

        if not self._is_supported_vmos_version(self.vip.version):
            msg = _('VMOS version is not supported')
            raise exception.ViolinInvalidBackendConfig(reason=msg)

        bn1 = ("/vshare/state/local/container/%s/threshold/usedspace"
               "/threshold_hard_val" % self.container)
        bn2 = ("/vshare/state/local/container/%s/threshold/provision"
               "/threshold_hard_val" % self.container)
        ret_dict = self.vip.basic.get_node_values([bn1, bn2])

        for node in ret_dict:
            # The infrastructure does not support space reclamation so
            # ensure it is disabled.  When used space exceeds the hard
            # limit, snapshot space reclamation begins.  Default is 0
            # => no space reclamation.
            #
            if node.endswith('/usedspace/threshold_hard_val'):
                if ret_dict[node] != 0:
                    msg = _('space reclamation threshold is enabled but not '
                            'supported by Cinder infrastructure.')
                    raise exception.ViolinInvalidBackendConfig(reason=msg)

            # The infrastructure does not support overprovisioning so
            # ensure it is disabled.  When provisioned space exceeds
            # the hard limit, further provisioning is stopped.
            # Default is 100 => provisioned space equals usable space.
            #
            elif node.endswith('/provision/threshold_hard_val'):
                if ret_dict[node] != 100:
                    msg = _('provisioned space threshold is not equal to '
                            'usable space.')
                    raise exception.ViolinInvalidBackendConfig(reason=msg)

    @utils.synchronized('vmem-lun')
    def _create_lun(self, volume):
        """Creates a new lun.

        The equivalent CLI command is "lun create container
        <container_name> name <lun_name> size <gb>"

        Arguments:
            volume -- volume object provided by the Manager
        """
        lun_type = '0'

        LOG.debug("Creating LUN %(name)s, %(size)s GB." %
                  {'name': volume['name'], 'size': volume['size']})

        if self.config.san_thin_provision:
            lun_type = '1'

        # using the defaults for fields: quantity, nozero,
        # readonly, startnum, blksize, naca, alua, preferredport
        #
        try:
            self._send_cmd(self.vip.lun.create_lun,
                           'LUN create: success!',
                           self.container, volume['id'],
                           volume['size'], 1, '0', lun_type, 'w',
                           1, 512, False, False, None)

        except exception.ViolinBackendErrExists:
            LOG.debug("Lun %s already exists, continuing.", volume['id'])

        except Exception:
            LOG.warn(_LW("Lun create for %s failed!"), volume['id'])
            raise

    @utils.synchronized('vmem-lun')
    def _delete_lun(self, volume):
        """Deletes a lun.

        The equivalent CLI command is "no lun create container
        <container_name> name <lun_name>"

        Arguments:
            volume -- volume object provided by the Manager
        """
        success_msgs = ['lun deletion started', '']

        LOG.debug("Deleting lun %s.", volume['id'])

        try:
            self._send_cmd(self.vip.lun.bulk_delete_luns,
                           success_msgs, self.container, volume['id'])

        except exception.ViolinBackendErrNotFound:
            LOG.debug("Lun %s already deleted, continuing.", volume['id'])

        except exception.ViolinBackendErrExists:
            LOG.warn(_LW("Lun %s has dependent snapshots, skipping."),
                     volume['id'])
            raise exception.VolumeIsBusy(volume_name=volume['id'])

        except Exception:
            LOG.exception(_LE("Lun delete for %s failed!"), volume['id'])
            raise

    @utils.synchronized('vmem-lun')
    def _extend_lun(self, volume, new_size):
        """Extend an existing volume's size.

        The equivalent CLI command is "lun resize container
        <container_name> name <lun_name> size <gb>"

        Arguments:
            volume   -- volume object provided by the Manager
            new_size -- new (increased) size in GB to be applied
        """
        LOG.debug("Extending lun %(id)s, from %(size)s to %(new_size)s GB." %
                  {'id': volume['id'], 'size': volume['size'],
                   'new_size': new_size})

        try:
            self._send_cmd(self.vip.lun.resize_lun, 'Success',
                           self.container, volume['id'], new_size)

        except Exception:
            LOG.exception(_LE("LUN extend for %s failed!"), volume['id'])
            raise

    @utils.synchronized('vmem-snap')
    def _create_lun_snapshot(self, snapshot):
        """Creates a new snapshot for a lun.

        The equivalent CLI command is "snapshot create container
        <container> lun <volume_name> name <snapshot_name>"

        Arguments:
            snapshot -- snapshot object provided by the Manager
        """
        LOG.debug("Creating snapshot %s.", snapshot['id'])

        try:
            self._send_cmd(self.vip.snapshot.create_lun_snapshot,
                           'Snapshot create: success!',
                           self.container, snapshot['volume_id'],
                           snapshot['id'])

        except exception.ViolinBackendErrExists:
            LOG.debug("Snapshot %s already exists, continuing.",
                      snapshot['id'])

        except Exception:
            LOG.exception(_LE("LUN snapshot create for %s failed!"),
                          snapshot['id'])
            raise

    @utils.synchronized('vmem-snap')
    def _delete_lun_snapshot(self, snapshot):
        """Deletes an existing snapshot for a lun.

        The equivalent CLI command is "no snapshot create container
        <container> lun <volume_name> name <snapshot_name>"

        Arguments:
            snapshot -- snapshot object provided by the Manager
        """
        LOG.debug("Deleting snapshot %s.", snapshot['id'])

        try:
            self._send_cmd(self.vip.snapshot.delete_lun_snapshot,
                           'Snapshot delete: success!',
                           self.container, snapshot['volume_id'],
                           snapshot['id'])

        except exception.ViolinBackendErrNotFound:
            LOG.debug("Snapshot %s already deleted, continuing.",
                      snapshot['id'])

        except Exception:
            LOG.exception(_LE("LUN snapshot delete for %s failed!"),
                          snapshot['id'])
            raise

    def _get_lun_id(self, volume_name):
        """Queries the gateway to find the lun id for the exported volume.

        Arguments:
            volume_name    -- LUN to query

        Returns:
            LUN ID for the exported lun.
        """
        lun_id = -1

        prefix = "/vshare/config/export/container"
        bn = "%s/%s/lun/%s/target/**" % (prefix, self.container, volume_name)
        resp = self.vip.basic.get_node_values(bn)

        for node in resp:
            if node.endswith('/lun_id'):
                lun_id = resp[node]
                break

        if lun_id == -1:
            raise exception.ViolinBackendErrNotFound()
        return lun_id

    def _get_snapshot_id(self, volume_name, snapshot_name):
        """Queries the gateway to find the lun id for the exported snapshot.

        Arguments:
            volume_name    -- LUN to query
            snapshot_name  -- Exported snapshot associated with LUN

        Returns:
            LUN ID for the exported lun
        """
        lun_id = -1

        prefix = "/vshare/config/export/snapshot/container"
        bn = "%s/%s/lun/%s/snap/%s/target/**" \
            % (prefix, self.container, volume_name, snapshot_name)
        resp = self.vip.basic.get_node_values(bn)

        for node in resp:
            if node.endswith('/lun_id'):
                lun_id = resp[node]
                break

        if lun_id == -1:
            raise exception.ViolinBackendErrNotFound()
        return lun_id

    def _send_cmd(self, request_func, success_msgs, *args):
        """Run an XG request function, and retry as needed.

        The request will be retried until it returns a success
        message, a failure message, or the global request timeout is
        hit.

        This wrapper is meant to deal with backend requests that can
        fail for any variety of reasons, for instance, when the system
        is already busy handling other LUN requests.  It is also smart
        enough to give up if clustering is down (eg no HA available),
        there is no space left, or other "fatal" errors are returned
        (see _fatal_error_code() for a list of all known error
        conditions).

        Arguments:
            request_func    -- XG api method to call
            success_msgs    -- Success messages expected from the backend
            *args           -- argument array to be passed to the request_func

        Returns:
            The response dict from the last XG call.
        """
        resp = {}
        start = time.time()
        done = False

        if isinstance(success_msgs, basestring):
            success_msgs = [success_msgs]

        while not done:
            if time.time() - start >= self.config.request_timeout:
                raise exception.ViolinRequestRetryTimeout(
                    timeout=self.config.request_timeout)

            resp = request_func(*args)

            if not resp['message']:
                # XG requests will return None for a message if no message
                # string is passed in the raw response
                resp['message'] = ''

            for msg in success_msgs:
                if not resp['code'] and msg in resp['message']:
                    done = True
                    break

            self._fatal_error_code(resp)

        return resp

    def _send_cmd_and_verify(self, request_func, verify_func,
                             request_success_msgs, rargs=None, vargs=None):
        """Run an XG request function, retry if needed, and verify success.

        If the verification fails, then retry the request/verify
        cycle until both functions are successful, the request
        function returns a failure message, or the global request
        timeout is hit.

        This wrapper is meant to deal with backend requests that can
        fail for any variety of reasons, for instance, when the system
        is already busy handling other LUN requests.  It is also smart
        enough to give up if clustering is down (eg no HA available),
        there is no space left, or other "fatal" errors are returned
        (see _fatal_error_code() for a list of all known error
        conditions).

        Arguments:
            request_func        -- XG api method to call
            verify_func         -- function to call to verify request was
                                   completed successfully (eg for export)
            request_success_msg -- Success message expected from the backend
                                   for the request_func
            rargs               -- argument array to be passed to the
                                   request_func
            vargs               -- argument array to be passed to the
                                   verify_func

        Returns:
            The response dict from the last XG call.
        """
        resp = {}
        start = time.time()
        request_needed = True
        verify_needed = True

        if isinstance(request_success_msgs, basestring):
            request_success_msgs = [request_success_msgs]

        rargs = rargs if rargs else []
        vargs = vargs if vargs else []

        while request_needed or verify_needed:
            if time.time() - start >= self.config.request_timeout:
                raise exception.ViolinRequestRetryTimeout(
                    timeout=self.config.request_timeout)

            if request_needed:
                resp = request_func(*rargs)
                if not resp['message']:
                    # XG requests will return None for a message if no message
                    # string is passed int the raw response
                    resp['message'] = ''
                    for msg in request_success_msgs:
                        if not resp['code'] and msg in resp['message']:
                            # XG request func was completed
                            request_needed = False
                            break
                self._fatal_error_code(resp)

            elif verify_needed:
                success = verify_func(*vargs)
                if success:
                    # XG verify func was completed
                    verify_needed = False
                else:
                    # try sending the request again
                    request_needed = True

        return resp

    def _get_igroup(self, volume, connector):
        """Gets the igroup that should be used when configuring a volume.

        Arguments:
            volume -- volume object used to determine the igroup name

        Returns:
            igroup_name -- name of igroup (for configuring targets &
                           initiators)
        """
        # Use the connector's primary hostname and use that as the
        # name of the igroup.  The name must follow syntax rules
        # required by the array: "must contain only alphanumeric
        # characters, dashes, and underscores.  The first character
        # must be alphanumeric".
        #
        igroup_name = re.sub(r'[\W]', '_', connector['host'])

        # verify that the igroup has been created on the backend, and
        # if it doesn't exist, create it!
        #
        bn = "/vshare/config/igroup/%s" % igroup_name
        resp = self.vip.basic.get_node_values(bn)

        if not len(resp):
            self.vip.igroup.create_igroup(igroup_name)

        return igroup_name

    def _wait_for_export_config(self, volume_name, snapshot_name=None,
                                state=False):
        """Polls backend to verify volume's export configuration.

        XG sets/queries following a request to create or delete a lun
        export may fail on the backend if vshared is still processing
        the export action (or times out).  We can check whether it is
        done by polling the export binding for a lun to ensure it is
        created or deleted.

        This function will try to verify the creation or removal of
        export state on both gateway nodes of the array every 5
        seconds.

        Arguments:
            volume_name   -- name of volume
            snapshot_name -- name of volume's snapshot
            state         -- True to poll for existence, False for lack of

        Returns:
            True if the export state was correctly added or removed
            (depending on 'state' param)
        """
        if not snapshot_name:
            bn = "/vshare/config/export/container/%s/lun/%s" \
                % (self.container, volume_name)
        else:
            bn = "/vshare/config/export/snapshot/container/%s/lun/%s/snap/%s" \
                % (self.container, volume_name, snapshot_name)

        def _loop_func(state):
            status = [False, False]
            mg_conns = [self.mga, self.mgb]

            LOG.debug("Entering _wait_for_export_config loop: state=%s.",
                      state)

            for node_id in xrange(2):
                resp = mg_conns[node_id].basic.get_node_values(bn)
                if state and len(resp.keys()):
                    status[node_id] = True
                elif (not state) and (not len(resp.keys())):
                    status[node_id] = True

            if status[0] and status[1]:
                raise loopingcall.LoopingCallDone(retvalue=True)

        timer = loopingcall.FixedIntervalLoopingCall(_loop_func, state)
        success = timer.start(interval=5).wait()

        return success

    def _is_supported_vmos_version(self, version_string):
        """Check that the array s/w version is supported. """
        for pattern in VMOS_SUPPORTED_VERSION_PATTERNS:
            if re.match(pattern, version_string):
                LOG.info(_LI("Verified VMOS version %s is supported."),
                         version_string)
                return True
        return False

    def _fatal_error_code(self, response):
        """Raise an exception for certain errors in a XG response.

        Error codes are extracted from vdmd_mgmt.c.

        Arguments:
            response -- a response dict result from an XG request
        """
        # known non-fatal response codes:
        # 1024: 'lun deletion in progress, try again later'
        # 14032: 'lc_err_lock_busy'

        if response['code'] == 14000:
            # lc_generic_error
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14002:
            # lc_err_assertion_failed
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14004:
            # lc_err_not_found
            raise exception.ViolinBackendErrNotFound()
        elif response['code'] == 14005:
            # lc_err_exists
            raise exception.ViolinBackendErrExists()
        elif response['code'] == 14008:
            # lc_err_unexpected_arg
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14014:
            # lc_err_io_error
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14016:
            # lc_err_io_closed
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14017:
            # lc_err_io_timeout
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14021:
            # lc_err_unexpected_case
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14025:
            # lc_err_no_fs_space
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14035:
            # lc_err_range
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14036:
            # lc_err_invalid_param
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 14121:
            # lc_err_cancelled_err
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 512:
            # Not enough free space in container (vdmd bug)
            raise exception.ViolinBackendErr(message=response['message'])
        elif response['code'] == 1 and 'LUN ID conflict' \
                in response['message']:
            # lun id conflict while attempting to export
            raise exception.ViolinBackendErr(message=response['message'])
