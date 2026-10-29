import cmd, sys, json
import os
from os import fork
from jinja2 import BaseLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from io import StringIO
import csv, base64
import getpass
import requests
import shlex
from urllib.parse import quote
import yaml
import importlib
from pathlib import Path
from urllib3.util.retry import Retry

# (connect, read) seconds for every call to the mPCC; 'timeout' in the
# config's 'global' section overrides the read part (#29).
DEFAULT_TIMEOUT = (10, 120)


class TimeoutSession(requests.Session):
  'A Session whose requests time out unless the caller passes its own timeout.'
  timeout = DEFAULT_TIMEOUT

  def request(self, method, url, **kwargs):
    if kwargs.get('timeout') is None:
      kwargs['timeout'] = self.timeout
    return super().request(method, url, **kwargs)


class MprovShell(cmd.Cmd):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    
  # config files 'connect' reads, in order of preference.  The first
  # readable one wins.
  configfiles = ["~/.mprov-mash.yaml", "/etc/mprov/mash.yaml", "/etc/mprov/jobserver.yaml"]
  configfile = None
  intro = "Welcome to the mProv shell.  Type help or ? to list commands.\n"
  prompt = '<mProv> # '
  file = None
  variables = {}
  session = TimeoutSession()
  mprovURL = ""
  apikey = ""
  models={}
  processes = []
  quiet = False
  config_data={}
  failed = False # set by err(); makes a script exit 1
  configKeys = ('mprovURL', 'apikey', 'timeout') # the 'global' keys mash reads
  inForLoop = False
  forLoopCmds = []
  forLoopItemName = ""
  forLoopList = [] # the list we will iterate on
  # query keys the mPCC reads besides model fields: MProvView's flags and
  # DRF's search, plus the ones single views take (as of mPCC 2544a86).
  queryKeys = {
    'detail', 'self', 'search', 'format',
    'hostname', 'network', 'isdhcp', 'managedns', 'new_subnet', 'new_netmask',
    'module', 'params', 'jobserver', 'status', 'powerstate', 'rescue',
  }


  def setFile(self, file):
    self.file = file

  def print(self, *args):
    'Use self.print not print() to output so we can catch it internally.'
    print(*args, file=self.stdout)
  
  def err(self, *args):
    'Report an error on stderr; a script that hit one exits 1 (#31, #32).'
    self.failed = True
    print(*args, file=sys.stderr)

  def warn(self, *args):
    'Like err(), but the command carries on and the exit status is unchanged.'
    print(*args, file=sys.stderr)

  def onecmd(self, line):
    'Run one command; an unexpected error ends that command, not the shell (#28).'
    try:
      return super().onecmd(line)
    except Exception as e:
      self.err(f"Error: {type(e).__name__}: {e}")

  def emptyline(self):
    return 

  def yaml_include(self, loader, node):
    # Placeholder: Unused.  
    return {}

  def load_config(self):
    # load the config yaml
    # print(self.configfile)
    yaml.add_constructor("!include", self.yaml_include)

    self.configfile = None
    skipped = []
    for path in self.configfiles:
      path = os.path.expanduser(path)
      if not os.path.isfile(path):
        skipped.append(f"{path}: not found")
      elif not os.access(path, os.R_OK):
        skipped.append(f"{path}: permission denied")
      else:
        self.configfile = path
        break
    if self.configfile is None:
      self.err("Unable to find a readable config file.  Tried:")
      for line in skipped:
        self.err(f"  {line}")
      return False

    with open(self.configfile, "r") as yamlfile:
      self.config_data = yaml.load(yamlfile, Loader=yaml.FullLoader)
    # Accept both shapes the file is written in: a top-level mapping
    # ('global:' as a top-level key, the obvious way to write it) and the
    # historical top-level list of mappings ('- global: {...}').
    if isinstance(self.config_data, list):
      result = {}
      for entry in self.config_data:
        if not isinstance(entry, dict):
          self.err(f"{self.configfile}: expected a mapping or a list of mappings, found a list containing a {type(entry).__name__} (expected format: global:\n  apikey: <api-key>\n  mprovURL: <mprov-url>)")
          return False
        result.update(entry)
      self.config_data = result
    if not isinstance(self.config_data, dict):
      self.err(f"{self.configfile}: expected a mapping or a list of mappings, found {type(self.config_data).__name__} (expected format: global:\n  apikey: <api-key>\n  mprovURL: <mprov-url>)")
      return False
    if 'global' not in self.config_data or not isinstance(self.config_data['global'], dict):
      self.err(f"{self.configfile}: config has no 'global' section (expected format: global:\n  apikey: <api-key>\n  mprovURL: <mprov-url>)")
      return False
    return True

  def _checkConfigKeys(self):
    '''Check the keys of the config just loaded (#44).

    mprovURL and apikey must be set.  In mash's own files an unknown key
    gets a warning (naming the known key it most likely meant), but the
    job server's jobserver.yaml has keys of its own, so it isn't checked.
    '''
    conf = self.config_data['global']
    if os.path.basename(self.configfile) != "jobserver.yaml":
      known = {k.lower(): k for k in self.configKeys}
      for key in conf:
        if key in self.configKeys:
          continue
        hint = f"; did you mean '{known[str(key).lower()]}'?" if str(key).lower() in known else ""
        self.warn(f"Warning: {self.configfile}: unknown key '{key}' in 'global'{hint}")
      for key in self.config_data:
        if key != 'global':
          self.warn(f"Warning: {self.configfile}: unknown section '{key}' (only 'global' is read)")
    for key in ('mprovURL', 'apikey'):
      if conf.get(key) in (None, ""):
        self.err(f"{self.configfile}: '{key}' isn't set in 'global' (expected format: global:\n  apikey: <api-key>\n  mprovURL: <mprov-url>)")
        return False
    return True

  def default(self,args):
    '''
    Default command to run when the command is not recognized.

    Here we will try to find a plugin with the name that matches the first part of the command,
    and pass the rest of the line to the plugin

    A trailing '&' runs the plugin command in the background, like the
    CRUD verbs (#37).
    '''
    if args.endswith("&"):
      return self._runInBackground(self.default, args[:-1].rstrip())
    if " " not in args:
      pluginName = args
      args = ""
    else:
      pluginName, args = args.split(" ", 1)
    pluginMod = importlib.util.find_spec(f"mash.plugins.{pluginName}")
    if pluginMod is not None:
      try:
        plugin = importlib.import_module(f"mash.plugins.{pluginName}")
        pluginCmd = getattr(plugin, "PluginCMD")
        if pluginCmd is not None:
          pluginInstance = pluginCmd(self)
          if pluginInstance is None:
            self.err(f"Error: Unable to instantiate plugin {pluginName}")
            return
          # send the line off to the plugin
          # print(f"Plugin: {pluginName}")
          pluginInstance.onecmd(args)
        else:
          self.err(f"Error: 'PluginCMD' class not found on plugin {pluginName}")
          return
      except Exception as e:
        self.err(f"Error: Exception in plugin {pluginName}. {e}")
        return
      return
      # Look in mash.plugins for mash.plugins.<first arg> for a matching plugin.
    self.err(f"Error: Unrecognized command {pluginName}")

  def do_help(self, arg: str) :
    result = False
    result = super().do_help(arg)
    if arg == "":
      # empty arg, list our plugins
      self.print("\nLoaded Plugins:\n===============")
      plugins = importlib.util.find_spec('mash.plugins')
      if plugins is not None:
        submodulePath = Path(plugins.origin).parent
        with os.scandir(submodulePath) as entries:
          for plugin in entries:
            if plugin.name.startswith('__'):
              continue
            pluginName, _ = plugin.name.split('.', 1)
            if plugin.is_file():
              self.print(pluginName)

      self.print("\n")
    else:
      self.print(arg)
      if " " not in arg:
        pluginName = arg
        arg=""
      else:
        pluginName, arg = arg.split(" ", 1)
      pluginMod = importlib.util.find_spec(f"mash.plugins.{pluginName}")
      if pluginMod is not None:
        try:
          plugin = importlib.import_module(f"mash.plugins.{pluginName}")
          pluginCmd = getattr(plugin, "PluginCMD")
          if pluginCmd is not None:
            pluginInstance = pluginCmd(self)
            if pluginInstance is None:
              self.err(f"Error: Unable to instantiate plugin {pluginName}")
              return
            # send the line off to the plugin
            pluginInstance.onecmd("help " + arg)
          else:
            self.err(f"Error: 'PluginCMD' class not found on plugin {pluginName}")
            return
        except Exception as e:
          self.err(f"Error: Exception in plugin {pluginName}. {e}")
          return
        return

    return result
   
    
  def do_connect(self,arg):
    '''
Connect to an mProv Control Center.

Usage: 
    connect <mprov_url> apikey <api_key> - Connects with an API key

    connect <mprov_url> user <user> password <password> - connects with a username and password.

    connect <mprov_url> user <user> - prompts for the password when run from a terminal.
    
    connect - With no arguments, mash reads the mprovURL and apikey from the 'global'
    section of the first readable file of: ~/.mprov-mash.yaml, /etc/mprov/mash.yaml,
    /etc/mprov/jobserver.yaml (the job server's own config).  An optional 'timeout'
    there sets how many seconds to wait for a reply (default 120).

    Every request gives up after 10 seconds without a connection or the timeout
    without a reply.  Ctrl-C stops a command that is waiting.

    '''
    authHeader = ""
    args = arg.split()
    if len(args) == 0:
      # we are reading from a yaml file.
      if not self.load_config():
        return
      if not self._checkConfigKeys():
        return
      authHeader = f"Api-Key {self.config_data['global']['apikey']}"
      self.mprovURL = self.config_data['global']['mprovURL']
      if 'timeout' in self.config_data['global']:
        try:
          readTimeout = float(self.config_data['global']['timeout'])
          if readTimeout <= 0:
            raise ValueError
        except (TypeError, ValueError):
          self.err(f"{self.configfile}: 'timeout' must be a number of seconds greater than 0")
          return
        self.session.timeout = (DEFAULT_TIMEOUT[0], readTimeout)

    elif len(args) == 3 and args[1] == 'apikey':
      # we are using an API key
      self.mprovURL = args[0]
      authHeader = f"Api-Key {args[2]}"

    elif args[1:2] == ['user'] and (len(args) == 3 or (len(args) == 5 and args[3] == 'password')):
      # We are using plain text auth
      if len(args) == 5:
        password = args[4]
      elif sys.stdin.isatty():
        try:
          password = getpass.getpass(f"Password for {args[2]}: ")
        except EOFError:
          # ^D at the prompt cancels the connect.
          self.err("")
          return
      else:
        self.err("connect: no password given, and stdin isn't a terminal to prompt on.")
        return
      self.mprovURL = args[0]
      encAuthStr = base64.b64encode(f"{args[2]}:{password}".encode()).decode()
      authHeader = f"Basic {encAuthStr}"

    else:
      self.err("Usage: connect [<mprov_url> apikey <api_key> | <mprov_url> user <user> [password <password>]]")
      return
    # Everything that talks to the mPCC concatenates paths onto mprovURL, so
    # store it without a trailing slash; callers add the slash they need.
    if self.mprovURL:
      self.mprovURL = self.mprovURL.rstrip("/")
    self._connectToMPCC(authHeader)


  def _waitForBackground(self):
    'Wait for the backgrounded commands; one that failed counts as a failure.'
    if(self.processes):
      if not self.quiet:
        self.print("Waiting for background processes")
      while self.processes:
        pid, status = os.wait()
        if pid != 0:
          if not self.quiet:
            print(f"PID {pid} finished.")
          if status != 0:
            self.failed = True
          self.processes.remove(pid)

  def scriptStatus(self):
    'The exit status of a script: 1 if any command in it failed (#32).'
    self._waitForBackground()
    return 1 if self.failed else 0

  def _exit(self):
    if self.file is not None:
      sys.exit(self.scriptStatus())
    sys.exit(0)

  def do_disconnect(self, arg):
    self._waitForBackground()
    self.session.close()

  def do_create(self,arg):
    'Issue a create command to the mPCC. Args create <model> <model args>'
    if arg is None or arg == "": 
      self.err("No argument specified.")
      return
    self._sendHttpRequest("post", arg, True)

  def do_retrieve(self,arg):
    '''
Issue a retrieve command to the mPCC. 
  
Args:
  retrieve <model> [model_args]

Return: 
  Sets MPROV_RESULT to the python object representing the returned object, or sets
  MPROV_RESULT to None if there was an error.
'''
    if arg is None or arg == "": 
      self.err("No argument specified.")
      return
    self._sendHttpRequest("get", arg)
    
  def do_update(self,arg):
    'Issue a update command to the mPCC. Args update <model> <model args>'
    if arg is None or arg == "": 
      self.err("No argument specified.")
      return
    self._sendHttpRequest("patch",arg)
    

  def do_delete(self,arg):
    'Issue a delete command to the mPCC. Args delete <model> <model args>'
    self._sendHttpRequest("delete", arg)

  def do_exit(self, arg):
    'Quit the Shell.'
    self._exit()
  def do_quit(self, arg):
    'Quit the Shell.'
    self._exit()
  def do_EOF(self, arg):
    'Quit the Shell.'
    self._exit()
    
  # alias the http methods to their CRUD equivs.
  def do_post(self, arg):
    'Alias to create. (See \'help create\')'
    return self.do_create(arg)

  def do_get(self, arg):
    'Alias to retrieve. (See \'help retrieve\')'
    return self.do_retrieve(arg)

  def do_patch(self,arg):
    'Alias to update. (See \'help update\')'
    return self.do_update(arg)
  
  def do_let(self, arg):
    '''
Assign an variable internal to this shell session.

You can use jinja2 template strings.  They must reference an already available
internal variable.

Starting a value with a backtick (`) will cause the value to be executed
as if it was an internal command, capturing its output into the variable.


Examples: let foo=bar
          let something=Something else {{foo}}
          let another=`pvar something
          let test=`print I have {{ something }}
'''
    if '=' not in arg:
      self.err("Usage: let <name>=<value>")
      return
    key,value=arg.split('=',1)
    key = key.strip()
    value = value.strip()
    if value=="":
      self.err("Error: Empty value in Assignment")
      return
    #  a backtick at the beginning of a let statement means, run this internal command,
    #  and assign its output as is (it may be empty, or start with a '$').
    if value[0] == '`':
      self.variables[key]=self.execInternal(value[1:])
      return
    
    # a dollar sign means copy the internal variable to 
    # a new internal variable.
    if value[0] == '$':
      intVar = value[1:]
      if intVar in self.variables:
        self.variables[key] = self.variables[intVar]
        return
      else:
        self.err(f"Error: Undefined variable ${intVar}")
        return
    
    # otherwise, assign the given value.
    self.variables[key]=value

  def do_models(self,arg):
    'Display a list of supported data models'
    for model in self.models:
      self.print(model)

  def do_model(self, arg):
    'Display the information about a specific model'
    model = arg
    if model in self.models:
      
      self.print(self.models[model])
      
      return
    self.err(f"Error: Unknown model {model}")

  def do_pvar(self,arg):
    'Display the contents of a variable, or a comma separated list of variables'

    # see if we have a comma separated list of vars to print
    if ',' not in arg:
      if arg in self.variables:
        self.print(f"{arg}={self.variables[arg]}")
      else:
        self.err(f"Error: Unknown variable {arg}")
      return
    for varName in arg.split(','):
      varName = varName.strip()
      if varName in self.variables:
        self.print(f"{varName}={self.variables[varName]}")
  def do_p(self,arg):
    'Alias to pvar'
    self.do_pvar(arg)

  def do_print(self,arg):
    'Print random text and use internal variables'
    self.print(arg)

  def do_foreach(self, arg):
    ''' 
        Run a loop of commands.  Syntax: foreach item in list
        item is a single item from a list
        list is an actual array or a white space separated string
        MUST end your loop with endforeach.
    '''

    if " " not in arg:
      self.err("Error: Syntax error")
      return
    args = arg.split(None, 2)
    if len(args) < 3 :
      self.err("Error: Syntax error")
      return
    if args[1] != "in":
      self.err("Error: Syntax error")
      return
    if " " in args[2]:
      # Strip one matching pair of surrounding quotes (quoted inline lists
      # are the only inline form that worked on master).
      rest = args[2]
      if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in ('"', "'"):
        rest = rest[1:-1]
      # convert the string to a list
      self.forLoopList = rest.split(" ")
    else:
      # print(args)
      if args[2] not in self.variables:
        self.err(f"Error: {args[2]} is not defined")
        return
      if type(self.variables[args[2]]) is not list:
        self.err(f"Error: {args[2]} must be type list")
        return
      # print(args[2])
      self.forLoopList = self.variables[args[2]]
    self.variables[args[0]] = None
    self.forLoopItemName = args[0]
    
    self.prompt = "<mProv> -for-> "
    self.inForLoop = True
    

  def do_endforeach(self,arg):
    ''' Ends a foreach loop, attempts to run the loop, 
        and then returns to normal operation. If any command
        in the loop fails, the loop stops and an error is set
    '''
    self.prompt = "<mProv> # "
    self.inForLoop = False
    if len(self.forLoopCmds) > 0:
      # Run our for loop cmds.
      for i in self.forLoopList:
        self.variables[self.forLoopItemName] = i
        for command in self.forLoopCmds:
          rendered = self.renderString(command)
          if rendered is None or self.onecmd(rendered) == False:
            self.err("Error running loop.")
            self.forLoopCmds.clear()
            self.forLoopList=[]
            self.forLoopItemName = ""
            return
      self.forLoopCmds.clear()
      self.forLoopList=[]
      self.forLoopItemName = ""
            
  def do_seq(self, arg):
    '''
    Syntax: seq <var> <start> <end> <width>
    Creates a sequence as a list and puts it in variable var
    '''
    args = arg.split()
    try:
      if len(args) not in (3, 4):
        raise ValueError
      start, end = int(args[1]), int(args[2])
      width = int(args[3]) if len(args) == 4 else 1
    except ValueError:
      self.err("Usage: seq <var> <start> <end> [<width>]  (start, end and width are integers)")
      return
    self.variables[args[0]] = []
    for i in range(start, end + 1):
      self.variables[args[0]].append(str(i).zfill(width))

    
  def execInternal(self, arg):
    'Executes the specified command, capturing the output, and returning it as a string. '
    old_stout = self.stdout
    self.stdout = tmpstdout = StringIO()
    try:
      self.onecmd(arg)
    finally:
      self.stdout = old_stout
    return tmpstdout.getvalue()

  def renderString(self, tempStr):
    '''use the internal variables to render a string.

    Returns None if the template can't be rendered (a syntax error, an
    undefined name, an attribute the sandbox refuses, ...), so callers
    don't run the command with the raw or half-rendered text (#57).'''
    jinjaEnv = SandboxedEnvironment(
      loader=BaseLoader,
      autoescape=False,
      undefined=StrictUndefined
    )
    try:
      templateStr=jinjaEnv.from_string(tempStr)
      return templateStr.render(**self.variables)
    except Exception as e:
      self.err(f"Error trying to template, {e}")
    return None
  
  def _connectToMPCC(self, authHeader):
    self.session.headers.update({
      'Content-Type': 'application/json',
      'Authorization': authHeader,
      'Connection': 'close',
    })
    try:
      # retry failed connections, but not a request that timed out waiting
      # for its reply, or a hung mPCC holds every GET for 21 timeouts (#29).
      adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=Retry(total=20, read=0), pool_block=True)
      self.session.mount('https://', adapter)
      self.session.mount('http://', adapter)
      response = self.session.get(self.mprovURL, stream=True)
    except Exception:
      self.err(f"Error: Unable to communicate with mPCC {self.mprovURL}")
      return
    if response.status_code==200:
      # we connected, get the supported data models.
      self._getMPCCModels()
    else:
      # the mPCC's / needs a login, so a bad key or password lands here (#38).
      self.models = {}
      hint = "; check the API key or user and password" if response.status_code in (401, 403) else ""
      self.err(f"Error: Unable to connect to mPCC {self.mprovURL}, code: {response.status_code}{hint}")
      body = response.text.strip()
      if body:
        self.err(body[:500])
  def _parseArgType(self, arg):
    if arg == None or arg == "''" or arg == "\"\"" or arg=="":
      return None

    if arg[0] == "[" and arg[len(arg)-1] == "]":
      return arg[1:-1:].split(",")
    if arg[0] == "{" and arg[len(arg)-1] == "}":
      raise ValueError(f"dict values aren't supported yet: {arg}")
    return arg
  def _httpErrorExit(self):
    """Single exit for every _sendHttpRequest error path (mprov-ng/mash#26).

    Clears MPROV_RESULT so a failed command cannot leave the previous
    command's result behind.  Error branches should use
    "return self._httpErrorExit()".
    """
    self.variables["MPROV_RESULT"] = None
    self.failed = True
    return

  def _runInBackground(self, func, *args, **kwargs):
    'Run func(*args, **kwargs) in a forked child; the parent tracks it and returns.'
    ret = fork()
    if ret != 0:
      # we are parent
      # Process tracking,
      self.processes.append(ret)
      # do nothing and return.
      return
    # we are the child: run the command, then always exit, so an error
    # path can't return into the parent's script and run the rest of it
    # a second time.
    try:
      func(*args, **kwargs)
    except BaseException as e:
      if not isinstance(e, SystemExit):
        self.err(f"Error: {type(e).__name__}: {e}")
    finally:
      self.stdout.flush()
      sys.stderr.flush()
      # the parent counts a non-zero exit as a failed command (#32)
      os._exit(1 if self.failed else 0)

  def _sendHttpRequest(self, method, arg, checkargs=False, background=False):
    if arg is None or arg == "":
      self.err("No argument specified.")
      return self._httpErrorExit()
    if arg[-1] == '&' and not background:
      # if the last character of the string is an &, fork and return as parent.
      return self._runInBackground(self._sendHttpRequest, method, arg[:-1], checkargs, background=True)

    # parse the model out, and the args, if any were passed.
    try:
      model, model_args = arg.split(' ', 1)
    except:
      model = arg
      model_args = ""
      
    if model not in self.models:
      self.err(f"Error: Unknown Model {model}.")
      return self._httpErrorExit()
    
    # get the endpoint
    if 'endpoint' in self.models[model]:
      mEndpoint = self.models[model]['endpoint']
    else:
      self.err(f"Error: Model {model} does not seem to have a registered endpoint in the mPCC.")
      return self._httpErrorExit()
    requestData = {}
    idStr = ""
    queryParams = []
    if method  == "post" or method == "patch":
      
      # check our args against the data structure.
      try:
        margs = shlex.split(model_args)
      except ValueError as e:
        self.err(f"Error: can't parse the arguments: {e}")
        return self._httpErrorExit()
      for marg in margs:
        if "=" not in marg:
          self.err(f"Error: expected <field>=<value>, got '{marg}'")
          return self._httpErrorExit()
        key, value = marg.split("=", 1)
        if key in self.models[model]['fields']:
          # check our value for list or dict and add it to the 
          # data.
          try:
            requestData[key]=self._parseArgType(value)
          except ValueError as e:
            self.err(f"Error: {key}: {e}")
            return self._httpErrorExit()
          if key == 'id' or key == 'pk':
            idStr=f"{value}/"
        else:
          self.err(f"Error: Model {model} does not have field {key}")
          self.err(f"Check 'model {model}' and try again.")
          return self._httpErrorExit()
      if checkargs:
        # make sure the required fields are present
        for field in self.models[model]['fields']:
          if field not in requestData and self.models[model]['fields'][field]['required']:
            self.err(f"Error: Missing field required {field} for model {model}.")
            self.err(f"Check 'model {model}' and try again.")
            return self._httpErrorExit()
    elif method == "get" or method == "delete":
      # every token is key=value; requests encodes them, so a value with
      # '&', '#' or '%' in it stays one value (#19, #36).
      for marg in model_args.split():
        if "=" not in marg or marg.startswith("="):
          self.err(f"Error: expected <field>=<value>, got '{marg}'")
          return self._httpErrorExit()
        key, value = marg.split("=", 1)
        if key == 'id' or key == 'pk':
          # we got an id, so add it to the URL
          idStr = f"{quote(value, safe='')}/"
        elif key not in self.models[model].get('fields', {}) and key not in self.queryKeys:
          # the mPCC ignores filters it doesn't know, so warn rather than refuse.
          self.warn(f"Warning: Model {model} has no field {key}; the mPCC may ignore this filter and match every row.")
        queryParams.append((key, value))
    
    if method == "post":
      try:
        response = self.session.post(f"{self.mprovURL}{mEndpoint}{idStr}", params=queryParams, data=json.dumps(requestData), headers={'Connection':'close'}, stream=True)
      except requests.RequestException as e:
        self.err(f"Error: {e}")
        return self._httpErrorExit()
    elif method == "get":
      try:
        response = self.session.get(f"{self.mprovURL}{mEndpoint}{idStr}", params=queryParams, stream=True) # TODO: Add query string and ID stuff.
      except requests.RequestException as e:
        self.err(f"Error: {e}")
        return self._httpErrorExit()
    elif method == "patch":
      try:
        response = self.session.patch(f"{self.mprovURL}{mEndpoint}{idStr}", params=queryParams, data=json.dumps(requestData), stream=True) # TODO:
      except requests.RequestException as e:
        self.err(f"Error: {e}")
        return self._httpErrorExit()
    elif method == "delete":
      try:
        response = self.session.delete(f"{self.mprovURL}{mEndpoint}{idStr}", params=queryParams, stream=True) # TODO
      except requests.RequestException as e:
        self.err(f"Error: {e}")
        return self._httpErrorExit()
    else: 
      response = None
      self.err(f"Error: Unsupported method {method}.")
      return self._httpErrorExit()
    
    if response.status_code < 200 or response.status_code > 299 :
      self.err(f"Error: Communications error with mPCC, code: {response.status_code}")
      self.err(f"{response.text}")
      return self._httpErrorExit()

    # only assign MPROV_RESULT if we are not running in the background/parallel.  
    if not background:
      if not response.text.strip():
        # a successful delete answers 204 with no body (DRF's destroy()),
        # and some views answer an empty 200: nothing to return (#69).
        self.variables['MPROV_RESULT'] = None
      else:
        try:
          self.variables['MPROV_RESULT'] = response.json()
        except Exception:
          self.err("Error: the mPCC's reply isn't JSON; MPROV_RESULT not set")
          return self._httpErrorExit()
      if not self.quiet:
        self.print("OK")
    else:
      # self.print(f"{response.text}")
      # exit because we were backgrounded and forked.  Don't want to return to main.
      sys.exit(0)


  def _getMPCCModels(self):
    response = self.session.get(f"{self.mprovURL}/datamodel/")
    if response.status_code == 200:
      modellist = response.json()['datamodels']
      for model in modellist:
        response = self.session.get(f"{self.mprovURL}/datamodel/?model={model}")
        if response.status_code != 200:
          self.err(f"Error: Unable to retrieve data structure for model {model}, code: {response.status_code}")
          continue
        self.models[model] = response.json()
    else:
      self.err(f"Error: Unable to retrieve the data models from the mPCC, code: {response.status_code}")
    
    
  # pre-process commandline if needed
  def precmd(self, line):

    # ignore comments.
    if len(line) > 0:
          if line[0] == "#": 
            return ""
    if self.inForLoop :
      # we are in a for loop, so just add the command to the forLoopCmds list
      if line == "endforeach":
        return line
      self.forLoopCmds.append(line)
      line = ""
    else:
      # pass the string through the jinja2 template engine and map internal variable values.

      line = self.renderString(line)
      if line is None:
        # the template failed; renderString reported it, so skip the command.
        line = ""
    return line

  def cmdloop(self, intro=None):
    if self.file != None:
      self.quiet = True
      # we are getting a file piped in.
      # it should be an FD, not a file name.
      for line in self.file:

        line=line.strip()
        # skip comments.
        if len(line) > 0:
          if line[0] == "#": 
            continue
        
        self.onecmd(self.precmd(line))
    else:
      # Ctrl-C stops the command that is running (or the line being typed)
      # and goes back to the prompt, like bash (#30).
      while True:
        try:
          return super().cmdloop(intro=intro)
        except KeyboardInterrupt:
          self.err("^C")
          intro = ""










  