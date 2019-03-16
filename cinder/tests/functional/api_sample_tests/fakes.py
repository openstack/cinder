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
        "host": "null",
        "cluster": "cluster@backend",
        "ref": {
            "source-name": "existingLV",
            "source-id": "1234"
        },
        "name": "New Volume",
        "availability_zone": "az2",
        "description": "Volume imported from existingLV",
        "volume_type": "null",
        "bootable": True,
        "metadata": {
            "key1": "value1",
            "key2": "value2"
        }
    }

    return volume
