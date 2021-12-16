import subprocess
import sys
import os
import argparse
import re
import itertools
from pathlib import Path

def git_log_follow_all(git_options, pathspecs):
    all_commits, all_past_pathspecs = map(flatten, zip(
        *(git_pathspec_history(pathspec)
          for pathspec in git_pathspecs_trees(pathspecs))))

    return git_selective_log(git_options, all_commits, all_past_pathspecs)

def git_pathspecs_trees(pathspecs):
    return flatten(git_ls_files(pathspec) for pathspec in pathspecs)

def git_ls_files(pathspec):
    output = run_get_stdout(['git', 'ls-files',
                             '-z',
                             '--', pathspec])
    paths = list(filter(len, output.split(b'\0')))
    return paths or [pathspec]

def git_pathspec_history(pathspec):
    commits = []
    pathspec_past_paths = [pathspec]

    output = run_get_stdout(['git', 'log',
                             '--follow', '--name-status',
                             '--pretty=format:%x00%x00%H', '-z',
                             '--', pathspec])
    rename_status_re = re.compile(br'^R\d+$')
    records = filter(len, output.split(b'\0\0'))
    for record in records:
        commit, statusblob = record.split(b'\n', 1)
        commits.append(commit)

        for status_line in parse_statusblob(statusblob):
            try:
                status, from_, to = status_line
            except ValueError:
                pass
            else:
                if (status_is_name_change(status)
                    and to == pathspec_past_paths[-1]):
                    pathspec_past_paths.append(from_)
    return commits, pathspec_past_paths

def parse_statusblob(statusblob):
    # Parses lines generated by this code from git diff.c:
    # if (p->status == DIFF_STATUS_COPIED ||
    #     p->status == DIFF_STATUS_RENAMED) {
    #         /* ... */
    #         write_name_quoted(name_a, opt->file, inter_name_termination);
    #         write_name_quoted(name_b, opt->file, line_termination);
    # } else {
    #         /* ... */
    #         write_name_quoted(name_a, opt->file, line_termination);
    # }

    fields = list(filter(len, statusblob.split(b'\0')))
    i = 0
    while i < len(fields):
        if status_is_name_change(fields[i]):
            chunk = 3
        else:
            chunk = 2
        yield fields[i:i+chunk]
        i += chunk

def status_is_name_change(status):
    return status.startswith(b'R') or status.startswith(b'C')

def git_selective_log(git_options, commits, pathspecs):
    """Show git log for all commits, but only for pathspecs"""
    if not commits and sys.stderr.isatty():
        print('nothing to do.', file=sys.stderr)
        return 0

    result = subprocess.run(['git', 'log',
                             '--stdin', '--ignore-missing']
                            + git_options
                            + ['--'] + list(pathspecs),
                            input=b'\n'.join(commits))
    return result.returncode

def run_get_stdout(*args, **kwargs):
    result = subprocess.run(*args, check=True, capture_output=True, **kwargs)
    return result.stdout

def flatten(iter):
    return itertools.chain(*iter)

def main():
    git_options, pathspecs = parse_cmdline(sys.argv[1:])
    try:
        result = git_log_follow_all(git_options, pathspecs)
        exit(result)
    except subprocess.CalledProcessError as ex:
        # A git plumbing call failed
        program = Path(sys.argv[0]).name
        cmd = ' '.join(map(os.fsdecode, ex.cmd))
        print(f'{program}: {cmd}', file=sys.stderr)
        if ex.stderr:
            print(os.fsdecode(ex.stderr), file=sys.stderr)
        exit(ex.returncode)

def parse_cmdline(argv):
    # On the use of os.fsencode: It's important that the file names be
    # byte strings, since they will be compared against byte strings
    # retrieved from git's stdout
    try:
        double_dash = argv.index('--')
    except ValueError:
        # Try our best to separate pathspecs from other arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('pathspec', nargs='*', type=os.fsencode)
        args, git_options = parser.parse_known_args(argv)
        pathspecs = args.pathspec
    else:
        # pathspecs are separated from other arguments by --
        git_options = argv[:double_dash]
        pathspecs = list(map(os.fsencode, argv[double_dash + 1:]))
    return git_options, pathspecs

if __name__ == '__main__':
    main()
