/* Copyright (c) 2016 Red Hat, Inc.
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
*/

/* Fix replication_status field in volumes table.

   There are some drivers that did not update the replication_status field on
   the volumes on creation and since the scheduler was not updating them on
   creation there is an inconsistency between the database and the storage
   device backend.

   Some of the drivers that have been detected to be missing this are:
       - kaminario
       - pure
       - solidfire

   This migration will fix this updating the volume_status field based on the
   volume type's replication status.
*/

UPDATE volumes
SET replication_status='enabled'
WHERE (not volumes.deleted or volumes.deleted IS NULL)
    AND volumes.replication_status='disabled'
    AND EXISTS(
        SELECT *
        FROM volume_type_extra_specs
        WHERE volumes.volume_type_id=volume_type_extra_specs.volume_type_id
        AND (volume_type_extra_specs.deleted IS NULL
             OR not volume_type_extra_specs.deleted)
        AND volume_type_extra_specs.key='replication_enabled'
        AND volume_type_extra_specs.value='<is> True'
    );
