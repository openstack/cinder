# Copyright (c) 2014, 2015, Oracle and/or its affiliates. All rights reserved.
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
ZFS Storage Appliance Proxy
"""
import json

from oslo_log import log
from oslo_service import loopingcall

from cinder import exception
from cinder.i18n import _, _LE, _LW
from cinder.volume.drivers.zfssa import restclient
from cinder.volume.drivers.zfssa import webdavclient

LOG = log.getLogger(__name__)


def factory_restclient(url, **kwargs):
    return restclient.RestClientURL(url, **kwargs)


class ZFSSAApi(object):
    """ZFSSA API proxy class"""

    def __init__(self):
        self.host = None
        self.url = None
        self.rclient = None

    def __del__(self):
        if self.rclient and self.rclient.islogin():
            self.rclient.logout()

    def _is_pool_owned(self, pdata):
        """Returns True if the pool's owner is the same as the host."""
        svc = '/api/system/v1/version'
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error getting version: '
                               'svc: %(svc)s.'
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'svc': svc,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        vdata = json.loads(ret.data)
        return vdata['version']['asn'] == pdata['pool']['asn'] and \
            vdata['version']['nodename'] == pdata['pool']['owner']

    def set_host(self, host, timeout=None):
        self.host = host
        self.url = "https://" + self.host + ":215"
        self.rclient = factory_restclient(self.url, timeout=timeout)

    def login(self, auth_str):
        """Login to the appliance"""
        if self.rclient and not self.rclient.islogin():
            self.rclient.login(auth_str)

    def logout(self):
        self.rclient.logout()

    def verify_service(self, service, status='online'):
        """Checks whether a service is online or not"""
        svc = '/api/service/v1/services/' + service
        ret = self.rclient.get(svc)

        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying '
                               'Service: %(service)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'service': service,
                                'ret.status': ret.status,
                                'ret.data': ret.data})

            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        data = json.loads(ret.data)['service']

        if data['<status>'] != status:
            exception_msg = (_('%(service)s Service is not %(status)s '
                               'on storage appliance: %(host)s')
                             % {'service': service,
                                'status': status,
                                'host': self.host})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def get_asn(self):
        """Returns appliance asn."""
        svc = '/api/system/v1/version'
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error getting appliance version details. '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['version']['asn']

    def get_replication_targets(self):
        """Returns all replication targets configured on the appliance."""
        svc = '/api/storage/v1/replication/targets'
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error getting replication target details. '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val

    def edit_inherit_replication_flag(self, pool, project, volume, set=True):
        """Edit the inherit replication flag for volume."""
        svc = ('/api/storage/v1/pools/%(pool)s/projects/%(project)s'
               '/filesystems/%(volume)s/replication'
               % {'pool': pool,
                  'project': project,
                  'volume': volume})
        arg = {'inherited': set}
        ret = self.rclient.put(svc, arg)

        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error setting replication inheritance '
                               'to %(set)s '
                               'for volume: %(vol)s '
                               'project %(project)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'set': set,
                                'project': project,
                                'vol': volume,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_replication_action(self, host_pool, host_project, tgt_name,
                                  tgt_pool, volume):
        """Create a replication action."""
        arg = {'pool': host_pool,
               'project': host_project,
               'target_pool': tgt_pool,
               'target': tgt_name}

        if volume is not None:
            arg.update({'share': volume})

        svc = '/api/storage/v1/replication/actions'
        ret = self.rclient.post(svc, arg)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Creating replication action on: '
                               'pool: %(pool)s '
                               'Project: %(proj)s '
                               'volume: %(vol)s '
                               'for target: %(tgt)s and pool: %(tgt_pool)s'
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'pool': host_pool,
                                'proj': host_project,
                                'vol': volume,
                                'tgt': tgt_name,
                                'tgt_pool': tgt_pool,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['action']['id']

    def delete_replication_action(self, action_id):
        """Delete a replication action."""
        svc = '/api/storage/v1/replication/actions/%s' % action_id
        ret = self.rclient.delete(svc)
        if ret.status != restclient.Status.NO_CONTENT:
            exception_msg = (_('Error Deleting '
                               'replication action: %(id)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'id': action_id,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def send_repl_update(self, action_id):
        """Send replication update

           Send replication update to the target appliance and then wait for
           it to complete.
        """

        svc = '/api/storage/v1/replication/actions/%s/sendupdate' % action_id
        ret = self.rclient.put(svc)
        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error sending replication update '
                               'for action id: %(id)s . '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'id': action_id,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        def _loop_func():
            svc = '/api/storage/v1/replication/actions/%s' % action_id
            ret = self.rclient.get(svc)
            if ret.status != restclient.Status.OK:
                exception_msg = (_('Error getting replication action: %(id)s. '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'id': action_id,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

            val = json.loads(ret.data)
            if val['action']['last_result'] == 'success':
                raise loopingcall.LoopingCallDone()
            elif (val['action']['last_result'] == '<unknown>' and
                    val['action']['state'] == 'sending'):
                pass
            else:
                exception_msg = (_('Error sending replication update. '
                                   'Returned error: %(err)s. '
                                   'Action: %(id)s.')
                                 % {'err': val['action']['last_result'],
                                    'id': action_id})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

        timer = loopingcall.FixedIntervalLoopingCall(_loop_func)
        timer.start(interval=5).wait()

    def get_replication_source(self, asn):
        """Return the replication source json which has a matching asn."""
        svc = "/api/storage/v1/replication/sources"
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error getting replication source details. '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)

        for source in val['sources']:
            if source['asn'] == asn:
                return source
        return None

    def sever_replication(self, package, src_name, project=None):
        """Sever Replication at the destination.

           This method will sever the package and move the volume to a project,
           if project name is not passed in then the package name is selected
           as the project name
        """

        svc = ('/api/storage/v1/replication/sources/%(src)s/packages/%(pkg)s'
               '/sever' % {'src': src_name, 'pkg': package})

        if not project:
            project = package

        arg = {'projname': project}
        ret = self.rclient.put(svc, arg)

        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error severing the package: %(package)s '
                               'from source: %(src)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'package': package,
                                'src': src_name,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def move_volume(self, pool, project, volume, tgt_project):
        """Move a LUN from one project to another within the same pool."""
        svc = ('/api/storage/v1/pools/%(pool)s/projects/%(project)s'
               '/filesystems/%(volume)s' % {'pool': pool,
                                            'project': project,
                                            'volume': volume})

        arg = {'project': tgt_project}

        ret = self.rclient.put(svc, arg)
        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error moving volume: %(vol)s '
                               'from source project: %(src)s '
                               'to target project: %(tgt)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'vol': volume,
                                'src': project,
                                'tgt': tgt_project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def delete_project(self, pool, project):
        """Delete a project."""
        svc = ('/api/storage/v1/pools/%(pool)s/projects/%(project)s' %
               {'pool': pool,
                'project': project})
        ret = self.rclient.delete(svc)
        if ret.status != restclient.Status.NO_CONTENT:
            exception_msg = (_('Error Deleting '
                               'project: %(project)s '
                               'on pool: %(pool)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'project': project,
                                'pool': pool,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def get_project_stats(self, pool, project):
        """Get project stats.

           Get available space and total space of a project
           returns (avail, total).
        """
        svc = '/api/storage/v1/pools/%s/projects/%s' % (pool, project)
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting Project Stats: '
                               'Pool: %(pool)s '
                               'Project: %(project)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        avail = val['project']['space_available']
        total = avail + val['project']['space_total']

        return avail, total

    def create_project(self, pool, project, compression=None, logbias=None):
        """Create a project on a pool.

        Check first whether the pool exists.
        """
        self.verify_pool(pool)
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + project
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = '/api/storage/v1/pools/' + pool + '/projects'
            arg = {
                'name': project
            }
            if compression and compression != '':
                arg.update({'compression': compression})
            if logbias and logbias != '':
                arg.update({'logbias': logbias})

            ret = self.rclient.post(svc, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating Project: '
                                   '%(project)s on '
                                   'Pool: %(pool)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'project': project,
                                    'pool': pool,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_initiator(self, initiator, alias, chapuser=None,
                         chapsecret=None):
        """Create an iSCSI initiator."""

        svc = '/api/san/v1/iscsi/initiators/alias=' + alias
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = '/api/san/v1/iscsi/initiators'
            arg = {
                'initiator': initiator,
                'alias': alias
            }
            if chapuser and chapuser != '' and chapsecret and chapsecret != '':
                arg.update({'chapuser': chapuser,
                            'chapsecret': chapsecret})

            ret = self.rclient.post(svc, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating Initiator: '
                                   '%(initiator)s on '
                                   'Alias: %(alias)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'initiator': initiator,
                                    'alias': alias,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def add_to_initiatorgroup(self, initiator, initiatorgroup):
        """Add an iSCSI initiator to initiatorgroup"""
        svc = '/api/san/v1/iscsi/initiator-groups/' + initiatorgroup
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = '/api/san/v1/iscsi/initiator-groups'
            arg = {
                'name': initiatorgroup,
                'initiators': [initiator]
            }
            ret = self.rclient.post(svc, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Adding Initiator: '
                                   '%(initiator)s on group'
                                   'InitiatorGroup: %(initiatorgroup)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'initiator': initiator,
                                    'initiatorgroup': initiatorgroup,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)
        else:
            val = json.loads(ret.data)
            inits = val['group']['initiators']
            if inits is None:
                exception_msg = (_('Error Getting Initiators: '
                                   'InitiatorGroup: %(initiatorgroup)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'initiatorgroup': initiatorgroup,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

            if initiator in inits:
                return

            inits.append(initiator)
            svc = '/api/san/v1/iscsi/initiator-groups/' + initiatorgroup
            arg = {
                'initiators': inits
            }
            ret = self.rclient.put(svc, arg)
            if ret.status != restclient.Status.ACCEPTED:
                exception_msg = (_('Error Adding Initiator: '
                                   '%(initiator)s on group'
                                   'InitiatorGroup: %(initiatorgroup)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'initiator': initiator,
                                    'initiatorgroup': initiatorgroup,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_target(self, alias, interfaces=None, tchapuser=None,
                      tchapsecret=None):
        """Create an iSCSI target.

        :param interfaces: an array with network interfaces
        :param tchapuser, tchapsecret: target's chapuser and chapsecret
        :returns: target iqn
        """
        svc = '/api/san/v1/iscsi/targets/alias=' + alias
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = '/api/san/v1/iscsi/targets'
            arg = {
                'alias': alias
            }

            if tchapuser and tchapuser != '' and tchapsecret and \
               tchapsecret != '':
                arg.update({'targetchapuser': tchapuser,
                            'targetchapsecret': tchapsecret,
                            'auth': 'chap'})

            if interfaces is not None and len(interfaces) > 0:
                arg.update({'interfaces': interfaces})

            ret = self.rclient.post(svc, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating Target: '
                                   '%(alias)s'
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'alias': alias,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['target']['iqn']

    def get_target(self, alias):
        """Get an iSCSI target iqn."""
        svc = '/api/san/v1/iscsi/targets/alias=' + alias
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting Target: '
                               '%(alias)s'
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'alias': alias,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['target']['iqn']

    def add_to_targetgroup(self, iqn, targetgroup):
        """Add an iSCSI target to targetgroup."""
        svc = '/api/san/v1/iscsi/target-groups/' + targetgroup
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svccrt = '/api/san/v1/iscsi/target-groups'
            arg = {
                'name': targetgroup,
                'targets': [iqn]
            }

            ret = self.rclient.post(svccrt, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating TargetGroup: '
                                   '%(targetgroup)s with'
                                   'IQN: %(iqn)s'
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'targetgroup': targetgroup,
                                    'iqn': iqn,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

            return

        arg = {
            'targets': [iqn]
        }

        ret = self.rclient.put(svc, arg)
        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error Adding to TargetGroup: '
                               '%(targetgroup)s with'
                               'IQN: %(iqn)s'
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'targetgroup': targetgroup,
                                'iqn': iqn,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def verify_pool(self, pool):
        """Checks whether pool exists."""
        svc = '/api/storage/v1/pools/' + pool
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying Pool: '
                               '%(pool)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'pool': pool,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def verify_project(self, pool, project):
        """Checks whether project exists."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + project
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying '
                               'Project: %(project)s on '
                               'Pool: %(pool)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'project': project,
                                'pool': pool,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def verify_initiator(self, iqn):
        """Check whether initiator iqn exists."""
        svc = '/api/san/v1/iscsi/initiators/' + iqn
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying '
                               'Initiator: %(iqn)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'initiator': iqn,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def verify_target(self, alias):
        """Check whether target alias exists."""
        svc = '/api/san/v1/iscsi/targets/alias=' + alias
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying '
                               'Target: %(alias)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'alias': alias,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_lun(self, pool, project, lun, volsize, targetgroup, specs):
        """Create a LUN.

        specs - contains volume properties (e.g blocksize, compression).
        """
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
              project + '/luns'
        arg = {
            'name': lun,
            'volsize': volsize,
            'targetgroup': targetgroup,
            'initiatorgroup': 'com.sun.ms.vss.hg.maskAll'
        }
        if specs:
            arg.update(specs)

        ret = self.rclient.post(svc, arg)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Creating '
                               'Volume: %(lun)s '
                               'Size: %(size)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'lun': lun,
                                'size': volsize,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val

    def get_lun(self, pool, project, lun):
        """return iscsi lun properties."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + "/luns/" + lun
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting '
                               'Volume: %(lun)s on '
                               'Pool: %(pool)s '
                               'Project: %(project)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeNotFound(volume_id=lun)

        val = json.loads(ret.data)
        ret = {
            'guid': val['lun']['lunguid'],
            'number': val['lun']['assignednumber'],
            'initiatorgroup': val['lun']['initiatorgroup'],
            'size': val['lun']['volsize'],
            'nodestroy': val['lun']['nodestroy'],
            'targetgroup': val['lun']['targetgroup']
        }
        if 'origin' in val['lun']:
            ret.update({'origin': val['lun']['origin']})
        if 'custom:image_id' in val['lun']:
            ret.update({'image_id': val['lun']['custom:image_id']})
            ret.update({'updated_at': val['lun']['custom:updated_at']})

        return ret

    def get_lun_snapshot(self, pool, project, lun, snapshot):
        """Return iscsi lun snapshot properties."""
        svc = ('/api/storage/v1/pools/' + pool + '/projects/' +
               project + '/luns/' + lun + '/snapshots/' + snapshot)

        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_LE('Error Getting '
                                 'Snapshot: %(snapshot)s of '
                                 'Volume: %(lun)s in '
                                 'Pool: %(pool)s, '
                                 'Project: %(project)s  '
                                 'Return code: %(ret.status)d, '
                                 'Message: %(ret.data)s.'),
                             {'snapshot': snapshot,
                              'lun': lun,
                              'pool': pool,
                              'project': project,
                              'ret.status': ret.status,
                              'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.SnapshotNotFound(snapshot_id=snapshot)

        val = json.loads(ret.data)['snapshot']
        ret = {
            'name': val['name'],
            'numclones': val['numclones'],
        }
        return ret

    def set_lun_initiatorgroup(self, pool, project, lun, initiatorgroup):
        """Set the initiatorgroup property of a LUN."""
        if initiatorgroup == '':
            initiatorgroup = 'com.sun.ms.vss.hg.maskAll'

        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun
        arg = {
            'initiatorgroup': initiatorgroup
        }

        ret = self.rclient.put(svc, arg)
        if ret.status != restclient.Status.ACCEPTED:
            LOG.error(_LE('Error Setting Volume: %(lun)s to InitiatorGroup: '
                          '%(initiatorgroup)s Pool: %(pool)s Project: '
                          '%(project)s  Return code: %(ret.status)d Message: '
                          '%(ret.data)s.'),
                      {'lun': lun,
                       'initiatorgroup': initiatorgroup,
                       'pool': pool,
                       'project': project,
                       'ret.status': ret.status,
                       'ret.data': ret.data})

    def delete_lun(self, pool, project, lun):
        """delete iscsi lun."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun

        ret = self.rclient.delete(svc)
        if ret.status != restclient.Status.NO_CONTENT:
            exception_msg = (_('Error Deleting Volume: %(lun)s from '
                               'Pool: %(pool)s, Project: %(project)s. '
                               'Return code: %(ret.status)d, '
                               'Message: %(ret.data)s.'),
                             {'lun': lun,
                              'pool': pool,
                              'project': project,
                              'ret.status': ret.status,
                              'ret.data': ret.data})
            LOG.error(exception_msg)
            if ret.status == restclient.Status.FORBIDDEN:
                # This means that the lun exists but it can't be deleted:
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_snapshot(self, pool, project, lun, snapshot):
        """create snapshot."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun + '/snapshots'
        arg = {
            'name': snapshot
        }

        ret = self.rclient.post(svc, arg)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Creating '
                               'Snapshot: %(snapshot)s on'
                               'Volume: %(lun)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.'),
                             {'snapshot': snapshot,
                              'lun': lun,
                              'pool': pool,
                              'project': project,
                              'ret.status': ret.status,
                              'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def delete_snapshot(self, pool, project, lun, snapshot):
        """delete snapshot."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
              project + '/luns/' + lun + '/snapshots/' + snapshot

        ret = self.rclient.delete(svc)
        if ret.status != restclient.Status.NO_CONTENT:
            exception_msg = (_('Error Deleting '
                               'Snapshot: %(snapshot)s on '
                               'Volume: %(lun)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def clone_snapshot(self, pool, project, lun, snapshot, clone_proj, clone):
        """clone 'snapshot' to a lun named 'clone' in project 'clone_proj'."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun + '/snapshots/' + snapshot + '/clone'
        arg = {
            'project': clone_proj,
            'share': clone,
            'nodestroy': True
        }

        ret = self.rclient.put(svc, arg)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Cloning '
                               'Snapshot: %(snapshot)s on '
                               'Volume: %(lun)s of '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Clone project: %(clone_proj)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'clone_proj': clone_proj,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def set_lun_props(self, pool, project, lun, **kargs):
        """set lun properties."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun
        if kargs is None:
            return

        ret = self.rclient.put(svc, kargs)
        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error Setting props '
                               'Props: %(props)s on '
                               'Volume: %(lun)s of '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'props': kargs,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def num_clones(self, pool, project, lun, snapshot):
        """Checks whether snapshot has clones or not."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun + '/snapshots/' + snapshot

        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting '
                               'Snapshot: %(snapshot)s on '
                               'Volume: %(lun)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['snapshot']['numclones']

    def get_initiator_initiatorgroup(self, initiator):
        """Returns the initiator group of the initiator."""
        groups = []
        svc = "/api/san/v1/iscsi/initiator-groups"
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            msg = _('Error getting initiator groups.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        val = json.loads(ret.data)
        for initiator_group in val['groups']:
            if initiator in initiator_group['initiators']:
                groups.append(initiator_group["name"])
        if len(groups) == 0:
            LOG.debug("Initiator group not found. Attaching volume to "
                      "default initiator group.")
            groups.append('default')
        return groups

    def create_schema(self, schema):
        """Create a custom ZFSSA schema."""
        base = '/api/storage/v1/schema'

        svc = "%(base)s/%(prop)s" % {'base': base, 'prop': schema['property']}
        ret = self.rclient.get(svc)
        if ret.status == restclient.Status.OK:
            LOG.warning(_LW('Property %s already exists.'), schema['property'])
            return

        ret = self.rclient.post(base, schema)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Creating '
                               'Property: %(property)s '
                               'Type: %(type)s '
                               'Description: %(description)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'property': schema['property'],
                                'type': schema['type'],
                                'description': schema['description'],
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_schemas(self, schemas):
        """Create multiple custom ZFSSA schemas."""
        ret = []
        for schema in schemas:
            res = self.create_schema(schema)
            ret.append(res)
        return ret


class ZFSSANfsApi(ZFSSAApi):
    """ZFSSA API proxy class for NFS driver"""
    projects_path = '/api/storage/v1/pools/%s/projects'
    project_path = projects_path + '/%s'

    shares_path = project_path + '/filesystems'
    share_path = shares_path + '/%s'
    share_snapshots_path = share_path + '/snapshots'
    share_snapshot_path = share_snapshots_path + '/%s'

    services_path = '/api/service/v1/services/'

    def __init__(self, *args, **kwargs):
        super(ZFSSANfsApi, self).__init__(*args, **kwargs)
        self.webdavclient = None

    def set_webdav(self, https_path, auth_str):
        self.webdavclient = webdavclient.ZFSSAWebDAVClient(https_path,
                                                           auth_str)

    def verify_share(self, pool, project, share):
        """Checks whether the share exists"""
        svc = self.share_path % (pool, project, share)
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying '
                               'share: %(share)s on '
                               'Project: %(project)s and '
                               'Pool: %(pool)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'share': share,
                                'project': project,
                                'pool': pool,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_snapshot(self, pool, project, share, snapshot):
        """create snapshot of a share"""
        svc = self.share_snapshots_path % (pool, project, share)

        arg = {
            'name': snapshot
        }

        ret = self.rclient.post(svc, arg)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Creating '
                               'Snapshot: %(snapshot)s on'
                               'share: %(share)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'share': share,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def delete_snapshot(self, pool, project, share, snapshot):
        """delete snapshot of a share"""
        svc = self.share_snapshot_path % (pool, project, share, snapshot)

        ret = self.rclient.delete(svc)
        if ret.status != restclient.Status.NO_CONTENT:
            exception_msg = (_('Error Deleting '
                               'Snapshot: %(snapshot)s on '
                               'Share: %(share)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'share': share,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_snapshot_of_volume_file(self, src_file="", dst_file=""):
        src_file = '.zfs/snapshot/' + src_file
        return self.webdavclient.request(src_file=src_file, dst_file=dst_file,
                                         method='COPY')

    def delete_snapshot_of_volume_file(self, src_file=""):
        return self.webdavclient.request(src_file=src_file, method='DELETE')

    def create_volume_from_snapshot_file(self, src_file="", dst_file="",
                                         method='COPY'):
        return self.webdavclient.request(src_file=src_file, dst_file=dst_file,
                                         method=method)

    def _change_service_state(self, service, state=''):
        svc = self.services_path + service + '/' + state
        ret = self.rclient.put(svc)
        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error Verifying '
                               'Service: %(service)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'service': service,
                                'ret.status': ret.status,
                                'ret.data': ret.data})

            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)
        data = json.loads(ret.data)['service']
        LOG.debug('%(service)s service state: %(data)s',
                  {'service': service, 'data': data})

        status = 'online' if state == 'enable' else 'disabled'

        if data['<status>'] != status:
            exception_msg = (_('%(service)s Service is not %(status)s '
                               'on storage appliance: %(host)s')
                             % {'service': service,
                                'status': status,
                                'host': self.host})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def enable_service(self, service):
        self._change_service_state(service, state='enable')
        self.verify_service(service)

    def disable_service(self, service):
        self._change_service_state(service, state='disable')
        self.verify_service(service, status='offline')

    def modify_service(self, service, edit_args=None):
        """Edit service properties"""
        if edit_args is None:
            edit_args = {}

        svc = self.services_path + service

        ret = self.rclient.put(svc, edit_args)

        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error modifying '
                               'Service: %(service)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'service': service,
                                'ret.status': ret.status,
                                'ret.data': ret.data})

            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)
        data = json.loads(ret.data)['service']
        LOG.debug('Modify %(service)s service '
                  'return data: %(data)s',
                  {'service': service,
                   'data': data})

    def create_share(self, pool, project, share, args):
        """Create a share in the specified pool and project"""
        svc = self.share_path % (pool, project, share)
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = self.shares_path % (pool, project)
            args.update({'name': share})
            ret = self.rclient.post(svc, args)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating '
                                   'Share: %(name)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s.')
                                 % {'name': share,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)
        else:
            LOG.debug('Editing properties of a pre-existing share')
            ret = self.rclient.put(svc, args)
            if ret.status != restclient.Status.ACCEPTED:
                exception_msg = (_('Error editing share: '
                                   '%(share)s on '
                                   'Pool: %(pool)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'share': share,
                                    'pool': pool,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def get_share(self, pool, project, share):
        """return share properties"""
        svc = self.share_path % (pool, project, share)
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting '
                               'Share: %(share)s on '
                               'Pool: %(pool)s '
                               'Project: %(project)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'share': share,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['filesystem']

    def get_volume(self, volume):
        LOG.debug('Getting volume %s.', volume)
        try:
            resp = self.webdavclient.request(src_file=volume,
                                             method='PROPFIND')
        except Exception:
            raise exception.VolumeNotFound(volume_id=volume)

        resp = resp.read()
        numclones = self._parse_prop(resp, 'numclones')
        result = {
            'numclones': int(numclones) if numclones != '' else 0,
            'updated_at': self._parse_prop(resp, 'updated_at'),
            'image_id': self._parse_prop(resp, 'image_id'),
            'origin': self._parse_prop(resp, 'origin'),
        }
        return result

    def delete_file(self, filename):
        try:
            self.webdavclient.request(src_file=filename, method='DELETE')
        except Exception:
            exception_msg = (_LE('Cannot delete file %s.'), filename)
            LOG.error(exception_msg)

    def set_file_props(self, file, specs):
        """Set custom properties to a file."""
        for key in specs:
            self.webdavclient.set_file_prop(file, key, specs[key])

    def _parse_prop(self, response, prop):
        """Parse a property value from the WebDAV response."""
        propval = ""
        for line in response.split("\n"):
            if prop in line:
                try:
                    propval = line[(line.index('>') + 1):line.index('</')]
                except Exception:
                    pass
        return propval

    def create_directory(self, dirname):
        try:
            self.webdavclient.request(src_file=dirname, method='GET')
            LOG.debug('Directory %s already exists.', dirname)
        except Exception:
            # The directory does not exist yet
            try:
                self.webdavclient.request(src_file=dirname, method='MKCOL')
            except Exception:
                exception_msg = (_('Cannot create directory %s.'), dirname)
                raise exception.VolumeBackendAPIException(data=exception_msg)
