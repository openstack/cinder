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


class URIHelper(object):

    """This map will be a map of maps.

    e.g for project component type, it will hold a map
    of its operations vs their uris
    """
    COMPONENT_TYPE_VS_URIS_MAP = dict()
    """Volume URIs."""
    VOLUME_URIS_MAP = dict()
    URI_VOLUMES = '/block/volumes'
    URI_VOLUME = URI_VOLUMES + '/{0}'
    URI_VOLUME_TASK_LIST = URI_VOLUME + '/tasks'
    URI_VOLUME_TASK = URI_VOLUME_TASK_LIST + '/{1}'

    """Consistencygroup URIs."""
    CG_URIS_MAP = dict()
    URI_CGS = '/block/consistency-groups'
    URI_CG = URI_CGS + '/{0}'
    URI_CG_TASK_LIST = URI_CG + '/tasks'
    URI_CG_TASK = URI_CG_TASK_LIST + '/{1}'

    """Export Group URIs."""
    # Map to hold all export group uris
    EXPORT_GROUP_URIS_MAP = dict()
    URI_EXPORT_GROUP_TASKS_LIST = '/block/exports/{0}/tasks'
    URI_EXPORT_GROUP_TASK = URI_EXPORT_GROUP_TASKS_LIST + '/{1}'

    def __init__(self):
        """During initialization of the class, lets fill all the maps."""
        self.__fillExportGroupMap()
        self.__fillVolumeMap()
        self.__fillConsistencyGroupMap()
        self.__initializeComponentVsUriMap()

    def __call__(self):
        return self

    def __initializeComponentVsUriMap(self):
        self.COMPONENT_TYPE_VS_URIS_MAP["export"] = self.EXPORT_GROUP_URIS_MAP
        self.COMPONENT_TYPE_VS_URIS_MAP[
            "volume"] = self.VOLUME_URIS_MAP
        self.COMPONENT_TYPE_VS_URIS_MAP[
            "consistencygroup"] = self.CG_URIS_MAP

    def __fillExportGroupMap(self):
        self.EXPORT_GROUP_URIS_MAP["task"] = self.URI_EXPORT_GROUP_TASK

    def __fillVolumeMap(self):
        self.VOLUME_URIS_MAP["task"] = self.URI_VOLUME_TASK

    def __fillConsistencyGroupMap(self):
        self.CG_URIS_MAP["task"] = self.URI_CG_TASK

    def getUri(self, componentType, operationType):
        return (
            self.COMPONENT_TYPE_VS_URIS_MAP.get(
                componentType).get(
                operationType)
        )

"""Defining the singleton instance.

Use this instance any time the access is required for this module/class
"""
singletonURIHelperInstance = URIHelper()
