#!/usr/bin/python3

import sys
from mash.app import MprovShell

# SIGINT and SIGTERM keep Python's default handling, so a hung request
# can always be interrupted (#30).  The interactive shell turns Ctrl-C
# into "back to the prompt" in MprovShell.cmdloop().


def main():
  
  shell = MprovShell()
  args = sys.argv[1:]
  while args[:1] in (['--json'], ['--dry-run']):
    if args[0] == '--json':
      # results as JSON lines from the start, like 'output json' (#42)
      shell.outputMode = "json"
    else:
      # preview changes from the start, like 'dryrun on' (#43)
      shell.dryRun = True
    args = args[1:]
  
  # Like bash and python: a script file on the command line wins, then a
  # non-TTY stdin, then the interactive shell.  '-' means stdin.
  if len(args) >= 1 and args[0] != '-':
    try:
      shell.setFile(open(args[0], 'r'))
    except OSError as e:
      print(f"mash: {args[0]}: {e.strerror}", file=sys.stderr)
      sys.exit(1)
  elif len(args) >= 1 or not sys.stdin.isatty():
    # we are getting a script on stdin.
    shell.setFile(sys.stdin)
  else:
    shell.setFile(None)
  try:
    shell.cmdloop()
    if shell.file is not None:
      # a script exits 1 if any command in it failed (#32)
      sys.exit(shell.scriptStatus())
  except KeyboardInterrupt:
    # Ctrl-C in a script stops it, with the shell's usual 128 + SIGINT.
    print("", file=sys.stderr)
    sys.exit(130)

def __main__():
  main()

if __name__ == "__main__":
    main()