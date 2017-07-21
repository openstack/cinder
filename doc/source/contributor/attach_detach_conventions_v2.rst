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

==================================
Volume Attach/Detach workflow - V2
==================================

Previously there were six API calls associated with attach/detach of volumes in
Cinder (3 calls for each operation).  As the projects grew and the
functionality of *simple* things like attach/detach evolved things have become
a bit vague and we have a number of race issues during the calls that
continually cause us some problems.

Additionally, the existing code path makes things like multi-attach extremely
difficult to implement due to no real good tracking mechanism of attachment
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
================

attachment-create
-----------------

```
cinder --os-volume-api-version 3.27 attachment-create <volume-id> <instance-uuid>
```

The attachment_create call simply creates an empty Attachment record for the
specified Volume with an Instance UUID field set.  This is particularly
useful for cases like Nova Boot from Volume where Nova hasn't sent
the job to the actual Compute host yet, but needs to make initial preparations
to reserve the volume for use, so here we can reserve the volume and indicate
that we will be attaching it to <Instance-UUID> in the future.

Alternatively, the caller may provide a connector in which case the Cinder API
will create the attachment and perform the update on the attachment to set the
connector info and return the connection data needed to make a connection.

The attachment_create call can be used in one of two ways:

1. Create an empty Attachment object (reserve). In this case the
   attachment_create call requires an instance_uuid and a volume_uuid,
   and just creates an empty Attachment object and returns the UUID of
   Attachment to the caller.

2. Create and complete the Attachment process in one call.  The reserve process
   is only needed in certain cases, in many cases Nova actually has enough
   information to do everything in a single call.  Also, non-nova consumers
   typically don't require the granularity of a separate reserve at all.

   To perform the complete operation, include the connector data in the
   attachment_create call and the Cinder API will perform the reserve and
   initialize the connection in the single request.

This full usage of attachment-create would be::

  usage: cinder --os-volume-api-version 3.27 attachment-create
         <volume>  <instance_uuid> ...

  Positional arguments:
  <volume>                  Name or ID of volume or volumes to attach.
  <instance_uuid>           ID of instance attaching to.

  Optional arguments:
  --connect <connect>       Make an active connection using provided connector info (True or False).
  --initiator <initiator>   iqn of the initiator attaching to. Default=None.
  --ip <ip>                 ip of the system attaching to. Default=None.
  --host <host>             Name of the host attaching to. Default=None.
  --platform <platform>     Platform type. Default=x86_64.
  --ostype <ostype>         OS type. Default=linux2.
  --multipath <multipath>   Use multipath. Default=False.
  --mountpoint <mountpoint> Mountpoint volume will be attached at. Default=None.

Returns the connection information for the attachment::

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

attachment-update
-----------------

```
cinder --os-volume-api-version 3.27 attachment-update <attachment-id>
```

Once we have a reserved volume, this CLI can be used to update an attachment for a cinder volume.
This call is designed to be more of an attachment completion than anything else.
It expects the value of a connector object to notify the driver that the volume is going to be
connected and where it's being connected to. The usage is the following::

  usage: cinder --os-volume-api-version 3.27 attachment-update
         <attachment-id> ...

  Positional arguments:
    <attachment-id>           ID of attachment.

  Optional arguments:
    --initiator <initiator>   iqn of the initiator attaching to. Default=None.
    --ip <ip>                 ip of the system attaching to. Default=None.
    --host <host>             Name of the host attaching to. Default=None.
    --platform <platform>     Platform type. Default=x86_64.
    --ostype <ostype>         OS type. Default=linux2.
    --multipath <multipath>   Use multipath. Default=False.
    --mountpoint <mountpoint> Mountpoint volume will be attached at. Default=None.

attachment-delete
-----------------

```
cinder --os-volume-api-version 3.27 attachment-delete <attachment-id>
```

