..
      Copyright (c) 2015 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Migration
=========

Introduction to volume migration
--------------------------------
Cinder provides the volume migration support within the same deployment,
which means the node of cinder volume service, c-vol node where the
source volume is located, is able to access the c-vol node where
the destination volume is located, and both of them share the same
Cinder API service, scheduler service, message queue service, etc.

As a general rule migration is possible for volumes in 'available' or
‘in-use’ status, for the driver which has implemented volume migration.
So far, we are confident that migration will succeed for 'available'
volumes, whose drivers implement the migration routines. However,
the migration of 'in-use' volumes is driver dependent. It depends on
different drivers involved in the operation. It may fail depending on
the source or destination driver of the volume.

For example, from RBD to LVM, the migration of 'in-use' volume will
succeed, but from LVM to RBD, it will fail.

There are two major scenarios, which volume migration supports
in Cinder:

Scenario 1: Migration between two back-ends with the same volume type,
regardless if they are located on the same c-vol node or not.

Scenario 2: Migration between two back-ends with different volume types,
regardless if the back-ends are located on the same c-vol node or not.


How to do volume migration via CLI
----------------------------------
Scenario 1 of volume migration is done via the following command from
the CLI::

 cinder migrate [--force-host-copy [<True|False>]]
                [--lock-volume [<True|False>]]
                <volume> <host>

 Mandatory arguments:
   <volume>              ID of volume to migrate.
   <host>                Destination host. The format of host is
                         host@backend#POOL, while 'host' is the host
                         name of the volume node, 'backend' is the back-end
                         name and 'POOL' is a logical concept to describe
                         a set of storage resource, residing in the
                         back-end. If the back-end does not have specified
                         pools, 'POOL' needs to be set with the same name
                         as 'backend'.

 Optional arguments:
   --force-host-copy [<True|False>]
                         Enables or disables generic host-based force-
                         migration, which bypasses the driver optimization.
                         Default=False.
   --lock-volume [<True|False>]
                         Enables or disables the termination of volume
                         migration caused by other commands. This option
                         applies to the available volume. True means it locks
                         the volume state and does not allow the migration to
                         be aborted. The volume status will be in maintenance
                         during the migration. False means it allows the volume
                         migration to be aborted. The volume status is still in
                         the original status. Default=False.

Important note: Currently, error handling for failed migration operations is
under development in Cinder. If we would like the volume migration to finish
without any interruption, please set --lock-volume to True. If it is set
to False, we cannot predict what will happen, if other actions like attach,
detach, extend, etc, are issued on the volume during the migration.
It all depends on which stage the volume migration has reached and when the
request of another action comes.


Scenario 2 of volume migration can be done via the following command
from the CLI::

 cinder retype --migration-policy on-demand
               <volume> <volume-type>
 Mandatory arguments:
   <volume>              Name or ID of volume for which to modify type.
   <volume-type>         New volume type.

Source volume type and destination volume type must be different and
they must refer to different back-ends.


Configurations
--------------
To set up an environment to try the volume migration, we need to
configure at least two different back-ends on the same node of cinder
volume service, c-vol node or two back-ends on two different volume
nodes of cinder volume service, c-vol nodes. Which command to use,
‘cinder migrate’ or ‘cinder retype’, depends on which type of volume
we would like to test.

**Scenario 1 for migration**

To configure the environment for Scenario 1 migration, e.g. a
volume is migrated from back-end <driver-backend> on Node 1 to back-end
<driver-backend> on Node 2, cinder.conf needs to contains the following
entries for the same back-end on both of source and the destination
nodes:

For Node 1:
    ...
    [<driver-backend>]
    volume_driver=xxxx
    volume_backend_name=<driver-backend>
    ...

For Node 2:
    ...
    [<driver-backend>]
    volume_driver=xxxx
    volume_backend_name=<driver-backend>
    ...

If a volume with a predefined volume type is going to migrate,
the back-end drivers from Node 1 and Node 2 should have the same
value for volume_backend_name, which means <driver-backend> should be
the same for Node 1 and Node 2. The volume type can be created
with the extra specs {volume_backend_name: driver-biz}.

If we are going to migrate a volume with a volume type of none, it
is not necessary to set the same value to volume_backend_name for
both Node 1 and Node 2.

**Scenario 2 for migration**

To configure the environment for Scenario 2 migration:
For example, a volume is migrated from driver-biz back-end on Node 1
to driver-net back-end on Node 2, cinder.conf needs to contains
the following entries:

For Node 1:
    ...
    [driver-biz]
    volume_driver=xxxx
    volume_backend_name=driver-biz
    ...

For Node 2:
    ...
    [driver-net]
    volume_driver=xxxx
    volume_backend_name=driver-net
    ...

For example, a volume is migrated from driver-biz back-end on Node 1
to driver-biz back-net on the same node, cinder.conf needs to
contains the following entries:

    ...
    [driver-biz]
    volume_driver=xxxx
    volume_backend_name=driver-biz
    ...

    ...
    [driver-net]
    volume_driver=xxxx
    volume_backend_name=driver-net
    ...

Two volume types need to be created. One is with the extra specs:
{volume_backend_name: driver-biz}. The other is with the extra specs:
{volume_backend_name: driver-net}.


What can be tracked during volume migration
-------------------------------------------
The volume migration is an administrator only action and it may take
a relatively long time to finish. The property ‘migration status’ will
indicate the stage of the migration process for the volume. The
administrator can check the ‘migration status’ via the ‘cinder list’
or ‘cinder show <volume-id>’ command. The ‘cinder list’ command presents
a list of all the volumes with some properties displayed, including the
migration status, only to the administrator. However, the migration status
is not included if ‘cinder list’ is issued by an ordinary user. The
‘cinder show <volume-id>’ will present all the detailed information of a
specific volume, including the migration status, only to the administrator.

If the migration status of a volume shows ‘starting’, ‘migrating’ or
‘completing’, it means the volume is in the process of a migration.
If the migration status is ‘success’, it means the migration has finished
and the previous migration of this volume succeeded. If the
migration status is ‘error’, it means the migration has finished and
the previous migration of this volume failed.


How to implement volume migration for a back-end driver
-------------------------------------------------------
There are two kinds of implementations for the volume migration currently
in Cinder.

The first is the generic host-assisted migration, which consists of two
different transfer modes, block-based and file-based. This implementation
is based on the volume attachment to the node of cinder volume service,
c-vol node. Any back-end driver supporting iSCSI will be able to support
the generic host-assisted migration for sure. The back-end driver without
iSCSI supported needs to be tested to decide if it supports this kind of
migration. The block-based transfer mode is done by ‘dd’ command,
applying to drivers like LVM, Storwize, etc, and the file-based transfer
mode is done by file copy, typically applying to the RBD driver.

The second is the driver specific migration.
Since some storage back-ends have their special commands to copy the volume,
Cinder also provides a way for them to implement in terms of their own
internal commands to migrate.

If the volume is migrated between two nodes configured with the same
storage back-end, the migration will be optimized by calling the method
migrate_volume in the driver, if the driver provides an implementation for
it to migrate the volume within the same back-end, and will fallback to
the generic host-assisted migration provided in the manager, if no such
implementation is found or this implementation is not applicable for
this migration.

If your storage driver in Cinder provides iSCSI support, it should
naturally work under the generic host-assisted migration, when
--force-host-copy is set to True from the API request. Normally you
do not need to change any code, unless you need to transfer the volume
from your driver via a different way from the block-based transfer
or the file-based transfer.

If your driver uses a network connection to communicate the block data
itself, you can use file I/O to participate in migration. Please take
the RBD driver as a reference for this implementation.

If you would like to implement a driver specific volume migration for
your driver, the API method associated with the driver specific migration
is the following admin only method:

    migrate_volume(self, ctxt, volume, host)

If your driver is taken as the destination back-end for a generic host-assisted
migration and your driver needs to update the volume model after a successful
migration, you need to implement the following method for your driver:

    update_migrated_volume(self, ctxt, volume, new_volume, original_volume_status):


Required methods
----------------
There is one mandatory method that needs to be implemented for
the driver to implement the driver specific volume migration.

**migrate_volume**

Used to migrate the volume directly if source and destination are
managed by same storage.

There is one optional method that could be implemented for
the driver to implement the generic host-assisted migration.

**update_migrated_volume**

Used to return the key-value pairs to update the volume model after
a successful migration. The key-value pairs returned are supposed to
be the final values your driver would like to be in the volume model,
if a migration is completed.

This method can be used in a generally wide range, but the most common
use case covered in this method is to rename the back-end name to the
original volume id in your driver to make sure that the back-end still
keeps the same id or name as it is before the volume migration. For
this use case, there are two important fields: _name_id and
provider_location.

The field _name_id is used to map the cinder volume id and the back-end
id or name. The default value is None, which means the cinder
volume id is the same to the back-end id or name. If they are different,
_name_id is used to saved the back-end id or name.

The field provider_location is used to save the export information,
created by the volume attach. This field is optional, since some drivers
support the export creation and some do not. It is the driver
maintainer's responsibility to decide what this field needs to be.

If the back-end id or name is renamed successfully, this method can
return {'_name_id': None, 'provider_location': None}. It is the choice
for your driver to implement this method and decide what use cases should
be covered.

