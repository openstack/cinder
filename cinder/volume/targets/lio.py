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

from oslo_concurrency import processutils as putils
from oslo_log import log as logging

from cinder import exception
from cinder import utils
from cinder.volume.targets import iscsi


LOG = logging.getLogger(__name__)


class LioAdm(iscsi.ISCSITarget):
    """iSCSI target administration for LIO using python-rtslib."""
    def __init__(self, *args, **kwargs):
        super(LioAdm, self).__init__(*args, **kwargs)

        # FIXME(jdg): modify executor to use the cinder-rtstool
        self.iscsi_target_prefix =\
            self.configuration.safe_get('iscsi_target_prefix')

        self._verify_rtstool()

    def _verify_rtstool(self):
        try:
            # This call doesn't need locking
            utils.execute('cinder-rtstool', 'verify')
        except (OSError, putils.ProcessExecutionError):
            LOG.error('cinder-rtstool is not installed correctly')
            raise

    @staticmethod
    @utils.synchronized('lioadm', external=True)
    def _execute(*args, **kwargs):
        """Locked execution to prevent racing issues.

        Racing issues are derived from a bug in RTSLib:
            https://github.com/agrover/rtslib-fb/issues/36
        """
        return utils.execute(*args, **kwargs)

    def _get_target(self, iqn):
        (out, err) = self._execute('cinder-rtstool',
                                   'get-targets',
                                   run_as_root=True)
        lines = out.split('\n')
        for line in lines:
            if iqn in line:
                return line

        return None

    def _get_targets(self):
        (out, err) = self._execute('cinder-rtstool',
                                   'get-targets',
                                   run_as_root=True)
        return out

    def _get_iscsi_target(self, context, vol_id):
        return 0

    def _get_target_and_lun(self, context, volume):
        lun = 0  # For lio, the lun starts at lun 0.
        iscsi_target = 0  # NOTE: Not used by lio.
        return iscsi_target, lun

    def _persist_configuration(self, vol_id):
        try:
            self._execute('cinder-rtstool', 'save', run_as_root=True)

        # On persistence failure we don't raise an exception, as target has
        # been successfully created.
        except putils.ProcessExecutionError:
            LOG.warning("Failed to save iscsi LIO configuration when "
                        "modifying volume id: %(vol_id)s.",
                        {'vol_id': vol_id})

    def _restore_configuration(self):
        try:
            self._execute('cinder-rtstool', 'restore', run_as_root=True)

        # On persistence failure we don't raise an exception, as target has
        # been successfully created.
        except putils.ProcessExecutionError:
            LOG.warning("Failed to restore iscsi LIO configuration.")

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):
        # tid and lun are not used

        vol_id = name.split(':')[1]

        LOG.info('Creating iscsi_target for volume: %s', vol_id)

        chap_auth_userid = ""
        chap_auth_password = ""
        if chap_auth is not None:
            (chap_auth_userid, chap_auth_password) = chap_auth

        optional_args = []
        if 'portals_port' in kwargs:
            optional_args.append('-p%s' % kwargs['portals_port'])

        if 'portals_ips' in kwargs:
            optional_args.append('-a' + ','.join(kwargs['portals_ips']))

        try:
            command_args = ['cinder-rtstool',
                            'create',
                            path,
                            name,
                            chap_auth_userid,
                            chap_auth_password,
                            self.iscsi_protocol == 'iser'] + optional_args
            self._execute(*command_args, run_as_root=True)
        except putils.ProcessExecutionError:
            LOG.exception("Failed to create iscsi target for volume "
                          "id:%s.", vol_id)

            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (self.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error("Failed to create iscsi target for volume id:%s.",
                      vol_id)
            raise exception.NotFound()

        # We make changes persistent
        self._persist_configuration(vol_id)

        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info('Removing iscsi_target: %s', vol_id)
        vol_uuid_name = vol_name
        iqn = '%s%s' % (self.iscsi_target_prefix, vol_uuid_name)

        try:
            self._execute('cinder-rtstool',
                          'delete',
                          iqn,
                          run_as_root=True)
        except putils.ProcessExecutionError:
            LOG.exception("Failed to remove iscsi target for volume id:%s.",
                          vol_id)
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

        # We make changes persistent
        self._persist_configuration(vol_id)

    def initialize_connection(self, volume, connector):
        volume_iqn = volume['provider_location'].split(' ')[1]

        (auth_method, auth_user, auth_pass) = \
            volume['provider_auth'].split(' ', 3)

        # Add initiator iqns to target ACL
        try:
            self._execute('cinder-rtstool', 'add-initiator',
                          volume_iqn,
                          auth_user,
                          auth_pass,
                          connector['initiator'],
                          run_as_root=True)
        except putils.ProcessExecutionError:
            LOG.exception("Failed to add initiator iqn %s to target",
                          connector['initiator'])
            raise exception.ISCSITargetAttachFailed(
                volume_id=volume['id'])

        # We make changes persistent
        self._persist_configuration(volume['id'])

        return super(LioAdm, self).initialize_connection(volume, connector)

    def terminate_connection(self, volume, connector, **kwargs):
        if volume['provider_location'] is None:
            LOG.debug('No provider_location for volume %s.',
                      volume['id'])
            return

        volume_iqn = volume['provider_location'].split(' ')[1]

        # Delete initiator iqns from target ACL
        try:
            self._execute('cinder-rtstool', 'delete-initiator',
                          volume_iqn,
                          connector['initiator'],
                          run_as_root=True)
        except putils.ProcessExecutionError:
            LOG.exception(
                "Failed to delete initiator iqn %s from target.",
                connector['initiator'])
            raise exception.ISCSITargetDetachFailed(volume_id=volume['id'])

        # We make changes persistent
        self._persist_configuration(volume['id'])

    def ensure_export(self, context, volume, volume_path):
        """Recreate exports for logical volumes."""

        # Restore saved configuration file if no target exists.
        if not self._get_targets():
            LOG.info('Restoring iSCSI target from configuration file')
            self._restore_configuration()
            return

        LOG.info("Skipping ensure_export. Found existing iSCSI target.")
