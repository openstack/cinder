# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2012 Alyseo.
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
Desc    : Driver to store volumes on Coraid Appliances.
Require : Coraid EtherCloud ESM, Coraid VSX and Coraid SRX.
Author  : Jean-Baptiste RANSY <openstack@alyseo.com>
Contrib : Larry Matter <support@coraid.com>
"""

import cookielib
import os
import time
import urllib2

from oslo.config import cfg

from cinder import context
from cinder import exception
from cinder import flags
from cinder.openstack.common import jsonutils
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS
coraid_opts = [
    cfg.StrOpt('coraid_esm_address',
               default='',
               help='IP address of Coraid ESM'),
    cfg.StrOpt('coraid_user',
               default='admin',
               help='User name to connect to Coraid ESM'),
    cfg.StrOpt('coraid_group',
               default=False,
               help='Group name of coraid_user (must have admin privilege)'),
    cfg.StrOpt('coraid_password',
               default='password',
               help='Password to connect to Coraid ESM'),
    cfg.StrOpt('coraid_repository_key',
               default='coraid_repository',
               help='Volume Type key name to store ESM Repository Name'),
]
FLAGS.register_opts(coraid_opts)


class CoraidException(Exception):
    def __init__(self, message=None, error=None):
        super(CoraidException, self).__init__(message, error)

    def __str__(self):
        return '%s: %s' % self.args


class CoraidRESTException(CoraidException):
    pass


class CoraidESMException(CoraidException):
    pass


class CoraidRESTClient(object):
    """Executes volume driver commands on Coraid ESM EtherCloud Appliance."""

    def __init__(self, ipaddress, user, group, password):
        self.url = "https://%s:8443/" % ipaddress
        self.user = user
        self.group = group
        self.password = password
        self.session = False
        self.cookiejar = cookielib.CookieJar()
        self.urlOpener = urllib2.build_opener(
            urllib2.HTTPCookieProcessor(self.cookiejar))
        LOG.debug(_('Running with CoraidDriver for ESM EtherCLoud'))

    def _login(self):
        """Login and Session Handler."""
        if not self.session or self.session < time.time():
            url = ('admin?op=login&username=%s&password=%s' %
                   (self.user, self.password))
            data = 'Login'
            reply = self._esm(url, data)
            if reply.get('state') == 'adminSucceed':
                self.session = time.time() + 1100
                msg = _('Update session cookie %(session)s')
                LOG.debug(msg % dict(session=self.session))
                self._set_group(reply)
                return True
            else:
                errmsg = reply.get('message', '')
                msg = _('Message : %(message)s')
                raise CoraidESMException(msg % dict(message=errmsg))
        return True

    def _set_group(self, reply):
        """Set effective group."""
        if self.group:
            group = self.group
            groupId = self._get_group_id(group, reply)
            if groupId:
                url = ('admin?op=setRbacGroup&groupId=%s' % (groupId))
                data = 'Group'
                reply = self._esm(url, data)
                if reply.get('state') == 'adminSucceed':
                    return True
                else:
                    errmsg = reply.get('message', '')
                    msg = _('Error while trying to set group: %(message)s')
                    raise CoraidRESTException(msg % dict(message=errmsg))
            else:
                msg = _('Unable to find group: %(group)s')
                raise CoraidESMException(msg % dict(group=group))
        return True

    def _get_group_id(self, groupName, loginResult):
        """Map group name to group ID."""
        # NOTE(lmatter): All other groups are under the admin group
        fullName = "admin group:%s" % groupName
        groupId = False
        for kid in loginResult['values']:
            fullPath = kid['fullPath']
            if fullPath == fullName:
                return kid['groupId']
        return False

    def _esm(self, url=False, data=None):
        """
        _esm represent the entry point to send requests to ESM Appliance.
        Send the HTTPS call, get response in JSON
        convert response into Python Object and return it.
        """
        if url:
            url = self.url + url

            req = urllib2.Request(url, data)

            try:
                res = self.urlOpener.open(req).read()
            except Exception:
                raise CoraidRESTException(_('ESM urlOpen error'))

            try:
                res_json = jsonutils.loads(res)
            except Exception:
                raise CoraidRESTException(_('JSON Error'))

            return res_json
        else:
            raise CoraidRESTException(_('Request without URL'))

    def _configure(self, data):
        """In charge of all commands into 'configure'."""
        self._login()
        url = 'configure'
        LOG.debug(_('Configure data : %s'), data)
        response = self._esm(url, data)
        LOG.debug(_("Configure response : %s"), response)
        if response:
            if response.get('configState') == 'completedSuccessfully':
                return True
            else:
                errmsg = response.get('message', '')
                msg = _('Message : %(message)s')
                raise CoraidESMException(msg % dict(message=errmsg))
        return False

    def _get_volume_info(self, lvname):
        """Fetch information for a given Volume or Snapshot."""
        self._login()
        url = 'fetch?shelf=cms&orchStrRepo&lv=%s' % (lvname)
        response = self._esm(url)

        items = []
        for cmd, reply in response:
            if len(reply['reply']) != 0:
                items.append(reply['reply'])

        volume_info = False
        for item in items[0]:
            if item['lv']['name'] == lvname:
                volume_info = {
                    "pool": item['lv']['containingPool'],
                    "repo": item['repoName'],
                    "vsxidx": item['lv']['lunIndex'],
                    "index": item['lv']['lvStatus']['exportedLun']['lun'],
                    "shelf": item['lv']['lvStatus']['exportedLun']['shelf']}

        if volume_info:
            return volume_info
        else:
            msg = _('Informtion about Volume %(volname)s not found')
            raise CoraidESMException(msg % dict(volname=volume_name))

    def _get_lun_address(self, volume_name):
        """Return AoE Address for a given Volume."""
        volume_info = self._get_volume_info(volume_name)
        shelf = volume_info['shelf']
        lun = volume_info['index']
        return {'shelf': shelf, 'lun': lun}

    def create_lun(self, volume_name, volume_size, repository):
        """Create LUN on Coraid Backend Storage."""
        data = '[{"addr":"cms","data":"{' \
               '\\"servers\\":[\\"\\"],' \
               '\\"repoName\\":\\"%s\\",' \
               '\\"size\\":\\"%sG\\",' \
               '\\"lvName\\":\\"%s\\"}",' \
               '"op":"orchStrLun",' \
               '"args":"add"}]' % (repository, volume_size,
                                   volume_name)
        return self._configure(data)

    def delete_lun(self, volume_name):
        """Delete LUN."""
        volume_info = self._get_volume_info(volume_name)
        repository = volume_info['repo']
        data = '[{"addr":"cms","data":"{' \
               '\\"repoName\\":\\"%s\\",' \
               '\\"lvName\\":\\"%s\\"}",' \
               '"op":"orchStrLun/verified",' \
               '"args":"delete"}]' % (repository, volume_name)
        return self._configure(data)

    def create_snapshot(self, volume_name, snapshot_name):
        """Create Snapshot."""
        volume_info = self._get_volume_info(volume_name)
        repository = volume_info['repo']
        data = '[{"addr":"cms","data":"{' \
               '\\"repoName\\":\\"%s\\",' \
               '\\"lvName\\":\\"%s\\",' \
               '\\"newLvName\\":\\"%s\\"}",' \
               '"op":"orchStrLunMods",' \
               '"args":"addClSnap"}]' % (repository, volume_name,
                                         snapshot_name)
        return self._configure(data)

    def delete_snapshot(self, snapshot_name):
        """Delete Snapshot."""
        snapshot_info = self._get_volume_info(snapshot_name)
        repository = snapshot_info['repo']
        data = '[{"addr":"cms","data":"{' \
               '\\"repoName\\":\\"%s\\",' \
               '\\"lvName\\":\\"%s\\"}",' \
               '"op":"orchStrLunMods",' \
               '"args":"delClSnap"}]' % (repository, snapshot_name)
        return self._configure(data)

    def create_volume_from_snapshot(self, snapshot_name,
                                    volume_name, repository):
        """Create a LUN from a Snapshot."""
        snapshot_info = self._get_volume_info(snapshot_name)
        snapshot_repo = snapshot_info['repo']
        data = '[{"addr":"cms","data":"{' \
               '\\"lvName\\":\\"%s\\",' \
               '\\"repoName\\":\\"%s\\",' \
               '\\"newLvName\\":\\"%s\\",' \
               '\\"newRepoName\\":\\"%s\\"}",' \
               '"op":"orchStrLunMods",' \
               '"args":"addClone"}]' % (snapshot_name, snapshot_repo,
                                        volume_name, repository)
        return self._configure(data)


class CoraidDriver(driver.VolumeDriver):
    """This is the Class to set in cinder.conf (volume_driver)."""

    def __init__(self, *args, **kwargs):
        super(CoraidDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(coraid_opts)

    def do_setup(self, context):
        """Initialize the volume driver."""
        self.esm = CoraidRESTClient(self.configuration.coraid_esm_address,
                                    self.configuration.coraid_user,
                                    self.configuration.coraid_group,
                                    self.configuration.coraid_password)

    def check_for_setup_error(self):
        """Return an error if prerequisites aren't met."""
        if not self.esm._login():
            raise LookupError(_("Cannot login on Coraid ESM"))

    def _get_repository(self, volume_type):
        """
        Return the ESM Repository from the Volume Type.
        The ESM Repository is stored into a volume_type_extra_specs key.
        """
        volume_type_id = volume_type['id']
        repository_key_name = self.configuration.coraid_repository_key
        repository = volume_types.get_volume_type_extra_specs(
            volume_type_id, repository_key_name)
        return repository

    def create_volume(self, volume):
        """Create a Volume."""
        try:
            repository = self._get_repository(volume['volume_type'])
            self.esm.create_lun(volume['name'], volume['size'], repository)
        except Exception:
            msg = _('Fail to create volume %(volname)s')
            LOG.debug(msg % dict(volname=volume['name']))
            raise
        # NOTE(jbr_): The manager currently interprets any return as
        # being the model_update for provider location.
        # return None to not break it (thank to jgriffith and DuncanT)
        return

    def delete_volume(self, volume):
        """Delete a Volume."""
        try:
            self.esm.delete_lun(volume['name'])
        except Exception:
            msg = _('Failed to delete volume %(volname)s')
            LOG.debug(msg % dict(volname=volume['name']))
            raise
        return

    def create_snapshot(self, snapshot):
        """Create a Snapshot."""
        try:
            volume_name = (FLAGS.volume_name_template
                           % snapshot['volume_id'])
            snapshot_name = (FLAGS.snapshot_name_template
                             % snapshot['id'])
            self.esm.create_snapshot(volume_name, snapshot_name)
        except Exception, e:
            msg = _('Failed to Create Snapshot %(snapname)s')
            LOG.debug(msg % dict(snapname=snapshot_name))
            raise
        return

    def delete_snapshot(self, snapshot):
        """Delete a Snapshot."""
        try:
            snapshot_name = (FLAGS.snapshot_name_template
                             % snapshot['id'])
            self.esm.delete_snapshot(snapshot_name)
        except Exception:
            msg = _('Failed to Delete Snapshot %(snapname)s')
            LOG.debug(msg % dict(snapname=snapshot_name))
            raise
        return

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a Volume from a Snapshot."""
        try:
            snapshot_name = (FLAGS.snapshot_name_template
                             % snapshot['id'])
            repository = self._get_repository(volume['volume_type'])
            self.esm.create_volume_from_snapshot(snapshot_name,
                                                 volume['name'],
                                                 repository)
        except Exception:
            msg = _('Failed to Create Volume from Snapshot %(snapname)s')
            LOG.debug(msg % dict(snapname=snapshot_name))
            raise
        return

    def initialize_connection(self, volume, connector):
        """Return connection information."""
        try:
            infos = self.esm._get_lun_address(volume['name'])
            shelf = infos['shelf']
            lun = infos['lun']

            aoe_properties = {
                'target_shelf': shelf,
                'target_lun': lun,
            }
            return {
                'driver_volume_type': 'aoe',
                'data': aoe_properties,
            }
        except Exception:
            msg = _('Failed to Initialize Connection. '
                    'Volume Name: %(volname)s '
                    'Shelf: %(shelf)s, '
                    'Lun: %(lun)s')
            LOG.debug(msg % dict(volname=volume['name'],
                                 shelf=shelf,
                                 lun=lun))
            raise
        return

    def get_volume_stats(self, refresh=False):
        """Return Volume Stats."""
        data = {'driver_version': '1.0',
                'free_capacity_gb': 'unknown',
                'reserved_percentage': 0,
                'storage_protocol': 'aoe',
                'total_capacity_gb': 'unknown',
                'vendor_name': 'Coraid'}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or 'EtherCloud ESM'
        return data

    def local_path(self, volume):
        pass

    def create_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def ensure_export(self, context, volume):
        pass

    def attach_volume(self, context, volume, instance_uuid, mountpoint):
        pass

    def detach_volume(self, context, volume):
        pass
