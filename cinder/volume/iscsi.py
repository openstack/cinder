# Copyright (c) 2013 Mirantis, Inc.
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

import os
import re

from cinder.brick.iscsi import iscsi
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils
from cinder.volume import utils

LOG = logging.getLogger(__name__)


class _ExportMixin(object):

    def __init__(self, *args, **kwargs):
        self.db = kwargs.pop('db', None)
        super(_ExportMixin, self).__init__(*args, **kwargs)

    def create_export(self, context, volume, volume_path, conf):
        """Creates an export for a logical volume."""
        iscsi_name = "%s%s" % (conf.iscsi_target_prefix,
                               volume['name'])
        max_targets = conf.safe_get('iscsi_num_targets')
        (iscsi_target, lun) = self._get_target_and_lun(context,
                                                       volume,
                                                       max_targets)

        current_chap_auth = self._get_target_chap_auth(iscsi_name)
        if current_chap_auth:
            (chap_username, chap_password) = current_chap_auth
        else:
            chap_username = utils.generate_username()
            chap_password = utils.generate_password()
        chap_auth = self._iscsi_authentication('IncomingUser',
                                               chap_username,
                                               chap_password)
        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        tid = self.create_iscsi_target(iscsi_name,
                                       iscsi_target,
                                       0,
                                       volume_path,
                                       chap_auth,
                                       write_cache=
                                       conf.iscsi_write_cache)
        data = {}
        data['location'] = self._iscsi_location(
            conf.iscsi_ip_address, tid, iscsi_name, conf.iscsi_port, lun)
        data['auth'] = self._iscsi_authentication(
            'CHAP', chap_username, chap_password)
        return data

    def remove_export(self, context, volume):
        try:
            iscsi_target = self._get_iscsi_target(context, volume['id'])
        except exception.NotFound:
            LOG.info(_("Skipping remove_export. No iscsi_target "
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
            LOG.info(_("Skipping remove_export. No iscsi_target "
                       "is presently exported for volume: %s"), volume['id'])
            return

        self.remove_iscsi_target(iscsi_target, 0, volume['id'], volume['name'])

    def ensure_export(self, context, volume, iscsi_name, volume_path,
                      vg_name, conf, old_name=None):
        iscsi_target = self._get_target_for_ensure_export(context,
                                                          volume['id'])
        if iscsi_target is None:
            LOG.info(_("Skipping remove_export. No iscsi_target "
                       "provisioned for volume: %s"), volume['id'])
            return
        chap_auth = None
        # Check for https://bugs.launchpad.net/cinder/+bug/1065702
        old_name = None
        if (volume['provider_location'] is not None and
                volume['name'] not in volume['provider_location']):

            msg = _('Detected inconsistency in provider_location id')
            LOG.debug('%s', msg)
            old_name = self._fix_id_migration(context, volume)
            if 'in-use' in volume['status']:
                old_name = None
        self.create_iscsi_target(iscsi_name, iscsi_target, 0, volume_path,
                                 chap_auth, check_exit_code=False,
                                 old_name=old_name,
                                 write_cache=conf.iscsi_write_cache)

    def _ensure_iscsi_targets(self, context, host, max_targets):
        """Ensure that target ids have been created in datastore."""
        # NOTE(jdg): tgtadm doesn't use the iscsi_targets table
        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        host_iscsi_targets = self.db.iscsi_target_count_by_host(context,
                                                                host)
        if host_iscsi_targets >= max_targets:
            return

        # NOTE(vish): Target ids start at 1, not 0.
        target_end = max_targets + 1
        for target_num in xrange(1, target_end):
            target = {'host': host, 'target_num': target_num}
            self.db.iscsi_target_create_safe(context, target)

    def _get_target_for_ensure_export(self, context, volume_id):
        try:
            iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                               volume_id)
            return iscsi_target
        except exception.NotFound:
            return None

    def _get_target_and_lun(self, context, volume, max_targets):
        lun = 0
        self._ensure_iscsi_targets(context, volume['host'], max_targets)
        iscsi_target = self.db.volume_allocate_iscsi_target(context,
                                                            volume['id'],
                                                            volume['host'])
        return iscsi_target, lun

    def _get_iscsi_target(self, context, vol_id):
        return self.db.volume_get_iscsi_target_num(context, vol_id)

    def _iscsi_authentication(self, chap, name, password):
        return "%s %s %s" % (chap, name, password)

    def _iscsi_location(self, ip, target, iqn, port, lun=None):
        return "%s:%s,%s %s %s" % (ip, port,
                                   target, iqn, lun)

    def _fix_id_migration(self, context, volume, vg_name):
        """Fix provider_location and dev files to address bug 1065702.

        For volumes that the provider_location has NOT been updated
        and are not currently in-use we'll create a new iscsi target
        and remove the persist file.

        If the volume is in-use, we'll just stick with the old name
        and when detach is called we'll feed back into ensure_export
        again if necessary and fix things up then.

        Details at: https://bugs.launchpad.net/cinder/+bug/1065702
        """

        model_update = {}
        pattern = re.compile(r":|\s")
        fields = pattern.split(volume['provider_location'])
        old_name = fields[3]

        volume['provider_location'] = \
            volume['provider_location'].replace(old_name, volume['name'])
        model_update['provider_location'] = volume['provider_location']

        self.db.volume_update(context, volume['id'], model_update)

        start = os.getcwd()

        os.chdir('/dev/%s' % vg_name)

        try:
            (out, err) = self._execute('readlink', old_name)
        except putils.ProcessExecutionError:
            link_path = '/dev/%s/%s' % (vg_name,
                                        old_name)
            LOG.debug('Symbolic link %s not found' % link_path)
            os.chdir(start)
            return

        rel_path = out.rstrip()
        self._execute('ln',
                      '-s',
                      rel_path, volume['name'],
                      run_as_root=True)
        os.chdir(start)
        return old_name


class TgtAdm(_ExportMixin, iscsi.TgtAdm):

    def _get_target_and_lun(self, context, volume, max_targets):
        lun = 1  # For tgtadm the controller is lun 0, dev starts at lun 1
        iscsi_target = 0  # NOTE(jdg): Not used by tgtadm
        return iscsi_target, lun

    def _get_iscsi_target(self, context, vol_id):
        return 0

    def _get_target_for_ensure_export(self, context, volume_id):
        return 1


class FakeIscsiHelper(_ExportMixin, iscsi.FakeIscsiHelper):

    def create_export(self, context, volume, volume_path, conf):
        return {
            'location': "fake_location",
            'auth': "fake_auth"
        }

    def remove_export(self, context, volume):
        pass

    def ensure_export(self, context, volume, iscsi_name, volume_path,
                      vg_name, conf, old_name=None):
        pass


class LioAdm(_ExportMixin, iscsi.LioAdm):

    def remove_export(self, context, volume):
        try:
            iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                               volume['id'])
        except exception.NotFound:
            LOG.info(_("Skipping remove_export. No iscsi_target "
                       "provisioned for volume: %s"), volume['id'])
            return

        self.remove_iscsi_target(iscsi_target, 0, volume['id'], volume['name'])

    def ensure_export(self, context, volume, iscsi_name, volume_path,
                      vg_name, conf, old_name=None):
        try:
            volume_info = self.db.volume_get(context, volume['id'])
            (auth_method,
             auth_user,
             auth_pass) = volume_info['provider_auth'].split(' ', 3)
            chap_auth = self._iscsi_authentication(auth_method,
                                                   auth_user,
                                                   auth_pass)
        except exception.NotFound:
            LOG.debug("volume_info:%s", volume_info)
            LOG.info(_("Skipping ensure_export. No iscsi_target "
                       "provision for volume: %s"), volume['id'])

        iscsi_target = 1

        self.create_iscsi_target(iscsi_name, iscsi_target, 0, volume_path,
                                 chap_auth, check_exit_code=False)


class IetAdm(_ExportMixin, iscsi.IetAdm):
    pass


class ISERTgtAdm(_ExportMixin, iscsi.ISERTgtAdm):
    def _get_target_and_lun(self, context, volume, max_targets):
        lun = 1  # For tgtadm the controller is lun 0, dev starts at lun 1
        iscsi_target = 0  # NOTE(jdg): Not used by tgtadm
        return iscsi_target, lun

    def _get_iscsi_target(self, context, vol_id):
        return 0

    def _get_target_for_ensure_export(self, context, volume_id):
        return 1
