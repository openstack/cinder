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


import os
import re
import time

from oslo_concurrency import processutils as putils
import six

from cinder import exception
from cinder.openstack.common import fileutils
from cinder.i18n import _, _LI, _LW, _LE
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume.targets import iscsi
from cinder.volume import utils as vutils

LOG = logging.getLogger(__name__)


class TgtAdm(iscsi.ISCSITarget):
    """Target object for block storage devices.

    Base class for target object, where target
    is data transport mechanism (target) specific calls.
    This includes things like create targets, attach, detach
    etc.
    """

    VOLUME_CONF = """
                <target %s>
                    backing-store %s
                    lld iscsi
                    write-cache %s
                </target>
                  """
    VOLUME_CONF_WITH_CHAP_AUTH = """
                                <target %s>
                                    backing-store %s
                                    lld iscsi
                                    %s
                                    write-cache %s
                                </target>
                                 """

    def __init__(self, *args, **kwargs):
        super(TgtAdm, self).__init__(*args, **kwargs)
        self.volumes_dir = self.configuration.safe_get('volumes_dir')

    def _get_target(self, iqn):
        (out, err) = utils.execute('tgt-admin', '--show', run_as_root=True)
        lines = out.split('\n')
        for line in lines:
            if iqn in line:
                parsed = line.split()
                tid = parsed[1]
                return tid[:-1]

        return None

    def _verify_backing_lun(self, iqn, tid):
        backing_lun = True
        capture = False
        target_info = []

        (out, err) = utils.execute('tgt-admin', '--show', run_as_root=True)
        lines = out.split('\n')

        for line in lines:
            if iqn in line and "Target %s" % tid in line:
                capture = True
            if capture:
                target_info.append(line)
            if iqn not in line and 'Target ' in line:
                capture = False

        if '        LUN: 1' not in target_info:
            backing_lun = False

        return backing_lun

    def _recreate_backing_lun(self, iqn, tid, name, path):
        LOG.warning(_LW('Attempting recreate of backing lun...'))

        # Since we think the most common case of this is a dev busy
        # (create vol from snapshot) we're going to add a sleep here
        # this will hopefully give things enough time to stabilize
        # how long should we wait??  I have no idea, let's go big
        # and error on the side of caution
        time.sleep(10)
        try:
            (out, err) = utils.execute('tgtadm', '--lld', 'iscsi',
                                       '--op', 'new', '--mode',
                                       'logicalunit', '--tid',
                                       tid, '--lun', '1', '-b',
                                       path, run_as_root=True)
            LOG.debug('StdOut from recreate backing lun: %s' % out)
            LOG.debug('StdErr from recreate backing lun: %s' % err)
        except putils.ProcessExecutionError as e:
            LOG.error(_LE("Failed to recover attempt to create "
                          "iscsi backing lun for volume "
                          "id:%(vol_id)s: %(e)s")
                      % {'vol_id': name, 'e': e})

    def _iscsi_location(self, ip, target, iqn, lun=None):
        return "%s:%s,%s %s %s" % (ip, self.configuration.iscsi_port,
                                   target, iqn, lun)

    def _get_iscsi_target(self, context, vol_id):
        return 0

    def _get_target_and_lun(self, context, volume):
        lun = 1  # For tgtadm the controller is lun 0, dev starts at lun 1
        iscsi_target = 0  # NOTE(jdg): Not used by tgtadm
        return iscsi_target, lun

    def _ensure_iscsi_targets(self, context, host):
        """Ensure that target ids have been created in datastore."""
        # NOTE(jdg): tgtadm doesn't use the iscsi_targets table
        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        host_iscsi_targets = self.db.iscsi_target_count_by_host(context,
                                                                host)
        if host_iscsi_targets >= self.configuration.iscsi_num_targets:
            return

        # NOTE(vish): Target ids start at 1, not 0.
        target_end = self.configuration.iscsi_num_targets + 1
        for target_num in xrange(1, target_end):
            target = {'host': host, 'target_num': target_num}
            self.db.iscsi_target_create_safe(context, target)

    def _get_target_chap_auth(self, name):
        volumes_dir = self.volumes_dir
        vol_id = name.split(':')[1]
        volume_path = os.path.join(volumes_dir, vol_id)

        try:
            with open(volume_path, 'r') as f:
                volume_conf = f.read()
        except Exception as e:
            LOG.debug('Failed to open config for %(vol_id)s: %(e)s'
                      % {'vol_id': vol_id, 'e': six.text_type(e)})
            return None

        m = re.search('incominguser (\w+) (\w+)', volume_conf)
        if m:
            return (m.group(1), m.group(2))
        LOG.debug('Failed to find CHAP auth from config for %s' % vol_id)
        return None

    def ensure_export(self, context, volume, volume_path):
        chap_auth = None
        old_name = None

        # FIXME (jdg): This appears to be broken in existing code
        # we recreate the iscsi target but we pass in None
        # for CHAP, so we just recreated without CHAP even if
        # we had it set on initial create

        iscsi_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                               volume['name'])
        iscsi_write_cache = self.configuration.get('iscsi_write_cache', 'on')
        self.create_iscsi_target(
            iscsi_name,
            1, 0, volume_path,
            chap_auth, check_exit_code=False,
            old_name=old_name,
            iscsi_write_cache=iscsi_write_cache)

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):
        # Note(jdg) tid and lun aren't used by TgtAdm but remain for
        # compatibility
        fileutils.ensure_tree(self.volumes_dir)

        vol_id = name.split(':')[1]
        write_cache = kwargs.get('iscsi_write_cache', 'on')
        if chap_auth is None:
            volume_conf = self.VOLUME_CONF % (name, path, write_cache)
        else:
            chap_str = re.sub('^IncomingUser ', 'incominguser ', chap_auth)
            volume_conf = self.VOLUME_CONF_WITH_CHAP_AUTH % (name,
                                                             path, chap_str,
                                                             write_cache)
        LOG.info(_LI('Creating iscsi_target for: %s') % vol_id)
        volumes_dir = self.volumes_dir
        volume_path = os.path.join(volumes_dir, vol_id)

        f = open(volume_path, 'w+')
        f.write(volume_conf)
        f.close()
        LOG.debug(('Created volume path %(vp)s,\n'
                   'content: %(vc)s')
                  % {'vp': volume_path, 'vc': volume_conf})

        old_persist_file = None
        old_name = kwargs.get('old_name', None)
        if old_name is not None:
            old_persist_file = os.path.join(volumes_dir, old_name)

        try:
            # with the persistent tgts we create them
            # by creating the entry in the persist file
            # and then doing an update to get the target
            # created.
            (out, err) = utils.execute('tgt-admin', '--update', name,
                                       run_as_root=True)
            LOG.debug("StdOut from tgt-admin --update: %s", out)
            LOG.debug("StdErr from tgt-admin --update: %s", err)

            # Grab targets list for debug
            # Consider adding a check for lun 0 and 1 for tgtadm
            # before considering this as valid
            (out, err) = utils.execute('tgtadm',
                                       '--lld',
                                       'iscsi',
                                       '--op',
                                       'show',
                                       '--mode',
                                       'target',
                                       run_as_root=True)
            LOG.debug("Targets after update: %s" % out)
        except putils.ProcessExecutionError as e:
            if "target already exists" in e.stderr:
                LOG.warning(_LW('Could not create target because '
                                'it already exists for volume: %s'), vol_id)
                # NOTE(jdg): We've run into issues where the command being sent
                # was not correct. This may be related to using the executor
                # directly? Even though the above call specified is a show
                # we see a new being called instead...

                # Adding the additional Warning message above for a clear
                # ER marker (Ref bug: #1398078).
                pass
            else:
                LOG.warning(_LW("Failed to create iscsi target for volume "
                            "id:%(vol_id)s: %(e)s")
                            % {'vol_id': vol_id, 'e': e})

                # Don't forget to remove the persistent file we created
                os.unlink(volume_path)
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (self.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_LE("Failed to create iscsi target for volume "
                          "id:%(vol_id)s. Please ensure your tgtd config file "
                          "contains 'include %(volumes_dir)s/*'") % {
                      'vol_id': vol_id,
                      'volumes_dir': volumes_dir, })
            raise exception.NotFound()

        # NOTE(jdg): Sometimes we have some issues with the backing lun
        # not being created, believe this is due to a device busy
        # or something related, so we're going to add some code
        # here that verifies the backing lun (lun 1) was created
        # and we'll try and recreate it if it's not there
        if not self._verify_backing_lun(iqn, tid):
            try:
                self._recreate_backing_lun(iqn, tid, name, path)
            except putils.ProcessExecutionError:
                os.unlink(volume_path)
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

            # Finally check once more and if no go, fail and punt
            if not self._verify_backing_lun(iqn, tid):
                os.unlink(volume_path)
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        if old_persist_file is not None and os.path.exists(old_persist_file):
            os.unlink(old_persist_file)

        return tid

    def create_export(self, context, volume, volume_path):
        """Creates an export for a logical volume."""
        iscsi_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                               volume['name'])
        iscsi_target, lun = self._get_target_and_lun(context, volume)
        chap_username = vutils.generate_username()
        chap_password = vutils.generate_password()
        chap_auth = self._iscsi_authentication('IncomingUser', chap_username,
                                               chap_password)
        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        iscsi_write_cache = self.configuration.get('iscsi_write_cache', 'on')
        tid = self.create_iscsi_target(iscsi_name,
                                       iscsi_target,
                                       0,
                                       volume_path,
                                       chap_auth,
                                       iscsi_write_cache=iscsi_write_cache)
        data = {}
        data['location'] = self._iscsi_location(
            self.configuration.iscsi_ip_address, tid, iscsi_name, lun)
        LOG.debug('Set provider_location to: %s', data['location'])
        data['auth'] = self._iscsi_authentication(
            'CHAP', chap_username, chap_password)
        return data

    def remove_export(self, context, volume):
        try:
            iscsi_target = self._get_iscsi_target(context, volume['id'])
        except exception.NotFound:
            LOG.info(_LI("Skipping remove_export. No iscsi_target "
                         "provisioned for volume: %s"), volume['id'])
            return
        try:

            # NOTE: provider_location may be unset if the volume hasn't
            # been exported
            location = volume['provider_location'].split(' ')
            iqn = location[1]

            # ietadm show will exit with an error
            # this export has already been removed
            self.show_target(iscsi_target, iqn=iqn)

        except Exception:
            LOG.info(_LI("Skipping remove_export. No iscsi_target "
                         "is presently exported for volume: %s"), volume['id'])
            return

        self.remove_iscsi_target(iscsi_target, 0, volume['id'], volume['name'])

    def initialize_connection(self, volume, connector):
        iscsi_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_LI('Removing iscsi_target for: %s') % vol_id)
        vol_uuid_file = vol_name
        volume_path = os.path.join(self.volumes_dir, vol_uuid_file)
        if not os.path.exists(volume_path):
            LOG.warning(_LW('Volume path %s does not exist, '
                            'nothing to remove.') % volume_path)
            return

        if os.path.isfile(volume_path):
            iqn = '%s%s' % (self.iscsi_target_prefix,
                            vol_uuid_file)
        else:
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)
        try:
            # NOTE(vish): --force is a workaround for bug:
            #             https://bugs.launchpad.net/cinder/+bug/1159948
            utils.execute('tgt-admin',
                          '--force',
                          '--delete',
                          iqn,
                          run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_LE("Failed to remove iscsi target for volume "
                          "id:%(vol_id)s: %(e)s")
                      % {'vol_id': vol_id, 'e': e})
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)
        # NOTE(jdg): There's a bug in some versions of tgt that
        # will sometimes fail silently when using the force flag
        #    https://bugs.launchpad.net/ubuntu/+source/tgt/+bug/1305343
        # For now work-around by checking if the target was deleted,
        # if it wasn't, try again without the force.

        # This will NOT do any good for the case of mutliple sessions
        # which the force was aded for but it will however address
        # the cases pointed out in bug:
        #    https://bugs.launchpad.net/cinder/+bug/1304122
        if self._get_target(iqn):
            try:
                LOG.warning(_LW('Silent failure of target removal '
                                'detected, retry....'))
                utils.execute('tgt-admin',
                              '--delete',
                              iqn,
                              run_as_root=True)
            except putils.ProcessExecutionError as e:
                LOG.error(_LE("Failed to remove iscsi target for volume "
                              "id:%(vol_id)s: %(e)s")
                          % {'vol_id': vol_id, 'e': e})
                raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

        # NOTE(jdg): This *should* be there still but incase
        # it's not we don't care, so just ignore it if was
        # somehow deleted between entry of this method
        # and here
        if os.path.exists(volume_path):
            os.unlink(volume_path)
        else:
            LOG.debug('Volume path %s not found at end, '
                      'of remove_iscsi_target.' % volume_path)

    def show_target(self, tid, iqn=None, **kwargs):
        if iqn is None:
            raise exception.InvalidParameterValue(
                err=_('valid iqn needed for show_target'))

        tid = self._get_target(iqn)
        if tid is None:
            raise exception.NotFound()
