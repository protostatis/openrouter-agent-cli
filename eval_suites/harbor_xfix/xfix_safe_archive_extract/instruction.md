Fix the ZIP extractor run with
`python3 run_extract.py archive.zip destination`.

The archive contains POSIX-style member names. Before writing anything, check
the complete archive and reject it if any member is not a regular file or
directory, has an absolute name, contains a `..` path component, duplicates
another normalized path, or conflicts with another member as both a file and a
directory. Normalize repeated separators and `.` components when checking for
duplicates and conflicts. A symbolic link is not a regular file and must be
rejected. A file may have implicit parent directories, but a member cannot be
placed below a member that is a file.

Invalid archives must be rejected as a whole: no destination directory or
extracted file may be created. Print exactly `error:<reason>` and exit with
status 2, where the reason is `absolute_path`, `path_traversal`, `symlink`,
`duplicate_path`, `path_conflict`, or `unsupported_type`. For a valid archive,
create the destination, extract its regular files and directories, print
`extracted N files`, and exit with status 0. The destination used by this task
does not exist before the command starts. Do not modify the archive or
`run_extract.py`.
