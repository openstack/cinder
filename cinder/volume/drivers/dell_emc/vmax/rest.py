# Copyright (c) 2017 Dell Inc. or its subsidiaries.
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

import json

from oslo_log import log as logging
from oslo_service import loopingcall
import requests
import requests.auth
import requests.packages.urllib3.exceptions as urllib_exp
import six

from cinder import exception
from cinder.i18n import _
from cinder.utils import retry
from cinder.volume.drivers.dell_emc.vmax import utils

requests.packages.urllib3.disable_warnings(urllib_exp.InsecureRequestWarning)

LOG = logging.getLogger(__name__)
SLOPROVISIONING = 'sloprovisioning'
REPLICATION = 'replication'
U4V_VERSION = '84'
retry_exc_tuple = (exception.VolumeBackendAPIException,)
# HTTP constants
GET = 'GET'
POST = 'POST'
PUT = 'PUT'
DELETE = 'DELETE'
STATUS_200 = 200
STATUS_201 = 201
STATUS_202 = 202
STATUS_204 = 204
# Job constants
INCOMPLETE_LIST = ['created', 'scheduled', 'running',
                   'validating', 'validated']
CREATED = 'created'
SUCCEEDED = 'succeeded'
CREATE_VOL_STRING = "Creating new Volumes"


class VMAXRest(object):
    """Rest class based on Unisphere for VMAX Rest API."""

    def __init__(self):
        self.utils = utils.VMAXUtils()
        self.session = None
        self.base_uri = None
        self.user = None
        self.passwd = None
        self.verify = None
        self.cert = None

    def set_rest_credentials(self, array_info):
        """Given the array record set the rest server credentials.

        :param array_info: record
        """
        ip = array_info['RestServerIp']
        port = array_info['RestServerPort']
        self.user = array_info['RestUserName']
        self.passwd = array_info['RestPassword']
        self.cert = array_info['SSLCert']
        verify = array_info['SSLVerify']
        if verify and verify.lower() == 'false':
            verify = False
        self.verify = verify
        ip_port = "%(ip)s:%(port)s" % {'ip': ip, 'port': port}
        self.base_uri = ("https://%(ip_port)s/univmax/restapi"
                         % {'ip_port': ip_port})
        self.session = self._establish_rest_session()

    def _establish_rest_session(self):
        """Establish the rest session.

        :returns: requests.session() -- session, the rest session
        """
        session = requests.session()
        session.headers = {'content-type': 'application/json',
                           'accept': 'application/json',
                           'Application-Type': 'openstack'}
        session.auth = requests.auth.HTTPBasicAuth(self.user, self.passwd)
        if self.verify is not None:
            session.verify = self.verify
        if self.cert:
            session.cert = self.cert

        return session

    def request(self, target_uri, method, params=None, request_object=None):
        """Sends a request (GET, POST, PUT, DELETE) to the target api.

        :param target_uri: target uri (string)
        :param method: The method (GET, POST, PUT, or DELETE)
        :param params: Additional URL parameters
        :param request_object: request payload (dict)
        :return: server response object (dict)
        :raises: VolumeBackendAPIException
        """
        message, status_code = None, None
        if not self.session:
            self.session = self._establish_rest_session()
        url = ("%(self.base_uri)s%(target_uri)s" %
               {'self.base_uri': self.base_uri,
                'target_uri': target_uri})
        try:
            if request_object:
                response = self.session.request(
                    method=method, url=url,
                    data=json.dumps(request_object, sort_keys=True,
                                    indent=4))
            elif params:
                response = self.session.request(method=method, url=url,
                                                params=params)
            else:
                response = self.session.request(method=method, url=url)
            status_code = response.status_code
            try:
                message = response.json()
            except ValueError:
                LOG.debug("No response received from API. Status code "
                          "received is: %(status_code)s",
                          {'status_code': status_code})
                message = None
            LOG.debug("%(method)s request to %(url)s has returned with "
                      "a status code of: %(status_code)s.",
                      {'method': method, 'url': url,
                       'status_code': status_code})

        except requests.Timeout:
            LOG.error("The %(method)s request to URL %(url)s timed-out, "
                      "but may have been successful. Please check the array.",
                      {'method': method, 'url': url})
        except Exception as e:
            exception_message = (_("The %(method)s request to URL %(url)s "
                                   "failed with exception %(e)s")
                                 % {'method': method, 'url': url,
                                    'e': six.text_type(e)})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        return status_code, message

    def wait_for_job_complete(self, job, extra_specs):
        """Given the job wait for it to complete.

        :param job: the job dict
        :param extra_specs: the extra_specs dict.
        :return rc -- int, result -- string, status -- string,
                task -- list of dicts detailing tasks in the job
        :raises: VolumeBackendAPIException
        """
        res, tasks = None, None
        if job['status'].lower == CREATED:
            try:
                res, tasks = job['result'], job['task']
            except KeyError:
                pass
            return 0, res, job['status'], tasks

        def _wait_for_job_complete():
            result = None
            # Called at an interval until the job is finished.
            retries = kwargs['retries']
            try:
                kwargs['retries'] = retries + 1
                if not kwargs['wait_for_job_called']:
                    is_complete, result, rc, status, task = (
                        self._is_job_finished(job_id))
                    if is_complete is True:
                        kwargs['wait_for_job_called'] = True
                        kwargs['rc'], kwargs['status'] = rc, status
                        kwargs['result'], kwargs['task'] = result, task
            except Exception:
                exception_message = (_("Issue encountered waiting for job."))
                LOG.exception(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            if retries > int(extra_specs[utils.RETRIES]):
                LOG.error("_wait_for_job_complete failed after "
                          "%(retries)d tries.", {'retries': retries})
                kwargs['rc'], kwargs['result'] = -1, result

                raise loopingcall.LoopingCallDone()
            if kwargs['wait_for_job_called']:
                raise loopingcall.LoopingCallDone()

        job_id = job['jobId']
        kwargs = {'retries': 0, 'wait_for_job_called': False,
                  'rc': 0, 'result': None}

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_job_complete)
        timer.start(interval=int(extra_specs[utils.INTERVAL])).wait()
        LOG.debug("Return code is: %(rc)lu. Result is %(res)s.",
                  {'rc': kwargs['rc'], 'res': kwargs['result']})
        return (kwargs['rc'], kwargs['result'],
                kwargs['status'], kwargs['task'])

    def _is_job_finished(self, job_id):
        """Check if the job is finished.

        :param job_id: the id of the job
        :returns: complete -- bool, result -- string,
                  rc -- int, status -- string, task -- list of dicts
        """
        complete, rc, status, result, task = False, 0, None, None, None
        job_url = "/%s/system/job/%s" % (U4V_VERSION, job_id)
        job = self._get_request(job_url, 'job')
        if job:
            status = job['status']
            try:
                result, task = job['result'], job['task']
            except KeyError:
                pass
            if status.lower() == SUCCEEDED:
                complete = True
            elif status.lower() in INCOMPLETE_LIST:
                complete = False
            else:
                rc, complete = -1, True
        return complete, result, rc, status, task

    @staticmethod
    def check_status_code_success(operation, status_code, message):
        """Check if a status code indicates success.

        :param operation: the operation
        :param status_code: the status code
        :param message: the server response
        :raises: VolumeBackendAPIException
        """
        if status_code not in [STATUS_200, STATUS_201,
                               STATUS_202, STATUS_204]:
            exception_message = (
                _('Error %(operation)s. The status code received '
                  'is %(sc)s and the message is %(message)s.')
                % {'operation': operation,
                   'sc': status_code, 'message': message})
            raise exception.VolumeBackendAPIException(
                data=exception_message)

    def wait_for_job(self, operation, status_code, job, extra_specs):
        """Check if call is async, wait for it to complete.

        :param operation: the operation being performed
        :param status_code: the status code
        :param job: the job
        :param extra_specs: the extra specifications
        :return: task -- list of dicts detailing tasks in the job
        :raises: VolumeBackendAPIException
        """
        task = None
        if status_code == STATUS_202:
            rc, result, status, task = self.wait_for_job_complete(
                job, extra_specs)
            if rc != 0:
                exception_message = (_(
                    "Error %(operation)s. Status code: %(sc)lu. "
                    "Error: %(error)s. Status: %(status)s.")
                    % {'operation': operation, 'sc': rc,
                       'error': six.text_type(result),
                       'status': status})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)
        return task

    @staticmethod
    def _build_uri(array, category, resource_type,
                   resource_name=None, private=''):
        """Build the target url.

        :param array: the array serial number
        :param category: the resource category e.g. sloprovisioning
        :param resource_type: the resource type e.g. maskingview
        :param resource_name: the name of a specific resource
        :param private: empty string or '/private' if private url
        :return: target url, string
        """
        target_uri = ('%(private)s/%(version)s/%(category)s/symmetrix/'
                      '%(array)s/%(resource_type)s'
                      % {'private': private, 'version': U4V_VERSION,
                         'category': category, 'array': array,
                         'resource_type': resource_type})
        if resource_name:
            target_uri += '/%(resource_name)s' % {
                'resource_name': resource_name}
        return target_uri

    def _get_request(self, target_uri, resource_type, params=None):
        """Send a GET request to the array.

        :param target_uri: the target uri
        :param resource_type: the resource type, e.g. maskingview
        :param params: optional dict of filter params
        :return: resource_object -- dict or None
        """
        resource_object = None
        sc, message = self.request(target_uri, GET, params=params)
        operation = 'get %(res)s' % {'res': resource_type}
        try:
            self.check_status_code_success(operation, sc, message)
        except Exception as e:
            LOG.debug("Get resource failed with %(e)s",
                      {'e': e})
        if sc == STATUS_200:
            resource_object = message
        return resource_object

    def get_resource(self, array, category, resource_type,
                     resource_name=None, params=None, private=''):
        """Get resource details from array.

        :param array: the array serial number
        :param category: the resource category e.g. sloprovisioning
        :param resource_type: the resource type e.g. maskingview
        :param resource_name: the name of a specific resource
        :param params: query parameters
        :param private: empty string or '/private' if private url
        :return: resource object -- dict or None
        """
        target_uri = self._build_uri(array, category, resource_type,
                                     resource_name, private)
        return self._get_request(target_uri, resource_type, params)

    def create_resource(self, array, category, resource_type, payload,
                        private=''):
        """Create a provisioning resource.

        :param array: the array serial number
        :param category: the category
        :param resource_type: the resource type
        :param payload: the payload
        :param private: empty string or '/private' if private url
        :return: status_code -- int, message -- string, server response
        """
        target_uri = self._build_uri(array, category, resource_type,
                                     None, private)
        status_code, message = self.request(target_uri, POST,
                                            request_object=payload)
        operation = 'Create %(res)s resource' % {'res': resource_type}
        self.check_status_code_success(
            operation, status_code, message)
        return status_code, message

    def modify_resource(self, array, category, resource_type, payload,
                        resource_name=None, private=''):
        """Modify a resource.

        :param array: the array serial number
        :param category: the category
        :param resource_type: the resource type
        :param payload: the payload
        :param resource_name: the resource name
        :param private: empty string or '/private' if private url
        :return: status_code -- int, message -- string (server response)
        """
        target_uri = self._build_uri(array, category, resource_type,
                                     resource_name, private)
        status_code, message = self.request(target_uri, PUT,
                                            request_object=payload)
        operation = 'modify %(res)s resource' % {'res': resource_type}
        self.check_status_code_success(operation, status_code, message)
        return status_code, message

    def delete_resource(
            self, array, category, resource_type, resource_name,
            payload=None, private=''):
        """Delete a provisioning resource.

        :param array: the array serial number
        :param category: the resource category e.g. sloprovisioning
        :param resource_type: the type of resource to be deleted
        :param resource_name: the name of the resource to be deleted
        :param payload: the payload, optional
        :param private: empty string or '/private' if private url
        """
        target_uri = self._build_uri(array, category, resource_type,
                                     resource_name, private)
        status_code, message = self.request(target_uri, DELETE,
                                            request_object=payload)
        operation = 'delete %(res)s resource' % {'res': resource_type}
        self.check_status_code_success(operation, status_code, message)

    def get_array_serial(self, array):
        """Get an array from its serial number.

        :param array: the array serial number
        :return: array_details -- dict or None
        """
        target_uri = '/%s/system/symmetrix/%s' % (U4V_VERSION, array)
        array_details = self._get_request(target_uri, 'system')
        if not array_details:
            LOG.error("Cannot connect to array %(array)s.",
                      {'array': array})
        return array_details

    def get_srp_by_name(self, array, srp=None):
        """Returns the details of a storage pool.

        :param array: the array serial number
        :param srp: the storage resource pool name
        :returns: SRP_details -- dict or None
        """
        LOG.debug("storagePoolName: %(srp)s, array: %(array)s.",
                  {'srp': srp, 'array': array})
        srp_details = self.get_resource(array, SLOPROVISIONING, 'srp',
                                        resource_name=srp, params=None)
        return srp_details

    def get_slo_list(self, array):
        """Returns the list of service levels associated with an srp.

        :param array: the array serial number
        :return slo_list -- list of service level names
        """
        slo_list = []
        slo_dict = self.get_resource(array, SLOPROVISIONING, 'slo')
        if slo_dict:
            slo_list = slo_dict['sloId']
        return slo_list

    def get_workload_settings(self, array):
        """Get valid workload options from array.

        :param array: the array serial number
        :return: workload_setting -- list of workload names
        """
        workload_setting = []
        wl_details = self.get_resource(array, SLOPROVISIONING, 'workloadtype')
        if wl_details:
            workload_setting = wl_details['workloadId']
        return workload_setting

    def get_headroom_capacity(self, array, srp, slo, workload):
        """Get capacity of the different slo/ workload combinations.

        :param array: the array serial number
        :param srp: the storage resource srp
        :param slo: the service level
        :param workload: the workload
        :return remaining_capacity -- string, or None
        """
        params = {'srp': srp, 'slo': slo, 'workloadtype': workload}
        try:
            headroom = self.get_resource(array, 'wlp',
                                         'headroom', params=params)
            remaining_capacity = headroom['headroom'][0]['headroomCapacity']
        except (KeyError, TypeError):
            remaining_capacity = None
        return remaining_capacity

    def get_storage_group(self, array, storage_group_name):
        """Given a name, return storage group details.

        :param array: the array serial number
        :param storage_group_name: the name of the storage group
        :return: storage group dict or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'storagegroup',
            resource_name=storage_group_name)

    def get_storage_group_list(self, array, params=None):
        """"Return a list of storage groups.

        :param array: the array serial number
        :param params: optional filter parameters
        :return: storage group list
        """
        sg_list = []
        sg_details = self.get_resource(array, SLOPROVISIONING,
                                       'storagegroup', params=params)
        if sg_details:
            sg_list = sg_details['storageGroupId']
        return sg_list

    def get_num_vols_in_sg(self, array, storage_group_name):
        """Get the number of volumes in a storage group.

        :param array: the array serial number
        :param storage_group_name: the storage group name
        :return: num_vols -- int
        """
        num_vols = 0
        storagegroup = self.get_storage_group(array, storage_group_name)
        try:
            num_vols = int(storagegroup['num_of_vols'])
        except (KeyError, TypeError):
            pass
        return num_vols

    def is_child_sg_in_parent_sg(self, array, child_name, parent_name):
        """Check if a child storage group is a member of a parent group.

        :param array: the array serial number
        :param child_name: the child sg name
        :param parent_name: the parent sg name
        :return: bool
        """
        parent_sg = self.get_storage_group(array, parent_name)
        if parent_sg and parent_sg.get('child_storage_group'):
            child_sg_list = parent_sg['child_storage_group']
            if child_name in child_sg_list:
                return True
        return False

    def add_child_sg_to_parent_sg(
            self, array, child_sg, parent_sg, extra_specs):
        """Add a storage group to a parent storage group.

        This method adds an existing storage group to another storage
        group, i.e. cascaded storage groups.
        :param array: the array serial number
        :param child_sg: the name of the child sg
        :param parent_sg: the name of the parent sg
        :param extra_specs: the extra specifications
        """
        payload = {"editStorageGroupActionParam": {
            "expandStorageGroupParam": {
                "addExistingStorageGroupParam": {
                    "storageGroupId": [child_sg]}}}}
        sc, job = self.modify_storage_group(array, parent_sg, payload)
        self.wait_for_job('Add child sg to parent sg', sc, job, extra_specs)

    def remove_child_sg_from_parent_sg(
            self, array, child_sg, parent_sg, extra_specs):
        """Remove a storage group from its parent storage group.

        This method removes a child storage group from its parent group.
        :param array: the array serial number
        :param child_sg: the name of the child sg
        :param parent_sg: the name of the parent sg
        :param extra_specs: the extra specifications
        """
        payload = {"editStorageGroupActionParam": {
            "removeStorageGroupParam": {
                "storageGroupId": [child_sg], "force": 'true'}}}
        status_code, job = self.modify_storage_group(
            array, parent_sg, payload)
        self.wait_for_job(
            'Remove child sg from parent sg', status_code, job, extra_specs)

    def _create_storagegroup(self, array, payload):
        """Create a storage group.

        :param array: the array serial number
        :param payload: the payload -- dict
        :return: status_code -- int, message -- string, server response
        """
        return self.create_resource(
            array, SLOPROVISIONING, 'storagegroup', payload)

    def create_storage_group(self, array, storagegroup_name,
                             srp, slo, workload, extra_specs):
        """Create the volume in the specified storage group.

        :param array: the array serial number
        :param storagegroup_name: the group name (String)
        :param srp: the SRP (String)
        :param slo: the SLO (String)
        :param workload: the workload (String)
        :param extra_specs: additional info
        :returns: storagegroup_name - string
        """
        srp_id = srp if slo else "None"
        payload = ({"srpId": srp_id,
                    "storageGroupId": storagegroup_name,
                    "emulation": "FBA",
                    "create_empty_storage_group": "true"})

        if slo:
            slo_param = {"num_of_vols": 0,
                         "sloId": slo,
                         "workloadSelection": workload,
                         "volumeAttribute": {
                             "volume_size": "0",
                             "capacityUnit": "GB"}}
            payload.update({"sloBasedStorageGroupParam": [slo_param]})

        status_code, job = self._create_storagegroup(array, payload)
        self.wait_for_job('Create storage group', status_code,
                          job, extra_specs)
        return storagegroup_name

    def modify_storage_group(self, array, storagegroup, payload):
        """Modify a storage group (PUT operation).

        :param array: the array serial number
        :param storagegroup: storage group name
        :param payload: the request payload
        :return: status_code -- int, message -- string, server response
        """
        return self.modify_resource(
            array, SLOPROVISIONING, 'storagegroup', payload,
            resource_name=storagegroup)

    def create_volume_from_sg(self, array, volume_name, storagegroup_name,
                              volume_size, extra_specs):
        """Create a new volume in the given storage group.

        :param array: the array serial number
        :param volume_name: the volume name (String)
        :param storagegroup_name: the storage group name
        :param volume_size: volume size (String)
        :param extra_specs: the extra specifications
        :returns: dict -- volume_dict - the volume dict
        :raises: VolumeBackendAPIException
        """
        payload = (
            {"executionOption": "ASYNCHRONOUS",
             "editStorageGroupActionParam": {
                 "expandStorageGroupParam": {
                     "addVolumeParam": {
                         "num_of_vols": 1,
                         "emulation": "FBA",
                         "volumeIdentifier": {
                             "identifier_name": volume_name,
                             "volumeIdentifierChoice": "identifier_name"},
                         "volumeAttribute": {
                             "volume_size": volume_size,
                             "capacityUnit": "GB"}}}}})
        status_code, job = self.modify_storage_group(
            array, storagegroup_name, payload)

        LOG.debug("Create Volume: %(volumename)s. Status code: %(sc)lu.",
                  {'volumename': volume_name,
                   'sc': status_code})

        task = self.wait_for_job('Create volume', status_code,
                                 job, extra_specs)

        # Find the newly created volume.
        device_id = None
        if task:
            for t in task:
                try:
                    desc = t["description"]
                    if CREATE_VOL_STRING in desc:
                        t_list = desc.split()
                        device_id = t_list[(len(t_list) - 1)]
                        device_id = device_id[1:-1]
                        break
                    if device_id:
                        self.get_volume(array, device_id)
                except Exception as e:
                    LOG.info("Could not retrieve device id from job. "
                             "Exception received was %(e)s. Attempting "
                             "retrieval by volume_identifier.",
                             {'e': e})

        if not device_id:
            device_id = self.find_volume_device_id(array, volume_name)

        volume_dict = {'array': array, 'device_id': device_id}
        return volume_dict

    def add_vol_to_sg(self, array, storagegroup_name, device_id, extra_specs):
        """Add a volume to a storage group.

        :param array: the array serial number
        :param storagegroup_name: storage group name
        :param device_id: the device id
        :param extra_specs: extra specifications
        """
        if not isinstance(device_id, list):
            device_id = [device_id]
        payload = ({"executionOption": "ASYNCHRONOUS",
                    "editStorageGroupActionParam": {
                        "expandStorageGroupParam": {
                            "addSpecificVolumeParam": {
                                "volumeId": device_id}}}})
        status_code, job = self.modify_storage_group(
            array, storagegroup_name, payload)

        self.wait_for_job('Add volume to sg', status_code, job, extra_specs)

    @retry(retry_exc_tuple, interval=2, retries=3)
    def remove_vol_from_sg(self, array, storagegroup_name,
                           device_id, extra_specs):
        """Remove a volume from a storage group.

        :param array: the array serial number
        :param storagegroup_name: storage group name
        :param device_id: the device id
        :param extra_specs: the extra specifications
        """
        if not isinstance(device_id, list):
            device_id = [device_id]
        payload = ({"executionOption": "ASYNCHRONOUS",
                    "editStorageGroupActionParam": {
                        "removeVolumeParam": {
                            "volumeId": device_id}}})
        status_code, job = self.modify_storage_group(
            array, storagegroup_name, payload)

        self.wait_for_job('Remove vol from sg', status_code, job, extra_specs)

    def get_vmax_default_storage_group(self, array, srp, slo, workload):
        """Get the default storage group.

        :param array: the array serial number
        :param srp: the pool name
        :param slo: the SLO
        :param workload: the workload
        :returns: the storage group dict (or None), the storage group name
        """
        storagegroup_name = self.utils.get_default_storage_group_name(
            srp, slo, workload)
        storagegroup = self.get_storage_group(array, storagegroup_name)
        return storagegroup, storagegroup_name

    def delete_storage_group(self, array, storagegroup_name):
        """Delete a storage group.

        :param array: the array serial number
        :param storagegroup_name: storage group name
        """
        self.delete_resource(
            array, SLOPROVISIONING, 'storagegroup', storagegroup_name)
        LOG.debug("Storage Group successfully deleted.")

    def get_volume(self, array, device_id):
        """Get a VMAX volume from array.

        :param array: the array serial number
        :param device_id: the volume device id
        :return: volume dict
        :raises: VolumeBackendAPIException
        """
        volume_dict = self.get_resource(
            array, SLOPROVISIONING, 'volume', resource_name=device_id)
        if not volume_dict:
            exception_message = (_("Volume %(deviceID)s not found.")
                                 % {'deviceID': device_id})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)
        return volume_dict

    def _get_private_volume(self, array, device_id):
        """Get a more detailed list of attributes of a volume.

        :param array: the array serial number
        :param device_id: the volume device id
        :return: volume dict
        :raises: VolumeBackendAPIException
        """
        try:
            wwn = (self.get_volume(array, device_id))['wwn']
            params = {'wwn': wwn}
            volume_info = self.get_resource(
                array, SLOPROVISIONING, 'volume', params=params,
                private='/private')
            volume_dict = volume_info['resultList']['result'][0]
        except KeyError:
            exception_message = (_("Volume %(deviceID)s not found.")
                                 % {'deviceID': device_id})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)
        return volume_dict

    def get_volume_list(self, array, params):
        """Get a filtered list of VMAX volumes from array.

        Filter parameters are required as the unfiltered volume list could be
        very large and could affect performance if called often.
        :param array: the array serial number
        :param params: filter parameters
        :return: device_ids -- list
        """
        device_ids = []
        volumes = self.get_resource(
            array, SLOPROVISIONING, 'volume', params=params)
        try:
            volume_dict_list = volumes['resultList']['result']
            for vol_dict in volume_dict_list:
                device_id = vol_dict['volumeId']
                device_ids.append(device_id)
        except (KeyError, TypeError):
            pass
        return device_ids

    def _modify_volume(self, array, device_id, payload):
        """Modify a volume (PUT operation).

        :param array: the array serial number
        :param device_id: volume device id
        :param payload: the request payload
        """
        return self.modify_resource(array, SLOPROVISIONING, 'volume',
                                    payload, resource_name=device_id)

    def extend_volume(self, array, device_id, new_size, extra_specs):
        """Extend a VMAX volume.

        :param array: the array serial number
        :param device_id: volume device id
        :param new_size: the new required size for the device
        :param extra_specs: the extra specifications
        """
        extend_vol_payload = {"executionOption": "ASYNCHRONOUS",
                              "editVolumeActionParam": {
                                  "expandVolumeParam": {
                                      "volumeAttribute": {
                                          "volume_size": new_size,
                                          "capacityUnit": "GB"}}}}

        status_code, job = self._modify_volume(
            array, device_id, extend_vol_payload)
        LOG.debug("Extend Device: %(device_id)s. Status code: %(sc)lu.",
                  {'device_id': device_id, 'sc': status_code})
        self.wait_for_job('Extending volume', status_code, job, extra_specs)

    def rename_volume(self, array, device_id, new_name):
        """Rename a volume.

        :param array: the array serial number
        :param device_id: the volume device id
        :param new_name: the new name for the volume
        """
        rename_vol_payload = {"editVolumeActionParam": {
            "modifyVolumeIdentifierParam": {
                "volumeIdentifier": {
                    "identifier_name": new_name,
                    "volumeIdentifierChoice": "identifier_name"}}}}
        self._modify_volume(array, device_id, rename_vol_payload)

    def delete_volume(self, array, device_id):
        """Deallocate and delete a volume.

        :param array: the array serial number
        :param device_id: volume device id
        """
        # Deallocate volume
        payload = {"editVolumeActionParam": {
            "freeVolumeParam": {"free_volume": 'true'}}}
        try:
            self._modify_volume(array, device_id, payload)
        except Exception as e:
            LOG.warning('Deallocate volume failed with %(e)s.'
                        'Attempting delete.', {'e': e})
        # Delete volume
        self.delete_resource(array, SLOPROVISIONING, "volume", device_id)

    def find_mv_connections_for_vol(self, array, maskingview, device_id):
        """Find the host_lun_id for a volume in a masking view.

        :param array: the array serial number
        :param maskingview: the masking view name
        :param device_id: the device ID
        :return: host_lun_id -- int
        """
        host_lun_id = None
        resource_name = ('%(maskingview)s/connections'
                         % {'maskingview': maskingview})
        params = {'volume_id': device_id}
        connection_info = self.get_resource(
            array, SLOPROVISIONING, 'maskingview',
            resource_name=resource_name, params=params)
        if not connection_info:
            LOG.error('Cannot retrive masking view connection information '
                      'for %(mv)s.', {'mv': maskingview})
        else:
            try:
                host_lun_id = (connection_info['maskingViewConnection']
                               [0]['host_lun_address'])
                host_lun_id = int(host_lun_id, 16)
            except Exception as e:
                LOG.error("Unable to retrieve connection information "
                          "for volume %(vol)s in masking view %(mv)s"
                          "Exception received: %(e)s.",
                          {'vol': device_id, 'mv': maskingview,
                           'e': e})
        return host_lun_id

    def get_storage_groups_from_volume(self, array, device_id):
        """Returns all the storage groups for a particular volume.

        :param array: the array serial number
        :param device_id: the volume device id
        :return: storagegroup_list
        """
        sg_list = []
        vol = self.get_volume(array, device_id)
        if vol and vol.get('storageGroupId'):
            sg_list = vol['storageGroupId']
        num_storage_groups = len(sg_list)
        LOG.debug("There are %(num)d storage groups associated "
                  "with volume %(deviceId)s.",
                  {'num': num_storage_groups, 'deviceId': device_id})
        return sg_list

    def is_volume_in_storagegroup(self, array, device_id, storagegroup):
        """See if a volume is a member of the given storage group.

        :param array: the array serial number
        :param device_id: the device id
        :param storagegroup: the storage group name
        :return: bool
        """
        is_vol_in_sg = False
        sg_list = self.get_storage_groups_from_volume(array, device_id)
        if storagegroup in sg_list:
            is_vol_in_sg = True
        return is_vol_in_sg

    def find_volume_device_id(self, array, volume_name):
        """Given a volume identifier, find the corresponding device_id.

        :param array: the array serial number
        :param volume_name: the volume name (OS-<UUID>)
        :return: device_id
        """
        device_id = None
        params = {"volume_identifier": volume_name}

        volume_list = self.get_volume_list(array, params)
        if not volume_list:
            LOG.debug("Cannot find record for volume %(volumeId)s.",
                      {'volumeId': volume_name})
        else:
            device_id = volume_list[0]
        return device_id

    def find_volume_identifier(self, array, device_id):
        """Get the volume identifier of a VMAX volume.

        :param array: array serial number
        :param device_id: the device id
        :return: the volume identifier -- string
        """
        vol = self.get_volume(array, device_id)
        return vol['volume_identifier']

    def get_size_of_device_on_array(self, array, device_id):
        """Get the size of the volume from the array.

        :param array: the array serial number
        :param device_id: the volume device id
        :return: size --  or None
        """
        cap = None
        try:
            vol = self.get_volume(array, device_id)
            cap = vol['cap_gb']
        except Exception as e:
            LOG.error("Error retrieving size of volume %(vol)s. "
                      "Exception received was %(e)s.",
                      {'vol': device_id, 'e': e})
        return cap

    def get_portgroup(self, array, portgroup):
        """Get a portgroup from the array.

        :param array: array serial number
        :param portgroup: the portgroup name
        :return: portgroup dict or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'portgroup', resource_name=portgroup)

    def get_port_ids(self, array, portgroup):
        """Get a list of port identifiers from a port group.

        :param array: the array serial number
        :param portgroup: the name of the portgroup
        :return: list of port ids, e.g. ['FA-3D:35', 'FA-4D:32']
        """
        portlist = []
        portgroup_info = self.get_portgroup(array, portgroup)
        if portgroup_info:
            port_key = portgroup_info["symmetrixPortKey"]
            for key in port_key:
                port = key['portId']
                portlist.append(port)
        return portlist

    def get_port(self, array, port_id):
        """Get director port details.

        :param array: the array serial number
        :param port_id: the port id
        :return: port dict, or None
        """
        dir_id = port_id.split(':')[0]
        port_no = port_id.split(':')[1]

        resource_name = ('%(directorId)s/port/%(port_number)s'
                         % {'directorId': dir_id, 'port_number': port_no})
        return self.get_resource(array, SLOPROVISIONING, 'director',
                                 resource_name=resource_name)

    def get_iscsi_ip_address_and_iqn(self, array, port_id):
        """Get the IPv4Address from the director port.

        :param array: the array serial number
        :param port_id: the director port identifier
        :return: (list of ip_addresses, iqn)
        """
        ip_addresses, iqn = None, None
        port_details = self.get_port(array, port_id)
        if port_details:
            ip_addresses = port_details['symmetrixPort']['ip_addresses']
            iqn = port_details['symmetrixPort']['identifier']
        return ip_addresses, iqn

    def get_target_wwns(self, array, portgroup):
        """Get the director ports' wwns.

        :param array: the array serial number
        :param portgroup: portgroup
        :returns: target_wwns -- the list of target wwns for the masking view
        """
        target_wwns = []
        port_ids = self.get_port_ids(array, portgroup)
        for port in port_ids:
            port_info = self.get_port(array, port)
            if port_info:
                wwn = port_info['symmetrixPort']['identifier']
                target_wwns.append(wwn)
            else:
                LOG.error("Error retrieving port %(port)s "
                          "from portgroup %(portgroup)s.",
                          {'port': port, 'portgroup': portgroup})
        return target_wwns

    def get_initiator_group(self, array, initiator_group=None, params=None):
        """Retrieve initiator group details from the array.

        :param array: the array serial number
        :param initiator_group: the initaitor group name
        :param params: optional filter parameters
        :return: initiator group dict, or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'host',
            resource_name=initiator_group, params=params)

    def get_initiator(self, array, initiator_id):
        """Retrieve initaitor details from the array.

        :param array: the array serial number
        :param initiator_id: the initiator id
        :return: initiator dict, or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'initiator',
            resource_name=initiator_id)

    def get_initiator_list(self, array, params=None):
        """Retrieve initaitor list from the array.

        :param array: the array serial number
        :param params: dict of optional params
        :return: list of initiators
        """
        init_dict = self.get_resource(
            array, SLOPROVISIONING, 'initiator', params=params)
        try:
            init_list = init_dict['initiatorId']
        except KeyError:
            init_list = []
        return init_list

    def get_in_use_initiator_list_from_array(self, array):
        """Get the list of initiators which are in-use from the array.

        Gets the list of initiators from the array which are in
        hosts/ initiator groups.
        :param array: the array serial number
        :return: init_list
        """
        params = {'in_a_host': 'true'}
        return self.get_initiator_list(array, params)

    def get_initiator_group_from_initiator(self, array, initiator):
        """Given an initiator, get its corresponding initiator group, if any.

        :param array: the array serial number
        :param initiator: the initiator id
        :return: found_init_group_name -- string
        """
        found_init_group_name = None
        init_details = self.get_initiator(array, initiator)
        if init_details:
            found_init_group_name = init_details.get('host')
        else:
            LOG.error("Unable to retrieve initiator details for "
                      "%(init)s.", {'init': initiator})
        return found_init_group_name

    def create_initiator_group(self, array, init_group_name,
                               init_list, extra_specs):
        """Create a new initiator group containing the given initiators.

        :param array: the array serial number
        :param init_group_name: the initiator group name
        :param init_list: the list of initiators
        :param extra_specs: extra specifications
        """
        new_ig_data = ({"executionOption": "ASYNCHRONOUS",
                        "hostId": init_group_name, "initiatorId": init_list})
        sc, job = self.create_resource(array, SLOPROVISIONING,
                                       'host', new_ig_data)
        self.wait_for_job('create initiator group', sc, job, extra_specs)

    def delete_initiator_group(self, array, initiatorgroup_name):
        """Delete an initiator group.

        :param array: the array serial number
        :param initiatorgroup_name: initiator group name
        """
        self.delete_resource(
            array, SLOPROVISIONING, 'host', initiatorgroup_name)
        LOG.debug("Initiator Group successfully deleted.")

    def get_masking_view(self, array, masking_view_name):
        """Get details of a masking view.

        :param array: array serial number
        :param masking_view_name: the masking view name
        :return: masking view dict
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'maskingview', masking_view_name)

    def get_masking_view_list(self, array, params):
        """Get a list of masking views from the array.

        :param array: array serial number
        :param params: optional GET parameters
        :return: masking view list
        """
        masking_view_list = []
        masking_view_details = self.get_resource(
            array, SLOPROVISIONING, 'maskingview', params=params)
        try:
            masking_view_list = masking_view_details['maskingViewId']
        except (KeyError, TypeError):
            pass
        return masking_view_list

    def get_masking_views_from_storage_group(self, array, storagegroup):
        """Return any masking views associated with a storage group.

        :param array: the array serial number
        :param storagegroup: the storage group name
        :return: masking view list
        """
        maskingviewlist = []
        storagegroup = self.get_storage_group(array, storagegroup)
        if storagegroup and storagegroup.get('maskingview'):
            maskingviewlist = storagegroup['maskingview']
        return maskingviewlist

    def get_masking_views_by_initiator_group(
            self, array, initiatorgroup_name):
        """Given initiator group, retrieve the masking view instance name.

        Retrieve the list of masking view instances associated with the
        given initiator group.
        :param array: the array serial number
        :param initiatorgroup_name: the name of the initiator group
        :returns: list of masking view names
        """
        masking_view_list = []
        ig_details = self.get_initiator_group(
            array, initiatorgroup_name)
        if ig_details:
            if ig_details.get('maskingview'):
                masking_view_list = ig_details['maskingview']
        else:
            LOG.error("Error retrieving initiator group %(ig_name)s",
                      {'ig_name': initiatorgroup_name})
        return masking_view_list

    def get_element_from_masking_view(
            self, array, maskingview_name, portgroup=False, host=False,
            storagegroup=False):
        """Return the name of the specified element from a masking view.

        :param array: the array serial number
        :param maskingview_name: the masking view name
        :param portgroup: the port group name - optional
        :param host: the host name - optional
        :param storagegroup: the storage group name - optional
        :return: name of the specified element -- string
        :raises: VolumeBackendAPIException
        """
        element = None
        masking_view_details = self.get_masking_view(array, maskingview_name)
        if masking_view_details:
            if portgroup:
                element = masking_view_details['portGroupId']
            elif host:
                element = masking_view_details['hostId']
            elif storagegroup:
                element = masking_view_details['storageGroupId']
        else:
            exception_message = (_("Error retrieving masking group."))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)
        return element

    def get_common_masking_views(self, array, portgroup_name, ig_name):
        """Get common masking views for a given portgroup and initiator group.

        :param array: the array serial number
        :param portgroup_name: the port group name
        :param ig_name: the initiator group name
        :return: masking view list
        """
        params = {'port_group_name': portgroup_name,
                  'host_or_host_group_name': ig_name}
        masking_view_list = self.get_masking_view_list(array, params)
        if not masking_view_list:
            LOG.info("No common masking views found for %(pg_name)s "
                     "and %(ig_name)s.",
                     {'pg_name': portgroup_name, 'ig_name': ig_name})
        return masking_view_list

    def create_masking_view(self, array, maskingview_name, storagegroup_name,
                            port_group_name, init_group_name, extra_specs):
        """Create a new masking view.

        :param array: the array serial number
        :param maskingview_name: the masking view name
        :param storagegroup_name: the storage group name
        :param port_group_name: the port group
        :param init_group_name: the initiator group
        :param extra_specs: extra specifications
        """
        payload = ({"executionOption": "ASYNCHRONOUS",
                    "portGroupSelection": {
                        "useExistingPortGroupParam": {
                            "portGroupId": port_group_name}},
                    "maskingViewId": maskingview_name,
                    "hostOrHostGroupSelection": {
                        "useExistingHostParam": {
                            "hostId": init_group_name}},
                    "storageGroupSelection": {
                        "useExistingStorageGroupParam": {
                            "storageGroupId": storagegroup_name}}})

        status_code, job = self.create_resource(
            array, SLOPROVISIONING, 'maskingview', payload)

        self.wait_for_job('Create masking view', status_code, job, extra_specs)

    def delete_masking_view(self, array, maskingview_name):
        """Delete a masking view.

        :param array: the array serial number
        :param maskingview_name: the masking view name
        """
        return self.delete_resource(
            array, SLOPROVISIONING, 'maskingview', maskingview_name)

    def get_replication_capabilities(self, array):
        """Check what replication features are licensed and enabled.

        Example return value for this method:
        {"symmetrixId": "000197800128",
         "snapVxCapable": true,
         "rdfCapable": true}
        :param: array
        :returns: capabilities dict for the given array
        """
        array_capabilities = None
        target_uri = ("/%s/replication/capabilities/symmetrix"
                      % U4V_VERSION)
        capabilities = self._get_request(
            target_uri, 'replication capabilities')
        if capabilities:
            symm_list = capabilities['symmetrixCapability']
            for symm in symm_list:
                if symm['symmetrixId'] == array:
                    array_capabilities = symm
                    break
        return array_capabilities

    def is_snapvx_licensed(self, array):
        """Check if the snapVx feature is licensed and enabled.

        :param array: the array serial number
        :returns: True if licensed and enabled; False otherwise.
        """
        snap_capability = False
        capabilities = self.get_replication_capabilities(array)
        if capabilities:
            snap_capability = capabilities['snapVxCapable']
        else:
            LOG.error("Cannot access replication capabilities "
                      "for array %(array)s", {'array': array})
        return snap_capability

    def create_volume_snap(self, array, snap_name, device_id, extra_specs):
        """Create a snapVx snapshot of a volume.

        :param array: the array serial number
        :param snap_name: the name of the snapshot
        :param device_id: the source device id
        :param extra_specs: the extra specifications
        """
        payload = {"deviceNameListSource": [{"name": device_id}],
                   "bothSides": 'false', "star": 'false',
                   "force": 'false'}
        resource_type = 'snapshot/%(snap)s' % {'snap': snap_name}
        status_code, job = self.create_resource(
            array, REPLICATION, resource_type,
            payload, private='/private')
        self.wait_for_job('Create volume snapVx', status_code,
                          job, extra_specs)

    def modify_volume_snap(self, array, source_id, target_id, snap_name,
                           extra_specs, link=False, unlink=False):
        """Link or unlink a snapVx to or from a target volume.

        :param array: the array serial number
        :param source_id: the source device id
        :param target_id: the target device id
        :param snap_name: the snapshot name
        :param extra_specs: extra specifications
        :param link: Flag to indicate action = Link
        :param unlink: Flag to indicate action = Unlink
        """
        action = ''
        if link:
            action = "Link"
        elif unlink:
            action = "Unlink"
        if action:
            payload = {"deviceNameListSource": [{"name": source_id}],
                       "deviceNameListTarget": [
                           {"name": target_id}],
                       "copy": 'true', "action": action,
                       "star": 'false', "force": 'false',
                       "exact": 'false', "remote": 'false',
                       "symforce": 'false', "nocopy": 'false'}
            status_code, job = self.modify_resource(
                array, REPLICATION, 'snapshot', payload,
                resource_name=snap_name, private='/private')

            self.wait_for_job('Modify snapVx relationship to target',
                              status_code, job, extra_specs)

    def delete_volume_snap(self, array, snap_name, source_device_id):
        """Delete the snapshot of a volume.

        :param array: the array serial number
        :param snap_name: the name of the snapshot
        :param source_device_id: the source device id
        """
        payload = {"deviceNameListSource": [{"name": source_device_id}]}
        return self.delete_resource(
            array, REPLICATION, 'snapshot', snap_name, payload=payload,
            private='/private')

    def get_volume_snap_info(self, array, source_device_id):
        """Get snapVx information associated with a volume.

        :param array: the array serial number
        :param source_device_id: the source volume device ID
        :return: message -- dict, or None
        """
        resource_name = ("%(device_id)s/snapshot"
                         % {'device_id': source_device_id})
        return self.get_resource(array, REPLICATION, 'volume',
                                 resource_name, private='/private')

    def get_volume_snap(self, array, device_id, snap_name):
        """Given a volume snap info, retrieve the snapVx object.

        :param array: the array serial number
        :param device_id: the source volume device id
        :param snap_name: the name of the snapshot
        :return: snapshot dict, or None
        """
        snapshot = None
        snap_info = self.get_volume_snap_info(array, device_id)
        if snap_info:
            if (snap_info.get('snapshotSrcs') and
                    bool(snap_info['snapshotSrcs'])):
                        for snap in snap_info['snapshotSrcs']:
                            if snap['snapshotName'] == snap_name:
                                snapshot = snap
        return snapshot

    def get_volume_snapshot_list(self, array, source_device_id):
        """Get a list of snapshot details for a particular volume.

        :param array: the array serial number
        :param source_device_id: the osurce device id
        :return: snapshot list or None
        """
        snapshot_list = []
        snap_info = self.get_volume_snap_info(array, source_device_id)
        if snap_info:
            if bool(snap_info['snapshotSrcs']):
                snapshot_list = snap_info['snapshotSrcs']
        return snapshot_list

    def is_vol_in_rep_session(self, array, device_id):
        """Check if a volume is in a replication session.

        :param array: the array serial number
        :param device_id: the device id
        :return: snapvx_tgt -- bool, snapvx_src -- bool,
                 rdf_grp -- list or None
        """
        snapvx_src = False
        snapvx_tgt = False
        rdf_grp = None
        volume_details = self.get_volume(array, device_id)
        if volume_details:
            if volume_details.get('snapvx_target'):
                snap_target = volume_details['snapvx_target']
                snapvx_tgt = True if snap_target == 'true' else False
            if volume_details.get('snapvx_source'):
                snap_source = volume_details['snapvx_source']
                snapvx_src = True if snap_source == 'true' else False
            if volume_details.get('rdfGroupId'):
                rdf_grp = volume_details['rdfGroupId']
        return snapvx_tgt, snapvx_src, rdf_grp

    def is_sync_complete(self, array, source_device_id,
                         target_device_id, snap_name, extra_specs):
        """Check if a sync session is complete.

        :param array: the array serial number
        :param source_device_id: source device id
        :param target_device_id: target device id
        :param snap_name: snapshot name
        :param extra_specs: extra specifications
        :return: bool
        """

        def _wait_for_sync():
            """Called at an interval until the synchronization is finished.

            :raises: loopingcall.LoopingCallDone
            :raises: VolumeBackendAPIException
            """
            retries = kwargs['retries']
            try:
                kwargs['retries'] = retries + 1
                if not kwargs['wait_for_sync_called']:
                    if self._is_sync_complete(
                            array, source_device_id, snap_name,
                            target_device_id):
                        kwargs['wait_for_sync_called'] = True
            except Exception:
                exception_message = (_("Issue encountered waiting for "
                                       "synchronization."))
                LOG.exception(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            if kwargs['retries'] > int(extra_specs[utils.RETRIES]):
                LOG.error("_wait_for_sync failed after %(retries)d "
                          "tries.", {'retries': retries})
                raise loopingcall.LoopingCallDone(
                    retvalue=int(extra_specs[utils.RETRIES]))
            if kwargs['wait_for_sync_called']:
                raise loopingcall.LoopingCallDone()

        kwargs = {'retries': 0,
                  'wait_for_sync_called': False}
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_sync)
        rc = timer.start(interval=int(
            extra_specs[utils.INTERVAL])).wait()
        return rc

    def _is_sync_complete(self, array, source_device_id, snap_name,
                          target_device_id):
        """Helper function to check if snapVx sync session is complete.

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: the snapshot name
        :param target_device_id: the target device id
        :return: defined -- bool
        """
        defined = True
        session = self._get_sync_session(
            array, source_device_id, snap_name, target_device_id)
        if session:
            defined = session['defined']
        return defined

    def _get_sync_session(self, array, source_device_id, snap_name,
                          target_device_id):
        """Get a particular sync session.

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: the snapshot name
        :param target_device_id: the target device id
        :return: sync session -- dict, or None
        """
        session = None
        linked_device_list = self.get_snap_linked_device_list(
            array, source_device_id, snap_name)
        for target in linked_device_list:
            if target_device_id == target['targetDevice']:
                session = target
        return session

    def _find_snap_vx_source_sessions(self, array, source_device_id):
        """Find all snap sessions for a given source volume.

        :param array: the array serial number
        :param source_device_id: the source device id
        :return: list of snapshot dicts
        """
        snap_dict_list = []
        snapshots = self.get_volume_snapshot_list(array, source_device_id)
        for snapshot in snapshots:
            if bool(snapshot['linkedDevices']):
                link_info = {'linked_vols': snapshot['linkedDevices'],
                             'snap_name': snapshot['snapshotName']}
                snap_dict_list.append(link_info)
        return snap_dict_list

    def get_snap_linked_device_list(self, array, source_device_id, snap_name):
        """Get the list of linked devices for a particular snapVx snapshot.

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: the snapshot name
        :return: linked_device_list
        """
        linked_device_list = []
        snap_list = self._find_snap_vx_source_sessions(array, source_device_id)
        for snap in snap_list:
            if snap['snap_name'] == snap_name:
                linked_device_list = snap['linked_vols']
        return linked_device_list

    def find_snap_vx_sessions(self, array, device_id, tgt_only=False):
        """Find all snapVX sessions for a device (source and target).

        :param array: the array serial number
        :param device_id: the device id
        :param tgt_only: Flag - return only sessions where device is target
        :return: list of snapshot dicts
        """
        snap_dict_list, sessions = [], []
        vol_details = self._get_private_volume(array, device_id)
        snap_vx_info = vol_details['timeFinderInfo']
        is_snap_src = snap_vx_info['snapVXSrc']
        is_snap_tgt = snap_vx_info['snapVXTgt']
        if snap_vx_info.get('snapVXSession'):
            sessions = snap_vx_info['snapVXSession']
        if is_snap_src and not tgt_only:
            for session in sessions:
                if session.get('srcSnapshotGenInfo'):
                    src_list = session['srcSnapshotGenInfo']
                    for src in src_list:
                        snap_name = src['snapshotHeader']['snapshotName']
                        target_list, target_dict = [], {}
                        if src.get('lnkSnapshotGenInfo'):
                            target_dict = src['lnkSnapshotGenInfo']
                        for tgt in target_dict:
                            target_list.append(tgt['targetDevice'])
                        link_info = {'target_vol_list': target_list,
                                     'snap_name': snap_name,
                                     'source_vol': device_id}
                        snap_dict_list.append(link_info)
        if is_snap_tgt:
            for session in sessions:
                if session.get('tgtSrcSnapshotGenInfo'):
                    tgt = session['tgtSrcSnapshotGenInfo']
                    snap_name = tgt['snapshotName']
                    target_list = [tgt['targetDevice']]
                    source_vol = tgt['sourceDevice']
                    link_info = {'target_vol_list': target_list,
                                 'snap_name': snap_name,
                                 'source_vol': source_vol}
                    snap_dict_list.append(link_info)
        return snap_dict_list
