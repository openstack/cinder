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
from cinder.i18n import _LE, _LI, _LW
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
        self.lio_initiator_iqns =\
            self.configuration.safe_get('lio_initiator_iqns')

        if self.lio_initiator_iqns is not None:
            LOG.warning(_LW("The lio_initiator_iqns option has been "
                            "deprecated and no longer has any effect."))

        self._verify_rtstool()

    def _get_target_chap_auth(self, context, iscsi_name):
        """Get the current chap auth username and password."""
        try:
            # 'iscsi_name': 'iqn.2010-10.org.openstack:volume-00000001'
            vol_id = iscsi_name.split(':volume-')[1]
            volume_info = self.db.volume_get(context, vol_id)
            # 'provider_auth': 'CHAP user_id password'
            if volume_info['provider_auth']:
                return tuple(volume_info['provider_auth'].split(' ', 3)[1:])
        except exception.NotFound:
            LOG.debug('Failed to get CHAP auth from DB for %s', vol_id)

    def _verify_rtstool(self):
        try:
            # This call doesn't need locking
            utils.execute('cinder-rtstool', 'verify')
        except (OSError, putils.ProcessExecutionError):
            LOG.error(_LE('cinder-rtstool is not installed correctly'))
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
            LOG.warning(_LW("Failed to save iscsi LIO configuration when "
                            "modifying volume id: %(vol_id)s."),
                        {'vol_id': vol_id})

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):
        # tid and lun are not used

        vol_id = name.split(':')[1]

        LOG.info(_LI('Creating iscsi_target for volume: %s'), vol_id)

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
            LOG.exception(_LE("Failed to create iscsi target for volume "
                              "id:%s."), vol_id)

            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (self.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_LE("Failed to create iscsi target for volume "
                          "id:%s."), vol_id)
            raise exception.NotFound()

        # We make changes persistent
        self._persist_configuration(vol_id)

        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_LI('Removing iscsi_target: %s'), vol_id)
        vol_uuid_name = vol_name
        iqn = '%s%s' % (self.iscsi_target_prefix, vol_uuid_name)

        try:
            self._execute('cinder-rtstool',
                          'delete',
                          iqn,
                          run_as_root=True)
        except putils.ProcessExecutionError:
            LOG.exception(_LE("Failed to remove iscsi target for volume "
                              "id:%s."), vol_id)
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
            LOG.exception(_LE("Failed to add initiator iqn %s to target"),
                          connector['initiator'])
            raise exception.ISCSITargetAttachFailed(
                volume_id=volume['id'])

        # We make changes persistent
        self._persist_configuration(volume['id'])

        iscsi_properties = self._get_iscsi_properties(volume,
                                                      connector.get(
                                                          'multipath'))

        return {
            'driver_volume_type': self.iscsi_protocol,
            'data': iscsi_properties
        }

    def terminate_connection(self, volume, connector, **kwargs):
        volume_iqn = volume['provider_location'].split(' ')[1]

        # Delete initiator iqns from target ACL
        try:
            self._execute('cinder-rtstool', 'delete-initiator',
                          volume_iqn,
                          connector['initiator'],
                          run_as_root=True)
        except putils.ProcessExecutionError:
            LOG.exception(_LE("Failed to delete initiator iqn %s to target."),
                          connector['initiator'])
            raise exception.ISCSITargetDetachFailed(volume_id=volume['id'])

        # We make changes persistent
        self._persist_configuration(volume['id'])
