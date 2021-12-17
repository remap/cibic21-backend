# Backend code for CiBiC 2021

This repo contains code and supporting scripts for the serverless backend of CiBiC 2021 pilot project. For more information about the project, see [this](https://remap.ucla.edu/cibic-civic-bicycle-commuting/).

## Repo structure

The repo structure is intended to be updated as code progresses.
Repo folders:
* "lambda" -- contains subfolders for each AWS lambda, common code and supporting scripts.

## Dev environment setup

### Prerequisites

::macOS::
* get brew
```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

* get `python`
```
brew update
brew install python virtualenv
```

> ⚠️ Python versions
> TouchDesginer — python 3.7.2
> AWS CLI >= python 3.4
> -> brew installs `python3.9.9`

::win64::
-> [Python Release Python 3.10.1 | Python.org](https://www.python.org/downloads/release/python-3101/)

* get virtualenv
```
pip install virtualenv --user
```

> ⚠️
> might need to update PATH variable by adding path to your Python’s scripts, for example “C:\Users\username\AppData\Roaming\Python\Python39\Scripts”

### AWS CLI
-> [Installing or updating the latest version of the AWS CLI - AWS Command Line Interface](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

::macOS::
```bash
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
sudo installer -pkg AWSCLIV2.pkg -target /
```

::win64::
```
msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi
```

* check:

::macOS::
```bash
$ which aws
/usr/local/bin/aws
$ aws --version
aws-cli/2.4.6 Python/3.8.8 Darwin/20.6.0 exe/x86_64 prompt/off
```

::win64::
-> open “cmd.exe”
```
aws --version
```

* setup configuration files

::macOS::  `~/.aws/credentials`
::win64::  `%UserProfile%\.aws\credentials`
```
[default]
aws_access_key_id = AKUR5AHRWEEOP44QQJCD
aws_secret_access_key = RbWeaJopFy4d0rhTYnYoKIT3gJQkFG8xkvo3PTcK
```

::macOS::  `~/.aws/config`
::win64::  `%UserProfile%\.aws\config`
```
[default]
region = us-west-1
output=json
```

### Setup

After cloning the repo, create virtual environment like this (standing in the repo root):

::macOS::
```bash
virtualenv -p python3 env
source env/bin/activate
pip install boto3 jq
complete -C aws_completer aws
```

::win64::
```
python -m virtualenv .
.\scripts\activate
pip install boto3
complete -C aws_completer aws
```
