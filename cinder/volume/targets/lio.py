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

from cinder import exception
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils
from cinder.volume.targets.tgt import TgtAdm

LOG = logging.getLogger(__name__)


class LioAdm(TgtAdm):
    """iSCSI target administration for LIO using python-rtslib."""
    def __init__(self, *args, **kwargs):
        super(LioAdm, self).__init__(*args, **kwargs)

        # FIXME(jdg): modify executor to use the cinder-rtstool
        self.iscsi_target_prefix =\
            self.configuration.safe_get('iscsi_target_prefix')
        self.lio_initiator_iqns =\
            self.configuration.safe_get('lio_initiator_iqns')
        self._verify_rtstool()

    def remove_export(self, context, volume):
        try:
            iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                               volume['id'])
        except exception.NotFound:
            LOG.info(_("Skipping remove_export. No iscsi_target "
                       "provisioned for volume: %s"), volume['id'])
            return

        self.remove_iscsi_target(iscsi_target, 0, volume['id'], volume['name'])

    def ensure_export(self, context, volume,
                      iscsi_name, volume_path,
                      volume_group, config):
        try:
            volume_info = self.db.volume_get(context, volume['id'])
            (auth_method,
             auth_user,
             auth_pass) = volume_info['provider_auth'].split(' ', 3)
            chap_auth = self._iscsi_authentication(auth_method,
                                                   auth_user,
                                                   auth_pass)
        except exception.NotFound:
            LOG.debug(("volume_info:%s"), volume_info)
            LOG.info(_("Skipping ensure_export. No iscsi_target "
                       "provision for volume: %s"), volume['id'])

        iscsi_target = 1

        self.create_iscsi_target(iscsi_name, iscsi_target, 0, volume_path,
                                 chap_auth, check_exit_code=False)

    def _verify_rtstool(self):
        try:
            self._execute('cinder-rtstool', 'verify')
        except (OSError, putils.ProcessExecutionError):
            LOG.error(_('cinder-rtstool is not installed correctly'))
            raise

    def _get_target(self, iqn):
        (out, err) = self._execute('cinder-rtstool',
                                   'get-targets',
                                   run_as_root=True)
        lines = out.split('\n')
        for line in lines:
            if iqn in line:
                return line

        return None

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):
        # tid and lun are not used

        vol_id = name.split(':')[1]

        LOG.info(_('Creating iscsi_target for volume: %s') % vol_id)

        # rtstool requires chap_auth, but unit tests don't provide it
        chap_auth_userid = 'test_id'
        chap_auth_password = 'test_pass'

        if chap_auth is not None:
            (chap_auth_userid, chap_auth_password) = chap_auth.split(' ')[1:]

        extra_args = []
        if self.lio_initiator_iqns:
            extra_args.append(self.lio_initiator_iqns)

        try:
            command_args = ['cinder-rtstool',
                            'create',
                            path,
                            name,
                            chap_auth_userid,
                            chap_auth_password]
            if extra_args:
                command_args.extend(extra_args)
            self._execute(*command_args, run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to create iscsi target for volume "
                        "id:%s.") % vol_id)
            LOG.error(_("%s") % e)

            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (self.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_("Failed to create iscsi target for volume "
                        "id:%s.") % vol_id)
            raise exception.NotFound()

        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_('Removing iscsi_target: %s') % vol_id)
        vol_uuid_name = vol_name
        iqn = '%s%s' % (self.iscsi_target_prefix, vol_uuid_name)

        try:
            self._execute('cinder-rtstool',
                          'delete',
                          iqn,
                          run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to remove iscsi target for volume "
                        "id:%s.") % vol_id)
            LOG.error(_("%s") % e)
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

    def show_target(self, tid, iqn=None, **kwargs):
        if iqn is None:
            raise exception.InvalidParameterValue(
                err=_('valid iqn needed for show_target'))

        tid = self._get_target(iqn)
        if tid is None:
            raise exception.NotFound()

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
            LOG.error(_("Failed to add initiator iqn %s to target") %
                      connector['initiator'])
            raise exception.ISCSITargetAttachFailed(
                volume_id=volume['id'])

        iscsi_properties = self._get_iscsi_properties(volume)

        # FIXME(jdg): For LIO the target_lun is 0, other than that all data
        # is the same as it is for tgtadm, just modify it here
        iscsi_properties['target_lun'] = 0

        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }
