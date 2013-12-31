# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import contextlib
import os
import pickle

from cinder import units
from cinder.volume.drivers.xenapi import tools


class XenAPIException(Exception):
    def __init__(self, original_exception):
        super(XenAPIException, self).__init__(str(original_exception))
        self.original_exception = original_exception


class OperationsBase(object):
    def __init__(self, xenapi_session):
        self.session = xenapi_session

    def call_xenapi(self, method, *args):
        return self.session.call_xenapi(method, *args)


class VMOperations(OperationsBase):
    def get_by_uuid(self, vm_uuid):
        return self.call_xenapi('VM.get_by_uuid', vm_uuid)

    def get_vbds(self, vm_uuid):
        return self.call_xenapi('VM.get_VBDs', vm_uuid)


class VBDOperations(OperationsBase):
    def create(self, vm_ref, vdi_ref, userdevice, bootable, mode, type,
               empty, other_config):
        vbd_rec = dict(
            VM=vm_ref,
            VDI=vdi_ref,
            userdevice=str(userdevice),
            bootable=bootable,
            mode=mode,
            type=type,
            empty=empty,
            other_config=other_config,
            qos_algorithm_type='',
            qos_algorithm_params=dict()
        )
        return self.call_xenapi('VBD.create', vbd_rec)

    def destroy(self, vbd_ref):
        self.call_xenapi('VBD.destroy', vbd_ref)

    def get_device(self, vbd_ref):
        return self.call_xenapi('VBD.get_device', vbd_ref)

    def plug(self, vbd_ref):
        return self.call_xenapi('VBD.plug', vbd_ref)

    def unplug(self, vbd_ref):
        return self.call_xenapi('VBD.unplug', vbd_ref)

    def get_vdi(self, vbd_ref):
        return self.call_xenapi('VBD.get_VDI', vbd_ref)


class PoolOperations(OperationsBase):
    def get_all(self):
        return self.call_xenapi('pool.get_all')

    def get_default_SR(self, pool_ref):
        return self.call_xenapi('pool.get_default_SR', pool_ref)


class PbdOperations(OperationsBase):
    def get_all(self):
        return self.call_xenapi('PBD.get_all')

    def unplug(self, pbd_ref):
        self.call_xenapi('PBD.unplug', pbd_ref)

    def create(self, host_ref, sr_ref, device_config):
        return self.call_xenapi(
            'PBD.create',
            dict(
                host=host_ref,
                SR=sr_ref,
                device_config=device_config
            )
        )

    def plug(self, pbd_ref):
        self.call_xenapi('PBD.plug', pbd_ref)


class SrOperations(OperationsBase):
    def get_all(self):
        return self.call_xenapi('SR.get_all')

    def get_record(self, sr_ref):
        return self.call_xenapi('SR.get_record', sr_ref)

    def forget(self, sr_ref):
        self.call_xenapi('SR.forget', sr_ref)

    def scan(self, sr_ref):
        self.call_xenapi('SR.scan', sr_ref)

    def create(self, host_ref, device_config, name_label, name_description,
               sr_type, physical_size=None, content_type=None,
               shared=False, sm_config=None):
        return self.call_xenapi(
            'SR.create',
            host_ref,
            device_config,
            physical_size or '0',
            name_label or '',
            name_description or '',
            sr_type,
            content_type or '',
            shared,
            sm_config or dict()
        )

    def introduce(self, sr_uuid, name_label, name_description, sr_type,
                  content_type=None, shared=False, sm_config=None):
        return self.call_xenapi(
            'SR.introduce',
            sr_uuid,
            name_label or '',
            name_description or '',
            sr_type,
            content_type or '',
            shared,
            sm_config or dict()
        )

    def get_uuid(self, sr_ref):
        return self.get_record(sr_ref)['uuid']

    def get_name_label(self, sr_ref):
        return self.get_record(sr_ref)['name_label']

    def get_name_description(self, sr_ref):
        return self.get_record(sr_ref)['name_description']

    def destroy(self, sr_ref):
        self.call_xenapi('SR.destroy', sr_ref)


class VdiOperations(OperationsBase):
    def get_all(self):
        return self.call_xenapi('VDI.get_all')

    def get_record(self, vdi_ref):
        return self.call_xenapi('VDI.get_record', vdi_ref)

    def get_by_uuid(self, vdi_uuid):
        return self.call_xenapi('VDI.get_by_uuid', vdi_uuid)

    def get_uuid(self, vdi_ref):
        return self.get_record(vdi_ref)['uuid']

    def create(self, sr_ref, size, vdi_type,
               sharable=False, read_only=False, other_config=None):
        return self.call_xenapi('VDI.create',
                                dict(SR=sr_ref,
                                     virtual_size=str(size),
                                     type=vdi_type,
                                     sharable=sharable,
                                     read_only=read_only,
                                     other_config=other_config or dict()))

    def destroy(self, vdi_ref):
        self.call_xenapi('VDI.destroy', vdi_ref)

    def copy(self, vdi_ref, sr_ref):
        return self.call_xenapi('VDI.copy', vdi_ref, sr_ref)

    def resize(self, vdi_ref, size):
        return self.call_xenapi('VDI.resize', vdi_ref, str(size))


class HostOperations(OperationsBase):
    def get_record(self, host_ref):
        return self.call_xenapi('host.get_record', host_ref)

    def get_uuid(self, host_ref):
        return self.get_record(host_ref)['uuid']


class XenAPISession(object):
    def __init__(self, session, exception_to_convert):
        self._session = session
        self._exception_to_convert = exception_to_convert
        self.handle = self._session.handle
        self.PBD = PbdOperations(self)
        self.SR = SrOperations(self)
        self.VDI = VdiOperations(self)
        self.host = HostOperations(self)
        self.pool = PoolOperations(self)
        self.VBD = VBDOperations(self)
        self.VM = VMOperations(self)

    def close(self):
        return self.call_xenapi('logout')

    @contextlib.contextmanager
    def exception_converter(self):
        try:
            yield None
        except self._exception_to_convert as e:
            raise XenAPIException(e)

    def call_xenapi(self, method, *args):
        with self.exception_converter():
            return self._session.xenapi_request(method, args)

    def call_plugin(self, host_ref, plugin, function, args):
        with self.exception_converter():
            return self._session.xenapi.host.call_plugin(
                host_ref, plugin, function, args)

    def get_pool(self):
        return self.call_xenapi('session.get_pool', self.handle)

    def get_this_host(self):
        return self.call_xenapi('session.get_this_host', self.handle)


class CompoundOperations(object):
    def unplug_pbds_from_sr(self, sr_ref):
        sr_rec = self.SR.get_record(sr_ref)
        for pbd_ref in sr_rec.get('PBDs', []):
            self.PBD.unplug(pbd_ref)

    def unplug_pbds_and_forget_sr(self, sr_ref):
        self.unplug_pbds_from_sr(sr_ref)
        self.SR.forget(sr_ref)

    def create_new_vdi(self, sr_ref, size_in_gigabytes):
        return self.VDI.create(sr_ref,
                               to_bytes(size_in_gigabytes),
                               'User', )


def to_bytes(size_in_gigs):
    return size_in_gigs * units.GiB


class NFSOperationsMixIn(CompoundOperations):
    def is_nfs_sr(self, sr_ref):
        return self.SR.get_record(sr_ref).get('type') == 'nfs'

    @contextlib.contextmanager
    def new_sr_on_nfs(self, host_ref, server, serverpath,
                      name_label=None, name_description=None):

        device_config = dict(
            server=server,
            serverpath=serverpath
        )
        name_label = name_label or ''
        name_description = name_description or ''
        sr_type = 'nfs'

        sr_ref = self.SR.create(
            host_ref,
            device_config,
            name_label,
            name_description,
            sr_type,
        )
        yield sr_ref

        self.unplug_pbds_and_forget_sr(sr_ref)

    def plug_nfs_sr(self, host_ref, server, serverpath, sr_uuid,
                    name_label=None, name_description=None):

        device_config = dict(
            server=server,
            serverpath=serverpath
        )
        sr_type = 'nfs'

        sr_ref = self.SR.introduce(
            sr_uuid,
            name_label,
            name_description,
            sr_type,
        )

        pbd_ref = self.PBD.create(
            host_ref,
            sr_ref,
            device_config
        )

        self.PBD.plug(pbd_ref)

        return sr_ref

    def connect_volume(self, server, serverpath, sr_uuid, vdi_uuid):
        host_ref = self.get_this_host()
        sr_ref = self.plug_nfs_sr(
            host_ref,
            server,
            serverpath,
            sr_uuid
        )
        self.SR.scan(sr_ref)
        vdi_ref = self.VDI.get_by_uuid(vdi_uuid)
        return dict(sr_ref=sr_ref, vdi_ref=vdi_ref)

    def copy_vdi_to_sr(self, vdi_ref, sr_ref):
        return self.VDI.copy(vdi_ref, sr_ref)


class ContextAwareSession(XenAPISession):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class OpenStackXenAPISession(ContextAwareSession,
                             NFSOperationsMixIn):
    pass


def connect(url, user, password):
    import XenAPI
    session = XenAPI.Session(url)
    session.login_with_password(user, password)
    return OpenStackXenAPISession(session, XenAPI.Failure)


class SessionFactory(object):
    def __init__(self, url, user, password):
        self.url = url
        self.user = user
        self.password = password

    def get_session(self):
        return connect(self.url, self.user, self.password)


class XapiPluginProxy(object):
    def __init__(self, session_factory, plugin_name):
        self._session_factory = session_factory
        self._plugin_name = plugin_name

    def call(self, function, *plugin_args, **plugin_kwargs):
        plugin_params = dict(args=plugin_args, kwargs=plugin_kwargs)
        args = dict(params=pickle.dumps(plugin_params))

        with self._session_factory.get_session() as session:
            host_ref = session.get_this_host()
            result = session.call_plugin(
                host_ref, self._plugin_name, function, args)

        return pickle.loads(result)


class GlancePluginProxy(XapiPluginProxy):
    def __init__(self, session_factory):
        super(GlancePluginProxy, self).__init__(session_factory, 'glance')

    def download_vhd(self, image_id, glance_host, glance_port, glance_use_ssl,
                     uuid_stack, sr_path, auth_token):
        return self.call(
            'download_vhd',
            image_id=image_id,
            glance_host=glance_host,
            glance_port=glance_port,
            glance_use_ssl=glance_use_ssl,
            uuid_stack=uuid_stack,
            sr_path=sr_path,
            auth_token=auth_token)

    def upload_vhd(self, vdi_uuids, image_id, glance_host, glance_port,
                   glance_use_ssl, sr_path, auth_token, properties):
        return self.call(
            'upload_vhd',
            vdi_uuids=vdi_uuids,
            image_id=image_id,
            glance_host=glance_host,
            glance_port=glance_port,
            glance_use_ssl=glance_use_ssl,
            sr_path=sr_path,
            auth_token=auth_token,
            properties=properties)


class NFSBasedVolumeOperations(object):
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self.glance_plugin = GlancePluginProxy(session_factory)

    def create_volume(self, server, serverpath, size,
                      name=None, description=None):
        with self._session_factory.get_session() as session:
            host_ref = session.get_this_host()
            with session.new_sr_on_nfs(host_ref, server, serverpath,
                                       name, description) as sr_ref:
                vdi_ref = session.create_new_vdi(sr_ref, size)

                return dict(
                    sr_uuid=session.SR.get_uuid(sr_ref),
                    vdi_uuid=session.VDI.get_uuid(vdi_ref)
                )

    def delete_volume(self, server, serverpath, sr_uuid, vdi_uuid):
        with self._session_factory.get_session() as session:
            refs = session.connect_volume(
                server, serverpath, sr_uuid, vdi_uuid)

            session.VDI.destroy(refs['vdi_ref'])
            sr_ref = refs['sr_ref']
            session.unplug_pbds_from_sr(sr_ref)
            session.SR.destroy(sr_ref)

    def connect_volume(self, server, serverpath, sr_uuid, vdi_uuid):
        with self._session_factory.get_session() as session:
            refs = session.connect_volume(
                server, serverpath, sr_uuid, vdi_uuid)

            return session.VDI.get_uuid(refs['vdi_ref'])

    def disconnect_volume(self, vdi_uuid):
        with self._session_factory.get_session() as session:
            vdi_ref = session.VDI.get_by_uuid(vdi_uuid)
            vdi_rec = session.VDI.get_record(vdi_ref)
            sr_ref = vdi_rec['SR']
            session.unplug_pbds_and_forget_sr(sr_ref)

    def copy_volume(self, server, serverpath, sr_uuid, vdi_uuid,
                    name=None, description=None):
        with self._session_factory.get_session() as session:
            src_refs = session.connect_volume(
                server, serverpath, sr_uuid, vdi_uuid)
            try:
                host_ref = session.get_this_host()

                with session.new_sr_on_nfs(host_ref, server, serverpath,
                                           name, description) as target_sr_ref:
                    target_vdi_ref = session.copy_vdi_to_sr(
                        src_refs['vdi_ref'], target_sr_ref)

                    dst_refs = dict(
                        sr_uuid=session.SR.get_uuid(target_sr_ref),
                        vdi_uuid=session.VDI.get_uuid(target_vdi_ref)
                    )

            finally:
                session.unplug_pbds_and_forget_sr(src_refs['sr_ref'])

            return dst_refs

    def resize_volume(self, server, serverpath, sr_uuid, vdi_uuid,
                      size_in_gigabytes):
        self.connect_volume(server, serverpath, sr_uuid, vdi_uuid)

        try:
            with self._session_factory.get_session() as session:
                vdi_ref = session.VDI.get_by_uuid(vdi_uuid)
                session.VDI.resize(vdi_ref, to_bytes(size_in_gigabytes))
        finally:
            self.disconnect_volume(vdi_uuid)

    def use_glance_plugin_to_overwrite_volume(self, server, serverpath,
                                              sr_uuid, vdi_uuid, glance_server,
                                              image_id, auth_token,
                                              sr_base_path):
        self.connect_volume(server, serverpath, sr_uuid, vdi_uuid)

        uuid_stack = [vdi_uuid]
        glance_host, glance_port, glance_use_ssl = glance_server

        try:
            result = self.glance_plugin.download_vhd(
                image_id, glance_host, glance_port, glance_use_ssl, uuid_stack,
                os.path.join(sr_base_path, sr_uuid), auth_token)
        finally:
            self.disconnect_volume(vdi_uuid)

        if len(result) != 1 or result['root']['uuid'] != vdi_uuid:
            return False

        return True

    def use_glance_plugin_to_upload_volume(self, server, serverpath,
                                           sr_uuid, vdi_uuid, glance_server,
                                           image_id, auth_token, sr_base_path):
        self.connect_volume(server, serverpath, sr_uuid, vdi_uuid)

        vdi_uuids = [vdi_uuid]
        glance_host, glance_port, glance_use_ssl = glance_server

        try:
            result = self.glance_plugin.upload_vhd(
                vdi_uuids, image_id, glance_host, glance_port, glance_use_ssl,
                os.path.join(sr_base_path, sr_uuid), auth_token, dict())
        finally:
            self.disconnect_volume(vdi_uuid)

    @contextlib.contextmanager
    def volume_attached_here(self, server, serverpath, sr_uuid, vdi_uuid,
                             readonly=True):
        self.connect_volume(server, serverpath, sr_uuid, vdi_uuid)

        with self._session_factory.get_session() as session:
            vm_uuid = tools.get_this_vm_uuid()
            vm_ref = session.VM.get_by_uuid(vm_uuid)
            vdi_ref = session.VDI.get_by_uuid(vdi_uuid)
            vbd_ref = session.VBD.create(
                vm_ref, vdi_ref, userdevice='autodetect', bootable=False,
                mode='RO' if readonly else 'RW', type='disk', empty=False,
                other_config=dict())
            session.VBD.plug(vbd_ref)
            device = session.VBD.get_device(vbd_ref)
            try:
                yield "/dev/" + device
            finally:
                session.VBD.unplug(vbd_ref)
                session.VBD.destroy(vbd_ref)
                self.disconnect_volume(vdi_uuid)
