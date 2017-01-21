..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

=============================
Volume Attach/Detach workflow
=============================

Previously there were six API calls associated with attach/detach of volumes in
Cinder (3 calls for each operation).  As the projects grew and the
functionality of *simple* things like attach/detach evolved things have become
a bit vague and we have a number of race issues during the calls that
continually cause us some problems.

Additionally, the existing code path makes things like multi-attach extremely
difficult to implement due to no real good tracking mechansim of attachment
info.

To try and improve this we've proposed a new Attachments Object and API.  Now
we keep an Attachment record for each attachment that we want to perform as
opposed to trying to infer the information from the Volume Object.

Attachment Object
=================

We actually already had a VolumeAttachment Table in the db, however we
weren't really using it, or at least using it efficiently. For V2 of attach
implementation (V3 API) flow we'll use the Attachment Table (object) as
the primary handle for managing attachment(s) for a volume.

In addition, we also introduce the AttachmentSpecs Table which will store the
connector information for an Attachment so we no longer have the problem of
lost connector info, or trying to reassemble it.

New API and Flow
=================

```
attachment_create <instance_uuid> <volume_id>
```

The attachment_create call simply creates an empty Attachment record for the
specified Volume with an optional Instance UUID field set.  This is
particularly useful for cases like Nova Boot from Volume where Nova hasn't sent
the job to the actual Compute host yet, but needs to make initial preparations
to reserve the volume for use, so here we can reserve the volume and indicate
that we will be attaching it to <Instance-UUID> in the future.

Alternatively, the caller may provide a connector in which case the Cinder API
will create the attachment and perform the update on the attachment to set the
connector info and return the connection data needed to make a connection.

The attachment_create call can be used in one of two ways:
1. Create an empty Attachment object (reserve)
   attachment_create call.  In this case the attachment_create call requires
   an instance_uuid and a volume_uuid, and just creates an empty attachment
   object and returns the UUID of said attachment to the caller.

2. Create and Complete the Attachment process in one call.  The Reserve process
   is only needed in certain cases, in many cases Nova actually has enough
   information to do everything in a single call.  Also, non-nova consumers
   typically don't require the granularity of a separate reserve at all.

   To perform the complete operation, include the connector data in the
   attachment_create call and the Cinder API will perform the reserve and
   initialize the connection in the single request.



param instance-uuid: The ID of the Instance we'll be attaching to
param volume-id: The ID of the volume to reserve an Attachment record for
rtyp: string:`VolumeAttachmentID`

```
cinder --os-volume-api-version 3.27 attachment-create --instance <instance-uuid>  <volume-id>
```

param volume_id: The ID of the volume to create attachment for.
parm attachment_id: The ID of a previously reserved attachment.

param connector: Dictionary of connection info
param mode: `rw` or `ro` (defaults to `rw` if omitted).
param mountpoint: Mountpoint of remote attachment.
rtype: :class:`VolumeAttachment`

Example connector:
    {'initiator': 'iqn.1993-08.org.debian:01:cad181614cec',
     'ip':'192.168.1.20',
     'platform': 'x86_64',
     'host': 'tempest-1',
     'os_type': 'linux2',
     'multipath': False}

```
cinder --os-volume-api-version 3.27 attachment-create --initiator iqn.1993-08.org.debian:01:29353d53fa41 --ip 1.1.1.1 --host blah --instance <instance-id> <volume-id>
```

Returns a dictionary including the connector and attachment_id:

```
+-------------------+-----------------------------------------------------------------------+
| Property          | Value                                                                 |
+-------------------+-----------------------------------------------------------------------+
| access_mode       | rw                                                                    |
| attachment_id     | 6ab061ad-5c45-48f3-ad9c-bbd3b6275bf2                                  |
| auth_method       | CHAP                                                                  |
| auth_password     | kystSioDKHSV2j9y                                                      |
| auth_username     | hxGUgiWvsS4GqAQcfA78                                                  |
| encrypted         | False                                                                 |
| qos_specs         | None                                                                  |
| target_discovered | False                                                                 |
| target_iqn        | iqn.2010-10.org.openstack:volume-23212c97-5ed7-42d7-b433-dbf8fc38ec35 |
| target_lun        | 0                                                                     |
| target_portal     | 192.168.0.9:3260                                                      |
| volume_id         | 23212c97-5ed7-42d7-b433-dbf8fc38ec35                                  |
+-------------------+-----------------------------------------------------------------------+
```


attachment-delete
=================

```
cinder --os-volume-api-version 3.27 attachment-delete 6ab061ad-5c45-48f3-ad9c-bbd3b6275bf2
```

