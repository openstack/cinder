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
import textwrap
import time

from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_utils import fileutils

from cinder import exception
from cinder import utils
from cinder.volume.targets import iscsi

LOG = logging.getLogger(__name__)


class TgtAdm(iscsi.ISCSITarget):
    """Target object for block storage devices.

    Base class for target object, where target
    is data transport mechanism (target) specific calls.
    This includes things like create targets, attach, detach
    etc.
    """

    VOLUME_CONF = textwrap.dedent("""
                <target %(name)s>
                    backing-store %(path)s
                    driver %(driver)s
                    %(chap_auth)s
                    %(target_flags)s
                    write-cache %(write_cache)s
                </target>
                  """)

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
        LOG.warning('Attempting recreate of backing lun...')

        # Since we think the most common case of this is a dev busy
        # (create vol from snapshot) we're going to add a sleep here
        # this will hopefully give things enough time to stabilize
        # how long should we wait??  I have no idea, let's go big
        # and error on the side of caution
        time.sleep(10)

        (out, err) = (None, None)
        try:
            (out, err) = utils.execute('tgtadm', '--lld', 'iscsi',
                                       '--op', 'new', '--mode',
                                       'logicalunit', '--tid',
                                       tid, '--lun', '1', '-b',
                                       path, run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error("Failed recovery attempt to create "
                      "iscsi backing lun for Volume "
                      "ID:%(vol_id)s: %(e)s",
                      {'vol_id': name, 'e': e})
        finally:
            LOG.debug('StdOut from recreate backing lun: %s', out)
            LOG.debug('StdErr from recreate backing lun: %s', err)

    def _get_iscsi_target(self, context, vol_id):
        return 0

    def _get_target_and_lun(self, context, volume):
        lun = 1  # For tgtadm the controller is lun 0, dev starts at lun 1
        iscsi_target = 0  # NOTE(jdg): Not used by tgtadm
        return iscsi_target, lun

    @utils.retry(putils.ProcessExecutionError)
    def _do_tgt_update(self, name):
        (out, err) = utils.execute('tgt-admin', '--update', name,
                                   run_as_root=True)
        LOG.debug("StdOut from tgt-admin --update: %s", out)
        LOG.debug("StdErr from tgt-admin --update: %s", err)

    @utils.retry(exception.NotFound)
    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):

        # Note(jdg) tid and lun aren't used by TgtAdm but remain for
        # compatibility

        # NOTE(jdg): Remove this when we get to the bottom of bug: #1398078
        # for now, since we intermittently hit target already exists we're
        # adding some debug info to try and pinpoint what's going on
        (out, err) = utils.execute('tgtadm',
                                   '--lld',
                                   'iscsi',
                                   '--op',
                                   'show',
                                   '--mode',
                                   'target',
                                   run_as_root=True)
        LOG.debug("Targets prior to update: %s", out)
        fileutils.ensure_tree(self.volumes_dir)

        vol_id = name.split(':')[1]
        write_cache = self.configuration.get('iscsi_write_cache', 'on')
        driver = self.iscsi_protocol
        chap_str = ''

        if chap_auth is not None:
            chap_str = 'incominguser %s %s' % chap_auth

        target_flags = self.configuration.get('iscsi_target_flags', '')
        if target_flags:
            target_flags = 'bsoflags ' + target_flags

        volume_conf = self.VOLUME_CONF % {
            'name': name, 'path': path, 'driver': driver,
            'chap_auth': chap_str, 'target_flags': target_flags,
            'write_cache': write_cache}

        LOG.debug('Creating iscsi_target for Volume ID: %s', vol_id)
        volumes_dir = self.volumes_dir
        volume_path = os.path.join(volumes_dir, vol_id)

        if os.path.exists(volume_path):
            LOG.debug(('Persistence file already exists for volume, '
                       'found file at: %s'), volume_path)
        utils.robust_file_write(volumes_dir, vol_id, volume_conf)
        LOG.debug(('Created volume path %(vp)s,\n'
                   'content: %(vc)s'),
                  {'vp': volume_path, 'vc': volume_conf})

        old_persist_file = None
        old_name = kwargs.get('old_name', None)
        if old_name is not None:
            LOG.debug('Detected old persistence file for volume '
                      '%(vol)s at %(old_name)s',
                      {'vol': vol_id, 'old_name': old_name})
            old_persist_file = os.path.join(volumes_dir, old_name)

        try:
            # With the persistent tgts we create them
            # by creating the entry in the persist file
            # and then doing an update to get the target
            # created.

            self._do_tgt_update(name)
        except putils.ProcessExecutionError as e:
            if "target already exists" in e.stderr:
                # Adding the additional Warning message below for a clear
                # ER marker (Ref bug: #1398078).
                LOG.warning('Could not create target because '
                            'it already exists for volume: %s', vol_id)
                LOG.debug('Exception was: %s', e)

            else:
                LOG.error("Failed to create iscsi target for Volume "
                          "ID: %(vol_id)s: %(e)s",
                          {'vol_id': vol_id, 'e': e})

            # Don't forget to remove the persistent file we created
            os.unlink(volume_path)
            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

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
        LOG.debug("Targets after update: %s", out)

        iqn = '%s%s' % (self.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.warning("Failed to create iscsi target for Volume "
                        "ID: %(vol_id)s. It could be caused by problem "
                        "with concurrency. "
                        "Also please ensure your tgtd config "
                        "file contains 'include %(volumes_dir)s/*'",
                        {'vol_id': vol_id,
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

        if old_persist_file is not None:
            fileutils.delete_if_exists(old_persist_file)

        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info('Removing iscsi_target for Volume ID: %s', vol_id)
        vol_uuid_file = vol_name
        volume_path = os.path.join(self.volumes_dir, vol_uuid_file)
        if not os.path.exists(volume_path):
            LOG.warning('Volume path %s does not exist, '
                        'nothing to remove.', volume_path)
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
            non_fatal_errors = ("can't find the target",
                                "access control rule does not exist")

            if any(error in e.stderr for error in non_fatal_errors):
                LOG.warning("Failed target removal because target or "
                            "ACL's couldn't be found for iqn: %s.", iqn)
            else:
                LOG.error("Failed to remove iscsi target for Volume "
                          "ID: %(vol_id)s: %(e)s",
                          {'vol_id': vol_id, 'e': e})
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
                LOG.warning('Silent failure of target removal '
                            'detected, retry....')
                utils.execute('tgt-admin',
                              '--delete',
                              iqn,
                              run_as_root=True)
            except putils.ProcessExecutionError as e:
                LOG.error("Failed to remove iscsi target for Volume "
                          "ID: %(vol_id)s: %(e)s",
                          {'vol_id': vol_id, 'e': e})
                raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

        # NOTE(jdg): This *should* be there still but incase
        # it's not we don't care, so just ignore it if was
        # somehow deleted between entry of this method
        # and here
        if os.path.exists(volume_path):
            os.unlink(volume_path)
        else:
            LOG.debug('Volume path %s not found at end, '
                      'of remove_iscsi_target.', volume_path)
