# mash (mProv Admin Shell)

This is the command line utility for talking to the mProv Control Center (mPCC).
It works as an interactive shell, and it can also run scripts that create,
read, update and delete mPCC objects in bulk.

## Requirements
`mash` needs Python 3.8 or later, and the packages listed in `requirements.txt`. To install those with pip: `pip install -r requirements.txt`

The package is on PyPI as `mprov_mash` (`pip install mprov_mash`), which installs the `mash` command.

## Connecting

Every session starts with `connect`. It checks that the mPCC answers, then
loads the mPCC's data models (see [Models](#models)).

```
connect                                    # read the mprovURL and apikey from a config file
connect https://mpcc.example.com apikey <key>
connect https://mpcc.example.com user admin password <password>
connect https://mpcc.example.com user admin  # prompts for the password (terminal only)
```

`connect` with no arguments reads the first readable file in this list:

1. `~/.mprov-mash.yaml`
2. `/etc/mprov/mash.yaml`
3. `/etc/mprov/jobserver.yaml` (the job server's own config, so mash works on a job server with no extra setup)

If none of them can be read, `connect` lists each file it tried and why it skipped it.

The file needs a `global` section:

```yaml
global:
  mprovURL: https://mpcc.example.com
  apikey: <api-key>
  timeout: 300   # optional: seconds to wait for a reply (default 120)
```

`mprovURL` and `apikey` must both be set. In mash's own files an unknown key
or section gets a warning, which names the key you probably meant. Keys in
`jobserver.yaml` aren't checked, because the job server has keys of its own.

Every request to the mPCC gives up after 10 seconds without a connection, or
after `timeout` seconds without a reply. A request that timed out is not
retried. Press Ctrl-C to stop a command that is waiting.

If the mPCC refuses the login (401/403), `connect` says so and suggests
checking the API key or the user and password.

## Models

The mPCC describes its objects as data models, for example
`systems.models.System` or `networks.models.Switch`.

```
models                        # list every model
model systems.models.System   # its endpoint and fields, including which fields are required
```

## Create, retrieve, update, delete

```
create   <model> <field>=<value> ...   # POST   (alias: post)
retrieve <model> [<key>=<value> ...]   # GET    (alias: get)
update   <model> id=<id> <field>=<value> ...   # PATCH (alias: patch)
delete   <model> id=<id>               # DELETE
```

- `create` checks that every required field is given, and both `create` and
  `update` refuse a field the model doesn't have. Quote a value that has spaces
  in it: `create ... name="rack 1"`. A value written as `[a,b,c]` is sent as a
  list.
- `id=` (or `pk=`) puts the id in the URL (`.../systems/12/`). Every other
  `key=value` on `retrieve`/`delete` becomes a query parameter, encoded so that
  `&`, `#` and `%` stay inside the value.
- A query key that isn't a field of the model, and isn't one of the extra keys
  the mPCC reads (`detail`, `self`, `search`, `format`, `hostname`, `network`,
  `isdhcp`, `managedns`, `new_subnet`, `new_netmask`, `module`, `params`,
  `jobserver`, `status`, `powerstate`, `rescue`), still gets sent, but mash
  warns you about it. Older mPCCs ignore unknown filters and return every row;
  newer ones reject them with 400. Lookups such as `hostname__startswith=` are
  not supported.
- The parsed reply is stored in the variable `MPROV_RESULT`. `retrieve` with
  filters always returns a list, even when only one object matches. A
  successful delete has no reply body, so `MPROV_RESULT` is `None` afterwards.
  After any failed command, `MPROV_RESULT` is `None` too, so you never see the
  previous command's result by mistake.
- Add `&` to the end of the line to run the command in the background. A
  background command doesn't set `MPROV_RESULT`. A script waits for its
  background commands before it exits.

## Variables and templates

```
let name=value                 # set a variable
let copy=$name                 # copy a variable
let out=`retrieve ...          # run a command and keep what it printed
let id={{ MPROV_RESULT['id'] }}
seq nodes 1 40 3               # nodes = ['001', '002', ..., '040']
pvar name                      # show variables (alias: p); also pvar a,b,c
print Hello {{ name }}
```

Every line is rendered as a Jinja2 template before it runs, using the shell's
variables. Templates run in Jinja2's sandbox. A name that isn't defined, or a
template that doesn't render, is an error, and the command is not run. That
way a missing id can't turn into a request like `DELETE /systems//`.
Variables set with `let` hold strings. `MPROV_RESULT` holds the parsed JSON
reply, so you can index into it.

## Loops

```
seq nodeNums 1 40 3
foreach nodeNum in nodeNums
print Creating c{{ nodeNum }}
create systems.models.System hostname=c{{ nodeNum }} ...
endforeach

foreach rack in "r1 r2 r3"
...
endforeach
```

`foreach` loops over a list variable, or over a list of words written in the
line itself (put the words in quotes). Each command in the loop is rendered
again on every pass. If a command fails, the loop stops. Loops can't be
nested.

## BMC power

```
bmc power <action> <node_spec>
bmc power on compute00[01-20,21,23]
bmc power status compute0050
```

The actions are `on`, `off`, `cycle`, `reset`, `status`, `pxe` and `pxeefi`
(PXE boot to provision, using legacy BIOS or UEFI). Any other action is
refused. A node spec is either one hostname or a Slurm-style range. Each node
gets one line of output: either `OK`, its status, or `ERROR` with the reason,
such as no BMC configured or the IPMI call failing. The command fails if any
node failed. Add `&` to the end of the line to run it in the background.

## Output modes and dry runs

```
output json     # each result as one line of compact JSON on stdout
output text     # the default
dryrun on       # print the changes instead of sending them
dryrun off      # the default
```

- In `json` mode, `create`, `retrieve`, `update` and `delete` print the mPCC's
  reply (`null` if the reply has no body). `models` prints a list, and
  `model` and `pvar` print an object. Errors still go to stderr. `mash --json`
  starts in this mode.
- With `dryrun on`, `create`, `update`, `delete` and every `bmc power` action
  except `status` print the request they would send, for example
  `DRY RUN: PATCH https://mpcc.example.com/systems/12/ {"id": "12", "hostname": "c001"}`,
  and set `MPROV_RESULT` to `None`. Reads (`retrieve`, `bmc power status`)
  are still sent, so you can preview a loop over their results.
  `mash --dry-run` starts in this mode.

## Scripts

```
mash script.mash            # run a file
some-command | mash         # run commands from stdin
mash -                      # read stdin even when it's a terminal
mash --dry-run script.mash  # preview the changes a script would make
```

A script file named on the command line takes priority over stdin. A file can
also start with `#!/usr/bin/env mash`. Lines that start with `#` are comments.
In a script, mash doesn't show the prompt or print `OK` after each command.

- Errors and warnings go to stderr. Results and `print` output go to stdout.
- A script exits with status 1 if any of its commands failed, including
  background commands, and 0 if they all succeeded. Warnings don't change the
  exit status. If a command fails, the script still runs the rest of its
  commands; check the exit status when the script finishes.
- Ctrl-C stops a script with exit status 130. In the interactive shell,
  Ctrl-C stops the running command and takes you back to the prompt.

For example scripts, see `tools/` in
[mprov_scripts](https://github.com/mprov-ng/mprov_scripts/tree/master/tools).

## Help

`help` lists the commands and the loaded plugins. `help <command>` (for
example `help connect` or `help bmc power`) explains one command.
