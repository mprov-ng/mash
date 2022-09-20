import cmd, sys, json
from importlib.util import module_from_spec
from curses import raw
from urllib import response
from jinja2 import Environment, BaseLoader, select_autoescape
from io import StringIO
import csv, base64
import requests
import shlex

class MprovShell(cmd.Cmd):
  intro = "Welcome to the mProv shell.  Type help or ? to list commands.\n"
  prompt = '<mProv> # '
  file = None
  variables = {}
  session = requests.Session()
  mprovURL = ""
  models={}

  def setFile(self, file):
    self.file = file

  def print(self, *args):
    'Use self.print not print() to output so we can catch it internally.'
    print(*args, file=self.stdout)

  def do_connect(self,arg):
    '''
Connect to an mProv Control Center.

Usage: 
    connect <mprov_url> apikey <api_key> - Connects with an API key

    connect <mprov_url> user <user> password <password> - connects with a username and password.
    
    connect - With no arguments, mprov-cmd will try to read the .mprov-cmd.yaml file in the user's 
    home directory (~/.mprov-cmd.yaml) and then try to read /etc/mprov/mprov-cmd.yaml

    '''
    args = arg.split(' ')
    authHeader = ""
    if len(args) == 0:
      # TODO: we are reading from a yaml file.
      self.print("Not Implemented")
      return
    if len(args) > 0:
      self.mprovURL = args[0]
      if 'apikey' == args[1]: 
        # we are using an API key
        authHeader = f"Api-Key {args[2]}"
        
      if 'user' == args[2]:
        # We are using plain text auth
        rawAuthStr=f"{args[2]}:{args[4]}"
        encAuthStr=base64.b64encode(rawAuthStr)
        authHeader = f"Basic {encAuthStr}"
    self._connectToMPCC(authHeader)


  def do_disconnect(self, arg):
    self.session.close()

  def do_create(self,arg):
    'Issue a create command to the mPCC. Args create <model> <model args>'

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
    self._sendHttpRequest("get", arg)
    
  def do_update(self,arg):
    'Issue a update command to the mPCC. Args update <model> <model args>'
    self._sendHttpRequest("patch",arg)
    

  def do_delete(self,arg):
    'Issue a delete command to the mPCC. Args delete <model> <model args>'
    self._sendHttpRequest("delete", arg)

  def do_exit(self, arg):
    'Quit the Shell.'
    sys.exit(0)
  def do_quit(self, arg):
    'Quit the Shell.'
    sys.exit(0)
  def do_EOF(self, arg):
    'Quit the Shell.'
    sys.exit(0)
    
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
    key,value=arg.split('=',1)
    key = key.strip()
    value = value.strip()
    #  a backtick at the beginning of a let statement means, run this internal command.
    if value[0] == '`':
      value=self.execInternal(value[1:])    
    
    # a dollar sign means copy the internal variable to 
    # a new internal variable.
    if value[0] == '$':
      intVar = value[1:]
      if intVar in self.variables:
        self.variables[key] = self.variables[intVar]
        return
      else:
        self.print(f"Error: Undefined variable ${intVar}")
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
    self.print(f"Error: Unknown model {model}")

  def do_pvar(self,arg):
    'Display the contents of a variable, or a comma separated list of variables'

    # see if we have a comma separated list of vars to print
    if ',' not in arg:
      if arg in self.variables:
        self.print(f"{arg}={self.variables[arg]}")
      else:
        self.print(f"Error: Unknown variable {arg}")
      return
    csvparser = csv.reader(arg)
    for vars in csvparser:
      for varName in vars:
        if varName in self.variables:
          self.print(f"{varName}={self.variables[varName]}")
  
  def do_print(self,arg):
    'Print random text and use internal variables'
    self.print(arg)

  def execInternal(self, arg):
    'Executes the specified command, capturing the output, and returning it as a string. '
    old_stout = self.stdout
    self.stdout = tmpstdout = StringIO()
    self.onecmd(arg)
    self.stdout = old_stout
    return tmpstdout.getvalue()

  def renderString(self, tempStr):
    'use the internal variables to render a string.'
    jinjaEnv = Environment(
      loader=BaseLoader,
      autoescape=False
    )
    templateStr=jinjaEnv.from_string(tempStr)
    return templateStr.render(**self.variables)
  
  def _connectToMPCC(self, authHeader):
    print(authHeader)
    self.session.headers.update({
      'Content-Type': 'application/json',
      'Authorization': authHeader,
    })
    try:
      response = self.session.get(self.mprovURL, stream=True)
    except:
      self.print(f"Error: Unable to communicate with mPCC {self.mprovURL}")
      return
    if response.status_code==200:
      # we connected, get the supported data models.
      self._getMPCCModels()

  def _sendHttpRequest(self, method, arg, checkargs=False, background=False):

    # parse the model out, and the args, if any were passed.
    try:
      model, model_args = arg.split(' ', 1)
    except:
      model = arg
      model_args = ""
      
    if model not in self.models:
      self.print(f"Error: Unknown Model {model}.")
      return
    
    # get the endpoint
    if 'endpoint' in self.models[model]:
      mEndpoint = self.models[model]['endpoint']
    else:
      self.print(f"Error: Model {model} does not seem to have a registered endpoint in the mPCC.")
      return
    requestData = {}
    idStr = ""
    queryString = ""
    if method  == "post" or method == "patch":
      
      # check our args against the data structure.
      for marg in shlex.split(model_args):
        key, value = marg.split("=", 1)
        if key in self.models[model]['fields']:
          requestData[key]=value
          if key == 'id' or key == 'pk':
            idStr=f"{value}/"
        else:
          self.print(f"Error: Model {model} does not have field {key}")
          self.print(f"Check 'model {model}' and try again.")
          self.variables['MPROV_RESULT']=None
          return
      if checkargs:
        # make sure the required fields are present
        for field in self.models[model]['fields']:
          if field not in requestData and self.models[model]['fields'][field]['required']:
            self.print(f"Error: Missing field required {field} for model {model}.")
            self.print(f"Check 'model {model}' and try again.")
            self.variables['MPROV_RESULT']=None
            return
    elif method == "get" or method == "delete":
      # build query strings
      if model_args == "" :
        queryString=""
      else:
        queryString = "?"

        for marg in model_args.split(" "):
          try:
            key, value = marg.split('=',1)
            if key == 'id' or key == 'pk':
              # we got an id, so add it to the URL
              idStr=f"{value}/"
          except:
            pass
          queryString += f"{marg}&"
    
    # TODO: add the ability to detect if we should background the request.
    
    if method == "post":
      response = self.session.post(f"{self.mprovURL}{mEndpoint}{idStr}{queryString}", data=json.dumps(requestData))
    elif method == "get":
      response = self.session.get(f"{self.mprovURL}{mEndpoint}{idStr}{queryString}") # TODO: Add query string and ID stuff.
    elif method == "patch":
      response = self.session.patch(f"{self.mprovURL}{mEndpoint}{idStr}{queryString}", data=json.dumps(requestData)) # TODO:
    elif method == "delete":
      response = self.session.delete(f"{self.mprovURL}{mEndpoint}{idStr}{queryString}") # TODO
    else: 
      response = None
      self.print(f"Error: Unsupported method {method}.")
      return
    
    if response.status_code < 200 and response.status_code > 299 :
      self.print(f"Error: Communications error with mPCC, code: {response.status_code}")
      self.print(f"{response.text}")
      return

    # only assign MPROV_RESULT if we are not running in the background/parallel.  
    if not background:
      try:
        self.variables['MPROV_RESULT'] = response.json()
      except: 
        print("Error setting MPROV_RESULT")
        # self.print(f"{response.text}")
        self.variables['MPROV_RESULT'] = None
        self.print("ERROR")
        return
      self.print("OK")
    else:
      self.print(f"{response.text}")


  def _getMPCCModels(self):
    response = self.session.get(f"{self.mprovURL}/datamodel/")
    if response.status_code == 200:
      modellist = response.json()['datamodels']
      for model in modellist:
        response = self.session.get(f"{self.mprovURL}/datamodel/?model={model}")
        if response.status_code != 200:
          self.print(f"Error: Unable to retrieve data structure for model {model}, code: {response.status_code}")
          continue
        self.models[model] = response.json()
    else:
      self.print(f"Error: Unable to retrieve the data models from the mPCC, code: {response.status_code}")
    
    
  # pre-process commandline if needed
  def precmd(self, line):
    # pass the string through the jinja2 template engine and map internal variable values.
    line = self.renderString(line)
    return line

  def cmdloop(self, intro=None):
    if self.file != None:
      # we are getting a file piped in.
      # it should be an FD, not a file name.
      for line in self.file:

        line=line.strip()
        # skip comments.
        if line[0] == "#": 
          continue
        
        self.onecmd(line)
    else:
      return super().cmdloop(intro=intro)










  