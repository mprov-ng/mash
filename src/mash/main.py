#!/usr/bin/python3

import signal, os, sys
from mash.app import MprovShell

# an exit handler if we need it.
def exitHandler(signum, frame):
  pass

# setup an exit handler.
signal.signal(signal.SIGINT, exitHandler)
signal.signal(signal.SIGTERM, exitHandler)


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
  shell.cmdloop()

def __main__():
  main()

if __name__ == "__main__":
    main()