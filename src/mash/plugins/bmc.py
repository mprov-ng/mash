import cmd, sys
from mash.utils import rangeToList
'''
This plugin is used to perform power functions on nodes through the mPCC.
'''
# the actions the mPCC's /power/<action>/ carries out; it answers 200 to
# any other action and does nothing, so mash checks first (#41).
POWER_ACTIONS = ['on', 'off', 'cycle', 'reset', 'status', 'pxe', 'pxeefi']

class PluginCMD(cmd.Cmd):
  mashCmd = None
  def __init__(self, mashCmd=None):
    if mashCmd is None:
      print("ERROR: mashCmd not passed to plugin!", file=sys.stderr)
      return
    self.mashCmd = mashCmd
    super().__init__(stdin=mashCmd.stdin, stdout=mashCmd.stdout)

  def default(self, arg):
    if arg == "":
      self.do_help("")
      return
    if " " not in arg:
      self.do_help(arg)
      return
    self.mashCmd.err(f"Error: Unrecognized sub command to bmc: {arg}")
    return

  def do_power(self, arg):
    '''
Manage the power of a node or set of nodes via the BMC, if configured.

bmc power <action> <node_spec>

  action:  One of
             on, off, cycle, reset  power the node on, off, off and on, or reset it
             status                 show whether the node is powered on
             pxe, pxeefi            PXE boot the node (legacy BIOS or UEFI) to provision it
  node_spec: Either the name of a node, or a node range in slurm type notation. (ie. compute00[01-30,31,35,36-40,45-99])

  End the line with '&' to run it in the background.

Examples: bmc power on compute00[01-20,21,23]
          bmc power off compute0050
          bmc power status compute0050
    '''
    if(self.mashCmd.mprovURL is None) or self.mashCmd.mprovURL == "" :
      self.mashCmd.err("ERROR: You probably aren't connected.")
      return
    try:
      action, noderange = arg.split(" ", 1)
    except Exception as e:
      self.do_help("power")
      return
    if action not in POWER_ACTIONS:
      self.mashCmd.err(f"Error: unknown power action '{action}' (one of: {', '.join(POWER_ACTIONS)})")
      return
    nodelist = rangeToList(noderange)
    failed = False
    for node in nodelist:
      try:
        response = self.mashCmd.session.get(f"{self.mashCmd.mprovURL}/power/{action}/?hostname={node}", stream=True)
      except Exception as e:
        failed = True
        self.mashCmd.print(f"{node}: ERROR {e}")
        continue
      if 200 <= response.status_code < 300:
        try:
          body = response.json()
        except Exception:
          body = None
        if isinstance(body, dict):
          if len(body) == 0:
            failed = True
            self.mashCmd.print(f"{node}: ERROR no BMC configured")
            continue
          # Power API returns { "<node>-bmc": <result> } per node.
          for bmc_name, entry in body.items():
            if entry is None:
              self.mashCmd.print(f"{node}: OK")
            elif isinstance(entry, dict):
              status = entry.get("status", "")
              details = entry.get("details", "")
              # Non-200 status inside body means failure (e.g. 400 timed out, 409 pxe refused)
              try:
                status_int = int(status)
              except Exception:
                status_int = 200
              if status_int != 200:
                failed = True
                self.mashCmd.print(f"{node}: ERROR {details or entry}")
              else:
                # status action may include chassis_status
                if action == "status" and "chassis_status" in entry:
                  self.mashCmd.print(f"{node}: {entry['chassis_status']}")
                elif action == "status" and details:
                  self.mashCmd.print(f"{node}: {details}")
                else:
                  self.mashCmd.print(f"{node}: {response.text.strip() or 'OK'}")
            else:
              self.mashCmd.print(f"{node}: {response.text.strip() or 'OK'}")
        else:
          self.mashCmd.print(f"{node}: {response.text.strip() or 'OK'}")
      else:
        failed = True
        self.mashCmd.print(f"{node}: ERROR code {response.status_code}: {response.text.strip()}")
    if failed:
      self.mashCmd.err(f"Error: 'bmc power {action}' failed on one or more nodes.")
    
