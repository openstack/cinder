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


def stub_copy_volume_to_image(self, context, volume, metadata, force):
    image_metadata = {
        "status": "uploading",
        "container_format": "bare",
        "image_name": "test",
        "visibility": "private",
        "updated_at": "2017-06-05T08:44:28.000000",
        "image_id": "de75b74e-7f0d-4b59-a263-bd87bfc313bd",
        "display_description": None,
        "id": "3a81fdac-e8ae-4e61-b6a2-2e14ff316f19",
        "size": 1,
        "disk_format": "raw",
        "volume_type": None,
        "protected": False
    }
    return image_metadata


def stub_manage_existing(self, req, body):
    volume = {
        "volume": {
            "status": "creating",
            "user_id": "eae1472b5fc5496998a3d06550929e7e",
            "attachments": [],
            "links": [
                {
                    "href":
                        "http://10.0.2.15:8776/v3/87c8522052ca4eed98bc672b4c1a"
                        "3ddb/volumes/23cf872b-c781-4cd4-847d-5f2ec8cbd91c",
                    "rel": "self"
                },
                {
                    "href": "http://10.0.2.15:8776/87c8522052ca4eed98bc672b4c1"
                            "a3ddb/volumes/23cf872b-c781-4cd4-847d-5f2ec8cbd91"
                            "c",
                    "rel": "bookmark"
                }
            ],
            "availability_zone": "az2",
            "bootable": "false",
            "encrypted": "false",
            "created_at": "2014-07-18T00:12:54.000000",
            "description": "Volume imported from existingLV",
            "os-vol-tenant-attr:tenant_id": "87c8522052ca4eed98bc672b4c1a3ddb",
            "volume_type": "null",
            "name": "New Volume",
            "source_volid": "null",
            "snapshot_id": "null",
            "metadata": {
                "key2": "value2",
                "key1": "value1"
            },
            "id": "23cf872b-c781-4cd4-847d-5f2ec8cbd91c",
            "size": 0
        }
    }

    return volume


def stub_manage_existing_snapshot(self, req, body):
    snapshot = {
        "snapshot": {
            "status": "creating",
            "size": 1,
            "metadata": {
                "manage-snap-meta1": "value1",
                "manage-snap-meta3": "value3",
                "manage-snap-meta2": "value2"
            },
            "name": "new_snapshot",
            "volume_id": "1df34919-aba7-4a1b-a614-3b409d71ac03",
            "created_at": "2018-09-26T03:45:03.893592",
            "description": "this is a new snapshot",
            "id": "b6314a71-9d3d-439a-861d-b790def0d693",
            "updated_at": "null"
        }
    }

    return snapshot
