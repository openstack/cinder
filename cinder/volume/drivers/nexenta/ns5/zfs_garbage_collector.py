from oslo_log import log as logging
from cinder import exception

LOG = logging.getLogger(__name__)


class ZFSGarbageCollectorMixIn(object):
    def __init__(self):
        self.__needless_objects = set()

    def mark_as_garbage(self, zfs_object):
        """Put ZFS object into list for further removal

        :param zfs_object: full path to a volume or a snapshot
        """
        self.__needless_objects.add(zfs_object)

    def should_destroy_later(self, e):
        return 'Failed to destroy snapshot' in e.args[0] or (
            'must be destroyed first' in e.args[0])

    def destroy_later_or_raise(self, e, zfs_object):
        do = self.should_destroy_later(e)
        if do:
            LOG.debug('Failed to destroy ZFS object. Will do it later.')
            self.mark_as_garbage(zfs_object)
        else:
            raise e

    def collect_zfs_garbage(self, zfs_object):
        """Recursively destroy ZFS parent volumes and snapshots if they are
        marked as garbage

        :param zfs_object: full path to a volume or a snapshot
        """
        self.__collect_garbage(zfs_object)

    def __collect_garbage(self, zfs_object):
        if zfs_object and zfs_object in self.__needless_objects:
            sp = zfs_object.split('/')
            path = '/'.join(sp[:-1])
            name = sp[-1]
            if '@' in name:  # it's a snapshot:
                volume, snap = name.split('@')
                parent = '/'.join((path, volume))
                url = self.get_delete_snapshot_url(zfs_object)
                try:
                    self.nef.delete(url)
                except exception.NexentaException as exc:
                    LOG.debug('Error occurred while trying to delete '
                              'snapshot: {}'.format(exc))
                    return
            else:
                url = self.get_original_snapshot_url(zfs_object)
                # Check if there is parent snapshot
                field = 'originalSnapshot'
                parent = self.nef.get('{}?fields={}'.format(
                    url, field)).get(field)

                url = self.get_delete_volume_url(zfs_object)
                try:
                    self.nef.delete(url)
                except exception.NexentaException as exc:
                    LOG.debug('Error occurred while trying to delete '
                              'volume: {}'.format(exc))
                    return
            self.__needless_objects.remove(zfs_object)
            self.__collect_garbage(parent)

    def get_delete_snapshot_url(self, zfs_object):
        raise NotImplementedError()

    def get_original_snapshot_url(self, zfs_object):
        raise NotImplementedError()

    def get_delete_volume_url(self, zfs_object):
        raise NotImplementedError()
