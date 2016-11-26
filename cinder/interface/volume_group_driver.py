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
#

"""
Generic volume group volume driver interface.
"""

from cinder.interface import base


class VolumeGroupDriver(base.CinderInterface):
    """Interface for drivers that support groups."""

    def create_group(self, context, group):
        """Creates a group.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :returns: model_update

        model_update will be in this format: {'status': xxx, ......}.

        If the status in model_update is 'error', the manager will throw
        an exception and it will be caught in the try-except block in the
        manager. If the driver throws an exception, the manager will also
        catch it in the try-except block. The group status in the db will
        be changed to 'error'.

        For a successful operation, the driver can either build the
        model_update and return it or return None. The group status will
        be set to 'available'.
        """

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :param source_group: a Group object as source.
        :param source_vols: a list of Volume objects in the source_group.
        :returns: model_update, volumes_model_update

        The source can be group_snapshot or a source group.

        param volumes is a list of objects retrieved from the db. It cannot
        be assigned to volumes_model_update. volumes_model_update is a list
        of dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        To be consistent with other volume operations, the manager will
        assume the operation is successful if no exception is thrown by
        the driver. For a successful operation, the driver can either build
        the model_update and volumes_model_update and return them or
        return None, None.
        """

    def delete_group(self, context, group, volumes):
        """Deletes a group.

        :param context: the context of the caller.
        :param group: the Group object to be deleted.
        :param volumes: a list of Volume objects in the group.
        :returns: model_update, volumes_model_update

        param volumes is a list of objects retrieved from the db. It cannot
        be assigned to volumes_model_update. volumes_model_update is a list
        of dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate volumes_model_update and model_update
        and return them.

        The manager will check volumes_model_update and update db accordingly
        for each volume. If the driver successfully deleted some volumes
        but failed to delete others, it should set statuses of the volumes
        accordingly so that the manager can update db correctly.

        If the status in any entry of volumes_model_update is 'error_deleting'
        or 'error', the status in model_update will be set to the same if it
        is not already 'error_deleting' or 'error'.

        If the status in model_update is 'error_deleting' or 'error', the
        manager will raise an exception and the status of the group will be
        set to 'error' in the db. If volumes_model_update is not returned by
        the driver, the manager will set the status of every volume in the
        group to 'error' in the except block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager. The statuses of the
        group and all volumes in it will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and volumes_model_update and return them or
        return None, None. The statuses of the group and all volumes
        will be set to 'deleted' after the manager deletes them from db.
        """

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group.

        :param context: the context of the caller.
        :param group: the Group object to be updated.
        :param add_volumes: a list of Volume objects to be added.
        :param remove_volumes: a list of Volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update

        model_update is a dictionary that the driver wants the manager
        to update upon a successful return. If None is returned, the manager
        will set the status to 'available'.

        add_volumes_update and remove_volumes_update are lists of dictionaries
        that the driver wants the manager to update upon a successful return.
        Note that each entry requires a {'id': xxx} so that the correct
        volume entry can be updated. If None is returned, the volume will
        remain its original status. Also note that you cannot directly
        assign add_volumes to add_volumes_update as add_volumes is a list of
        volume objects and cannot be used for db update directly. Same with
        remove_volumes.

        If the driver throws an exception, the status of the group as well as
        those of the volumes to be added/removed will be set to 'error'.
        """

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update

        param snapshots is a list of Snapshot objects. It cannot be assigned
        to snapshots_model_update. snapshots_model_update is a list of
        dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate snapshots_model_update and model_update
        and return them.

        The manager will check snapshots_model_update and update db accordingly
        for each snapshot. If the driver successfully deleted some snapshots
        but failed to delete others, it should set statuses of the snapshots
        accordingly so that the manager can update db correctly.

        If the status in any entry of snapshots_model_update is 'error', the
        status in model_update will be set to the same if it is not already
        'error'.

        If the status in model_update is 'error', the manager will raise an
        exception and the status of group_snapshot will be set to 'error' in
        the db. If snapshots_model_update is not returned by the driver, the
        manager will set the status of every snapshot to 'error' in the except
        block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager and the statuses of
        group_snapshot and all snapshots will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and snapshots_model_update and return them or
        return None, None. The statuses of group_snapshot and all snapshots
        will be set to 'available' at the end of the manager function.
        """

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update

        param snapshots is a list of objects. It cannot be assigned to
        snapshots_model_update. snapshots_model_update is a list of of
        dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        The driver should populate snapshots_model_update and model_update
        and return them.

        The manager will check snapshots_model_update and update db accordingly
        for each snapshot. If the driver successfully deleted some snapshots
        but failed to delete others, it should set statuses of the snapshots
        accordingly so that the manager can update db correctly.

        If the status in any entry of snapshots_model_update is
        'error_deleting' or 'error', the status in model_update will be set to
        the same if it is not already 'error_deleting' or 'error'.

        If the status in model_update is 'error_deleting' or 'error', the
        manager will raise an exception and the status of group_snapshot will
        be set to 'error' in the db. If snapshots_model_update is not returned
        by the driver, the manager will set the status of every snapshot to
        'error' in the except block.

        If the driver raises an exception during the operation, it will be
        caught by the try-except block in the manager and the statuses of
        group_snapshot and all snapshots will be set to 'error'.

        For a successful operation, the driver can either build the
        model_update and snapshots_model_update and return them or
        return None, None. The statuses of group_snapshot and all snapshots
        will be set to 'deleted' after the manager deletes them from db.
        """
