# Copyright (c) 2016 EMC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import oslo_serialization

from cinder.i18n import _
from cinder.volume.drivers.coprhd.helpers import commoncoprhdapi as common
from cinder.volume.drivers.coprhd.helpers import consistencygroup
from cinder.volume.drivers.coprhd.helpers import volume


class Snapshot(common.CoprHDResource):

    # Commonly used URIs for the 'Snapshot' module
    URI_SNAPSHOTS = '/{0}/snapshots/{1}'
    URI_BLOCK_SNAPSHOTS = '/block/snapshots/{0}'
    URI_SEARCH_SNAPSHOT_BY_TAG = '/block/snapshots/search?tag={0}'
    URI_SNAPSHOT_LIST = '/{0}/{1}/{2}/protection/snapshots'
    URI_SNAPSHOT_TASKS_BY_OPID = '/vdc/tasks/{0}'
    URI_RESOURCE_DEACTIVATE = '{0}/deactivate'
    URI_CONSISTENCY_GROUP = "/block/consistency-groups"
    URI_CONSISTENCY_GROUPS_SNAPSHOT_INSTANCE = (
        URI_CONSISTENCY_GROUP + "/{0}/protection/snapshots/{1}")
    URI_CONSISTENCY_GROUPS_SNAPSHOT_DEACTIVATE = (
        URI_CONSISTENCY_GROUPS_SNAPSHOT_INSTANCE + "/deactivate")
    URI_BLOCK_SNAPSHOTS_TAG = URI_BLOCK_SNAPSHOTS + '/tags'

    VOLUMES = 'volumes'
    CG = 'consistency-groups'
    BLOCK = 'block'

    timeout = 300

    def snapshot_list_uri(self, otype, otypename, ouri):
        """Makes REST API call to list snapshots under a volume.

        :param otype: block
        :param otypename: either volume or consistency-group should be
                          provided
        :param ouri: uri of volume or consistency-group
        :returns: list of snapshots
        """
        (s, h) = common.service_json_request(
            self.ipaddr, self.port,
            "GET",
            Snapshot.URI_SNAPSHOT_LIST.format(otype, otypename, ouri), None)
        o = common.json_decode(s)
        return o['snapshot']

    def snapshot_show_uri(self, otype, resource_uri, suri):
        """Retrieves snapshot details based on snapshot Name or Label.

        :param otype: block
        :param suri: uri of the Snapshot.
        :param resource_uri: uri of the source resource
        :returns: Snapshot details in JSON response payload
        """
        if(resource_uri is not None and
           resource_uri.find('BlockConsistencyGroup') > 0):
            (s, h) = common.service_json_request(
                self.ipaddr, self.port,
                "GET",
                Snapshot.URI_CONSISTENCY_GROUPS_SNAPSHOT_INSTANCE.format(
                    resource_uri,
                    suri),
                None)
        else:
            (s, h) = common.service_json_request(
                self.ipaddr, self.port,
                "GET",
                Snapshot.URI_SNAPSHOTS.format(otype, suri), None)

        return common.json_decode(s)

    def snapshot_query(self, storageres_type,
                       storageres_typename, resuri, snapshot_name):
        if resuri is not None:
            uris = self.snapshot_list_uri(
                storageres_type,
                storageres_typename,
                resuri)
            for uri in uris:
                snapshot = self.snapshot_show_uri(
                    storageres_type,
                    resuri,
                    uri['id'])
                if (False == common.get_node_value(snapshot, 'inactive') and
                        snapshot['name'] == snapshot_name):
                    return snapshot['id']

        raise common.CoprHdError(
            common.CoprHdError.SOS_FAILURE_ERR,
            (_("snapshot with the name: "
               "%s Not Found") % snapshot_name))

    def storage_resource_query(self,
                               storageres_type,
                               volume_name,
                               cg_name,
                               project,
                               tenant):
        resourcepath = "/" + project
        if tenant is not None:
            resourcepath = tenant + resourcepath

        resUri = None
        resourceObj = None
        if Snapshot.BLOCK == storageres_type and volume_name is not None:
            resourceObj = volume.Volume(self.ipaddr, self.port)
            resUri = resourceObj.volume_query(resourcepath, volume_name)
        elif Snapshot.BLOCK == storageres_type and cg_name is not None:
            resourceObj = consistencygroup.ConsistencyGroup(
                self.ipaddr,
                self.port)
            resUri = resourceObj.consistencygroup_query(
                cg_name,
                project,
                tenant)
        else:
            resourceObj = None

        return resUri

    def snapshot_create(self, otype, typename, ouri,
                        snaplabel, inactive, sync,
                        readonly=False, synctimeout=0):
        """New snapshot is created, for a given volume.

        :param otype: block type should be provided
        :param typename: either volume or consistency-groups should
                         be provided
        :param ouri: uri of volume
        :param snaplabel: name of the snapshot
        :param inactive: if true, the snapshot will not activate the
                         synchronization between source and target volumes
        :param sync: synchronous request
        :param synctimeout: Query for task status for 'synctimeout' secs.
                            If the task doesn't complete in synctimeout secs,
                            an exception is thrown
        """

        # check snapshot is already exist
        is_snapshot_exist = True
        try:
            self.snapshot_query(otype, typename, ouri, snaplabel)
        except common.CoprHdError as e:
            if e.err_code == common.CoprHdError.NOT_FOUND_ERR:
                is_snapshot_exist = False
            else:
                raise

        if is_snapshot_exist:
            raise common.CoprHdError(
                common.CoprHdError.ENTRY_ALREADY_EXISTS_ERR,
                (_("Snapshot with name %(snaplabel)s"
                   " already exists under %(typename)s") %
                 {'snaplabel': snaplabel,
                  'typename': typename
                  }))

        parms = {
            'name': snaplabel,
            # if true, the snapshot will not activate the synchronization
            # between source and target volumes
            'create_inactive': inactive
        }
        if readonly is True:
            parms['read_only'] = readonly
        body = oslo_serialization.jsonutils.dumps(parms)

        # REST api call
        (s, h) = common.service_json_request(
            self.ipaddr, self.port,
            "POST",
            Snapshot.URI_SNAPSHOT_LIST.format(otype, typename, ouri), body)
        o = common.json_decode(s)

        task = o["task"][0]

        if sync:
            return (
                common.block_until_complete(
                    otype,
                    task['resource']['id'],
                    task["id"], self.ipaddr, self.port, synctimeout)
            )
        else:
            return o

    def snapshot_delete_uri(self, otype, resource_uri,
                            suri, sync, synctimeout=0):
        """Delete a snapshot by uri.

        :param otype: block
        :param resource_uri: uri of the source resource
        :param suri: Uri of the Snapshot
        :param sync: To perform operation synchronously
        :param synctimeout: Query for task status for 'synctimeout' secs. If
                            the task doesn't complete in synctimeout secs,
                            an exception is thrown
        """
        s = None
        if resource_uri.find("Volume") > 0:

            (s, h) = common.service_json_request(
                self.ipaddr, self.port,
                "POST",
                Snapshot.URI_RESOURCE_DEACTIVATE.format(
                    Snapshot.URI_BLOCK_SNAPSHOTS.format(suri)),
                None)
        elif resource_uri.find("BlockConsistencyGroup") > 0:

            (s, h) = common.service_json_request(
                self.ipaddr, self.port,
                "POST",
                Snapshot.URI_CONSISTENCY_GROUPS_SNAPSHOT_DEACTIVATE.format(
                    resource_uri,
                    suri),
                None)
        o = common.json_decode(s)
        task = o["task"][0]

        if sync:
            return (
                common.block_until_complete(
                    otype,
                    task['resource']['id'],
                    task["id"], self.ipaddr, self.port, synctimeout)
            )
        else:
            return o

    def snapshot_delete(self, storageres_type,
                        storageres_typename, resource_uri,
                        name, sync, synctimeout=0):
        snapshotUri = self.snapshot_query(
            storageres_type,
            storageres_typename,
            resource_uri,
            name)
        self.snapshot_delete_uri(
            storageres_type,
            resource_uri,
            snapshotUri,
            sync, synctimeout)
