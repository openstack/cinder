# Copyright (c) 2020 SAP SE
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
RPC server and client for communicating with other VMDK drivers directly.
This is the gateway which allows us gathering VMWare related information from
other hosts and perform cross vCenter operations.
"""
import oslo_messaging as messaging
from oslo_vmware import vim_util

from cinder import rpc
from cinder.volume.rpcapi import VolumeAPI
from cinder.volume import volume_utils


class VmdkDriverRemoteApi(rpc.RPCAPI):
    RPC_API_VERSION = VolumeAPI.RPC_API_VERSION
    RPC_DEFAULT_VERSION = RPC_API_VERSION
    TOPIC = VolumeAPI.TOPIC
    BINARY = VolumeAPI.BINARY

    def _get_cctxt(self, host=None, version=None, **kwargs):
        kwargs['server'] = volume_utils.extract_host(host)
        return super(VmdkDriverRemoteApi, self)._get_cctxt(version=version,
                                                           **kwargs)

    def get_service_locator_info(self, ctxt, host):
        cctxt = self._get_cctxt(host)
        return cctxt.call(ctxt, 'get_service_locator_info')

    def select_ds_for_volume(self, ctxt, cinder_host, volume):
        cctxt = self._get_cctxt(cinder_host)
        return cctxt.call(ctxt, 'select_ds_for_volume', volume=volume,
                          cinder_host=cinder_host)

    def move_volume_backing_to_folder(self, ctxt, host, volume, folder):
        cctxt = self._get_cctxt(host)
        return cctxt.call(ctxt, 'move_volume_backing_to_folder', volume=volume,
                          folder=folder)

    def create_backing(self, ctxt, host, volume, create_params=None,
                       cinder_host=None):
        cctxt = self._get_cctxt(host)
        return cctxt.call(ctxt, 'create_backing', volume=volume,
                          create_params=create_params,
                          cinder_host=cinder_host or host)

    def destory_backing(self, ctxt, host, volume):
        cctxt = self._get_cctxt(host)
        return cctxt.call(ctxt, 'destory_backing', volume=volume)

    @volume_utils.trace
    def update_fcd_policy(self, ctxt, cinder_host, prov_loc, profile_id):
        cctxt = self._get_cctxt(cinder_host)
        return cctxt.call(ctxt, 'update_fcd_policy',
                          prov_loc=prov_loc,
                          profile_id=profile_id)


class VmdkDriverRemoteService(object):
    RPC_API_VERSION = VmdkDriverRemoteApi.RPC_API_VERSION

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, driver):
        self._driver = driver

    def get_service_locator_info(self, ctxt):
        return self._driver.service_locator_info

    def select_ds_for_volume(self, ctxt, volume, cinder_host=None):
        """Select datastore for volume.

        cinder_host is a host@backend_name#pool entry.
        host is an vmware host, which is returned from the driver call
        to select_ds_for_volume and returned as part of this call
        """
        (host, rp, folder, summary) = self._driver._select_ds_for_volume(
            volume, cinder_host=cinder_host)

        profile_id = self._driver._get_storage_profile_id(volume)

        return {
            'host': host.value,
            'resource_pool': rp.value,
            'folder': folder.value,
            'datastore': summary.datastore.value,
            'profile_id': profile_id,
        }

    def move_volume_backing_to_folder(self, ctxt, volume, folder):
        backing = self._driver.volumeops.get_backing(volume['name'],
                                                     volume['id'])
        folder_ref = vim_util.get_moref(folder, 'Folder')
        self._driver.volumeops.move_backing_to_folder(backing, folder_ref)

    def create_backing(self, ctxt, volume, create_params=None,
                       cinder_host=None):
        return self._driver._create_backing(volume,
                                            create_params=create_params,
                                            cinder_host=cinder_host)

    @volume_utils.trace
    def destory_backing(self, ctxt, volume):
        backing = self._driver.volumeops.get_backing_by_uuid(volume.id)
        disk_device = self._driver.volumeops._get_disk_device(backing)
        self._driver.volumeops.detach_disk_from_backing(backing,
                                                        disk_device)
        self._driver.volumeops.delete_backing(backing)

    @volume_utils.trace
    def update_fcd_policy(self, ctxt, prov_loc, profile_id):
        vops = self._driver.volumeops
        fcd_location = vops._get_fcd_loc(prov_loc)
        return self._driver.volumeops.update_fcd_policy(fcd_location,
                                                        profile_id)
