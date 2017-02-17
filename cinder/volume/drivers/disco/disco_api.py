#    copyright (c) 2016 Industrial Technology Research Institute.
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

"""DISCO Backup Service Implementation."""

import json

import requests
import six


class DiscoApi(object):
    """Class for all the requests to Disco API."""

    def __init__(self, ip, port):
        """Init client."""
        # Rest related variables
        self.req_headers = {'Content-type': 'application/json'}
        prefix_vars = {'server_ip': ip,
                       'server_port': port,
                       'api_prefix': 'RM-REST-Server/disco'}
        self.request_prefix = ("http://%(server_ip)s:%(server_port)s"
                               "/%(api_prefix)s") % prefix_vars
        self.prefix_var = {'req_prefix': self.request_prefix}

    def volumeCreate(self, volume_name, size):
        """Create a DISCO volume."""
        params = {'volumeName': volume_name, 'volumeSize': size,
                  'backupPolicyId': -1}
        data = json.dumps(params,
                          sort_keys=True,
                          indent=4,
                          separators=(',', ': '))
        request = ("%(req_prefix)s/volume" % self.prefix_var)
        r = requests.post(request, data, headers=self.req_headers)
        return r.json()

    def volumeDelete(self, volume_id):
        """Delete the temporary volume."""
        request_vars = {'req_prefix': self.request_prefix,
                        'volume_id': six.text_type(volume_id)}
        request = ("%(req_prefix)s/volume/%(volume_id)s") % request_vars
        r = requests.delete(request)
        return r.json()

    def volumeExtend(self, vol_id, size):
        """Extend DISCO volume."""
        params = {'volumeSize': six.text_type(size),
                  'volumeId': six.text_type(vol_id)}
        data = json.dumps(params,
                          sort_keys=True,
                          indent=4,
                          separators=(',', ': '))
        request = ("%(req_prefix)s/volume/extend" % self.prefix_var)
        r = requests.put(request, data, headers=self.req_headers)
        return r.json()

    def volumeDetail(self, volume_id):
        """Get volume information of the destination DISCO volume."""
        request_vars = {'req_prefix': self.request_prefix,
                        'vol_id': six.text_type(volume_id)}
        request = ("%(req_prefix)s/volume/%(vol_id)s") % request_vars
        r = requests.get(request)
        volume_info = r.json()
        return volume_info

    def volumeDetailByName(self, volume_name):
        """Get volume information of the DISCO volume."""
        request_vars = {'req_prefix': self.request_prefix,
                        'volume_name': six.text_type(volume_name)}
        request = ("%(req_prefix)s/volume?name=%(volume_name)s") % request_vars
        r = requests.get(request)
        return r.json()

    def volumeClone(self, volume_id, volume_name):
        """Clone a DISCO volume."""
        params = {'volumeName': volume_name, 'volumeId': volume_id}
        data = json.dumps(params,
                          sort_keys=True,
                          indent=4,
                          separators=(',', ': '))
        request = ("%(req_prefix)s/clone" % self.prefix_var)
        r = requests.post(request, data, headers=self.req_headers)
        return r.json()

    def cloneDetail(self, clone_id, clone_name):
        """Get detail of the clone."""
        request_vars = {'req_prefix': self.request_prefix,
                        'clone_name': clone_name,
                        'clone_id': six.text_type(clone_id)}
        request = ("%(req_prefix)s/clone?cloneId=%(clone_id)s&"
                   "name=%(clone_name)s") % request_vars
        r = requests.get(request)
        return r.json()

    def snapshotCreate(self, disco_volume_id, reserve_days, zone_id=None,
                       description=None):
        """Take a snapshot of the volume."""
        params = {'volumeId': disco_volume_id,
                  'reserveDays': reserve_days,
                  'description': description}
        data = json.dumps(params, sort_keys=True, indent=4,
                          separators=(',', ': '))

        request = ("%(req_prefix)s/snapshot" % self.prefix_var)
        r = requests.post(request, data, headers=self.req_headers)
        return r.json()

    def snapshotDelete(self, snapshot_id):
        """Delete a snapshot."""
        request_vars = {'req_prefix': self.request_prefix,
                        'snapshot_id': six.text_type(snapshot_id)}
        request = ("%(req_prefix)s/snapshot/%(snapshot_id)s") % request_vars
        r = requests.delete(request)
        return r.json()

    def snapshotDetail(self, snapshot_id):
        """Monitor end of the snapshot."""
        request_vars = {'req_prefix': self.request_prefix,
                        'snapshot_id': snapshot_id}
        request = ("%(req_prefix)s/snapshot/%(snapshot_id)s") % request_vars
        r = requests.get(request)
        return r.json()

    def restoreFromSnapshot(self, snapshot_id, volume_name, zone_id,
                            description, volume_id):
        """restore a snapshot of into a volume."""
        params = {'snapshotId': snapshot_id,
                  'volumeName': volume_name,
                  'zone_id': zone_id,
                  'description': "local restore snapshot",
                  'volumeId': volume_id}
        data = json.dumps(params,
                          sort_keys=True,
                          indent=4,
                          separators=(',', ': '))
        request = ("%(req_prefix)s/restore" % self.prefix_var)
        r = requests.post(request, data, headers=self.req_headers)
        return r.json()

    def restoreDetail(self, restore_id):
        """Monitor end of the restore."""
        request_vars = {'req_prefix': self.request_prefix,
                        'restore_id': restore_id}
        request = ("%(req_prefix)s/restore/%(restore_id)s") % request_vars
        r = requests.get(request)
        return r.json()

    def systemInformationList(self):
        """Get the list of the system information."""
        request = ("%(req_prefix)s/systemInformationList") % self.prefix_var
        r = requests.get(request)
        return r.json()
