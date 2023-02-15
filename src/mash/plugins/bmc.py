import cmd, sys
from mash.utils import rangeToList
'''
This plugin is used to perform power functions on nodes through the mPCC.
'''
class PluginCMD(cmd.Cmd):
  background=False
  mashCmd = None
  def __init__(self, mashCmd=None):
    if mashCmd is None:
      print("ERROR: mashCmd not passed to plugin!", file=sys.stderr)
      return
    self.mashCmd = mashCmd
    super().__init__()

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

  action:  One of 'on', 'off', 'cycle', or 'reset'
  node_spec: Either the name of a node, or a node rang in slurm type notation. (ie. compute00[01-30,31,35,36-40,45-99])

Examples: bmc power on compute00[01-20,21,23]
          bmc power off compute0050
    '''
    try:
      action, noderange = arg.split(" ", 1)
    except Exception as e:
      self.do_help("power")
      return
    nodelist = rangeToList(noderange)
    for node in nodelist:
      response = self.mashCmd.session.get(f"{self.mashCmd.mprovURL}power/{action}/?hostname={node}", timeout=None, stream=True)
    

  def precmd(self, line: str) -> str:
    if line[-1] == "&":
      line = line[:-1]
      self.background = True
    return line