#    Copyright (c) 2020 Open-E, Inc.
#    All Rights Reserved.
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


"""REST cmd interoperation class for Open-E JovianDSS driver."""
import re

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.open_e.jovian_common import exception as jexc
from cinder.volume.drivers.open_e.jovian_common import rest_proxy

LOG = logging.getLogger(__name__)


class JovianRESTAPI(object):
    """Jovian REST API proxy."""

    def __init__(self, config):

        self.pool = config.get('jovian_pool', 'Pool-0')
        self.rproxy = rest_proxy.JovianRESTProxy(config)

        self.resource_dne_msg = (
            re.compile(r'^Zfs resource: .* not found in this collection\.$'))

    def _general_error(self, url, resp):
        reason = "Request %s failure" % url
        if 'error' in resp:

            eclass = resp.get('class', 'Unknown')
            code = resp.get('code', 'Unknown')
            msg = resp.get('message', 'Unknown')

            reason = _("Request to %(url)s failed with code: %(code)s "
                       "of type:%(eclass)s reason:%(message)s")
            reason = (reason % {'url': url,
                                'code': code,
                                'eclass': eclass,
                                'message': msg})
        raise jexc.JDSSException(reason=reason)

    def get_active_host(self):
        """Return address of currently used host."""
        return self.rproxy.get_active_host()

    def is_pool_exists(self):
        """is_pool_exists.

        GET
        /pools/<string:poolname>

        :param pool_name:
        :return: Bool
        """
        req = ""
        LOG.debug("check pool")

        resp = self.rproxy.pool_request('GET', req)

        if resp["code"] == 200 and not resp["error"]:
            return True

        return False

    def get_iface_info(self):
        """get_iface_info

        GET
        /network/interfaces
        :return list of internet ifaces
        """
        req = '/network/interfaces'

        LOG.debug("get network interfaces")

        resp = self.rproxy.request('GET', req)
        if (resp['error'] is None) and (resp['code'] == 200):
            return resp['data']
        raise jexc.JDSSRESTException(resp['error']['message'])

    def get_luns(self):
        """get_all_pool_volumes.

        GET
        /pools/<string:poolname>/volumes
        :param pool_name
        :return list of all pool volumes
        """
        req = '/volumes'

        LOG.debug("get all volumes")
        resp = self.rproxy.pool_request('GET', req)

        if resp['error'] is None and resp['code'] == 200:
            return resp['data']
        raise jexc.JDSSRESTException(resp['error']['message'])

    def create_lun(self, volume_name, volume_size, sparse=False,
                   block_size=None):
        """create_volume.

        POST
        .../volumes

        :param volume_name:
        :param volume_size:
        :return:
        """
        volume_size_str = str(volume_size)
        jbody = {
            'name': volume_name,
            'size': volume_size_str,
            'sparse': sparse
        }
        if block_size:
            jbody['blocksize'] = block_size

        req = '/volumes'

        LOG.debug("create volume %s", str(jbody))
        resp = self.rproxy.pool_request('POST', req, json_data=jbody)

        if not resp["error"] and resp["code"] in (200, 201):
            return

        if resp["error"] is not None:
            if resp["error"]["errno"] == str(5):
                msg = _('Failed to create volume %s.' %
                        resp['error']['message'])
                raise jexc.JDSSRESTException(msg)

        raise jexc.JDSSRESTException('Failed to create volume.')

    def extend_lun(self, volume_name, volume_size):
        """create_volume.

        PUT /volumes/<string:volume_name>
        """
        req = '/volumes/' + volume_name
        volume_size_str = str(volume_size)
        jbody = {
            'size': volume_size_str
        }

        LOG.debug("jdss extend volume %(volume)s to %(size)s",
                  {"volume": volume_name,
                   "size": volume_size_str})
        resp = self.rproxy.pool_request('PUT', req, json_data=jbody)

        if not resp["error"] and resp["code"] == 201:
            return

        if resp["error"]:
            raise jexc.JDSSRESTException(
                _('Failed to extend volume %s' % resp['error']['message']))

        raise jexc.JDSSRESTException('Failed to extend volume.')

    def is_lun(self, volume_name):
        """is_lun.

        GET /volumes/<string:volumename>
        Returns True if volume exists. Uses GET request.
        :param pool_name:
        :param volume_name:
        :return:
        """
        req = '/volumes/' + volume_name

        LOG.debug("check volume %s", volume_name)
        ret = self.rproxy.pool_request('GET', req)

        if not ret["error"] and ret["code"] == 200:
            return True
        return False

    def get_lun(self, volume_name):
        """get_lun.

        GET /volumes/<volume_name>
        :param volume_name:
        :return:
        {
            "data":
            {
                "origin": null,
                "referenced": "65536",
                "primarycache": "all",
                "logbias": "latency",
                "creation": "1432730973",
                "sync": "always",
                "is_clone": false,
                "dedup": "off",
                "used": "1076101120",
                "full_name": "Pool-0/v1",
                "type": "volume",
                "written": "65536",
                "usedbyrefreservation": "1076035584",
                "compression": "lz4",
                "usedbysnapshots": "0",
                "copies": "1",
                "compressratio": "1.00x",
                "readonly": "off",
                "mlslabel": "none",
                "secondarycache": "all",
                "available": "976123452576",
                "resource_name": "Pool-0/v1",
                "volblocksize": "131072",
                "refcompressratio": "1.00x",
                "snapdev": "hidden",
                "volsize": "1073741824",
                "reservation": "0",
                "usedbychildren": "0",
                "usedbydataset": "65536",
                "name": "v1",
                "checksum": "on",
                "refreservation": "1076101120"
            },
            "error": null
        }
        """
        req = '/volumes/' + volume_name

        LOG.debug("get volume %s info", volume_name)
        resp = self.rproxy.pool_request('GET', req)

        if not resp['error'] and resp['code'] == 200:
            return resp['data']

        if resp['error']:
            if 'message' in resp['error']:
                if self.resource_dne_msg.match(resp['error']['message']):
                    raise jexc.JDSSResourceNotFoundException(res=volume_name)

        self._general_error(req, resp)

    def modify_lun(self, volume_name, prop=None):
        """Update volume properties

        :prop volume_name: volume name
        :prop prop: dictionary
            {
                <property>: <value>
            }
        """

        req = '/volumes/' + volume_name

        resp = self.rproxy.pool_request('PUT', req, json_data=prop)

        if resp["code"] in (200, 201, 204):
            LOG.debug("volume %s updated", volume_name)
            return

        if resp["code"] == 500:
            if resp["error"] is not None:
                if resp["error"]["errno"] == 1:
                    raise jexc.JDSSResourceNotFoundException(
                        res=volume_name)

        self._general_error(req, resp)

    def make_readonly_lun(self, volume_name):
        """Set volume into read only mode

        :param: volume_name: volume name
        """
        prop = {"property_name": "readonly", "property_value": "on"}

        self.modify_property_lun(volume_name, prop)

    def modify_property_lun(self, volume_name, prop=None):
        """Change volume properties

        :prop: volume_name: volume name
        :prop: prop: dictionary of volume properties in format
                { "property_name": "<name of property>",
                  "property_value":"<value of a property>"}
        """

        req = '/volumes/%s/properties' % volume_name

        resp = self.rproxy.pool_request('PUT', req, json_data=prop)

        if resp["code"] in (200, 201, 204):
            LOG.debug(
                "volume %s properties updated", volume_name)
            return

        if resp["code"] == 500:
            if resp["error"] is not None:
                if resp["error"]["errno"] == 1:
                    raise jexc.JDSSResourceNotFoundException(
                        res=volume_name)
                raise jexc.JDSSRESTException(request=req,
                                             reason=resp['error']['message'])
        raise jexc.JDSSRESTException(request=req, reason="unknown")

    def delete_lun(self, volume_name,
                   recursively_children=False,
                   recursively_dependents=False,
                   force_umount=False):
        """delete_volume.

        DELETE /volumes/<string:volumename>
        :param volume_name:
        :return:
        """
        jbody = {}
        if recursively_children:
            jbody['recursively_children'] = True

        if recursively_dependents:
            jbody['recursively_dependents'] = True

        if force_umount:
            jbody['force_umount'] = True

        req = '/volumes/' + volume_name
        LOG.debug(("delete volume:%(vol)s "
                   "recursively children:%(args)s"),
                  {'vol': volume_name,
                   'args': jbody})

        if len(jbody) > 0:
            resp = self.rproxy.pool_request('DELETE', req, json_data=jbody)
        else:
            resp = self.rproxy.pool_request('DELETE', req)

        if resp["code"] == 204:
            LOG.debug(
                "volume %s deleted", volume_name)
            return

        # Handle DNE case
        if resp["code"] == 500:
            if 'message' in resp['error']:
                if self.resource_dne_msg.match(resp['error']['message']):
                    LOG.debug("volume %s do not exists, delition success",
                              volume_name)
                    return

        # Handle volume busy
        if resp["code"] == 500 and resp["error"]:
            if resp["error"]["errno"] == 1000:
                LOG.warning(
                    "volume %s is busy", volume_name)
                raise exception.VolumeIsBusy(volume_name=volume_name)

        raise jexc.JDSSRESTException('Failed to delete volume.')

    def is_target(self, target_name):
        """is_target.

        GET /san/iscsi/targets/ target_name
        :param target_name:
        :return: Bool
        """
        req = '/san/iscsi/targets/' + target_name

        LOG.debug("check if targe %s exists", target_name)
        resp = self.rproxy.pool_request('GET', req)

        if resp["error"] or resp["code"] not in (200, 201):
            return False

        if "name" in resp["data"]:
            if resp["data"]["name"] == target_name:
                LOG.debug(
                    "target %s exists", target_name)
                return True

        return False

    def create_target(self,
                      target_name,
                      use_chap=True,
                      allow_ip=None,
                      deny_ip=None):
        """create_target.

        POST /san/iscsi/targets
        :param target_name:
        :param chap_cred:
        :param allow_ip:
        "allow_ip": [
                "192.168.2.30/0",
                "192.168.3.45"
            ],

        :return:
        """
        req = '/san/iscsi/targets'

        LOG.debug("create target %s", target_name)

        jdata = {"name": target_name, "active": True}

        jdata["incoming_users_active"] = use_chap

        if allow_ip:
            jdata["allow_ip"] = allow_ip

        if deny_ip:
            jdata["deny_ip"] = deny_ip

        resp = self.rproxy.pool_request('POST', req, json_data=jdata)

        if not resp["error"] and resp["code"] == 201:
            return

        if resp["code"] == 409:
            raise jexc.JDSSResourceExistsException(res=target_name)

        self._general_error(req, resp)

    def delete_target(self, target_name):
        """delete_target.

        DELETE /san/iscsi/targets/<target_name>
        :param pool_name:
        :param target_name:
        :return:
        """
        req = '/san/iscsi/targets/' + target_name

        LOG.debug("delete target %s", target_name)

        resp = self.rproxy.pool_request('DELETE', req)

        if resp["code"] in (200, 201, 204):
            LOG.debug(
                "target %s deleted", target_name)
            return

        not_found_err = "opene.exceptions.ItemNotFoundError"
        if (resp["code"] == 404) or \
                (resp["error"]["class"] == not_found_err):
            raise jexc.JDSSResourceNotFoundException(res=target_name)

        self._general_error(req, resp)

    def create_target_user(self, target_name, chap_cred):
        """Set CHAP credentials for accees specific target.

        POST
        /san/iscsi/targets/<target_name>/incoming-users

        :param target_name:
        :param chap_cred:
        {
            "name": "target_user",
            "password": "3e21ewqdsacxz" --- 12 chars min
        }
        :return:
        """
        req = "/san/iscsi/targets/%s/incoming-users" % target_name

        LOG.debug("add credentails to target %s", target_name)

        resp = self.rproxy.pool_request('POST', req, json_data=chap_cred)

        if not resp["error"] and resp["code"] in (200, 201, 204):
            return

        if resp['code'] == 404:
            raise jexc.JDSSResourceNotFoundException(res=target_name)

        self._general_error(req, resp)

    def get_target_user(self, target_name):
        """Get name of CHAP user for accessing target

        GET
        /san/iscsi/targets/<target_name>/incoming-users

        :param target_name:
        """
        req = "/san/iscsi/targets/%s/incoming-users" % target_name

        LOG.debug("get chap cred for target %s", target_name)

        resp = self.rproxy.pool_request('GET', req)

        if not resp["error"] and resp["code"] == 200:
            return resp['data']

        if resp['code'] == 404:
            raise jexc.JDSSResourceNotFoundException(res=target_name)

        self._general_error(req, resp)

    def delete_target_user(self, target_name, user_name):
        """Delete CHAP user for target

        DELETE
        /san/iscsi/targets/<target_name>/incoming-users/<user_name>

        :param target_name: target name
        :param user_name: user name
        """
        req = '/san/iscsi/targets/%(target)s/incoming-users/%(user)s' % {
            'target': target_name,
            'user': user_name}

        LOG.debug("remove credentails from target %s", target_name)

        resp = self.rproxy.pool_request('DELETE', req)

        if resp["error"] is None and resp["code"] == 204:
            return

        if resp['code'] == 404:
            raise jexc.JDSSResourceNotFoundException(res=target_name)

        self._general_error(req, resp)

    def is_target_lun(self, target_name, lun_name):
        """is_target_lun.

        GET /san/iscsi/targets/<target_name>/luns/<lun_name>
        :param pool_name:
        :param target_name:
        :param lun_name:
        :return: Bool
        """
        req = '/san/iscsi/targets/%(tar)s/luns/%(lun)s' % {
            'tar': target_name,
            'lun': lun_name}

        LOG.debug("check if volume %(vol)s is associated with %(tar)s",
                  {'vol': lun_name,
                   'tar': target_name})
        resp = self.rproxy.pool_request('GET', req)

        if not resp["error"] and resp["code"] == 200:
            LOG.debug("volume %(vol)s is associated with %(tar)s",
                      {'vol': lun_name,
                       'tar': target_name})
            return True

        if resp['code'] == 404:
            LOG.debug("volume %(vol)s is not associated with %(tar)s",
                      {'vol': lun_name,
                       'tar': target_name})
            return False

        self._general_error(req, resp)

    def attach_target_vol(self, target_name, lun_name, lun_id=0):
        """attach_target_vol.

        POST /san/iscsi/targets/<target_name>/luns
        :param target_name:
        :param lun_name:
        :return:
        """
        req = '/san/iscsi/targets/%s/luns' % target_name

        jbody = {"name": lun_name, "lun": lun_id}
        LOG.debug("atach volume %(vol)s to target %(tar)s",
                  {'vol': lun_name,
                   'tar': target_name})

        resp = self.rproxy.pool_request('POST', req, json_data=jbody)

        if not resp["error"] and resp["code"] == 201:
            return

        if resp['code'] == 409:
            raise jexc.JDSSResourceExistsException(res=lun_name)

        if resp['code'] == 404:
            raise jexc.JDSSResourceNotFoundException(res=target_name)

        self._general_error(req, resp)

    def detach_target_vol(self, target_name, lun_name):
        """detach_target_vol.

        DELETE /san/iscsi/targets/<target_name>/luns/
        <lun_name>
        :param target_name:
        :param lun_name:
        :return:
        """
        req = '/san/iscsi/targets/%(tar)s/luns/%(lun)s' % {
            'tar': target_name,
            'lun': lun_name}

        LOG.debug("detach volume %(vol)s from target %(tar)s",
                  {'vol': lun_name,
                   'tar': target_name})

        resp = self.rproxy.pool_request('DELETE', req)

        if resp["code"] in (200, 201, 204):
            return

        if resp['code'] == 404:
            raise jexc.JDSSResourceNotFoundException(res=lun_name)

        self._general_error(req, resp)

    def create_snapshot(self, volume_name, snapshot_name):
        """create_snapshot.

        POST /pools/<string:poolname>/volumes/<string:volumename>/snapshots
        :param pool_name:
        :param volume_name: source volume
        :param snapshot_name: snapshot name
        :return:
        """
        req = '/volumes/%s/snapshots' % volume_name

        jbody = {
            'snapshot_name': snapshot_name
        }

        LOG.debug("create snapshot %s", snapshot_name)

        resp = self.rproxy.pool_request('POST', req, json_data=jbody)

        if not resp["error"] and resp["code"] in (200, 201, 204):
            return

        if resp["code"] == 500:
            if resp["error"]:
                if resp["error"]["errno"] == 5:
                    raise jexc.JDSSSnapshotExistsException(
                        snapshot=snapshot_name)
                if resp["error"]["errno"] == 1:
                    raise jexc.JDSSVolumeNotFoundException(
                        volume=volume_name)

        self._general_error(req, resp)

    def create_volume_from_snapshot(self, volume_name, snapshot_name,
                                    original_vol_name, **options):
        """create_volume_from_snapshot.

        POST /volumes/<string:volumename>/clone
        :param volume_name: volume that is going to be created
        :param snapshot_name: slice of original volume
        :param original_vol_name: sample copy
        :return:
        """
        req = '/volumes/%s/clone' % original_vol_name

        jbody = {
            'name': volume_name,
            'snapshot': snapshot_name,
            'sparse': False
        }

        if 'sparse' in options:
            jbody['sparse'] = options['sparse']

        LOG.debug("create volume %(vol)s from snapshot %(snap)s",
                  {'vol': volume_name,
                   'snap': snapshot_name})

        resp = self.rproxy.pool_request('POST', req, json_data=jbody)

        if not resp["error"] and resp["code"] in (200, 201, 204):
            return

        if resp["code"] == 500:
            if resp["error"]:
                if resp["error"]["errno"] == 100:
                    raise jexc.JDSSVolumeExistsException(
                        volume=volume_name)
                if resp["error"]["errno"] == 1:
                    raise jexc.JDSSResourceNotFoundException(
                        res="%(vol)s@%(snap)s" % {'vol': original_vol_name,
                                                  'snap': snapshot_name})

        self._general_error(req, resp)

    def rollback_volume_to_snapshot(self, volume_name, snapshot_name):
        """Rollback volume to its snapshot

        POST /volumes/<volume_name>/snapshots/<snapshot_name>/rollback
        :param volume_name: volume that is going to be restored
        :param snapshot_name: snapshot of a volume above
        :return:
        """
        req = ('/volumes/%(vol)s/snapshots/'
               '%(snap)s/rollback') % {'vol': volume_name,
                                       'snap': snapshot_name}

        LOG.debug("rollback volume %(vol)s to snapshot %(snap)s",
                  {'vol': volume_name,
                   'snap': snapshot_name})

        resp = self.rproxy.pool_request('POST', req)

        if not resp["error"] and resp["code"] == 200:
            return

        if resp["code"] == 500:
            if resp["error"]:
                if resp["error"]["errno"] == 1:
                    raise jexc.JDSSResourceNotFoundException(
                        res="%(vol)s@%(snap)s" % {'vol': volume_name,
                                                  'snap': snapshot_name})

        self._general_error(req, resp)

    def delete_snapshot(self,
                        volume_name,
                        snapshot_name,
                        recursively_children=False,
                        recursively_dependents=False,
                        force_umount=False):
        """delete_snapshot.

        DELETE /volumes/<string:volumename>/snapshots/
            <string:snapshotname>
        :param volume_name: volume that snapshot belongs to
        :param snapshot_name: snapshot name
        :param recursively_children: boolean indicating if zfs should
            recursively destroy all children of resource, in case of snapshot
            remove all snapshots in descendant file system (default false).
        :param recursively_dependents: boolean indicating if zfs should
            recursively destroy all dependents, including cloned file systems
            outside the target hierarchy (default false).
        :param force_umount: boolean indicating if volume should be forced to
            umount (defualt false).
        :return:
        """

        req = '/volumes/%(vol)s/snapshots/%(snap)s' % {
            'vol': volume_name,
            'snap': snapshot_name}
        LOG.debug("delete snapshot %(snap)s of volume %(vol)s",
                  {'snap': snapshot_name,
                   'vol': volume_name})

        jbody = {}
        if recursively_children:
            jbody['recursively_children'] = True

        if recursively_dependents:
            jbody['recursively_dependents'] = True

        if force_umount:
            jbody['force_umount'] = True

        resp = dict()
        if len(jbody) > 0:
            resp = self.rproxy.pool_request('DELETE', req, json_data=jbody)
        else:
            resp = self.rproxy.pool_request('DELETE', req)

        if resp["code"] in (200, 201, 204):
            LOG.debug("snapshot %s deleted", snapshot_name)
            return

        if resp["code"] == 500:
            if resp["error"]:
                if resp["error"]["errno"] == 1000:
                    raise jexc.JDSSSnapshotIsBusyException(
                        snapshot=snapshot_name)
        self._general_error(req, resp)

    def get_snapshots(self, volume_name):
        """get_snapshots.

        GET
        /volumes/<string:volumename>/
            snapshots

        :param volume_name: that snapshot belongs to
        :return:
        {
            "data":
            [
                {
                    "referenced": "65536",
                    "name": "MySnapshot",
                    "defer_destroy": "off",
                    "userrefs": "0",
                    "primarycache": "all",
                    "type": "snapshot",
                    "creation": "2015-5-27 16:8:35",
                    "refcompressratio": "1.00x",
                    "compressratio": "1.00x",
                    "written": "65536",
                    "used": "0",
                    "clones": "",
                    "mlslabel": "none",
                    "secondarycache": "all"
                }
            ],
            "error": null
        }
        """
        req = '/volumes/%s/snapshots' % volume_name

        LOG.debug("get snapshots for volume %s ", volume_name)

        resp = self.rproxy.pool_request('GET', req)

        if not resp["error"] and resp["code"] == 200:
            return resp["data"]["entries"]

        if resp['code'] == 500:
            if 'message' in resp['error']:
                if self.resource_dne_msg.match(resp['error']['message']):
                    raise jexc.JDSSResourceNotFoundException(volume_name)

        self._general_error(req, resp)

    def get_pool_stats(self):
        """get_pool_stats.

        GET /pools/<string:poolname>
        :param pool_name:
        :return:
        {
          "data": {
            "available": "24433164288",
            "status": 24,
            "name": "Pool-0",
            "scan": {
              "errors": 0,
              "repaired": "0",
              "start_time": 1463476815,
              "state": "finished",
              "end_time": 1463476820,
              "type": "scrub"
            },
            "iostats": {
              "read": "0",
              "write": "0",
              "chksum": "0"
            },
            "vdevs": [
              {
                "name": "scsi-SSCST_BIOoWKF6TM0qafySQBUd1bb392e",
                "iostats": {
                  "read": "0",
                  "write": "0",
                  "chksum": "0"
                },
                "disks": [
                  {
                    "led": "off",
                    "name": "sdb",
                    "iostats": {
                      "read": "0",
                      "write": "0",
                      "chksum": "0"
                    },
                    "health": "ONLINE",
                    "sn": "d1bb392e",
                    "path": "pci-0000:04:00.0-scsi-0:0:0:0",
                    "model": "oWKF6TM0qafySQBU",
                    "id": "scsi-SSCST_BIOoWKF6TM0qafySQBUd1bb392e",
                    "size": 30064771072
                  }
                ],
                "health": "ONLINE",
                "vdev_replacings": [],
                "vdev_spares": [],
                "type": ""
              }
            ],
            "health": "ONLINE",
            "operation": "none",
            "id": "11612982948930769833",
            "size": "29796335616"
          },
          "error": null
        }
        """
        req = ""
        LOG.debug("Get pool %s fsprops", self.pool)

        resp = self.rproxy.pool_request('GET', req)
        if not resp["error"] and resp["code"] == 200:
            return resp["data"]

        self._general_error(req, resp)
