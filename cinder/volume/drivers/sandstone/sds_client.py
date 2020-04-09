# Copyright (c) 2019 ShenZhen SandStone Data Technologies Co., Ltd.
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
"""SandStone iSCSI Driver."""

import hashlib
import json
import re
import time

from oslo_log import log as logging
import requests
import six

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.sandstone import constants

LOG = logging.getLogger(__name__)


class RestCmd(object):
    """Restful api class."""

    def __init__(self, address, user, password,
                 suppress_requests_ssl_warnings):
        """Init RestCmd class.

        :param address: Restapi uri.
        :param user: login web username.
        :param password: login web password.
        """
        self.address = "https://%(address)s" % {"address": address}
        self.user = user
        self.password = password
        self.pagesize = constants.PAGESIZE
        self.session = None
        self.short_wait = 10
        self.long_wait = 12000
        self.debug = True
        self._init_http_header()

    def _init_http_header(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip, deflate",
        })
        self.session.verify = False

    def run(self, url, method, data=None, json_flag=True,
            filter_flag=False, om_op_flag=False):
        """Run rest cmd function.

        :param url: rest api uri resource.
        :param data: rest api uri json parameter.
        :param filter_flag: controller whether filter log. (default 'No')
        :param om_op_flag: api op have basic and om, use different prefix uri.
        """
        kwargs = {}
        if data:
            kwargs["data"] = json.dumps(data)
        if om_op_flag:
            rest_url = self.address + constants.OM_URI + url
        else:
            rest_url = self.address + constants.BASIC_URI + url

        func = getattr(self.session, method.lower())
        try:
            result = func(rest_url, **kwargs)
        except requests.RequestException as err:
            msg = _('Bad response from server: %(url)s. '
                    'Error: %(err)s') % {'url': rest_url, 'err': err}
            raise exception.VolumeBackendAPIException(msg)

        try:
            result.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response.status_code == constants.CONNECT_ERROR:
                try:
                    self.login()
                except requests.ConnectTimeout as err:
                    msg = (_("Sandstone web server may be abnormal "
                             "or storage may be poweroff. Error: %(err)s")
                           % {'err': err})
                    raise exception.VolumeBackendAPIException(msg)
            else:
                return {"error": {"code": exc.response.status_code,
                                  "description": six.text_type(exc)}}

        if not filter_flag:
            LOG.info('''
            Request URL: %(url)s,
            Call Method: %(method)s,
            Request Data: %(data)s,
            Response Data: %(res)s,
            Result Data: %(res_json)s.''', {'url': url, 'method': method,
                                            'data': data, 'res': result,
                                            'res_json': result.json()})

        if json_flag:
            return result.json()
        return result

    def _assert_restapi_result(self, result, err):
        if result.get("success") != 1:
            msg = (_('%(err)s\nresult:%(res)s') % {"err": err,
                                                   "res": result})
            raise exception.VolumeBackendAPIException(data=msg)

    def login(self):
        """Login web get with token session."""
        url = 'user/login'

        sha256 = hashlib.sha256()
        sha256.update(self.password.encode("utf8"))
        password = sha256.hexdigest()

        data = {"username": self.user, "password": password}
        result = self.run(url=url, data=data, method='POST', json_flag=False,
                          om_op_flag=True)
        self._assert_restapi_result(result.json(), _('Login error.'))
        cookies = result.cookies
        set_cookie = result.headers['Set-Cookie']
        self.session.headers['Cookie'] = ';'.join(
            ['XSRF-TOKEN={}'.format(cookies['XSRF-TOKEN']),
             ' username={}'.format(self.user),
             ' sdsom_sessionid={}'.format(self._find_sessionid(set_cookie))])
        self.session.headers["Referer"] = self.address
        self.session.headers["X-XSRF-TOKEN"] = cookies["XSRF-TOKEN"]

    def _find_sessionid(self, headers):
        sessionid = re.findall("sdsom_sessionid=(\\w+);", headers)
        if sessionid:
            return sessionid[0]
        return ""

    def _check_special_result(self, result, contain):
        if result.get("success") == 0 and contain in result.get("data"):
            return True

    def logout(self):
        """Logout release resource."""
        url = 'user/logout'
        data = {"username": self.user}
        result = self.run(url, 'POST', data=data,
                          om_op_flag=True)
        self._assert_restapi_result(result, _("Logout out error."))

    def query_capacity_info(self):
        """Query cluster capacity."""
        url = 'capacity'
        capacity_info = {}

        result = self.run(url, 'POST', filter_flag=True)
        self._assert_restapi_result(result, _("Query capacity error."))
        capacity_info["capacity_bytes"] = result["data"].get(
            "capacity_bytes", 0)
        capacity_info["free_bytes"] = result["data"].get("free_bytes", 0)
        return capacity_info

    def query_pool_info(self):
        """Query use pool status."""
        url = 'pool/list'

        result = self.run(url, 'POST')
        self._assert_restapi_result(result, _("Query pool status error."))
        return result["data"]

    def get_poolid_from_poolname(self):
        """Use poolname get poolid from pool/list maps."""
        data = self.query_pool_info()
        poolname_map_poolid = {}
        if data:
            for pool in data:
                poolname_map_poolid[pool["realname"]] = pool["pool_id"]
        return poolname_map_poolid

    def create_initiator(self, initiator_name):
        """Create client iqn in storage cluster."""
        url = 'resource/initiator/create'
        data = {"iqn": initiator_name, "type": "iSCSI",
                "remark": "Cinder iSCSI"}
        result = self.run(url, 'POST', data=data)
        # initiator exist, return no err.
        if self._check_special_result(result, "already exist"):
            return
        self._assert_restapi_result(result, _("Create initiator error."))

    def _delaytask_list(self, pagesize=20):
        url = 'delaytask/list'
        data = {"pageno": 1, "pagesize": pagesize}
        return self.run(url, 'POST', data=data, om_op_flag=True)

    def _judge_delaytask_status(self, wait_time, func_name, *args):
        # wait 10 seconds for task
        func = getattr(self, func_name.lower())
        for wait in range(1, wait_time + 1):
            try:
                task_status = func(*args)
                if self.debug:
                    LOG.info(task_status)
            except exception.VolumeBackendAPIException as exc:
                msg = (_("Task: run %(task)s failed, "
                         "err: %(err)s.")
                       % {"task": func_name,
                          "err": exc})
                LOG.error(msg)
            if task_status.get('run_status') == "failed":
                msg = (_("Task : run %(task)s failed, "
                         "parameter : %(parameter)s, "
                         "progress is %(process)d.")
                       % {"task": func_name,
                          "process": task_status.get('progress'),
                          "parameter": args})
                raise exception.VolumeBackendAPIException(data=msg)
            elif task_status.get('run_status') != "completed":
                msg = (_("Task : running %(task)s , "
                         "parameter : %(parameter)s, "
                         "progress is %(process)d, "
                         "waited for 1 second, "
                         "total waited %(total)d second.")
                       % {"task": func_name,
                          "process": task_status.get('progress', 0),
                          "parameter": args,
                          "total": wait})
                LOG.info(msg)
                time.sleep(1)
            elif task_status.get('run_status') == "completed":
                msg = (_("Task : running %(task)s successfully, "
                         "parameter : %(parameter)s, "
                         "progress is %(process)d, "
                         "total spend %(total)d second.")
                       % {"task": func_name,
                          "process": task_status.get('progress'),
                          "parameter": args,
                          "total": wait})
                LOG.info(msg)
                break

    def add_initiator_to_target(self, target_name, initiator_name):
        """Bind client iqn to storage target iqn."""
        url = 'resource/target/add_initiator_to_target'
        data = {"targetName": target_name,
                "iqns": [{"ip": "", "iqn": initiator_name}]}
        result = self.run(url, 'POST', data=data)
        # wait 10 seconds to map initiator
        self._judge_delaytask_status(self.short_wait,
                                     "query_map_initiator_porcess",
                                     target_name, initiator_name)
        self._assert_restapi_result(result, _("Add initiator "
                                              "to target error."))

    def query_map_initiator_porcess(self, target_name,
                                    initiator_name):
        """Query initiator add to target process."""
        result = self._delaytask_list()
        self._assert_restapi_result(result, _("Query mapping "
                                              "initiator process error."))

        result = result["data"].get("results", None) or []
        expected_parameter = [{"target_name": target_name,
                               "iqns": [{"ip": "", "iqn": initiator_name}]}]
        task = [map_initiator_task for map_initiator_task in result
                if map_initiator_task["executor"] == "MapInitiator"
                and map_initiator_task["parameter"] == expected_parameter]
        if task:
            return task[0]
        return {}

    def query_initiator_by_name(self, initiator_name):
        """Query initiator exist or not."""
        url = 'resource/initiator/list'
        data = {"initiatorMark": "", "pageno": 1,
                "pagesize": self.pagesize, "type": "iSCSI"}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Query initiator "
                                              "by name error."))

        result = result["data"].get("results", None) or []
        initiator_info = [initiator for initiator in result
                          if initiator.get("iqn", None) == initiator_name]
        if initiator_info:
            return initiator_info[0]
        return None

    def query_target_initiatoracl(self, target_name, initiator_name):
        """Query target iqn bind client iqn info."""
        url = 'resource/target/get_target_acl_list'
        data = {"pageno": 1, "pagesize": self.pagesize,
                "targetName": target_name}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Query target "
                                              "initiatoracl error."))

        results = result["data"].get("results", None)
        acl_info = [acl for acl in results or []
                    if acl.get("name", None) == initiator_name]
        return acl_info or None

    def query_node_by_targetips(self, target_ips):
        """Query target ip relation with node."""
        url = 'block/gateway/server/list'
        result = self.run(url, 'POST')
        self._assert_restapi_result(result, _("Query node by "
                                              "targetips error."))

        targetip_to_hostid = {}
        for node in result["data"]:
            for node_access_ip in node.get("networks"):
                goal_ip = node_access_ip.get("address")
                if goal_ip in target_ips:
                    targetip_to_hostid[goal_ip] =\
                        node_access_ip.get("hostid", None)
        return targetip_to_hostid

    def query_target_by_name(self, target_name):
        """Query target iqn exist or not."""
        url = 'resource/target/list'
        data = {"pageno": 1, "pagesize": self.pagesize,
                "thirdParty": [0, 1], "targetMark": ""}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Query target by name error."))

        result = result["data"].get("results", None) or []
        target_info = [target for target in result
                       if target.get("name", None) == target_name]
        if target_info:
            return target_info[0]
        return None

    def create_target(self, target_name, targetip_to_hostid):
        """Create target iqn."""
        url = 'resource/target/create'
        data = {"type": "iSCSI", "readOnly": 0,
                "thirdParty": 1, "targetName": target_name,
                "networks": [{"hostid": host_id, "address": address}
                             for address, host_id in
                             targetip_to_hostid.items()]}
        result = self.run(url, 'POST', data=data)
        # target exist, return no err.
        if self._check_special_result(result, "already exist"):
            return
        self._assert_restapi_result(result, _("Create target error."))

    def add_chap_by_target(self, target_name, username, password):
        """Add chap to target, only support forward."""
        url = 'resource/target/add_chap'
        data = {"password": password,
                "user": username, "targetName": target_name}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Add chap by target error."))

    def query_chapinfo_by_target(self, target_name, username):
        """Query chapinfo by target, check chap add target or not."""
        url = 'resource/target/get_chap_list'
        data = {"targetName": target_name}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Query chapinfo "
                                              "by target error."))

        result = result.get('data') or []
        chapinfo = [c for c in result if c.get("user") == username]
        if chapinfo:
            return chapinfo[0]
        return None

    def create_lun(self, capacity_bytes, poolid, volume_name):
        """Create lun resource."""
        url = 'resource/lun/add'
        data = {"capacity_bytes": capacity_bytes,
                "poolId": poolid, "priority": "normal",
                "qosSettings": {}, "volumeName": volume_name}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Create lun error."))

    def delete_lun(self, poolid, volume_name):
        """Delete lun resource."""
        url = 'resource/lun/batch_delete'
        data = {"delayTime": 0, "volumeNameList": [{
            "poolId": poolid,
            "volumeName": volume_name}]}
        result = self.run(url, 'POST', data=data)
        # lun deleted, return no err.
        if self._check_special_result(result, "not found"):
            return
        self._assert_restapi_result(result, _("Delete lun error."))

    def extend_lun(self, capacity_bytes, poolid, volume_name):
        """Extend lun, only support enlarge."""
        url = 'resource/lun/resize'

        data = {"capacity_bytes": capacity_bytes,
                "poolId": poolid,
                "volumeName": volume_name}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Extend lun error."))

    def unmap_lun(self, target_name, poolid, volume_name, pool_name):
        """Unbind lun from target iqn."""
        url = 'resource/target/unmap_luns'
        volume_info = self.query_lun_by_name(volume_name, poolid)
        result = {"success": 0}
        if volume_info:
            uuid = volume_info.get("uuid", None)
            data = {"targetName": target_name,
                    "targetLunList": [uuid],
                    "targetSnapList": []}
            result = self.run(url, 'POST', data=data)
            # lun unmaped, return no err.
            if self._check_special_result(result, "not mapped"):
                return
            # wait for 10 seconds to unmap lun.
            self._judge_delaytask_status(self.short_wait,
                                         "query_unmapping_lun_porcess",
                                         target_name, volume_name,
                                         uuid, pool_name)
            self._assert_restapi_result(result, _("Unmap lun error."))
        else:
            self._assert_restapi_result(result,
                                        _("Unmap lun error, uuid is None."))

    def mapping_lun(self, target_name, poolid, volume_name, pool_name):
        """Bind lun to target iqn."""
        url = 'resource/target/map_luns'
        volume_info = self.query_lun_by_name(volume_name, poolid)
        result = {"success": 0}
        if volume_info:
            uuid = volume_info.get("uuid", None)
            data = {"targetName": target_name,
                    "targetLunList": [uuid],
                    "targetSnapList": []}
            result = self.run(url, 'POST', data=data)
            # lun maped, return no err.
            if self._check_special_result(result, "already mapped"):
                return
            # wait for 10 seconds to map lun.
            self._judge_delaytask_status(self.short_wait,
                                         "query_mapping_lun_porcess",
                                         target_name, volume_name,
                                         uuid, pool_name)
            self._assert_restapi_result(result, _("Map lun error."))
        else:
            self._assert_restapi_result(result,
                                        _("Map lun error, uuid is None."))

    def query_mapping_lun_porcess(self, target_name, volume_name,
                                  uuid, pool_name):
        """Query mapping lun process."""
        result = self._delaytask_list()
        self._assert_restapi_result(result, _("Query mapping "
                                              "lun process error."))

        expected_parameter = {"target_name": target_name,
                              "image_id": uuid,
                              "target_realname": target_name,
                              "meta_pool": pool_name,
                              "image_realname": volume_name}
        result = result["data"].get("results", None) or []
        task = [map_initiator_task for map_initiator_task in result
                if map_initiator_task["executor"] == "TargetMap"
                and map_initiator_task["parameter"] == expected_parameter]
        if task:
            return task[0]
        return {}

    def query_unmapping_lun_porcess(self, target_name, volume_name,
                                    uuid, pool_name):
        """Query mapping lun process."""
        result = self._delaytask_list()
        self._assert_restapi_result(result, _("Query mapping "
                                              "lun process error."))

        expected_parameter = {"target_name": target_name,
                              "image_id": uuid,
                              "target_realname": target_name,
                              "meta_pool": pool_name,
                              "image_name": volume_name}
        result = result["data"].get("results", None) or []
        task = [map_initiator_task for map_initiator_task in result
                if map_initiator_task["executor"] == "TargetUnmap"
                and map_initiator_task["parameter"] == expected_parameter]
        if task:
            return task[0]
        return {}

    def query_target_lunacl(self, target_name, poolid, volume_name):
        """Query target iqn relation with lun."""
        url = 'resource/target/get_luns'
        data = {"pageno": 1, "pagesize": self.pagesize,
                "pools": [poolid], "targetName": target_name}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Query target lunacl error."))

        # target get_luns use results
        result = result["data"].get("results", None) or []
        lunid = [volume.get("lid", None) for volume in result
                 if volume.get("name", None) == volume_name
                 and volume.get("pool_id") == poolid]
        if lunid:
            return lunid[0]
        return None

    def query_lun_by_name(self, volume_name, poolid):
        """Query lun exist or not."""
        url = 'resource/lun/list'
        data = {"pageno": 1, "pagesize": self.pagesize,
                "volumeMark": volume_name,
                "sortType": "time", "sortOrder": "desc",
                "pools": [poolid], "thirdParty": [0, 1]}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Query lun by name error."))

        result = result["data"].get("results", None) or []
        volume_info = [volume for volume in result
                       if volume.get("volumeName", None) == volume_name]
        if volume_info:
            return volume_info[0]
        return None

    def query_target_by_lun(self, volume_name, poolid):
        """Query lun already mapped target name."""
        url = "resource/lun/targets"
        data = {"poolId": poolid, "volumeName": volume_name}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Query target by lun error."))

        data = result["data"]
        target_name = data[0].get("name", None)
        return target_name

    def create_snapshot(self, poolid, volume_name, snapshot_name):
        """Create lun snapshot."""
        url = 'resource/snapshot/add'
        data = {"lunName": volume_name,
                "poolId": poolid,
                "remark": "Cinder iSCSI snapshot.",
                "snapName": snapshot_name}
        result = self.run(url, 'POST', data=data)
        # snapshot existed, return no err.
        if self._check_special_result(result, "has exists"):
            return
        # wait for 10 seconds to create snapshot
        self._judge_delaytask_status(self.short_wait,
                                     "query_create_snapshot_process",
                                     poolid, volume_name, snapshot_name)
        self._assert_restapi_result(result, _("Create snapshot error."))

    def query_create_snapshot_process(self, poolid,
                                      volume_name, snapshot_name):
        """Query create snapshot process."""
        result = self._delaytask_list()
        self._assert_restapi_result(result, _("Query flatten "
                                              "lun process error."))
        result = result["data"].get("results", None) or []
        task = [flatten_task for flatten_task in result
                if flatten_task["executor"] == "SnapCreate"
                and flatten_task["parameter"].get("pool_id", None)
                == poolid
                and flatten_task["parameter"].get("snap_name", None)
                == snapshot_name
                and flatten_task["parameter"].get("lun_name", None)
                == volume_name]

        if task:
            return task[0]
        return {}

    def delete_snapshot(self, poolid, volume_name, snapshot_name):
        """Delete lun snapshot."""
        url = 'resource/snapshot/delete'
        data = {"lunName": volume_name,
                "poolId": poolid, "snapName": snapshot_name}
        result = self.run(url, 'POST', data=data)
        # snapshot deleted, need return no err.
        if self._check_special_result(result, "not found"):
            return
        # wait for 10 seconds to delete snapshot
        self._judge_delaytask_status(self.short_wait,
                                     "query_delete_snapshot_process",
                                     poolid, volume_name, snapshot_name)
        self._assert_restapi_result(result, _("Delete snapshot error."))

    def query_delete_snapshot_process(self, poolid,
                                      volume_name, snapshot_name):
        """Query delete snapshot process."""
        result = self._delaytask_list()
        self._assert_restapi_result(result, _("Query delete "
                                              "snapshot process error."))
        result = result["data"].get("results", None) or []
        task = [flatten_task for flatten_task in result
                if flatten_task["executor"] == "SnapDelete"
                and flatten_task["parameter"].get("pool_id", None)
                == poolid
                and flatten_task["parameter"].get("snap_name", None)
                == snapshot_name
                and flatten_task["parameter"].get("lun_name", None)
                == volume_name]

        if task:
            return task[0]
        return {}

    def create_lun_from_snapshot(self, snapshot_name, src_volume_name,
                                 poolid, dst_volume_name):
        """Create lun from source lun snapshot."""
        url = 'resource/snapshot/clone'
        data = {"snapshot": {"poolId": poolid,
                             "lunName": src_volume_name,
                             "snapName": snapshot_name},
                "cloneLun": {"lunName": dst_volume_name,
                             "poolId": poolid}}
        result = self.run(url, 'POST', data=data)
        # clone volume exsited, return no err.
        if self._check_special_result(result, "already exists"):
            return
        # wait for 10 seconds to clone lun
        self._judge_delaytask_status(self.short_wait,
                                     "query_clone_lun_process",
                                     poolid, src_volume_name, snapshot_name)
        self._assert_restapi_result(result, _("Create lun "
                                              "from snapshot error."))
        self.flatten_lun(dst_volume_name, poolid)

    def query_clone_lun_process(self, poolid, volume_name, snapshot_name):
        """Query clone lun process."""
        result = self._delaytask_list()
        self._assert_restapi_result(result, _("Query flatten "
                                              "lun process error."))
        result = result["data"].get("results", None) or []
        task = [flatten_task for flatten_task in result
                if flatten_task["executor"] == "SnapClone"
                and flatten_task["parameter"].get("pool_id", None)
                == poolid
                and flatten_task["parameter"].get("snap_name", None)
                == snapshot_name
                and flatten_task["parameter"].get("lun_name", None)
                == volume_name]

        if task:
            return task[0]
        return {}

    def flatten_lun(self, volume_name, poolid):
        """Flatten lun."""
        url = 'resource/lun/flatten'
        data = {"poolId": poolid,
                "volumeName": volume_name}
        result = self.run(url, 'POST', data=data)
        # volume flattened, return no err.
        if self._check_special_result(result, "not need flatten"):
            return
        # wait for longest 200 min to flatten
        self._judge_delaytask_status(self.long_wait,
                                     "query_flatten_lun_process",
                                     poolid, volume_name)
        self._assert_restapi_result(result, _("Flatten lun error."))

    def query_flatten_lun_process(self, poolid, volume_name):
        """Query flatten lun process."""
        result = self._delaytask_list()
        self._assert_restapi_result(result, _("Query flatten "
                                              "lun process error."))
        result = result["data"].get("results", None) or []
        task = [flatten_task for flatten_task in result
                if flatten_task["executor"] == "LunFlatten"
                and flatten_task["parameter"].get("pool_id", None)
                == poolid
                and flatten_task["parameter"].get("lun_name", None)
                == volume_name]
        if task:
            return task[0]
        return {}

    def create_lun_from_lun(self, dst_volume_name, poolid, src_volume_name):
        """Clone lun from source lun."""
        tmp_snapshot_name = 'temp' + src_volume_name + 'clone' +\
                            dst_volume_name
        self.create_snapshot(poolid, src_volume_name, tmp_snapshot_name)
        self.create_lun_from_snapshot(tmp_snapshot_name, src_volume_name,
                                      poolid, dst_volume_name)
        self.flatten_lun(dst_volume_name, poolid)

        self.delete_snapshot(poolid, src_volume_name, tmp_snapshot_name)

    def query_snapshot_by_name(self, volume_name, poolid, snapshot_name):
        """Query snapshot exist or not."""
        url = 'resource/snapshot/list'
        data = {"lunName": volume_name, "pageno": 1,
                "pagesize": self.pagesize, "poolId": poolid,
                "snapMark": ""}
        result = self.run(url, 'POST', data=data)
        self._assert_restapi_result(result, _("Query snapshot by name error."))

        result = result["data"].get("results", None) or []
        snapshot_info = [snapshot for snapshot in result
                         if snapshot.get("snapName", None) ==
                         snapshot_name]
        return snapshot_info
