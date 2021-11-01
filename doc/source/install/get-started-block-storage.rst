=====================================
Cinder Block Storage service overview
=====================================

The OpenStack Block Storage service (Cinder) adds persistent storage
to a virtual machine. Block Storage provides an infrastructure for managing
volumes, and interacts with OpenStack Compute to provide volumes for
instances. The service also enables management of volume snapshots, and
volume types.

The Block Storage service consists of the following components:

cinder-api
  Accepts API requests, and routes them to the ``cinder-volume`` for
  action.

cinder-volume
  Interacts directly with the Block Storage service, and processes
  such as the ``cinder-scheduler``. It also interacts with these processes
  through a message queue. The ``cinder-volume`` service responds to read
  and write requests sent to the Block Storage service to maintain
  state. It can interact with a variety of storage providers through a
  driver architecture.

cinder-scheduler daemon
  Selects the optimal storage provider node on which to create the
  volume. A similar component to the ``nova-scheduler``.

cinder-backup daemon
  The ``cinder-backup`` service provides backing up volumes of any type to
  a backup storage provider. Like the ``cinder-volume`` service, it can
  interact with a variety of storage providers through a driver
  architecture.

Messaging queue
  Routes information between the Block Storage processes.

The default volume type
-----------------------

Since the Train release, it is required that each volume must have a
*volume type*, and thus the required configuration option
``default_volume_type`` must have a value.  A system-defined volume type
named ``__DEFAULT__`` is created in the database during installation and
is the default value of the ``default_volume_type`` configuration option.

You (or your deployment tool) may wish to have a different volume type that
is more suitable for your particular installation as the default type.
This can be accomplished by creating the volume type you want using the
Block Storage API, and then setting that volume type as the value for
the configuration option.  (The latter operation, of course, cannot be
done via the Block Storage API.)

The system defined ``__DEFAULT__`` volume type is a regular volume type
that may be updated or deleted.  There is nothing special about it.  It only
exists because there must always be at least one volume type in a cinder
deployment, and before the Block Storage API comes up, there is no way for
there to be a volume type unless the system creates it.

Given that since the Victoria release it is possible to set a default
volume type for any project, having a volume type named ``__DEFAULT__``
in your deployment may be confusing to your users, leading them to think this
is the type that will be assigned while creating volumes (if the user doesn't
specify one) or them specifically requesting ``__DEFAULT__`` when creating a
volume instead of the actual configured default type for the system or their
project.

If you don't wish to use the ``__DEFAULT__`` type, you may delete it.  The
Block Storage API will prevent deletion under these circumstances:

* If ``__DEFAULT__`` is the value of the ``default_volume_type`` configuration
  option then it cannot be deleted.  The solution is to make a different
  volume type the value of that configuration option.
* If there are volumes in the deployment of the ``__DEFAULT__`` type, then
  it cannot be deleted.  The solution is to retype those volumes to some
  other appropriate volume type.
