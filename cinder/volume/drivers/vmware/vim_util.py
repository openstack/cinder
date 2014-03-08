# Copyright (c) 2013 VMware, Inc.
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
The VMware API utility module.
"""

import netaddr


def get_soap_url(protocol, host, path='sdk'):
    """Return URL to SOAP services for ESX/VC server.

    :param protocol: https or http
    :param host: ESX/VC server host IP
    :param path: path part of the SOAP URL
    :return: URL to SOAP services for ESX/VC server
    """
    if netaddr.valid_ipv6(host):
        return '%s://[%s]/%s' % (protocol, host, path)
    return '%s://%s/%s' % (protocol, host, path)


def build_selection_spec(client_factory, name):
    """Builds the selection spec.

    :param client_factory: Factory to get API input specs
    :param name: Name for the selection spec
    :return: Selection spec
    """
    sel_spec = client_factory.create('ns0:SelectionSpec')
    sel_spec.name = name
    return sel_spec


def build_traversal_spec(client_factory, name, type, path, skip,
                         select_set):
    """Builds the traversal spec object.

    :param client_factory: Factory to get API input specs
    :param name: Name for the traversal spec
    :param type: Type of the managed object reference
    :param path: Property path of the managed object reference
    :param skip: Whether or not to filter the object identified by param path
    :param select_set: Set of selection specs specifying additional objects
                       to filter
    :return: Traversal spec
    """
    traversal_spec = client_factory.create('ns0:TraversalSpec')
    traversal_spec.name = name
    traversal_spec.type = type
    traversal_spec.path = path
    traversal_spec.skip = skip
    traversal_spec.selectSet = select_set
    return traversal_spec


def build_recursive_traversal_spec(client_factory):
    """Builds Recursive Traversal Spec to traverse managed object hierarchy.

    :param client_factory: Factory to get API input specs
    :return: Recursive traversal spec
    """
    visit_folders_select_spec = build_selection_spec(client_factory,
                                                     'visitFolders')
    # Next hop from Datacenter
    dc_to_hf = build_traversal_spec(client_factory, 'dc_to_hf', 'Datacenter',
                                    'hostFolder', False,
                                    [visit_folders_select_spec])
    dc_to_vmf = build_traversal_spec(client_factory, 'dc_to_vmf', 'Datacenter',
                                     'vmFolder', False,
                                     [visit_folders_select_spec])

    # Next hop from HostSystem
    h_to_vm = build_traversal_spec(client_factory, 'h_to_vm', 'HostSystem',
                                   'vm', False,
                                   [visit_folders_select_spec])

    # Next hop from ComputeResource
    cr_to_h = build_traversal_spec(client_factory, 'cr_to_h',
                                   'ComputeResource', 'host', False, [])
    cr_to_ds = build_traversal_spec(client_factory, 'cr_to_ds',
                                    'ComputeResource', 'datastore', False, [])

    rp_to_rp_select_spec = build_selection_spec(client_factory, 'rp_to_rp')
    rp_to_vm_select_spec = build_selection_spec(client_factory, 'rp_to_vm')

    cr_to_rp = build_traversal_spec(client_factory, 'cr_to_rp',
                                    'ComputeResource', 'resourcePool', False,
                                    [rp_to_rp_select_spec,
                                     rp_to_vm_select_spec])

    # Next hop from ClusterComputeResource
    ccr_to_h = build_traversal_spec(client_factory, 'ccr_to_h',
                                    'ClusterComputeResource', 'host',
                                    False, [])
    ccr_to_ds = build_traversal_spec(client_factory, 'ccr_to_ds',
                                     'ClusterComputeResource', 'datastore',
                                     False, [])
    ccr_to_rp = build_traversal_spec(client_factory, 'ccr_to_rp',
                                     'ClusterComputeResource', 'resourcePool',
                                     False,
                                     [rp_to_rp_select_spec,
                                      rp_to_vm_select_spec])
    # Next hop from ResourcePool
    rp_to_rp = build_traversal_spec(client_factory, 'rp_to_rp', 'ResourcePool',
                                    'resourcePool', False,
                                    [rp_to_rp_select_spec,
                                     rp_to_vm_select_spec])
    rp_to_vm = build_traversal_spec(client_factory, 'rp_to_vm', 'ResourcePool',
                                    'vm', False,
                                    [rp_to_rp_select_spec,
                                     rp_to_vm_select_spec])

    # Get the assorted traversal spec which takes care of the objects to
    # be searched for from the rootFolder
    traversal_spec = build_traversal_spec(client_factory, 'visitFolders',
                                          'Folder', 'childEntity', False,
                                          [visit_folders_select_spec,
                                           h_to_vm, dc_to_hf, dc_to_vmf,
                                           cr_to_ds, cr_to_h, cr_to_rp,
                                           ccr_to_h, ccr_to_ds, ccr_to_rp,
                                           rp_to_rp, rp_to_vm])
    return traversal_spec


def build_property_spec(client_factory, type='VirtualMachine',
                        properties_to_collect=None,
                        all_properties=False):
    """Builds the Property Spec.

    :param client_factory: Factory to get API input specs
    :param type: Type of the managed object reference property
    :param properties_to_collect: Properties of the managed object reference
                                  to be collected while traversal filtering
    :param all_properties: Whether all the properties of managed object
                           reference needs to be collected
    :return: Property spec
    """
    if not properties_to_collect:
        properties_to_collect = ['name']

    property_spec = client_factory.create('ns0:PropertySpec')
    property_spec.all = all_properties
    property_spec.pathSet = properties_to_collect
    property_spec.type = type
    return property_spec


def build_object_spec(client_factory, root_folder, traversal_specs):
    """Builds the object Spec.

    :param client_factory: Factory to get API input specs
    :param root_folder: Root folder reference as the starting point for
                        traversal
    :param traversal_specs: filter specs required for traversal
    :return: Object spec
    """
    object_spec = client_factory.create('ns0:ObjectSpec')
    object_spec.obj = root_folder
    object_spec.skip = False
    object_spec.selectSet = traversal_specs
    return object_spec


def build_property_filter_spec(client_factory, property_specs, object_specs):
    """Builds the Property Filter Spec.

    :param client_factory: Factory to get API input specs
    :param property_specs: Property specs to be collected for filtered objects
    :param object_specs: Object specs to identify objects to be filtered
    :return: Property filter spec
    """
    property_filter_spec = client_factory.create('ns0:PropertyFilterSpec')
    property_filter_spec.propSet = property_specs
    property_filter_spec.objectSet = object_specs
    return property_filter_spec


def get_objects(vim, type, max_objects, props_to_collect=None,
                all_properties=False):
    """Gets all managed object references of a specified type.

    It is caller's responsibility to continue or cancel retrieval.

    :param vim: Vim object
    :param type: Type of the managed object reference
    :param max_objects: Maximum number of objects that should be returned in
                        a single call
    :param props_to_collect: Properties of the managed object reference
                             to be collected
    :param all_properties: Whether all properties of the managed object
                           reference are to be collected
    :return: All managed object references of a specified type
    """

    if not props_to_collect:
        props_to_collect = ['name']

    client_factory = vim.client.factory
    recur_trav_spec = build_recursive_traversal_spec(client_factory)
    object_spec = build_object_spec(client_factory,
                                    vim.service_content.rootFolder,
                                    [recur_trav_spec])
    property_spec = build_property_spec(client_factory, type=type,
                                        properties_to_collect=props_to_collect,
                                        all_properties=all_properties)
    property_filter_spec = build_property_filter_spec(client_factory,
                                                      [property_spec],
                                                      [object_spec])
    options = client_factory.create('ns0:RetrieveOptions')
    options.maxObjects = max_objects
    return vim.RetrievePropertiesEx(vim.service_content.propertyCollector,
                                    specSet=[property_filter_spec],
                                    options=options)


def get_object_properties(vim, mobj, properties):
    """Gets properties of the managed object specified.

    :param vim: Vim object
    :param mobj: Reference to the managed object
    :param properties: Properties of the managed object reference
                       to be retrieved
    :return: Properties of the managed object specified
    """

    client_factory = vim.client.factory
    if mobj is None:
        return None
    collector = vim.service_content.propertyCollector
    property_filter_spec = client_factory.create('ns0:PropertyFilterSpec')
    property_spec = client_factory.create('ns0:PropertySpec')
    property_spec.all = (properties is None or len(properties) == 0)
    property_spec.pathSet = properties
    property_spec.type = mobj._type
    object_spec = client_factory.create('ns0:ObjectSpec')
    object_spec.obj = mobj
    object_spec.skip = False
    property_filter_spec.propSet = [property_spec]
    property_filter_spec.objectSet = [object_spec]
    options = client_factory.create('ns0:RetrieveOptions')
    options.maxObjects = 1
    retrieve_result = vim.RetrievePropertiesEx(collector,
                                               specSet=[property_filter_spec],
                                               options=options)
    cancel_retrieval(vim, retrieve_result)
    return retrieve_result.objects


def _get_token(retrieve_result):
    """Get token from results to obtain next set of results.

    :retrieve_result: Result from the RetrievePropertiesEx API
    :return: Token to obtain next set of results. None if no more results.
    """
    return getattr(retrieve_result, 'token', None)


def cancel_retrieval(vim, retrieve_result):
    """Cancels the retrieve operation if necessary.

    :param vim: Vim object
    :param retrieve_result: Result from the RetrievePropertiesEx API
    """

    token = _get_token(retrieve_result)
    if token:
        collector = vim.service_content.propertyCollector
        vim.CancelRetrievePropertiesEx(collector, token=token)


def continue_retrieval(vim, retrieve_result):
    """Continue retrieving results, if present.

    :param vim: Vim object
    :param retrieve_result: Result from the RetrievePropertiesEx API
    """

    token = _get_token(retrieve_result)
    if token:
        collector = vim.service_content.propertyCollector
        return vim.ContinueRetrievePropertiesEx(collector, token=token)


def get_object_property(vim, mobj, property_name):
    """Gets property of the managed object specified.

    :param vim: Vim object
    :param mobj: Reference to the managed object
    :param property_name: Name of the property to be retrieved
    :return: Property of the managed object specified
    """
    props = get_object_properties(vim, mobj, [property_name])
    prop_val = None
    if props:
        prop = None
        if hasattr(props[0], 'propSet'):
            # propSet will be set only if the server provides value
            # for the field
            prop = props[0].propSet
        if prop:
            prop_val = prop[0].val
    return prop_val


def convert_datastores_to_hubs(pbm_client_factory, datastores):
    """Convert Datastore morefs to PbmPlacementHub morefs.

    :param pbm_client_factory: pbm client factory
    :param datastores: list of datastore morefs
    :returns: list of PbmPlacementHub morefs
    """
    hubs = []
    for ds in datastores:
        hub = pbm_client_factory.create('ns0:PbmPlacementHub')
        hub.hubId = ds.value
        hub.hubType = 'Datastore'
        hubs.append(hub)
    return hubs


def convert_hubs_to_datastores(hubs, datastores):
    """Get filtered subset of datastores as represented by hubs.

    :param hubs: represents a sub set of datastore ids
    :param datastores: represents all candidate datastores
    :returns: that subset of datastores objects that are also present in hubs
    """
    hubIds = [hub.hubId for hub in hubs]
    filtered_dss = [ds for ds in datastores if ds.value in hubIds]
    return filtered_dss
