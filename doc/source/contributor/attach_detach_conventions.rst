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

There are six API calls associated with attach/detach of volumes in Cinder
(3 calls for each operation).  This can lead to some confusion for developers
trying to work on Cinder.  The convention is actually quite simple, although
it may be difficult to decipher from the code.


Attach/Detach Operations are multi-part commands
================================================

There are three things that happen in the workflow for an attach or detach call.

1. Update the status of the volume in the DB (ie attaching/detaching)

- For Attach, this is the cinder.volume.api.reserve method
- For Detach, the analogous call is cinder.volume.api.begin_detaching

2. Handle the connection operations that need to be done on the Volume

- For Attach, this is the cinder.volume.api.initialize_connection method
- For Detach, the analogous calls is cinder.volume.api.terminate_connection

3. Finalize the status of the volume and release the resource

- For attach, this is the cinder.volume.api.attach method
- For detach, the analogous call is cinder.volume.api.detach

Attach workflow
===============

reserve_volume(self, context, volume)
-------------------------------------

Probably the most simple call in to Cinder.  This method simply checks that
the specified volume is in an “available” state and can be attached.
Any other state results in an Error response notifying Nova that the volume
is NOT available.  The only valid state for this call to succeed is “available”.

NOTE: multi-attach will add "in-use" to the above acceptable states.

If the volume is in fact available, we immediately issue an update to the Cinder
database and mark the status of the volume to “attaching” thereby reserving the
volume so that it won’t be used by another API call anywhere else.

initialize_connection(self, context, volume, connector)
-------------------------------------------------------

This is the only attach related API call that should be doing any significant
work.  This method is responsible for building and returning all of the info
needed by the caller (Nova) to actually attach the specified volume to the
remote node.  This method returns vital information to the caller that includes
things like CHAP credential, iqn and lun information.  An example response is
shown here:

::

    {
        'driver_volume_type': 'iscsi',
        'data': {
            'auth_password': 'YZ2Hceyh7VySh5HY',
            'target_discovered': False,
            'encrypted': False,
            'qos_specs': None,
            'target_iqn': 'iqn.2010-10.org.openstack:volume-8b1ec3fe-8c57-45ca-a1cf-a481bfc8fce2',
            'target_portal': '11.0.0.8:3260',
            'volume_id': '8b1ec3fe-8c57-45ca-a1cf-a481bfc8fce2',
            'target_lun': 1,
            'access_mode': 'rw',
            'auth_username': 'nE9PY8juynmmZ95F7Xb7',
            'auth_method': 'CHAP'
        }
    }

In the process of building this data structure, the Cinder Volume Manager makes a number of
calls to the backend driver, and builds a volume_attachment entry in the database to store
the connection information passed in via the connector object.

driver.validate_connector
*************************

Simply verifies that the initiator data is included in the passed in
connector (there are some drivers that utilize pieces of this connector
data, but in the case of the reference, it just verifies it's there).

driver.create_export
********************

This is the target specific, persistent data associated with a volume.
This method is responsible for building an actual iSCSI target, and
providing the "location" and "auth" information which will be used to
form the response data in the parent request.
We call this infor the model_update and it's used to update vital target
information associated with the volume in the Cinder database.

driver.initialize_connection
****************************

Now that we've actually built a target and persisted the important
bits of information associated with it, we're ready to actually assign
the target to a volume and form the needed info to pass back out
to our caller.  This is where we finally put everything together and
form the example data structure response shown earlier.

This method is sort of deceptive, it does a whole lot of formatting
of the data we've put together in the create_export call, but it doesn't
really offer any new info.  It's completely dependent on the information
that was gathered in the create_export call and put into the database.  At
this point, all we're doing is taking all the various entries from the database
and putting it together into the desired format/structure.

The key method call for updating and obtaining all of this info was
done by the create_export call.  This formatted data is then passed
back up to the API and returned as the response back out to Nova.

At this point, we return attach info to the caller that provides everything
needed to make the remote iSCSI connection.

attach(self, context, volume, instance_uuid, host_name, mount_point, mode)
--------------------------------------------------------------------------

This is the last call that *should* be pretty simple.  The intent is that this
is simply used to finalize the attach process.  In other words, we simply
update the status on the Volume in the database, and provide a mechanism to
notify the driver that the attachment has completed successfully.

There's some additional information that has been added to this finalize call
over time like instance_uuid, host_name etc.  Some of these are only provided
during the actual attach call and may be desired for some drivers for one
reason or another.


Detach workflow
===============

begin_detaching(self, context, volume)
--------------------------------------

Analogous to the Attach workflows ``reserve_volume`` method.
Performs a simple conditional update of Volume status to ``detaching``.


terminate_connection(self, context, volume, connector, force=False)
-------------------------------------------------------------------
Analogous to the Attach workflows ``initialize_connection`` method.

Used to send calls down to drivers/target-drivers to do any sort of cleanup
they might require.

For most this is a noop, as connections and **iscsi session management is the
responsibility of the initiator**.  HOWEVER, there are a number of special
cases here, particularly for target-drivers like LIO that use
access-groups, in those cases they remove the initiator from the access
list during this call which effectively closes sessions from the target
side.


detach(self, context, volume, attachment_id)
-------------------------------------------------------------------
The final update to the DB and yet another opportunity to pass something
down to the volume-driver.  Initially a simple call-back that now has quite
a bit of cruft built up in the volume-manager.

For drivers like LVM this again is a noop and just updates the db entry to
mark things as complete and set the volume to available again.

