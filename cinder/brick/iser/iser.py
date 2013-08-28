# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Mellanox Technologies. All rights reserved.
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
Helper code for the iSER volume driver.

"""


import os

from oslo.config import cfg

from cinder.brick import exception
from cinder.brick import executor
from cinder.openstack.common import fileutils
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils

LOG = logging.getLogger(__name__)

iser_helper_opt = [cfg.StrOpt('iser_helper',
                              default='tgtadm',
                              help='iser target user-land tool to use'),
                   cfg.StrOpt('volumes_dir',
                              default='$state_path/volumes',
                              help='Volume configuration file storage '
                                   'directory'
                              )
                   ]

CONF = cfg.CONF
CONF.register_opts(iser_helper_opt)


class TargetAdmin(executor.Executor):
    """iSER target administration.

    Base class for iSER target admin helpers.
    """

    def __init__(self, cmd, root_helper, execute):
        super(TargetAdmin, self).__init__(root_helper, execute=execute)
        self._cmd = cmd

    def _run(self, *args, **kwargs):
        self._execute(self._cmd, *args, run_as_root=True, **kwargs)

    def create_iser_target(self, name, tid, lun, path,
                           chap_auth=None, **kwargs):
        """Create a iSER target and logical unit."""
        raise NotImplementedError()

    def remove_iser_target(self, tid, lun, vol_id, vol_name, **kwargs):
        """Remove a iSER target and logical unit."""
        raise NotImplementedError()

    def _new_target(self, name, tid, **kwargs):
        """Create a new iSER target."""
        raise NotImplementedError()

    def _delete_target(self, tid, **kwargs):
        """Delete a target."""
        raise NotImplementedError()

    def show_target(self, tid, iqn=None, **kwargs):
        """Query the given target ID."""
        raise NotImplementedError()

    def _new_logicalunit(self, tid, lun, path, **kwargs):
        """Create a new LUN on a target using the supplied path."""
        raise NotImplementedError()

    def _delete_logicalunit(self, tid, lun, **kwargs):
        """Delete a logical unit from a target."""
        raise NotImplementedError()


class TgtAdm(TargetAdmin):
    """iSER target administration using tgtadm."""

    def __init__(self, root_helper, execute=putils.execute):
        super(TgtAdm, self).__init__('tgtadm', root_helper, execute)

    def _get_target(self, iqn):
        (out, err) = self._execute('tgt-admin', '--show', run_as_root=True)
        lines = out.split('\n')
        for line in lines:
            if iqn in line:
                parsed = line.split()
                tid = parsed[1]
                return tid[:-1]

        return None

    def create_iser_target(self, name, tid, lun, path,
                           chap_auth=None, **kwargs):
        # Note(jdg) tid and lun aren't used by TgtAdm but remain for
        # compatibility

        fileutils.ensure_tree(CONF.volumes_dir)

        vol_id = name.split(':')[1]
        if chap_auth is None:
            volume_conf = """
                <target %s>
                    driver iser
                    backing-store %s
                </target>
            """ % (name, path)
        else:
            volume_conf = """
                <target %s>
                    driver iser
                    backing-store %s
                    %s
                </target>
            """ % (name, path, chap_auth)

        LOG.info(_('Creating iser_target for: %s') % vol_id)
        volumes_dir = CONF.volumes_dir
        volume_path = os.path.join(volumes_dir, vol_id)

        f = open(volume_path, 'w+')
        f.write(volume_conf)
        f.close()

        old_persist_file = None
        old_name = kwargs.get('old_name', None)
        if old_name is not None:
            old_persist_file = os.path.join(volumes_dir, old_name)

        try:
            (out, err) = self._execute('tgt-admin',
                                       '--update',
                                       name,
                                       run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to create iser target for volume "
                        "id:%(vol_id)s: %(e)s")
                      % {'vol_id': vol_id, 'e': str(e)})

            #Don't forget to remove the persistent file we created
            os.unlink(volume_path)
            raise exception.ISERTargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (CONF.iser_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_("Failed to create iser target for volume "
                        "id:%(vol_id)s. Please ensure your tgtd config file "
                        "contains 'include %(volumes_dir)s/*'") %
                      {'vol_id': vol_id, 'volumes_dir': volumes_dir})
            raise exception.NotFound()

        if old_persist_file is not None and os.path.exists(old_persist_file):
            os.unlink(old_persist_file)

        return tid

    def remove_iser_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_('Removing iser_target for: %s') % vol_id)
        vol_uuid_file = vol_name
        volume_path = os.path.join(CONF.volumes_dir, vol_uuid_file)
        if os.path.isfile(volume_path):
            iqn = '%s%s' % (CONF.iser_target_prefix,
                            vol_uuid_file)
        else:
            raise exception.ISERTargetRemoveFailed(volume_id=vol_id)
        try:
            # NOTE(vish): --force is a workaround for bug:
            #             https://bugs.launchpad.net/cinder/+bug/1159948
            self._execute('tgt-admin',
                          '--force',
                          '--delete',
                          iqn,
                          run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to remove iser target for volume "
                        "id:%(vol_id)s: %(e)s")
                      % {'vol_id': vol_id, 'e': str(e)})
            raise exception.ISERTargetRemoveFailed(volume_id=vol_id)

        os.unlink(volume_path)

    def show_target(self, tid, iqn=None, **kwargs):
        if iqn is None:
            raise exception.InvalidParameterValue(
                err=_('valid iqn needed for show_target'))

        tid = self._get_target(iqn)
        if tid is None:
            raise exception.NotFound()


class FakeIserHelper(object):

    def __init__(self):
        self.tid = 1

    def set_execute(self, execute):
        self._execute = execute

    def create_iser_target(self, *args, **kwargs):
        self.tid += 1
        return self.tid


def get_target_admin(root_helper):
    if CONF.iser_helper == 'fake':
        return FakeIserHelper()
    else:
        return TgtAdm(root_helper)
