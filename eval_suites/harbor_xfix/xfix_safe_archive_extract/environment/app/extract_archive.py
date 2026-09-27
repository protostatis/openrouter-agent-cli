import zipfile

from archive_policy import validate_members


def extract(archive_path, destination):
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        validate_members(infos)
        archive.extractall(destination)
        return sum(not info.is_dir() for info in infos)
