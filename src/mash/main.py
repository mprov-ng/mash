#!/usr/bin/python3

import sys
from mash.app import MprovShell

# SIGINT and SIGTERM keep Python's default handling, so a hung request
# can always be interrupted (#30).  The interactive shell turns Ctrl-C
# into "back to the prompt" in MprovShell.cmdloop().


def main():
  
  shell = MprovShell()
  
  # Like bash and python: a script file on the command line wins, then a
  # non-TTY stdin, then the interactive shell.  '-' means stdin.
  if len(sys.argv) >= 2 and sys.argv[1] != '-':
    try:
      shell.setFile(open(sys.argv[1], 'r'))
    except OSError as e:
      print(f"mash: {sys.argv[1]}: {e.strerror}", file=sys.stderr)
      sys.exit(1)
  elif len(sys.argv) >= 2 or not sys.stdin.isatty():
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