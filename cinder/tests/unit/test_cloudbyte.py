# Copyright 2015 CloudByte Inc.
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

""" Test class for cloudbyte's cinder driver.

This involves mocking of elasticenter's json responses
when a method of this driver is unit tested.
"""

import json

import mock
import testtools
from testtools import matchers

from cinder import context
from cinder import exception
from cinder.volume import configuration as conf
from cinder.volume.drivers.cloudbyte import cloudbyte
from cinder.volume import qos_specs
from cinder.volume import volume_types

# A fake list account response of cloudbyte's elasticenter
FAKE_LIST_ACCOUNT_RESPONSE = """{ "listAccountResponse" : {
    "count":1 ,
    "account" : [{
        "id": "d13a4e9e-0c05-4d2d-8a5e-5efd3ef058e0",
        "name": "CustomerA",
        "simpleid": 1,
        "description": "None",
        "iqnname": "iqn.2014-05.cvsacc1",
        "availIOPS": 508,
        "totaliops": 2000,
        "usedIOPS": 1492,
        "volumes": [],
        "storageBuckets": [],
        "tsms": [],
        "qosgroups": [],
        "filesystemslist": [],
        "currentUsedSpace": 53179,
        "currentAvailableSpace": 1249349,
        "currentThroughput": 156,
        "currentIOPS": 33,
        "currentLatency": 0,
        "currentThrottle": 0,
        "numericquota": 3145728.0,
        "currentnumericquota": 1253376.0,
        "currentavailablequota": 1892352.0,
        "revisionnumber": 1
    }]
    }}"""

# A fake list tsm response of cloudbyte's elasticenter
FAKE_LIST_TSM_RESPONSE = """{ "listTsmResponse" : {
    "count":1 ,
    "listTsm" : [{
        "id": "955eaf34-4221-3a77-82d0-99113b126fa8",
        "simpleid": 2,
        "name": "openstack",
        "ipaddress": "172.16.50.40",
        "accountname": "CustomerA",
        "sitename": "BLR",
        "clustername": "HAGrp1",
        "controllerName": "Controller",
        "controlleripaddress": "172.16.50.6",
        "clusterstatus": "Online",
        "hapoolstatus": "ONLINE",
        "hapoolname": "pool",
        "hapoolavailiops": 1700,
        "hapoolgrace": true,
        "hapoolavailtput": 6800,
        "poollatency": 10,
        "accountid": "d13a4e9e-0c05-4d2d-8a5e-5efd3ef058e0",
        "controllerid": "8c2f7084-99c0-36e6-9cb7-205e3ba4c813",
        "poolid": "adcbef8f-2193-3f2c-9bb1-fcaf977ae0fc",
        "datasetid": "87a23025-f2b2-39e9-85ac-9cda15bfed1a",
        "storageBuckets": [],
        "currentUsedSpace": 16384,
        "currentAvailableSpace": 188416,
        "currentTotalSpace": 204800,
        "currentThroughput": 12,
        "tpcontrol": "true",
        "currentIOPS": 0,
        "iopscontrol": "true",
        "gracecontrol": "false",
        "currentLatency": 0,
        "currentThrottle": 0,
        "iops": "1000",
        "availIOPS": "500",
        "availThroughput": "2000",
        "usedIOPS": "500",
        "usedThroughput": "2000",
        "throughput": "4000",
        "latency": "15",
        "graceallowed": true,
        "numericquota": 1048576.0,
        "currentnumericquota": 204800.0,
        "availablequota": 843776.0,
        "blocksize": "4",
        "type": "1",
        "iqnname": "iqn.2014-05.cvsacc1.openstack",
        "interfaceName": "em0",
        "revisionnumber": 0,
        "status": "Online",
        "subnet": "16",
        "managedstate": "Available",
        "configurationstate": "sync",
        "offlinenodes": "",
        "pooltakeover": "noTakeOver",
        "totalprovisionquota": "536576",
        "haNodeStatus": "Available",
        "ispooltakeoveronpartialfailure": true,
        "filesystemslist": [],
        "volumes": [],
        "qosgrouplist": []
    }]
    }}"""

# A fake add QOS group response of cloudbyte's elasticenter
FAKE_ADD_QOS_GROUP_RESPONSE = """{ "addqosgroupresponse" : {
    "qosgroup" : {
        "id": "d73662ac-6db8-3b2c-981a-012af4e2f7bd",
        "name": "QoS_DS1acc1openstacktsm",
        "tsmid": "8146146e-f67b-3942-8074-3074599207a4",
        "controllerid": "f1603e87-d1e6-3dcb-a549-7a6e77f82d86",
        "poolid": "73b567c0-e57d-37b5-b765-9d70725f59af",
        "parentid": "81ebdcbb-f73b-3337-8f32-222820e6acb9",
        "tsmName": "openstacktsm",
        "offlinenodes": "",
        "sitename": "site1",
        "clustername": "HA1",
        "controllerName": "node1",
        "clusterstatus": "Online",
        "currentThroughput": 0,
        "currentIOPS": 0,
        "currentLatency": 0,
        "currentThrottle": 0,
        "iopsvalue": "(0/100)",
        "throughputvalue": "(0/400)",
        "iops": "100",
        "iopscontrol": "true",
        "throughput": "400",
        "tpcontrol": "true",
        "blocksize": "4k",
        "latency": "15",
        "graceallowed": false,
        "type": "1",
        "revisionnumber": 0,
        "managedstate": "Available",
        "configurationstate": "init",
        "standardproviops": 0,
        "operatingblocksize": 0,
        "operatingcachehit": 0,
        "operatingiops": 0,
        "standardoperatingiops": 0
    }
    }}"""

# A fake create volume response of cloudbyte's elasticenter
FAKE_CREATE_VOLUME_RESPONSE = """{ "createvolumeresponse" : {
        "jobid": "f94e2257-9515-4a44-add0-4b16cb1bcf67"
    }}"""

# A fake query async job response of cloudbyte's elasticenter
FAKE_QUERY_ASYNC_JOB_RESULT_RESPONSE = """{ "queryasyncjobresultresponse" : {
    "accountid": "e8aca633-7bce-4ab7-915a-6d8847248467",
    "userid": "a83d1030-1b85-40f7-9479-f40e4dbdd5d5",
    "cmd": "com.cloudbyte.api.commands.CreateVolumeCmd",
    "msg": "5",
    "jobstatus": 1,
    "jobprocstatus": 0,
    "jobresultcode": 0,
    "jobresulttype": "object",
    "jobresult": {
    "storage": {
        "id": "92cfd601-bc1f-3fa7-8322-c492099f3326",
        "name": "DS1",
        "simpleid": 20,
        "compression": "off",
        "sync": "always",
        "noofcopies": 1,
        "recordsize": "4k",
        "deduplication": "off",
        "quota": "10G",
        "path": "devpool1/acc1openstacktsm/DS1",
        "tsmid": "8146146e-f67b-3942-8074-3074599207a4",
        "poolid": "73b567c0-e57d-37b5-b765-9d70725f59af",
        "mountpoint": "acc1DS1",
        "currentUsedSpace": 0,
        "currentAvailableSpace": 0,
        "currentTotalSpace": 0,
        "currentThroughput": 0,
        "currentIOPS": 0,
        "currentLatency": 0,
        "currentThrottle": 0,
        "tsmName": "openstacktsm",
        "hapoolname": "devpool1",
        "revisionnumber": 0,
        "blocklength": "512B",
        "nfsenabled": false,
        "cifsenabled": false,
        "iscsienabled": true,
        "fcenabled": false
    }
    },
    "created": "2014-06-16 15:49:49",
    "jobid": "f94e2257-9515-4a44-add0-4b16cb1bcf67"
    }}"""

# A fake list filesystem response of cloudbyte's elasticenter
FAKE_LIST_FILE_SYSTEM_RESPONSE = """{ "listFilesystemResponse" : {
    "count":1 ,
    "filesystem" : [{
        "id": "c93df32e-3a99-3491-8e10-cf318a7f9b7f",
        "name": "c93df32e3a9934918e10cf318a7f9b7f",
        "simpleid": 34,
        "type": "filesystem",
        "revisionnumber": 1,
        "path": "/cvsacc1DS1",
        "clusterid": "8b404f12-7975-4e4e-8549-7abeba397fc9",
        "clusterstatus": "Online",
        "Tsmid": "955eaf34-4221-3a77-82d0-99113b126fa8",
        "tsmType": "1",
        "accountid": "d13a4e9e-0c05-4d2d-8a5e-5efd3ef058e0",
        "poolid": "adcbef8f-2193-3f2c-9bb1-fcaf977ae0fc",
        "controllerid": "8c2f7084-99c0-36e6-9cb7-205e3ba4c813",
        "groupid": "663923c9-084b-3778-b13d-72f23d046b8d",
        "parentid": "08de7c14-62af-3992-8407-28f5f053e59b",
        "compression": "off",
        "sync": "always",
        "noofcopies": 1,
        "recordsize": "4k",
        "deduplication": "off",
        "quota": "1T",
        "unicode": "off",
        "casesensitivity": "sensitive",
        "readonly": false,
        "nfsenabled": true,
        "cifsenabled": false,
        "iscsienabled": false,
        "fcenabled": false,
        "currentUsedSpace": 19968,
        "currentAvailableSpace": 1028608,
        "currentTotalSpace": 1048576,
        "currentThroughput": 0,
        "currentIOPS": 0,
        "currentLatency": 0,
        "currentThrottle": 0,
        "numericquota": 1048576.0,
        "status": "Online",
        "managedstate": "Available",
        "configurationstate": "sync",
        "tsmName": "cvstsm1",
        "ipaddress": "172.16.50.35",
        "sitename": "BLR",
        "clustername": "HAGrp1",
        "controllerName": "Controller",
        "hapoolname": "pool",
        "hapoolgrace": true,
        "tsmgrace": true,
        "tsmcontrolgrace": "false",
        "accountname": "CustomerA",
        "groupname": "QoS_DS1cvsacc1cvstsm1",
        "iops": "500",
        "blocksize": "4",
        "throughput": "2000",
        "latency": "15",
        "graceallowed": false,
        "offlinenodes": "",
        "tpcontrol": "true",
        "iopscontrol": "true",
        "tsmAvailIops": "8",
        "tsmAvailTput": "32",
        "iqnname": "",
        "mountpoint": "cvsacc1DS1",
        "pooltakeover": "noTakeOver",
        "volumeaccessible": "true",
        "localschedulecount": 0
    }]
    }}"""

# A fake list storage snapshot response of cloudbyte's elasticenter
FAKE_LIST_STORAGE_SNAPSHOTS_RESPONSE = """{ "listDatasetSnapshotsResponse" : {
    "count":1 ,
    "snapshot" : [{
        "name": "snap_c60890b1f23646f29e6d51e6e592cee6",
        "path": "DS1@snap_c60890b1f23646f29e6d51e6e592cee6",
        "availMem": "-",
        "usedMem": "0",
        "refer": "26K",
        "mountpoint": "-",
        "timestamp": "Mon Jun 16 2014 14:41",
        "clones": 0,
        "pooltakeover": "noTakeOver",
        "managedstate": "Available"
    }]
    }}"""

# A fake delete storage snapshot response of cloudbyte's elasticenter
FAKE_DELETE_STORAGE_SNAPSHOT_RESPONSE = """{ "deleteSnapshotResponse" :  {
    "DeleteSnapshot" : {
        "status": "success"
    }
    }}"""

# A fake update volume iscsi service response of cloudbyte's elasticenter
FAKE_UPDATE_VOLUME_ISCSI_SERVICE_RESPONSE = (
    """{ "updatingvolumeiscsidetails" :  {
    "viscsioptions" : {
        "id": "0426c04a-8fac-30e8-a8ad-ddab2f08013a",
        "volume_id": "12371e7c-392b-34b9-ac43-073b3c85f1d1",
        "ag_id": "4459248d-e9f1-3d2a-b7e8-b5d9ce587fc1",
        "ig_id": "527bd65b-ebec-39ce-a5e9-9dd1106cc0fc",
        "iqnname": "iqn.2014-06.acc1.openstacktsm:acc1DS1",
        "authmethod": "None",
        "status": true,
        "usn": "12371e7c392b34b9ac43073b3c85f1d1",
        "initialdigest": "Auto",
        "queuedepth": "32",
        "inqproduct": 0,
        "inqrevision": 0,
        "blocklength": "512B"
    }}
    }""")

# A fake list iscsi initiator response of cloudbyte's elasticenter
FAKE_LIST_ISCSI_INITIATOR_RESPONSE = """{ "listInitiatorsResponse" : {
    "count":2 ,
    "initiator" : [{
        "id": "527bd65b-ebec-39ce-a5e9-9dd1106cc0fc",
        "accountid": "86c5251a-9044-4690-b924-0d97627aeb8c",
        "name": "ALL",
        "netmask": "ALL",
        "initiatorgroup": "ALL"
        },{
        "id": "203e0235-1d5a-3130-9204-98e3f642a564",
        "accountid": "86c5251a-9044-4690-b924-0d97627aeb8c",
        "name": "None",
        "netmask": "None",
        "initiatorgroup": "None"
        }]
     }}"""

# A fake delete file system response of cloudbyte's elasticenter
FAKE_DELETE_FILE_SYSTEM_RESPONSE = """{ "deleteFileSystemResponse" : {
        "jobid": "e1fe861a-17e3-41b5-ae7c-937caac62cdf"
    }}"""

# A fake create storage snapshot response of cloudbyte's elasticenter
FAKE_CREATE_STORAGE_SNAPSHOT_RESPONSE = (
    """{ "createStorageSnapshotResponse" :  {
    "StorageSnapshot" : {
        "id": "21d7a92a-f15e-3f5b-b981-cb30697b8028",
        "name": "snap_c60890b1f23646f29e6d51e6e592cee6",
        "usn": "21d7a92af15e3f5bb981cb30697b8028",
        "lunusn": "12371e7c392b34b9ac43073b3c85f1d1",
        "lunid": "12371e7c-392b-34b9-ac43-073b3c85f1d1",
        "scsiEnabled": false
    }}
    }""")

# A fake list volume iscsi service response of cloudbyte's elasticenter
FAKE_LIST_VOLUME_ISCSI_SERVICE_RESPONSE = (
    """{ "listVolumeiSCSIServiceResponse" : {
    "count":1 ,
    "iSCSIService" : [{
        "id": "67ddcbf4-6887-3ced-8695-7b9cdffce885",
        "volume_id": "c93df32e-3a99-3491-8e10-cf318a7f9b7f",
        "ag_id": "4459248d-e9f1-3d2a-b7e8-b5d9ce587fc1",
        "ig_id": "203e0235-1d5a-3130-9204-98e3f642a564",
        "iqnname": "iqn.2014-06.acc1.openstacktsm:acc1DS1",
        "authmethod": "None",
        "status": true,
        "usn": "92cfd601bc1f3fa78322c492099f3326",
        "initialdigest": "Auto",
        "queuedepth": "32",
        "inqproduct": 0,
        "inqrevision": 0,
        "blocklength": "512B"
    }]
    }}""")

# A fake clone dataset snapshot response of cloudbyte's elasticenter
FAKE_CLONE_DATASET_SNAPSHOT_RESPONSE = """{ "cloneDatasetSnapshot" : {
    "filesystem" : {
        "id": "dcd46a57-e3f4-3fc1-8dd8-2e658d9ebb11",
        "name": "DS1Snap1clone1",
        "simpleid": 21,
        "type": "volume",
        "revisionnumber": 1,
        "path": "iqn.2014-06.acc1.openstacktsm:acc1DS1Snap1clone1",
        "clusterid": "0ff44329-9a69-4611-bac2-6eaf1b08bb18",
        "clusterstatus": "Online",
        "Tsmid": "8146146e-f67b-3942-8074-3074599207a4",
        "tsmType": "1",
        "accountid": "86c5251a-9044-4690-b924-0d97627aeb8c",
        "poolid": "73b567c0-e57d-37b5-b765-9d70725f59af",
        "controllerid": "f1603e87-d1e6-3dcb-a549-7a6e77f82d86",
        "groupid": "d73662ac-6db8-3b2c-981a-012af4e2f7bd",
        "parentid": "81ebdcbb-f73b-3337-8f32-222820e6acb9",
        "compression": "off",
        "sync": "always",
        "noofcopies": 1,
        "recordsize": "4k",
        "deduplication": "off",
        "quota": "10G",
        "unicode": "off",
        "casesensitivity": "sensitive",
        "readonly": false,
        "nfsenabled": false,
        "cifsenabled": false,
        "iscsienabled": true,
        "fcenabled": false,
        "currentUsedSpace": 0,
        "currentAvailableSpace": 10240,
        "currentTotalSpace": 10240,
        "currentThroughput": 0,
        "currentIOPS": 0,
        "currentLatency": 0,
        "currentThrottle": 0,
        "numericquota": 10240.0,
        "status": "Online",
        "managedstate": "Available",
        "configurationstate": "sync",
        "tsmName": "openstacktsm",
        "ipaddress": "20.10.22.56",
        "sitename": "site1",
        "clustername": "HA1",
        "controllerName": "node1",
        "hapoolname": "devpool1",
        "hapoolgrace": true,
        "tsmgrace": true,
        "tsmcontrolgrace": "false",
        "accountname": "acc1",
        "groupname": "QoS_DS1acc1openstacktsm",
        "iops": "100",
        "blocksize": "4k",
        "throughput": "400",
        "latency": "15",
        "graceallowed": false,
        "offlinenodes": "",
        "tpcontrol": "true",
        "iopscontrol": "true",
        "tsmAvailIops": "700",
        "tsmAvailTput": "2800",
        "iqnname": "iqn.2014-06.acc1.openstacktsm:acc1DS1Snap1clone1",
        "mountpoint": "acc1DS1Snap1clone1",
        "blocklength": "512B",
        "volumeaccessible": "true",
        "localschedulecount": 0
    }
    }}"""

# A fake update filesystem response of cloudbyte's elasticenter
FAKE_UPDATE_FILE_SYSTEM_RESPONSE = """{ "updatefilesystemresponse" : {
    "count":1 ,
    "filesystem" : [{
        "id": "92cfd601-bc1f-3fa7-8322-c492099f3326",
        "name": "DS1",
        "simpleid": 20,
        "type": "volume",
        "revisionnumber": 1,
        "path": "iqn.2014-06.acc1.openstacktsm:acc1DS1",
        "clusterid": "0ff44329-9a69-4611-bac2-6eaf1b08bb18",
        "clusterstatus": "Online",
        "Tsmid": "8146146e-f67b-3942-8074-3074599207a4",
        "tsmType": "1",
        "accountid": "86c5251a-9044-4690-b924-0d97627aeb8c",
        "poolid": "73b567c0-e57d-37b5-b765-9d70725f59af",
        "controllerid": "f1603e87-d1e6-3dcb-a549-7a6e77f82d86",
        "groupid": "d73662ac-6db8-3b2c-981a-012af4e2f7bd",
        "parentid": "81ebdcbb-f73b-3337-8f32-222820e6acb9",
        "compression": "off",
        "sync": "always",
        "noofcopies": 1,
        "recordsize": "4k",
        "deduplication": "off",
        "quota": "12G",
        "unicode": "off",
        "casesensitivity": "sensitive",
        "readonly": false,
        "nfsenabled": false,
        "cifsenabled": false,
        "iscsienabled": true,
        "fcenabled": false,
        "currentUsedSpace": 0,
        "currentAvailableSpace": 10240,
        "currentTotalSpace": 10240,
        "currentThroughput": 0,
        "currentIOPS": 0,
        "currentLatency": 0,
        "currentThrottle": 0,
        "numericquota": 12288.0,
        "status": "Online",
        "managedstate": "Available",
        "configurationstate": "sync",
        "tsmName": "openstacktsm",
        "ipaddress": "20.10.22.56",
        "sitename": "site1",
        "clustername": "HA1",
        "controllerName": "node1",
        "hapoolname": "devpool1",
        "hapoolgrace": true,
        "tsmgrace": true,
        "tsmcontrolgrace": "false",
        "accountname": "acc1",
        "groupname": "QoS_DS1acc1openstacktsm",
        "iops": "100",
        "blocksize": "4k",
        "throughput": "400",
        "latency": "15",
        "graceallowed": false,
        "offlinenodes": "",
        "tpcontrol": "true",
        "iopscontrol": "true",
        "tsmAvailIops": "700",
        "tsmAvailTput": "2800",
        "iqnname": "iqn.2014-06.acc1.openstacktsm:acc1DS1",
        "mountpoint": "acc1DS1",
        "blocklength": "512B",
        "volumeaccessible": "true",
        "localschedulecount": 0
    }]
    }}"""

# A fake update QOS group response of cloudbyte's elasticenter
FAKE_UPDATE_QOS_GROUP_RESPONSE = """{ "updateqosresponse" : {
    "count":1 ,
    "qosgroup" : [{
        "id": "d73662ac-6db8-3b2c-981a-012af4e2f7bd",
        "name": "QoS_DS1acc1openstacktsm",
        "tsmid": "8146146e-f67b-3942-8074-3074599207a4",
        "controllerid": "f1603e87-d1e6-3dcb-a549-7a6e77f82d86",
        "poolid": "73b567c0-e57d-37b5-b765-9d70725f59af",
        "parentid": "81ebdcbb-f73b-3337-8f32-222820e6acb9",
        "tsmName": "openstacktsm",
        "offlinenodes": "",
        "sitename": "site1",
        "clustername": "HA1",
        "controllerName": "node1",
        "clusterstatus": "Online",
        "currentThroughput": 0,
        "currentIOPS": 0,
        "currentLatency": 0,
        "currentThrottle": 0,
        "iopsvalue": "(0/101)",
        "throughputvalue": "(0/404)",
        "iops": "101",
        "iopscontrol": "true",
        "throughput": "404",
        "tpcontrol": "true",
        "blocksize": "4k",
        "latency": "15",
        "graceallowed": true,
        "type": "1",
        "revisionnumber": 2,
        "managedstate": "Available",
        "configurationstate": "sync",
        "status": "Online",
        "standardproviops": 0,
        "operatingblocksize": 0,
        "operatingcachehit": 0,
        "operatingiops": 0,
        "standardoperatingiops": 0
    }]
    }}"""

# A fake list iSCSI auth user response of cloudbyte's elasticenter
FAKE_LIST_ISCSI_AUTH_USER_RESPONSE = """{ "listiSCSIAuthUsersResponse" : {
    "count":1 ,
    "authuser" : [{
        "id": "53d00164-a974-31b8-a854-bd346a8ea937",
        "accountid": "12d41531-c41a-4ab7-abe2-ce0db2570119",
        "authgroupid": "537744eb-c594-3145-85c0-96079922b894",
        "chapusername": "fakeauthgroupchapuser",
        "chappassword": "fakeauthgroupchapsecret",
        "mutualchapusername": "fakeauthgroupmutualchapuser",
        "mutualchappassword": "fakeauthgroupmutualchapsecret"
    }]
    }}"""

# A fake list iSCSI auth group response of cloudbyte's elasticenter
FAKE_LIST_ISCSI_AUTH_GROUP_RESPONSE = """{ "listiSCSIAuthGroupResponse" : {
    "count":2 ,
    "authgroup" : [{
        "id": "32d935ee-a60f-3681-b792-d8ccfe7e8e7f",
        "name": "None",
        "comment": "None"
        }, {
        "id": "537744eb-c594-3145-85c0-96079922b894",
        "name": "fakeauthgroup",
        "comment": "Fake Auth Group For Openstack "
    }]
    }}"""


# This dict maps the http commands of elasticenter
# with its respective fake responses
MAP_COMMAND_TO_FAKE_RESPONSE = {}

MAP_COMMAND_TO_FAKE_RESPONSE['deleteFileSystem'] = (
    json.loads(FAKE_DELETE_FILE_SYSTEM_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["listFileSystem"] = (
    json.loads(FAKE_LIST_FILE_SYSTEM_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["deleteSnapshot"] = (
    json.loads(FAKE_DELETE_STORAGE_SNAPSHOT_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["updateVolumeiSCSIService"] = (
    json.loads(FAKE_UPDATE_VOLUME_ISCSI_SERVICE_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["createStorageSnapshot"] = (
    json.loads(FAKE_CREATE_STORAGE_SNAPSHOT_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["listAccount"] = (
    json.loads(FAKE_LIST_ACCOUNT_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["listTsm"] = (
    json.loads(FAKE_LIST_TSM_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["addQosGroup"] = (
    json.loads(FAKE_ADD_QOS_GROUP_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["queryAsyncJobResult"] = (
    json.loads(FAKE_QUERY_ASYNC_JOB_RESULT_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["createVolume"] = (
    json.loads(FAKE_CREATE_VOLUME_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["listVolumeiSCSIService"] = (
    json.loads(FAKE_LIST_VOLUME_ISCSI_SERVICE_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE["listiSCSIInitiator"] = (
    json.loads(FAKE_LIST_ISCSI_INITIATOR_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE['cloneDatasetSnapshot'] = (
    json.loads(FAKE_CLONE_DATASET_SNAPSHOT_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE['updateFileSystem'] = (
    json.loads(FAKE_UPDATE_FILE_SYSTEM_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE['updateQosGroup'] = (
    json.loads(FAKE_UPDATE_QOS_GROUP_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE['listStorageSnapshots'] = (
    json.loads(FAKE_LIST_STORAGE_SNAPSHOTS_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE['listiSCSIAuthUser'] = (
    json.loads(FAKE_LIST_ISCSI_AUTH_USER_RESPONSE))
MAP_COMMAND_TO_FAKE_RESPONSE['listiSCSIAuthGroup'] = (
    json.loads(FAKE_LIST_ISCSI_AUTH_GROUP_RESPONSE))


class CloudByteISCSIDriverTestCase(testtools.TestCase):

    def setUp(self):
        super(CloudByteISCSIDriverTestCase, self).setUp()
        self._configure_driver()
        self.ctxt = context.get_admin_context()

    def _configure_driver(self):

        configuration = conf.Configuration(None, None)

        # initialize the elasticenter iscsi driver
        self.driver = cloudbyte.CloudByteISCSIDriver(
            configuration=configuration)

        # override some parts of driver configuration
        self.driver.configuration.cb_tsm_name = 'openstack'
        self.driver.configuration.cb_account_name = 'CustomerA'
        self.driver.configuration.cb_auth_group = 'fakeauthgroup'
        self.driver.configuration.cb_apikey = 'G4ZUB39WH7lbiZhPhL3nbd'
        self.driver.configuration.san_ip = '172.16.51.30'

    def _side_effect_api_req(self, cmd, params, version='1.0'):
        """This is a side effect function.

        The return value is determined based on cmd argument.
        The signature matches exactly with the method it tries
        to mock.
        """
        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_create_vol(self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'createVolume':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_delete_file_system(
            self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'deleteFileSystem':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_query_asyncjob_response(
            self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'queryAsyncJobResult':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_query_asyncjob(
            self, cmd, params, version='1.0'):
        """This is a side effect function."""

        if cmd == 'queryAsyncJobResult':
            return {'queryasyncjobresultresponse': {'jobstatus': 0}}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_list_tsm(self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'listTsm':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _none_response_to_list_tsm(self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'listTsm':
            return {"listTsmResponse": {}}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_list_iscsi_auth_group(self, cmd, params,
                                                      version='1.0'):
        """This is a side effect function."""
        if cmd == 'listiSCSIAuthGroup':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_list_iscsi_auth_user(self, cmd, params,
                                                     version='1.0'):
        """This is a side effect function."""
        if cmd == 'listiSCSIAuthUser':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_enable_chap(self):
        """This is a side effect function."""
        self.driver.cb_use_chap = True

    def _side_effect_disable_chap(self):
        """This is a side effect function."""
        self.driver.cb_use_chap = False

    def _side_effect_api_req_to_list_filesystem(
            self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'listFileSystem':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _fake_api_req_to_list_filesystem(
            self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'listFileSystem':
            return {"listFilesystemResponse": {"filesystem": [{}]}}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_list_vol_iscsi_service(
            self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'listVolumeiSCSIService':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_api_req_to_list_iscsi_initiator(
            self, cmd, params, version='1.0'):
        """This is a side effect function."""
        if cmd == 'listiSCSIInitiator':
            return {}

        return MAP_COMMAND_TO_FAKE_RESPONSE[cmd]

    def _side_effect_create_vol_from_snap(self, cloned_volume, snapshot):
        """This is a side effect function."""
        return {}

    def _side_effect_create_snapshot(self, snapshot):
        """This is a side effect function."""
        model_update = {}
        model_update['provider_id'] = "devpool1/acc1openstacktsm/DS1@DS1Snap1"
        return model_update

    def _side_effect_get_connection(self, host, url):
        """This is a side effect function."""

        return_obj = {}

        return_obj['http_status'] = 200

        # mock the response data
        return_obj['data'] = MAP_COMMAND_TO_FAKE_RESPONSE['listTsm']
        return_obj['error'] = None

        return return_obj

    def _side_effect_get_err_connection(self, host, url):
        """This is a side effect function."""

        return_obj = {}

        return_obj['http_status'] = 500

        # mock the response data
        return_obj['data'] = None
        return_obj['error'] = "Http status: 500, Error: Elasticenter "
        "is not available."

        return return_obj

    def _side_effect_get_err_connection2(self, host, url):
        """This is a side effect function."""

        msg = ("Error executing CloudByte API %(cmd)s , Error: %(err)s" %
               {'cmd': 'MockTest', 'err': 'Error'})
        raise exception.VolumeBackendAPIException(msg)

    def _get_fake_volume_id(self):

        # Get the filesystems
        fs_list = MAP_COMMAND_TO_FAKE_RESPONSE['listFileSystem']
        filesystems = fs_list['listFilesystemResponse']['filesystem']

        # Get the volume id from the first filesystem
        volume_id = filesystems[0]['id']

        return volume_id

    def _fake_get_volume_type(self, ctxt, type_id):
        fake_type = {'qos_specs_id': 'fake-id',
                     'extra_specs': {'qos:iops': '100000'},
                     'id': 'fake-volume-type-id'}

        return fake_type

    def _fake_get_qos_spec(self, ctxt, spec_id):
        fake_qos_spec = {'id': 'fake-qos-spec-id',
                         'specs': {'iops': '1000',
                                   'graceallowed': 'true',
                                   'readonly': 'true'}}
        return fake_qos_spec

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_execute_and_get_response_details')
    def test_api_request_for_cloudbyte(self, mock_conn):

        # Test - I

        # configure the mocks with respective side-effects
        mock_conn.side_effect = self._side_effect_get_connection

        # run the test
        data = self.driver._api_request_for_cloudbyte('listTsm', {})

        # assert the data attributes
        self.assertEqual(1, data['listTsmResponse']['count'])

        # Test - II

        # configure the mocks with side-effects
        mock_conn.reset_mock()
        mock_conn.side_effect = self._side_effect_get_err_connection

        # run the test
        with testtools.ExpectedException(
                exception.VolumeBackendAPIException,
                'Bad or unexpected response from the storage volume '
                'backend API: Failed to execute CloudByte API'):
            self.driver._api_request_for_cloudbyte('listTsm', {})

        # Test - III

        # configure the mocks with side-effects
        mock_conn.reset_mock()
        mock_conn.side_effect = self._side_effect_get_err_connection2

        # run the test
        with testtools.ExpectedException(
                exception.VolumeBackendAPIException,
                'Error executing CloudByte API'):
            self.driver._api_request_for_cloudbyte('listTsm', {})

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_delete_volume(self, mock_api_req):

        # prepare the dependencies
        fake_volume_id = self._get_fake_volume_id()
        volume = {'id': fake_volume_id, 'provider_id': fake_volume_id}

        # Test-I

        mock_api_req.side_effect = self._side_effect_api_req

        # run the test
        self.driver.delete_volume(volume)

        # assert that 7 api calls were invoked
        self.assertEqual(7, mock_api_req.call_count)

        # Test-II

        # reset & re-configure mock
        volume['provider_id'] = None
        mock_api_req.reset_mock()
        mock_api_req.side_effect = self._side_effect_api_req

        # run the test
        self.driver.delete_volume(volume)

        # assert that no api calls were invoked
        self.assertEqual(0, mock_api_req.call_count)

        # Test-III

        # re-configure the dependencies
        volume['provider_id'] = fake_volume_id

        # reset & re-configure mock
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = (
            self._side_effect_api_req_to_delete_file_system)

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          volume)

        # assert that 6 api calls were invoked
        self.assertEqual(6, mock_api_req.call_count)

        # Test - IV

        # reset the mocks
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = (
            self._side_effect_api_req_to_query_asyncjob_response)

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          volume)

        # assert that 7 api calls were invoked
        self.assertEqual(7, mock_api_req.call_count)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_delete_snapshot(self, mock_api_req):

        snapshot = {
            'id': 'SomeID',
            'provider_id': 'devpool1/acc1openstacktsm/DS1@DS1Snap1',
            'display_name': 'DS1Snap1',
            'volume_id': 'SomeVol',
            'volume': {
                'display_name': 'DS1'
            }

        }

        # Test - I

        # now run the test
        self.driver.delete_snapshot(snapshot)

        # assert that 1 api call was invoked
        self.assertEqual(1, mock_api_req.call_count)

        # Test - II

        # reconfigure the dependencies
        snapshot['provider_id'] = None

        # reset & reconfigure the mock
        mock_api_req.reset_mock()
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        self.driver.delete_snapshot(snapshot)

        # assert that no api calls were invoked
        self.assertEqual(0, mock_api_req.call_count)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_create_snapshot(self, mock_api_req):

        # prepare the dependencies
        fake_volume_id = self._get_fake_volume_id()

        snapshot = {
            'id': 'c60890b1-f236-46f2-9e6d-51e6e592cee6',
            'display_name': 'DS1Snap1',
            'volume_id': 'SomeVol',
            'volume': {
                'display_name': 'DS1',
                'provider_id': fake_volume_id

            }
        }

        # Test - I

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        model_update = self.driver.create_snapshot(snapshot)

        # assert that 2 api calls were invoked
        self.assertEqual(2, mock_api_req.call_count)

        self.assertEqual('DS1@snap_c60890b1f23646f29e6d51e6e592cee6',
                         model_update['provider_id'])

        # Test - II

        # reconfigure the dependencies
        snapshot['volume']['provider_id'] = None

        # reset & reconfigure the mock
        mock_api_req.reset_mock()
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test & assert the exception
        with testtools.ExpectedException(
                exception.VolumeBackendAPIException,
                'Bad or unexpected response from the storage volume '
                'backend API: Failed to create snapshot'):
            self.driver.create_snapshot(snapshot)

        # assert that no api calls were invoked
        self.assertEqual(0, mock_api_req.call_count)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_create_volume(self, mock_api_req):

        # prepare the dependencies
        fake_volume_id = self._get_fake_volume_id()

        volume = {
            'id': fake_volume_id,
            'size': 22,
            'volume_type_id': None
        }

        # Test - I

        # enable CHAP
        self._side_effect_enable_chap()

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        provider_details = self.driver.create_volume(volume)

        # assert equality checks for certain configuration attributes
        self.assertEqual(
            'openstack', self.driver.configuration.cb_tsm_name)
        self.assertEqual(
            'CustomerA', self.driver.configuration.cb_account_name)
        self.assertEqual(
            'fakeauthgroup', self.driver.configuration.cb_auth_group)

        # assert the result
        self.assertEqual(
            'CHAP fakeauthgroupchapuser fakeauthgroupchapsecret',
            provider_details['provider_auth'])
        self.assertThat(
            provider_details['provider_location'],
            matchers.Contains('172.16.50.35:3260'))

        # assert the invoked api calls to CloudByte Storage
        self.assertEqual(11, mock_api_req.call_count)

        # Test - II

        # reset the mock
        mock_api_req.reset_mock()

        # disable CHAP
        self._side_effect_disable_chap()

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        provider_details = self.driver.create_volume(volume)

        # assert equality checks for certain configuration attributes
        self.assertEqual(
            'openstack', self.driver.configuration.cb_tsm_name)
        self.assertEqual(
            'CustomerA', self.driver.configuration.cb_account_name)

        # assert the result
        self.assertEqual(
            None,
            provider_details['provider_auth'])
        self.assertThat(
            provider_details['provider_location'],
            matchers.Contains('172.16.50.35:3260'))

        # assert the invoked api calls to CloudByte Storage
        self.assertEqual(9, mock_api_req.call_count)

        # Test - III

        # reconfigure the dependencies
        volume['id'] = 'NotExists'
        del volume['size']

        # reset & reconfigure the mock
        mock_api_req.reset_mock()
        mock_api_req.side_effect = self._side_effect_api_req

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

        # Test - IV

        # reconfigure the dependencies
        volume['id'] = 'abc'

        # reset the mocks
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = self._side_effect_api_req_to_create_vol

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

        # Test - V

        # reconfigure the dependencies
        # reset the mocks
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = self._side_effect_api_req_to_list_filesystem

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

        # Test - VI

        volume['id'] = fake_volume_id
        # reconfigure the dependencies
        # reset the mocks
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = (
            self._side_effect_api_req_to_list_vol_iscsi_service)

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

        # Test - VII

        # reconfigure the dependencies
        # reset the mocks
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = (
            self._side_effect_api_req_to_list_iscsi_initiator)

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

        # Test - VIII

        volume['id'] = fake_volume_id
        volume['size'] = 22

        # reconfigure the dependencies
        # reset the mocks
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = (
            self._none_response_to_list_tsm)

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

        # Test - IX

        volume['id'] = fake_volume_id
        volume['size'] = 22

        # reconfigure the dependencies
        # reset the mocks
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = (
            self._side_effect_api_req_to_create_vol)

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

        # Test - X

        # reset the mocks
        mock_api_req.reset_mock()

        # configure or re-configure the mocks
        mock_api_req.side_effect = (
            self._side_effect_api_req_to_query_asyncjob_response)

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       'create_volume_from_snapshot')
    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       'create_snapshot')
    def test_create_cloned_volume(self, mock_create_snapshot,
                                  mock_create_vol_from_snap, mock_api_req):

        # prepare the input test data
        fake_volume_id = self._get_fake_volume_id()

        src_volume = {'display_name': 'DS1Snap1'}

        cloned_volume = {
            'source_volid': fake_volume_id,
            'id': 'SomeNewID',
            'display_name': 'CloneOfDS1Snap1'
        }

        # Test - I

        # configure the mocks with respective sideeffects
        mock_api_req.side_effect = self._side_effect_api_req
        mock_create_vol_from_snap.side_effect = (
            self._side_effect_create_vol_from_snap)
        mock_create_snapshot.side_effect = (
            self._side_effect_create_snapshot)

        # now run the test
        self.driver.create_cloned_volume(cloned_volume, src_volume)

        # assert that n api calls were invoked
        self.assertEqual(0, mock_api_req.call_count)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_create_volume_from_snapshot(self, mock_api_req):

        # prepare the input test data
        fake_volume_id = self._get_fake_volume_id()

        snapshot = {
            'volume_id': fake_volume_id,
            'provider_id': 'devpool1/acc1openstacktsm/DS1@DS1Snap1',
            'id': 'SomeSnapID',
            'volume': {
                'provider_id': fake_volume_id
            }
        }

        cloned_volume = {
            'display_name': 'CloneOfDS1Snap1',
            'id': 'ClonedVolID'
        }

        # Test - I

        # enable CHAP
        self._side_effect_enable_chap()

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        provider_details = (
            self.driver.create_volume_from_snapshot(cloned_volume, snapshot))

        # assert the result
        self.assertEqual(
            'CHAP fakeauthgroupchapuser fakeauthgroupchapsecret',
            provider_details['provider_auth'])
        self.assertEqual(
            '20.10.22.56:3260 '
            'iqn.2014-06.acc1.openstacktsm:acc1DS1Snap1clone1 0',
            provider_details['provider_location'])

        # assert the invoked api calls to CloudByte Storage
        self.assertEqual(4, mock_api_req.call_count)

        # Test - II

        # reset the mocks
        mock_api_req.reset_mock()

        # disable CHAP
        self._side_effect_disable_chap()

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        provider_details = (
            self.driver.create_volume_from_snapshot(cloned_volume, snapshot))

        # assert the result
        self.assertEqual(
            None,
            provider_details['provider_auth'])
        self.assertEqual(
            '20.10.22.56:3260 '
            'iqn.2014-06.acc1.openstacktsm:acc1DS1Snap1clone1 0',
            provider_details['provider_location'])

        # assert n api calls were invoked
        self.assertEqual(1, mock_api_req.call_count)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_extend_volume(self, mock_api_req):

        # prepare the input test data
        fake_volume_id = self._get_fake_volume_id()

        volume = {
            'id': 'SomeID',
            'provider_id': fake_volume_id
        }

        new_size = '2'

        # Test - I

        # configure the mock with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        self.driver.extend_volume(volume, new_size)

        # assert n api calls were invoked
        self.assertEqual(1, mock_api_req.call_count)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_create_export(self, mock_api_req):

        # Test - I

        # enable CHAP
        self._side_effect_enable_chap()

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        model_update = self.driver.create_export({}, {}, {})

        # assert the result
        self.assertEqual('CHAP fakeauthgroupchapuser fakeauthgroupchapsecret',
                         model_update['provider_auth'])

        # Test - II

        # reset the mocks
        mock_api_req.reset_mock()

        # disable CHAP
        self._side_effect_disable_chap()

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        model_update = self.driver.create_export({}, {}, {})

        # assert the result
        self.assertEqual(None,
                         model_update['provider_auth'])

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_ensure_export(self, mock_api_req):

        # Test - I

        # enable CHAP
        self._side_effect_enable_chap()

        # configure the mock with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        model_update = self.driver.ensure_export({}, {})

        # assert the result to have a provider_auth attribute
        self.assertEqual('CHAP fakeauthgroupchapuser fakeauthgroupchapsecret',
                         model_update['provider_auth'])

        # Test - II

        # reset the mocks
        mock_api_req.reset_mock()

        # disable CHAP
        self._side_effect_disable_chap()

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req

        # now run the test
        model_update = self.driver.create_export({}, {}, {})

        # assert the result
        self.assertEqual(None,
                         model_update['provider_auth'])

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    def test_get_volume_stats(self, mock_api_req):

        # configure the mock with a side-effect
        mock_api_req.side_effect = self._side_effect_api_req

        # Test - I

        # run the test
        vol_stats = self.driver.get_volume_stats()

        # assert 0 api calls were invoked
        self.assertEqual(0, mock_api_req.call_count)

        # Test - II

        # run the test with refresh as True
        vol_stats = self.driver.get_volume_stats(refresh=True)

        # assert n api calls were invoked
        self.assertEqual(1, mock_api_req.call_count)

        # assert the result attributes with respective values
        self.assertEqual(1024.0, vol_stats['total_capacity_gb'])
        self.assertEqual(824.0, vol_stats['free_capacity_gb'])
        self.assertEqual(0, vol_stats['reserved_percentage'])
        self.assertEqual('CloudByte', vol_stats['vendor_name'])
        self.assertEqual('iSCSI', vol_stats['storage_protocol'])

        # Test - III

        # configure the mocks with side-effect
        mock_api_req.reset_mock()
        mock_api_req.side_effect = self._side_effect_api_req_to_list_tsm

        # run the test with refresh as True
        with testtools.ExpectedException(
                exception.VolumeBackendAPIException,
                "Bad or unexpected response from the storage volume "
                "backend API: No response was received from CloudByte "
                "storage list tsm API call."):
            self.driver.get_volume_stats(refresh=True)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    @mock.patch.object(volume_types,
                       'get_volume_type')
    @mock.patch.object(qos_specs,
                       'get_qos_specs')
    def test_retype(self, get_qos_spec, get_volume_type, mock_api_req):

        # prepare the input test data
        fake_new_type = {'id': 'fake-new-type-id'}
        fake_volume_id = self._get_fake_volume_id()

        volume = {
            'id': 'SomeID',
            'provider_id': fake_volume_id
        }

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req
        get_qos_spec.side_effect = self._fake_get_qos_spec
        get_volume_type.side_effect = self._fake_get_volume_type

        self.assertTrue(self.driver.retype(self.ctxt,
                                           volume,
                                           fake_new_type, None, None))

        # assert the invoked api calls
        self.assertEqual(3, mock_api_req.call_count)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    @mock.patch.object(volume_types,
                       'get_volume_type')
    @mock.patch.object(qos_specs,
                       'get_qos_specs')
    def test_retype_without_provider_id(self, get_qos_spec, get_volume_type,
                                        mock_api_req):

        # prepare the input test data
        fake_new_type = {'id': 'fake-new-type-id'}
        volume = {'id': 'SomeID'}

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req
        get_qos_spec.side_effect = self._fake_get_qos_spec
        get_volume_type.side_effect = self._fake_get_volume_type

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.retype,
                          self.ctxt, volume, fake_new_type, None, None)

    @mock.patch.object(cloudbyte.CloudByteISCSIDriver,
                       '_api_request_for_cloudbyte')
    @mock.patch.object(volume_types,
                       'get_volume_type')
    @mock.patch.object(qos_specs,
                       'get_qos_specs')
    def test_retype_without_filesystem(self, get_qos_spec, get_volume_type,
                                       mock_api_req):

        # prepare the input test data
        fake_new_type = {'id': 'fake-new-type-id'}
        fake_volume_id = self._get_fake_volume_id()

        volume = {
            'id': 'SomeID',
            'provider_id': fake_volume_id
        }

        # configure the mocks with respective side-effects
        mock_api_req.side_effect = self._side_effect_api_req
        get_qos_spec.side_effect = self._fake_get_qos_spec
        get_volume_type.side_effect = self._fake_get_volume_type
        mock_api_req.side_effect = self._fake_api_req_to_list_filesystem

        # Now run the test & assert the exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.retype,
                          self.ctxt, volume, fake_new_type, None, None)
