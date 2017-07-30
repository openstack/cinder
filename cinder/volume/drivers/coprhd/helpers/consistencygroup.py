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
from cinder.volume.drivers.coprhd.helpers import project


class ConsistencyGroup(common.CoprHDResource):

    URI_CONSISTENCY_GROUP = "/block/consistency-groups"
    URI_CONSISTENCY_GROUPS_INSTANCE = URI_CONSISTENCY_GROUP + "/{0}"
    URI_CONSISTENCY_GROUPS_DEACTIVATE = (URI_CONSISTENCY_GROUPS_INSTANCE +
                                         "/deactivate")
    URI_CONSISTENCY_GROUPS_SEARCH = (
        '/block/consistency-groups/search?project={0}')
    URI_SEARCH_CONSISTENCY_GROUPS_BY_TAG = (
        '/block/consistency-groups/search?tag={0}')
    URI_CONSISTENCY_GROUP_TAGS = (
        '/block/consistency-groups/{0}/tags')

    def list(self, project_name, tenant):
        """This function gives list of comma separated consistency group uris.

        :param project_name: Name of the project path
        :param tenant: Name of the tenant
        :returns: list of consistency group ids separated by comma
        """
        if tenant is None:
            tenant = ""
        projobj = project.Project(self.ipaddr, self.port)
        fullproj = tenant + "/" + project_name
        projuri = projobj.project_query(fullproj)

        (s, h) = common.service_json_request(
            self.ipaddr, self.port, "GET",
            self.URI_CONSISTENCY_GROUPS_SEARCH.format(projuri), None)
        o = common.json_decode(s)
        if not o:
            return []

        congroups = []
        resources = common.get_node_value(o, "resource")
        for resource in resources:
            congroups.append(resource["id"])

        return congroups

    def show(self, name, project, tenant):
        """This function will display the consistency group with details.

        :param name: Name of the consistency group
        :param project: Name of the project
        :param tenant: Name of the tenant
        :returns: details of consistency group
        """
        uri = self.consistencygroup_query(name, project, tenant)
        (s, h) = common.service_json_request(
            self.ipaddr, self.port, "GET",
            self.URI_CONSISTENCY_GROUPS_INSTANCE.format(uri), None)
        o = common.json_decode(s)
        if o['inactive']:
            return None
        return o

    def consistencygroup_query(self, name, project, tenant):
        """This function will return consistency group id.

        :param name: Name/id of the consistency group
        :param project: Name of the project
        :param tenant: Name of the tenant
        :returns: id of the consistency group
        """
        if common.is_uri(name):
            return name

        uris = self.list(project, tenant)
        for uri in uris:
            congroup = self.show(uri, project, tenant)
            if congroup and congroup['name'] == name:
                return congroup['id']
        raise common.CoprHdError(common.CoprHdError.NOT_FOUND_ERR,
                                 (_("Consistency Group %s: not found") % name))

    # Blocks the operation until the task is complete/error out/timeout
    def check_for_sync(self, result, sync, synctimeout=0):
        if len(result["resource"]) > 0:
            resource = result["resource"]
            return (
                common.block_until_complete("consistencygroup", resource["id"],
                                            result["id"], self.ipaddr,
                                            self.port, synctimeout)
            )
        else:
            raise common.CoprHdError(
                common.CoprHdError.SOS_FAILURE_ERR,
                _("error: task list is empty, no task response found"))

    def create(self, name, project_name, tenant):
        """This function will create consistency group with the given name.

        :param name: Name of the consistency group
        :param project_name: Name of the project path
        :param tenant: Container tenant name
        :returns: status of creation
        """
        # check for existence of consistency group.
        try:
            status = self.show(name, project_name, tenant)
        except common.CoprHdError as e:
            if e.err_code == common.CoprHdError.NOT_FOUND_ERR:
                if tenant is None:
                    tenant = ""
                fullproj = tenant + "/" + project_name
                projobj = project.Project(self.ipaddr, self.port)
                projuri = projobj.project_query(fullproj)

                parms = {'name': name, 'project': projuri, }
                body = oslo_serialization.jsonutils.dumps(parms)

                (s, h) = common.service_json_request(
                    self.ipaddr, self.port, "POST",
                    self.URI_CONSISTENCY_GROUP, body)

                o = common.json_decode(s)
                return o
            else:
                raise
        if status:
            common.format_err_msg_and_raise(
                "create", "consistency group",
                (_("consistency group with name: %s already exists") % name),
                common.CoprHdError.ENTRY_ALREADY_EXISTS_ERR)

    def delete(self, name, project, tenant, coprhdonly=False):
        """This function marks a particular consistency group as delete.

        :param name: Name of the consistency group
        :param project: Name of the project
        :param tenant: Name of the tenant
        :returns: status of the delete operation
            false, incase it fails to do delete
        """
        params = ''
        if coprhdonly is True:
            params += "?type=" + 'CoprHD_ONLY'
        uri = self.consistencygroup_query(name, project, tenant)
        (s, h) = common.service_json_request(
            self.ipaddr, self.port,
            "POST",
            self.URI_CONSISTENCY_GROUPS_DEACTIVATE.format(uri) + params,
            None)
        return

    def update(self, uri, project, tenant, add_volumes, remove_volumes,
               sync, synctimeout=0):
        """Function used to add or remove volumes from consistency group.

        It will update the consistency group with given volumes

        :param uri: URI of the consistency group
        :param project: Name of the project path
        :param tenant: Container tenant name
        :param add_volumes: volumes to be added to the consistency group
        :param remove_volumes: volumes to be removed from CG
        :param sync: synchronous request
        :param synctimeout: Query for task status for 'synctimeout' secs.
                            If the task doesn't complete in synctimeout
                            secs, an exception is thrown
        :returns: status of creation
        """
        if tenant is None:
            tenant = ""

        parms = []
        add_voluris = []
        remove_voluris = []
        from cinder.volume.drivers.coprhd.helpers.volume import Volume
        volobj = Volume(self.ipaddr, self.port)
        if add_volumes:
            for volname in add_volumes:
                full_project_name = tenant + "/" + project
                add_voluris.append(
                    volobj.volume_query(full_project_name, volname))
            volumes = {'volume': add_voluris}
            parms = {'add_volumes': volumes}

        if remove_volumes:
            for volname in remove_volumes:
                full_project_name = tenant + "/" + project
                remove_voluris.append(
                    volobj.volume_query(full_project_name, volname))
            volumes = {'volume': remove_voluris}
            parms = {'remove_volumes': volumes}

        body = oslo_serialization.jsonutils.dumps(parms)
        (s, h) = common.service_json_request(
            self.ipaddr, self.port, "PUT",
            self.URI_CONSISTENCY_GROUPS_INSTANCE.format(uri),
            body)

        o = common.json_decode(s)
        if sync:
            return self.check_for_sync(o, sync, synctimeout)
        else:
            return o
